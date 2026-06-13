#!/bin/sh
# API-Key Consistency Checker
#
# The backend authenticates internal/admin endpoints (MCP tools, worker stats,
# diagnostics) with an API key delivered to the backend pods via the API_KEY
# env var, and to the frontend via a rendered ConfigMap. Both are written by
# the kube-operator on each reconcile. If the operator regenerates the key on
# rollout, the frontend's stored apiKey goes stale until it is rolled.
#
# This script:
#   - reads API_KEY from every backend pod's env
#   - reads the apiKey from the frontend ConfigMap (data field config.json)
#   - reads the apiKey from every running frontend pod's mounted config file
#   - compares all sources and reports
#   - with --fix, converges state by rolling restart of frontend (and backend
#     if pods disagree among themselves)
#
# Usage:
#   sh check-api-key.sh                    # Check only
#   sh check-api-key.sh --fix              # Check, then converge if issues
#   sh check-api-key.sh --env stage        # Override env
#   sh check-api-key.sh --show             # Print full keys (default: masked)
#   sh check-api-key.sh -h                 # Help

set -e

# ── Colors ───────────────────────────────────────────────────────
GREEN="\033[32m"
RED="\033[31m"
YELLOW="\033[33m"
CYAN="\033[36m"
BOLD="\033[1m"
DIM="\033[2m"
RESET="\033[0m"

# ── Defaults ─────────────────────────────────────────────────────
CAPABILITY="nexus-ai"
ENV="dev"
NAMESPACE=""
DO_FIX=0
SHOW_FULL=0

# ── Load .env.local ──────────────────────────────────────────────
_script_dir="$(cd "$(dirname "$0")" && pwd)"
_env_local="${_script_dir}/.env.local"
[ -f "$_env_local" ] && . "$_env_local"
unset _script_dir _env_local

# ── Argument parsing ─────────────────────────────────────────────
while [ $# -gt 0 ]; do
    case "$1" in
        --capability)    CAPABILITY="$2"; shift 2 ;;
        --env)           ENV="$2"; shift 2 ;;
        --namespace|-n)  NAMESPACE="$2"; shift 2 ;;
        --fix)           DO_FIX=1; shift ;;
        --show)          SHOW_FULL=1; shift ;;
        --help|-h)
            cat <<'EOF'
API-Key Consistency Checker

Usage: sh check-api-key.sh [OPTIONS]

Options:
  --capability NAME   Capability name (default: nexus-ai)
  --env ENV           Environment (default: from .env.local or 'dev')
  --namespace NS      Override namespace (default: {capability}-{env})
  --fix               Converge sources after diagnosis (see below)
  --show              Print full API keys instead of masked (first 6 chars)
  --help, -h          Show this help

Reads API_KEY from:
  • every backend pod env (the value the backend actually validates against)
  • the frontend ConfigMap's config.json
  • every frontend pod's rendered config file inside the container
and verifies they all agree. The backend env is treated as the source of truth.

With --fix:
  • if backend pods disagree, restart the backend Deployment so all pods come
    from the current spec
  • if the frontend ConfigMap or pods carry a stale apiKey, REWRITE the
    ConfigMap's data.config.json apiKey field to the backend's truth value
    (independent of operator behaviour), then restart the frontend Deployment
    so pods re-mount the patched ConfigMap
The script never generates a new key on its own; the truth value is whatever
the backend env API_KEY already holds.

Caveat: the ConfigMap patch is a "until next operator reconcile" recovery —
any full operator reconcile will overwrite the ConfigMap. Apply the
idempotent fix in kubernetes.py:248-261 (so the operator re-reads the
existing backend env) for a permanent solution.
EOF
            exit 0
            ;;
        *)
            echo "Unknown argument: $1 (try --help)" >&2
            exit 2
            ;;
    esac
done

NAMESPACE="${NAMESPACE:-${CAPABILITY}-${ENV}}"
BACKEND_DEP="${CAPABILITY}-${ENV}-backend"
FRONTEND_DEP="${CAPABILITY}-${ENV}-frontend"
FRONTEND_CM="${CAPABILITY}-${ENV}-frontend-config"

# ── Helpers ──────────────────────────────────────────────────────
hr()      { printf "${DIM}--------------------------------------------------------------------${RESET}\n"; }
header()  { echo ""; printf "${BOLD}${CYAN}== %s ==${RESET}\n" "$1"; }
red()     { printf "${RED}%s${RESET}\n" "$1"; }
yellow()  { printf "${YELLOW}%s${RESET}\n" "$1"; }
green()   { printf "${GREEN}%s${RESET}\n" "$1"; }

# Truncate a value for display unless --show was passed.
disp() {
    val="$1"
    if [ -z "$val" ]; then
        echo "<empty>"
    elif [ "$SHOW_FULL" = "1" ]; then
        echo "$val"
    else
        echo "${val%"${val#??????}"}…  (len=$(printf %s "$val" | wc -c | tr -d ' '))"
    fi
}

# Print a row in the consistency table.
row() {
    src="$1"; val="$2"; status="$3"
    printf "  %-44s %-32s %s\n" "$src" "$(disp "$val")" "$status"
}

# ── Pre-flight ───────────────────────────────────────────────────
header "API-Key Consistency Checker  Namespace: ${NAMESPACE}  $(date)"

if ! command -v kubectl >/dev/null 2>&1; then red "kubectl not on PATH"; exit 1; fi
if ! command -v python3 >/dev/null 2>&1; then red "python3 not on PATH"; exit 1; fi
if ! kubectl get ns "$NAMESPACE" >/dev/null 2>&1; then
    red "Namespace '$NAMESPACE' not found in context $(kubectl config current-context 2>/dev/null)"
    exit 1
fi

# ── Collect: backend pod env values ──────────────────────────────
BACKEND_PODS=$(kubectl -n "$NAMESPACE" get pod \
    -l "app=${BACKEND_DEP}" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null)
if [ -z "$BACKEND_PODS" ]; then
    BACKEND_PODS=$(kubectl -n "$NAMESPACE" get pod \
        -l "app.kubernetes.io/component=backend" \
        -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null)
fi
if [ -z "$BACKEND_PODS" ]; then
    red "No backend pods found in $NAMESPACE (label app=${BACKEND_DEP} or component=backend)"
    exit 1
fi

# Build a temp file with "podname=value" lines; awk-friendly.
TMP_BE=$(mktemp)
for p in $BACKEND_PODS; do
    v=$(kubectl -n "$NAMESPACE" exec "$p" -c backend -- sh -c 'echo "$API_KEY"' 2>/dev/null | tr -d '\r\n' || true)
    echo "${p}=${v}" >> "$TMP_BE"
done

# Source-of-truth = first non-empty backend value
TRUTH=$(awk -F= 'NF>=2 && $2!="" {print $2; exit}' "$TMP_BE")

# Are all backend pods consistent?
BE_VALUES=$(awk -F= '{print $2}' "$TMP_BE" | sort -u)
BE_UNIQ_COUNT=$(printf %s "$BE_VALUES" | grep -c .)
BE_AGREE=$([ "$BE_UNIQ_COUNT" -le 1 ] && echo 1 || echo 0)

# ── Collect: frontend ConfigMap ──────────────────────────────────
CM_KEY=""
CM_FOUND=1
if kubectl -n "$NAMESPACE" get cm "$FRONTEND_CM" >/dev/null 2>&1; then
    CM_DATA=$(kubectl -n "$NAMESPACE" get cm "$FRONTEND_CM" -o json 2>/dev/null)
    CM_KEY=$(printf '%s' "$CM_DATA" | python3 -c "
import sys, json, re
cm = json.load(sys.stdin)
data = cm.get('data') or {}
# Look at every data value, try JSON parse, walk for 'apiKey'
def find_key(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.lower() in ('apikey','api_key'):
                if isinstance(v, str) and v:
                    return v
            r = find_key(v)
            if r: return r
    elif isinstance(obj, list):
        for it in obj:
            r = find_key(it)
            if r: return r
    return None
for fname, raw in data.items():
    try:
        parsed = json.loads(raw)
    except Exception:
        # plain text - regex fallback
        m = re.search(r'\"?(?:apiKey|api_key|API_KEY)\"?\s*[:=]\s*\"?([A-Za-z0-9_\\-]{8,})\"?', raw or '')
        if m: print(m.group(1)); break
        continue
    found = find_key(parsed)
    if found:
        print(found); break
" 2>/dev/null)
else
    CM_FOUND=0
fi

# ── Collect: frontend pod mounted config files ───────────────────
FRONTEND_PODS=$(kubectl -n "$NAMESPACE" get pod \
    -l "app=${FRONTEND_DEP}" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null)
if [ -z "$FRONTEND_PODS" ]; then
    FRONTEND_PODS=$(kubectl -n "$NAMESPACE" get pod \
        -l "app.kubernetes.io/component=frontend" \
        -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null)
fi

TMP_FE=$(mktemp)
for p in $FRONTEND_PODS; do
    # Search the common mount points for an apiKey value; first hit wins.
    v=$(kubectl -n "$NAMESPACE" exec "$p" -c frontend -- sh -c '
        for f in /usr/share/nginx/html/config.json \
                 /usr/share/nginx/html/runtime-config.json \
                 /etc/nginx/conf.d/api_key.conf \
                 /config/config.json; do
            [ -f "$f" ] && grep -h -oE "\"?(apiKey|api_key|API_KEY)\"?[[:space:]]*[:=][[:space:]]*\"?[A-Za-z0-9_-]{8,}\"?" "$f" 2>/dev/null \
              | head -1 \
              | sed -E "s/.*[:=][[:space:]]*\"?([A-Za-z0-9_-]+)\"?.*/\1/" \
              && exit 0
        done
    ' 2>/dev/null | tr -d '\r\n')
    echo "${p}=${v}" >> "$TMP_FE"
done

# ── Report ───────────────────────────────────────────────────────
hr
printf "  %-44s %-32s %s\n" "SOURCE" "VALUE" "STATUS"
hr

# Backend rows
while IFS= read -r line; do
    p=$(echo "$line" | cut -d= -f1)
    v=$(echo "$line" | cut -d= -f2-)
    if [ -z "$v" ]; then
        row "backend pod  $p  (env API_KEY)" "$v" "$(red '✗ empty')"
    elif [ "$v" = "$TRUTH" ]; then
        row "backend pod  $p  (env API_KEY)" "$v" "$(green '✓ truth')"
    else
        row "backend pod  $p  (env API_KEY)" "$v" "$(red '✗ MISMATCH vs other backend pods')"
    fi
done < "$TMP_BE"

# ConfigMap row
if [ "$CM_FOUND" = "0" ]; then
    row "frontend ConfigMap  $FRONTEND_CM" "" "$(red '✗ ConfigMap not found')"
elif [ -z "$CM_KEY" ]; then
    row "frontend ConfigMap  $FRONTEND_CM" "" "$(yellow '? no apiKey field parsed')"
elif [ "$CM_KEY" = "$TRUTH" ]; then
    row "frontend ConfigMap  $FRONTEND_CM" "$CM_KEY" "$(green '✓ matches backend')"
else
    row "frontend ConfigMap  $FRONTEND_CM" "$CM_KEY" "$(red '✗ MISMATCH vs backend')"
fi

# Frontend pod rows
FE_PODS_OK=1
while IFS= read -r line; do
    [ -z "$line" ] && continue
    p=$(echo "$line" | cut -d= -f1)
    v=$(echo "$line" | cut -d= -f2-)
    if [ -z "$v" ]; then
        row "frontend pod $p (mounted config)" "" "$(yellow '? no apiKey file found')"
        FE_PODS_OK=0
    elif [ "$v" = "$TRUTH" ]; then
        row "frontend pod $p (mounted config)" "$v" "$(green '✓ matches backend')"
    else
        row "frontend pod $p (mounted config)" "$v" "$(red '✗ MISMATCH vs backend')"
        FE_PODS_OK=0
    fi
done < "$TMP_FE"

# Cleanup
trap 'rm -f "$TMP_BE" "$TMP_FE" 2>/dev/null' EXIT

# ── Verdict ──────────────────────────────────────────────────────
echo ""
hr
PROBLEMS=""
[ "$BE_AGREE" = "0" ]                            && PROBLEMS="$PROBLEMS backend-pods-diverge"
[ "$CM_FOUND" = "1" ] && [ -n "$CM_KEY" ] && [ "$CM_KEY" != "$TRUTH" ] && PROBLEMS="$PROBLEMS frontend-configmap-stale"
[ "$FE_PODS_OK" = "0" ]                          && PROBLEMS="$PROBLEMS frontend-pods-stale"
[ "$CM_FOUND" = "0" ]                            && PROBLEMS="$PROBLEMS frontend-configmap-missing"

if [ -z "$PROBLEMS" ]; then
    green "✓ All sources agree. API key auth should work."
    exit 0
fi

red   "✗ Inconsistency detected:$PROBLEMS"
yellow "  Source of truth used: backend pod env API_KEY = $(disp "$TRUTH")"

if [ "$DO_FIX" != "1" ]; then
    yellow "  Re-run with --fix to converge state (rolling restarts only; no key generation)."
    exit 1
fi

# ── Fix ──────────────────────────────────────────────────────────
header "Fix"

case "$PROBLEMS" in
    *backend-pods-diverge*)
        yellow "  Restarting backend Deployment so all pods come from current spec..."
        kubectl -n "$NAMESPACE" rollout restart deploy "$BACKEND_DEP"
        kubectl -n "$NAMESPACE" rollout status  deploy "$BACKEND_DEP" --timeout=300s
        ;;
esac

case "$PROBLEMS" in
    *frontend-configmap-stale*|*frontend-pods-stale*)
        yellow "  Patching ConfigMap $FRONTEND_CM (data.config.json -> apiKey=truth)..."
        # Read the current ConfigMap, rewrite every nested apiKey/api_key field
        # in every JSON data value to the truth value, then push back.
        NEW_CM=$(kubectl -n "$NAMESPACE" get cm "$FRONTEND_CM" -o json 2>/dev/null \
          | TRUTH_KEY="$TRUTH" python3 -c "
import os, sys, json
truth = os.environ['TRUTH_KEY']
cm = json.load(sys.stdin)
data = cm.get('data') or {}
patched = [False]
def rw(o):
    if isinstance(o, dict):
        for k, v in list(o.items()):
            if isinstance(k, str) and k.lower() in ('apikey', 'api_key'):
                o[k] = truth
                patched[0] = True
            else:
                rw(v)
    elif isinstance(o, list):
        for it in o: rw(it)
for fname, raw in list(data.items()):
    try:
        obj = json.loads(raw)
    except Exception:
        continue
    before = json.dumps(obj, sort_keys=True)
    rw(obj)
    after = json.dumps(obj, sort_keys=True)
    if before != after:
        data[fname] = json.dumps(obj, indent=2)
cm['data'] = data
# Strip server-managed fields so 'kubectl replace' is clean.
md = cm.get('metadata') or {}
for f in ('resourceVersion','uid','creationTimestamp','managedFields','generation'):
    md.pop(f, None)
cm['metadata'] = md
print(json.dumps(cm))
sys.exit(0 if patched[0] else 3)
")
        rc=$?
        if [ "$rc" -eq 0 ] && [ -n "$NEW_CM" ]; then
            echo "$NEW_CM" | kubectl -n "$NAMESPACE" apply -f - >/dev/null
            green "    ConfigMap patched"
        elif [ "$rc" -eq 3 ]; then
            red "    No apiKey field found inside ConfigMap data; cannot auto-patch."
            red "    Inspect manually: kubectl -n $NAMESPACE get cm $FRONTEND_CM -o yaml"
            exit 1
        else
            red "    Failed to patch ConfigMap (python returned $rc)"
            exit 1
        fi
        yellow "  Restarting frontend Deployment so pods re-mount the patched ConfigMap..."
        kubectl -n "$NAMESPACE" rollout restart deploy "$FRONTEND_DEP"
        kubectl -n "$NAMESPACE" rollout status  deploy "$FRONTEND_DEP" --timeout=300s
        ;;
esac

case "$PROBLEMS" in
    *frontend-configmap-missing*)
        red "  ConfigMap $FRONTEND_CM does not exist. This requires a full operator"
        red "  reconcile to recreate (e.g., kubectl rollout restart -n nexus-system"
        red "  deploy/nexus-operator, then re-run this script)."
        red "  WARNING: if the operator is still on the pre-idempotent image, the"
        red "  restart will rotate the backend API_KEY too. Roll out the operator"
        red "  with the kubernetes.py fix first to avoid that cycle."
        exit 1
        ;;
esac

echo ""
green "Fix applied. Re-run without --fix to verify."
green "  sh $(basename "$0") --env $ENV"
echo ""
yellow "Note: this script patches the ConfigMap directly to converge state. The"
yellow "next FULL operator reconcile (operator restart, CR spec change) will"
yellow "overwrite the ConfigMap with whatever api_key the operator computes."
yellow "Once the operator runs the idempotent fix (read-existing-key in"
yellow "kubernetes.py:248-261), that overwrite will preserve the current key."

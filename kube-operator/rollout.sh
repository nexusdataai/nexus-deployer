#!/bin/sh
# Rollout Update + Diagnostics Script
#
# Performs rolling restart of frontend / backend / BSS Magic,
# waits for full readiness, then runs infrastructure diagnostics.
#
# Runs from a workstation or CI host with kubectl access.
#
# Usage:
#   sh rollout.sh                           # Roll out all, then diagnose
#   sh rollout.sh backend                   # Roll out backend only
#   sh rollout.sh bssmagic backend          # Roll out BSS Magic then backend
#   sh rollout.sh --env stage all           # Target the stage environment
#   sh rollout.sh --skip-diagnostics all    # Rollout + wait only
#   sh rollout.sh --diagnostics-only        # Just run diagnostics
#   sh rollout.sh --dry-run all             # Show plan without executing

set -e

# ── Colors ─────────────────────────────────────────────────────────
GREEN="\033[32m"
RED="\033[31m"
YELLOW="\033[33m"
CYAN="\033[36m"
BOLD="\033[1m"
DIM="\033[2m"
RESET="\033[0m"

# ── Defaults ───────────────────────────────────────────────────────
CAPABILITY="nexus-ai"
ENV="dev"
NAMESPACE=""
TIMEOUT=300
SKIP_DIAGNOSTICS=0
DIAGNOSTICS_ONLY=0
JSON_MODE=0
DRY_RUN=0
FIX_KEYS=0
COMPONENTS=""

# ── Load .env.local (overrides defaults; CLI args override these) ─
_script_dir="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_DIR="$_script_dir"
. "${SCRIPT_DIR}/lib/init-kube-env.sh"
_env_local="${_script_dir}/.env.local"
[ -f "$_env_local" ] && . "$_env_local"
unset _script_dir _env_local

# ── Argument parsing ──────────────────────────────────────────────
while [ $# -gt 0 ]; do
    case "$1" in
        --capability)       CAPABILITY="$2"; shift 2 ;;
        --env)              ENV="$2"; shift 2 ;;
        --namespace|-n)     NAMESPACE="$2"; shift 2 ;;
        --timeout)          TIMEOUT="$2"; shift 2 ;;
        --skip-diagnostics) SKIP_DIAGNOSTICS=1; shift ;;
        --diagnostics-only) DIAGNOSTICS_ONLY=1; shift ;;
        --json|-j)          JSON_MODE=1; shift ;;
        --dry-run)          DRY_RUN=1; shift ;;
        --fix-keys)         FIX_KEYS=1; shift ;;
        --help|-h)
            cat <<'EOF'
Rollout Update + Diagnostics

Usage: sh rollout.sh [OPTIONS] [COMPONENT...]

Components:
  frontend    Roll out the frontend Deployment
  backend     Roll out the backend Deployment
  bssmagic    Roll out the BSS Magic StatefulSet
  all         Roll out all three (default)

Options:
  --capability NAME   Capability name (default: nexus-ai)
  --env ENV           Environment (default: dev)
  --namespace NS      Override namespace (default: {capability}-{env})
  --timeout SECS      Rollout timeout per component (default: 300)
  --skip-diagnostics  Only rollout + wait, skip diagnostics
  --diagnostics-only  Skip rollout, just run diagnostics
  --fix-keys          Sync frontend config.json apiKey from backend API_KEY
  --json              Output diagnostics as JSON
  --dry-run           Show what would be done without executing
  --help              Show this help

Phases:
  1.   Rollout restart + wait for readiness
  2.   Pod health check (HTTP/TCP)
  2.5  API key & connectivity verification
  3.   Infrastructure diagnostics

Ordering (when rolling out multiple):
  1. BSS Magic  (backend depends on FDW)
  2. Backend    (frontend proxies to it)
  3. Frontend
EOF
            exit 0
            ;;
        frontend|backend|bssmagic|all)
            COMPONENTS="${COMPONENTS} $1"; shift ;;
        *)
            echo "Unknown option: $1"; exit 1 ;;
    esac
done

[ -z "$NAMESPACE" ] && NAMESPACE="${CAPABILITY}-${ENV}"
[ -z "$COMPONENTS" ] && COMPONENTS="all"

# Expand "all" into ordered list
case "$COMPONENTS" in
    *all*) COMPONENTS="bssmagic backend frontend" ;;
esac

# ── Naming helpers ─────────────────────────────────────────────────
resource_name() {
    echo "${CAPABILITY}-${ENV}-${1}"
}

resource_kind() {
    case "$1" in
        bssmagic) echo "statefulset" ;;
        *)        echo "deployment" ;;
    esac
}

health_check_cmd() {
    case "$1" in
        backend)  echo "curl -sf --max-time 5 http://localhost:8000/health" ;;
        frontend) echo "wget -qO- --timeout=5 http://localhost:8080/ >/dev/null 2>&1" ;;
        bssmagic) echo "pg_isready -U postgres -d bssmagic -q 2>/dev/null || echo fail" ;;
    esac
}

# ── Utility ────────────────────────────────────────────────────────
log_info()  { printf "${CYAN}▶${RESET} %s\n" "$1"; }
log_ok()    { printf "${GREEN}✓${RESET} %s\n" "$1"; }
log_fail()  { printf "${RED}✗${RESET} %s\n" "$1"; }
log_warn()  { printf "${YELLOW}⚠${RESET} %s\n" "$1"; }
log_phase() { printf "\n${BOLD}── %s ──${RESET}\n" "$1"; }

run_cmd() {
    if [ "$DRY_RUN" = "1" ]; then
        printf "  ${DIM}[dry-run] %s${RESET}\n" "$*"
        return 0
    fi
    eval "$@"
}

get_pod() {
    component="$1"
    name=$(resource_name "$component")
    kubectl get pods -l "app=${name}" -n "$NAMESPACE" \
        --field-selector=status.phase=Running \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null
}

OVERALL_EXIT=0

# ── Header ─────────────────────────────────────────────────────────
printf "\n${BOLD}Rollout Update + Diagnostics${RESET}\n"
printf "Capability:  ${BOLD}${CAPABILITY}${RESET}\n"
printf "Environment: ${BOLD}${ENV}${RESET}\n"
printf "Namespace:   ${BOLD}${NAMESPACE}${RESET}\n"
printf "Components:  ${BOLD}${COMPONENTS}${RESET}\n"
printf "Timeout:     ${TIMEOUT}s per component\n"
[ "$DRY_RUN" = "1" ] && printf "${YELLOW}DRY RUN — no changes will be made${RESET}\n"

# ── Phase 1 + 2: Rollout + Wait (per component) ──────────────────
if [ "$DIAGNOSTICS_ONLY" = "0" ]; then
    for comp in $COMPONENTS; do
        name=$(resource_name "$comp")
        kind=$(resource_kind "$comp")

        log_phase "Phase 1: Rollout restart ${comp} (${kind}/${name})"

        if ! run_cmd "kubectl rollout restart ${kind}/${name} -n ${NAMESPACE}" && [ "$DRY_RUN" = "0" ]; then
            log_fail "Failed to restart ${kind}/${name}"
            OVERALL_EXIT=1
            continue
        fi
        [ "$DRY_RUN" = "0" ] && log_ok "Rollout restart triggered for ${kind}/${name}"

        log_phase "Phase 2: Wait for ${comp} readiness"

        log_info "Waiting for rollout to complete (timeout: ${TIMEOUT}s)..."
        if ! run_cmd "kubectl rollout status ${kind}/${name} -n ${NAMESPACE} --timeout=${TIMEOUT}s" && [ "$DRY_RUN" = "0" ]; then
            log_fail "Rollout did not complete within ${TIMEOUT}s"

            log_phase "Crash diagnostics for ${comp}"
            printf "  ${DIM}Pod status:${RESET}\n"
            kubectl get pods -l "app=${name}" -n "$NAMESPACE" -o wide 2>/dev/null | sed 's/^/    /'

            _fail_pod=$(kubectl get pods -l "app=${name}" -n "$NAMESPACE" \
                --sort-by=.metadata.creationTimestamp \
                -o jsonpath='{.items[?(@.status.phase!="Running")].metadata.name}' 2>/dev/null | awk '{print $NF}')
            if [ -z "$_fail_pod" ]; then
                _fail_pod=$(kubectl get pods -l "app=${name}" -n "$NAMESPACE" \
                    --sort-by=.metadata.creationTimestamp \
                    -o jsonpath='{.items[-1:].metadata.name}' 2>/dev/null)
            fi

            if [ -n "$_fail_pod" ]; then
                printf "\n  ${DIM}Crash logs (${_fail_pod}):${RESET}\n"
                kubectl logs "$_fail_pod" -n "$NAMESPACE" --tail=40 2>/dev/null | sed 's/^/    /' || true
                _prev_logs=$(kubectl logs "$_fail_pod" -n "$NAMESPACE" --previous --tail=40 2>/dev/null)
                if [ -n "$_prev_logs" ]; then
                    printf "\n  ${DIM}Previous crash logs (${_fail_pod}):${RESET}\n"
                    echo "$_prev_logs" | sed 's/^/    /'
                fi
                printf "\n  ${DIM}Pod events:${RESET}\n"
                kubectl describe pod "$_fail_pod" -n "$NAMESPACE" 2>/dev/null \
                    | sed -n '/Events:/,$ p' | head -25 | sed 's/^/    /'
            fi
            echo ""

            OVERALL_EXIT=1
            continue
        fi
        [ "$DRY_RUN" = "0" ] && log_ok "Rollout complete"

        log_info "Verifying pod readiness..."
        if ! run_cmd "kubectl wait --for=condition=ready pod -l app=${name} -n ${NAMESPACE} --timeout=120s" && [ "$DRY_RUN" = "0" ]; then
            log_warn "Pod readiness wait timed out"
        else
            [ "$DRY_RUN" = "0" ] && log_ok "Pod(s) ready"
        fi

        # HTTP/TCP health poll
        if [ "$DRY_RUN" = "0" ]; then
            pod=$(get_pod "$comp")
            if [ -n "$pod" ]; then
                hc=$(health_check_cmd "$comp")
                log_info "Health-checking ${comp} pod (${pod})..."
                attempts=0
                max_attempts=12
                while [ $attempts -lt $max_attempts ]; do
                    result=$(kubectl exec "$pod" -n "$NAMESPACE" -- sh -c "$hc" 2>/dev/null) && break
                    attempts=$((attempts + 1))
                    sleep 5
                done
                if [ $attempts -lt $max_attempts ]; then
                    log_ok "Health check passed for ${comp}"
                else
                    log_warn "Health check did not pass after ${max_attempts} attempts"
                fi
            else
                log_warn "No running pod found for ${comp}"
            fi
        fi

        printf "  ${DIM}Pod status:${RESET}\n"
        run_cmd "kubectl get pods -l app=${name} -n ${NAMESPACE} -o wide 2>/dev/null | sed 's/^/    /'"
        echo ""
    done
fi

# ── Phase 2.5: API Key & Connectivity Verification ────────────────
if [ "$SKIP_DIAGNOSTICS" = "0" ] && [ "$DRY_RUN" = "0" ]; then
    log_phase "Phase 2.5: API Key & Connectivity Verification"

    _be_pod=$(get_pod "backend")
    _fe_pod=$(get_pod "frontend")

    if [ -z "$_be_pod" ]; then
        log_fail "No running backend pod — skipping key verification"
        OVERALL_EXIT=2
    elif [ -z "$_fe_pod" ]; then
        log_fail "No running frontend pod — skipping key verification"
        OVERALL_EXIT=2
    else
        # ── Extract keys ──
        _be_key=$(kubectl exec "$_be_pod" -n "$NAMESPACE" -- printenv API_KEY 2>/dev/null) || _be_key=""
        _fe_config=$(kubectl exec "$_fe_pod" -n "$NAMESPACE" -- cat /usr/share/nginx/html/config.json 2>/dev/null) || _fe_config=""
        _fe_key=""
        _fe_base_url=""
        if [ -n "$_fe_config" ]; then
            _fe_key=$(echo "$_fe_config" | python3 -c "
import sys,json
try:
    c=json.load(sys.stdin)
    print(c.get('gateway',{}).get('apiKey','') or c.get('api',{}).get('apiKey',''))
except: pass" 2>/dev/null) || _fe_key=""
            _fe_base_url=$(echo "$_fe_config" | python3 -c "
import sys,json
try:
    c=json.load(sys.stdin)
    print(c.get('api',{}).get('baseUrl',''))
except: pass" 2>/dev/null) || _fe_base_url=""
        fi

        _mask() {
            _k="$1"; _len=${#_k}
            if [ "$_len" -eq 0 ]; then echo "(empty)"; return; fi
            if [ "$_len" -le 8 ]; then echo "****"; return; fi
            echo "$(echo "$_k" | cut -c1-4)…$(echo "$_k" | tail -c 5)"
        }

        printf "  Backend pod:             %s\n" "$_be_pod"
        printf "  Frontend pod:            %s\n" "$_fe_pod"
        echo ""

        printf "  Backend API_KEY env:     "
        if [ -n "$_be_key" ]; then
            printf "${GREEN}SET${RESET}  [%s]  (%d chars)\n" "$(_mask "$_be_key")" "${#_be_key}"
        else
            printf "${RED}NOT SET${RESET}\n"
        fi

        printf "  Frontend config apiKey:  "
        if [ -n "$_fe_key" ]; then
            printf "${GREEN}SET${RESET}  [%s]  (%d chars)\n" "$(_mask "$_fe_key")" "${#_fe_key}"
        else
            printf "${RED}EMPTY / MISSING${RESET}\n"
        fi

        printf "  Frontend config baseUrl: "
        if [ -z "$_fe_base_url" ]; then
            printf "${CYAN}(empty — using nginx proxy)${RESET}\n"
        else
            printf "%s\n" "$_fe_base_url"
        fi
        echo ""

        # ── Compare keys ──
        _keys_ok=1
        if [ -n "$_be_key" ] && [ -n "$_fe_key" ]; then
            if [ "$_be_key" = "$_fe_key" ]; then
                log_ok "Keys MATCH — frontend and backend share the same API key"
            else
                log_fail "Keys DO NOT MATCH — frontend sends a different key than backend expects"
                printf "    ${DIM}This is why MCP Tools and Worker Pool show 'Invalid API key'${RESET}\n"
                _keys_ok=0
                OVERALL_EXIT=2
            fi
        elif [ -z "$_be_key" ]; then
            log_fail "Backend API_KEY not set — all authenticated endpoints return 503"
            _keys_ok=0
            OVERALL_EXIT=2
        else
            log_fail "Frontend apiKey empty — browser sends blank x-api-key header"
            _keys_ok=0
            OVERALL_EXIT=2
        fi

        # ── Auto-fix: patch ConfigMap and restart frontend ──
        if [ "$_keys_ok" = "0" ] && [ -n "$_be_key" ] && [ "$FIX_KEYS" = "1" ]; then
            _cm_name="$(resource_name frontend)-config"
            log_info "Fixing: patching ConfigMap ${_cm_name} with backend API_KEY..."

            if kubectl get configmap "$_cm_name" -n "$NAMESPACE" -o json 2>/dev/null | \
                python3 -c "
import sys, json
cm = json.load(sys.stdin)
cfg = json.loads(cm['data']['config.json'])
cfg.setdefault('gateway', {})['apiKey'] = sys.argv[1]
cm['data']['config.json'] = json.dumps(cfg, indent=2)
json.dump(cm, sys.stdout)
" "$_be_key" 2>/dev/null | \
                kubectl apply -f - -n "$NAMESPACE" >/dev/null 2>&1; then

                log_ok "ConfigMap ${_cm_name} patched with backend API_KEY"

                _fe_deploy=$(resource_name "frontend")
                log_info "Restarting frontend to pick up new config..."
                if kubectl rollout restart "deployment/${_fe_deploy}" -n "$NAMESPACE" >/dev/null 2>&1; then
                    log_ok "Frontend restart triggered"
                    log_info "Waiting for frontend rollout..."
                    if kubectl rollout status "deployment/${_fe_deploy}" -n "$NAMESPACE" --timeout="${TIMEOUT}s" 2>/dev/null; then
                        log_ok "Frontend rollout complete"
                    else
                        log_warn "Frontend rollout timed out"
                    fi
                    sleep 3
                    _fe_pod=$(get_pod "frontend")
                    _fe_key="$_be_key"
                    log_ok "Keys now synchronized"
                else
                    log_fail "Failed to restart frontend deployment"
                fi
            else
                log_fail "Failed to patch ConfigMap ${_cm_name}"
                printf "    ${DIM}Manual fix: kubectl get configmap %s -n %s -o json | ... | kubectl apply -f -${RESET}\n" "$_cm_name" "$NAMESPACE"
            fi
        elif [ "$_keys_ok" = "0" ] && [ -n "$_be_key" ] && [ "$FIX_KEYS" = "0" ]; then
            printf "    ${DIM}Run with --fix-keys to auto-sync frontend apiKey from backend${RESET}\n"
        fi

        # ── Live endpoint tests using frontend's key against backend ──
        log_info "Testing backend /tools with frontend's API key..."
        _tools_http=$(kubectl exec "$_be_pod" -n "$NAMESPACE" -- \
            curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
            -H "x-api-key: ${_fe_key}" http://localhost:8000/tools 2>/dev/null) || _tools_http="000"
        case "$_tools_http" in
            200) log_ok "/tools → 200 OK" ;;
            401) log_fail "/tools → 401 Invalid API key" ; [ "$OVERALL_EXIT" -lt 2 ] && OVERALL_EXIT=2 ;;
            503) log_fail "/tools → 503 API_KEY not configured on server" ; [ "$OVERALL_EXIT" -lt 2 ] && OVERALL_EXIT=2 ;;
            *)   log_warn "/tools → HTTP ${_tools_http}" ;;
        esac

        log_info "Testing backend /stats with frontend's API key..."
        _stats_http=$(kubectl exec "$_be_pod" -n "$NAMESPACE" -- \
            curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
            -H "x-api-key: ${_fe_key}" http://localhost:8000/stats 2>/dev/null) || _stats_http="000"
        case "$_stats_http" in
            200) log_ok "/stats → 200 OK" ;;
            401) log_fail "/stats → 401 Invalid API key" ; [ "$OVERALL_EXIT" -lt 2 ] && OVERALL_EXIT=2 ;;
            503) log_fail "/stats → 503 API_KEY not configured on server" ; [ "$OVERALL_EXIT" -lt 2 ] && OVERALL_EXIT=2 ;;
            *)   log_warn "/stats → HTTP ${_stats_http}" ;;
        esac

        log_info "Testing backend /health (no auth required)..."
        _health_http=$(kubectl exec "$_be_pod" -n "$NAMESPACE" -- \
            curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
            http://localhost:8000/health 2>/dev/null) || _health_http="000"
        case "$_health_http" in
            200) log_ok "/health → 200 OK" ;;
            *)   log_fail "/health → HTTP ${_health_http}" ; [ "$OVERALL_EXIT" -lt 2 ] && OVERALL_EXIT=2 ;;
        esac

        # ── Frontend → backend proxy test ──
        # Test /stats through nginx — it's proxied by the regex location block
        # and requires auth, so it validates the full proxy + key chain
        log_info "Testing frontend nginx proxy → backend /stats..."
        _proxy_http=$(kubectl exec "$_fe_pod" -n "$NAMESPACE" -- \
            wget -qS -O /dev/null --timeout=5 \
            --header="x-api-key: ${_fe_key}" \
            http://localhost:8080/stats 2>&1 | grep -o 'HTTP/[0-9.]* [0-9]*' | tail -1 | grep -o '[0-9]*$') || _proxy_http=""
        case "$_proxy_http" in
            200) log_ok "Proxy → /stats returned 200 (full proxy + auth chain works)" ;;
            401) log_warn "Proxy → /stats returned 401 (proxy works, but key rejected by backend)" ;;
            "")
                log_fail "Frontend proxy to backend unreachable (nginx upstream down or misconfigured)"
                printf "    ${DIM}Check: kubectl exec %s -n %s -- cat /etc/nginx/nginx.conf${RESET}\n" "$_fe_pod" "$NAMESPACE"
                [ "$OVERALL_EXIT" -lt 2 ] && OVERALL_EXIT=2
                ;;
            *)  log_warn "Proxy → /stats returned HTTP ${_proxy_http}" ;;
        esac

        # Also verify the /api/ proxy path (most UI requests use this)
        log_info "Testing frontend nginx proxy → backend /api/v1/health..."
        _api_proxy_out=$(kubectl exec "$_fe_pod" -n "$NAMESPACE" -- \
            wget -qO- --timeout=5 http://localhost:8080/api/v1/health 2>/dev/null) || _api_proxy_out=""
        if [ -n "$_api_proxy_out" ]; then
            log_ok "Proxy → /api/v1/health reachable"
        else
            # /api/v1/health may not exist as a route; try the base health endpoint through /api/ prefix
            _api_proxy_out=$(kubectl exec "$_fe_pod" -n "$NAMESPACE" -- \
                wget -qO- --timeout=5 http://localhost:8080/health 2>/dev/null) || _api_proxy_out=""
            if [ -n "$_api_proxy_out" ]; then
                log_ok "Proxy → /health reachable (backend proxied via regex location)"
            else
                log_warn "/api/ proxy path returned empty — backend may not serve /api/v1/health"
                printf "    ${DIM}This is non-critical if /stats proxy test passed above${RESET}\n"
            fi
        fi

        echo ""
    fi
fi

# ── Phase 3: Infrastructure Diagnostics ───────────────────────────
if [ "$SKIP_DIAGNOSTICS" = "0" ]; then
    log_phase "Phase 3: Infrastructure Diagnostics"

    if [ "$DRY_RUN" = "1" ]; then
        run_cmd "kubectl exec <backend-pod> -n ${NAMESPACE} -- curl -sf http://localhost:8000/api/v1/diagnostics/infrastructure"
    else
        be_name=$(resource_name "backend")
        be_pod=$(get_pod "backend")

        if [ -z "$be_pod" ]; then
            log_fail "No running backend pod found — cannot run diagnostics"
            OVERALL_EXIT=1
        else
            log_info "Running diagnostics via ${be_pod}..."

            diag_output=$(kubectl exec "$be_pod" -n "$NAMESPACE" -- \
                curl -sf --max-time 120 http://localhost:8000/api/v1/diagnostics/infrastructure 2>/dev/null) || true

            if [ -z "$diag_output" ]; then
                log_fail "Diagnostics returned no output"
                OVERALL_EXIT=1
            else
                diag_status=$(echo "$diag_output" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")

                if [ "$JSON_MODE" = "1" ]; then
                    echo "$diag_output"
                else
                    # Pretty-print via the same Python one-liner pattern
                    echo "$diag_output" | python3 -c "
import sys, json
data = json.load(sys.stdin)
status = data.get('status','unknown')
colors = {'healthy':'\033[32m','degraded':'\033[33m','unhealthy':'\033[31m'}
print(f\"  Overall: {colors.get(status,'')}\033[1m{status.upper()}\033[0m\")
print(f\"  Timestamp: {data.get('timestamp','N/A')}\")
print()
checks = data.get('checks',{})
sym = {'pass':'\033[32m✓\033[0m','fail':'\033[31m✗\033[0m','warning':'\033[33m⚠\033[0m','skipped':'\033[90m⏭\033[0m'}
mx = max((len(k) for k in checks), default=0)
for key, c in checks.items():
    s = sym.get(c.get('status','?'),'?')
    lat = c.get('latency_ms',0)
    msg = c.get('message','')
    print(f'  {s} {key:<{mx}}  \033[2m{lat:>8.0f}ms\033[0m  {msg}')
    for sub_key in ('tables','buckets'):
        sub = c.get('details',{}).get(sub_key,{})
        for sk, sv in sub.items():
            ss = sym.get(sv.get('status','fail'),'?')
            r = 'R:OK' if sv.get('readable', sv.get('read_access')) else 'R:NO'
            w = 'W:OK' if sv.get('writable', sv.get('write_access')) else 'W:NO'
            name = sv.get('table_name', sv.get('bucket','?'))
            print(f'      {ss} {sk}: {name}  {r}  {w}')
pc = sum(1 for c in checks.values() if c.get('status')=='pass')
fc = sum(1 for c in checks.values() if c.get('status')=='fail')
print(f'\n  {pc} passed, {fc} failed, {len(checks)} total')
" 2>/dev/null || echo "$diag_output"
                fi

                case "$diag_status" in
                    healthy)
                        log_ok "Infrastructure diagnostics: HEALTHY"
                        ;;
                    degraded)
                        log_warn "Infrastructure diagnostics: DEGRADED"
                        [ "$OVERALL_EXIT" = "0" ] && OVERALL_EXIT=2
                        ;;
                    unhealthy)
                        log_fail "Infrastructure diagnostics: UNHEALTHY"
                        [ "$OVERALL_EXIT" = "0" ] && OVERALL_EXIT=2
                        ;;
                    *)
                        log_warn "Infrastructure diagnostics: ${diag_status}"
                        [ "$OVERALL_EXIT" = "0" ] && OVERALL_EXIT=2
                        ;;
                esac
            fi
        fi
    fi
fi

# ── Summary ────────────────────────────────────────────────────────
log_phase "Summary"
run_cmd "kubectl get pods -n ${NAMESPACE} -o wide 2>/dev/null | sed 's/^/  /'"

echo ""
if [ "$OVERALL_EXIT" = "0" ]; then
    log_ok "All phases completed successfully"
elif [ "$OVERALL_EXIT" = "1" ]; then
    log_fail "Rollout or readiness failure (exit code 1)"
else
    log_warn "Diagnostics degraded/unhealthy (exit code ${OVERALL_EXIT})"
fi
echo ""

exit $OVERALL_EXIT

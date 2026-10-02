#!/bin/sh
# App Rollout Update + Diagnostics Script
#
# Performs versioned rolling upgrade of frontend / backend / BSS Magic,
# waits for full readiness, then runs infrastructure diagnostics.
# Supports rollback on failure (automatic or manual).
#
# Runs from a workstation or CI host with kubectl + aws CLI access.
#
# Usage:
#   sh app-rollout.sh                                    # Roll out all (restart), then diagnose
#   sh app-rollout.sh --version 1.3.0-a7f2bc1 all       # Upgrade all to specific version
#   sh app-rollout.sh --backend-version 1.3.0 backend   # Upgrade backend to specific version
#   sh app-rollout.sh --rollback backend                 # Rollback backend to previous version
#   sh app-rollout.sh --rollback-to 1.2.0-ff3a901 all   # Rollback all to explicit version
#   sh app-rollout.sh --list-versions backend            # List available ECR tags
#   sh app-rollout.sh --env stage all                    # Target the stage environment
#   sh app-rollout.sh --skip-diagnostics all             # Rollout + wait only
#   sh app-rollout.sh --diagnostics-only                 # Just run diagnostics
#   sh app-rollout.sh --dry-run all                      # Show plan without executing

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
SKIP_ECR_VERIFY=0
DIAGNOSTICS_ONLY=0
JSON_MODE=0
DRY_RUN=0
FIX_KEYS=0
COMPONENTS=""
REGION="us-east-1"
AWS_PROFILE="${AWS_PROFILE:-external-access}"

# Version control
TARGET_VERSION=""
BACKEND_VERSION=""
FRONTEND_VERSION=""
BSSMAGIC_VERSION=""
SRE_BACKEND_VERSION=""
SRE_UI_VERSION=""
SRE_POSTGRES_VERSION=""
AI_ENGINE_API_VERSION=""
AI_ENGINE_UI_VERSION=""
ONTOLOGY_API_VERSION=""
ONTOLOGY_UI_VERSION=""
SIMULATOR_VERSION=""
ROLLBACK_MODE=0
ROLLBACK_TO_VERSION=""
LIST_VERSIONS=0
AUTO_ROLLBACK=1
# When no explicit --version is passed, default the target to the most recently
# pushed versioned tag in ECR (excluding the floating ":latest" pointer).
# Set to 1 (via --restart-only) to preserve the legacy "kubectl rollout restart
# without changing the image" behavior.
RESTART_ONLY=0

# ── Load .env.local (overrides defaults; CLI args override these) ─
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "${SCRIPT_DIR}/lib/init-kube-env.sh"
_env_local="${SCRIPT_DIR}/.env.local"
[ -f "$_env_local" ] && . "$_env_local"
unset _env_local

# ── Argument parsing ──────────────────────────────────────────────
while [ $# -gt 0 ]; do
    case "$1" in
        --capability)       CAPABILITY="$2"; shift 2 ;;
        --env)              ENV="$2"; shift 2 ;;
        --namespace|-n)     NAMESPACE="$2"; shift 2 ;;
        --timeout)          TIMEOUT="$2"; shift 2 ;;
        --skip-diagnostics) SKIP_DIAGNOSTICS=1; shift ;;
        --skip-ecr-verify)  SKIP_ECR_VERIFY=1; shift ;;
        --diagnostics-only) DIAGNOSTICS_ONLY=1; shift ;;
        --json|-j)          JSON_MODE=1; shift ;;
        --dry-run)          DRY_RUN=1; shift ;;
        --fix-keys)         FIX_KEYS=1; shift ;;
        --version)          TARGET_VERSION="$2"; shift 2 ;;
        --backend-version)  BACKEND_VERSION="$2"; shift 2 ;;
        --frontend-version) FRONTEND_VERSION="$2"; shift 2 ;;
        --bssmagic-version) BSSMAGIC_VERSION="$2"; shift 2 ;;
        --sre-backend-version) SRE_BACKEND_VERSION="$2"; shift 2 ;;
        --sre-ui-version)      SRE_UI_VERSION="$2"; shift 2 ;;
        --ai-engine-api-version) AI_ENGINE_API_VERSION="$2"; shift 2 ;;
        --ai-engine-ui-version)  AI_ENGINE_UI_VERSION="$2"; shift 2 ;;
        --ontology-api-version) ONTOLOGY_API_VERSION="$2"; shift 2 ;;
        --ontology-ui-version)  ONTOLOGY_UI_VERSION="$2"; shift 2 ;;
        --simulator-version)    SIMULATOR_VERSION="$2"; shift 2 ;;
        --simulator-api-version) SIMULATOR_API_VERSION="$2"; shift 2 ;;
        --simulator-ui-version)  SIMULATOR_UI_VERSION="$2"; shift 2 ;;
        --rollback)         ROLLBACK_MODE=1; shift ;;
        --rollback-to)      ROLLBACK_MODE=1; ROLLBACK_TO_VERSION="$2"; shift 2 ;;
        --list-versions)    LIST_VERSIONS=1; shift ;;
        --no-auto-rollback) AUTO_ROLLBACK=0; shift ;;
        --restart-only)     RESTART_ONLY=1; shift ;;
        --help|-h)
            cat <<'EOF'
Rollout Update + Diagnostics

Usage: sh app-rollout.sh [OPTIONS] [COMPONENT...]

Components:
  frontend    Roll out the frontend Deployment
  backend     Roll out the backend Deployment
  bssmagic    Roll out the BSS Magic StatefulSet
  all         Roll out all three (default)

Version Options:
  --version TAG           Target version tag for all components (e.g., 1.3.0-a7f2bc1)
  --backend-version TAG   Target version for backend only
  --frontend-version TAG  Target version for frontend only
  --bssmagic-version TAG  Target version for BSS Magic only
  --rollback              Rollback to previous version (from annotation)
  --rollback-to TAG       Rollback to explicit version tag
  --list-versions         List available image tags in ECR
  --no-auto-rollback      Disable automatic rollback on failure
  --restart-only          Skip ECR auto-detect and just restart at the deployed
                          image (legacy behavior; useful for config-only changes)

When no --version / --backend-version / --frontend-version / --bssmagic-version
is provided, the target is auto-detected from ECR: for each component the most
recently pushed tag (preferring N.N.N-* for backend/frontend, YYYYMMDD-* for
BSS Magic, ignoring the floating "latest" pointer) becomes the target version.

Options:
  --capability NAME   Capability name (default: nexus-ai)
  --env ENV           Environment (default: dev)
  --namespace NS      Override namespace (default: {capability}-{env})
  --timeout SECS      Rollout timeout per component (default: 300)
  --skip-diagnostics  Rollout + kubectl rollout status only (skip extra pod wait/health exec)
  --skip-ecr-verify   Skip ECR image existence check (use when image was just pushed)
  --diagnostics-only  Skip rollout, just run diagnostics
  --fix-keys          Sync frontend config.json apiKey from backend API_KEY
  --json              Output diagnostics as JSON
  --dry-run           Show what would be done without executing
  --help              Show this help

Phases:
  0.   Pre-flight (verify image in ECR, record current version)
  1.   Image update + rollout restart + wait for readiness
  2.   Pod health check (HTTP/TCP)
  2.5  API key & connectivity verification
  3.   Infrastructure diagnostics
  4.   Capability inventory (inspect-capability.sh)

On failure: auto-rollback via kubectl rollout undo (disable with --no-auto-rollback)

Ordering (when rolling out multiple):
  1. BSS Magic  (backend depends on FDW)
  2. Backend    (frontend proxies to it)
  3. Frontend
EOF
            exit 0
            ;;
        frontend|backend|bssmagic|all|sre-backend|sre-ui|sre-postgres|sre-all|ai-engine-api|ai-engine-worker|ai-engine-ui|ai-engine-all|ontology-api|ontology-ui|ontology-all|simulator|simulator-api|simulator-ui|simulator-all)
            COMPONENTS="${COMPONENTS} $1"; shift ;;
        *)
            echo "Unknown option: $1"; exit 1 ;;
    esac
done

[ -z "$NAMESPACE" ] && NAMESPACE="${CAPABILITY}-${ENV}"
[ -z "$COMPONENTS" ] && COMPONENTS="all"

# Packaged image tags from package-images.sh / deploy-app-changes.sh.
PACKAGED_BACKEND_TAG=""
PACKAGED_FRONTEND_TAG=""
PACKAGED_BSSMAGIC_TAG=""
PACKAGED_AI_ENGINE_API_TAG=""
PACKAGED_AI_ENGINE_UI_TAG=""
PACKAGED_SRE_BACKEND_TAG=""
PACKAGED_SRE_UI_TAG=""
PACKAGED_SRE_POSTGRES_TAG=""
PACKAGED_ONTOLOGY_API_TAG=""
PACKAGED_ONTOLOGY_UI_TAG=""
PACKAGED_SIMULATOR_TAG=""
_NEXUS_VERSIONS="${SCRIPT_DIR}/images/nexus/versions.env"
if [ -f "$_NEXUS_VERSIONS" ]; then
    PACKAGED_BACKEND_TAG=$(. "$_NEXUS_VERSIONS" >/dev/null 2>&1; echo "${BACKEND_TAG:-}")
    PACKAGED_FRONTEND_TAG=$(. "$_NEXUS_VERSIONS" >/dev/null 2>&1; echo "${FRONTEND_TAG:-}")
fi
_BSS_VERSIONS="${SCRIPT_DIR}/images/bssmagic/versions.env"
if [ -f "$_BSS_VERSIONS" ]; then
    PACKAGED_BSSMAGIC_TAG=$(. "$_BSS_VERSIONS" >/dev/null 2>&1; echo "${BSSMAGIC_TAG:-}")
fi
_AI_ENGINE_VERSIONS="${SCRIPT_DIR}/images/nexus-ai-engine/versions.env"
if [ -f "$_AI_ENGINE_VERSIONS" ]; then
    PACKAGED_AI_ENGINE_API_TAG=$(. "$_AI_ENGINE_VERSIONS" >/dev/null 2>&1; echo "${AI_ENGINE_API_TAG:-}")
    PACKAGED_AI_ENGINE_UI_TAG=$(. "$_AI_ENGINE_VERSIONS" >/dev/null 2>&1; echo "${AI_ENGINE_UI_TAG:-}")
fi
_SRE_VERSIONS="${SCRIPT_DIR}/images/nexus-sre/versions.env"
if [ -f "$_SRE_VERSIONS" ]; then
    PACKAGED_SRE_BACKEND_TAG=$(. "$_SRE_VERSIONS" >/dev/null 2>&1; echo "${SRE_BACKEND_TAG:-}")
    PACKAGED_SRE_UI_TAG=$(. "$_SRE_VERSIONS" >/dev/null 2>&1; echo "${SRE_UI_TAG:-}")
    PACKAGED_SRE_POSTGRES_TAG=$(. "$_SRE_VERSIONS" >/dev/null 2>&1; echo "${SRE_POSTGRES_TAG:-}")
fi
_ONTOLOGY_VERSIONS="${SCRIPT_DIR}/images/nexus-ontology/versions.env"
if [ -f "$_ONTOLOGY_VERSIONS" ]; then
    PACKAGED_ONTOLOGY_API_TAG=$(. "$_ONTOLOGY_VERSIONS" >/dev/null 2>&1; echo "${ONTOLOGY_API_TAG:-}")
    PACKAGED_ONTOLOGY_UI_TAG=$(. "$_ONTOLOGY_VERSIONS" >/dev/null 2>&1; echo "${ONTOLOGY_UI_TAG:-}")
fi
_SIMULATOR_VERSIONS="${SCRIPT_DIR}/images/nexus-simulator/versions.env"
if [ -f "$_SIMULATOR_VERSIONS" ]; then
    PACKAGED_SIMULATOR_TAG=$(. "$_SIMULATOR_VERSIONS" >/dev/null 2>&1; echo "${SIMULATOR_API_TAG:-${SIMULATOR_TAG:-}}")
    PACKAGED_SIMULATOR_API_TAG=$(. "$_SIMULATOR_VERSIONS" >/dev/null 2>&1; echo "${SIMULATOR_API_TAG:-${SIMULATOR_TAG:-}}")
    PACKAGED_SIMULATOR_UI_TAG=$(. "$_SIMULATOR_VERSIONS" >/dev/null 2>&1; echo "${SIMULATOR_UI_TAG:-}")
fi
unset _NEXUS_VERSIONS _BSS_VERSIONS _AI_ENGINE_VERSIONS _SRE_VERSIONS _ONTOLOGY_VERSIONS _SIMULATOR_VERSIONS

# Expand "all" / "sre-all" / "ai-engine-all" into ordered lists.
#
# `sre-all`, `ai-engine-all`, and the plain `all` are mutually exclusive per
# invocation. Use the component set that matches the capability you are rolling:
#   nexus-ai     -> all (bssmagic backend frontend)
#   nexus-sre    -> sre-all
#   ai-engine    -> ai-engine-all
case "$COMPONENTS" in
    *sre-all*)        COMPONENTS="sre-postgres sre-backend sre-ui" ;;
    *ai-engine-all*)  COMPONENTS="ai-engine-api ai-engine-worker ai-engine-ui" ;;
    *ontology-all*)  COMPONENTS="ontology-api ontology-ui" ;;
    *simulator-all*) COMPONENTS="simulator-api simulator-ui" ;;
    *all*)            COMPONENTS="bssmagic backend frontend" ;;
esac

# ── Naming helpers ─────────────────────────────────────────────────
#
# For legacy nexus-ai components the resource name is
# `${CAPABILITY}-${ENV}-${component}`. For nexus-sre and nexus-ai-engine the
# deployments use fixed names in capability-specific namespaces.
resource_name() {
    case "$1" in
        sre-backend)     echo "nexus-sre-backend" ;;
        sre-ui)          echo "nexus-sre-ui" ;;
        sre-postgres)    echo "nexus-sre-postgres" ;;
        ai-engine-api)   echo "nexus-ai-engine" ;;
        ai-engine-worker) echo "ai-engine-${ENV}-job-worker" ;;
        ai-engine-ui)    echo "nexus-ai-engine-ui" ;;
        ontology-api)    echo "${CAPABILITY}-${ENV}-backend" ;;
        ontology-ui)     echo "${CAPABILITY}-${ENV}-frontend" ;;
        simulator|simulator-api) echo "${CAPABILITY}-${ENV}-backend" ;;
        simulator-ui)    echo "${CAPABILITY}-${ENV}-frontend" ;;
        *)               echo "${CAPABILITY}-${ENV}-${1}" ;;
    esac
}

resource_kind() {
    case "$1" in
        bssmagic|sre-postgres) echo "statefulset" ;;
        *)                     echo "deployment" ;;
    esac
}

ecr_repo() {
    case "$1" in
        backend)      echo "ai-job-engine" ;;
        frontend)     echo "nexus-ui" ;;
        bssmagic)     echo "bssmagic-nexus-k8s" ;;
        sre-backend)     echo "nexus-sre-backend" ;;
        sre-ui)          echo "nexus-sre-ui" ;;
        sre-postgres)    echo "nexus-sre-postgres" ;;
        ai-engine-api)   echo "nexus-ai-engine-api" ;;
        ai-engine-worker) echo "nexus-ai-engine-api" ;;
        ai-engine-ui)    echo "nexus-ai-engine-ui" ;;
        ontology-api)    echo "nexus-ontology-api" ;;
        ontology-ui)     echo "nexus-ontology-ui" ;;
        simulator|simulator-api) echo "nexus-simulator-api" ;;
        simulator-ui)    echo "nexus-simulator-ui" ;;
    esac
}

container_name() {
    case "$1" in
        backend)      echo "backend" ;;
        frontend)     echo "frontend" ;;
        bssmagic)     echo "bssmagic-runtime" ;;
        sre-backend)     echo "backend" ;;
        sre-ui)          echo "ui" ;;
        sre-postgres)    echo "postgres" ;;
        ai-engine-api)   echo "server" ;;
        ai-engine-worker) echo "job-worker" ;;
        ai-engine-ui)    echo "ui" ;;
        ontology-api)    echo "backend" ;;
        ontology-ui)     echo "frontend" ;;
        simulator|simulator-api) echo "backend" ;;
        simulator-ui)    echo "frontend" ;;
    esac
}

health_check_cmd() {
    case "$1" in
        backend)      echo "curl -sf --max-time 5 http://localhost:8000/health" ;;
        frontend)     echo "wget -qO- --timeout=5 http://localhost:8080/ >/dev/null 2>&1" ;;
        bssmagic)     echo "pg_isready -U postgres -d bssmagic -q 2>/dev/null || echo fail" ;;
        sre-backend)  echo "curl -sf --max-time 5 http://127.0.0.1:8000/healthz" ;;
        sre-ui)       echo "wget -qO- --timeout=5 http://127.0.0.1:8080/healthz >/dev/null 2>&1" ;;
        sre-postgres)    echo "pg_isready -U nexus -d nexus_sre -q 2>/dev/null || echo fail" ;;
        ai-engine-api)   echo "curl -sf --max-time 5 http://127.0.0.1:8000/health" ;;
        ai-engine-worker) echo "curl -sf --max-time 5 http://127.0.0.1:8081/live" ;;
        ai-engine-ui)    echo "wget -qO- --timeout=5 http://127.0.0.1:8080/ >/dev/null 2>&1" ;;
        ontology-api)    echo "curl -sf --max-time 5 http://127.0.0.1:8000/health" ;;
        ontology-ui)     echo "wget -qO- --timeout=5 http://127.0.0.1:8080/ >/dev/null 2>&1" ;;
        simulator|simulator-api) echo "curl -sf --max-time 5 http://127.0.0.1:8000/health" ;;
        simulator-ui)    echo "wget -qO- --timeout=5 http://127.0.0.1:8080/ >/dev/null 2>&1" ;;
    esac
}

target_version_for() {
    case "$1" in
        backend)     _tv="${BACKEND_VERSION:-${TARGET_VERSION}}" ;;
        frontend)    _tv="${FRONTEND_VERSION:-${TARGET_VERSION}}" ;;
        bssmagic)    _tv="${BSSMAGIC_VERSION:-${TARGET_VERSION}}" ;;
        sre-backend)     _tv="${SRE_BACKEND_VERSION:-${TARGET_VERSION}}" ;;
        sre-ui)          _tv="${SRE_UI_VERSION:-${TARGET_VERSION}}" ;;
        sre-postgres)    _tv="${SRE_POSTGRES_VERSION:-${TARGET_VERSION}}" ;;
        ai-engine-api)   _tv="${AI_ENGINE_API_VERSION:-${TARGET_VERSION}}" ;;
        ai-engine-worker) _tv="${AI_ENGINE_WORKER_VERSION:-${AI_ENGINE_API_VERSION:-${TARGET_VERSION}}}" ;;
        ai-engine-ui)    _tv="${AI_ENGINE_UI_VERSION:-${TARGET_VERSION}}" ;;
        ontology-api)    _tv="${ONTOLOGY_API_VERSION:-${TARGET_VERSION}}" ;;
        ontology-ui)     _tv="${ONTOLOGY_UI_VERSION:-${TARGET_VERSION}}" ;;
        simulator|simulator-api) _tv="${SIMULATOR_API_VERSION:-${SIMULATOR_VERSION:-${TARGET_VERSION}}}" ;;
        simulator-ui)    _tv="${SIMULATOR_UI_VERSION:-${TARGET_VERSION}}" ;;
        *)               _tv="" ;;
    esac
    if [ -n "$_tv" ]; then
        echo "$_tv"
        return
    fi
    # No explicit version: rollback/restart-only opt out; else prefer packaged
    # tags from images/*/versions.env, then ECR auto-detect.
    [ "$ROLLBACK_MODE" = "1" ] && return
    [ "$RESTART_ONLY" = "1" ] && return
    case "$1" in
        backend)  [ -n "$PACKAGED_BACKEND_TAG" ]  && { echo "$PACKAGED_BACKEND_TAG";  return; } ;;
        frontend) [ -n "$PACKAGED_FRONTEND_TAG" ] && { echo "$PACKAGED_FRONTEND_TAG"; return; } ;;
        bssmagic) [ -n "$PACKAGED_BSSMAGIC_TAG" ] && { echo "$PACKAGED_BSSMAGIC_TAG"; return; } ;;
        ai-engine-api)  [ -n "$PACKAGED_AI_ENGINE_API_TAG" ]  && { echo "$PACKAGED_AI_ENGINE_API_TAG";  return; } ;;
        ai-engine-worker)
            [ -n "$PACKAGED_AI_ENGINE_WORKER_TAG" ] && { echo "$PACKAGED_AI_ENGINE_WORKER_TAG"; return; }
            [ -n "$PACKAGED_AI_ENGINE_API_TAG" ] && { echo "$PACKAGED_AI_ENGINE_API_TAG"; return; }
            ;;
        ai-engine-ui)   [ -n "$PACKAGED_AI_ENGINE_UI_TAG" ]   && { echo "$PACKAGED_AI_ENGINE_UI_TAG";   return; } ;;
        sre-backend)    [ -n "$PACKAGED_SRE_BACKEND_TAG" ]    && { echo "$PACKAGED_SRE_BACKEND_TAG";    return; } ;;
        sre-ui)         [ -n "$PACKAGED_SRE_UI_TAG" ]         && { echo "$PACKAGED_SRE_UI_TAG";         return; } ;;
        sre-postgres)   [ -n "$PACKAGED_SRE_POSTGRES_TAG" ]   && { echo "$PACKAGED_SRE_POSTGRES_TAG";   return; } ;;
        ontology-api)   [ -n "$PACKAGED_ONTOLOGY_API_TAG" ]   && { echo "$PACKAGED_ONTOLOGY_API_TAG";   return; } ;;
        ontology-ui)    [ -n "$PACKAGED_ONTOLOGY_UI_TAG" ]    && { echo "$PACKAGED_ONTOLOGY_UI_TAG";    return; } ;;
        simulator|simulator-api)
            [ -n "$PACKAGED_SIMULATOR_API_TAG" ] && { echo "$PACKAGED_SIMULATOR_API_TAG"; return; }
            [ -n "$PACKAGED_SIMULATOR_TAG" ] && { echo "$PACKAGED_SIMULATOR_TAG"; return; }
            ;;
        simulator-ui)   [ -n "$PACKAGED_SIMULATOR_UI_TAG" ] && { echo "$PACKAGED_SIMULATOR_UI_TAG"; return; } ;;
    esac
    latest_versioned_ecr_tag "$1"
}

# Resolve the version that will actually be deployed for a component,
# matching the same logic used inside the rollout loop (Phase 0).
planned_version_for() {
    _pv_comp="$1"
    if [ "$ROLLBACK_MODE" = "1" ]; then
        if [ -n "$ROLLBACK_TO_VERSION" ]; then
            echo "$ROLLBACK_TO_VERSION"
        else
            get_previous_version_annotation "$_pv_comp"
        fi
    else
        _pv_explicit=$(target_version_for "$_pv_comp")
        if [ -n "$_pv_explicit" ]; then
            echo "$_pv_explicit"
        else
            _pv_current=$(get_current_version_annotation "$_pv_comp")
            [ -z "$_pv_current" ] && _pv_current=$(get_current_image "$_pv_comp" | grep -o ':[^:]*$' | tr -d ':')
            resolve_versioned_tag "$_pv_comp" "$_pv_current"
        fi
    fi
}

# Compare two semver-like tags ("vN.N.N..." or "N.N.N-suffix").
# Echoes one of: "<" (a<b, upgrade), ">" (a>b, downgrade),
# "=" (equal), "?" (incomparable / non-semver).
compare_versions() {
    python3 -c "
import sys, re
a, b = sys.argv[1], sys.argv[2]
def parse(v):
    v = (v or '').lstrip('v')
    m = re.match(r'^(\d+)\.(\d+)\.(\d+)', v)
    return tuple(int(x) for x in m.groups()) if m else None
pa, pb = parse(a), parse(b)
if pa is None or pb is None:
    print('?')
elif pa < pb:
    print('<')
elif pa > pb:
    print('>')
else:
    print('=')" "$1" "$2" 2>/dev/null || echo "?"
}

# Friendly label for a component (used in narrative upgrade plan + Phase 4).
component_label() {
    case "$1" in
        frontend) echo "frontend (UI)" ;;
        backend)  echo "backend (API)" ;;
        bssmagic) echo "BSS Magic" ;;
        ai-engine-api) echo "AI Engine API" ;;
        ai-engine-worker) echo "AI Engine Job Worker" ;;
        ai-engine-ui)  echo "AI Engine UI" ;;
        ontology-api) echo "Ontology API" ;;
        ontology-ui)  echo "Ontology UI" ;;
        simulator)    echo "Simulator" ;;
        *)             echo "$1" ;;
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

# For Deployments: pod-template-hash of the newest ReplicaSet, used to scope
# pod selectors to the new generation during/after a rollout (so old/terminating
# pods are excluded). For StatefulSets: empty (pods are deterministically named
# NAME-0, NAME-1, ... and don't carry a pod-template-hash).
latest_rs_hash() {
    component="$1"
    name=$(resource_name "$component")
    if [ "$(resource_kind "$component")" = "deployment" ]; then
        kubectl get rs -l "app=${name}" -n "$NAMESPACE" \
            --sort-by=.metadata.creationTimestamp \
            -o jsonpath='{.items[-1:].metadata.labels.pod-template-hash}' 2>/dev/null
    fi
}

# Get the imageID (registry/repo@sha256:...) of the running container for a
# component. Used to resolve a meaningful version when the spec image is :latest.
get_running_image_digest() {
    _comp="$1"
    _name=$(resource_name "$_comp")
    _container=$(container_name "$_comp")
    _hash=$(latest_rs_hash "$_comp")
    _selector="app=${_name}"
    [ -n "$_hash" ] && _selector="${_selector},pod-template-hash=${_hash}"
    _image_id=$(kubectl get pods -l "$_selector" -n "$NAMESPACE" \
        --field-selector=status.phase=Running \
        --sort-by=.metadata.creationTimestamp \
        -o jsonpath="{.items[-1:].status.containerStatuses[?(@.name==\"${_container}\")].imageID}" 2>/dev/null)
    echo "$_image_id" | grep -oE 'sha256:[a-f0-9]+' | head -1
}

# Resolve a meaningful version label for a tag. If the tag is empty or "latest",
# look up sibling tags in ECR via the running container's manifest digest and
# return the most informative one (prefer N.N.N-* pattern, else any non-"latest").
# If nothing better is found, returns the input tag unchanged.
resolve_versioned_tag() {
    _comp="$1"
    _tag="$2"
    if [ -n "$_tag" ] && [ "$_tag" != "latest" ]; then
        echo "$_tag"
        return
    fi
    _digest=$(get_running_image_digest "$_comp")
    if [ -z "$_digest" ]; then
        echo "$_tag"
        return
    fi
    _repo=$(ecr_repo "$_comp")
    # Capture stderr too so a transient AWS failure (SSO expired, throttling,
    # repo missing) doesn't silently kill the script under `set -e`.
    _all_tags=$(aws ecr describe-images --repository-name "${_repo}" \
        --image-ids "imageDigest=${_digest}" \
        --region "${REGION}" --profile "${AWS_PROFILE}" \
        --query 'imageDetails[0].imageTags' --output json 2>&1) || {
        printf >&2 '\033[33m⚠ resolve_versioned_tag: aws ecr describe-images failed for repo=%s digest=%s — %s\033[0m\n' \
            "$_repo" "${_digest:0:24}…" "$(printf '%s' "$_all_tags" | awk 'NF{print; exit}')"
        echo "$_tag"
        return
    }
    if [ -z "$_all_tags" ] || [ "$_all_tags" = "null" ]; then
        echo "$_tag"
        return
    fi
    _best=$(echo "$_all_tags" | python3 -c "
import sys, json, re
tags = json.load(sys.stdin) or []
versioned = [t for t in tags if re.match(r'^\d+\.\d+\.\d+', t)]
if versioned:
    print(versioned[0]); sys.exit()
non_latest = [t for t in tags if t != 'latest']
if non_latest:
    print(non_latest[0]); sys.exit()
if tags:
    print(tags[0])" 2>/dev/null)
    if [ -n "$_best" ]; then
        echo "$_best"
    else
        echo "$_tag"
    fi
}

get_pod() {
    component="$1"
    name=$(resource_name "$component")
    _hash=$(latest_rs_hash "$component")
    _selector="app=${name}"
    [ -n "$_hash" ] && _selector="${_selector},pod-template-hash=${_hash}"
    kubectl get pods -l "$_selector" -n "$NAMESPACE" \
        --field-selector=status.phase=Running \
        --sort-by=.metadata.creationTimestamp \
        -o jsonpath='{.items[-1:].metadata.name}' 2>/dev/null
}

get_current_image() {
    component="$1"
    name=$(resource_name "$component")
    kind=$(resource_kind "$component")
    _container=$(container_name "$component")
    kubectl get "${kind}/${name}" -n "$NAMESPACE" \
        -o jsonpath="{.spec.template.spec.containers[?(@.name==\"${_container}\")].image}" 2>/dev/null || echo ""
}

get_current_version_annotation() {
    component="$1"
    name=$(resource_name "$component")
    kind=$(resource_kind "$component")
    kubectl get "${kind}/${name}" -n "$NAMESPACE" \
        -o jsonpath='{.metadata.annotations.nexus\.com/app-version}' 2>/dev/null || echo ""
}

get_previous_version_annotation() {
    component="$1"
    name=$(resource_name "$component")
    kind=$(resource_kind "$component")
    kubectl get "${kind}/${name}" -n "$NAMESPACE" \
        -o jsonpath='{.metadata.annotations.nexus\.com/previous-version}' 2>/dev/null || echo ""
}

get_ecr_registry() {
    if [ -n "${ECR_REGISTRY:-}" ]; then
        echo "${ECR_REGISTRY}"
        return 0
    fi
    ACCOUNT_ID=$(nexus_aws_account_id)
    echo "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
}

verify_image_exists() {
    _repo="$1"
    _tag="$2"
    aws_cli ecr describe-images --repository-name "${_repo}" --image-ids "imageTag=${_tag}" \
        --region "${REGION}" > /dev/null 2>&1
}

# Per-component cache for ECR auto-detect (POSIX sh; no associative arrays).
# A "_DONE" flag distinguishes "looked up and found nothing" from "not yet looked up".
_LATEST_ECR_TAG_backend=""
_LATEST_ECR_TAG_frontend=""
_LATEST_ECR_TAG_bssmagic=""
_LATEST_ECR_TAG_DONE_backend=0
_LATEST_ECR_TAG_DONE_frontend=0
_LATEST_ECR_TAG_DONE_bssmagic=0

# Returns the most recently pushed *versioned* tag in ECR for a component
# (excluding the literal "latest" pointer). Prefers semver-shaped tags
# (N.N.N-*) for backend/frontend and date-shaped tags (YYYYMMDD-*) for
# BSS Magic; falls back to any non-"latest" tag on the newest image.
# Returns empty when ECR is unreachable, the repo does not exist, or the
# repo has no qualifying tags — callers must treat empty as "no auto target"
# and fall back to legacy behavior.
latest_versioned_ecr_tag() {
    _lt_comp="$1"
    case "$_lt_comp" in
        backend)
            [ "$_LATEST_ECR_TAG_DONE_backend"  = "1" ] && { echo "$_LATEST_ECR_TAG_backend";  return; } ;;
        frontend)
            [ "$_LATEST_ECR_TAG_DONE_frontend" = "1" ] && { echo "$_LATEST_ECR_TAG_frontend"; return; } ;;
        bssmagic)
            [ "$_LATEST_ECR_TAG_DONE_bssmagic" = "1" ] && { echo "$_LATEST_ECR_TAG_bssmagic"; return; } ;;
        *)
            return ;;
    esac

    _lt_repo=$(ecr_repo "$_lt_comp")
    [ -z "$_lt_repo" ] && return

    case "$_lt_comp" in
        bssmagic) _lt_pattern='^[0-9]{8}-' ;;
        *)        _lt_pattern='^[0-9]+\.[0-9]+\.[0-9]+' ;;
    esac

    # Split AWS call from python3 parsing so a non-zero AWS exit (under set -e)
    # is caught explicitly instead of silently killing the script.
    _lt_aws=$(aws ecr describe-images --repository-name "${_lt_repo}" \
            --region "${REGION}" --profile "${AWS_PROFILE}" \
            --query 'sort_by(imageDetails,& imagePushedAt)[*].imageTags' \
            --output json 2>&1) || {
        printf >&2 '\033[33m⚠ latest_versioned_ecr_tag: aws ecr describe-images failed for repo=%s — %s\033[0m\n' \
            "$_lt_repo" "$(printf '%s' "$_lt_aws" | awk 'NF{print; exit}')"
        _lt_aws=""
    }
    _lt_tag=$(printf '%s' "$_lt_aws" | python3 -c "
import sys, json, re
try:
    data = json.load(sys.stdin) or []
except Exception:
    sys.exit(0)
pat = re.compile(r'$_lt_pattern')
# Walk newest -> oldest; first preferred-shape tag wins.
for tags in reversed(data):
    if not tags:
        continue
    matches = [t for t in tags if t != 'latest' and pat.match(t)]
    if matches:
        print(matches[0]); sys.exit(0)
# Fallback: newest image's first non-'latest' tag.
for tags in reversed(data):
    if not tags:
        continue
    others = [t for t in tags if t != 'latest']
    if others:
        print(others[0]); sys.exit(0)
" 2>/dev/null)

    case "$_lt_comp" in
        backend)  _LATEST_ECR_TAG_backend="$_lt_tag";  _LATEST_ECR_TAG_DONE_backend=1 ;;
        frontend) _LATEST_ECR_TAG_frontend="$_lt_tag"; _LATEST_ECR_TAG_DONE_frontend=1 ;;
        bssmagic) _LATEST_ECR_TAG_bssmagic="$_lt_tag"; _LATEST_ECR_TAG_DONE_bssmagic=1 ;;
    esac
    echo "$_lt_tag"
}

annotate_version() {
    _component="$1"
    _version="$2"
    _prev_version="$3"
    _name=$(resource_name "$_component")
    _kind=$(resource_kind "$_component")
    _now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    kubectl annotate "${_kind}/${_name}" -n "$NAMESPACE" --overwrite \
        "nexus.ai/app-version=${_version}" \
        "nexus.ai/previous-version=${_prev_version}" \
        "nexus.ai/deployed-at=${_now}" \
        "nexus.ai/deployed-by=app-rollout.sh" 2>/dev/null || true
}

OVERALL_EXIT=0

# ── List Versions Mode ─────────────────────────────────────────────
if [ "$LIST_VERSIONS" = "1" ]; then
    printf "\n${BOLD}Available Image Tags in ECR${RESET}\n\n"
    for comp in $COMPONENTS; do
        repo=$(ecr_repo "$comp")
        printf "${BOLD}${comp}${RESET} (${repo}):\n"
        aws ecr describe-images --repository-name "${repo}" \
            --region "${REGION}" --profile "${AWS_PROFILE}" \
            --query 'sort_by(imageDetails,& imagePushedAt)[*].{tags:imageTags,pushed:imagePushedAt,size:imageSizeInBytes}' \
            --output json 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
for img in reversed(data[-20:]):
    tags = img.get('tags') or ['<untagged>']
    pushed = img.get('pushed','?')[:19]
    size_mb = round((img.get('size',0) or 0) / 1048576, 1)
    print(f'  {pushed}  {size_mb:>6.1f}MB  {\" | \".join(tags)}')
" 2>/dev/null || echo "  (failed to query ECR)"
        echo ""
    done
    exit 0
fi

# ── Header ─────────────────────────────────────────────────────────
ECR_REGISTRY=$(get_ecr_registry)

printf "\n${BOLD}Rollout Update + Diagnostics${RESET}\n"
printf "Capability:  ${BOLD}${CAPABILITY}${RESET}\n"
printf "Environment: ${BOLD}${ENV}${RESET}\n"
printf "Namespace:   ${BOLD}${NAMESPACE}${RESET}\n"
printf "Components:  ${BOLD}${COMPONENTS}${RESET}\n"
printf "Timeout:     ${TIMEOUT}s per component\n"
printf "ECR:         ${ECR_REGISTRY}\n"
if [ -n "$TARGET_VERSION" ]; then
    printf "Version:     ${BOLD}${TARGET_VERSION}${RESET} (all components)\n"
fi
[ -n "$BACKEND_VERSION" ] && printf "  Backend:   ${BOLD}${BACKEND_VERSION}${RESET}\n"
[ -n "$FRONTEND_VERSION" ] && printf "  Frontend:  ${BOLD}${FRONTEND_VERSION}${RESET}\n"
[ -n "$BSSMAGIC_VERSION" ] && printf "  BSS Magic: ${BOLD}${BSSMAGIC_VERSION}${RESET}\n"
if [ -n "$PACKAGED_BACKEND_TAG" ] || [ -n "$PACKAGED_FRONTEND_TAG" ] || [ -n "$PACKAGED_BSSMAGIC_TAG" ]; then
    printf "Packaged:    ${DIM}(from images/nexus/versions.env)${RESET}\n"
    [ -n "$PACKAGED_BACKEND_TAG" ]  && printf "  Backend:   ${BOLD}%s${RESET}\n" "$PACKAGED_BACKEND_TAG"
    [ -n "$PACKAGED_FRONTEND_TAG" ] && printf "  Frontend:  ${BOLD}%s${RESET}\n" "$PACKAGED_FRONTEND_TAG"
    [ -n "$PACKAGED_BSSMAGIC_TAG" ] && printf "  BSS Magic: ${BOLD}%s${RESET}\n" "$PACKAGED_BSSMAGIC_TAG"
fi
if [ -z "$TARGET_VERSION" ] && [ -z "$BACKEND_VERSION" ] && [ -z "$FRONTEND_VERSION" ] \
    && [ -z "$BSSMAGIC_VERSION" ] && [ "$ROLLBACK_MODE" = "0" ] && [ "$RESTART_ONLY" = "0" ]; then
    printf "Target:      ${BOLD}ECR latest${RESET} ${DIM}(auto-detected; pass --version to pin or --restart-only to skip)${RESET}\n"
fi
[ "$RESTART_ONLY" = "1" ] && printf "Mode:        ${YELLOW}RESTART-ONLY${RESET} ${DIM}(no image change, just kubectl rollout restart)${RESET}\n"
[ "$ROLLBACK_MODE" = "1" ] && printf "Mode:        ${YELLOW}ROLLBACK${RESET}\n"
[ "$DRY_RUN" = "1" ] && printf "${YELLOW}DRY RUN — no changes will be made${RESET}\n"
echo ""

# ── Planned Deployment ────────────────────────────────────────────
if [ "$DIAGNOSTICS_ONLY" = "0" ]; then
    # ── Running in Pods (digest-resolved actual versions) ──
    # Mirrors operator-rollout.sh's "Running in pod" line: shows the actual
    # semver running inside each pod (resolved via the container's imageID
    # digest) along with the deployment spec's image tag in parens. This makes
    # it obvious when a deployment uses ":latest" but is actually pulling
    # 1.1.2-5526084 underneath.
    #
    # set -e is disabled inside the loop because kubectl's jsonpath '[-1:]'
    # used by the existing helpers (latest_rs_hash, get_running_image_digest)
    # exits non-zero when the array is empty, which would kill the script for
    # not-yet-deployed components. We want "(not deployed)" rendering instead.
    printf "${BOLD}Running in Pods:${RESET}\n"
    set +e
    for comp in $COMPONENTS; do
        _rip_label=$(component_label "$comp")
        _rip_spec_tag=$(get_current_image "$comp" | grep -o ':[^:]*$' | tr -d ':')
        _rip_resolved=$(resolve_versioned_tag "$comp" "$_rip_spec_tag")
        if [ -z "$_rip_resolved" ] && [ -z "$_rip_spec_tag" ]; then
            printf "  %-22s ${DIM}(not deployed)${RESET}\n" "${_rip_label}:"
        elif [ -n "$_rip_spec_tag" ] && [ -n "$_rip_resolved" ] && [ "$_rip_resolved" != "$_rip_spec_tag" ]; then
            printf "  %-22s ${BOLD}%s${RESET} ${DIM}(deployed as :%s)${RESET}\n" \
                "${_rip_label}:" "$_rip_resolved" "$_rip_spec_tag"
        else
            printf "  %-22s ${BOLD}%s${RESET}\n" "${_rip_label}:" "${_rip_resolved:-${_rip_spec_tag}}"
        fi
    done
    set -e
    echo ""

    printf "${BOLD}Currently Deployed → Planned:${RESET}\n"
    printf "  ${DIM}%-10s %-22s    %-22s %-30s %s${RESET}\n" \
        "COMPONENT" "CURRENT" "TARGET" "ACTION" "REPO"

    # First pass: per-component table (current → target, action label, repo).
    for comp in $COMPONENTS; do
        _pd_repo=$(ecr_repo "$comp")
        _pd_planned=$(planned_version_for "$comp")
        _pd_current=$(get_current_version_annotation "$comp")
        [ -z "$_pd_current" ] && _pd_current=$(get_current_image "$comp" | grep -o ':[^:]*$' | tr -d ':')
        _pd_current=$(resolve_versioned_tag "$comp" "$_pd_current")
        [ -z "$_pd_current" ] && _pd_current="(none)"

        # Classify the change so the operator can see at a glance what will happen.
        if [ -z "$_pd_planned" ]; then
            _pd_action="UNRESOLVED";              _pd_color="${YELLOW}"
            _pd_target_disp="(unresolved)";       _pd_target_color="${YELLOW}"
        elif [ "$ROLLBACK_MODE" = "1" ]; then
            _pd_action="ROLLBACK";                _pd_color="${YELLOW}"
            _pd_target_disp="${_pd_planned}";     _pd_target_color="${BOLD}"
        elif [ "$_pd_current" = "(none)" ]; then
            _pd_action="NEW DEPLOY";              _pd_color="${CYAN}"
            _pd_target_disp="${_pd_planned}";     _pd_target_color="${BOLD}"
        elif [ "$_pd_planned" = "$_pd_current" ]; then
            _pd_action="RESTART (no version change)"; _pd_color="${DIM}"
            _pd_target_disp="${_pd_planned}";     _pd_target_color="${BOLD}"
        else
            _pd_cmp=$(compare_versions "$_pd_current" "$_pd_planned")
            case "$_pd_cmp" in
                '<') _pd_action="UPGRADE";   _pd_color="${GREEN}" ;;
                '>') _pd_action="DOWNGRADE"; _pd_color="${YELLOW}" ;;
                '=') _pd_action="RESTART (same image)"; _pd_color="${DIM}" ;;
                *)   _pd_action="CHANGE";    _pd_color="${CYAN}" ;;
            esac
            _pd_target_disp="${_pd_planned}"; _pd_target_color="${BOLD}"
        fi

        printf "  %-10s ${DIM}%-22s${RESET} → ${_pd_target_color}%-22s${RESET} ${_pd_color}%-30s${RESET} ${DIM}[%s]${RESET}\n" \
            "${comp}:" "${_pd_current}" "${_pd_target_disp}" "${_pd_action}" "${_pd_repo}"
    done
    echo ""

    # Second pass: human-readable upgrade plan.
    printf "${BOLD}Upgrade Plan:${RESET}\n"
    for comp in $COMPONENTS; do
        _np_planned=$(planned_version_for "$comp")
        _np_current=$(get_current_version_annotation "$comp")
        [ -z "$_np_current" ] && _np_current=$(get_current_image "$comp" | grep -o ':[^:]*$' | tr -d ':')
        _np_current=$(resolve_versioned_tag "$comp" "$_np_current")
        [ -z "$_np_current" ] && _np_current="(none)"
        _np_label=$(component_label "$comp")

        if [ -z "$_np_planned" ]; then
            printf "  • ${YELLOW}%s${RESET}: target version unresolved — pre-flight will fail\n" "$_np_label"
        elif [ "$ROLLBACK_MODE" = "1" ]; then
            printf "  • %s: ${YELLOW}ROLLBACK${RESET} %s → %s will be performed\n" \
                "$_np_label" "$_np_current" "$_np_planned"
        elif [ "$_np_current" = "(none)" ]; then
            printf "  • %s: ${CYAN}initial deploy${RESET} of %s will be performed\n" \
                "$_np_label" "$_np_planned"
        elif [ "$_np_planned" = "$_np_current" ]; then
            printf "  • %s: ${DIM}rolling restart at %s (no version change)${RESET}\n" \
                "$_np_label" "$_np_current"
        else
            _np_cmp=$(compare_versions "$_np_current" "$_np_planned")
            case "$_np_cmp" in
                '<') printf "  • %s: ${GREEN}UPGRADE${RESET} %s → %s will be performed\n" \
                        "$_np_label" "$_np_current" "$_np_planned" ;;
                '>') printf "  • %s: ${YELLOW}DOWNGRADE${RESET} %s → %s will be performed\n" \
                        "$_np_label" "$_np_current" "$_np_planned" ;;
                '=') printf "  • %s: ${DIM}rolling restart at %s (same image)${RESET}\n" \
                        "$_np_label" "$_np_current" ;;
                *)   printf "  • %s: ${CYAN}CHANGE${RESET} %s → %s will be performed\n" \
                        "$_np_label" "$_np_current" "$_np_planned" ;;
            esac
        fi
    done
    echo ""
fi

# ── Phase 0 + 1 + 2: Pre-flight, Image Update, Rollout, Health ────
if [ "$DIAGNOSTICS_ONLY" = "0" ]; then
    for comp in $COMPONENTS; do
        name=$(resource_name "$comp")
        kind=$(resource_kind "$comp")
        repo=$(ecr_repo "$comp")
        _container=$(container_name "$comp")

        # Determine target version
        if [ "$ROLLBACK_MODE" = "1" ]; then
            if [ -n "$ROLLBACK_TO_VERSION" ]; then
                comp_version="$ROLLBACK_TO_VERSION"
            else
                comp_version=$(get_previous_version_annotation "$comp")
                if [ -z "$comp_version" ]; then
                    log_fail "No previous version annotation found for ${comp} — cannot rollback"
                    log_info "Use --rollback-to TAG to specify an explicit version"
                    OVERALL_EXIT=1
                    continue
                fi
            fi
        else
            comp_version=$(target_version_for "$comp")
        fi

        # ── Phase 0: Pre-flight ──
        if [ -n "$comp_version" ]; then
            log_phase "Phase 0: Pre-flight for ${comp} → ${comp_version}"

            current_image=$(get_current_image "$comp")
            current_version=$(get_current_version_annotation "$comp")
            [ -z "$current_version" ] && current_version=$(echo "$current_image" | grep -o ':[^:]*$' | tr -d ':')
            [ -z "$current_version" ] && current_version="unknown"

            printf "  Current:  ${DIM}%s${RESET}\n" "${current_version}"
            printf "  Target:   ${BOLD}%s${RESET}\n" "${comp_version}"

            if [ "$DRY_RUN" = "0" ]; then
                if [ "$SKIP_ECR_VERIFY" = "1" ]; then
                    log_info "Skipping ECR verify (--skip-ecr-verify; image assumed present)"
                else
                    log_info "Verifying image ${repo}:${comp_version} exists in ECR..."
                    if ! verify_image_exists "$repo" "$comp_version"; then
                        log_fail "Image ${repo}:${comp_version} NOT FOUND in ECR"
                        log_info "Available tags: sh app-rollout.sh --list-versions ${comp}"
                        OVERALL_EXIT=1
                        continue
                    fi
                    log_ok "Image verified in ECR"
                fi
            fi

            full_image="${ECR_REGISTRY}/${repo}:${comp_version}"

            # Save current version for rollback
            if [ "$DRY_RUN" = "0" ] && [ "$ROLLBACK_MODE" != "1" ]; then
                annotate_version "$comp" "$comp_version" "$current_version"
            fi

            # ── Phase 1: Image Update + Rollout ──
            log_phase "Phase 1: Update image for ${comp} (${kind}/${name})"

            if ! run_cmd "kubectl set image ${kind}/${name} ${_container}=${full_image} -n ${NAMESPACE}" && [ "$DRY_RUN" = "0" ]; then
                log_fail "Failed to set image for ${kind}/${name}"
                OVERALL_EXIT=1
                continue
            fi
            [ "$DRY_RUN" = "0" ] && log_ok "Image updated to ${comp_version}"
        else
            # No version specified — plain restart (legacy behavior)
            log_phase "Phase 1: Rollout restart ${comp} (${kind}/${name})"

            current_image=$(get_current_image "$comp")
            current_version=$(get_current_version_annotation "$comp")
            _existing_ann="$current_version"
            [ -z "$current_version" ] && current_version=$(echo "$current_image" | grep -o ':[^:]*$' | tr -d ':')

            if ! run_cmd "kubectl rollout restart ${kind}/${name} -n ${NAMESPACE}" && [ "$DRY_RUN" = "0" ]; then
                log_fail "Failed to restart ${kind}/${name}"
                OVERALL_EXIT=1
                continue
            fi
            [ "$DRY_RUN" = "0" ] && log_ok "Rollout restart triggered for ${kind}/${name}"

            # Backfill nexus.ai/app-version annotation if missing, so the
            # Summary block and About dialog show the real image tag instead
            # of "(unknown)" for resources created before the annotation feature.
            if [ "$DRY_RUN" = "0" ] && [ -z "$_existing_ann" ] && [ -n "$current_version" ]; then
                annotate_version "$comp" "$current_version" "$current_version"
                log_ok "Backfilled version annotation: ${current_version}"
            fi
        fi

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

            # Auto-rollback on failure
            if [ "$AUTO_ROLLBACK" = "1" ] && [ -n "$comp_version" ]; then
                log_phase "Auto-rollback for ${comp}"
                log_info "Rolling back ${kind}/${name}..."
                if kubectl rollout undo "${kind}/${name}" -n "$NAMESPACE" 2>/dev/null; then
                    log_ok "Rollback triggered"
                    kubectl rollout status "${kind}/${name}" -n "$NAMESPACE" --timeout=120s 2>/dev/null || true
                    # Restore annotation
                    if [ -n "$current_version" ] && [ "$current_version" != "unknown" ]; then
                        annotate_version "$comp" "$current_version" "$comp_version"
                    fi
                    log_warn "Rolled back to previous revision"
                else
                    log_fail "Auto-rollback failed"
                fi
            fi

            OVERALL_EXIT=1
            continue
        fi
        [ "$DRY_RUN" = "0" ] && log_ok "Rollout complete"

        # Update annotation after successful rollback
        if [ "$ROLLBACK_MODE" = "1" ] && [ "$DRY_RUN" = "0" ] && [ -n "$comp_version" ]; then
            annotate_version "$comp" "$comp_version" "$current_version"
            log_ok "Version annotation updated (rolled back to ${comp_version})"
        fi

        # When --skip-diagnostics is set, trust kubectl rollout status (Deployment
        # Ready condition) and skip redundant pod wait + exec health polling.
        if [ "$SKIP_DIAGNOSTICS" = "0" ]; then
            log_info "Verifying pod readiness..."
            _hash=$(latest_rs_hash "$comp")
            _wait_selector="app=${name}"
            [ -n "$_hash" ] && _wait_selector="${_wait_selector},pod-template-hash=${_hash}"
            if ! run_cmd "kubectl wait --for=condition=ready pod -l ${_wait_selector} -n ${NAMESPACE} --timeout=120s" && [ "$DRY_RUN" = "0" ]; then
                log_warn "Pod readiness wait timed out"
            else
                [ "$DRY_RUN" = "0" ] && log_ok "Pod(s) ready"
            fi

            # HTTP/TCP health poll
            if [ "$DRY_RUN" = "0" ]; then
                pod=$(get_pod "$comp")
                if [ -n "$pod" ]; then
                    hc=$(health_check_cmd "$comp")
                    _hc_container=$(container_name "$comp")
                    log_info "Health-checking ${comp} pod (${pod})..."
                    attempts=0
                    max_attempts=12
                    while [ $attempts -lt $max_attempts ]; do
                        if [ -n "$_hc_container" ]; then
                            result=$(kubectl exec "$pod" -n "$NAMESPACE" -c "$_hc_container" -- sh -c "$hc" 2>/dev/null) && break
                        else
                            result=$(kubectl exec "$pod" -n "$NAMESPACE" -- sh -c "$hc" 2>/dev/null) && break
                        fi
                        attempts=$((attempts + 1))
                        sleep 5
                    done
                    if [ $attempts -lt $max_attempts ]; then
                        log_ok "Health check passed for ${comp}"
                    else
                        log_warn "Health check did not pass after ${max_attempts} attempts"
                        if [ "$AUTO_ROLLBACK" = "1" ] && [ -n "$comp_version" ]; then
                            log_phase "Auto-rollback (health failure) for ${comp}"
                            if kubectl rollout undo "${kind}/${name}" -n "$NAMESPACE" 2>/dev/null; then
                                kubectl rollout status "${kind}/${name}" -n "$NAMESPACE" --timeout=120s 2>/dev/null || true
                                if [ -n "$current_version" ] && [ "$current_version" != "unknown" ]; then
                                    annotate_version "$comp" "$current_version" "$comp_version"
                                fi
                                log_warn "Rolled back due to health check failure"
                            fi
                            OVERALL_EXIT=1
                            continue
                        fi
                    fi
                else
                    log_warn "No running pod found for ${comp}"
                fi
            fi
        fi

        if [ "$SKIP_DIAGNOSTICS" = "0" ]; then
            printf "  ${DIM}Pod status:${RESET}\n"
            run_cmd "kubectl get pods -l app=${name} -n ${NAMESPACE} -o wide 2>/dev/null | sed 's/^/    /'"
            echo ""
        fi
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

        log_info "Testing frontend nginx proxy → backend /api/v1/health..."
        _api_proxy_out=$(kubectl exec "$_fe_pod" -n "$NAMESPACE" -- \
            wget -qO- --timeout=5 http://localhost:8080/api/v1/health 2>/dev/null) || _api_proxy_out=""
        if [ -n "$_api_proxy_out" ]; then
            log_ok "Proxy → /api/v1/health reachable"
        else
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

# ── Phase 4: Capability Inventory ─────────────────────────────────
# Runs inspect-capability.sh after the deploy so the operator gets a
# full inventory of cluster + AWS resources tied to this capability.
# Skipped when --skip-diagnostics is passed (consistent with Phase 2.5/3).
if [ "$SKIP_DIAGNOSTICS" = "0" ]; then
    log_phase "Phase 4: Capability Inventory"

    _inspect_script="${SCRIPT_DIR}/inspect-capability.sh"

    if [ "$DRY_RUN" = "1" ]; then
        run_cmd "bash ${_inspect_script} --env ${ENV}"
    elif [ ! -f "$_inspect_script" ]; then
        log_warn "inspect-capability.sh not found at ${_inspect_script} — skipping inventory"
    else
        log_info "Running inspect-capability.sh --env ${ENV}..."
        if bash "$_inspect_script" --env "$ENV"; then
            log_ok "Capability inventory complete"
        else
            log_warn "inspect-capability.sh exited non-zero"
            [ "$OVERALL_EXIT" = "0" ] && OVERALL_EXIT=2
        fi
    fi
fi

# ── Summary ────────────────────────────────────────────────────────
log_phase "Summary"

# Show deployed versions. Mirrors operator-rollout.sh: resolves :latest to a
# sibling versioned tag via the running pod's image digest, and appends
# "(image tag: <tag>)" when the deployment spec uses a tag distinct from the
# resolved semver (e.g. spec=":latest" -> resolved="1.1.2-5526084").
# set -e shielded for the same reason as the "Running in Pods" section above.
printf "  ${BOLD}Deployed Versions:${RESET}\n"
set +e
for comp in $COMPONENTS; do
    _sum_spec_tag=$(get_current_image "$comp" | grep -o ':[^:]*$' | tr -d ':')
    _sum_ver=$(get_current_version_annotation "$comp")
    [ -z "$_sum_ver" ] && _sum_ver="$_sum_spec_tag"
    _sum_ver=$(resolve_versioned_tag "$comp" "$_sum_ver")
    [ -z "$_sum_ver" ] && _sum_ver="(unknown)"

    if [ -n "$_sum_spec_tag" ] && [ "$_sum_ver" != "$_sum_spec_tag" ] \
            && [ "$_sum_ver" != "(unknown)" ]; then
        printf "    %-12s %s ${DIM}(image tag: %s)${RESET}\n" \
            "${comp}:" "${_sum_ver}" "${_sum_spec_tag}"
    else
        printf "    %-12s %s\n" "${comp}:" "${_sum_ver}"
    fi
done
set -e
echo ""

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

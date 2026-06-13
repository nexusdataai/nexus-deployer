#!/bin/bash
#
# Create ECR Images (crane edition - no Docker daemon required)
# Loads .tar.gz images and pushes to ECR using crane.
# Drop-in replacement for create-ecr-images.sh on hosts without Docker.
#
# Feature-parity with create-ecr-images.sh:
#   - Pre-push survey of existing ECR tags per repo
#   - Per-component version resolution (CLI override > versions.env > VERSION+git sha)
#   - Dual-tag push (:latest AND :<version>) via `crane tag` (single upload)
#   - Per-push capture-and-record so failures are reported instead of swallowed
#   - Detailed final summary with non-zero exit when any push failed
#
# Crane-specific differences vs. docker version:
#   - Tar-only: no Dockerfile build path. Provide tars via package-images.sh.
#   - No --no-cache flag (irrelevant — there's no build to skip).
#
# Requires: crane (go-containerregistry), aws CLI, python3
#
# Usage:
#   ./create-ecr-images-crane.sh                       # Push all images to ECR
#   ./create-ecr-images-crane.sh --skip-operator       # Skip operator image
#   ./create-ecr-images-crane.sh --skip-app-images     # Skip CallSense images
#   ./create-ecr-images-crane.sh --skip-bssmagic       # Skip BSS Magic image
#   ./create-ecr-images-crane.sh --only-operator       # Only push operator image
#   ./create-ecr-images-crane.sh --version 1.2.3       # Override backend + frontend tag
#   ./create-ecr-images-crane.sh --bssmagic-version V  # Override BSS Magic tag
#   ./create-ecr-images-crane.sh --operator-version V  # Override operator tag
#   ./create-ecr-images-crane.sh --help
#
# Image sources (.tar.gz only - no build support without Docker):
#   Operator:   images/operator/totogi-operator.tar.gz
#   CallSense:  images/callsense/ai-job-engine.tar.gz + starhub-ui.tar.gz
#   BSS Magic:  images/bssmagic/bssmagic-starhub-k8s.tar.gz
#

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGES_DIR="${SCRIPT_DIR}/images/callsense"
BSSMAGIC_IMAGES_DIR="${SCRIPT_DIR}/images/bssmagic"
OPERATOR_IMAGES_DIR="${SCRIPT_DIR}/images/operator"
BACKEND_DIR="/opt/mycode/trilogy/starhub-backend"
FRONTEND_DIR="/opt/mycode/trilogy/starhub-ui"

_ENVLOCAL="${SCRIPT_DIR}/.env.local"
if [ -f "$_ENVLOCAL" ]; then
    _ENV_LOCAL_ENV=$(grep '^ENV[[:space:]]*=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true)
    _ENV_LOCAL_CLUSTER=$(grep '^Cluster[[:space:]]*=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true)
fi

DEPLOY_ENV="${DEPLOY_ENV:-${_ENV_LOCAL_ENV:-prod}}"
CLUSTER_NAME="${CLUSTER_NAME:-${_ENV_LOCAL_CLUSTER:-starhub-test}}"
REGION="${REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-external-access}"

PUSH_OPERATOR=true
PUSH_APP=true
PUSH_BSSMAGIC=true
ONLY_MODE=""
APP_VERSION_OVERRIDE=""
BSSMAGIC_VERSION_OVERRIDE=""
OPERATOR_VERSION_OVERRIDE=""

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# ── Push-result tracking (populated by record_push_ok / record_push_fail) ──
PUSHED_OK=()
PUSHED_FAIL=()
record_push_ok()   { PUSHED_OK+=("$1"); }
record_push_fail() { PUSHED_FAIL+=("$1"$'\t'"$2"); }

# ── Survey: print a table of currently-pushed tags for a repo ──
# Args: $1 = ECR repository name, $2 = friendly label
survey_ecr_repo() {
    local repo="$1" label="$2"
    local repo_check
    repo_check=$(aws ecr describe-repositories --repository-names "$repo" \
                   --region "${REGION}" --profile "${AWS_PROFILE}" 2>&1) || {
        if echo "$repo_check" | grep -q "RepositoryNotFoundException"; then
            printf "  %-22s %s %s\n" "${label}:" "(repo not found)" "[${repo}]"
            return 0
        fi
        printf "  %-22s ${RED}error:${NC} %s\n" "${label}:" \
               "$(echo "$repo_check" | head -n1)"
        return 0
    }

    local images_json
    images_json=$(aws ecr describe-images --repository-name "$repo" \
                    --region "${REGION}" --profile "${AWS_PROFILE}" \
                    --output json 2>&1) || {
        printf "  %-22s ${RED}error:${NC} %s\n" "${label}:" \
               "$(echo "$images_json" | head -n1)"
        return 0
    }

    local images
    images=$(echo "$images_json" | python3 -c "
import sys, json
data = json.load(sys.stdin).get('imageDetails', [])
data.sort(key=lambda x: x.get('imagePushedAt', ''), reverse=True)
for img in data[:5]:
    tags = img.get('imageTags') or ['<untagged>']
    tag = tags[0]
    pushed = str(img.get('imagePushedAt', ''))[:19]
    size_mb = (img.get('imageSizeInBytes') or 0) // 1024 // 1024
    print(f'{tag}\t{pushed}\t{size_mb}')
" 2>&1) || {
        printf "  %-22s ${RED}error:${NC} %s\n" "${label}:" \
               "$(echo "$images" | head -n1)"
        return 0
    }

    if [ -z "$images" ]; then
        printf "  %-22s ${YELLOW}(repo exists but empty)${NC} [${repo}]\n" "${label}:"
        return 0
    fi

    printf "  %-22s [${repo}]  (5 most recent of %d)\n" "${label}:" \
           "$(echo "$images_json" | python3 -c "import sys,json;print(len(json.load(sys.stdin).get('imageDetails',[])))")"
    while IFS=$'\t' read -r tag pushed size_mb; do
        printf "    %-40s %s   ${CYAN}%sMB${NC}\n" "$tag" "$pushed" "$size_mb"
    done <<< "$images"
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-operator)    PUSH_OPERATOR=false; shift ;;
        --skip-app-images)  PUSH_APP=false; shift ;;
        --skip-bssmagic)    PUSH_BSSMAGIC=false; shift ;;
        --only-operator)    ONLY_MODE="operator"; shift ;;
        --only-app-images)  ONLY_MODE="app"; shift ;;
        --only-bssmagic)    ONLY_MODE="bssmagic"; shift ;;
        --version)          APP_VERSION_OVERRIDE="$2"; shift 2 ;;
        --bssmagic-version) BSSMAGIC_VERSION_OVERRIDE="$2"; shift 2 ;;
        --operator-version) OPERATOR_VERSION_OVERRIDE="$2"; shift 2 ;;
        --env)              DEPLOY_ENV="$2"; shift 2 ;;
        --help|-h)
            echo "Create ECR Images (crane - no Docker daemon required)"
            echo ""
            echo "Pushes .tar.gz images to ECR using crane."
            echo "Run before operator-rollout.sh / app-rollout.sh."
            echo ""
            echo "Usage:"
            echo "  $0                       # Push all images"
            echo "  $0 --skip-operator       # Skip operator"
            echo "  $0 --skip-app-images     # Skip CallSense (backend + frontend)"
            echo "  $0 --skip-bssmagic       # Skip BSS Magic"
            echo "  $0 --only-operator       # Only operator"
            echo "  $0 --only-app-images     # Only CallSense"
            echo "  $0 --only-bssmagic       # Only BSS Magic"
            echo "  $0 --version 1.2.3       # Override backend + frontend version tag"
            echo "  $0 --bssmagic-version V  # Override BSS Magic version tag"
            echo "  $0 --operator-version V  # Override operator version tag (default: kube-operator/VERSION + git sha)"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [ -n "$ONLY_MODE" ]; then
    PUSH_OPERATOR=false; PUSH_APP=false; PUSH_BSSMAGIC=false
    case "$ONLY_MODE" in
        operator) PUSH_OPERATOR=true ;;
        app)      PUSH_APP=true ;;
        bssmagic) PUSH_BSSMAGIC=true ;;
    esac
fi

if ! command -v crane &>/dev/null; then
    echo -e "${RED}crane not found. Install from: https://github.com/google/go-containerregistry/releases${NC}"
    exit 1
fi

CURRENT_ACCOUNT=$(aws sts get-caller-identity --profile "${AWS_PROFILE}" --query 'Account' --output text 2>/dev/null || true)
if [ -z "$CURRENT_ACCOUNT" ]; then
    echo -e "${RED}Failed to get AWS account ID. Are you logged in?${NC}"
    exit 1
fi
ECR_REGISTRY="${CURRENT_ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Create ECR Images (crane - no Docker daemon)${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
echo ""
echo "  AWS Account:  ${CURRENT_ACCOUNT}"
echo "  Region:       ${REGION}"
echo "  ECR Registry: ${ECR_REGISTRY}"
echo "  Operator:     ${PUSH_OPERATOR}"
echo "  CallSense:    ${PUSH_APP}"
echo "  BSS Magic:    ${PUSH_BSSMAGIC}"
echo ""

# ECR login (crane)
echo -e "${CYAN}── ECR Login (crane) ──${NC}"
LOGIN_ERR=$(aws ecr get-login-password --region "${REGION}" --profile "${AWS_PROFILE}" 2>&1 \
    | crane auth login --username AWS --password-stdin "${ECR_REGISTRY}" 2>&1) || {
    echo -e "  ${RED}✗${NC} ECR login failed:"
    echo "    ${LOGIN_ERR}"
    exit 1
}
echo -e "  ${GREEN}✓${NC} ECR login done"
echo ""

# ── Pre-push: existing ECR images (top 5 most-recent tags per repo) ──
echo -e "${CYAN}── Existing ECR Images ──${NC}"
survey_ecr_repo "totogi-operator"        "Operator"
survey_ecr_repo "ai-job-engine"          "Backend"
survey_ecr_repo "starhub-ui"             "Frontend"
survey_ecr_repo "bssmagic-starhub-k8s"   "BSS Magic"
echo ""

# ── Helper: ensure ECR repo exists, capture failures explicitly ──
# Args: $1=repo_name, $2=extra-create-args (optional, e.g. "--image-scanning-configuration scanOnPush=true")
# Echoes "ok" on success, "FAIL: <reason>" on failure.
ensure_ecr_repo() {
    local repo_name="$1"
    local extra_args="${2:-}"
    if aws ecr describe-repositories --repository-names "$repo_name" \
            --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1; then
        echo "ok"
        return 0
    fi
    echo "  Creating ECR repo: $repo_name" >&2
    local err
    # shellcheck disable=SC2086
    if err=$(aws ecr create-repository --repository-name "$repo_name" \
               --region "${REGION}" --profile "${AWS_PROFILE}" \
               $extra_args 2>&1 >/dev/null); then
        echo "ok"
    else
        echo "FAIL: $err"
    fi
}

# ── Helper: push tar to ECR with versioned + :latest tags via crane ──
# Args: $1=tar_path, $2=repo_name, $3=version_tag
# Pushes to <ECR>/<repo>:<version_tag>, then aliases :latest at the registry
# (using `crane tag`) so :latest shares the same digest without re-uploading.
# Records each tag in PUSHED_OK / PUSHED_FAIL.
crane_push_dual_tag() {
    local tar_path="$1"
    local repo_name="$2"
    local version_tag="$3"
    local versioned_target="${ECR_REGISTRY}/${repo_name}:${version_tag}"
    local latest_target="${ECR_REGISTRY}/${repo_name}:latest"

    if [ ! -f "$tar_path" ]; then
        echo -e "  ${RED}✗${NC} Tar not found: ${tar_path}"
        record_push_fail "$versioned_target" "tar not found: ${tar_path}"
        record_push_fail "$latest_target"    "tar not found: ${tar_path}"
        return 1
    fi

    # crane prefers an uncompressed tar; decompress .tar.gz to a temp file
    local push_path="$tar_path"
    local tmp_tar=""
    if [[ "$tar_path" == *.tar.gz ]] || file "$tar_path" 2>/dev/null | grep -q gzip; then
        tmp_tar="$(dirname "$tar_path")/.$(basename "$tar_path" .gz)"
        echo "  Decompressing ${tar_path}..."
        if ! gunzip -c "$tar_path" > "$tmp_tar" 2>&1; then
            echo -e "  ${RED}✗${NC} Failed to decompress ${tar_path}"
            record_push_fail "$versioned_target" "decompress failed: ${tar_path}"
            record_push_fail "$latest_target"    "decompress failed: ${tar_path}"
            return 1
        fi
        push_path="$tmp_tar"
    fi

    # Push the versioned tag first (the source of truth)
    local push_err
    if push_err=$(crane push "$push_path" "$versioned_target" 2>&1); then
        echo -e "  ${GREEN}✓${NC} pushed: ${versioned_target}"
        record_push_ok "$versioned_target"
        # Alias :latest to the same digest (registry-side, no re-upload)
        local tag_err
        if tag_err=$(crane tag "$versioned_target" "latest" 2>&1); then
            echo -e "  ${GREEN}✓${NC} tagged: ${latest_target}"
            record_push_ok "$latest_target"
        else
            echo -e "  ${RED}✗${NC} tag failed: ${latest_target}"
            echo "${tag_err}" | sed 's/^/      /'
            record_push_fail "$latest_target" "$(echo "$tag_err" | tail -n3 | tr '\n' ' ')"
        fi
    else
        echo -e "  ${RED}✗${NC} push failed: ${versioned_target}"
        echo "${push_err}" | sed 's/^/      /'
        record_push_fail "$versioned_target" "$(echo "$push_err" | tail -n3 | tr '\n' ' ')"
        record_push_fail "$latest_target"    "skipped (versioned push failed)"
    fi

    [ -n "$tmp_tar" ] && rm -f "$tmp_tar"
}

STEP=0
TOTAL=0
[ "$PUSH_OPERATOR" = true ] && TOTAL=$((TOTAL+1))
[ "$PUSH_APP" = true ] && TOTAL=$((TOTAL+1))
[ "$PUSH_BSSMAGIC" = true ] && TOTAL=$((TOTAL+1))

# ──────────────────────────────────────────────────────────────
# Operator Image
# ──────────────────────────────────────────────────────────────
if [ "$PUSH_OPERATOR" = true ]; then
    STEP=$((STEP+1))
    echo -e "${CYAN}── [${STEP}/${TOTAL}] Operator Image ──${NC}"

    OPERATOR_TAR="${OPERATOR_IMAGES_DIR}/totogi-operator.tar.gz"

    # Resolve operator version tag (crane has no build path; tar file is authoritative).
    # Priority:
    #   1. --operator-version CLI override
    #   2. versions.env present AND matches live: use it
    #   3. versions.env present but stale: ERROR — crane cannot rebuild
    #   4. else: live VERSION + git sha
    _op_ver=$(cat "${SCRIPT_DIR}/VERSION" 2>/dev/null | tr -d '[:space:]' || echo "0.0.0")
    _op_sha=$(cd "${SCRIPT_DIR}" 2>/dev/null && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    LIVE_OPERATOR_TAG="${_op_ver}-${_op_sha}"
    _OP_TAR_STALE=false

    if [ -n "${OPERATOR_VERSION_OVERRIDE}" ]; then
        OPERATOR_TAG="${OPERATOR_VERSION_OVERRIDE}"
        echo "  (using --operator-version override: ${OPERATOR_TAG})"
    elif [ -f "${OPERATOR_IMAGES_DIR}/versions.env" ]; then
        _saved_OPERATOR_TAG=$(. "${OPERATOR_IMAGES_DIR}/versions.env" >/dev/null 2>&1; echo "${OPERATOR_TAG:-}")
        if [ -n "${_saved_OPERATOR_TAG}" ] && [ "${_saved_OPERATOR_TAG}" != "${LIVE_OPERATOR_TAG}" ]; then
            echo -e "  ${RED}✗${NC} ${OPERATOR_IMAGES_DIR}/versions.env is stale:"
            echo "      saved: ${_saved_OPERATOR_TAG}"
            echo "      live:  ${LIVE_OPERATOR_TAG}"
            echo "      Crane cannot rebuild without Docker. Re-run package-images.sh, or pass --operator-version <tag> to override."
            OPERATOR_TAG="${LIVE_OPERATOR_TAG}"
            _OP_TAR_STALE=true
        else
            OPERATOR_TAG="${_saved_OPERATOR_TAG:-$LIVE_OPERATOR_TAG}"
            echo "  (read operator version from ${OPERATOR_IMAGES_DIR}/versions.env — matches live)"
        fi
    else
        OPERATOR_TAG="${LIVE_OPERATOR_TAG}"
    fi
    echo "  Operator version tag: ${OPERATOR_TAG}"
    echo "  Push plan:"
    echo "    ${ECR_REGISTRY}/totogi-operator:latest"
    echo "    ${ECR_REGISTRY}/totogi-operator:${OPERATOR_TAG}"

    if [ "$_OP_TAR_STALE" = true ]; then
        record_push_fail "${ECR_REGISTRY}/totogi-operator:latest"          "stale tar (saved=${_saved_OPERATOR_TAG} live=${LIVE_OPERATOR_TAG}); run package-images.sh"
        record_push_fail "${ECR_REGISTRY}/totogi-operator:${OPERATOR_TAG}" "stale tar (saved=${_saved_OPERATOR_TAG} live=${LIVE_OPERATOR_TAG}); run package-images.sh"
    elif [ ! -f "$OPERATOR_TAR" ]; then
        echo -e "  ${RED}✗${NC} Operator tar not found at ${OPERATOR_TAR}"
        echo "    Cannot build without Docker. Provide the tar via package-images.sh."
        record_push_fail "${ECR_REGISTRY}/totogi-operator:latest"          "tar not found: ${OPERATOR_TAR}"
        record_push_fail "${ECR_REGISTRY}/totogi-operator:${OPERATOR_TAG}" "tar not found: ${OPERATOR_TAR}"
    else
        echo "  Loading from tar: ${OPERATOR_TAR}"
        repo_status=$(ensure_ecr_repo "totogi-operator")
        if [ "$repo_status" != "ok" ]; then
            echo -e "  ${RED}✗${NC} Failed to create repo 'totogi-operator': ${repo_status#FAIL: }"
            record_push_fail "${ECR_REGISTRY}/totogi-operator:latest"          "create-repository failed: ${repo_status#FAIL: }"
            record_push_fail "${ECR_REGISTRY}/totogi-operator:${OPERATOR_TAG}" "create-repository failed: ${repo_status#FAIL: }"
        else
            crane_push_dual_tag "$OPERATOR_TAR" "totogi-operator" "$OPERATOR_TAG"
        fi
    fi
    echo ""
fi

# ──────────────────────────────────────────────────────────────
# CallSense Images (backend + frontend)
# ──────────────────────────────────────────────────────────────
if [ "$PUSH_APP" = true ]; then
    STEP=$((STEP+1))
    echo -e "${CYAN}── [${STEP}/${TOTAL}] CallSense Images (backend + frontend) ──${NC}"

    BACKEND_TAR="${IMAGES_DIR}/ai-job-engine.tar.gz"
    FRONTEND_TAR="${IMAGES_DIR}/starhub-ui.tar.gz"

    # Resolve version tags (crane has no build path; tar files are authoritative).
    # Priority:
    #   1. --version CLI override
    #   2. versions.env present AND matches live VERSION+sha: use it
    #   3. versions.env present but stale: ERROR — crane cannot rebuild
    #   4. else: live VERSION + git sha
    _be_ver=$(cat "${BACKEND_DIR}/VERSION" 2>/dev/null | tr -d '[:space:]' || echo "0.0.0")
    _be_sha=$(cd "${BACKEND_DIR}" 2>/dev/null && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    _fe_ver=$(cat "${FRONTEND_DIR}/VERSION" 2>/dev/null | tr -d '[:space:]' || echo "0.0.0")
    _fe_sha=$(cd "${FRONTEND_DIR}" 2>/dev/null && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    LIVE_BACKEND_TAG="${_be_ver}-${_be_sha}"
    LIVE_FRONTEND_TAG="${_fe_ver}-${_fe_sha}"
    _APP_TAR_STALE=false

    if [ -n "${APP_VERSION_OVERRIDE}" ]; then
        BACKEND_TAG="${APP_VERSION_OVERRIDE}"
        FRONTEND_TAG="${APP_VERSION_OVERRIDE}"
        echo "  (using --version override: ${BACKEND_TAG})"
    elif [ -f "${IMAGES_DIR}/versions.env" ]; then
        _saved_BACKEND_TAG=$(. "${IMAGES_DIR}/versions.env" >/dev/null 2>&1; echo "${BACKEND_TAG:-}")
        _saved_FRONTEND_TAG=$(. "${IMAGES_DIR}/versions.env" >/dev/null 2>&1; echo "${FRONTEND_TAG:-}")
        if [ "${_saved_BACKEND_TAG}" != "${LIVE_BACKEND_TAG}" ] || [ "${_saved_FRONTEND_TAG}" != "${LIVE_FRONTEND_TAG}" ]; then
            echo -e "  ${RED}✗${NC} ${IMAGES_DIR}/versions.env is stale:"
            echo "      saved: backend=${_saved_BACKEND_TAG:-<unset>}  frontend=${_saved_FRONTEND_TAG:-<unset>}"
            echo "      live:  backend=${LIVE_BACKEND_TAG}            frontend=${LIVE_FRONTEND_TAG}"
            echo "      Crane cannot rebuild without Docker. Re-run package-images.sh, or pass --version <tag> to override."
            BACKEND_TAG="${LIVE_BACKEND_TAG}"
            FRONTEND_TAG="${LIVE_FRONTEND_TAG}"
            _APP_TAR_STALE=true
        else
            BACKEND_TAG="${_saved_BACKEND_TAG}"
            FRONTEND_TAG="${_saved_FRONTEND_TAG}"
            echo "  (read versions from ${IMAGES_DIR}/versions.env — matches live)"
        fi
    else
        BACKEND_TAG="${LIVE_BACKEND_TAG}"
        FRONTEND_TAG="${LIVE_FRONTEND_TAG}"
    fi
    echo "  Backend version tag:  ${BACKEND_TAG}"
    echo "  Frontend version tag: ${FRONTEND_TAG}"
    echo "  Push plan:"
    echo "    ${ECR_REGISTRY}/ai-job-engine:latest"
    echo "    ${ECR_REGISTRY}/ai-job-engine:${BACKEND_TAG}"
    echo "    ${ECR_REGISTRY}/starhub-ui:latest"
    echo "    ${ECR_REGISTRY}/starhub-ui:${FRONTEND_TAG}"

    if [ "$_APP_TAR_STALE" = true ]; then
        for repo_pair in "ai-job-engine|${BACKEND_TAG}" "starhub-ui|${FRONTEND_TAG}"; do
            r="${repo_pair%%|*}"; t="${repo_pair##*|}"
            record_push_fail "${ECR_REGISTRY}/${r}:latest" "stale tar (saved/live mismatch); run package-images.sh"
            record_push_fail "${ECR_REGISTRY}/${r}:${t}"   "stale tar (saved/live mismatch); run package-images.sh"
        done
    elif [ ! -f "$BACKEND_TAR" ] || [ ! -f "$FRONTEND_TAR" ]; then
        echo -e "  ${RED}✗${NC} CallSense tar files not found in ${IMAGES_DIR}/"
        echo "    Cannot build without Docker. Provide the tar files via package-images.sh."
        for repo_pair in "ai-job-engine|${BACKEND_TAG}" "starhub-ui|${FRONTEND_TAG}"; do
            r="${repo_pair%%|*}"; t="${repo_pair##*|}"
            record_push_fail "${ECR_REGISTRY}/${r}:latest" "tar not found in ${IMAGES_DIR}"
            record_push_fail "${ECR_REGISTRY}/${r}:${t}"   "tar not found in ${IMAGES_DIR}"
        done
    else
        for repo_pair in "ai-job-engine|${BACKEND_TAG}|${BACKEND_TAR}" "starhub-ui|${FRONTEND_TAG}|${FRONTEND_TAR}"; do
            IFS='|' read -r repo tag tar_path <<< "$repo_pair"
            repo_status=$(ensure_ecr_repo "$repo")
            if [ "$repo_status" != "ok" ]; then
                echo -e "  ${RED}✗${NC} Failed to create repo '${repo}': ${repo_status#FAIL: }"
                record_push_fail "${ECR_REGISTRY}/${repo}:latest" "create-repository failed: ${repo_status#FAIL: }"
                record_push_fail "${ECR_REGISTRY}/${repo}:${tag}" "create-repository failed: ${repo_status#FAIL: }"
                continue
            fi
            crane_push_dual_tag "$tar_path" "$repo" "$tag"
        done
    fi
    echo ""
fi

# ──────────────────────────────────────────────────────────────
# BSS Magic Image
# ──────────────────────────────────────────────────────────────
if [ "$PUSH_BSSMAGIC" = true ]; then
    STEP=$((STEP+1))
    echo -e "${CYAN}── [${STEP}/${TOTAL}] BSS Magic Image ──${NC}"

    BSS_TAR="${BSSMAGIC_IMAGES_DIR}/bssmagic-starhub-k8s.tar.gz"

    # Resolve BSS Magic version (priority: CLI override > versions.env from tar > date-based)
    if [ -n "${BSSMAGIC_VERSION_OVERRIDE}" ]; then
        BSSMAGIC_TAG="${BSSMAGIC_VERSION_OVERRIDE}"
    elif [ -f "${BSSMAGIC_IMAGES_DIR}/versions.env" ]; then
        . "${BSSMAGIC_IMAGES_DIR}/versions.env"
        echo "  (read version from ${BSSMAGIC_IMAGES_DIR}/versions.env)"
    else
        BSSMAGIC_TAG="${BSSMAGIC_TAG:-$(date +%Y%m%d)-manual}"
    fi
    echo "  BSS Magic version tag: ${BSSMAGIC_TAG}"

    if [ -f "$BSS_TAR" ]; then
        echo "  Push plan:"
        echo "    ${ECR_REGISTRY}/bssmagic-starhub-k8s:latest"
        echo "    ${ECR_REGISTRY}/bssmagic-starhub-k8s:${BSSMAGIC_TAG}"
        echo "  Loading from tar: ${BSS_TAR}"

        repo_status=$(ensure_ecr_repo "bssmagic-starhub-k8s" "--image-scanning-configuration scanOnPush=true")
        if [ "$repo_status" != "ok" ]; then
            echo -e "  ${RED}✗${NC} Failed to create repo 'bssmagic-starhub-k8s': ${repo_status#FAIL: }"
            record_push_fail "${ECR_REGISTRY}/bssmagic-starhub-k8s:latest"          "create-repository failed: ${repo_status#FAIL: }"
            record_push_fail "${ECR_REGISTRY}/bssmagic-starhub-k8s:${BSSMAGIC_TAG}" "create-repository failed: ${repo_status#FAIL: }"
        else
            crane_push_dual_tag "$BSS_TAR" "bssmagic-starhub-k8s" "$BSSMAGIC_TAG"
        fi
    else
        echo -e "  ${YELLOW}!${NC} BSS Magic tar not found at ${BSS_TAR}"
        echo "    Will use whatever image is already in ECR."
        echo "    Run ./package-images.sh --only-bssmagic to create the tar."
    fi
    echo ""
fi

# ──────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────
FAIL_COUNT=${#PUSHED_FAIL[@]}
OK_COUNT=${#PUSHED_OK[@]}

if [ "$FAIL_COUNT" -eq 0 ]; then
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  ECR Images Ready  (${OK_COUNT} pushed, 0 failed)${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
else
    echo -e "${RED}═══════════════════════════════════════════════════════════════════${NC}"
    echo -e "${RED}  ECR Push Completed With Errors  (${OK_COUNT} pushed, ${FAIL_COUNT} failed)${NC}"
    echo -e "${RED}═══════════════════════════════════════════════════════════════════${NC}"
fi
echo ""
echo "  Registry: ${ECR_REGISTRY}"
echo ""

if [ "$OK_COUNT" -gt 0 ]; then
    echo -e "${CYAN}── Pushed Successfully ──${NC}"
    for img in "${PUSHED_OK[@]}"; do
        echo -e "  ${GREEN}✓${NC} ${img}"
    done
    echo ""
fi

if [ "$FAIL_COUNT" -gt 0 ]; then
    echo -e "${CYAN}── Failures ──${NC}"
    for entry in "${PUSHED_FAIL[@]}"; do
        img="${entry%%	*}"
        reason="${entry#*	}"
        echo -e "  ${RED}✗${NC} ${img}"
        echo "      reason: ${reason}"
    done
    echo ""
    echo "  You can now deploy with (after fixing the failures above):"
    echo "    ./operator-rollout.sh --version <operator-tag>"
    echo "    ./app-rollout.sh --version <app-tag> all"
    echo ""
    exit 1
fi

echo "  You can now deploy with:"
echo "    ./operator-rollout.sh --version <operator-tag>"
echo "    ./app-rollout.sh --version <app-tag> all"
echo ""

#!/bin/bash
#
# Create ECR Images
# Builds/loads and pushes operator, Nexus (backend + frontend), and BSS Magic
# Docker images to ECR. Run this before e2e-deploy.sh.
# Reads defaults from .env.local.
#
# Each image is pushed with BOTH :latest and :<version> tags. Versions are
# resolved per-component, priority highest-first:
#   1. CLI override (--version, --bssmagic-version, --operator-version)
#   2. images/<component>/versions.env (written by package-images.sh) — used
#      when it matches the live VERSION+git-sha; otherwise reported stale.
#   3. live VERSION file + git short sha:  <ver>-<sha>
#        Operator:  kube-operator/VERSION
#        Backend:   nexus-backend/VERSION
#        Frontend:  nexus-ui/VERSION
#        BSS Magic: no VERSION file by default — falls back to
#                   $(date +%Y%m%d)-manual unless --bssmagic-version is given.
#
# Usage:
#   ./create-ecr-images.sh                       # Push all images to ECR (dual-tagged)
#   ./create-ecr-images.sh --skip-operator       # Skip operator image
#   ./create-ecr-images.sh --skip-app-images     # Skip Nexus (backend + frontend)
#   ./create-ecr-images.sh --skip-bssmagic       # Skip BSS Magic image
#   ./create-ecr-images.sh --only-operator       # Only push operator image
#   ./create-ecr-images.sh --version 1.2.3       # Override backend + frontend version tag
#   ./create-ecr-images.sh --bssmagic-version V  # Override BSS Magic version tag
#   ./create-ecr-images.sh --operator-version V  # Override operator version tag
#   ./create-ecr-images.sh --help
#
# Image sources (auto-detected):
#   Operator:   Built from kube-operator/Dockerfile (or images/operator/*.tar.gz)
#   Nexus:      images/nexus/*.tar.gz (or built from nexus-backend + nexus-ui)
#   BSS Magic:  images/bssmagic/*.tar.gz
#

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGES_DIR="${SCRIPT_DIR}/images/nexus"
BSSMAGIC_IMAGES_DIR="${SCRIPT_DIR}/images/bssmagic"
OPERATOR_IMAGES_DIR="${SCRIPT_DIR}/images/operator"
SRE_IMAGES_DIR="${SCRIPT_DIR}/images/nexus-sre"
AI_ENGINE_IMAGES_DIR="${SCRIPT_DIR}/images/nexus-ai-engine"
ONTOLOGY_IMAGES_DIR="${SCRIPT_DIR}/images/nexus-ontology"
BACKEND_DIR="/opt/mycode/nexus/nexus-backend"
FRONTEND_DIR="/opt/mycode/nexus/nexus-ui"
SRE_BACKEND_DIR="/opt/mycode/nexus/nexus-sre/backend"
SRE_FRONTEND_DIR="/opt/mycode/nexus/nexus-sre/frontend"
SRE_POSTGRES_DIR="/opt/mycode/nexus/nexus-sre/postgres-image"
AI_ENGINE_DIR="/opt/mycode/nexus/nexus-ai-engine"
ONTOLOGY_DIR="/opt/mycode/nexus/nexus-ontology"

_ENVLOCAL="${SCRIPT_DIR}/.env.local"
if [ -f "$_ENVLOCAL" ]; then
    _ENV_LOCAL_ENV=$(grep '^ENV=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- || true)
    _ENV_LOCAL_CLUSTER=$(grep '^Cluster=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- || true)
fi

DEPLOY_ENV="${DEPLOY_ENV:-${_ENV_LOCAL_ENV:-prod}}"
CLUSTER_NAME="${CLUSTER_NAME:-${_ENV_LOCAL_CLUSTER:-nexus-dev}}"
REGION="${REGION:-us-east-1}"
# AWS_PROFILE is read from .env.local when set (survhana for nexus-prod);
# defaults to ptr-tech for legacy compatibility.
_ENV_LOCAL_AWS_PROFILE=$(grep '^AWS_PROFILE=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- || true)
AWS_PROFILE="${AWS_PROFILE:-${_ENV_LOCAL_AWS_PROFILE:-ptr-tech}}"

PUSH_OPERATOR=true
PUSH_APP=true
PUSH_BSSMAGIC=true
PUSH_SRE_BACKEND=false
PUSH_SRE_UI=false
PUSH_SRE_POSTGRES=false
PUSH_AI_ENGINE_API=false
PUSH_AI_ENGINE_UI=false
PUSH_ONTOLOGY_API=false
PUSH_ONTOLOGY_UI=false
ONLY_MODE=""
NO_CACHE=false
APP_VERSION_OVERRIDE=""
BSSMAGIC_VERSION_OVERRIDE=""
OPERATOR_VERSION_OVERRIDE=""
SRE_VERSION_OVERRIDE=""
AI_ENGINE_VERSION_OVERRIDE=""
ONTOLOGY_VERSION_OVERRIDE=""

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# ── Push-result tracking ─────────────────────────────────────────
PUSHED_OK=()
PUSHED_FAIL=()
record_push_ok()   { PUSHED_OK+=("$1"); }
record_push_fail() { PUSHED_FAIL+=("$1"$'\t'"$2"); }

# ── docker push of a single ref, with success/failure recording ──
docker_push_recorded() {
    local ref="$1"
    if push_err=$(docker push "$ref" 2>&1); then
        echo -e "  ${GREEN}✓${NC} pushed: ${ref}"
        record_push_ok "$ref"
        return 0
    else
        echo -e "  ${RED}✗${NC} push failed: ${ref}"
        echo "$push_err" | tail -n3 | sed 's/^/      /'
        record_push_fail "$ref" "$(echo "$push_err" | tail -n3 | tr '\n' ' ')"
        return 1
    fi
}

# ── Dual-tag a local Docker image (:latest + :<version>) and push both ──
# Args: $1=local_image_ref (e.g. nexus-operator:latest), $2=ecr_repo_name,
#       $3=version_tag
docker_dual_tag_push() {
    local local_ref="$1" repo="$2" version_tag="$3"
    local versioned="${ECR_REGISTRY}/${repo}:${version_tag}"
    local latest="${ECR_REGISTRY}/${repo}:latest"

    docker tag "$local_ref" "$versioned"
    docker tag "$local_ref" "$latest"
    docker_push_recorded "$versioned"
    docker_push_recorded "$latest"
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-operator)     PUSH_OPERATOR=false; shift ;;
        --skip-app-images)   PUSH_APP=false; shift ;;
        --skip-bssmagic)     PUSH_BSSMAGIC=false; shift ;;
        --only-operator)     ONLY_MODE="operator"; shift ;;
        --only-app-images)   ONLY_MODE="app"; shift ;;
        --only-bssmagic)     ONLY_MODE="bssmagic"; shift ;;
        --only-sre-images)   ONLY_MODE="sre"; shift ;;
        --with-sre-images)   PUSH_SRE_BACKEND=true; PUSH_SRE_UI=true; PUSH_SRE_POSTGRES=true; shift ;;
        --only-sre-postgres) ONLY_MODE="sre-postgres"; shift ;;
        --only-ai-engine-images) ONLY_MODE="ai-engine"; shift ;;
        --only-ai-engine-api)  ONLY_MODE="ai-engine-api"; shift ;;
        --with-ai-engine-images) PUSH_AI_ENGINE_API=true; shift ;;
        --ai-engine-version)   AI_ENGINE_VERSION_OVERRIDE="$2"; shift 2 ;;
        --only-ontology-images) ONLY_MODE="ontology"; shift ;;
        --only-ontology-api)   ONLY_MODE="ontology-api"; shift ;;
        --with-ontology-images) PUSH_ONTOLOGY_API=true; PUSH_ONTOLOGY_UI=true; shift ;;
        --ontology-version)    ONTOLOGY_VERSION_OVERRIDE="$2"; shift 2 ;;
        --sre-version)       SRE_VERSION_OVERRIDE="$2"; shift 2 ;;
        --no-cache)          NO_CACHE=true; shift ;;
        --env)               DEPLOY_ENV="$2"; shift 2 ;;
        --version)           APP_VERSION_OVERRIDE="$2"; shift 2 ;;
        --bssmagic-version)  BSSMAGIC_VERSION_OVERRIDE="$2"; shift 2 ;;
        --operator-version)  OPERATOR_VERSION_OVERRIDE="$2"; shift 2 ;;
        --help|-h)
            echo "Create ECR Images"
            echo ""
            echo "Builds/loads and pushes all Docker images to ECR with both"
            echo ":latest and :<version> tags. Run this before e2e-deploy.sh."
            echo ""
            echo "Usage:"
            echo "  $0                       # Push all images"
            echo "  $0 --skip-operator       # Skip operator"
            echo "  $0 --skip-app-images     # Skip Nexus (backend + frontend)"
            echo "  $0 --skip-bssmagic       # Skip BSS Magic"
            echo "  $0 --only-operator       # Only operator"
            echo "  $0 --only-app-images     # Only Nexus"
            echo "  $0 --only-bssmagic       # Only BSS Magic"
            echo "  $0 --no-cache            # Force rebuild from Dockerfile (ignore tar files)"
            echo "  $0 --version 1.2.3       # Override backend + frontend version tag"
            echo "  $0 --bssmagic-version V  # Override BSS Magic version tag"
            echo "  $0 --operator-version V  # Override operator version tag (default: kube-operator/VERSION + git sha)"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [ -n "$ONLY_MODE" ]; then
    PUSH_OPERATOR=false; PUSH_APP=false; PUSH_BSSMAGIC=false; PUSH_SRE_BACKEND=false; PUSH_SRE_UI=false; PUSH_SRE_POSTGRES=false; PUSH_AI_ENGINE_API=false; PUSH_AI_ENGINE_UI=false; PUSH_ONTOLOGY_API=false; PUSH_ONTOLOGY_UI=false
    case "$ONLY_MODE" in
        operator)     PUSH_OPERATOR=true ;;
        app)          PUSH_APP=true ;;
        bssmagic)     PUSH_BSSMAGIC=true ;;
        sre)          PUSH_SRE_BACKEND=true; PUSH_SRE_UI=true; PUSH_SRE_POSTGRES=true ;;
        sre-postgres) PUSH_SRE_POSTGRES=true ;;
        ai-engine)    PUSH_AI_ENGINE_API=true; PUSH_AI_ENGINE_UI=true ;;
        ai-engine-api) PUSH_AI_ENGINE_API=true ;;
        ontology)     PUSH_ONTOLOGY_API=true; PUSH_ONTOLOGY_UI=true ;;
        ontology-api) PUSH_ONTOLOGY_API=true ;;
    esac
fi

CURRENT_ACCOUNT=$(aws sts get-caller-identity --profile "${AWS_PROFILE}" --query 'Account' --output text 2>/dev/null || true)
if [ -z "$CURRENT_ACCOUNT" ]; then
    echo -e "${RED}Failed to get AWS account ID. Are you logged in?${NC}"
    exit 1
fi
ECR_REGISTRY="${CURRENT_ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Create ECR Images${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
echo ""
echo "  AWS Account:  ${CURRENT_ACCOUNT}"
echo "  Region:       ${REGION}"
echo "  ECR Registry: ${ECR_REGISTRY}"
echo "  Operator:     ${PUSH_OPERATOR}"
echo "  Nexus:        ${PUSH_APP}"
echo "  BSS Magic:    ${PUSH_BSSMAGIC}"
echo "  nexus-sre-backend:  ${PUSH_SRE_BACKEND}"
echo "  nexus-sre-ui:       ${PUSH_SRE_UI}"
echo "  nexus-sre-postgres: ${PUSH_SRE_POSTGRES}"
echo "  nexus-ai-engine-api: ${PUSH_AI_ENGINE_API}"
echo "  nexus-ai-engine-ui:  ${PUSH_AI_ENGINE_UI}"
echo "  nexus-ontology-api:  ${PUSH_ONTOLOGY_API}"
echo "  nexus-ontology-ui:   ${PUSH_ONTOLOGY_UI}"
echo ""

# ECR login
echo -e "${CYAN}── ECR Login ──${NC}"
aws ecr get-login-password --region "${REGION}" --profile "${AWS_PROFILE}" \
    | docker login --username AWS --password-stdin "${ECR_REGISTRY}" 2>/dev/null || true
echo -e "  ${GREEN}✓${NC} ECR login done"
echo ""

STEP=0
TOTAL=0
[ "$PUSH_OPERATOR" = true ] && TOTAL=$((TOTAL+1))
[ "$PUSH_APP" = true ] && TOTAL=$((TOTAL+1))
[ "$PUSH_BSSMAGIC" = true ] && TOTAL=$((TOTAL+1))
[ "$PUSH_SRE_BACKEND" = true ] && TOTAL=$((TOTAL+1))
[ "$PUSH_SRE_UI" = true ] && TOTAL=$((TOTAL+1))
[ "$PUSH_SRE_POSTGRES" = true ] && TOTAL=$((TOTAL+1))
[ "$PUSH_AI_ENGINE_API" = true ] && TOTAL=$((TOTAL+1))
[ "$PUSH_AI_ENGINE_UI" = true ] && TOTAL=$((TOTAL+1))
[ "$PUSH_ONTOLOGY_API" = true ] && TOTAL=$((TOTAL+1))
[ "$PUSH_ONTOLOGY_UI" = true ] && TOTAL=$((TOTAL+1))

# ──────────────────────────────────────────────────────────────
# Operator Image
# ──────────────────────────────────────────────────────────────
if [ "$PUSH_OPERATOR" = true ]; then
    STEP=$((STEP+1))
    echo -e "${CYAN}── [${STEP}/${TOTAL}] Operator Image ──${NC}"

    # Resolve operator version tag.
    # Priority: --operator-version > images/operator/versions.env > VERSION+sha
    _op_ver=$(cat "${SCRIPT_DIR}/VERSION" 2>/dev/null | tr -d '[:space:]' || echo "0.0.0")
    _op_sha=$(cd "${SCRIPT_DIR}" 2>/dev/null && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    LIVE_OPERATOR_TAG="${_op_ver}-${_op_sha}"

    if [ -n "${OPERATOR_VERSION_OVERRIDE}" ]; then
        OPERATOR_TAG="${OPERATOR_VERSION_OVERRIDE}"
        echo "  (using --operator-version override: ${OPERATOR_TAG})"
    elif [ -f "${OPERATOR_IMAGES_DIR}/versions.env" ]; then
        _saved_OPERATOR_TAG=$(. "${OPERATOR_IMAGES_DIR}/versions.env" >/dev/null 2>&1; echo "${OPERATOR_TAG:-}")
        OPERATOR_TAG="${_saved_OPERATOR_TAG:-$LIVE_OPERATOR_TAG}"
        echo "  (read operator version from ${OPERATOR_IMAGES_DIR}/versions.env: ${OPERATOR_TAG})"
    else
        OPERATOR_TAG="${LIVE_OPERATOR_TAG}"
    fi

    HAS_OPERATOR_TAR=false
    [ -f "${OPERATOR_IMAGES_DIR}/nexus-operator.tar.gz" ] && HAS_OPERATOR_TAR=true

    if [ "$NO_CACHE" = true ] || [ "$HAS_OPERATOR_TAR" = false ]; then
        echo "  Building from source: ${SCRIPT_DIR}/Dockerfile"
        docker build --no-cache -t nexus-operator:latest "${SCRIPT_DIR}"
    else
        echo "  Loading from tar: ${OPERATOR_IMAGES_DIR}/nexus-operator.tar.gz"
        docker load -i "${OPERATOR_IMAGES_DIR}/nexus-operator.tar.gz"
    fi

    echo "  Operator version tag: ${OPERATOR_TAG}"
    echo "  Push plan:"
    echo "    ${ECR_REGISTRY}/nexus-operator:${OPERATOR_TAG}"
    echo "    ${ECR_REGISTRY}/nexus-operator:latest"

    aws ecr describe-repositories --repository-names "nexus-operator" \
        --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1 \
    || aws ecr create-repository --repository-name "nexus-operator" \
        --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1 \
    || true

    docker_dual_tag_push "nexus-operator:latest" "nexus-operator" "$OPERATOR_TAG"
    echo ""
fi

# ──────────────────────────────────────────────────────────────
# Nexus Images (backend + frontend)
# ──────────────────────────────────────────────────────────────
if [ "$PUSH_APP" = true ]; then
    STEP=$((STEP+1))
    echo -e "${CYAN}── [${STEP}/${TOTAL}] Nexus Images (backend + frontend) ──${NC}"

    # Resolve version tags.
    # Priority: --version > images/nexus/versions.env > VERSION+sha (per repo)
    _be_ver=$(cat "${BACKEND_DIR}/VERSION" 2>/dev/null | tr -d '[:space:]' || echo "0.0.0")
    _be_sha=$(cd "${BACKEND_DIR}" 2>/dev/null && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    _fe_ver=$(cat "${FRONTEND_DIR}/VERSION" 2>/dev/null | tr -d '[:space:]' || echo "0.0.0")
    _fe_sha=$(cd "${FRONTEND_DIR}" 2>/dev/null && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    LIVE_BACKEND_TAG="${_be_ver}-${_be_sha}"
    LIVE_FRONTEND_TAG="${_fe_ver}-${_fe_sha}"

    if [ -n "${APP_VERSION_OVERRIDE}" ]; then
        BACKEND_TAG="${APP_VERSION_OVERRIDE}"
        FRONTEND_TAG="${APP_VERSION_OVERRIDE}"
        echo "  (using --version override: ${BACKEND_TAG})"
    elif [ -f "${IMAGES_DIR}/versions.env" ]; then
        _saved_BACKEND_TAG=$(. "${IMAGES_DIR}/versions.env" >/dev/null 2>&1; echo "${BACKEND_TAG:-}")
        _saved_FRONTEND_TAG=$(. "${IMAGES_DIR}/versions.env" >/dev/null 2>&1; echo "${FRONTEND_TAG:-}")
        BACKEND_TAG="${_saved_BACKEND_TAG:-$LIVE_BACKEND_TAG}"
        FRONTEND_TAG="${_saved_FRONTEND_TAG:-$LIVE_FRONTEND_TAG}"
        echo "  (read versions from ${IMAGES_DIR}/versions.env: backend=${BACKEND_TAG}, frontend=${FRONTEND_TAG})"
    else
        BACKEND_TAG="${LIVE_BACKEND_TAG}"
        FRONTEND_TAG="${LIVE_FRONTEND_TAG}"
    fi

    HAS_TAR_IMAGES=false
    [ -f "${IMAGES_DIR}/ai-job-engine.tar.gz" ] && [ -f "${IMAGES_DIR}/nexus-ui.tar.gz" ] && HAS_TAR_IMAGES=true

    if [ "$NO_CACHE" = true ] || [ "$HAS_TAR_IMAGES" = false ]; then
        if [ ! -d "${BACKEND_DIR}" ] || [ ! -d "${FRONTEND_DIR}" ]; then
            echo -e "${RED}  Source directories not available for fresh build.${NC}"
            echo "  Ensure nexus-backend and nexus-ui repos exist."
            exit 1
        fi
        echo "  Building from source (fresh)..."
        echo "  Building backend (ai-job-engine)..."
        docker build --no-cache -t ai-job-engine:latest "${BACKEND_DIR}"
        echo "  Building frontend (nexus-ui)..."
        docker build --no-cache -t nexus-ui:latest "${FRONTEND_DIR}"
    else
        echo "  Loading from tar files..."
        echo "    Loading ai-job-engine..."
        docker load -i "${IMAGES_DIR}/ai-job-engine.tar.gz"
        echo "    Loading nexus-ui..."
        docker load -i "${IMAGES_DIR}/nexus-ui.tar.gz"
    fi

    echo "  Backend version tag:  ${BACKEND_TAG}"
    echo "  Frontend version tag: ${FRONTEND_TAG}"
    echo "  Push plan:"
    echo "    ${ECR_REGISTRY}/ai-job-engine:${BACKEND_TAG}"
    echo "    ${ECR_REGISTRY}/ai-job-engine:latest"
    echo "    ${ECR_REGISTRY}/nexus-ui:${FRONTEND_TAG}"
    echo "    ${ECR_REGISTRY}/nexus-ui:latest"

    for repo_pair in "ai-job-engine|${BACKEND_TAG}" "nexus-ui|${FRONTEND_TAG}"; do
        IFS='|' read -r repo tag <<< "$repo_pair"
        aws ecr describe-repositories --repository-names "$repo" \
            --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1 \
        || aws ecr create-repository --repository-name "$repo" \
            --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1 \
        || true
        docker_dual_tag_push "${repo}:latest" "$repo" "$tag"
    done
    echo ""
fi

# ──────────────────────────────────────────────────────────────
# BSS Magic Image
# ──────────────────────────────────────────────────────────────
if [ "$PUSH_BSSMAGIC" = true ]; then
    STEP=$((STEP+1))
    echo -e "${CYAN}── [${STEP}/${TOTAL}] BSS Magic Image ──${NC}"

    # Resolve BSS Magic version (priority: CLI override > versions.env > date-stamp)
    if [ -n "${BSSMAGIC_VERSION_OVERRIDE}" ]; then
        BSSMAGIC_TAG="${BSSMAGIC_VERSION_OVERRIDE}"
    elif [ -f "${BSSMAGIC_IMAGES_DIR}/versions.env" ]; then
        . "${BSSMAGIC_IMAGES_DIR}/versions.env"
        echo "  (read version from ${BSSMAGIC_IMAGES_DIR}/versions.env)"
    else
        BSSMAGIC_TAG="${BSSMAGIC_TAG:-$(date +%Y%m%d)-manual}"
    fi
    echo "  BSS Magic version tag: ${BSSMAGIC_TAG}"

    if [ -f "${BSSMAGIC_IMAGES_DIR}/bssmagic-nexus-k8s.tar.gz" ]; then
        echo "  Push plan:"
        echo "    ${ECR_REGISTRY}/bssmagic-nexus-k8s:${BSSMAGIC_TAG}"
        echo "    ${ECR_REGISTRY}/bssmagic-nexus-k8s:latest"
        echo "  Loading from tar: ${BSSMAGIC_IMAGES_DIR}/bssmagic-nexus-k8s.tar.gz"
        docker load -i "${BSSMAGIC_IMAGES_DIR}/bssmagic-nexus-k8s.tar.gz"

        aws ecr describe-repositories --repository-names "bssmagic-nexus-k8s" \
            --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1 \
        || aws ecr create-repository --repository-name "bssmagic-nexus-k8s" \
            --region "${REGION}" --profile "${AWS_PROFILE}" \
            --image-scanning-configuration scanOnPush=true > /dev/null 2>&1 \
        || true

        docker_dual_tag_push "bssmagic-nexus-k8s:latest" "bssmagic-nexus-k8s" "$BSSMAGIC_TAG"
    else
        echo -e "  ${YELLOW}!${NC} BSS Magic tar not found at ${BSSMAGIC_IMAGES_DIR}/bssmagic-nexus-k8s.tar.gz"
        echo "    Will use whatever image is already in ECR."
        echo "    Run ./package-images.sh --only-bssmagic to create the tar."
    fi
    echo ""
fi

# ──────────────────────────────────────────────────────────────
# nexus-sre backend + ui
# ──────────────────────────────────────────────────────────────
sre_push() {
    local repo="$1" src_dir="$2" tar_name="$3"
    STEP=$((STEP+1))
    echo -e "${CYAN}── [${STEP}/${TOTAL}] ${repo} ──${NC}"

    _ver=$(cat "${src_dir}/VERSION" 2>/dev/null | tr -d '[:space:]' || echo "0.0.0")
    _sha=$(cd "${src_dir}" 2>/dev/null && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    LIVE_TAG="${_ver}-${_sha}"
    if [ -n "${SRE_VERSION_OVERRIDE}" ]; then
        TAG="${SRE_VERSION_OVERRIDE}"
        echo "  (using --sre-version override: ${TAG})"
    else
        TAG="${LIVE_TAG}"
    fi

    HAS_TAR=false
    [ -f "${SRE_IMAGES_DIR}/${tar_name}" ] && HAS_TAR=true

    if [ "$NO_CACHE" = true ] || [ "$HAS_TAR" = false ]; then
        if [ ! -d "${src_dir}" ]; then
            echo -e "${RED}  Source directory not available: ${src_dir}${NC}"
            return 1
        fi
        echo "  Building from source: ${src_dir}"
        docker build --no-cache -t "${repo}:latest" "${src_dir}"
    else
        echo "  Loading from tar: ${SRE_IMAGES_DIR}/${tar_name}"
        docker load -i "${SRE_IMAGES_DIR}/${tar_name}"
    fi

    echo "  Version tag: ${TAG}"
    echo "  Push plan:"
    echo "    ${ECR_REGISTRY}/${repo}:${TAG}"
    echo "    ${ECR_REGISTRY}/${repo}:latest"

    aws ecr describe-repositories --repository-names "$repo" \
        --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1 \
    || aws ecr create-repository --repository-name "$repo" \
        --region "${REGION}" --profile "${AWS_PROFILE}" \
        --image-scanning-configuration scanOnPush=true > /dev/null 2>&1 \
    || true

    docker_dual_tag_push "${repo}:latest" "$repo" "$TAG"
    echo ""
}

if [ "$PUSH_SRE_BACKEND" = true ]; then
    sre_push "nexus-sre-backend" "${SRE_BACKEND_DIR}" "nexus-sre-backend.tar.gz"
fi

if [ "$PUSH_SRE_UI" = true ]; then
    sre_push "nexus-sre-ui" "${SRE_FRONTEND_DIR}" "nexus-sre-ui.tar.gz"
fi

if [ "$PUSH_SRE_POSTGRES" = true ]; then
    sre_push "nexus-sre-postgres" "${SRE_POSTGRES_DIR}" "nexus-sre-postgres.tar.gz"
fi

# ──────────────────────────────────────────────────────────────
# nexus-ai-engine API (+ UI from S11)
# ──────────────────────────────────────────────────────────────
ai_engine_push() {
    local repo="$1" src_dir="$2" tar_name="$3" version_file="$4"
    STEP=$((STEP+1))
    echo -e "${CYAN}── [${STEP}/${TOTAL}] ${repo} ──${NC}"

    _ver=$(cat "${version_file}" 2>/dev/null | tr -d '[:space:]' || echo "0.0.0")
    _sha=$(cd "${AI_ENGINE_DIR}" 2>/dev/null && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    LIVE_TAG="${_ver}-${_sha}"
    if [ -n "${AI_ENGINE_VERSION_OVERRIDE}" ]; then
        TAG="${AI_ENGINE_VERSION_OVERRIDE}"
        echo "  (using --ai-engine-version override: ${TAG})"
    else
        TAG="${LIVE_TAG}"
    fi

    HAS_TAR=false
    [ -f "${AI_ENGINE_IMAGES_DIR}/${tar_name}" ] && HAS_TAR=true

    if [ "$NO_CACHE" = true ] || [ "$HAS_TAR" = false ]; then
        if [ ! -d "${src_dir}" ]; then
            echo -e "${RED}  Source directory not available: ${src_dir}${NC}"
            return 1
        fi
        echo "  Building from source: ${src_dir}"
        docker build --no-cache -t "${repo}:latest" "${src_dir}"
    else
        echo "  Loading from tar: ${AI_ENGINE_IMAGES_DIR}/${tar_name}"
        docker load -i "${AI_ENGINE_IMAGES_DIR}/${tar_name}"
    fi

    echo "  Version tag: ${TAG}"
    echo "  Push plan:"
    echo "    ${ECR_REGISTRY}/${repo}:${TAG}"
    echo "    ${ECR_REGISTRY}/${repo}:latest"

    aws ecr describe-repositories --repository-names "$repo" \
        --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1 \
    || aws ecr create-repository --repository-name "$repo" \
        --region "${REGION}" --profile "${AWS_PROFILE}" \
        --image-scanning-configuration scanOnPush=true > /dev/null 2>&1 \
    || true

    docker_dual_tag_push "${repo}:latest" "$repo" "$TAG"
    echo ""
}

if [ "$PUSH_AI_ENGINE_API" = true ]; then
    ai_engine_push "nexus-ai-engine-api" "${AI_ENGINE_DIR}" "nexus-ai-engine-api.tar.gz" "${AI_ENGINE_DIR}/backend/VERSION"
fi

if [ "$PUSH_AI_ENGINE_UI" = true ]; then
    ai_engine_push "nexus-ai-engine-ui" "${AI_ENGINE_DIR}/frontend" "nexus-ai-engine-ui.tar.gz" "${AI_ENGINE_DIR}/frontend/VERSION"
fi

# ──────────────────────────────────────────────────────────────
# nexus-ontology API + UI
# ──────────────────────────────────────────────────────────────
ontology_push() {
    local repo="$1" src_dir="$2" tar_name="$3" version_file="$4"
    STEP=$((STEP+1))
    echo -e "${CYAN}── [${STEP}/${TOTAL}] ${repo} ──${NC}"

    _ver=$(cat "${version_file}" 2>/dev/null | tr -d '[:space:]' || echo "0.0.0")
    _sha=$(cd "${ONTOLOGY_DIR}" 2>/dev/null && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    LIVE_TAG="${_ver}-${_sha}"
    if [ -n "${ONTOLOGY_VERSION_OVERRIDE}" ]; then
        TAG="${ONTOLOGY_VERSION_OVERRIDE}"
        echo "  (using --ontology-version override: ${TAG})"
    else
        TAG="${LIVE_TAG}"
    fi

    HAS_TAR=false
    [ -f "${ONTOLOGY_IMAGES_DIR}/${tar_name}" ] && HAS_TAR=true

    if [ "$NO_CACHE" = true ] || [ "$HAS_TAR" = false ]; then
        if [ ! -d "${src_dir}" ]; then
            echo -e "${RED}  Source directory not available: ${src_dir}${NC}"
            return 1
        fi
        echo "  Building from source: ${src_dir}"
        docker build --no-cache -t "${repo}:latest" "${src_dir}"
    else
        echo "  Loading from tar: ${ONTOLOGY_IMAGES_DIR}/${tar_name}"
        docker load -i "${ONTOLOGY_IMAGES_DIR}/${tar_name}"
    fi

    echo "  Version tag: ${TAG}"
    echo "  Push plan:"
    echo "    ${ECR_REGISTRY}/${repo}:${TAG}"
    echo "    ${ECR_REGISTRY}/${repo}:latest"

    aws ecr describe-repositories --repository-names "$repo" \
        --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1 \
    || aws ecr create-repository --repository-name "$repo" \
        --region "${REGION}" --profile "${AWS_PROFILE}" \
        --image-scanning-configuration scanOnPush=true > /dev/null 2>&1 \
    || true

    docker_dual_tag_push "${repo}:latest" "$repo" "$TAG"
    echo ""
}

if [ "$PUSH_ONTOLOGY_API" = true ]; then
    ontology_push "nexus-ontology-api" "${ONTOLOGY_DIR}/backend" "nexus-ontology-api.tar.gz" "${ONTOLOGY_DIR}/backend/VERSION"
fi

if [ "$PUSH_ONTOLOGY_UI" = true ]; then
    ontology_push "nexus-ontology-ui" "${ONTOLOGY_DIR}/frontend" "nexus-ontology-ui.tar.gz" "${ONTOLOGY_DIR}/frontend/VERSION"
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
    exit 1
fi

echo "  You can now deploy with:"
echo "    ./e2e-deploy.sh"
echo ""

#!/bin/bash
#
# Create ECR Images
# Builds/loads and pushes operator, Nexus (backend + frontend), and BSS Magic
# Docker images to ECR. Run this before e2e-deploy.sh.
# Reads defaults from .env.local.
#
# Usage:
#   ./create-ecr-images.sh                       # Push all images to ECR
#   ./create-ecr-images.sh --skip-operator       # Skip operator image
#   ./create-ecr-images.sh --skip-app-images     # Skip Nexus images
#   ./create-ecr-images.sh --skip-bssmagic       # Skip BSS Magic image
#   ./create-ecr-images.sh --only-operator       # Only push operator image
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
BACKEND_DIR="/opt/mycode/nexus/nexus-backend"
FRONTEND_DIR="/opt/mycode/nexus/nexus-ui"

_ENVLOCAL="${SCRIPT_DIR}/.env.local"
if [ -f "$_ENVLOCAL" ]; then
    _ENV_LOCAL_ENV=$(grep '^ENV=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- || true)
    _ENV_LOCAL_CLUSTER=$(grep '^Cluster=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- || true)
fi

DEPLOY_ENV="${DEPLOY_ENV:-${_ENV_LOCAL_ENV:-prod}}"
CLUSTER_NAME="${CLUSTER_NAME:-${_ENV_LOCAL_CLUSTER:-nexus-dev}}"
REGION="${REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-ptr-tech}"

PUSH_OPERATOR=true
PUSH_APP=true
PUSH_BSSMAGIC=true
ONLY_MODE=""
NO_CACHE=false

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-operator)    PUSH_OPERATOR=false; shift ;;
        --skip-app-images)  PUSH_APP=false; shift ;;
        --skip-bssmagic)    PUSH_BSSMAGIC=false; shift ;;
        --only-operator)    ONLY_MODE="operator"; shift ;;
        --only-app-images)  ONLY_MODE="app"; shift ;;
        --only-bssmagic)    ONLY_MODE="bssmagic"; shift ;;
        --no-cache)         NO_CACHE=true; shift ;;
        --env)              DEPLOY_ENV="$2"; shift 2 ;;
        --help|-h)
            echo "Create ECR Images"
            echo ""
            echo "Builds/loads and pushes all Docker images to ECR."
            echo "Run this before e2e-deploy.sh."
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

# ──────────────────────────────────────────────────────────────
# Operator Image
# ──────────────────────────────────────────────────────────────
if [ "$PUSH_OPERATOR" = true ]; then
    STEP=$((STEP+1))
    echo -e "${CYAN}── [${STEP}/${TOTAL}] Operator Image ──${NC}"

    HAS_OPERATOR_TAR=false
    [ -f "${OPERATOR_IMAGES_DIR}/totogi-operator.tar.gz" ] && HAS_OPERATOR_TAR=true

    if [ "$NO_CACHE" = true ] || [ "$HAS_OPERATOR_TAR" = false ]; then
        echo "  Building from source: ${SCRIPT_DIR}/Dockerfile"
        docker build --no-cache -t totogi-operator:latest "${SCRIPT_DIR}"
    else
        echo "  Loading from tar: ${OPERATOR_IMAGES_DIR}/totogi-operator.tar.gz"
        docker load -i "${OPERATOR_IMAGES_DIR}/totogi-operator.tar.gz"
    fi

    aws ecr describe-repositories --repository-names "totogi-operator" \
        --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1 \
    || aws ecr create-repository --repository-name "totogi-operator" \
        --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1 \
    || true

    docker tag totogi-operator:latest "${ECR_REGISTRY}/totogi-operator:latest"
    docker push "${ECR_REGISTRY}/totogi-operator:latest"
    echo -e "  ${GREEN}✓${NC} Operator image pushed"
    echo ""
fi

# ──────────────────────────────────────────────────────────────
# Nexus Images (backend + frontend)
# ──────────────────────────────────────────────────────────────
if [ "$PUSH_APP" = true ]; then
    STEP=$((STEP+1))
    echo -e "${CYAN}── [${STEP}/${TOTAL}] Nexus Images (backend + frontend) ──${NC}"

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

    for repo in ai-job-engine nexus-ui; do
        aws ecr describe-repositories --repository-names "$repo" \
            --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1 \
        || aws ecr create-repository --repository-name "$repo" \
            --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1 \
        || true
        docker tag "${repo}:latest" "${ECR_REGISTRY}/${repo}:latest"
        docker push "${ECR_REGISTRY}/${repo}:latest"
        echo -e "  ${GREEN}✓${NC} ${repo} pushed"
    done
    echo ""
fi

# ──────────────────────────────────────────────────────────────
# BSS Magic Image
# ──────────────────────────────────────────────────────────────
if [ "$PUSH_BSSMAGIC" = true ]; then
    STEP=$((STEP+1))
    echo -e "${CYAN}── [${STEP}/${TOTAL}] BSS Magic Image ──${NC}"

    if [ -f "${BSSMAGIC_IMAGES_DIR}/bssmagic-nexus-k8s.tar.gz" ]; then
        echo "  Loading from tar: ${BSSMAGIC_IMAGES_DIR}/bssmagic-nexus-k8s.tar.gz"
        docker load -i "${BSSMAGIC_IMAGES_DIR}/bssmagic-nexus-k8s.tar.gz"

        aws ecr describe-repositories --repository-names "bssmagic-nexus-k8s" \
            --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1 \
        || aws ecr create-repository --repository-name "bssmagic-nexus-k8s" \
            --region "${REGION}" --profile "${AWS_PROFILE}" \
            --image-scanning-configuration scanOnPush=true > /dev/null 2>&1 \
        || true

        docker tag "bssmagic-nexus-k8s:latest" "${ECR_REGISTRY}/bssmagic-nexus-k8s:latest"
        docker push "${ECR_REGISTRY}/bssmagic-nexus-k8s:latest"
        echo -e "  ${GREEN}✓${NC} BSS Magic image pushed"
    else
        echo -e "  ${YELLOW}!${NC} BSS Magic tar not found at ${BSSMAGIC_IMAGES_DIR}/bssmagic-nexus-k8s.tar.gz"
        echo "    Will use whatever image is already in ECR."
        echo "    Run ./package-images.sh --only-bssmagic to create the tar."
    fi
    echo ""
fi

# ──────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ECR Images Ready${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
echo ""
echo "  Registry: ${ECR_REGISTRY}"
echo ""
echo "  You can now deploy with:"
echo "    ./e2e-deploy.sh"
echo ""

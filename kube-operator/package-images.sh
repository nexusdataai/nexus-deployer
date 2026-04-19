#!/bin/bash
#
# Package CallSense + BSS Magic + Operator Images
# Builds frontend, backend, BSS Magic, and operator Docker images locally from source
# and saves them as compressed tar files for offline delivery.
# Reads defaults from .env.local (ENV, Branch, Cluster). CLI args override.
#
# CallSense images:   No AWS credentials required (public base images).
# BSS Magic image:    Requires access to CloudSense base image ECR
#                     (008731404932.dkr.ecr.us-east-1.amazonaws.com).
#
# Usage:
#   ./package-images.sh
#   ./package-images.sh --backend-dir /path/to/backend --frontend-dir /path/to/frontend
#   ./package-images.sh --skip-bssmagic        # Only package CallSense + operator images
#   ./package-images.sh --only-bssmagic        # Only package BSS Magic image
#   ./package-images.sh --only-operator        # Only package operator image
#   ./package-images.sh --skip-operator        # Skip operator image
#
# Output:
#   images/callsense/ai-job-engine.tar.gz
#   images/callsense/starhub-ui.tar.gz
#   images/callsense/checksums.sha256
#   images/bssmagic/bssmagic-starhub-k8s.tar.gz
#   images/bssmagic/checksums.sha256
#   images/operator/totogi-operator.tar.gz
#   images/operator/checksums.sha256
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load defaults from .env.local (CLI args and env vars override these)
_ENVLOCAL="${SCRIPT_DIR}/.env.local"
if [ -f "$_ENVLOCAL" ]; then
    _ENV_LOCAL_ENV=$(grep '^ENV=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2-)
    _ENV_LOCAL_BRANCH=$(grep '^Branch=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2-)
    _ENV_LOCAL_CLUSTER=$(grep '^Cluster=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2-)
fi

DEPLOY_ENV="${DEPLOY_ENV:-${_ENV_LOCAL_ENV:-prod}}"
GIT_BRANCH="${GIT_BRANCH:-${_ENV_LOCAL_BRANCH:-}}"
CLUSTER_NAME="${CLUSTER_NAME:-${_ENV_LOCAL_CLUSTER:-}}"

CALLSENSE_OUTPUT="${SCRIPT_DIR}/images/callsense"
BSSMAGIC_OUTPUT="${SCRIPT_DIR}/images/bssmagic"
OPERATOR_OUTPUT="${SCRIPT_DIR}/images/operator"

BACKEND_IMAGE="ai-job-engine:latest"
FRONTEND_IMAGE="starhub-ui:latest"
BSSMAGIC_IMAGE="bssmagic-starhub-k8s:latest"
OPERATOR_IMAGE="totogi-operator:latest"

SKIP_BSSMAGIC=false
ONLY_BSSMAGIC=false
SKIP_OPERATOR=false
ONLY_OPERATOR=false

# Parse arguments (before resolving dirs, so --only-bssmagic can skip missing dirs)
while [[ $# -gt 0 ]]; do
    case $1 in
        --backend-dir)   BACKEND_DIR="$2"; shift 2 ;;
        --frontend-dir)  FRONTEND_DIR="$2"; shift 2 ;;
        --bssmagic-dir)  BSSMAGIC_DIR="$2"; shift 2 ;;
        --skip-bssmagic) SKIP_BSSMAGIC=true; shift ;;
        --only-bssmagic) ONLY_BSSMAGIC=true; shift ;;
        --skip-operator) SKIP_OPERATOR=true; shift ;;
        --only-operator) ONLY_OPERATOR=true; shift ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Builds all images locally and saves as tar.gz for offline delivery."
            echo ""
            echo "Options:"
            echo "  --backend-dir DIR    Path to starhub-backend source (default: ../../starhub-backend)"
            echo "  --frontend-dir DIR   Path to starhub-ui source (default: ../../starhub-ui)"
            echo "  --bssmagic-dir DIR   Path to bssmagic-image build context (default: ../bssmagic-image)"
            echo "  --skip-bssmagic      Skip BSS Magic image (only package CallSense)"
            echo "  --only-bssmagic      Only package BSS Magic image (skip CallSense)"
            echo "  --skip-operator      Skip operator image"
            echo "  --only-operator      Only package operator image"
            echo "  --help               Show this help"
            echo ""
            echo "Notes:"
            echo "  CallSense images require starhub-backend + starhub-ui source repos."
            echo "  BSS Magic image requires access to CloudSense base image ECR."
            echo "  Operator image is built from kube-operator/Dockerfile."
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ──────────────────────────────────────────────────────────────
# Resolve source directories (deferred until after arg parsing
# so --only-bssmagic doesn't fail when starhub-backend/ui missing)
# ──────────────────────────────────────────────────────────────
if [ "$ONLY_BSSMAGIC" = false ] && [ "$ONLY_OPERATOR" = false ]; then
    BACKEND_DIR="${BACKEND_DIR:-$(cd "$SCRIPT_DIR/../../starhub-backend" 2>/dev/null && pwd || echo "")}"
    FRONTEND_DIR="${FRONTEND_DIR:-$(cd "$SCRIPT_DIR/../../starhub-ui" 2>/dev/null && pwd || echo "")}"
fi
BSSMAGIC_DIR="${BSSMAGIC_DIR:-$(cd "$SCRIPT_DIR/../bssmagic-image" 2>/dev/null && pwd || echo "")}"

# ──────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────
if [ "$ONLY_BSSMAGIC" = false ] && [ "$ONLY_OPERATOR" = false ]; then
    if [ ! -f "${BACKEND_DIR}/Dockerfile" ]; then
        echo "ERROR: Backend Dockerfile not found at ${BACKEND_DIR}/Dockerfile"
        echo "  Use --backend-dir to specify the starhub-backend directory"
        echo "  Or use --only-bssmagic to skip CallSense images"
        exit 1
    fi
    if [ ! -f "${FRONTEND_DIR}/Dockerfile" ]; then
        echo "ERROR: Frontend Dockerfile not found at ${FRONTEND_DIR}/Dockerfile"
        echo "  Use --frontend-dir to specify the starhub-ui directory"
        echo "  Or use --only-bssmagic to skip CallSense images"
        exit 1
    fi
fi

if [ "$SKIP_BSSMAGIC" = false ]; then
    if [ ! -f "${BSSMAGIC_DIR}/Dockerfile" ]; then
        echo "ERROR: BSS Magic Dockerfile not found at ${BSSMAGIC_DIR}/Dockerfile"
        echo "  Use --bssmagic-dir to specify the bssmagic-image directory"
        echo "  Or use --skip-bssmagic to skip BSS Magic image"
        exit 1
    fi
fi

# Calculate total steps
TOTAL_STEPS=0
PACKAGE_CALLSENSE=false
PACKAGE_BSSMAGIC=false
PACKAGE_OPERATOR=false

if [ "$ONLY_BSSMAGIC" = true ]; then
    PACKAGE_BSSMAGIC=true
elif [ "$ONLY_OPERATOR" = true ]; then
    PACKAGE_OPERATOR=true
else
    PACKAGE_CALLSENSE=true
    [ "$SKIP_BSSMAGIC" = false ] && PACKAGE_BSSMAGIC=true
    [ "$SKIP_OPERATOR" = false ] && PACKAGE_OPERATOR=true
fi

[ "$PACKAGE_CALLSENSE" = true ] && TOTAL_STEPS=$((TOTAL_STEPS + 4))
[ "$PACKAGE_BSSMAGIC" = true ] && TOTAL_STEPS=$((TOTAL_STEPS + 3))
[ "$PACKAGE_OPERATOR" = true ] && TOTAL_STEPS=$((TOTAL_STEPS + 3))
CURRENT_STEP=0

echo "=============================================="
echo "  Package Images"
echo "=============================================="
echo ""
if [ "$PACKAGE_CALLSENSE" = true ]; then
    echo "  Backend source:   ${BACKEND_DIR}"
    echo "  Frontend source:  ${FRONTEND_DIR}"
    echo "  CallSense output: ${CALLSENSE_OUTPUT}"
fi
if [ "$PACKAGE_BSSMAGIC" = true ]; then
    echo "  BSS Magic source: ${BSSMAGIC_DIR}"
    echo "  BSS Magic output: ${BSSMAGIC_OUTPUT}"
fi
if [ "$PACKAGE_OPERATOR" = true ]; then
    echo "  Operator source:  ${SCRIPT_DIR}"
    echo "  Operator output:  ${OPERATOR_OUTPUT}"
fi
echo ""

# ──────────────────────────────────────────────────────────────
# CallSense Images (frontend + backend)
# ──────────────────────────────────────────────────────────────
if [ "$PACKAGE_CALLSENSE" = true ]; then
    mkdir -p "${CALLSENSE_OUTPUT}"

    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Building backend image: ${BACKEND_IMAGE} ==="
    docker build -t "${BACKEND_IMAGE}" "${BACKEND_DIR}"
    echo "  Done."
    echo ""

    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Building frontend image: ${FRONTEND_IMAGE} ==="
    docker build -t "${FRONTEND_IMAGE}" "${FRONTEND_DIR}"
    echo "  Done."
    echo ""

    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Saving CallSense images as tar.gz ==="
    echo "  Saving ${BACKEND_IMAGE}..."
    docker save "${BACKEND_IMAGE}" | gzip > "${CALLSENSE_OUTPUT}/ai-job-engine.tar.gz"
    echo "  Saving ${FRONTEND_IMAGE}..."
    docker save "${FRONTEND_IMAGE}" | gzip > "${CALLSENSE_OUTPUT}/starhub-ui.tar.gz"
    echo "  Done."
    echo ""

    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Generating CallSense checksums ==="
    cd "${CALLSENSE_OUTPUT}"
    sha256sum ai-job-engine.tar.gz starhub-ui.tar.gz > checksums.sha256
    cd "${SCRIPT_DIR}"
    echo "  Done."
    echo ""
fi

# ──────────────────────────────────────────────────────────────
# BSS Magic Image
# ──────────────────────────────────────────────────────────────
if [ "$PACKAGE_BSSMAGIC" = true ]; then
    mkdir -p "${BSSMAGIC_OUTPUT}"

    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Building BSS Magic image: ${BSSMAGIC_IMAGE} ==="
    echo ""
    echo "  NOTE: This requires access to CloudSense base image ECR."
    echo "  If the build fails with 'pull access denied', log in first:"
    echo "    aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 008731404932.dkr.ecr.us-east-1.amazonaws.com"
    echo ""
    docker build -t "${BSSMAGIC_IMAGE}" "${BSSMAGIC_DIR}"
    echo "  Done."
    echo ""

    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Saving BSS Magic image as tar.gz ==="
    echo "  Saving ${BSSMAGIC_IMAGE}..."
    docker save "${BSSMAGIC_IMAGE}" | gzip > "${BSSMAGIC_OUTPUT}/bssmagic-starhub-k8s.tar.gz"
    echo "  Done."
    echo ""

    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Generating BSS Magic checksums ==="
    cd "${BSSMAGIC_OUTPUT}"
    sha256sum bssmagic-starhub-k8s.tar.gz > checksums.sha256
    cd "${SCRIPT_DIR}"
    echo "  Done."
    echo ""
fi

# ──────────────────────────────────────────────────────────────
# Operator Image
# ──────────────────────────────────────────────────────────────
if [ "$PACKAGE_OPERATOR" = true ]; then
    mkdir -p "${OPERATOR_OUTPUT}"

    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Building operator image: ${OPERATOR_IMAGE} ==="
    docker build -t "${OPERATOR_IMAGE}" "${SCRIPT_DIR}"
    echo "  Done."
    echo ""

    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Saving operator image as tar.gz ==="
    echo "  Saving ${OPERATOR_IMAGE}..."
    docker save "${OPERATOR_IMAGE}" | gzip > "${OPERATOR_OUTPUT}/totogi-operator.tar.gz"
    echo "  Done."
    echo ""

    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Generating operator checksums ==="
    cd "${OPERATOR_OUTPUT}"
    sha256sum totogi-operator.tar.gz > checksums.sha256
    cd "${SCRIPT_DIR}"
    echo "  Done."
    echo ""
fi

# ──────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────
echo "=============================================="
echo "  Package Complete"
echo "=============================================="
echo ""
echo "  Files:"
if [ "$PACKAGE_CALLSENSE" = true ] && [ -d "${CALLSENSE_OUTPUT}" ]; then
    ls -lh "${CALLSENSE_OUTPUT}/"*.tar.gz 2>/dev/null | awk '{print "    " $5 "  " $NF}'
fi
if [ "$PACKAGE_BSSMAGIC" = true ] && [ -d "${BSSMAGIC_OUTPUT}" ]; then
    ls -lh "${BSSMAGIC_OUTPUT}/"*.tar.gz 2>/dev/null | awk '{print "    " $5 "  " $NF}'
fi
if [ "$PACKAGE_OPERATOR" = true ] && [ -d "${OPERATOR_OUTPUT}" ]; then
    ls -lh "${OPERATOR_OUTPUT}/"*.tar.gz 2>/dev/null | awk '{print "    " $5 "  " $NF}'
fi
echo ""
echo "  These files can now be shipped with kube-operator/"
echo "  and deployed to any AWS account via e2e-deploy.sh"
echo ""

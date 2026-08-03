#!/bin/bash
#
# Package Nexus + BSS Magic + Operator Images
# Builds frontend, backend, BSS Magic, and operator Docker images locally from source
# and saves them as compressed tar files for offline delivery.
# Reads defaults from .env.local (ENV, Branch, Cluster). CLI args override.
#
# Nexus images:      No AWS credentials required (public base images).
# BSS Magic image:   Requires access to CloudSense base image ECR
#                    (654654554404.dkr.ecr.us-east-1.amazonaws.com).
#
# Usage:
#   ./package-images.sh
#   ./package-images.sh --backend-dir /path/to/backend --frontend-dir /path/to/frontend
#   ./package-images.sh --skip-bssmagic        # Only package Nexus + operator images
#   ./package-images.sh --only-bssmagic        # Only package BSS Magic image
#   ./package-images.sh --only-operator        # Only package operator image
#   ./package-images.sh --skip-operator        # Skip operator image
#
# Output:
#   images/nexus/ai-job-engine.tar.gz
#   images/nexus/nexus-ui.tar.gz
#   images/nexus/checksums.sha256
#   images/bssmagic/bssmagic-nexus-k8s.tar.gz
#   images/bssmagic/checksums.sha256
#   images/operator/nexus-operator.tar.gz
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

NEXUS_OUTPUT="${SCRIPT_DIR}/images/nexus"
BSSMAGIC_OUTPUT="${SCRIPT_DIR}/images/bssmagic"
OPERATOR_OUTPUT="${SCRIPT_DIR}/images/operator"
SRE_OUTPUT="${SCRIPT_DIR}/images/nexus-sre"
AI_ENGINE_OUTPUT="${SCRIPT_DIR}/images/nexus-ai-engine"

BACKEND_IMAGE="ai-job-engine:latest"
FRONTEND_IMAGE="nexus-ui:latest"
BSSMAGIC_IMAGE="bssmagic-nexus-k8s:latest"
OPERATOR_IMAGE="nexus-operator:latest"
SRE_BACKEND_IMAGE="nexus-sre-backend:latest"
SRE_UI_IMAGE="nexus-sre-ui:latest"
SRE_POSTGRES_IMAGE="nexus-sre-postgres:latest"
AI_ENGINE_API_IMAGE="nexus-ai-engine-api:latest"
AI_ENGINE_UI_IMAGE="nexus-ai-engine-ui:latest"

SKIP_BSSMAGIC=false
ONLY_BSSMAGIC=false
SKIP_OPERATOR=false
ONLY_OPERATOR=false
SKIP_SRE_BACKEND=false
ONLY_SRE_BACKEND=false
SKIP_SRE_UI=false
ONLY_SRE_UI=false
SKIP_SRE_POSTGRES=false
ONLY_SRE_POSTGRES=false
ONLY_SRE=false
SKIP_SRE=true    # default: legacy invocations do not touch SRE images
SKIP_AI_ENGINE=true
SKIP_AI_ENGINE_API=false
ONLY_AI_ENGINE=false
ONLY_AI_ENGINE_API=false
ONLY_AI_ENGINE_UI=false

# Parse arguments (before resolving dirs, so --only-bssmagic can skip missing dirs)
while [[ $# -gt 0 ]]; do
    case $1 in
        --backend-dir)        BACKEND_DIR="$2"; shift 2 ;;
        --frontend-dir)       FRONTEND_DIR="$2"; shift 2 ;;
        --bssmagic-dir)       BSSMAGIC_DIR="$2"; shift 2 ;;
        --sre-backend-dir)    SRE_BACKEND_DIR="$2"; shift 2 ;;
        --sre-frontend-dir)   SRE_FRONTEND_DIR="$2"; shift 2 ;;
        --sre-postgres-dir)   SRE_POSTGRES_DIR="$2"; shift 2 ;;
        --ai-engine-dir)      AI_ENGINE_DIR="$2"; shift 2 ;;
        --skip-bssmagic)      SKIP_BSSMAGIC=true; shift ;;
        --only-bssmagic)      ONLY_BSSMAGIC=true; shift ;;
        --skip-operator)      SKIP_OPERATOR=true; shift ;;
        --only-operator)      ONLY_OPERATOR=true; shift ;;
        --only-sre-backend)   ONLY_SRE_BACKEND=true; SKIP_SRE=false; shift ;;
        --only-sre-ui)        ONLY_SRE_UI=true; SKIP_SRE=false; shift ;;
        --only-sre-postgres)  ONLY_SRE_POSTGRES=true; SKIP_SRE=false; shift ;;
        --only-sre-images)    ONLY_SRE=true; SKIP_SRE=false; shift ;;
        --skip-sre-backend)   SKIP_SRE_BACKEND=true; shift ;;
        --skip-sre-ui)        SKIP_SRE_UI=true; shift ;;
        --skip-sre-postgres)  SKIP_SRE_POSTGRES=true; shift ;;
        --with-sre-images)    SKIP_SRE=false; shift ;;
        --only-ai-engine-api) ONLY_AI_ENGINE_API=true; SKIP_AI_ENGINE=false; shift ;;
        --only-ai-engine-ui)  ONLY_AI_ENGINE_UI=true; SKIP_AI_ENGINE=false; shift ;;
        --only-ai-engine-images) ONLY_AI_ENGINE=true; SKIP_AI_ENGINE=false; shift ;;
        --with-ai-engine-images) SKIP_AI_ENGINE=false; shift ;;
        --skip-ai-engine-api) SKIP_AI_ENGINE_API=true; shift ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Builds all images locally and saves as tar.gz for offline delivery."
            echo ""
            echo "Options:"
            echo "  --backend-dir DIR    Path to nexus-backend source (default: ../../nexus-backend)"
            echo "  --frontend-dir DIR   Path to nexus-ui source (default: ../../nexus-ui)"
            echo "  --bssmagic-dir DIR   Path to bssmagic-image build context (default: ../bssmagic-image)"
            echo "  --skip-bssmagic      Skip BSS Magic image (only package Nexus)"
            echo "  --only-bssmagic      Only package BSS Magic image (skip Nexus)"
            echo "  --skip-operator      Skip operator image"
            echo "  --only-operator      Only package operator image"
            echo ""
            echo "  --with-sre-images    Also package nexus-sre backend + ui + postgres images"
            echo "  --only-sre-images    Only package nexus-sre images (skip Nexus/BSS/operator)"
            echo "  --only-sre-backend   Only package nexus-sre backend image"
            echo "  --only-sre-ui        Only package nexus-sre ui image"
            echo "  --only-sre-postgres  Only package nexus-sre postgres (pgvector+AGE) image"
            echo "  --skip-sre-backend   Skip nexus-sre backend image"
            echo "  --skip-sre-ui        Skip nexus-sre ui image"
            echo "  --skip-sre-postgres  Skip nexus-sre postgres image"
            echo "  --sre-backend-dir DIR   Path to nexus-sre backend (default: ../../nexus-sre/backend)"
            echo "  --sre-frontend-dir DIR  Path to nexus-sre frontend (default: ../../nexus-sre/frontend)"
            echo "  --sre-postgres-dir DIR  Path to nexus-sre postgres-image (default: ../../nexus-sre/postgres-image)"
            echo ""
            echo "  --with-ai-engine-images    Also package nexus-ai-engine API image"
            echo "  --only-ai-engine-images    Only package nexus-ai-engine images (skip Nexus/BSS/operator)"
            echo "  --only-ai-engine-api       Only package nexus-ai-engine API image"
            echo "  --only-ai-engine-ui        Only package nexus-ai-engine UI image (S11+)"
            echo "  --skip-ai-engine-api       Skip nexus-ai-engine API when bundling"
            echo "  --ai-engine-dir DIR        Path to nexus-ai-engine repo root (default: ../../nexus-ai-engine)"
            echo "  --help               Show this help"
            echo ""
            echo "Notes:"
            echo "  Nexus images require nexus-backend + nexus-ui source repos."
            echo "  BSS Magic image requires access to CloudSense base image ECR."
            echo "  Operator image is built from kube-operator/Dockerfile."
            echo "  SRE postgres image builds Apache AGE (same pattern as bssmagic-image)."
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ──────────────────────────────────────────────────────────────
# Resolve source directories (deferred until after arg parsing
# so --only-bssmagic doesn't fail when nexus-backend/ui missing)
# ──────────────────────────────────────────────────────────────
SRE_MODE=false
AI_ENGINE_MODE=false
if [ "$ONLY_SRE" = true ] || [ "$ONLY_SRE_BACKEND" = true ] || [ "$ONLY_SRE_UI" = true ] || [ "$ONLY_SRE_POSTGRES" = true ]; then
    SRE_MODE=true
fi
if [ "$ONLY_AI_ENGINE" = true ] || [ "$ONLY_AI_ENGINE_API" = true ] || [ "$ONLY_AI_ENGINE_UI" = true ]; then
    AI_ENGINE_MODE=true
fi

if [ "$SRE_MODE" = false ] && [ "$AI_ENGINE_MODE" = false ] && [ "$ONLY_BSSMAGIC" = false ] && [ "$ONLY_OPERATOR" = false ]; then
    BACKEND_DIR="${BACKEND_DIR:-$(cd "$SCRIPT_DIR/../../nexus-backend" 2>/dev/null && pwd || echo "")}"
    FRONTEND_DIR="${FRONTEND_DIR:-$(cd "$SCRIPT_DIR/../../nexus-ui" 2>/dev/null && pwd || echo "")}"
fi
BSSMAGIC_DIR="${BSSMAGIC_DIR:-$(cd "$SCRIPT_DIR/../bssmagic-image" 2>/dev/null && pwd || echo "")}"
SRE_BACKEND_DIR="${SRE_BACKEND_DIR:-$(cd "$SCRIPT_DIR/../../nexus-sre/backend" 2>/dev/null && pwd || echo "")}"
SRE_FRONTEND_DIR="${SRE_FRONTEND_DIR:-$(cd "$SCRIPT_DIR/../../nexus-sre/frontend" 2>/dev/null && pwd || echo "")}"
SRE_POSTGRES_DIR="${SRE_POSTGRES_DIR:-$(cd "$SCRIPT_DIR/../../nexus-sre/postgres-image" 2>/dev/null && pwd || echo "")}"
AI_ENGINE_DIR="${AI_ENGINE_DIR:-$(cd "$SCRIPT_DIR/../../nexus-ai-engine" 2>/dev/null && pwd || echo "")}"

# ──────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────
if [ "$SRE_MODE" = false ] && [ "$AI_ENGINE_MODE" = false ] && [ "$ONLY_BSSMAGIC" = false ] && [ "$ONLY_OPERATOR" = false ]; then
    if [ ! -f "${BACKEND_DIR}/Dockerfile" ]; then
        echo "ERROR: Backend Dockerfile not found at ${BACKEND_DIR}/Dockerfile"
        echo "  Use --backend-dir to specify the nexus-backend directory"
        echo "  Or use --only-bssmagic to skip Nexus images"
        exit 1
    fi
    if [ ! -f "${FRONTEND_DIR}/Dockerfile" ]; then
        echo "ERROR: Frontend Dockerfile not found at ${FRONTEND_DIR}/Dockerfile"
        echo "  Use --frontend-dir to specify the nexus-ui directory"
        echo "  Or use --only-bssmagic to skip Nexus images"
        exit 1
    fi
fi

# Validate SRE dirs only if we intend to package them
if [ "$SRE_MODE" = true ] || [ "$SKIP_SRE" = false ]; then
    if [ "$SKIP_SRE_BACKEND" != true ] && [ "$ONLY_SRE_UI" != true ] && [ "$ONLY_SRE_POSTGRES" != true ] && [ ! -f "${SRE_BACKEND_DIR}/Dockerfile" ]; then
        echo "ERROR: nexus-sre backend Dockerfile not found at ${SRE_BACKEND_DIR}/Dockerfile"
        echo "  Use --sre-backend-dir to specify the nexus-sre backend directory"
        exit 1
    fi
    if [ "$SKIP_SRE_UI" != true ] && [ "$ONLY_SRE_BACKEND" != true ] && [ "$ONLY_SRE_POSTGRES" != true ] && [ ! -f "${SRE_FRONTEND_DIR}/Dockerfile" ]; then
        echo "ERROR: nexus-sre ui Dockerfile not found at ${SRE_FRONTEND_DIR}/Dockerfile"
        echo "  Use --sre-frontend-dir to specify the nexus-sre frontend directory"
        exit 1
    fi
    if [ "$SKIP_SRE_POSTGRES" != true ] && [ "$ONLY_SRE_BACKEND" != true ] && [ "$ONLY_SRE_UI" != true ] && [ ! -f "${SRE_POSTGRES_DIR}/Dockerfile" ]; then
        echo "ERROR: nexus-sre postgres Dockerfile not found at ${SRE_POSTGRES_DIR}/Dockerfile"
        echo "  Use --sre-postgres-dir to specify the nexus-sre postgres-image directory"
        exit 1
    fi
fi

# Validate AI Engine dirs only if we intend to package them
if [ "$AI_ENGINE_MODE" = true ] || [ "$SKIP_AI_ENGINE" = false ]; then
    if [ "$SKIP_AI_ENGINE_API" != true ] && [ "$ONLY_AI_ENGINE_UI" != true ] && [ ! -f "${AI_ENGINE_DIR}/Dockerfile" ]; then
        echo "ERROR: nexus-ai-engine Dockerfile not found at ${AI_ENGINE_DIR}/Dockerfile"
        echo "  Use --ai-engine-dir to specify the nexus-ai-engine repository root"
        exit 1
    fi
    if [ "$ONLY_AI_ENGINE_UI" = true ] && [ ! -f "${AI_ENGINE_DIR}/frontend/Dockerfile" ]; then
        echo "ERROR: nexus-ai-engine UI Dockerfile not found at ${AI_ENGINE_DIR}/frontend/Dockerfile (S11+)"
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
PACKAGE_NEXUS=false
PACKAGE_BSSMAGIC=false
PACKAGE_OPERATOR=false
PACKAGE_SRE_BACKEND=false
PACKAGE_SRE_UI=false
PACKAGE_SRE_POSTGRES=false
PACKAGE_AI_ENGINE_API=false
PACKAGE_AI_ENGINE_UI=false

if [ "$AI_ENGINE_MODE" = true ]; then
    if [ "$ONLY_AI_ENGINE_API" = true ]; then
        PACKAGE_AI_ENGINE_API=true
    elif [ "$ONLY_AI_ENGINE_UI" = true ]; then
        PACKAGE_AI_ENGINE_UI=true
    else
        [ "${SKIP_AI_ENGINE_API}" = false ] && PACKAGE_AI_ENGINE_API=true
        PACKAGE_AI_ENGINE_UI=true
    fi
elif [ "$SRE_MODE" = true ]; then
    if [ "$ONLY_SRE_BACKEND" = true ]; then
        PACKAGE_SRE_BACKEND=true
    elif [ "$ONLY_SRE_UI" = true ]; then
        PACKAGE_SRE_UI=true
    elif [ "$ONLY_SRE_POSTGRES" = true ]; then
        PACKAGE_SRE_POSTGRES=true
    else
        [ "$SKIP_SRE_BACKEND" = false ] && PACKAGE_SRE_BACKEND=true
        [ "$SKIP_SRE_UI" = false ] && PACKAGE_SRE_UI=true
        [ "$SKIP_SRE_POSTGRES" = false ] && PACKAGE_SRE_POSTGRES=true
    fi
elif [ "$ONLY_BSSMAGIC" = true ]; then
    PACKAGE_BSSMAGIC=true
elif [ "$ONLY_OPERATOR" = true ]; then
    PACKAGE_OPERATOR=true
else
    PACKAGE_NEXUS=true
    [ "$SKIP_BSSMAGIC" = false ] && PACKAGE_BSSMAGIC=true
    [ "$SKIP_OPERATOR" = false ] && PACKAGE_OPERATOR=true
    if [ "$SKIP_SRE" = false ]; then
        [ "$SKIP_SRE_BACKEND" = false ] && PACKAGE_SRE_BACKEND=true
        [ "$SKIP_SRE_UI" = false ] && PACKAGE_SRE_UI=true
        [ "$SKIP_SRE_POSTGRES" = false ] && PACKAGE_SRE_POSTGRES=true
    fi
    if [ "$SKIP_AI_ENGINE" = false ]; then
        [ "${SKIP_AI_ENGINE_API}" = false ] && PACKAGE_AI_ENGINE_API=true
    fi
fi

[ "$PACKAGE_NEXUS" = true ] && TOTAL_STEPS=$((TOTAL_STEPS + 4))
[ "$PACKAGE_BSSMAGIC" = true ] && TOTAL_STEPS=$((TOTAL_STEPS + 3))
[ "$PACKAGE_OPERATOR" = true ] && TOTAL_STEPS=$((TOTAL_STEPS + 3))
[ "$PACKAGE_SRE_BACKEND" = true ] && TOTAL_STEPS=$((TOTAL_STEPS + 2))
[ "$PACKAGE_SRE_UI" = true ] && TOTAL_STEPS=$((TOTAL_STEPS + 2))
[ "$PACKAGE_SRE_POSTGRES" = true ] && TOTAL_STEPS=$((TOTAL_STEPS + 2))
[ "$PACKAGE_AI_ENGINE_API" = true ] && TOTAL_STEPS=$((TOTAL_STEPS + 2))
[ "$PACKAGE_AI_ENGINE_UI" = true ] && TOTAL_STEPS=$((TOTAL_STEPS + 2))
CURRENT_STEP=0

echo "=============================================="
echo "  Package Images"
echo "=============================================="
echo ""
if [ "$PACKAGE_NEXUS" = true ]; then
    echo "  Backend source:   ${BACKEND_DIR}"
    echo "  Frontend source:  ${FRONTEND_DIR}"
    echo "  Nexus output:     ${NEXUS_OUTPUT}"
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
# Nexus Images (frontend + backend)
# ──────────────────────────────────────────────────────────────
if [ "$PACKAGE_NEXUS" = true ]; then
    mkdir -p "${NEXUS_OUTPUT}"

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
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Saving Nexus images as tar.gz ==="
    echo "  Saving ${BACKEND_IMAGE}..."
    docker save "${BACKEND_IMAGE}" | gzip > "${NEXUS_OUTPUT}/ai-job-engine.tar.gz"
    echo "  Saving ${FRONTEND_IMAGE}..."
    docker save "${FRONTEND_IMAGE}" | gzip > "${NEXUS_OUTPUT}/nexus-ui.tar.gz"
    echo "  Done."
    echo ""

    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Generating Nexus checksums ==="
    cd "${NEXUS_OUTPUT}"
    sha256sum ai-job-engine.tar.gz nexus-ui.tar.gz > checksums.sha256
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

    BASE_IMAGE="654654554404.dkr.ecr.us-east-1.amazonaws.com/nexus/bssmagic-runtime:latest"
    if ! docker image inspect "$BASE_IMAGE" &>/dev/null; then
        echo "  Base image not found locally. Logging in to ECR and pulling..."
        aws ecr get-login-password --region us-east-1 --profile ptr-tech 2>/dev/null \
            | docker login --username AWS --password-stdin 654654554404.dkr.ecr.us-east-1.amazonaws.com 2>/dev/null || true
        if ! docker pull "$BASE_IMAGE" 2>/dev/null; then
            echo ""
            echo "  ❌ Base image not available: $BASE_IMAGE"
            echo ""
            echo "  The bssmagic-runtime base image must be pushed to your ECR first."
            echo "  On a machine that has the image locally, run:"
            echo ""
            echo "    aws ecr get-login-password --region us-east-1 --profile ptr-tech | \\"
            echo "      docker login --username AWS --password-stdin 654654554404.dkr.ecr.us-east-1.amazonaws.com"
            echo "    docker tag <local-bssmagic-runtime-image>:latest $BASE_IMAGE"
            echo "    docker push $BASE_IMAGE"
            echo ""
            echo "  Then re-run this script."
            exit 1
        fi
    else
        echo "  Base image found locally."
    fi
    echo ""
    docker build -t "${BSSMAGIC_IMAGE}" "${BSSMAGIC_DIR}"
    echo "  Done."
    echo ""

    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Saving BSS Magic image as tar.gz ==="
    echo "  Saving ${BSSMAGIC_IMAGE}..."
    docker save "${BSSMAGIC_IMAGE}" | gzip > "${BSSMAGIC_OUTPUT}/bssmagic-nexus-k8s.tar.gz"
    echo "  Done."
    echo ""

    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Generating BSS Magic checksums ==="
    cd "${BSSMAGIC_OUTPUT}"
    sha256sum bssmagic-nexus-k8s.tar.gz > checksums.sha256
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
    docker save "${OPERATOR_IMAGE}" | gzip > "${OPERATOR_OUTPUT}/nexus-operator.tar.gz"
    echo "  Done."
    echo ""

    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Generating operator checksums ==="
    cd "${OPERATOR_OUTPUT}"
    sha256sum nexus-operator.tar.gz > checksums.sha256
    cd "${SCRIPT_DIR}"
    echo "  Done."
    echo ""
fi

# ──────────────────────────────────────────────────────────────
# nexus-sre Images
# ──────────────────────────────────────────────────────────────
if [ "$PACKAGE_SRE_BACKEND" = true ] || [ "$PACKAGE_SRE_UI" = true ] || [ "$PACKAGE_SRE_POSTGRES" = true ]; then
    mkdir -p "${SRE_OUTPUT}"
fi

if [ "$PACKAGE_SRE_BACKEND" = true ]; then
    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Building nexus-sre backend image: ${SRE_BACKEND_IMAGE} ==="
    docker build -t "${SRE_BACKEND_IMAGE}" "${SRE_BACKEND_DIR}"
    echo "  Done."
    echo ""

    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Saving ${SRE_BACKEND_IMAGE} as tar.gz ==="
    docker save "${SRE_BACKEND_IMAGE}" | gzip > "${SRE_OUTPUT}/nexus-sre-backend.tar.gz"
    (cd "${SRE_OUTPUT}" && sha256sum nexus-sre-backend.tar.gz >> checksums.sha256)
    echo "  Done."
    echo ""
fi

if [ "$PACKAGE_SRE_UI" = true ]; then
    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Building nexus-sre ui image: ${SRE_UI_IMAGE} ==="
    docker build -t "${SRE_UI_IMAGE}" "${SRE_FRONTEND_DIR}"
    echo "  Done."
    echo ""

    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Saving ${SRE_UI_IMAGE} as tar.gz ==="
    docker save "${SRE_UI_IMAGE}" | gzip > "${SRE_OUTPUT}/nexus-sre-ui.tar.gz"
    (cd "${SRE_OUTPUT}" && sha256sum nexus-sre-ui.tar.gz >> checksums.sha256)
    echo "  Done."
    echo ""
fi

if [ "$PACKAGE_SRE_POSTGRES" = true ]; then
    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Building nexus-sre postgres image (pgvector+AGE): ${SRE_POSTGRES_IMAGE} ==="
    docker build -t "${SRE_POSTGRES_IMAGE}" "${SRE_POSTGRES_DIR}"
    echo "  Done."
    echo ""

    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Saving ${SRE_POSTGRES_IMAGE} as tar.gz ==="
    docker save "${SRE_POSTGRES_IMAGE}" | gzip > "${SRE_OUTPUT}/nexus-sre-postgres.tar.gz"
    (cd "${SRE_OUTPUT}" && sha256sum nexus-sre-postgres.tar.gz >> checksums.sha256)
    echo "  Done."
    echo ""
fi

# ──────────────────────────────────────────────────────────────
# nexus-ai-engine Images
# ──────────────────────────────────────────────────────────────
if [ "$PACKAGE_AI_ENGINE_API" = true ] || [ "$PACKAGE_AI_ENGINE_UI" = true ]; then
    mkdir -p "${AI_ENGINE_OUTPUT}"
fi

if [ "$PACKAGE_AI_ENGINE_API" = true ]; then
    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Building nexus-ai-engine API image: ${AI_ENGINE_API_IMAGE} ==="
    docker build -t "${AI_ENGINE_API_IMAGE}" "${AI_ENGINE_DIR}"
    echo "  Done."
    echo ""

    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Saving ${AI_ENGINE_API_IMAGE} as tar.gz ==="
    docker save "${AI_ENGINE_API_IMAGE}" | gzip > "${AI_ENGINE_OUTPUT}/nexus-ai-engine-api.tar.gz"
    (cd "${AI_ENGINE_OUTPUT}" && sha256sum nexus-ai-engine-api.tar.gz >> checksums.sha256)
    echo "  Done."
    echo ""
fi

if [ "$PACKAGE_AI_ENGINE_UI" = true ]; then
    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Building nexus-ai-engine UI image: ${AI_ENGINE_UI_IMAGE} ==="
    docker build -t "${AI_ENGINE_UI_IMAGE}" "${AI_ENGINE_DIR}/frontend"
    echo "  Done."
    echo ""

    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo "=== [${CURRENT_STEP}/${TOTAL_STEPS}] Saving ${AI_ENGINE_UI_IMAGE} as tar.gz ==="
    docker save "${AI_ENGINE_UI_IMAGE}" | gzip > "${AI_ENGINE_OUTPUT}/nexus-ai-engine-ui.tar.gz"
    (cd "${AI_ENGINE_OUTPUT}" && sha256sum nexus-ai-engine-ui.tar.gz >> checksums.sha256)
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
if [ "$PACKAGE_NEXUS" = true ] && [ -d "${NEXUS_OUTPUT}" ]; then
    ls -lh "${NEXUS_OUTPUT}/"*.tar.gz 2>/dev/null | awk '{print "    " $5 "  " $NF}'
fi
if [ "$PACKAGE_BSSMAGIC" = true ] && [ -d "${BSSMAGIC_OUTPUT}" ]; then
    ls -lh "${BSSMAGIC_OUTPUT}/"*.tar.gz 2>/dev/null | awk '{print "    " $5 "  " $NF}'
fi
if [ "$PACKAGE_OPERATOR" = true ] && [ -d "${OPERATOR_OUTPUT}" ]; then
    ls -lh "${OPERATOR_OUTPUT}/"*.tar.gz 2>/dev/null | awk '{print "    " $5 "  " $NF}'
fi
if { [ "$PACKAGE_SRE_BACKEND" = true ] || [ "$PACKAGE_SRE_UI" = true ] || [ "$PACKAGE_SRE_POSTGRES" = true ]; } && [ -d "${SRE_OUTPUT}" ]; then
    ls -lh "${SRE_OUTPUT}/"*.tar.gz 2>/dev/null | awk '{print "    " $5 "  " $NF}'
fi
if { [ "$PACKAGE_AI_ENGINE_API" = true ] || [ "$PACKAGE_AI_ENGINE_UI" = true ]; } && [ -d "${AI_ENGINE_OUTPUT}" ]; then
    ls -lh "${AI_ENGINE_OUTPUT}/"*.tar.gz 2>/dev/null | awk '{print "    " $5 "  " $NF}'
fi
echo ""
echo "  These files can now be shipped with kube-operator/"
echo "  and deployed to any AWS account via e2e-deploy.sh"
echo ""

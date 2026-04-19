
#!/bin/bash
#
# Deploy App Changes
# Rebuilds and deploys backend + frontend images, restarts pods
#
# Usage:
#   ./deploy-app-changes.sh                        # Uses .env.local defaults (or dev if absent)
#   ./deploy-app-changes.sh --env prod             # Deploy to prod (starhub-test)
#   ./deploy-app-changes.sh --env stage            # Deploy to stage (starhub-stage)
#   ./deploy-app-changes.sh --env dev --cluster X  # Deploy dev to custom cluster
#
# Reads defaults from .env.local (ENV, Branch, Cluster). CLI args override.
#
# Location: /opt/mycode/trilogy/starhub-deployer/kube-operator/
# Run from: This directory or anywhere

set -eo pipefail

# Optional: enable BuildKit if docker buildx is available (faster; otherwise legacy builder)
if docker buildx version >/dev/null 2>&1; then
    export DOCKER_BUILDKIT=1
fi

# Determine directories relative to script location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TRILOGY_ROOT="$(cd "$DEPLOYER_ROOT/.." && pwd)"

BACKEND_DIR="${TRILOGY_ROOT}/starhub-backend"
FRONTEND_DIR="${TRILOGY_ROOT}/starhub-ui"
DOCS_VENV="${DOCS_VENV:-/tmp/docs-venv}"

# Load defaults from .env.local (CLI args and env vars override these)
_ENVLOCAL="${SCRIPT_DIR}/.env.local"
_ENV_LOCAL_ENV=""
_ENV_LOCAL_BRANCH=""
_ENV_LOCAL_CLUSTER=""
if [ -f "$_ENVLOCAL" ]; then
    # grep returns 1 when key missing — must not abort under set -e
    _ENV_LOCAL_ENV=$(grep '^ENV=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2-) || true
    _ENV_LOCAL_BRANCH=$(grep '^Branch=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2-) || true
    _ENV_LOCAL_CLUSTER=$(grep '^Cluster=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2-) || true
fi

DEPLOY_ENV="${DEPLOY_ENV:-${_ENV_LOCAL_ENV:-dev}}"
CLUSTER_NAME="${CLUSTER_NAME:-${_ENV_LOCAL_CLUSTER:-}}"
GIT_BRANCH="${GIT_BRANCH:-${_ENV_LOCAL_BRANCH:-}}"
AWS_PROFILE="${AWS_PROFILE:-external-access}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --env)      DEPLOY_ENV="$2"; shift 2 ;;
        --cluster)  CLUSTER_NAME="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [--env ENV] [--cluster NAME]"
            echo ""
            echo "Options:"
            echo "  --env ENV        Target environment: dev, stage, prod (default: dev)"
            echo "  --cluster NAME   EKS cluster name (default: dev=starhub-test1, prod=starhub-test)"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Derive cluster from env if not explicitly set
if [ -z "$CLUSTER_NAME" ]; then
    case "$DEPLOY_ENV" in
        prod)  CLUSTER_NAME="starhub-test" ;;
        dev)   CLUSTER_NAME="starhub-test1" ;;
        *)     CLUSTER_NAME="starhub-${DEPLOY_ENV}" ;;
    esac
fi

NAMESPACE="call-processing-${DEPLOY_ENV}"

# Preflight: paths and tools (clear errors before long Docker builds)
for _d in "$BACKEND_DIR" "$FRONTEND_DIR"; do
    [ -d "$_d" ] || { echo "ERROR: Directory not found: $_d"; exit 1; }
done
for _cmd in docker aws kubectl python3; do
    command -v "$_cmd" >/dev/null || { echo "ERROR: Required command not on PATH: $_cmd"; exit 1; }
done

# AWS Configuration
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --profile "${AWS_PROFILE}")
REGION="ap-southeast-1"
ECR_BACKEND="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/ai-job-engine:latest"
ECR_FRONTEND="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/starhub-ui:latest"

# Switch kubeconfig to target cluster
aws eks update-kubeconfig --name "${CLUSTER_NAME}" --region "${REGION}" --profile "${AWS_PROFILE}" 2>/dev/null \
    || { echo "Failed to update kubeconfig for cluster '${CLUSTER_NAME}'"; exit 1; }

kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1 \
    || { echo "ERROR: Namespace '${NAMESPACE}' not found in cluster '${CLUSTER_NAME}'. Check --env or .env.local ENV=."; exit 1; }

echo "================================================"
echo "  Deploying App Changes"
echo "================================================"
echo ""
echo "Environment: ${DEPLOY_ENV}"
echo "Cluster:     ${CLUSTER_NAME}"
echo "Namespace:   ${NAMESPACE}"
echo "Account:     ${ACCOUNT_ID}"
echo "Region:      ${REGION}"
echo ""
echo "Directories:"
echo "  Backend:  ${BACKEND_DIR}"
echo "  Frontend: ${FRONTEND_DIR}"
echo ""

# ECR login
echo "Logging in to ECR..."
aws ecr get-login-password --region ${REGION} --profile "${AWS_PROFILE}" | \
  docker login --username AWS --password-stdin ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com

echo ""
echo "================================================"
echo "  Building Backend"
echo "================================================"
cd "${BACKEND_DIR}"

echo "Building ai-job-engine..."
docker build --no-cache -t ai-job-engine:latest .

echo "Tagging for ECR..."
docker tag ai-job-engine:latest $ECR_BACKEND

echo "Pushing to ECR..."
docker push $ECR_BACKEND

echo "✅ Backend image pushed"

echo ""
echo "================================================"
echo "  Building Documentation"
echo "================================================"
DOCS_DIR="${TRILOGY_ROOT}/starhub-docs"
if [ -d "$DOCS_DIR" ]; then
    cd "$DOCS_DIR"
    # Self-heal venv if missing, broken, or mkdocs not importable (avoids stale /tmp/docs-venv)
    if [ ! -x "${DOCS_VENV}/bin/python" ] || ! "${DOCS_VENV}/bin/python" -c "import mkdocs" 2>/dev/null; then
        echo "Preparing docs Python venv at ${DOCS_VENV}..."
        rm -rf "${DOCS_VENV}"
        python3 -m venv "${DOCS_VENV}"
    fi
    [ -x "${DOCS_VENV}/bin/pip" ] || { echo "ERROR: Failed to create docs venv (no pip)"; exit 1; }
    "${DOCS_VENV}/bin/pip" install -q -r requirements.txt
    # python -m mkdocs avoids broken console-script entrypoints after partial installs
    "${DOCS_VENV}/bin/python" -m mkdocs build -q
    rm -rf "${FRONTEND_DIR}/docs-site"
    cp -r site "${FRONTEND_DIR}/docs-site"
    echo "✅ Docs built: $(find site -name 'index.html' 2>/dev/null | wc -l) pages"
else
    echo "⚠️  Docs repo not found at $DOCS_DIR, creating empty docs-site"
    mkdir -p "${FRONTEND_DIR}/docs-site"
    echo "<html><body><h1>Documentation not available</h1></body></html>" > "${FRONTEND_DIR}/docs-site/index.html"
fi

echo ""
echo "================================================"
echo "  Building Frontend"
echo "================================================"
cd "${FRONTEND_DIR}"

echo "Building starhub-ui..."
docker build --no-cache -t starhub-ui:latest .

echo "Tagging for ECR..."
docker tag starhub-ui:latest $ECR_FRONTEND

echo "Pushing to ECR..."
docker push $ECR_FRONTEND

echo "✅ Frontend image pushed"

echo ""
echo "================================================"
echo "  Deploying to Kubernetes"
echo "================================================"

echo "Restarting backend pods..."
kubectl delete pods -l app=${NAMESPACE}-backend -n ${NAMESPACE}

echo "Restarting frontend pods..."
kubectl delete pods -l app=${NAMESPACE}-frontend -n ${NAMESPACE}

echo ""
echo "Waiting for backend pods to be ready..."
kubectl wait --for=condition=ready pod -l app=${NAMESPACE}-backend -n ${NAMESPACE} --timeout=300s || echo "Backend pods still starting..."

echo "Waiting for frontend pods to be ready..."
kubectl wait --for=condition=ready pod -l app=${NAMESPACE}-frontend -n ${NAMESPACE} --timeout=300s || echo "Frontend pods still starting..."

echo ""
echo "Checking pod status..."
kubectl get pods -n ${NAMESPACE}

echo ""
echo "================================================"
echo "  ✅ Deployment Complete! (${DEPLOY_ENV})"
echo "================================================"
echo ""

# Show ALB URLs (public + internal if present), detect HTTPS
ALB_HOST=$(kubectl get ingress ${NAMESPACE}-app-ingress -n ${NAMESPACE} -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
ALB_CERT=$(kubectl get ingress ${NAMESPACE}-app-ingress -n ${NAMESPACE} -o jsonpath='{.metadata.annotations.alb\.ingress\.kubernetes\.io/certificate-arn}' 2>/dev/null || echo "")
ALB_SCHEME="http"
[ -n "$ALB_CERT" ] && ALB_SCHEME="https"
if [ -n "$ALB_HOST" ]; then
    echo "Public Application URL: ${ALB_SCHEME}://${ALB_HOST}"
    echo ""
    echo "Test endpoints:"
    echo "  curl ${ALB_SCHEME}://${ALB_HOST}/api/v1/auth/health"
    echo "  curl ${ALB_SCHEME}://${ALB_HOST}/"
else
    echo "No ALB Ingress found. Checking services..."
    kubectl get svc -n ${NAMESPACE}
fi

INTERNAL_ALB_HOST=$(kubectl get ingress ${NAMESPACE}-internal-ingress -n ${NAMESPACE} -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
INTERNAL_CERT=$(kubectl get ingress ${NAMESPACE}-internal-ingress -n ${NAMESPACE} -o jsonpath='{.metadata.annotations.alb\.ingress\.kubernetes\.io/certificate-arn}' 2>/dev/null || echo "")
INT_SCHEME="http"
[ -n "$INTERNAL_CERT" ] && INT_SCHEME="https"
if [ -n "$INTERNAL_ALB_HOST" ]; then
    echo ""
    echo "Internal (VPC-only) URL: ${INT_SCHEME}://${INTERNAL_ALB_HOST}"
fi
echo ""

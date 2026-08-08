#!/bin/bash
#
# deploy-capability.sh — First-time capability deploy via Nexus operator
#
# Central DevOps entry point for all Nexus products. Application repos stay
# free of deployment scripts; manage everything from nexus-deployer/kube-operator.
#
# Workflow:
#   1. ./operator.sh deploy                          # once per cluster
#   2. ./deploy-capability.sh --product <name>       # first-time deploy
#   3. ./deploy-app-changes.sh <product> --env dev   # dev iteration
#   4. ./app-rollout.sh ...                           # prod image updates
#
# Products:
#   nexus-ai      Full stack (BSS Magic, Cognito, DynamoDB/S3/Glue)
#   ontology      Backend + UI + DynamoDB/S3/Glue (dataServices in CR)
#   ai-engine     Backend + UI (lightweight CR)
#   sre           Backend + UI (lightweight CR; postgres via app-rollout)
#   simulator     API server only (lightweight CR)
#
# Usage:
#   ./deploy-capability.sh --product ontology --env dev
#   ./deploy-capability.sh --product nexus-ai --env prod
#   ./deploy-capability.sh --product ontology --env dev --skip-images
#   ./deploy-capability.sh --help

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/init-kube-env.sh
. "${SCRIPT_DIR}/lib/init-kube-env.sh"
# shellcheck source=lib/deploy-capability-products.sh
. "${SCRIPT_DIR}/lib/deploy-capability-products.sh"

DEPLOYER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
NEXUS_ROOT="$(cd "$DEPLOYER_ROOT/.." && pwd)"

_ENVLOCAL="${SCRIPT_DIR}/.env.local"
if [ -f "$_ENVLOCAL" ]; then
    _ENV_LOCAL_ENV=$(grep '^ENV=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- || true)
    _ENV_LOCAL_CLUSTER=$(grep '^Cluster=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- || true)
    _ENV_LOCAL_CERT=$(grep '^CertificateArn=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- || true)
fi

PRODUCT="${PRODUCT:-nexus-ai}"
AWS_PROFILE="${AWS_PROFILE:-external-access}"
DEPLOY_ENV="${DEPLOY_ENV:-${_ENV_LOCAL_ENV:-dev}}"
CLUSTER_NAME="${CLUSTER_NAME:-${_ENV_LOCAL_CLUSTER:-}}"
CERTIFICATE_ARN="${CERTIFICATE_ARN:-${_ENV_LOCAL_CERT:-}}"
NAMESPACE_OVERRIDE=""
CLUSTER_EXPLICIT=false
SKIP_IMAGES=false
SKIP_CREDS=false
SKIP_SSM_FIX=false
SKIP_IAM=false
REBUILD_IMAGES=false

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

step_num=0
total_steps=9

dcap_log_fail() { echo -e "${RED}  ✗ $1${NC}"; }
dcap_log_ok()   { echo -e "${GREEN}  ✓ $1${NC}"; }
dcap_log_warn() { echo -e "${YELLOW}  ⚠ $1${NC}"; }
dcap_log_info() { echo "  $1"; }

step() {
    step_num=$((step_num + 1))
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  Step ${step_num}/${total_steps}: $1${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════════${NC}"
    echo ""
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --product)      PRODUCT="$2"; shift 2 ;;
        --env)          DEPLOY_ENV="$2"; shift 2 ;;
        --cluster)      CLUSTER_NAME="$2"; CLUSTER_EXPLICIT=true; shift 2 ;;
        --namespace|-n) NAMESPACE_OVERRIDE="$2"; shift 2 ;;
        --capability)   CAPABILITY_FILE="$2"; shift 2 ;;
        --cert|--certificate) CERTIFICATE_ARN="$2"; shift 2 ;;
        --skip-images)  SKIP_IMAGES=true; shift ;;
        --skip-iam)     SKIP_IAM=true; shift ;;
        --rebuild-images) REBUILD_IMAGES=true; shift ;;
        --skip-creds)   SKIP_CREDS=true; shift ;;
        --skip-ssm-fix) SKIP_SSM_FIX=true; shift ;;
        --help|-h)
            sed -n '2,28p' "$0"
            echo ""
            echo "Products: $(dcap_list_products)"
            exit 0
            ;;
        nexus-ai|ontology|nexus-ontology|ai-engine|nexus-ai-engine|sre|nexus-sre|simulator|nexus-simulator)
            PRODUCT="$1"; shift ;;
        *) dcap_log_fail "Unknown option: $1"; exit 1 ;;
    esac
done

dcap_load_product "$PRODUCT" || exit 1
[ "${DCP_SKIP_CREDS_DEFAULT:-false}" = true ] && [ "$SKIP_CREDS" = false ] && SKIP_CREDS=true
[ "${DCP_SKIP_SSM_FIX_DEFAULT:-false}" = true ] && [ "$SKIP_SSM_FIX" = false ] && SKIP_SSM_FIX=true

CURRENT_ACCOUNT=$(aws_cli sts get-caller-identity --query 'Account' --output text 2>/dev/null || true)
[ -z "$CURRENT_ACCOUNT" ] && CURRENT_ACCOUNT=$(aws sts get-caller-identity --profile "${AWS_PROFILE}" --query 'Account' --output text 2>/dev/null || true)
[ -z "$CURRENT_ACCOUNT" ] && { dcap_log_fail "Failed to get AWS account ID"; exit 1; }

REGION=$(aws configure get region --profile "${AWS_PROFILE}" 2>/dev/null || echo "us-east-1")
ECR_REGISTRY="${CURRENT_ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

if [ "$CLUSTER_EXPLICIT" = false ] && [ -z "$CLUSTER_NAME" ]; then
    case "$DEPLOY_ENV" in
        prod) CLUSTER_NAME="nexus-prod" ;;
        dev)  CLUSTER_NAME="nexus-dev" ;;
        *)    CLUSTER_NAME="nexus-${DEPLOY_ENV}" ;;
    esac
fi
export CLUSTER_NAME DEPLOY_ENV REGION ECR_REGISTRY

nexus_eks_update_kubeconfig "${CLUSTER_NAME}" "${REGION}" "${AWS_PROFILE}" >/dev/null 2>&1 \
    || aws eks update-kubeconfig --name "${CLUSTER_NAME}" --region "${REGION}" --profile "${AWS_PROFILE}" \
        --kubeconfig "${KUBECONFIG}" 2>/dev/null \
    || { dcap_log_fail "Failed to update kubeconfig for cluster '${CLUSTER_NAME}'"; exit 1; }

kubectl get nodes >/dev/null 2>&1 || { dcap_log_fail "kubectl cannot connect to cluster"; exit 1; }

OPERATOR_READY=$(kubectl get deployment nexus-operator -n nexus-system -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
if [ -z "$OPERATOR_READY" ] || [ "$OPERATOR_READY" = "0" ]; then
    dcap_log_fail "Nexus operator is not running. Deploy first: ./operator.sh deploy"
    exit 1
fi
dcap_log_ok "Operator is running (${OPERATOR_READY} replica(s))"

[ "$SKIP_IMAGES" = true ] && total_steps=$((total_steps - 1))
[ "$SKIP_IAM" = true ] && total_steps=$((total_steps - 1))
[ "$SKIP_CREDS" = true ] && total_steps=$((total_steps - 1))
[ "$SKIP_SSM_FIX" = true ] && total_steps=$((total_steps - 1))

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Deploy Capability${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
echo ""
echo "  Product:        ${PRODUCT} (${DCP_LABEL})"
echo "  Mode:           ${DCP_MODE}"
echo "  Environment:    ${DEPLOY_ENV}"
echo "  Cluster:        ${CLUSTER_NAME}"
echo "  Namespace:      ${NAMESPACE}"
echo "  ECR:            ${ECR_REGISTRY}"
echo "  Capability CR:  $(basename "${CAPABILITY_FILE}")"
echo ""

# ── Ensure operator CRDs (network config required for kopf to reconcile) ──
step "Ensure operator CRDs"
NETWORK_CRD="${SCRIPT_DIR}/manifests/network-config-crd.yaml"
if [ -f "$NETWORK_CRD" ]; then
    kubectl apply -f "$NETWORK_CRD" >/dev/null 2>&1 \
        && dcap_log_ok "NexusNetworkConfig CRD ready" \
        || dcap_log_warn "Could not apply network-config CRD (may already exist)"
else
    dcap_log_warn "Missing ${NETWORK_CRD}"
fi

# ── Bootstrap IAM app role (admin-managed; idempotent) ─────────────────
if [ "$SKIP_IAM" = false ]; then
    step "Bootstrap IAM app role (IRSA)"
    if [ -x "${SCRIPT_DIR}/setup-iam-policies.sh" ]; then
        bash "${SCRIPT_DIR}/setup-iam-policies.sh" \
            --cluster "${CLUSTER_NAME}" \
            --region "${REGION}" \
            --profile "${AWS_PROFILE}" \
            --env "${DEPLOY_ENV}" \
            --capability "${DCP_CAPABILITY_NAME}" \
            --skip-confirm \
            || dcap_log_warn "IAM bootstrap failed — app pods may lack AWS access until admin runs setup-iam-policies.sh"
        dcap_log_ok "IAM role ${DCP_CAPABILITY_NAME}-${DEPLOY_ENV}-app-role ensured"
    else
        dcap_log_warn "setup-iam-policies.sh not found — skipping IAM bootstrap"
    fi
fi

# ── Push images ───────────────────────────────────────────────────
if [ "$SKIP_IMAGES" = false ]; then
    step "Push images to ECR"

    aws_cli ecr get-login-password --region "${REGION}" \
        | docker login --username AWS --password-stdin "${ECR_REGISTRY}" >/dev/null 2>&1 \
        || aws ecr get-login-password --region "${REGION}" --profile "${AWS_PROFILE}" \
            | docker login --username AWS --password-stdin "${ECR_REGISTRY}" >/dev/null 2>&1 \
        || dcap_log_warn "ECR docker login failed — create-ecr-images may still work"

    if [ "${DCP_PRE_BUILD_UI:-false}" = true ]; then
        FE_DIR="${NEXUS_ROOT}/nexus-ontology/frontend"
        [ "$PRODUCT" = ai-engine ] && FE_DIR="${NEXUS_ROOT}/nexus-ai-engine/frontend"
        [ "$PRODUCT" = sre ] && FE_DIR="${NEXUS_ROOT}/nexus-sre/frontend"
        if [ -d "$FE_DIR" ]; then
            dcap_log_info "Building docs site for UI image..."
            bash "${SCRIPT_DIR}/build-docs-site.sh" "$FE_DIR" || dcap_log_warn "Docs build failed (continuing)"
        fi
    fi

    case "${DCP_ECR_MODE}" in
        script)
            cd "${SCRIPT_DIR}"
            ECR_EXTRA=()
            [ "$REBUILD_IMAGES" = true ] && ECR_EXTRA+=(--no-cache)
            bash "${DCP_ECR_SCRIPT[0]}" "${DCP_ECR_ARGS[@]}" "${ECR_EXTRA[@]}" \
                || { dcap_log_fail "ECR push failed"; exit 1; }
            dcap_log_ok "Images pushed via ${DCP_ECR_SCRIPT[0]}"
            ;;
        callsense)
            IMAGES_DIR="${SCRIPT_DIR}/images/callsense"
            for IMAGE_NAME in ai-job-engine nexus-ui; do
                TAR_FILE="${IMAGES_DIR}/${IMAGE_NAME}.tar.gz"
                TAR_PLAIN="${IMAGES_DIR}/${IMAGE_NAME}.tar"
                ECR_TARGET="${ECR_REGISTRY}/${IMAGE_NAME}:latest"
                if [ ! -f "$TAR_FILE" ] && [ ! -f "$TAR_PLAIN" ]; then
                    dcap_log_warn "${IMAGE_NAME} tar not found — run package-images.sh or use create-ecr-images.sh"
                    continue
                fi
                aws_cli ecr describe-repositories --repository-names "${IMAGE_NAME}" --region "${REGION}" >/dev/null 2>&1 \
                    || aws_cli ecr create-repository --repository-name "${IMAGE_NAME}" --region "${REGION}" >/dev/null 2>&1
                docker load -i "${TAR_FILE:-$TAR_PLAIN}" 2>/dev/null
                docker tag "${IMAGE_NAME}:latest" "${ECR_TARGET}" 2>/dev/null
                docker push "${ECR_TARGET}" 2>/dev/null
                dcap_log_ok "${IMAGE_NAME} pushed"
            done
            BSS_IMAGE_NAME="bssmagic-nexus-k8s"
            BSS_TAR="${SCRIPT_DIR}/bss-magic/${BSS_IMAGE_NAME}.tar.gz"
            BSS_TAR_PLAIN="${SCRIPT_DIR}/bss-magic/${BSS_IMAGE_NAME}.tar"
            if [ -f "$BSS_TAR" ] || [ -f "$BSS_TAR_PLAIN" ]; then
                aws_cli ecr describe-repositories --repository-names "${BSS_IMAGE_NAME}" --region "${REGION}" >/dev/null 2>&1 \
                    || aws_cli ecr create-repository --repository-name "${BSS_IMAGE_NAME}" --region "${REGION}" >/dev/null 2>&1
                docker load -i "${BSS_TAR:-$BSS_TAR_PLAIN}" 2>/dev/null
                docker tag "${BSS_IMAGE_NAME}:latest" "${ECR_REGISTRY}/${BSS_IMAGE_NAME}:latest" 2>/dev/null
                docker push "${ECR_REGISTRY}/${BSS_IMAGE_NAME}:latest" 2>/dev/null
                dcap_log_ok "BSS Magic image pushed"
            else
                dcap_log_warn "BSS Magic tar not found — skipping"
            fi
            ;;
    esac
fi

# ── BSS credentials (nexus-ai only) ─────────────────────────────
if [ "$SKIP_CREDS" = false ] && [ "$DCP_MODE" = "cr-full" ]; then
    step "Upload BSS Magic credentials to Secrets Manager"
    CREDS_ZIP_PATH="${SCRIPT_DIR}/../bssmagic-image/secrets/credentials.zip"
    CREDS_SECRET_ID="nexus-ai/${DEPLOY_ENV}/bssmagic-credentials"
    if [ -f "${CREDS_ZIP_PATH}" ]; then
        if aws_cli secretsmanager describe-secret --secret-id "${CREDS_SECRET_ID}" --region "${REGION}" >/dev/null 2>&1; then
            aws_cli secretsmanager put-secret-value --secret-id "${CREDS_SECRET_ID}" \
                --secret-binary "fileb://${CREDS_ZIP_PATH}" --region "${REGION}" >/dev/null 2>&1 \
                && dcap_log_ok "credentials.zip uploaded" \
                || dcap_log_warn "Failed to upload credentials.zip"
        else
            aws_cli secretsmanager create-secret --name "${CREDS_SECRET_ID}" \
                --secret-binary "fileb://${CREDS_ZIP_PATH}" --region "${REGION}" >/dev/null 2>&1 \
                && dcap_log_ok "credentials.zip secret created" \
                || dcap_log_warn "Failed to create credentials secret"
        fi
    else
        dcap_log_warn "credentials.zip not found at ${CREDS_ZIP_PATH}"
    fi
fi

# ── Apply NexusCapability CR ──────────────────────────────────────
step "Apply NexusCapability CR"

PATCHED_FILE="/tmp/capability-${PRODUCT}-${DEPLOY_ENV}-patched.yaml"
sed -e "s|__ECR_REGISTRY__|${ECR_REGISTRY}|g" -e "s|__ENV__|${DEPLOY_ENV}|g" "${CAPABILITY_FILE}" > "${PATCHED_FILE}"

if [ -n "$CERTIFICATE_ARN" ]; then
    sed -i 's|# certificateArn:.*|certificateArn: "'"${CERTIFICATE_ARN}"'"|g' "${PATCHED_FILE}" 2>/dev/null || true
    if ! grep -q "certificateArn:" "${PATCHED_FILE}"; then
        sed -i '/healthCheckPath:/a\    certificateArn: "'"${CERTIFICATE_ARN}"'"' "${PATCHED_FILE}" 2>/dev/null || true
    fi
fi

kubectl create namespace "${NAMESPACE}" 2>/dev/null || true

CAP_NAME=$(grep -E "^\s+name:" "${PATCHED_FILE}" | head -1 | awk '{print $2}')
if [ -n "$CAP_NAME" ]; then
    DELETION_TS=$(kubectl get nexuscapability "$CAP_NAME" -n "$NAMESPACE" -o jsonpath='{.metadata.deletionTimestamp}' 2>/dev/null || echo "")
    if [ -n "$DELETION_TS" ]; then
        kubectl patch nexuscapability "$CAP_NAME" -n "$NAMESPACE" --type merge \
            -p '{"metadata":{"finalizers":[]}}' >/dev/null 2>&1 || true
        sleep 5
    fi
fi

if ! kubectl apply -f "${PATCHED_FILE}" 2>/dev/null; then
    sleep 10
    kubectl apply -f "${PATCHED_FILE}"
fi
rm -f "${PATCHED_FILE}"
dcap_log_ok "NexusCapability applied in ${NAMESPACE}"

# ── Monitor operator reconciliation ───────────────────────────────
step "Monitor operator reconciliation"

timeout 600 bash -c "AWS_PROFILE='${AWS_PROFILE}' ./operator.sh monitor ${NAMESPACE}/${CAP_NAME:-} 2>&1" || true
echo ""

dcap_log_info "Waiting for pods..."
for i in $(seq 1 36); do
    POD_LINES=$(kubectl get pods -n "${NAMESPACE}" --no-headers 2>/dev/null || true)
    TOTAL=$(echo "$POD_LINES" | grep -c . 2>/dev/null || echo 0)
    TOTAL=${TOTAL:-0}
    NOT_READY=0
    if [ "$TOTAL" -gt 0 ]; then
        NOT_READY=$(echo "$POD_LINES" | awk '$2 !~ /^(1\/1|2\/2|3\/3)$/ { n++ } END { print n + 0 }')
    fi
    if [ "$NOT_READY" -eq 0 ] && [ "$TOTAL" -gt 0 ]; then
        dcap_log_ok "All ${TOTAL} pods ready"
        break
    fi
    echo "    ${TOTAL} pods, not all ready... (${i}/36)"
    sleep 10
done

kubectl get nexuscapability -n "${NAMESPACE}" 2>/dev/null || true
kubectl get pods -n "${NAMESPACE}" 2>/dev/null || true

ALB_HOST=""
if [ "${DCP_WAIT_ALB:-false}" = true ]; then
    dcap_log_info "Waiting for ALB Ingress..."
    for i in $(seq 1 24); do
        ALB_HOST=$(kubectl get ingress -n "${NAMESPACE}" -o jsonpath='{.items[0].status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
        [ -n "$ALB_HOST" ] && { dcap_log_ok "ALB: ${ALB_HOST}"; break; }
        sleep 10
    done
fi

# ── Default admin user (Cognito) ──────────────────────────────────
step "Setup default admin user"
if [ -x "${SCRIPT_DIR}/setup-capability-admin.sh" ]; then
    bash "${SCRIPT_DIR}/setup-capability-admin.sh" \
        --capability "${DCP_CAPABILITY_NAME}" \
        --env "${DEPLOY_ENV}" \
        --cluster "${CLUSTER_NAME}" \
        --email "admin@nexus.ai" \
        --password "Pass123!" \
        && dcap_log_ok "Admin user admin@nexus.ai ready" \
        || dcap_log_warn "Admin setup failed — run: ./setup-capability-admin.sh --capability ${DCP_CAPABILITY_NAME} --env ${DEPLOY_ENV}"
else
    dcap_log_warn "setup-capability-admin.sh not found"
fi

# ── SSM fix (nexus-ai only) ───────────────────────────────────────
if [ "$SKIP_SSM_FIX" = false ] && [ "$DCP_MODE" = "cr-full" ]; then
    step "Verify and fix SSM parameters"
    SSM_PREFIX="/${CAPABILITY_NAME}/${DEPLOY_ENV}"
    COGNITO_POOL_NAME="${CAPABILITY_NAME}-${DEPLOY_ENV}"
    COGNITO_POOL_ID=$(aws_cli cognito-idp list-user-pools --max-results 60 --region "${REGION}" \
        --query "UserPools[?Name=='${COGNITO_POOL_NAME}'].Id | [0]" --output text 2>/dev/null || echo "None")
    if [ "$COGNITO_POOL_ID" != "None" ] && [ -n "$COGNITO_POOL_ID" ]; then
        aws_cli ssm put-parameter --name "${SSM_PREFIX}/cognito/user-pool-id" \
            --value "${COGNITO_POOL_ID}" --type String --overwrite --region "${REGION}" >/dev/null 2>&1 || true
        dcap_log_ok "SSM cognito/user-pool-id updated"
    fi
fi

# ── Verify ────────────────────────────────────────────────────────
step "Verify capability"
AWS_PROFILE="${AWS_PROFILE}" ./operator.sh verify-capability "${NAMESPACE}" 2>&1 || true

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✓ Capability deploy complete (${PRODUCT})${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
echo ""
echo "  Namespace:  ${NAMESPACE}"
echo "  Dev updates: ./deploy-app-changes.sh ${PRODUCT} --env ${DEPLOY_ENV}"
echo "  Prod rollout: ./app-rollout.sh --capability ${DCP_CAPABILITY_NAME} --env ${DEPLOY_ENV} ..."
if [ -n "$ALB_HOST" ]; then
    echo ""
    echo "  URL: http://${ALB_HOST}/"
fi
echo ""

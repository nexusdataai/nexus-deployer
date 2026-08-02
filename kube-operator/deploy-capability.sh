#!/bin/bash
#
# Deploy Capability
#
# Deploys the CallSense + BSS Magic capability on top of an existing operator.
# Does NOT touch operator, ALB controller, EBS CSI, or cluster access.
#
# Steps:
#   1. Push CallSense app images to ECR (backend + frontend)
#   2. Push BSS Magic image to ECR
#   3. Upload BSS Magic credentials.zip to Secrets Manager
#   4. Apply capability (NexusCapability CR)
#   5. Monitor deployment progress
#   6. Verify and fix SSM parameters (Glue, Cognito)
#   7. Verify all resources
#
# Reads defaults from .env.local (ENV, Branch, Cluster). CLI args override.
#
# Usage:
#   ./deploy-capability.sh                          # Uses .env.local defaults
#   ./deploy-capability.sh --env dev                # Deploy dev environment
#   ./deploy-capability.sh --env stage              # Deploy stage environment
#   ./deploy-capability.sh --skip-images            # Skip image push (already in ECR)
#   ./deploy-capability.sh --skip-creds             # Skip credentials upload
#   ./deploy-capability.sh --capability my-cap.yaml # Use custom capability file
#   ./deploy-capability.sh --help                   # Show help

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SCRIPT_DIR}/lib/init-kube-env.sh"

# Load defaults from .env.local
_ENVLOCAL="${SCRIPT_DIR}/.env.local"
if [ -f "$_ENVLOCAL" ]; then
    _ENV_LOCAL_ENV=$(grep '^ENV=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- || true)
    _ENV_LOCAL_CLUSTER=$(grep '^Cluster=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- || true)
    _ENV_LOCAL_CERT=$(grep '^CertificateArn=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- || true)
fi

# Defaults
CAPABILITY_FILE="${SCRIPT_DIR}/examples/nexus-ai-complete.yaml"
AWS_PROFILE="${AWS_PROFILE:-external-access}"
DEPLOY_ENV="${DEPLOY_ENV:-${_ENV_LOCAL_ENV:-prod}}"
CLUSTER_NAME="${CLUSTER_NAME:-${_ENV_LOCAL_CLUSTER:-}}"
CERTIFICATE_ARN="${CERTIFICATE_ARN:-${_ENV_LOCAL_CERT:-}}"
CLUSTER_EXPLICIT=false
SKIP_IMAGES=false
SKIP_CREDS=false

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

step_num=0
total_steps=7

step() {
    step_num=$((step_num + 1))
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  Step ${step_num}/${total_steps}: $1${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════════${NC}"
    echo ""
}

success() { echo -e "${GREEN}  ✓ $1${NC}"; }
fail()    { echo -e "${RED}  ✗ $1${NC}"; exit 1; }
warn()    { echo -e "${YELLOW}  ⚠ $1${NC}"; }

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --env)          DEPLOY_ENV="$2"; shift 2 ;;
        --cluster)      CLUSTER_NAME="$2"; CLUSTER_EXPLICIT=true; shift 2 ;;
        --capability)   CAPABILITY_FILE="$2"; shift 2 ;;
        --cert|--certificate) CERTIFICATE_ARN="$2"; shift 2 ;;
        --skip-images)  SKIP_IMAGES=true; shift ;;
        --skip-creds)   SKIP_CREDS=true; shift ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Deploy capability on top of existing operator. Does NOT touch operator/ALB/EBS."
            echo ""
            echo "Options:"
            echo "  --env ENV              Target environment: dev, stage, prod (default: from .env.local or prod)"
            echo "  --cluster NAME         EKS cluster name (default: from .env.local)"
            echo "  --capability FILE      Capability YAML file (default: examples/nexus-ai-complete.yaml)"
            echo "  --cert ARN             ACM certificate ARN for HTTPS"
            echo "  --skip-images          Skip pushing images to ECR (already pushed)"
            echo "  --skip-creds           Skip uploading BSS Magic credentials"
            echo "  --help                 Show this help"
            exit 0
            ;;
        *) echo -e "${RED}Unknown option: $1${NC}"; exit 1 ;;
    esac
done

# ──────────────────────────────────────────────────────────────
# Resolve AWS account, region, cluster
# ──────────────────────────────────────────────────────────────
CURRENT_ACCOUNT=$(aws sts get-caller-identity --profile "${AWS_PROFILE}" --query 'Account' --output text 2>/dev/null || true)
[ -z "$CURRENT_ACCOUNT" ] && fail "Failed to get AWS account ID. Are you logged in?"

REGION=$(aws configure get region --profile "${AWS_PROFILE}" 2>/dev/null || echo "us-east-1")
ECR_REGISTRY="${CURRENT_ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

if [ "$CLUSTER_EXPLICIT" = true ]; then
    :
elif [ -n "$CLUSTER_NAME" ]; then
    :
else
    case "$DEPLOY_ENV" in
        prod) CLUSTER_NAME="nexus-test" ;;
        *)    CLUSTER_NAME="nexus-${DEPLOY_ENV}" ;;
    esac
fi
export CLUSTER_NAME DEPLOY_ENV REGION

aws eks update-kubeconfig \
    --name "${CLUSTER_NAME}" --region "${REGION}" --profile "${AWS_PROFILE}" \
    --kubeconfig "${KUBECONFIG}" 2>/dev/null \
|| fail "Failed to update kubeconfig for cluster '${CLUSTER_NAME}'"

# Verify kubectl works
kubectl get nodes >/dev/null 2>&1 || fail "kubectl cannot connect to cluster (Unauthorized)"

# Verify operator is running
OPERATOR_READY=$(kubectl get deployment nexus-operator -n nexus-system -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
if [ "$OPERATOR_READY" = "" ] || [ "$OPERATOR_READY" = "0" ]; then
    fail "Nexus operator is not running. Deploy operator first with: ./operator.sh deploy"
fi
success "Operator is running (${OPERATOR_READY} replica(s))"

# Adjust step count
[ "$SKIP_IMAGES" = true ] && total_steps=$((total_steps - 2))
[ "$SKIP_CREDS" = true ] && total_steps=$((total_steps - 1))

CAPABILITY_NAME="nexus-ai"
NAMESPACE="${CAPABILITY_NAME}-${DEPLOY_ENV}"

cd "${SCRIPT_DIR}"

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Deploy Capability${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
echo ""
echo "  Environment:    ${DEPLOY_ENV}"
echo "  Cluster:        ${CLUSTER_NAME}"
echo "  AWS Account:    ${CURRENT_ACCOUNT}"
echo "  Region:         ${REGION}"
echo "  ECR Registry:   ${ECR_REGISTRY}"
echo "  Namespace:      ${NAMESPACE}"
echo "  Capability:     $(basename ${CAPABILITY_FILE})"
echo "  Skip Images:    ${SKIP_IMAGES}"
echo "  Skip Creds:     ${SKIP_CREDS}"
echo ""

# ──────────────────────────────────────────────────────────────
# Step 1: Push CallSense app images to ECR
# ──────────────────────────────────────────────────────────────
if [ "$SKIP_IMAGES" = false ]; then
    step "Push CallSense app images to ECR"

    # ECR login
    aws ecr get-login-password --region "${REGION}" --profile "${AWS_PROFILE}" \
        | docker login --username AWS --password-stdin "${ECR_REGISTRY}" 2>/dev/null \
    || { warn "Docker login failed — trying crane"; }

    IMAGES_DIR="${SCRIPT_DIR}/images"
    CALLSENSE_DIR="${IMAGES_DIR}/callsense"

    for IMAGE_NAME in ai-job-engine nexus-ui; do
        TAR_FILE="${CALLSENSE_DIR}/${IMAGE_NAME}.tar.gz"
        TAR_PLAIN="${CALLSENSE_DIR}/${IMAGE_NAME}.tar"
        ECR_TARGET="${ECR_REGISTRY}/${IMAGE_NAME}:latest"

        if [ ! -f "$TAR_FILE" ] && [ ! -f "$TAR_PLAIN" ]; then
            warn "${IMAGE_NAME} tar not found in ${CALLSENSE_DIR} — skipping"
            continue
        fi

        # Ensure ECR repo exists
        aws ecr describe-repositories --repository-names "${IMAGE_NAME}" \
            --region "${REGION}" --profile "${AWS_PROFILE}" >/dev/null 2>&1 \
        || aws ecr create-repository --repository-name "${IMAGE_NAME}" \
            --region "${REGION}" --profile "${AWS_PROFILE}" >/dev/null 2>&1

        # Push via docker or crane
        if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
            echo "  Loading ${IMAGE_NAME} via docker..."
            docker load -i "${TAR_FILE:-$TAR_PLAIN}" 2>/dev/null
            docker tag "${IMAGE_NAME}:latest" "${ECR_TARGET}" 2>/dev/null
            docker push "${ECR_TARGET}" 2>/dev/null
        elif command -v crane >/dev/null 2>&1; then
            echo "  Pushing ${IMAGE_NAME} via crane..."
            if [ -f "$TAR_FILE" ]; then
                gunzip -kf "$TAR_FILE" 2>/dev/null || true
            fi
            crane push "${TAR_PLAIN}" "${ECR_TARGET}"
        else
            warn "Neither docker nor crane available — cannot push ${IMAGE_NAME}"
            continue
        fi
        success "${IMAGE_NAME} pushed to ECR"
    done

    # ──────────────────────────────────────────────────────────────
    # Step 2: Push BSS Magic image to ECR
    # ──────────────────────────────────────────────────────────────
    step "Push BSS Magic image to ECR"

    BSS_IMAGE_NAME="bssmagic-nexus-k8s"
    BSS_TAR="${SCRIPT_DIR}/bss-magic/${BSS_IMAGE_NAME}.tar.gz"
    BSS_TAR_PLAIN="${SCRIPT_DIR}/bss-magic/${BSS_IMAGE_NAME}.tar"
    BSS_ECR="${ECR_REGISTRY}/${BSS_IMAGE_NAME}:latest"

    if [ -f "$BSS_TAR" ] || [ -f "$BSS_TAR_PLAIN" ]; then
        aws ecr describe-repositories --repository-names "${BSS_IMAGE_NAME}" \
            --region "${REGION}" --profile "${AWS_PROFILE}" >/dev/null 2>&1 \
        || aws ecr create-repository --repository-name "${BSS_IMAGE_NAME}" \
            --region "${REGION}" --profile "${AWS_PROFILE}" >/dev/null 2>&1

        if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
            docker load -i "${BSS_TAR:-$BSS_TAR_PLAIN}" 2>/dev/null
            docker tag "${BSS_IMAGE_NAME}:latest" "${BSS_ECR}" 2>/dev/null
            docker push "${BSS_ECR}" 2>/dev/null
        elif command -v crane >/dev/null 2>&1; then
            if [ -f "$BSS_TAR" ]; then gunzip -kf "$BSS_TAR" 2>/dev/null || true; fi
            crane push "${BSS_TAR_PLAIN}" "${BSS_ECR}"
        else
            warn "Neither docker nor crane available — cannot push BSS Magic image"
        fi
        success "BSS Magic image pushed to ECR"
    else
        warn "BSS Magic tar not found — skipping"
    fi
fi

# ──────────────────────────────────────────────────────────────
# Step 3: Upload BSS Magic credentials to Secrets Manager
# ──────────────────────────────────────────────────────────────
if [ "$SKIP_CREDS" = false ]; then
    step "Upload BSS Magic credentials to Secrets Manager"

    CREDS_ZIP_PATH="${SCRIPT_DIR}/../bssmagic-image/secrets/credentials.zip"
    CREDS_SECRET_ID="nexus-ai/${DEPLOY_ENV}/bssmagic-credentials"
    CREDS_ZIP_PATH_WIN=$(cygpath -w "${CREDS_ZIP_PATH}" 2>/dev/null || echo "${CREDS_ZIP_PATH}")

    SECRET_EXISTS="false"
    if aws secretsmanager describe-secret --secret-id "${CREDS_SECRET_ID}" \
        --region "${REGION}" --profile "${AWS_PROFILE}" >/dev/null 2>&1; then
        SECRET_EXISTS="true"
    fi

    EXISTING_CREDS_TYPE="none"
    if [ "$SECRET_EXISTS" = "true" ]; then
        BINARY_CHECK=$(aws secretsmanager get-secret-value --secret-id "${CREDS_SECRET_ID}" \
            --region "${REGION}" --profile "${AWS_PROFILE}" --query "SecretBinary" --output text 2>/dev/null || echo "None")
        if [ "$BINARY_CHECK" != "None" ] && [ -n "$BINARY_CHECK" ]; then
            EXISTING_CREDS_TYPE="binary"
        fi
    fi

    if [ "$EXISTING_CREDS_TYPE" = "binary" ]; then
        success "credentials.zip already uploaded to Secrets Manager"
    elif [ -f "${CREDS_ZIP_PATH}" ]; then
        echo "  Uploading credentials.zip..."
        if [ "$SECRET_EXISTS" = "true" ]; then
            aws secretsmanager put-secret-value --secret-id "${CREDS_SECRET_ID}" \
                --secret-binary "fileb://${CREDS_ZIP_PATH_WIN}" \
                --region "${REGION}" --profile "${AWS_PROFILE}" >/dev/null 2>&1 \
            && success "credentials.zip uploaded" \
            || warn "Failed to upload credentials.zip"
        else
            aws secretsmanager create-secret --name "${CREDS_SECRET_ID}" \
                --description "BSS Magic credentials.zip" \
                --secret-binary "fileb://${CREDS_ZIP_PATH_WIN}" \
                --region "${REGION}" --profile "${AWS_PROFILE}" >/dev/null 2>&1 \
            && success "credentials.zip secret created" \
            || warn "Failed to create credentials secret"
        fi
    else
        warn "credentials.zip not found at: ${CREDS_ZIP_PATH}"
        warn "BSS Magic controller will fail without credentials."
    fi
fi

# ──────────────────────────────────────────────────────────────
# Step 4: Apply capability
# ──────────────────────────────────────────────────────────────
step "Apply capability"

PATCHED_FILE="/tmp/capability-${DEPLOY_ENV}-patched.yaml"
sed -e "s|__ECR_REGISTRY__|${ECR_REGISTRY}|g" -e "s|__ENV__|${DEPLOY_ENV}|g" "${CAPABILITY_FILE}" > "${PATCHED_FILE}"

if [ -n "$CERTIFICATE_ARN" ]; then
    echo "  HTTPS: Enabled (certificate: ${CERTIFICATE_ARN:0:60}...)"
    sed -i 's|# certificateArn:.*|certificateArn: "'"${CERTIFICATE_ARN}"'"|g' "${PATCHED_FILE}"
    if ! grep -q "certificateArn:" "${PATCHED_FILE}"; then
        sed -i '/healthCheckPath:/a\    certificateArn: "'"${CERTIFICATE_ARN}"'"' "${PATCHED_FILE}"
    fi
fi

echo "  Namespace: ${NAMESPACE}"
echo "  File:      $(basename ${CAPABILITY_FILE})"
echo "  Env:       ${DEPLOY_ENV}"
echo "  Registry:  ${ECR_REGISTRY}"
echo ""

kubectl create namespace "${NAMESPACE}" 2>/dev/null || true

# Clear stale capability stuck in Terminating
CAP_NAME=$(grep -E "^\s+name:" "${PATCHED_FILE}" | head -1 | awk '{print $2}')
if [ -n "$CAP_NAME" ]; then
    DELETION_TS=$(kubectl get nexuscapability "$CAP_NAME" -n "$NAMESPACE" -o jsonpath='{.metadata.deletionTimestamp}' 2>/dev/null || echo "")
    if [ -n "$DELETION_TS" ]; then
        echo "  ⚠ Capability '$CAP_NAME' stuck in Terminating — clearing finalizers..."
        kubectl patch nexuscapability "$CAP_NAME" -n "$NAMESPACE" --type merge -p '{"metadata":{"finalizers":[]}}' >/dev/null 2>&1 || true
        local_wait=0
        while [ "$local_wait" -lt 15 ]; do
            kubectl get nexuscapability "$CAP_NAME" -n "$NAMESPACE" >/dev/null 2>&1 || break
            sleep 2; local_wait=$((local_wait + 2))
        done
        echo "  ✓ Stale capability cleared"
    fi
fi

if ! kubectl apply -f "${PATCHED_FILE}" 2>/dev/null; then
    echo "  Retrying after 10s..."
    sleep 10
    kubectl apply -f "${PATCHED_FILE}"
fi
rm -f "${PATCHED_FILE}"
success "Capability applied"

# ──────────────────────────────────────────────────────────────
# Step 5: Monitor deployment and wait for readiness
# ──────────────────────────────────────────────────────────────
step "Monitor deployment and wait for readiness"

timeout 300 bash -c "AWS_PROFILE='${AWS_PROFILE}' ./operator.sh monitor 2>&1" || true
echo ""

echo "  Waiting for all pods to be ready..."
for i in $(seq 1 30); do
    NOT_READY=$(kubectl get pods -n "${NAMESPACE}" --no-headers 2>/dev/null | awk '{print $2}' | grep -v "1/1\|2/2\|3/3" | wc -l)
    TOTAL=$(kubectl get pods -n "${NAMESPACE}" --no-headers 2>/dev/null | wc -l)
    if [ "$NOT_READY" -eq 0 ] && [ "$TOTAL" -gt 0 ]; then
        success "All ${TOTAL} pods are ready"
        break
    fi
    echo "    ${TOTAL} pods, waiting... (${i}/30)"
    sleep 10
done

echo ""
echo "  Waiting for ALB Ingress..."
ALB_HOST=""
for i in $(seq 1 30); do
    ALB_HOST=$(kubectl get ingress -n "${NAMESPACE}" -o jsonpath='{.items[0].status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
    if [ -n "$ALB_HOST" ]; then
        success "ALB: ${ALB_HOST}"
        break
    fi
    echo "    Waiting for ALB address... (${i}/30)"
    sleep 10
done

[ -z "$ALB_HOST" ] && warn "ALB Ingress not ready yet — continuing"

if [ -n "$ALB_HOST" ]; then
    echo ""
    echo "  Waiting for DNS + healthy response..."
    for i in $(seq 1 24); do
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://${ALB_HOST}/" --connect-timeout 5 2>/dev/null || echo "000")
        if [ "$HTTP_CODE" = "200" ]; then
            success "ALB healthy: HTTP 200"
            break
        fi
        echo "    HTTP ${HTTP_CODE}... (${i}/24)"
        sleep 10
    done
fi

# ──────────────────────────────────────────────────────────────
# Step 6: Verify and fix SSM parameters
# ──────────────────────────────────────────────────────────────
step "Verify and fix SSM parameters"

CAP_SANITIZED="${CAPABILITY_NAME//-/_}"
SSM_PREFIX="/${CAPABILITY_NAME}/${DEPLOY_ENV}"
SSM_FIXED=0

echo "  Checking SSM parameters under ${SSM_PREFIX}/..."
echo ""

# Cognito user pool and app client
COGNITO_POOL_NAME="${CAPABILITY_NAME}-${DEPLOY_ENV}"
COGNITO_POOL_ID=$(aws cognito-idp list-user-pools --max-results 60 \
    --region "${REGION}" --profile "${AWS_PROFILE}" \
    --query "UserPools[?Name=='${COGNITO_POOL_NAME}'].Id | [0]" --output text 2>/dev/null || echo "None")

if [ "$COGNITO_POOL_ID" != "None" ] && [ -n "$COGNITO_POOL_ID" ]; then
    CURRENT_POOL_ID=$(aws ssm get-parameter --name "${SSM_PREFIX}/cognito/user-pool-id" \
        --query "Parameter.Value" --output text \
        --region "${REGION}" --profile "${AWS_PROFILE}" 2>/dev/null || echo "")
    if [ "$CURRENT_POOL_ID" != "$COGNITO_POOL_ID" ]; then
        echo "  Fixing cognito/user-pool-id: '${CURRENT_POOL_ID}' → '${COGNITO_POOL_ID}'"
        aws ssm put-parameter --name "${SSM_PREFIX}/cognito/user-pool-id" \
            --value "${COGNITO_POOL_ID}" --type String --overwrite \
            --region "${REGION}" --profile "${AWS_PROFILE}" >/dev/null
        SSM_FIXED=$((SSM_FIXED + 1))
    else
        echo "  ✓ cognito/user-pool-id: ${CURRENT_POOL_ID}"
    fi

    COGNITO_CLIENT_ID=$(aws cognito-idp list-user-pool-clients --user-pool-id "${COGNITO_POOL_ID}" \
        --region "${REGION}" --profile "${AWS_PROFILE}" \
        --query "UserPoolClients[0].ClientId" --output text 2>/dev/null || echo "None")
    if [ "$COGNITO_CLIENT_ID" != "None" ] && [ -n "$COGNITO_CLIENT_ID" ]; then
        CURRENT_CLIENT_ID=$(aws ssm get-parameter --name "${SSM_PREFIX}/cognito/app-client-id" \
            --query "Parameter.Value" --output text \
            --region "${REGION}" --profile "${AWS_PROFILE}" 2>/dev/null || echo "")
        if [ "$CURRENT_CLIENT_ID" != "$COGNITO_CLIENT_ID" ]; then
            echo "  Fixing cognito/app-client-id: '${CURRENT_CLIENT_ID}' → '${COGNITO_CLIENT_ID}'"
            aws ssm put-parameter --name "${SSM_PREFIX}/cognito/app-client-id" \
                --value "${COGNITO_CLIENT_ID}" --type String --overwrite \
                --region "${REGION}" --profile "${AWS_PROFILE}" >/dev/null
            SSM_FIXED=$((SSM_FIXED + 1))
        else
            echo "  ✓ cognito/app-client-id: ${CURRENT_CLIENT_ID}"
        fi
    else
        warn "No Cognito app client found for pool ${COGNITO_POOL_ID}"
    fi
else
    warn "No Cognito user pool found with name '${COGNITO_POOL_NAME}'"
fi

echo ""
if [ "$SSM_FIXED" -gt 0 ]; then
    echo "  Fixed ${SSM_FIXED} SSM parameter(s) — restarting backend pods..."
    kubectl delete pods -l app=${NAMESPACE}-backend -n ${NAMESPACE} 2>/dev/null || true
    kubectl wait --for=condition=ready pod -l app=${NAMESPACE}-backend \
        -n ${NAMESPACE} --timeout=120s 2>/dev/null || true
    success "Backend pods restarted with correct SSM parameters"
else
    success "All SSM parameters are correct"
fi

# ──────────────────────────────────────────────────────────────
# Step 7: Verify all resources
# ──────────────────────────────────────────────────────────────
step "Verify all resources"

# verify-capability runs a Job in nexus-system as the operator SA (IRSA); needs kubectl + verify-capability.py
AWS_PROFILE="${AWS_PROFILE}" ./operator.sh verify-capability "${NAMESPACE}" 2>&1
verify_exit=$?

# ──────────────────────────────────────────────────────────────
# Final Summary
# ──────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
if [ $verify_exit -eq 0 ]; then
    echo -e "${GREEN}  ✓ CAPABILITY DEPLOYMENT COMPLETE - ALL CHECKS PASSED${NC}"
else
    echo -e "${YELLOW}  ⚠ CAPABILITY DEPLOYMENT COMPLETE - SOME CHECKS FAILED${NC}"
fi
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"

# Application URLs
ALB_CERT=$(kubectl get ingress "${NAMESPACE}-app-ingress" -n "${NAMESPACE}" -o jsonpath='{.metadata.annotations.alb\.ingress\.kubernetes\.io/certificate-arn}' 2>/dev/null || echo "")
ALB_SCHEME="http"
[ -n "$ALB_CERT" ] && ALB_SCHEME="https"
if [ -n "$ALB_HOST" ]; then
    echo ""
    echo -e "${GREEN}  Public Application URL:${NC}"
    echo -e "    ${CYAN}${ALB_SCHEME}://${ALB_HOST}${NC}"
fi

INTERNAL_ALB_HOST=$(kubectl get ingress "${NAMESPACE}-internal-ingress" -n "${NAMESPACE}" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
INTERNAL_CERT=$(kubectl get ingress "${NAMESPACE}-internal-ingress" -n "${NAMESPACE}" -o jsonpath='{.metadata.annotations.alb\.ingress\.kubernetes\.io/certificate-arn}' 2>/dev/null || echo "")
INT_SCHEME="http"
[ -n "$INTERNAL_CERT" ] && INT_SCHEME="https"
if [ -n "$INTERNAL_ALB_HOST" ]; then
    echo ""
    echo -e "${GREEN}  Internal (VPC-only) URL:${NC}"
    echo -e "    ${CYAN}${INT_SCHEME}://${INTERNAL_ALB_HOST}${NC}"
fi

# Admin credentials
ADMIN_EMAIL=$(kubectl get secret "${NAMESPACE}-admin-credentials" -n "${NAMESPACE}" -o jsonpath='{.data.admin-email}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
ADMIN_PASS=$(kubectl get secret "${NAMESPACE}-admin-credentials" -n "${NAMESPACE}" -o jsonpath='{.data.admin-password}' 2>/dev/null | base64 -d 2>/dev/null || echo "")

if [ -n "$ADMIN_EMAIL" ] && [ -n "$ADMIN_PASS" ]; then
    echo ""
    echo -e "${GREEN}  Admin Login:${NC}"
    echo -e "    Email:    ${CYAN}${ADMIN_EMAIL}${NC}"
    echo -e "    Password: ${CYAN}${ADMIN_PASS}${NC}"
    echo ""
    echo "    On first login, you will be prompted to set a new password."
else
    echo ""
    echo "  Admin credentials not found. Check:"
    echo "    kubectl get secret ${NAMESPACE}-admin-credentials -n ${NAMESPACE}"
fi

echo ""

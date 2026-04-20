#!/bin/bash
#
# End-to-End Deployment Script
#
# Performs a complete clean deployment cycle:
#   1. Delete existing operator (--full cleanup)
#   2. Ensure EBS CSI Driver (IAM role + EKS add-on for persistent storage)
#   3. Upload BSS Magic credentials.zip to Secrets Manager
#   4. Deploy operator
#   5. Apply capability (NexusCapability CR)
#   6. Monitor deployment progress
#   7. Verify and fix SSM parameters (Glue, Cognito)
#   8. Verify all resources
#
# Prerequisites:
#   Run ./create-ecr-images.sh first to push images to ECR.
#
# Reads defaults from .env.local (ENV, Branch, Cluster). CLI args override.
#
# Usage:
#   ./create-ecr-images.sh                   # Push images to ECR first
#   ./e2e-deploy.sh                          # Uses .env.local defaults (or prod if absent)
#   ./e2e-deploy.sh --env dev                # Deploy dev environment to starhub-dev cluster
#   ./e2e-deploy.sh --env stage              # Deploy stage environment to starhub-stage cluster
#   ./e2e-deploy.sh --env dev --cluster X    # Deploy dev to a custom cluster
#   ./e2e-deploy.sh --skip-clean             # Skip delete step
#   ./e2e-deploy.sh --skip-app-images        # Skip loading/pushing CallSense app images
#   ./e2e-deploy.sh --skip-bssmagic-image    # Skip loading/pushing BSS Magic image
#   ./e2e-deploy.sh --capability my-cap.yaml # Use custom capability file
#   ./e2e-deploy.sh --help                   # Show help

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load defaults from .env.local (CLI args and env vars override these)
_ENVLOCAL="${SCRIPT_DIR}/.env.local"
if [ -f "$_ENVLOCAL" ]; then
    _ENV_LOCAL_ENV=$(grep '^ENV=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- || true)
    _ENV_LOCAL_BRANCH=$(grep '^Branch=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- || true)
    _ENV_LOCAL_CLUSTER=$(grep '^Cluster=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- || true)
    _ENV_LOCAL_CERT=$(grep '^CertificateArn=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- || true)
fi

# Defaults
SKIP_CLEAN=false
CAPABILITY_FILE="${SCRIPT_DIR}/examples/call-processing-complete.yaml"
AWS_PROFILE="${AWS_PROFILE:-external-access}"
DEPLOY_ENV="${DEPLOY_ENV:-${_ENV_LOCAL_ENV:-prod}}"
CLUSTER_NAME="${CLUSTER_NAME:-${_ENV_LOCAL_CLUSTER:-}}"
GIT_BRANCH="${GIT_BRANCH:-${_ENV_LOCAL_BRANCH:-}}"
CERTIFICATE_ARN="${CERTIFICATE_ARN:-${_ENV_LOCAL_CERT:-}}"
CLUSTER_EXPLICIT=false

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

step_num=0
total_steps=8

step() {
    step_num=$((step_num + 1))
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  Step ${step_num}/${total_steps}: $1${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════════${NC}"
    echo ""
}

success() {
    echo -e "${GREEN}  ✓ $1${NC}"
}

fail() {
    echo -e "${RED}  ✗ $1${NC}"
    exit 1
}

warn() {
    echo -e "${YELLOW}  ⚠ $1${NC}"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-clean)
            SKIP_CLEAN=true
            shift
            ;;
        --env)
            DEPLOY_ENV="$2"
            shift 2
            ;;
        --cluster)
            CLUSTER_NAME="$2"
            CLUSTER_EXPLICIT=true
            shift 2
            ;;
        --capability)
            CAPABILITY_FILE="$2"
            shift 2
            ;;
        --cert|--certificate)
            CERTIFICATE_ARN="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --env ENV              Target environment: dev, stage, prod (default: prod)"
            echo "  --cluster NAME         EKS cluster name (default: starhub-{env}, prod=starhub-test)"
            echo "  --skip-clean           Skip the delete/cleanup step"
            echo "  --capability FILE      Use custom capability YAML"
            echo "  --cert ARN             ACM certificate ARN for HTTPS (enables SSL + redirect)"
            echo "  --help                 Show this help"
            echo ""
            echo "Environment Variables:"
            echo "  AWS_PROFILE            AWS profile (default: external-access)"
            echo "  DEPLOY_ENV             Target environment (same as --env)"
            echo "  CLUSTER_NAME           EKS cluster name (same as --cluster)"
            echo ""
            echo "Prerequisites:"
            echo "  Run ./create-ecr-images.sh first to push images to ECR."
            echo ""
            echo "Examples:"
            echo "  $0                                    # Full E2E (prod on starhub-test)"
            echo "  $0 --env dev                          # Deploy dev to starhub-dev cluster"
            echo "  $0 --env stage                        # Deploy stage to starhub-stage cluster"
            echo "  $0 --env dev --cluster my-cluster     # Deploy dev to custom cluster"
            echo "  $0 --skip-clean                       # Redeploy without cleanup"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# ──────────────────────────────────────────────────────────────
# Resolve AWS account and region
# ──────────────────────────────────────────────────────────────
CURRENT_ACCOUNT=$(aws sts get-caller-identity --profile "${AWS_PROFILE}" --query 'Account' --output text 2>/dev/null || true)
if [ -z "$CURRENT_ACCOUNT" ]; then
    fail "Failed to get AWS account ID from profile '${AWS_PROFILE}'. Are you logged in?"
fi

# Detect region from existing EKS cluster or default
REGION=$(aws configure get region --profile "${AWS_PROFILE}" 2>/dev/null || echo "us-east-1")
ECR_REGISTRY="${CURRENT_ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

# Resolve cluster name from --env convention (if not explicitly provided via --cluster)
if [ "$CLUSTER_EXPLICIT" = true ]; then
    : # --cluster was given explicitly, use as-is
elif [ -n "$CLUSTER_NAME" ]; then
    : # CLUSTER_NAME set via env var, use as-is
else
    case "$DEPLOY_ENV" in
        prod) CLUSTER_NAME="starhub-test" ;;
        *)    CLUSTER_NAME="starhub-${DEPLOY_ENV}" ;;
    esac
fi
export CLUSTER_NAME
export DEPLOY_ENV
export REGION

# Switch kubeconfig to target cluster
aws eks update-kubeconfig \
    --name "${CLUSTER_NAME}" \
    --region "${REGION}" \
    --profile "${AWS_PROFILE}" 2>/dev/null \
|| fail "Failed to update kubeconfig for cluster '${CLUSTER_NAME}'. Does it exist?"

# Adjust step count
if [ "$SKIP_CLEAN" = true ]; then
    total_steps=$((total_steps - 1))
fi

cd "${SCRIPT_DIR}"

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  CallSense + BSS Magic E2E Deployment${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
echo ""
echo "  Environment:    ${DEPLOY_ENV}"
echo "  AWS Profile:    ${AWS_PROFILE}"
echo "  AWS Account:    ${CURRENT_ACCOUNT}"
echo "  Region:         ${REGION}"
echo "  Cluster:        ${CLUSTER_NAME}"
echo "  ECR Registry:   ${ECR_REGISTRY}"
echo "  Capability:     ${CAPABILITY_FILE}"
echo "  Skip Clean:     ${SKIP_CLEAN}"
echo ""

# ──────────────────────────────────────────────────────────────
# Step 1: Clean (optional)
# ──────────────────────────────────────────────────────────────
if [ "$SKIP_CLEAN" = false ]; then
    step "Delete existing operator (full cleanup)"
    
    AWS_PROFILE="${AWS_PROFILE}" ./operator-nexus-dev.sh delete --full --keep-ecr --keep-iam 2>&1 || true
    success "Cleanup complete"
    
    # Refresh kubeconfig after delete (access entry was removed)
    echo "  Refreshing kubeconfig..."
    AWS_PROFILE="${AWS_PROFILE}" aws eks update-kubeconfig \
        --name "${CLUSTER_NAME}" \
        --region "${REGION}" \
        --profile "${AWS_PROFILE}" 2>/dev/null || true
    
    echo "  Waiting 10s for cluster state to settle..."
    sleep 10
fi

# ──────────────────────────────────────────────────────────────
# Step 2: Ensure EBS CSI Driver (required for BSS Magic PVC)
# ──────────────────────────────────────────────────────────────
step "Ensure EBS CSI Driver for persistent storage"

# Check if EBS CSI Driver add-on already exists and is active
EBS_CSI_STATUS=$(aws eks describe-addon --cluster-name "${CLUSTER_NAME}" --addon-name aws-ebs-csi-driver \
    --query "addon.status" --output text --region "${REGION}" --profile "${AWS_PROFILE}" 2>/dev/null || echo "NOT_FOUND")

if [ "$EBS_CSI_STATUS" = "ACTIVE" ]; then
    success "EBS CSI Driver already active"
else
    echo "  EBS CSI Driver status: ${EBS_CSI_STATUS}"
    echo "  Setting up EBS CSI Driver with IRSA..."

    # Get OIDC provider ID
    OIDC_URL=$(aws eks describe-cluster --name "${CLUSTER_NAME}" --region "${REGION}" --profile "${AWS_PROFILE}" \
        --query "cluster.identity.oidc.issuer" --output text 2>/dev/null)
    OIDC_ID=$(echo "$OIDC_URL" | awk -F'/' '{print $NF}')

    if [ -z "$OIDC_ID" ]; then
        fail "Could not get OIDC provider ID for cluster ${CLUSTER_NAME}"
    fi
    echo "  OIDC Provider ID: ${OIDC_ID}"

    # Ensure OIDC provider is registered in IAM (may already be done by fix-irsa)
    OIDC_ARN="arn:aws:iam::${CURRENT_ACCOUNT}:oidc-provider/oidc.eks.${REGION}.amazonaws.com/id/${OIDC_ID}"
    if ! aws iam get-open-id-connect-provider --open-id-connect-provider-arn "${OIDC_ARN}" \
        --profile "${AWS_PROFILE}" >/dev/null 2>&1; then
        echo "  Registering OIDC provider in IAM..."
        aws iam create-open-id-connect-provider \
            --url "${OIDC_URL}" \
            --client-id-list sts.amazonaws.com \
            --thumbprint-list "9e99a48a9960b14926bb7f3b02e22da2b0ab7280" \
            --profile "${AWS_PROFILE}" >/dev/null 2>&1 || true
    fi

    # Create IAM role for EBS CSI Driver (idempotent — handles race conditions)
    EBS_CSI_ROLE_NAME="AmazonEKS_EBS_CSI_DriverRole"
    TRUST_POLICY=$(cat <<TRUSTEOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "${OIDC_ARN}"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "oidc.eks.${REGION}.amazonaws.com/id/${OIDC_ID}:aud": "sts.amazonaws.com",
        "oidc.eks.${REGION}.amazonaws.com/id/${OIDC_ID}:sub": "system:serviceaccount:kube-system:ebs-csi-controller-sa"
      }
    }
  }]
}
TRUSTEOF
    )
    if aws iam get-role --role-name "${EBS_CSI_ROLE_NAME}" --profile "${AWS_PROFILE}" >/dev/null 2>&1; then
        echo "  IAM role ${EBS_CSI_ROLE_NAME} already exists, updating trust policy"
        aws iam update-assume-role-policy \
            --role-name "${EBS_CSI_ROLE_NAME}" \
            --policy-document "${TRUST_POLICY}" \
            --profile "${AWS_PROFILE}" 2>/dev/null || true
    else
        echo "  Creating IAM role: ${EBS_CSI_ROLE_NAME}..."
        aws iam create-role \
            --role-name "${EBS_CSI_ROLE_NAME}" \
            --assume-role-policy-document "${TRUST_POLICY}" \
            --description "IRSA role for EBS CSI Driver on EKS cluster ${CLUSTER_NAME}" \
            --tags "Key=Capability,Value=call-processing" "Key=Environment,Value=${DEPLOY_ENV}" "Key=managed-by,Value=nexus-operator" \
            --profile "${AWS_PROFILE}" >/dev/null 2>&1 || {
                echo "  Role may already exist (IAM propagation delay) — continuing"
            }
    fi

    aws iam attach-role-policy \
        --role-name "${EBS_CSI_ROLE_NAME}" \
        --policy-arn "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy" \
        --profile "${AWS_PROFILE}" 2>/dev/null || true

    success "IAM role ${EBS_CSI_ROLE_NAME} ready"

    EBS_CSI_ROLE_ARN="arn:aws:iam::${CURRENT_ACCOUNT}:role/${EBS_CSI_ROLE_NAME}"

    # Delete stuck add-on if it's in a bad state (CREATING/DEGRADED)
    if [ "$EBS_CSI_STATUS" != "NOT_FOUND" ] && [ "$EBS_CSI_STATUS" != "ACTIVE" ]; then
        echo "  Removing stuck EBS CSI add-on (status: ${EBS_CSI_STATUS})..."
        aws eks delete-addon --cluster-name "${CLUSTER_NAME}" --addon-name aws-ebs-csi-driver \
            --region "${REGION}" --profile "${AWS_PROFILE}" >/dev/null 2>&1 || true
        echo "  Waiting 30s for deletion..."
        sleep 30
    fi

    # Install the add-on
    if [ "$EBS_CSI_STATUS" = "NOT_FOUND" ] || [ "$EBS_CSI_STATUS" != "ACTIVE" ]; then
        echo "  Installing aws-ebs-csi-driver add-on..."
        aws eks create-addon \
            --cluster-name "${CLUSTER_NAME}" \
            --addon-name aws-ebs-csi-driver \
            --service-account-role-arn "${EBS_CSI_ROLE_ARN}" \
            --region "${REGION}" --profile "${AWS_PROFILE}" >/dev/null

        # Wait for ACTIVE (up to 3 minutes)
        echo "  Waiting for EBS CSI Driver to become ACTIVE..."
        for i in $(seq 1 18); do
            CSI_STATUS=$(aws eks describe-addon --cluster-name "${CLUSTER_NAME}" --addon-name aws-ebs-csi-driver \
                --query "addon.status" --output text --region "${REGION}" --profile "${AWS_PROFILE}" 2>/dev/null || echo "UNKNOWN")
            if [ "$CSI_STATUS" = "ACTIVE" ]; then
                success "EBS CSI Driver is ACTIVE"
                break
            fi
            echo "    Status: ${CSI_STATUS} (${i}/18)"
            sleep 10
        done

        if [ "$CSI_STATUS" != "ACTIVE" ]; then
            warn "EBS CSI Driver not yet ACTIVE (status: ${CSI_STATUS}). BSS Magic PVC may be delayed."
        fi
    fi
fi

# Ensure gp2 StorageClass is marked as default
SC_DEFAULT=$(kubectl get storageclass gp2 -o jsonpath='{.metadata.annotations.storageclass\.kubernetes\.io/is-default-class}' 2>/dev/null || echo "")
if [ "$SC_DEFAULT" != "true" ]; then
    echo "  Marking gp2 StorageClass as default..."
    kubectl annotate storageclass gp2 storageclass.kubernetes.io/is-default-class=true --overwrite 2>/dev/null || true
fi
success "Storage prerequisites ready (EBS CSI + gp2 StorageClass)"

# ──────────────────────────────────────────────────────────────
# Step 3: Upload BSS Magic credentials.zip to Secrets Manager
# ──────────────────────────────────────────────────────────────
step "Upload BSS Magic credentials to Secrets Manager"

CREDS_ZIP_PATH="${SCRIPT_DIR}/../bssmagic-image/secrets/credentials.zip"
CREDS_SECRET_ID="call-processing/${DEPLOY_ENV}/bssmagic-credentials"

# Convert to Windows path for AWS CLI fileb:// (Git Bash paths don't work with fileb://)
CREDS_ZIP_PATH_WIN=$(cygpath -w "${CREDS_ZIP_PATH}" 2>/dev/null || echo "${CREDS_ZIP_PATH}")

# Check if secret exists at all
SECRET_EXISTS="false"
if aws secretsmanager describe-secret --secret-id "${CREDS_SECRET_ID}" \
    --region "${REGION}" --profile "${AWS_PROFILE}" >/dev/null 2>&1; then
    SECRET_EXISTS="true"
fi

# Check if it already has real binary content (not a placeholder)
EXISTING_CREDS_TYPE="none"
if [ "$SECRET_EXISTS" = "true" ]; then
    # Try to get binary content size
    BINARY_CHECK=$(aws secretsmanager get-secret-value --secret-id "${CREDS_SECRET_ID}" \
        --region "${REGION}" --profile "${AWS_PROFILE}" --query "SecretBinary" --output text 2>/dev/null || echo "None")
    if [ "$BINARY_CHECK" != "None" ] && [ -n "$BINARY_CHECK" ]; then
        EXISTING_CREDS_TYPE="binary"
    else
        EXISTING_CREDS_TYPE="placeholder"
    fi
fi

if [ "$EXISTING_CREDS_TYPE" = "binary" ]; then
    success "credentials.zip already uploaded to Secrets Manager"
elif [ -f "${CREDS_ZIP_PATH}" ]; then
    echo "  Uploading credentials.zip..."
    echo "  File: ${CREDS_ZIP_PATH_WIN}"

    if [ "$SECRET_EXISTS" = "true" ]; then
        # Secret exists (placeholder) — update with binary
        aws secretsmanager put-secret-value --secret-id "${CREDS_SECRET_ID}" \
            --secret-binary "fileb://${CREDS_ZIP_PATH_WIN}" \
            --region "${REGION}" --profile "${AWS_PROFILE}" >/dev/null 2>&1 \
        && success "credentials.zip uploaded to Secrets Manager" \
        || { warn "Failed to upload credentials.zip — will retry during operator deploy"; }
    else
        # Secret doesn't exist — create with binary
        aws secretsmanager create-secret --name "${CREDS_SECRET_ID}" \
            --description "BSS Magic credentials.zip" \
            --secret-binary "fileb://${CREDS_ZIP_PATH_WIN}" \
            --region "${REGION}" --profile "${AWS_PROFILE}" >/dev/null 2>&1 \
        && success "credentials.zip secret created in Secrets Manager" \
        || { warn "Failed to create credentials secret — will be created during operator deploy"; }
    fi
else
    warn "credentials.zip not found at: ${CREDS_ZIP_PATH}"
    warn "BSS Magic controller will fail without credentials."
    warn "To fix: copy credentials.zip to starhub-deployer/bssmagic-image/secrets/"
fi

# ──────────────────────────────────────────────────────────────
# Step 4: Deploy operator
# ──────────────────────────────────────────────────────────────
step "Deploy operator (IRSA + ALB Controller)"

AWS_PROFILE="${AWS_PROFILE}" ./operator-nexus-dev.sh deploy 2>&1
deploy_exit=$?
if [ $deploy_exit -ne 0 ]; then
    fail "Operator deployment failed (exit code: $deploy_exit)"
fi
success "Operator deployed"

# Ensure CRD is up to date (supports internalIngress, latest schema)
echo ""
echo "  Updating CRD..."
CRD_DEL_TS=$(kubectl get crd nexuscapabilities.nexus.ai -o jsonpath='{.metadata.deletionTimestamp}' 2>/dev/null || echo "")
if [ -n "$CRD_DEL_TS" ]; then
    echo "  CRD is stuck in Terminating — clearing finalizers and recreating..."
    kubectl patch crd nexuscapabilities.nexus.ai --type=json -p='[{"op":"remove","path":"/metadata/finalizers"}]' 2>/dev/null || true
    sleep 5
    kubectl apply -f "${SCRIPT_DIR}/manifests/crd.yaml" 2>/dev/null || kubectl create -f "${SCRIPT_DIR}/manifests/crd.yaml" 2>/dev/null || true
else
    kubectl apply -f "${SCRIPT_DIR}/manifests/crd.yaml" 2>/dev/null || kubectl replace -f "${SCRIPT_DIR}/manifests/crd.yaml" 2>/dev/null || kubectl create -f "${SCRIPT_DIR}/manifests/crd.yaml" 2>/dev/null || true
fi
success "CRD ready"

# ──────────────────────────────────────────────────────────────
# Step 5: Apply capability
# ──────────────────────────────────────────────────────────────
step "Apply capability"

# Substitute __ECR_REGISTRY__ and __ENV__ placeholders
PATCHED_FILE="/tmp/capability-${DEPLOY_ENV}-patched.yaml"
sed -e "s|__ECR_REGISTRY__|${ECR_REGISTRY}|g" -e "s|__ENV__|${DEPLOY_ENV}|g" "${CAPABILITY_FILE}" > "${PATCHED_FILE}"

# Inject ACM certificate ARN for HTTPS if provided
if [ -n "$CERTIFICATE_ARN" ]; then
    echo "  HTTPS:     Enabled (certificate: ${CERTIFICATE_ARN:0:60}...)"
    sed -i 's|# certificateArn:.*|certificateArn: "'"${CERTIFICATE_ARN}"'"|g' "${PATCHED_FILE}"
    if ! grep -q "certificateArn:" "${PATCHED_FILE}"; then
        sed -i '/healthCheckPath:/a\    certificateArn: "'"${CERTIFICATE_ARN}"'"' "${PATCHED_FILE}"
    fi
fi

# Extract namespace from patched YAML
NAMESPACE=$(grep -E "^\s+namespace:" "${PATCHED_FILE}" | head -1 | awk '{print $2}')
if [ -z "$NAMESPACE" ]; then
    NAMESPACE="default"
fi

echo "  Namespace: ${NAMESPACE}"
echo "  File:      ${CAPABILITY_FILE}"
echo "  Env:       ${DEPLOY_ENV}"
echo "  Registry:  ${ECR_REGISTRY}"
echo ""

# Create namespace if needed
kubectl create namespace "${NAMESPACE}" 2>/dev/null || true

# Ensure no stale NexusCapability is stuck in Terminating state
CAP_NAME=$(grep -E "^\s+name:" "${PATCHED_FILE}" | head -1 | awk '{print $2}')
if [ -n "$CAP_NAME" ]; then
    DELETION_TS=$(kubectl get nexuscapability "$CAP_NAME" -n "$NAMESPACE" -o jsonpath='{.metadata.deletionTimestamp}' 2>/dev/null || echo "")
    if [ -n "$DELETION_TS" ]; then
        echo "  ⚠ Existing capability '$CAP_NAME' is stuck in Terminating (since $DELETION_TS)"
        echo "  Clearing finalizers to allow fresh creation..."
        kubectl patch nexuscapability "$CAP_NAME" -n "$NAMESPACE" --type merge -p '{"metadata":{"finalizers":[]}}' > /dev/null 2>&1 || true
        local_wait=0
        while [ "$local_wait" -lt 15 ]; do
            kubectl get nexuscapability "$CAP_NAME" -n "$NAMESPACE" > /dev/null 2>&1 || break
            sleep 2
            local_wait=$((local_wait + 2))
        done
        echo "  ✓ Stale capability cleared"
    fi
fi

if ! kubectl apply -f "${PATCHED_FILE}" 2>/dev/null; then
    echo "  Retrying after 10s (CRD may still be initializing)..."
    sleep 10
    kubectl apply -f "${PATCHED_FILE}"
fi
rm -f "${PATCHED_FILE}"
success "Capability applied"

# ──────────────────────────────────────────────────────────────
# Step 6: Monitor deployment + wait for readiness
# ──────────────────────────────────────────────────────────────
step "Monitor deployment and wait for readiness"

# Monitor with timeout
timeout 300 bash -c "AWS_PROFILE='${AWS_PROFILE}' ./operator-nexus-dev.sh monitor 2>&1" || true
echo ""

# Wait for all pods to be ready
echo "  Waiting for all pods to be ready..."
for i in $(seq 1 30); do
    READY=$(kubectl get pods -n "${NAMESPACE}" --no-headers 2>/dev/null | awk '{print $2}' | grep -v "1/1\|2/2\|3/3" | wc -l)
    TOTAL=$(kubectl get pods -n "${NAMESPACE}" --no-headers 2>/dev/null | wc -l)
    if [ "$READY" -eq 0 ] && [ "$TOTAL" -gt 0 ]; then
        success "All ${TOTAL} pods are ready"
        break
    fi
    echo "    ${TOTAL} pods found, waiting for all to be ready... (${i}/30)"
    sleep 10
done

# Wait for ALB Ingress to get an address
echo ""
echo "  Waiting for ALB Ingress to be provisioned..."
ALB_HOST=""
for i in $(seq 1 30); do
    ALB_HOST=$(kubectl get ingress -n "${NAMESPACE}" -o jsonpath='{.items[0].status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
    if [ -n "$ALB_HOST" ]; then
        success "ALB created: ${ALB_HOST}"
        break
    fi
    echo "    Waiting for ALB address... (${i}/30)"
    sleep 10
done

if [ -z "$ALB_HOST" ]; then
    warn "ALB Ingress not ready yet - continuing with verify"
fi

# Wait for ALB DNS propagation
if [ -n "$ALB_HOST" ]; then
    echo ""
    echo "  Waiting for DNS propagation..."
    for i in $(seq 1 18); do
        if nslookup "$ALB_HOST" >/dev/null 2>&1; then
            success "DNS resolved"
            break
        fi
        echo "    DNS not ready... (${i}/18)"
        sleep 10
    done
    
    # Wait for ALB to become active with healthy targets (HTTP 200)
    echo ""
    echo "  Waiting for ALB healthy response (HTTP 200)..."
    ALB_HEALTHY=false
    for i in $(seq 1 24); do
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://${ALB_HOST}/" --connect-timeout 5 2>/dev/null || echo "000")
        if [ "$HTTP_CODE" = "200" ]; then
            success "ALB healthy: HTTP ${HTTP_CODE}"
            ALB_HEALTHY=true
            break
        fi
        if [ "$HTTP_CODE" = "000" ]; then
            echo "    ALB not reachable yet... (${i}/24)"
        else
            echo "    ALB returned HTTP ${HTTP_CODE} (targets may still be registering)... (${i}/24)"
        fi
        sleep 10
    done
    if [ "$ALB_HEALTHY" = false ]; then
        warn "ALB did not return HTTP 200 within timeout. Last response: HTTP ${HTTP_CODE}"
        warn "Target groups may need more time to register. Check: aws elbv2 describe-target-health"
    fi
fi

# ──────────────────────────────────────────────────────────────
# Step 7: Verify and fix SSM parameters
# ──────────────────────────────────────────────────────────────
step "Verify and fix SSM parameters"

CAPABILITY_NAME="call-processing"
CAP_SANITIZED="${CAPABILITY_NAME//-/_}"
SSM_PREFIX="/${CAPABILITY_NAME}/${DEPLOY_ENV}"
SSM_FIXED=0

EXPECTED_GLUE_DB="${CAP_SANITIZED}_${DEPLOY_ENV}_db"
EXPECTED_GLUE_TABLE="${CAP_SANITIZED}_${DEPLOY_ENV}_call_records"

echo "  Checking SSM parameters under ${SSM_PREFIX}/..."
echo ""

# --- Glue database ---
CURRENT_GLUE_DB=$(aws ssm get-parameter --name "${SSM_PREFIX}/glue/database" \
    --query "Parameter.Value" --output text \
    --region "${REGION}" --profile "${AWS_PROFILE}" 2>/dev/null || echo "")
if [ "$CURRENT_GLUE_DB" != "$EXPECTED_GLUE_DB" ]; then
    echo "  Fixing glue/database: '${CURRENT_GLUE_DB}' → '${EXPECTED_GLUE_DB}'"
    aws ssm put-parameter --name "${SSM_PREFIX}/glue/database" \
        --value "${EXPECTED_GLUE_DB}" --type String --overwrite \
        --region "${REGION}" --profile "${AWS_PROFILE}" >/dev/null
    SSM_FIXED=$((SSM_FIXED + 1))
else
    echo "  ✓ glue/database: ${CURRENT_GLUE_DB}"
fi

# --- Glue table ---
CURRENT_GLUE_TABLE=$(aws ssm get-parameter --name "${SSM_PREFIX}/glue/table" \
    --query "Parameter.Value" --output text \
    --region "${REGION}" --profile "${AWS_PROFILE}" 2>/dev/null || echo "")
if [ "$CURRENT_GLUE_TABLE" != "$EXPECTED_GLUE_TABLE" ]; then
    echo "  Fixing glue/table: '${CURRENT_GLUE_TABLE}' → '${EXPECTED_GLUE_TABLE}'"
    aws ssm put-parameter --name "${SSM_PREFIX}/glue/table" \
        --value "${EXPECTED_GLUE_TABLE}" --type String --overwrite \
        --region "${REGION}" --profile "${AWS_PROFILE}" >/dev/null
    SSM_FIXED=$((SSM_FIXED + 1))
else
    echo "  ✓ glue/table: ${CURRENT_GLUE_TABLE}"
fi

# --- Cognito user pool and app client ---
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
# Step 8: Verify all resources
# ──────────────────────────────────────────────────────────────
step "Verify all resources"

AWS_PROFILE="${AWS_PROFILE}" ./operator-nexus-dev.sh verify-capability "${NAMESPACE}" 2>&1
verify_exit=$?

# ──────────────────────────────────────────────────────────────
# Final Summary with login credentials
# ──────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"
if [ $verify_exit -eq 0 ]; then
    echo -e "${GREEN}  ✓ E2E DEPLOYMENT COMPLETE - ALL CHECKS PASSED${NC}"
else
    echo -e "${YELLOW}  ⚠ E2E DEPLOYMENT COMPLETE - SOME CHECKS FAILED${NC}"
fi
echo -e "${GREEN}═══════════════════════════════════════════════════════════════════${NC}"

# Show application URLs (public + internal if present), detect HTTPS
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

# Show admin login credentials
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

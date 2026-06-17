#!/bin/bash
#
# Full Capability Cleanup Script
# Completely removes all Kubernetes and AWS resources for a capability.
# Dry run by default — requires --confirm to actually delete.
# Reads defaults from .env.local when run from a dev machine.
#
# Local / jumpbox: uses AWS_PROFILE and aws eks update-kubeconfig.
#
# In-cluster (operator pod + IRSA): detected when KUBERNETES_SERVICE_HOST is set;
# uses default AWS credential chain and in-cluster kubectl. Requires aws CLI +
# kubectl in the image (see kube-operator Dockerfile). Use -it for --confirm
# so the confirmation prompt works:
#
#   kubectl exec -n nexus-system -it deploy/nexus-operator -- \
#     env DEPLOY_ENV=stage /bin/bash /app/cleanup-capability.sh --confirm
#
# Usage:
#   ./cleanup-capability.sh                          # Dry run
#   ./cleanup-capability.sh --confirm                # Delete (interactive confirm)
#   ./cleanup-capability.sh --env dev --confirm
#   ./cleanup-capability.sh --local ...              # Force profile mode in a pod
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

_ENVLOCAL="${SCRIPT_DIR}/.env.local"
if [ -f "$_ENVLOCAL" ]; then
    _ENV_LOCAL_ENV=$(grep '^ENV[[:space:]]*=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true)
    _ENV_LOCAL_CLUSTER=$(grep '^Cluster[[:space:]]*=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true)
fi

DEPLOY_ENV="${DEPLOY_ENV:-${_ENV_LOCAL_ENV:-prod}}"
CLUSTER_NAME="${CLUSTER_NAME:-${_ENV_LOCAL_CLUSTER:-nexus-test}}"
REGION="${REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-external-access}"
INSPECT_FORCE_LOCAL="${INSPECT_FORCE_LOCAL:-0}"
CONFIRM=false

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
log_fail() { echo -e "  ${RED}✗${NC} $1"; }
log_warn() { echo -e "  ${YELLOW}!${NC} $1"; }
log_info() { echo -e "  ${CYAN}→${NC} $1"; }
log_dry()  { echo -e "  ${YELLOW}[DRY]${NC} Would delete: $1"; }

while [[ $# -gt 0 ]]; do
    case $1 in
        --confirm) CONFIRM=true; shift ;;
        --env)     DEPLOY_ENV="$2"; shift 2 ;;
        --cluster) CLUSTER_NAME="$2"; shift 2 ;;
        --local)   INSPECT_FORCE_LOCAL=1; shift ;;
        --help|-h)
            echo "Full Capability Cleanup"
            echo ""
            echo "Completely removes all Kubernetes and AWS resources for a capability."
            echo "DRY RUN by default — use --confirm to actually delete."
            echo ""
            echo "Usage:"
            echo "  $0 [--local] [--env ENV] [--cluster NAME] [--confirm]"
            echo ""
            echo "Options:"
            echo "  --confirm        Actually perform deletions (required)"
            echo "  --env ENV        Target environment (default: from .env.local)"
            echo "  --cluster NAME   EKS cluster name (local mode only)"
            echo "  --local          Force AWS profile + kubeconfig (not IRSA)"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

USE_AWS_PROFILE=1
RUN_MODE="local"
if [ -n "${KUBERNETES_SERVICE_HOST:-}" ] && [ "${INSPECT_FORCE_LOCAL}" != "1" ]; then
    USE_AWS_PROFILE=0
    RUN_MODE="in-cluster"
    REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-${REGION}}}"
    CLUSTER_NAME="${EKS_CLUSTER_NAME:-${CLUSTER_NAME}}"
fi

CAP="nexus-ai"
NS="${CAP}-${DEPLOY_ENV}"
CAP_US="${CAP//-/_}_${DEPLOY_ENV//-/_}"

# Timeout wrapper for AWS CLI (prevents hanging on unreachable services)
AWS_TIMEOUT=10
taws() {
    if [ "${USE_AWS_PROFILE}" = "1" ]; then
        timeout "${AWS_TIMEOUT}" aws "$@" --profile "${AWS_PROFILE}"
    else
        timeout "${AWS_TIMEOUT}" aws "$@"
    fi
}

echo ""
echo -e "${RED}================================================================${NC}"
if [ "$CONFIRM" = true ]; then
    echo -e "${RED}  FULL CAPABILITY CLEANUP (DESTRUCTIVE)${NC}"
else
    echo -e "${YELLOW}  FULL CAPABILITY CLEANUP (DRY RUN)${NC}"
fi
echo -e "${RED}================================================================${NC}"
echo ""
echo "  Mode:        ${RUN_MODE}"
echo "  Capability:  ${CAP}"
echo "  Environment: ${DEPLOY_ENV}"
echo "  Namespace:   ${NS}"
echo "  Cluster:     ${CLUSTER_NAME}"
echo "  Region:      ${REGION}"
echo ""

if [ "$CONFIRM" = true ]; then
    echo -e "  ${RED}WARNING: This will permanently destroy ALL data and resources!${NC}"
    echo ""
    read -rp "  Type the environment name to confirm (${DEPLOY_ENV}): " typed_env
    if [ "$typed_env" != "$DEPLOY_ENV" ]; then
        echo "  Aborted — confirmation did not match."
        exit 1
    fi
    echo ""
fi

if [ "${USE_AWS_PROFILE}" = "1" ]; then
    aws eks update-kubeconfig --name "${CLUSTER_NAME}" --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1 || true
    ACCOUNT_ID=$(timeout 15 aws sts get-caller-identity --profile "${AWS_PROFILE}" --query Account --output text 2>/dev/null || echo "")
else
    ACCOUNT_ID=$(timeout 15 aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")
fi

export CLEANUP_USE_AWS_PROFILE="${USE_AWS_PROFILE}"

DELETED=0
SKIPPED=0
FAILED=0

do_delete() {
    local LABEL="$1"
    shift
    if [ "$CONFIRM" = true ]; then
        if "$@" > /dev/null 2>&1; then
            log_ok "Deleted: ${LABEL}"
            DELETED=$((DELETED+1))
        else
            log_info "Already deleted: ${LABEL}"
        fi
    else
        log_dry "${LABEL}"
        SKIPPED=$((SKIPPED+1))
    fi
}

# ──────────────────────────────────────────────────────────────
# Step 1: Delete Ingresses + ALBs (before namespace)
# ──────────────────────────────────────────────────────────────
echo -e "${CYAN}── Step 1: Ingresses & ALB Load Balancers ──${NC}"

if kubectl get ns "${NS}" > /dev/null 2>&1; then
    if [ "$CONFIRM" = true ]; then
        log_info "Removing finalizers from NexusCapability CRs..."
        for CR in $(kubectl get nexuscapability -n "${NS}" -o name 2>/dev/null); do
            kubectl patch "$CR" -n "${NS}" --type=json -p='[{"op":"remove","path":"/metadata/finalizers"}]' 2>/dev/null || true
        done

        log_info "Deleting ingresses first (triggers ALB cleanup)..."
        kubectl delete ingress --all -n "${NS}" --timeout=30s 2>/dev/null || true
        for ING in $(kubectl get ingress -n "${NS}" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null); do
            kubectl patch ingress "$ING" -n "${NS}" --type=json -p='[{"op":"remove","path":"/metadata/finalizers"}]' 2>/dev/null || true
            kubectl delete ingress "$ING" -n "${NS}" --force --grace-period=0 2>/dev/null || true
        done
        log_ok "Ingresses deleted"
        DELETED=$((DELETED+1))
    else
        ING_COUNT=$(kubectl get ingress -n "${NS}" --no-headers 2>/dev/null | wc -l)
        log_dry "${ING_COUNT} Ingress(es) in ${NS}"
        SKIPPED=$((SKIPPED+1))
    fi
else
    log_info "Namespace ${NS} does not exist — skipping ingress deletion"
fi

echo ""
log_info "Waiting for ALB controller to delete ALBs..."
for ALB_NAME in "${CAP}-${DEPLOY_ENV}" "${CAP}-${DEPLOY_ENV}-internal"; do
    ALB_EXISTS=$(taws elbv2 describe-load-balancers --names "${ALB_NAME}" --region "${REGION}" --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null || echo "None")
    if [ "$ALB_EXISTS" != "None" ] && [ -n "$ALB_EXISTS" ]; then
        if [ "$CONFIRM" = true ]; then
            for i in $(seq 1 18); do
                STILL=$(taws elbv2 describe-load-balancers --names "${ALB_NAME}" --region "${REGION}" --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null || echo "None")
                if [ "$STILL" = "None" ] || [ -z "$STILL" ]; then
                    log_ok "ALB ${ALB_NAME} removed by controller"
                    DELETED=$((DELETED+1))
                    break
                fi
                echo "    Waiting for ${ALB_NAME}... (${i}/18)"
                sleep 10
            done
            if [ "$STILL" != "None" ] && [ -n "$STILL" ]; then
                log_warn "ALB ${ALB_NAME} still exists — force deleting via AWS API"
                taws elbv2 delete-load-balancer --load-balancer-arn "$STILL" --region "${REGION}" 2>/dev/null && log_ok "Force deleted ALB ${ALB_NAME}" || log_fail "Could not delete ALB ${ALB_NAME}"
                DELETED=$((DELETED+1))
            fi
        else
            log_dry "ALB: ${ALB_NAME}"
            SKIPPED=$((SKIPPED+1))
        fi
    else
        log_info "ALB ${ALB_NAME} does not exist"
    fi
done

# ──────────────────────────────────────────────────────────────
# Step 2: Delete Kubernetes Namespace
# ──────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}── Step 2: Kubernetes Namespace ──${NC}"

if kubectl get ns "${NS}" > /dev/null 2>&1; then
    if [ "$CONFIRM" = true ]; then
        log_info "Deleting namespace ${NS} (cascades to remaining resources)..."
        kubectl delete ns "${NS}" --timeout=60s 2>/dev/null || true

        if kubectl get ns "${NS}" > /dev/null 2>&1; then
            log_warn "Namespace still exists — force removing finalizers"
            kubectl get ns "${NS}" -o json | python3 -c "
import sys, json
ns = json.load(sys.stdin)
ns['spec']['finalizers'] = []
json.dump(ns, sys.stdout)
" | kubectl replace --raw "/api/v1/namespaces/${NS}/finalize" -f - 2>/dev/null || true
        fi
        log_ok "Namespace ${NS} deleted"
        DELETED=$((DELETED+1))
    else
        POD_COUNT=$(kubectl get pods -n "${NS}" --no-headers 2>/dev/null | wc -l)
        SVC_COUNT=$(kubectl get svc -n "${NS}" --no-headers 2>/dev/null | wc -l)
        log_dry "Namespace ${NS} (${POD_COUNT} pods, ${SVC_COUNT} services)"
        SKIPPED=$((SKIPPED+1))
    fi
else
    log_info "Namespace ${NS} already deleted"
fi

# ──────────────────────────────────────────────────────────────
# Step 3: Cognito
# ──────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}── Step 3: Cognito ──${NC}"

POOL_NAME="${CAP}-${DEPLOY_ENV}"
POOL_ID=$(taws cognito-idp list-user-pools --max-results 60 --region "${REGION}" --query "UserPools[?Name=='${POOL_NAME}'].Id | [0]" --output text 2>/dev/null || echo "None")

if [ "$POOL_ID" != "None" ] && [ -n "$POOL_ID" ]; then
    DOMAIN=$(taws cognito-idp describe-user-pool --user-pool-id "${POOL_ID}" --region "${REGION}" --query 'UserPool.Domain' --output text 2>/dev/null || echo "None")
    if [ "$DOMAIN" != "None" ] && [ -n "$DOMAIN" ]; then
        do_delete "Cognito Domain: ${DOMAIN}" taws cognito-idp delete-user-pool-domain --user-pool-id "${POOL_ID}" --domain "${DOMAIN}" --region "${REGION}"
    fi
    do_delete "Cognito User Pool: ${POOL_NAME} (${POOL_ID})" taws cognito-idp delete-user-pool --user-pool-id "${POOL_ID}" --region "${REGION}"
else
    log_info "Cognito pool ${POOL_NAME} already deleted"
fi

# ──────────────────────────────────────────────────────────────
# Step 4: IAM Role (admin-managed — never delete)
# ──────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}── Step 4: IAM Role ──${NC}"
log_info "IAM roles are admin-managed — skipping (not deleting ${CAP}-${DEPLOY_ENV}-app-role)"

# ──────────────────────────────────────────────────────────────
# Step 5: Secrets Manager
# ──────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}── Step 5: Secrets Manager ──${NC}"

for SECRET_TYPE in api-keys wxcc openai license anthropic github bssmagic-credentials bssmagic-axway-config; do
    SECRET_ID="${CAP}/${DEPLOY_ENV}/${SECRET_TYPE}"
    if taws secretsmanager describe-secret --secret-id "${SECRET_ID}" --region "${REGION}" > /dev/null 2>&1; then
        do_delete "Secret: ${SECRET_ID}" taws secretsmanager delete-secret --secret-id "${SECRET_ID}" --force-delete-without-recovery --region "${REGION}"
    else
        log_info "Secret ${SECRET_ID} already deleted"
    fi
done

# ──────────────────────────────────────────────────────────────
# Step 6: SSM Parameters
# ──────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}── Step 6: SSM Parameters ──${NC}"

SSM_PREFIX="/${CAP}/${DEPLOY_ENV}/"
SSM_PARAMS=$(taws ssm get-parameters-by-path --path "${SSM_PREFIX}" --recursive --region "${REGION}" --query 'Parameters[*].Name' --output text 2>/dev/null || echo "")

if [ -n "$SSM_PARAMS" ]; then
    PARAM_COUNT=$(echo "$SSM_PARAMS" | wc -w)
    if [ "$CONFIRM" = true ]; then
        for PARAM in $SSM_PARAMS; do
            taws ssm delete-parameter --name "${PARAM}" --region "${REGION}" 2>/dev/null || true
        done
        log_ok "Deleted ${PARAM_COUNT} SSM parameters under ${SSM_PREFIX}"
        DELETED=$((DELETED+PARAM_COUNT))
    else
        log_dry "${PARAM_COUNT} SSM parameters under ${SSM_PREFIX}"
        SKIPPED=$((SKIPPED+PARAM_COUNT))
    fi
else
    log_info "SSM parameters under ${SSM_PREFIX} already deleted"
fi

# ──────────────────────────────────────────────────────────────
# Step 7: Glue
# ──────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}── Step 7: Glue Catalog ──${NC}"

GLUE_DB="${CAP_US}_db"
GLUE_TABLE="${CAP_US}_call_records"

if taws glue get-table --database-name "${GLUE_DB}" --name "${GLUE_TABLE}" --region "${REGION}" > /dev/null 2>&1; then
    do_delete "Glue Table: ${GLUE_TABLE}" taws glue delete-table --database-name "${GLUE_DB}" --name "${GLUE_TABLE}" --region "${REGION}"
else
    log_info "Glue table ${GLUE_TABLE} already deleted"
fi

if taws glue get-database --name "${GLUE_DB}" --region "${REGION}" > /dev/null 2>&1; then
    do_delete "Glue Database: ${GLUE_DB}" taws glue delete-database --name "${GLUE_DB}" --region "${REGION}"
else
    log_info "Glue database ${GLUE_DB} already deleted"
fi

# ──────────────────────────────────────────────────────────────
# Step 8: S3 Buckets (empty + delete)
# ──────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}── Step 8: S3 Buckets ──${NC}"

for BUCKET_SUFFIX in wxcc-simulator sfdc-simulator journey-logs journey-reports bssmagic-dumps; do
    BUCKET="${CAP}-${DEPLOY_ENV}-${BUCKET_SUFFIX}-${ACCOUNT_ID}"
    if taws s3api head-bucket --bucket "${BUCKET}" --region "${REGION}" > /dev/null 2>&1; then
        if [ "$CONFIRM" = true ]; then
            log_info "Emptying bucket ${BUCKET} (objects + versions + delete markers)..."

            python3 -c "
import boto3, os
region = '${REGION}'
if os.environ.get('CLEANUP_USE_AWS_PROFILE') == '1':
    session = boto3.Session(profile_name=os.environ.get('AWS_PROFILE', 'default'), region_name=region)
else:
    session = boto3.Session(region_name=region)
s3 = session.resource('s3')
bucket = s3.Bucket('${BUCKET}')
bucket.object_versions.delete()
print('  All versions and delete markers removed')
" 2>/dev/null || {
                taws s3 rm "s3://${BUCKET}" --recursive --region "${REGION}" 2>/dev/null || true
            }

            if taws s3api delete-bucket --bucket "${BUCKET}" --region "${REGION}" > /dev/null 2>&1; then
                log_ok "Deleted: S3 Bucket: ${BUCKET}"
                DELETED=$((DELETED+1))
            elif ! taws s3api head-bucket --bucket "${BUCKET}" --region "${REGION}" > /dev/null 2>&1; then
                log_ok "Already deleted: S3 Bucket: ${BUCKET}"
            else
                log_fail "Could not delete S3 Bucket: ${BUCKET} (may still have objects/versions)"
                FAILED=$((FAILED+1))
            fi
        else
            OBJ_COUNT=$(taws s3 ls "s3://${BUCKET}" --recursive --region "${REGION}" 2>/dev/null | wc -l || echo "0")
            log_dry "S3 Bucket: ${BUCKET} (~${OBJ_COUNT} objects)"
            SKIPPED=$((SKIPPED+1))
        fi
    else
        log_info "Bucket ${BUCKET} already deleted"
    fi
done

# ──────────────────────────────────────────────────────────────
# Step 9: DynamoDB Tables
# ──────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}── Step 9: DynamoDB Tables ──${NC}"

for TABLE_SUFFIX in transformation-system license sessions audit-log foundry-workspace control-plane-audit rbac wxcc-task-tracking lead-opportunity-tracking; do
    TABLE_NAME="${CAP}-${DEPLOY_ENV}-${TABLE_SUFFIX}"
    if taws dynamodb describe-table --table-name "${TABLE_NAME}" --region "${REGION}" > /dev/null 2>&1; then
        do_delete "DynamoDB Table: ${TABLE_NAME}" taws dynamodb delete-table --table-name "${TABLE_NAME}" --region "${REGION}"
    else
        log_info "Table ${TABLE_NAME} already deleted"
    fi
done

# Legacy un-prefixed DynamoDB tables (pre-foundry-consolidation). These were
# created by older versions of DataPlaneService / MappingRuleService /
# GDriveSettingsService and are now superseded by foundry-workspace PK
# namespaces (DATAPLANE#, MAPPINGRULE#, CONNECTORSETTING#). Clean them up
# on teardown if they still exist; no-op on fresh deployments.
for LEGACY_NAME in data-planes mapping-rules "${CAP}-${DEPLOY_ENV}-connector-settings"; do
    if taws dynamodb describe-table --table-name "${LEGACY_NAME}" --region "${REGION}" > /dev/null 2>&1; then
        do_delete "Legacy DynamoDB Table: ${LEGACY_NAME}" taws dynamodb delete-table --table-name "${LEGACY_NAME}" --region "${REGION}"
    fi
done

# ──────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────
echo ""
echo "================================================================"
if [ "$CONFIRM" = true ]; then
    echo -e "  ${GREEN}Cleanup Complete${NC}"
    echo ""
    echo -e "  Deleted: ${GREEN}${DELETED}${NC}  Failed: ${RED}${FAILED}${NC}"
else
    echo -e "  ${YELLOW}Dry Run Complete${NC}"
    echo ""
    echo -e "  Would delete: ${YELLOW}${SKIPPED}${NC} resources"
    echo ""
    echo "  To actually delete, run:"
    echo "    $0 --confirm"
fi
echo "================================================================"
echo ""

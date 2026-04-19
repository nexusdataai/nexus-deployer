#!/bin/bash
#
# Full Capability Cleanup Script
# Completely removes all Kubernetes and AWS resources for a capability.
# Dry run by default — requires --confirm to actually delete.
# Reads defaults from .env.local.
#
# Usage:
#   ./cleanup-capability.sh                          # Dry run (shows what would be deleted)
#   ./cleanup-capability.sh --confirm                # Actually delete everything
#   ./cleanup-capability.sh --env dev --confirm      # Clean dev environment
#   ./cleanup-capability.sh --help
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

_ENVLOCAL="${SCRIPT_DIR}/.env.local"
if [ -f "$_ENVLOCAL" ]; then
    _ENV_LOCAL_ENV=$(grep '^ENV=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2-)
    _ENV_LOCAL_CLUSTER=$(grep '^Cluster=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2-)
fi

DEPLOY_ENV="${DEPLOY_ENV:-${_ENV_LOCAL_ENV:-prod}}"
CLUSTER_NAME="${CLUSTER_NAME:-${_ENV_LOCAL_CLUSTER:-starhub-test}}"
REGION="${REGION:-ap-southeast-1}"
AWS_PROFILE="${AWS_PROFILE:-external-access}"
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
        --help|-h)
            echo "Full Capability Cleanup"
            echo ""
            echo "Completely removes all Kubernetes and AWS resources for a capability."
            echo "DRY RUN by default — use --confirm to actually delete."
            echo ""
            echo "Usage:"
            echo "  $0                          # Dry run"
            echo "  $0 --confirm                # Delete everything"
            echo "  $0 --env dev --confirm      # Clean dev environment"
            echo ""
            echo "Options:"
            echo "  --confirm        Actually perform deletions (required)"
            echo "  --env ENV        Target environment (default: from .env.local)"
            echo "  --cluster NAME   EKS cluster name (default: from .env.local)"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

CAP="call-processing"
NS="${CAP}-${DEPLOY_ENV}"
CAP_US="${CAP//-/_}_${DEPLOY_ENV//-/_}"

echo ""
echo -e "${RED}================================================================${NC}"
if [ "$CONFIRM" = true ]; then
    echo -e "${RED}  FULL CAPABILITY CLEANUP (DESTRUCTIVE)${NC}"
else
    echo -e "${YELLOW}  FULL CAPABILITY CLEANUP (DRY RUN)${NC}"
fi
echo -e "${RED}================================================================${NC}"
echo ""
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

aws eks update-kubeconfig --name "${CLUSTER_NAME}" --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1
ACCOUNT_ID=$(aws sts get-caller-identity --profile "${AWS_PROFILE}" --query Account --output text 2>/dev/null)

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
        log_info "Removing finalizers from TotogiCapability CRs..."
        for CR in $(kubectl get totogicapability -n "${NS}" -o name 2>/dev/null); do
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
    ALB_EXISTS=$(aws elbv2 describe-load-balancers --names "${ALB_NAME}" --region "${REGION}" --profile "${AWS_PROFILE}" --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null || echo "None")
    if [ "$ALB_EXISTS" != "None" ] && [ -n "$ALB_EXISTS" ]; then
        if [ "$CONFIRM" = true ]; then
            for i in $(seq 1 18); do
                STILL=$(aws elbv2 describe-load-balancers --names "${ALB_NAME}" --region "${REGION}" --profile "${AWS_PROFILE}" --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null || echo "None")
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
                aws elbv2 delete-load-balancer --load-balancer-arn "$STILL" --region "${REGION}" --profile "${AWS_PROFILE}" 2>/dev/null && log_ok "Force deleted ALB ${ALB_NAME}" || log_fail "Could not delete ALB ${ALB_NAME}"
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
POOL_ID=$(aws cognito-idp list-user-pools --max-results 60 --region "${REGION}" --profile "${AWS_PROFILE}" --query "UserPools[?Name=='${POOL_NAME}'].Id | [0]" --output text 2>/dev/null || echo "None")

if [ "$POOL_ID" != "None" ] && [ -n "$POOL_ID" ]; then
    DOMAIN=$(aws cognito-idp describe-user-pool --user-pool-id "${POOL_ID}" --region "${REGION}" --profile "${AWS_PROFILE}" --query 'UserPool.Domain' --output text 2>/dev/null || echo "None")
    if [ "$DOMAIN" != "None" ] && [ -n "$DOMAIN" ]; then
        do_delete "Cognito Domain: ${DOMAIN}" aws cognito-idp delete-user-pool-domain --user-pool-id "${POOL_ID}" --domain "${DOMAIN}" --region "${REGION}" --profile "${AWS_PROFILE}"
    fi
    do_delete "Cognito User Pool: ${POOL_NAME} (${POOL_ID})" aws cognito-idp delete-user-pool --user-pool-id "${POOL_ID}" --region "${REGION}" --profile "${AWS_PROFILE}"
else
    log_info "Cognito pool ${POOL_NAME} already deleted"
fi

# ──────────────────────────────────────────────────────────────
# Step 4: IAM Role
# ──────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}── Step 4: IAM Role ──${NC}"

APP_ROLE="${CAP}-${DEPLOY_ENV}-app-role"
if aws iam get-role --role-name "${APP_ROLE}" --profile "${AWS_PROFILE}" > /dev/null 2>&1; then
    if [ "$CONFIRM" = true ]; then
        for POLICY in $(aws iam list-role-policies --role-name "${APP_ROLE}" --profile "${AWS_PROFILE}" --query 'PolicyNames' --output text 2>/dev/null); do
            aws iam delete-role-policy --role-name "${APP_ROLE}" --policy-name "${POLICY}" --profile "${AWS_PROFILE}" 2>/dev/null || true
        done
        for POLICY_ARN in $(aws iam list-attached-role-policies --role-name "${APP_ROLE}" --profile "${AWS_PROFILE}" --query 'AttachedPolicies[*].PolicyArn' --output text 2>/dev/null); do
            aws iam detach-role-policy --role-name "${APP_ROLE}" --policy-arn "${POLICY_ARN}" --profile "${AWS_PROFILE}" 2>/dev/null || true
        done
        do_delete "IAM Role: ${APP_ROLE}" aws iam delete-role --role-name "${APP_ROLE}" --profile "${AWS_PROFILE}"
    else
        log_dry "IAM Role: ${APP_ROLE} (+ inline/attached policies)"
        SKIPPED=$((SKIPPED+1))
    fi
else
    log_info "IAM role ${APP_ROLE} already deleted"
fi

# ──────────────────────────────────────────────────────────────
# Step 5: Secrets Manager
# ──────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}── Step 5: Secrets Manager ──${NC}"

for SECRET_TYPE in api-keys wxcc openai license anthropic github bssmagic-credentials bssmagic-axway-config; do
    SECRET_ID="${CAP}/${DEPLOY_ENV}/${SECRET_TYPE}"
    if aws secretsmanager describe-secret --secret-id "${SECRET_ID}" --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1; then
        do_delete "Secret: ${SECRET_ID}" aws secretsmanager delete-secret --secret-id "${SECRET_ID}" --force-delete-without-recovery --region "${REGION}" --profile "${AWS_PROFILE}"
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
SSM_PARAMS=$(aws ssm get-parameters-by-path --path "${SSM_PREFIX}" --recursive --region "${REGION}" --profile "${AWS_PROFILE}" --query 'Parameters[*].Name' --output text 2>/dev/null || echo "")

if [ -n "$SSM_PARAMS" ]; then
    PARAM_COUNT=$(echo "$SSM_PARAMS" | wc -w)
    if [ "$CONFIRM" = true ]; then
        for PARAM in $SSM_PARAMS; do
            aws ssm delete-parameter --name "${PARAM}" --region "${REGION}" --profile "${AWS_PROFILE}" 2>/dev/null || true
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

if aws glue get-table --database-name "${GLUE_DB}" --name "${GLUE_TABLE}" --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1; then
    do_delete "Glue Table: ${GLUE_TABLE}" aws glue delete-table --database-name "${GLUE_DB}" --name "${GLUE_TABLE}" --region "${REGION}" --profile "${AWS_PROFILE}"
else
    log_info "Glue table ${GLUE_TABLE} already deleted"
fi

if aws glue get-database --name "${GLUE_DB}" --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1; then
    do_delete "Glue Database: ${GLUE_DB}" aws glue delete-database --name "${GLUE_DB}" --region "${REGION}" --profile "${AWS_PROFILE}"
else
    log_info "Glue database ${GLUE_DB} already deleted"
fi

# ──────────────────────────────────────────────────────────────
# Step 8: S3 Buckets (empty + delete)
# ──────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}── Step 8: S3 Buckets ──${NC}"

for BUCKET_SUFFIX in call-data wxcc-simulator journey-logs journey-reports bssmagic-dumps; do
    BUCKET="${CAP}-${DEPLOY_ENV}-${BUCKET_SUFFIX}-${ACCOUNT_ID}"
    if aws s3api head-bucket --bucket "${BUCKET}" --profile "${AWS_PROFILE}" --region "${REGION}" > /dev/null 2>&1; then
        if [ "$CONFIRM" = true ]; then
            log_info "Emptying bucket ${BUCKET} (objects + versions + delete markers)..."

            python3 -c "
import boto3, sys
session = boto3.Session(profile_name='${AWS_PROFILE}', region_name='${REGION}')
s3 = session.resource('s3')
bucket = s3.Bucket('${BUCKET}')
bucket.object_versions.delete()
print('  All versions and delete markers removed')
" 2>/dev/null || {
                aws s3 rm "s3://${BUCKET}" --recursive --profile "${AWS_PROFILE}" --region "${REGION}" 2>/dev/null || true
            }

            if aws s3api delete-bucket --bucket "${BUCKET}" --profile "${AWS_PROFILE}" --region "${REGION}" > /dev/null 2>&1; then
                log_ok "Deleted: S3 Bucket: ${BUCKET}"
                DELETED=$((DELETED+1))
            elif ! aws s3api head-bucket --bucket "${BUCKET}" --profile "${AWS_PROFILE}" --region "${REGION}" > /dev/null 2>&1; then
                log_ok "Already deleted: S3 Bucket: ${BUCKET}"
            else
                log_fail "Could not delete S3 Bucket: ${BUCKET} (may still have objects/versions)"
                FAILED=$((FAILED+1))
            fi
        else
            OBJ_COUNT=$(aws s3 ls "s3://${BUCKET}" --recursive --profile "${AWS_PROFILE}" --region "${REGION}" 2>/dev/null | wc -l || echo "0")
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

for TABLE_SUFFIX in transformation-system license wxcc-task-tracking sessions audit-log; do
    TABLE_NAME="${CAP}-${DEPLOY_ENV}-${TABLE_SUFFIX}"
    if aws dynamodb describe-table --table-name "${TABLE_NAME}" --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1; then
        do_delete "DynamoDB Table: ${TABLE_NAME}" aws dynamodb delete-table --table-name "${TABLE_NAME}" --region "${REGION}" --profile "${AWS_PROFILE}"
    else
        log_info "Table ${TABLE_NAME} already deleted"
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

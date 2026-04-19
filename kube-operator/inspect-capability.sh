#!/bin/bash
#
# Inspect TotogiCapability Resources
# Lists all cluster and AWS resources provisioned by the operator in tabular format.
# Reads defaults from .env.local.
#
# Usage:
#   ./inspect-capability.sh              # Uses .env.local defaults
#   ./inspect-capability.sh --env prod   # Override environment
#   ./inspect-capability.sh --help
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

while [[ $# -gt 0 ]]; do
    case $1 in
        --env)     DEPLOY_ENV="$2"; shift 2 ;;
        --cluster) CLUSTER_NAME="$2"; shift 2 ;;
        --help|-h)
            echo "Inspect TotogiCapability Resources"
            echo ""
            echo "Usage: $0 [--env ENV] [--cluster NAME]"
            echo ""
            echo "Lists all Kubernetes and AWS resources created by the operator"
            echo "for a given capability/environment, with their tags and status."
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

CAP="call-processing"
NS="${CAP}-${DEPLOY_ENV}"
CAP_US="${CAP//-/_}_${DEPLOY_ENV//-/_}"

echo ""
echo "================================================================"
echo "  Capability Resource Inspector"
echo "================================================================"
echo ""
echo "  Capability: ${CAP}"
echo "  Environment: ${DEPLOY_ENV}"
echo "  Namespace: ${NS}"
echo "  Cluster: ${CLUSTER_NAME}"
echo "  Region: ${REGION}"
echo ""

aws eks update-kubeconfig --name "${CLUSTER_NAME}" --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1
ACCOUNT_ID=$(aws sts get-caller-identity --profile "${AWS_PROFILE}" --query Account --output text 2>/dev/null)
echo "  Account: ${ACCOUNT_ID}"
echo ""

# Helper: print a table row
row() {
    printf "  %-45s %-12s %s\n" "$1" "$2" "$3"
}
header() {
    echo ""
    echo "================================================================"
    echo "  $1"
    echo "================================================================"
    echo ""
    printf "  %-45s %-12s %s\n" "RESOURCE" "STATUS" "TAGS / DETAILS"
    printf "  %-45s %-12s %s\n" "---------------------------------------------" "------------" "-----------------------------"
}

# ── Kubernetes Resources ──
header "Kubernetes Resources (Cluster: ${CLUSTER_NAME})"

# Namespace
NS_STATUS=$(kubectl get ns "${NS}" -o jsonpath='{.status.phase}' 2>/dev/null || echo "NOT FOUND")
row "Namespace: ${NS}" "${NS_STATUS}" ""

# Pods
for POD in $(kubectl get pods -n "${NS}" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null); do
    POD_PHASE=$(kubectl get pod "$POD" -n "${NS}" -o jsonpath='{.status.phase}' 2>/dev/null)
    POD_READY=$(kubectl get pod "$POD" -n "${NS}" -o jsonpath='{.status.containerStatuses[0].ready}' 2>/dev/null)
    row "Pod: ${POD}" "${POD_PHASE}" "Ready: ${POD_READY}"
done

# Services
for SVC in $(kubectl get svc -n "${NS}" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null); do
    SVC_TYPE=$(kubectl get svc "$SVC" -n "${NS}" -o jsonpath='{.spec.type}' 2>/dev/null)
    row "Service: ${SVC}" "${SVC_TYPE}" ""
done

# Ingresses
for ING in $(kubectl get ingress -n "${NS}" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null); do
    ING_HOST=$(kubectl get ingress "$ING" -n "${NS}" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "pending")
    ING_SCHEME=$(kubectl get ingress "$ING" -n "${NS}" -o jsonpath='{.metadata.annotations.alb\.ingress\.kubernetes\.io/scheme}' 2>/dev/null || echo "")
    ING_CERT=$(kubectl get ingress "$ING" -n "${NS}" -o jsonpath='{.metadata.annotations.alb\.ingress\.kubernetes\.io/certificate-arn}' 2>/dev/null || echo "")
    DETAIL="${ING_SCHEME}"
    [ -n "$ING_CERT" ] && DETAIL="${DETAIL}, HTTPS"
    [ -n "$ING_HOST" ] && DETAIL="${DETAIL}, ${ING_HOST}"
    row "Ingress: ${ING}" "Active" "${DETAIL}"
done

# ServiceAccount
SA="${NS}-app-sa"
SA_ROLE=$(kubectl get sa "${SA}" -n "${NS}" -o jsonpath='{.metadata.annotations.eks\.amazonaws\.com/role-arn}' 2>/dev/null || echo "NOT FOUND")
if [ "$SA_ROLE" != "NOT FOUND" ]; then
    row "ServiceAccount: ${SA}" "Active" "IRSA: ${SA_ROLE##*/}"
else
    row "ServiceAccount: ${SA}" "NOT FOUND" ""
fi

# Deployments / StatefulSets
for DEP in $(kubectl get deploy -n "${NS}" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null); do
    REPLICAS=$(kubectl get deploy "$DEP" -n "${NS}" -o jsonpath='{.status.readyReplicas}/{.spec.replicas}' 2>/dev/null)
    row "Deployment: ${DEP}" "${REPLICAS}" ""
done
for STS in $(kubectl get statefulset -n "${NS}" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null); do
    REPLICAS=$(kubectl get statefulset "$STS" -n "${NS}" -o jsonpath='{.status.readyReplicas}/{.spec.replicas}' 2>/dev/null)
    row "StatefulSet: ${STS}" "${REPLICAS}" ""
done

# K8s Secrets
for SEC in $(kubectl get secret -n "${NS}" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null | grep -v "^default-token\|^sh\.helm"); do
    row "K8s Secret: ${SEC}" "Active" ""
done

# ── DynamoDB Tables ──
header "DynamoDB Tables"

for TABLE_SUFFIX in transformation-system license wxcc-task-tracking sessions audit-log; do
    TABLE_NAME="${CAP}-${DEPLOY_ENV}-${TABLE_SUFFIX}"
    STATUS=$(aws dynamodb describe-table --table-name "${TABLE_NAME}" --region "${REGION}" --profile "${AWS_PROFILE}" --query 'Table.TableStatus' --output text 2>/dev/null || echo "NOT FOUND")
    TAGS=""
    if [ "$STATUS" != "NOT FOUND" ]; then
        TABLE_ARN=$(aws dynamodb describe-table --table-name "${TABLE_NAME}" --region "${REGION}" --profile "${AWS_PROFILE}" --query 'Table.TableArn' --output text 2>/dev/null)
        TAGS=$(aws dynamodb list-tags-of-resource --resource-arn "${TABLE_ARN}" --region "${REGION}" --profile "${AWS_PROFILE}" --query 'Tags[*].[Key,Value]' --output text 2>/dev/null | tr '\t' '=' | tr '\n' ', ' | sed 's/, $//')
    fi
    row "${TABLE_NAME}" "${STATUS}" "${TAGS:-No tags}"
done

# ── S3 Buckets ──
header "S3 Buckets"

for BUCKET_SUFFIX in call-data wxcc-simulator journey-logs journey-reports bssmagic-dumps; do
    BUCKET="${CAP}-${DEPLOY_ENV}-${BUCKET_SUFFIX}-${ACCOUNT_ID}"
    if aws s3api head-bucket --bucket "${BUCKET}" --profile "${AWS_PROFILE}" --region "${REGION}" > /dev/null 2>&1; then
        STATUS="Active"
        TAGS=$(aws s3api get-bucket-tagging --bucket "${BUCKET}" --profile "${AWS_PROFILE}" --region "${REGION}" --query 'TagSet[*].[Key,Value]' --output text 2>/dev/null | tr '\t' '=' | tr '\n' ', ' | sed 's/, $//' || echo "No tags")
    else
        STATUS="NOT FOUND"
        TAGS=""
    fi
    row "${BUCKET}" "${STATUS}" "${TAGS:-No tags}"
done

# ── Glue Catalog ──
header "Glue Catalog"

GLUE_DB="${CAP_US}_db"
DB_EXISTS=$(aws glue get-database --name "${GLUE_DB}" --region "${REGION}" --profile "${AWS_PROFILE}" --query 'Database.Name' --output text 2>/dev/null || echo "NOT FOUND")
if [ "$DB_EXISTS" != "NOT FOUND" ]; then
    DB_ARN="arn:aws:glue:${REGION}:${ACCOUNT_ID}:database/${GLUE_DB}"
    DB_TAGS=$(aws glue get-tags --resource-arn "${DB_ARN}" --region "${REGION}" --profile "${AWS_PROFILE}" --query 'Tags' --output json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(', '.join(f'{k}={v}' for k,v in d.items()))" 2>/dev/null || echo "No tags")
    row "Database: ${GLUE_DB}" "Active" "${DB_TAGS}"
else
    row "Database: ${GLUE_DB}" "NOT FOUND" ""
fi

GLUE_TABLE="${CAP_US}_call_records"
TBL_EXISTS=$(aws glue get-table --database-name "${GLUE_DB}" --name "${GLUE_TABLE}" --region "${REGION}" --profile "${AWS_PROFILE}" --query 'Table.Name' --output text 2>/dev/null || echo "NOT FOUND")
if [ "$TBL_EXISTS" != "NOT FOUND" ]; then
    TBL_ARN="arn:aws:glue:${REGION}:${ACCOUNT_ID}:table/${GLUE_DB}/${GLUE_TABLE}"
    TBL_TAGS=$(aws glue get-tags --resource-arn "${TBL_ARN}" --region "${REGION}" --profile "${AWS_PROFILE}" --query 'Tags' --output json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(', '.join(f'{k}={v}' for k,v in d.items()))" 2>/dev/null || echo "No tags")
    row "Table: ${GLUE_TABLE}" "Active" "${TBL_TAGS}"
else
    row "Table: ${GLUE_TABLE}" "NOT FOUND" ""
fi

# ── SSM Parameters ──
header "SSM Parameters"

SSM_PREFIX="/${CAP}/${DEPLOY_ENV}/"
SSM_PARAMS=$(aws ssm get-parameters-by-path --path "${SSM_PREFIX}" --recursive --region "${REGION}" --profile "${AWS_PROFILE}" --query 'Parameters[*].Name' --output text 2>/dev/null || echo "")

if [ -n "$SSM_PARAMS" ]; then
    for PARAM in $SSM_PARAMS; do
        PARAM_TAGS=$(aws ssm list-tags-for-resource --resource-type Parameter --resource-id "${PARAM}" --region "${REGION}" --profile "${AWS_PROFILE}" --query 'TagList[*].[Key,Value]' --output text 2>/dev/null | tr '\t' '=' | tr '\n' ', ' | sed 's/, $//' || echo "")
        PARAM_SHORT="${PARAM#${SSM_PREFIX}}"
        row "${PARAM_SHORT}" "Active" "${PARAM_TAGS:-No tags}"
    done
else
    row "(none found under ${SSM_PREFIX})" "EMPTY" ""
fi

# ── Secrets Manager ──
header "Secrets Manager"

for SECRET_TYPE in api-keys wxcc openai license anthropic github bssmagic-credentials bssmagic-axway-config; do
    SECRET_ID="${CAP}/${DEPLOY_ENV}/${SECRET_TYPE}"
    SECRET_ARN=$(aws secretsmanager describe-secret --secret-id "${SECRET_ID}" --region "${REGION}" --profile "${AWS_PROFILE}" --query 'ARN' --output text 2>/dev/null || echo "NOT FOUND")
    if [ "$SECRET_ARN" != "NOT FOUND" ]; then
        SECRET_TAGS_RAW=$(aws secretsmanager describe-secret --secret-id "${SECRET_ID}" --region "${REGION}" --profile "${AWS_PROFILE}" --query 'Tags[*].[Key,Value]' --output text 2>/dev/null)
        if [ -n "$SECRET_TAGS_RAW" ] && [ "$SECRET_TAGS_RAW" != "None" ]; then
            SECRET_TAGS=$(echo "$SECRET_TAGS_RAW" | tr '\t' '=' | tr '\n' ', ' | sed 's/, $//')
        else
            SECRET_TAGS="No tags"
        fi
        row "${SECRET_ID}" "Active" "${SECRET_TAGS}"
    else
        row "${SECRET_ID}" "NOT FOUND" ""
    fi
done

# ── IAM Roles ──
header "IAM Roles"

APP_ROLE="${CAP}-${DEPLOY_ENV}-app-role"
ROLE_ARN=$(aws iam get-role --role-name "${APP_ROLE}" --profile "${AWS_PROFILE}" --query 'Role.Arn' --output text 2>/dev/null || echo "NOT FOUND")
if [ "$ROLE_ARN" != "NOT FOUND" ]; then
    ROLE_TAGS=$(aws iam list-role-tags --role-name "${APP_ROLE}" --profile "${AWS_PROFILE}" --query 'Tags[*].[Key,Value]' --output text 2>/dev/null | tr '\t' '=' | tr '\n' ', ' | sed 's/, $//' || echo "No tags")
    row "Role: ${APP_ROLE}" "Active" "${ROLE_TAGS:-No tags}"
else
    row "Role: ${APP_ROLE}" "NOT FOUND" ""
fi

ALB_ROLE="AmazonEKSLoadBalancerControllerRole"
ALB_ROLE_ARN=$(aws iam get-role --role-name "${ALB_ROLE}" --profile "${AWS_PROFILE}" --query 'Role.Arn' --output text 2>/dev/null || echo "NOT FOUND")
if [ "$ALB_ROLE_ARN" != "NOT FOUND" ]; then
    ALB_TAGS=$(aws iam list-role-tags --role-name "${ALB_ROLE}" --profile "${AWS_PROFILE}" --query 'Tags[*].[Key,Value]' --output text 2>/dev/null | tr '\t' '=' | tr '\n' ', ' | sed 's/, $//' || echo "No tags")
    row "Role: ${ALB_ROLE}" "Active" "${ALB_TAGS:-No tags}"
else
    row "Role: ${ALB_ROLE}" "NOT FOUND" ""
fi

EBS_ROLE="AmazonEKS_EBS_CSI_DriverRole"
EBS_ROLE_ARN=$(aws iam get-role --role-name "${EBS_ROLE}" --profile "${AWS_PROFILE}" --query 'Role.Arn' --output text 2>/dev/null || echo "NOT FOUND")
if [ "$EBS_ROLE_ARN" != "NOT FOUND" ]; then
    EBS_TAGS=$(aws iam list-role-tags --role-name "${EBS_ROLE}" --profile "${AWS_PROFILE}" --query 'Tags[*].[Key,Value]' --output text 2>/dev/null | tr '\t' '=' | tr '\n' ', ' | sed 's/, $//' || echo "No tags")
    row "Role: ${EBS_ROLE}" "Active" "${EBS_TAGS:-No tags}"
else
    row "Role: ${EBS_ROLE}" "NOT FOUND" ""
fi

# ── Cognito ──
header "Cognito"

POOL_NAME="${CAP}-${DEPLOY_ENV}"
POOL_ID=$(aws cognito-idp list-user-pools --max-results 60 --region "${REGION}" --profile "${AWS_PROFILE}" --query "UserPools[?Name=='${POOL_NAME}'].Id | [0]" --output text 2>/dev/null || echo "None")

if [ "$POOL_ID" != "None" ] && [ -n "$POOL_ID" ]; then
    POOL_TAGS_JSON=$(aws cognito-idp describe-user-pool --user-pool-id "${POOL_ID}" --region "${REGION}" --profile "${AWS_PROFILE}" --query 'UserPool.UserPoolTags' --output json 2>/dev/null || echo "{}")
    POOL_TAGS=$(echo "$POOL_TAGS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(', '.join(f'{k}={v}' for k,v in d.items()))" 2>/dev/null || echo "No tags")
    row "User Pool: ${POOL_NAME} (${POOL_ID})" "Active" "${POOL_TAGS}"

    CLIENT_ID=$(aws cognito-idp list-user-pool-clients --user-pool-id "${POOL_ID}" --region "${REGION}" --profile "${AWS_PROFILE}" --query 'UserPoolClients[0].ClientId' --output text 2>/dev/null || echo "None")
    if [ "$CLIENT_ID" != "None" ]; then
        row "App Client: ${CLIENT_ID}" "Active" "(not taggable)"
    fi

    DOMAIN=$(aws cognito-idp describe-user-pool --user-pool-id "${POOL_ID}" --region "${REGION}" --profile "${AWS_PROFILE}" --query 'UserPool.Domain' --output text 2>/dev/null || echo "None")
    if [ "$DOMAIN" != "None" ]; then
        row "Domain: ${DOMAIN}" "Active" "(not taggable)"
    fi
else
    row "User Pool: ${POOL_NAME}" "NOT FOUND" ""
fi

# ── ALB Load Balancers ──
header "ALB Load Balancers"

for ALB_NAME in "${CAP}-${DEPLOY_ENV}" "${CAP}-${DEPLOY_ENV}-internal"; do
    ALB_INFO=$(aws elbv2 describe-load-balancers --names "${ALB_NAME}" --region "${REGION}" --profile "${AWS_PROFILE}" --output json 2>/dev/null || echo '{"LoadBalancers":[]}')
    ALB_EXISTS=$(echo "$ALB_INFO" | python3 -c "import sys,json; lb=json.load(sys.stdin).get('LoadBalancers',[]); print('yes' if lb else 'no')" 2>/dev/null)

    if [ "$ALB_EXISTS" = "yes" ]; then
        ALB_ARN=$(echo "$ALB_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin)['LoadBalancers'][0]['LoadBalancerArn'])" 2>/dev/null)
        ALB_SCHEME=$(echo "$ALB_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin)['LoadBalancers'][0]['Scheme'])" 2>/dev/null)
        ALB_STATE=$(echo "$ALB_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin)['LoadBalancers'][0].get('State',{}).get('Code','unknown'))" 2>/dev/null)
        ALB_DNS=$(echo "$ALB_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin)['LoadBalancers'][0].get('DNSName',''))" 2>/dev/null)
        ALB_TAGS=$(aws elbv2 describe-tags --resource-arns "${ALB_ARN}" --region "${REGION}" --profile "${AWS_PROFILE}" --query 'TagDescriptions[0].Tags[*].[Key,Value]' --output text 2>/dev/null | tr '\t' '=' | tr '\n' ', ' | sed 's/, $//' || echo "No tags")
        row "ALB: ${ALB_NAME} (${ALB_SCHEME})" "${ALB_STATE}" "${ALB_TAGS}"
        row "  DNS: ${ALB_DNS}" "" ""
    else
        row "ALB: ${ALB_NAME}" "NOT FOUND" ""
    fi
done

# ── Summary ──
echo ""
echo "================================================================"
echo "  Inspection Complete"
echo "================================================================"
echo ""

K8S_COUNT=$(kubectl get pods,svc,deploy,statefulset,ingress,sa -n "${NS}" --no-headers 2>/dev/null | wc -l)
echo "  Kubernetes resources in ${NS}: ${K8S_COUNT}"

AWS_FOUND=0
for svc in "DynamoDB:dynamodb:describe-table" "S3:s3api:head-bucket" "Glue:glue:get-database" "Secrets:secretsmanager:describe-secret" "Cognito:cognito-idp:list-user-pools"; do
    : # counted inline above
done
echo ""

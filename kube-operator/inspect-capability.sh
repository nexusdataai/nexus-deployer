#!/bin/bash
#
# Inspect TotogiCapability Resources
# Lists all cluster and AWS resources provisioned by the operator in tabular format.
# Reads defaults from .env.local when run from a dev machine.
#
# Usage (local / jumpbox — uses AWS_PROFILE + aws eks update-kubeconfig):
#   ./inspect-capability.sh              # Uses .env.local defaults
#   ./inspect-capability.sh --env stage  # Override environment
#   ./inspect-capability.sh --local      # Force profile/kubeconfig even if K8s env vars exist
#
# Usage (inside cluster — operator pod / same pattern as IRSA):
#   Uses pod service account credentials (no --profile). Detected when KUBERNETES_SERVICE_HOST is set.
#   Requires aws CLI + kubectl in the container (see kube-operator Dockerfile).
#
#   kubectl exec -n nexus-system deploy/totogi-operator -- \
#     env DEPLOY_ENV=stage AWS_REGION=ap-southeast-1 /bin/bash /app/inspect-capability.sh
#
#   In-cluster AWS calls use the pod service account (IRSA). DynamoDB checks use boto3 (same as the
#   operator); the aws CLI can fail for DDB in the same pod while boto3 succeeds.
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
INSPECT_FORCE_LOCAL="${INSPECT_FORCE_LOCAL:-0}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --env)     DEPLOY_ENV="$2"; shift 2 ;;
        --cluster) CLUSTER_NAME="$2"; shift 2 ;;
        --local)   INSPECT_FORCE_LOCAL=1; shift ;;
        --help|-h)
            echo "Inspect TotogiCapability Resources"
            echo ""
            echo "Usage: $0 [--env ENV] [--cluster NAME] [--local]"
            echo ""
            echo "  --local   Force jumpbox mode (AWS profile + kubeconfig) even in a pod."
            echo ""
            echo "Without --local, if KUBERNETES_SERVICE_HOST is set, uses in-cluster"
            echo "kubectl and IAM/IRSA (no AWS profile)."
            echo ""
            echo "Lists Kubernetes and AWS resources for call-processing/<env>."
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# In-cluster: operator (or any) pod with IRSA — use instance/web identity, not ~/.aws profile
USE_AWS_PROFILE=1
RUN_MODE="local"
if [ -n "${KUBERNETES_SERVICE_HOST:-}" ] && [ "${INSPECT_FORCE_LOCAL}" != "1" ]; then
    USE_AWS_PROFILE=0
    RUN_MODE="in-cluster"
    REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-${REGION}}}"
    CLUSTER_NAME="${EKS_CLUSTER_NAME:-${CLUSTER_NAME}}"
fi

export REGION
CAP="call-processing"
NS="${CAP}-${DEPLOY_ENV}"
CAP_US="${CAP//-/_}_${DEPLOY_ENV//-/_}"

echo ""
echo "================================================================"
echo "  Capability Resource Inspector"
echo "================================================================"
echo ""
echo "  Mode: ${RUN_MODE}"
echo "  Capability: ${CAP}"
echo "  Environment: ${DEPLOY_ENV}"
echo "  Namespace: ${NS}"
echo "  Cluster: ${CLUSTER_NAME}"
echo "  Region: ${REGION}"
echo ""

if [ "${USE_AWS_PROFILE}" = "1" ]; then
    aws eks update-kubeconfig --name "${CLUSTER_NAME}" --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1 || true
    ACCOUNT_ID=$(timeout 15 aws sts get-caller-identity --profile "${AWS_PROFILE}" --query Account --output text 2>/dev/null || echo "")
else
    ACCOUNT_ID=$(timeout 15 aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")
    # AWS CLI v1 sometimes fails IRSA in the operator image while boto3 works; align with verify-capability.py.
    if [ -z "${ACCOUNT_ID}" ]; then
        ACCOUNT_ID=$(timeout 25 python3 -c "import boto3; print(boto3.client('sts', region_name='${REGION}').get_caller_identity()['Account'])" 2>/dev/null | tr -d ' \r\n' || true)
    fi
fi
echo "  Account: ${ACCOUNT_ID}"
if [ -z "${ACCOUNT_ID}" ]; then
    echo "  Note: Account ID unavailable (STS failed). S3 bucket names below omit the account suffix."
fi
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
# Helper: aws CLI with timeout to prevent hanging on unreachable services
AWS_TIMEOUT=10
# DynamoDB: allow slightly longer; boto3 path uses same IRSA as operator (aws CLI often fails in-pod for DDB)
DDB_TIMEOUT=25
# ELBv2 (ALB): same — Ingress shows hostnames but aws elbv2 in-pod can return empty
ELB_TIMEOUT=25
taws() {
    if [ "${USE_AWS_PROFILE}" = "1" ]; then
        timeout "${AWS_TIMEOUT}" aws "$@" --profile "${AWS_PROFILE}"
    else
        timeout "${AWS_TIMEOUT}" aws "$@"
    fi
}

# In-cluster: describe DynamoDB via boto3 (same default credential chain / IRSA as totogi-operator process).
# Table name -> prints "STATUS|details" where details are items/billing/tags (empty if NOT FOUND).
inspect_ddb_boto3_line() {
    local tn="$1"
    timeout "${DDB_TIMEOUT}" python3 -c "
import os, sys
import boto3
from botocore.exceptions import ClientError
region = os.environ.get('REGION', 'ap-southeast-1')
name = sys.argv[1]
c = boto3.client('dynamodb', region_name=region)
try:
    r = c.describe_table(TableName=name)
    t = r['Table']
    status = t['TableStatus']
    arn = t['TableArn']
    items = str(t.get('ItemCount', '?'))
    bms = t.get('BillingModeSummary') or {}
    bill = bms.get('BillingMode', '') or ''
    extra = 'items≈' + items + ' billing=' + bill
    try:
        tagr = c.list_tags_of_resource(ResourceArn=arn)
        pairs = [x['Key'] + '=' + x['Value'] for x in tagr.get('Tags', [])]
        tags = ', '.join(pairs)
    except Exception:
        tags = ''
    det = extra + ('; ' + tags if tags else '')
    print(status + '|' + det)
except ClientError as e:
    code = e.response['Error']['Code']
    if code == 'ResourceNotFoundException':
        print('NOT FOUND|')
    else:
        print('ERROR|' + code + ': ' + e.response['Error'].get('Message', '')[:100])
except Exception as e:
    print('ERROR|' + str(e)[:120])
" "${tn}" 2>/dev/null || echo "ERROR|timeout or boto3 failure"
}

# In-cluster: true if table exists and ACTIVE (for summary counter)
inspect_ddb_boto3_active() {
    local tn="$1"
    out=$(timeout "${DDB_TIMEOUT}" python3 -c "
import os, sys
import boto3
from botocore.exceptions import ClientError
region = os.environ.get('REGION', 'ap-southeast-1')
c = boto3.client('dynamodb', region_name=region)
try:
    r = c.describe_table(TableName=sys.argv[1])['Table']
    print('yes' if r.get('TableStatus') == 'ACTIVE' else 'no')
except ClientError:
    print('no')
except Exception:
    print('no')
" "${tn}" 2>/dev/null || echo "no")
    [ "${out}" = "yes" ]
}

# In-cluster: describe ALB by LoadBalancerName (must match alb.ingress.kubernetes.io/load-balancer-name)
inspect_alb_boto3_json() {
    local lb_name="$1"
    timeout "${ELB_TIMEOUT}" python3 -c "
import os, sys, json
import boto3
from botocore.exceptions import ClientError
region = os.environ.get('REGION', 'ap-southeast-1')
name = sys.argv[1]
c = boto3.client('elbv2', region_name=region)
try:
    r = c.describe_load_balancers(Names=[name])
    print(json.dumps({'LoadBalancers': r.get('LoadBalancers', [])}))
except ClientError as e:
    code = e.response.get('Error', {}).get('Code', '')
    if code in ('LoadBalancerNotFoundException', 'LoadBalancerNotFound', 'ValidationException'):
        print('{\"LoadBalancers\":[]}')
    else:
        print('{\"LoadBalancers\":[]}')
except Exception:
    print('{\"LoadBalancers\":[]}')
" "${lb_name}" 2>/dev/null || echo '{"LoadBalancers":[]}'
}

# In-cluster: ALB tags (Key\\tValue lines for same tr pipeline as aws CLI)
inspect_alb_tags_boto3() {
    local lb_arn="$1"
    timeout "${ELB_TIMEOUT}" python3 -c "
import os, sys
import boto3
from botocore.exceptions import ClientError
region = os.environ.get('REGION', 'ap-southeast-1')
arn = sys.argv[1]
c = boto3.client('elbv2', region_name=region)
try:
    r = c.describe_tags(ResourceArns=[arn])
    for td in r.get('TagDescriptions', []):
        for t in td.get('Tags', []):
            print(t.get('Key', '') + '\t' + str(t.get('Value', '')))
except ClientError:
    pass
except Exception:
    pass
" "${lb_arn}" 2>/dev/null
}

# ── Kubernetes Resources ──
header "Kubernetes Resources (Cluster: ${CLUSTER_NAME})"

# Namespace
NS_STATUS=$(kubectl get ns "${NS}" -o jsonpath='{.status.phase}' 2>/dev/null || echo "NOT FOUND")
row "Namespace: ${NS}" "${NS_STATUS}" ""

# TotogiCapability CR (operator reconciliation status)
for TCR in $(kubectl get totogicapabilities.totogi.com -n "${NS}" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null); do
    TCPHASE=$(kubectl get totogicapabilities.totogi.com "$TCR" -n "${NS}" -o jsonpath='{.status.phase}' 2>/dev/null || echo "?")
    TCMSG=$(kubectl get totogicapabilities.totogi.com "$TCR" -n "${NS}" -o jsonpath='{.status.message}' 2>/dev/null || echo "")
    row "TotogiCapability: ${TCR}" "${TCPHASE}" "${TCMSG}"
done

# Pods (multi-container ready counts)
for POD in $(kubectl get pods -n "${NS}" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null); do
    POD_PHASE=$(kubectl get pod "$POD" -n "${NS}" -o jsonpath='{.status.phase}' 2>/dev/null)
    POD_RDY=$(kubectl get pod "$POD" -n "${NS}" -o jsonpath='{range .status.containerStatuses[*]}{.ready}{" "}{end}' 2>/dev/null | tr -s ' ' '\n' | grep -c true 2>/dev/null || echo "0")
    POD_TOT=$(kubectl get pod "$POD" -n "${NS}" -o jsonpath='{range .status.containerStatuses[*]}{.name}{" "}{end}' 2>/dev/null | wc -w | tr -d ' ')
    row "Pod: ${POD}" "${POD_PHASE}" "containers ready: ${POD_RDY}/${POD_TOT:-?}"
done

# Services
for SVC in $(kubectl get svc -n "${NS}" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null); do
    SVC_TYPE=$(kubectl get svc "$SVC" -n "${NS}" -o jsonpath='{.spec.type}' 2>/dev/null)
    row "Service: ${SVC}" "${SVC_TYPE}" ""
done

# Ingresses
if ! kubectl get ingress -n "${NS}" --no-headers 2>/dev/null | grep -q .; then
    row "(no Ingress in namespace)" "—" "Set spec.ingress.enabled: true for ALB; internal ALB requires this too"
fi
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

# ConfigMaps
for CM in $(kubectl get configmap -n "${NS}" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null); do
    row "ConfigMap: ${CM}" "Active" ""
done

# PersistentVolumeClaims (e.g. BSS Magic PostgreSQL)
for PVC in $(kubectl get pvc -n "${NS}" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null); do
    PVC_STAT=$(kubectl get pvc "$PVC" -n "${NS}" -o jsonpath='{.status.phase}' 2>/dev/null || echo "?")
    PVC_CAP=$(kubectl get pvc "$PVC" -n "${NS}" -o jsonpath='{.status.capacity.storage}' 2>/dev/null || echo "")
    PVC_SC=$(kubectl get pvc "$PVC" -n "${NS}" -o jsonpath='{.spec.storageClassName}' 2>/dev/null || echo "")
    row "PVC: ${PVC}" "${PVC_STAT}" "size=${PVC_CAP} sc=${PVC_SC}"
done

# K8s Secrets
for SEC in $(kubectl get secret -n "${NS}" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null | grep -v "^default-token\|^sh\.helm"); do
    row "K8s Secret: ${SEC}" "Active" ""
done

# ── DynamoDB Tables ──
header "DynamoDB Tables"

for TABLE_SUFFIX in transformation-system license wxcc-task-tracking sessions audit-log lead-opportunity-tracking; do
    TABLE_NAME="${CAP}-${DEPLOY_ENV}-${TABLE_SUFFIX}"
    if [ "${USE_AWS_PROFILE}" = "1" ]; then
        STATUS=$(taws dynamodb describe-table --table-name "${TABLE_NAME}" --region "${REGION}" --query 'Table.TableStatus' --output text 2>/dev/null || echo "NOT FOUND")
        TAGS=""
        if [ "$STATUS" != "NOT FOUND" ]; then
            TABLE_ARN=$(taws dynamodb describe-table --table-name "${TABLE_NAME}" --region "${REGION}" --query 'Table.TableArn' --output text 2>/dev/null)
            TAGS=$(taws dynamodb list-tags-of-resource --resource-arn "${TABLE_ARN}" --region "${REGION}" --query 'Tags[*].[Key,Value]' --output text 2>/dev/null | tr '\t' '=' | tr '\n' ', ' | sed 's/, $//')
            DDB_ITEMS=$(taws dynamodb describe-table --table-name "${TABLE_NAME}" --region "${REGION}" --query 'Table.ItemCount' --output text 2>/dev/null || echo "?")
            DDB_BILL=$(taws dynamodb describe-table --table-name "${TABLE_NAME}" --region "${REGION}" --query 'Table.BillingModeSummary.BillingMode' --output text 2>/dev/null || echo "")
            EXTRA="items≈${DDB_ITEMS} billing=${DDB_BILL}"
            TAGS="${EXTRA}; ${TAGS}"
        fi
        row "${TABLE_NAME}" "${STATUS}" "${TAGS:-No tags}"
    else
        # Same IRSA as operator (boto3); not aws CLI
        IFS='|' read -r STATUS DETAIL <<< "$(inspect_ddb_boto3_line "${TABLE_NAME}")"
        TAGS="${DETAIL}"
        [ -z "${TAGS}" ] && TAGS="No tags"
        row "${TABLE_NAME}" "${STATUS}" "${TAGS}"
    fi
done

# ── S3 Buckets ──
header "S3 Buckets"

for BUCKET_SUFFIX in call-data wxcc-simulator sfdc-simulator journey-logs journey-reports bssmagic-dumps; do
    BUCKET="${CAP}-${DEPLOY_ENV}-${BUCKET_SUFFIX}-${ACCOUNT_ID}"
    if taws s3api head-bucket --bucket "${BUCKET}" --region "${REGION}" > /dev/null 2>&1; then
        STATUS="Active"
        TAGS=$(taws s3api get-bucket-tagging --bucket "${BUCKET}" --region "${REGION}" --query 'TagSet[*].[Key,Value]' --output text 2>/dev/null | tr '\t' '=' | tr '\n' ', ' | sed 's/, $//' || echo "No tags")
    else
        STATUS="NOT FOUND"
        TAGS=""
    fi
    row "${BUCKET}" "${STATUS}" "${TAGS:-No tags}"
done

# ── Glue Catalog ──
header "Glue Catalog"

GLUE_DB="${CAP_US}_db"
DB_EXISTS=$(taws glue get-database --name "${GLUE_DB}" --region "${REGION}" --query 'Database.Name' --output text 2>/dev/null || echo "NOT FOUND")
if [ "$DB_EXISTS" != "NOT FOUND" ]; then
    DB_ARN="arn:aws:glue:${REGION}:${ACCOUNT_ID}:database/${GLUE_DB}"
    DB_TAGS=$(taws glue get-tags --resource-arn "${DB_ARN}" --region "${REGION}" --query 'Tags' --output json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(', '.join(f'{k}={v}' for k,v in d.items()))" 2>/dev/null || echo "No tags")
    row "Database: ${GLUE_DB}" "Active" "${DB_TAGS}"
else
    row "Database: ${GLUE_DB}" "NOT FOUND" ""
fi

GLUE_TABLE="${CAP_US}_call_records"
TBL_EXISTS=$(taws glue get-table --database-name "${GLUE_DB}" --name "${GLUE_TABLE}" --region "${REGION}" --query 'Table.Name' --output text 2>/dev/null || echo "NOT FOUND")
if [ "$TBL_EXISTS" != "NOT FOUND" ]; then
    TBL_ARN="arn:aws:glue:${REGION}:${ACCOUNT_ID}:table/${GLUE_DB}/${GLUE_TABLE}"
    TBL_TAGS=$(taws glue get-tags --resource-arn "${TBL_ARN}" --region "${REGION}" --query 'Tags' --output json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(', '.join(f'{k}={v}' for k,v in d.items()))" 2>/dev/null || echo "No tags")
    row "Table: ${GLUE_TABLE}" "Active" "${TBL_TAGS}"
else
    row "Table: ${GLUE_TABLE}" "NOT FOUND" ""
fi

# ── Athena (operator configures primary workgroup output → call-data bucket) ──
header "Athena Workgroup (primary)"

ATH_OUT=$(taws athena get-work-group --work-group primary --region "${REGION}" --query 'WorkGroup.Configuration.ResultConfiguration.OutputLocation' --output text 2>/dev/null || echo "NOT FOUND")
if [ "$ATH_OUT" != "NOT FOUND" ] && [ -n "$ATH_OUT" ] && [ "$ATH_OUT" != "None" ]; then
    row "WorkGroup: primary" "configured" "OutputLocation=${ATH_OUT}"
else
    row "WorkGroup: primary" "NOT SET or N/A" "(Glue provisioner sets s3://.../athena-results/ when possible)"
fi

# ── SSM Parameters ──
header "SSM Parameters"

SSM_PREFIX="/${CAP}/${DEPLOY_ENV}/"
SSM_PARAMS=$(taws ssm get-parameters-by-path --path "${SSM_PREFIX}" --recursive --region "${REGION}" --query 'Parameters[*].Name' --output text 2>/dev/null || echo "")

if [ -n "$SSM_PARAMS" ]; then
    for PARAM in $SSM_PARAMS; do
        PARAM_TAGS=$(taws ssm list-tags-for-resource --resource-type Parameter --resource-id "${PARAM}" --region "${REGION}" --query 'TagList[*].[Key,Value]' --output text 2>/dev/null | tr '\t' '=' | tr '\n' ', ' | sed 's/, $//' || echo "")
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
    SECRET_ARN=$(taws secretsmanager describe-secret --secret-id "${SECRET_ID}" --region "${REGION}" --query 'ARN' --output text 2>/dev/null || echo "NOT FOUND")
    if [ "$SECRET_ARN" != "NOT FOUND" ]; then
        SECRET_TAGS_RAW=$(taws secretsmanager describe-secret --secret-id "${SECRET_ID}" --region "${REGION}" --query 'Tags[*].[Key,Value]' --output text 2>/dev/null)
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
ROLE_ARN=$(taws iam get-role --role-name "${APP_ROLE}" --query 'Role.Arn' --output text 2>/dev/null || echo "NOT FOUND")
if [ "$ROLE_ARN" != "NOT FOUND" ]; then
    ROLE_TAGS=$(taws iam list-role-tags --role-name "${APP_ROLE}" --query 'Tags[*].[Key,Value]' --output text 2>/dev/null | tr '\t' '=' | tr '\n' ', ' | sed 's/, $//' || echo "No tags")
    row "Role: ${APP_ROLE}" "Active" "${ROLE_TAGS:-No tags}"
else
    row "Role: ${APP_ROLE}" "NOT FOUND" ""
fi

ALB_ROLE="AmazonEKSLoadBalancerControllerRole"
ALB_ROLE_ARN=$(taws iam get-role --role-name "${ALB_ROLE}" --query 'Role.Arn' --output text 2>/dev/null || echo "NOT FOUND")
if [ "$ALB_ROLE_ARN" != "NOT FOUND" ]; then
    ALB_TAGS=$(taws iam list-role-tags --role-name "${ALB_ROLE}" --query 'Tags[*].[Key,Value]' --output text 2>/dev/null | tr '\t' '=' | tr '\n' ', ' | sed 's/, $//' || echo "No tags")
    row "Role: ${ALB_ROLE}" "Active" "${ALB_TAGS:-No tags}"
else
    row "Role: ${ALB_ROLE}" "NOT FOUND" ""
fi

EBS_ROLE="AmazonEKS_EBS_CSI_DriverRole"
EBS_ROLE_ARN=$(taws iam get-role --role-name "${EBS_ROLE}" --query 'Role.Arn' --output text 2>/dev/null || echo "NOT FOUND")
if [ "$EBS_ROLE_ARN" != "NOT FOUND" ]; then
    EBS_TAGS=$(taws iam list-role-tags --role-name "${EBS_ROLE}" --query 'Tags[*].[Key,Value]' --output text 2>/dev/null | tr '\t' '=' | tr '\n' ', ' | sed 's/, $//' || echo "No tags")
    row "Role: ${EBS_ROLE}" "Active" "${EBS_TAGS:-No tags}"
else
    row "Role: ${EBS_ROLE}" "NOT FOUND" ""
fi

# ── Cognito ──
header "Cognito"

POOL_NAME="${CAP}-${DEPLOY_ENV}"
POOL_ID=$(taws cognito-idp list-user-pools --max-results 60 --region "${REGION}" --query "UserPools[?Name=='${POOL_NAME}'].Id | [0]" --output text 2>/dev/null || echo "None")

if [ "$POOL_ID" != "None" ] && [ -n "$POOL_ID" ]; then
    POOL_TAGS_JSON=$(taws cognito-idp describe-user-pool --user-pool-id "${POOL_ID}" --region "${REGION}" --query 'UserPool.UserPoolTags' --output json 2>/dev/null || echo "{}")
    POOL_TAGS=$(echo "$POOL_TAGS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(', '.join(f'{k}={v}' for k,v in d.items()))" 2>/dev/null || echo "No tags")
    row "User Pool: ${POOL_NAME} (${POOL_ID})" "Active" "${POOL_TAGS}"

    CLIENT_ID=$(taws cognito-idp list-user-pool-clients --user-pool-id "${POOL_ID}" --region "${REGION}" --query 'UserPoolClients[0].ClientId' --output text 2>/dev/null || echo "None")
    if [ "$CLIENT_ID" != "None" ]; then
        row "App Client: ${CLIENT_ID}" "Active" "(not taggable)"
    fi

    DOMAIN=$(taws cognito-idp describe-user-pool --user-pool-id "${POOL_ID}" --region "${REGION}" --query 'UserPool.Domain' --output text 2>/dev/null || echo "None")
    if [ "$DOMAIN" != "None" ]; then
        row "Domain: ${DOMAIN}" "Active" "(not taggable)"
    fi
else
    row "User Pool: ${POOL_NAME}" "NOT FOUND" ""
fi

# ── ALB Load Balancers ──
header "ALB Load Balancers"

for ALB_NAME in "${CAP}-${DEPLOY_ENV}" "${CAP}-${DEPLOY_ENV}-internal"; do
    if [ "${USE_AWS_PROFILE}" = "1" ]; then
        ALB_INFO=$(taws elbv2 describe-load-balancers --names "${ALB_NAME}" --region "${REGION}" --output json 2>/dev/null || echo '{"LoadBalancers":[]}')
    else
        ALB_INFO=$(inspect_alb_boto3_json "${ALB_NAME}")
    fi
    ALB_EXISTS=$(echo "$ALB_INFO" | python3 -c "import sys,json; lb=json.load(sys.stdin).get('LoadBalancers',[]); print('yes' if lb else 'no')" 2>/dev/null)

    if [ "$ALB_EXISTS" = "yes" ]; then
        ALB_ARN=$(echo "$ALB_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin)['LoadBalancers'][0]['LoadBalancerArn'])" 2>/dev/null)
        ALB_SCHEME=$(echo "$ALB_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin)['LoadBalancers'][0]['Scheme'])" 2>/dev/null)
        ALB_STATE=$(echo "$ALB_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin)['LoadBalancers'][0].get('State',{}).get('Code','unknown'))" 2>/dev/null)
        ALB_DNS=$(echo "$ALB_INFO" | python3 -c "import sys,json; print(json.load(sys.stdin)['LoadBalancers'][0].get('DNSName',''))" 2>/dev/null)
        if [ "${USE_AWS_PROFILE}" = "1" ]; then
            ALB_TAGS=$(taws elbv2 describe-tags --resource-arns "${ALB_ARN}" --region "${REGION}" --query 'TagDescriptions[0].Tags[*].[Key,Value]' --output text 2>/dev/null | tr '\t' '=' | tr '\n' ', ' | sed 's/, $//' || echo "No tags")
        else
            ALB_TAGS=$(inspect_alb_tags_boto3 "${ALB_ARN}" | tr '\t' '=' | tr '\n' ', ' | sed 's/, $//' || true)
            [ -z "${ALB_TAGS}" ] && ALB_TAGS="No tags"
        fi
        row "ALB: ${ALB_NAME} (${ALB_SCHEME})" "${ALB_STATE}" "${ALB_TAGS}"
        row "  DNS: ${ALB_DNS}" "" ""
    else
        row "ALB: ${ALB_NAME}" "NOT FOUND (via elbv2 API)" ""
    fi
done

# Fallback: if elbv2 API failed (no VPC endpoint), show ALB info from Ingress resources
if [ "${USE_AWS_PROFILE}" != "1" ]; then
    INGRESS_LIST=$(kubectl get ingress -n "${NS}" --no-headers -o custom-columns='NAME:.metadata.name,HOST:.status.loadBalancer.ingress[0].hostname,SCHEME:.metadata.annotations.alb\.ingress\.kubernetes\.io/scheme,ALBNAME:.metadata.annotations.alb\.ingress\.kubernetes\.io/load-balancer-name,PORTS:.metadata.annotations.alb\.ingress\.kubernetes\.io/listen-ports' 2>/dev/null || echo "")
    if [ -n "${INGRESS_LIST}" ]; then
        HAS_FALLBACK=false
        while IFS= read -r line; do
            _ING_NAME=$(echo "$line" | awk '{print $1}')
            _ING_HOST=$(echo "$line" | awk '{print $2}')
            _ING_SCHEME=$(echo "$line" | awk '{print $3}')
            _ING_ALB=$(echo "$line" | awk '{print $4}')
            _ING_PORTS=$(echo "$line" | awk '{$1=$2=$3=$4=""; print}' | sed 's/^ *//')
            if [ -n "${_ING_HOST}" ] && [ "${_ING_HOST}" != "<none>" ]; then
                if [ "${HAS_FALLBACK}" = false ]; then
                    echo ""
                    echo "  (elbv2 API unreachable from pod — showing ALB info from Ingress resources)"
                    HAS_FALLBACK=true
                fi
                row "ALB: ${_ING_ALB} (${_ING_SCHEME})" "Active (ingress)" "ports=${_ING_PORTS}"
                row "  DNS: ${_ING_HOST}" "" ""
            fi
        done <<< "${INGRESS_LIST}"
    fi
fi

# ── Summary ──
echo ""
echo "================================================================"
echo "  Inspection Complete"
echo "================================================================"
echo ""

K8S_COUNT=$( (kubectl get pods,svc,deploy,statefulset,ingress,sa,configmap,pvc -n "${NS}" --no-headers 2>/dev/null
    kubectl get totogicapabilities.totogi.com -n "${NS}" --no-headers 2>/dev/null) | wc -l)
echo "  Kubernetes resources in ${NS}: ${K8S_COUNT}"

DDB_OK=0
for _sfx in transformation-system license wxcc-task-tracking sessions audit-log lead-opportunity-tracking; do
    _tn="${CAP}-${DEPLOY_ENV}-${_sfx}"
    if [ "${USE_AWS_PROFILE}" = "1" ]; then
        taws dynamodb describe-table --table-name "${_tn}" --region "${REGION}" --query 'Table.TableStatus' --output text 2>/dev/null | grep -q ACTIVE && DDB_OK=$((DDB_OK + 1)) || true
    else
        inspect_ddb_boto3_active "${_tn}" && DDB_OK=$((DDB_OK + 1)) || true
    fi
done
echo "  DynamoDB tables ACTIVE: ${DDB_OK}/6"

S3_OK=0
for _bsfx in call-data wxcc-simulator sfdc-simulator journey-logs journey-reports bssmagic-dumps; do
    _bn="${CAP}-${DEPLOY_ENV}-${_bsfx}-${ACCOUNT_ID}"
    taws s3api head-bucket --bucket "${_bn}" --region "${REGION}" > /dev/null 2>&1 && S3_OK=$((S3_OK + 1)) || true
done
echo "  S3 buckets reachable: ${S3_OK}/6"
echo ""

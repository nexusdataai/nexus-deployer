#!/bin/bash
#
# Inspect NexusCapability Resources
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
#   kubectl exec -n nexus-system deploy/nexus-operator -- \
#     env DEPLOY_ENV=stage AWS_REGION=us-east-1 /bin/bash /app/inspect-capability.sh
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
CLUSTER_NAME="${CLUSTER_NAME:-${_ENV_LOCAL_CLUSTER:-nexus-dev}}"
REGION="${REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-external-access}"
INSPECT_FORCE_LOCAL="${INSPECT_FORCE_LOCAL:-0}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --env)     DEPLOY_ENV="$2"; shift 2 ;;
        --cluster) CLUSTER_NAME="$2"; shift 2 ;;
        --local)   INSPECT_FORCE_LOCAL=1; shift ;;
        --help|-h)
            echo "Inspect NexusCapability Resources"
            echo ""
            echo "Usage: $0 [--env ENV] [--cluster NAME] [--local]"
            echo ""
            echo "  --local   Force jumpbox mode (AWS profile + kubeconfig) even in a pod."
            echo ""
            echo "Without --local, if KUBERNETES_SERVICE_HOST is set, uses in-cluster"
            echo "kubectl and IAM/IRSA (no AWS profile)."
            echo ""
            echo "Lists Kubernetes and AWS resources for nexus-ai/<env>."
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
CAP="nexus-ai"
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

# In-cluster: describe DynamoDB via boto3 (same default credential chain / IRSA as nexus-operator process).
# Table name -> prints "STATUS|details" where details are items/billing/tags (empty if NOT FOUND).
inspect_ddb_boto3_line() {
    local tn="$1"
    timeout "${DDB_TIMEOUT}" python3 -c "
import os, sys
import boto3
from botocore.exceptions import ClientError
region = os.environ.get('REGION', 'us-east-1')
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
region = os.environ.get('REGION', 'us-east-1')
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
region = os.environ.get('REGION', 'us-east-1')
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
region = os.environ.get('REGION', 'us-east-1')
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

# NexusCapability CR (operator reconciliation status)
for TCR in $(kubectl get nexuscapabilities.nexus.ai -n "${NS}" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null); do
    TCPHASE=$(kubectl get nexuscapabilities.nexus.ai "$TCR" -n "${NS}" -o jsonpath='{.status.phase}' 2>/dev/null || echo "?")
    TCMSG=$(kubectl get nexuscapabilities.nexus.ai "$TCR" -n "${NS}" -o jsonpath='{.status.message}' 2>/dev/null || echo "")
    row "NexusCapability: ${TCR}" "${TCPHASE}" "${TCMSG}"
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

# ── Redis Cache ──
header "Redis Cache (Simulator Data Store)"

REDIS_SVC="redis-svc"
REDIS_PORT=6379

# Check if Redis service exists in namespace
REDIS_SVC_IP=$(kubectl get svc "${REDIS_SVC}" -n "${NS}" -o jsonpath='{.spec.clusterIP}' 2>/dev/null || echo "")
if [ -n "${REDIS_SVC_IP}" ] && [ "${REDIS_SVC_IP}" != "None" ]; then
    row "Service: ${REDIS_SVC}" "Active" "ClusterIP: ${REDIS_SVC_IP}:${REDIS_PORT}"
else
    row "Service: ${REDIS_SVC}" "NOT FOUND" "Deploy redis-statefulset.yaml to enable Redis cache"
fi

# Check Redis StatefulSet
REDIS_STS_READY=$(kubectl get statefulset redis -n "${NS}" -o jsonpath='{.status.readyReplicas}/{.spec.replicas}' 2>/dev/null || echo "")
if [ -n "${REDIS_STS_READY}" ]; then
    row "StatefulSet: redis" "${REDIS_STS_READY}" ""
fi

# Check Redis PVC
REDIS_PVC=$(kubectl get pvc -n "${NS}" -l app=redis --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null | head -1)
if [ -n "${REDIS_PVC}" ]; then
    REDIS_PVC_STAT=$(kubectl get pvc "${REDIS_PVC}" -n "${NS}" -o jsonpath='{.status.phase}' 2>/dev/null || echo "?")
    REDIS_PVC_CAP=$(kubectl get pvc "${REDIS_PVC}" -n "${NS}" -o jsonpath='{.status.capacity.storage}' 2>/dev/null || echo "")
    row "PVC: ${REDIS_PVC}" "${REDIS_PVC_STAT}" "size=${REDIS_PVC_CAP}"
fi

# Connectivity check from a backend pod
BACKEND_POD=$(kubectl get pods -n "${NS}" -l "app=${NS}-backend" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null | head -1)
if [ -n "${BACKEND_POD}" ] && [ -n "${REDIS_SVC_IP}" ] && [ "${REDIS_SVC_IP}" != "None" ]; then
    REDIS_PING=$(kubectl exec -n "${NS}" "${BACKEND_POD}" -- timeout 5 python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(3)
try:
    s.connect(('${REDIS_SVC}', ${REDIS_PORT}))
    s.sendall(b'*1\r\n\$4\r\nPING\r\n')
    resp = s.recv(32).decode().strip()
    print('PONG' if 'PONG' in resp else resp)
finally:
    s.close()
" 2>/dev/null || echo "FAILED")
    if [ "${REDIS_PING}" = "PONG" ]; then
        row "Connectivity: backend→redis" "OK" "PING=PONG"
    else
        row "Connectivity: backend→redis" "FAILED" "${REDIS_PING}"
    fi

    # Memory usage
    REDIS_INFO=$(kubectl exec -n "${NS}" "${BACKEND_POD}" -- timeout 5 python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(3)
try:
    s.connect(('${REDIS_SVC}', ${REDIS_PORT}))
    s.sendall(b'*2\r\n\$4\r\nINFO\r\n\$6\r\nmemory\r\n')
    data = b''
    while True:
        chunk = s.recv(4096)
        if not chunk: break
        data += chunk
        if b'maxmemory_policy' in data: break
    text = data.decode(errors='replace')
    for line in text.split('\r\n'):
        if line.startswith('used_memory_human:'):
            print('mem=' + line.split(':')[1])
        elif line.startswith('maxmemory_human:'):
            print('max=' + line.split(':')[1])
        elif line.startswith('maxmemory_policy:'):
            print('policy=' + line.split(':')[1])
finally:
    s.close()
" 2>/dev/null | tr '\n' ', ' || echo "unavailable")
    row "Redis memory" "INFO" "${REDIS_INFO}"

    # Key count for simulator prefixes
    REDIS_KEYS=$(kubectl exec -n "${NS}" "${BACKEND_POD}" -- timeout 5 python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(3)
try:
    s.connect(('${REDIS_SVC}', ${REDIS_PORT}))
    s.sendall(b'*2\r\n\$6\r\nDBSIZE\r\n\$0\r\n')
    resp = s.recv(128).decode().strip()
    print(resp.replace(':', ''))
finally:
    s.close()
" 2>/dev/null || echo "?")
    row "Redis keys (total)" "DBSIZE" "${REDIS_KEYS}"
elif [ -z "${BACKEND_POD}" ]; then
    row "Connectivity: backend→redis" "SKIP" "No backend pod found"
fi

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

# ── Athena Deep Diagnostics ──
header "Athena Deep Diagnostics (end-to-end)"

# 1. Resolve what the backend actually uses (SSM → env → fallback)
BACKEND_GLUE_DB=$(taws ssm get-parameter --name "/${CAP}/${DEPLOY_ENV}/glue/database" --region "${REGION}" --query 'Parameter.Value' --output text 2>/dev/null || echo "")
BACKEND_GLUE_TBL=$(taws ssm get-parameter --name "/${CAP}/${DEPLOY_ENV}/glue/table" --region "${REGION}" --query 'Parameter.Value' --output text 2>/dev/null || echo "")

if [ -n "${BACKEND_GLUE_DB}" ] && [ "${BACKEND_GLUE_DB}" != "None" ]; then
    row "SSM glue/database" "SET" "${BACKEND_GLUE_DB}"
else
    BACKEND_GLUE_DB=""
    row "SSM glue/database" "NOT SET" "backend falls back to GLUE_DATABASE_NAME env or built-in default"
fi
if [ -n "${BACKEND_GLUE_TBL}" ] && [ "${BACKEND_GLUE_TBL}" != "None" ]; then
    row "SSM glue/table" "SET" "${BACKEND_GLUE_TBL}"
else
    BACKEND_GLUE_TBL=""
    row "SSM glue/table" "NOT SET" "backend falls back to GLUE_TABLE_NAME env or 'wxcc_calls'"
fi

# If SSM didn't have them, try to read from the backend pod env
if [ -z "${BACKEND_GLUE_DB}" ]; then
    BACKEND_POD=$(kubectl get pods -n "${NS}" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null | grep -E '(backend|app)' | head -1)
    if [ -n "${BACKEND_POD}" ]; then
        BACKEND_GLUE_DB=$(kubectl exec -n "${NS}" "${BACKEND_POD}" -c app -- printenv GLUE_DATABASE_NAME 2>/dev/null || echo "")
        [ -z "${BACKEND_GLUE_DB}" ] && BACKEND_GLUE_DB=$(kubectl exec -n "${NS}" "${BACKEND_POD}" -c app -- printenv GLUE_DATABASE 2>/dev/null || echo "")
        BACKEND_GLUE_TBL=$(kubectl exec -n "${NS}" "${BACKEND_POD}" -c app -- printenv GLUE_TABLE_NAME 2>/dev/null || echo "")
        [ -z "${BACKEND_GLUE_TBL}" ] && BACKEND_GLUE_TBL=$(kubectl exec -n "${NS}" "${BACKEND_POD}" -c app -- printenv GLUE_TABLE 2>/dev/null || echo "")
        if [ -n "${BACKEND_GLUE_DB}" ]; then
            row "Pod env GLUE_DATABASE_NAME" "SET" "${BACKEND_GLUE_DB} (from ${BACKEND_POD})"
        fi
        if [ -n "${BACKEND_GLUE_TBL}" ]; then
            row "Pod env GLUE_TABLE_NAME" "SET" "${BACKEND_GLUE_TBL} (from ${BACKEND_POD})"
        fi
    fi
fi

# Final resolved names (matching backend config_provider.py fallback chain)
RESOLVED_DB="${BACKEND_GLUE_DB:-${CAP}-${DEPLOY_ENV}-analytics}"
RESOLVED_TBL="${BACKEND_GLUE_TBL:-wxcc_calls}"
row "Resolved DB (backend uses)" "—" "${RESOLVED_DB}"
row "Resolved Table (backend uses)" "—" "${RESOLVED_TBL}"
echo ""

# Also test with the operator's naming convention
row "Operator DB name" "—" "${GLUE_DB}  (from inspect script)"
if [ "${RESOLVED_DB}" != "${GLUE_DB}" ]; then
    row "*** NAME MISMATCH ***" "WARNING" "backend='${RESOLVED_DB}' vs operator='${GLUE_DB}'"
fi

echo ""
printf "  %-45s %-12s %s\n" "---------------------------------------------" "------------" "-----------------------------"

# 2. Deep Glue catalog check (with details)
ATHENA_DIAG_OK=0
ATHENA_DIAG_TOTAL=0

# 2a. Check Glue database (using resolved name the backend actually queries)
ATHENA_DIAG_TOTAL=$((ATHENA_DIAG_TOTAL + 1))
if [ "${USE_AWS_PROFILE}" = "1" ]; then
    GLUE_DB_CHECK=$(taws glue get-database --name "${RESOLVED_DB}" --region "${REGION}" --query 'Database.Name' --output text 2>&1)
    GLUE_DB_EXIT=$?
else
    GLUE_DB_CHECK=$(timeout "${AWS_TIMEOUT}" python3 -c "
import os, sys, boto3
from botocore.exceptions import ClientError
region = os.environ.get('REGION', 'us-east-1')
c = boto3.client('glue', region_name=region)
try:
    r = c.get_database(Name=sys.argv[1])
    print(r['Database']['Name'])
except ClientError as e:
    print('ERROR:' + e.response['Error']['Code'] + ':' + e.response['Error'].get('Message','')[:200])
    sys.exit(1)
except Exception as e:
    print('ERROR:' + str(e)[:200])
    sys.exit(1)
" "${RESOLVED_DB}" 2>&1)
    GLUE_DB_EXIT=$?
fi

if [ ${GLUE_DB_EXIT} -eq 0 ] && [[ "${GLUE_DB_CHECK}" != ERROR:* ]]; then
    row "Glue DB: ${RESOLVED_DB}" "EXISTS" ""
    ATHENA_DIAG_OK=$((ATHENA_DIAG_OK + 1))
else
    row "Glue DB: ${RESOLVED_DB}" "FAIL" "${GLUE_DB_CHECK}"
fi

# 2b. Check Glue table (columns, location, serde, partition keys)
ATHENA_DIAG_TOTAL=$((ATHENA_DIAG_TOTAL + 1))
if [ "${USE_AWS_PROFILE}" = "1" ]; then
    GLUE_TBL_JSON=$(taws glue get-table --database-name "${RESOLVED_DB}" --name "${RESOLVED_TBL}" --region "${REGION}" --output json 2>&1)
    GLUE_TBL_EXIT=$?
else
    GLUE_TBL_JSON=$(timeout "${AWS_TIMEOUT}" python3 -c "
import os, sys, json, boto3
from botocore.exceptions import ClientError
region = os.environ.get('REGION', 'us-east-1')
c = boto3.client('glue', region_name=region)
try:
    r = c.get_table(DatabaseName=sys.argv[1], Name=sys.argv[2])
    print(json.dumps(r, default=str))
except ClientError as e:
    print(json.dumps({'Error': e.response['Error']['Code'] + ': ' + e.response['Error'].get('Message','')}))
    sys.exit(1)
except Exception as e:
    print(json.dumps({'Error': str(e)[:200]}))
    sys.exit(1)
" "${RESOLVED_DB}" "${RESOLVED_TBL}" 2>&1)
    GLUE_TBL_EXIT=$?
fi

if [ ${GLUE_TBL_EXIT} -eq 0 ]; then
    TBL_LOCATION=$(echo "${GLUE_TBL_JSON}" | python3 -c "import sys,json; t=json.load(sys.stdin).get('Table',{}); sd=t.get('StorageDescriptor',{}); print(sd.get('Location','N/A'))" 2>/dev/null || echo "parse error")
    TBL_SERDE=$(echo "${GLUE_TBL_JSON}" | python3 -c "import sys,json; t=json.load(sys.stdin).get('Table',{}); sd=t.get('StorageDescriptor',{}); si=sd.get('SerdeInfo',{}); print(si.get('SerializationLibrary','N/A').split('.')[-1])" 2>/dev/null || echo "parse error")
    TBL_COLS=$(echo "${GLUE_TBL_JSON}" | python3 -c "import sys,json; t=json.load(sys.stdin).get('Table',{}); sd=t.get('StorageDescriptor',{}); cols=sd.get('Columns',[]); print(len(cols))" 2>/dev/null || echo "?")
    TBL_PKEYS=$(echo "${GLUE_TBL_JSON}" | python3 -c "import sys,json; t=json.load(sys.stdin).get('Table',{}); pk=t.get('PartitionKeys',[]); print(', '.join(p['Name'] for p in pk) if pk else 'none')" 2>/dev/null || echo "?")
    TBL_INPUT=$(echo "${GLUE_TBL_JSON}" | python3 -c "import sys,json; t=json.load(sys.stdin).get('Table',{}); sd=t.get('StorageDescriptor',{}); print(sd.get('InputFormat','N/A').split('.')[-1])" 2>/dev/null || echo "?")

    row "Glue Table: ${RESOLVED_TBL}" "EXISTS" "columns=${TBL_COLS} serde=${TBL_SERDE} fmt=${TBL_INPUT}"
    row "  S3 Location" "—" "${TBL_LOCATION}"
    row "  Partition Keys" "—" "${TBL_PKEYS}"
    ATHENA_DIAG_OK=$((ATHENA_DIAG_OK + 1))

    # 2c. Check partitions
    ATHENA_DIAG_TOTAL=$((ATHENA_DIAG_TOTAL + 1))
    if [ "${USE_AWS_PROFILE}" = "1" ]; then
        PART_COUNT=$(taws glue get-partitions --database-name "${RESOLVED_DB}" --table-name "${RESOLVED_TBL}" --region "${REGION}" --query 'length(Partitions)' --output text 2>/dev/null || echo "0")
        LAST_PARTS=$(taws glue get-partitions --database-name "${RESOLVED_DB}" --table-name "${RESOLVED_TBL}" --region "${REGION}" --max-items 3 --query 'Partitions[*].Values' --output json 2>/dev/null || echo "[]")
    else
        read -r PART_COUNT LAST_PARTS <<< "$(timeout "${AWS_TIMEOUT}" python3 -c "
import os, sys, json, boto3
region = os.environ.get('REGION', 'us-east-1')
c = boto3.client('glue', region_name=region)
try:
    r = c.get_partitions(DatabaseName=sys.argv[1], TableName=sys.argv[2], MaxResults=5)
    parts = r.get('Partitions', [])
    vals = [p.get('Values', []) for p in parts[-3:]]
    print(str(len(parts)) + ' ' + json.dumps(vals))
except Exception as e:
    print('0 []')
" "${RESOLVED_DB}" "${RESOLVED_TBL}" 2>/dev/null || echo "0 []")"
    fi

    if [ "${PART_COUNT}" != "0" ] && [ "${PART_COUNT}" != "" ]; then
        LAST_PARTS_FMT=$(echo "${LAST_PARTS}" | python3 -c "import sys,json; vals=json.load(sys.stdin); print('; '.join('/'.join(v) for v in vals[-3:]))" 2>/dev/null || echo "${LAST_PARTS}")
        row "Partitions" "${PART_COUNT} found" "recent: ${LAST_PARTS_FMT}"
        ATHENA_DIAG_OK=$((ATHENA_DIAG_OK + 1))
    else
        row "Partitions" "NONE" "table may be unpartitioned or empty"
    fi

    # 2d. Check S3 data path has objects
    ATHENA_DIAG_TOTAL=$((ATHENA_DIAG_TOTAL + 1))
    if [ -n "${TBL_LOCATION}" ] && [ "${TBL_LOCATION}" != "N/A" ] && [ "${TBL_LOCATION}" != "parse error" ]; then
        S3_OBJ_COUNT=$(taws s3 ls "${TBL_LOCATION}/" --recursive --region "${REGION}" 2>/dev/null | head -20 | wc -l | tr -d ' ')
        if [ "${S3_OBJ_COUNT}" -gt 0 ] 2>/dev/null; then
            row "S3 data at table location" "${S3_OBJ_COUNT}+ objects" "${TBL_LOCATION}"
            ATHENA_DIAG_OK=$((ATHENA_DIAG_OK + 1))
        else
            row "S3 data at table location" "EMPTY/FAIL" "no objects found or access denied"
        fi
    else
        row "S3 data at table location" "SKIP" "could not determine table location"
    fi
else
    row "Glue Table: ${RESOLVED_TBL}" "FAIL" "$(echo "${GLUE_TBL_JSON}" | head -c 200)"
fi

# 3. Run live Athena query (SELECT COUNT(*) — mirrors backend check_glue_athena)
echo ""
printf "  %-45s %-12s %s\n" "---------------------------------------------" "------------" "-----------------------------"
ATHENA_DIAG_TOTAL=$((ATHENA_DIAG_TOTAL + 1))

RECORDINGS_BUCKET="${CAP}-${DEPLOY_ENV}-call-data-${ACCOUNT_ID}"
ATHENA_OUTPUT="s3://${RECORDINGS_BUCKET}/athena-results/"
ATHENA_QUERY="SELECT COUNT(*) as total FROM \"${RESOLVED_DB}\".\"${RESOLVED_TBL}\""

row "Athena query" "RUNNING" "${ATHENA_QUERY}"
row "  Output location" "—" "${ATHENA_OUTPUT}"

if [ "${USE_AWS_PROFILE}" = "1" ]; then
    QUERY_EXEC_ID=$(taws athena start-query-execution \
        --query-string "${ATHENA_QUERY}" \
        --query-execution-context "Database=${RESOLVED_DB}" \
        --result-configuration "OutputLocation=${ATHENA_OUTPUT}" \
        --region "${REGION}" \
        --query 'QueryExecutionId' --output text 2>&1) && QUERY_START_EXIT=0 || QUERY_START_EXIT=$?
else
    QUERY_EXEC_ID=$(timeout 15 python3 -c "
import os, sys, boto3
region = os.environ.get('REGION', 'us-east-1')
c = boto3.client('athena', region_name=region)
try:
    r = c.start_query_execution(
        QueryString=sys.argv[1],
        QueryExecutionContext={'Database': sys.argv[2]},
        ResultConfiguration={'OutputLocation': sys.argv[3]}
    )
    print(r['QueryExecutionId'])
except Exception as e:
    print('ERROR:' + str(e)[:300])
    sys.exit(1)
" "${ATHENA_QUERY}" "${RESOLVED_DB}" "${ATHENA_OUTPUT}" 2>&1) && QUERY_START_EXIT=0 || QUERY_START_EXIT=$?
fi

if [ ${QUERY_START_EXIT} -ne 0 ] || [[ "${QUERY_EXEC_ID}" == ERROR:* ]]; then
    row "Athena start_query_execution" "FAIL" "${QUERY_EXEC_ID}"
else
    row "  QueryExecutionId" "STARTED" "${QUERY_EXEC_ID}"

    # Poll for result (up to 30 seconds, matching backend's wait)
    ATHENA_STATE="RUNNING"
    ATHENA_REASON=""
    for _i in $(seq 1 10); do
        sleep 3
        if [ "${USE_AWS_PROFILE}" = "1" ]; then
            ATHENA_STATUS_JSON=$(taws athena get-query-execution --query-execution-id "${QUERY_EXEC_ID}" --region "${REGION}" --output json 2>/dev/null || echo "{}")
        else
            ATHENA_STATUS_JSON=$(timeout 10 python3 -c "
import os, sys, json, boto3
region = os.environ.get('REGION', 'us-east-1')
c = boto3.client('athena', region_name=region)
try:
    r = c.get_query_execution(QueryExecutionId=sys.argv[1])
    print(json.dumps(r, default=str))
except Exception as e:
    print(json.dumps({'error': str(e)[:200]}))
" "${QUERY_EXEC_ID}" 2>/dev/null || echo "{}")
        fi

        ATHENA_STATE=$(echo "${ATHENA_STATUS_JSON}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('QueryExecution',{}).get('Status',{}).get('State','UNKNOWN'))" 2>/dev/null || echo "UNKNOWN")
        ATHENA_REASON=$(echo "${ATHENA_STATUS_JSON}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('QueryExecution',{}).get('Status',{}).get('StateChangeReason','')[:300])" 2>/dev/null || echo "")

        if [ "${ATHENA_STATE}" = "SUCCEEDED" ] || [ "${ATHENA_STATE}" = "FAILED" ] || [ "${ATHENA_STATE}" = "CANCELLED" ]; then
            break
        fi
    done

    if [ "${ATHENA_STATE}" = "SUCCEEDED" ]; then
        # Get the query result
        if [ "${USE_AWS_PROFILE}" = "1" ]; then
            ATHENA_RESULT=$(taws athena get-query-results --query-execution-id "${QUERY_EXEC_ID}" --region "${REGION}" --query 'ResultSet.Rows[1].Data[0].VarCharValue' --output text 2>/dev/null || echo "?")
        else
            ATHENA_RESULT=$(timeout 10 python3 -c "
import os, sys, json, boto3
region = os.environ.get('REGION', 'us-east-1')
c = boto3.client('athena', region_name=region)
try:
    r = c.get_query_results(QueryExecutionId=sys.argv[1])
    rows = r['ResultSet']['Rows']
    print(rows[1]['Data'][0].get('VarCharValue', '0') if len(rows) > 1 else '0')
except Exception as e:
    print('ERROR:' + str(e)[:200])
" "${QUERY_EXEC_ID}" 2>/dev/null || echo "?")
        fi

        EXEC_TIME=$(echo "${ATHENA_STATUS_JSON}" | python3 -c "import sys,json; d=json.load(sys.stdin); s=d.get('QueryExecution',{}).get('Statistics',{}); print(str(s.get('EngineExecutionTimeInMillis','?'))+'ms')" 2>/dev/null || echo "?")
        row "Athena query result" "SUCCEEDED" "count=${ATHENA_RESULT} exec_time=${EXEC_TIME}"
        ATHENA_DIAG_OK=$((ATHENA_DIAG_OK + 1))
    elif [ "${ATHENA_STATE}" = "FAILED" ]; then
        row "Athena query result" "FAILED" "${ATHENA_REASON}"
    elif [ "${ATHENA_STATE}" = "CANCELLED" ]; then
        row "Athena query result" "CANCELLED" "${ATHENA_REASON}"
    else
        row "Athena query result" "TIMEOUT" "still ${ATHENA_STATE} after 30s — check in console: ${QUERY_EXEC_ID}"
    fi
fi

# (VPC endpoint and IAM checks moved to "App Permissions + VPC Endpoints" section below)

# 6. Optionally hit the backend diagnostics API from inside the pod
BACKEND_POD="${BACKEND_POD:-$(kubectl get pods -n "${NS}" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null | grep -E '(backend|app)' | head -1)}"
# Auto-detect container name (avoid hard-coding -c app)
if [ -n "${BACKEND_POD}" ]; then
    BACKEND_CONTAINER=$(kubectl get pod "${BACKEND_POD}" -n "${NS}" -o jsonpath='{.spec.containers[0].name}' 2>/dev/null || echo "")
    if [ -n "${BACKEND_CONTAINER}" ]; then
        KEXEC="kubectl exec -n ${NS} ${BACKEND_POD} -c ${BACKEND_CONTAINER} --"
    else
        KEXEC="kubectl exec -n ${NS} ${BACKEND_POD} --"
    fi
fi
if [ -n "${BACKEND_POD}" ]; then
    echo ""
    printf "  %-45s %-12s %s\n" "---------------------------------------------" "------------" "-----------------------------"
    row "Backend pod" "—" "${BACKEND_POD} (container: ${BACKEND_CONTAINER:-default})"

    DIAG_RAW=$(${KEXEC} \
        python3 -c "
import asyncio, json, sys
try:
    from services.diagnostics_service import CallProcessingDiagnostics
    diag = CallProcessingDiagnostics()
    result = asyncio.get_event_loop().run_until_complete(diag.check_glue_athena())
    print(json.dumps({'status': result.status.value if hasattr(result.status,'value') else str(result.status),
                      'message': result.message,
                      'error': result.error or '',
                      'latency_ms': round(result.latency_ms,1),
                      'details': result.details or {}}))
except Exception as e:
    print(json.dumps({'status':'ERROR','message':str(e)[:500],'error':'','details':{}}))
" 2>&1 || echo '{"status":"EXEC_FAIL","message":"kubectl exec failed","error":"","details":{}}')

    DIAG_STATUS=$(echo "${DIAG_RAW}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "parse_error")
    DIAG_MSG=$(echo "${DIAG_RAW}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('message','')[:200])" 2>/dev/null || echo "")
    DIAG_ERR=$(echo "${DIAG_RAW}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error','')[:300])" 2>/dev/null || echo "")
    DIAG_LAT=$(echo "${DIAG_RAW}" | python3 -c "import sys,json; print(str(json.load(sys.stdin).get('latency_ms','?'))+'ms')" 2>/dev/null || echo "?")
    DIAG_DET=$(echo "${DIAG_RAW}" | python3 -c "import sys,json; d=json.load(sys.stdin).get('details',{}); print(json.dumps(d)[:300] if d else '')" 2>/dev/null || echo "")

    row "Backend check_glue_athena()" "${DIAG_STATUS}" "${DIAG_LAT}"
    row "  message" "—" "${DIAG_MSG}"
    if [ -n "${DIAG_ERR}" ]; then
        row "  error (ACTUAL EXCEPTION)" "***" "${DIAG_ERR}"
    fi
    if [ -n "${DIAG_DET}" ]; then
        row "  details" "—" "${DIAG_DET}"
    fi
fi

echo ""
echo "  Athena diagnostics passed: ${ATHENA_DIAG_OK}/${ATHENA_DIAG_TOTAL}"
echo ""

# ── WXCC Connectivity Deep Diagnostics ──
header "WXCC Connectivity Deep Diagnostics (end-to-end)"

WXCC_DIAG_OK=0
WXCC_DIAG_TOTAL=0

# Re-resolve backend pod and KEXEC if not already set
if [ -z "${BACKEND_POD}" ]; then
    BACKEND_POD=$(kubectl get pods -n "${NS}" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null | grep -E '(backend|app)' | head -1)
    if [ -n "${BACKEND_POD}" ]; then
        BACKEND_CONTAINER=$(kubectl get pod "${BACKEND_POD}" -n "${NS}" -o jsonpath='{.spec.containers[0].name}' 2>/dev/null || echo "")
        if [ -n "${BACKEND_CONTAINER}" ]; then
            KEXEC="kubectl exec -n ${NS} ${BACKEND_POD} -c ${BACKEND_CONTAINER} --"
        else
            KEXEC="kubectl exec -n ${NS} ${BACKEND_POD} --"
        fi
    fi
fi

if [ -z "${BACKEND_POD}" ]; then
    row "Backend pod" "NOT FOUND" "Cannot run WXCC diagnostics without a backend pod"
else
    row "Backend pod" "—" "${BACKEND_POD} (container: ${BACKEND_CONTAINER:-default})"

    # 1. WXCC SSM configuration (what the backend resolves)
    WXCC_BASE_URL=$(taws ssm get-parameter --name "/${CAP}/${DEPLOY_ENV}/webex/base_url" --region "${REGION}" --query 'Parameter.Value' --output text 2>/dev/null || echo "")
    WXCC_ORG_ID=$(taws ssm get-parameter --name "/${CAP}/${DEPLOY_ENV}/webex/org_id" --region "${REGION}" --query 'Parameter.Value' --output text 2>/dev/null || echo "")
    WXCC_CLIENT_ID=$(taws ssm get-parameter --name "/${CAP}/${DEPLOY_ENV}/webex/client_id" --region "${REGION}" --query 'Parameter.Value' --output text 2>/dev/null || echo "")
    WXCC_REDIRECT=$(taws ssm get-parameter --name "/${CAP}/${DEPLOY_ENV}/webex/redirect_uri" --region "${REGION}" --query 'Parameter.Value' --output text 2>/dev/null || echo "")

    WXCC_DIAG_TOTAL=$((WXCC_DIAG_TOTAL + 1))
    if [ -n "${WXCC_BASE_URL}" ] && [ "${WXCC_BASE_URL}" != "None" ]; then
        row "SSM webex/base_url" "SET" "${WXCC_BASE_URL}"
        WXCC_DIAG_OK=$((WXCC_DIAG_OK + 1))
    else
        row "SSM webex/base_url" "NOT SET" "defaults to https://api.wxcc-us1.cisco.com/v1"
        WXCC_BASE_URL="https://api.wxcc-us1.cisco.com/v1"
    fi

    WXCC_DIAG_TOTAL=$((WXCC_DIAG_TOTAL + 1))
    if [ -n "${WXCC_ORG_ID}" ] && [ "${WXCC_ORG_ID}" != "None" ]; then
        row "SSM webex/org_id" "SET" "${WXCC_ORG_ID}"
        WXCC_DIAG_OK=$((WXCC_DIAG_OK + 1))
    else
        row "SSM webex/org_id" "NOT SET" "*** REQUIRED — connection will fail ***"
    fi

    if [ -n "${WXCC_CLIENT_ID}" ] && [ "${WXCC_CLIENT_ID}" != "None" ]; then
        row "SSM webex/client_id" "SET" "${WXCC_CLIENT_ID:0:20}..."
    else
        row "SSM webex/client_id" "NOT SET" ""
    fi
    row "SSM webex/redirect_uri" "${WXCC_REDIRECT:+SET}" "${WXCC_REDIRECT:-not set (defaults to https://trilogy.com)}"

    # 2. Check Secrets Manager for credentials and tokens
    echo ""
    printf "  %-45s %-12s %s\n" "---------------------------------------------" "------------" "-----------------------------"

    WXCC_CRED_SECRET="${CAP}-${DEPLOY_ENV}-webex-credentials"
    WXCC_TOKEN_SECRET="${CAP}-${DEPLOY_ENV}-webex-tokens"

    WXCC_DIAG_TOTAL=$((WXCC_DIAG_TOTAL + 1))
    CRED_EXISTS=$(taws secretsmanager describe-secret --secret-id "${WXCC_CRED_SECRET}" --region "${REGION}" --query 'Name' --output text 2>/dev/null || echo "NOT FOUND")
    if [ "${CRED_EXISTS}" != "NOT FOUND" ]; then
        CRED_KEYS=$(taws secretsmanager get-secret-value --secret-id "${WXCC_CRED_SECRET}" --region "${REGION}" --query 'SecretString' --output text 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print('keys: '+', '.join(d.keys())+' | has_secret: '+str(bool(d.get('client_secret'))))" 2>/dev/null || echo "parse error")
        row "Secret: ${WXCC_CRED_SECRET}" "EXISTS" "${CRED_KEYS}"
        WXCC_DIAG_OK=$((WXCC_DIAG_OK + 1))
    else
        row "Secret: ${WXCC_CRED_SECRET}" "NOT FOUND" "*** No OAuth credentials stored ***"
    fi

    WXCC_DIAG_TOTAL=$((WXCC_DIAG_TOTAL + 1))
    TOKEN_EXISTS=$(taws secretsmanager describe-secret --secret-id "${WXCC_TOKEN_SECRET}" --region "${REGION}" --query 'Name' --output text 2>/dev/null || echo "NOT FOUND")
    if [ "${TOKEN_EXISTS}" != "NOT FOUND" ]; then
        TOKEN_INFO=$(taws secretsmanager get-secret-value --secret-id "${WXCC_TOKEN_SECRET}" --region "${REGION}" --query 'SecretString' --output text 2>/dev/null | python3 -c "
import sys, json, time
d = json.load(sys.stdin)
has_at = bool(d.get('access_token'))
has_rt = bool(d.get('refresh_token'))
exp = d.get('expires_at', 0)
now = time.time()
remaining = exp - now if exp else -1
if remaining > 0:
    hrs = remaining / 3600
    exp_str = f'expires_in={hrs:.1f}h'
elif exp:
    exp_str = f'EXPIRED ({-remaining/3600:.1f}h ago)'
else:
    exp_str = 'no expires_at'
at_len = len(d.get('access_token',''))
print(f'access_token={has_at} ({at_len}ch) | refresh_token={has_rt} | {exp_str}')
" 2>/dev/null || echo "parse error")
        row "Secret: ${WXCC_TOKEN_SECRET}" "EXISTS" "${TOKEN_INFO}"

        # Check if token is expired
        IS_EXPIRED=$(taws secretsmanager get-secret-value --secret-id "${WXCC_TOKEN_SECRET}" --region "${REGION}" --query 'SecretString' --output text 2>/dev/null | python3 -c "
import sys, json, time
d = json.load(sys.stdin)
exp = d.get('expires_at', 0)
print('yes' if not exp or time.time() > (exp - 300) else 'no')
" 2>/dev/null || echo "unknown")
        if [ "${IS_EXPIRED}" = "no" ]; then
            row "  Token status" "VALID" "not expired (with 5min buffer)"
            WXCC_DIAG_OK=$((WXCC_DIAG_OK + 1))
        else
            row "  Token status" "EXPIRED" "*** access token expired — refresh or re-auth needed ***"
        fi
    else
        row "Secret: ${WXCC_TOKEN_SECRET}" "NOT FOUND" "*** No OAuth tokens stored — need to connect via UI ***"
    fi

    # 3. Simulator mode check
    echo ""
    printf "  %-45s %-12s %s\n" "---------------------------------------------" "------------" "-----------------------------"

    WXCC_ENABLED=$(taws ssm get-parameter --name "/${CAP}/${DEPLOY_ENV}/wxcc/enabled" --region "${REGION}" --query 'Parameter.Value' --output text 2>/dev/null || echo "NOT SET")
    if [ "${WXCC_ENABLED}" = "true" ]; then
        row "SSM wxcc/enabled (simulator)" "true" "*** SIMULATOR MODE — real API not used ***"
    elif [ "${WXCC_ENABLED}" = "false" ] || [ "${WXCC_ENABLED}" = "NOT SET" ] || [ "${WXCC_ENABLED}" = "None" ]; then
        row "SSM wxcc/enabled (simulator)" "${WXCC_ENABLED}" "real Webex API mode"
    else
        row "SSM wxcc/enabled (simulator)" "${WXCC_ENABLED}" ""
    fi

    # 4. DNS resolution from inside the pod
    WXCC_HOST=$(echo "${WXCC_BASE_URL}" | python3 -c "import sys; from urllib.parse import urlparse; print(urlparse(sys.stdin.read().strip()).hostname or '')" 2>/dev/null || echo "")
    if [ -n "${WXCC_HOST}" ]; then
        WXCC_DIAG_TOTAL=$((WXCC_DIAG_TOTAL + 1))
        DNS_RESULT=$(${KEXEC} python3 -c "
import socket
try:
    ip = socket.getaddrinfo('${WXCC_HOST}', 443)[0][4]
    print('OK|' + str(ip))
except Exception as e:
    print('FAIL|' + str(e)[:200])
" 2>/dev/null || echo "FAIL|kubectl exec failed")

        DNS_STATUS=$(echo "${DNS_RESULT}" | cut -d'|' -f1)
        DNS_DETAIL=$(echo "${DNS_RESULT}" | cut -d'|' -f2-)
        if [ "${DNS_STATUS}" = "OK" ]; then
            row "DNS: ${WXCC_HOST} (from pod)" "RESOLVES" "${DNS_DETAIL}"
            WXCC_DIAG_OK=$((WXCC_DIAG_OK + 1))
        else
            row "DNS: ${WXCC_HOST} (from pod)" "FAIL" "${DNS_DETAIL}"
        fi
    fi

    # 5. HTTPS connectivity from inside the pod (raw GET, no auth)
    if [ -n "${WXCC_HOST}" ]; then
        WXCC_DIAG_TOTAL=$((WXCC_DIAG_TOTAL + 1))
        HTTPS_RESULT=$(${KEXEC} python3 -c "
import requests, time
url = 'https://${WXCC_HOST}/search'
start = time.time()
try:
    r = requests.get(url, timeout=10)
    ms = int((time.time()-start)*1000)
    print(f'OK|status={r.status_code} latency={ms}ms')
except requests.exceptions.ConnectTimeout:
    print('FAIL|connect timeout (10s) — likely no outbound route or firewall')
except requests.exceptions.ConnectionError as e:
    print(f'FAIL|connection error: {str(e)[:200]}')
except Exception as e:
    ms = int((time.time()-start)*1000)
    print(f'FAIL|{str(e)[:200]} ({ms}ms)')
" 2>/dev/null || echo "FAIL|kubectl exec failed")

        HTTPS_STATUS=$(echo "${HTTPS_RESULT}" | cut -d'|' -f1)
        HTTPS_DETAIL=$(echo "${HTTPS_RESULT}" | cut -d'|' -f2-)
        if [ "${HTTPS_STATUS}" = "OK" ]; then
            row "HTTPS to ${WXCC_HOST} (from pod)" "REACHABLE" "${HTTPS_DETAIL}"
            WXCC_DIAG_OK=$((WXCC_DIAG_OK + 1))
        else
            row "HTTPS to ${WXCC_HOST} (from pod)" "FAIL" "${HTTPS_DETAIL}"
        fi
    fi

    # 5b. HTTPS to Webex token endpoint (refresh tokens go here, different host)
    WXCC_DIAG_TOTAL=$((WXCC_DIAG_TOTAL + 1))
    TOKEN_EP_RESULT=$(${KEXEC} python3 -c "
import requests, time
url = 'https://webexapis.com/v1/access_token'
start = time.time()
try:
    r = requests.get(url, timeout=10)
    ms = int((time.time()-start)*1000)
    print(f'OK|status={r.status_code} latency={ms}ms (expected 405 for GET)')
except requests.exceptions.ConnectTimeout:
    print('FAIL|connect timeout — pod cannot reach webexapis.com (token refresh will fail)')
except requests.exceptions.ConnectionError as e:
    print(f'FAIL|connection error: {str(e)[:200]}')
except Exception as e:
    ms = int((time.time()-start)*1000)
    print(f'FAIL|{str(e)[:200]} ({ms}ms)')
" 2>/dev/null || echo "FAIL|kubectl exec failed")

    TOKEN_EP_STATUS=$(echo "${TOKEN_EP_RESULT}" | cut -d'|' -f1)
    TOKEN_EP_DETAIL=$(echo "${TOKEN_EP_RESULT}" | cut -d'|' -f2-)
    if [ "${TOKEN_EP_STATUS}" = "OK" ]; then
        row "HTTPS to webexapis.com (token EP)" "REACHABLE" "${TOKEN_EP_DETAIL}"
        WXCC_DIAG_OK=$((WXCC_DIAG_OK + 1))
    else
        row "HTTPS to webexapis.com (token EP)" "FAIL" "${TOKEN_EP_DETAIL}"
    fi

    # 6. Token refresh test from inside the pod
    echo ""
    printf "  %-45s %-12s %s\n" "---------------------------------------------" "------------" "-----------------------------"

    WXCC_DIAG_TOTAL=$((WXCC_DIAG_TOTAL + 1))
    REFRESH_RESULT=$(${KEXEC} python3 -c "
import os, json, time, sys
os.environ['USE_AWS_SECRETS'] = 'true'
sys.path.insert(0, '/app/scripts/call-scripts')
from secrets_provider import SecretsProvider
p = SecretsProvider()
config = p.get_webex_config()
tokens = p.get_webex_tokens()
exp = tokens.get('expires_at', 0)
now = time.time()
remaining = exp - now if exp else -1
is_expired = p.is_token_expired()
d = {
    'base_url': config.get('base_url',''),
    'org_id': config.get('org_id',''),
    'simulator_mode': config.get('simulator_mode', False),
    'has_access_token': bool(tokens.get('access_token')),
    'has_refresh_token': bool(tokens.get('refresh_token')),
    'access_token_len': len(tokens.get('access_token','')),
    'is_expired': is_expired,
    'remaining_hours': round(remaining/3600, 1) if remaining > 0 else 0,
    'expired_hours_ago': round(-remaining/3600, 1) if remaining < 0 else 0,
}
print(json.dumps(d))
" 2>/dev/null || echo '{"error":"kubectl exec failed"}')

    if echo "${REFRESH_RESULT}" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
        _SIM=$(echo "${REFRESH_RESULT}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('simulator_mode',False))" 2>/dev/null)
        _BASE=$(echo "${REFRESH_RESULT}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('base_url',''))" 2>/dev/null)
        _ORG=$(echo "${REFRESH_RESULT}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('org_id',''))" 2>/dev/null)
        _HAS_AT=$(echo "${REFRESH_RESULT}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('has_access_token',False))" 2>/dev/null)
        _HAS_RT=$(echo "${REFRESH_RESULT}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('has_refresh_token',False))" 2>/dev/null)
        _AT_LEN=$(echo "${REFRESH_RESULT}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token_len',0))" 2>/dev/null)
        _EXP=$(echo "${REFRESH_RESULT}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('is_expired',True))" 2>/dev/null)
        _REM=$(echo "${REFRESH_RESULT}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('remaining_hours',0))" 2>/dev/null)
        _AGO=$(echo "${REFRESH_RESULT}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('expired_hours_ago',0))" 2>/dev/null)

        row "Pod SecretsProvider config" "—" "base_url=${_BASE}"
        row "  org_id" "—" "${_ORG}"
        row "  simulator_mode" "—" "${_SIM}"
        row "  access_token" "${_HAS_AT}" "${_AT_LEN} chars"
        row "  refresh_token" "${_HAS_RT}" ""
        if [ "${_EXP}" = "False" ]; then
            row "  token expired?" "NO" "${_REM}h remaining"
            WXCC_DIAG_OK=$((WXCC_DIAG_OK + 1))
        else
            row "  token expired?" "YES" "expired ${_AGO}h ago"
        fi
    else
        row "Pod SecretsProvider" "FAIL" "${REFRESH_RESULT:0:200}"
    fi

    # 7. Full test_connection() via the backend's WXCCGraphAPI (the actual diagnostic)
    echo ""
    printf "  %-45s %-12s %s\n" "---------------------------------------------" "------------" "-----------------------------"

    WXCC_DIAG_TOTAL=$((WXCC_DIAG_TOTAL + 1))
    row "Backend test_connection()" "RUNNING" "calling WXCCGraphAPI.test_connection() inside pod..."

    CONN_RAW=$(${KEXEC} python3 -c "
import os, json, sys
os.environ['USE_AWS_SECRETS'] = 'true'
sys.path.insert(0, '/app/scripts/call-scripts')
from secrets_provider import SecretsProvider
from wxcc_graph_api import WXCCGraphAPI
try:
    provider = SecretsProvider()
    api = WXCCGraphAPI(secrets_provider=provider, verbose=False, request_timeout=15)
    result = api.test_connection()
    print(json.dumps(result))
except Exception as e:
    import traceback
    print(json.dumps({'success': False, 'error': str(e), 'traceback': traceback.format_exc()[:500]}))
" 2>&1 || echo '{"success":false,"error":"kubectl exec failed"}')

    # Parse only the last JSON line (skip any log output)
    CONN_JSON=$(echo "${CONN_RAW}" | grep -E '^\{' | tail -1)
    if [ -z "${CONN_JSON}" ]; then
        CONN_JSON='{"success":false,"error":"no JSON output from pod"}'
    fi

    CONN_SUCCESS=$(echo "${CONN_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('success',False))" 2>/dev/null || echo "False")
    CONN_MSG=$(echo "${CONN_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('message','')[:300])" 2>/dev/null || echo "")
    CONN_ERR=$(echo "${CONN_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error','')[:300])" 2>/dev/null || echo "")
    CONN_CODE=$(echo "${CONN_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status_code','N/A'))" 2>/dev/null || echo "N/A")
    CONN_BASE=$(echo "${CONN_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('base_url',''))" 2>/dev/null || echo "")
    CONN_ORG=$(echo "${CONN_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('org_id',''))" 2>/dev/null || echo "")
    CONN_TB=$(echo "${CONN_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('traceback','')[:300])" 2>/dev/null || echo "")

    if [ "${CONN_SUCCESS}" = "True" ]; then
        row "test_connection()" "SUCCESS" "HTTP ${CONN_CODE} — ${CONN_MSG}"
        WXCC_DIAG_OK=$((WXCC_DIAG_OK + 1))
    else
        row "test_connection()" "FAIL" "HTTP ${CONN_CODE} — ${CONN_MSG}"
        if [ -n "${CONN_ERR}" ]; then
            row "  error" "***" "${CONN_ERR}"
        fi
        if [ -n "${CONN_TB}" ]; then
            row "  traceback" "***" "${CONN_TB}"
        fi
    fi
    row "  base_url used" "—" "${CONN_BASE}"
    row "  org_id used" "—" "${CONN_ORG}"

    # 8. Token refresh attempt (if expired, try to refresh and report result)
    if [ "${_EXP}" = "True" ] && [ "${_HAS_RT}" = "True" ]; then
        echo ""
        printf "  %-45s %-12s %s\n" "---------------------------------------------" "------------" "-----------------------------"
        row "Token refresh attempt" "RUNNING" "access_token expired, trying refresh_token..."

        REFRESH_RAW=$(${KEXEC} python3 -c "
import os, json, sys
os.environ['USE_AWS_SECRETS'] = 'true'
sys.path.insert(0, '/app/scripts/call-scripts')
from secrets_provider import SecretsProvider
from wxcc_graph_api import WXCCGraphAPI
try:
    provider = SecretsProvider()
    api = WXCCGraphAPI(secrets_provider=provider, verbose=False, request_timeout=15)
    refreshed = api.refresh_token_if_needed()
    if refreshed:
        result = api.test_connection()
        print(json.dumps({'refreshed': True, 'test_success': result.get('success'), 'status_code': result.get('status_code'), 'message': result.get('message','')}))
    else:
        print(json.dumps({'refreshed': False, 'message': 'token not expired or refresh not needed'}))
except Exception as e:
    print(json.dumps({'refreshed': False, 'error': str(e)[:300]}))
" 2>&1 | grep -E '^\{' | tail -1 || echo '{"refreshed":false,"error":"exec failed"}')

        REFRESH_OK=$(echo "${REFRESH_RAW}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('refreshed',False))" 2>/dev/null || echo "False")
        REFRESH_MSG=$(echo "${REFRESH_RAW}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('message','') or d.get('error',''))" 2>/dev/null || echo "")
        REFRESH_CODE=$(echo "${REFRESH_RAW}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status_code','N/A'))" 2>/dev/null || echo "")
        REFRESH_TEST=$(echo "${REFRESH_RAW}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('test_success',False))" 2>/dev/null || echo "")

        if [ "${REFRESH_OK}" = "True" ]; then
            row "Token refresh" "REFRESHED" "new token obtained"
            if [ "${REFRESH_TEST}" = "True" ]; then
                row "  Post-refresh connection" "SUCCESS" "HTTP ${REFRESH_CODE}"
            else
                row "  Post-refresh connection" "FAIL" "HTTP ${REFRESH_CODE} — ${REFRESH_MSG}"
            fi
        else
            row "Token refresh" "FAILED" "${REFRESH_MSG}"
            row "  *** ACTION NEEDED ***" "—" "Re-authenticate via UI Webex Connector > Configuration"
        fi
    fi
fi

echo ""
echo "  WXCC diagnostics passed: ${WXCC_DIAG_OK}/${WXCC_DIAG_TOTAL}"
echo ""

# ── Call Processing Pipeline Diagnostics (single-call end-to-end) ──
header "Call Processing Pipeline (single-call diagnostic)"

PIPE_OK=0
PIPE_TOTAL=0

if [ -z "${BACKEND_POD}" ]; then
    row "Backend pod" "NOT FOUND" "Cannot run pipeline diagnostics"
else
    row "Running inside pod" "—" "${BACKEND_POD}"
    echo ""

    # Run the full pipeline diagnostic as one Python script inside the pod.
    # This tests each sub-step independently and reports per-step results as JSON lines.
    PIPE_RAW=$(${KEXEC} python3 -c "
import os, sys, json, time

os.environ['USE_AWS_SECRETS'] = 'true'
sys.path.insert(0, '/app/scripts/call-scripts')

results = {}

# ── Step 1: WXCC API - fetch 1 task ──
step = 'fetch_tasks'
start = time.time()
try:
    from secrets_provider import SecretsProvider
    from wxcc_graph_api import WXCCGraphAPI
    provider = SecretsProvider()
    api = WXCCGraphAPI(secrets_provider=provider, verbose=False, request_timeout=15)
    tasks_resp = api.get_tasks(days_back=7, page_size=5)
    tasks = tasks_resp.get('data', [])
    ms = int((time.time() - start) * 1000)
    results[step] = {'status': 'PASS', 'ms': ms, 'detail': f'{len(tasks)} tasks fetched (7 days)', 'task_count': len(tasks)}
    # Pick first task with a recording for later steps
    test_task_id = None
    test_task_data = None
    for t in tasks:
        rc = t.get('attributes', {}).get('recordingCount')
        if rc and int(rc) > 0:
            test_task_id = t.get('id')
            test_task_data = t
            break
    if not test_task_id and tasks:
        test_task_id = tasks[0].get('id')
        test_task_data = tasks[0]
    results[step]['test_task_id'] = (test_task_id or '')[:30]
except Exception as e:
    ms = int((time.time() - start) * 1000)
    results[step] = {'status': 'FAIL', 'ms': ms, 'detail': str(e)[:300]}
    test_task_id = None
    test_task_data = None

# ── Step 2: Recording URL (Capture API) ──
step = 'get_recording_url'
start = time.time()
if test_task_id:
    try:
        rec_info = api.get_recording_url(test_task_id)
        recordings = rec_info.get('recordings', [])
        ms = int((time.time() - start) * 1000)
        if recordings:
            file_url = recordings[0].get('file_path', '')
            results[step] = {'status': 'PASS', 'ms': ms, 'detail': f'{len(recordings)} recording(s), url_len={len(file_url)}'}
        else:
            results[step] = {'status': 'WARN', 'ms': ms, 'detail': 'no recordings for this task (try a task with recordingCount>0)'}
            file_url = None
    except Exception as e:
        ms = int((time.time() - start) * 1000)
        results[step] = {'status': 'FAIL', 'ms': ms, 'detail': str(e)[:300]}
        file_url = None
else:
    results[step] = {'status': 'SKIP', 'ms': 0, 'detail': 'no task_id from step 1'}
    file_url = None

# ── Step 3: Download recording ──
step = 'download_recording'
start = time.time()
temp_file = None
if file_url:
    try:
        import tempfile as tf
        temp_file = os.path.join(tf.gettempdir(), 'diag_recording.wav')
        api.download_recording(file_url, temp_file)
        fsize = os.path.getsize(temp_file)
        ms = int((time.time() - start) * 1000)
        results[step] = {'status': 'PASS', 'ms': ms, 'detail': f'downloaded {fsize} bytes'}
    except Exception as e:
        ms = int((time.time() - start) * 1000)
        results[step] = {'status': 'FAIL', 'ms': ms, 'detail': str(e)[:300]}
        temp_file = None
else:
    results[step] = {'status': 'SKIP', 'ms': 0, 'detail': 'no recording URL from step 2'}

# ── Step 4: S3 upload (recording) ──
step = 's3_upload'
start = time.time()
if temp_file and os.path.exists(temp_file):
    try:
        from config import S3_RECORDINGS_BUCKET
        bucket = S3_RECORDINGS_BUCKET
        s3_key = f'call-detail/_diagnostic_test/recording.wav'
        api.upload_to_s3(temp_file, bucket=bucket, s3_key=s3_key, extra_args={'ContentType': 'audio/wav'})
        ms = int((time.time() - start) * 1000)
        results[step] = {'status': 'PASS', 'ms': ms, 'detail': f's3://{bucket}/{s3_key}'}
        # Clean up test file from S3
        try:
            import boto3
            boto3.client('s3', region_name=os.environ.get('AWS_REGION','us-east-1')).delete_object(Bucket=bucket, Key=s3_key)
        except Exception:
            pass
    except Exception as e:
        ms = int((time.time() - start) * 1000)
        results[step] = {'status': 'FAIL', 'ms': ms, 'detail': str(e)[:300]}
else:
    results[step] = {'status': 'SKIP', 'ms': 0, 'detail': 'no recording file from step 3'}

# ── Step 5: OpenAI transcription ──
step = 'openai_transcription'
start = time.time()
if temp_file and os.path.exists(temp_file):
    try:
        transcriber = api._get_transcriber()
        transcript_result = transcriber.transcribe_with_diarization(temp_file)
        segments = transcript_result.get('segments', transcript_result.get('text', ''))
        seg_count = len(segments) if isinstance(segments, list) else 0
        text_len = len(transcript_result.get('text', ''))
        ms = int((time.time() - start) * 1000)
        results[step] = {'status': 'PASS', 'ms': ms, 'detail': f'{seg_count} segments, {text_len} chars'}
    except Exception as e:
        ms = int((time.time() - start) * 1000)
        err = str(e)[:300]
        if 'api key' in err.lower() or 'openai' in err.lower() or 'auth' in err.lower():
            results[step] = {'status': 'FAIL', 'ms': ms, 'detail': f'OpenAI API key issue: {err}'}
        else:
            results[step] = {'status': 'FAIL', 'ms': ms, 'detail': err}
else:
    results[step] = {'status': 'SKIP', 'ms': 0, 'detail': 'no recording file for transcription'}

# Clean up temp file
if temp_file and os.path.exists(temp_file):
    try:
        os.remove(temp_file)
    except Exception:
        pass

# ── Step 6: Glue catalog (ensure partition) ──
step = 'glue_registration'
start = time.time()
try:
    from glue_catalog import GlueCatalog
    from config import S3_RECORDINGS_BUCKET, GLUE_DATABASE_NAME, GLUE_TABLE_NAME
    catalog = GlueCatalog(
        database_name=GLUE_DATABASE_NAME,
        table_name=GLUE_TABLE_NAME,
        s3_bucket=S3_RECORDINGS_BUCKET
    )
    # Check DB exists
    db_ok = True
    try:
        import boto3
        glue = boto3.client('glue', region_name=os.environ.get('AWS_REGION','us-east-1'))
        glue.get_database(Name=GLUE_DATABASE_NAME)
    except Exception as e:
        db_ok = False

    tbl_ok = True
    try:
        glue.get_table(DatabaseName=GLUE_DATABASE_NAME, Name=GLUE_TABLE_NAME)
    except Exception as e:
        tbl_ok = False

    ms = int((time.time() - start) * 1000)
    if db_ok and tbl_ok:
        results[step] = {'status': 'PASS', 'ms': ms, 'detail': f'db={GLUE_DATABASE_NAME} table={GLUE_TABLE_NAME} both exist'}
    elif db_ok:
        results[step] = {'status': 'WARN', 'ms': ms, 'detail': f'db exists but table {GLUE_TABLE_NAME} missing (will be created on first run)'}
    else:
        results[step] = {'status': 'FAIL', 'ms': ms, 'detail': f'db {GLUE_DATABASE_NAME} not found'}
except Exception as e:
    ms = int((time.time() - start) * 1000)
    results[step] = {'status': 'FAIL', 'ms': ms, 'detail': str(e)[:300]}

# ── Step 7: OpenAI API key availability ──
step = 'openai_api_key'
start = time.time()
try:
    # Same logic as call_processor._get_openai_api_key()
    import importlib.util
    cp_path = '/app/src/stages/call-process/call_processor.py'
    spec = importlib.util.spec_from_file_location('call_processor', cp_path)
    cp_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cp_mod)
    key = cp_mod._get_openai_api_key()
    ms = int((time.time() - start) * 1000)
    if key:
        results[step] = {'status': 'PASS', 'ms': ms, 'detail': f'key found ({len(key)} chars, prefix={key[:8]}...)'}
    else:
        results[step] = {'status': 'FAIL', 'ms': ms, 'detail': 'no OpenAI API key found (check Secrets Manager or env)'}
except Exception as e:
    ms = int((time.time() - start) * 1000)
    results[step] = {'status': 'FAIL', 'ms': ms, 'detail': str(e)[:300]}

# ── Step 8: DynamoDB task tracker ──
step = 'task_tracker'
start = time.time()
try:
    from task_tracker import TaskTracker
    tracker = TaskTracker()
    ms = int((time.time() - start) * 1000)
    results[step] = {'status': 'PASS', 'ms': ms, 'detail': f'table={tracker.table_name}'}
except Exception as e:
    ms = int((time.time() - start) * 1000)
    results[step] = {'status': 'FAIL', 'ms': ms, 'detail': str(e)[:300]}

# Output all results as a single JSON object
print(json.dumps(results))
" 2>&1) && PIPE_EXIT=0 || PIPE_EXIT=$?

    # Parse the last JSON line (skip log noise)
    PIPE_JSON=$(echo "${PIPE_RAW}" | grep -E '^\{' | tail -1)
    if [ -z "${PIPE_JSON}" ]; then
        row "Pipeline diagnostic" "EXEC FAIL" "no JSON output (exit=${PIPE_EXIT})"
        # Show last few lines of raw output for debugging
        echo "${PIPE_RAW}" | tail -5 | while IFS= read -r _line; do
            row "  output" "—" "${_line:0:120}"
        done
    else
        # Parse and display each step
        STEP_ORDER="fetch_tasks get_recording_url download_recording s3_upload openai_transcription glue_registration openai_api_key task_tracker"
        STEP_LABELS="1:Fetch Tasks (WXCC API)|2:Get Recording URL (Capture API)|3:Download Recording|4:S3 Upload|5:OpenAI Transcription|6:Glue Catalog|7:OpenAI API Key|8:DynamoDB Task Tracker"

        _idx=0
        for _step in ${STEP_ORDER}; do
            _idx=$((_idx + 1))
            _label=$(echo "${STEP_LABELS}" | tr '|' '\n' | sed -n "${_idx}p")

            _status=$(echo "${PIPE_JSON}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('${_step}',{}).get('status','N/A'))" 2>/dev/null || echo "N/A")
            _ms=$(echo "${PIPE_JSON}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(str(d.get('${_step}',{}).get('ms','?'))+'ms')" 2>/dev/null || echo "?")
            _detail=$(echo "${PIPE_JSON}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('${_step}',{}).get('detail','')[:200])" 2>/dev/null || echo "")

            PIPE_TOTAL=$((PIPE_TOTAL + 1))
            if [ "${_status}" = "PASS" ]; then
                PIPE_OK=$((PIPE_OK + 1))
                row "${_label}" "PASS (${_ms})" "${_detail}"
            elif [ "${_status}" = "SKIP" ]; then
                row "${_label}" "SKIP" "${_detail}"
            elif [ "${_status}" = "WARN" ]; then
                PIPE_OK=$((PIPE_OK + 1))
                row "${_label}" "WARN (${_ms})" "${_detail}"
            else
                row "${_label}" "FAIL (${_ms})" "${_detail}"
            fi
        done

        # Show which test task was used
        _test_tid=$(echo "${PIPE_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('fetch_tasks',{}).get('test_task_id','none'))" 2>/dev/null || echo "")
        if [ -n "${_test_tid}" ] && [ "${_test_tid}" != "none" ]; then
            echo ""
            row "Test task used" "—" "${_test_tid}"
        fi
    fi
fi

echo ""
echo "  Pipeline diagnostics passed: ${PIPE_OK}/${PIPE_TOTAL}"
echo ""

# ── App Permissions + VPC Endpoints (from backend pod) ──
header "App Permissions + VPC Endpoints (from backend pod)"

if [ -z "${BACKEND_POD}" ]; then
    row "Backend pod" "NOT FOUND" "Cannot run permission/endpoint checks"
else
    row "Running inside pod" "—" "${BACKEND_POD} (container: ${BACKEND_CONTAINER:-default})"
    echo ""

    # Combined: VPC endpoint DNS/TLS diagnostics + IAM permission checks
    # All done in a single python3 exec to minimize round-trips
    ${KEXEC} python3 -c "
import os, sys, socket, ssl, ipaddress, json, signal

REGION = '${REGION}'
CAP = '${CAP}'
ENV = '${DEPLOY_ENV}'

# ── Part 1: VPC Endpoint DNS + TLS Diagnostics ──
print('=== VPC_ENDPOINTS ===')
SERVICES = {
    'sts':             f'sts.{REGION}.amazonaws.com',
    'ssm':             f'ssm.{REGION}.amazonaws.com',
    'secretsmanager':  f'secretsmanager.{REGION}.amazonaws.com',
    'dynamodb':        f'dynamodb.{REGION}.amazonaws.com',
    's3':              f's3.{REGION}.amazonaws.com',
    'glue':            f'glue.{REGION}.amazonaws.com',
    'athena':          f'athena.{REGION}.amazonaws.com',
    'cognito-idp':     f'cognito-idp.{REGION}.amazonaws.com',
    'logs':            f'logs.{REGION}.amazonaws.com',
    'ecr':             f'api.ecr.{REGION}.amazonaws.com',
    'eks':             f'eks.{REGION}.amazonaws.com',
    'events':          f'events.{REGION}.amazonaws.com',
    'ec2':             f'ec2.{REGION}.amazonaws.com',
    'iam':             f'iam.{REGION}.amazonaws.com',
    'ssmmessages':     f'ssmmessages.{REGION}.amazonaws.com',
    'webexapis':       'webexapis.com',
}

def detect_cert_owner(sans, svc_name):
    for san in sans:
        if f'.{svc_name}.' in san or san.startswith(f'{svc_name}.') or f'.{svc_name}.{REGION}.vpce.' in san:
            return svc_name
        for s in SERVICES:
            if f'.{s}.' in san or san.startswith(f'{s}.'):
                return s
    return 'unknown'

for svc, host in SERVICES.items():
    try:
        results = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
        ips = sorted(set(r[4][0] for r in results))
        is_private = all(ipaddress.ip_address(ip).is_private for ip in ips)
        route = 'VPCE' if is_private else 'PUBLIC'

        # TLS cert check
        tls_status = 'OK'
        cert_owner = ''
        sans_str = ''
        cross = ''
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with socket.create_connection((ips[0], 443), timeout=5) as sock:
                with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                    der = ssock.getpeercert()
                    sans = [e[1] for e in (der or {}).get('subjectAltName', []) if e[0] == 'DNS']
                    sans_str = ','.join(sans[:3])
                    if is_private and sans:
                        cert_owner = detect_cert_owner(sans, svc)
                        if cert_owner != svc and cert_owner != 'unknown':
                            cross = f'CROSS:{cert_owner}'
        except Exception as e:
            tls_status = 'TLS_FAIL'
            sans_str = str(e)[:80]

        print(f'{svc}|{host}|{ips[0]}|{route}|{tls_status}|{sans_str}|{cross}')
    except Exception as e:
        print(f'{svc}|{host}|-|-|DNS_FAIL|-|{str(e)[:80]}')

# ── Part 2: IAM Permission Checks ──
print('=== IAM_PERMISSIONS ===')
try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError

    FAST = Config(connect_timeout=4, read_timeout=4, retries={'max_attempts': 0})
    TIMEOUT = 8
    SAFE_CODES = {'ResourceNotFoundException','ParameterNotFound','EntityNotFoundException',
                  'NoSuchEntity','NoSuchBucket','NotFoundException','SecretNotFoundException',
                  'InvalidRequestException','ResourceNotFoundFault'}

    class Timeout(Exception): pass
    def _alarm(s, f): raise Timeout()

    def _client(svc):
        hosts = {
            'ec2': f'ec2.{REGION}.amazonaws.com', 's3': f's3.{REGION}.amazonaws.com',
            'ssm': f'ssm.{REGION}.amazonaws.com', 'sts': f'sts.{REGION}.amazonaws.com',
            'glue': f'glue.{REGION}.amazonaws.com', 'ecr': f'api.ecr.{REGION}.amazonaws.com',
            'secretsmanager': f'secretsmanager.{REGION}.amazonaws.com',
            'logs': f'logs.{REGION}.amazonaws.com', 'cognito-idp': f'cognito-idp.{REGION}.amazonaws.com',
            'athena': f'athena.{REGION}.amazonaws.com', 'events': f'events.{REGION}.amazonaws.com',
            'eks': f'eks.{REGION}.amazonaws.com', 'iam': f'iam.{REGION}.amazonaws.com',
            'dynamodb': f'dynamodb.{REGION}.amazonaws.com',
        }
        kw = {'region_name': REGION, 'config': FAST}
        if svc in hosts:
            kw['endpoint_url'] = f'https://{hosts[svc]}'
        return boto3.client(svc, **kw)

    def safe_call(client, method, kwargs):
        old = signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(TIMEOUT)
        try:
            return getattr(client, method)(**kwargs)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)

    PREFIX = f'{CAP}-{ENV}'
    SSM_PATH = f'/{CAP}/{ENV}/'
    GLUE_DB = f\"{CAP.replace('-','_')}_{ENV.replace('-','_')}_db\"
    GLUE_TBL = f\"{CAP.replace('-','_')}_{ENV.replace('-','_')}_call_records\"

    # Get account ID first (needed for S3 bucket and Athena output)
    try:
        _sts = _client('sts')
        _acct = safe_call(_sts, 'get_caller_identity', {}).get('Account', '000000000000')
        print(f'STS|sts:GetCallerIdentity|OK|account={_acct}')
    except Exception as e:
        _acct = '000000000000'
        print(f'STS|sts:GetCallerIdentity|ERROR|{str(e)[:120]}')

    S3_BUCKET = f'{PREFIX}-call-data-{_acct}'

    CHECKS = [
        ('DynamoDB',          'dynamodb',        'describe_table',        {'TableName':f'{PREFIX}-transformation-system'},    'dynamodb:DescribeTable'),
        ('DynamoDB',          'dynamodb',        'get_item',              {'TableName':f'{PREFIX}-transformation-system','Key':{'pk':{'S':'_iam_check'}}}, 'dynamodb:GetItem'),
        ('DynamoDB',          'dynamodb',        'update_time_to_live',   {'TableName':f'{PREFIX}-sessions','TimeToLiveSpecification':{'Enabled':True,'AttributeName':'ttl'}}, 'dynamodb:UpdateTimeToLive'),
        ('S3',                's3',              'head_bucket',           {'Bucket':S3_BUCKET},                              's3:HeadBucket'),
        ('S3',                's3',              'get_bucket_location',   {'Bucket':S3_BUCKET},                              's3:GetBucketLocation'),
        ('SSM',               'ssm',             'get_parameters_by_path',{'Path':SSM_PATH,'MaxResults':1},                  'ssm:GetParametersByPath'),
        ('SecretsManager',    'secretsmanager',  'describe_secret',       {'SecretId':f'{CAP}/{ENV}/api-keys'},              'secretsmanager:DescribeSecret'),
        ('Glue',              'glue',            'get_database',          {'Name':GLUE_DB},                                  'glue:GetDatabase'),
        ('Glue',              'glue',            'get_table',             {'DatabaseName':GLUE_DB,'Name':GLUE_TBL},          'glue:GetTable'),
        ('Glue',              'glue',            'get_partitions',        {'DatabaseName':GLUE_DB,'TableName':GLUE_TBL,'MaxResults':1}, 'glue:GetPartitions'),
        ('Glue',              'glue',            'batch_delete_partition', {'DatabaseName':GLUE_DB,'TableName':GLUE_TBL,'PartitionsToDelete':[]}, 'glue:BatchDeletePartition'),
        ('Athena',            'athena',          'start_query_execution', {'QueryString':'SELECT 1','QueryExecutionContext':{'Database':GLUE_DB},'ResultConfiguration':{'OutputLocation':f's3://{S3_BUCKET}/athena-results/'}}, 'athena:StartQueryExecution'),
        ('Cognito',           'cognito-idp',     'describe_user_pool',    {'UserPoolId':'us-east-1_nonexistent'},       'cognito-idp:DescribeUserPool'),
        ('Cognito',           'cognito-idp',     'admin_update_user_attributes', {'UserPoolId':'us-east-1_nonexistent','Username':'_iam_check','UserAttributes':[]}, 'cognito-idp:AdminUpdateUserAttributes'),
        ('Cognito',           'cognito-idp',     'admin_disable_user',    {'UserPoolId':'us-east-1_nonexistent','Username':'_iam_check'}, 'cognito-idp:AdminDisableUser'),
        ('CloudWatchLogs',    'logs',            'describe_log_groups',   {'limit':1},                                       'logs:DescribeLogGroups'),
    ]

    clients = {}
    for sid, svc, method, kwargs, action in CHECKS:
        if svc not in clients:
            try:
                clients[svc] = _client(svc)
            except Exception as e:
                print(f'{sid}|{action}|ERROR|client error: {str(e)[:100]}')
                continue
        try:
            safe_call(clients[svc], method, kwargs)
            print(f'{sid}|{action}|OK|')
        except ClientError as e:
            code = e.response['Error']['Code']
            msg = e.response['Error'].get('Message','')[:120]
            if code in ('AccessDenied','AccessDeniedException','UnauthorizedAccess'):
                print(f'{sid}|{action}|DENIED|{code}: {msg}')
            elif code in SAFE_CODES:
                print(f'{sid}|{action}|OK|{code} (resource not found, permission OK)')
            else:
                print(f'{sid}|{action}|OK|{code}: {msg}')
        except Timeout:
            print(f'{sid}|{action}|NO_ENDPOINT|timeout {TIMEOUT}s (VPC endpoint missing?)')
        except Exception as e:
            err = str(e)[:120]
            if 'Could not connect' in err or 'timed out' in err.lower():
                print(f'{sid}|{action}|NO_ENDPOINT|{err}')
            else:
                print(f'{sid}|{action}|ERROR|{err}')
except ImportError as e:
    print(f'-|-|ERROR|boto3 not available: {e}')
" 2>&1 | {
        # Parse the combined output into two sections
        _section=""
        _vpce_ok=0; _vpce_total=0; _vpce_fail=0
        _iam_ok=0; _iam_total=0; _iam_denied=0; _iam_noep=0

        while IFS= read -r _line; do
            case "${_line}" in
                "=== VPC_ENDPOINTS ===")
                    _section="vpce"
                    printf "  %-18s %-42s %-8s %-7s %-8s %s\n" "SERVICE" "HOSTNAME" "IP" "ROUTE" "TLS" "NOTES"
                    printf "  %-18s %-42s %-8s %-7s %-8s %s\n" "------------------" "------------------------------------------" "--------" "-------" "--------" "-----------------------------"
                    continue ;;
                "=== IAM_PERMISSIONS ===")
                    _section="iam"
                    echo ""
                    echo "  ================================================================"
                    echo "    IAM Permission Checks (app role)"
                    echo "  ================================================================"
                    echo ""
                    printf "  %-18s %-40s %-14s %s\n" "SECTION" "ACTION" "RESULT" "NOTES"
                    printf "  %-18s %-40s %-14s %s\n" "------------------" "----------------------------------------" "--------------" "-----------------------------"
                    continue ;;
            esac

            if [ "${_section}" = "vpce" ]; then
                IFS='|' read -r _svc _host _ip _route _tls _sans _cross <<< "${_line}"
                _vpce_total=$((_vpce_total + 1))
                if [ "${_route}" = "VPCE" ] && [ "${_tls}" = "OK" ] && [ -z "${_cross}" ]; then
                    _vpce_ok=$((_vpce_ok + 1))
                    printf "  %-18s %-42s %-8s %-7s %-8s %s\n" "${_svc}" "${_host}" "${_ip}" "VPCE" "OK" "${_sans:0:40}"
                elif [ -n "${_cross}" ]; then
                    _vpce_fail=$((_vpce_fail + 1))
                    printf "  %-18s %-42s %-8s %-7s %-8s %s\n" "${_svc}" "${_host}" "${_ip}" "VPCE" "***CROSS" "${_cross} SANs=${_sans:0:30}"
                elif [ "${_route}" = "PUBLIC" ]; then
                    printf "  %-18s %-42s %-8s %-7s %-8s %s\n" "${_svc}" "${_host}" "${_ip}" "PUBLIC" "${_tls}" "no VPC endpoint"
                elif [ "${_route}" = "DNS_FAIL" ] || [ "${_tls}" = "DNS_FAIL" ]; then
                    _vpce_fail=$((_vpce_fail + 1))
                    printf "  %-18s %-42s %-8s %-7s %-8s %s\n" "${_svc}" "${_host}" "-" "FAIL" "DNS" "${_sans:0:50}"
                else
                    printf "  %-18s %-42s %-8s %-7s %-8s %s\n" "${_svc}" "${_host}" "${_ip}" "${_route}" "${_tls}" "${_sans:0:40}"
                fi
            elif [ "${_section}" = "iam" ]; then
                IFS='|' read -r _sid _action _result _note <<< "${_line}"
                _iam_total=$((_iam_total + 1))
                case "${_result}" in
                    OK)          _iam_ok=$((_iam_ok + 1));      printf "  %-18s %-40s %-14s %s\n" "${_sid}" "${_action}" "OK" "${_note:0:50}" ;;
                    DENIED)      _iam_denied=$((_iam_denied+1)); printf "  %-18s %-40s %-14s %s\n" "${_sid}" "${_action}" "*** DENIED ***" "${_note:0:60}" ;;
                    NO_ENDPOINT) _iam_noep=$((_iam_noep + 1));   printf "  %-18s %-40s %-14s %s\n" "${_sid}" "${_action}" "NO ENDPOINT" "${_note:0:50}" ;;
                    *)           printf "  %-18s %-40s %-14s %s\n" "${_sid}" "${_action}" "${_result}" "${_note:0:50}" ;;
                esac
            fi
        done

        echo ""
        echo "  ================================================================"
        echo "    Summary"
        echo "  ================================================================"
        echo ""
        echo "  VPC Endpoints: ${_vpce_ok}/${_vpce_total} reachable via VPCE, ${_vpce_fail} failed"
        echo "  IAM Permissions: ${_iam_ok}/${_iam_total} OK, ${_iam_denied} DENIED, ${_iam_noep} NO_ENDPOINT"
        echo ""
        if [ "${_iam_denied}" -gt 0 ] 2>/dev/null; then
            echo "  *** IAM PERMISSION FAILURES DETECTED ***"
            echo "  Admin: verify policy attached to ${CAP}-${DEPLOY_ENV}-app-role"
            echo "  Expected policy: kube-operator/permissions/app-policy-set.json"
            echo "  Run: aws iam get-role-policy --role-name ${CAP}-${DEPLOY_ENV}-app-role --policy-name <name>"
        fi
        if [ "${_vpce_fail}" -gt 0 ] 2>/dev/null; then
            echo "  *** VPC ENDPOINT ISSUES DETECTED ***"
            echo "  Admin: check VPC endpoint DNS and TLS in AWS Console > VPC > Endpoints"
        fi
        if [ "${_iam_noep}" -gt 0 ] 2>/dev/null; then
            echo "  *** MISSING VPC ENDPOINTS ***"
            echo "  Some AWS services are unreachable. Admin: create VPC endpoints for those services."
        fi
    }
fi
echo ""

# ── Call DB Doctor (from backend pod) ──
header "Call DB Doctor (Glue catalog health)"

DB_DOC_OK=0
DB_DOC_TOTAL=0

if [ -z "${BACKEND_POD}" ]; then
    row "Backend pod" "NOT FOUND" "Cannot run DB Doctor"
else
    row "Running DB Doctor inside" "—" "${BACKEND_POD}"

    DB_DOC_RAW=$(${KEXEC} python3 -c "
import os, sys, json
os.environ['USE_AWS_SECRETS'] = 'true'
sys.path.insert(0, '/app/scripts/call-scripts')
try:
    from src.services.db_doctor_service import DbDoctorService
    doctor = DbDoctorService()
    d = {
        'bucket': doctor.catalog.bucket,
        'database': doctor.catalog.database_name,
        'table': doctor.catalog.table_name,
    }
    report = doctor.diagnose()
    d.update(report.to_dict())
    print(json.dumps(d, default=str))
except Exception as e:
    import traceback
    print(json.dumps({'error': str(e), 'traceback': traceback.format_exc()[:500]}, default=str))
" 2>&1) && DB_DOC_EXIT=0 || DB_DOC_EXIT=$?

    DB_DOC_JSON=$(echo "${DB_DOC_RAW}" | grep -E '^\{' | tail -1)
    if [ -z "${DB_DOC_JSON}" ]; then
        row "DB Doctor" "EXEC FAIL" "no JSON output (exit=${DB_DOC_EXIT})"
        echo "${DB_DOC_RAW}" | tail -5 | while IFS= read -r _line; do
            row "  output" "—" "${_line:0:150}"
        done
    else
        _doc_err=$(echo "${DB_DOC_JSON}" | python3 -c "import sys,json; e=json.load(sys.stdin).get('error'); print(e if e and e != 'None' else '')" 2>/dev/null || echo "")

        if [ -n "${_doc_err}" ]; then
            row "DB Doctor" "ERROR" "${_doc_err:0:200}"
            _doc_tb=$(echo "${DB_DOC_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('traceback','')[:300])" 2>/dev/null || echo "")
            if [ -n "${_doc_tb}" ]; then
                row "  traceback" "—" "${_doc_tb}"
            fi
        else
            _doc_bucket=$(echo "${DB_DOC_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('bucket',''))" 2>/dev/null)
            _doc_db=$(echo "${DB_DOC_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('database',''))" 2>/dev/null)
            _doc_tbl=$(echo "${DB_DOC_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('table',''))" 2>/dev/null)
            _doc_stage=$(echo "${DB_DOC_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('stage',''))" 2>/dev/null)

            row "Config: bucket" "—" "${_doc_bucket}"
            row "Config: database" "—" "${_doc_db}"
            row "Config: table" "—" "${_doc_tbl}"
            row "Diagnosis stage" "—" "${_doc_stage}"
            echo ""
            printf "  %-45s %-12s %s\n" "---------------------------------------------" "------------" "-----------------------------"

            # Core checks
            for _field in database_exists table_exists s3_bucket_accessible; do
                DB_DOC_TOTAL=$((DB_DOC_TOTAL + 1))
                _val=$(echo "${DB_DOC_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('${_field}', False))" 2>/dev/null || echo "False")
                if [ "${_val}" = "True" ]; then
                    DB_DOC_OK=$((DB_DOC_OK + 1))
                    row "${_field}" "PASS" ""
                else
                    row "${_field}" "*** FAIL ***" ""
                fi
            done

            # Partition counts
            _s3_parts=$(echo "${DB_DOC_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('total_s3_partitions',0))" 2>/dev/null)
            _cat_parts=$(echo "${DB_DOC_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('total_catalog_partitions',0))" 2>/dev/null)
            _missing=$(echo "${DB_DOC_JSON}" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('missing_partitions',[])))" 2>/dev/null)
            _orphaned=$(echo "${DB_DOC_JSON}" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('orphaned_partitions',[])))" 2>/dev/null)
            row "S3 partitions" "—" "${_s3_parts}"
            row "Catalog partitions" "—" "${_cat_parts}"
            row "Missing (S3 but not catalog)" "—" "${_missing}"
            row "Orphaned (catalog but not S3)" "—" "${_orphaned}"

            # Schema
            _schema_valid=$(echo "${DB_DOC_JSON}" | python3 -c "import sys,json; si=json.load(sys.stdin).get('schema_info'); print(si.get('is_valid',False) if si else 'N/A')" 2>/dev/null || echo "N/A")
            _schema_issues=$(echo "${DB_DOC_JSON}" | python3 -c "import sys,json; si=json.load(sys.stdin).get('schema_info'); print(len(si.get('issues',[])) if si else 0)" 2>/dev/null || echo "0")
            DB_DOC_TOTAL=$((DB_DOC_TOTAL + 1))
            if [ "${_schema_valid}" = "True" ]; then
                DB_DOC_OK=$((DB_DOC_OK + 1))
                row "Schema valid" "PASS" "0 issues"
            else
                row "Schema valid" "FAIL" "${_schema_issues} issue(s)"
                echo "${DB_DOC_JSON}" | python3 -c "
import sys,json
si = json.load(sys.stdin).get('schema_info')
if si:
    for issue in si.get('issues', [])[:5]:
        print('SCHEMA_ISSUE|' + issue[:200])
" 2>/dev/null | while IFS='|' read -r _tag _issue; do
                    row "  schema issue" "—" "${_issue}"
                done
            fi

            # Athena query test
            _athena_ok=$(echo "${DB_DOC_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('athena_query_success',False))" 2>/dev/null)
            _athena_ms=$(echo "${DB_DOC_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('athena_query_time_ms',0))" 2>/dev/null)
            _athena_rows=$(echo "${DB_DOC_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('athena_row_count',0))" 2>/dev/null)
            _athena_err=$(echo "${DB_DOC_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('athena_error','') or '')" 2>/dev/null)
            DB_DOC_TOTAL=$((DB_DOC_TOTAL + 1))
            if [ "${_athena_ok}" = "True" ]; then
                DB_DOC_OK=$((DB_DOC_OK + 1))
                row "Athena query test" "PASS" "${_athena_ms}ms, ${_athena_rows} rows"
            else
                row "Athena query test" "FAIL" "${_athena_err:0:200}"
            fi

            # Data integrity
            _data_checked=$(echo "${DB_DOC_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('data_samples_checked',0))" 2>/dev/null)
            _data_issues=$(echo "${DB_DOC_JSON}" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('data_integrity_issues',[])))" 2>/dev/null)
            row "Data integrity" "—" "${_data_checked} sampled, ${_data_issues} issues"

            # Call assets
            _calls_ok=$(echo "${DB_DOC_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('calls_with_all_assets',0))" 2>/dev/null)
            _calls_missing=$(echo "${DB_DOC_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('calls_with_missing_assets',0))" 2>/dev/null)
            row "Call assets" "—" "${_calls_ok} ok, ${_calls_missing} with missing assets"

            # Recommendations
            echo ""
            printf "  %-45s %-12s %s\n" "---------------------------------------------" "------------" "-----------------------------"
            echo "${DB_DOC_JSON}" | python3 -c "
import sys,json
recs = json.load(sys.stdin).get('recommendations', [])
for r in recs[:10]:
    print('REC|' + r[:250])
if not recs:
    print('REC|No recommendations (database healthy or not accessible)')
" 2>/dev/null | while IFS='|' read -r _tag _rec; do
                row "  recommendation" "—" "${_rec}"
            done

            # Tracker summary
            _tracker=$(echo "${DB_DOC_JSON}" | python3 -c "import sys,json; t=json.load(sys.stdin).get('tracker_summary'); print(json.dumps(t)[:200] if t else '')" 2>/dev/null)
            if [ -n "${_tracker}" ]; then
                row "Task tracker summary" "—" "${_tracker}"
            fi
        fi
    fi
fi

echo ""
echo "  DB Doctor checks passed: ${DB_DOC_OK}/${DB_DOC_TOTAL}"
echo ""

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
    kubectl get nexuscapabilities.nexus.ai -n "${NS}" --no-headers 2>/dev/null) | wc -l)
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

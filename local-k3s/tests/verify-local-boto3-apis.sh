#!/bin/bash
#
# verify-local-boto3-apis.sh — Verify DynamoDB (Scylla) and Athena (MiniStack) boto3 APIs.
#
# Exercises the same split-endpoint pattern injected into nexus-ontology / nexus-ai pods:
#   AWS_ENDPOINT_URL_DYNAMODB -> Scylla Alternator
#   Athena/Glue -> MiniStack
#   S3 (Athena output) -> MinIO
#
# Usage:
#   ./verify-local-boto3-apis.sh
#   ./verify-local-boto3-apis.sh --kube-context local-cluster
#   ./verify-local-boto3-apis.sh --host   # run on this machine (requires port-forwards)
#   ./verify-local-boto3-apis.sh --skip-load
#   ./verify-local-boto3-apis.sh --workers 8 --stress-iterations 25 --endurance-seconds 60
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LK3S_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=../lib/common.sh
. "${LK3S_ROOT}/lib/common.sh"

NAMESPACE="nexus-local"
KUBE_CONTEXT=""
RUN_MODE="in-cluster"
CAPABILITIES="ontology,nexus-ai"
ENVIRONMENT="local"
SKIP_ATHENA=false
SKIP_LOAD=false
WORKERS=8
STRESS_ITERATIONS=25
ENDURANCE_SECONDS=60
ENDURANCE_WORKERS=4
SCYLLA_OVERRIDE=""
MINISTACK_OVERRIDE=""
MINIO_OVERRIDE=""

HOST_SCYLLA="${HOST_SCYLLA_ENDPOINT:-http://127.0.0.1:8000}"
HOST_MINISTACK="${HOST_MINISTACK_ENDPOINT:-http://127.0.0.1:4566}"
HOST_MINIO="${HOST_MINIO_ENDPOINT:-http://127.0.0.1:9000}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --kube-context) KUBE_CONTEXT="$2"; shift 2 ;;
        --namespace) NAMESPACE="$2"; shift 2 ;;
        --capabilities) CAPABILITIES="$2"; shift 2 ;;
        --environment) ENVIRONMENT="$2"; shift 2 ;;
        --host) RUN_MODE="host"; shift ;;
        --in-cluster) RUN_MODE="in-cluster"; shift ;;
        --skip-athena) SKIP_ATHENA=true; shift ;;
        --skip-load) SKIP_LOAD=true; shift ;;
        --workers) WORKERS="$2"; shift 2 ;;
        --stress-iterations) STRESS_ITERATIONS="$2"; shift 2 ;;
        --endurance-seconds) ENDURANCE_SECONDS="$2"; shift 2 ;;
        --endurance-workers) ENDURANCE_WORKERS="$2"; shift 2 ;;
        --scylla-endpoint) SCYLLA_OVERRIDE="$2"; shift 2 ;;
        --ministack-endpoint) MINISTACK_OVERRIDE="$2"; shift 2 ;;
        --minio-endpoint) MINIO_OVERRIDE="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [--kube-context NAME] [--namespace NS] [--host|--in-cluster]"
            echo "       [--capabilities ontology,nexus-ai] [--environment local] [--skip-athena]"
            echo "       [--skip-load] [--workers N] [--stress-iterations N]"
            echo "       [--endurance-seconds N] [--endurance-workers N]"
            echo "       [--scylla-endpoint URL] [--ministack-endpoint URL] [--minio-endpoint URL]"
            exit 0
            ;;
        *) lk3s_fail "Unknown option: $1"; exit 1 ;;
    esac
done

export KUBECONFIG="${LK3S_KUBECONFIG}"
KUBE_CONTEXT="${KUBE_CONTEXT:-${LK3S_CLUSTER_NAME}}"

kctl() {
    kubectl --context "${KUBE_CONTEXT}" "$@"
}

PY_SCRIPT="${SCRIPT_DIR}/verify_boto3_apis.py"
INIT_SCRIPT="${LK3S_DEPLOYER_ROOT}/kube-operator/scripts/local_init_aws.py"

# In-cluster always uses Service DNS. Do not inherit host port-forward env vars
# (SCYLLA_ENDPOINT / AWS_ENDPOINT_URL_* would point at 127.0.0.1).
INCLUSTER_SCYLLA="http://scylla-svc.${NAMESPACE}.svc.cluster.local:8000"
INCLUSTER_MINISTACK="http://ministack-svc.${NAMESPACE}.svc.cluster.local:4566"
INCLUSTER_MINIO="http://minio-svc.${NAMESPACE}.svc.cluster.local:9000"

lk3s_need_cmd python3

_run_host() {
    local scylla="${SCYLLA_OVERRIDE:-${HOST_SCYLLA}}"
    local ministack="${MINISTACK_OVERRIDE:-${HOST_MINISTACK}}"
    local minio="${MINIO_OVERRIDE:-${HOST_MINIO}}"
    lk3s_log "Running boto3 verification on host (requires port-forwards to nexus-local services)"
    lk3s_log "  Scylla:    ${scylla}"
    lk3s_log "  MiniStack: ${ministack}"
    lk3s_log "  MinIO:     ${minio}"
    echo ""
    local args=(
        "${PY_SCRIPT}"
        --capabilities "${CAPABILITIES}"
        --environment "${ENVIRONMENT}"
        --scylla-endpoint "${scylla}"
        --ministack-endpoint "${ministack}"
        --minio-endpoint "${minio}"
        --workers "${WORKERS}"
        --stress-iterations "${STRESS_ITERATIONS}"
        --endurance-seconds "${ENDURANCE_SECONDS}"
        --endurance-workers "${ENDURANCE_WORKERS}"
    )
    [[ "${SKIP_ATHENA}" == true ]] && args+=(--skip-athena)
    [[ "${SKIP_LOAD}" == true ]] && args+=(--skip-load)
    PYTHONPATH="${INIT_SCRIPT%/*}" PYTHONUNBUFFERED=1 python3 -u "${args[@]}"
}

_run_in_cluster() {
    local scylla="${SCYLLA_OVERRIDE:-${INCLUSTER_SCYLLA}}"
    local ministack="${MINISTACK_OVERRIDE:-${INCLUSTER_MINISTACK}}"
    local minio="${MINIO_OVERRIDE:-${INCLUSTER_MINIO}}"
    lk3s_log "Running boto3 verification inside cluster (namespace ${NAMESPACE})"
    lk3s_log "  Scylla:    ${scylla}"
    lk3s_log "  MiniStack: ${ministack}"
    lk3s_log "  MinIO:     ${minio}"
    if ! kctl get ns "${NAMESPACE}" >/dev/null 2>&1; then
        lk3s_fail "Namespace ${NAMESPACE} not found on context ${KUBE_CONTEXT} (KUBECONFIG=${KUBECONFIG})"
        lk3s_fail "Run: cd ${LK3S_ROOT} && ./deploy-local-aws-stack.sh --kube-context ${KUBE_CONTEXT}"
        exit 1
    fi

    CM_NAME="nexus-local-verify-boto3"
    kctl create configmap "${CM_NAME}" \
        --from-file=verify_boto3_apis.py="${PY_SCRIPT}" \
        --from-file=local_init_aws.py="${INIT_SCRIPT}" \
        -n "${NAMESPACE}" --dry-run=client -o yaml | kctl apply -f - >/dev/null

    local extra_flags=""
    [[ "${SKIP_ATHENA}" == true ]] && extra_flags="${extra_flags} --skip-athena"
    [[ "${SKIP_LOAD}" == true ]] && extra_flags="${extra_flags} --skip-load"

    kctl delete pod nexus-local-verify-boto3 -n "${NAMESPACE}" --ignore-not-found --wait=true >/dev/null 2>&1 || true
    kctl run nexus-local-verify-boto3 \
        --rm -i --restart=Never -n "${NAMESPACE}" \
        --image=python:3.12-slim \
        --overrides="$(cat <<EOF
{
  "spec": {
    "containers": [{
      "name": "verify",
      "image": "python:3.12-slim",
      "imagePullPolicy": "IfNotPresent",
      "env": [
        {"name": "PYTHONUNBUFFERED", "value": "1"},
        {"name": "FORCE_COLOR", "value": "1"},
        {"name": "AWS_ACCESS_KEY_ID", "value": "minioadmin"},
        {"name": "AWS_SECRET_ACCESS_KEY", "value": "minioadmin"},
        {"name": "AWS_DEFAULT_REGION", "value": "us-east-1"}
      ],
      "command": ["sh", "-c"],
      "args": ["pip install --no-cache-dir --root-user-action=ignore -q boto3 && python -u /scripts/verify_boto3_apis.py --capabilities ${CAPABILITIES} --environment ${ENVIRONMENT} --scylla-endpoint ${scylla} --ministack-endpoint ${ministack} --minio-endpoint ${minio} --workers ${WORKERS} --stress-iterations ${STRESS_ITERATIONS} --endurance-seconds ${ENDURANCE_SECONDS} --endurance-workers ${ENDURANCE_WORKERS} ${extra_flags}"],
      "volumeMounts": [
        {"name": "scripts", "mountPath": "/scripts"}
      ]
    }],
    "volumes": [{
      "name": "scripts",
      "configMap": {"name": "${CM_NAME}"}
    }]
  }
}
EOF
)"
}

case "${RUN_MODE}" in
    host)
        if ! python3 -c "import boto3" 2>/dev/null; then
            lk3s_fail "boto3 required on host: pip install boto3"
            exit 1
        fi
        _run_host
        ;;
    in-cluster)
        _run_in_cluster
        ;;
esac

lk3s_ok "boto3 API verification passed"

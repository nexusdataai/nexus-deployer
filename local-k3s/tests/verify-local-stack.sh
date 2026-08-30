#!/bin/bash
#
# verify-local-stack.sh — Functional R/W checks for the nexus-local shared stack.
#
# Covers the services MiniStack and application pods actually use:
#   MinIO (S3), Scylla (DynamoDB Alternator), Trino, Redis,
#   Postgres + pgvector + Apache AGE, MiniStack (SSM/Secrets), Mimir.
#
# Default: run the Python checker as a Job inside the cluster.
#   ./verify-local-stack.sh --kube-context local-cluster
#   ./verify-local-stack.sh --host   # requires port-forwards + local python deps
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LK3S_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=../lib/common.sh
. "${LK3S_ROOT}/lib/common.sh"

NAMESPACE="nexus-local"
KUBE_CONTEXT=""
RUN_MODE="in-cluster"
LOAD_ITEMS=40
MINIO_OBJECT_KB=32
PY_SCRIPT="${SCRIPT_DIR}/verify_local_stack.py"
JOB_NAME="nexus-verify-stack"
CM_NAME="nexus-verify-stack"
PY_IMAGE="${VERIFY_PY_IMAGE:-python:3.12-slim}"

usage() {
    cat <<EOF
Usage: $0 [options]

Options:
  --kube-context NAME   kubectl context (default: ${LK3S_CLUSTER_NAME})
  --namespace NS        stack namespace (default: nexus-local)
  --host                run checker on this machine (needs port-forwards)
  --in-cluster          run checker as a Job in the cluster (default)
  --load-items N        items/rows/keys for load loops (default: 40)
  --minio-object-kb N   size of each MinIO load object (default: 32)
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --kube-context) KUBE_CONTEXT="$2"; shift 2 ;;
        --namespace) NAMESPACE="$2"; shift 2 ;;
        --host) RUN_MODE="host"; shift ;;
        --in-cluster) RUN_MODE="in-cluster"; shift ;;
        --load-items) LOAD_ITEMS="$2"; shift 2 ;;
        --minio-object-kb) MINIO_OBJECT_KB="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) lk3s_fail "Unknown option: $1"; exit 1 ;;
    esac
done

export KUBECONFIG="${LK3S_KUBECONFIG}"
KUBE_CONTEXT="${KUBE_CONTEXT:-${LK3S_CLUSTER_NAME}}"

kctl() {
    kubectl --context "${KUBE_CONTEXT}" "$@"
}

preflight() {
    lk3s_log "Preflight: namespace ${NAMESPACE} on context ${KUBE_CONTEXT}"
    kctl get ns "${NAMESPACE}" >/dev/null

    echo ""
    echo "Pods:"
    kctl get pods -n "${NAMESPACE}" -o wide
    echo ""
    echo "Services:"
    kctl get svc -n "${NAMESPACE}"
    echo ""

    local not_ready
    not_ready="$(kctl get pods -n "${NAMESPACE}" --no-headers 2>/dev/null \
        | grep -vE 'Completed|Succeeded' \
        | grep -v 'nexus-verify-stack' \
        | grep -vcE 'Running|1/1' || true)"
    if [ "${not_ready}" != "0" ]; then
        lk3s_warn "Some pods are not Ready — checks for those services may skip or fail"
    fi

    local required=(minio-svc scylla-svc trino-svc redis-svc)
    local svc
    for svc in "${required[@]}"; do
        if kctl get svc "${svc}" -n "${NAMESPACE}" >/dev/null 2>&1; then
            lk3s_ok "service ${svc}"
        else
            lk3s_fail "missing required service ${svc}"
            return 1
        fi
    done
    for svc in pgvector-svc ministack-svc mimir-svc; do
        if kctl get svc "${svc}" -n "${NAMESPACE}" >/dev/null 2>&1; then
            lk3s_ok "service ${svc}"
        else
            lk3s_warn "optional service ${svc} not found"
        fi
    done
}

run_host() {
    lk3s_need_cmd python3
    lk3s_log "Running stack checker on host (port-forwards required)"
    python3 - <<'PY' || { lk3s_fail "Missing python deps. Install: pip install boto3 redis psycopg2-binary trino"; exit 1; }
import boto3, redis, psycopg2, trino
print("deps ok")
PY
    python3 "${PY_SCRIPT}" \
        --namespace "${NAMESPACE}" \
        --load-items "${LOAD_ITEMS}" \
        --minio-object-kb "${MINIO_OBJECT_KB}" \
        --minio-endpoint "${MINIO_ENDPOINT:-http://127.0.0.1:9000}" \
        --scylla-endpoint "${SCYLLA_ENDPOINT:-http://127.0.0.1:8001}" \
        --trino-host "${TRINO_HOST:-127.0.0.1}" \
        --trino-port "${TRINO_PORT:-8080}" \
        --redis-host "${REDIS_HOST:-127.0.0.1}" \
        --redis-port "${REDIS_PORT:-6379}" \
        --pg-host "${PG_HOST:-127.0.0.1}" \
        --pg-port "${PG_PORT:-5432}" \
        --ministack-endpoint "${MINISTACK_ENDPOINT:-http://127.0.0.1:4566}" \
        --mimir-url "${MIMIR_URL:-http://127.0.0.1:9090}"
}

run_in_cluster() {
    [ -f "${PY_SCRIPT}" ] || { lk3s_fail "Missing ${PY_SCRIPT}"; exit 1; }

    lk3s_log "Running stack checker as Job/${JOB_NAME} in ${NAMESPACE}"
    kctl delete job "${JOB_NAME}" -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1 || true
    kctl delete configmap "${CM_NAME}" -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1 || true

    kctl create configmap "${CM_NAME}" \
        --from-file=verify_local_stack.py="${PY_SCRIPT}" \
        -n "${NAMESPACE}" >/dev/null

    kctl apply -n "${NAMESPACE}" -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${JOB_NAME}
  labels:
    app: nexus-verify-stack
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 600
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: verify
          image: ${PY_IMAGE}
          imagePullPolicy: IfNotPresent
          env:
            - name: NAMESPACE
              value: ${NAMESPACE}
            - name: PYTHONUNBUFFERED
              value: "1"
            - name: FORCE_COLOR
              value: "1"
            - name: PIP_DISABLE_PIP_VERSION_CHECK
              value: "1"
            - name: PIP_ROOT_USER_ACTION
              value: ignore
          command: ["bash", "-lc"]
          args:
            - |
              set -euo pipefail
              echo "Installing Python packages (boto3 redis psycopg2-binary trino cramjam)…"
              pip install -q --no-cache-dir boto3 redis psycopg2-binary trino cramjam
              echo "Packages ready. Starting API matrix…"
              python -u /scripts/verify_local_stack.py \\
                --namespace ${NAMESPACE} \\
                --load-items ${LOAD_ITEMS} \\
                --minio-object-kb ${MINIO_OBJECT_KB}
          volumeMounts:
            - name: scripts
              mountPath: /scripts
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: "1"
              memory: 1Gi
      volumes:
        - name: scripts
          configMap:
            name: ${CM_NAME}
            defaultMode: 0555
EOF

    lk3s_log "Waiting for verifier pod..."
    local pod=""
    local i
    for i in $(seq 1 60); do
        pod="$(kctl get pods -n "${NAMESPACE}" -l job-name="${JOB_NAME}" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
        [ -n "${pod}" ] && break
        sleep 2
    done
    if [ -z "${pod}" ]; then
        lk3s_fail "Verifier pod did not start"
        return 1
    fi

    kctl wait --for=condition=Ready "pod/${pod}" -n "${NAMESPACE}" --timeout=180s >/dev/null 2>&1 || true
    echo ""
    kctl logs -n "${NAMESPACE}" -f "${pod}" 2>/dev/null || kctl logs -n "${NAMESPACE}" "${pod}" || true
    echo ""

    # logs -f returns when the container exits. Do not wait for Job Complete —
    # a failed Job never becomes Complete, so that wait burns the full timeout.
    local succeeded failed exit_code=""
    local i
    for i in $(seq 1 15); do
        exit_code="$(kctl get pod "${pod}" -n "${NAMESPACE}" -o jsonpath='{.status.containerStatuses[0].state.terminated.exitCode}' 2>/dev/null || true)"
        [ -n "${exit_code}" ] && break
        sleep 1
    done
    succeeded="$(kctl get job "${JOB_NAME}" -n "${NAMESPACE}" -o jsonpath='{.status.succeeded}' 2>/dev/null || true)"
    failed="$(kctl get job "${JOB_NAME}" -n "${NAMESPACE}" -o jsonpath='{.status.failed}' 2>/dev/null || true)"
    if [ "${succeeded:-0}" = "1" ] || [ "${exit_code:-1}" = "0" ]; then
        lk3s_ok "Stack verification job succeeded"
        return 0
    fi
    lk3s_fail "Stack verification job did not succeed (failed=${failed:-?} exit=${exit_code:-?})"
    kctl describe pod "${pod}" -n "${NAMESPACE}" | tail -25 || true
    return 1
}

preflight
echo ""
case "${RUN_MODE}" in
    host) run_host ;;
    in-cluster) run_in_cluster ;;
    *) lk3s_fail "Unknown run mode ${RUN_MODE}"; exit 1 ;;
esac

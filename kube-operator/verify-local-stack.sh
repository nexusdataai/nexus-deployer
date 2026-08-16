#!/bin/bash
#
# verify-local-stack.sh — Smoke checks for nexus-local AWS emulation stack.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="nexus-local"
KUBE_CONTEXT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --kube-context) KUBE_CONTEXT="$2"; shift 2 ;;
        --namespace) NAMESPACE="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

KUBECTL=(kubectl)
[ -n "${KUBE_CONTEXT}" ] && KUBECTL+=(--context "${KUBE_CONTEXT}")

fail=0
check() {
    if "$@"; then echo "  OK: $*"; else echo "  FAIL: $*" >&2; fail=1; fi
}

echo "Verifying namespace ${NAMESPACE} ..."
check "${KUBECTL[@]}" get ns "${NAMESPACE}"
check "${KUBECTL[@]}" get pods -n "${NAMESPACE}"

echo "Checking services ..."
for svc in redis-svc ministack-svc minio-svc scylla-svc trino-svc; do
    check "${KUBECTL[@]}" get svc "${svc}" -n "${NAMESPACE}"
done

echo "MiniStack health (in-cluster) ..."
check "${KUBECTL[@]}" run ms-health --rm -i --restart=Never -n "${NAMESPACE}" \
    --image=curlimages/curl:8.5.0 --command -- \
    curl -sf "http://ministack-svc:4566/_ministack/health"

echo "Trino info ..."
check "${KUBECTL[@]}" run trino-health --rm -i --restart=Never -n "${NAMESPACE}" \
    --image=curlimages/curl:8.5.0 --command -- \
    curl -sf "http://trino-svc:8080/v1/info"

if [ "${fail}" -eq 0 ]; then
    echo "Local stack verification passed"
else
    echo "Local stack verification failed" >&2
    exit 1
fi

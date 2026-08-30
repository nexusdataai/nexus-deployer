#!/bin/bash
#
# verify-local-k3s-cluster.sh — Health checks for local K3s cluster.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LK3S_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source=../lib/common.sh
. "${LK3S_ROOT}/lib/common.sh"

FAIL=0

check() {
    if "$@"; then
        lk3s_ok "$*"
    else
        lk3s_fail "$*"
        FAIL=1
    fi
}

lk3s_log "Verifying K3s cluster (${LK3S_CLUSTER_NAME})"
export KUBECONFIG="${LK3S_KUBECONFIG}"

check lk3s_kubectl cluster-info
check lk3s_kubectl get nodes
check lk3s_kubectl get storageclass local-path

verify_sample_pod() {
    local pod="lk3s-verify-$$"
    lk3s_kubectl run "${pod}" \
        --restart=Never \
        --image=busybox:1.36 \
        --command -- sleep 15
    lk3s_kubectl wait --for=condition=Ready "pod/${pod}" --timeout=60s
    lk3s_kubectl delete pod "${pod}" --ignore-not-found --wait=false >/dev/null
}
check verify_sample_pod

if [ "${FAIL}" -eq 0 ]; then
    lk3s_ok "K3s verification passed"
else
    lk3s_fail "K3s verification failed"
    exit 1
fi

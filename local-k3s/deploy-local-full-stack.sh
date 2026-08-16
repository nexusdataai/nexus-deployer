#!/bin/bash
#
# deploy-local-full-stack.sh — Orchestrate K3s + operator + local AWS emulation stack.
#
# Usage:
#   ./deploy-local-full-stack.sh
#   ./deploy-local-full-stack.sh --skip-k3s --product ontology --env local
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "${SCRIPT_DIR}/lib/common.sh"

KUBE_OP="${LK3S_DEPLOYER_ROOT}/kube-operator"
SKIP_K3S=false
SKIP_OPERATOR=false
SKIP_AWS_STACK=false
DEPLOY_CAPABILITY=""
DEPLOY_ENV="local"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-k3s) SKIP_K3S=true; shift ;;
        --skip-operator) SKIP_OPERATOR=true; shift ;;
        --skip-aws-stack) SKIP_AWS_STACK=true; shift ;;
        --product) DEPLOY_CAPABILITY="$2"; shift 2 ;;
        --env) DEPLOY_ENV="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [--skip-k3s] [--skip-operator] [--skip-aws-stack] [--product NAME] [--env ENV]"
            exit 0
            ;;
        *) lk3s_fail "Unknown option: $1"; shift ;;
    esac
done

export KUBECONFIG="${LK3S_KUBECONFIG}"

if [ "${SKIP_K3S}" = false ]; then
    if ! lk3s_kubectl get nodes >/dev/null 2>&1; then
        AUTO_APPROVE=yes "${SCRIPT_DIR}/create-local-k3s-cluster.sh"
    else
        lk3s_ok "K3s cluster already reachable"
    fi
    "${SCRIPT_DIR}/verify-local-k3s-cluster.sh"
fi

if [ "${SKIP_OPERATOR}" = false ]; then
    lk3s_log "Deploying Nexus operator ..."
    (cd "${KUBE_OP}" && CLUSTER_NAME="${LK3S_CLUSTER_NAME}" ./operator.sh deploy)
fi

if [ "${SKIP_AWS_STACK}" = false ]; then
    lk3s_log "Deploying nexus-local AWS emulation stack ..."
    (cd "${KUBE_OP}" && ./deploy-local-aws-stack.sh --kube-context "${LK3S_CLUSTER_NAME}")
fi

if [ -n "${DEPLOY_CAPABILITY}" ]; then
    lk3s_log "Deploying capability ${DEPLOY_CAPABILITY} (${DEPLOY_ENV}) ..."
    (cd "${KUBE_OP}" && ./deploy-capability.sh --product "${DEPLOY_CAPABILITY}" --env "${DEPLOY_ENV}" --skip-iam --skip-creds --skip-ssm-fix)
fi

lk3s_ok "Local full stack deployment complete"

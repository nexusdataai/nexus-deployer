#!/bin/bash
#
# deploy-local-aws-stack.sh — Deploy shared nexus-local AWS emulation stack (Helm).
#
# Usage:
#   ./deploy-local-aws-stack.sh
#   ./deploy-local-aws-stack.sh --kube-context local-cluster
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART_DIR="${SCRIPT_DIR}/charts/nexus-local-aws-stack"
NAMESPACE="nexus-local"
KUBE_CONTEXT=""
VALUES_FILE="${CHART_DIR}/values-k3s.yaml"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --kube-context) KUBE_CONTEXT="$2"; shift 2 ;;
        --namespace) NAMESPACE="$2"; shift 2 ;;
        --values) VALUES_FILE="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [--kube-context NAME] [--namespace NS] [--values FILE]"
            exit 0
            ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

KUBECTL=(kubectl)
if [ -n "${KUBE_CONTEXT}" ]; then
    KUBECTL+=(--context "${KUBE_CONTEXT}")
fi

if ! command -v helm >/dev/null 2>&1; then
    echo "helm is required; install from https://helm.sh" >&2
    exit 1
fi

mkdir -p "${CHART_DIR}/files"
cp "${SCRIPT_DIR}/scripts/local_init_aws.py" "${CHART_DIR}/files/local_init_aws.py"

echo "Installing Helm chart nexus-local-aws-stack ..."
helm upgrade --install nexus-local-aws "${CHART_DIR}" \
    -n "${NAMESPACE}" --create-namespace \
    -f "${VALUES_FILE}" \
    ${KUBE_CONTEXT:+--kube-context "$KUBE_CONTEXT"}

echo "Waiting for core pods ..."
for label in app=minio app=scylla app=ministack app=redis; do
    "${KUBECTL[@]}" wait --for=condition=ready pod -l "${label}" -n "${NAMESPACE}" --timeout=600s 2>/dev/null || true
done

echo "Waiting for init Job ..."
"${KUBECTL[@]}" wait --for=condition=complete job/nexus-local-init -n "${NAMESPACE}" --timeout=600s || {
    echo "Init job logs:"
    "${KUBECTL[@]}" logs -n "${NAMESPACE}" job/nexus-local-init --tail=100 || true
    exit 1
}

echo "nexus-local AWS stack deployed in namespace ${NAMESPACE}"

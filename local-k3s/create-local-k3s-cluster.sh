#!/bin/bash
#
# create-local-k3s-cluster.sh — Install a single-node K3s cluster for Nexus local dev.
#
# Usage:
#   ./create-local-k3s-cluster.sh
#   ./create-local-k3s-cluster.sh --name nexus-local-k3s
#   AUTO_APPROVE=yes ./create-local-k3s-cluster.sh
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/k3s-install.sh
. "${SCRIPT_DIR}/lib/k3s-install.sh"
# shellcheck source=lib/kubeconfig.sh
. "${SCRIPT_DIR}/lib/kubeconfig.sh"

AUTO_APPROVE="${AUTO_APPROVE:-no}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --name) LK3S_CLUSTER_NAME="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [--name CLUSTER_NAME]"
            exit 0
            ;;
        *) lk3s_fail "Unknown option: $1"; exit 1 ;;
    esac
done

echo ""
lk3s_log "Nexus local K3s cluster setup"
lk3s_log "Cluster: ${LK3S_CLUSTER_NAME}"
echo ""

lk3s_need_root
lk3s_check_ram_gb 8
lk3s_check_disk_gb 100

if [ "${AUTO_APPROVE}" != "yes" ]; then
    read -r -p "Install K3s on this host? [y/N] " ans
    case "${ans}" in
        y|Y|yes|YES) ;;
        *) echo "Aborted."; exit 0 ;;
    esac
fi

lk3s_install_server
lk3s_export_kubeconfig
lk3s_wait_node_ready 90
lk3s_verify_addons
lk3s_write_cluster_info

echo ""
lk3s_ok "K3s cluster ready"
echo "  export KUBECONFIG=${LK3S_KUBECONFIG}"
echo "  kubectl config use-context ${LK3S_CLUSTER_NAME}"
echo ""
echo "Next:"
echo "  cd ${LK3S_DEPLOYER_ROOT}/kube-operator && ./operator.sh deploy"
echo "  ./deploy-local-aws-stack.sh"
echo ""

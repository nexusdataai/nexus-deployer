#!/bin/bash
#
# delete-local-k3s-cluster.sh — Uninstall K3s and optionally purge data.
#
# Usage:
#   ./delete-local-k3s-cluster.sh
#   ./delete-local-k3s-cluster.sh --purge-data
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "${SCRIPT_DIR}/lib/common.sh"

PURGE_DATA=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --name) LK3S_CLUSTER_NAME="$2"; shift 2 ;;
        --purge-data) PURGE_DATA=true; shift ;;
        --help|-h)
            echo "Usage: $0 [--purge-data] [--name CLUSTER_NAME]"
            exit 0
            ;;
        *) lk3s_fail "Unknown option: $1"; exit 1 ;;
    esac
done

lk3s_need_root

if [ -x /usr/local/bin/k3s-uninstall.sh ]; then
    lk3s_log "Running k3s-uninstall.sh ..."
    lk3s_sudo /usr/local/bin/k3s-uninstall.sh || true
else
    lk3s_warn "k3s-uninstall.sh not found — K3s may not be installed"
fi

if [ "${PURGE_DATA}" = true ]; then
    lk3s_log "Purging K3s data ..."
    lk3s_sudo rm -rf /var/lib/rancher/k3s /etc/rancher/k3s 2>/dev/null || true
    lk3s_ok "Data purged"
fi

rm -f "${LK3S_CLUSTER_INFO}" 2>/dev/null || true
lk3s_ok "K3s removed (kubeconfig entry may remain in ${LK3S_KUBECONFIG})"

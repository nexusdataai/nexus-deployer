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
# shellcheck source=lib/k3s-install.sh
. "${SCRIPT_DIR}/lib/k3s-install.sh"
# shellcheck source=lib/kubeconfig.sh
. "${SCRIPT_DIR}/lib/kubeconfig.sh"

PURGE_DATA=false
VERBOSE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --name) LK3S_CLUSTER_NAME="$2"; shift 2 ;;
        --purge-data) PURGE_DATA=true; shift ;;
        --verbose|-v) VERBOSE=true; shift ;;
        --help|-h)
            echo "Usage: $0 [--purge-data] [--name CLUSTER_NAME] [--verbose]"
            exit 0
            ;;
        *) lk3s_fail "Unknown option: $1"; exit 1 ;;
    esac
done

lk3s_need_root

if ! lk3s_is_installed; then
    lk3s_warn "K3s does not appear to be installed on this host"
    lk3s_remove_kubeconfig_context
    rm -f "${LK3S_CLUSTER_INFO}" 2>/dev/null || true
    lk3s_ok "Nothing to remove"
    exit 0
fi

UNINSTALL_SCRIPT=""
if UNINSTALL_SCRIPT=$(lk3s_find_uninstall_script); then
    lk3s_log "Running ${UNINSTALL_SCRIPT} ..."
    lk3s_run_uninstall_script "${UNINSTALL_SCRIPT}" "${VERBOSE}" || true
else
    lk3s_warn "No k3s uninstall script found — stopping processes with k3s-killall.sh"
    if [ -x /usr/local/bin/k3s-killall.sh ]; then
        lk3s_sudo /usr/local/bin/k3s-killall.sh || true
    fi
    lk3s_sudo rm -rf /etc/rancher/k3s /var/lib/rancher/k3s /run/k3s /run/flannel 2>/dev/null || true
    lk3s_sudo rm -f /usr/local/bin/k3s /usr/local/bin/k3s-killall.sh 2>/dev/null || true
    for svc in /etc/systemd/system/k3s*.service; do
        [ -f "${svc}" ] || continue
        lk3s_sudo systemctl disable "$(basename "${svc}")" 2>/dev/null || true
        lk3s_sudo rm -f "${svc}" "${svc}.env" 2>/dev/null || true
    done
    lk3s_sudo systemctl daemon-reload 2>/dev/null || true
fi

if [ "${PURGE_DATA}" = true ]; then
    lk3s_log "Purging remaining K3s data ..."
    lk3s_sudo rm -rf /var/lib/rancher/k3s /etc/rancher/k3s /var/lib/kubelet 2>/dev/null || true
    lk3s_ok "Data purged"
fi

lk3s_remove_kubeconfig_context
rm -f "${LK3S_CLUSTER_INFO}" 2>/dev/null || true

if lk3s_is_installed; then
    lk3s_fail "K3s still appears to be installed — check /usr/local/bin/k3s and systemd units"
    exit 1
fi

lk3s_ok "K3s removed"

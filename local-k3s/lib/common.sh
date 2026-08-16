#!/bin/bash
# Shared helpers for local K3s cluster scripts.

set -euo pipefail

LK3S_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LK3S_DEPLOYER_ROOT="$(cd "${LK3S_ROOT}/.." && pwd)"
LK3S_KUBECONFIG_DIR="${LK3S_DEPLOYER_ROOT}/aws-login/.kube"
LK3S_KUBECONFIG="${KUBECONFIG:-${LK3S_KUBECONFIG_DIR}/config}"
LK3S_CLUSTER_NAME="${CLUSTER_NAME:-local-cluster}"
LK3S_CLUSTER_INFO="${LK3S_ROOT}/.cluster-info"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

lk3s_log()   { echo -e "${CYAN}[local-k3s]${NC} $*"; }
lk3s_ok()    { echo -e "${GREEN}  ✓${NC} $*"; }
lk3s_warn()  { echo -e "${YELLOW}  ⚠${NC} $*"; }
lk3s_fail()  { echo -e "${RED}  ✗${NC} $*" >&2; }

lk3s_need_cmd() {
    command -v "$1" >/dev/null 2>&1 || {
        lk3s_fail "Required command not found: $1"
        exit 1
    }
}

lk3s_need_root() {
    if [ "$(id -u)" -ne 0 ] && ! command -v sudo >/dev/null 2>&1; then
        lk3s_fail "Root or sudo required to install K3s"
        exit 1
    fi
}

lk3s_sudo() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}

lk3s_kubectl() {
    export KUBECONFIG="${LK3S_KUBECONFIG}"
    if command -v kubectl >/dev/null 2>&1; then
        kubectl "$@"
    elif [ -x /usr/local/bin/k3s ]; then
        lk3s_sudo k3s kubectl "$@"
    else
        lk3s_fail "kubectl not found; install K3s first"
        exit 1
    fi
}

lk3s_write_cluster_info() {
    mkdir -p "$(dirname "${LK3S_CLUSTER_INFO}")"
    cat >"${LK3S_CLUSTER_INFO}" <<EOF
CLUSTER_NAME=${LK3S_CLUSTER_NAME}
KUBECONFIG=${LK3S_KUBECONFIG}
CONTEXT=${LK3S_CLUSTER_NAME}
STORAGE_CLASS=local-path
CREATED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
EOF
}

lk3s_check_disk_gb() {
    local min_gb="${1:-100}"
    local avail_kb
    avail_kb=$(df -Pk "${LK3S_ROOT}" | awk 'NR==2 {print $4}')
    local avail_gb=$((avail_kb / 1024 / 1024))
    if [ "${avail_gb}" -lt "${min_gb}" ]; then
        lk3s_warn "Available disk ${avail_gb}GB < recommended ${min_gb}GB"
    else
        lk3s_ok "Disk OK: ${avail_gb}GB available"
    fi
}

lk3s_check_ram_gb() {
    local min_gb="${1:-8}"
    local total_kb
    total_kb=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    local total_gb=$((total_kb / 1024 / 1024))
    if [ "${total_gb}" -lt "${min_gb}" ]; then
        lk3s_warn "RAM ${total_gb}GB < recommended ${min_gb}GB — stack may OOM"
    else
        lk3s_ok "RAM OK: ${total_gb}GB"
    fi
}

#!/bin/bash
# Install or verify K3s server.

lk3s_install_server() {
    local config_file="${LK3S_ROOT}/config/k3s-server.yaml"
    lk3s_need_cmd curl

    if lk3s_sudo test -x /usr/local/bin/k3s 2>/dev/null; then
        lk3s_ok "K3s already installed"
        return 0
    fi

    lk3s_log "Installing K3s server (https://get.k3s.io) ..."
    local exec_args="server --write-kubeconfig-mode 644"
    if [ -f "${config_file}" ]; then
        exec_args="${exec_args} --config ${config_file}"
    fi

    curl -sfL https://get.k3s.io | INSTALL_K3S_NAME="${LK3S_CLUSTER_NAME}" \
        INSTALL_K3S_EXEC="${exec_args}" sh -

    lk3s_ok "K3s installed"
}

lk3s_wait_node_ready() {
    local attempts="${1:-60}"
    lk3s_log "Waiting for node Ready ..."
    local i=0
    while [ "${i}" -lt "${attempts}" ]; do
        if lk3s_kubectl get nodes -o jsonpath='{.items[0].status.conditions[?(@.type=="Ready")].status}' 2>/dev/null | grep -q True; then
            lk3s_ok "Node is Ready"
            return 0
        fi
        sleep 2
        i=$((i + 1))
    done
    lk3s_fail "Node did not become Ready within $((attempts * 2))s"
    return 1
}

lk3s_verify_addons() {
    lk3s_log "Checking CoreDNS and local-path storage ..."
    lk3s_kubectl get deploy -n kube-system coredns >/dev/null 2>&1 && lk3s_ok "CoreDNS running" || lk3s_warn "CoreDNS not found"
    if lk3s_kubectl get storageclass local-path >/dev/null 2>&1; then
        lk3s_ok "StorageClass local-path present"
    else
        lk3s_warn "StorageClass local-path missing — check K3s install"
    fi
}

# Resolve the K3s uninstall script for this host.
# create-local-k3s-cluster.sh installs with INSTALL_K3S_NAME=$LK3S_CLUSTER_NAME, which
# produces k3s-<name>-uninstall.sh (not k3s-uninstall.sh).
lk3s_find_uninstall_script() {
    local -a candidates=()
    local svc base script

    candidates+=("/usr/local/bin/k3s-${LK3S_CLUSTER_NAME}-uninstall.sh")
    candidates+=("/usr/local/bin/k3s-uninstall.sh")

    for svc in /etc/systemd/system/k3s*.service; do
        [ -f "${svc}" ] || continue
        base=$(basename "${svc}" .service)
        candidates+=("/usr/local/bin/${base}-uninstall.sh")
    done

    for script in /usr/local/bin/k3s-*-uninstall.sh; do
        [ -f "${script}" ] || continue
        candidates+=("${script}")
    done

    local seen=" "
    for script in "${candidates[@]}"; do
        case "${seen}" in
            *" ${script} "*) continue ;;
        esac
        seen="${seen}${script} "
        if [ -x "${script}" ]; then
            echo "${script}"
            return 0
        fi
    done
    return 1
}

lk3s_is_installed() {
    [ -x /usr/local/bin/k3s ] || return 1
    compgen -G '/etc/systemd/system/k3s*.service' >/dev/null 2>&1 && return 0
    pgrep -x k3s >/dev/null 2>&1 && return 0
    return 1
}

# Run the upstream K3s uninstall script with less terminal noise.
# The stock script uses set -x and may print benign stderr such as
# "Cannot find device" or "Unit ... not loaded" while tearing down CNI.
lk3s_run_uninstall_script() {
    local script="$1"
    local verbose="${2:-false}"

    if [ "${verbose}" = true ]; then
        lk3s_sudo "${script}"
        return $?
    fi

    local output rc
    output=$(mktemp)
    if lk3s_sudo "${script}" >"${output}" 2>&1; then
        rc=0
    else
        rc=$?
    fi

    grep -vE \
        '^(Cannot find device|Failed to reset failed state of unit|Unit .+ not loaded\.|\+\s)' \
        "${output}" >&2 || true
    rm -f "${output}"
    return "${rc}"
}

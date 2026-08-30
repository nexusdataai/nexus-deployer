#!/bin/bash
# Merge K3s kubeconfig into project aws-login/.kube/config

lk3s_export_kubeconfig() {
    local src="/etc/rancher/k3s/k3s.yaml"
    if ! lk3s_sudo test -f "${src}"; then
        lk3s_fail "K3s kubeconfig not found at ${src}"
        return 1
    fi

    mkdir -p "${LK3S_KUBECONFIG_DIR}"
    local tmp
    tmp=$(mktemp)
    lk3s_sudo cat "${src}" >"${tmp}"

    # Rename default context/cluster/user to nexus-local-k3s
    sed -i "s/name: default/name: ${LK3S_CLUSTER_NAME}/g" "${tmp}" 2>/dev/null || \
        sed -i '' "s/name: default/name: ${LK3S_CLUSTER_NAME}/g" "${tmp}"
    sed -i "s/cluster: default/cluster: ${LK3S_CLUSTER_NAME}/g" "${tmp}" 2>/dev/null || \
        sed -i '' "s/cluster: default/cluster: ${LK3S_CLUSTER_NAME}/g" "${tmp}"
    sed -i "s/user: default/user: ${LK3S_CLUSTER_NAME}/g" "${tmp}" 2>/dev/null || \
        sed -i '' "s/user: default/user: ${LK3S_CLUSTER_NAME}/g" "${tmp}"
    sed -i "s/current-context: default/current-context: ${LK3S_CLUSTER_NAME}/g" "${tmp}" 2>/dev/null || \
        sed -i '' "s/current-context: default/current-context: ${LK3S_CLUSTER_NAME}/g" "${tmp}"

    if [ -f "${LK3S_KUBECONFIG}" ]; then
        KUBECONFIG="${tmp}:${LK3S_KUBECONFIG}" kubectl config view --flatten >"${LK3S_KUBECONFIG}.merged"
        mv "${LK3S_KUBECONFIG}.merged" "${LK3S_KUBECONFIG}"
        rm -f "${tmp}"
    else
        mv "${tmp}" "${LK3S_KUBECONFIG}"
    fi

    chmod 600 "${LK3S_KUBECONFIG}" 2>/dev/null || true
    export KUBECONFIG="${LK3S_KUBECONFIG}"
    kubectl config use-context "${LK3S_CLUSTER_NAME}" >/dev/null 2>&1 || true
    lk3s_ok "Kubeconfig exported to ${LK3S_KUBECONFIG} (context: ${LK3S_CLUSTER_NAME})"
}

lk3s_remove_kubeconfig_context() {
    if [ ! -f "${LK3S_KUBECONFIG}" ]; then
        return 0
    fi
    export KUBECONFIG="${LK3S_KUBECONFIG}"
    kubectl config delete-context "${LK3S_CLUSTER_NAME}" >/dev/null 2>&1 || true
    kubectl config delete-cluster "${LK3S_CLUSTER_NAME}" >/dev/null 2>&1 || true
    kubectl config unset "users.${LK3S_CLUSTER_NAME}" >/dev/null 2>&1 || true
    lk3s_ok "Removed kubeconfig context ${LK3S_CLUSTER_NAME}"
}

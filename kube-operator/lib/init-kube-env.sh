#!/bin/sh
# Initialize project-local KUBECONFIG for kube-operator scripts.
#
# Source AFTER SCRIPT_DIR is set in the calling script:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   . "${SCRIPT_DIR}/lib/init-kube-env.sh"
#
# Skipped inside operator pods (KUBERNETES_SERVICE_HOST set). Force local mode:
#   NEXUS_FORCE_LOCAL_KUBECONFIG=1 ./inspect-capability.sh --local

if [ -n "${NEXUS_KUBE_ENV_INITIALIZED:-}" ]; then
    # Parent script may have initialized kube env without loading aws-cli helpers.
    if [ -n "${SCRIPT_DIR:-}" ] && [ -z "${NEXUS_AWS_LOGIN_DIR:-}" ]; then
        _AWS_LOGIN_DIR="$(cd "${SCRIPT_DIR}/../aws-login" && pwd)"
        # shellcheck source=../../aws-login/lib/kube-env.sh
        . "${_AWS_LOGIN_DIR}/lib/kube-env.sh"
        nexus_kube_env_init "${_AWS_LOGIN_DIR}"
        unset _AWS_LOGIN_DIR
    fi
    if [ -n "${SCRIPT_DIR:-}" ] && ! type nexus_aws_account_id >/dev/null 2>&1; then
        # shellcheck source=aws-cli.sh
        . "${SCRIPT_DIR}/lib/aws-cli.sh"
    fi
    return 0 2>/dev/null || exit 0
fi

if [ -n "${KUBERNETES_SERVICE_HOST:-}" ] && [ "${NEXUS_FORCE_LOCAL_KUBECONFIG:-}" != "1" ]; then
    export NEXUS_KUBE_ENV_INITIALIZED=1
    return 0 2>/dev/null || exit 0
fi

if [ -z "${SCRIPT_DIR:-}" ]; then
    echo "init-kube-env.sh: SCRIPT_DIR must be set before sourcing" >&2
    return 1 2>/dev/null || exit 1
fi

_AWS_LOGIN_DIR="$(cd "${SCRIPT_DIR}/../aws-login" && pwd)"
# shellcheck source=../../aws-login/lib/kube-env.sh
. "${_AWS_LOGIN_DIR}/lib/kube-env.sh"
nexus_kube_env_init "${_AWS_LOGIN_DIR}"
# shellcheck source=aws-cli.sh
. "${SCRIPT_DIR}/lib/aws-cli.sh"

export NEXUS_KUBE_ENV_INITIALIZED=1
unset _AWS_LOGIN_DIR

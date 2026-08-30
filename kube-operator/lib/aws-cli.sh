#!/bin/sh
# AWS CLI helpers for kube-operator scripts (jumpbox + dev workstation).
#
# Sourced from lib/init-kube-env.sh after .active-env is loaded.

# Run aws with profile only when AWS_PROFILE is set and non-empty.
aws_cli() {
    if [ -n "${AWS_PROFILE:-}" ]; then
        aws --profile "${AWS_PROFILE}" "$@"
    else
        aws "$@"
    fi
}

# Print current AWS account or empty.
nexus_aws_account_id() {
    local account
    account=$(aws_cli sts get-caller-identity --query 'Account' --output text 2>/dev/null || true)
    if [ -n "$account" ] && [ "$account" != "None" ]; then
        echo "$account"
        return 0
    fi
    # Local K3s .active-env uses minioadmin keys for Scylla/MinIO — not valid for STS/ECR.
    if [ "${NEXUS_LOCAL_K3S:-}" = "1" ] || [ "${NEXUS_AWS_AUTH_TYPE:-}" = "local" ] || [ "${AWS_PROFILE:-}" = "local" ]; then
        account=$(env -u AWS_PROFILE -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN -u AWS_DEFAULT_PROFILE \
            aws sts get-caller-identity --query 'Account' --output text 2>/dev/null || true)
        if [ -n "$account" ] && [ "$account" != "None" ]; then
            echo "$account"
        fi
    fi
}

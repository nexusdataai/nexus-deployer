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
    aws_cli sts get-caller-identity --query 'Account' --output text 2>/dev/null || true
}

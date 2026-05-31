#!/bin/bash
#
# Cross-Account Provisioner Role Setup
# Creates a NexusClusterProvisioner role in each member account that only
# the master account can assume, with a permission boundary to prevent
# privilege escalation.
#
# Usage:
#   ./setup-cross-account-roles.sh --account-id 123456789012
#   ./setup-cross-account-roles.sh --all-accounts
#   ./setup-cross-account-roles.sh --all-accounts --external-id my-secret-id
#

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
POLICIES_DIR="${SCRIPT_DIR}/policies"

# Defaults
AWS_PROFILE="${AWS_PROFILE:-default}"
REGION="${REGION:-us-east-1}"
ACCOUNT_ID=""
ALL_ACCOUNTS=false
AUTO_APPROVE="${AUTO_APPROVE:-no}"
ROLE_NAME="NexusClusterProvisioner"
POLICY_NAME="NexusClusterProvisionerPolicy"
BOUNDARY_NAME="NexusProvisionerBoundary"
EXTERNAL_ID="${EXTERNAL_ID:-nexus-provision-$(date +%Y)}"
BOOTSTRAP_ROLE="${BOOTSTRAP_ROLE:-OrganizationAccountAccessRole}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --profile)         AWS_PROFILE="$2"; shift 2 ;;
        --region)          REGION="$2"; shift 2 ;;
        --account-id)      ACCOUNT_ID="$2"; shift 2 ;;
        --all-accounts)    ALL_ACCOUNTS=true; shift ;;
        --external-id)     EXTERNAL_ID="$2"; shift 2 ;;
        --bootstrap-role)  BOOTSTRAP_ROLE="$2"; shift 2 ;;
        --auto-approve)    AUTO_APPROVE=yes; shift ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Create NexusClusterProvisioner role in member accounts."
            echo ""
            echo "Options:"
            echo "  --account-id ID           Target member account (or use --all-accounts)"
            echo "  --all-accounts            Create in all member accounts"
            echo "  --external-id ID          External ID for role assumption (default: auto-generated)"
            echo "  --bootstrap-role ROLE     Role to assume for initial setup (default: OrganizationAccountAccessRole)"
            echo "  --profile PROFILE         AWS CLI profile (default: default)"
            echo "  --auto-approve            Skip confirmation prompts"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

AWS_CMD="aws --profile ${AWS_PROFILE} --region ${REGION}"

log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
info() { log "INFO  $*"; }
warn() { log "WARN  $*"; }
err()  { log "ERROR $*"; }
die()  { err "$*"; exit 1; }

confirm() {
    if [[ "${AUTO_APPROVE}" == "yes" ]]; then return 0; fi
    read -r -p "$1 [y/N]: " response
    [[ "$response" =~ ^[Yy]$ ]]
}

MASTER_ACCOUNT_ID=$(${AWS_CMD} sts get-caller-identity --query 'Account' --output text)
info "Master account: ${MASTER_ACCOUNT_ID}"

TARGET_CMD="aws --region ${REGION}"

# ── Cross-Account Session ───────────────────────────────────────────────────

assume_bootstrap_role() {
    local target_account="$1"
    local role_arn="arn:aws:iam::${target_account}:role/${BOOTSTRAP_ROLE}"

    info "Assuming bootstrap role ${role_arn}..."
    local creds
    creds=$(${AWS_CMD} sts assume-role \
        --role-arn "${role_arn}" \
        --role-session-name "nexus-role-setup" \
        --duration-seconds 3600 \
        --output json)

    export AWS_ACCESS_KEY_ID=$(echo "${creds}" | python3 -c "import sys,json; print(json.load(sys.stdin)['Credentials']['AccessKeyId'])")
    export AWS_SECRET_ACCESS_KEY=$(echo "${creds}" | python3 -c "import sys,json; print(json.load(sys.stdin)['Credentials']['SecretAccessKey'])")
    export AWS_SESSION_TOKEN=$(echo "${creds}" | python3 -c "import sys,json; print(json.load(sys.stdin)['Credentials']['SessionToken'])")
}

clear_assumed_role() {
    unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
}

# ── Role Creation ───────────────────────────────────────────────────────────

create_provisioner_role() {
    local target_account="$1"

    if [[ "${target_account}" == "${MASTER_ACCOUNT_ID}" ]]; then
        warn "Skipping master account."
        return
    fi

    info ""
    info "── Setting up ${ROLE_NAME} in account ${target_account} ──"

    assume_bootstrap_role "${target_account}"

    local verified_id
    verified_id=$(${TARGET_CMD} sts get-caller-identity --query 'Account' --output text 2>/dev/null)
    if [[ "${verified_id}" != "${target_account}" ]]; then
        warn "Could not verify role assumption for ${target_account}. Skipping."
        clear_assumed_role
        return
    fi

    local trust_policy
    trust_policy=$(cat "${POLICIES_DIR}/cross-account-provisioner-role.json" \
        | sed "s/\${MASTER_ACCOUNT_ID}/${MASTER_ACCOUNT_ID}/g" \
        | sed "s/\${EXTERNAL_ID}/${EXTERNAL_ID}/g")

    local provisioner_policy
    provisioner_policy=$(cat "${POLICIES_DIR}/cross-account-provisioner-policy.json")

    local existing_role
    existing_role=$(${TARGET_CMD} iam get-role --role-name "${ROLE_NAME}" \
        --query 'Role.Arn' --output text 2>/dev/null || echo "NONE")

    if [[ "${existing_role}" != "NONE" ]]; then
        info "Role ${ROLE_NAME} already exists. Updating trust policy and permissions..."
        ${TARGET_CMD} iam update-assume-role-policy \
            --role-name "${ROLE_NAME}" \
            --policy-document "${trust_policy}"
    else
        info "Creating role ${ROLE_NAME}..."
        ${TARGET_CMD} iam create-role \
            --role-name "${ROLE_NAME}" \
            --assume-role-policy-document "${trust_policy}" \
            --description "Cross-account role for nexus-ai cluster provisioning from master account" \
            --max-session-duration 7200 \
            --tags "Key=nexus:managed-by,Value=aws-account-security" >/dev/null
    fi

    info "Creating/updating provisioner policy..."
    local policy_arn="arn:aws:iam::${target_account}:policy/${POLICY_NAME}"
    local policy_exists
    policy_exists=$(${TARGET_CMD} iam get-policy --policy-arn "${policy_arn}" \
        --query 'Policy.Arn' --output text 2>/dev/null || echo "NONE")

    if [[ "${policy_exists}" != "NONE" ]]; then
        local versions
        versions=$(${TARGET_CMD} iam list-policy-versions --policy-arn "${policy_arn}" \
            --query 'Versions[?!IsDefaultVersion].VersionId' --output text 2>/dev/null)
        for v in ${versions}; do
            ${TARGET_CMD} iam delete-policy-version --policy-arn "${policy_arn}" \
                --version-id "${v}" 2>/dev/null || true
        done

        ${TARGET_CMD} iam create-policy-version \
            --policy-arn "${policy_arn}" \
            --policy-document "${provisioner_policy}" \
            --set-as-default >/dev/null
    else
        ${TARGET_CMD} iam create-policy \
            --policy-name "${POLICY_NAME}" \
            --policy-document "${provisioner_policy}" \
            --description "Permissions for nexus-ai cluster provisioning" >/dev/null
    fi

    info "Attaching provisioner policy to role..."
    ${TARGET_CMD} iam attach-role-policy \
        --role-name "${ROLE_NAME}" \
        --policy-arn "${policy_arn}" 2>/dev/null || true

    info "Creating/updating permission boundary..."
    local boundary_arn="arn:aws:iam::${target_account}:policy/${BOUNDARY_NAME}"
    local boundary_exists
    boundary_exists=$(${TARGET_CMD} iam get-policy --policy-arn "${boundary_arn}" \
        --query 'Policy.Arn' --output text 2>/dev/null || echo "NONE")

    if [[ "${boundary_exists}" != "NONE" ]]; then
        local bversions
        bversions=$(${TARGET_CMD} iam list-policy-versions --policy-arn "${boundary_arn}" \
            --query 'Versions[?!IsDefaultVersion].VersionId' --output text 2>/dev/null)
        for v in ${bversions}; do
            ${TARGET_CMD} iam delete-policy-version --policy-arn "${boundary_arn}" \
                --version-id "${v}" 2>/dev/null || true
        done

        ${TARGET_CMD} iam create-policy-version \
            --policy-arn "${boundary_arn}" \
            --policy-document "${provisioner_policy}" \
            --set-as-default >/dev/null
    else
        ${TARGET_CMD} iam create-policy \
            --policy-name "${BOUNDARY_NAME}" \
            --policy-document "${provisioner_policy}" \
            --description "Permission boundary for nexus-ai provisioner role" >/dev/null
    fi

    info "Attaching permission boundary to role..."
    ${TARGET_CMD} iam put-role-permissions-boundary \
        --role-name "${ROLE_NAME}" \
        --permissions-boundary "${boundary_arn}" 2>/dev/null || true

    clear_assumed_role
    info "── ${ROLE_NAME} configured in account ${target_account} ──"
}

# ── Main ────────────────────────────────────────────────────────────────────

main() {
    info "=========================================="
    info "Cross-Account Provisioner Role Setup"
    info "=========================================="
    info "Master Account: ${MASTER_ACCOUNT_ID}"
    info "Role Name:      ${ROLE_NAME}"
    info "External ID:    ${EXTERNAL_ID}"
    info ""

    if [[ "${ALL_ACCOUNTS}" == "true" ]]; then
        local accounts
        accounts=$(${AWS_CMD} organizations list-accounts \
            --query "Accounts[?Status=='ACTIVE'].Id" --output text)

        local count
        count=$(echo "${accounts}" | wc -w)
        info "Found ${count} active accounts."

        if ! confirm "Create ${ROLE_NAME} in all member accounts?"; then
            info "Aborted."
            exit 0
        fi

        for acct in ${accounts}; do
            create_provisioner_role "${acct}"
        done
    elif [[ -n "${ACCOUNT_ID}" ]]; then
        if ! confirm "Create ${ROLE_NAME} in account ${ACCOUNT_ID}?"; then
            info "Aborted."
            exit 0
        fi
        create_provisioner_role "${ACCOUNT_ID}"
    else
        die "Specify --account-id or --all-accounts."
    fi

    info ""
    info "=========================================="
    info "Cross-account role setup complete."
    info "=========================================="
    info ""
    info "To provision a cluster in a member account from master:"
    info "  aws sts assume-role \\"
    info "    --role-arn arn:aws:iam::<MEMBER_ACCOUNT>:role/${ROLE_NAME} \\"
    info "    --external-id ${EXTERNAL_ID} \\"
    info "    --role-session-name nexus-provisioner"
}

main

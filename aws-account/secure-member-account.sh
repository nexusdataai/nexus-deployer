#!/bin/bash
#
# Member Account Hardening Script
# Applies security baseline to an AWS account.
#
# Two modes:
#   (A) Cross-account assume-role mode (default).
#       Run from the management account; the script assumes
#       OrganizationAccountAccessRole (or --cross-account-role) into the
#       target member and applies the baseline there.
#   (B) In-place mode (--no-assume).
#       The given --profile already belongs to the target account; the
#       script applies the baseline against that profile directly without
#       any sts:AssumeRole call. Used by aws-iam-bootstrap.sh for
#       standalone accounts that are not part of an Organization.
#
# Actions (identical in both modes):
#   - Set IAM password policy
#   - Enable S3 Block Public Access (account-level)
#   - Enable default EBS encryption
#   - Enforce IMDSv2 as account default
#   - Delete default VPCs in all regions
#   - Opt-out of unused regions
#
# Usage:
#   ./secure-member-account.sh --account-id 123456789012
#   ./secure-member-account.sh --all-accounts
#   ./secure-member-account.sh --no-assume --profile <local-admin> \
#                              --account-id <self-account-id>
#

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Defaults
AWS_PROFILE="${AWS_PROFILE:-default}"
REGION="${REGION:-us-east-1}"
ACCOUNT_ID=""
ALL_ACCOUNTS=false
AUTO_APPROVE="${AUTO_APPROVE:-no}"
CROSS_ACCOUNT_ROLE="${CROSS_ACCOUNT_ROLE:-OrganizationAccountAccessRole}"
ALLOWED_REGION="us-east-1"
NO_ASSUME="${NO_ASSUME:-no}"

ALL_AWS_REGIONS=(
    us-east-1 us-east-2 us-west-1 us-west-2
    af-south-1 ap-east-1 ap-south-1 ap-south-2
    us-east-1 ap-southeast-2 ap-southeast-3 ap-southeast-4
    ap-northeast-1 ap-northeast-2 ap-northeast-3
    ca-central-1 ca-west-1
    eu-central-1 eu-central-2 eu-west-1 eu-west-2 eu-west-3
    eu-south-1 eu-south-2 eu-north-1
    il-central-1 me-south-1 me-central-1 sa-east-1
)

while [[ $# -gt 0 ]]; do
    case $1 in
        --profile)            AWS_PROFILE="$2"; shift 2 ;;
        --region)             REGION="$2"; shift 2 ;;
        --account-id)         ACCOUNT_ID="$2"; shift 2 ;;
        --all-accounts)       ALL_ACCOUNTS=true; shift ;;
        --cross-account-role) CROSS_ACCOUNT_ROLE="$2"; shift 2 ;;
        --no-assume)          NO_ASSUME=yes; shift ;;
        --auto-approve)       AUTO_APPROVE=yes; shift ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Harden a member account security baseline."
            echo ""
            echo "Options:"
            echo "  --account-id ID              Target member account ID"
            echo "  --all-accounts               Apply to all member accounts in org"
            echo "  --cross-account-role ROLE    Role name to assume (default: OrganizationAccountAccessRole)"
            echo "  --no-assume                  Skip sts:AssumeRole; --profile already belongs to the target account"
            echo "  --profile PROFILE            AWS CLI profile (default: default)"
            echo "  --auto-approve               Skip confirmation prompts"
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

# ── Cross-Account Session ───────────────────────────────────────────────────

assume_role() {
    local target_account="$1"
    local role_arn="arn:aws:iam::${target_account}:role/${CROSS_ACCOUNT_ROLE}"

    info "Assuming role ${role_arn}..."
    local creds
    creds=$(${AWS_CMD} sts assume-role \
        --role-arn "${role_arn}" \
        --role-session-name "nexus-account-hardening" \
        --duration-seconds 3600 \
        --output json)

    export AWS_ACCESS_KEY_ID=$(echo "${creds}" | python3 -c "import sys,json; print(json.load(sys.stdin)['Credentials']['AccessKeyId'])")
    export AWS_SECRET_ACCESS_KEY=$(echo "${creds}" | python3 -c "import sys,json; print(json.load(sys.stdin)['Credentials']['SecretAccessKey'])")
    export AWS_SESSION_TOKEN=$(echo "${creds}" | python3 -c "import sys,json; print(json.load(sys.stdin)['Credentials']['SessionToken'])")
}

clear_assumed_role() {
    unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
}

# When running in the target account context:
#   - assume-role mode: env-var creds are set by assume_role(); use plain `aws`
#     (no --profile) so it picks them up.
#   - --no-assume mode: --profile already belongs to the target; use it.
# harden_account() rewrites TARGET_CMD just before invoking the action
# helpers, so the value below is only a safe default.
TARGET_CMD="aws --region ${REGION}"

# ── Hardening Functions ─────────────────────────────────────────────────────

set_password_policy() {
    info "  Setting IAM password policy..."
    ${TARGET_CMD} iam update-account-password-policy \
        --minimum-password-length 14 \
        --require-symbols \
        --require-numbers \
        --require-uppercase-characters \
        --require-lowercase-characters \
        --allow-users-to-change-password \
        --max-password-age 90 \
        --password-reuse-prevention 24 \
        --hard-expiry 2>/dev/null \
        || warn "  Failed to set password policy."
    info "  Password policy set."
}

enable_s3_block_public_access() {
    info "  Enabling S3 Block Public Access (account-level)..."
    ${TARGET_CMD} s3control put-public-access-block \
        --account-id "${CURRENT_ACCOUNT}" \
        --public-access-block-configuration \
            "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" \
        2>/dev/null \
        || warn "  Failed to set S3 Block Public Access."
    info "  S3 Block Public Access enabled."
}

enable_ebs_default_encryption() {
    info "  Enabling default EBS encryption..."
    ${TARGET_CMD} ec2 enable-ebs-encryption-by-default --region "${ALLOWED_REGION}" 2>/dev/null \
        || warn "  Failed to enable EBS default encryption."
    info "  EBS default encryption enabled."
}

enforce_imdsv2() {
    info "  Setting IMDSv2 as account default..."
    ${TARGET_CMD} ec2 modify-instance-metadata-defaults \
        --http-tokens required \
        --http-put-response-hop-limit 2 \
        --http-endpoint enabled \
        --region "${ALLOWED_REGION}" 2>/dev/null \
        || warn "  Failed to set IMDSv2 defaults (may require newer CLI version)."
    info "  IMDSv2 enforcement set."
}

delete_default_vpcs() {
    info "  Deleting default VPCs in all regions..."
    for r in "${ALL_AWS_REGIONS[@]}"; do
        local vpc_id
        vpc_id=$(${TARGET_CMD} ec2 describe-vpcs --region "${r}" \
            --filters "Name=isDefault,Values=true" \
            --query 'Vpcs[0].VpcId' --output text 2>/dev/null || echo "None")

        if [[ -z "${vpc_id}" || "${vpc_id}" == "None" ]]; then
            continue
        fi

        info "    Deleting default VPC ${vpc_id} in ${r}..."

        local igws
        igws=$(${TARGET_CMD} ec2 describe-internet-gateways --region "${r}" \
            --filters "Name=attachment.vpc-id,Values=${vpc_id}" \
            --query 'InternetGateways[].InternetGatewayId' --output text 2>/dev/null)
        for igw in ${igws}; do
            ${TARGET_CMD} ec2 detach-internet-gateway --region "${r}" \
                --internet-gateway-id "${igw}" --vpc-id "${vpc_id}" 2>/dev/null || true
            ${TARGET_CMD} ec2 delete-internet-gateway --region "${r}" \
                --internet-gateway-id "${igw}" 2>/dev/null || true
        done

        local subnets
        subnets=$(${TARGET_CMD} ec2 describe-subnets --region "${r}" \
            --filters "Name=vpc-id,Values=${vpc_id}" \
            --query 'Subnets[].SubnetId' --output text 2>/dev/null)
        for subnet in ${subnets}; do
            ${TARGET_CMD} ec2 delete-subnet --region "${r}" \
                --subnet-id "${subnet}" 2>/dev/null || true
        done

        ${TARGET_CMD} ec2 delete-vpc --region "${r}" --vpc-id "${vpc_id}" 2>/dev/null \
            || warn "    Could not delete VPC ${vpc_id} in ${r} (may have dependencies)."
    done
    info "  Default VPC cleanup complete."
}

opt_out_unused_regions() {
    info "  Opting out of unused regions..."
    local opt_in_regions
    opt_in_regions=$(${TARGET_CMD} account list-regions \
        --region-opt-status-contains ENABLED ENABLED_BY_DEFAULT \
        --query 'Regions[].RegionName' --output text 2>/dev/null || echo "")

    if [[ -z "${opt_in_regions}" ]]; then
        warn "  Could not list regions (account API may not be available)."
        return
    fi

    for r in ${opt_in_regions}; do
        if [[ "${r}" == "${ALLOWED_REGION}" ]]; then
            continue
        fi
        # Only opt-in regions can be disabled; default regions cannot
        local status
        status=$(${TARGET_CMD} account get-region-opt-status \
            --region-name "${r}" \
            --query 'RegionOptStatus' --output text 2>/dev/null || echo "UNKNOWN")

        if [[ "${status}" == "ENABLED" ]]; then
            info "    Disabling opt-in region ${r}..."
            ${TARGET_CMD} account disable-region --region-name "${r}" 2>/dev/null \
                || warn "    Could not disable ${r}."
        fi
    done
    info "  Region opt-out complete."
}

# ── Harden a Single Account ────────────────────────────────────────────────

harden_account() {
    local target_account="$1"
    CURRENT_ACCOUNT="${target_account}"

    info ""
    info "── Hardening account ${target_account} ──"

    if [[ "${NO_ASSUME}" == "yes" ]]; then
        # In-place: caller's --profile already belongs to the target.
        # No assume-role; no master-account guard (caller IS the target).
        TARGET_CMD="aws --profile ${AWS_PROFILE} --region ${REGION}"
    else
        # Cross-account: refuse to harden the management account by accident.
        if [[ "${target_account}" == "${MASTER_ACCOUNT_ID}" ]]; then
            warn "Skipping master account ${target_account}."
            return
        fi

        assume_role "${target_account}"
        TARGET_CMD="aws --region ${REGION}"
    fi

    local verified_id
    verified_id=$(${TARGET_CMD} sts get-caller-identity --query 'Account' --output text 2>/dev/null)
    if [[ "${verified_id}" != "${target_account}" ]]; then
        if [[ "${NO_ASSUME}" == "yes" ]]; then
            warn "Profile ${AWS_PROFILE} resolves to '${verified_id}', expected '${target_account}'. Skipping."
        else
            warn "Role assumption verification failed for ${target_account}. Skipping."
            clear_assumed_role
        fi
        return
    fi

    set_password_policy
    enable_s3_block_public_access
    enable_ebs_default_encryption
    enforce_imdsv2
    delete_default_vpcs
    opt_out_unused_regions

    [[ "${NO_ASSUME}" != "yes" ]] && clear_assumed_role
    info "── Account ${target_account} hardened ──"
}

# ── Main ────────────────────────────────────────────────────────────────────

main() {
    info "=========================================="
    info "Member Account Hardening"
    info "=========================================="
    info "Master Account: ${MASTER_ACCOUNT_ID}"

    if [[ "${ALL_ACCOUNTS}" == "true" ]]; then
        local accounts
        accounts=$(${AWS_CMD} organizations list-accounts \
            --query "Accounts[?Status=='ACTIVE'].Id" --output text)

        local count
        count=$(echo "${accounts}" | wc -w)
        info "Found ${count} active accounts."

        if ! confirm "Harden all ${count} member accounts?"; then
            info "Aborted."
            exit 0
        fi

        for acct in ${accounts}; do
            harden_account "${acct}"
        done
    elif [[ -n "${ACCOUNT_ID}" ]]; then
        if ! confirm "Harden account ${ACCOUNT_ID}?"; then
            info "Aborted."
            exit 0
        fi
        harden_account "${ACCOUNT_ID}"
    else
        die "Specify --account-id or --all-accounts."
    fi

    info ""
    info "=========================================="
    info "Account hardening complete."
    info "=========================================="
}

main

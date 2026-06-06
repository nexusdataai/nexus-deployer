#!/bin/bash
#
# AWS Organization Bootstrap Script
# Creates and configures AWS Organization with OUs, service access principals,
# and delegated admin for security services.
#
# Prerequisites:
#   - AWS CLI v2 configured with master account credentials
#   - Master account must not already belong to another organization
#
# Usage:
#   ./setup-organization.sh
#   ./setup-organization.sh --profile master-admin
#   ./setup-organization.sh --member-accounts 111111111111,222222222222
#

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Defaults
AWS_PROFILE="${AWS_PROFILE:-default}"
REGION="${REGION:-us-east-1}"
MEMBER_ACCOUNTS="${MEMBER_ACCOUNTS:-}"
MEMBER_EMAILS="${MEMBER_EMAILS:-}"
AUTO_APPROVE="${AUTO_APPROVE:-no}"
SINGLE_INVITE=no
TARGET_ACCOUNT_ID=""
TARGET_EMAIL=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --profile)            AWS_PROFILE="$2"; shift 2 ;;
        --region)             REGION="$2"; shift 2 ;;
        --member-accounts)    MEMBER_ACCOUNTS="$2"; shift 2 ;;
        --member-emails)      MEMBER_EMAILS="$2"; shift 2 ;;
        --auto-approve)       AUTO_APPROVE=yes; shift ;;
        --single-invite)      SINGLE_INVITE=yes; shift ;;
        --target-account-id)  TARGET_ACCOUNT_ID="$2"; shift 2 ;;
        --target-email)       TARGET_EMAIL="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Bootstrap AWS Organization for nexus-ai deployments."
            echo ""
            echo "Options:"
            echo "  --profile PROFILE              AWS CLI profile (default: default)"
            echo "  --region REGION                AWS region (default: us-east-1)"
            echo "  --member-accounts IDs          Comma-separated existing account IDs to invite"
            echo "  --member-emails EMAILS         Comma-separated emails to create new accounts"
            echo "  --auto-approve                 Skip confirmation prompts"
            echo ""
            echo "Single-invite mode (skips org/OU/service-access setup):"
            echo "  --single-invite                Only send one invite, emit HandshakeId on stdout"
            echo "  --target-account-id ID         (single-invite) Account ID to invite"
            echo "  --target-email EMAIL           (single-invite) Root email of the target account"
            echo ""
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

MASTER_ACCOUNT_ID=$(${AWS_CMD} sts get-caller-identity --query 'Account' --output text 2>/dev/null) \
    || die "Failed to get caller identity. Check AWS credentials."
info "Master account: ${MASTER_ACCOUNT_ID}"

# ── 1. Create Organization ──────────────────────────────────────────────────

create_organization() {
    info "Checking for existing organization..."
    local org_id
    org_id=$(${AWS_CMD} organizations describe-organization --query 'Organization.Id' --output text 2>/dev/null || echo "NONE")

    if [[ "${org_id}" != "NONE" ]]; then
        info "Organization already exists: ${org_id}"
        local features
        features=$(${AWS_CMD} organizations describe-organization --query 'Organization.FeatureSet' --output text)
        if [[ "${features}" != "ALL" ]]; then
            warn "Organization feature set is '${features}', not 'ALL'. Enable all features manually."
        fi
    else
        info "Creating AWS Organization with ALL features..."
        ${AWS_CMD} organizations create-organization --feature-set ALL
        info "Organization created."
    fi
}

# ── 2. Create Organizational Units ──────────────────────────────────────────

get_root_id() {
    ${AWS_CMD} organizations list-roots --query 'Roots[0].Id' --output text
}

create_ou() {
    local parent_id="$1"
    local ou_name="$2"

    local existing
    existing=$(${AWS_CMD} organizations list-organizational-units-for-parent \
        --parent-id "${parent_id}" \
        --query "OrganizationalUnits[?Name=='${ou_name}'].Id" \
        --output text 2>/dev/null)

    if [[ -n "${existing}" && "${existing}" != "None" ]]; then
        info "OU '${ou_name}' already exists: ${existing}"
        echo "${existing}"
    else
        info "Creating OU '${ou_name}'..."
        local ou_id
        ou_id=$(${AWS_CMD} organizations create-organizational-unit \
            --parent-id "${parent_id}" \
            --name "${ou_name}" \
            --query 'OrganizationalUnit.Id' \
            --output text)
        info "Created OU '${ou_name}': ${ou_id}"
        echo "${ou_id}"
    fi
}

create_organizational_units() {
    local root_id
    root_id=$(get_root_id)
    info "Org root: ${root_id}"

    OU_NEXUS_PROD=$(create_ou "${root_id}" "NexusProduction")
    OU_NEXUS_DEV=$(create_ou "${root_id}" "NexusDev")
    OU_SECURITY=$(create_ou "${root_id}" "Security")
    OU_SUSPENDED=$(create_ou "${root_id}" "Suspended")
}

# ── 3. Enable AWS Service Access Principals ─────────────────────────────────

enable_service_access() {
    local principals=(
        "cloudtrail.amazonaws.com"
        "guardduty.amazonaws.com"
        "config.amazonaws.com"
        "config-multiaccountsetup.amazonaws.com"
        "securityhub.amazonaws.com"
        "access-analyzer.amazonaws.com"
        "member.org.stacksets.cloudformation.amazonaws.com"
        "sso.amazonaws.com"
    )

    for principal in "${principals[@]}"; do
        info "Enabling service access for ${principal}..."
        ${AWS_CMD} organizations enable-aws-service-access \
            --service-principal "${principal}" 2>/dev/null || true
    done
    info "All service access principals enabled."
}

# ── 4. Invite Existing Accounts / Create New Accounts ───────────────────────

move_account_to_ou() {
    local account_id="$1"
    local target_ou="$2"
    local root_id
    root_id=$(get_root_id)

    local current_parent
    current_parent=$(${AWS_CMD} organizations list-parents \
        --child-id "${account_id}" \
        --query 'Parents[0].Id' \
        --output text 2>/dev/null)

    if [[ "${current_parent}" == "${target_ou}" ]]; then
        info "Account ${account_id} already in target OU."
        return
    fi

    info "Moving account ${account_id} from ${current_parent} to ${target_ou}..."
    ${AWS_CMD} organizations move-account \
        --account-id "${account_id}" \
        --source-parent-id "${current_parent}" \
        --destination-parent-id "${target_ou}"
}

invite_member_accounts() {
    if [[ -z "${MEMBER_ACCOUNTS}" ]]; then return; fi

    IFS=',' read -ra ACCOUNTS <<< "${MEMBER_ACCOUNTS}"
    for account_id in "${ACCOUNTS[@]}"; do
        account_id=$(echo "${account_id}" | tr -d ' ')
        info "Inviting account ${account_id} to organization..."
        local status
        status=$(${AWS_CMD} organizations describe-account \
            --account-id "${account_id}" \
            --query 'Account.Status' \
            --output text 2>/dev/null || echo "NOT_MEMBER")

        if [[ "${status}" == "ACTIVE" ]]; then
            info "Account ${account_id} is already an active member."
        else
            ${AWS_CMD} organizations invite-account-to-organization \
                --target "{\"Id\":\"${account_id}\",\"Type\":\"ACCOUNT\"}" \
                --notes "Nexus AI organization consolidation" 2>/dev/null \
                || warn "Could not invite ${account_id} (may already have a pending invite)."
        fi
    done
}

invite_single_account() {
    # Used by onboard-account.sh in --single-invite mode.
    # Emits a final stdout line "HANDSHAKE_ID=<id>" that the orchestrator parses.
    [[ -n "${TARGET_ACCOUNT_ID}" ]] || die "--target-account-id is required with --single-invite"
    [[ -n "${TARGET_EMAIL}" ]]      || die "--target-email is required with --single-invite"

    info "Single-invite: account ${TARGET_ACCOUNT_ID} (${TARGET_EMAIL})..."

    local status
    status=$(${AWS_CMD} organizations describe-account \
        --account-id "${TARGET_ACCOUNT_ID}" \
        --query 'Account.Status' \
        --output text 2>/dev/null || echo "NOT_MEMBER")

    if [[ "${status}" == "ACTIVE" ]]; then
        info "Account ${TARGET_ACCOUNT_ID} is already an active member; no invite needed."
        echo "HANDSHAKE_ID=ALREADY_MEMBER"
        return
    fi

    # Reuse an existing OPEN handshake for this account if one already exists,
    # to keep the operation idempotent across re-runs.
    local existing_hid
    existing_hid=$(${AWS_CMD} organizations list-handshakes-for-organization \
        --filter "ActionType=INVITE" \
        --query "Handshakes[?contains(Parties[].Id, \`${TARGET_ACCOUNT_ID}\`) && State=='OPEN'].Id | [0]" \
        --output text 2>/dev/null || echo "None")

    if [[ -n "${existing_hid}" && "${existing_hid}" != "None" ]]; then
        info "Re-using existing OPEN invite handshake: ${existing_hid}"
        echo "HANDSHAKE_ID=${existing_hid}"
        return
    fi

    # AWS Organizations HandshakeParty accepts only {Id, Type}.
    # With Type=ACCOUNT, Id is the 12-digit account ID; email is NOT part
    # of the target object. We keep TARGET_EMAIL for logging/manifest only.
    local hid
    hid=$(${AWS_CMD} organizations invite-account-to-organization \
        --target "{\"Id\":\"${TARGET_ACCOUNT_ID}\",\"Type\":\"ACCOUNT\"}" \
        --notes "Nexus AI onboarding via onboard-account.sh (email=${TARGET_EMAIL})" \
        --query 'Handshake.Id' --output text) \
        || die "invite-account-to-organization failed for ${TARGET_ACCOUNT_ID}."

    info "Invite sent. HandshakeId=${hid}"
    echo "HANDSHAKE_ID=${hid}"
}

create_new_accounts() {
    if [[ -z "${MEMBER_EMAILS}" ]]; then return; fi

    IFS=',' read -ra EMAILS <<< "${MEMBER_EMAILS}"
    for email in "${EMAILS[@]}"; do
        email=$(echo "${email}" | tr -d ' ')
        local account_name
        account_name="nexus-$(echo "${email}" | cut -d@ -f1)"

        info "Creating account for ${email} (name: ${account_name})..."
        local request_id
        request_id=$(${AWS_CMD} organizations create-account \
            --email "${email}" \
            --account-name "${account_name}" \
            --iam-user-access-to-billing DENY \
            --query 'CreateAccountStatus.Id' \
            --output text 2>/dev/null) || { warn "Failed to create account for ${email}"; continue; }

        info "Account creation initiated (request: ${request_id}). Waiting..."
        local state="IN_PROGRESS"
        while [[ "${state}" == "IN_PROGRESS" ]]; do
            sleep 5
            state=$(${AWS_CMD} organizations describe-create-account-status \
                --create-account-request-id "${request_id}" \
                --query 'CreateAccountStatus.State' \
                --output text)
        done

        if [[ "${state}" == "SUCCEEDED" ]]; then
            local new_id
            new_id=$(${AWS_CMD} organizations describe-create-account-status \
                --create-account-request-id "${request_id}" \
                --query 'CreateAccountStatus.AccountId' \
                --output text)
            info "Account created: ${new_id} (${email})"
        else
            local reason
            reason=$(${AWS_CMD} organizations describe-create-account-status \
                --create-account-request-id "${request_id}" \
                --query 'CreateAccountStatus.FailureReason' \
                --output text)
            warn "Account creation failed for ${email}: ${reason}"
        fi
    done
}

# ── 5. Enable Delegated Admin ───────────────────────────────────────────────

enable_delegated_admin() {
    info "Delegated admin setup is handled per-service during security service enablement."
    info "See enable-security-services.sh for GuardDuty, Security Hub, and Config delegation."
}

# ── Main ────────────────────────────────────────────────────────────────────

main() {
    info "=========================================="
    info "AWS Organization Bootstrap"
    info "=========================================="
    info "Master Account: ${MASTER_ACCOUNT_ID}"
    info "Region:         ${REGION}"
    info ""

    if [[ "${SINGLE_INVITE}" == "yes" ]]; then
        # Fast path used by onboard-account.sh: only send one invite, skip
        # all org/OU/service-access setup (those must already be in place).
        invite_single_account
        return
    fi

    if ! confirm "Proceed with organization setup?"; then
        info "Aborted."
        exit 0
    fi

    create_organization
    create_organizational_units
    enable_service_access
    invite_member_accounts
    create_new_accounts
    enable_delegated_admin

    info ""
    info "=========================================="
    info "Organization setup complete."
    info "=========================================="
    info ""
    info "OUs created:"
    info "  NexusProduction: ${OU_NEXUS_PROD}"
    info "  NexusDev:        ${OU_NEXUS_DEV}"
    info "  Security:        ${OU_SECURITY}"
    info "  Suspended:       ${OU_SUSPENDED}"
    info ""
    info "Next steps:"
    info "  1. Move member accounts to appropriate OUs"
    info "  2. Run apply-service-control-policies.sh to attach SCPs"
    info "  3. Run secure-member-account.sh for each member account"
    info "  4. Run setup-cross-account-roles.sh for provisioning roles"
    info "  5. Run enable-security-services.sh for monitoring"
}

main

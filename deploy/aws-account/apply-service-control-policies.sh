#!/bin/bash
#
# Apply Service Control Policies to AWS Organization
# Attaches all nexus-ai SCPs to the appropriate OUs with idempotent logic.
#
# Prerequisites:
#   - Organization and OUs created via setup-organization.sh
#   - SCP JSON files present in policies/ directory
#
# Usage:
#   ./apply-service-control-policies.sh
#   ./apply-service-control-policies.sh --profile master-admin --detach
#

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
POLICIES_DIR="${SCRIPT_DIR}/policies"

# Defaults
AWS_PROFILE="${AWS_PROFILE:-default}"
REGION="${REGION:-us-east-1}"
AUTO_APPROVE="${AUTO_APPROVE:-no}"
ACTION="attach"

while [[ $# -gt 0 ]]; do
    case $1 in
        --profile)       AWS_PROFILE="$2"; shift 2 ;;
        --region)        REGION="$2"; shift 2 ;;
        --detach)        ACTION="detach"; shift ;;
        --auto-approve)  AUTO_APPROVE=yes; shift ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Attach or detach SCPs to Organization OUs."
            echo ""
            echo "Options:"
            echo "  --profile PROFILE     AWS CLI profile (default: default)"
            echo "  --region REGION       AWS region (default: us-east-1)"
            echo "  --detach              Detach all SCPs instead of attaching"
            echo "  --auto-approve        Skip confirmation prompts"
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

get_root_id() {
    ${AWS_CMD} organizations list-roots --query 'Roots[0].Id' --output text
}

get_ou_id() {
    local parent_id="$1"
    local ou_name="$2"
    ${AWS_CMD} organizations list-organizational-units-for-parent \
        --parent-id "${parent_id}" \
        --query "OrganizationalUnits[?Name=='${ou_name}'].Id | [0]" \
        --output text 2>/dev/null
}

# ── SCP Management ──────────────────────────────────────────────────────────

create_or_update_scp() {
    local scp_name="$1"
    local scp_file="$2"
    local description="$3"

    if [[ ! -f "${scp_file}" ]]; then
        die "SCP file not found: ${scp_file}"
    fi

    local scp_content
    scp_content=$(cat "${scp_file}")

    local existing_id
    existing_id=$(${AWS_CMD} organizations list-policies --filter SERVICE_CONTROL_POLICY \
        --query "Policies[?Name=='${scp_name}'].Id | [0]" \
        --output text 2>/dev/null)

    if [[ -n "${existing_id}" && "${existing_id}" != "None" ]]; then
        info "Updating existing SCP '${scp_name}' (${existing_id})..."
        ${AWS_CMD} organizations update-policy \
            --policy-id "${existing_id}" \
            --content "${scp_content}" \
            --description "${description}" >/dev/null
        echo "${existing_id}"
    else
        info "Creating SCP '${scp_name}'..."
        local policy_id
        policy_id=$(${AWS_CMD} organizations create-policy \
            --name "${scp_name}" \
            --description "${description}" \
            --type SERVICE_CONTROL_POLICY \
            --content "${scp_content}" \
            --query 'Policy.PolicySummary.Id' \
            --output text)
        info "Created SCP '${scp_name}': ${policy_id}"
        echo "${policy_id}"
    fi
}

attach_scp() {
    local policy_id="$1"
    local target_id="$2"
    local target_name="$3"

    local already_attached
    already_attached=$(${AWS_CMD} organizations list-policies-for-target \
        --target-id "${target_id}" \
        --filter SERVICE_CONTROL_POLICY \
        --query "Policies[?Id=='${policy_id}'].Id | [0]" \
        --output text 2>/dev/null)

    if [[ -n "${already_attached}" && "${already_attached}" != "None" ]]; then
        info "SCP ${policy_id} already attached to ${target_name}."
    else
        info "Attaching SCP ${policy_id} to ${target_name} (${target_id})..."
        ${AWS_CMD} organizations attach-policy \
            --policy-id "${policy_id}" \
            --target-id "${target_id}"
    fi
}

detach_scp() {
    local policy_id="$1"
    local target_id="$2"
    local target_name="$3"

    local is_attached
    is_attached=$(${AWS_CMD} organizations list-policies-for-target \
        --target-id "${target_id}" \
        --filter SERVICE_CONTROL_POLICY \
        --query "Policies[?Id=='${policy_id}'].Id | [0]" \
        --output text 2>/dev/null)

    if [[ -n "${is_attached}" && "${is_attached}" != "None" ]]; then
        info "Detaching SCP ${policy_id} from ${target_name} (${target_id})..."
        ${AWS_CMD} organizations detach-policy \
            --policy-id "${policy_id}" \
            --target-id "${target_id}"
    else
        info "SCP ${policy_id} not attached to ${target_name}. Nothing to detach."
    fi
}

# ── Main ────────────────────────────────────────────────────────────────────

main() {
    info "=========================================="
    info "Service Control Policy Management"
    info "=========================================="
    info "Action: ${ACTION}"

    local root_id
    root_id=$(get_root_id)
    info "Org root: ${root_id}"

    local ou_prod ou_dev
    ou_prod=$(get_ou_id "${root_id}" "NexusProduction")
    ou_dev=$(get_ou_id "${root_id}" "NexusDev")

    if [[ -z "${ou_prod}" || "${ou_prod}" == "None" ]]; then
        die "OU 'NexusProduction' not found. Run setup-organization.sh first."
    fi
    if [[ -z "${ou_dev}" || "${ou_dev}" == "None" ]]; then
        die "OU 'NexusDev' not found. Run setup-organization.sh first."
    fi

    info "NexusProduction OU: ${ou_prod}"
    info "NexusDev OU:        ${ou_dev}"

    if ! confirm "Proceed to ${ACTION} SCPs?"; then
        info "Aborted."
        exit 0
    fi

    info ""
    info "── Creating/Updating SCP Policies ──"

    SCP_REGION=$(create_or_update_scp \
        "NexusRegionRestriction" \
        "${POLICIES_DIR}/scp-region-restriction.json" \
        "Restrict AWS API calls to us-east-1 by default")

    SCP_SERVICE=$(create_or_update_scp \
        "NexusServiceWhitelist" \
        "${POLICIES_DIR}/scp-service-whitelist.json" \
        "Allow only nexus-ai required AWS services")

    SCP_ROOT=$(create_or_update_scp \
        "NexusRootProtection" \
        "${POLICIES_DIR}/scp-root-account-protection.json" \
        "Restrict root user actions in member accounts")

    SCP_IAM=$(create_or_update_scp \
        "NexusIAMGuardrails" \
        "${POLICIES_DIR}/scp-iam-guardrails.json" \
        "Prevent IAM user creation and protect provisioner role")

    SCP_SECURITY=$(create_or_update_scp \
        "NexusSecurityBaseline" \
        "${POLICIES_DIR}/scp-security-baseline.json" \
        "Prevent disabling security services")

    info ""
    info "── ${ACTION^}ing SCPs to OUs ──"

    # Region restriction, service whitelist, root protection, and security baseline
    # apply to org root (all accounts except master which is exempt from SCPs by default
    # when the SCP is attached to the root -- master is only governed by SCPs attached
    # directly or via its OU)
    local scp_action_fn="${ACTION}_scp"

    ${scp_action_fn} "${SCP_REGION}" "${root_id}" "OrgRoot"
    ${scp_action_fn} "${SCP_SERVICE}" "${root_id}" "OrgRoot"
    ${scp_action_fn} "${SCP_ROOT}" "${root_id}" "OrgRoot"
    ${scp_action_fn} "${SCP_SECURITY}" "${root_id}" "OrgRoot"

    # IAM guardrails only on member account OUs (not master)
    ${scp_action_fn} "${SCP_IAM}" "${ou_prod}" "NexusProduction"
    ${scp_action_fn} "${SCP_IAM}" "${ou_dev}" "NexusDev"

    info ""
    info "=========================================="
    info "SCP ${ACTION} complete."
    info "=========================================="
    info ""
    info "Policies:"
    info "  Region Restriction: ${SCP_REGION}"
    info "  Service Whitelist:  ${SCP_SERVICE}"
    info "  Root Protection:    ${SCP_ROOT}"
    info "  IAM Guardrails:     ${SCP_IAM}"
    info "  Security Baseline:  ${SCP_SECURITY}"
}

main

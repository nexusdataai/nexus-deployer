#!/bin/bash
#
# Per-Account Region Management
# Enable or disable additional AWS regions for specific member accounts.
# Creates per-account region SCPs and extends security services to new regions.
#
# Prerequisites:
#   - Organization with SCPs applied via apply-service-control-policies.sh
#   - Security services enabled via enable-security-services.sh
#
# Usage:
#   ./manage-account-regions.sh --account-id 123456789012 --enable-region eu-west-1
#   ./manage-account-regions.sh --account-id 123456789012 --disable-region eu-west-1
#   ./manage-account-regions.sh --account-id 123456789012 --list
#

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
POLICIES_DIR="${SCRIPT_DIR}/policies"

# Defaults
AWS_PROFILE="${AWS_PROFILE:-default}"
REGION="${REGION:-us-east-1}"
ACCOUNT_ID=""
ENABLE_REGION=""
DISABLE_REGION=""
LIST_REGIONS=false
AUTO_APPROVE="${AUTO_APPROVE:-no}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --profile)         AWS_PROFILE="$2"; shift 2 ;;
        --region)          REGION="$2"; shift 2 ;;
        --account-id)      ACCOUNT_ID="$2"; shift 2 ;;
        --enable-region)   ENABLE_REGION="$2"; shift 2 ;;
        --disable-region)  DISABLE_REGION="$2"; shift 2 ;;
        --list)            LIST_REGIONS=true; shift ;;
        --auto-approve)    AUTO_APPROVE=yes; shift ;;
        --help|-h)
            echo "Usage: $0 --account-id ACCOUNT_ID [OPTIONS]"
            echo ""
            echo "Manage allowed AWS regions per member account."
            echo ""
            echo "Actions (choose one):"
            echo "  --enable-region REGION    Enable an additional region"
            echo "  --disable-region REGION   Disable a previously enabled region"
            echo "  --list                    List currently allowed regions"
            echo ""
            echo "Options:"
            echo "  --account-id ID           Target member account ID (required)"
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

[[ -n "${ACCOUNT_ID}" ]] || die "--account-id is required."

MASTER_ACCOUNT_ID=$(${AWS_CMD} sts get-caller-identity --query 'Account' --output text)
[[ "${ACCOUNT_ID}" != "${MASTER_ACCOUNT_ID}" ]] || die "Cannot modify region restrictions for the master account."

GLOBAL_SERVICES_NOTACTION=(
    "a4b:*" "acm:*" "aws-marketplace-management:*" "aws-marketplace:*"
    "aws-portal:*" "budgets:*" "ce:*" "chime:*" "cloudfront:*" "cur:*"
    "globalaccelerator:*" "health:*" "iam:*" "importexport:*" "organizations:*"
    "route53:*" "route53domains:*" "shield:*" "sts:*" "support:*"
    "trustedadvisor:*" "waf:*" "wafv2:*" "wellarchitected:*"
)

SCP_NAME_PREFIX="NexusRegion"

# ── Helpers ─────────────────────────────────────────────────────────────────

get_account_region_scp_name() {
    echo "${SCP_NAME_PREFIX}-${ACCOUNT_ID}"
}

get_account_region_scp_id() {
    local scp_name
    scp_name=$(get_account_region_scp_name)
    ${AWS_CMD} organizations list-policies --filter SERVICE_CONTROL_POLICY \
        --query "Policies[?Name=='${scp_name}'].Id | [0]" \
        --output text 2>/dev/null
}

get_default_region_scp_id() {
    ${AWS_CMD} organizations list-policies --filter SERVICE_CONTROL_POLICY \
        --query "Policies[?Name=='NexusRegionRestriction'].Id | [0]" \
        --output text 2>/dev/null
}

get_current_allowed_regions() {
    local scp_id
    scp_id=$(get_account_region_scp_id)

    if [[ -z "${scp_id}" || "${scp_id}" == "None" ]]; then
        echo "us-east-1"
        return
    fi

    ${AWS_CMD} organizations describe-policy --policy-id "${scp_id}" \
        --query 'Policy.Content' --output text \
        | python3 -c "
import sys, json
policy = json.load(sys.stdin)
for stmt in policy.get('Statement', []):
    regions = stmt.get('Condition', {}).get('StringNotEquals', {}).get('aws:RequestedRegion', [])
    if regions:
        for r in regions:
            print(r)
" 2>/dev/null || echo "us-east-1"
}

generate_region_scp() {
    local regions_json="$1"
    local not_actions
    not_actions=$(printf '        "%s",\n' "${GLOBAL_SERVICES_NOTACTION[@]}" | sed '$ s/,$//')

    cat <<EOFPOLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyNonAllowedRegions",
      "Effect": "Deny",
      "NotAction": [
${not_actions}
      ],
      "Resource": "*",
      "Condition": {
        "StringNotEquals": {
          "aws:RequestedRegion": ${regions_json}
        }
      }
    }
  ]
}
EOFPOLICY
}

get_account_parent_ou() {
    ${AWS_CMD} organizations list-parents \
        --child-id "${ACCOUNT_ID}" \
        --query 'Parents[0].Id' --output text
}

# ── List ────────────────────────────────────────────────────────────────────

list_account_regions() {
    info "Allowed regions for account ${ACCOUNT_ID}:"
    local scp_id
    scp_id=$(get_account_region_scp_id)

    if [[ -z "${scp_id}" || "${scp_id}" == "None" ]]; then
        info "  Using org default: us-east-1"
        info "  (No per-account region SCP found)"
    else
        info "  Per-account SCP: ${scp_id}"
        local regions
        regions=$(get_current_allowed_regions)
        echo "${regions}" | while read -r r; do
            info "  - ${r}"
        done
    fi
}

# ── Enable Region ───────────────────────────────────────────────────────────

enable_region_for_account() {
    local new_region="$1"
    info "Enabling region '${new_region}' for account ${ACCOUNT_ID}..."

    local current_regions
    current_regions=$(get_current_allowed_regions)

    if echo "${current_regions}" | grep -q "^${new_region}$"; then
        info "Region '${new_region}' is already allowed for account ${ACCOUNT_ID}."
        return
    fi

    local all_regions
    all_regions=$(echo -e "${current_regions}\n${new_region}" | sort -u)
    local regions_json
    regions_json=$(echo "${all_regions}" | python3 -c "import sys, json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))")

    if ! confirm "Allow regions ${regions_json} for account ${ACCOUNT_ID}?"; then
        info "Aborted."
        return
    fi

    local scp_content
    scp_content=$(generate_region_scp "${regions_json}")

    local scp_name
    scp_name=$(get_account_region_scp_name)
    local scp_id
    scp_id=$(get_account_region_scp_id)

    if [[ -n "${scp_id}" && "${scp_id}" != "None" ]]; then
        info "Updating per-account region SCP (${scp_id})..."
        ${AWS_CMD} organizations update-policy \
            --policy-id "${scp_id}" \
            --content "${scp_content}" \
            --description "Region restriction for account ${ACCOUNT_ID}: ${regions_json}" >/dev/null
    else
        info "Creating per-account region SCP..."
        scp_id=$(${AWS_CMD} organizations create-policy \
            --name "${scp_name}" \
            --description "Region restriction for account ${ACCOUNT_ID}: ${regions_json}" \
            --type SERVICE_CONTROL_POLICY \
            --content "${scp_content}" \
            --query 'Policy.PolicySummary.Id' \
            --output text)
        info "Created SCP: ${scp_id}"

        info "Attaching per-account SCP to account ${ACCOUNT_ID}..."
        ${AWS_CMD} organizations attach-policy \
            --policy-id "${scp_id}" \
            --target-id "${ACCOUNT_ID}"
    fi

    local default_scp_id
    default_scp_id=$(get_default_region_scp_id)
    if [[ -n "${default_scp_id}" && "${default_scp_id}" != "None" ]]; then
        info "Detaching default region SCP from account ${ACCOUNT_ID}..."
        ${AWS_CMD} organizations detach-policy \
            --policy-id "${default_scp_id}" \
            --target-id "${ACCOUNT_ID}" 2>/dev/null || true
    fi

    info "Opting in region '${new_region}' for account ${ACCOUNT_ID}..."
    ${AWS_CMD} account enable-region --region-name "${new_region}" \
        --account-id "${ACCOUNT_ID}" 2>/dev/null \
        || warn "Could not opt-in region (may already be enabled or is an opt-in region)."

    extend_security_services "${new_region}"

    local scp_file="${POLICIES_DIR}/scp-region-${ACCOUNT_ID}.json"
    echo "${scp_content}" > "${scp_file}"
    info "Saved per-account SCP to ${scp_file}"

    info "Region '${new_region}' enabled for account ${ACCOUNT_ID}."
}

# ── Disable Region ──────────────────────────────────────────────────────────

disable_region_for_account() {
    local target_region="$1"
    info "Disabling region '${target_region}' for account ${ACCOUNT_ID}..."

    if [[ "${target_region}" == "us-east-1" ]]; then
        die "Cannot disable us-east-1 (default region)."
    fi

    local current_regions
    current_regions=$(get_current_allowed_regions)

    if ! echo "${current_regions}" | grep -q "^${target_region}$"; then
        info "Region '${target_region}' is not currently allowed for account ${ACCOUNT_ID}."
        return
    fi

    local remaining_regions
    remaining_regions=$(echo "${current_regions}" | grep -v "^${target_region}$")
    local remaining_count
    remaining_count=$(echo "${remaining_regions}" | wc -l)

    if ! confirm "Remove region '${target_region}' from account ${ACCOUNT_ID}? Remaining: ${remaining_regions}"; then
        info "Aborted."
        return
    fi

    if [[ "${remaining_count}" -le 1 && "$(echo "${remaining_regions}" | tr -d '[:space:]')" == "us-east-1" ]]; then
        info "Only us-east-1 remains. Reverting to org default SCP..."
        local scp_id
        scp_id=$(get_account_region_scp_id)
        if [[ -n "${scp_id}" && "${scp_id}" != "None" ]]; then
            ${AWS_CMD} organizations detach-policy \
                --policy-id "${scp_id}" \
                --target-id "${ACCOUNT_ID}" 2>/dev/null || true
            ${AWS_CMD} organizations delete-policy \
                --policy-id "${scp_id}" 2>/dev/null || true
            info "Removed per-account SCP."
        fi

        rm -f "${POLICIES_DIR}/scp-region-${ACCOUNT_ID}.json"
    else
        local regions_json
        regions_json=$(echo "${remaining_regions}" | python3 -c "import sys, json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))")
        local scp_content
        scp_content=$(generate_region_scp "${regions_json}")
        local scp_id
        scp_id=$(get_account_region_scp_id)

        info "Updating per-account region SCP..."
        ${AWS_CMD} organizations update-policy \
            --policy-id "${scp_id}" \
            --content "${scp_content}" \
            --description "Region restriction for account ${ACCOUNT_ID}: ${regions_json}" >/dev/null

        echo "${scp_content}" > "${POLICIES_DIR}/scp-region-${ACCOUNT_ID}.json"
    fi

    info "Disabling region opt-in for '${target_region}'..."
    ${AWS_CMD} account disable-region --region-name "${target_region}" \
        --account-id "${ACCOUNT_ID}" 2>/dev/null \
        || warn "Could not opt-out region (may be a default region that cannot be disabled)."

    info "Region '${target_region}' disabled for account ${ACCOUNT_ID}."
}

# ── Extend Security Services to New Region ──────────────────────────────────

extend_security_services() {
    local target_region="$1"
    info "Extending security services to ${target_region} for account ${ACCOUNT_ID}..."

    info "  Enabling GuardDuty in ${target_region}..."
    local detector_id
    detector_id=$(${AWS_CMD} guardduty list-detectors --region "${target_region}" \
        --query 'DetectorIds[0]' --output text 2>/dev/null || echo "")
    if [[ -z "${detector_id}" || "${detector_id}" == "None" ]]; then
        ${AWS_CMD} guardduty create-detector --enable \
            --region "${target_region}" \
            --features '[{"Name":"EKS_AUDIT_LOGS","Status":"ENABLED"},{"Name":"S3_DATA_EVENTS","Status":"ENABLED"},{"Name":"EKS_RUNTIME_MONITORING","Status":"ENABLED"}]' \
            2>/dev/null || warn "  Could not enable GuardDuty in ${target_region}."
    fi

    info "  Enabling Security Hub in ${target_region}..."
    ${AWS_CMD} securityhub enable-security-hub \
        --region "${target_region}" \
        --enable-default-standards 2>/dev/null \
        || warn "  Could not enable Security Hub in ${target_region} (may already be enabled)."

    info "  Enabling Config recorder in ${target_region}..."
    ${AWS_CMD} configservice put-configuration-recorder \
        --region "${target_region}" \
        --configuration-recorder "name=default,roleARN=arn:aws:iam::${ACCOUNT_ID}:role/aws-service-role/config.amazonaws.com/AWSServiceRoleForConfig,recordingGroup={allSupported=true,includeGlobalResourceTypes=false}" \
        2>/dev/null || warn "  Could not set up Config in ${target_region}."

    info "  Security services extended to ${target_region}."
}

# ── Main ────────────────────────────────────────────────────────────────────

main() {
    info "=========================================="
    info "Per-Account Region Management"
    info "=========================================="
    info "Account: ${ACCOUNT_ID}"

    if [[ "${LIST_REGIONS}" == "true" ]]; then
        list_account_regions
    elif [[ -n "${ENABLE_REGION}" ]]; then
        enable_region_for_account "${ENABLE_REGION}"
    elif [[ -n "${DISABLE_REGION}" ]]; then
        disable_region_for_account "${DISABLE_REGION}"
    else
        die "Specify --enable-region, --disable-region, or --list."
    fi
}

main

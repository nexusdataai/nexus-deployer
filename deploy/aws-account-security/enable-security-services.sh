#!/bin/bash
#
# Enable Security Services Across Organization
# Sets up CloudTrail (org trail), GuardDuty, AWS Config, Security Hub,
# and IAM Access Analyzer for the entire AWS Organization.
#
# Prerequisites:
#   - Organization created and SCPs applied
#   - Service access principals enabled via setup-organization.sh
#
# Usage:
#   ./enable-security-services.sh
#   ./enable-security-services.sh --profile master-admin --trail-bucket my-bucket
#

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Defaults
AWS_PROFILE="${AWS_PROFILE:-default}"
REGION="${REGION:-us-east-1}"
AUTO_APPROVE="${AUTO_APPROVE:-no}"
TRAIL_NAME="nexus-org-trail"
TRAIL_BUCKET=""
CONFIG_BUCKET=""
SNS_TOPIC_ARN=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --profile)        AWS_PROFILE="$2"; shift 2 ;;
        --region)         REGION="$2"; shift 2 ;;
        --trail-bucket)   TRAIL_BUCKET="$2"; shift 2 ;;
        --config-bucket)  CONFIG_BUCKET="$2"; shift 2 ;;
        --sns-topic)      SNS_TOPIC_ARN="$2"; shift 2 ;;
        --auto-approve)   AUTO_APPROVE=yes; shift ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Enable organization-wide security monitoring services."
            echo ""
            echo "Options:"
            echo "  --profile PROFILE         AWS CLI profile (default: default)"
            echo "  --region REGION           AWS region (default: us-east-1)"
            echo "  --trail-bucket NAME       S3 bucket for CloudTrail logs (auto-created if empty)"
            echo "  --config-bucket NAME      S3 bucket for Config snapshots (auto-created if empty)"
            echo "  --sns-topic ARN           SNS topic for security alerts"
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
ORG_ID=$(${AWS_CMD} organizations describe-organization --query 'Organization.Id' --output text)
info "Master account: ${MASTER_ACCOUNT_ID}"
info "Organization:   ${ORG_ID}"

[[ -z "${TRAIL_BUCKET}" ]] && TRAIL_BUCKET="nexus-cloudtrail-${MASTER_ACCOUNT_ID}"
[[ -z "${CONFIG_BUCKET}" ]] && CONFIG_BUCKET="nexus-config-${MASTER_ACCOUNT_ID}"

# ── 1. CloudTrail Organization Trail ────────────────────────────────────────

setup_cloudtrail() {
    info ""
    info "── CloudTrail Organization Trail ──"

    info "Ensuring CloudTrail S3 bucket exists: ${TRAIL_BUCKET}..."
    if ! ${AWS_CMD} s3api head-bucket --bucket "${TRAIL_BUCKET}" 2>/dev/null; then
        ${AWS_CMD} s3api create-bucket --bucket "${TRAIL_BUCKET}" --region "${REGION}" \
            $(if [[ "${REGION}" != "us-east-1" ]]; then echo "--create-bucket-configuration LocationConstraint=${REGION}"; fi) \
            >/dev/null
        info "Bucket created: ${TRAIL_BUCKET}"
    fi

    info "Setting bucket policy for CloudTrail..."
    local bucket_policy
    bucket_policy=$(cat <<EOFBP
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AWSCloudTrailAclCheck",
      "Effect": "Allow",
      "Principal": {"Service": "cloudtrail.amazonaws.com"},
      "Action": "s3:GetBucketAcl",
      "Resource": "arn:aws:s3:::${TRAIL_BUCKET}",
      "Condition": {"StringEquals": {"aws:SourceArn": "arn:aws:cloudtrail:${REGION}:${MASTER_ACCOUNT_ID}:trail/${TRAIL_NAME}"}}
    },
    {
      "Sid": "AWSCloudTrailWrite",
      "Effect": "Allow",
      "Principal": {"Service": "cloudtrail.amazonaws.com"},
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::${TRAIL_BUCKET}/AWSLogs/${ORG_ID}/*",
      "Condition": {
        "StringEquals": {
          "s3:x-amz-acl": "bucket-owner-full-control",
          "aws:SourceArn": "arn:aws:cloudtrail:${REGION}:${MASTER_ACCOUNT_ID}:trail/${TRAIL_NAME}"
        }
      }
    },
    {
      "Sid": "AWSCloudTrailWriteAccount",
      "Effect": "Allow",
      "Principal": {"Service": "cloudtrail.amazonaws.com"},
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::${TRAIL_BUCKET}/AWSLogs/${MASTER_ACCOUNT_ID}/*",
      "Condition": {
        "StringEquals": {
          "s3:x-amz-acl": "bucket-owner-full-control",
          "aws:SourceArn": "arn:aws:cloudtrail:${REGION}:${MASTER_ACCOUNT_ID}:trail/${TRAIL_NAME}"
        }
      }
    }
  ]
}
EOFBP
)
    ${AWS_CMD} s3api put-bucket-policy --bucket "${TRAIL_BUCKET}" --policy "${bucket_policy}"

    ${AWS_CMD} s3api put-public-access-block --bucket "${TRAIL_BUCKET}" \
        --public-access-block-configuration \
        "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

    ${AWS_CMD} s3api put-bucket-encryption --bucket "${TRAIL_BUCKET}" \
        --server-side-encryption-configuration \
        '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms"},"BucketKeyEnabled":true}]}'

    local trail_exists
    trail_exists=$(${AWS_CMD} cloudtrail describe-trails \
        --trail-name-list "${TRAIL_NAME}" \
        --query 'trailList[0].TrailARN' --output text 2>/dev/null || echo "None")

    if [[ "${trail_exists}" == "None" ]]; then
        info "Creating organization trail: ${TRAIL_NAME}..."
        ${AWS_CMD} cloudtrail create-trail \
            --name "${TRAIL_NAME}" \
            --s3-bucket-name "${TRAIL_BUCKET}" \
            --is-organization-trail \
            --is-multi-region-trail \
            --enable-log-file-validation \
            --include-global-service-events >/dev/null
    else
        info "Trail ${TRAIL_NAME} already exists. Updating..."
        ${AWS_CMD} cloudtrail update-trail \
            --name "${TRAIL_NAME}" \
            --s3-bucket-name "${TRAIL_BUCKET}" \
            --is-organization-trail \
            --is-multi-region-trail \
            --enable-log-file-validation \
            --include-global-service-events >/dev/null
    fi

    info "Starting trail logging..."
    ${AWS_CMD} cloudtrail start-logging --name "${TRAIL_NAME}" 2>/dev/null || true

    info "Enabling data events for S3 and DynamoDB..."
    ${AWS_CMD} cloudtrail put-event-selectors \
        --trail-name "${TRAIL_NAME}" \
        --advanced-event-selectors '[
            {
                "Name": "S3DataEvents",
                "FieldSelectors": [
                    {"Field": "eventCategory", "Equals": ["Data"]},
                    {"Field": "resources.type", "Equals": ["AWS::S3::Object"]}
                ]
            },
            {
                "Name": "DynamoDBDataEvents",
                "FieldSelectors": [
                    {"Field": "eventCategory", "Equals": ["Data"]},
                    {"Field": "resources.type", "Equals": ["AWS::DynamoDB::Table"]}
                ]
            }
        ]' 2>/dev/null || warn "Could not set advanced event selectors (may need newer CLI)."

    info "CloudTrail organization trail configured."
}

# ── 2. GuardDuty ────────────────────────────────────────────────────────────

setup_guardduty() {
    info ""
    info "── GuardDuty ──"

    local detector_id
    detector_id=$(${AWS_CMD} guardduty list-detectors \
        --query 'DetectorIds[0]' --output text 2>/dev/null || echo "")

    if [[ -z "${detector_id}" || "${detector_id}" == "None" ]]; then
        info "Creating GuardDuty detector..."
        detector_id=$(${AWS_CMD} guardduty create-detector \
            --enable \
            --features '[
                {"Name":"S3_DATA_EVENTS","Status":"ENABLED"},
                {"Name":"EKS_AUDIT_LOGS","Status":"ENABLED"},
                {"Name":"EKS_RUNTIME_MONITORING","Status":"ENABLED","AdditionalConfiguration":[{"Name":"EKS_ADDON_MANAGEMENT","Status":"ENABLED"}]},
                {"Name":"RUNTIME_MONITORING","Status":"ENABLED"},
                {"Name":"MALWARE_PROTECTION","Status":"ENABLED"}
            ]' \
            --query 'DetectorId' --output text 2>/dev/null) \
            || die "Failed to create GuardDuty detector."
    else
        info "GuardDuty detector exists: ${detector_id}. Updating features..."
        ${AWS_CMD} guardduty update-detector \
            --detector-id "${detector_id}" \
            --enable \
            --features '[
                {"Name":"S3_DATA_EVENTS","Status":"ENABLED"},
                {"Name":"EKS_AUDIT_LOGS","Status":"ENABLED"},
                {"Name":"EKS_RUNTIME_MONITORING","Status":"ENABLED","AdditionalConfiguration":[{"Name":"EKS_ADDON_MANAGEMENT","Status":"ENABLED"}]},
                {"Name":"RUNTIME_MONITORING","Status":"ENABLED"},
                {"Name":"MALWARE_PROTECTION","Status":"ENABLED"}
            ]' 2>/dev/null || warn "Could not update all GuardDuty features."
    fi

    info "Enabling GuardDuty auto-enable for new member accounts..."
    ${AWS_CMD} guardduty update-organization-configuration \
        --detector-id "${detector_id}" \
        --auto-enable ALL \
        --features '[
            {"Name":"S3_DATA_EVENTS","AutoEnable":"ALL"},
            {"Name":"EKS_AUDIT_LOGS","AutoEnable":"ALL"},
            {"Name":"EKS_RUNTIME_MONITORING","AutoEnable":"ALL"},
            {"Name":"RUNTIME_MONITORING","AutoEnable":"ALL"}
        ]' 2>/dev/null || warn "Could not set org auto-enable (may need delegated admin)."

    info "Enrolling existing member accounts..."
    local member_accounts
    member_accounts=$(${AWS_CMD} organizations list-accounts \
        --query "Accounts[?Id!='${MASTER_ACCOUNT_ID}' && Status=='ACTIVE'].Id" --output text 2>/dev/null)

    for acct in ${member_accounts}; do
        ${AWS_CMD} guardduty create-members \
            --detector-id "${detector_id}" \
            --account-details "[{\"AccountId\":\"${acct}\"}]" 2>/dev/null || true
        ${AWS_CMD} guardduty invite-members \
            --detector-id "${detector_id}" \
            --account-ids "${acct}" 2>/dev/null || true
    done

    info "GuardDuty configured. Detector: ${detector_id}"
}

# ── 3. AWS Config ───────────────────────────────────────────────────────────

setup_config() {
    info ""
    info "── AWS Config ──"

    info "Ensuring Config S3 bucket: ${CONFIG_BUCKET}..."
    if ! ${AWS_CMD} s3api head-bucket --bucket "${CONFIG_BUCKET}" 2>/dev/null; then
        ${AWS_CMD} s3api create-bucket --bucket "${CONFIG_BUCKET}" --region "${REGION}" \
            $(if [[ "${REGION}" != "us-east-1" ]]; then echo "--create-bucket-configuration LocationConstraint=${REGION}"; fi) \
            >/dev/null
    fi

    ${AWS_CMD} s3api put-public-access-block --bucket "${CONFIG_BUCKET}" \
        --public-access-block-configuration \
        "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

    local config_bucket_policy
    config_bucket_policy=$(cat <<EOFCBP
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AWSConfigBucketPermissionsCheck",
      "Effect": "Allow",
      "Principal": {"Service": "config.amazonaws.com"},
      "Action": "s3:GetBucketAcl",
      "Resource": "arn:aws:s3:::${CONFIG_BUCKET}"
    },
    {
      "Sid": "AWSConfigBucketDelivery",
      "Effect": "Allow",
      "Principal": {"Service": "config.amazonaws.com"},
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::${CONFIG_BUCKET}/*",
      "Condition": {"StringEquals": {"s3:x-amz-acl": "bucket-owner-full-control"}}
    }
  ]
}
EOFCBP
)
    ${AWS_CMD} s3api put-bucket-policy --bucket "${CONFIG_BUCKET}" --policy "${config_bucket_policy}"

    info "Setting up Config recorder in master account..."
    local config_role_arn="arn:aws:iam::${MASTER_ACCOUNT_ID}:role/aws-service-role/config.amazonaws.com/AWSServiceRoleForConfig"

    ${AWS_CMD} iam create-service-linked-role \
        --aws-service-name config.amazonaws.com 2>/dev/null || true

    ${AWS_CMD} configservice put-configuration-recorder \
        --configuration-recorder "name=default,roleARN=${config_role_arn},recordingGroup={allSupported=true,includeGlobalResourceTypes=true}" \
        2>/dev/null || warn "Could not configure recorder."

    ${AWS_CMD} configservice put-delivery-channel \
        --delivery-channel "{\"name\":\"default\",\"s3BucketName\":\"${CONFIG_BUCKET}\",\"configSnapshotDeliveryProperties\":{\"deliveryFrequency\":\"TwentyFour_Hours\"}}" \
        2>/dev/null || warn "Could not set delivery channel."

    ${AWS_CMD} configservice start-configuration-recorder \
        --configuration-recorder-name default 2>/dev/null || true

    info "Setting up Config aggregator..."
    ${AWS_CMD} configservice put-configuration-aggregator \
        --configuration-aggregator-name "nexus-org-aggregator" \
        --organization-aggregation-source "{\"RoleArn\":\"${config_role_arn}\",\"AllAwsRegions\":true}" \
        2>/dev/null || warn "Could not create org aggregator (may need different role)."

    info "Deploying Config rules..."
    local rules=(
        "iam-root-access-key-check"
        "root-account-mfa-enabled"
        "s3-bucket-public-read-prohibited"
        "s3-bucket-public-write-prohibited"
        "encrypted-volumes"
        "restricted-ssh"
        "vpc-flow-logs-enabled"
        "cloud-trail-enabled"
        "iam-user-mfa-enabled"
        "s3-bucket-server-side-encryption-enabled"
        "ebs-optimized-instance"
    )

    for rule in "${rules[@]}"; do
        info "  Enabling rule: ${rule}..."
        ${AWS_CMD} configservice put-config-rule \
            --config-rule "{
                \"ConfigRuleName\": \"${rule}\",
                \"Source\": {
                    \"Owner\": \"AWS\",
                    \"SourceIdentifier\": \"$(echo "${rule}" | tr '[:lower:]-' '[:upper:]_')\"
                }
            }" 2>/dev/null || warn "  Could not enable rule ${rule}."
    done

    info "AWS Config configured."
}

# ── 4. Security Hub ─────────────────────────────────────────────────────────

setup_security_hub() {
    info ""
    info "── Security Hub ──"

    info "Enabling Security Hub..."
    ${AWS_CMD} securityhub enable-security-hub \
        --enable-default-standards 2>/dev/null \
        || info "Security Hub may already be enabled."

    info "Enabling AWS Foundational Security Best Practices..."
    ${AWS_CMD} securityhub batch-enable-standards \
        --standards-subscription-requests '[
            {"StandardsArn":"arn:aws:securityhub:'"${REGION}"'::standards/aws-foundational-security-best-practices/v/1.0.0"},
            {"StandardsArn":"arn:aws:securityhub:::ruleset/cis-aws-foundations-benchmark/v/1.4.0"}
        ]' 2>/dev/null || warn "Could not enable standards (may already be enabled)."

    info "Configuring auto-enable for new member accounts..."
    ${AWS_CMD} securityhub update-organization-configuration \
        --auto-enable 2>/dev/null \
        || warn "Could not set auto-enable (may need delegated admin)."

    info "Enrolling existing member accounts..."
    local member_accounts
    member_accounts=$(${AWS_CMD} organizations list-accounts \
        --query "Accounts[?Id!='${MASTER_ACCOUNT_ID}' && Status=='ACTIVE'].{AccountId:Id,Email:Email}" \
        --output json 2>/dev/null)

    local account_list
    account_list=$(echo "${member_accounts}" | python3 -c "
import sys, json
accounts = json.load(sys.stdin)
result = [{'AccountId': a['AccountId']} for a in accounts if a.get('AccountId')]
print(json.dumps(result))
" 2>/dev/null || echo "[]")

    if [[ "${account_list}" != "[]" ]]; then
        ${AWS_CMD} securityhub create-members \
            --account-details "${account_list}" 2>/dev/null || true
    fi

    info "Security Hub configured."
}

# ── 5. IAM Access Analyzer ──────────────────────────────────────────────────

setup_access_analyzer() {
    info ""
    info "── IAM Access Analyzer ──"

    local existing
    existing=$(${AWS_CMD} accessanalyzer list-analyzers \
        --type ORGANIZATION \
        --query 'analyzers[0].arn' --output text 2>/dev/null || echo "None")

    if [[ "${existing}" != "None" ]]; then
        info "Organization Access Analyzer already exists: ${existing}"
    else
        info "Creating organization-level Access Analyzer..."
        ${AWS_CMD} accessanalyzer create-analyzer \
            --analyzer-name "nexus-org-analyzer" \
            --type ORGANIZATION \
            --tags "nexus:managed-by=aws-account-security" 2>/dev/null \
            || warn "Could not create Access Analyzer."
    fi

    info "IAM Access Analyzer configured."
}

# ── Main ────────────────────────────────────────────────────────────────────

main() {
    info "=========================================="
    info "Security Services Enablement"
    info "=========================================="
    info "Master Account: ${MASTER_ACCOUNT_ID}"
    info "Organization:   ${ORG_ID}"
    info "CloudTrail Bucket: ${TRAIL_BUCKET}"
    info "Config Bucket:     ${CONFIG_BUCKET}"
    info ""

    if ! confirm "Enable security services across the organization?"; then
        info "Aborted."
        exit 0
    fi

    setup_cloudtrail
    setup_guardduty
    setup_config
    setup_security_hub
    setup_access_analyzer

    info ""
    info "=========================================="
    info "Security services enablement complete."
    info "=========================================="
    info ""
    info "Services enabled:"
    info "  - CloudTrail org trail (${TRAIL_NAME}) -> s3://${TRAIL_BUCKET}"
    info "  - GuardDuty with EKS monitoring"
    info "  - AWS Config with org aggregator -> s3://${CONFIG_BUCKET}"
    info "  - Security Hub (FSBP + CIS Benchmarks)"
    info "  - IAM Access Analyzer (org-level)"
    info ""
    info "Next: Run audit-account-compliance.sh to verify."
}

main

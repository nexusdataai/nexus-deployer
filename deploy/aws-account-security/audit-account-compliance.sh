#!/bin/bash
#
# Continuous Multi-Account Compliance Audit
# Runs compliance checks across all member accounts, supports drift detection,
# scheduled execution, SNS alerts, and centralized S3 report storage.
#
# Usage:
#   ./audit-account-compliance.sh --all-accounts
#   ./audit-account-compliance.sh --account-id 123456789012
#   ./audit-account-compliance.sh --all-accounts --detect-drift
#   ./audit-account-compliance.sh --install-schedule --cron "0 6 * * *" --sns-topic arn:aws:sns:...
#

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Defaults
AWS_PROFILE="${AWS_PROFILE:-default}"
REGION="${REGION:-us-east-1}"
ACCOUNT_ID=""
ALL_ACCOUNTS=false
DETECT_DRIFT=false
INSTALL_SCHEDULE=false
CRON_EXPR=""
SNS_TOPIC_ARN=""
REPORT_BUCKET=""
CROSS_ACCOUNT_ROLE="${CROSS_ACCOUNT_ROLE:-NexusClusterProvisioner}"
EXTERNAL_ID="${EXTERNAL_ID:-}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --profile)            AWS_PROFILE="$2"; shift 2 ;;
        --region)             REGION="$2"; shift 2 ;;
        --account-id)         ACCOUNT_ID="$2"; shift 2 ;;
        --all-accounts)       ALL_ACCOUNTS=true; shift ;;
        --detect-drift)       DETECT_DRIFT=true; shift ;;
        --install-schedule)   INSTALL_SCHEDULE=true; shift ;;
        --cron)               CRON_EXPR="$2"; shift 2 ;;
        --sns-topic)          SNS_TOPIC_ARN="$2"; shift 2 ;;
        --report-bucket)      REPORT_BUCKET="$2"; shift 2 ;;
        --cross-account-role) CROSS_ACCOUNT_ROLE="$2"; shift 2 ;;
        --external-id)        EXTERNAL_ID="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Run compliance audit across AWS Organization accounts."
            echo ""
            echo "Audit targets:"
            echo "  --account-id ID           Audit a single account"
            echo "  --all-accounts            Audit all member accounts"
            echo ""
            echo "Options:"
            echo "  --detect-drift            Compare against last baseline"
            echo "  --sns-topic ARN           Send alerts on failures"
            echo "  --report-bucket NAME      S3 bucket for reports (auto-generated if empty)"
            echo "  --cross-account-role ROLE Role to assume (default: NexusClusterProvisioner)"
            echo "  --external-id ID          External ID for role assumption"
            echo ""
            echo "Schedule:"
            echo "  --install-schedule        Install as cron job"
            echo "  --cron EXPR               Cron expression (e.g. '0 6 * * *')"
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

MASTER_ACCOUNT_ID=$(${AWS_CMD} sts get-caller-identity --query 'Account' --output text)
TIMESTAMP=$(date '+%Y-%m-%dT%H-%M-%S')

[[ -z "${REPORT_BUCKET}" ]] && REPORT_BUCKET="nexus-audit-reports-${MASTER_ACCOUNT_ID}"

TARGET_CMD="aws --region ${REGION}"

TOTAL_PASS=0
TOTAL_FAIL=0
TOTAL_WARN=0
REPORT_LINES=()

# ── Helpers ─────────────────────────────────────────────────────────────────

assume_role() {
    local target_account="$1"
    local role_arn="arn:aws:iam::${target_account}:role/${CROSS_ACCOUNT_ROLE}"
    local assume_args="--role-arn ${role_arn} --role-session-name nexus-audit --duration-seconds 3600"
    [[ -n "${EXTERNAL_ID}" ]] && assume_args="${assume_args} --external-id ${EXTERNAL_ID}"

    local creds
    creds=$(${AWS_CMD} sts assume-role ${assume_args} --output json 2>/dev/null) || return 1

    export AWS_ACCESS_KEY_ID=$(echo "${creds}" | python3 -c "import sys,json; print(json.load(sys.stdin)['Credentials']['AccessKeyId'])")
    export AWS_SECRET_ACCESS_KEY=$(echo "${creds}" | python3 -c "import sys,json; print(json.load(sys.stdin)['Credentials']['SecretAccessKey'])")
    export AWS_SESSION_TOKEN=$(echo "${creds}" | python3 -c "import sys,json; print(json.load(sys.stdin)['Credentials']['SessionToken'])")
}

clear_assumed_role() {
    unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
}

check_pass() {
    local check_name="$1"
    TOTAL_PASS=$((TOTAL_PASS + 1))
    REPORT_LINES+=("{\"account\":\"${CURRENT_ACCOUNT}\",\"check\":\"${check_name}\",\"status\":\"PASS\"}")
    info "    [PASS] ${check_name}"
}

check_fail() {
    local check_name="$1"
    local detail="$2"
    TOTAL_FAIL=$((TOTAL_FAIL + 1))
    REPORT_LINES+=("{\"account\":\"${CURRENT_ACCOUNT}\",\"check\":\"${check_name}\",\"status\":\"FAIL\",\"detail\":\"${detail}\"}")
    err "    [FAIL] ${check_name}: ${detail}"
}

check_warn() {
    local check_name="$1"
    local detail="$2"
    TOTAL_WARN=$((TOTAL_WARN + 1))
    REPORT_LINES+=("{\"account\":\"${CURRENT_ACCOUNT}\",\"check\":\"${check_name}\",\"status\":\"WARN\",\"detail\":\"${detail}\"}")
    warn "    [WARN] ${check_name}: ${detail}"
}

# ── Org-Level Checks (run from master) ──────────────────────────────────────

audit_org_scps() {
    info "  Checking SCPs..."
    local root_id
    root_id=$(${AWS_CMD} organizations list-roots --query 'Roots[0].Id' --output text)

    local expected_scps=("NexusRegionRestriction" "NexusServiceWhitelist" "NexusRootProtection" "NexusSecurityBaseline")
    local attached_policies
    attached_policies=$(${AWS_CMD} organizations list-policies-for-target \
        --target-id "${root_id}" --filter SERVICE_CONTROL_POLICY \
        --query 'Policies[].Name' --output text 2>/dev/null)

    for scp_name in "${expected_scps[@]}"; do
        if echo "${attached_policies}" | grep -q "${scp_name}"; then
            check_pass "SCP ${scp_name} attached to root"
        else
            check_fail "SCP ${scp_name} attached to root" "Not found"
        fi
    done
}

audit_cloudtrail() {
    info "  Checking CloudTrail..."
    local trail_status
    trail_status=$(${AWS_CMD} cloudtrail get-trail-status --name "nexus-org-trail" \
        --query 'IsLogging' --output text 2>/dev/null || echo "false")

    if [[ "${trail_status}" == "True" ]]; then
        check_pass "CloudTrail org trail is logging"
    else
        check_fail "CloudTrail org trail is logging" "Trail not logging or not found"
    fi
}

audit_guardduty_master() {
    info "  Checking GuardDuty (master)..."
    local detector_id
    detector_id=$(${AWS_CMD} guardduty list-detectors --query 'DetectorIds[0]' --output text 2>/dev/null)

    if [[ -n "${detector_id}" && "${detector_id}" != "None" ]]; then
        local status
        status=$(${AWS_CMD} guardduty get-detector --detector-id "${detector_id}" \
            --query 'Status' --output text 2>/dev/null)
        if [[ "${status}" == "ENABLED" ]]; then
            check_pass "GuardDuty enabled in master"
        else
            check_fail "GuardDuty enabled in master" "Status: ${status}"
        fi
    else
        check_fail "GuardDuty enabled in master" "No detector found"
    fi
}

audit_security_hub_master() {
    info "  Checking Security Hub (master)..."
    local hub_arn
    hub_arn=$(${AWS_CMD} securityhub describe-hub --query 'HubArn' --output text 2>/dev/null || echo "None")

    if [[ "${hub_arn}" != "None" ]]; then
        check_pass "Security Hub enabled in master"
    else
        check_fail "Security Hub enabled in master" "Not enabled"
    fi
}

audit_access_analyzer() {
    info "  Checking Access Analyzer..."
    local analyzer
    analyzer=$(${AWS_CMD} accessanalyzer list-analyzers --type ORGANIZATION \
        --query 'analyzers[0].status' --output text 2>/dev/null || echo "None")

    if [[ "${analyzer}" == "ACTIVE" ]]; then
        check_pass "Organization Access Analyzer active"
    else
        check_fail "Organization Access Analyzer active" "Status: ${analyzer}"
    fi
}

# ── Per-Account Checks ──────────────────────────────────────────────────────

audit_account() {
    local target_account="$1"
    CURRENT_ACCOUNT="${target_account}"
    info ""
    info "── Auditing account ${target_account} ──"

    if [[ "${target_account}" != "${MASTER_ACCOUNT_ID}" ]]; then
        if ! assume_role "${target_account}"; then
            check_fail "Cross-account role assumption" "Cannot assume ${CROSS_ACCOUNT_ROLE}"
            return
        fi
    fi

    # 1. Root access keys
    info "  Checking root access keys..."
    local root_keys
    root_keys=$(${TARGET_CMD} iam get-account-summary \
        --query 'SummaryMap.AccountAccessKeysPresent' --output text 2>/dev/null || echo "UNKNOWN")
    if [[ "${root_keys}" == "0" ]]; then
        check_pass "No root access keys"
    elif [[ "${root_keys}" == "UNKNOWN" ]]; then
        check_warn "No root access keys" "Could not determine"
    else
        check_fail "No root access keys" "Root access keys present"
    fi

    # 2. Password policy
    info "  Checking password policy..."
    local min_length
    min_length=$(${TARGET_CMD} iam get-account-password-policy \
        --query 'PasswordPolicy.MinimumPasswordLength' --output text 2>/dev/null || echo "0")
    if [[ "${min_length}" -ge 14 ]]; then
        check_pass "Password policy min length >= 14"
    else
        check_fail "Password policy min length >= 14" "Current: ${min_length}"
    fi

    # 3. S3 Block Public Access
    info "  Checking S3 Block Public Access..."
    local block_public
    block_public=$(${TARGET_CMD} s3control get-public-access-block \
        --account-id "${target_account}" \
        --query '[PublicAccessBlockConfiguration.BlockPublicAcls, PublicAccessBlockConfiguration.BlockPublicPolicy, PublicAccessBlockConfiguration.IgnorePublicAcls, PublicAccessBlockConfiguration.RestrictPublicBuckets]' \
        --output text 2>/dev/null || echo "")
    if echo "${block_public}" | grep -q "False"; then
        check_fail "S3 Block Public Access (all four)" "Not all enabled"
    elif [[ -z "${block_public}" ]]; then
        check_fail "S3 Block Public Access (all four)" "Not configured"
    else
        check_pass "S3 Block Public Access (all four)"
    fi

    # 4. EBS default encryption
    info "  Checking EBS default encryption..."
    local ebs_enc
    ebs_enc=$(${TARGET_CMD} ec2 get-ebs-encryption-by-default \
        --query 'EbsEncryptionByDefault' --output text 2>/dev/null || echo "False")
    if [[ "${ebs_enc}" == "True" ]]; then
        check_pass "EBS default encryption enabled"
    else
        check_fail "EBS default encryption enabled" "Disabled"
    fi

    # 5. IAM users (should be none in member accounts)
    if [[ "${target_account}" != "${MASTER_ACCOUNT_ID}" ]]; then
        info "  Checking for IAM users..."
        local user_count
        user_count=$(${TARGET_CMD} iam list-users --query 'length(Users)' --output text 2>/dev/null || echo "UNKNOWN")
        if [[ "${user_count}" == "0" ]]; then
            check_pass "No IAM users in member account"
        elif [[ "${user_count}" == "UNKNOWN" ]]; then
            check_warn "No IAM users in member account" "Could not determine"
        else
            check_fail "No IAM users in member account" "${user_count} users found"
        fi
    fi

    # 6. Default VPCs
    info "  Checking for default VPCs..."
    local default_vpcs
    default_vpcs=$(${TARGET_CMD} ec2 describe-vpcs \
        --filters "Name=isDefault,Values=true" \
        --query 'length(Vpcs)' --output text 2>/dev/null || echo "UNKNOWN")
    if [[ "${default_vpcs}" == "0" ]]; then
        check_pass "No default VPC in ${REGION}"
    elif [[ "${default_vpcs}" == "UNKNOWN" ]]; then
        check_warn "No default VPC in ${REGION}" "Could not determine"
    else
        check_fail "No default VPC in ${REGION}" "${default_vpcs} default VPC(s) found"
    fi

    # 7. GuardDuty
    info "  Checking GuardDuty..."
    local gd_detectors
    gd_detectors=$(${TARGET_CMD} guardduty list-detectors --query 'DetectorIds[0]' --output text 2>/dev/null || echo "")
    if [[ -n "${gd_detectors}" && "${gd_detectors}" != "None" ]]; then
        check_pass "GuardDuty detector present"
    else
        check_fail "GuardDuty detector present" "No detector"
    fi

    # 8. Config recorder
    info "  Checking Config recorder..."
    local config_status
    config_status=$(${TARGET_CMD} configservice describe-configuration-recorder-status \
        --query 'ConfigurationRecordersStatus[0].recording' --output text 2>/dev/null || echo "false")
    if [[ "${config_status}" == "True" || "${config_status}" == "true" ]]; then
        check_pass "Config recorder active"
    else
        check_warn "Config recorder active" "Not recording"
    fi

    # 9. Security Hub
    info "  Checking Security Hub..."
    local hub
    hub=$(${TARGET_CMD} securityhub describe-hub --query 'HubArn' --output text 2>/dev/null || echo "None")
    if [[ "${hub}" != "None" ]]; then
        check_pass "Security Hub enabled"
    else
        check_warn "Security Hub enabled" "Not enabled in this account"
    fi

    # 10. Open security groups
    info "  Checking for open security groups (0.0.0.0/0 on non-443/80)..."
    local open_sgs
    open_sgs=$(${TARGET_CMD} ec2 describe-security-groups \
        --filters "Name=ip-permission.cidr,Values=0.0.0.0/0" \
        --query "SecurityGroups[?!(IpPermissions[?FromPort==\`443\` || FromPort==\`80\`])].GroupId" \
        --output text 2>/dev/null || echo "")
    if [[ -z "${open_sgs}" ]]; then
        check_pass "No overly permissive security groups"
    else
        check_warn "No overly permissive security groups" "Review: ${open_sgs}"
    fi

    if [[ "${target_account}" != "${MASTER_ACCOUNT_ID}" ]]; then
        clear_assumed_role
    fi
}

# ── Report Generation ───────────────────────────────────────────────────────

generate_report() {
    info ""
    info "=========================================="
    info "AUDIT REPORT"
    info "=========================================="
    info "Timestamp: ${TIMESTAMP}"
    info "Pass: ${TOTAL_PASS}  Fail: ${TOTAL_FAIL}  Warn: ${TOTAL_WARN}"
    info ""

    local report_json="["
    local first=true
    for line in "${REPORT_LINES[@]}"; do
        if [[ "${first}" == "true" ]]; then
            first=false
        else
            report_json+=","
        fi
        report_json+="${line}"
    done
    report_json+="]"

    local report_file="/tmp/nexus-audit-${TIMESTAMP}.json"
    python3 -c "
import json, sys
data = json.loads('''${report_json}''')
report = {
    'timestamp': '${TIMESTAMP}',
    'master_account': '${MASTER_ACCOUNT_ID}',
    'summary': {'pass': ${TOTAL_PASS}, 'fail': ${TOTAL_FAIL}, 'warn': ${TOTAL_WARN}},
    'checks': data
}
with open('${report_file}', 'w') as f:
    json.dump(report, f, indent=2)
print(json.dumps(report['summary']))
"

    info "Report saved: ${report_file}"

    if ${AWS_CMD} s3api head-bucket --bucket "${REPORT_BUCKET}" 2>/dev/null; then
        local s3_key="audit-reports/${TIMESTAMP}/compliance-report.json"
        ${AWS_CMD} s3 cp "${report_file}" "s3://${REPORT_BUCKET}/${s3_key}" --quiet 2>/dev/null \
            && info "Report uploaded: s3://${REPORT_BUCKET}/${s3_key}" \
            || warn "Could not upload report to S3."
    fi

    if [[ -n "${SNS_TOPIC_ARN}" && ${TOTAL_FAIL} -gt 0 ]]; then
        info "Sending SNS alert for ${TOTAL_FAIL} failures..."
        ${AWS_CMD} sns publish \
            --topic-arn "${SNS_TOPIC_ARN}" \
            --subject "Nexus Audit: ${TOTAL_FAIL} FAILURES detected (${TIMESTAMP})" \
            --message "$(cat "${report_file}")" 2>/dev/null \
            || warn "Could not send SNS alert."
    fi
}

# ── Drift Detection ─────────────────────────────────────────────────────────

detect_drift() {
    if [[ "${DETECT_DRIFT}" != "true" ]]; then return; fi

    info ""
    info "── Drift Detection ──"

    if ! ${AWS_CMD} s3api head-bucket --bucket "${REPORT_BUCKET}" 2>/dev/null; then
        warn "Report bucket not found. Skipping drift detection."
        return
    fi

    local latest_baseline
    latest_baseline=$(${AWS_CMD} s3api list-objects-v2 \
        --bucket "${REPORT_BUCKET}" --prefix "audit-reports/" \
        --query 'sort_by(Contents, &LastModified)[-2].Key' \
        --output text 2>/dev/null || echo "None")

    if [[ "${latest_baseline}" == "None" || -z "${latest_baseline}" ]]; then
        info "No previous baseline found. Current run becomes the baseline."
        return
    fi

    info "Comparing against baseline: ${latest_baseline}"
    local baseline_file="/tmp/nexus-audit-baseline.json"
    ${AWS_CMD} s3 cp "s3://${REPORT_BUCKET}/${latest_baseline}" "${baseline_file}" --quiet 2>/dev/null

    python3 -c "
import json
with open('${baseline_file}') as f:
    baseline = json.load(f)
with open('/tmp/nexus-audit-${TIMESTAMP}.json') as f:
    current = json.load(f)

baseline_checks = {(c['account'], c['check']): c['status'] for c in baseline.get('checks', [])}
current_checks = {(c['account'], c['check']): c['status'] for c in current.get('checks', [])}

drifts = []
for key, status in current_checks.items():
    prev = baseline_checks.get(key, 'NEW')
    if prev != status:
        drifts.append({'account': key[0], 'check': key[1], 'previous': prev, 'current': status})

if drifts:
    print(f'DRIFT DETECTED: {len(drifts)} check(s) changed since last baseline.')
    for d in drifts:
        print(f\"  Account {d['account']}: {d['check']} changed from {d['previous']} to {d['current']}\")
else:
    print('No drift detected.')
" 2>/dev/null || warn "Drift comparison failed."
}

# ── Schedule Installation ───────────────────────────────────────────────────

install_schedule() {
    if [[ "${INSTALL_SCHEDULE}" != "true" ]]; then return; fi

    [[ -z "${CRON_EXPR}" ]] && { err "Specify --cron with --install-schedule."; exit 1; }

    info "Installing cron schedule: ${CRON_EXPR}"
    local script_path
    script_path=$(realpath "$0")
    local cron_cmd="${CRON_EXPR} ${script_path} --all-accounts --profile ${AWS_PROFILE}"
    [[ -n "${SNS_TOPIC_ARN}" ]] && cron_cmd="${cron_cmd} --sns-topic ${SNS_TOPIC_ARN}"
    [[ -n "${REPORT_BUCKET}" ]] && cron_cmd="${cron_cmd} --report-bucket ${REPORT_BUCKET}"
    cron_cmd="${cron_cmd} >> /var/log/nexus-audit.log 2>&1"

    (crontab -l 2>/dev/null | grep -v "audit-account-compliance"; echo "${cron_cmd}") | crontab -
    info "Cron job installed. Verify with: crontab -l"
    exit 0
}

# ── Main ────────────────────────────────────────────────────────────────────

main() {
    install_schedule

    info "=========================================="
    info "Nexus Multi-Account Compliance Audit"
    info "=========================================="
    info "Master Account: ${MASTER_ACCOUNT_ID}"
    info "Timestamp:      ${TIMESTAMP}"
    info ""

    CURRENT_ACCOUNT="${MASTER_ACCOUNT_ID}"
    audit_org_scps
    audit_cloudtrail
    audit_guardduty_master
    audit_security_hub_master
    audit_access_analyzer

    if [[ "${ALL_ACCOUNTS}" == "true" ]]; then
        local accounts
        accounts=$(${AWS_CMD} organizations list-accounts \
            --query "Accounts[?Status=='ACTIVE'].Id" --output text)

        for acct in ${accounts}; do
            audit_account "${acct}"
        done
    elif [[ -n "${ACCOUNT_ID}" ]]; then
        audit_account "${ACCOUNT_ID}"
    else
        audit_account "${MASTER_ACCOUNT_ID}"
    fi

    generate_report
    detect_drift

    local exit_code=0
    [[ ${TOTAL_FAIL} -gt 0 ]] && exit_code=1
    info ""
    info "Audit complete. Exit code: ${exit_code}"
    exit ${exit_code}
}

main

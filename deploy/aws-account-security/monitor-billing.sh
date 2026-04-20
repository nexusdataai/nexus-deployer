#!/bin/bash
#
# Multi-Account Billing Monitoring
# Sets up budgets, cost anomaly detection, and generates cost reports
# across the entire AWS Organization.
#
# Usage:
#   ./monitor-billing.sh --setup --monthly-budget 5000 --alert-email admin@company.com
#   ./monitor-billing.sh --report
#   ./monitor-billing.sh --report --account-id 123456789012
#   ./monitor-billing.sh --set-budget --account-id 123456789012 --amount 3000
#   ./monitor-billing.sh --status
#

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Defaults
AWS_PROFILE="${AWS_PROFILE:-default}"
REGION="${REGION:-us-east-1}"
ACTION=""
ACCOUNT_ID=""
MONTHLY_BUDGET=""
ALERT_EMAIL=""
REPORT_BUCKET=""
SNS_TOPIC_NAME="nexus-billing-alerts"
BUDGET_AMOUNT=""

COST_ALLOCATION_TAGS=("nexus:capability" "nexus:environment" "nexus:account-alias")

while [[ $# -gt 0 ]]; do
    case $1 in
        --profile)         AWS_PROFILE="$2"; shift 2 ;;
        --region)          REGION="$2"; shift 2 ;;
        --setup)           ACTION="setup"; shift ;;
        --report)          ACTION="report"; shift ;;
        --set-budget)      ACTION="set-budget"; shift ;;
        --status)          ACTION="status"; shift ;;
        --account-id)      ACCOUNT_ID="$2"; shift 2 ;;
        --monthly-budget)  MONTHLY_BUDGET="$2"; shift 2 ;;
        --amount)          BUDGET_AMOUNT="$2"; shift 2 ;;
        --alert-email)     ALERT_EMAIL="$2"; shift 2 ;;
        --report-bucket)   REPORT_BUCKET="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 ACTION [OPTIONS]"
            echo ""
            echo "Multi-account billing monitoring and alerting."
            echo ""
            echo "Actions:"
            echo "  --setup              Initial setup (budgets, alarms, anomaly detection)"
            echo "  --report             Generate cost report"
            echo "  --set-budget         Update budget for a specific account"
            echo "  --status             Show active alerts and anomalies"
            echo ""
            echo "Options:"
            echo "  --monthly-budget N   Monthly budget in USD (for --setup)"
            echo "  --alert-email EMAIL  Email for budget alerts"
            echo "  --account-id ID      Target account (for --report or --set-budget)"
            echo "  --amount N           Budget amount (for --set-budget)"
            echo "  --report-bucket NAME S3 bucket for reports"
            echo "  --profile PROFILE    AWS CLI profile"
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

MASTER_ACCOUNT_ID=$(${AWS_CMD} sts get-caller-identity --query 'Account' --output text)
[[ -z "${REPORT_BUCKET}" ]] && REPORT_BUCKET="nexus-billing-reports-${MASTER_ACCOUNT_ID}"
TIMESTAMP=$(date '+%Y-%m-%dT%H-%M-%S')
CURRENT_MONTH=$(date '+%Y-%m')
PREVIOUS_MONTH=$(date -d "$(date +%Y-%m-01) -1 month" '+%Y-%m' 2>/dev/null \
    || date -v-1m '+%Y-%m' 2>/dev/null \
    || echo "")

[[ -z "${ACTION}" ]] && die "Specify an action: --setup, --report, --set-budget, or --status."

# ── Setup ───────────────────────────────────────────────────────────────────

setup_billing() {
    [[ -z "${MONTHLY_BUDGET}" ]] && die "--monthly-budget is required for --setup."
    [[ -z "${ALERT_EMAIL}" ]] && die "--alert-email is required for --setup."

    info "=========================================="
    info "Billing Monitoring Setup"
    info "=========================================="
    info "Master Account: ${MASTER_ACCOUNT_ID}"
    info "Monthly Budget: \$${MONTHLY_BUDGET}"
    info "Alert Email:    ${ALERT_EMAIL}"
    info ""

    # SNS Topic
    info "── Creating SNS topic ──"
    local sns_topic_arn
    sns_topic_arn=$(${AWS_CMD} sns create-topic --name "${SNS_TOPIC_NAME}" \
        --query 'TopicArn' --output text 2>/dev/null)
    info "SNS topic: ${sns_topic_arn}"

    ${AWS_CMD} sns subscribe \
        --topic-arn "${sns_topic_arn}" \
        --protocol email \
        --notification-endpoint "${ALERT_EMAIL}" 2>/dev/null \
        || warn "Could not subscribe email (may already exist)."

    # Cost Allocation Tags
    info ""
    info "── Activating cost allocation tags ──"
    for tag in "${COST_ALLOCATION_TAGS[@]}"; do
        ${AWS_CMD} ce update-cost-allocation-tags-status \
            --cost-allocation-tags-status "[{\"TagKey\":\"${tag}\",\"Status\":\"Active\"}]" \
            2>/dev/null || warn "Could not activate tag: ${tag}"
        info "  Activated: ${tag}"
    done

    # Org-wide budget
    info ""
    info "── Creating organization-wide budget ──"
    create_budget "nexus-org-total" "${MONTHLY_BUDGET}" "${sns_topic_arn}" ""

    # Per-account budgets
    info ""
    info "── Creating per-account budgets ──"
    local accounts
    accounts=$(${AWS_CMD} organizations list-accounts \
        --query "Accounts[?Status=='ACTIVE'].Id" --output text 2>/dev/null)

    local per_account_budget
    per_account_budget=$(echo "${MONTHLY_BUDGET}" | python3 -c "import sys; print(int(float(sys.stdin.read().strip())))")

    for acct in ${accounts}; do
        create_budget "nexus-account-${acct}" "${per_account_budget}" "${sns_topic_arn}" "${acct}"
    done

    # Cost Anomaly Detection
    info ""
    info "── Setting up Cost Anomaly Detection ──"
    setup_anomaly_detection "${sns_topic_arn}"

    # Report bucket
    info ""
    info "── Ensuring report bucket ──"
    if ! ${AWS_CMD} s3api head-bucket --bucket "${REPORT_BUCKET}" 2>/dev/null; then
        ${AWS_CMD} s3api create-bucket --bucket "${REPORT_BUCKET}" --region "${REGION}" \
            $(if [[ "${REGION}" != "us-east-1" ]]; then echo "--create-bucket-configuration LocationConstraint=${REGION}"; fi) \
            >/dev/null
        ${AWS_CMD} s3api put-public-access-block --bucket "${REPORT_BUCKET}" \
            --public-access-block-configuration \
            "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
        info "Created: s3://${REPORT_BUCKET}"
    else
        info "Bucket exists: s3://${REPORT_BUCKET}"
    fi

    info ""
    info "=========================================="
    info "Billing monitoring setup complete."
    info "=========================================="
    info ""
    info "IMPORTANT: Check ${ALERT_EMAIL} to confirm the SNS subscription."
}

create_budget() {
    local budget_name="$1"
    local amount="$2"
    local topic_arn="$3"
    local linked_account="$4"

    local cost_filters="{}"
    if [[ -n "${linked_account}" ]]; then
        cost_filters="{\"LinkedAccount\":{\"Key\":\"LinkedAccount\",\"Values\":[\"${linked_account}\"]}}"
    fi

    local budget_json
    budget_json=$(cat <<EOFBUDGET
{
    "BudgetName": "${budget_name}",
    "BudgetType": "COST",
    "BudgetLimit": {
        "Amount": "${amount}",
        "Unit": "USD"
    },
    "TimeUnit": "MONTHLY",
    "CostFilters": ${cost_filters},
    "CostTypes": {
        "IncludeTax": true,
        "IncludeSubscription": true,
        "UseBlended": false,
        "IncludeRefund": false,
        "IncludeCredit": false,
        "IncludeUpfront": true,
        "IncludeRecurring": true,
        "IncludeOtherSubscription": true,
        "IncludeSupport": true,
        "IncludeDiscount": true,
        "UseAmortized": false
    }
}
EOFBUDGET
)

    local thresholds=("50" "80" "100" "120")
    local notifications_json="["
    local subscribers_json="["
    local first=true

    for threshold in "${thresholds[@]}"; do
        local comp_type="GREATER_THAN"
        local notif_type="ACTUAL"
        [[ "${threshold}" == "120" ]] && notif_type="FORECASTED"

        if [[ "${first}" == "true" ]]; then
            first=false
        else
            notifications_json+=","
            subscribers_json+=","
        fi

        notifications_json+="{
            \"NotificationType\":\"${notif_type}\",
            \"ComparisonOperator\":\"${comp_type}\",
            \"Threshold\":${threshold},
            \"ThresholdType\":\"PERCENTAGE\",
            \"NotificationState\":\"ALARM\"
        }"

        subscribers_json+="[{\"SubscriptionType\":\"SNS\",\"Address\":\"${topic_arn}\"}]"
    done

    notifications_json+="]"
    subscribers_json+="]"

    info "  Creating budget: ${budget_name} (\$${amount}/month)..."
    ${AWS_CMD} budgets create-budget \
        --account-id "${MASTER_ACCOUNT_ID}" \
        --budget "${budget_json}" \
        --notifications-with-subscribers "$(python3 -c "
import json
notifs = json.loads('${notifications_json}')
subs = json.loads('${subscribers_json}')
result = [{'Notification': n, 'Subscribers': s} for n, s in zip(notifs, subs)]
print(json.dumps(result))
")" 2>/dev/null \
        || warn "  Budget ${budget_name} may already exist (updating not supported via create)."
}

setup_anomaly_detection() {
    local topic_arn="$1"

    info "Creating cost anomaly monitor (org-level)..."
    local monitor_arn
    monitor_arn=$(${AWS_CMD} ce create-anomaly-monitor \
        --anomaly-monitor '{
            "MonitorName": "nexus-org-cost-monitor",
            "MonitorType": "DIMENSIONAL",
            "MonitorDimension": "SERVICE"
        }' \
        --query 'MonitorArn' --output text 2>/dev/null) \
        || { warn "Could not create anomaly monitor (may already exist)."; return; }

    info "Monitor ARN: ${monitor_arn}"

    info "Creating anomaly subscription..."
    ${AWS_CMD} ce create-anomaly-subscription \
        --anomaly-subscription "{
            \"SubscriptionName\": \"nexus-cost-anomaly-alerts\",
            \"MonitorArnList\": [\"${monitor_arn}\"],
            \"Subscribers\": [{\"Type\": \"SNS\", \"Address\": \"${topic_arn}\"}],
            \"Frequency\": \"DAILY\",
            \"ThresholdExpression\": {
                \"Dimensions\": {
                    \"Key\": \"ANOMALY_TOTAL_IMPACT_ABSOLUTE\",
                    \"MatchOptions\": [\"GREATER_THAN_OR_EQUAL\"],
                    \"Values\": [\"10\"]
                }
            }
        }" 2>/dev/null \
        || warn "Could not create anomaly subscription."

    info "Cost anomaly detection configured."
}

# ── Report ──────────────────────────────────────────────────────────────────

generate_cost_report() {
    info "=========================================="
    info "Cost Report"
    info "=========================================="
    info "Period: ${CURRENT_MONTH}"
    info ""

    local start_date="${CURRENT_MONTH}-01"
    local end_date
    end_date=$(date '+%Y-%m-%d')

    local filter_expr="{}"
    if [[ -n "${ACCOUNT_ID}" ]]; then
        filter_expr="{\"Dimensions\":{\"Key\":\"LINKED_ACCOUNT\",\"Values\":[\"${ACCOUNT_ID}\"]}}"
    fi

    # Total org spend
    info "── Organization Total (MTD) ──"
    local total_result
    total_result=$(${AWS_CMD} ce get-cost-and-usage \
        --time-period "Start=${start_date},End=${end_date}" \
        --granularity MONTHLY \
        --metrics "UnblendedCost" "BlendedCost" \
        --filter "${filter_expr}" \
        --output json 2>/dev/null)

    local mtd_cost
    mtd_cost=$(echo "${total_result}" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for period in data.get('ResultsByTime', []):
    cost = period['Total']['UnblendedCost']['Amount']
    print(f'{float(cost):.2f}')
" 2>/dev/null || echo "N/A")
    info "  MTD Spend: \$${mtd_cost}"

    # Forecast
    info ""
    info "── Forecast ──"
    local forecast
    forecast=$(${AWS_CMD} ce get-cost-forecast \
        --time-period "Start=${end_date},End=$(date -d "$(date +%Y-%m-01) +1 month -1 day" '+%Y-%m-%d' 2>/dev/null || date -v+1m -v1d -v-1d '+%Y-%m-%d' 2>/dev/null || echo "${end_date}")" \
        --granularity MONTHLY \
        --metric UNBLENDED_COST \
        --output json 2>/dev/null || echo "{}")

    local forecast_amount
    forecast_amount=$(echo "${forecast}" | python3 -c "
import sys, json
data = json.load(sys.stdin)
total = data.get('Total', {}).get('Amount', 'N/A')
if total != 'N/A':
    print(f'{float(total):.2f}')
else:
    print('N/A')
" 2>/dev/null || echo "N/A")
    info "  Projected Month-End: \$${forecast_amount}"

    # Per-account breakdown
    info ""
    info "── Per-Account Breakdown ──"
    local account_breakdown
    account_breakdown=$(${AWS_CMD} ce get-cost-and-usage \
        --time-period "Start=${start_date},End=${end_date}" \
        --granularity MONTHLY \
        --metrics "UnblendedCost" \
        --group-by "Type=DIMENSION,Key=LINKED_ACCOUNT" \
        --output json 2>/dev/null)

    echo "${account_breakdown}" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for period in data.get('ResultsByTime', []):
    groups = sorted(period.get('Groups', []), key=lambda g: float(g['Metrics']['UnblendedCost']['Amount']), reverse=True)
    for g in groups:
        acct = g['Keys'][0]
        cost = float(g['Metrics']['UnblendedCost']['Amount'])
        print(f'  Account {acct}: \${cost:.2f}')
" 2>/dev/null || warn "  Could not retrieve per-account breakdown."

    # Top services
    info ""
    info "── Top Services by Cost ──"
    local service_breakdown
    service_breakdown=$(${AWS_CMD} ce get-cost-and-usage \
        --time-period "Start=${start_date},End=${end_date}" \
        --granularity MONTHLY \
        --metrics "UnblendedCost" \
        --group-by "Type=DIMENSION,Key=SERVICE" \
        --filter "${filter_expr}" \
        --output json 2>/dev/null)

    echo "${service_breakdown}" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for period in data.get('ResultsByTime', []):
    groups = sorted(period.get('Groups', []), key=lambda g: float(g['Metrics']['UnblendedCost']['Amount']), reverse=True)[:10]
    for g in groups:
        svc = g['Keys'][0]
        cost = float(g['Metrics']['UnblendedCost']['Amount'])
        if cost > 0.01:
            print(f'  {svc}: \${cost:.2f}')
" 2>/dev/null || warn "  Could not retrieve service breakdown."

    # Previous month comparison
    if [[ -n "${PREVIOUS_MONTH}" ]]; then
        info ""
        info "── Month-over-Month Comparison ──"
        local prev_start="${PREVIOUS_MONTH}-01"
        local prev_end="${CURRENT_MONTH}-01"
        local prev_result
        prev_result=$(${AWS_CMD} ce get-cost-and-usage \
            --time-period "Start=${prev_start},End=${prev_end}" \
            --granularity MONTHLY \
            --metrics "UnblendedCost" \
            --filter "${filter_expr}" \
            --output json 2>/dev/null)

        local prev_cost
        prev_cost=$(echo "${prev_result}" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for period in data.get('ResultsByTime', []):
    cost = period['Total']['UnblendedCost']['Amount']
    print(f'{float(cost):.2f}')
" 2>/dev/null || echo "N/A")
        info "  Previous month (${PREVIOUS_MONTH}): \$${prev_cost}"
        info "  Current MTD (${CURRENT_MONTH}):     \$${mtd_cost}"
    fi

    # Data transfer costs
    info ""
    info "── Data Transfer Costs ──"
    local dt_result
    dt_result=$(${AWS_CMD} ce get-cost-and-usage \
        --time-period "Start=${start_date},End=${end_date}" \
        --granularity MONTHLY \
        --metrics "UnblendedCost" \
        --filter "{\"Dimensions\":{\"Key\":\"USAGE_TYPE_GROUP\",\"Values\":[\"EC2: Data Transfer - Internet (Out)\",\"EC2: Data Transfer - Region to Region (Out)\"]}}" \
        --output json 2>/dev/null || echo "{}")

    echo "${dt_result}" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for period in data.get('ResultsByTime', []):
    cost = float(period.get('Total', {}).get('UnblendedCost', {}).get('Amount', '0'))
    print(f'  Data Transfer: \${cost:.2f}')
" 2>/dev/null || info "  Data transfer breakdown not available."

    # Save report
    local report_file="/tmp/nexus-billing-${TIMESTAMP}.json"
    python3 -c "
import json
report = {
    'timestamp': '${TIMESTAMP}',
    'period': '${CURRENT_MONTH}',
    'mtd_cost': '${mtd_cost}',
    'forecast': '${forecast_amount}',
    'master_account': '${MASTER_ACCOUNT_ID}'
}
with open('${report_file}', 'w') as f:
    json.dump(report, f, indent=2)
" 2>/dev/null

    if ${AWS_CMD} s3api head-bucket --bucket "${REPORT_BUCKET}" 2>/dev/null; then
        ${AWS_CMD} s3 cp "${report_file}" \
            "s3://${REPORT_BUCKET}/billing-reports/${TIMESTAMP}/cost-report.json" \
            --quiet 2>/dev/null \
            && info "Report uploaded to s3://${REPORT_BUCKET}/billing-reports/${TIMESTAMP}/" \
            || warn "Could not upload report."
    fi

    info ""
    info "Report saved: ${report_file}"
}

# ── Set Budget ──────────────────────────────────────────────────────────────

set_account_budget() {
    [[ -z "${ACCOUNT_ID}" ]] && die "--account-id is required for --set-budget."
    [[ -z "${BUDGET_AMOUNT}" ]] && die "--amount is required for --set-budget."

    local budget_name="nexus-account-${ACCOUNT_ID}"
    info "Updating budget ${budget_name} to \$${BUDGET_AMOUNT}/month..."

    ${AWS_CMD} budgets update-budget \
        --account-id "${MASTER_ACCOUNT_ID}" \
        --new-budget "{
            \"BudgetName\": \"${budget_name}\",
            \"BudgetType\": \"COST\",
            \"BudgetLimit\": {\"Amount\": \"${BUDGET_AMOUNT}\", \"Unit\": \"USD\"},
            \"TimeUnit\": \"MONTHLY\",
            \"CostFilters\": {\"LinkedAccount\": {\"Key\": \"LinkedAccount\", \"Values\": [\"${ACCOUNT_ID}\"]}},
            \"CostTypes\": {
                \"IncludeTax\": true, \"IncludeSubscription\": true,
                \"UseBlended\": false, \"IncludeRefund\": false,
                \"IncludeCredit\": false, \"IncludeUpfront\": true,
                \"IncludeRecurring\": true, \"IncludeOtherSubscription\": true,
                \"IncludeSupport\": true, \"IncludeDiscount\": true,
                \"UseAmortized\": false
            }
        }" 2>/dev/null \
        || die "Failed to update budget. Ensure it was created via --setup first."

    info "Budget updated: ${budget_name} -> \$${BUDGET_AMOUNT}/month"
}

# ── Status ──────────────────────────────────────────────────────────────────

show_status() {
    info "=========================================="
    info "Billing Status"
    info "=========================================="
    info ""

    info "── Active Budgets ──"
    ${AWS_CMD} budgets describe-budgets \
        --account-id "${MASTER_ACCOUNT_ID}" \
        --output json 2>/dev/null \
        | python3 -c "
import sys, json
data = json.load(sys.stdin)
for b in data.get('Budgets', []):
    name = b['BudgetName']
    limit = b['BudgetLimit']['Amount']
    actual = b.get('CalculatedSpend', {}).get('ActualSpend', {}).get('Amount', 'N/A')
    forecast = b.get('CalculatedSpend', {}).get('ForecastedSpend', {}).get('Amount', 'N/A')
    actual_str = f'\${float(actual):.2f}' if actual != 'N/A' else 'N/A'
    forecast_str = f'\${float(forecast):.2f}' if forecast != 'N/A' else 'N/A'
    print(f'  {name}: Limit=\${limit} | Actual={actual_str} | Forecast={forecast_str}')
" 2>/dev/null || warn "  Could not retrieve budgets."

    info ""
    info "── Recent Cost Anomalies ──"
    local today
    today=$(date '+%Y-%m-%d')
    local thirty_days_ago
    thirty_days_ago=$(date -d "30 days ago" '+%Y-%m-%d' 2>/dev/null \
        || date -v-30d '+%Y-%m-%d' 2>/dev/null \
        || echo "${today}")

    ${AWS_CMD} ce get-anomalies \
        --date-interval "{\"StartDate\":\"${thirty_days_ago}\",\"EndDate\":\"${today}\"}" \
        --output json 2>/dev/null \
        | python3 -c "
import sys, json
data = json.load(sys.stdin)
anomalies = data.get('Anomalies', [])
if not anomalies:
    print('  No anomalies in the last 30 days.')
else:
    for a in anomalies[:10]:
        svc = a.get('DimensionValue', 'Unknown')
        impact = a.get('Impact', {}).get('TotalImpact', 'N/A')
        status = a.get('AnomalyScore', {}).get('CurrentScore', 'N/A')
        start = a.get('AnomalyStartDate', 'Unknown')
        print(f'  {start} | Service: {svc} | Impact: \${impact} | Score: {status}')
" 2>/dev/null || warn "  Could not retrieve anomalies."
}

# ── Main ────────────────────────────────────────────────────────────────────

main() {
    case "${ACTION}" in
        setup)      setup_billing ;;
        report)     generate_cost_report ;;
        set-budget) set_account_budget ;;
        status)     show_status ;;
        *)          die "Unknown action: ${ACTION}" ;;
    esac
}

main

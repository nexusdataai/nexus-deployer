#!/bin/bash
#
# Setup CloudWatch Metric Filters, Alarms, and Dashboard
#
# Creates alerting on error patterns in application logs and a monitoring dashboard.
# Requires: Fluent Bit or watchtower shipping logs to CloudWatch.
#
# Usage:
#   ./setup-cloudwatch-alerts.sh setup       # Create filters, alarms, dashboard
#   ./setup-cloudwatch-alerts.sh verify      # Check alarm status
#   ./setup-cloudwatch-alerts.sh teardown    # Remove all alerting resources
#
# Reads: .env.local (ENV, Cluster)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

_ENVLOCAL="${SCRIPT_DIR}/.env.local"
if [ -f "$_ENVLOCAL" ]; then
    _ENV=$(grep '^ENV[[:space:]]*=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true)
fi

DEPLOY_ENV="${DEPLOY_ENV:-${_ENV:-prod}}"
AWS_PROFILE="${AWS_PROFILE:-external-access}"
REGION="${REGION:-us-east-1}"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --profile "${AWS_PROFILE}" 2>/dev/null || echo "")
if [ -z "$ACCOUNT_ID" ]; then
    echo "Failed to get AWS account ID. Check credentials."
    exit 1
fi

LOG_GROUP="/nexus/nexus-ai/${DEPLOY_ENV}"
NAMESPACE_PREFIX="CallSense-${DEPLOY_ENV}"
DASHBOARD_NAME="CallSense-${DEPLOY_ENV}-Monitoring"
SNS_TOPIC_NAME="callsense-${DEPLOY_ENV}-alerts"
SNS_TOPIC_ARN="arn:aws:sns:${REGION}:${ACCOUNT_ID}:${SNS_TOPIC_NAME}"

show_help() {
    echo "Usage: $0 {setup|verify|teardown} [--email EMAIL]"
    echo ""
    echo "Commands:"
    echo "  setup      Create metric filters, alarms, SNS topic, and dashboard"
    echo "  verify     Show alarm states and recent alarm history"
    echo "  teardown   Remove all alerting resources"
    echo ""
    echo "Options:"
    echo "  --email EMAIL   Subscribe this email to the alert SNS topic"
}

# Capture the subcommand first (positional $1), then shift it off so the flag
# loop below scans only the remaining args. Previously `shift 2` inside the
# loop also dropped $1 (the subcommand), causing the email address to land in
# $1 and the case statement at the bottom to fall through to show_help.
CMD="${1:-}"
[ $# -gt 0 ] && shift

ALERT_EMAIL=""
while [ $# -gt 0 ]; do
    case "$1" in
        --email) ALERT_EMAIL="${2:-}"; shift 2 ;;
        *) shift ;;
    esac
done

do_setup() {
    echo "================================================"
    echo "  Setting up CloudWatch Alerting"
    echo "================================================"
    echo ""
    echo "Environment: ${DEPLOY_ENV}"
    echo "Log Group:   ${LOG_GROUP}"
    echo "Dashboard:   ${DASHBOARD_NAME}"
    echo ""

    # SNS Topic
    echo "Creating SNS topic for alerts..."
    aws sns create-topic --name "${SNS_TOPIC_NAME}" \
        --region "${REGION}" --profile "${AWS_PROFILE}" \
        --output text --query 'TopicArn' 2>/dev/null || true

    if [ -n "$ALERT_EMAIL" ]; then
        echo "Subscribing ${ALERT_EMAIL}..."
        aws sns subscribe --topic-arn "${SNS_TOPIC_ARN}" \
            --protocol email --notification-endpoint "${ALERT_EMAIL}" \
            --region "${REGION}" --profile "${AWS_PROFILE}" 2>/dev/null || true
        echo "Check email for confirmation link."
    fi

    # Metric Filters
    echo ""
    echo "Creating metric filters..."

    aws logs put-metric-filter \
        --log-group-name "${LOG_GROUP}" \
        --filter-name "${NAMESPACE_PREFIX}-BackendErrors" \
        --filter-pattern "ERROR" \
        --metric-transformations \
            metricName="BackendErrorCount",metricNamespace="${NAMESPACE_PREFIX}",metricValue="1",defaultValue=0 \
        --region "${REGION}" --profile "${AWS_PROFILE}" 2>/dev/null || true

    aws logs put-metric-filter \
        --log-group-name "${LOG_GROUP}" \
        --filter-name "${NAMESPACE_PREFIX}-CriticalErrors" \
        --filter-pattern "CRITICAL" \
        --metric-transformations \
            metricName="CriticalErrorCount",metricNamespace="${NAMESPACE_PREFIX}",metricValue="1",defaultValue=0 \
        --region "${REGION}" --profile "${AWS_PROFILE}" 2>/dev/null || true

    aws logs put-metric-filter \
        --log-group-name "${LOG_GROUP}" \
        --filter-name "${NAMESPACE_PREFIX}-Nginx5xx" \
        --filter-pattern '"\" 5"' \
        --metric-transformations \
            metricName="Nginx5xxCount",metricNamespace="${NAMESPACE_PREFIX}",metricValue="1",defaultValue=0 \
        --region "${REGION}" --profile "${AWS_PROFILE}" 2>/dev/null || true

    aws logs put-metric-filter \
        --log-group-name "${LOG_GROUP}" \
        --filter-name "${NAMESPACE_PREFIX}-AccessDenied" \
        --filter-pattern "AccessDenied" \
        --metric-transformations \
            metricName="AccessDeniedCount",metricNamespace="${NAMESPACE_PREFIX}",metricValue="1",defaultValue=0 \
        --region "${REGION}" --profile "${AWS_PROFILE}" 2>/dev/null || true

    echo "Created 4 metric filters."

    # Alarms
    echo ""
    echo "Creating alarms..."

    aws cloudwatch put-metric-alarm \
        --alarm-name "${NAMESPACE_PREFIX}-HighErrorRate" \
        --alarm-description "Backend ERROR count exceeds 50 in 5 minutes" \
        --namespace "${NAMESPACE_PREFIX}" \
        --metric-name "BackendErrorCount" \
        --statistic Sum \
        --period 300 \
        --evaluation-periods 1 \
        --threshold 50 \
        --comparison-operator GreaterThanThreshold \
        --alarm-actions "${SNS_TOPIC_ARN}" \
        --ok-actions "${SNS_TOPIC_ARN}" \
        --treat-missing-data notBreaching \
        --region "${REGION}" --profile "${AWS_PROFILE}" 2>/dev/null || true

    aws cloudwatch put-metric-alarm \
        --alarm-name "${NAMESPACE_PREFIX}-CriticalAlert" \
        --alarm-description "Any CRITICAL error detected" \
        --namespace "${NAMESPACE_PREFIX}" \
        --metric-name "CriticalErrorCount" \
        --statistic Sum \
        --period 60 \
        --evaluation-periods 1 \
        --threshold 0 \
        --comparison-operator GreaterThanThreshold \
        --alarm-actions "${SNS_TOPIC_ARN}" \
        --treat-missing-data notBreaching \
        --region "${REGION}" --profile "${AWS_PROFILE}" 2>/dev/null || true

    aws cloudwatch put-metric-alarm \
        --alarm-name "${NAMESPACE_PREFIX}-Nginx5xxSpike" \
        --alarm-description "Nginx 5xx errors exceed 10 in 5 minutes" \
        --namespace "${NAMESPACE_PREFIX}" \
        --metric-name "Nginx5xxCount" \
        --statistic Sum \
        --period 300 \
        --evaluation-periods 1 \
        --threshold 10 \
        --comparison-operator GreaterThanThreshold \
        --alarm-actions "${SNS_TOPIC_ARN}" \
        --ok-actions "${SNS_TOPIC_ARN}" \
        --treat-missing-data notBreaching \
        --region "${REGION}" --profile "${AWS_PROFILE}" 2>/dev/null || true

    echo "Created 3 alarms."

    # Dashboard
    echo ""
    echo "Creating dashboard..."

    DASHBOARD_BODY=$(cat <<DBEOF
{
  "widgets": [
    {
      "type": "metric",
      "x": 0, "y": 0, "width": 12, "height": 6,
      "properties": {
        "title": "Error Rates",
        "metrics": [
          ["${NAMESPACE_PREFIX}", "BackendErrorCount", {"stat": "Sum", "period": 300, "label": "Backend Errors"}],
          ["${NAMESPACE_PREFIX}", "Nginx5xxCount", {"stat": "Sum", "period": 300, "label": "Nginx 5xx"}],
          ["${NAMESPACE_PREFIX}", "CriticalErrorCount", {"stat": "Sum", "period": 300, "label": "Critical"}],
          ["${NAMESPACE_PREFIX}", "AccessDeniedCount", {"stat": "Sum", "period": 300, "label": "Access Denied"}]
        ],
        "region": "${REGION}",
        "view": "timeSeries",
        "stacked": false,
        "period": 300
      }
    },
    {
      "type": "log",
      "x": 12, "y": 0, "width": 12, "height": 6,
      "properties": {
        "title": "Recent Errors",
        "query": "SOURCE '${LOG_GROUP}' | fields @timestamp, @message | filter @message like /ERROR|CRITICAL/ | sort @timestamp desc | limit 50",
        "region": "${REGION}",
        "view": "table"
      }
    },
    {
      "type": "metric",
      "x": 0, "y": 6, "width": 8, "height": 6,
      "properties": {
        "title": "Alarm Status",
        "metrics": [
          [{"expression": "METRICS('m1')", "label": "", "id": "e1"}],
          ["${NAMESPACE_PREFIX}", "BackendErrorCount", {"stat": "Sum", "period": 60, "id": "m1", "visible": false}]
        ],
        "region": "${REGION}",
        "view": "timeSeries",
        "period": 60
      }
    },
    {
      "type": "log",
      "x": 8, "y": 6, "width": 16, "height": 6,
      "properties": {
        "title": "Nginx 5xx Requests",
        "query": "SOURCE '${LOG_GROUP}' | fields @timestamp, @message | filter @message like /\\\" 5[0-9][0-9] / | sort @timestamp desc | limit 30",
        "region": "${REGION}",
        "view": "table"
      }
    }
  ]
}
DBEOF
)

    aws cloudwatch put-dashboard \
        --dashboard-name "${DASHBOARD_NAME}" \
        --dashboard-body "${DASHBOARD_BODY}" \
        --region "${REGION}" --profile "${AWS_PROFILE}" 2>/dev/null || true

    echo ""
    echo "================================================"
    echo "  CloudWatch Alerting Setup Complete"
    echo "================================================"
    echo ""
    echo "SNS Topic:  ${SNS_TOPIC_ARN}"
    echo "Dashboard:  https://${REGION}.console.aws.amazon.com/cloudwatch/home?region=${REGION}#dashboards:name=${DASHBOARD_NAME}"
    echo ""
    echo "Alarms:"
    echo "  ${NAMESPACE_PREFIX}-HighErrorRate     (>50 errors in 5min)"
    echo "  ${NAMESPACE_PREFIX}-CriticalAlert     (any CRITICAL)"
    echo "  ${NAMESPACE_PREFIX}-Nginx5xxSpike     (>10 5xx in 5min)"
    echo ""
    echo "Metric Filters:"
    echo "  BackendErrorCount, CriticalErrorCount, Nginx5xxCount, AccessDeniedCount"
    if [ -z "$ALERT_EMAIL" ]; then
        echo ""
        echo "To subscribe an email: $0 setup --email your@email.com"
    fi
}

do_verify() {
    echo "CloudWatch Alarms:"
    echo ""
    aws cloudwatch describe-alarms \
        --alarm-name-prefix "${NAMESPACE_PREFIX}" \
        --region "${REGION}" --profile "${AWS_PROFILE}" \
        --query 'MetricAlarms[].{Name:AlarmName,State:StateValue,Reason:StateReason}' \
        --output table 2>/dev/null || echo "No alarms found."
    echo ""

    echo "Metric Filters:"
    aws logs describe-metric-filters \
        --log-group-name "${LOG_GROUP}" \
        --region "${REGION}" --profile "${AWS_PROFILE}" \
        --query 'metricFilters[].{Name:filterName,Pattern:filterPattern}' \
        --output table 2>/dev/null || echo "No filters found (log group may not exist yet)."
    echo ""

    echo "Dashboard: https://${REGION}.console.aws.amazon.com/cloudwatch/home?region=${REGION}#dashboards:name=${DASHBOARD_NAME}"
}

do_teardown() {
    echo "Removing CloudWatch alerting resources..."

    aws cloudwatch delete-alarms \
        --alarm-names "${NAMESPACE_PREFIX}-HighErrorRate" "${NAMESPACE_PREFIX}-CriticalAlert" "${NAMESPACE_PREFIX}-Nginx5xxSpike" \
        --region "${REGION}" --profile "${AWS_PROFILE}" 2>/dev/null || true
    echo "Deleted alarms."

    for f in BackendErrors CriticalErrors Nginx5xx AccessDenied; do
        aws logs delete-metric-filter \
            --log-group-name "${LOG_GROUP}" \
            --filter-name "${NAMESPACE_PREFIX}-${f}" \
            --region "${REGION}" --profile "${AWS_PROFILE}" 2>/dev/null || true
    done
    echo "Deleted metric filters."

    aws cloudwatch delete-dashboards \
        --dashboard-names "${DASHBOARD_NAME}" \
        --region "${REGION}" --profile "${AWS_PROFILE}" 2>/dev/null || true
    echo "Deleted dashboard."

    echo "SNS topic '${SNS_TOPIC_NAME}' preserved (may have other subscriptions)."
    echo "Done."
}

case "$CMD" in
    setup)    do_setup ;;
    verify)   do_verify ;;
    teardown) do_teardown ;;
    -h|--help|help) show_help ;;
    *) show_help; exit 1 ;;
esac

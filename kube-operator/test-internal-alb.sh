#!/bin/bash
#
# Internal ALB Verification Script
# Tests the internal (VPC-only) ALB from inside the EKS cluster via kubectl exec.
# Reads cluster defaults from .env.local.
#
# Usage:
#   ./test-internal-alb.sh              # Run all tests
#   ./test-internal-alb.sh --help       # Show help
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

_ENVLOCAL="${SCRIPT_DIR}/.env.local"
if [ -f "$_ENVLOCAL" ]; then
    _ENV_LOCAL_ENV=$(grep '^ENV=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2-)
    _ENV_LOCAL_CLUSTER=$(grep '^Cluster=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2-)
fi

DEPLOY_ENV="${DEPLOY_ENV:-${_ENV_LOCAL_ENV:-prod}}"
CLUSTER_NAME="${CLUSTER_NAME:-${_ENV_LOCAL_CLUSTER:-starhub-test}}"
REGION="${REGION:-ap-southeast-1}"
AWS_PROFILE="${AWS_PROFILE:-external-access}"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

check()  { if [ "$2" = "true" ]; then echo -e "  ${GREEN}✓${NC} $1"; echo -e "      $3"; PASS=$((PASS+1)); else echo -e "  ${RED}✗${NC} $1"; echo -e "      $3"; FAIL=$((FAIL+1)); fi; }
warn_()  { echo -e "  ${YELLOW}!${NC} $1"; echo -e "      $2"; WARN=$((WARN+1)); }
info_()  { echo -e "  ${CYAN}→${NC} $1"; }

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    echo "Internal ALB Verification Script"
    echo ""
    echo "Tests the internal (VPC-only) ALB by running curl from inside the EKS cluster."
    echo "Verifies DNS resolution, HTTP endpoints, path routing, and ALB configuration."
    echo ""
    echo "Usage: $0"
    echo ""
    echo "Environment variables (or set in .env.local):"
    echo "  DEPLOY_ENV     Target environment (default: from .env.local or prod)"
    echo "  CLUSTER_NAME   EKS cluster name (default: from .env.local or starhub-test)"
    exit 0
fi

NAMESPACE="call-processing-${DEPLOY_ENV}"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Internal ALB Verification - ${CLUSTER_NAME}"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "  Cluster:     ${CLUSTER_NAME}"
echo "  Namespace:   ${NAMESPACE}"
echo "  Environment: ${DEPLOY_ENV}"
echo ""

aws eks update-kubeconfig --name "${CLUSTER_NAME}" --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1

# ── Step 1: Find internal ingress ──
echo -e "${CYAN}── Step 1: Ingress Resource ──${NC}"

INTERNAL_INGRESS_NAME="${NAMESPACE}-internal-ingress"
INTERNAL_HOST=$(kubectl get ingress "${INTERNAL_INGRESS_NAME}" -n "${NAMESPACE}" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
INTERNAL_SCHEME=$(kubectl get ingress "${INTERNAL_INGRESS_NAME}" -n "${NAMESPACE}" -o jsonpath='{.metadata.annotations.alb\.ingress\.kubernetes\.io/scheme}' 2>/dev/null || echo "")

if [ -n "$INTERNAL_HOST" ]; then
    check "Ingress ${INTERNAL_INGRESS_NAME}" "true" "Host: ${INTERNAL_HOST}"
else
    check "Ingress ${INTERNAL_INGRESS_NAME}" "false" "NOT FOUND or no address assigned"
    echo ""
    echo -e "  ${RED}Cannot proceed without internal ingress. Ensure internalIngress.enabled=true in the capability spec.${NC}"
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo -e "  Passed: ${GREEN}${PASS}${NC}  Failed: ${RED}${FAIL}${NC}  Warnings: ${YELLOW}${WARN}${NC}"
    echo "═══════════════════════════════════════════════════════════"
    exit 1
fi

if [ "$INTERNAL_SCHEME" = "internal" ]; then
    check "ALB scheme annotation" "true" "scheme: internal"
else
    check "ALB scheme annotation" "false" "Expected 'internal', got '${INTERNAL_SCHEME}'"
fi

# ── Step 2: AWS ALB configuration ──
echo ""
echo -e "${CYAN}── Step 2: AWS ALB Configuration ──${NC}"

ALB_NAME=$(kubectl get ingress "${INTERNAL_INGRESS_NAME}" -n "${NAMESPACE}" -o jsonpath='{.metadata.annotations.alb\.ingress\.kubernetes\.io/load-balancer-name}' 2>/dev/null || echo "")
info_ "ALB name: ${ALB_NAME}"

ALB_INFO=$(aws elbv2 describe-load-balancers --names "${ALB_NAME}" --region "${REGION}" --profile "${AWS_PROFILE}" --output json 2>/dev/null || echo "{}")
ALB_SCHEME=$(echo "$ALB_INFO" | python3 -c "import sys,json; lb=json.load(sys.stdin).get('LoadBalancers',[]); print(lb[0]['Scheme'] if lb else 'NotFound')" 2>/dev/null)
ALB_VPC=$(echo "$ALB_INFO" | python3 -c "import sys,json; lb=json.load(sys.stdin).get('LoadBalancers',[]); print(lb[0]['VpcId'] if lb else 'NotFound')" 2>/dev/null)
ALB_STATE=$(echo "$ALB_INFO" | python3 -c "import sys,json; lb=json.load(sys.stdin).get('LoadBalancers',[]); print(lb[0].get('State',{}).get('Code','unknown') if lb else 'NotFound')" 2>/dev/null)

if [ "$ALB_SCHEME" = "internal" ]; then
    check "ALB scheme (AWS)" "true" "Scheme: internal"
else
    check "ALB scheme (AWS)" "false" "Expected 'internal', got '${ALB_SCHEME}'"
fi

if [ "$ALB_STATE" = "active" ]; then
    check "ALB state" "true" "State: active"
else
    check "ALB state" "false" "State: ${ALB_STATE}"
fi

EKS_VPC=$(aws eks describe-cluster --name "${CLUSTER_NAME}" --region "${REGION}" --profile "${AWS_PROFILE}" --query 'cluster.resourcesVpcConfig.vpcId' --output text 2>/dev/null || echo "")
if [ "$ALB_VPC" = "$EKS_VPC" ]; then
    check "ALB in EKS VPC" "true" "VPC: ${ALB_VPC}"
else
    check "ALB in EKS VPC" "false" "ALB VPC: ${ALB_VPC}, EKS VPC: ${EKS_VPC}"
fi

# ── Step 3: DNS resolution from inside cluster ──
echo ""
echo -e "${CYAN}── Step 3: DNS Resolution (from pod) ──${NC}"

TEST_POD=$(kubectl get pods -n "${NAMESPACE}" -l "app=${NAMESPACE}-backend" --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [ -z "$TEST_POD" ]; then
    TEST_POD=$(kubectl get pods -n "${NAMESPACE}" --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
fi

if [ -z "$TEST_POD" ]; then
    check "Find running pod for tests" "false" "No running pods in ${NAMESPACE}"
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo -e "  Passed: ${GREEN}${PASS}${NC}  Failed: ${RED}${FAIL}${NC}  Warnings: ${YELLOW}${WARN}${NC}"
    echo "═══════════════════════════════════════════════════════════"
    exit 1
fi

info_ "Using pod: ${TEST_POD}"

DNS_RESULT=$(kubectl exec "${TEST_POD}" -n "${NAMESPACE}" -- sh -c "getent hosts ${INTERNAL_HOST} 2>/dev/null | head -1" 2>/dev/null || echo "")
if [ -n "$DNS_RESULT" ]; then
    RESOLVED_IP=$(echo "$DNS_RESULT" | awk '{print $1}')
    if echo "$RESOLVED_IP" | grep -qE '^10\.|^172\.(1[6-9]|2[0-9]|3[01])\.|^192\.168\.'; then
        check "DNS resolves to private IP" "true" "${RESOLVED_IP} (private)"
    else
        warn_ "DNS resolves to non-private IP" "${RESOLVED_IP} — may not be truly internal"
    fi
else
    check "DNS resolution" "false" "Could not resolve ${INTERNAL_HOST}"
fi

# ── Step 4: HTTP endpoint tests ──
echo ""
echo -e "${CYAN}── Step 4: HTTP Endpoint Tests (from pod) ──${NC}"

run_curl() {
    local PATH_="$1"
    local LABEL="$2"
    local RESULT
    RESULT=$(kubectl exec "${TEST_POD}" -n "${NAMESPACE}" -- curl -s -o /dev/null -w '%{http_code}' "http://${INTERNAL_HOST}${PATH_}" --connect-timeout 5 2>/dev/null || echo "000")
    if [ "$RESULT" = "200" ]; then
        check "${LABEL}" "true" "HTTP ${RESULT}"
    elif [ "$RESULT" = "000" ]; then
        check "${LABEL}" "false" "Connection failed (timeout/unreachable)"
    else
        warn_ "${LABEL}" "HTTP ${RESULT} (expected 200)"
    fi
}

run_curl "/" "Frontend (GET /)"
run_curl "/api/v1/auth/health" "Backend auth health (GET /api/v1/auth/health)"
run_curl "/health" "Backend health (GET /health)"

# ── Step 5: Target group health ──
echo ""
echo -e "${CYAN}── Step 5: ALB Target Group Health ──${NC}"

ALB_ARN=$(echo "$ALB_INFO" | python3 -c "import sys,json; lb=json.load(sys.stdin).get('LoadBalancers',[]); print(lb[0]['LoadBalancerArn'] if lb else '')" 2>/dev/null)

if [ -n "$ALB_ARN" ]; then
    TG_ARNS=$(aws elbv2 describe-target-groups --load-balancer-arn "${ALB_ARN}" --region "${REGION}" --profile "${AWS_PROFILE}" --query 'TargetGroups[*].TargetGroupArn' --output text 2>/dev/null || echo "")

    for TG_ARN in $TG_ARNS; do
        TG_NAME=$(echo "$TG_ARN" | grep -o 'targetgroup/[^/]*' | cut -d/ -f2)
        HEALTHY=$(aws elbv2 describe-target-health --target-group-arn "$TG_ARN" --region "${REGION}" --profile "${AWS_PROFILE}" --query 'TargetHealthDescriptions[?TargetHealth.State==`healthy`] | length(@)' --output text 2>/dev/null || echo "0")
        TOTAL=$(aws elbv2 describe-target-health --target-group-arn "$TG_ARN" --region "${REGION}" --profile "${AWS_PROFILE}" --query 'TargetHealthDescriptions | length(@)' --output text 2>/dev/null || echo "0")

        if [ "$HEALTHY" = "$TOTAL" ] && [ "$TOTAL" != "0" ]; then
            check "Target group: ${TG_NAME}" "true" "${HEALTHY}/${TOTAL} targets healthy"
        elif [ "$HEALTHY" != "0" ]; then
            warn_ "Target group: ${TG_NAME}" "${HEALTHY}/${TOTAL} targets healthy (some unhealthy)"
        else
            check "Target group: ${TG_NAME}" "false" "0/${TOTAL} targets healthy"
        fi
    done
else
    check "ALB target groups" "false" "Could not find ALB ARN"
fi

# ── Step 6: Compare with public ALB ──
echo ""
echo -e "${CYAN}── Step 6: Public vs Internal ALB Comparison ──${NC}"

PUBLIC_HOST=$(kubectl get ingress "${NAMESPACE}-app-ingress" -n "${NAMESPACE}" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
if [ -n "$PUBLIC_HOST" ]; then
    info_ "Public ALB:   ${PUBLIC_HOST}"
    info_ "Internal ALB: ${INTERNAL_HOST}"

    PUB_CODE=$(kubectl exec "${TEST_POD}" -n "${NAMESPACE}" -- curl -s -o /dev/null -w '%{http_code}' "http://${PUBLIC_HOST}/" --connect-timeout 5 2>/dev/null || echo "000")
    INT_CODE=$(kubectl exec "${TEST_POD}" -n "${NAMESPACE}" -- curl -s -o /dev/null -w '%{http_code}' "http://${INTERNAL_HOST}/" --connect-timeout 5 2>/dev/null || echo "000")

    if [ "$PUB_CODE" = "200" ] && [ "$INT_CODE" = "200" ]; then
        check "Both ALBs return HTTP 200" "true" "Public: ${PUB_CODE}, Internal: ${INT_CODE}"
    else
        warn_ "ALB response mismatch" "Public: ${PUB_CODE}, Internal: ${INT_CODE}"
    fi
else
    warn_ "Public ALB not found" "Cannot compare"
fi

# ── Summary ──
echo ""
echo "═══════════════════════════════════════════════════════════"
echo -e "  Passed: ${GREEN}${PASS}${NC}  Failed: ${RED}${FAIL}${NC}  Warnings: ${YELLOW}${WARN}${NC}"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "  Internal ALB URL:"
echo -e "    ${CYAN}http://${INTERNAL_HOST}${NC}"
echo ""
echo "  This URL is only accessible from within VPC ${ALB_VPC}"
echo ""

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi

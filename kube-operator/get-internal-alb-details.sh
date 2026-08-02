#!/bin/bash
#
# Internal ALB Details
# Shows listeners, rules, target groups, target health, and security config
# for the internal (VPC-only) ALB.
#
# Usage:
#   ./get-internal-alb-details.sh                # Uses .env.local defaults
#   ./get-internal-alb-details.sh --env stage    # Specific environment
#   DEPLOY_ENV=stage ./get-internal-alb-details.sh
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SCRIPT_DIR}/lib/init-kube-env.sh"

_ENVLOCAL="${SCRIPT_DIR}/.env.local"
if [ -f "$_ENVLOCAL" ]; then
    _ENV_LOCAL_ENV=$(grep '^ENV=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2-)
fi

DEPLOY_ENV="${DEPLOY_ENV:-${_ENV_LOCAL_ENV:-prod}}"
REGION="${REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-external-access}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --env)     DEPLOY_ENV="$2"; shift 2 ;;
        --region)  REGION="$2"; shift 2 ;;
        --profile) AWS_PROFILE="$2"; shift 2 ;;
        --help|-h)
            echo "Internal ALB Details"
            echo ""
            echo "Usage: $0 [--env ENV] [--region REGION] [--profile PROFILE]"
            echo ""
            echo "Options:"
            echo "  --env ENV        Target environment (default: from .env.local or prod)"
            echo "  --region REGION  AWS region (default: us-east-1)"
            echo "  --profile PROF   AWS CLI profile (default: external-access)"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

CYAN='\033[0;36m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

ALB_NAME="nexus-ai-${DEPLOY_ENV}-internal"
NAMESPACE="nexus-ai-${DEPLOY_ENV}"

AWS="aws --region ${REGION} --profile ${AWS_PROFILE}"

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  Internal ALB Details: ${ALB_NAME}${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo "  Environment: ${DEPLOY_ENV}"
echo "  Region:      ${REGION}"
echo "  Profile:     ${AWS_PROFILE}"
echo ""

# ── Load Balancer ──
echo -e "${CYAN}── Load Balancer ──${NC}"
echo ""

ALB_JSON=$($AWS elbv2 describe-load-balancers --names "${ALB_NAME}" --output json 2>/dev/null || echo '{"LoadBalancers":[]}')
ALB_COUNT=$(echo "$ALB_JSON" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('LoadBalancers',[])))" 2>/dev/null)

if [ "$ALB_COUNT" = "0" ]; then
    echo -e "  ${RED}ALB '${ALB_NAME}' not found in ${REGION}${NC}"
    echo ""
    echo "  Check the Ingress resource:"
    echo "    kubectl get ingress -n ${NAMESPACE}"
    exit 1
fi

ALB_ARN=$(echo "$ALB_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['LoadBalancers'][0]['LoadBalancerArn'])" 2>/dev/null)
ALB_DNS=$(echo "$ALB_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['LoadBalancers'][0].get('DNSName',''))" 2>/dev/null)
ALB_SCHEME=$(echo "$ALB_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['LoadBalancers'][0]['Scheme'])" 2>/dev/null)
ALB_STATE=$(echo "$ALB_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['LoadBalancers'][0].get('State',{}).get('Code','unknown'))" 2>/dev/null)
ALB_VPC=$(echo "$ALB_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['LoadBalancers'][0].get('VpcId',''))" 2>/dev/null)
ALB_TYPE=$(echo "$ALB_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['LoadBalancers'][0].get('Type',''))" 2>/dev/null)
ALB_SGs=$(echo "$ALB_JSON" | python3 -c "import sys,json; print(', '.join(json.load(sys.stdin)['LoadBalancers'][0].get('SecurityGroups',[])))" 2>/dev/null)
ALB_AZs=$(echo "$ALB_JSON" | python3 -c "import sys,json; azs=json.load(sys.stdin)['LoadBalancers'][0].get('AvailabilityZones',[]); print(', '.join(f\"{a['ZoneName']} ({a['SubnetId']})\" for a in azs))" 2>/dev/null)

printf "  %-22s %s\n" "Name:" "${ALB_NAME}"
printf "  %-22s %s\n" "DNS:" "${ALB_DNS}"
printf "  %-22s %s\n" "Scheme:" "${ALB_SCHEME}"
printf "  %-22s %s\n" "State:" "${ALB_STATE}"
printf "  %-22s %s\n" "Type:" "${ALB_TYPE}"
printf "  %-22s %s\n" "VPC:" "${ALB_VPC}"
printf "  %-22s %s\n" "Security Groups:" "${ALB_SGs}"
printf "  %-22s %s\n" "Availability Zones:" "${ALB_AZs}"
printf "  %-22s %s\n" "ARN:" "${ALB_ARN}"

# ── Listeners ──
echo ""
echo -e "${CYAN}── Listeners ──${NC}"
echo ""

LISTENERS_JSON=$($AWS elbv2 describe-listeners --load-balancer-arn "${ALB_ARN}" --output json 2>/dev/null)
LISTENER_COUNT=$(echo "$LISTENERS_JSON" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('Listeners',[])))" 2>/dev/null)

echo "  Total listeners: ${LISTENER_COUNT}"
echo ""

echo "$LISTENERS_JSON" | python3 -c "
import sys, json
listeners = json.load(sys.stdin).get('Listeners', [])
for l in sorted(listeners, key=lambda x: x['Port']):
    port = l['Port']
    proto = l['Protocol']
    ssl = l.get('SslPolicy', '-')
    certs = l.get('Certificates', [])
    cert = certs[0]['CertificateArn'].split('/')[-1] if certs else '-'
    actions = l.get('DefaultActions', [])
    action_type = actions[0]['Type'] if actions else '-'
    print(f'  {proto}:{port}  ssl_policy={ssl}  cert={cert}  default_action={action_type}')
" 2>/dev/null

HAS_HTTP=$(echo "$LISTENERS_JSON" | python3 -c "
import sys, json
listeners = json.load(sys.stdin).get('Listeners', [])
print('yes' if any(l['Protocol'] == 'HTTP' for l in listeners) else 'no')
" 2>/dev/null)

echo ""
if [ "$HAS_HTTP" = "no" ]; then
    echo -e "  ${GREEN}No HTTP listener — HTTPS-only configuration confirmed${NC}"
else
    echo -e "  ${YELLOW}HTTP listener present — expected HTTPS-only for internal ALB${NC}"
fi

# ── Listener Rules ──
echo ""
echo -e "${CYAN}── Listener Rules ──${NC}"
echo ""

echo "$LISTENERS_JSON" | python3 -c "
import sys, json
listeners = json.load(sys.stdin).get('Listeners', [])
for l in sorted(listeners, key=lambda x: x['Port']):
    print(f\"  Listener {l['Protocol']}:{l['Port']}  ({l['ListenerArn'].split('/')[-1]})\")
" 2>/dev/null

LISTENER_ARNS=$(echo "$LISTENERS_JSON" | python3 -c "
import sys, json
for l in json.load(sys.stdin).get('Listeners', []):
    print(l['ListenerArn'])
" 2>/dev/null)

for LARN in $LISTENER_ARNS; do
    L_PORT=$(echo "$LISTENERS_JSON" | python3 -c "
import sys, json
for l in json.load(sys.stdin).get('Listeners', []):
    if l['ListenerArn'] == '${LARN}':
        print(f\"{l['Protocol']}:{l['Port']}\")
" 2>/dev/null)
    echo ""
    echo "  Rules for ${L_PORT}:"

    RULES_JSON=$($AWS elbv2 describe-rules --listener-arn "${LARN}" --output json 2>/dev/null)
    echo "$RULES_JSON" | python3 -c "
import sys, json
rules = json.load(sys.stdin).get('Rules', [])
for r in rules:
    pri = r.get('Priority', '-')
    conds = r.get('Conditions', [])
    acts = r.get('Actions', [])
    path = '-'
    for c in conds:
        vals = c.get('Values', [])
        field = c.get('Field', '')
        if vals:
            path = f'{field}={vals[0]}'
    tg = '-'
    atype = '-'
    for a in acts:
        atype = a.get('Type', '-')
        arn = a.get('TargetGroupArn', '')
        if arn:
            tg = arn.split('/')[-2] if '/' in arn else arn
    print(f'    Priority {pri:>5s}  {path:<30s}  action={atype:<12s}  target={tg}')
" 2>/dev/null
done

# ── Target Groups ──
echo ""
echo -e "${CYAN}── Target Groups ──${NC}"
echo ""

TG_JSON=$($AWS elbv2 describe-target-groups --load-balancer-arn "${ALB_ARN}" --output json 2>/dev/null)

echo "$TG_JSON" | python3 -c "
import sys, json
tgs = json.load(sys.stdin).get('TargetGroups', [])
print(f'  Total target groups: {len(tgs)}')
print()
fmt = '  {:<45s} {:>5s}  {:<8s} {:<7s}  {:<15s}'
print(fmt.format('NAME', 'PORT', 'PROTO', 'TYPE', 'HEALTH CHECK'))
print(fmt.format('-' * 45, '-----', '--------', '-------', '-' * 15))
for t in tgs:
    name = t.get('TargetGroupName', '')
    port = str(t.get('Port', '-'))
    proto = t.get('Protocol', '-')
    ttype = t.get('TargetType', '-')
    hpath = t.get('HealthCheckPath', '-')
    hproto = t.get('HealthCheckProtocol', '-')
    print(fmt.format(name, port, proto, ttype, f'{hproto} {hpath}'))
" 2>/dev/null

# ── Target Health ──
echo ""
echo -e "${CYAN}── Target Health ──${NC}"

TG_ARNS=$(echo "$TG_JSON" | python3 -c "
import sys, json
for t in json.load(sys.stdin).get('TargetGroups', []):
    print(t['TargetGroupArn'])
" 2>/dev/null)

for TG_ARN in $TG_ARNS; do
    TG_NAME=$(echo "$TG_ARN" | grep -o 'targetgroup/[^/]*' | cut -d/ -f2)
    echo ""
    echo "  Target Group: ${TG_NAME}"

    TH_JSON=$($AWS elbv2 describe-target-health --target-group-arn "${TG_ARN}" --output json 2>/dev/null)
    TOTAL=$(echo "$TH_JSON" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('TargetHealthDescriptions',[])))" 2>/dev/null)

    if [ "$TOTAL" = "0" ]; then
        echo -e "    ${YELLOW}No registered targets${NC}"
        continue
    fi

    echo "$TH_JSON" | python3 -c "
import sys, json
targets = json.load(sys.stdin).get('TargetHealthDescriptions', [])
healthy = sum(1 for t in targets if t.get('TargetHealth',{}).get('State') == 'healthy')
total = len(targets)
for t in targets:
    ip = t.get('Target',{}).get('Id','?')
    port = t.get('Target',{}).get('Port','?')
    state = t.get('TargetHealth',{}).get('State','?')
    reason = t.get('TargetHealth',{}).get('Reason','')
    marker = '${GREEN}' if state == 'healthy' else '${RED}'
    suffix = f'  ({reason})' if reason and state != 'healthy' else ''
    print(f'    {marker}{ip}:{port}  {state}{suffix}${NC}')
print(f'    --- {healthy}/{total} healthy')
" 2>/dev/null
done

# ── Ingress Annotations ──
echo ""
echo -e "${CYAN}── Kubernetes Ingress Annotations ──${NC}"
echo ""

INGRESS_NAME="${NAMESPACE}-internal-ingress"
ANNOTATIONS=$(kubectl get ingress "${INGRESS_NAME}" -n "${NAMESPACE}" -o json 2>/dev/null | python3 -c "
import sys, json
ann = json.load(sys.stdin).get('metadata',{}).get('annotations',{})
for k, v in sorted(ann.items()):
    if 'alb.ingress' in k or 'kubernetes.io/ingress' in k:
        short = k.replace('alb.ingress.kubernetes.io/', '')
        print(f'  {short:<30s} {v}')
" 2>/dev/null || echo "  (ingress not found)")

echo "$ANNOTATIONS"

# ── Summary ──
echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo "  Internal ALB URL:"
echo -e "    ${GREEN}https://${ALB_DNS}${NC}"
echo ""
echo "  Accessible only from within VPC ${ALB_VPC}"
echo ""

#!/bin/bash
#
# Enable/Disable HTTPS on ALB Ingresses
# Patches running ingresses with ACM certificate, updates Cognito callback URLs,
# updates SSM redirect-uri, and verifies the setup.
# Reads defaults from .env.local.
#
# Usage:
#   ./enable-https.sh                                    # Uses CertificateArn from .env.local
#   ./enable-https.sh --cert arn:aws:acm:REGION:ACCT:certificate/UUID
#   ./enable-https.sh --disable                          # Revert to HTTP-only
#   ./enable-https.sh --help
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

_ENVLOCAL="${SCRIPT_DIR}/.env.local"
if [ -f "$_ENVLOCAL" ]; then
    _ENV_LOCAL_ENV=$(grep '^ENV=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2-)
    _ENV_LOCAL_CLUSTER=$(grep '^Cluster=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2-)
    _ENV_LOCAL_CERT=$(grep '^CertificateArn=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2-)
fi

DEPLOY_ENV="${DEPLOY_ENV:-${_ENV_LOCAL_ENV:-prod}}"
CLUSTER_NAME="${CLUSTER_NAME:-${_ENV_LOCAL_CLUSTER:-starhub-test}}"
REGION="${REGION:-ap-southeast-1}"
AWS_PROFILE="${AWS_PROFILE:-external-access}"
CERTIFICATE_ARN="${CERTIFICATE_ARN:-${_ENV_LOCAL_CERT:-}}"
DISABLE_HTTPS=false

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
log_fail() { echo -e "  ${RED}✗${NC} $1"; }
log_warn() { echo -e "  ${YELLOW}!${NC} $1"; }
log_info() { echo -e "  ${CYAN}→${NC} $1"; }

while [[ $# -gt 0 ]]; do
    case $1 in
        --cert|--certificate)
            CERTIFICATE_ARN="$2"; shift 2 ;;
        --disable)
            DISABLE_HTTPS=true; shift ;;
        --env)
            DEPLOY_ENV="$2"; shift 2 ;;
        --cluster)
            CLUSTER_NAME="$2"; shift 2 ;;
        --help|-h)
            echo "Enable/Disable HTTPS on ALB Ingresses"
            echo ""
            echo "Usage:"
            echo "  $0                          # Enable HTTPS using CertificateArn from .env.local"
            echo "  $0 --cert <ACM_ARN>         # Enable HTTPS with specified certificate"
            echo "  $0 --disable                # Revert to HTTP-only"
            echo ""
            echo "Options:"
            echo "  --cert ARN       ACM certificate ARN"
            echo "  --disable        Remove HTTPS, revert to HTTP-only"
            echo "  --env ENV        Target environment (default: from .env.local)"
            echo "  --cluster NAME   EKS cluster name (default: from .env.local)"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

NAMESPACE="call-processing-${DEPLOY_ENV}"
CAPABILITY_NAME="call-processing"

echo ""
echo "═══════════════════════════════════════════════════════════"
if [ "$DISABLE_HTTPS" = true ]; then
    echo "  Disable HTTPS - ${CLUSTER_NAME}"
else
    echo "  Enable HTTPS - ${CLUSTER_NAME}"
fi
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "  Cluster:     ${CLUSTER_NAME}"
echo "  Namespace:   ${NAMESPACE}"
echo "  Environment: ${DEPLOY_ENV}"
if [ "$DISABLE_HTTPS" = false ]; then
    echo "  Certificate: ${CERTIFICATE_ARN:-NOT SET}"
fi
echo ""

aws eks update-kubeconfig --name "${CLUSTER_NAME}" --region "${REGION}" --profile "${AWS_PROFILE}" > /dev/null 2>&1
log_ok "kubectl connected"

# ── Disable mode ──
if [ "$DISABLE_HTTPS" = true ]; then
    echo ""
    echo -e "${CYAN}── Reverting to HTTP-only ──${NC}"

    for INGRESS_NAME in "${NAMESPACE}-app-ingress" "${NAMESPACE}-internal-ingress"; do
        if kubectl get ingress "$INGRESS_NAME" -n "$NAMESPACE" > /dev/null 2>&1; then
            kubectl annotate ingress "$INGRESS_NAME" -n "$NAMESPACE" \
                "alb.ingress.kubernetes.io/certificate-arn-" \
                "alb.ingress.kubernetes.io/ssl-redirect-" \
                --overwrite 2>/dev/null || true
            kubectl annotate ingress "$INGRESS_NAME" -n "$NAMESPACE" \
                'alb.ingress.kubernetes.io/listen-ports=[{"HTTP": 80}]' \
                --overwrite 2>/dev/null || true
            log_ok "Reverted $INGRESS_NAME to HTTP-only"
        fi
    done

    echo ""
    log_info "Waiting 30s for ALB controller to reconcile..."
    sleep 30

    ALB_HOST=$(kubectl get ingress "${NAMESPACE}-app-ingress" -n "${NAMESPACE}" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
    if [ -n "$ALB_HOST" ]; then
        log_ok "Application URL: http://${ALB_HOST}"
    fi
    echo ""
    log_ok "HTTPS disabled. HTTP-only mode active."
    exit 0
fi

# ── Enable mode ──
if [ -z "$CERTIFICATE_ARN" ]; then
    log_fail "No certificate ARN provided."
    echo "  Set CertificateArn in .env.local or pass --cert <ARN>"
    exit 1
fi

# Step 1: Validate certificate
echo -e "${CYAN}── Step 1: Validate ACM Certificate ──${NC}"

CERT_STATUS=$(aws acm describe-certificate --certificate-arn "$CERTIFICATE_ARN" \
    --region "$REGION" --profile "$AWS_PROFILE" \
    --query 'Certificate.Status' --output text 2>/dev/null || echo "NOT_FOUND")

if [ "$CERT_STATUS" = "ISSUED" ]; then
    CERT_DOMAIN=$(aws acm describe-certificate --certificate-arn "$CERTIFICATE_ARN" \
        --region "$REGION" --profile "$AWS_PROFILE" \
        --query 'Certificate.DomainName' --output text 2>/dev/null || echo "")
    log_ok "Certificate valid: ${CERT_STATUS} (domain: ${CERT_DOMAIN})"
    if [ -n "$CERT_DOMAIN" ] && [[ "$CERT_DOMAIN" != \** ]]; then
        CANONICAL_HOST="$CERT_DOMAIN"
    fi
elif [ "$CERT_STATUS" = "NOT_FOUND" ]; then
    log_fail "Certificate not found: ${CERTIFICATE_ARN}"
    echo "  Verify the ARN and region (${REGION})"
    exit 1
else
    log_warn "Certificate status: ${CERT_STATUS} (expected ISSUED)"
    echo "  HTTPS may not work until the certificate is fully issued."
fi

# Step 2: Patch ingress annotations
echo ""
echo -e "${CYAN}── Step 2: Patch Ingress Annotations ──${NC}"

patch_ingress() {
    local INGRESS_NAME="$1"
    local LABEL="$2"

    if ! kubectl get ingress "$INGRESS_NAME" -n "$NAMESPACE" > /dev/null 2>&1; then
        log_info "$LABEL ingress not found — skipping"
        return
    fi

    kubectl annotate ingress "$INGRESS_NAME" -n "$NAMESPACE" \
        "alb.ingress.kubernetes.io/certificate-arn=${CERTIFICATE_ARN}" \
        'alb.ingress.kubernetes.io/listen-ports=[{"HTTP": 80}, {"HTTPS": 443}]' \
        "alb.ingress.kubernetes.io/ssl-redirect=443" \
        --overwrite 2>/dev/null
    log_ok "Patched $LABEL ingress: $INGRESS_NAME"
}

patch_ingress "${NAMESPACE}-app-ingress" "Public"
patch_ingress "${NAMESPACE}-internal-ingress" "Internal"

# Step 3: Wait for ALB controller to reconcile
echo ""
echo -e "${CYAN}── Step 3: Wait for ALB Listener Update ──${NC}"
log_info "Waiting 30s for ALB controller to add HTTPS listener..."
sleep 30
log_ok "Reconciliation period complete"

# Step 4: Update Cognito callback URLs
echo ""
echo -e "${CYAN}── Step 4: Update Cognito Callback URLs ──${NC}"

SSM_PREFIX="/${CAPABILITY_NAME}/${DEPLOY_ENV}"
COGNITO_POOL_ID=$(aws ssm get-parameter --name "${SSM_PREFIX}/cognito/user-pool-id" \
    --query "Parameter.Value" --output text \
    --region "$REGION" --profile "$AWS_PROFILE" 2>/dev/null || echo "")
COGNITO_CLIENT_ID=$(aws ssm get-parameter --name "${SSM_PREFIX}/cognito/app-client-id" \
    --query "Parameter.Value" --output text \
    --region "$REGION" --profile "$AWS_PROFILE" 2>/dev/null || echo "")

if [ -n "$COGNITO_POOL_ID" ] && [ -n "$COGNITO_CLIENT_ID" ]; then
    ALB_HOST=$(kubectl get ingress "${NAMESPACE}-app-ingress" -n "${NAMESPACE}" \
        -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")

    if [ -n "$ALB_HOST" ]; then
        COGNITO_DOMAIN="${CANONICAL_HOST:-$ALB_HOST}"

        CURRENT_CALLBACKS=$(aws cognito-idp describe-user-pool-client \
            --user-pool-id "$COGNITO_POOL_ID" --client-id "$COGNITO_CLIENT_ID" \
            --region "$REGION" --profile "$AWS_PROFILE" \
            --query 'UserPoolClient.CallbackURLs' --output json 2>/dev/null || echo "[]")

        UPDATED_CALLBACKS=$(echo "$CURRENT_CALLBACKS" | python3 -c "
import sys, json
urls = json.load(sys.stdin)
updated = set(urls)
updated.add('https://${COGNITO_DOMAIN}/auth/callback')
updated.add('https://${ALB_HOST}/auth/callback')
for u in list(updated):
    if 'localhost' not in u and u.startswith('http://'):
        updated.add(u.replace('http://', 'https://', 1))
print(json.dumps(sorted(updated)))
" 2>/dev/null)

        CURRENT_LOGOUTS=$(aws cognito-idp describe-user-pool-client \
            --user-pool-id "$COGNITO_POOL_ID" --client-id "$COGNITO_CLIENT_ID" \
            --region "$REGION" --profile "$AWS_PROFILE" \
            --query 'UserPoolClient.LogoutURLs' --output json 2>/dev/null || echo "[]")

        UPDATED_LOGOUTS=$(echo "$CURRENT_LOGOUTS" | python3 -c "
import sys, json
urls = json.load(sys.stdin)
updated = set(urls)
updated.add('https://${COGNITO_DOMAIN}')
updated.add('https://${COGNITO_DOMAIN}/login')
updated.add('https://${ALB_HOST}')
updated.add('https://${ALB_HOST}/login')
for u in list(updated):
    if 'localhost' not in u and u.startswith('http://'):
        updated.add(u.replace('http://', 'https://', 1))
print(json.dumps(sorted(updated)))
" 2>/dev/null)

        OAUTH_FLOWS=$(aws cognito-idp describe-user-pool-client \
            --user-pool-id "$COGNITO_POOL_ID" --client-id "$COGNITO_CLIENT_ID" \
            --region "$REGION" --profile "$AWS_PROFILE" \
            --query 'UserPoolClient.AllowedOAuthFlows' --output json 2>/dev/null || echo '["code"]')

        OAUTH_SCOPES=$(aws cognito-idp describe-user-pool-client \
            --user-pool-id "$COGNITO_POOL_ID" --client-id "$COGNITO_CLIENT_ID" \
            --region "$REGION" --profile "$AWS_PROFILE" \
            --query 'UserPoolClient.AllowedOAuthScopes' --output json 2>/dev/null || echo '["openid","email","profile"]')

        AUTH_FLOWS=$(aws cognito-idp describe-user-pool-client \
            --user-pool-id "$COGNITO_POOL_ID" --client-id "$COGNITO_CLIENT_ID" \
            --region "$REGION" --profile "$AWS_PROFILE" \
            --query 'UserPoolClient.ExplicitAuthFlows' --output json 2>/dev/null || echo '["ALLOW_USER_SRP_AUTH","ALLOW_REFRESH_TOKEN_AUTH","ALLOW_ADMIN_USER_PASSWORD_AUTH"]')

        aws cognito-idp update-user-pool-client \
            --user-pool-id "$COGNITO_POOL_ID" \
            --client-id "$COGNITO_CLIENT_ID" \
            --explicit-auth-flows "$AUTH_FLOWS" \
            --callback-urls "$UPDATED_CALLBACKS" \
            --logout-urls "$UPDATED_LOGOUTS" \
            --supported-identity-providers "COGNITO" \
            --allowed-o-auth-flows "$OAUTH_FLOWS" \
            --allowed-o-auth-scopes "$OAUTH_SCOPES" \
            --allowed-o-auth-flows-user-pool-client \
            --region "$REGION" --profile "$AWS_PROFILE" > /dev/null 2>&1

        log_ok "Cognito callback URLs updated with https://${COGNITO_DOMAIN}"
    else
        log_warn "Could not determine ALB host — skipping Cognito update"
    fi
else
    log_warn "Cognito pool/client not found in SSM — skipping"
fi

# Step 5: Update SSM redirect-uri
echo ""
echo -e "${CYAN}── Step 5: Update SSM Redirect URI ──${NC}"

if [ -n "$ALB_HOST" ]; then
    SSM_DOMAIN="${CANONICAL_HOST:-$ALB_HOST}"
    HTTPS_REDIRECT="https://${SSM_DOMAIN}/auth/callback"
    aws ssm put-parameter \
        --name "${SSM_PREFIX}/cognito/redirect-uri" \
        --value "$HTTPS_REDIRECT" \
        --type String --overwrite \
        --region "$REGION" --profile "$AWS_PROFILE" > /dev/null 2>&1
    log_ok "SSM redirect-uri updated: ${HTTPS_REDIRECT}"
else
    log_warn "ALB host not available — skipping SSM update"
fi

# Step 6: Restart backend pods to pick up new SSM
echo ""
echo -e "${CYAN}── Step 6: Restart Backend Pods ──${NC}"
kubectl rollout restart deployment "${NAMESPACE}-backend" -n "$NAMESPACE" 2>/dev/null || true
log_info "Waiting for backend rollout..."
kubectl rollout status deployment "${NAMESPACE}-backend" -n "$NAMESPACE" --timeout=120s 2>/dev/null || true
log_ok "Backend pods restarted"

# Step 7: Verify
echo ""
echo -e "${CYAN}── Step 7: Verify HTTPS ──${NC}"

PASS=0
FAIL=0

if [ -n "$ALB_HOST" ]; then
    HTTPS_CODE=$(curl -sk -o /dev/null -w '%{http_code}' "https://${ALB_HOST}/" --connect-timeout 10 2>/dev/null || echo "000")
    if [ "$HTTPS_CODE" = "200" ]; then
        log_ok "HTTPS GET https://${ALB_HOST}/ -> HTTP ${HTTPS_CODE}"
        PASS=$((PASS+1))
    else
        log_fail "HTTPS GET https://${ALB_HOST}/ -> HTTP ${HTTPS_CODE}"
        FAIL=$((FAIL+1))
    fi

    REDIRECT_CODE=$(curl -s -o /dev/null -w '%{http_code}' "http://${ALB_HOST}/" --connect-timeout 10 2>/dev/null || echo "000")
    if [ "$REDIRECT_CODE" = "301" ] || [ "$REDIRECT_CODE" = "302" ] || [ "$REDIRECT_CODE" = "307" ]; then
        log_ok "HTTP->HTTPS redirect: HTTP ${REDIRECT_CODE}"
        PASS=$((PASS+1))
    else
        log_warn "HTTP redirect check: HTTP ${REDIRECT_CODE} (expected 301/302/307)"
    fi

    HTTPS_API=$(curl -sk -o /dev/null -w '%{http_code}' "https://${ALB_HOST}/api/v1/auth/health" --connect-timeout 10 2>/dev/null || echo "000")
    if [ "$HTTPS_API" = "200" ]; then
        log_ok "HTTPS API health: HTTP ${HTTPS_API}"
        PASS=$((PASS+1))
    else
        log_fail "HTTPS API health: HTTP ${HTTPS_API}"
        FAIL=$((FAIL+1))
    fi
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo -e "  Passed: ${GREEN}${PASS}${NC}  Failed: ${RED}${FAIL}${NC}"
echo "═══════════════════════════════════════════════════════════"
echo ""
if [ -n "$ALB_HOST" ]; then
    echo -e "  ${GREEN}Public URL:${NC}   ${CYAN}https://${ALB_HOST}${NC}"
fi

INTERNAL_HOST=$(kubectl get ingress "${NAMESPACE}-internal-ingress" -n "${NAMESPACE}" \
    -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
if [ -n "$INTERNAL_HOST" ]; then
    echo -e "  ${GREEN}Internal URL:${NC} ${CYAN}https://${INTERNAL_HOST}${NC}  (VPC-only)"
fi
echo ""

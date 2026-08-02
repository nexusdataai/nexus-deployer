#!/bin/bash
#
# Setup Admin User
# Sets the admin password permanently (bypasses FORCE_CHANGE_PASSWORD)
# and verifies login works end-to-end.
# Reads defaults from .env.local.
#
# Usage:
#   ./setup-admin.sh                                  # Uses defaults from .env.local
#   ./setup-admin.sh --email admin@nexus.ai --password MyPass123!
#   ./setup-admin.sh --verify-only                    # Only verify login, don't set password
#   ./setup-admin.sh --help
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SCRIPT_DIR}/lib/init-kube-env.sh"

_ENVLOCAL="${SCRIPT_DIR}/.env.local"
if [ -f "$_ENVLOCAL" ]; then
    _ENV_LOCAL_ENV=$(grep '^ENV=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- || true)
    _ENV_LOCAL_CLUSTER=$(grep '^Cluster=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- || true)
fi

DEPLOY_ENV="${DEPLOY_ENV:-${_ENV_LOCAL_ENV:-prod}}"
CLUSTER_NAME="${CLUSTER_NAME:-${_ENV_LOCAL_CLUSTER:-nexus-test}}"
REGION="${REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-external-access}"

ADMIN_EMAIL=""
ADMIN_PASSWORD=""
VERIFY_ONLY=false

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

while [[ $# -gt 0 ]]; do
    case $1 in
        --email)        ADMIN_EMAIL="$2"; shift 2 ;;
        --password)     ADMIN_PASSWORD="$2"; shift 2 ;;
        --env)          DEPLOY_ENV="$2"; shift 2 ;;
        --verify-only)  VERIFY_ONLY=true; shift ;;
        --help|-h)
            echo "Setup Admin User"
            echo ""
            echo "Sets the admin password and verifies login."
            echo "Run this after e2e-deploy.sh to activate the admin account."
            echo ""
            echo "Usage:"
            echo "  $0                                    # Interactive (prompts for password)"
            echo "  $0 --email admin@nexus.ai --password Pass123!"
            echo "  $0 --verify-only                      # Only verify existing login"
            echo ""
            echo "Options:"
            echo "  --email EMAIL       Admin email (default: from K8s secret)"
            echo "  --password PASS     Admin password to set"
            echo "  --env ENV           Target environment"
            echo "  --verify-only       Only verify login, don't change password"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

NAMESPACE="nexus-ai-${DEPLOY_ENV}"
CAP="nexus-ai"
SSM_PREFIX="/${CAP}/${DEPLOY_ENV}"

echo ""
echo "================================================================"
echo "  Admin User Setup"
echo "================================================================"
echo ""
echo "  Environment: ${DEPLOY_ENV}"
echo "  Namespace:   ${NAMESPACE}"
echo "  Region:      ${REGION}"
echo ""

# Get Cognito config from SSM
POOL_ID=$(aws ssm get-parameter --name "${SSM_PREFIX}/cognito/user-pool-id" --region "$REGION" --profile "$AWS_PROFILE" --query 'Parameter.Value' --output text 2>/dev/null || echo "")
CLIENT_ID=$(aws ssm get-parameter --name "${SSM_PREFIX}/cognito/app-client-id" --region "$REGION" --profile "$AWS_PROFILE" --query 'Parameter.Value' --output text 2>/dev/null || echo "")

if [ -z "$POOL_ID" ] || [ -z "$CLIENT_ID" ]; then
    echo -e "  ${RED}Cognito not configured. Run e2e-deploy.sh first.${NC}"
    exit 1
fi

echo -e "  ${CYAN}Cognito Pool:${NC}  ${POOL_ID}"
echo -e "  ${CYAN}Cognito Client:${NC} ${CLIENT_ID}"

# Get admin credentials from K8s secret if not provided
if [ -z "$ADMIN_EMAIL" ]; then
    nexus_eks_update_kubeconfig "${CLUSTER_NAME}" "${REGION}" "${AWS_PROFILE}" >/dev/null 2>&1
    ADMIN_EMAIL=$(kubectl get secret "${NAMESPACE}-admin-credentials" -n "${NAMESPACE}" -o jsonpath='{.data.admin-email}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
    if [ -z "$ADMIN_EMAIL" ]; then
        echo -e "  ${YELLOW}Could not read admin email from K8s secret.${NC}"
        read -rp "  Enter admin email: " ADMIN_EMAIL
    fi
fi

echo -e "  ${CYAN}Admin Email:${NC}   ${ADMIN_EMAIL}"
echo ""

if [ "$VERIFY_ONLY" = false ]; then
    # Get password
    if [ -z "$ADMIN_PASSWORD" ]; then
        ADMIN_PASSWORD=$(kubectl get secret "${NAMESPACE}-admin-credentials" -n "${NAMESPACE}" -o jsonpath='{.data.admin-password}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
        if [ -z "$ADMIN_PASSWORD" ]; then
            read -rsp "  Enter admin password: " ADMIN_PASSWORD
            echo ""
        fi
    fi

    # Check current user status
    echo -e "${CYAN}── Step 1: Check User Status ──${NC}"
    USER_STATUS=$(aws cognito-idp admin-get-user --user-pool-id "$POOL_ID" --username "$ADMIN_EMAIL" --region "$REGION" --profile "$AWS_PROFILE" --query 'UserStatus' --output text 2>/dev/null || echo "NOT_FOUND")

    if [ "$USER_STATUS" = "NOT_FOUND" ]; then
        echo -e "  ${RED}User ${ADMIN_EMAIL} not found in Cognito pool.${NC}"
        exit 1
    fi

    echo -e "  ${CYAN}Current status:${NC} ${USER_STATUS}"

    if [ "$USER_STATUS" = "FORCE_CHANGE_PASSWORD" ]; then
        echo -e "  ${YELLOW}User requires password change — setting permanent password...${NC}"
    else
        echo -e "  ${GREEN}User is already ${USER_STATUS}${NC}"
    fi

    # Set permanent password
    echo ""
    echo -e "${CYAN}── Step 2: Set Permanent Password ──${NC}"
    if aws cognito-idp admin-set-user-password \
        --user-pool-id "$POOL_ID" \
        --username "$ADMIN_EMAIL" \
        --password "$ADMIN_PASSWORD" \
        --permanent \
        --region "$REGION" --profile "$AWS_PROFILE" 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} Password set permanently"
    else
        echo -e "  ${RED}✗${NC} Failed to set password"
        echo "    Ensure password meets policy: 8+ chars, uppercase, lowercase, number, special char"
        exit 1
    fi

    # Verify status changed
    NEW_STATUS=$(aws cognito-idp admin-get-user --user-pool-id "$POOL_ID" --username "$ADMIN_EMAIL" --region "$REGION" --profile "$AWS_PROFILE" --query 'UserStatus' --output text 2>/dev/null)
    echo -e "  ${CYAN}New status:${NC} ${NEW_STATUS}"

    # Ensure auth flows are enabled
    echo ""
    echo -e "${CYAN}── Step 3: Verify Auth Flows ──${NC}"
    AUTH_FLOWS=$(aws cognito-idp describe-user-pool-client --user-pool-id "$POOL_ID" --client-id "$CLIENT_ID" --region "$REGION" --profile "$AWS_PROFILE" --query 'UserPoolClient.ExplicitAuthFlows' --output json 2>/dev/null || echo "null")

    if echo "$AUTH_FLOWS" | grep -q "ALLOW_ADMIN_USER_PASSWORD_AUTH"; then
        echo -e "  ${GREEN}✓${NC} ADMIN_USER_PASSWORD_AUTH is enabled"
    else
        echo -e "  ${YELLOW}!${NC} ADMIN_USER_PASSWORD_AUTH missing — enabling..."
        CALLBACK_URLS=$(aws cognito-idp describe-user-pool-client --user-pool-id "$POOL_ID" --client-id "$CLIENT_ID" --region "$REGION" --profile "$AWS_PROFILE" --query 'UserPoolClient.CallbackURLs' --output json 2>/dev/null)
        LOGOUT_URLS=$(aws cognito-idp describe-user-pool-client --user-pool-id "$POOL_ID" --client-id "$CLIENT_ID" --region "$REGION" --profile "$AWS_PROFILE" --query 'UserPoolClient.LogoutURLs' --output json 2>/dev/null)
        OAUTH_FLOWS=$(aws cognito-idp describe-user-pool-client --user-pool-id "$POOL_ID" --client-id "$CLIENT_ID" --region "$REGION" --profile "$AWS_PROFILE" --query 'UserPoolClient.AllowedOAuthFlows' --output json 2>/dev/null)
        OAUTH_SCOPES=$(aws cognito-idp describe-user-pool-client --user-pool-id "$POOL_ID" --client-id "$CLIENT_ID" --region "$REGION" --profile "$AWS_PROFILE" --query 'UserPoolClient.AllowedOAuthScopes' --output json 2>/dev/null)

        aws cognito-idp update-user-pool-client \
            --user-pool-id "$POOL_ID" \
            --client-id "$CLIENT_ID" \
            --explicit-auth-flows "ALLOW_USER_SRP_AUTH" "ALLOW_REFRESH_TOKEN_AUTH" "ALLOW_ADMIN_USER_PASSWORD_AUTH" \
            --callback-urls "$CALLBACK_URLS" \
            --logout-urls "$LOGOUT_URLS" \
            --supported-identity-providers "COGNITO" \
            --allowed-o-auth-flows "$OAUTH_FLOWS" \
            --allowed-o-auth-scopes "$OAUTH_SCOPES" \
            --allowed-o-auth-flows-user-pool-client \
            --region "$REGION" --profile "$AWS_PROFILE" > /dev/null 2>&1
        echo -e "  ${GREEN}✓${NC} Auth flows enabled"
    fi
fi

# Verify login
echo ""
echo -e "${CYAN}── Step 4: Verify Login ──${NC}"

if [ -z "$ADMIN_PASSWORD" ]; then
    ADMIN_PASSWORD=$(kubectl get secret "${NAMESPACE}-admin-credentials" -n "${NAMESPACE}" -o jsonpath='{.data.admin-password}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
    if [ -z "$ADMIN_PASSWORD" ]; then
        read -rsp "  Enter password to verify: " ADMIN_PASSWORD
        echo ""
    fi
fi

# Test Cognito auth directly
LOGIN_RESULT=$(aws cognito-idp admin-initiate-auth \
    --user-pool-id "$POOL_ID" \
    --client-id "$CLIENT_ID" \
    --auth-flow ADMIN_USER_PASSWORD_AUTH \
    --auth-parameters "USERNAME=${ADMIN_EMAIL},PASSWORD=${ADMIN_PASSWORD}" \
    --region "$REGION" --profile "$AWS_PROFILE" \
    --query 'AuthenticationResult.AccessToken' --output text 2>/dev/null || echo "FAILED")

if [ "$LOGIN_RESULT" != "FAILED" ] && [ -n "$LOGIN_RESULT" ]; then
    echo -e "  ${GREEN}✓${NC} Cognito direct auth: SUCCESS"
else
    echo -e "  ${RED}✗${NC} Cognito direct auth: FAILED"
    echo "    Check email/password and try again."
    exit 1
fi

# Test via ALB endpoint
ALB_HOST=$(kubectl get ingress "${NAMESPACE}-app-ingress" -n "${NAMESPACE}" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
ALB_CERT=$(kubectl get ingress "${NAMESPACE}-app-ingress" -n "${NAMESPACE}" -o jsonpath='{.metadata.annotations.alb\.ingress\.kubernetes\.io/certificate-arn}' 2>/dev/null || echo "")
SCHEME="http"
[ -n "$ALB_CERT" ] && SCHEME="https"

if [ -n "$ALB_HOST" ]; then
    CURL_FLAGS="-s"
    [ "$SCHEME" = "https" ] && CURL_FLAGS="-sk"

    # Test health
    HEALTH=$(curl $CURL_FLAGS "${SCHEME}://${ALB_HOST}/api/v1/auth/health" 2>/dev/null || echo "")
    if echo "$HEALTH" | grep -q "healthy"; then
        echo -e "  ${GREEN}✓${NC} Auth health endpoint: healthy"
    else
        echo -e "  ${RED}✗${NC} Auth health endpoint: not responding"
    fi

    # Test login via ALB
    LOGIN_RESP=$(curl $CURL_FLAGS -X POST "${SCHEME}://${ALB_HOST}/api/v1/auth/login" \
        -H "Content-Type: application/json" \
        -d "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\"}" 2>/dev/null || echo "")

    if echo "$LOGIN_RESP" | grep -q "access_token"; then
        echo -e "  ${GREEN}✓${NC} ALB login endpoint: SUCCESS"
        ROLE=$(echo "$LOGIN_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('user',{}).get('role','unknown'))" 2>/dev/null || echo "unknown")
        echo -e "      Role: ${ROLE}"
    else
        echo -e "  ${RED}✗${NC} ALB login endpoint: FAILED"
        echo "      Response: $(echo "$LOGIN_RESP" | head -c 100)"
    fi
else
    echo -e "  ${YELLOW}!${NC} ALB not available — skipping endpoint test"
fi

# Summary
echo ""
echo "================================================================"
echo -e "  ${GREEN}Admin Setup Complete${NC}"
echo "================================================================"
echo ""
echo -e "  Email:    ${CYAN}${ADMIN_EMAIL}${NC}"
if [ -n "$ALB_HOST" ]; then
    echo -e "  Login:    ${CYAN}${SCHEME}://${ALB_HOST}/login${NC}"
fi
echo ""

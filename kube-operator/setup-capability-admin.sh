#!/bin/bash
#
# Ensure default admin user exists for any capability (Cognito + K8s secret).
#
# Usage:
#   ./setup-capability-admin.sh --capability ontology --env dev
#   ./setup-capability-admin.sh --capability nexus-ai --env prod --verify-only
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SCRIPT_DIR}/lib/init-kube-env.sh"

CAPABILITY=""
DEPLOY_ENV=""
REGION="${REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-external-access}"
CLUSTER_NAME="${CLUSTER_NAME:-}"
ADMIN_EMAIL="admin@nexus.ai"
ADMIN_PASSWORD="Pass123!"
VERIFY_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --capability) CAPABILITY="$2"; shift 2 ;;
        --env)        DEPLOY_ENV="$2"; shift 2 ;;
        --cluster)    CLUSTER_NAME="$2"; shift 2 ;;
        --email)      ADMIN_EMAIL="$2"; shift 2 ;;
        --password)   ADMIN_PASSWORD="$2"; shift 2 ;;
        --verify-only) VERIFY_ONLY=true; shift ;;
        --help|-h)
            sed -n '2,12p' "$0"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

[ -n "$CAPABILITY" ] && [ -n "$DEPLOY_ENV" ] || {
    echo "Usage: $0 --capability NAME --env ENV [--email admin@nexus.ai] [--password Pass123!]"
    exit 1
}

case "$CAPABILITY" in
    nexus-ai)     NS="nexus-ai-${DEPLOY_ENV}" ;;
    ontology)     NS="ontology-${DEPLOY_ENV}" ;;
    ai-engine)
        case "$DEPLOY_ENV" in prod) NS="ai-engine" ;; *) NS="ai-engine-${DEPLOY_ENV}" ;; esac
        ;;
    nexus-sre|sre) NS="nexus-sre" ;;
    simulator)    NS="nexus-simulator" ;;
    *)            NS="${CAPABILITY}-${DEPLOY_ENV}" ;;
esac

SSM_PREFIX="/${CAPABILITY}/${DEPLOY_ENV}"
[ -f "${SCRIPT_DIR}/.env.local" ] && CLUSTER_NAME="${CLUSTER_NAME:-$(grep '^Cluster=' "${SCRIPT_DIR}/.env.local" | cut -d= -f2-)}"

echo ""
echo "Setup capability admin: ${CAPABILITY} (${DEPLOY_ENV})"
echo "  Namespace: ${NS}"
echo "  Email:     ${ADMIN_EMAIL}"
echo ""

if [ "$VERIFY_ONLY" = false ]; then
    nexus_eks_update_kubeconfig "${CLUSTER_NAME}" "${REGION}" "${AWS_PROFILE}" >/dev/null 2>&1 || true
    AWS_PROFILE="${AWS_PROFILE}" python3 "${SCRIPT_DIR}/scripts/provision_capability_admin.py" \
        --capability "${CAPABILITY}" \
        --env "${DEPLOY_ENV}" \
        --region "${REGION}" \
        --email "${ADMIN_EMAIL}" \
        --password "${ADMIN_PASSWORD}"
fi

POOL_ID=$(aws ssm get-parameter --name "${SSM_PREFIX}/cognito/user-pool-id" --region "$REGION" --profile "$AWS_PROFILE" --query 'Parameter.Value' --output text 2>/dev/null || echo "")
CLIENT_ID=$(aws ssm get-parameter --name "${SSM_PREFIX}/cognito/app-client-id" --region "$REGION" --profile "$AWS_PROFILE" --query 'Parameter.Value' --output text 2>/dev/null || echo "")

if [ -z "$POOL_ID" ] || [ -z "$CLIENT_ID" ]; then
    echo "ERROR: Cognito not configured in SSM (${SSM_PREFIX}/cognito/*)"
    exit 1
fi

LOGIN_RESULT=$(aws cognito-idp admin-initiate-auth \
    --user-pool-id "$POOL_ID" \
    --client-id "$CLIENT_ID" \
    --auth-flow ADMIN_USER_PASSWORD_AUTH \
    --auth-parameters "USERNAME=${ADMIN_EMAIL},PASSWORD=${ADMIN_PASSWORD}" \
    --region "$REGION" --profile "$AWS_PROFILE" \
    --query 'AuthenticationResult.AccessToken' --output text 2>/dev/null || echo "FAILED")

if [ "$LOGIN_RESULT" != "FAILED" ] && [ -n "$LOGIN_RESULT" ]; then
    echo "✓ Admin login verified (Cognito)"
else
    echo "✗ Admin login failed — check email/password and Cognito client auth flows"
    exit 1
fi

echo "✓ Admin ready: ${ADMIN_EMAIL}"

#!/bin/bash
#
# EKS Cluster Access Management Script
# Diagnoses and fixes kubectl access: auth mode, access entries, OIDC, and connectivity.
# Reads cluster defaults from .env.local.
#
# Usage:
#   ./cluster-access.sh check                          # Diagnose cluster access (read-only)
#   ./cluster-access.sh fix                            # Fix access: create access entry + verify OIDC
#   ./cluster-access.sh grant-github                   # Grant GitHub Actions roles access (both repos, env from .env.local)
#   ./cluster-access.sh grant-github --repo backend    # Grant only nexus-backend role
#   ./cluster-access.sh grant-github --env prod        # Grant roles for prod environment
#   ./cluster-access.sh --help                         # Show help
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

_ENVLOCAL="${SCRIPT_DIR}/.env.local"
if [ -f "$_ENVLOCAL" ]; then
    _ENV_LOCAL_CLUSTER=$(grep '^Cluster=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2-)
    _ENV_LOCAL_ENV=$(grep '^ENV=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2-)
fi

CLUSTER_NAME="${CLUSTER_NAME:-${_ENV_LOCAL_CLUSTER:-nexus-dev}}"
REGION="${REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-ptr-tech}"
ACCESS_POLICY_ARN="arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log_ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
log_fail() { echo -e "  ${RED}✗${NC} $1"; }
log_warn() { echo -e "  ${YELLOW}!${NC} $1"; }
log_info() { echo -e "  ${CYAN}→${NC} $1"; }

show_help() {
    cat << EOF
EKS Cluster Access Management
==============================

Commands:
  check                  Diagnose cluster access (auth mode, access entries, OIDC, kubectl)
  fix                    Fix access: create access entry + verify OIDC for your current role
  grant-github [opts]    Grant GitHub Actions IAM roles access to the cluster

grant-github options:
  --repo REPO    Target repo: backend, ui, or both (default: both)
  --env ENV      Target environment: dev, stage, prod (default: from .env.local ENV)

Examples:
  ./cluster-access.sh grant-github                    # Both repos, env from .env.local
  ./cluster-access.sh grant-github --repo backend     # Only nexus-backend
  ./cluster-access.sh grant-github --env prod         # Both repos, prod environment
  ./cluster-access.sh grant-github --repo ui --env stage

Environment variables (or set in .env.local):
  CLUSTER_NAME    EKS cluster name   (default: from .env.local or nexus-dev)
  REGION          AWS region         (default: us-east-1)
  AWS_PROFILE     AWS CLI profile    (default: ptr-tech)

EOF
}

# ── Helpers ──

get_account_id() {
    aws sts get-caller-identity --profile "$AWS_PROFILE" --query "Account" --output text 2>/dev/null
}

get_caller_arn() {
    aws sts get-caller-identity --profile "$AWS_PROFILE" --query "Arn" --output text 2>/dev/null
}

get_role_arn_from_caller() {
    local caller_arn="$1"
    if [[ "$caller_arn" == *"assumed-role"* ]]; then
        local account_id
        account_id=$(echo "$caller_arn" | grep -o '[0-9]\{12\}')
        local role_name
        role_name=$(echo "$caller_arn" | awk -F'/' '{print $2}')
        local full_arn
        full_arn=$(aws iam get-role --role-name "$role_name" --profile "$AWS_PROFILE" \
            --query 'Role.Arn' --output text 2>/dev/null || echo "")
        if [ -n "$full_arn" ] && [ "$full_arn" != "None" ]; then
            echo "$full_arn"
        else
            echo "arn:aws:iam::${account_id}:role/${role_name}"
        fi
    else
        echo "$caller_arn"
    fi
}

# ── Section: AWS Credentials ──

check_aws_credentials() {
    echo ""
    echo -e "${CYAN}── AWS Credentials ──${NC}"

    local CALLER_ARN
    CALLER_ARN=$(get_caller_arn 2>&1) || true

    if [ -z "$CALLER_ARN" ] || [[ "$CALLER_ARN" == *"ExpiredToken"* ]] || [[ "$CALLER_ARN" == *"error"* ]]; then
        log_fail "AWS credentials expired or invalid (profile: $AWS_PROFILE)"
        echo -e "      Run your AWS login script to refresh, e.g.:"
        echo -e "        ${BOLD}cd nexus-deployer/deploy && bash aws-login.sh${NC}"
        CREDS_OK=false
        return 1
    fi

    local ACCOUNT_ID
    ACCOUNT_ID=$(get_account_id)
    PRINCIPAL_ROLE_ARN=$(get_role_arn_from_caller "$CALLER_ARN")

    log_ok "Credentials valid (profile: $AWS_PROFILE)"
    log_info "Account:  $ACCOUNT_ID"
    log_info "Identity: $CALLER_ARN"
    log_info "Role ARN: $PRINCIPAL_ROLE_ARN"
    CREDS_OK=true
}

# ── Section: Cluster Info & Auth Mode ──

check_auth_mode() {
    echo ""
    echo -e "${CYAN}── Cluster Authentication Mode ──${NC}"

    local CLUSTER_JSON
    CLUSTER_JSON=$(aws eks describe-cluster --name "$CLUSTER_NAME" --region "$REGION" --profile "$AWS_PROFILE" --output json 2>&1) || {
        log_fail "Cannot describe cluster $CLUSTER_NAME"
        echo "      $CLUSTER_JSON"
        return 1
    }

    local STATUS
    STATUS=$(echo "$CLUSTER_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['cluster']['status'])")
    local VERSION
    VERSION=$(echo "$CLUSTER_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['cluster']['version'])")
    AUTH_MODE=$(echo "$CLUSTER_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['cluster'].get('accessConfig',{}).get('authenticationMode','CONFIG_MAP'))")

    log_ok "Cluster: $CLUSTER_NAME ($STATUS, v$VERSION)"

    case "$AUTH_MODE" in
        API)
            log_ok "Auth mode: API (EKS Access Entries only)"
            ;;
        API_AND_CONFIG_MAP)
            log_ok "Auth mode: API_AND_CONFIG_MAP (hybrid)"
            log_info "Access granted via EKS Access Entries OR aws-auth ConfigMap"
            ;;
        CONFIG_MAP)
            log_warn "Auth mode: CONFIG_MAP (legacy aws-auth only)"
            log_info "Access granted only via aws-auth ConfigMap in kube-system"
            ;;
    esac
}

# ── Section: EKS Access Entries ──

check_access_entries() {
    echo ""
    echo -e "${CYAN}── EKS Access Entries ──${NC}"

    if [ "$AUTH_MODE" = "CONFIG_MAP" ]; then
        log_warn "Skipped — cluster uses CONFIG_MAP auth only (access entries not applicable)"
        HAS_ACCESS_ENTRY=false
        return
    fi

    local ENTRIES_JSON
    ENTRIES_JSON=$(aws eks list-access-entries --cluster-name "$CLUSTER_NAME" --region "$REGION" --profile "$AWS_PROFILE" --output json 2>&1)
    local ENTRIES
    ENTRIES=$(echo "$ENTRIES_JSON" | python3 -c "import sys,json; [print(e) for e in json.load(sys.stdin).get('accessEntries',[])]")

    log_info "All access entries:"
    if [ -z "$ENTRIES" ]; then
        echo "      (none)"
    else
        while IFS= read -r entry; do
            local short="${entry##*/}"
            if [ "$entry" = "$PRINCIPAL_ROLE_ARN" ]; then
                echo -e "      ${GREEN}→ $short (YOUR ROLE)${NC}"
            else
                echo "      - $short"
            fi
        done <<< "$ENTRIES"
    fi

    echo ""
    log_info "Checking your role: ${PRINCIPAL_ROLE_ARN##*/}"

    local ENTRY_DETAIL
    ENTRY_DETAIL=$(aws eks describe-access-entry \
        --cluster-name "$CLUSTER_NAME" \
        --region "$REGION" \
        --profile "$AWS_PROFILE" \
        --principal-arn "$PRINCIPAL_ROLE_ARN" \
        --output json 2>&1) || true

    if echo "$ENTRY_DETAIL" | grep -q "ResourceNotFoundException"; then
        log_fail "No access entry for your role"
        HAS_ACCESS_ENTRY=false
        return
    fi

    local ENTRY_TYPE
    ENTRY_TYPE=$(echo "$ENTRY_DETAIL" | python3 -c "import sys,json; print(json.load(sys.stdin)['accessEntry']['type'])" 2>/dev/null || echo "unknown")
    log_ok "Access entry exists (type: $ENTRY_TYPE)"

    local POLICIES_JSON
    POLICIES_JSON=$(aws eks list-associated-access-policies \
        --cluster-name "$CLUSTER_NAME" \
        --region "$REGION" \
        --profile "$AWS_PROFILE" \
        --principal-arn "$PRINCIPAL_ROLE_ARN" \
        --output json 2>&1)

    local POLICY_LIST
    POLICY_LIST=$(echo "$POLICIES_JSON" | python3 -c "
import sys,json
policies = json.load(sys.stdin).get('associatedAccessPolicies',[])
for p in policies:
    name = p['policyArn'].split('/')[-1]
    scope = p.get('accessScope',{}).get('type','unknown')
    print(f'{name} (scope: {scope})')
" 2>/dev/null)

    if [ -n "$POLICY_LIST" ]; then
        log_ok "Attached policies:"
        while IFS= read -r pol; do
            echo "      - $pol"
        done <<< "$POLICY_LIST"
        HAS_ACCESS_ENTRY=true
    else
        log_warn "Access entry exists but NO policies attached (no effective access)"
        HAS_ACCESS_ENTRY=false
    fi
}

# ── Section: OIDC Provider ──

check_oidc() {
    echo ""
    echo -e "${CYAN}── OIDC Provider (IRSA) ──${NC}"

    local CLUSTER_JSON
    CLUSTER_JSON=$(aws eks describe-cluster --name "$CLUSTER_NAME" --region "$REGION" --profile "$AWS_PROFILE" --output json 2>&1)

    OIDC_ISSUER=$(echo "$CLUSTER_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['cluster'].get('identity',{}).get('oidc',{}).get('issuer',''))" 2>/dev/null)

    if [ -z "$OIDC_ISSUER" ]; then
        log_fail "No OIDC issuer configured on cluster"
        log_info "IRSA (IAM Roles for Service Accounts) will not work"
        OIDC_OK=false
        return
    fi

    OIDC_PROVIDER="${OIDC_ISSUER#https://}"
    log_ok "OIDC issuer: $OIDC_ISSUER"

    local ACCOUNT_ID
    ACCOUNT_ID=$(get_account_id)
    local OIDC_ARN="arn:aws:iam::${ACCOUNT_ID}:oidc-provider/${OIDC_PROVIDER}"

    local OIDC_DETAIL
    OIDC_DETAIL=$(aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_ARN" --profile "$AWS_PROFILE" --output json 2>&1) || true

    if echo "$OIDC_DETAIL" | grep -q "NoSuchEntity"; then
        log_fail "OIDC provider NOT registered in IAM"
        log_info "IRSA will not work until this is fixed"
        OIDC_OK=false
        return
    fi

    log_ok "OIDC provider registered in IAM"

    local THUMBPRINTS
    THUMBPRINTS=$(echo "$OIDC_DETAIL" | python3 -c "import sys,json; ts=json.load(sys.stdin).get('ThumbprintList',[]); print(len(ts))" 2>/dev/null || echo "0")
    log_info "Certificate thumbprints: $THUMBPRINTS"

    local HAS_STS
    HAS_STS=$(echo "$OIDC_DETAIL" | python3 -c "import sys,json; print('sts.amazonaws.com' in json.load(sys.stdin).get('ClientIDList',[]))" 2>/dev/null || echo "False")
    if [ "$HAS_STS" = "True" ]; then
        log_ok "STS audience configured (sts.amazonaws.com)"
    else
        log_warn "STS audience missing — some IRSA roles may not work"
    fi
    OIDC_OK=true
}

# ── Section: kubectl Connectivity ──

check_kubectl() {
    echo ""
    echo -e "${CYAN}── kubectl Connectivity ──${NC}"

    aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$REGION" --profile "$AWS_PROFILE" > /dev/null 2>&1
    log_info "Kubeconfig updated for $CLUSTER_NAME"

    local MAX_RETRIES="${1:-1}"
    local attempt=1

    while [ "$attempt" -le "$MAX_RETRIES" ]; do
        if kubectl get nodes > /dev/null 2>&1; then
            local NODE_COUNT
            NODE_COUNT=$(kubectl get nodes --no-headers 2>/dev/null | wc -l)
            log_ok "kubectl connected — $NODE_COUNT node(s)"
            KUBECTL_OK=true
            return
        fi
        if [ "$attempt" -lt "$MAX_RETRIES" ]; then
            log_info "Waiting for access entry propagation... (attempt $attempt/$MAX_RETRIES)"
            sleep 10
        fi
        attempt=$((attempt + 1))
    done

    log_fail "kubectl cannot connect (Unauthorized)"
    KUBECTL_OK=false
}

# ── Fix: Create Access Entry ──

fix_access_entry() {
    echo ""
    echo -e "${CYAN}── Fix: EKS Access Entry ──${NC}"

    if [ "$AUTH_MODE" = "CONFIG_MAP" ]; then
        log_warn "Cluster uses CONFIG_MAP auth only"
        log_info "Switching auth mode to API_AND_CONFIG_MAP to enable access entries"
        aws eks update-cluster-config \
            --name "$CLUSTER_NAME" \
            --region "$REGION" \
            --profile "$AWS_PROFILE" \
            --access-config authenticationMode=API_AND_CONFIG_MAP > /dev/null 2>&1

        log_info "Waiting for cluster update (this may take 1-2 minutes)..."
        aws eks wait cluster-active --name "$CLUSTER_NAME" --region "$REGION" --profile "$AWS_PROFILE" 2>/dev/null || sleep 30
        AUTH_MODE="API_AND_CONFIG_MAP"
        log_ok "Auth mode updated to API_AND_CONFIG_MAP"
    fi

    local EXISTING
    EXISTING=$(aws eks describe-access-entry \
        --cluster-name "$CLUSTER_NAME" \
        --region "$REGION" \
        --profile "$AWS_PROFILE" \
        --principal-arn "$PRINCIPAL_ROLE_ARN" \
        --output text 2>&1) || true

    if echo "$EXISTING" | grep -q "ResourceNotFoundException"; then
        log_info "Creating access entry for ${PRINCIPAL_ROLE_ARN##*/}"
        aws eks create-access-entry \
            --cluster-name "$CLUSTER_NAME" \
            --region "$REGION" \
            --profile "$AWS_PROFILE" \
            --principal-arn "$PRINCIPAL_ROLE_ARN" \
            --type STANDARD > /dev/null
        log_ok "Access entry created"
    else
        log_ok "Access entry already exists"
    fi

    local HAS_POLICY
    HAS_POLICY=$(aws eks list-associated-access-policies \
        --cluster-name "$CLUSTER_NAME" \
        --region "$REGION" \
        --profile "$AWS_PROFILE" \
        --principal-arn "$PRINCIPAL_ROLE_ARN" \
        --query "associatedAccessPolicies[?policyArn=='$ACCESS_POLICY_ARN'].policyArn" \
        --output text 2>&1)

    if [ -n "$HAS_POLICY" ] && [[ "$HAS_POLICY" != *"error"* ]]; then
        log_ok "AmazonEKSClusterAdminPolicy already attached"
    else
        log_info "Attaching AmazonEKSClusterAdminPolicy"
        aws eks associate-access-policy \
            --cluster-name "$CLUSTER_NAME" \
            --region "$REGION" \
            --profile "$AWS_PROFILE" \
            --principal-arn "$PRINCIPAL_ROLE_ARN" \
            --policy-arn "$ACCESS_POLICY_ARN" \
            --access-scope type=cluster > /dev/null
        log_ok "Policy attached"
    fi
}

# ── Fix: OIDC Provider ──

fix_oidc() {
    echo ""
    echo -e "${CYAN}── Fix: OIDC Provider ──${NC}"

    if [ -z "$OIDC_ISSUER" ]; then
        log_fail "Cluster has no OIDC issuer — cannot fix automatically"
        log_info "The cluster may need to be recreated with OIDC enabled"
        return 1
    fi

    if [ "$OIDC_OK" = "true" ]; then
        log_ok "OIDC provider already registered in IAM — no fix needed"
        return
    fi

    local ACCOUNT_ID
    ACCOUNT_ID=$(get_account_id)
    local OIDC_ARN="arn:aws:iam::${ACCOUNT_ID}:oidc-provider/${OIDC_PROVIDER}"

    log_info "Getting certificate thumbprint..."
    local THUMBPRINT
    THUMBPRINT=$(python3 -c "
import ssl, hashlib, socket
hostname = '${OIDC_PROVIDER}'.split('/')[0]
ctx = ssl.create_default_context()
with ctx.wrap_socket(socket.socket(), server_hostname=hostname) as s:
    s.connect((hostname, 443))
    der = s.getpeercert(binary_form=True)
    print(hashlib.sha1(der).hexdigest())
" 2>/dev/null)

    if [ -z "$THUMBPRINT" ]; then
        log_fail "Could not get OIDC thumbprint"
        return 1
    fi
    log_info "Thumbprint: ${THUMBPRINT:0:16}..."

    log_info "Creating OIDC provider in IAM"
    aws iam create-open-id-connect-provider \
        --url "$OIDC_ISSUER" \
        --client-id-list sts.amazonaws.com \
        --thumbprint-list "$THUMBPRINT" \
        --profile "$AWS_PROFILE" > /dev/null 2>&1

    log_ok "OIDC provider created: $OIDC_ARN"
    OIDC_OK=true
}

# ── Summary ──

print_summary() {
    local PASS=0
    local FAIL=0
    local items=()

    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo "  ACCESS SUMMARY — $CLUSTER_NAME"
    echo "═══════════════════════════════════════════════════════════"
    echo ""

    if [ "$CREDS_OK" = "true" ]; then
        log_ok "AWS Credentials"; PASS=$((PASS+1))
    else
        log_fail "AWS Credentials (expired — re-run login)"; FAIL=$((FAIL+1))
    fi

    if [ -n "$AUTH_MODE" ]; then
        log_ok "Auth Mode: $AUTH_MODE"; PASS=$((PASS+1))
    else
        log_fail "Auth Mode: unknown"; FAIL=$((FAIL+1))
    fi

    if [ "$HAS_ACCESS_ENTRY" = "true" ]; then
        log_ok "Access Entry + Policy"; PASS=$((PASS+1))
    else
        log_fail "Access Entry (missing or no policy)"; FAIL=$((FAIL+1))
    fi

    if [ "$OIDC_OK" = "true" ]; then
        log_ok "OIDC Provider (IRSA)"; PASS=$((PASS+1))
    else
        log_fail "OIDC Provider (not registered in IAM)"; FAIL=$((FAIL+1))
    fi

    if [ "$KUBECTL_OK" = "true" ]; then
        log_ok "kubectl connected"; PASS=$((PASS+1))
    else
        log_fail "kubectl (Unauthorized)"; FAIL=$((FAIL+1))
    fi

    echo ""
    echo -e "  Passed: ${GREEN}${PASS}${NC}  Failed: ${RED}${FAIL}${NC}"
    echo "═══════════════════════════════════════════════════════════"

    if [ "$FAIL" -gt 0 ] && [ "$1" = "check" ]; then
        echo ""
        echo -e "  Run ${BOLD}./cluster-access.sh fix${NC} to resolve issues automatically."
    fi

    [ "$FAIL" -eq 0 ]
}

# ── Commands ──

do_check() {
    echo ""
    echo "=============================================="
    echo "  Cluster Access Check — $CLUSTER_NAME"
    echo "=============================================="
    echo ""
    echo "  Cluster:     $CLUSTER_NAME"
    echo "  Region:      $REGION"
    echo "  AWS Profile: $AWS_PROFILE"

    CREDS_OK=false
    AUTH_MODE=""
    HAS_ACCESS_ENTRY=false
    OIDC_OK=false
    KUBECTL_OK=false
    PRINCIPAL_ROLE_ARN=""
    OIDC_ISSUER=""
    OIDC_PROVIDER=""

    check_aws_credentials || { print_summary "check"; return 1; }
    check_auth_mode || { print_summary "check"; return 1; }
    check_access_entries
    check_oidc
    check_kubectl
    print_summary "check"
}

do_fix() {
    echo ""
    echo "=============================================="
    echo "  Cluster Access Fix — $CLUSTER_NAME"
    echo "=============================================="
    echo ""
    echo "  Cluster:     $CLUSTER_NAME"
    echo "  Region:      $REGION"
    echo "  AWS Profile: $AWS_PROFILE"

    CREDS_OK=false
    AUTH_MODE=""
    HAS_ACCESS_ENTRY=false
    OIDC_OK=false
    KUBECTL_OK=false
    PRINCIPAL_ROLE_ARN=""
    OIDC_ISSUER=""
    OIDC_PROVIDER=""

    check_aws_credentials || return 1

    check_auth_mode || return 1
    check_access_entries
    check_oidc

    if [ "$HAS_ACCESS_ENTRY" != "true" ]; then
        fix_access_entry
        HAS_ACCESS_ENTRY=true
    else
        echo ""
        log_ok "Access entry already in place — no fix needed"
    fi

    if [ "$OIDC_OK" != "true" ]; then
        fix_oidc
    fi

    check_kubectl 4

    print_summary "fix"
}

# ── Grant GitHub Actions Role Access ──

grant_one_github_role() {
    local ROLE_ARN="$1"
    local ROLE_SHORT="${ROLE_ARN##*/}"

    echo ""
    echo -e "${CYAN}── Grant: ${ROLE_SHORT} ──${NC}"

    local EXISTING
    EXISTING=$(aws eks describe-access-entry \
        --cluster-name "$CLUSTER_NAME" \
        --region "$REGION" \
        --profile "$AWS_PROFILE" \
        --principal-arn "$ROLE_ARN" \
        --output text 2>&1) || true

    if echo "$EXISTING" | grep -q "ResourceNotFoundException"; then
        log_info "Creating access entry for ${ROLE_SHORT}"
        aws eks create-access-entry \
            --cluster-name "$CLUSTER_NAME" \
            --region "$REGION" \
            --profile "$AWS_PROFILE" \
            --principal-arn "$ROLE_ARN" \
            --type STANDARD > /dev/null
        log_ok "Access entry created"
    else
        log_ok "Access entry already exists"
    fi

    local HAS_POLICY
    HAS_POLICY=$(aws eks list-associated-access-policies \
        --cluster-name "$CLUSTER_NAME" \
        --region "$REGION" \
        --profile "$AWS_PROFILE" \
        --principal-arn "$ROLE_ARN" \
        --query "associatedAccessPolicies[?policyArn=='$ACCESS_POLICY_ARN'].policyArn" \
        --output text 2>&1)

    if [ -n "$HAS_POLICY" ] && [[ "$HAS_POLICY" != *"error"* ]]; then
        log_ok "AmazonEKSClusterAdminPolicy already attached"
    else
        log_info "Attaching AmazonEKSClusterAdminPolicy"
        aws eks associate-access-policy \
            --cluster-name "$CLUSTER_NAME" \
            --region "$REGION" \
            --profile "$AWS_PROFILE" \
            --principal-arn "$ROLE_ARN" \
            --policy-arn "$ACCESS_POLICY_ARN" \
            --access-scope type=cluster > /dev/null
        log_ok "Policy attached"
    fi
}

do_grant_github() {
    local GH_REPO="both"
    local GH_ENV="${_ENV_LOCAL_ENV:-dev}"

    shift
    while [[ $# -gt 0 ]]; do
        case $1 in
            --repo)  GH_REPO="$2"; shift 2 ;;
            --env)   GH_ENV="$2"; shift 2 ;;
            *)       echo "Unknown option for grant-github: $1"; exit 1 ;;
        esac
    done

    echo ""
    echo "=============================================="
    echo "  Grant GitHub Actions Access — $CLUSTER_NAME"
    echo "=============================================="
    echo ""
    echo "  Cluster:     $CLUSTER_NAME"
    echo "  Region:      $REGION"
    echo "  AWS Profile: $AWS_PROFILE"
    echo "  Target Env:  $GH_ENV"
    echo "  Target Repo: $GH_REPO"

    check_aws_credentials || return 1

    local ACCOUNT_ID
    ACCOUNT_ID=$(get_account_id)

    check_auth_mode || return 1

    if [ "$AUTH_MODE" = "CONFIG_MAP" ]; then
        log_warn "Cluster uses CONFIG_MAP auth only"
        log_info "Switching auth mode to API_AND_CONFIG_MAP to enable access entries"
        aws eks update-cluster-config \
            --name "$CLUSTER_NAME" \
            --region "$REGION" \
            --profile "$AWS_PROFILE" \
            --access-config authenticationMode=API_AND_CONFIG_MAP > /dev/null 2>&1
        log_info "Waiting for cluster update (this may take 1-2 minutes)..."
        aws eks wait cluster-active --name "$CLUSTER_NAME" --region "$REGION" --profile "$AWS_PROFILE" 2>/dev/null || sleep 30
        AUTH_MODE="API_AND_CONFIG_MAP"
        log_ok "Auth mode updated to API_AND_CONFIG_MAP"
    fi

    local REPOS=()
    case "$GH_REPO" in
        backend)  REPOS=("nexus-backend") ;;
        ui)       REPOS=("nexus-ui") ;;
        both|all) REPOS=("nexus-backend" "nexus-ui") ;;
        *)        REPOS=("$GH_REPO") ;;
    esac

    local SUCCESS=0
    local TOTAL=0
    for repo in "${REPOS[@]}"; do
        local ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/GitHubActions-${repo}-${GH_ENV}"
        TOTAL=$((TOTAL + 1))
        if grant_one_github_role "$ROLE_ARN"; then
            SUCCESS=$((SUCCESS + 1))
        fi
    done

    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo "  GRANT SUMMARY — $CLUSTER_NAME"
    echo "═══════════════════════════════════════════════════════════"
    echo ""
    for repo in "${REPOS[@]}"; do
        log_ok "GitHubActions-${repo}-${GH_ENV} → cluster admin on ${CLUSTER_NAME}"
    done
    echo ""
    log_info "GitHub Actions workflows using these roles can now deploy to this cluster."
    echo "═══════════════════════════════════════════════════════════"
}

# ── Main ──

COMMAND="${1:-}"

case "$COMMAND" in
    check|status|diagnose)
        do_check
        ;;
    fix|repair|restore)
        do_fix
        ;;
    grant-github)
        do_grant_github "$@"
        ;;
    --help|-h|help)
        show_help
        ;;
    *)
        if [ -n "$COMMAND" ]; then
            echo "Unknown command: $COMMAND"
            echo ""
        fi
        show_help
        exit 1
        ;;
esac

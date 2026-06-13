#!/bin/bash
#
# Bootstrap IAM Policies & Roles for an EKS Cluster (one-shot, run by AWS admin)
# ---------------------------------------------------------------------------
# Creates the four IRSA roles required by the Totogi platform on a fresh
# AWS account / EKS cluster:
#
#   1. totogi-operator-role               (operator pod, namespace: totogi-system)
#   2. <capability>-<env>-app-role        (application pods, namespace: <capability>-<env>)
#   3. AmazonEKS_EBS_CSI_DriverRole       (EBS CSI controller)
#   4. velero-backup-role                 (Velero backup controller)
#
# For each role the script:
#   - discovers the cluster's OIDC issuer (registers it in IAM if missing)
#   - renders the trust policy with the cluster's OIDC provider + account ID
#   - renders the permissions policy with region / account / capability / env
#   - creates the role + inline/managed policy (or UPDATES if it already exists)
#
# Defaults are read from kube-operator/.env.local; CLI flags override.
#
# Usage:
#   ./setup-iam-policies.sh                                  # interactive (uses .env.local)
#   ./setup-iam-policies.sh --cluster nexus-test1 --env dev --capability nexus-ai
#   ./setup-iam-policies.sh --dry-run                        # render policies, do not call IAM
#   ./setup-iam-policies.sh --skip-confirm                   # skip the "y/N" prompt
#   ./setup-iam-policies.sh --help
#
# Required AWS permissions (run as admin):
#   iam:CreateOpenIDConnectProvider, iam:GetOpenIDConnectProvider,
#   iam:CreateRole, iam:GetRole, iam:UpdateAssumeRolePolicy,
#   iam:PutRolePolicy, iam:GetRolePolicy,
#   iam:CreatePolicy, iam:CreatePolicyVersion, iam:DeletePolicyVersion,
#   iam:AttachRolePolicy, iam:ListAttachedRolePolicies, iam:ListPolicyVersions,
#   eks:DescribeCluster, sts:GetCallerIdentity
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PERMS_DIR="${SCRIPT_DIR}/permissions"

# ── .env.local defaults ──
_ENVLOCAL="${SCRIPT_DIR}/.env.local"
_ENV_LOCAL_ENV=""
_ENV_LOCAL_CLUSTER=""
_ENV_LOCAL_BSL=""
if [ -f "$_ENVLOCAL" ]; then
    _ENV_LOCAL_ENV=$(grep '^ENV[[:space:]]*=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true)
    _ENV_LOCAL_CLUSTER=$(grep '^Cluster[[:space:]]*=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true)
    _ENV_LOCAL_BSL=$(grep '^BackupStorageLocation[[:space:]]*=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true)
fi

# ── Defaults (CLI overrides win) ──
CLUSTER_NAME="${CLUSTER_NAME:-${_ENV_LOCAL_CLUSTER:-nexus-test1}}"
REGION="${REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-default}"
DEPLOY_ENV="${DEPLOY_ENV:-${_ENV_LOCAL_ENV:-dev}}"
CAPABILITY="${CAPABILITY:-nexus-ai}"
ACCOUNT_ID_OVERRIDE=""
BUCKET_NAME="${BUCKET_NAME:-${_ENV_LOCAL_BSL#s3://}}"
BUCKET_NAME="${BUCKET_NAME:-nexus-test-backup}"
DRY_RUN=false
SKIP_CONFIRM=false

# ── Constants (match permissions/ADMIN-SETUP.md conventions) ──
OPERATOR_ROLE_NAME="totogi-operator-role"
OPERATOR_INLINE_POLICY_NAME="totogi-operator-policy"
EBS_CSI_ROLE_NAME="AmazonEKS_EBS_CSI_DriverRole"
EBS_CSI_MANAGED_POLICY_ARN="arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
VELERO_ROLE_NAME="velero-backup-role"
VELERO_POLICY_NAME="VeleroBackupPolicy"

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
log_ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
log_fail() { echo -e "  ${RED}✗${NC} $1"; }
log_warn() { echo -e "  ${YELLOW}!${NC} $1"; }
log_info() { echo -e "  ${CYAN}→${NC} $1"; }
log_step() { echo -e "\n${CYAN}── $1 ──${NC}"; }

show_help() {
    cat << EOF
Bootstrap IAM Policies & Roles for an EKS Cluster
==================================================

One-shot bootstrap script run by an AWS administrator. Discovers the cluster
OIDC provider, registers it in IAM if missing, and creates (or updates) the
four IRSA roles required by the Totogi platform.

Usage:
  $0 [options]

Options:
  --cluster NAME       EKS cluster name        (default: $CLUSTER_NAME)
  --region REGION      AWS region              (default: $REGION)
  --profile PROFILE    AWS CLI profile         (default: $AWS_PROFILE)
  --env ENV            Deployment env          (default: $DEPLOY_ENV)
  --capability NAME    Capability name         (default: $CAPABILITY)
  --account-id ID      Override AWS account ID (default: from sts:GetCallerIdentity)
  --bucket NAME        Velero S3 backup bucket (default: $BUCKET_NAME)
  --dry-run            Render policies but do not call IAM
  --skip-confirm       Skip "Continue? [y/N]" prompt
  --help, -h           Show this help

Roles created:
  1. ${OPERATOR_ROLE_NAME}               (inline: ${OPERATOR_INLINE_POLICY_NAME})
  2. <capability>-<env>-app-role         (inline: <capability>-<env>-app-role-policy)
  3. ${EBS_CSI_ROLE_NAME}      (managed: AmazonEBSCSIDriverPolicy)
  4. ${VELERO_ROLE_NAME}                 (managed: ${VELERO_POLICY_NAME})

Idempotent: existing roles have their trust policy + inline/managed policy
updated in place. Safe to re-run.
EOF
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --cluster)        CLUSTER_NAME="$2"; shift 2 ;;
        --region)         REGION="$2"; shift 2 ;;
        --profile)        AWS_PROFILE="$2"; shift 2 ;;
        --env)            DEPLOY_ENV="$2"; shift 2 ;;
        --capability)     CAPABILITY="$2"; shift 2 ;;
        --account-id)     ACCOUNT_ID_OVERRIDE="$2"; shift 2 ;;
        --bucket)         BUCKET_NAME="$2"; shift 2 ;;
        --dry-run)        DRY_RUN=true; shift ;;
        --skip-confirm)   SKIP_CONFIRM=true; shift ;;
        --help|-h)        show_help; exit 0 ;;
        *) log_fail "Unknown option: $1"; echo ""; show_help; exit 1 ;;
    esac
done

APP_ROLE_NAME="${CAPABILITY}-${DEPLOY_ENV}-app-role"
APP_INLINE_POLICY_NAME="${APP_ROLE_NAME}-policy"
APP_NAMESPACE="${CAPABILITY}-${DEPLOY_ENV}"

# ── Pre-flight ──
require_cmd() { command -v "$1" >/dev/null 2>&1 || { log_fail "Required command not found: $1"; exit 1; }; }
require_cmd aws
require_cmd python3
require_cmd openssl

# Validate template files exist
for f in operator-trust-policy.json operator-policy.json \
         app-trust-policy.json app-policy.json \
         ebs-csi-trust-policy.json \
         velero-backup-trust-policy.json velero-backup-policy.json; do
    [ -f "${PERMS_DIR}/${f}" ] || { log_fail "Missing template: ${PERMS_DIR}/${f}"; exit 1; }
done

aws_call() { aws "$@" --profile "$AWS_PROFILE" --region "$REGION"; }

# ── Step 1: Caller identity & account ID ──
log_step "Caller Identity"
CALLER_JSON=$(aws sts get-caller-identity --profile "$AWS_PROFILE" --output json 2>&1) || {
    log_fail "AWS credentials invalid for profile '$AWS_PROFILE'"
    echo "$CALLER_JSON"
    exit 1
}
ACCOUNT_ID=$(echo "$CALLER_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['Account'])")
CALLER_ARN=$(echo "$CALLER_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['Arn'])")
[ -n "$ACCOUNT_ID_OVERRIDE" ] && ACCOUNT_ID="$ACCOUNT_ID_OVERRIDE"

log_ok "Profile:   $AWS_PROFILE"
log_ok "Account:   $ACCOUNT_ID"
log_ok "Identity:  $CALLER_ARN"

# ── Step 2: Discover cluster OIDC issuer ──
log_step "Discover Cluster OIDC Provider"
CLUSTER_JSON=$(aws_call eks describe-cluster --name "$CLUSTER_NAME" --output json 2>&1) || {
    log_fail "Cannot describe cluster '$CLUSTER_NAME' in $REGION"
    echo "$CLUSTER_JSON"
    exit 1
}
OIDC_ISSUER=$(echo "$CLUSTER_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['cluster'].get('identity',{}).get('oidc',{}).get('issuer',''))")
if [ -z "$OIDC_ISSUER" ]; then
    log_fail "Cluster has no OIDC issuer configured. Cannot proceed (IRSA requires it)."
    exit 1
fi
OIDC_PROVIDER="${OIDC_ISSUER#https://}"
OIDC_PROVIDER_ARN="arn:aws:iam::${ACCOUNT_ID}:oidc-provider/${OIDC_PROVIDER}"
log_ok "Cluster:        $CLUSTER_NAME"
log_ok "OIDC issuer:    $OIDC_ISSUER"
log_ok "OIDC provider:  $OIDC_PROVIDER"

# ── Confirm before any IAM write ──
echo ""
echo -e "${BOLD}About to create/update IAM resources in account ${ACCOUNT_ID} (region ${REGION}):${NC}"
echo "  • OIDC provider:  ${OIDC_PROVIDER_ARN}"
echo "  • Role:           ${OPERATOR_ROLE_NAME}                 (+ inline policy ${OPERATOR_INLINE_POLICY_NAME})"
echo "  • Role:           ${APP_ROLE_NAME}            (+ inline policy ${APP_INLINE_POLICY_NAME})"
echo "                    namespace: ${APP_NAMESPACE}"
echo "  • Role:           ${EBS_CSI_ROLE_NAME}       (+ managed policy AmazonEBSCSIDriverPolicy)"
echo "  • Role:           ${VELERO_ROLE_NAME}                  (+ managed policy ${VELERO_POLICY_NAME})"
echo "                    backup bucket: s3://${BUCKET_NAME}"
[ "$DRY_RUN" = "true" ] && echo -e "${YELLOW}  [DRY-RUN] no IAM API calls will be made${NC}"

if [ "$SKIP_CONFIRM" != "true" ] && [ "$DRY_RUN" != "true" ]; then
    read -rp "Continue? [y/N] " ans
    [[ "$ans" =~ ^[yY]$ ]] || { echo "Aborted."; exit 0; }
fi

# ── Step 3: OIDC provider registration ──
log_step "IAM OIDC Provider"
OIDC_LOOKUP=$(aws iam get-open-id-connect-provider \
    --open-id-connect-provider-arn "$OIDC_PROVIDER_ARN" \
    --profile "$AWS_PROFILE" --output json 2>&1) || true

if echo "$OIDC_LOOKUP" | grep -q "NoSuchEntity"; then
    log_warn "OIDC provider not registered in IAM — creating"
    if [ "$DRY_RUN" != "true" ]; then
        OIDC_HOST=$(echo "$OIDC_PROVIDER" | cut -d/ -f1)
        THUMBPRINT=$(echo | openssl s_client -servername "$OIDC_HOST" -showcerts \
                       -connect "${OIDC_HOST}:443" 2>/dev/null \
                     | python3 -c '
import sys, re, subprocess
data = sys.stdin.read()
certs = re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", data, re.S)
if not certs:
    sys.exit("no certs returned by openssl s_client")
last = certs[-1]
fp = subprocess.run(["openssl","x509","-fingerprint","-sha1","-noout"],
                    input=last.encode(), capture_output=True, check=True).stdout.decode()
print(fp.split("=",1)[1].strip().replace(":","").lower())
') || { log_fail "Could not compute OIDC thumbprint"; exit 1; }

        aws iam create-open-id-connect-provider \
            --url "$OIDC_ISSUER" \
            --client-id-list "sts.amazonaws.com" \
            --thumbprint-list "$THUMBPRINT" \
            --profile "$AWS_PROFILE" > /dev/null
        log_ok "OIDC provider created"
    else
        log_info "[dry-run] would create OIDC provider with thumbprint discovery"
    fi
else
    log_ok "OIDC provider already registered"
    HAS_STS=$(echo "$OIDC_LOOKUP" | python3 -c "import sys,json; print('sts.amazonaws.com' in json.load(sys.stdin).get('ClientIDList',[]))" 2>/dev/null || echo "False")
    if [ "$HAS_STS" != "True" ]; then
        log_warn "STS audience missing on existing provider — adding"
        if [ "$DRY_RUN" != "true" ]; then
            aws iam add-client-id-to-open-id-connect-provider \
                --open-id-connect-provider-arn "$OIDC_PROVIDER_ARN" \
                --client-id "sts.amazonaws.com" \
                --profile "$AWS_PROFILE" > /dev/null
            log_ok "STS audience added"
        fi
    fi
fi

# ── Helper: render template with sed substitutions ──
# render_template <template-path> <output-path> [extra sed args...]
render_template() {
    local tpl="$1"; local out="$2"; shift 2
    sed -e "s|\${ACCOUNT_ID}|${ACCOUNT_ID}|g" \
        -e "s|\${OIDC_PROVIDER}|${OIDC_PROVIDER}|g" \
        -e "s|<region>|${REGION}|g" \
        -e "s|<account-id>|${ACCOUNT_ID}|g" \
        "$@" \
        "$tpl" > "$out"
}

# ── Helper: idempotent create-or-update role w/ inline policy ──
# upsert_role_inline <role-name> <trust-doc-path> <inline-policy-name> <inline-doc-path> <description>
upsert_role_inline() {
    local role="$1" trust_doc="$2" pol_name="$3" pol_doc="$4" desc="$5"

    if [ "$DRY_RUN" = "true" ]; then
        log_info "[dry-run] role=$role  trust=$trust_doc  inline=$pol_name <- $pol_doc"
        return
    fi

    if aws iam get-role --role-name "$role" --profile "$AWS_PROFILE" >/dev/null 2>&1; then
        log_info "Role '$role' exists — updating trust policy"
        aws iam update-assume-role-policy \
            --role-name "$role" \
            --policy-document "file://${trust_doc}" \
            --profile "$AWS_PROFILE" > /dev/null
        log_ok "Trust policy updated"
    else
        log_info "Creating role '$role'"
        aws iam create-role \
            --role-name "$role" \
            --assume-role-policy-document "file://${trust_doc}" \
            --description "$desc" \
            --profile "$AWS_PROFILE" > /dev/null
        log_ok "Role created"
    fi

    aws iam put-role-policy \
        --role-name "$role" \
        --policy-name "$pol_name" \
        --policy-document "file://${pol_doc}" \
        --profile "$AWS_PROFILE" > /dev/null
    log_ok "Inline policy '$pol_name' attached"
}

# ── Helper: idempotent create-or-update role w/ managed policy ──
# upsert_role_managed <role-name> <trust-doc-path> <managed-policy-arn> <description>
upsert_role_managed() {
    local role="$1" trust_doc="$2" pol_arn="$3" desc="$4"

    if [ "$DRY_RUN" = "true" ]; then
        log_info "[dry-run] role=$role  trust=$trust_doc  managed=$pol_arn"
        return
    fi

    if aws iam get-role --role-name "$role" --profile "$AWS_PROFILE" >/dev/null 2>&1; then
        log_info "Role '$role' exists — updating trust policy"
        aws iam update-assume-role-policy \
            --role-name "$role" \
            --policy-document "file://${trust_doc}" \
            --profile "$AWS_PROFILE" > /dev/null
        log_ok "Trust policy updated"
    else
        log_info "Creating role '$role'"
        aws iam create-role \
            --role-name "$role" \
            --assume-role-policy-document "file://${trust_doc}" \
            --description "$desc" \
            --profile "$AWS_PROFILE" > /dev/null
        log_ok "Role created"
    fi

    if aws iam list-attached-role-policies --role-name "$role" --profile "$AWS_PROFILE" \
        --query "AttachedPolicies[?PolicyArn=='${pol_arn}'].PolicyArn" --output text 2>/dev/null \
        | grep -q "$pol_arn"; then
        log_ok "Managed policy already attached"
    else
        aws iam attach-role-policy \
            --role-name "$role" \
            --policy-arn "$pol_arn" \
            --profile "$AWS_PROFILE" > /dev/null
        log_ok "Managed policy '${pol_arn##*/}' attached"
    fi
}

# ── Helper: idempotent create-or-update customer-managed policy ──
# upsert_managed_policy <policy-name> <doc-path>  -> echoes the policy ARN
upsert_managed_policy() {
    local name="$1" doc="$2"
    local arn="arn:aws:iam::${ACCOUNT_ID}:policy/${name}"

    if [ "$DRY_RUN" = "true" ]; then
        log_info "[dry-run] managed-policy=$name <- $doc"
        echo "$arn"
        return
    fi

    if aws iam get-policy --policy-arn "$arn" --profile "$AWS_PROFILE" >/dev/null 2>&1; then
        log_info "Managed policy '$name' exists — adding new default version"
        # AWS allows max 5 versions; prune non-default before creating a new one.
        local versions
        versions=$(aws iam list-policy-versions --policy-arn "$arn" --profile "$AWS_PROFILE" \
                     --query "Versions[?IsDefaultVersion==\`false\`].VersionId" --output text 2>/dev/null || echo "")
        for v in $versions; do
            aws iam delete-policy-version --policy-arn "$arn" --version-id "$v" \
                --profile "$AWS_PROFILE" >/dev/null 2>&1 || true
        done
        aws iam create-policy-version \
            --policy-arn "$arn" \
            --policy-document "file://${doc}" \
            --set-as-default \
            --profile "$AWS_PROFILE" > /dev/null
        log_ok "Policy version updated"
    else
        log_info "Creating managed policy '$name'"
        aws iam create-policy \
            --policy-name "$name" \
            --policy-document "file://${doc}" \
            --profile "$AWS_PROFILE" > /dev/null
        log_ok "Managed policy created"
    fi
    echo "$arn"
}

# ── Render all templates into a tmpdir ──
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

render_template "${PERMS_DIR}/operator-trust-policy.json" "${TMPDIR}/operator-trust.json"
render_template "${PERMS_DIR}/operator-policy.json"       "${TMPDIR}/operator-perms.json"

render_template "${PERMS_DIR}/app-trust-policy.json" "${TMPDIR}/app-trust.json" \
    -e "s|\${CAPABILITY}|${CAPABILITY}|g" \
    -e "s|\${ENV}|${DEPLOY_ENV}|g"
render_template "${PERMS_DIR}/app-policy.json" "${TMPDIR}/app-perms.json" \
    -e "s|<capability>|${CAPABILITY}|g" \
    -e "s|<capability_underscore>|${CAPABILITY//-/_}|g" \
    -e "s|<env>|${DEPLOY_ENV}|g"

render_template "${PERMS_DIR}/ebs-csi-trust-policy.json" "${TMPDIR}/ebs-csi-trust.json"

render_template "${PERMS_DIR}/velero-backup-trust-policy.json" "${TMPDIR}/velero-trust.json"
render_template "${PERMS_DIR}/velero-backup-policy.json" "${TMPDIR}/velero-perms.json" \
    -e "s|\${BUCKET_NAME}|${BUCKET_NAME}|g"

# Validate every rendered policy still parses as JSON
for f in "${TMPDIR}"/*.json; do
    python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$f" \
        || { log_fail "Rendered policy is not valid JSON: $f"; exit 1; }
done
log_ok "All policy templates rendered & validated"

# ── Step 4: Create roles ──
log_step "Role 1/4: ${OPERATOR_ROLE_NAME}"
upsert_role_inline "$OPERATOR_ROLE_NAME" \
    "${TMPDIR}/operator-trust.json" \
    "$OPERATOR_INLINE_POLICY_NAME" \
    "${TMPDIR}/operator-perms.json" \
    "Totogi operator pod (IRSA) - cluster ${CLUSTER_NAME}"

log_step "Role 2/4: ${APP_ROLE_NAME}"
upsert_role_inline "$APP_ROLE_NAME" \
    "${TMPDIR}/app-trust.json" \
    "$APP_INLINE_POLICY_NAME" \
    "${TMPDIR}/app-perms.json" \
    "App role for ${CAPABILITY}/${DEPLOY_ENV} (IRSA) - cluster ${CLUSTER_NAME}"

log_step "Role 3/4: ${EBS_CSI_ROLE_NAME}"
upsert_role_managed "$EBS_CSI_ROLE_NAME" \
    "${TMPDIR}/ebs-csi-trust.json" \
    "$EBS_CSI_MANAGED_POLICY_ARN" \
    "EBS CSI driver controller (IRSA) - cluster ${CLUSTER_NAME}"

log_step "Role 4/4: ${VELERO_ROLE_NAME}"
VELERO_POLICY_ARN=$(upsert_managed_policy "$VELERO_POLICY_NAME" "${TMPDIR}/velero-perms.json" | tail -n1)
upsert_role_managed "$VELERO_ROLE_NAME" \
    "${TMPDIR}/velero-trust.json" \
    "$VELERO_POLICY_ARN" \
    "Velero backup controller (IRSA) - cluster ${CLUSTER_NAME}"

# ── Step 5: Verification ──
log_step "Verification"
if [ "$DRY_RUN" = "true" ]; then
    log_info "[dry-run] skipping verification"
else
    for role in "$OPERATOR_ROLE_NAME" "$APP_ROLE_NAME" "$EBS_CSI_ROLE_NAME" "$VELERO_ROLE_NAME"; do
        ARN=$(aws iam get-role --role-name "$role" --profile "$AWS_PROFILE" \
                --query "Role.Arn" --output text 2>/dev/null || echo "MISSING")
        if [ "$ARN" = "MISSING" ]; then
            log_fail "$role  (NOT FOUND)"
        else
            log_ok "$role  ->  $ARN"
        fi
    done
fi

# ── Summary ──
echo ""
echo "================================================================"
echo -e "  ${GREEN}IAM Bootstrap Complete${NC}"
echo "================================================================"
echo ""
echo "  Cluster:        $CLUSTER_NAME"
echo "  Region:         $REGION"
echo "  Account:        $ACCOUNT_ID"
echo "  OIDC provider:  $OIDC_PROVIDER"
echo ""
echo "  Operator role:  arn:aws:iam::${ACCOUNT_ID}:role/${OPERATOR_ROLE_NAME}"
echo "  App role:       arn:aws:iam::${ACCOUNT_ID}:role/${APP_ROLE_NAME}"
echo "                  (namespace: ${APP_NAMESPACE})"
echo "  EBS-CSI role:   arn:aws:iam::${ACCOUNT_ID}:role/${EBS_CSI_ROLE_NAME}"
echo "  Velero role:    arn:aws:iam::${ACCOUNT_ID}:role/${VELERO_ROLE_NAME}"
echo "                  policy: arn:aws:iam::${ACCOUNT_ID}:policy/${VELERO_POLICY_NAME}"
echo ""
echo "  Next steps (deployment team, from jumpbox):"
echo "    aws eks create-addon --cluster-name ${CLUSTER_NAME} \\"
echo "      --addon-name aws-ebs-csi-driver \\"
echo "      --service-account-role-arn arn:aws:iam::${ACCOUNT_ID}:role/${EBS_CSI_ROLE_NAME} \\"
echo "      --resolve-conflicts OVERWRITE"
echo "    cd kube-operator && ./setup-velero-backup.sh setup"
echo "    cd kube-operator && ./create-ecr-images.sh"
echo "    cd kube-operator && ./operator-rollout.sh --version <operator-tag>"
echo "    cd kube-operator && ./app-rollout.sh --version <app-tag> all"
echo ""

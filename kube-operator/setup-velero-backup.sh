#!/bin/bash
#
# Velero Backup Setup Script for EKS Clusters
# Creates S3 bucket, IAM policy/role with IRSA, installs Velero, and verifies.
# Reads cluster defaults from .env.local.
#
# Usage:
#   ./setup-velero-backup.sh setup                          # Full setup: IAM + install + verify
#   ./setup-velero-backup.sh verify                         # Verify existing Velero installation
#   ./setup-velero-backup.sh teardown                       # Remove Velero and IAM resources
#   ./setup-velero-backup.sh backup                         # Create an on-demand backup
#   ./setup-velero-backup.sh list-backups                   # List all backups
#   ./setup-velero-backup.sh restore <backup-name>          # Full cluster restore from backup
#   ./setup-velero-backup.sh restore-ns <backup> <ns>       # Restore a single namespace
#   ./setup-velero-backup.sh --help                         # Show help
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

_ENVLOCAL="${SCRIPT_DIR}/.env.local"
if [ -f "$_ENVLOCAL" ]; then
    _ENV_LOCAL_CLUSTER=$(grep '^Cluster=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2-)
    _ENV_LOCAL_BSL=$(grep '^BackupStorageLocation=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2-)
fi

CLUSTER_NAME="${CLUSTER_NAME:-${_ENV_LOCAL_CLUSTER:-nexus-test1}}"
REGION="${REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-external-access}"
BUCKET_NAME="${BUCKET_NAME:-${_ENV_LOCAL_BSL#s3://}}"
BUCKET_NAME="${BUCKET_NAME:-nexus-eks-backup-bucket}"
VELERO_NAMESPACE="velero"
VELERO_SA="velero"
VELERO_PLUGIN_VERSION="${VELERO_PLUGIN_VERSION:-v1.11.0}"
IAM_POLICY_NAME="VeleroBackupPolicy"
IAM_ROLE_NAME="velero-backup-role"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
log_fail() { echo -e "  ${RED}✗${NC} $1"; }
log_warn() { echo -e "  ${YELLOW}!${NC} $1"; }
log_info() { echo -e "  ${CYAN}→${NC} $1"; }

show_help() {
    cat << EOF
Velero Backup Setup for EKS
============================

Commands:
  setup                       Full setup: S3 bucket, IAM policy/role (IRSA), Velero install, verify
  verify                      Verify existing Velero installation and BSL health
  teardown                    Uninstall Velero and remove IAM resources (keeps S3 bucket)
  backup [NAME]               Create an on-demand full-cluster backup
  list-backups                List all available backups with status
  restore <BACKUP> [--force]    Restore entire cluster from a backup
  restore-ns <BACKUP> <NS> [--force]  Restore a single namespace from a backup

Options:
  --force     Overwrite existing resources with backup versions (default: skip existing)

Environment variables (or set in .env.local):
  CLUSTER_NAME           EKS cluster name       (default: from .env.local or nexus-test1)
  REGION                 AWS region             (default: us-east-1)
  AWS_PROFILE            AWS CLI profile        (default: external-access)
  BUCKET_NAME            S3 backup bucket       (default: from .env.local BackupStorageLocation or nexus-eks-backup-bucket)
  VELERO_PLUGIN_VERSION  AWS plugin version     (default: v1.11.0)

EOF
}

get_account_id() {
    aws sts get-caller-identity --profile "$AWS_PROFILE" --query "Account" --output text
}

get_oidc_issuer() {
    aws eks describe-cluster --name "$CLUSTER_NAME" --region "$REGION" --profile "$AWS_PROFILE" \
        --query "cluster.identity.oidc.issuer" --output text
}

switch_context() {
    echo ""
    echo "  Cluster:     $CLUSTER_NAME"
    echo "  Region:      $REGION"
    echo "  AWS Profile: $AWS_PROFILE"
    echo "  Bucket:      $BUCKET_NAME"
    echo ""

    aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$REGION" --profile "$AWS_PROFILE" > /dev/null 2>&1

    if ! kubectl get nodes > /dev/null 2>&1; then
        echo ""
        log_fail "kubectl cannot connect to cluster (Unauthorized). Re-run your AWS login and try again."
        exit 1
    fi
    log_ok "kubectl connected to cluster"
}

setup_s3_bucket() {
    echo ""
    echo -e "${CYAN}── S3 Bucket ──${NC}"

    if aws s3api head-bucket --bucket "$BUCKET_NAME" --profile "$AWS_PROFILE" --region "$REGION" > /dev/null 2>&1; then
        log_ok "Bucket $BUCKET_NAME already exists"
    else
        log_info "Creating bucket $BUCKET_NAME in $REGION"
        aws s3api create-bucket \
            --bucket "$BUCKET_NAME" \
            --region "$REGION" \
            --create-bucket-configuration LocationConstraint="$REGION" \
            --profile "$AWS_PROFILE" > /dev/null
        log_ok "Bucket $BUCKET_NAME created"
    fi
}

setup_iam() {
    echo ""
    echo -e "${CYAN}── IAM Policy & Role (IRSA) ──${NC}"

    local ACCOUNT_ID
    ACCOUNT_ID=$(get_account_id)
    local OIDC_ISSUER
    OIDC_ISSUER=$(get_oidc_issuer)
    local OIDC_PROVIDER="${OIDC_ISSUER#https://}"
    local POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${IAM_POLICY_NAME}"

    # Test if IAM API is reachable (may not be on private jumpboxes without NAT/VPC endpoint)
    local IAM_REACHABLE=true
    local IAM_TEST
    IAM_TEST=$(aws iam get-policy --policy-arn "$POLICY_ARN" --profile "$AWS_PROFILE" 2>&1) || true
    if echo "$IAM_TEST" | grep -qi "connection was closed\|Could not connect\|timed out\|Name or service not known"; then
        IAM_REACHABLE=false
        log_warn "IAM API is not reachable from this machine (no VPC endpoint or NAT)"
        log_info "Assuming role '$IAM_ROLE_NAME' and policy '$IAM_POLICY_NAME' were pre-created by admin"
        log_info "See permissions/ADMIN-SETUP.md Step 4 for instructions"
        ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${IAM_ROLE_NAME}"
        log_ok "Using pre-created role: $ROLE_ARN"
        return
    fi

    # --- Policy ---
    local POLICY_DOC
    POLICY_DOC=$(cat <<POLICYJSON
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "ec2:DescribeVolumes",
                "ec2:DescribeSnapshots",
                "ec2:CreateTags",
                "ec2:CreateVolume",
                "ec2:CreateSnapshot",
                "ec2:DeleteSnapshot"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:DeleteObject",
                "s3:PutObject",
                "s3:AbortMultipartUpload",
                "s3:ListMultipartUploadParts"
            ],
            "Resource": "arn:aws:s3:::${BUCKET_NAME}/*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "s3:ListBucket"
            ],
            "Resource": "arn:aws:s3:::${BUCKET_NAME}"
        }
    ]
}
POLICYJSON
    )

    if echo "$IAM_TEST" | grep -q "NoSuchEntity"; then
        log_info "Creating IAM policy $IAM_POLICY_NAME"
        aws iam create-policy \
            --policy-name "$IAM_POLICY_NAME" \
            --policy-document "$POLICY_DOC" \
            --profile "$AWS_PROFILE" > /dev/null
        log_ok "IAM policy created: $POLICY_ARN"
    else
        log_ok "IAM policy $IAM_POLICY_NAME already exists"
        local CURRENT_VERSION_ID
        CURRENT_VERSION_ID=$(aws iam get-policy --policy-arn "$POLICY_ARN" --profile "$AWS_PROFILE" \
            --query "Policy.DefaultVersionId" --output text 2>/dev/null)
        local CURRENT_DOC
        CURRENT_DOC=$(aws iam get-policy-version --policy-arn "$POLICY_ARN" --version-id "$CURRENT_VERSION_ID" \
            --profile "$AWS_PROFILE" --query "PolicyVersion.Document" --output json 2>/dev/null)
        local DESIRED_BUCKET_REF="arn:aws:s3:::${BUCKET_NAME}"
        if echo "$CURRENT_DOC" | grep -q "$DESIRED_BUCKET_REF"; then
            log_ok "Policy already references bucket $BUCKET_NAME — no update needed"
        else
            log_info "Updating policy for bucket $BUCKET_NAME"
            local OLD_VERSIONS
            OLD_VERSIONS=$(aws iam list-policy-versions --policy-arn "$POLICY_ARN" --profile "$AWS_PROFILE" \
                --query "Versions[?IsDefaultVersion==\`false\`].VersionId" --output text 2>/dev/null)
            for OLD_V in $OLD_VERSIONS; do
                aws iam delete-policy-version --policy-arn "$POLICY_ARN" --version-id "$OLD_V" \
                    --profile "$AWS_PROFILE" > /dev/null 2>&1 || true
            done
            aws iam create-policy-version \
                --policy-arn "$POLICY_ARN" \
                --policy-document "$POLICY_DOC" \
                --set-as-default \
                --profile "$AWS_PROFILE" > /dev/null
            log_ok "IAM policy updated"
        fi
    fi

    # --- Role ---
    local TRUST_POLICY
    TRUST_POLICY=$(cat <<TRUSTJSON
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Federated": "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/${OIDC_PROVIDER}"
            },
            "Action": "sts:AssumeRoleWithWebIdentity",
            "Condition": {
                "StringEquals": {
                    "${OIDC_PROVIDER}:aud": "sts.amazonaws.com",
                    "${OIDC_PROVIDER}:sub": "system:serviceaccount:${VELERO_NAMESPACE}:${VELERO_SA}"
                }
            }
        }
    ]
}
TRUSTJSON
    )

    if aws iam get-role --role-name "$IAM_ROLE_NAME" --profile "$AWS_PROFILE" > /dev/null 2>&1; then
        log_ok "IAM role $IAM_ROLE_NAME already exists"
        aws iam update-assume-role-policy \
            --role-name "$IAM_ROLE_NAME" \
            --policy-document "$TRUST_POLICY" \
            --profile "$AWS_PROFILE" 2>/dev/null && log_ok "Trust policy updated" || log_warn "Could not update trust policy (may need admin)"
    else
        log_info "Creating IAM role $IAM_ROLE_NAME"
        aws iam create-role \
            --role-name "$IAM_ROLE_NAME" \
            --assume-role-policy-document "$TRUST_POLICY" \
            --profile "$AWS_PROFILE" > /dev/null
        log_ok "IAM role created"
    fi

    if aws iam list-attached-role-policies --role-name "$IAM_ROLE_NAME" --profile "$AWS_PROFILE" \
        --query "AttachedPolicies[?PolicyArn=='${POLICY_ARN}'].PolicyArn" --output text 2>/dev/null | grep -q "$POLICY_ARN"; then
        log_ok "Policy already attached to role"
    else
        aws iam attach-role-policy \
            --role-name "$IAM_ROLE_NAME" \
            --policy-arn "$POLICY_ARN" \
            --profile "$AWS_PROFILE" 2>/dev/null && log_ok "Policy attached to role" || log_warn "Could not attach policy (may need admin)"
    fi

    ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${IAM_ROLE_NAME}"
}

install_velero() {
    echo ""
    echo -e "${CYAN}── Velero Installation ──${NC}"

    local ACCOUNT_ID
    ACCOUNT_ID=$(get_account_id)
    ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${IAM_ROLE_NAME}"

    if kubectl get namespace "$VELERO_NAMESPACE" > /dev/null 2>&1; then
        log_warn "Velero namespace exists — checking if already installed"
        if kubectl get deployment velero -n "$VELERO_NAMESPACE" > /dev/null 2>&1; then
            log_ok "Velero deployment already exists"
            log_info "Ensuring SA annotation and BSL region are correct"
            kubectl annotate serviceaccount "$VELERO_SA" -n "$VELERO_NAMESPACE" \
                "eks.amazonaws.com/role-arn=${ROLE_ARN}" --overwrite > /dev/null
            log_ok "Service account annotated with IRSA role"

            kubectl patch backupstoragelocation default -n "$VELERO_NAMESPACE" \
                --type merge -p "{\"spec\":{\"objectStorage\":{\"bucket\":\"${BUCKET_NAME}\"},\"config\":{\"region\":\"${REGION}\"}}}" > /dev/null 2>&1 || true
            kubectl patch volumesnapshotlocation default -n "$VELERO_NAMESPACE" \
                --type merge -p "{\"spec\":{\"config\":{\"region\":\"${REGION}\"}}}" > /dev/null 2>&1 || true
            log_ok "BSL bucket set to $BUCKET_NAME, region set to $REGION"

            log_info "Restarting Velero to pick up changes"
            kubectl scale deploy velero -n "$VELERO_NAMESPACE" --replicas=0 > /dev/null 2>&1
            sleep 5
            kubectl scale deploy velero -n "$VELERO_NAMESPACE" --replicas=1 > /dev/null 2>&1
            sleep 15
            log_ok "Velero restarted"
            return
        fi
    fi

    log_info "Installing Velero via CLI"
    velero install \
        --provider aws \
        --plugins "velero/velero-plugin-for-aws:${VELERO_PLUGIN_VERSION}" \
        --bucket "$BUCKET_NAME" \
        --backup-location-config "region=${REGION}" \
        --snapshot-location-config "region=${REGION}" \
        --no-secret \
        --sa-annotations "eks.amazonaws.com/role-arn=${ROLE_ARN}" \
        --wait

    log_ok "Velero installed"
}

do_verify() {
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo "  Velero Backup Verification"
    echo "═══════════════════════════════════════════════════════════"

    local PASS=0
    local FAIL=0

    echo ""
    echo -e "${CYAN}── S3 Bucket ──${NC}"
    if aws s3api head-bucket --bucket "$BUCKET_NAME" --profile "$AWS_PROFILE" --region "$REGION" > /dev/null 2>&1; then
        log_ok "Bucket: $BUCKET_NAME (accessible)"
        PASS=$((PASS + 1))
    else
        log_fail "Bucket: $BUCKET_NAME (not accessible)"
        FAIL=$((FAIL + 1))
    fi

    echo ""
    echo -e "${CYAN}── IAM ──${NC}"
    local ACCOUNT_ID
    ACCOUNT_ID=$(get_account_id)
    local POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${IAM_POLICY_NAME}"

    if aws iam get-policy --policy-arn "$POLICY_ARN" --profile "$AWS_PROFILE" > /dev/null 2>&1; then
        log_ok "IAM Policy: $IAM_POLICY_NAME"
        PASS=$((PASS + 1))
    else
        log_fail "IAM Policy: $IAM_POLICY_NAME (not found)"
        FAIL=$((FAIL + 1))
    fi

    if aws iam get-role --role-name "$IAM_ROLE_NAME" --profile "$AWS_PROFILE" > /dev/null 2>&1; then
        log_ok "IAM Role: $IAM_ROLE_NAME"
        PASS=$((PASS + 1))
    else
        log_fail "IAM Role: $IAM_ROLE_NAME (not found)"
        FAIL=$((FAIL + 1))
    fi

    echo ""
    echo -e "${CYAN}── Kubernetes ──${NC}"
    if kubectl get namespace "$VELERO_NAMESPACE" > /dev/null 2>&1; then
        log_ok "Namespace: $VELERO_NAMESPACE"
        PASS=$((PASS + 1))
    else
        log_fail "Namespace: $VELERO_NAMESPACE (not found)"
        FAIL=$((FAIL + 1))
        echo ""
        echo -e "  Passed: ${GREEN}${PASS}${NC}  Failed: ${RED}${FAIL}${NC}"
        return
    fi

    local POD_STATUS
    POD_STATUS=$(kubectl get pods -n "$VELERO_NAMESPACE" -l component=velero -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "NotFound")
    if [ "$POD_STATUS" = "Running" ]; then
        log_ok "Velero pod: Running"
        PASS=$((PASS + 1))
    else
        log_fail "Velero pod: $POD_STATUS"
        FAIL=$((FAIL + 1))
    fi

    local SA_ROLE
    SA_ROLE=$(kubectl get sa "$VELERO_SA" -n "$VELERO_NAMESPACE" -o jsonpath='{.metadata.annotations.eks\.amazonaws\.com/role-arn}' 2>/dev/null || echo "")
    if [ -n "$SA_ROLE" ]; then
        log_ok "IRSA annotation: ${SA_ROLE##*/}"
        PASS=$((PASS + 1))
    else
        log_fail "IRSA annotation: missing"
        FAIL=$((FAIL + 1))
    fi

    echo ""
    echo -e "${CYAN}── BackupStorageLocation ──${NC}"
    local BSL_PHASE
    BSL_PHASE=$(kubectl get backupstoragelocation default -n "$VELERO_NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || echo "NotFound")
    if [ "$BSL_PHASE" = "Available" ]; then
        log_ok "BSL 'default': Available"
        PASS=$((PASS + 1))
    else
        log_fail "BSL 'default': $BSL_PHASE"
        FAIL=$((FAIL + 1))
        local BSL_MSG
        BSL_MSG=$(kubectl get backupstoragelocation default -n "$VELERO_NAMESPACE" -o jsonpath='{.status.message}' 2>/dev/null || echo "")
        if [ -n "$BSL_MSG" ]; then
            echo -e "      ${RED}${BSL_MSG}${NC}"
        fi
    fi

    local BSL_REGION
    BSL_REGION=$(kubectl get backupstoragelocation default -n "$VELERO_NAMESPACE" -o jsonpath='{.spec.config.region}' 2>/dev/null || echo "")
    if [ "$BSL_REGION" = "$REGION" ]; then
        log_ok "BSL region: $BSL_REGION"
        PASS=$((PASS + 1))
    else
        log_fail "BSL region: $BSL_REGION (expected $REGION)"
        FAIL=$((FAIL + 1))
    fi

    local BSL_BUCKET
    BSL_BUCKET=$(kubectl get backupstoragelocation default -n "$VELERO_NAMESPACE" -o jsonpath='{.spec.objectStorage.bucket}' 2>/dev/null || echo "")
    if [ "$BSL_BUCKET" = "$BUCKET_NAME" ]; then
        log_ok "BSL bucket: $BSL_BUCKET"
        PASS=$((PASS + 1))
    else
        log_fail "BSL bucket: $BSL_BUCKET (expected $BUCKET_NAME)"
        FAIL=$((FAIL + 1))
    fi

    echo ""
    echo -e "${CYAN}── Recent Backups ──${NC}"
    local BACKUP_COUNT
    BACKUP_COUNT=$(velero backup get -o json 2>/dev/null | python3 -c "import sys,json; items=json.load(sys.stdin).get('items',[]); print(len(items))" 2>/dev/null || echo "0")
    log_info "Total backups: $BACKUP_COUNT"

    if [ "$BACKUP_COUNT" -gt 0 ]; then
        velero backup get 2>/dev/null | head -6
    fi

    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo -e "  Passed: ${GREEN}${PASS}${NC}  Failed: ${RED}${FAIL}${NC}"
    echo "═══════════════════════════════════════════════════════════"

    if [ "$FAIL" -gt 0 ]; then
        return 1
    fi
}

do_backup() {
    local BACKUP_NAME="${1:-manual-$(date +%Y%m%d-%H%M%S)}"

    echo ""
    echo -e "${CYAN}── Creating Backup: ${BACKUP_NAME} ──${NC}"

    velero backup create "$BACKUP_NAME" \
        --exclude-namespaces velero,kube-system \
        --exclude-resources customresourcedefinitions \
        --wait
    echo ""
    velero backup describe "$BACKUP_NAME" | head -20
    echo ""

    local PHASE
    PHASE=$(velero backup get "$BACKUP_NAME" -o json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',{}).get('phase','Unknown'))" 2>/dev/null || echo "Unknown")
    if [ "$PHASE" = "Completed" ]; then
        log_ok "Backup $BACKUP_NAME: $PHASE"
    else
        log_fail "Backup $BACKUP_NAME: $PHASE"
        return 1
    fi
}

do_teardown() {
    echo ""
    echo -e "${RED}── Velero Teardown ──${NC}"
    echo ""
    read -rp "  This will uninstall Velero and remove IAM resources. Continue? [y/N] " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo "  Aborted."
        return 0
    fi

    log_info "Uninstalling Velero"
    velero uninstall --force 2>/dev/null || true
    log_ok "Velero uninstalled"

    local ACCOUNT_ID
    ACCOUNT_ID=$(get_account_id)
    local POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${IAM_POLICY_NAME}"

    log_info "Detaching policy from role"
    aws iam detach-role-policy --role-name "$IAM_ROLE_NAME" --policy-arn "$POLICY_ARN" --profile "$AWS_PROFILE" 2>/dev/null || true

    log_info "Deleting IAM role $IAM_ROLE_NAME"
    aws iam delete-role --role-name "$IAM_ROLE_NAME" --profile "$AWS_PROFILE" 2>/dev/null || true
    log_ok "Role deleted"

    log_info "Deleting IAM policy $IAM_POLICY_NAME"
    aws iam delete-policy --policy-arn "$POLICY_ARN" --profile "$AWS_PROFILE" 2>/dev/null || true
    log_ok "Policy deleted"

    log_warn "S3 bucket $BUCKET_NAME was NOT deleted (contains backup data)"
}

do_list_backups() {
    echo ""
    echo -e "${CYAN}── Available Backups ──${NC}"
    echo ""

    local BACKUP_OUTPUT
    BACKUP_OUTPUT=$(velero backup get 2>/dev/null || kubectl get backups -n velero 2>/dev/null || true)

    if [ -z "$BACKUP_OUTPUT" ] || echo "$BACKUP_OUTPUT" | grep -qi "no backups found\|No resources found"; then
        log_warn "No backups found"
        return 0
    fi

    local BACKUP_COUNT
    BACKUP_COUNT=$(echo "$BACKUP_OUTPUT" | tail -n +2 | grep -c . || echo "0")

    log_info "$BACKUP_COUNT backup(s) found:"
    echo ""
    echo "$BACKUP_OUTPUT"
    echo ""

    log_info "To restore from a backup:"
    echo "    ./setup-velero-backup.sh restore <BACKUP_NAME>"
    echo "    ./setup-velero-backup.sh restore-ns <BACKUP_NAME> <NAMESPACE>"
}

_show_restore_result() {
    local RESTORE_NAME="$1"
    echo ""
    local RESTORE_PHASE
    RESTORE_PHASE=$(velero restore get "$RESTORE_NAME" -o json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',{}).get('phase','Unknown'))" 2>/dev/null || echo "Unknown")

    if [ "$RESTORE_PHASE" = "Completed" ]; then
        log_ok "Restore $RESTORE_NAME: $RESTORE_PHASE"
    elif [ "$RESTORE_PHASE" = "PartiallyFailed" ]; then
        log_warn "Restore $RESTORE_NAME: $RESTORE_PHASE (some resources may have been skipped)"
        log_info "Run 'velero restore describe $RESTORE_NAME' for details"
    else
        log_fail "Restore $RESTORE_NAME: $RESTORE_PHASE"
        log_info "Run 'velero restore describe $RESTORE_NAME' for details"
        return 1
    fi

    echo ""
    log_info "Restore summary:"
    velero restore describe "$RESTORE_NAME" 2>/dev/null | grep -A5 "Phase\|Warnings\|Errors" | head -15
}

do_restore() {
    local BACKUP_NAME="${1:-}"
    local FORCE_UPDATE="${2:-}"
    if [ -z "$BACKUP_NAME" ]; then
        log_fail "Usage: $0 restore <BACKUP_NAME> [--force]"
        echo ""
        log_info "Available backups:"
        velero backup get 2>/dev/null || true
        return 1
    fi

    local BACKUP_PHASE
    BACKUP_PHASE=$(velero backup get "$BACKUP_NAME" -o json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',{}).get('phase','Unknown'))" 2>/dev/null || echo "NotFound")

    if [ "$BACKUP_PHASE" = "NotFound" ]; then
        log_fail "Backup '$BACKUP_NAME' not found"
        echo ""
        log_info "Available backups:"
        velero backup get 2>/dev/null || true
        return 1
    fi

    if [ "$BACKUP_PHASE" != "Completed" ]; then
        log_warn "Backup '$BACKUP_NAME' phase is '$BACKUP_PHASE' (expected Completed)"
        read -rp "  Continue anyway? [y/N] " confirm
        if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
            echo "  Aborted."
            return 0
        fi
    fi

    echo ""
    echo -e "${CYAN}── Full Cluster Restore from: ${BACKUP_NAME} ──${NC}"
    echo ""
    if [ "$FORCE_UPDATE" = "--force" ]; then
        log_warn "FORCE mode: existing resources will be OVERWRITTEN with backup versions."
    else
        log_info "Existing resources that already exist will be skipped."
        log_info "Use '$0 restore $BACKUP_NAME --force' to overwrite existing resources."
    fi
    echo ""
    read -rp "  Proceed with restore? [y/N] " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo "  Aborted."
        return 0
    fi

    local RESTORE_NAME="restore-${BACKUP_NAME}-$(date +%H%M%S)"
    log_info "Creating restore: $RESTORE_NAME"
    local RESTORE_CMD=(velero restore create "$RESTORE_NAME"
        --from-backup "$BACKUP_NAME"
        --exclude-namespaces velero,kube-system
        --exclude-resources customresourcedefinitions,pods,replicasets
    )
    if [ "$FORCE_UPDATE" = "--force" ]; then
        RESTORE_CMD+=(--existing-resource-policy update)
    fi
    RESTORE_CMD+=(--wait)
    "${RESTORE_CMD[@]}"

    _show_restore_result "$RESTORE_NAME"
}

do_restore_namespace() {
    local BACKUP_NAME="${1:-}"
    local TARGET_NS="${2:-}"
    local FORCE_UPDATE="${3:-}"

    if [ -z "$BACKUP_NAME" ] || [ -z "$TARGET_NS" ]; then
        log_fail "Usage: $0 restore-ns <BACKUP_NAME> <NAMESPACE> [--force]"
        echo ""
        log_info "Available backups:"
        velero backup get 2>/dev/null || true
        return 1
    fi

    local BACKUP_PHASE
    BACKUP_PHASE=$(velero backup get "$BACKUP_NAME" -o json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',{}).get('phase','Unknown'))" 2>/dev/null || echo "NotFound")

    if [ "$BACKUP_PHASE" = "NotFound" ]; then
        log_fail "Backup '$BACKUP_NAME' not found"
        return 1
    fi

    echo ""
    echo -e "${CYAN}── Namespace Restore: ${TARGET_NS} from ${BACKUP_NAME} ──${NC}"
    echo ""
    if [ "$FORCE_UPDATE" = "--force" ]; then
        log_warn "FORCE mode: existing resources in '$TARGET_NS' will be OVERWRITTEN."
    else
        log_info "Existing resources that already exist will be skipped."
        log_info "Use '$0 restore-ns $BACKUP_NAME $TARGET_NS --force' to overwrite."
    fi
    echo ""
    read -rp "  Proceed? [y/N] " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo "  Aborted."
        return 0
    fi

    local RESTORE_NAME="restore-${TARGET_NS}-$(date +%H%M%S)"
    log_info "Creating restore: $RESTORE_NAME (namespace: $TARGET_NS)"
    local RESTORE_CMD=(velero restore create "$RESTORE_NAME"
        --from-backup "$BACKUP_NAME"
        --include-namespaces "$TARGET_NS"
        --exclude-resources pods,replicasets
    )
    if [ "$FORCE_UPDATE" = "--force" ]; then
        RESTORE_CMD+=(--existing-resource-policy update)
    fi
    RESTORE_CMD+=(--wait)
    "${RESTORE_CMD[@]}"

    _show_restore_result "$RESTORE_NAME"

    echo ""
    log_info "Pods in $TARGET_NS (recreated by controllers):"
    kubectl get pods -n "$TARGET_NS" --no-headers 2>/dev/null | head -10 || true
}

# ── Main ──

COMMAND="${1:-}"
shift || true

case "$COMMAND" in
    setup)
        echo ""
        echo "=============================================="
        echo "  Velero Backup Setup - ${CLUSTER_NAME}"
        echo "=============================================="
        switch_context
        setup_s3_bucket
        setup_iam
        install_velero
        do_verify
        ;;
    verify)
        echo ""
        echo "=============================================="
        echo "  Velero Backup Verify - ${CLUSTER_NAME}"
        echo "=============================================="
        switch_context
        do_verify
        ;;
    teardown)
        echo ""
        echo "=============================================="
        echo "  Velero Backup Teardown - ${CLUSTER_NAME}"
        echo "=============================================="
        switch_context
        do_teardown
        ;;
    backup)
        echo ""
        echo "=============================================="
        echo "  Velero Backup - ${CLUSTER_NAME}"
        echo "=============================================="
        switch_context
        do_backup "$@"
        ;;
    list-backups|list)
        echo ""
        echo "=============================================="
        echo "  Velero Backups - ${CLUSTER_NAME}"
        echo "=============================================="
        switch_context
        do_list_backups
        ;;
    restore)
        echo ""
        echo "=============================================="
        echo "  Velero Restore - ${CLUSTER_NAME}"
        echo "=============================================="
        switch_context
        do_restore "$@"
        ;;
    restore-ns|restore-namespace)
        echo ""
        echo "=============================================="
        echo "  Velero Namespace Restore - ${CLUSTER_NAME}"
        echo "=============================================="
        switch_context
        do_restore_namespace "$@"
        ;;
    --help|-h|help)
        show_help
        ;;
    *)
        echo "Unknown command: $COMMAND"
        echo ""
        show_help
        exit 1
        ;;
esac

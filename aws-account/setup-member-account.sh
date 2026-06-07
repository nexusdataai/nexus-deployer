#!/bin/bash
#
# AWS Member Account Setup (member-side, root-key driven)
#
# Runs ENTIRELY inside the member account with its root access key/secret.
# Never talks to the management account. Drives the in-account
# configuration end-to-end:
#
#   Phase 0  validate root keys + account identity
#   Phase 1  identity baseline      (password policy, Access Analyzer,
#                                    optional IAM admin user via
#                                    aws-iam-bootstrap.sh)
#   Phase 2  security baseline      (S3 BPA, EBS encryption, IMDSv2,
#                                    CloudTrail, GuardDuty, Security Hub,
#                                    AWS Config)
#   Phase 3  region lockdown        (delete default VPCs in all regions,
#                                    disable opt-in regions != allowed)
#   Phase 4  billing visibility     (cost-allocation tags, monthly Budget,
#                                    CloudWatch billing alarm)
#   Phase 5  NexusClusterProvisioner cross-account role (mgmt-account
#                                    trust + ExternalId + permission
#                                    boundary; uses existing
#                                    policies/cross-account-provisioner-*.json)
#   Phase 6  revoke bootstrap root access key (optional)
#   Phase 7  emit manifest JSON to audit-logs/
#
# Operator + App IRSA roles are NOT created here -- they require the EKS
# OIDC provider and are produced by
# deploy/eks/create-hardened-eks-cluster.sh Step 4 once the cluster exists.
#
# Usage:
#   ./setup-member-account.sh \
#       --account-id 040740747817 \
#       --root-access-key-id "$ROOT_AK" \
#       --root-secret-access-key "$ROOT_SK" \
#       --management-account-id 654654554404 \
#       [--external-id <secret>]              # default: nexus-provision-<YYYY>
#       [--allowed-region us-east-1]
#       [--budget-email papu@ptrtechnology.com]
#       [--monthly-budget-usd 100]
#       [--create-iam-admin-user papu]
#       [--keep-root-key]
#       [--skip-region-lockdown]
#       [--auto-approve] [--dry-run]
#
# Root keys may also come from .env.member.local (gitignored) or env vars:
#   ROOT_AK, ROOT_SK, ROOT_TOKEN, or AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
#

set -e
set +x  # never echo commands; secrets may be in env

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
POLICIES_DIR="${SCRIPT_DIR}/policies"
AUDIT_LOG_DIR="${SCRIPT_DIR}/audit-logs"

# ── Optional config file (.env.member.local) ────────────────────────────────
#
# Same convention as aws-iam-bootstrap.sh. CLI flag > parent-shell env > file.
#
# Tolerant parser: accepts BOTH UPPER_SNAKE_CASE keys (bash-style, e.g.
# ROOT_AK, MANAGEMENT_ACCOUNT_ID) AND CLI-flag-style hyphenated keys
# (e.g. account-id, management-account-id, dry-run). We can't `source`
# the file because hyphens aren't valid bash identifiers; instead we
# read key=value lines, normalize the key (lower/hyphen -> upper/underscore),
# and route via case. AWS_ACCESS_KEY_ID/_SECRET_ACCESS_KEY/_SESSION_TOKEN
# are aliased to ROOT_AK/_SK/_TOKEN. Lines starting with '#' and blank
# lines are ignored. Unknown keys produce a warning, not a fatal error.
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env.member.local}"
if [[ -f "${ENV_FILE}" ]]; then
    _perms=$(stat -c '%a' "${ENV_FILE}" 2>/dev/null || echo "")
    if [[ -n "${_perms}" && "${_perms}" != "600" && "${_perms}" != "400" ]]; then
        echo "[WARN] ${ENV_FILE} permissions are ${_perms}; expected 600. Run: chmod 600 ${ENV_FILE}" >&2
    fi
    unset _perms

    while IFS= read -r _line || [[ -n "${_line}" ]]; do
        # strip CR for CRLF line endings
        _line="${_line%$'\r'}"
        # skip blank / comment lines
        [[ -z "${_line// }" ]] && continue
        [[ "${_line}" =~ ^[[:space:]]*# ]] && continue
        # require key=value
        [[ "${_line}" != *=* ]] && continue

        _k="${_line%%=*}"
        _v="${_line#*=}"
        # trim whitespace around key and value
        _k="${_k#"${_k%%[![:space:]]*}"}"
        _k="${_k%"${_k##*[![:space:]]}"}"
        _v="${_v#"${_v%%[![:space:]]*}"}"
        _v="${_v%"${_v##*[![:space:]]}"}"
        # strip a single layer of matching outer quotes
        if [[ "${_v}" == \"*\" ]]; then _v="${_v#\"}"; _v="${_v%\"}"
        elif [[ "${_v}" == \'*\' ]]; then _v="${_v#\'}"; _v="${_v%\'}"
        fi

        # Normalize: lowercase/hyphens -> uppercase/underscores.
        # E.g. management-account-id -> MANAGEMENT_ACCOUNT_ID.
        _norm=$(echo "${_k}" | tr '[:lower:]-' '[:upper:]_')

        case "${_norm}" in
            ACCOUNT_ID)              ACCOUNT_ID="${ACCOUNT_ID:-${_v}}" ;;
            MANAGEMENT_ACCOUNT_ID)   MANAGEMENT_ACCOUNT_ID="${MANAGEMENT_ACCOUNT_ID:-${_v}}" ;;
            EXTERNAL_ID)             EXTERNAL_ID="${EXTERNAL_ID:-${_v}}" ;;
            ALLOWED_REGION|REGION)   ALLOWED_REGION="${ALLOWED_REGION:-${_v}}" ;;
            BUDGET_EMAIL)            BUDGET_EMAIL="${BUDGET_EMAIL:-${_v}}" ;;
            MONTHLY_BUDGET_USD)      MONTHLY_BUDGET_USD="${MONTHLY_BUDGET_USD:-${_v}}" ;;
            CREATE_IAM_ADMIN_USER)   CREATE_IAM_ADMIN_USER="${CREATE_IAM_ADMIN_USER:-${_v}}" ;;
            KEEP_ROOT_KEY)           KEEP_ROOT_KEY="${KEEP_ROOT_KEY:-${_v}}" ;;
            SKIP_REGION_LOCKDOWN)    SKIP_REGION_LOCKDOWN="${SKIP_REGION_LOCKDOWN:-${_v}}" ;;
            AUTO_APPROVE)            AUTO_APPROVE="${AUTO_APPROVE:-${_v}}" ;;
            DRY_RUN)                 DRY_RUN="${DRY_RUN:-${_v}}" ;;
            ROOT_AK)                 ROOT_AK="${ROOT_AK:-${_v}}" ;;
            ROOT_SK)                 ROOT_SK="${ROOT_SK:-${_v}}" ;;
            ROOT_TOKEN)              ROOT_TOKEN="${ROOT_TOKEN:-${_v}}" ;;
            AWS_ACCESS_KEY_ID)       ROOT_AK="${ROOT_AK:-${_v}}" ;;
            AWS_SECRET_ACCESS_KEY)   ROOT_SK="${ROOT_SK:-${_v}}" ;;
            AWS_SESSION_TOKEN)       ROOT_TOKEN="${ROOT_TOKEN:-${_v}}" ;;
            *)
                echo "[WARN] ${ENV_FILE}: unknown key '${_k}'; ignoring." >&2
                ;;
        esac
    done < "${ENV_FILE}"
    unset _line _k _v _norm

    # Scrub AWS-standard names so they cannot leak into aws-cli calls that
    # bypass aws_as_root. Every subsequent aws call goes through aws_as_root.
    unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN

    _LOADED_ENV_FILE="${ENV_FILE}"
fi

# ── Defaults ────────────────────────────────────────────────────────────────

ACCOUNT_ID="${ACCOUNT_ID:-}"
ROOT_AK="${ROOT_AK:-}"
ROOT_SK="${ROOT_SK:-}"
ROOT_TOKEN="${ROOT_TOKEN:-}"
MANAGEMENT_ACCOUNT_ID="${MANAGEMENT_ACCOUNT_ID:-}"
# Empty by default: trust scoped by Principal only (any identity in the
# management account with sts:AssumeRole IAM perms, e.g. an SSO user with
# AdministratorAccess). Set to a non-empty secret to add an extra
# sts:ExternalId check; the assume-role caller must then pass
# --external-id <value>.
EXTERNAL_ID="${EXTERNAL_ID:-}"
ALLOWED_REGION="${ALLOWED_REGION:-us-east-1}"
BUDGET_EMAIL="${BUDGET_EMAIL:-}"
MONTHLY_BUDGET_USD="${MONTHLY_BUDGET_USD:-100}"
CREATE_IAM_ADMIN_USER="${CREATE_IAM_ADMIN_USER:-}"
KEEP_ROOT_KEY="${KEEP_ROOT_KEY:-no}"
SKIP_REGION_LOCKDOWN="${SKIP_REGION_LOCKDOWN:-no}"
AUTO_APPROVE="${AUTO_APPROVE:-no}"
DRY_RUN="${DRY_RUN:-no}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --account-id)               ACCOUNT_ID="$2"; shift 2 ;;
        --root-access-key-id)       ROOT_AK="$2"; shift 2 ;;
        --root-secret-access-key)   ROOT_SK="$2"; shift 2 ;;
        --root-session-token)       ROOT_TOKEN="$2"; shift 2 ;;
        --management-account-id)    MANAGEMENT_ACCOUNT_ID="$2"; shift 2 ;;
        --external-id)              EXTERNAL_ID="$2"; shift 2 ;;
        --allowed-region)           ALLOWED_REGION="$2"; shift 2 ;;
        --budget-email)             BUDGET_EMAIL="$2"; shift 2 ;;
        --monthly-budget-usd)       MONTHLY_BUDGET_USD="$2"; shift 2 ;;
        --create-iam-admin-user)    CREATE_IAM_ADMIN_USER="$2"; shift 2 ;;
        --keep-root-key)            KEEP_ROOT_KEY=yes; shift ;;
        --skip-region-lockdown)     SKIP_REGION_LOCKDOWN=yes; shift ;;
        --auto-approve)             AUTO_APPROVE=yes; shift ;;
        --dry-run)                  DRY_RUN=yes; shift ;;
        --help|-h)
            sed -n '2,52p' "$0"
            exit 0
            ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# Strip any AWS_PROFILE / AWS_SESSION_TOKEN the parent shell may have set
# so they cannot leak into aws_as_root invocations.
unset AWS_PROFILE AWS_DEFAULT_PROFILE

# ── Logging (stderr-only; stdout reserved for any future structured output) ──

log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >&2; }
info() { log "INFO  $*"; }
warn() { log "WARN  $*"; }
err()  { log "ERROR $*"; }

VALIDATION_PASSED=no
die() {
    err "$*"
    if [[ "${VALIDATION_PASSED}" == "yes" ]]; then
        emit_manifest "failed" "$*"
    fi
    exit 1
}

confirm() {
    if [[ "${AUTO_APPROVE}" == "yes" ]]; then return 0; fi
    read -r -p "$1 [y/N]: " response
    [[ "$response" =~ ^[Yy]$ ]]
}

# ── aws_as_root: every AWS call goes through here ──────────────────────────
#
# Same defensive measures as aws-iam-bootstrap.sh:aws_as_root:
#   - Inline VAR=value style (no `env -u` quirks under some terminals).
#   - AWS_PAGER="" + --no-cli-pager to kill the v2 pager.
#   - AWS_EC2_METADATA_DISABLED=true so the CLI doesn't hang on IMDS.
#   - --cli-connect-timeout / --cli-read-timeout to bound network hangs.
#   - stdin closed so it can never sit waiting for a prompt.
#   - timeout 60 as overall watchdog (slightly higher than aws-iam-bootstrap
#     because some calls here -- e.g. enabling SecurityHub default
#     standards -- legitimately take 30-45 s).
#
# Default region is ALLOWED_REGION. Pass `--region X` as args to override
# for cross-region calls (region-list traversal in Phase 3, CloudWatch
# billing alarm in us-east-1).
aws_as_root() {
    if [[ "${DRY_RUN}" == "yes" ]]; then
        echo "DRY-RUN: aws --region ${ALLOWED_REGION} $*" >&2
        return 0
    fi
    if [[ -n "${ROOT_TOKEN}" ]]; then
        AWS_ACCESS_KEY_ID="${ROOT_AK}" \
        AWS_SECRET_ACCESS_KEY="${ROOT_SK}" \
        AWS_SESSION_TOKEN="${ROOT_TOKEN}" \
        AWS_PAGER="" \
        AWS_EC2_METADATA_DISABLED=true \
        timeout 60 aws --region "${ALLOWED_REGION}" \
            --cli-connect-timeout 10 \
            --cli-read-timeout 30 \
            --no-cli-pager \
            "$@" </dev/null
    else
        AWS_ACCESS_KEY_ID="${ROOT_AK}" \
        AWS_SECRET_ACCESS_KEY="${ROOT_SK}" \
        AWS_PAGER="" \
        AWS_EC2_METADATA_DISABLED=true \
        timeout 60 aws --region "${ALLOWED_REGION}" \
            --cli-connect-timeout 10 \
            --cli-read-timeout 30 \
            --no-cli-pager \
            "$@" </dev/null
    fi
}

# ── Manifest accumulator ────────────────────────────────────────────────────

MANIFEST_TS=""
MANIFEST_PATH=""
declare -a STEPS
PROVISIONER_ROLE_ARN=""

json_escape() {
    python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))" <<< "$1"
}

record_step() {
    local name="$1" status="$2" detail="$3"
    local detail_esc
    detail_esc=$(json_escape "${detail}")
    STEPS+=("{\"step\":\"${name}\",\"status\":\"${status}\",\"detail\":${detail_esc}}")
    info "  step ${name}: ${status} -- ${detail}"
}

emit_manifest() {
    local overall_status="$1" overall_detail="${2:-}"
    mkdir -p "${AUDIT_LOG_DIR}"

    if [[ -z "${MANIFEST_PATH}" ]]; then
        MANIFEST_TS=$(date -u +%Y%m%dT%H%M%SZ)
        MANIFEST_PATH="${AUDIT_LOG_DIR}/setup-member-${ACCOUNT_ID}-${MANIFEST_TS}.json"
    fi

    local steps_joined
    steps_joined=$(IFS=,; echo "${STEPS[*]}")

    local overall_detail_esc
    overall_detail_esc=$(json_escape "${overall_detail}")

    cat > "${MANIFEST_PATH}" <<EOF
{
  "schema_version": "1.0",
  "tool": "setup-member-account.sh",
  "timestamp_utc": "${MANIFEST_TS}",
  "overall_status": "${overall_status}",
  "overall_detail": ${overall_detail_esc},
  "dry_run": $( [[ "${DRY_RUN}" == "yes" ]] && echo true || echo false ),
  "account_id": "${ACCOUNT_ID}",
  "management_account_id": "${MANAGEMENT_ACCOUNT_ID}",
  "allowed_region": "${ALLOWED_REGION}",
  "external_id": "${EXTERNAL_ID}",
  "provisioner_role_arn": $( [[ -n "${PROVISIONER_ROLE_ARN}" ]] && json_escape "${PROVISIONER_ROLE_ARN}" || echo null ),
  "iam_admin_user": $( [[ -n "${CREATE_IAM_ADMIN_USER}" ]] && json_escape "${CREATE_IAM_ADMIN_USER}" || echo null ),
  "monthly_budget_usd": ${MONTHLY_BUDGET_USD},
  "budget_email": $( [[ -n "${BUDGET_EMAIL}" ]] && json_escape "${BUDGET_EMAIL}" || echo null ),
  "root_key_revoked": $( [[ "${KEEP_ROOT_KEY}" == "yes" ]] && echo false || echo true ),
  "region_lockdown_applied": $( [[ "${SKIP_REGION_LOCKDOWN}" == "yes" ]] && echo false || echo true ),
  "phases": [${steps_joined}]
}
EOF
    info "Manifest written: ${MANIFEST_PATH}"
}

# ── Phase 0: Validate ───────────────────────────────────────────────────────

phase0_validate() {
    info ""
    info "── Phase 0: Validate inputs and root credentials ──"

    [[ -n "${ACCOUNT_ID}" ]] || die "--account-id is required"
    [[ "${ACCOUNT_ID}" =~ ^[0-9]{12}$ ]] || die "--account-id must be a 12-digit AWS account ID"
    [[ -n "${ROOT_AK}" ]] || die "--root-access-key-id (or ROOT_AK env var) is required"
    [[ -n "${ROOT_SK}" ]] || die "--root-secret-access-key (or ROOT_SK env var) is required"
    [[ -n "${MANAGEMENT_ACCOUNT_ID}" ]] || die "--management-account-id is required"
    [[ "${MANAGEMENT_ACCOUNT_ID}" =~ ^[0-9]{12}$ ]] || die "--management-account-id must be a 12-digit AWS account ID"
    [[ "${MANAGEMENT_ACCOUNT_ID}" != "${ACCOUNT_ID}" ]] || die "--management-account-id and --account-id must differ"

    [[ ${#ROOT_AK} -ge 16 ]] || die "Root access key is suspiciously short (${#ROOT_AK} chars). Re-check --root-access-key-id."
    [[ ${#ROOT_SK} -ge 30 ]] || die "Root secret key is suspiciously short (${#ROOT_SK} chars). Re-check --root-secret-access-key."

    [[ -f "${POLICIES_DIR}/cross-account-provisioner-role.json" ]] \
        || die "Missing ${POLICIES_DIR}/cross-account-provisioner-role.json"
    [[ -f "${POLICIES_DIR}/cross-account-provisioner-policy.json" ]] \
        || die "Missing ${POLICIES_DIR}/cross-account-provisioner-policy.json"

    if [[ -n "${CREATE_IAM_ADMIN_USER}" ]]; then
        [[ -f "${SCRIPT_DIR}/aws-iam-bootstrap.sh" ]] \
            || die "Missing ${SCRIPT_DIR}/aws-iam-bootstrap.sh (required by --create-iam-admin-user)"
    fi

    # Confirm we can actually call AWS with these keys, the account matches,
    # and the identity is the root user (not a stray IAM user).
    info "  Calling sts get-caller-identity (45 s timeout)..."
    if [[ "${DRY_RUN}" == "yes" ]]; then
        info "  DRY-RUN: skipping sts get-caller-identity"
        record_step "phase0_validate" "dry_run" "validations passed"
        VALIDATION_PASSED=yes
        return
    fi

    local raw rc
    raw=$(aws_as_root sts get-caller-identity --output json 2>&1) || rc=$?
    rc=${rc:-0}
    if [[ ${rc} -ne 0 ]]; then
        die "sts get-caller-identity failed (rc=${rc}): ${raw}"
    fi

    local caller_account arn
    caller_account=$(echo "${raw}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('Account',''))" 2>/dev/null || echo "")
    arn=$(echo "${raw}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('Arn',''))" 2>/dev/null || echo "")

    [[ -n "${caller_account}" ]] || die "Could not parse Account from sts response: ${raw:0:300}"
    [[ "${caller_account}" == "${ACCOUNT_ID}" ]] || die "Root keys are for account ${caller_account}, expected ${ACCOUNT_ID}."
    if [[ "${arn}" != *":root" ]]; then
        warn "Provided credentials are NOT for the root user (arn=${arn}). Continuing, but Phase 6 root-key revocation will be skipped."
    fi

    info "  Confirmed: caller is ${arn} in ${ACCOUNT_ID}."
    record_step "phase0_validate" "ok" "caller=${arn}"
    VALIDATION_PASSED=yes
}

# ── Phase 1: Identity baseline ──────────────────────────────────────────────

phase1_identity() {
    info ""
    info "── Phase 1: Identity baseline ──"

    info "  Setting IAM password policy..."
    aws_as_root iam update-account-password-policy \
        --minimum-password-length 14 \
        --require-symbols \
        --require-numbers \
        --require-uppercase-characters \
        --require-lowercase-characters \
        --allow-users-to-change-password \
        --max-password-age 90 \
        --password-reuse-prevention 24 \
        --hard-expiry 2>/dev/null \
        && info "  Password policy set." \
        || warn "  Failed to set password policy (may already be set or root has limited iam perms)."

    # Account-level IAM Access Analyzer.
    info "  Creating IAM Access Analyzer (ACCOUNT scope)..."
    local analyzer_name="nexus-account-analyzer"
    if aws_as_root accessanalyzer get-analyzer --analyzer-name "${analyzer_name}" \
        >/dev/null 2>&1; then
        info "  Access Analyzer '${analyzer_name}' already exists."
    else
        aws_as_root accessanalyzer create-analyzer \
            --analyzer-name "${analyzer_name}" \
            --type ACCOUNT 2>/dev/null \
            && info "  Access Analyzer created." \
            || warn "  Could not create Access Analyzer (may already exist under a different name)."
    fi

    # Optional: provision an IAM admin user via aws-iam-bootstrap.sh.
    # We hand it the same root creds via env vars and tell it to KEEP the
    # root key (we revoke it ourselves in Phase 6).
    if [[ -n "${CREATE_IAM_ADMIN_USER}" ]]; then
        info "  Invoking aws-iam-bootstrap.sh to create IAM admin user '${CREATE_IAM_ADMIN_USER}'..."
        local sub_rc=0
        if [[ "${DRY_RUN}" == "yes" ]]; then
            echo "DRY-RUN: ${SCRIPT_DIR}/aws-iam-bootstrap.sh --account-id ${ACCOUNT_ID} --profile-name ${CREATE_IAM_ADMIN_USER} --iam-user-name ${CREATE_IAM_ADMIN_USER} --region ${ALLOWED_REGION} --keep-root-key --auto-approve" >&2
        else
            set +e
            ROOT_AK="${ROOT_AK}" ROOT_SK="${ROOT_SK}" ROOT_TOKEN="${ROOT_TOKEN}" \
                bash "${SCRIPT_DIR}/aws-iam-bootstrap.sh" \
                    --account-id "${ACCOUNT_ID}" \
                    --profile-name "${CREATE_IAM_ADMIN_USER}" \
                    --iam-user-name "${CREATE_IAM_ADMIN_USER}" \
                    --region "${ALLOWED_REGION}" \
                    --keep-root-key \
                    --auto-approve \
                    >&2
            sub_rc=$?
            set -e
        fi
        if [[ ${sub_rc} -ne 0 ]]; then
            warn "  aws-iam-bootstrap.sh exited ${sub_rc}; continuing without local CLI profile."
        else
            info "  IAM admin user provisioned."
        fi
    fi

    record_step "phase1_identity" "ok" "password policy + access analyzer ${CREATE_IAM_ADMIN_USER:+(+ iam admin user ${CREATE_IAM_ADMIN_USER})}"
}

# ── Phase 2: Security baseline ──────────────────────────────────────────────

phase2_security() {
    info ""
    info "── Phase 2: Security baseline ──"

    info "  Enabling S3 Block Public Access (account-level)..."
    aws_as_root s3control put-public-access-block \
        --account-id "${ACCOUNT_ID}" \
        --public-access-block-configuration \
            "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" \
        2>/dev/null \
        && info "  S3 BPA enabled." \
        || warn "  Failed to set S3 BPA."

    info "  Enabling default EBS encryption in ${ALLOWED_REGION}..."
    aws_as_root ec2 enable-ebs-encryption-by-default 2>/dev/null \
        && info "  EBS default encryption enabled." \
        || warn "  Failed to enable EBS default encryption."

    info "  Enforcing IMDSv2 as account default..."
    aws_as_root ec2 modify-instance-metadata-defaults \
        --http-tokens required \
        --http-put-response-hop-limit 2 \
        --http-endpoint enabled 2>/dev/null \
        && info "  IMDSv2 default enforced." \
        || warn "  Failed to enforce IMDSv2 default (may require a newer CLI)."

    # CloudTrail with dedicated bucket.
    local trail_name="${ACCOUNT_ID}-baseline-trail"
    local bucket_name="nexus-cloudtrail-${ACCOUNT_ID}"
    info "  Configuring CloudTrail (trail=${trail_name}, bucket=${bucket_name})..."

    if [[ "${DRY_RUN}" != "yes" ]] \
        && ! aws_as_root s3api head-bucket --bucket "${bucket_name}" 2>/dev/null; then
        info "    Creating CloudTrail bucket s3://${bucket_name}..."
        if [[ "${ALLOWED_REGION}" == "us-east-1" ]]; then
            aws_as_root s3api create-bucket --bucket "${bucket_name}" 2>/dev/null \
                || warn "    create-bucket returned non-zero (may already exist or be globally taken)."
        else
            aws_as_root s3api create-bucket --bucket "${bucket_name}" \
                --create-bucket-configuration "LocationConstraint=${ALLOWED_REGION}" 2>/dev/null \
                || warn "    create-bucket returned non-zero."
        fi
        aws_as_root s3api put-public-access-block --bucket "${bucket_name}" \
            --public-access-block-configuration \
                "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" \
            >/dev/null 2>&1 || true
        aws_as_root s3api put-bucket-encryption --bucket "${bucket_name}" \
            --server-side-encryption-configuration \
                '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' \
            >/dev/null 2>&1 || true
        # CloudTrail bucket policy granting cloudtrail.amazonaws.com PutObject / GetBucketAcl.
        local ct_policy
        ct_policy=$(cat <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AWSCloudTrailAclCheck",
      "Effect": "Allow",
      "Principal": {"Service": "cloudtrail.amazonaws.com"},
      "Action": "s3:GetBucketAcl",
      "Resource": "arn:aws:s3:::${bucket_name}",
      "Condition": {"StringEquals": {"AWS:SourceArn": "arn:aws:cloudtrail:${ALLOWED_REGION}:${ACCOUNT_ID}:trail/${trail_name}"}}
    },
    {
      "Sid": "AWSCloudTrailWrite",
      "Effect": "Allow",
      "Principal": {"Service": "cloudtrail.amazonaws.com"},
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::${bucket_name}/AWSLogs/${ACCOUNT_ID}/*",
      "Condition": {
        "StringEquals": {
          "s3:x-amz-acl": "bucket-owner-full-control",
          "AWS:SourceArn": "arn:aws:cloudtrail:${ALLOWED_REGION}:${ACCOUNT_ID}:trail/${trail_name}"
        }
      }
    }
  ]
}
POLICY
)
        aws_as_root s3api put-bucket-policy --bucket "${bucket_name}" \
            --policy "${ct_policy}" >/dev/null 2>&1 \
            || warn "    Could not set CloudTrail bucket policy."
    fi

    if aws_as_root cloudtrail describe-trails --trail-name-list "${trail_name}" \
        --query 'trailList[0].TrailARN' --output text 2>/dev/null | grep -q "${trail_name}"; then
        info "    CloudTrail '${trail_name}' already exists."
    else
        aws_as_root cloudtrail create-trail \
            --name "${trail_name}" \
            --s3-bucket-name "${bucket_name}" \
            --is-multi-region-trail \
            --enable-log-file-validation 2>/dev/null \
            && aws_as_root cloudtrail start-logging --name "${trail_name}" 2>/dev/null \
            && info "    CloudTrail '${trail_name}' created and started." \
            || warn "    CloudTrail creation failed; check S3 bucket policy."
    fi

    # GuardDuty.
    info "  Enabling GuardDuty in ${ALLOWED_REGION}..."
    if aws_as_root guardduty list-detectors --query 'DetectorIds[0]' --output text 2>/dev/null \
        | grep -qE '^[a-z0-9]+$'; then
        info "    GuardDuty detector already exists."
    else
        aws_as_root guardduty create-detector \
            --enable \
            --finding-publishing-frequency FIFTEEN_MINUTES >/dev/null 2>&1 \
            && info "    GuardDuty detector created." \
            || warn "    GuardDuty create-detector failed."
    fi

    # Security Hub.
    info "  Enabling Security Hub in ${ALLOWED_REGION}..."
    if aws_as_root securityhub describe-hub >/dev/null 2>&1; then
        info "    Security Hub already enabled."
    else
        aws_as_root securityhub enable-security-hub --enable-default-standards \
            >/dev/null 2>&1 \
            && info "    Security Hub enabled with default standards." \
            || warn "    Security Hub enable failed."
    fi

    # AWS Config.
    info "  Enabling AWS Config in ${ALLOWED_REGION}..."
    enable_aws_config

    record_step "phase2_security" "ok" "S3 BPA, EBS encryption, IMDSv2, CloudTrail, GuardDuty, Security Hub, Config"
}

enable_aws_config() {
    # AWS Config needs: service-linked role + S3 bucket + ConfigurationRecorder + DeliveryChannel.
    local config_bucket="nexus-config-${ACCOUNT_ID}"
    local recorder_name="default"
    local channel_name="default"
    local role_arn="arn:aws:iam::${ACCOUNT_ID}:role/aws-service-role/config.amazonaws.com/AWSServiceRoleForConfig"

    # Check whether the recorder already exists; if so, skip the heavy lifting.
    if aws_as_root configservice describe-configuration-recorders \
        --query 'ConfigurationRecorders[0].name' --output text 2>/dev/null \
        | grep -qE '.+'; then
        info "    AWS Config recorder already configured."
        return
    fi

    # Service-linked role (idempotent; ignore if exists).
    aws_as_root iam create-service-linked-role \
        --aws-service-name config.amazonaws.com >/dev/null 2>&1 || true

    if [[ "${DRY_RUN}" != "yes" ]] \
        && ! aws_as_root s3api head-bucket --bucket "${config_bucket}" 2>/dev/null; then
        info "    Creating Config bucket s3://${config_bucket}..."
        if [[ "${ALLOWED_REGION}" == "us-east-1" ]]; then
            aws_as_root s3api create-bucket --bucket "${config_bucket}" 2>/dev/null \
                || warn "    Config bucket create returned non-zero."
        else
            aws_as_root s3api create-bucket --bucket "${config_bucket}" \
                --create-bucket-configuration "LocationConstraint=${ALLOWED_REGION}" 2>/dev/null \
                || warn "    Config bucket create returned non-zero."
        fi
        aws_as_root s3api put-public-access-block --bucket "${config_bucket}" \
            --public-access-block-configuration \
                "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" \
            >/dev/null 2>&1 || true
        local cfg_policy
        cfg_policy=$(cat <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {"Sid":"AWSConfigBucketPermissionsCheck","Effect":"Allow","Principal":{"Service":"config.amazonaws.com"},"Action":"s3:GetBucketAcl","Resource":"arn:aws:s3:::${config_bucket}"},
    {"Sid":"AWSConfigBucketExistenceCheck","Effect":"Allow","Principal":{"Service":"config.amazonaws.com"},"Action":"s3:ListBucket","Resource":"arn:aws:s3:::${config_bucket}"},
    {"Sid":"AWSConfigBucketDelivery","Effect":"Allow","Principal":{"Service":"config.amazonaws.com"},"Action":"s3:PutObject","Resource":"arn:aws:s3:::${config_bucket}/AWSLogs/${ACCOUNT_ID}/Config/*","Condition":{"StringEquals":{"s3:x-amz-acl":"bucket-owner-full-control"}}}
  ]
}
POLICY
)
        aws_as_root s3api put-bucket-policy --bucket "${config_bucket}" \
            --policy "${cfg_policy}" >/dev/null 2>&1 \
            || warn "    Config bucket policy failed."
    fi

    aws_as_root configservice put-configuration-recorder \
        --configuration-recorder "name=${recorder_name},roleARN=${role_arn},recordingGroup={allSupported=true,includeGlobalResourceTypes=true}" \
        >/dev/null 2>&1 \
        || warn "    put-configuration-recorder failed."

    aws_as_root configservice put-delivery-channel \
        --delivery-channel "name=${channel_name},s3BucketName=${config_bucket}" \
        >/dev/null 2>&1 \
        || warn "    put-delivery-channel failed."

    aws_as_root configservice start-configuration-recorder \
        --configuration-recorder-name "${recorder_name}" \
        >/dev/null 2>&1 \
        && info "    AWS Config recorder started." \
        || warn "    start-configuration-recorder failed."
}

# ── Phase 3: Region lockdown ────────────────────────────────────────────────

phase3_region_lockdown() {
    info ""
    info "── Phase 3: Region lockdown ──"
    if [[ "${SKIP_REGION_LOCKDOWN}" == "yes" ]]; then
        info "  --skip-region-lockdown set; skipping."
        record_step "phase3_region_lockdown" "skipped" "--skip-region-lockdown"
        return
    fi

    delete_default_vpcs
    opt_out_unused_regions

    record_step "phase3_region_lockdown" "ok" "default VPCs deleted, non-${ALLOWED_REGION} opt-in regions disabled"
}

ALL_AWS_REGIONS=(
    us-east-1 us-east-2 us-west-1 us-west-2
    af-south-1 ap-east-1 ap-south-1 ap-south-2
    ap-southeast-1 ap-southeast-2 ap-southeast-3 ap-southeast-4
    ap-northeast-1 ap-northeast-2 ap-northeast-3
    ca-central-1 ca-west-1
    eu-central-1 eu-central-2 eu-west-1 eu-west-2 eu-west-3
    eu-south-1 eu-south-2 eu-north-1
    il-central-1 me-south-1 me-central-1 sa-east-1
)

delete_default_vpcs() {
    info "  Deleting default VPCs in all regions..."
    for r in "${ALL_AWS_REGIONS[@]}"; do
        local vpc_id
        vpc_id=$(aws_as_root ec2 describe-vpcs --region "${r}" \
            --filters "Name=isDefault,Values=true" \
            --query 'Vpcs[0].VpcId' --output text 2>/dev/null || echo "None")
        if [[ -z "${vpc_id}" || "${vpc_id}" == "None" ]]; then
            continue
        fi

        info "    Deleting default VPC ${vpc_id} in ${r}..."

        local igws
        igws=$(aws_as_root ec2 describe-internet-gateways --region "${r}" \
            --filters "Name=attachment.vpc-id,Values=${vpc_id}" \
            --query 'InternetGateways[].InternetGatewayId' --output text 2>/dev/null) \
            || igws=""
        for igw in ${igws}; do
            aws_as_root ec2 detach-internet-gateway --region "${r}" \
                --internet-gateway-id "${igw}" --vpc-id "${vpc_id}" 2>/dev/null || true
            aws_as_root ec2 delete-internet-gateway --region "${r}" \
                --internet-gateway-id "${igw}" 2>/dev/null || true
        done

        local subnets
        subnets=$(aws_as_root ec2 describe-subnets --region "${r}" \
            --filters "Name=vpc-id,Values=${vpc_id}" \
            --query 'Subnets[].SubnetId' --output text 2>/dev/null) \
            || subnets=""
        for subnet in ${subnets}; do
            aws_as_root ec2 delete-subnet --region "${r}" \
                --subnet-id "${subnet}" 2>/dev/null || true
        done

        aws_as_root ec2 delete-vpc --region "${r}" --vpc-id "${vpc_id}" 2>/dev/null \
            || warn "    Could not delete VPC ${vpc_id} in ${r} (may have dependencies)."
    done
    info "  Default VPC cleanup complete."
}

opt_out_unused_regions() {
    info "  Opting out of unused opt-in regions (keeping ${ALLOWED_REGION})..."
    local opt_in_regions
    opt_in_regions=$(aws_as_root account list-regions \
        --region-opt-status-contains ENABLED \
        --query 'Regions[].RegionName' --output text 2>/dev/null || echo "")
    if [[ -z "${opt_in_regions}" ]]; then
        warn "  Could not list opt-in regions (account API may not be available); skipping disable."
        return
    fi
    for r in ${opt_in_regions}; do
        [[ "${r}" == "${ALLOWED_REGION}" ]] && continue
        info "    Disabling opt-in region ${r}..."
        aws_as_root account disable-region --region-name "${r}" 2>/dev/null \
            || warn "    Could not disable ${r} (may be default-enabled and undisable-able)."
    done
    info "  Region opt-out complete."
}

# ── Phase 4: Billing & cost visibility ──────────────────────────────────────

phase4_billing() {
    info ""
    info "── Phase 4: Billing & cost visibility ──"

    # Activate cost-allocation tags. Note: only USER-defined tags can be
    # activated; nexus:* tags must already exist on at least one resource
    # before AWS will list them. This call is idempotent and harmless when
    # the tags don't exist yet -- they'll auto-activate later when the
    # cluster script tags VPCs/subnets.
    info "  Activating user-defined cost-allocation tags..."
    aws_as_root ce update-cost-allocation-tags-status \
        --cost-allocation-tags-status \
            'TagKey=nexus:capability,Status=Active' \
            'TagKey=nexus:env,Status=Active' \
            'TagKey=nexus:network-profile,Status=Active' \
            'TagKey=nexus:managed-by,Status=Active' \
        >/dev/null 2>&1 \
        && info "    Cost-allocation tags activated." \
        || warn "    Cost-allocation tag activation failed (tags may not yet exist on any resource; benign)."

    # Monthly budget with email alerts at 80% and 100% actual.
    if [[ -n "${BUDGET_EMAIL}" ]]; then
        local budget_name="nexus-monthly-${MONTHLY_BUDGET_USD}usd"
        info "  Creating/updating monthly budget '${budget_name}' (\$${MONTHLY_BUDGET_USD}, alert -> ${BUDGET_EMAIL})..."

        if aws_as_root budgets describe-budget \
            --account-id "${ACCOUNT_ID}" \
            --budget-name "${budget_name}" >/dev/null 2>&1; then
            info "    Budget already exists; skipping create."
        else
            local budget_json
            budget_json=$(cat <<EOF
{
  "BudgetName": "${budget_name}",
  "BudgetLimit": {"Amount": "${MONTHLY_BUDGET_USD}", "Unit": "USD"},
  "TimeUnit": "MONTHLY",
  "BudgetType": "COST"
}
EOF
)
            local subs_json
            subs_json=$(cat <<EOF
[
  {
    "Notification": {"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"PERCENTAGE","NotificationState":"ALARM"},
    "Subscribers": [{"SubscriptionType":"EMAIL","Address":"${BUDGET_EMAIL}"}]
  },
  {
    "Notification": {"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE","NotificationState":"ALARM"},
    "Subscribers": [{"SubscriptionType":"EMAIL","Address":"${BUDGET_EMAIL}"}]
  },
  {
    "Notification": {"NotificationType":"FORECASTED","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE","NotificationState":"ALARM"},
    "Subscribers": [{"SubscriptionType":"EMAIL","Address":"${BUDGET_EMAIL}"}]
  }
]
EOF
)
            aws_as_root budgets create-budget \
                --account-id "${ACCOUNT_ID}" \
                --budget "${budget_json}" \
                --notifications-with-subscribers "${subs_json}" \
                >/dev/null 2>&1 \
                && info "    Budget '${budget_name}' created." \
                || warn "    Budget create failed."
        fi

        # CloudWatch billing alarm. Billing metrics are emitted ONLY in
        # us-east-1, so this call is region-pinned regardless of
        # ALLOWED_REGION.
        info "  Creating CloudWatch billing alarm (us-east-1, EstimatedCharges > \$${MONTHLY_BUDGET_USD})..."
        aws_as_root cloudwatch put-metric-alarm \
            --region us-east-1 \
            --alarm-name "nexus-billing-${MONTHLY_BUDGET_USD}usd" \
            --alarm-description "Total estimated AWS charges for ${ACCOUNT_ID} exceed \$${MONTHLY_BUDGET_USD}" \
            --metric-name EstimatedCharges \
            --namespace AWS/Billing \
            --statistic Maximum \
            --period 21600 \
            --threshold "${MONTHLY_BUDGET_USD}" \
            --comparison-operator GreaterThanThreshold \
            --evaluation-periods 1 \
            --dimensions "Name=Currency,Value=USD" \
            --treat-missing-data notBreaching \
            >/dev/null 2>&1 \
            && info "    Billing alarm created." \
            || warn "    Billing alarm create failed (billing-metric publishing may be off)."
    else
        warn "  --budget-email not set; skipping Budget and billing alarm."
    fi

    record_step "phase4_billing" "ok" "cost tags + budget (\$${MONTHLY_BUDGET_USD}/mo, ${BUDGET_EMAIL:-no email})"
}

# ── Phase 5: NexusClusterProvisioner role ───────────────────────────────────

phase5_provisioner_role() {
    info ""
    info "── Phase 5: NexusClusterProvisioner role ──"

    local role_name="NexusClusterProvisioner"
    local policy_name="NexusClusterProvisionerPolicy"
    local boundary_name="NexusProvisionerBoundary"
    local policy_arn="arn:aws:iam::${ACCOUNT_ID}:policy/${policy_name}"
    local boundary_arn="arn:aws:iam::${ACCOUNT_ID}:policy/${boundary_name}"

    # Build the trust policy. When EXTERNAL_ID is non-empty we use the
    # existing on-disk template (with Condition: sts:ExternalId). When
    # empty (default for SSO/management-side flows), we emit a Condition-
    # free trust inline so an SSO assume-role call without --external-id
    # is accepted.
    local trust_policy
    if [[ -n "${EXTERNAL_ID}" ]]; then
        trust_policy=$(sed \
            -e "s|\${MASTER_ACCOUNT_ID}|${MANAGEMENT_ACCOUNT_ID}|g" \
            -e "s|\${EXTERNAL_ID}|${EXTERNAL_ID}|g" \
            "${POLICIES_DIR}/cross-account-provisioner-role.json")
    else
        trust_policy=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowMasterAccountAssume",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::${MANAGEMENT_ACCOUNT_ID}:root"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
)
    fi
    local perms_policy
    perms_policy=$(cat "${POLICIES_DIR}/cross-account-provisioner-policy.json")

    # 5a: Role (trust policy).
    if aws_as_root iam get-role --role-name "${role_name}" >/dev/null 2>&1; then
        info "  Role ${role_name} exists; updating trust policy..."
        aws_as_root iam update-assume-role-policy \
            --role-name "${role_name}" \
            --policy-document "${trust_policy}" \
            >/dev/null 2>&1 \
            || warn "    update-assume-role-policy failed."
    else
        info "  Creating role ${role_name} (max session 7200 s)..."
        aws_as_root iam create-role \
            --role-name "${role_name}" \
            --assume-role-policy-document "${trust_policy}" \
            --description "Cross-account role assumed by management account ${MANAGEMENT_ACCOUNT_ID} for hardened EKS cluster provisioning. Managed by setup-member-account.sh." \
            --max-session-duration 7200 \
            --tags "Key=nexus:managed-by,Value=setup-member-account.sh" \
            >/dev/null 2>&1 \
            && info "    Role ${role_name} created." \
            || warn "    Role create failed."
    fi

    # 5b: Customer-managed permissions policy (idempotent ensure-create +
    # always-version-update).
    #
    # Prior logic used `iam:GetPolicy` as a gate between create and update.
    # That broke when GetPolicy returned non-zero for any reason (transient
    # error, missing iam:GetPolicy on root context, etc.) -- the script
    # then took the create-branch, create failed with EntityAlreadyExists,
    # and the new JSON never reached AWS. Result: a stale v1 stays as the
    # default, the role has almost no permissions, and downstream assume
    # calls hit UnauthorizedOperation on the first ec2:DescribeVpcs.
    #
    # New pattern: ALWAYS try create (tolerate EntityAlreadyExists), then
    # ALWAYS push a fresh version and set it as default. Same JSON ends up
    # attached whether it's a brand-new policy or an existing one.
    info "  Ensuring policy ${policy_name} exists..."
    aws_as_root iam create-policy \
        --policy-name "${policy_name}" \
        --policy-document "${perms_policy}" \
        --description "Permissions for nexus-ai cluster provisioning via NexusClusterProvisioner. Managed by setup-member-account.sh." \
        >/dev/null 2>&1 || true

    info "  Pushing latest policy version (deleting old non-default versions; AWS caps at 5)..."
    local versions
    versions=$(aws_as_root iam list-policy-versions --policy-arn "${policy_arn}" \
        --query 'Versions[?!IsDefaultVersion].VersionId' --output text 2>/dev/null) \
        || versions=""
    for v in ${versions}; do
        aws_as_root iam delete-policy-version --policy-arn "${policy_arn}" \
            --version-id "${v}" >/dev/null 2>&1 || true
    done
    # Capture stderr so the actual AWS error (LimitExceeded for >6144-char
    # policy, NoSuchEntity, etc.) is surfaced in the WARN instead of being
    # swallowed by >/dev/null. Otherwise this fails silently from the
    # operator's perspective.
    local pv_err pv_rc=0
    pv_err=$(aws_as_root iam create-policy-version \
        --policy-arn "${policy_arn}" \
        --policy-document "${perms_policy}" \
        --set-as-default 2>&1 >/dev/null) || pv_rc=$?
    if [ ${pv_rc} -eq 0 ]; then
        info "    Policy ${policy_name} now at latest version."
    else
        warn "    Could not push new policy version: ${pv_err}"
        warn "    Common causes:"
        warn "      - JSON exceeds 6144 non-whitespace chars (managed-policy limit)"
        warn "      - Policy is at 5-version cap (delete old versions in console)"
        warn "    Recovery: log in to ${ACCOUNT_ID} as root in the AWS console and"
        warn "             update ${policy_name} manually with the contents of"
        warn "             ${POLICIES_DIR}/cross-account-provisioner-policy.json"
    fi

    info "  Attaching policy to role..."
    aws_as_root iam attach-role-policy \
        --role-name "${role_name}" \
        --policy-arn "${policy_arn}" \
        >/dev/null 2>&1 || true

    # 5c: Permission boundary (same JSON used as a boundary; same idempotent
    # ensure-create + always-version-update pattern).
    info "  Ensuring boundary ${boundary_name} exists..."
    aws_as_root iam create-policy \
        --policy-name "${boundary_name}" \
        --policy-document "${perms_policy}" \
        --description "Permission boundary capping NexusClusterProvisioner privileges. Managed by setup-member-account.sh." \
        >/dev/null 2>&1 || true

    info "  Pushing latest boundary version..."
    local bversions
    bversions=$(aws_as_root iam list-policy-versions --policy-arn "${boundary_arn}" \
        --query 'Versions[?!IsDefaultVersion].VersionId' --output text 2>/dev/null) \
        || bversions=""
    for v in ${bversions}; do
        aws_as_root iam delete-policy-version --policy-arn "${boundary_arn}" \
            --version-id "${v}" >/dev/null 2>&1 || true
    done
    local bv_err bv_rc=0
    bv_err=$(aws_as_root iam create-policy-version \
        --policy-arn "${boundary_arn}" \
        --policy-document "${perms_policy}" \
        --set-as-default 2>&1 >/dev/null) || bv_rc=$?
    if [ ${bv_rc} -eq 0 ]; then
        info "    Boundary ${boundary_name} now at latest version."
    else
        warn "    Could not push new boundary version: ${bv_err}"
        warn "    Same recovery as the policy above."
    fi

    info "  Attaching permission boundary to role..."
    aws_as_root iam put-role-permissions-boundary \
        --role-name "${role_name}" \
        --permissions-boundary "${boundary_arn}" \
        >/dev/null 2>&1 || true

    PROVISIONER_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${role_name}"
    info "  Role ARN: ${PROVISIONER_ROLE_ARN}"
    if [[ -n "${EXTERNAL_ID}" ]]; then
        info "  External ID: ${EXTERNAL_ID}"
    else
        info "  External ID: (none -- trust scoped by Principal only)"
    fi

    record_step "phase5_provisioner_role" "ok" "${PROVISIONER_ROLE_ARN} (ExternalId=${EXTERNAL_ID:-none})"
}

# ── Phase 6: Revoke bootstrap root access key ───────────────────────────────

phase6_revoke_root_key() {
    info ""
    info "── Phase 6: Revoke bootstrap root access key ──"
    if [[ "${KEEP_ROOT_KEY}" == "yes" ]]; then
        warn "  --keep-root-key set; root key remains ACTIVE."
        record_step "phase6_revoke_root_key" "skipped" "--keep-root-key"
        return
    fi
    if [[ "${DRY_RUN}" == "yes" ]]; then
        echo "DRY-RUN: aws iam delete-access-key --access-key-id ${ROOT_AK:0:4}**** (root context)" >&2
        record_step "phase6_revoke_root_key" "dry_run" "would delete root AK ${ROOT_AK:0:4}****"
        return
    fi

    info "  Revoking root access key ${ROOT_AK:0:4}****..."
    if aws_as_root iam delete-access-key --access-key-id "${ROOT_AK}" 2>/dev/null; then
        info "  Root access key revoked."
        record_step "phase6_revoke_root_key" "ok" "root AK ${ROOT_AK:0:4}**** deleted"
    else
        warn "  Failed to delete root access key. Delete manually in the AWS console: IAM -> root user -> Security credentials."
        record_step "phase6_revoke_root_key" "warn" "delete-access-key non-zero; remove manually"
    fi
}

# ── Main ────────────────────────────────────────────────────────────────────

main() {
    info "=========================================="
    info "AWS Member Account Setup (member-side)"
    info "=========================================="
    [[ -n "${_LOADED_ENV_FILE:-}" ]] && info "Config file:           ${_LOADED_ENV_FILE}"
    info "Member Account:        ${ACCOUNT_ID}"
    info "Management Account:    ${MANAGEMENT_ACCOUNT_ID}"
    info "Allowed Region:        ${ALLOWED_REGION}"
    info "External ID:           ${EXTERNAL_ID:-(none -- trust by Principal only)}"
    info "Budget Email:          ${BUDGET_EMAIL:-(unset; skipping budgets)}"
    info "Monthly Budget USD:    ${MONTHLY_BUDGET_USD}"
    info "Create IAM admin user: ${CREATE_IAM_ADMIN_USER:-(skip)}"
    info "Revoke root key:       $( [[ "${KEEP_ROOT_KEY}" == "yes" ]] && echo no || echo yes )"
    info "Region lockdown:       $( [[ "${SKIP_REGION_LOCKDOWN}" == "yes" ]] && echo skipped || echo enforced )"
    info "Dry Run:               ${DRY_RUN}"
    info ""

    if ! confirm "Proceed with member-account setup?"; then
        info "Aborted by user."
        exit 0
    fi

    phase0_validate
    phase1_identity
    phase2_security
    phase3_region_lockdown
    phase4_billing
    phase5_provisioner_role
    phase6_revoke_root_key

    emit_manifest "succeeded" "All phases completed."

    info ""
    info "=========================================="
    info "Member account ${ACCOUNT_ID} is cluster-ready."
    info "=========================================="
    info "  NexusClusterProvisioner ARN: ${PROVISIONER_ROLE_ARN}"
    info "  External ID:                 ${EXTERNAL_ID:-(not required)}"
    info "  Manifest:                    ${MANIFEST_PATH}"
    info ""
    info "Next steps (from the MANAGEMENT account):"
    info "  1. Add this role to aws-login/.env.roles.local:"
    info "       member-${ACCOUNT_ID}=${PROVISIONER_ROLE_ARN}"
    info "  2. Assume into the member account:"
    info "       ./aws-login/assume-role-to-profile.sh --member-${ACCOUNT_ID} --console-url"
    if [[ -n "${EXTERNAL_ID}" ]]; then
        info "       (this role requires --external-id ${EXTERNAL_ID})"
    fi
    info "  3. Run the cluster creator using the resulting profile:"
    info "       AWS_PROFILE=member-${ACCOUNT_ID} \\"
    info "         ./deploy/eks/create-hardened-eks-cluster.sh --name <cluster> --auto-approve"
    info ""
    info "Operator + App IRSA roles are created by the cluster script (Step 4)."
}

# Manifest-on-error trap: if anything past validation blows up, still write
# a manifest so the audit-logs/ trail isn't half-empty.
trap '[[ "${VALIDATION_PASSED}" == "yes" ]] && emit_manifest "failed" "Unhandled error at line $LINENO"' ERR

# Credential scrub on the way out (success OR failure).
trap 'unset ROOT_AK ROOT_SK ROOT_TOKEN AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN' EXIT

main

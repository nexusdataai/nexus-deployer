#!/bin/bash
#
# AWS Standalone-Account IAM Bootstrap
#
# One-shot setup for a non-federated, non-org-member AWS account. From the
# supplied root access key + secret it:
#   1. Creates an IAM admin user with programmatic access.
#   2. Writes a local AWS CLI profile pointing at the new key.
#   3. Applies the SAME hardening that secure-member-account.sh applies to
#      Org-member accounts (password policy, S3 BPA, EBS encryption,
#      IMDSv2, default-VPC cleanup, opt-in region disable).
#   4. Creates the SAME NexusClusterProvisioner role (and permission
#      boundary) that setup-cross-account-roles.sh creates in Org-member
#      accounts. Trust principal in standalone mode is the target account
#      itself (i.e. any local IAM identity with sts:AssumeRole + the
#      correct external-id can assume).
#   5. Revokes the bootstrap root access key.
#
# After this runs you can use the new profile with any AWS tool (terraform,
# eksctl, kubectl, the EKS scripts under nexus-deployer/deploy/eks/, etc.).
#
# This is the standalone-account analogue of aws-sso-login.sh and produces
# a child account that is hardened identically to one onboarded by
# onboard-account.sh — only difference is Org membership.
#
# Usage:
#   ./aws-iam-bootstrap.sh \
#       --account-id            040740747817 \
#       --root-access-key-id    "$ROOT_AK" \
#       --root-secret-access-key "$ROOT_SK" \
#       --profile-name          promode-official \
#       [--iam-user-name papu]                  # default: papu
#       [--region us-east-1]                     # default: us-east-1
#       [--external-id <secret>]                 # NexusClusterProvisioner external-id
#                                                # (default: nexus-provision-<YYYY>)
#       [--management-account-id <12-digit-id>]  # Account whose root will be trusted
#                                                # by NexusClusterProvisioner. Default:
#                                                # the target account itself (i.e. trust
#                                                # is local) -- correct only for an
#                                                # isolated account that will not be
#                                                # driven from a separate management
#                                                # account. Set this to your management
#                                                # account ID when you intend to assume
#                                                # the role via assume-role-to-profile.sh.
#       [--skip-hardening]                       # do NOT run secure-member-account.sh
#       [--skip-provisioner-role]                # do NOT create NexusClusterProvisioner
#       [--keep-root-key]                        # do NOT delete the bootstrap root AK
#       [--auto-approve]                         # skip confirmation prompts
#       [--dry-run]                              # print all aws calls without executing
#
# Env-var alternative for root keys (preferred; keeps secrets off the
# command line and out of shell history):
#   ROOT_AK=AKIA... ROOT_SK=...  ./aws-iam-bootstrap.sh \
#       --account-id 040740747817 \
#       --profile-name promode-official
#

set -e
set +x  # never echo commands; secrets may be in env

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Optional config file (.env.iam.local) ──────────────────────────────────
#
# Auto-sourced when present. Supports either naming convention:
#   - ROOT_AK / ROOT_SK              (this script's internal names)
#   - AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY  (AWS-standard env names)
# Plus optional ACCOUNT_ID, PROFILE_NAME, IAM_USER_NAME, REGION,
#               EXTERNAL_ID, MANAGEMENT_ACCOUNT_ID, SKIP_HARDENING,
#               SKIP_PROVISIONER_ROLE, KEEP_ROOT_KEY, AUTO_APPROVE, DRY_RUN.
#
# Precedence (highest wins): CLI flag > pre-set parent-shell env var > file.
#
# Override path with the ENV_FILE env var:
#   ENV_FILE=/path/to/other.env ./aws-iam-bootstrap.sh ...
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env.iam.local}"
if [[ -f "${ENV_FILE}" ]]; then
    # Permission check: this file holds root credentials. Warn if loose.
    _perms=$(stat -c '%a' "${ENV_FILE}" 2>/dev/null || echo "")
    if [[ -n "${_perms}" && "${_perms}" != "600" && "${_perms}" != "400" ]]; then
        echo "[WARN] ${ENV_FILE} permissions are ${_perms}; expected 600. Run: chmod 600 ${ENV_FILE}" >&2
    fi
    unset _perms

    set -o allexport
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
    set +o allexport

    # Map AWS-standard env names to our internal names, only if internal
    # names are not already set by a parent shell.
    ROOT_AK="${ROOT_AK:-${AWS_ACCESS_KEY_ID:-}}"
    ROOT_SK="${ROOT_SK:-${AWS_SECRET_ACCESS_KEY:-}}"
    ROOT_TOKEN="${ROOT_TOKEN:-${AWS_SESSION_TOKEN:-}}"

    # CRITICAL: scrub the AWS-standard env-var names so they cannot leak
    # into any aws-cli call that bypasses our aws_as_root helper (every
    # subsequent call wraps creds explicitly via that helper).
    unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN

    _LOADED_ENV_FILE="${ENV_FILE}"
fi

# ── Defaults ────────────────────────────────────────────────────────────────

ACCOUNT_ID="${ACCOUNT_ID:-}"
ROOT_AK="${ROOT_AK:-}"
ROOT_SK="${ROOT_SK:-}"
ROOT_TOKEN="${ROOT_TOKEN:-}"
PROFILE_NAME="${PROFILE_NAME:-}"
IAM_USER_NAME="${IAM_USER_NAME:-papu}"
REGION="${REGION:-us-east-1}"
EXTERNAL_ID="${EXTERNAL_ID:-nexus-provision-$(date +%Y)}"
MANAGEMENT_ACCOUNT_ID="${MANAGEMENT_ACCOUNT_ID:-}"
SKIP_HARDENING="${SKIP_HARDENING:-no}"
SKIP_PROVISIONER_ROLE="${SKIP_PROVISIONER_ROLE:-no}"
KEEP_ROOT_KEY="${KEEP_ROOT_KEY:-no}"
AUTO_APPROVE="${AUTO_APPROVE:-no}"
DRY_RUN="${DRY_RUN:-no}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --account-id)              ACCOUNT_ID="$2"; shift 2 ;;
        --root-access-key-id)      ROOT_AK="$2"; shift 2 ;;
        --root-secret-access-key)  ROOT_SK="$2"; shift 2 ;;
        --root-session-token)      ROOT_TOKEN="$2"; shift 2 ;;
        --profile-name)            PROFILE_NAME="$2"; shift 2 ;;
        --iam-user-name)           IAM_USER_NAME="$2"; shift 2 ;;
        --region)                  REGION="$2"; shift 2 ;;
        --external-id)             EXTERNAL_ID="$2"; shift 2 ;;
        --management-account-id)   MANAGEMENT_ACCOUNT_ID="$2"; shift 2 ;;
        --skip-hardening)          SKIP_HARDENING=yes; shift ;;
        --skip-provisioner-role)   SKIP_PROVISIONER_ROLE=yes; shift ;;
        --keep-root-key)           KEEP_ROOT_KEY=yes; shift ;;
        --auto-approve)            AUTO_APPROVE=yes; shift ;;
        --dry-run)                 DRY_RUN=yes; shift ;;
        --help|-h)
            sed -n '2,60p' "$0"
            exit 0
            ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# Validate --management-account-id format if set.
if [[ -n "${MANAGEMENT_ACCOUNT_ID}" ]]; then
    [[ "${MANAGEMENT_ACCOUNT_ID}" =~ ^[0-9]{12}$ ]] \
        || { echo "ERROR: --management-account-id must be a 12-digit AWS account ID (got: ${MANAGEMENT_ACCOUNT_ID})" >&2; exit 1; }
fi

# Resolve sibling-script paths up front so we fail fast if the layout is wrong.
SECURE_SCRIPT="${SCRIPT_DIR}/secure-member-account.sh"
PROVISIONER_SCRIPT="${SCRIPT_DIR}/setup-cross-account-roles.sh"

# ── Logging (stderr-only; stdout reserved for any future structured output) ──

log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >&2; }
info() { log "INFO  $*"; }
warn() { log "WARN  $*"; }
err()  { log "ERROR $*"; }
die()  { err "$*"; exit 1; }

confirm() {
    if [[ "${AUTO_APPROVE}" == "yes" ]]; then return 0; fi
    read -r -p "$1 [y/N]: " response
    [[ "$response" =~ ^[Yy]$ ]]
}

# ── Validation ──────────────────────────────────────────────────────────────

[[ -n "${ACCOUNT_ID}" ]]    || die "--account-id is required"
[[ "${ACCOUNT_ID}" =~ ^[0-9]{12}$ ]] || die "--account-id must be a 12-digit AWS account ID"
[[ -n "${PROFILE_NAME}" ]]  || die "--profile-name is required (e.g. promode-official)"
[[ -n "${ROOT_AK}" ]]       || die "--root-access-key-id (or ROOT_AK env var) is required"
[[ -n "${ROOT_SK}" ]]       || die "--root-secret-access-key (or ROOT_SK env var) is required"
[[ "${PROFILE_NAME}" =~ ^[A-Za-z0-9_.-]+$ ]] || die "--profile-name has invalid characters"
[[ "${IAM_USER_NAME}" =~ ^[A-Za-z0-9._=,@+-]+$ ]] || die "--iam-user-name has invalid characters"

# Real AWS access keys are 20 chars; secret keys are 40 chars. Anything
# much shorter almost certainly means the env-var expansion got an empty
# or truncated value (e.g. unset $ROOT_AK, line break in copied secret).
[[ ${#ROOT_AK} -ge 16 ]] || die "Root access key is suspiciously short (${#ROOT_AK} chars; expected ~20). Re-check --root-access-key-id or \$ROOT_AK."
[[ ${#ROOT_SK} -ge 30 ]] || die "Root secret key is suspiciously short (${#ROOT_SK} chars; expected ~40). Re-check --root-secret-access-key or \$ROOT_SK."

# Force aws-cli to use the env-var credentials only for the bootstrap calls.
# Strip any AWS_PROFILE / AWS_SESSION_TOKEN the parent shell may have set
# so they cannot leak into aws_as_root invocations (we deliberately do
# NOT use `env -u` inside aws_as_root because it triggers an output-capture
# bug in some terminal environments).
unset AWS_PROFILE AWS_DEFAULT_PROFILE AWS_SESSION_TOKEN

# aws_as_root: run a single aws command as the supplied root user.
#
# Defensive measures (each blocks one specific failure mode we've hit):
#   * Inline VAR=value command pattern -> standard bash, no array quirks.
#   * AWS_PAGER="" + --no-cli-pager     -> kills the v2 pager (less) both
#                                           ways; some shells set AWS_PAGER
#                                           via .bashrc and the env-var alone
#                                           is sometimes not honoured.
#   * AWS_EC2_METADATA_DISABLED=true    -> aws-cli will NOT try to reach
#                                           169.254.169.254 IMDS, which on a
#                                           non-EC2 host hangs for ~30s per
#                                           attempt before timing out.
#   * --cli-connect-timeout / read      -> any network call dies in <30s
#                                           instead of hanging indefinitely.
#   * < /dev/null                       -> stdin closed so aws-cli can never
#                                           sit waiting for an interactive
#                                           prompt.
#   * `timeout 45 ...`                  -> last-resort overall watchdog.
#
# We do NOT set AWS_SHARED_CREDENTIALS_FILE / AWS_CONFIG_FILE to /dev/null
# any more -- env-var credentials already take priority over profile-based
# credentials in aws-cli's resolver, and pointing config to /dev/null was
# causing the new hang on at least one host.
aws_as_root() {
    if [[ "${DRY_RUN}" == "yes" ]]; then
        echo "DRY-RUN: aws --region ${REGION} $*" >&2
        return 0
    fi
    # Two CLI bugs to avoid here, both proven by tests on this host:
    #   1. AWS_PROFILE="" makes aws-cli look up a profile literally named
    #      empty-string and fail with "The config profile () could not be
    #      found". Solution: don't set AWS_PROFILE inline; rely on the
    #      script-level `unset` at startup to keep it out of the env.
    #   2. `env -u FOO BAR=val cmd` silently swallows aws-cli stdout in some
    #      terminal environments (cursor IDE in particular). Solution: use
    #      ONLY the inline `VAR=value cmd` pattern, never `env`.
    if [[ -n "${ROOT_TOKEN}" ]]; then
        AWS_ACCESS_KEY_ID="${ROOT_AK}" \
        AWS_SECRET_ACCESS_KEY="${ROOT_SK}" \
        AWS_SESSION_TOKEN="${ROOT_TOKEN}" \
        AWS_PAGER="" \
        AWS_EC2_METADATA_DISABLED=true \
        timeout 45 aws --region "${REGION}" \
            --cli-connect-timeout 10 \
            --cli-read-timeout 20 \
            --no-cli-pager \
            "$@" </dev/null
    else
        AWS_ACCESS_KEY_ID="${ROOT_AK}" \
        AWS_SECRET_ACCESS_KEY="${ROOT_SK}" \
        AWS_PAGER="" \
        AWS_EC2_METADATA_DISABLED=true \
        timeout 45 aws --region "${REGION}" \
            --cli-connect-timeout 10 \
            --cli-read-timeout 20 \
            --no-cli-pager \
            "$@" </dev/null
    fi
}

# Wrapper for calls using the brand-new IAM user keys (post key-creation).
new_aws() {
    if [[ "${DRY_RUN}" == "yes" ]]; then
        echo "DRY-RUN: aws --profile ${PROFILE_NAME} --region ${REGION} $*" >&2
        return 0
    fi
    AWS_PAGER="" \
    AWS_EC2_METADATA_DISABLED=true \
    timeout 45 aws --profile "${PROFILE_NAME}" --region "${REGION}" \
        --cli-connect-timeout 10 \
        --cli-read-timeout 20 \
        --no-cli-pager \
        "$@" </dev/null
}

# ── 1. Verify root identity in expected account ─────────────────────────────

verify_root_identity() {
    info "Verifying caller identity (AK starts ${ROOT_AK:0:4}***, ${#ROOT_AK}-char key, ${#ROOT_SK}-char secret)..."
    if [[ "${DRY_RUN}" == "yes" ]]; then
        echo "DRY-RUN: aws sts get-caller-identity (with supplied root keys)" >&2
        return 0
    fi

    local stderr_file
    stderr_file=$(mktemp)

    info "  -> calling sts get-caller-identity (45s timeout)..."
    local raw rc stderr_out
    raw=$(aws_as_root sts get-caller-identity --output json 2>"${stderr_file}")
    rc=$?
    stderr_out=$(cat "${stderr_file}")
    rm -f "${stderr_file}"
    info "  <- returned exit=${rc}, stdout=${#raw} bytes, stderr=${#stderr_out} bytes"

    if [[ ${rc} -eq 124 ]]; then
        die "sts get-caller-identity TIMED OUT after 45s. Likely network egress is blocked or DNS for sts.amazonaws.com is failing. Test with: curl -v https://sts.us-east-1.amazonaws.com/"
    fi
    if [[ ${rc} -ne 0 ]]; then
        die "sts get-caller-identity exit ${rc}: ${stderr_out:-<no stderr>}"
    fi
    if [[ -z "${raw}" ]]; then
        die "sts get-caller-identity returned EMPTY stdout (exit 0, stderr empty). Reproduce by hand: AWS_ACCESS_KEY_ID=\"\$ROOT_AK\" AWS_SECRET_ACCESS_KEY=\"\$ROOT_SK\" AWS_PAGER='' AWS_EC2_METADATA_DISABLED=true aws --no-cli-pager sts get-caller-identity"
    fi

    local caller_account arn
    caller_account=$(echo "${raw}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('Account',''))" 2>/dev/null || echo "")
    arn=$(echo "${raw}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('Arn',''))" 2>/dev/null || echo "")

    if [[ -z "${caller_account}" ]]; then
        die "Could not parse Account from aws response. Raw stdout (first 500 chars): ${raw:0:500}"
    fi

    if [[ "${caller_account}" != "${ACCOUNT_ID}" ]]; then
        die "Root keys are for account ${caller_account}, expected ${ACCOUNT_ID}. Wrong --account-id or keys belong to a different account."
    fi
    if [[ "${arn}" != *":root" ]]; then
        die "Provided credentials are NOT for the root user (arn=${arn}). The bootstrap script needs the root user's access key, not an IAM user's."
    fi
    info "Confirmed: caller is root of ${ACCOUNT_ID} (arn=${arn})."
}

# ── 2. Pre-flight: refuse if the target IAM user already exists ─────────────

check_user_doesnt_exist() {
    info "Checking that IAM user '${IAM_USER_NAME}' does not already exist..."
    if [[ "${DRY_RUN}" == "yes" ]]; then
        echo "DRY-RUN: aws iam get-user --user-name ${IAM_USER_NAME}" >&2
        return 0
    fi
    if aws_as_root iam get-user --user-name "${IAM_USER_NAME}" \
        --query 'User.Arn' --output text >/dev/null 2>&1; then
        die "IAM user '${IAM_USER_NAME}' already exists in ${ACCOUNT_ID}. Choose a different --iam-user-name or delete it first."
    fi
    info "User '${IAM_USER_NAME}' does not exist; proceeding to create."
}

# ── 3. Create the IAM admin user + access key ───────────────────────────────

create_admin_user() {
    info "Creating IAM user '${IAM_USER_NAME}' with AdministratorAccess..."
    aws_as_root iam create-user --user-name "${IAM_USER_NAME}" \
        --tags "Key=managed-by,Value=aws-iam-bootstrap.sh" >/dev/null
    aws_as_root iam attach-user-policy --user-name "${IAM_USER_NAME}" \
        --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
    info "User created."
}

create_access_key() {
    info "Creating access key for '${IAM_USER_NAME}'..."
    if [[ "${DRY_RUN}" == "yes" ]]; then
        echo "DRY-RUN: aws iam create-access-key --user-name ${IAM_USER_NAME}" >&2
        NEW_AK="AKIA_DRYRUN_DUMMY_AK"
        NEW_SK="(dry-run-dummy-secret)"
        return 0
    fi

    local stderr_file rc raw stderr_out
    stderr_file=$(mktemp)
    raw=$(aws_as_root iam create-access-key --user-name "${IAM_USER_NAME}" \
        --output json 2>"${stderr_file}")
    rc=$?
    stderr_out=$(cat "${stderr_file}")
    rm -f "${stderr_file}"

    if [[ ${rc} -ne 0 ]]; then
        die "iam create-access-key exit ${rc}: ${stderr_out:-<no stderr>}"
    fi
    if [[ -z "${raw}" ]]; then
        die "iam create-access-key returned empty output. stderr: ${stderr_out:-<empty>}"
    fi

    NEW_AK=$(echo "${raw}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('AccessKey',{}).get('AccessKeyId',''))" 2>/dev/null || echo "")
    NEW_SK=$(echo "${raw}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('AccessKey',{}).get('SecretAccessKey',''))" 2>/dev/null || echo "")
    if [[ -z "${NEW_AK}" || -z "${NEW_SK}" ]]; then
        die "Could not parse access key from response. Raw (first 200 chars): ${raw:0:200}"
    fi
    info "Access key created: ${NEW_AK}"
}

# ── 4. Write the new keys to ~/.aws/credentials + ~/.aws/config ─────────────

write_cli_profile() {
    info "Writing CLI profile '${PROFILE_NAME}' to ~/.aws/credentials + ~/.aws/config..."

    # Back up any existing same-named profile so we never silently overwrite.
    local creds_file="${HOME}/.aws/credentials"
    if [[ -f "${creds_file}" ]] && grep -q "^\[${PROFILE_NAME}\]$" "${creds_file}"; then
        local backup="${creds_file}.bak.$(date +%Y%m%dT%H%M%SZ)"
        cp "${creds_file}" "${backup}"
        info "Existing profile detected; backed up credentials file to ${backup}"
    fi

    if [[ "${DRY_RUN}" == "yes" ]]; then
        echo "DRY-RUN: aws configure set aws_access_key_id <new-ak> --profile ${PROFILE_NAME}" >&2
        echo "DRY-RUN: aws configure set aws_secret_access_key <new-sk> --profile ${PROFILE_NAME}" >&2
        echo "DRY-RUN: aws configure set region ${REGION} --profile ${PROFILE_NAME}" >&2
        echo "DRY-RUN: aws configure set output json --profile ${PROFILE_NAME}" >&2
        return 0
    fi

    aws configure set aws_access_key_id     "${NEW_AK}" --profile "${PROFILE_NAME}"
    aws configure set aws_secret_access_key "${NEW_SK}" --profile "${PROFILE_NAME}"
    aws configure set region                "${REGION}" --profile "${PROFILE_NAME}"
    aws configure set output                json        --profile "${PROFILE_NAME}"
    info "Profile '${PROFILE_NAME}' written."
}

# ── 5. Verify the new profile works ─────────────────────────────────────────

verify_new_profile() {
    info "Verifying profile '${PROFILE_NAME}' resolves to account ${ACCOUNT_ID}..."
    if [[ "${DRY_RUN}" == "yes" ]]; then
        echo "DRY-RUN: aws --profile ${PROFILE_NAME} sts get-caller-identity" >&2
        return 0
    fi
    # IAM eventual consistency: a fresh key sometimes needs a few seconds.
    local verified_account="" attempts=0
    while [[ ${attempts} -lt 6 ]]; do
        verified_account=$(aws --profile "${PROFILE_NAME}" --region "${REGION}" \
            sts get-caller-identity --query 'Account' --output text 2>/dev/null || echo "")
        if [[ "${verified_account}" == "${ACCOUNT_ID}" ]]; then
            info "Verified."
            return 0
        fi
        attempts=$((attempts + 1))
        sleep 5
    done
    die "Profile verification failed (got '${verified_account}' for account, expected '${ACCOUNT_ID}')."
}

# ── 6. Full hardening via secure-member-account.sh --no-assume ──────────────

run_hardening() {
    if [[ "${SKIP_HARDENING}" == "yes" ]]; then
        warn "Skipping hardening (--skip-hardening). Account will NOT match the standard child-account baseline."
        return 0
    fi
    [[ -x "${SECURE_SCRIPT}" ]] || die "Missing or non-executable: ${SECURE_SCRIPT}"

    info ""
    info "── Hardening (secure-member-account.sh --no-assume) ──"

    if [[ "${DRY_RUN}" == "yes" ]]; then
        echo "DRY-RUN: ${SECURE_SCRIPT} --no-assume --profile ${PROFILE_NAME} --region ${REGION} --account-id ${ACCOUNT_ID} --auto-approve" >&2
        return 0
    fi

    # Sibling script handles its own logging; --auto-approve avoids
    # double-prompting (we already confirmed at the top of this run).
    "${SECURE_SCRIPT}" \
        --no-assume \
        --profile "${PROFILE_NAME}" \
        --region "${REGION}" \
        --account-id "${ACCOUNT_ID}" \
        --auto-approve \
        || die "Hardening (secure-member-account.sh) failed. Bootstrap root key NOT revoked; re-run after fixing or pass --skip-hardening to bypass."
}

# ── 7. NexusClusterProvisioner role via setup-cross-account-roles.sh ────────

create_provisioner_role() {
    if [[ "${SKIP_PROVISIONER_ROLE}" == "yes" ]]; then
        warn "Skipping NexusClusterProvisioner creation (--skip-provisioner-role)."
        return 0
    fi
    [[ -x "${PROVISIONER_SCRIPT}" ]] || die "Missing or non-executable: ${PROVISIONER_SCRIPT}"

    info ""
    info "── NexusClusterProvisioner (setup-cross-account-roles.sh --no-assume) ──"
    info "  external-id:     ${EXTERNAL_ID}"
    if [[ -n "${MANAGEMENT_ACCOUNT_ID}" ]]; then
        info "  trust principal: arn:aws:iam::${MANAGEMENT_ACCOUNT_ID}:root  (--management-account-id)"
    else
        info "  trust principal: arn:aws:iam::${ACCOUNT_ID}:root  (local; not assumable from another account)"
    fi

    # Build the optional --trust-account-id passthrough.
    local trust_args=()
    [[ -n "${MANAGEMENT_ACCOUNT_ID}" ]] && trust_args+=(--trust-account-id "${MANAGEMENT_ACCOUNT_ID}")

    if [[ "${DRY_RUN}" == "yes" ]]; then
        echo "DRY-RUN: ${PROVISIONER_SCRIPT} --no-assume --profile ${PROFILE_NAME} --region ${REGION} --account-id ${ACCOUNT_ID} --external-id ${EXTERNAL_ID}${MANAGEMENT_ACCOUNT_ID:+ --trust-account-id ${MANAGEMENT_ACCOUNT_ID}} --auto-approve" >&2
        return 0
    fi

    "${PROVISIONER_SCRIPT}" \
        --no-assume \
        --profile "${PROFILE_NAME}" \
        --region "${REGION}" \
        --account-id "${ACCOUNT_ID}" \
        --external-id "${EXTERNAL_ID}" \
        "${trust_args[@]}" \
        --auto-approve \
        || die "Provisioner role setup failed. Bootstrap root key NOT revoked; re-run after fixing or pass --skip-provisioner-role to bypass."
}

# ── 7. Revoke the bootstrap root access key ─────────────────────────────────

delete_root_access_key() {
    if [[ "${KEEP_ROOT_KEY}" == "yes" ]]; then
        warn "Skipping root-key deletion (--keep-root-key). The bootstrap root key remains ACTIVE."
        return 0
    fi
    info "Revoking bootstrap root access key ${ROOT_AK:0:4}****..."
    if [[ "${DRY_RUN}" == "yes" ]]; then
        echo "DRY-RUN: aws iam delete-access-key --access-key-id ${ROOT_AK:0:4}**** (root context)" >&2
        return 0
    fi
    aws_as_root iam delete-access-key --access-key-id "${ROOT_AK}" 2>/dev/null \
        || warn "Failed to delete root access key. Delete manually via the AWS console: IAM -> root user -> Security credentials -> Access keys."
    info "Root access key revoked."
}

# ── Main ────────────────────────────────────────────────────────────────────

info "=========================================="
info "AWS Standalone-Account IAM Bootstrap"
info "=========================================="
[[ -n "${_LOADED_ENV_FILE:-}" ]] && info "Config file:         ${_LOADED_ENV_FILE}"
info "Account:             ${ACCOUNT_ID}"
info "IAM User:            ${IAM_USER_NAME}"
info "Local Profile:       ${PROFILE_NAME}"
info "Region:              ${REGION}"
info "Apply Hardening:     $( [[ "${SKIP_HARDENING}" == "yes" ]] && echo no || echo yes )"
info "Create Provisioner:  $( [[ "${SKIP_PROVISIONER_ROLE}" == "yes" ]] && echo no || echo yes )"
info "External-ID:         ${EXTERNAL_ID}"
info "Mgmt Account (trust):${MANAGEMENT_ACCOUNT_ID:-<unset — trust will be local; role NOT assumable from elsewhere>}"
info "Delete Root Key:     $( [[ "${KEEP_ROOT_KEY}" == "yes" ]] && echo no || echo yes )"
info "Dry Run:             ${DRY_RUN}"
info ""

if ! confirm "Proceed?"; then
    info "Aborted by user."
    exit 0
fi

NEW_AK=""
NEW_SK=""

verify_root_identity
check_user_doesnt_exist
create_admin_user
create_access_key
write_cli_profile
verify_new_profile
run_hardening
create_provisioner_role
delete_root_access_key

info ""
info "=========================================="
info "Bootstrap complete for ${ACCOUNT_ID}"
info "=========================================="
info "  IAM user created:      ${IAM_USER_NAME}"
info "  Local CLI profile:     ${PROFILE_NAME}"
[[ "${SKIP_HARDENING}" != "yes" ]]         && info "  Account hardened:      yes (password policy, S3 BPA, EBS encryption, IMDSv2, default-VPC cleanup, region opt-outs)"
[[ "${SKIP_PROVISIONER_ROLE}" != "yes" ]]  && info "  Provisioner role:      NexusClusterProvisioner (external-id=${EXTERNAL_ID})"
[[ "${SKIP_PROVISIONER_ROLE}" != "yes" ]]  && info "  Provisioner trust:     arn:aws:iam::${MANAGEMENT_ACCOUNT_ID:-${ACCOUNT_ID}}:root"
info "  Use with any AWS tool: AWS_PROFILE=${PROFILE_NAME} <command>"
info "                    or: aws --profile ${PROFILE_NAME} <command>"
[[ "${KEEP_ROOT_KEY}" != "yes" ]] && info "  Root access key:       REVOKED"
info ""
info "Next steps:"
info "  - Sign in as root once (web console) and enable MFA on the root user."
info "  - Provision EKS / other resources using the new profile, e.g.:"
info "      cd nexus-deployer/deploy/eks"
info "      ./create-hardened-eks-cluster.sh --profile ${PROFILE_NAME} --region ${REGION} ..."
if [[ "${SKIP_PROVISIONER_ROLE}" != "yes" ]]; then
    if [[ -n "${MANAGEMENT_ACCOUNT_ID}" ]]; then
        info "  - To assume NexusClusterProvisioner from the management account ${MANAGEMENT_ACCOUNT_ID}:"
        info "      aws sts assume-role --role-arn arn:aws:iam::${ACCOUNT_ID}:role/NexusClusterProvisioner \\"
        info "                          --external-id ${EXTERNAL_ID} \\"
        info "                          --role-session-name nexus-provisioner"
    else
        info "  - WARNING: --management-account-id was NOT set. The provisioner role trusts"
        info "    arn:aws:iam::${ACCOUNT_ID}:root, so it can only be assumed from inside"
        info "    ${ACCOUNT_ID} itself. To make it assumable from a management account, either"
        info "    re-run with --management-account-id <ID>, or run this one-liner from the new"
        info "    profile to repoint the trust now:"
        info "      aws --profile ${PROFILE_NAME} iam update-assume-role-policy \\"
        info "          --role-name NexusClusterProvisioner \\"
        info "          --policy-document '{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Principal\":{\"AWS\":\"arn:aws:iam::<MGMT_ID>:root\"},\"Action\":\"sts:AssumeRole\",\"Condition\":{\"StringEquals\":{\"sts:ExternalId\":\"${EXTERNAL_ID}\"}}}]}'"
    fi
fi

# Scrub the secret material from the env on the way out.
unset ROOT_AK ROOT_SK ROOT_TOKEN NEW_AK NEW_SK

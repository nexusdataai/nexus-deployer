#!/bin/bash
#
# AWS Account Onboarding Orchestrator
#
# Takes a participant AWS account's email + root access keys and produces a
# fully-hardened member of the PTR Technologies Organization with SSO
# AdministratorAccess granted to the named user (default: papu) and the
# bootstrap root access key revoked.
#
# Phases:
#   1. Invite (mgmt creds)                  -> setup-organization.sh --single-invite
#   2. Participant bootstrap (root creds)   -> lib/participant-bootstrap.sh
#   3a. Move to OU (mgmt creds)             -> organizations move-account
#   3b. Hardening (mgmt creds)              -> secure-member-account.sh
#   3c. Cross-account role (mgmt creds)     -> setup-cross-account-roles.sh
#   3d. Security services enrollment        -> guardduty/securityhub create-members
#   3e. SSO assignment (mgmt creds)         -> lib/assign-sso-admin.sh
#   4. Compliance audit (optional)          -> audit-account-compliance.sh
#   5. Onboarding manifest JSON
#
# Usage:
#   ./onboard-account.sh \
#       --account-email new-acct@example.com \
#       --account-id 123456789012 \
#       --root-access-key-id AKIA... \
#       --root-secret-access-key SECRET... \
#       [--profile ptr-tech] \
#       [--ou NexusProduction] \
#       [--sso-user papu] \
#       [--permission-set AdministratorAccess] \
#       [--auto-approve] \
#       [--dry-run] \
#       [--skip-audit]
#
# Root keys can also be supplied via env vars:
#   PARTICIPANT_ROOT_AK, PARTICIPANT_ROOT_SK, PARTICIPANT_ROOT_TOKEN
#

set -e
set +x  # never echo commands; root secrets may be in env

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
LIB_DIR="${SCRIPT_DIR}/lib"
AUDIT_LOG_DIR="${SCRIPT_DIR}/audit-logs"

# ── Defaults ────────────────────────────────────────────────────────────────

ACCOUNT_EMAIL=""
ACCOUNT_ID=""
ROOT_AK="${PARTICIPANT_ROOT_AK:-}"
ROOT_SK="${PARTICIPANT_ROOT_SK:-}"
ROOT_TOKEN="${PARTICIPANT_ROOT_TOKEN:-}"
AWS_PROFILE_ARG="${AWS_PROFILE:-}"   # if empty, fall back to DEFAULT_PROFILE from .env.sso.local
TARGET_OU="NexusProduction"
SSO_USER="papu"
PERMISSION_SET="AdministratorAccess"
AUTO_APPROVE=no
DRY_RUN=no
SKIP_AUDIT=no
REGION="us-east-1"

while [[ $# -gt 0 ]]; do
    case $1 in
        --account-email)           ACCOUNT_EMAIL="$2"; shift 2 ;;
        --account-id)              ACCOUNT_ID="$2"; shift 2 ;;
        --root-access-key-id)      ROOT_AK="$2"; shift 2 ;;
        --root-secret-access-key)  ROOT_SK="$2"; shift 2 ;;
        --root-session-token)      ROOT_TOKEN="$2"; shift 2 ;;
        --profile)                 AWS_PROFILE_ARG="$2"; shift 2 ;;
        --ou)                      TARGET_OU="$2"; shift 2 ;;
        --sso-user)                SSO_USER="$2"; shift 2 ;;
        --permission-set)          PERMISSION_SET="$2"; shift 2 ;;
        --region)                  REGION="$2"; shift 2 ;;
        --auto-approve)            AUTO_APPROVE=yes; shift ;;
        --dry-run)                 DRY_RUN=yes; shift ;;
        --skip-audit)              SKIP_AUDIT=yes; shift ;;
        --help|-h)
            # Print the usage docblock at the top of this script.
            sed -n '2,37p' "$0"
            exit 0
            ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# Pull DEFAULT_PROFILE from the SSO env file if --profile was not given.
if [[ -z "${AWS_PROFILE_ARG}" ]]; then
    ENV_FILE="${SCRIPT_DIR}/../../../nexus-backend/.env.sso.local"
    if [[ -f "${ENV_FILE}" ]]; then
        # shellcheck disable=SC1090
        AWS_PROFILE_ARG=$(grep -E '^DEFAULT_PROFILE=' "${ENV_FILE}" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
    fi
    AWS_PROFILE_ARG="${AWS_PROFILE_ARG:-default}"
fi

# ── Logging ─────────────────────────────────────────────────────────────────

log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
info() { log "INFO  $*"; }
warn() { log "WARN  $*"; }
err()  { log "ERROR $*" >&2; }

# Manifest emission is only meaningful once we've validated inputs and at
# least started the onboarding work. die() before that point exits cleanly
# without writing a useless empty manifest.
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

run_mgmt() {
    # Wrapper around `aws --profile <mgmt>` that honors --dry-run.
    # DRY-RUN: command goes to stderr, stdout stays empty so callers that
    # capture stdout (e.g. ROOT_ID=$(run_mgmt ...)) get a clean empty string
    # instead of the "DRY-RUN: ..." marker leaking into their values.
    if [[ "${DRY_RUN}" == "yes" ]]; then
        echo "DRY-RUN: aws --profile ${AWS_PROFILE_ARG} --region ${REGION} $*" >&2
        return 0
    fi
    aws --profile "${AWS_PROFILE_ARG}" --region "${REGION}" "$@"
}

# ── Validation ──────────────────────────────────────────────────────────────

validate_inputs() {
    [[ -n "${ACCOUNT_EMAIL}" ]] || die "--account-email is required"
    [[ -n "${ACCOUNT_ID}" ]]    || die "--account-id is required"
    [[ "${ACCOUNT_ID}" =~ ^[0-9]{12}$ ]] || die "--account-id must be a 12-digit AWS account ID"
    [[ -n "${ROOT_AK}" ]]       || die "--root-access-key-id (or PARTICIPANT_ROOT_AK env var) is required"
    [[ -n "${ROOT_SK}" ]]       || die "--root-secret-access-key (or PARTICIPANT_ROOT_SK env var) is required"
    [[ -f "${LIB_DIR}/participant-bootstrap.sh" ]] || die "Missing ${LIB_DIR}/participant-bootstrap.sh"
    [[ -f "${LIB_DIR}/assign-sso-admin.sh" ]]      || die "Missing ${LIB_DIR}/assign-sso-admin.sh"
    [[ -f "${SCRIPT_DIR}/setup-organization.sh" ]]      || die "Missing setup-organization.sh"
    [[ -f "${SCRIPT_DIR}/secure-member-account.sh" ]]   || die "Missing secure-member-account.sh"
    [[ -f "${SCRIPT_DIR}/setup-cross-account-roles.sh" ]] || die "Missing setup-cross-account-roles.sh"
    VALIDATION_PASSED=yes
}

# ── Manifest accumulator ────────────────────────────────────────────────────
#
# Each step appends a JSON-friendly fragment via record_step. emit_manifest
# stitches them into a single document at the end (success or failure).

MANIFEST_TS=""
MANIFEST_PATH=""
declare -a STEPS
MASTER_ACCOUNT_ID=""
ROOT_ID=""
TARGET_OU_ID=""
HANDSHAKE_ID=""
BOOTSTRAP_JSON=""
SSO_JSON=""
AUDIT_PATH=""

json_escape() {
    python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))" <<< "$1"
}

record_step() {
    local name="$1" status="$2" detail="$3"
    local detail_esc
    detail_esc=$(json_escape "${detail}")
    STEPS+=("{\"step\":\"${name}\",\"status\":\"${status}\",\"detail\":${detail_esc}}")
}

emit_manifest() {
    local overall_status="$1" overall_detail="${2:-}"
    mkdir -p "${AUDIT_LOG_DIR}"

    if [[ -z "${MANIFEST_PATH}" ]]; then
        MANIFEST_TS=$(date -u +%Y%m%dT%H%M%SZ)
        MANIFEST_PATH="${AUDIT_LOG_DIR}/onboarding-${ACCOUNT_ID}-${MANIFEST_TS}.json"
    fi

    local steps_joined
    steps_joined=$(IFS=,; echo "${STEPS[*]}")

    local overall_detail_esc
    overall_detail_esc=$(json_escape "${overall_detail}")

    local bootstrap_block="${BOOTSTRAP_JSON:-null}"
    local sso_block="${SSO_JSON:-null}"

    cat > "${MANIFEST_PATH}" <<EOF
{
  "schema_version": "1.0",
  "tool": "onboard-account.sh",
  "timestamp_utc": "${MANIFEST_TS}",
  "overall_status": "${overall_status}",
  "overall_detail": ${overall_detail_esc},
  "dry_run": $( [[ "${DRY_RUN}" == "yes" ]] && echo true || echo false ),
  "master_account_id": "${MASTER_ACCOUNT_ID}",
  "participant_account_id": "${ACCOUNT_ID}",
  "participant_email": "${ACCOUNT_EMAIL}",
  "target_ou": "${TARGET_OU}",
  "target_ou_id": "${TARGET_OU_ID}",
  "handshake_id": "${HANDSHAKE_ID}",
  "sso_user": "${SSO_USER}",
  "permission_set": "${PERMISSION_SET}",
  "participant_bootstrap": ${bootstrap_block},
  "sso_assignment": ${sso_block},
  "compliance_audit_path": $( [[ -n "${AUDIT_PATH}" ]] && json_escape "${AUDIT_PATH}" || echo null ),
  "steps": [${steps_joined}]
}
EOF
    info "Manifest written: ${MANIFEST_PATH}"
}

# ── Phase 1: Invite ─────────────────────────────────────────────────────────

phase1_invite() {
    info ""
    info "── Phase 1: Invite ${ACCOUNT_ID} (${ACCOUNT_EMAIL}) to org ${MASTER_ACCOUNT_ID} ──"

    local out
    if [[ "${DRY_RUN}" == "yes" ]]; then
        echo "DRY-RUN: ${SCRIPT_DIR}/setup-organization.sh --single-invite --target-account-id ${ACCOUNT_ID} --target-email ${ACCOUNT_EMAIL} --profile ${AWS_PROFILE_ARG} --region ${REGION} --auto-approve"
        HANDSHAKE_ID="h-DRYRUN"
        record_step "phase1_invite" "dry_run" "HandshakeId=h-DRYRUN"
        return
    fi

    out=$("${SCRIPT_DIR}/setup-organization.sh" \
        --single-invite \
        --target-account-id "${ACCOUNT_ID}" \
        --target-email "${ACCOUNT_EMAIL}" \
        --profile "${AWS_PROFILE_ARG}" \
        --region "${REGION}" \
        --auto-approve) \
        || { record_step "phase1_invite" "failed" "${out}"; die "Phase 1 (invite) failed."; }

    HANDSHAKE_ID=$(echo "${out}" | grep -E '^HANDSHAKE_ID=' | tail -1 | cut -d= -f2)
    [[ -n "${HANDSHAKE_ID}" ]] || { record_step "phase1_invite" "failed" "No HANDSHAKE_ID marker in stdout"; die "Could not parse HandshakeId from setup-organization.sh output."; }

    if [[ "${HANDSHAKE_ID}" == "ALREADY_MEMBER" ]]; then
        info "Account is already an organization member; Phase 1 is a no-op."
        record_step "phase1_invite" "skipped" "Account already a member"
        return
    fi

    info "HandshakeId: ${HANDSHAKE_ID}"
    record_step "phase1_invite" "ok" "HandshakeId=${HANDSHAKE_ID}"
}

# ── Phase 2: Participant bootstrap (root creds) ─────────────────────────────

phase2_participant_bootstrap() {
    info ""
    info "── Phase 2: Participant bootstrap (root creds, isolated subshell) ──"

    if [[ "${HANDSHAKE_ID}" == "ALREADY_MEMBER" ]]; then
        info "Skipping phase 2 (account already joined); assuming OrganizationAccountAccessRole exists."
        BOOTSTRAP_JSON='{"skipped":true,"reason":"already_member"}'
        record_step "phase2_participant_bootstrap" "skipped" "Account already joined; assuming OAA role exists"
        return
    fi

    # Build credential context for the helper. The helper itself does
    # `unset AWS_PROFILE AWS_DEFAULT_PROFILE` and always passes
    # --region/--no-profile equivalents, so we don't need env -i (which
    # also strips terminal-capture vars and is unfriendly to debug).
    local out
    local rc
    set +e
    out=$(
        AWS_ACCESS_KEY_ID="${ROOT_AK}" \
        AWS_SECRET_ACCESS_KEY="${ROOT_SK}" \
        AWS_SESSION_TOKEN="${ROOT_TOKEN}" \
        AWS_PROFILE="" \
        AWS_DEFAULT_PROFILE="" \
        bash "${LIB_DIR}/participant-bootstrap.sh" \
            --account-id "${ACCOUNT_ID}" \
            --master-account-id "${MASTER_ACCOUNT_ID}" \
            --handshake-id "${HANDSHAKE_ID}" \
            --region "${REGION}" \
            $( [[ "${DRY_RUN}" == "yes" ]] && echo "--dry-run" ) \
        2> >(while IFS= read -r line; do echo "  [participant-bootstrap] ${line}"; done >&2))
    rc=$?
    set -e

    if [[ ${rc} -ne 0 ]]; then
        record_step "phase2_participant_bootstrap" "failed" "exit=${rc}"
        die "Phase 2 (participant-bootstrap) failed with exit ${rc}."
    fi

    BOOTSTRAP_JSON="${out}"
    record_step "phase2_participant_bootstrap" "ok" "${out}"
}

# ── Phase 3a: Move account to target OU ─────────────────────────────────────

phase3a_move_to_ou() {
    info ""
    info "── Phase 3a: Move account ${ACCOUNT_ID} to OU ${TARGET_OU} ──"

    if [[ "${DRY_RUN}" == "yes" ]]; then
        echo "DRY-RUN: aws --profile ${AWS_PROFILE_ARG} --region ${REGION} organizations list-roots" >&2
        echo "DRY-RUN: aws --profile ${AWS_PROFILE_ARG} --region ${REGION} organizations list-organizational-units-for-parent --query OUs[?Name=='${TARGET_OU}']" >&2
        echo "DRY-RUN: aws --profile ${AWS_PROFILE_ARG} --region ${REGION} organizations move-account --account-id ${ACCOUNT_ID} --destination-parent-id <ou-${TARGET_OU}>" >&2
        TARGET_OU_ID="(dry-run)"
        record_step "phase3a_move_to_ou" "dry_run" "Would move ${ACCOUNT_ID} to OU ${TARGET_OU}"
        return
    fi

    ROOT_ID=$(run_mgmt organizations list-roots --query 'Roots[0].Id' --output text)
    TARGET_OU_ID=$(run_mgmt organizations list-organizational-units-for-parent \
        --parent-id "${ROOT_ID}" \
        --query "OrganizationalUnits[?Name=='${TARGET_OU}'].Id" --output text)

    if [[ -z "${TARGET_OU_ID}" || "${TARGET_OU_ID}" == "None" ]]; then
        record_step "phase3a_move_to_ou" "failed" "OU '${TARGET_OU}' not found under root ${ROOT_ID}"
        die "OU '${TARGET_OU}' not found. Run setup-organization.sh first to create it."
    fi

    local current_parent
    current_parent=$(run_mgmt organizations list-parents --child-id "${ACCOUNT_ID}" --query 'Parents[0].Id' --output text 2>/dev/null || echo "")

    if [[ "${current_parent}" == "${TARGET_OU_ID}" ]]; then
        info "Account already in ${TARGET_OU} (${TARGET_OU_ID})."
        record_step "phase3a_move_to_ou" "skipped" "Already in target OU ${TARGET_OU_ID}"
        return
    fi

    [[ -n "${current_parent}" ]] || { record_step "phase3a_move_to_ou" "failed" "Could not resolve current parent"; die "Could not resolve current parent of ${ACCOUNT_ID}."; }

    run_mgmt organizations move-account \
        --account-id "${ACCOUNT_ID}" \
        --source-parent-id "${current_parent}" \
        --destination-parent-id "${TARGET_OU_ID}" >/dev/null

    info "Moved ${ACCOUNT_ID} from ${current_parent} to ${TARGET_OU_ID}."
    record_step "phase3a_move_to_ou" "ok" "Moved ${current_parent} -> ${TARGET_OU_ID}"
}

# ── Phase 3b: Run hardening (secure-member-account.sh) ──────────────────────

phase3b_harden() {
    info ""
    info "── Phase 3b: Run secure-member-account.sh ──"

    local rc=0
    if [[ "${DRY_RUN}" == "yes" ]]; then
        echo "DRY-RUN: ${SCRIPT_DIR}/secure-member-account.sh --account-id ${ACCOUNT_ID} --profile ${AWS_PROFILE_ARG} --region ${REGION} --auto-approve"
        record_step "phase3b_harden" "dry_run" "Would harden ${ACCOUNT_ID}"
        return
    fi

    set +e
    "${SCRIPT_DIR}/secure-member-account.sh" \
        --account-id "${ACCOUNT_ID}" \
        --profile "${AWS_PROFILE_ARG}" \
        --region "${REGION}" \
        --auto-approve \
        2> >(while IFS= read -r line; do echo "  [secure-member] ${line}"; done >&2)
    rc=$?
    set -e

    if [[ ${rc} -ne 0 ]]; then
        record_step "phase3b_harden" "failed" "secure-member-account.sh exit=${rc}"
        die "Phase 3b (hardening) failed."
    fi
    record_step "phase3b_harden" "ok" "secure-member-account.sh succeeded"
}

# ── Phase 3c: Cross-account provisioner role ────────────────────────────────

phase3c_cross_account_role() {
    info ""
    info "── Phase 3c: Run setup-cross-account-roles.sh ──"

    if [[ "${DRY_RUN}" == "yes" ]]; then
        echo "DRY-RUN: ${SCRIPT_DIR}/setup-cross-account-roles.sh --account-id ${ACCOUNT_ID} --profile ${AWS_PROFILE_ARG} --region ${REGION} --auto-approve"
        record_step "phase3c_cross_account_role" "dry_run" "Would create NexusClusterProvisioner in ${ACCOUNT_ID}"
        return
    fi

    local rc=0
    set +e
    "${SCRIPT_DIR}/setup-cross-account-roles.sh" \
        --account-id "${ACCOUNT_ID}" \
        --profile "${AWS_PROFILE_ARG}" \
        --region "${REGION}" \
        --auto-approve \
        2> >(while IFS= read -r line; do echo "  [cross-account-role] ${line}"; done >&2)
    rc=$?
    set -e

    if [[ ${rc} -ne 0 ]]; then
        record_step "phase3c_cross_account_role" "failed" "setup-cross-account-roles.sh exit=${rc}"
        die "Phase 3c (cross-account role) failed."
    fi
    record_step "phase3c_cross_account_role" "ok" "NexusClusterProvisioner created/updated"
}

# ── Phase 3d: Enroll in org security services ───────────────────────────────

phase3d_enroll_security_services() {
    info ""
    info "── Phase 3d: Enroll in GuardDuty + Security Hub as org member ──"

    # GuardDuty: find the org detector and add member.
    local det
    det=$(run_mgmt guardduty list-detectors --query 'DetectorIds[0]' --output text 2>/dev/null || echo "")
    if [[ -n "${det}" && "${det}" != "None" && "${DRY_RUN}" != "yes" ]]; then
        run_mgmt guardduty create-members \
            --detector-id "${det}" \
            --account-details "AccountId=${ACCOUNT_ID},Email=${ACCOUNT_EMAIL}" >/dev/null 2>&1 \
            || warn "guardduty create-members non-zero (may already be a member)"
        run_mgmt guardduty invite-members \
            --detector-id "${det}" \
            --account-ids "${ACCOUNT_ID}" \
            --disable-email-notification >/dev/null 2>&1 \
            || warn "guardduty invite-members non-zero (auto-enable may have handled it)"
        record_step "phase3d_guardduty" "ok" "Enrolled as guardduty member (detector=${det})"
    elif [[ "${DRY_RUN}" == "yes" ]]; then
        record_step "phase3d_guardduty" "dry_run" "Would call guardduty create-members + invite-members"
    else
        warn "No GuardDuty detector found in master account; skipping enrollment."
        record_step "phase3d_guardduty" "skipped" "No GuardDuty detector in master; run enable-security-services.sh first"
    fi

    # Security Hub: create member.
    if [[ "${DRY_RUN}" == "yes" ]]; then
        record_step "phase3d_securityhub" "dry_run" "Would call securityhub create-members"
    else
        local sh_out
        sh_out=$(run_mgmt securityhub create-members \
            --account-details "AccountId=${ACCOUNT_ID},Email=${ACCOUNT_EMAIL}" 2>&1) || true
        if echo "${sh_out}" | grep -qi "Hub not found\|InvalidAccessException"; then
            warn "Security Hub not enabled in master; skipping enrollment."
            record_step "phase3d_securityhub" "skipped" "Security Hub not enabled in master; run enable-security-services.sh first"
        else
            record_step "phase3d_securityhub" "ok" "Enrolled as securityhub member"
        fi
    fi
}

# ── Phase 3e: SSO assignment ────────────────────────────────────────────────

phase3e_sso_assignment() {
    info ""
    info "── Phase 3e: Assign ${SSO_USER} -> ${PERMISSION_SET} on ${ACCOUNT_ID} ──"

    local rc=0
    local out
    set +e
    out=$("${LIB_DIR}/assign-sso-admin.sh" \
        --account-id "${ACCOUNT_ID}" \
        --user "${SSO_USER}" \
        --permission-set "${PERMISSION_SET}" \
        --profile "${AWS_PROFILE_ARG}" \
        --region "${REGION}" \
        $( [[ "${DRY_RUN}" == "yes" ]] && echo "--dry-run" ) \
        2> >(while IFS= read -r line; do echo "  [sso-assign] ${line}"; done >&2))
    rc=$?
    set -e

    if [[ ${rc} -ne 0 ]]; then
        record_step "phase3e_sso_assignment" "failed" "assign-sso-admin.sh exit=${rc}"
        die "Phase 3e (SSO assignment) failed."
    fi

    SSO_JSON="${out}"
    record_step "phase3e_sso_assignment" "ok" "${out}"
}

# ── Phase 4: Compliance audit (optional) ────────────────────────────────────

phase4_audit() {
    if [[ "${SKIP_AUDIT}" == "yes" ]]; then
        info ""
        info "── Phase 4: Compliance audit skipped (--skip-audit) ──"
        record_step "phase4_audit" "skipped" "--skip-audit"
        return
    fi

    info ""
    info "── Phase 4: Run audit-account-compliance.sh ──"

    if [[ "${DRY_RUN}" == "yes" ]]; then
        echo "DRY-RUN: ${SCRIPT_DIR}/audit-account-compliance.sh --account-id ${ACCOUNT_ID} --profile ${AWS_PROFILE_ARG} --region ${REGION}"
        record_step "phase4_audit" "dry_run" "Would audit ${ACCOUNT_ID}"
        return
    fi

    if [[ ! -f "${SCRIPT_DIR}/audit-account-compliance.sh" ]]; then
        warn "audit-account-compliance.sh not found; skipping."
        record_step "phase4_audit" "skipped" "audit-account-compliance.sh not present"
        return
    fi

    local rc=0
    set +e
    "${SCRIPT_DIR}/audit-account-compliance.sh" \
        --account-id "${ACCOUNT_ID}" \
        --profile "${AWS_PROFILE_ARG}" \
        --region "${REGION}" \
        2> >(while IFS= read -r line; do echo "  [audit] ${line}"; done >&2)
    rc=$?
    set -e

    AUDIT_PATH=$(ls -1t /tmp/nexus-audit-*.json 2>/dev/null | head -1)
    if [[ ${rc} -eq 0 ]]; then
        record_step "phase4_audit" "ok" "${AUDIT_PATH:-(no JSON written)}"
    else
        # Audit non-zero means compliance failures; onboarding itself succeeded.
        record_step "phase4_audit" "warn" "exit=${rc} (compliance issues found); ${AUDIT_PATH:-no json}"
        warn "Compliance audit reported issues (exit ${rc}). See ${AUDIT_PATH:-stderr}."
    fi
}

# ── Main ────────────────────────────────────────────────────────────────────

main() {
    info "=========================================="
    info "AWS Account Onboarding"
    info "=========================================="
    info "Participant Account: ${ACCOUNT_ID} (${ACCOUNT_EMAIL})"
    info "Management Profile:  ${AWS_PROFILE_ARG}"
    info "Target OU:           ${TARGET_OU}"
    info "SSO User:            ${SSO_USER}"
    info "Permission Set:      ${PERMISSION_SET}"
    info "Dry Run:             ${DRY_RUN}"
    info ""

    validate_inputs

    if ! confirm "Proceed with onboarding ${ACCOUNT_ID}?"; then
        info "Aborted by user."
        exit 0
    fi

    if [[ "${DRY_RUN}" == "yes" ]]; then
        echo "DRY-RUN: aws --profile ${AWS_PROFILE_ARG} --region ${REGION} sts get-caller-identity" >&2
        MASTER_ACCOUNT_ID="(dry-run-master)"
    else
        MASTER_ACCOUNT_ID=$(run_mgmt sts get-caller-identity --query 'Account' --output text)
    fi
    info "Management account confirmed: ${MASTER_ACCOUNT_ID}"

    phase1_invite
    phase2_participant_bootstrap
    phase3a_move_to_ou
    phase3b_harden
    phase3c_cross_account_role
    phase3d_enroll_security_services
    phase3e_sso_assignment
    phase4_audit

    emit_manifest "succeeded" "All phases completed."

    info ""
    info "=========================================="
    info "Onboarding complete for ${ACCOUNT_ID}"
    info "=========================================="
    info "  HandshakeId:         ${HANDSHAKE_ID}"
    info "  Target OU:           ${TARGET_OU} (${TARGET_OU_ID})"
    info "  SSO assignment:      ${SSO_USER} -> ${PERMISSION_SET}"
    info "  Manifest:            ${MANIFEST_PATH}"
    [[ -n "${AUDIT_PATH}" ]] && info "  Compliance audit:    ${AUDIT_PATH}"
    info ""
    info "Verify access by signing in as ${SSO_USER} at the SSO portal;"
    info "${ACCOUNT_ID} should appear with ${PERMISSION_SET} role."
}

# Ensure that on any unexpected error past validation a manifest is still
# produced. Before validation we exit silently so flag-parsing errors don't
# litter audit-logs/ with empty manifests.
trap '[[ "${VALIDATION_PASSED}" == "yes" ]] && emit_manifest "failed" "Unhandled error at line $LINENO"' ERR

main

# Scrub the secret material from the env on the way out.
unset ROOT_AK ROOT_SK ROOT_TOKEN PARTICIPANT_ROOT_AK PARTICIPANT_ROOT_SK PARTICIPANT_ROOT_TOKEN

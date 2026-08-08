#!/bin/bash
#
# Context-aware foundry backup + restore using environments.conf indices.
#
# Backs up foundry-workspace DynamoDB from a source context, stores the tarball
# locally, then restores into a target context (optionally cross-account).
#
# Usage:
#   ./context-dr.sh --source 5 --target 3
#   ./context-dr.sh --source 5 --target 3 --dry-run
#   ./context-dr.sh --source 5 --target 3 --target-capability ontology --target-env dev
#   ./context-dr.sh --restore-only --target 3 --input ./out/foundry-....tar.gz
#
# Requires:
#   - environments.conf row for each index (see aws-login/set-context.sh)
#   - Source/target AWS login works via set-context.sh (ADFS or keys)
#   - Target must have {capability}-{env}-foundry-workspace DDB table provisioned
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AWS_LOGIN_DIR="$(cd "${SCRIPT_DIR}/../aws-login" && pwd)"
FOUNDRY_PY="${SCRIPT_DIR}/foundry_backup.py"
SIM_PY="${SCRIPT_DIR}/simulator_backup.py"
CONFIG_FILE="${ENVIRONMENTS_CONF:-${AWS_LOGIN_DIR}/environments.conf}"
OUT_DIR="${SCRIPT_DIR}/out"

SOURCE_IDX=""
TARGET_IDX=""
DRY_RUN=0
BACKUP_ONLY=0
RESTORE_ONLY=0
INCLUDE_SIMULATORS=0
PRUNE=0
INPUT_TAR=""
SOURCE_CAPABILITY=""
SOURCE_ENV=""
TARGET_CAPABILITY=""
TARGET_ENV=""

usage() {
    cat <<EOF
Usage: $(basename "$0") --source INDEX --target INDEX [OPTIONS]

Backup foundry-workspace from environments.conf source index, save locally,
switch to target index, and restore.

Options:
  --source INDEX           Source environments.conf index (backup)
  --target INDEX           Target environments.conf index (restore)
  --dry-run                Restore dry-run only (backup still runs)
  --backup-only            Backup to local disk; skip restore
  --restore-only           Skip backup; restore existing tarball (--input required)
  --input PATH             Tarball for --restore-only (or skip re-backup)
  --out-dir PATH           Local backup directory (default: backup-restore/out)
  --include-simulators     Also backup/restore simulator S3 data (simulator_backup.py)
  --source-capability N    Override capability parsed from source namespace
  --source-env ENV         Override env parsed from source namespace
  --target-capability N    Override capability parsed from target namespace
  --target-env ENV         Override env parsed from target namespace
  --prune                  Delete target DDB rows not in backup (destructive)
  --config FILE            Alternate environments.conf path
  --help                   Show this help

Capability/env default: parsed from namespace field ({capability}-{env})
  e.g. nexus-ai-prod -> capability=nexus-ai env=prod
       ontology-dev  -> capability=ontology env=dev

Examples:
  ./context-dr.sh --source 5 --target 3
  ./context-dr.sh --source 5 --target 3 --target-capability ontology --target-env dev --dry-run
  ./context-dr.sh --backup-only --source 5
  ./context-dr.sh --restore-only --target 3 --input ./out/foundry-nexus-ai-prod-20260807.tar.gz

List contexts:  cd ../aws-login && ./set-context.sh --list
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --source)              SOURCE_IDX="$2"; shift 2 ;;
        --target)              TARGET_IDX="$2"; shift 2 ;;
        --dry-run)             DRY_RUN=1; shift ;;
        --backup-only)         BACKUP_ONLY=1; shift ;;
        --restore-only)        RESTORE_ONLY=1; shift ;;
        --input)               INPUT_TAR="$2"; shift 2 ;;
        --out-dir)             OUT_DIR="$2"; shift 2 ;;
        --include-simulators)  INCLUDE_SIMULATORS=1; shift ;;
        --source-capability)   SOURCE_CAPABILITY="$2"; shift 2 ;;
        --source-env)          SOURCE_ENV="$2"; shift 2 ;;
        --target-capability)   TARGET_CAPABILITY="$2"; shift 2 ;;
        --target-env)          TARGET_ENV="$2"; shift 2 ;;
        --prune)               PRUNE=1; shift ;;
        --config)              CONFIG_FILE="$2"; shift 2 ;;
        --help|-h)             usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "Missing environments config: $CONFIG_FILE" >&2
    exit 1
fi
if [[ ! -f "$FOUNDRY_PY" ]]; then
    echo "Missing $FOUNDRY_PY" >&2
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 required" >&2
    exit 1
fi

if [[ "$RESTORE_ONLY" -eq 1 ]]; then
    if [[ -z "$TARGET_IDX" ]]; then
        echo "--restore-only requires --target" >&2
        exit 1
    fi
    if [[ -z "$INPUT_TAR" ]]; then
        echo "--restore-only requires --input" >&2
        exit 1
    fi
elif [[ "$BACKUP_ONLY" -eq 1 ]]; then
    if [[ -z "$SOURCE_IDX" ]]; then
        echo "--backup-only requires --source" >&2
        exit 1
    fi
elif [[ -z "$SOURCE_IDX" || -z "$TARGET_IDX" ]]; then
    echo "--source and --target are required (unless --backup-only or --restore-only)" >&2
    usage >&2
    exit 1
fi

if [[ "$BACKUP_ONLY" -eq 1 && "$RESTORE_ONLY" -eq 1 ]]; then
    echo "Cannot combine --backup-only and --restore-only" >&2
    exit 1
fi

# shellcheck source=../aws-login/lib/parse-environments.sh
. "${AWS_LOGIN_DIR}/lib/parse-environments.sh"
# shellcheck source=../aws-login/lib/kube-env.sh
. "${AWS_LOGIN_DIR}/lib/kube-env.sh"

load_row() {
    local idx="$1"
    if ! nexus_env_load_row "$idx" "$CONFIG_FILE"; then
        exit 1
    fi
}

namespace_to_capability_env() {
    local ns="$1"
    if ! nexus_env_namespace_parts "$ns"; then
        echo "Cannot parse namespace '$ns' as {capability}-{env}" >&2
        exit 1
    fi
}

activate_context() {
    local idx="$1"
    local label="$2"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Activating context [$idx] $label ..."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    nexus_aws_clear_env_credentials
    if ! "${AWS_LOGIN_DIR}/set-context.sh" "$idx"; then
        echo "set-context.sh failed for index $idx" >&2
        exit 1
    fi
    # shellcheck disable=SC1091
    source "${AWS_LOGIN_DIR}/.active-env"
    nexus_aws_clear_env_credentials
    export AWS_PROFILE AWS_REGION KUBECONFIG
}

verify_aws_session() {
    local profile="$1"
    local label="$2"
    nexus_aws_clear_env_credentials
    local acct
    acct="$(aws sts get-caller-identity --profile "$profile" --query Account --output text 2>/dev/null || echo "?")"
    echo "  AWS session [$label]: account=$acct profile=$profile"
    if [[ "$acct" == "?" ]]; then
        echo "ERROR: AWS profile '$profile' is not valid" >&2
        exit 1
    fi
}

timestamp_slug() {
    date -u +%Y%m%dT%H%M%SZ
}

mkdir -p "$OUT_DIR"

FOUNDRY_TAR=""
SIM_TAR=""

# ── Backup phase ─────────────────────────────────────────────────────
if [[ "$RESTORE_ONLY" -eq 0 ]]; then
    load_row "$SOURCE_IDX"
    SRC_LABEL="$NEXUS_ROW_LABEL"
    SRC_PROFILE="$NEXUS_ROW_PROFILE"
    SRC_REGION="$NEXUS_ROW_REGION"
    SRC_NAMESPACE="$NEXUS_ROW_NAMESPACE"

    if [[ -z "$SOURCE_CAPABILITY" || -z "$SOURCE_ENV" ]]; then
        namespace_to_capability_env "$SRC_NAMESPACE"
        SOURCE_CAPABILITY="${SOURCE_CAPABILITY:-$NEXUS_ROW_CAPABILITY}"
        SOURCE_ENV="${SOURCE_ENV:-$NEXUS_ROW_ENV}"
    fi

    activate_context "$SOURCE_IDX" "$SRC_LABEL"
    verify_aws_session "$SRC_PROFILE" "source"

    TS="$(timestamp_slug)"
    SAFE_LABEL="$(echo "$SRC_LABEL" | tr ' /' '-' | tr -cd '[:alnum:]._-' )"
    FOUNDRY_TAR="${OUT_DIR}/foundry-${SOURCE_CAPABILITY}-${SOURCE_ENV}-${SAFE_LABEL}-${TS}.tar.gz"

    echo ""
    echo "Backing up foundry-workspace..."
    echo "  capability:  $SOURCE_CAPABILITY"
    echo "  env:         $SOURCE_ENV"
    echo "  profile:     $SRC_PROFILE"
    echo "  region:      $SRC_REGION"
    echo "  output:      $FOUNDRY_TAR"
    echo ""

    export SILENCE_FOUNDRY_BACKUP_DEPRECATION=1
    python3 "$FOUNDRY_PY" backup \
        --capability "$SOURCE_CAPABILITY" \
        --env "$SOURCE_ENV" \
        --profile "$SRC_PROFILE" \
        --region "$SRC_REGION" \
        -o "$FOUNDRY_TAR"

    echo ""
    python3 "$FOUNDRY_PY" inspect -i "$FOUNDRY_TAR"

    if [[ "$INCLUDE_SIMULATORS" -eq 1 ]]; then
        SIM_TAR="${OUT_DIR}/sim-${SOURCE_CAPABILITY}-${SOURCE_ENV}-${SAFE_LABEL}-${TS}.tar.gz"
        echo ""
        echo "Backing up simulator S3 data -> $SIM_TAR"
        python3 "$SIM_PY" backup \
            --capability "$SOURCE_CAPABILITY" \
            --env "$SOURCE_ENV" \
            --profile "$SRC_PROFILE" \
            --region "$SRC_REGION" \
            -o "$SIM_TAR"
    fi

    echo ""
    echo "Backup saved: $FOUNDRY_TAR"
    [[ -n "$SIM_TAR" ]] && echo "Simulator backup: $SIM_TAR"
fi

if [[ "$BACKUP_ONLY" -eq 1 ]]; then
    echo ""
    echo "Done (--backup-only). Restore later with:"
    echo "  $0 --restore-only --target ${TARGET_IDX:-TARGET} --input $FOUNDRY_TAR"
    if [[ -n "$TARGET_IDX" ]]; then
        echo "  # or full pipeline target:"
        echo "  $0 --restore-only --target $TARGET_IDX --input $FOUNDRY_TAR"
    fi
    exit 0
fi

# ── Restore phase ────────────────────────────────────────────────────
if [[ -n "$INPUT_TAR" ]]; then
    FOUNDRY_TAR="$INPUT_TAR"
fi
if [[ -z "$FOUNDRY_TAR" || ! -f "$FOUNDRY_TAR" ]]; then
    echo "Foundry tarball missing: ${FOUNDRY_TAR:-<unset>}" >&2
    exit 1
fi

load_row "$TARGET_IDX"
TGT_LABEL="$NEXUS_ROW_LABEL"
TGT_PROFILE="$NEXUS_ROW_PROFILE"
TGT_REGION="$NEXUS_ROW_REGION"
TGT_NAMESPACE="$NEXUS_ROW_NAMESPACE"

if [[ -z "$TARGET_CAPABILITY" || -z "$TARGET_ENV" ]]; then
    namespace_to_capability_env "$TGT_NAMESPACE"
    TARGET_CAPABILITY="${TARGET_CAPABILITY:-$NEXUS_ROW_CAPABILITY}"
    TARGET_ENV="${TARGET_ENV:-$NEXUS_ROW_ENV}"
fi

activate_context "$TARGET_IDX" "$TGT_LABEL"
verify_aws_session "$TGT_PROFILE" "target"

echo ""
echo "Restoring foundry-workspace..."
echo "  input:       $FOUNDRY_TAR"
echo "  capability:  $TARGET_CAPABILITY"
echo "  env:         $TARGET_ENV"
echo "  profile:     $TGT_PROFILE"
echo "  region:      $TGT_REGION"
echo "  dry-run:     $([[ "$DRY_RUN" -eq 1 ]] && echo yes || echo no)"
echo "  prune:       $([[ "$PRUNE" -eq 1 ]] && echo yes || echo no)"
echo ""

RESTORE_ARGS=(
    restore
    -i "$FOUNDRY_TAR"
    --target-capability "$TARGET_CAPABILITY"
    --target-env "$TARGET_ENV"
    --target-profile "$TGT_PROFILE"
    --target-region "$TGT_REGION"
)
[[ "$DRY_RUN" -eq 1 ]] && RESTORE_ARGS+=(--dry-run)
[[ "$PRUNE" -eq 1 ]] && RESTORE_ARGS+=(--prune)

export SILENCE_FOUNDRY_BACKUP_DEPRECATION=1
python3 "$FOUNDRY_PY" "${RESTORE_ARGS[@]}"

if [[ "$DRY_RUN" -eq 0 && "$INCLUDE_SIMULATORS" -eq 1 && -n "$SIM_TAR" && -f "$SIM_TAR" ]]; then
    echo ""
    echo "Restoring simulator S3 data from $SIM_TAR ..."
    SIM_RESTORE_ARGS=(
        restore
        -i "$SIM_TAR"
        --target-capability "$TARGET_CAPABILITY"
        --target-env "$TARGET_ENV"
        --target-profile "$TGT_PROFILE"
        --region "$TGT_REGION"
    )
    [[ "$DRY_RUN" -eq 1 ]] && SIM_RESTORE_ARGS+=(--dry-run)
    python3 "$SIM_PY" "${SIM_RESTORE_ARGS[@]}"
fi

echo ""
if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "Dry-run complete. Re-run without --dry-run to apply restore."
else
    echo "Restore complete."
    echo ""
    echo "Post-restore (recommended):"
    echo "  1. kubectl rollout restart deployment/${TARGET_CAPABILITY}-${TARGET_ENV}-backend -n ${TARGET_CAPABILITY}-${TARGET_ENV}"
    echo "  2. POST /api/v1/control-plane/entities/refresh on the target backend"
    echo "  3. Run Knowledge Processor (semantic_rag) to rebuild pgvector / AGE indexes"
fi
echo ""
echo "Foundry tarball kept at: $FOUNDRY_TAR"

#!/bin/bash
#
# Context-aware full-environment DR using environments.conf indices.
#
# Backs up foundry-workspace + transformation-system + simulator S3 from a
# source context, restores into target, runs semantic_rag, and verifies.
#
# Usage:
#   ./context-dr.sh --source 5 --target 3
#   ./context-dr.sh --source 5 --target 3 --target-capability ontology --target-env dev
#   ./context-dr.sh --source 5 --target 3 --mirror
#   ./context-dr.sh --preflight-only --target 3 --target-capability ontology --target-env dev
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AWS_LOGIN_DIR="$(cd "${SCRIPT_DIR}/../aws-login" && pwd)"
FOUNDRY_PY="${SCRIPT_DIR}/foundry_backup.py"
TRANSFORM_PY="${SCRIPT_DIR}/transformation_backup.py"
SIM_PY="${SCRIPT_DIR}/simulator_backup.py"
PREFLIGHT_PY="${SCRIPT_DIR}/dr_preflight.py"
POSTGRES_PY="${SCRIPT_DIR}/dr_postgres.py"
SEMANTIC_RAG_PY="${SCRIPT_DIR}/dr_semantic_rag.py"
VERIFY_PY="${SCRIPT_DIR}/dr_verify.py"
CONFIG_FILE="${ENVIRONMENTS_CONF:-${AWS_LOGIN_DIR}/environments.conf}"
OUT_DIR="${SCRIPT_DIR}/out"

SOURCE_IDX=""
TARGET_IDX=""
DRY_RUN=0
BACKUP_ONLY=0
RESTORE_ONLY=0
INCLUDE_SIMULATORS=1
INCLUDE_JOURNEYS=1
MIRROR=0
PRUNE=0
VERIFY=1
VERIFY_TIER=5
SKIP_PREFLIGHT=0
PREFLIGHT_ONLY=0
SKIP_SEMANTIC_RAG=0
SKIP_POSTGRES=0
SEMANTIC_RAG_TIMEOUT=2700
SKIP_BACKEND_RESTART=0
UI_SMOKE=0
INPUT_TAR=""
SOURCE_CAPABILITY=""
SOURCE_ENV=""
TARGET_CAPABILITY=""
TARGET_ENV=""
SEMANTIC_RAG_JOURNEY_ID=""
TS=""
DR_REPORT=""

usage() {
    cat <<EOF
Usage: $(basename "$0") --source INDEX --target INDEX [OPTIONS]

Full environment mimic: backup source, restore target, run semantic_rag, verify.

Options:
  --source INDEX              Source environments.conf index (backup)
  --target INDEX              Target environments.conf index (restore)
  --dry-run                   Restore dry-run only (backup still runs)
  --backup-only               Backup to local disk; skip restore
  --restore-only              Skip backup; restore existing tarball (--input required)
  --input PATH                Tarball for --restore-only
  --out-dir PATH              Local backup directory (default: backup-restore/out)
  --mirror                    Destructive exact match (DDB --prune + sim prefix clean)
  --skip-simulators           Skip simulator S3 backup/restore (default: included)
  --skip-journeys             Skip transformation-system backup/restore
  --skip-semantic-rag         Skip Knowledge Processor run after restore
  --skip-postgres             Skip pgvector Postgres ensure step
  --skip-preflight            Skip target preflight checks
  --preflight-only            Validate target readiness only; no backup/restore
  --semantic-rag-timeout SEC  Poll timeout for semantic_rag (default: 2700)
  --semantic-rag-journey-id ID  Override Knowledge Processor journey ID
  --source-capability N       Override source capability
  --source-env ENV            Override source env
  --target-capability N       Override target capability
  --target-env ENV            Override target env
  --prune                     Delete target DDB rows not in backup (same as --mirror for DDB)
  --no-verify                 Skip all post-restore verification
  --verify-tier N             Run verification tiers 2..N (default: 5)
  --ui-smoke                  Optional ALB HTTP smoke checks
  --skip-backend-restart      Skip kubectl rollout restart after restore
  --config FILE               Alternate environments.conf path
  --help                      Show this help

Examples:
  ./context-dr.sh --source 5 --target 3 --target-capability ontology --target-env dev
  ./context-dr.sh --source 5 --target 3 --mirror
  ./context-dr.sh --preflight-only --target 3 --target-capability ontology --target-env dev

List contexts:  cd ../aws-login && ./set-context.sh --list
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --source)                 SOURCE_IDX="$2"; shift 2 ;;
        --target)                 TARGET_IDX="$2"; shift 2 ;;
        --dry-run)                DRY_RUN=1; shift ;;
        --backup-only)            BACKUP_ONLY=1; shift ;;
        --restore-only)           RESTORE_ONLY=1; shift ;;
        --input)                  INPUT_TAR="$2"; shift 2 ;;
        --out-dir)                OUT_DIR="$2"; shift 2 ;;
        --mirror)                 MIRROR=1; PRUNE=1; shift ;;
        --skip-simulators)        INCLUDE_SIMULATORS=0; shift ;;
        --skip-journeys)          INCLUDE_JOURNEYS=0; shift ;;
        --skip-semantic-rag)      SKIP_SEMANTIC_RAG=1; shift ;;
        --skip-postgres)          SKIP_POSTGRES=1; shift ;;
        --skip-preflight)         SKIP_PREFLIGHT=1; shift ;;
        --preflight-only)         PREFLIGHT_ONLY=1; shift ;;
        --semantic-rag-timeout)   SEMANTIC_RAG_TIMEOUT="$2"; shift 2 ;;
        --semantic-rag-journey-id) SEMANTIC_RAG_JOURNEY_ID="$2"; shift 2 ;;
        --source-capability)      SOURCE_CAPABILITY="$2"; shift 2 ;;
        --source-env)             SOURCE_ENV="$2"; shift 2 ;;
        --target-capability)      TARGET_CAPABILITY="$2"; shift 2 ;;
        --target-env)             TARGET_ENV="$2"; shift 2 ;;
        --prune)                  PRUNE=1; shift ;;
        --no-verify)              VERIFY=0; shift ;;
        --verify-tier)            VERIFY_TIER="$2"; shift 2 ;;
        --ui-smoke)               UI_SMOKE=1; shift ;;
        --skip-backend-restart)   SKIP_BACKEND_RESTART=1; shift ;;
        --config)                 CONFIG_FILE="$2"; shift 2 ;;
        --help|-h)                usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

if [[ "$MIRROR" -eq 1 ]]; then
    echo ""
    echo "WARNING: --mirror is destructive — target-only DDB rows and stale simulator S3 keys will be removed."
    echo ""
fi

if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "Missing environments config: $CONFIG_FILE" >&2
    exit 1
fi
for f in "$FOUNDRY_PY" "$TRANSFORM_PY" "$SIM_PY"; do
    if [[ ! -f "$f" ]]; then
        echo "Missing $f" >&2
        exit 1
    fi
done
if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 required" >&2
    exit 1
fi

if [[ "$PREFLIGHT_ONLY" -eq 1 ]]; then
    if [[ -z "$TARGET_IDX" ]]; then
        echo "--preflight-only requires --target" >&2
        exit 1
    fi
elif [[ "$RESTORE_ONLY" -eq 1 ]]; then
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
    echo "--source and --target are required" >&2
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

run_preflight() {
    local cap="$1" env="$2" profile="$3" region="$4"
    local ns="$5" dep="$6"
    local sim_flag=() pg_flag=()
    if [[ "$INCLUDE_SIMULATORS" -eq 1 ]]; then
        sim_flag=(--require-simulators)
    else
        sim_flag=(--skip-simulators)
    fi
    if [[ "$SKIP_SEMANTIC_RAG" -eq 0 && "$SKIP_POSTGRES" -eq 0 ]]; then
        pg_flag=(--require-postgres)
    fi
    echo ""
    echo "Phase 0: Preflight checks..."
    python3 "$PREFLIGHT_PY" \
        --capability "$cap" --env "$env" \
        --profile "$profile" --region "$region" \
        --namespace "$ns" --deployment "$dep" \
        "${sim_flag[@]}" "${pg_flag[@]}"
}

entity_refresh() {
    local ns="$1" dep="$2"
    echo ""
    echo "Post-restore: entity catalog refresh..."
    if kubectl exec -n "$ns" "deploy/${dep}" -- \
        curl -sf -X POST --max-time 60 \
        http://127.0.0.1:8000/api/v1/control-plane/entities/refresh >/dev/null 2>&1; then
        echo "  entity-refresh: OK"
    else
        echo "  WARN: entity-refresh failed" >&2
    fi
}

timestamp_slug() {
    date -u +%Y%m%dT%H%M%SZ
}

mkdir -p "$OUT_DIR"

FOUNDRY_TAR=""
TRANSFORM_TAR=""
SIM_TAR=""
SEMANTIC_RAG_RESULT=""
RESULT_STATUS="PASS"
TIER1_OK="skip"
SEMANTIC_RAG_OK="skip"
VERIFY_OK="skip"

# ── Preflight-only mode ───────────────────────────────────────────────
if [[ "$PREFLIGHT_ONLY" -eq 1 ]]; then
    load_row "$TARGET_IDX"
    namespace_to_capability_env "$NEXUS_ROW_NAMESPACE"
    TARGET_CAPABILITY="${TARGET_CAPABILITY:-$NEXUS_ROW_CAPABILITY}"
    TARGET_ENV="${TARGET_ENV:-$NEXUS_ROW_ENV}"
    activate_context "$TARGET_IDX" "$NEXUS_ROW_LABEL"
    verify_aws_session "$NEXUS_ROW_PROFILE" "target"
    TARGET_NS="${TARGET_CAPABILITY}-${TARGET_ENV}"
    BACKEND_DEPLOY="${TARGET_NS}-backend"
    run_preflight "$TARGET_CAPABILITY" "$TARGET_ENV" "$NEXUS_ROW_PROFILE" "$NEXUS_ROW_REGION" \
        "$TARGET_NS" "$BACKEND_DEPLOY"
    exit $?
fi

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
    DR_REPORT="${OUT_DIR}/dr-report-${TS}.json"

    echo ""
    echo "Phase 1: Backing up foundry-workspace..."
    export SILENCE_FOUNDRY_BACKUP_DEPRECATION=1
    python3 "$FOUNDRY_PY" backup \
        --capability "$SOURCE_CAPABILITY" --env "$SOURCE_ENV" \
        --profile "$SRC_PROFILE" --region "$SRC_REGION" \
        -o "$FOUNDRY_TAR"
    python3 "$FOUNDRY_PY" inspect -i "$FOUNDRY_TAR"

    if [[ "$INCLUDE_JOURNEYS" -eq 1 ]]; then
        TRANSFORM_TAR="${OUT_DIR}/transformation-${SOURCE_CAPABILITY}-${SOURCE_ENV}-${SAFE_LABEL}-${TS}.tar.gz"
        echo ""
        echo "Phase 1: Backing up transformation-system (journeys)..."
        python3 "$TRANSFORM_PY" backup \
            --capability "$SOURCE_CAPABILITY" --env "$SOURCE_ENV" \
            --profile "$SRC_PROFILE" --region "$SRC_REGION" \
            -o "$TRANSFORM_TAR"
        python3 "$TRANSFORM_PY" inspect -i "$TRANSFORM_TAR"
    fi

    if [[ "$INCLUDE_SIMULATORS" -eq 1 ]]; then
        SIM_TAR="${OUT_DIR}/sim-${SOURCE_CAPABILITY}-${SOURCE_ENV}-${SAFE_LABEL}-${TS}.tar.gz"
        echo ""
        echo "Phase 1: Backing up simulator S3 data..."
        export SILENCE_SIMULATOR_BACKUP_HINT=1
        python3 "$SIM_PY" backup \
            --capability "$SOURCE_CAPABILITY" --env "$SOURCE_ENV" \
            --profile "$SRC_PROFILE" --region "$SRC_REGION" \
            -o "$SIM_TAR"
    fi

    echo ""
    echo "Backup complete:"
    echo "  $FOUNDRY_TAR"
    [[ -n "$TRANSFORM_TAR" ]] && echo "  $TRANSFORM_TAR"
    [[ -n "$SIM_TAR" ]] && echo "  $SIM_TAR"
fi

if [[ "$BACKUP_ONLY" -eq 1 ]]; then
    echo ""
    echo "Done (--backup-only)."
    exit 0
fi

# ── Restore phase ────────────────────────────────────────────────────
if [[ -n "$INPUT_TAR" ]]; then
    FOUNDRY_TAR="$INPUT_TAR"
    if [[ -z "$TRANSFORM_TAR" && "$INCLUDE_JOURNEYS" -eq 1 ]]; then
        TRANSFORM_TAR="${FOUNDRY_TAR/foundry-/transformation-}"
    fi
    if [[ -z "$SIM_TAR" && "$INCLUDE_SIMULATORS" -eq 1 ]]; then
        SIM_TAR="${FOUNDRY_TAR/foundry-/sim-}"
    fi
    if [[ -z "$TS" ]]; then
        TS="$(timestamp_slug)"
        DR_REPORT="${OUT_DIR}/dr-report-${TS}.json"
    fi
fi
if [[ -z "$FOUNDRY_TAR" || ! -f "$FOUNDRY_TAR" ]]; then
    echo "Foundry tarball missing: ${FOUNDRY_TAR:-<unset>}" >&2
    exit 1
fi
[[ -z "$DR_REPORT" ]] && DR_REPORT="${OUT_DIR}/dr-report-$(timestamp_slug).json"

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

TARGET_NS="${TARGET_CAPABILITY}-${TARGET_ENV}"
BACKEND_DEPLOY="${TARGET_NS}-backend"

if [[ "$SKIP_PREFLIGHT" -eq 0 && "$DRY_RUN" -eq 0 ]]; then
    run_preflight "$TARGET_CAPABILITY" "$TARGET_ENV" "$TGT_PROFILE" "$TGT_REGION" \
        "$TARGET_NS" "$BACKEND_DEPLOY"
fi

echo ""
echo "Phase 2: Restoring foundry-workspace..."
RESTORE_ARGS=(
    restore -i "$FOUNDRY_TAR"
    --target-capability "$TARGET_CAPABILITY" --target-env "$TARGET_ENV"
    --target-profile "$TGT_PROFILE" --target-region "$TGT_REGION"
)
[[ "$DRY_RUN" -eq 1 ]] && RESTORE_ARGS+=(--dry-run)
[[ "$PRUNE" -eq 1 ]] && RESTORE_ARGS+=(--prune)
export SILENCE_FOUNDRY_BACKUP_DEPRECATION=1
python3 "$FOUNDRY_PY" "${RESTORE_ARGS[@]}"

if [[ "$INCLUDE_JOURNEYS" -eq 1 ]]; then
    if [[ -z "$TRANSFORM_TAR" || ! -f "$TRANSFORM_TAR" ]]; then
        echo "WARN: journeys tarball missing; skipping transformation-system restore" >&2
    else
        echo ""
        echo "Phase 2: Restoring transformation-system (journeys)..."
        TRANSFORM_RESTORE_ARGS=(
            restore -i "$TRANSFORM_TAR"
            --target-capability "$TARGET_CAPABILITY" --target-env "$TARGET_ENV"
            --target-profile "$TGT_PROFILE" --target-region "$TGT_REGION"
        )
        [[ "$DRY_RUN" -eq 1 ]] && TRANSFORM_RESTORE_ARGS+=(--dry-run)
        [[ "$PRUNE" -eq 1 ]] && TRANSFORM_RESTORE_ARGS+=(--prune)
        python3 "$TRANSFORM_PY" "${TRANSFORM_RESTORE_ARGS[@]}"
    fi
fi

if [[ "$INCLUDE_SIMULATORS" -eq 1 && -n "$SIM_TAR" && -f "$SIM_TAR" ]]; then
    echo ""
    echo "Phase 2: Restoring simulator S3 data..."
    SIM_RESTORE_ARGS=(
        restore -i "$SIM_TAR"
        --target-capability "$TARGET_CAPABILITY" --target-env "$TARGET_ENV"
        --target-profile "$TGT_PROFILE" --region "$TGT_REGION"
    )
    [[ "$DRY_RUN" -eq 1 ]] && SIM_RESTORE_ARGS+=(--dry-run)
    export SILENCE_SIMULATOR_BACKUP_HINT=1
    python3 "$SIM_PY" "${SIM_RESTORE_ARGS[@]}"
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo ""
    echo "Dry-run complete. Re-run without --dry-run to apply restore."
    exit 0
fi

echo ""
echo "Phase 2: Restore complete."

# ── Phase 3: Post-restore hooks ──────────────────────────────────────
if [[ "$SKIP_BACKEND_RESTART" -eq 0 ]] && command -v kubectl >/dev/null 2>&1; then
    echo ""
    echo "Phase 3: Restarting backend..."
    if kubectl rollout restart "deployment/${BACKEND_DEPLOY}" -n "$TARGET_NS" >/dev/null 2>&1; then
        kubectl rollout status "deployment/${BACKEND_DEPLOY}" -n "$TARGET_NS" --timeout=180s >/dev/null 2>&1 || true
        if kubectl exec -n "$TARGET_NS" "deploy/${BACKEND_DEPLOY}" -- \
            curl -sf --max-time 10 http://127.0.0.1:8000/health >/dev/null 2>&1; then
            echo "  Backend health: OK"
        else
            echo "  WARN: backend health check failed" >&2
        fi
    else
        echo "  WARN: could not restart deployment/${BACKEND_DEPLOY}" >&2
    fi
fi

if command -v kubectl >/dev/null 2>&1; then
    entity_refresh "$TARGET_NS" "$BACKEND_DEPLOY"
fi

# ── Phase 3.5: pgvector Postgres (semantic_rag prerequisite) ─────────
POSTGRES_OK="SKIP"
if [[ "$SKIP_POSTGRES" -eq 0 ]] && [[ "$SKIP_SEMANTIC_RAG" -eq 0 ]] && command -v kubectl >/dev/null 2>&1 && [[ -f "$POSTGRES_PY" ]]; then
    echo ""
    echo "Phase 3.5: Ensuring pgvector Postgres for semantic_rag..."
    if python3 "$POSTGRES_PY" --namespace "$TARGET_NS" --deployment "$BACKEND_DEPLOY"; then
        POSTGRES_OK="OK"
    else
        POSTGRES_OK="FAIL"
        RESULT_STATUS="FAIL"
    fi
else
    echo ""
    echo "Phase 3.5: Skipping pgvector Postgres ensure"
fi

# ── Phase 4: semantic_rag ────────────────────────────────────────────
SEMANTIC_RAG_RESULT="${OUT_DIR}/semantic-rag-${TS:-$(timestamp_slug)}.json"
if [[ "$SKIP_SEMANTIC_RAG" -eq 0 ]] && command -v kubectl >/dev/null 2>&1 && [[ -f "$SEMANTIC_RAG_PY" ]]; then
    echo ""
    echo "Phase 4: Running Knowledge Processor (semantic_rag)..."
    SR_ARGS=(
        --namespace "$TARGET_NS" --deployment "$BACKEND_DEPLOY"
        --timeout "$SEMANTIC_RAG_TIMEOUT"
        --output "$SEMANTIC_RAG_RESULT"
    )
    [[ -n "$SEMANTIC_RAG_JOURNEY_ID" ]] && SR_ARGS+=(--journey-id "$SEMANTIC_RAG_JOURNEY_ID")
    [[ -n "$TRANSFORM_TAR" && -f "$TRANSFORM_TAR" ]] && SR_ARGS+=(--transform-tar "$TRANSFORM_TAR")
    if python3 "$SEMANTIC_RAG_PY" "${SR_ARGS[@]}"; then
        SEMANTIC_RAG_OK="OK"
    else
        SEMANTIC_RAG_OK="FAIL"
        RESULT_STATUS="FAIL"
    fi
else
    echo ""
    echo "Phase 4: Skipping semantic_rag"
fi

# ── Phase 5: Verification ────────────────────────────────────────────
if [[ "$VERIFY" -eq 1 ]]; then
    echo ""
    echo "Phase 5: Tier 1 — DynamoDB verification..."
    TIER1_OK="OK"
    VERIFY_ARGS=(
        verify -i "$FOUNDRY_TAR" --by-prefix
        --target-capability "$TARGET_CAPABILITY" --target-env "$TARGET_ENV"
        --target-profile "$TGT_PROFILE" --target-region "$TGT_REGION"
    )
    if ! python3 "$FOUNDRY_PY" "${VERIFY_ARGS[@]}"; then
        TIER1_OK="FAIL"
        RESULT_STATUS="FAIL"
    fi
    if [[ "$INCLUDE_JOURNEYS" -eq 1 && -n "$TRANSFORM_TAR" && -f "$TRANSFORM_TAR" ]]; then
        TRANSFORM_VERIFY_ARGS=(
            verify -i "$TRANSFORM_TAR"
            --target-capability "$TARGET_CAPABILITY" --target-env "$TARGET_ENV"
            --target-profile "$TGT_PROFILE" --target-region "$TGT_REGION"
        )
        if ! python3 "$TRANSFORM_PY" "${TRANSFORM_VERIFY_ARGS[@]}"; then
            TIER1_OK="FAIL"
            RESULT_STATUS="FAIL"
        fi
    fi
    if [[ "$INCLUDE_SIMULATORS" -eq 1 && -n "$SIM_TAR" && -f "$SIM_TAR" ]]; then
        SIM_VERIFY_ARGS=(
            verify -i "$SIM_TAR"
            --target-capability "$TARGET_CAPABILITY" --target-env "$TARGET_ENV"
            --target-profile "$TGT_PROFILE" --region "$TGT_REGION"
            --namespace "$TARGET_NS" --deployment "$BACKEND_DEPLOY"
        )
        if ! python3 "$SIM_PY" "${SIM_VERIFY_ARGS[@]}"; then
            TIER1_OK="FAIL"
            RESULT_STATUS="FAIL"
        fi
    fi

    if command -v kubectl >/dev/null 2>&1 && [[ -f "$VERIFY_PY" ]]; then
        echo ""
        echo "Phase 5: Tiers 2-${VERIFY_TIER} — API / index / RAG verification..."
        DR_VERIFY_ARGS=(
            --namespace "$TARGET_NS" --deployment "$BACKEND_DEPLOY"
            --foundry-tar "$FOUNDRY_TAR"
            --max-tier "$VERIFY_TIER"
        )
        [[ -n "$TRANSFORM_TAR" && -f "$TRANSFORM_TAR" ]] && DR_VERIFY_ARGS+=(--transform-tar "$TRANSFORM_TAR")
        [[ -n "$SIM_TAR" && -f "$SIM_TAR" ]] && DR_VERIFY_ARGS+=(--sim-tar "$SIM_TAR")
        [[ -f "$SEMANTIC_RAG_RESULT" ]] && DR_VERIFY_ARGS+=(--semantic-rag-result "$SEMANTIC_RAG_RESULT")
        [[ "$SKIP_SEMANTIC_RAG" -eq 1 ]] && DR_VERIFY_ARGS+=(--skip-semantic-rag)
        if python3 "$VERIFY_PY" "${DR_VERIFY_ARGS[@]}"; then
            VERIFY_OK="OK"
        else
            VERIFY_OK="FAIL"
            RESULT_STATUS="FAIL"
        fi
    fi
fi

# ── Optional UI smoke ────────────────────────────────────────────────
if [[ "$UI_SMOKE" -eq 1 ]] && command -v kubectl >/dev/null 2>&1; then
    echo ""
    echo "Phase 6: UI smoke (ALB)..."
    ALB="$(kubectl get ingress -n "$TARGET_NS" -o jsonpath='{.items[0].status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)"
    if [[ -n "$ALB" ]]; then
        for path in "/health" "/api/v1/solution-catalog" "/api/v1/journeys/?limit=10"; do
            code="$(curl -sk -o /dev/null -w '%{http_code}' "https://${ALB}${path}" 2>/dev/null || echo 0)"
            echo "  GET ${path} -> HTTP ${code}"
        done
    else
        echo "  WARN: no ALB ingress found in ${TARGET_NS}"
    fi
fi

# ── Summary report ───────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Context DR Summary"
echo "  Source: [${SOURCE_IDX:-?}] ${SRC_LABEL:-restore-only}"
echo "  Target: [${TARGET_IDX}] ${TGT_LABEL} (${TARGET_NS})"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Restore:      OK (mirror=$([[ "$MIRROR" -eq 1 ]] && echo yes || echo no))"
echo "  pgvector:     ${POSTGRES_OK}"
echo "  semantic_rag: ${SEMANTIC_RAG_OK}"
echo "  Verify tier1: ${TIER1_OK}"
echo "  Verify 2-${VERIFY_TIER}: ${VERIFY_OK}"
echo "  Tarballs:"
echo "    $FOUNDRY_TAR"
[[ -n "$TRANSFORM_TAR" && -f "$TRANSFORM_TAR" ]] && echo "    $TRANSFORM_TAR"
[[ -n "$SIM_TAR" && -f "$SIM_TAR" ]] && echo "    $SIM_TAR"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "RESULT: ${RESULT_STATUS}"
echo ""

python3 - "$DR_REPORT" "$RESULT_STATUS" "$FOUNDRY_TAR" "$TRANSFORM_TAR" "$SIM_TAR" "$SEMANTIC_RAG_RESULT" <<'PYEOF'
import json, sys
path, status, foundry, transform, sim, sr = sys.argv[1:7]
report = {
    "result": status,
    "foundry_tar": foundry,
    "transform_tar": transform or None,
    "sim_tar": sim or None,
    "semantic_rag_result": sr if sr and __import__("os").path.isfile(sr) else None,
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2)
    f.write("\n")
print(f"Report: {path}")
PYEOF

[[ "$RESULT_STATUS" == "PASS" ]] || exit 1

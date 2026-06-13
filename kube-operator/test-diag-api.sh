#!/bin/bash
# test-diag-api.sh -- Probe every backend health/diagnostics HTTP endpoint
#                     listed in OpsTraining/index.md §2 Identifying Issues, Option 3
#                     and print an ASCII table summarising each result.
#
# By default runs `kubectl exec` against a Running backend pod and curls
# localhost:8000 from inside the pod (no AWS auth or ALB needed). Override
# with --alb-host or --backend-url to probe via the public ALB or a port-forward.
#
# Usage:
#   sh test-diag-api.sh                                  # auto-detect backend pod
#   sh test-diag-api.sh --alb-host app.example.com       # probe via the public ALB
#   sh test-diag-api.sh --backend-url http://localhost:8000   # custom URL (port-forward)
#   sh test-diag-api.sh --namespace nexus-ai-prod
#   sh test-diag-api.sh --context starhub-test
#   sh test-diag-api.sh --json                           # machine-readable JSON
#   sh test-diag-api.sh --strict                         # exit non-zero on any FAIL
#   sh test-diag-api.sh --timeout 30                     # per-request timeout (default 20s)
#   sh test-diag-api.sh --skip-slow                      # skip /api/v1/diagnostics/nexus-ai (slow)
#   sh test-diag-api.sh --help

set -u

# ── Colours (ANSI-C quoting so $VAR carries a real ESC byte) ──────
GREEN=$'\033[32m'
RED=$'\033[31m'
YELLOW=$'\033[33m'
CYAN=$'\033[36m'
BOLD=$'\033[1m'
DIM=$'\033[2m'
RESET=$'\033[0m'

# ── Defaults ───────────────────────────────────────────────────────
NAMESPACE=""
CONTEXT=""
BACKEND_URL=""
ALB_HOST=""
TIMEOUT=20
JSON_MODE=0
STRICT_MODE=0
NO_COLOR=0
SKIP_SLOW=0

# ── Load .env.local (if present; CLI args override) ────────────────
_script_dir="$(cd "$(dirname "$0")" && pwd)"
_env_local="${_script_dir}/.env.local"
[ -f "$_env_local" ] && . "$_env_local"
unset _script_dir _env_local

# ── Argument parsing ───────────────────────────────────────────────
while [ $# -gt 0 ]; do
    case "$1" in
        --backend-url) BACKEND_URL="$2"; shift 2 ;;
        --alb-host)    ALB_HOST="$2"; shift 2 ;;
        --namespace|-n) NAMESPACE="$2"; shift 2 ;;
        --context)     CONTEXT="$2"; shift 2 ;;
        --timeout)     TIMEOUT="$2"; shift 2 ;;
        --json|-j)     JSON_MODE=1; shift ;;
        --strict)      STRICT_MODE=1; shift ;;
        --no-color)    NO_COLOR=1; shift ;;
        --skip-slow)   SKIP_SLOW=1; shift ;;
        --help|-h)
            cat <<'EOF'
test-diag-api.sh -- Probe backend health/diagnostics endpoints

Usage: sh test-diag-api.sh [OPTIONS]

Options:
  --backend-url URL    Direct URL to the backend (skips kubectl exec)
  --alb-host HOST      Public ALB host -> probe via https://HOST
  --namespace NS       Kubernetes namespace (default: auto-detect)
  --context CTX        kubeconfig context (e.g. starhub-test)
  --timeout SEC        Per-request timeout (default: 20s)
  --json               Machine-readable JSON output (skip ASCII table)
  --strict             Exit non-zero if any check FAILs
  --no-color           Disable ANSI colour output
  --skip-slow          Skip /api/v1/diagnostics/nexus-ai (5-15s)
  --help               Show this help

Probes (per OpsTraining/index.md §2 Identifying Issues, Option 3):
  GET /health
  GET /api/v1/health/live
  GET /api/v1/health/ready
  GET /api/v1/health/metrics
  GET /api/v1/health/dependencies
  GET /api/v1/health/fdw
  GET /api/v1/diagnostics/nexus-ai/summary
  GET /api/v1/diagnostics/nexus-ai                 (slow ~5-15s)
  GET /api/v1/diagnostics/sfdc/full
  GET /api/v1/diagnostics/infrastructure/{frontend,backend,
                                          dynamodb,s3,glue-athena,bssmagic}
  GET /api/v1/db-doctor/status

Exit code:
  0  by default (success)
  1  with --strict if any check returned FAIL
EOF
            exit 0
            ;;
        *) echo "Unknown option: $1"; echo "Run with --help for usage."; exit 1 ;;
    esac
done

# Suppress colour when not on a TTY or when --no-color asked
if [ "$NO_COLOR" = "1" ] || [ ! -t 1 ]; then
    GREEN=""; RED=""; YELLOW=""; CYAN=""; BOLD=""; DIM=""; RESET=""
fi

# ── Probe target resolution ────────────────────────────────────────
# Three modes:
#   direct  -- BACKEND_URL set; just use it
#   alb     -- ALB_HOST set; build https://<host>
#   in-pod  -- (default) kubectl exec into a Running backend pod, curl localhost:8000

KCTX_ARGS=""
[ -n "$CONTEXT" ] && KCTX_ARGS="--context=$CONTEXT"

MODE="in-pod"
if [ -n "$BACKEND_URL" ]; then
    MODE="direct"
elif [ -n "$ALB_HOST" ]; then
    MODE="alb"
    BACKEND_URL="https://${ALB_HOST}"
fi

POD=""
if [ "$MODE" = "in-pod" ]; then
    if [ -z "$NAMESPACE" ]; then
        # Try a couple of common defaults; the .env.local source above may
        # also have set ENV which we can fold into nexus-ai-${ENV}.
        if [ -n "${ENV:-}" ]; then
            NAMESPACE="nexus-ai-${ENV}"
        else
            NAMESPACE="nexus-ai-prod"
        fi
    fi
    if ! command -v kubectl >/dev/null 2>&1; then
        echo "ERROR: kubectl not found. Use --backend-url or --alb-host instead." >&2
        exit 2
    fi
    # Find a Running backend pod, trying multiple label selectors
    for sel in "app.kubernetes.io/name=backend" "app=backend" "app=${NAMESPACE}-backend"; do
        POD=$(kubectl ${KCTX_ARGS} -n "$NAMESPACE" get pods -l "$sel" \
              --field-selector=status.phase=Running \
              -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
        [ -n "$POD" ] && break
    done
    # Last-resort: name-based grep
    if [ -z "$POD" ]; then
        POD=$(kubectl ${KCTX_ARGS} -n "$NAMESPACE" get pods --no-headers 2>/dev/null \
              | awk '/-backend-[a-f0-9]+-[a-z0-9]+/ && $3=="Running" {print $1; exit}')
    fi
    if [ -z "$POD" ]; then
        echo "ERROR: No Running backend pod in namespace '$NAMESPACE'." >&2
        echo "       Try --namespace, --context, or --backend-url." >&2
        exit 2
    fi
    BACKEND_URL="http://localhost:8000"   # used inside the pod
fi

# ── Endpoint table -- one row per probe ────────────────────────────
# Format: "label|path|jq detail expression"
# The jq expression is evaluated against the response body. If jq fails or
# the field is absent, the script falls back to a truncated body snippet.
ENDPOINTS=(
  "gateway/health|/health|\"status=\" + (.status // \"n/a\") + (if .workers then \" workers=\" + (.workers|tostring) else \"\" end)"
  "api/health/live|/api/v1/health/live|\"status=\" + (.status // \"n/a\")"
  "api/health/ready|/api/v1/health/ready|\"status=\" + (.status // \"n/a\") + (if .checks then \" checks=\" + ((.checks // {}) | length | tostring) else \"\" end)"
  "api/health/metrics|/api/v1/health/metrics|\"cpu=\" + ((.system.cpu_percent // 0)|tostring) + \"% mem=\" + ((.system.memory_percent // 0)|tostring) + \"%\""
  "api/health/dependencies|/api/v1/health/dependencies|\"overall=\" + (.overall_status // \"n/a\")"
  "api/health/fdw|/api/v1/health/fdw|\"status=\" + (.status // \"n/a\") + (if .latencyMs then \" latency=\" + (.latencyMs|tostring) + \"ms\" else \"\" end)"
  "diag/cp/summary|/api/v1/diagnostics/nexus-ai/summary|\"status=\" + (.status // \"n/a\")"
  "diag/cp/full|/api/v1/diagnostics/nexus-ai|((.checks // {}) as \$c | (\$c | length) as \$total | ([\$c[] | select((.status // \"\") == \"pass\")] | length) as \$pass | \"checks=\" + (\$total|tostring) + \" pass=\" + (\$pass|tostring) + \" other=\" + ((\$total - \$pass)|tostring))"
  "diag/sfdc/full|/api/v1/diagnostics/sfdc/full|\"overall=\" + (.overall_status // \"n/a\") + (if .checks then \" checks=\" + (.checks | length | tostring) else \"\" end)"
  "diag/infra/frontend|/api/v1/diagnostics/infrastructure/frontend|.status // \"ok\""
  "diag/infra/backend|/api/v1/diagnostics/infrastructure/backend|.status // \"ok\""
  "diag/infra/dynamodb|/api/v1/diagnostics/infrastructure/dynamodb|.status // \"ok\""
  "diag/infra/s3|/api/v1/diagnostics/infrastructure/s3|.status // \"ok\""
  "diag/infra/glue-athena|/api/v1/diagnostics/infrastructure/glue-athena|.status // \"ok\""
  "diag/infra/bssmagic|/api/v1/diagnostics/infrastructure/bssmagic|.status // \"ok\""
  "db-doctor/status|/api/v1/db-doctor/status|\"status=\" + (.status // \"n/a\")"
)

# ── Probe runner ───────────────────────────────────────────────────
probe() {
    # Echoes a single line: code|latency_ms|body_or_empty
    local path="$1"
    local start_ms end_ms body code

    start_ms=$(date +%s%3N)
    if [ "$MODE" = "in-pod" ]; then
        body=$(kubectl ${KCTX_ARGS} -n "$NAMESPACE" exec "$POD" -c backend -- \
               curl -sk -o /dev/null -m "$TIMEOUT" -w "%{http_code}" \
               "${BACKEND_URL}${path}" 2>/dev/null) || true
        code="$body"
        if [ "$code" -ge 200 ] 2>/dev/null && [ "$code" -lt 600 ] 2>/dev/null; then
            body=$(kubectl ${KCTX_ARGS} -n "$NAMESPACE" exec "$POD" -c backend -- \
                   curl -sk -m "$TIMEOUT" "${BACKEND_URL}${path}" 2>/dev/null) || body=""
        else
            body=""
        fi
    else
        # Single-shot: capture body and status in one pass
        local tmpfile
        tmpfile=$(mktemp 2>/dev/null || mktemp -t diag)
        code=$(curl -sk -o "$tmpfile" -m "$TIMEOUT" -w "%{http_code}" \
               "${BACKEND_URL}${path}" 2>/dev/null) || code="000"
        body=$(cat "$tmpfile" 2>/dev/null || echo "")
        rm -f "$tmpfile"
    fi
    end_ms=$(date +%s%3N)

    [ -z "$code" ] && code="000"
    echo "${code}|$((end_ms - start_ms))|${body}"
}

extract_detail() {
    local jq_expr="$1"
    local body="$2"
    if [ -z "$body" ] || ! command -v jq >/dev/null 2>&1; then
        # No body or no jq -- show truncated raw body
        printf '%s' "$body" | head -c 60 | tr -d '\n'
        return
    fi
    # Try the supplied jq expression; fall back to raw body snippet
    local detail
    detail=$(printf '%s' "$body" | jq -r "$jq_expr" 2>/dev/null || true)
    if [ -z "$detail" ] || [ "$detail" = "null" ]; then
        printf '%s' "$body" | head -c 60 | tr -d '\n'
    else
        printf '%s' "$detail"
    fi
}

evaluate_status() {
    # Returns one of: PASS / FAIL / WARN
    local code="$1"
    local body="$2"
    if [ -z "$code" ] || [ "$code" = "000" ]; then
        echo "FAIL"; return
    fi
    if [ "$code" -ge 200 ] && [ "$code" -lt 300 ]; then
        # 2xx -- inspect body for an explicit failure marker
        case "$body" in
            *'"overall_status":"FAIL"'*|*'"overall_status": "FAIL"'*|\
            *'"status":"FAIL"'*|*'"status": "FAIL"'*|\
            *'"status":"unhealthy"'*|*'"status": "unhealthy"'*)
                echo "WARN"; return ;;
        esac
        echo "PASS"; return
    fi
    if [ "$code" = "401" ] || [ "$code" = "403" ]; then
        # Admin-gated; not a failure of the endpoint itself
        echo "WARN"; return
    fi
    echo "FAIL"
}

# ── Live per-probe progress (stderr; muted in JSON mode and non-TTY) ──
progress_start() {
    [ "$JSON_MODE" = "1" ] && return
    [ ! -t 2 ] && return
    printf "  [%2d/%2d] %-26s probing... " "$1" "$2" "$3" >&2
    [ "$3" = "diag/cp/full" ] && printf "%s(slow ~5-15s)%s " "$DIM" "$RESET" >&2
}

progress_skip() {
    [ "$JSON_MODE" = "1" ] && return
    [ ! -t 2 ] && return
    printf "%sSKIP%s\n" "$DIM" "$RESET" >&2
}

progress_end() {
    [ "$JSON_MODE" = "1" ] && return
    [ ! -t 2 ] && return
    local status="$1" code="$2" latency="$3"
    local color=""
    case "$status" in
        PASS) color="$GREEN" ;;
        FAIL) color="$RED" ;;
        WARN) color="$YELLOW" ;;
    esac
    printf "%s%s%s  HTTP=%-3s  %5dms\n" "$color" "$status" "$RESET" "$code" "$latency" >&2
}

# ── Run all probes ─────────────────────────────────────────────────
PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0
ROWS=()             # rendered rows for the table
JSON_ROWS=()        # JSON entries

# Pretty banner (skipped in JSON mode)
if [ "$JSON_MODE" = "0" ]; then
    printf "\n${CYAN}${BOLD}=================================================================${RESET}\n"
    printf "${CYAN}${BOLD}  Backend Diagnostics API Probe${RESET}\n"
    printf "${CYAN}${BOLD}=================================================================${RESET}\n\n"
    printf "  ${BOLD}Mode:${RESET}        %s\n" "$MODE"
    if [ "$MODE" = "in-pod" ]; then
        printf "  ${BOLD}Namespace:${RESET}   %s\n" "$NAMESPACE"
        printf "  ${BOLD}Pod:${RESET}         %s\n" "$POD"
    else
        printf "  ${BOLD}Backend URL:${RESET} %s\n" "$BACKEND_URL"
    fi
    [ -n "$CONTEXT" ] && printf "  ${BOLD}Context:${RESET}     %s\n" "$CONTEXT"
    printf "  ${BOLD}Timeout:${RESET}     ${TIMEOUT}s\n"
    [ "$SKIP_SLOW" = "1" ] && printf "  ${DIM}(skipping /api/v1/diagnostics/nexus-ai -- --skip-slow)${RESET}\n"
    printf "\n"
fi

TOTAL_PROBES=${#ENDPOINTS[@]}
PROBE_IDX=0
for entry in "${ENDPOINTS[@]}"; do
    label="${entry%%|*}"
    rest="${entry#*|}"
    path="${rest%%|*}"
    jq_expr="${rest#*|}"

    PROBE_IDX=$((PROBE_IDX + 1))
    progress_start "$PROBE_IDX" "$TOTAL_PROBES" "$label"

    # Skip the slow full battery if the user asked
    if [ "$SKIP_SLOW" = "1" ] && [ "$label" = "diag/cp/full" ]; then
        ROWS+=("${label}|SKIP|---|---|(--skip-slow)")
        progress_skip
        continue
    fi

    result=$(probe "$path")
    code="${result%%|*}"
    rest2="${result#*|}"
    latency_ms="${rest2%%|*}"
    body="${rest2#*|}"

    status=$(evaluate_status "$code" "$body")
    detail=$(extract_detail "$jq_expr" "$body")

    progress_end "$status" "$code" "$latency_ms"

    case "$status" in
        PASS) PASS_COUNT=$((PASS_COUNT+1)) ;;
        FAIL) FAIL_COUNT=$((FAIL_COUNT+1)) ;;
        WARN) WARN_COUNT=$((WARN_COUNT+1)) ;;
    esac

    ROWS+=("${label}|${status}|${code}|${latency_ms}ms|${detail}")
    if [ "$JSON_MODE" = "1" ]; then
        # Defer JSON construction to a final pass so we can print one valid array
        # Escape the detail string (jq -Rs handles arbitrary input)
        det_esc=$(printf '%s' "$detail" | jq -Rs '.' 2>/dev/null || printf '"%s"' "$(printf '%s' "$detail" | sed 's/"/\\"/g')")
        JSON_ROWS+=("{\"endpoint\":\"GET ${path}\",\"label\":\"${label}\",\"status\":\"${status}\",\"http_code\":\"${code}\",\"latency_ms\":${latency_ms:-0},\"detail\":${det_esc}}")
    fi
done

# ── Output ─────────────────────────────────────────────────────────
if [ "$JSON_MODE" = "1" ]; then
    # Comma-join the JSON rows
    saveIFS="$IFS"; IFS=,
    rows_joined="${JSON_ROWS[*]}"
    IFS="$saveIFS"
    printf '{"summary":{"pass":%d,"fail":%d,"warn":%d,"total":%d},"results":[%s]}\n' \
        "$PASS_COUNT" "$FAIL_COUNT" "$WARN_COUNT" \
        "$((PASS_COUNT + FAIL_COUNT + WARN_COUNT))" \
        "$rows_joined"
else
    # ASCII table -- column widths chosen to fit a typical 120-column terminal
    EW=23      # Endpoint label
    SW=6       # Status
    CW=4       # HTTP code
    LW=8       # Latency
    DW=70      # Detail (truncated)

    line=$(printf '+%*s+%*s+%*s+%*s+%*s+' \
        "$((EW+2))" '' "$((SW+2))" '' "$((CW+2))" '' "$((LW+2))" '' "$((DW+2))" '' | tr ' ' '-')
    # Insert a blank line on stderr before the table when progress was printed,
    # so the table on stdout doesn't visually butt up against the last probe line.
    [ -t 2 ] && [ "$JSON_MODE" = "0" ] && printf '\n' >&2
    printf '%s\n' "$line"
    printf "| ${BOLD}%-*s${RESET} | ${BOLD}%-*s${RESET} | ${BOLD}%-*s${RESET} | ${BOLD}%-*s${RESET} | ${BOLD}%-*s${RESET} |\n" \
        "$EW" "Endpoint" "$SW" "Status" "$CW" "HTTP" "$LW" "Latency" "$DW" "Detail"
    printf '%s\n' "$line"

    for row in "${ROWS[@]}"; do
        IFS='|' read -r label status code latency detail <<< "$row"
        case "$status" in
            PASS) col_status="${GREEN}${status} ${RESET}" ;;
            FAIL) col_status="${RED}${status} ${RESET}" ;;
            WARN) col_status="${YELLOW}${status} ${RESET}" ;;
            SKIP) col_status="${DIM}${status} ${RESET}" ;;
            *)    col_status="${status} " ;;
        esac
        # Truncate detail to fit
        if [ "${#detail}" -gt "$DW" ]; then
            detail="${detail:0:$((DW-3))}..."
        fi
        printf "| %-*s | %s%-$((SW-5))s | %*s | %*s | %-*s |\n" \
            "$EW" "$label" \
            "$col_status" "" \
            "$CW" "$code" \
            "$LW" "$latency" \
            "$DW" "$detail"
    done
    printf '%s\n' "$line"

    # Summary
    printf "\n  ${BOLD}Summary:${RESET}  "
    [ "$PASS_COUNT" -gt 0 ] && printf "${GREEN}%d PASS${RESET}  " "$PASS_COUNT"
    [ "$WARN_COUNT" -gt 0 ] && printf "${YELLOW}%d WARN${RESET}  " "$WARN_COUNT"
    [ "$FAIL_COUNT" -gt 0 ] && printf "${RED}%d FAIL${RESET}  " "$FAIL_COUNT"
    total=$((PASS_COUNT + FAIL_COUNT + WARN_COUNT))
    printf "(${total} probes total)\n\n"
fi

# Exit code
if [ "$STRICT_MODE" = "1" ] && [ "$FAIL_COUNT" -gt 0 ]; then
    exit 1
fi
exit 0

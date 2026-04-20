#!/bin/sh
# Log Monitoring and Analysis Script
#
# Fetches and analyzes logs from frontend (nginx files), backend (loguru stdout),
# and BSS Magic (interleaved stdout) pods. Produces a categorized health report
# with error counts, patterns, and actionable findings.
#
# Runs from a workstation or CI host with kubectl access.
#
# Usage:
#   sh logcheck.sh                           # Analyze all, last 1h
#   sh logcheck.sh backend                   # Backend logs only
#   sh logcheck.sh --since 5m all            # Last 5 minutes
#   sh logcheck.sh --save /tmp/logs all      # Save raw logs + report
#   sh logcheck.sh --errors-only all         # Only error lines
#   sh logcheck.sh --watch all               # Re-run every 60s
#   sh logcheck.sh --env stage all           # Target stage environment

set -e

# ── Colors ─────────────────────────────────────────────────────────
GREEN="\033[32m"
RED="\033[31m"
YELLOW="\033[33m"
CYAN="\033[36m"
BOLD="\033[1m"
DIM="\033[2m"
RESET="\033[0m"

# ── Defaults ───────────────────────────────────────────────────────
CAPABILITY="nexus-ai"
ENV="dev"
NAMESPACE=""
SINCE="1h"
TAIL="5000"
LEVEL="warn"
SAVE_DIR=""
JSON_MODE=0
WATCH_MODE=0
ERRORS_ONLY=0
COMPONENTS=""

# ── Load .env.local (overrides defaults; CLI args override these) ─
_script_dir="$(cd "$(dirname "$0")" && pwd)"
_env_local="${_script_dir}/.env.local"
[ -f "$_env_local" ] && . "$_env_local"
unset _script_dir _env_local

# ── Argument parsing ──────────────────────────────────────────────
while [ $# -gt 0 ]; do
    case "$1" in
        --capability)  CAPABILITY="$2"; shift 2 ;;
        --env)         ENV="$2"; shift 2 ;;
        --namespace|-n) NAMESPACE="$2"; shift 2 ;;
        --since)       SINCE="$2"; shift 2 ;;
        --tail)        TAIL="$2"; shift 2 ;;
        --level)       LEVEL="$2"; shift 2 ;;
        --save)        SAVE_DIR="$2"; shift 2 ;;
        --json|-j)     JSON_MODE=1; shift ;;
        --watch|-w)    WATCH_MODE=1; shift ;;
        --errors-only) ERRORS_ONLY=1; shift ;;
        --help|-h)
            cat <<'EOF'
Log Monitoring and Analysis

Usage: sh logcheck.sh [OPTIONS] [COMPONENT...]

Components: frontend, backend, bssmagic, all (default: all)

Options:
  --capability NAME   Capability name (default: nexus-ai)
  --env ENV           Environment (default: dev)
  --namespace NS      Override namespace (default: {capability}-{env})
  --since DURATION    Log time window (default: 1h)
  --tail LINES        Max lines per source (default: 5000)
  --level LEVEL       error, warn, or all (default: warn)
  --save DIR          Save raw logs + report to directory
  --json              Output report as JSON
  --watch             Continuous mode: re-run every 60s
  --errors-only       Only show error/fatal lines
  --help              Show this help
EOF
            exit 0
            ;;
        frontend|backend|bssmagic|all)
            COMPONENTS="${COMPONENTS} $1"; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

[ -z "$NAMESPACE" ] && NAMESPACE="${CAPABILITY}-${ENV}"
[ -z "$COMPONENTS" ] && COMPONENTS="all"
case "$COMPONENTS" in *all*) COMPONENTS="backend frontend bssmagic" ;; esac

# ── Temp dir for working files ────────────────────────────────────
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# ── Utility ────────────────────────────────────────────────────────
log_section() { printf "\n${BOLD}${CYAN}== %s ==${RESET}\n" "$1"; }
log_sub()     { printf "  ${BOLD}%s${RESET}\n" "$1"; }
log_ok()      { printf "  ${GREEN}✓${RESET} %s\n" "$1"; }
log_warn()    { printf "  ${YELLOW}⚠${RESET} %s\n" "$1"; }
log_fail()    { printf "  ${RED}✗${RESET} %s\n" "$1"; }
log_dim()     { printf "  ${DIM}%s${RESET}\n" "$1"; }
log_line()    { printf "    %s\n" "$1"; }

resource_name() { echo "${CAPABILITY}-${ENV}-${1}"; }

count_lines() { wc -l < "$1" | tr -d ' '; }

count_grep() {
    grep -c "$1" "$2" 2>/dev/null || echo "0"
}

grep_lines() {
    grep "$1" "$2" 2>/dev/null || true
}

top_patterns() {
    file="$1"; pattern="$2"; limit="${3:-5}"
    grep_lines "$pattern" "$file" | sort | uniq -c | sort -rn | head -n "$limit"
}

get_pod() {
    component="$1"
    name=$(resource_name "$component")
    kubectl get pods -l "app=${name}" -n "$NAMESPACE" \
        --field-selector=status.phase=Running \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null
}

# ── Pod metadata ──────────────────────────────────────────────────
collect_pod_meta() {
    component="$1"
    name=$(resource_name "$component")
    pod=$(get_pod "$component")
    meta_file="${TMPDIR}/${component}-meta.txt"

    if [ -z "$pod" ]; then
        echo "pod=; status=NotFound; restarts=0; ready=false; age=; reason=" > "$meta_file"
        return
    fi

    status=$(kubectl get pod "$pod" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
    restarts=$(kubectl get pod "$pod" -n "$NAMESPACE" -o jsonpath='{.status.containerStatuses[0].restartCount}' 2>/dev/null || echo "0")
    ready=$(kubectl get pod "$pod" -n "$NAMESPACE" -o jsonpath='{.status.containerStatuses[0].ready}' 2>/dev/null || echo "false")
    age=$(kubectl get pod "$pod" -n "$NAMESPACE" -o jsonpath='{.metadata.creationTimestamp}' 2>/dev/null || echo "")
    reason=$(kubectl get pod "$pod" -n "$NAMESPACE" -o jsonpath='{.status.containerStatuses[0].lastState.terminated.reason}' 2>/dev/null || echo "")

    echo "pod=${pod}; status=${status}; restarts=${restarts}; ready=${ready}; age=${age}; reason=${reason}" > "$meta_file"

    kubectl get events -n "$NAMESPACE" --field-selector "involvedObject.name=${pod},type=Warning" \
        --sort-by='.lastTimestamp' 2>/dev/null | tail -5 > "${TMPDIR}/${component}-events.txt" 2>/dev/null || true
}

print_pod_meta() {
    component="$1"
    meta_file="${TMPDIR}/${component}-meta.txt"
    [ ! -f "$meta_file" ] && return

    eval "$(cat "$meta_file")"
    if [ -z "$pod" ]; then
        log_fail "No running pod found"
        return
    fi
    printf "  Pod: ${BOLD}%s${RESET}  Status: %s  Ready: %s  Restarts: %s\n" "$pod" "$status" "$ready" "$restarts"
    [ -n "$reason" ] && printf "  ${YELLOW}Last termination reason: %s${RESET}\n" "$reason"

    events_file="${TMPDIR}/${component}-events.txt"
    if [ -f "$events_file" ] && [ -s "$events_file" ]; then
        evt_count=$(count_lines "$events_file")
        if [ "$evt_count" -gt 1 ]; then
            printf "  ${YELLOW}Warning events (%s):${RESET}\n" "$((evt_count - 1))"
            tail -n +2 "$events_file" | while IFS= read -r line; do
                log_line "$line"
            done
        fi
    fi
}

# ── Log collection ────────────────────────────────────────────────
fetch_backend_logs() {
    name=$(resource_name "backend")
    kubectl logs "deployment/${name}" -n "$NAMESPACE" \
        --since="$SINCE" --tail="$TAIL" 2>/dev/null > "${TMPDIR}/backend-raw.log" || true
}

fetch_frontend_logs() {
    pod=$(get_pod "frontend")
    [ -z "$pod" ] && return
    kubectl exec "$pod" -n "$NAMESPACE" -- cat /var/log/nginx/access.log 2>/dev/null \
        > "${TMPDIR}/frontend-access.log" || true
    kubectl exec "$pod" -n "$NAMESPACE" -- cat /var/log/nginx/error.log 2>/dev/null \
        > "${TMPDIR}/frontend-error.log" || true
}

fetch_bssmagic_logs() {
    name=$(resource_name "bssmagic")
    kubectl logs "statefulset/${name}" -n "$NAMESPACE" \
        --since="$SINCE" --tail="$TAIL" 2>/dev/null > "${TMPDIR}/bssmagic-raw.log" || true
}

# ── Backend analysis ──────────────────────────────────────────────
BE_ERRORS=0; BE_WARNINGS=0; BE_5XX=0; BE_STARTUP=0; BE_WORKER=0

analyze_backend() {
    log_file="${TMPDIR}/backend-raw.log"
    [ ! -f "$log_file" ] && log_fail "No backend logs collected" && return
    total=$(count_lines "$log_file")

    log_section "Backend Log Analysis (last ${SINCE}, ${total} lines)"
    print_pod_meta "backend"
    echo ""

    BE_ERRORS=$(count_grep '| ERROR \|| CRITICAL ' "$log_file")
    BE_WARNINGS=$(count_grep '| WARNING |' "$log_file")

    # Errors
    if [ "$BE_ERRORS" -gt 0 ]; then
        log_sub "Errors (${BE_ERRORS}):"
        top_patterns "$log_file" '| ERROR \|| CRITICAL ' 8 | while IFS= read -r line; do
            log_line "$line"
        done
    else
        [ "$ERRORS_ONLY" = "0" ] && log_ok "Errors: none"
    fi

    # Warnings
    if [ "$ERRORS_ONLY" = "0" ] && [ "$LEVEL" != "error" ]; then
        if [ "$BE_WARNINGS" -gt 0 ]; then
            log_sub "Warnings (${BE_WARNINGS}):"
            top_patterns "$log_file" '| WARNING |' 5 | while IFS= read -r line; do
                log_line "$line"
            done
        else
            log_ok "Warnings: none"
        fi
    fi

    # HTTP 5xx (uvicorn access log pattern: status code after the quoted request line)
    grep_lines '" [5][0-9][0-9] ' "$log_file" > "${TMPDIR}/backend-5xx.log" 2>/dev/null || true
    BE_5XX=$(count_lines "${TMPDIR}/backend-5xx.log")
    if [ "$BE_5XX" -gt 0 ]; then
        log_sub "HTTP 5xx (${BE_5XX}):"
        top_patterns "${TMPDIR}/backend-5xx.log" '.' 5 | while IFS= read -r line; do
            log_line "$line"
        done
    elif [ "$ERRORS_ONLY" = "0" ]; then
        log_ok "HTTP 5xx: none"
    fi

    # Startup issues
    grep_lines 'not mounted:\|not available:\|Failed to\|API_KEY not set' "$log_file" \
        > "${TMPDIR}/backend-startup.log" 2>/dev/null || true
    BE_STARTUP=$(count_lines "${TMPDIR}/backend-startup.log")
    if [ "$BE_STARTUP" -gt 0 ]; then
        log_sub "Startup Issues (${BE_STARTUP}):"
        top_patterns "${TMPDIR}/backend-startup.log" '.' 5 | while IFS= read -r line; do
            log_line "$line"
        done
    elif [ "$ERRORS_ONLY" = "0" ]; then
        log_ok "Startup Issues: none"
    fi

    # Worker issues
    grep_lines 'Found dead\|Kill after timeout\|Invalid JSON from MCP' "$log_file" \
        > "${TMPDIR}/backend-worker.log" 2>/dev/null || true
    BE_WORKER=$(count_lines "${TMPDIR}/backend-worker.log")
    if [ "$BE_WORKER" -gt 0 ]; then
        log_sub "Worker Issues (${BE_WORKER}):"
        top_patterns "${TMPDIR}/backend-worker.log" '.' 5 | while IFS= read -r line; do
            log_line "$line"
        done
    elif [ "$ERRORS_ONLY" = "0" ]; then
        log_ok "Worker Issues: none"
    fi

    # Auth / AWS issues
    grep_lines 'AssumeRoleWithWebIdentity\|NoCredentialsError\|credentials.*error\|credentials.*fail' "$log_file" \
        > "${TMPDIR}/backend-auth.log" 2>/dev/null || true
    auth_count=$(count_lines "${TMPDIR}/backend-auth.log")
    if [ "$auth_count" -gt 0 ]; then
        log_sub "Auth/AWS Issues (${auth_count}):"
        top_patterns "${TMPDIR}/backend-auth.log" '.' 3 | while IFS= read -r line; do
            log_line "$line"
        done
    elif [ "$ERRORS_ONLY" = "0" ]; then
        log_ok "Auth/AWS Issues: none"
    fi
}

# ── Frontend analysis ─────────────────────────────────────────────
FE_5XX=0; FE_PROXY=0; FE_ERR_LINES=0

analyze_frontend() {
    access_file="${TMPDIR}/frontend-access.log"
    error_file="${TMPDIR}/frontend-error.log"

    access_total=0; error_total=0
    [ -f "$access_file" ] && access_total=$(count_lines "$access_file")
    [ -f "$error_file" ] && error_total=$(count_lines "$error_file")

    log_section "Frontend Log Analysis (access: ${access_total} lines, error: ${error_total} lines)"
    print_pod_meta "frontend"
    echo ""

    if [ "$access_total" = "0" ] && [ "$error_total" = "0" ]; then
        log_warn "No frontend logs collected (pod may not exist or logs empty)"
        return
    fi

    # HTTP status distribution from access log
    if [ "$access_total" -gt 0 ] && [ "$ERRORS_ONLY" = "0" ]; then
        count_2xx=$(grep -c '" 2[0-9][0-9] ' "$access_file" 2>/dev/null || echo "0")
        count_3xx=$(grep -c '" 3[0-9][0-9] ' "$access_file" 2>/dev/null || echo "0")
        count_4xx=$(grep -c '" 4[0-9][0-9] ' "$access_file" 2>/dev/null || echo "0")
        count_5xx=$(grep -c '" 5[0-9][0-9] ' "$access_file" 2>/dev/null || echo "0")
        FE_5XX=$count_5xx
        log_sub "HTTP Status Distribution:"
        printf "    2xx: ${GREEN}%s${RESET}  3xx: %s  4xx: ${YELLOW}%s${RESET}  5xx: ${RED}%s${RESET}\n" \
            "$count_2xx" "$count_3xx" "$count_4xx" "$count_5xx"
    elif [ "$access_total" -gt 0 ]; then
        FE_5XX=$(grep -c '" 5[0-9][0-9] ' "$access_file" 2>/dev/null || echo "0")
    fi

    # 5xx detail
    if [ "$FE_5XX" -gt 0 ]; then
        log_sub "5xx Lines (${FE_5XX}):"
        grep_lines '" 5[0-9][0-9] ' "$access_file" | tail -10 | while IFS= read -r line; do
            log_line "$line"
        done
    elif [ "$ERRORS_ONLY" = "0" ]; then
        log_ok "5xx: none"
    fi

    # Error log analysis
    if [ "$error_total" -gt 0 ]; then
        grep_lines '\[error\]\|\[crit\]\|\[alert\]\|\[emerg\]' "$error_file" \
            > "${TMPDIR}/frontend-critical.log" 2>/dev/null || true
        FE_ERR_LINES=$(count_lines "${TMPDIR}/frontend-critical.log")
        if [ "$FE_ERR_LINES" -gt 0 ]; then
            log_sub "Error Log (${FE_ERR_LINES}):"
            tail -10 "${TMPDIR}/frontend-critical.log" | while IFS= read -r line; do
                log_line "$line"
            done
        elif [ "$ERRORS_ONLY" = "0" ]; then
            log_ok "Error log: clean"
        fi

        # Proxy issues
        grep_lines 'upstream timed out\|connect() failed\|no live upstreams' "$error_file" \
            > "${TMPDIR}/frontend-proxy.log" 2>/dev/null || true
        FE_PROXY=$(count_lines "${TMPDIR}/frontend-proxy.log")
        if [ "$FE_PROXY" -gt 0 ]; then
            log_sub "Proxy Issues (${FE_PROXY}):"
            top_patterns "${TMPDIR}/frontend-proxy.log" '.' 5 | while IFS= read -r line; do
                log_line "$line"
            done
        elif [ "$ERRORS_ONLY" = "0" ]; then
            log_ok "Proxy Issues: none"
        fi
    elif [ "$ERRORS_ONLY" = "0" ]; then
        log_ok "Error log: empty"
    fi
}

# ── BSS Magic analysis ───────────────────────────────────────────
BSS_PG_ERRORS=0; BSS_TMF_ERRORS=0; BSS_INIT=0

analyze_bssmagic() {
    log_file="${TMPDIR}/bssmagic-raw.log"
    [ ! -f "$log_file" ] && log_fail "No BSS Magic logs collected" && return
    total=$(count_lines "$log_file")

    log_section "BSS Magic Log Analysis (last ${SINCE}, ${total} lines)"
    print_pod_meta "bssmagic"
    echo ""

    if [ "$total" = "0" ]; then
        log_warn "No BSS Magic logs (pod may not exist)"
        return
    fi

    # PostgreSQL errors
    grep_lines 'FATAL:\|PANIC:\|ERROR:.*postgres\|could not\|connection refused' "$log_file" \
        > "${TMPDIR}/bss-pg-errors.log" 2>/dev/null || true
    BSS_PG_ERRORS=$(count_lines "${TMPDIR}/bss-pg-errors.log")
    if [ "$BSS_PG_ERRORS" -gt 0 ]; then
        log_sub "PostgreSQL Errors (${BSS_PG_ERRORS}):"
        top_patterns "${TMPDIR}/bss-pg-errors.log" '.' 5 | while IFS= read -r line; do
            log_line "$line"
        done
    elif [ "$ERRORS_ONLY" = "0" ]; then
        log_ok "PostgreSQL Errors: none"
    fi

    # TMF API errors
    grep_lines '\[TMF-REST\].*\(5[0-9][0-9]\)\|\[TMF-REST\].*error\|\[TMF-REST\].*failed\|\[TMF-REST\].*exception' "$log_file" \
        > "${TMPDIR}/bss-tmf-errors.log" 2>/dev/null || true
    BSS_TMF_ERRORS=$(count_lines "${TMPDIR}/bss-tmf-errors.log")
    if [ "$BSS_TMF_ERRORS" -gt 0 ]; then
        log_sub "TMF API Errors (${BSS_TMF_ERRORS}):"
        top_patterns "${TMPDIR}/bss-tmf-errors.log" '.' 5 | while IFS= read -r line; do
            log_line "$line"
        done
    elif [ "$ERRORS_ONLY" = "0" ]; then
        log_ok "TMF API Errors: none"
    fi

    # Init / restart issues
    grep_lines 'exited with code\|restarting in\|\[tmf-rest-api\].*failed\|restore.*failed\|mapping.*failed' "$log_file" \
        > "${TMPDIR}/bss-init.log" 2>/dev/null || true
    BSS_INIT=$(count_lines "${TMPDIR}/bss-init.log")
    if [ "$BSS_INIT" -gt 0 ]; then
        log_sub "Init/Restart Issues (${BSS_INIT}):"
        top_patterns "${TMPDIR}/bss-init.log" '.' 5 | while IFS= read -r line; do
            log_line "$line"
        done
    elif [ "$ERRORS_ONLY" = "0" ]; then
        log_ok "Init Issues: none"
    fi

    # FDW / Axway issues
    grep_lines 'multicorn\|foreign table.*error\|axway.*error\|axway.*503\|axway.*401' "$log_file" \
        > "${TMPDIR}/bss-fdw.log" 2>/dev/null || true
    fdw_count=$(count_lines "${TMPDIR}/bss-fdw.log")
    if [ "$fdw_count" -gt 0 ]; then
        log_sub "FDW/Axway Issues (${fdw_count}):"
        top_patterns "${TMPDIR}/bss-fdw.log" '.' 3 | while IFS= read -r line; do
            log_line "$line"
        done
    elif [ "$ERRORS_ONLY" = "0" ]; then
        log_ok "FDW/Axway Issues: none"
    fi
}

# ── Summary ───────────────────────────────────────────────────────
print_summary() {
    log_section "Summary"
    total_issues=0

    for comp in $COMPONENTS; do
        case "$comp" in
            backend)
                printf "  Backend:   ${RED}%s errors${RESET}, ${YELLOW}%s warnings${RESET}, %s 5xx, %s startup, %s worker\n" \
                    "$BE_ERRORS" "$BE_WARNINGS" "$BE_5XX" "$BE_STARTUP" "$BE_WORKER"
                total_issues=$((total_issues + BE_ERRORS + BE_5XX))
                ;;
            frontend)
                printf "  Frontend:  ${RED}%s 5xx${RESET}, ${YELLOW}%s proxy issues${RESET}, %s error lines\n" \
                    "$FE_5XX" "$FE_PROXY" "$FE_ERR_LINES"
                total_issues=$((total_issues + FE_5XX + FE_PROXY))
                ;;
            bssmagic)
                printf "  BSS Magic: ${RED}%s PG errors${RESET}, ${RED}%s TMF errors${RESET}, %s init issues\n" \
                    "$BSS_PG_ERRORS" "$BSS_TMF_ERRORS" "$BSS_INIT"
                total_issues=$((total_issues + BSS_PG_ERRORS + BSS_TMF_ERRORS))
                ;;
        esac
    done

    echo ""
    if [ "$total_issues" = "0" ]; then
        printf "  Overall:   ${GREEN}${BOLD}CLEAN${RESET} (no errors found)\n"
    else
        printf "  Overall:   ${RED}${BOLD}NEEDS ATTENTION${RESET} (%s issue(s) found)\n" "$total_issues"
    fi
}

# ── Save mode ─────────────────────────────────────────────────────
save_artifacts() {
    [ -z "$SAVE_DIR" ] && return
    mkdir -p "$SAVE_DIR"

    for comp in $COMPONENTS; do
        case "$comp" in
            backend)
                [ -f "${TMPDIR}/backend-raw.log" ] && cp "${TMPDIR}/backend-raw.log" "${SAVE_DIR}/backend-raw.log"
                ;;
            frontend)
                [ -f "${TMPDIR}/frontend-access.log" ] && cp "${TMPDIR}/frontend-access.log" "${SAVE_DIR}/frontend-access.log"
                [ -f "${TMPDIR}/frontend-error.log" ] && cp "${TMPDIR}/frontend-error.log" "${SAVE_DIR}/frontend-error.log"
                ;;
            bssmagic)
                [ -f "${TMPDIR}/bssmagic-raw.log" ] && cp "${TMPDIR}/bssmagic-raw.log" "${SAVE_DIR}/bssmagic-raw.log"
                ;;
        esac
    done
    printf "\n  ${DIM}Raw logs saved to: %s${RESET}\n" "$SAVE_DIR"
}

# ── JSON report ───────────────────────────────────────────────────
print_json_report() {
    [ "$JSON_MODE" = "0" ] && return

    cat <<ENDJSON
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "namespace": "${NAMESPACE}",
  "since": "${SINCE}",
  "backend": {
    "errors": ${BE_ERRORS},
    "warnings": ${BE_WARNINGS},
    "http_5xx": ${BE_5XX},
    "startup_issues": ${BE_STARTUP},
    "worker_issues": ${BE_WORKER}
  },
  "frontend": {
    "http_5xx": ${FE_5XX},
    "proxy_issues": ${FE_PROXY},
    "error_log_lines": ${FE_ERR_LINES}
  },
  "bssmagic": {
    "pg_errors": ${BSS_PG_ERRORS},
    "tmf_errors": ${BSS_TMF_ERRORS},
    "init_issues": ${BSS_INIT}
  },
  "total_issues": $((BE_ERRORS + BE_5XX + FE_5XX + FE_PROXY + BSS_PG_ERRORS + BSS_TMF_ERRORS))
}
ENDJSON
}

# ── Main run ──────────────────────────────────────────────────────
run_once() {
    printf "\n${BOLD}Log Analysis${RESET}  Namespace: ${BOLD}${NAMESPACE}${RESET}  Since: ${BOLD}${SINCE}${RESET}  $(date)\n"

    # Collect metadata
    for comp in $COMPONENTS; do
        collect_pod_meta "$comp"
    done

    # Fetch logs
    for comp in $COMPONENTS; do
        case "$comp" in
            backend)  fetch_backend_logs ;;
            frontend) fetch_frontend_logs ;;
            bssmagic) fetch_bssmagic_logs ;;
        esac
    done

    # Analyze
    for comp in $COMPONENTS; do
        case "$comp" in
            backend)  analyze_backend ;;
            frontend) analyze_frontend ;;
            bssmagic) analyze_bssmagic ;;
        esac
    done

    print_summary
    save_artifacts
    print_json_report
    echo ""
}

# ── Entry point ───────────────────────────────────────────────────
if [ "$WATCH_MODE" = "1" ]; then
    SINCE="2m"
    while true; do
        clear
        run_once
        printf "${DIM}Next refresh in 60s... (Ctrl+C to stop)${RESET}\n"
        sleep 60
    done
else
    run_once
fi

# Exit with error if issues found
total=$((BE_ERRORS + BE_5XX + FE_5XX + FE_PROXY + BSS_PG_ERRORS + BSS_TMF_ERRORS))
[ "$total" -gt 0 ] && exit 1
exit 0

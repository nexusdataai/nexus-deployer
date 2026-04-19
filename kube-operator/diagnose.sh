#!/bin/sh
# Infrastructure Diagnostics - Portable Shell Script
#
# Works inside any pod: frontend (nginx/alpine), backend (python/debian), BSS Magic.
# Auto-detects pod type and runs local checks + backend API checks.
#
# Usage:
#   # Auto-detect pod and run all checks
#   sh diagnose.sh
#
#   # Run only a specific category via the backend API
#   sh diagnose.sh --category backend
#   sh diagnose.sh --category dynamodb
#   sh diagnose.sh --category s3
#   sh diagnose.sh --category bssmagic
#
#   # Specify backend URL explicitly
#   sh diagnose.sh --backend-url http://call-processing-dev-backend-svc:8000
#
#   # Run local pod checks only (no backend API call)
#   sh diagnose.sh --local-only
#
#   # JSON output (from backend API)
#   sh diagnose.sh --json

set -e

GREEN="\033[32m"
RED="\033[31m"
YELLOW="\033[33m"
DIM="\033[2m"
BOLD="\033[1m"
RESET="\033[0m"

BACKEND_URL=""
CATEGORY=""
LOCAL_ONLY=0
JSON_MODE=0
PASS_COUNT=0
FAIL_COUNT=0

# ── Load .env.local (overrides defaults; CLI args override these) ─
_script_dir="$(cd "$(dirname "$0")" && pwd)"
_env_local="${_script_dir}/.env.local"
[ -f "$_env_local" ] && . "$_env_local"
unset _script_dir _env_local

while [ $# -gt 0 ]; do
    case "$1" in
        --backend-url) BACKEND_URL="$2"; shift 2 ;;
        --category|-c) CATEGORY="$2"; shift 2 ;;
        --local-only|-l) LOCAL_ONLY=1; shift ;;
        --json|-j) JSON_MODE=1; shift ;;
        --help|-h)
            echo "Usage: sh diagnose.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --backend-url URL   Backend gateway URL"
            echo "  --category CAT      frontend|backend|dynamodb|s3|glue-athena|bssmagic"
            echo "  --local-only        Only run local pod checks (no backend API)"
            echo "  --json              Output backend API response as JSON"
            echo "  --help              Show this help"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ── HTTP client abstraction ────────────────────────────────────────
http_get() {
    url="$1"
    if command -v curl >/dev/null 2>&1; then
        curl -sf --max-time 10 "$url" 2>/dev/null
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- --timeout=10 "$url" 2>/dev/null
    else
        return 1
    fi
}

http_status() {
    url="$1"
    if command -v curl >/dev/null 2>&1; then
        curl -so /dev/null -w "%{http_code}" --max-time 5 "$url" 2>/dev/null || echo "000"
    elif command -v wget >/dev/null 2>&1; then
        wget --spider -qS --timeout=5 "$url" 2>&1 | grep "HTTP/" | tail -1 | awk '{print $2}' || echo "000"
    else
        echo "000"
    fi
}

pass() {
    PASS_COUNT=$((PASS_COUNT + 1))
    printf "  ${GREEN}✓${RESET} %-35s %s\n" "$1" "$2"
}

fail() {
    FAIL_COUNT=$((FAIL_COUNT + 1))
    printf "  ${RED}✗${RESET} %-35s %s\n" "$1" "$2"
}

warn() {
    printf "  ${YELLOW}⚠${RESET} %-35s %s\n" "$1" "$2"
}

skip() {
    printf "  ${DIM}⏭ %-35s %s${RESET}\n" "$1" "$2"
}

# ── Pod type detection ─────────────────────────────────────────────
detect_pod() {
    if [ -f /usr/share/nginx/html/index.html ] || pgrep -x nginx >/dev/null 2>&1; then
        echo "frontend"
    elif [ -f /app/mcp_http_gateway.py ]; then
        echo "backend"
    elif [ -d /var/lib/postgresql ] || pgrep -x postgres >/dev/null 2>&1; then
        echo "bssmagic"
    else
        echo "unknown"
    fi
}

# ── Resolve backend URL ───────────────────────────────────────────
resolve_backend_url() {
    if [ -n "$BACKEND_URL" ]; then
        echo "$BACKEND_URL"
        return
    fi
    pod_type="$1"
    cap="${CAPABILITY_NAME:-call-processing}"
    env="${ENVIRONMENT:-dev}"
    case "$pod_type" in
        backend) echo "http://localhost:8000" ;;
        *)       echo "http://${cap}-${env}-backend-svc:8000" ;;
    esac
}

# ── Local checks per pod type ─────────────────────────────────────

check_frontend_local() {
    printf "\n${BOLD}── Frontend Local Checks ──${RESET}\n"

    # Nginx running
    if pgrep -x nginx >/dev/null 2>&1; then
        pass "nginx process" "running"
    else
        fail "nginx process" "not running"
    fi

    # Static HTML served
    code=$(http_status "http://localhost:8080/")
    if [ "$code" = "200" ]; then
        pass "static assets (port 8080)" "HTTP $code"
    else
        fail "static assets (port 8080)" "HTTP $code"
    fi

    # config.json
    cfg=$(http_get "http://localhost:8080/config.json" 2>/dev/null || true)
    if echo "$cfg" | grep -q "apiUrl\|baseUrl\|{" 2>/dev/null; then
        pass "config.json" "valid JSON"
    else
        fail "config.json" "missing or invalid"
    fi

    # Backend proxy
    code=$(http_status "http://localhost:8080/api/health")
    if [ "$code" = "200" ]; then
        pass "nginx -> backend proxy" "HTTP $code"
    else
        fail "nginx -> backend proxy" "HTTP $code (backend unreachable?)"
    fi
}

check_backend_local() {
    printf "\n${BOLD}── Backend Local Checks ──${RESET}\n"

    # Health endpoint
    code=$(http_status "http://localhost:8000/health")
    if [ "$code" = "200" ]; then
        pass "health endpoint" "HTTP $code"
    else
        fail "health endpoint" "HTTP $code"
    fi

    # Ready endpoint
    code=$(http_status "http://localhost:8000/ready")
    if [ "$code" = "200" ]; then
        pass "readiness endpoint" "HTTP $code"
    else
        warn "readiness endpoint" "HTTP $code"
    fi

    # Python process
    if pgrep -f "mcp_http_gateway" >/dev/null 2>&1; then
        pass "gateway process" "running"
    else
        fail "gateway process" "not running"
    fi

    # AWS identity (if aws cli available)
    if command -v python3 >/dev/null 2>&1; then
        arn=$(python3 -c "
import boto3, os, sys
try:
    from src.utils.aws_client_utils import vpc_boto3_client
    sts = vpc_boto3_client('sts', region_name=os.getenv('AWS_REGION','us-east-1'))
    print(sts.get_caller_identity()['Arn'])
except Exception as e:
    print(f'ERROR:{e}', file=sys.stderr)
" 2>/dev/null || true)
        if [ -n "$arn" ] && echo "$arn" | grep -qv "ERROR"; then
            pass "IAM identity" "$arn"
        else
            warn "IAM identity" "could not determine"
        fi
    else
        skip "IAM identity" "python3 not available"
    fi
}

check_bssmagic_local() {
    printf "\n${BOLD}── BSS Magic Local Checks ──${RESET}\n"

    # PostgreSQL
    if command -v psql >/dev/null 2>&1; then
        result=$(psql -U postgres -d bssmagic -tc "SELECT 1" 2>/dev/null || true)
        if echo "$result" | grep -q "1"; then
            pass "PostgreSQL (local)" "SELECT 1 OK"
        else
            fail "PostgreSQL (local)" "query failed"
        fi

        # Database size
        size=$(psql -U postgres -d bssmagic -tc "SELECT pg_size_pretty(pg_database_size('bssmagic'))" 2>/dev/null || true)
        if [ -n "$size" ]; then
            pass "PVC volume" "DB size: $(echo "$size" | xargs)"
        fi

        # Foreign tables
        ft_count=$(psql -U postgres -d bssmagic -tc "SELECT count(*) FROM information_schema.foreign_tables" 2>/dev/null || true)
        ft_count=$(echo "$ft_count" | xargs)
        if [ -n "$ft_count" ] && [ "$ft_count" -gt 0 ] 2>/dev/null; then
            pass "foreign tables" "$ft_count found"
        else
            warn "foreign tables" "${ft_count:-0} found"
        fi
    elif pgrep -x postgres >/dev/null 2>&1; then
        pass "PostgreSQL process" "running (psql not in PATH)"
    else
        fail "PostgreSQL" "not running"
    fi

    # TMF API (port 8000)
    code=$(http_status "http://localhost:8000/")
    if [ "$code" = "200" ]; then
        pass "TMF API (port 8000)" "HTTP $code"
    else
        fail "TMF API (port 8000)" "HTTP $code"
    fi

    # Controller health (port 3000)
    code=$(http_status "http://localhost:3000/")
    if [ "$code" = "200" ]; then
        pass "controller (port 3000)" "HTTP $code"
    else
        skip "controller (port 3000)" "HTTP $code (may not be exposed)"
    fi

    # Data directory
    pgdata="${PGDATA:-/var/lib/postgresql/data/pgdata}"
    if [ -d "$pgdata" ]; then
        pass "PGDATA directory" "$pgdata exists"
    else
        fail "PGDATA directory" "$pgdata missing"
    fi
}

# ── Backend API diagnostics ────────────────────────────────────────

run_api_diagnostics() {
    be_url="$1"
    path="/api/v1/diagnostics/infrastructure"
    if [ -n "$CATEGORY" ]; then
        path="${path}/${CATEGORY}"
    fi
    url="${be_url}${path}"

    printf "\n${BOLD}── Backend API: ${url} ──${RESET}\n"

    body=$(http_get "$url" || true)
    if [ -z "$body" ]; then
        fail "API call" "no response from $url"
        return 1
    fi

    if [ "$JSON_MODE" = "1" ]; then
        echo "$body"
        return 0
    fi

    # Parse with python if available, otherwise dump raw
    if command -v python3 >/dev/null 2>&1; then
        echo "$body" | python3 -c "
import sys, json
data = json.load(sys.stdin)
status = data.get('status','unknown')
colors = {'healthy':'\033[32m','degraded':'\033[33m','unhealthy':'\033[31m'}
print(f\"  Overall: {colors.get(status,'')}\033[1m{status.upper()}\033[0m\")
print(f\"  Timestamp: {data.get('timestamp','N/A')}\")
print()
checks = data.get('checks',{})
sym = {'pass':'\033[32m✓\033[0m','fail':'\033[31m✗\033[0m','warning':'\033[33m⚠\033[0m','skipped':'\033[90m⏭\033[0m'}
mx = max((len(k) for k in checks), default=0)
for key, c in checks.items():
    s = sym.get(c.get('status','?'),'?')
    lat = c.get('latency_ms',0)
    msg = c.get('message','')
    print(f'  {s} {key:<{mx}}  \033[2m{lat:>8.0f}ms\033[0m  {msg}')
    details = c.get('details',{})
    for sub_key in ('tables','buckets'):
        sub = details.get(sub_key,{})
        for sk, sv in sub.items():
            ss = sym.get(sv.get('status','fail'),'?')
            r = 'R:OK' if sv.get('readable', sv.get('read_access')) else 'R:NO'
            w = 'W:OK' if sv.get('writable', sv.get('write_access')) else 'W:NO'
            name = sv.get('table_name', sv.get('bucket','?'))
            print(f'      {ss} {sk}: {name}  {r}  {w}')
pc = sum(1 for c in checks.values() if c.get('status')=='pass')
fc = sum(1 for c in checks.values() if c.get('status')=='fail')
print(f'\n  {pc} passed, {fc} failed, {len(checks)} total')
" 2>/dev/null
    else
        echo "$body"
    fi
}

# ── Main ───────────────────────────────────────────────────────────

POD_TYPE=$(detect_pod)
BE_URL=$(resolve_backend_url "$POD_TYPE")

printf "${BOLD}Infrastructure Diagnostics${RESET}\n"
printf "Pod type:    ${BOLD}${POD_TYPE}${RESET}\n"
printf "Backend URL: ${DIM}${BE_URL}${RESET}\n"

# Run local checks for the detected pod
case "$POD_TYPE" in
    frontend) check_frontend_local ;;
    backend)  check_backend_local ;;
    bssmagic) check_bssmagic_local ;;
    *)        warn "pod detection" "unknown pod type — skipping local checks" ;;
esac

# Run backend API diagnostics (unless --local-only)
if [ "$LOCAL_ONLY" = "0" ]; then
    run_api_diagnostics "$BE_URL" || true
fi

# Summary
TOTAL=$((PASS_COUNT + FAIL_COUNT))
printf "\n${BOLD}Local checks: ${GREEN}${PASS_COUNT} passed${RESET}, "
if [ "$FAIL_COUNT" -gt 0 ]; then
    printf "${RED}${FAIL_COUNT} failed${RESET}"
else
    printf "${FAIL_COUNT} failed"
fi
printf " (${TOTAL} total)${RESET}\n\n"

[ "$FAIL_COUNT" -gt 0 ] && exit 1
exit 0

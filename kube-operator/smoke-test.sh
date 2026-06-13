#!/bin/bash
#
# Smoke Test Script
#
# Post-deployment validation. Run after operator-rollout.sh and app-rollout.sh
# (or any time you want to verify a running capability).
#
# Phases:
#   1. Diagnostics            - Backend health + AWS connectivity (~30s)
#   2. Smoke                  - Quick API endpoint validation (~30s)
#   3. BDD                    - BDD feature scenarios against live backend (~90s)
#   4. Integration            - Pipeline integration tests (~60s)
#   5. Pipeline               - Real end-to-end call processing pipeline (~120s)
#   6. OperatorState          - Operator-managed K8s state (ConfigMap, Secrets, STS env) (~5s)
#   7. AuthGate               - External /docs/ auth gate (302 → /login?next=) (~5s, requires --external-url)
#   8. CpqRuntimeConnector    - CPQ runtime connector + diagnostics endpoints (~5s)
#
# Usage:
#   ./smoke-test.sh                                    # Run all phases
#   ./smoke-test.sh --phase diagnostics                # Run a single phase
#   ./smoke-test.sh --openai-key sk-proj-...           # Pass OpenAI key
#   ./smoke-test.sh --namespace my-ns                  # Custom namespace
#   ./smoke-test.sh --external-url https://app.example.com   # Enable Phase 7 auth-gate test
#   ./smoke-test.sh --strict                           # Exit on first phase failure
#   ./smoke-test.sh --help                             # Show help
#
# Phase names accepted by --phase:
#   diagnostics | smoke | bdd | integration | pipeline | operator-state | auth-gate | cpq-runtime

set -euo pipefail

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Defaults
AWS_PROFILE="${AWS_PROFILE:-external-access}"
NAMESPACE=""
OPENAI_KEY="${OPENAI_API_KEY:-}"
RUN_PHASE=""
STRICT=false
CAPABILITY_FILE="${SCRIPT_DIR}/examples/nexus-ai-complete.yaml"
EXTERNAL_URL=""
KCTX_FLAG=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --phase)        RUN_PHASE="$2"; shift 2 ;;
        --openai-key)   OPENAI_KEY="$2"; shift 2 ;;
        --namespace)    NAMESPACE="$2"; shift 2 ;;
        --strict)       STRICT=true; shift ;;
        --capability)   CAPABILITY_FILE="$2"; shift 2 ;;
        --external-url) EXTERNAL_URL="$2"; shift 2 ;;
        --context)      KCTX_FLAG="--context=$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --phase PHASE        Run only specified phase"
            echo "                       (diagnostics|smoke|bdd|integration|pipeline|"
            echo "                        operator-state|auth-gate|cpq-runtime)"
            echo "  --openai-key KEY     Pass OpenAI API key for pipeline tests"
            echo "  --namespace NS       Kubernetes namespace (auto-detected if not set)"
            echo "  --context CTX        kubeconfig context (e.g. nexus-test)"
            echo "  --external-url URL   Public app URL — enables Phase 7 auth-gate test"
            echo "  --strict             Exit on first phase failure"
            echo "  --capability FILE    Capability YAML file (for namespace detection)"
            echo "  --help               Show this help"
            echo ""
            echo "Examples:"
            echo "  $0                                            # All phases (auth-gate skipped)"
            echo "  $0 --phase operator-state                     # Just verify K8s state"
            echo "  $0 --external-url https://app.example.com     # Include public auth gate"
            echo "  $0 --strict                                   # Fail fast on errors"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Detect namespace
if [ -z "$NAMESPACE" ]; then
    NAMESPACE=$(grep -E "^\s+namespace:" "${CAPABILITY_FILE}" 2>/dev/null | head -1 | awk '{print $2}')
    [ -z "$NAMESPACE" ] && NAMESPACE="nexus-ai-prod"
fi

# Capability name = namespace minus the last "-<env>" segment is unreliable;
# in this codebase capabilities use namespace == capability-name (e.g.
# "nexus-ai-prod"), so we'll use namespace as the capability prefix.
CAP_PREFIX="${NAMESPACE}"

# Find backend pod (tries several selectors used by current/older operator versions)
POD=""
for sel in "app.kubernetes.io/name=backend" "app=${NAMESPACE}-backend" "app=backend"; do
    POD=$(kubectl ${KCTX_FLAG} get pods -n "${NAMESPACE}" -l "$sel" \
        --field-selector=status.phase=Running \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
    [ -n "$POD" ] && break
done
# Last-resort: name-based grep (matches "<cap>-<env>-backend-<rs>-<pod>")
if [ -z "$POD" ]; then
    POD=$(kubectl ${KCTX_FLAG} get pods -n "${NAMESPACE}" --no-headers 2>/dev/null \
        | awk '/-backend-[a-f0-9]+-[a-z0-9]+/ && $3=="Running" {print $1; exit}' || true)
fi

if [ -z "$POD" ]; then
    echo -e "${RED}No backend pod found in namespace ${NAMESPACE}${NC}"
    echo "Tried selectors:"
    echo "  app.kubernetes.io/name=backend"
    echo "  app=${NAMESPACE}-backend"
    echo "  app=backend"
    echo "  name-based grep '*-backend-*'"
    echo "Ensure operator-rollout.sh + app-rollout.sh have completed."
    exit 1
fi

# Track results
PHASE_PASS=0
PHASE_FAIL=0
PHASE_SKIP=0

phase_header() {
    echo ""
    echo -e "${CYAN}=================================================================${NC}"
    echo -e "${CYAN}  Phase $1: $2${NC}"
    echo -e "${CYAN}=================================================================${NC}"
    echo ""
}

phase_result() {
    local phase_name="$1"
    local exit_code="$2"
    if [ "$exit_code" -eq 0 ]; then
        echo -e "${GREEN}  Phase ${phase_name}: PASSED${NC}"
        PHASE_PASS=$((PHASE_PASS + 1))
    else
        echo -e "${RED}  Phase ${phase_name}: FAILED (exit code: ${exit_code})${NC}"
        PHASE_FAIL=$((PHASE_FAIL + 1))
        if [ "$STRICT" = true ]; then
            echo -e "${RED}  Strict mode: aborting remaining phases${NC}"
            print_summary
            exit 1
        fi
    fi
}

should_run() {
    [ -z "$RUN_PHASE" ] || [ "$RUN_PHASE" = "$1" ]
}

print_summary() {
    echo ""
    echo -e "${CYAN}=================================================================${NC}"
    echo -e "${CYAN}  SMOKE TEST SUMMARY${NC}"
    echo -e "${CYAN}=================================================================${NC}"
    echo ""
    echo -e "  Phases passed:  ${GREEN}${PHASE_PASS}${NC}"
    echo -e "  Phases failed:  ${RED}${PHASE_FAIL}${NC}"
    echo -e "  Phases skipped: ${YELLOW}${PHASE_SKIP}${NC}"
    echo ""
    if [ "$PHASE_FAIL" -eq 0 ]; then
        echo -e "${GREEN}  ALL SMOKE TESTS PASSED${NC}"
    else
        echo -e "${RED}  SMOKE TESTS FAILED (${PHASE_FAIL} phase(s) failed)${NC}"
    fi
    echo ""
}

# ================================================================
# Header
# ================================================================
echo ""
echo -e "${CYAN}=================================================================${NC}"
echo -e "${CYAN}  Totogi Smoke Test${NC}"
echo -e "${CYAN}=================================================================${NC}"
echo ""
echo "  Namespace:    ${NAMESPACE}"
echo "  Pod:          ${POD}"
echo "  Context:      ${KCTX_FLAG:-<current>}"
if [ -n "$OPENAI_KEY" ]; then
    echo "  OpenAI Key:   SET (${OPENAI_KEY:0:10}...)"
else
    echo "  OpenAI Key:   NOT SET (will load from Secrets Manager)"
fi
if [ -n "$EXTERNAL_URL" ]; then
    echo "  External URL: ${EXTERNAL_URL}"
else
    echo "  External URL: (not set — Phase 7 auth-gate will be skipped)"
fi
echo "  Phase:        ${RUN_PHASE:-all}"
echo "  Strict:       ${STRICT}"
echo ""

# ================================================================
# Phase 1: Diagnostics
# ================================================================
if should_run "diagnostics"; then
    phase_header "1/8" "Diagnostics (Backend Health & AWS Connectivity)"

    kubectl ${KCTX_FLAG} exec -i -n "${NAMESPACE}" "${POD}" -- python3 << 'DIAG_EOF'
import json, sys, urllib.request, urllib.error

BASE = "http://localhost:8000"
PASS = 0
FAIL = 0

def api_get(path):
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=15) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try: return json.loads(e.read().decode())
        except: return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}

def check(name, ok, detail=""):
    global PASS, FAIL
    status = "PASS" if ok else "FAIL"
    PASS += 1 if ok else 0
    FAIL += 1 if not ok else 0
    print(f"  [{status}] {name}" + (f" - {detail}" if detail else ""))

r = api_get("/health")
check("Backend health", "status" in str(r) or "error" not in str(r), "HTTP 200")

r = api_get("/api/v1/diagnostics/nexus-ai")
checks = r.get("checks", {})
for comp, result in checks.items():
    status = result.get("status", "unknown")
    msg = result.get("message", "")[:80]
    latency = result.get("latency_ms", 0)
    ok = status in ("pass", "warning", "skipped")
    check(f"{comp}", ok, f"{status} ({latency:.0f}ms) {msg}")

print(f"\n  Diagnostics: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL > 0 else 0)
DIAG_EOF
    phase_result "Diagnostics" $?
else
    PHASE_SKIP=$((PHASE_SKIP + 1))
fi

# ================================================================
# Phase 2: Smoke Tests (Quick API validation)
# ================================================================
if should_run "smoke"; then
    phase_header "2/8" "Smoke Tests (API Endpoint Validation)"

    kubectl ${KCTX_FLAG} exec -i -n "${NAMESPACE}" "${POD}" -- python3 << 'SMOKE_EOF'
import json, sys, urllib.request, urllib.error

BASE = "http://localhost:8000"
PASS = 0
FAIL = 0

def check_endpoint(method, path, expect_status=200):
    global PASS, FAIL
    try:
        req = urllib.request.Request(f"{BASE}{path}", method=method)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
            PASS += 1
            detail = ""
            if isinstance(data, dict):
                if "status" in data: detail = f"status={data['status']}"
                elif "success" in data: detail = f"success={data['success']}"
                elif "enabled" in data: detail = f"enabled={data['enabled']}"
            print(f"  [PASS] {method} {path} -> {r.status} {detail}")
            return data
    except urllib.error.HTTPError as e:
        if e.code == expect_status:
            PASS += 1
            print(f"  [PASS] {method} {path} -> {e.code} (expected)")
        else:
            FAIL += 1
            print(f"  [FAIL] {method} {path} -> {e.code}")
        return None
    except Exception as e:
        FAIL += 1
        print(f"  [FAIL] {method} {path} -> {e}")
        return None

print("  API Endpoint Checks:")
print("  " + "-" * 50)

check_endpoint("GET", "/health")
check_endpoint("GET", "/api/v1/diagnostics/nexus-ai/summary")

r = check_endpoint("GET", "/api/v1/simulator/status")
if r:
    tasks = r.get("task_count", 0)
    recs = r.get("recording_count", 0)
    print(f"         Simulator: {tasks} tasks, {recs} recordings")

r = check_endpoint("GET", "/api/v1/journeys/")
if r:
    journeys = r.get("journeys", [])
    print(f"         Journeys: {len(journeys)} found")

check_endpoint("GET", "/api/v1/qa/analysis")
check_endpoint("GET", "/api/v1/calls/?page=1&page_size=1")
check_endpoint("GET", "/api/v1/auth/health")
check_endpoint("GET", "/api/v1/config/parameters")

print(f"\n  Smoke: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL > 0 else 0)
SMOKE_EOF
    phase_result "Smoke" $?
else
    PHASE_SKIP=$((PHASE_SKIP + 1))
fi

# ================================================================
# Phase 3: BDD Tests
# ================================================================
if should_run "bdd"; then
    phase_header "3/8" "BDD Tests (Behavioral Scenarios)"

    kubectl ${KCTX_FLAG} exec -i -n "${NAMESPACE}" "${POD}" -- bash -c '
cd /app
export SERVER_URL=http://localhost:8000
export BEHAVE_RUN_LIVE=true

echo "  Running BDD call-process simulator scenarios..."
echo "  " && echo "  -" | head -c 52 && echo ""

if [ -d "tests/bdd/features/call_process" ]; then
    python -m behave tests/bdd/features/call_process/call_process_simulator.feature \
        --no-capture --format progress --tags="~@live_wxcc" 2>&1 | tail -20
    BDD_EXIT=${PIPESTATUS[0]}
    if [ $BDD_EXIT -eq 0 ]; then
        echo ""
        echo "  [PASS] BDD scenarios completed"
    else
        echo ""
        echo "  [WARN] BDD scenarios had failures (exit: $BDD_EXIT)"
    fi
    exit $BDD_EXIT
else
    echo "  [SKIP] No BDD features found at tests/bdd/features/call_process/"
    exit 0
fi
' 2>&1
    phase_result "BDD" $?
else
    PHASE_SKIP=$((PHASE_SKIP + 1))
fi

# ================================================================
# Phase 4: Integration Tests
# ================================================================
if should_run "integration"; then
    phase_header "4/8" "Integration Tests (Pipeline Logic)"

    kubectl ${KCTX_FLAG} exec -i -n "${NAMESPACE}" "${POD}" -- bash -c '
cd /app
export SERVER_URL=http://localhost:8000
export USE_MOCK_AWS=true

echo "  Running call-process integration tests (mocked AWS)..."
echo "  " && echo "  -" | head -c 52 && echo ""

if [ -f "tests/integration/call_process/test_call_process_integration.py" ]; then
    python -m pytest tests/integration/call_process/test_call_process_integration.py \
        -v --tb=short -x --timeout=60 2>&1 | tail -30
    exit ${PIPESTATUS[0]}
else
    echo "  [SKIP] No integration tests found"
    exit 0
fi
' 2>&1
    phase_result "Integration" $?
else
    PHASE_SKIP=$((PHASE_SKIP + 1))
fi

# ================================================================
# Phase 5: Pipeline E2E (Real call processing)
# ================================================================
if should_run "pipeline"; then
    phase_header "5/8" "Pipeline E2E (Real Call Processing)"

    EXTRA_ENV=""
    if [ -n "$OPENAI_KEY" ]; then
        EXTRA_ENV="export OPENAI_API_KEY='${OPENAI_KEY}';"
    fi

    timeout 180 kubectl ${KCTX_FLAG} exec -i -n "${NAMESPACE}" "${POD}" -- bash -c "${EXTRA_ENV} python3" << 'PIPELINE_EOF'
import json, time, sys, urllib.request, urllib.error

BASE = "http://localhost:8000"
PASS = 0
FAIL = 0
WARN = 0

def api(method, path, data=None):
    url = f"{BASE}{path}"
    body = json.dumps(data).encode() if data else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try: return json.loads(e.read().decode())
        except: return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}

def check(name, ok, detail=""):
    global PASS, FAIL
    PASS += 1 if ok else 0
    FAIL += 1 if not ok else 0
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    return ok

def warn(name, detail=""):
    global WARN
    WARN += 1
    print(f"  [WARN] {name}" + (f" - {detail}" if detail else ""))

print("  [1/7] Checking OpenAI API key...")
r = api("GET", "/api/v1/diagnostics/nexus-ai/openai")
openai_ok = r.get("status") == "pass"
if not check("OpenAI API key", openai_ok, r.get("message", "")):
    warn("OpenAI", "Key not available - transcription/analysis will be skipped")

print("  [2/7] Checking WXCC Simulator...")
r = api("GET", "/api/v1/simulator/status")
task_count = r.get("task_count", 0)
rec_count = r.get("recording_count", 0)
if task_count == 0:
    print("  Seeding simulator with test data...")
    seed_r = api("POST", "/api/v1/simulator/seed", {"num_tasks": 3, "include_recordings": True})
    if seed_r.get("success"):
        print(f"    Seeded: {seed_r.get('data', {}).get('tasks_created', '?')} tasks")
        r = api("GET", "/api/v1/simulator/status")
        task_count = r.get("task_count", 0)
        rec_count = r.get("recording_count", 0)
sim_ok = task_count > 0
if not check("Simulator tasks", sim_ok, f"{task_count} tasks, {rec_count} recordings"):
    print("  FATAL: No simulator tasks available.")
    sys.exit(1)

print("  [3/7] Creating smoke-test journey...")
ts = int(time.time())
r = api("POST", "/api/v1/journeys/", {
    "name": f"smoke-test-{ts}",
    "description": "Automated smoke test journey",
    "odaComponentType": "product-management",
    "stages": [{
        "stageId": "call_process",
        "name": "Call Processing",
        "description": "Process call recordings",
        "type": "call-process"
    }]
})
journey_id = r.get("journey_id") or r.get("journeyId") or r.get("id")
if not journey_id and isinstance(r, dict):
    for key in ("data", "journey", "result"):
        if isinstance(r.get(key), dict):
            journey_id = r[key].get("journey_id") or r[key].get("journeyId") or r[key].get("id")
            if journey_id: break

if not check("Create journey", bool(journey_id), f"ID: {journey_id}" if journey_id else f"Resp: {str(r)[:80]}"):
    print("  FATAL: Could not create test journey.")
    sys.exit(1)

print("  [4/7] Executing call-process job...")
r = api("POST", f"/api/v1/journeys/{journey_id}/jobs?stage_id=call_process&triggered_by=smoke-test")
job_id = r.get("job_id") or r.get("jobId")
if not job_id and isinstance(r, dict):
    for key in ("data", "job", "result"):
        if isinstance(r.get(key), dict):
            job_id = r[key].get("job_id") or r[key].get("jobId")
            if job_id: break

if not check("Start job", bool(job_id), f"Job: {job_id}" if job_id else f"Resp: {str(r)[:80]}"):
    print("  FATAL: Could not start job.")
    sys.exit(1)

print("  [5/7] Waiting for job to complete (timeout: 120s)...")
status = "running"
progress = 0
for attempt in range(24):
    time.sleep(5)
    r = api("GET", f"/api/v1/journeys/{journey_id}/jobs/{job_id}/status")
    status = r.get("status", "unknown")
    progress = r.get("progress", 0)
    step = r.get("current_step", "?")
    print(f"    Poll {attempt+1}: status={status}, progress={progress}%, step={step}")
    if status in ("completed", "failed", "cancelled"):
        break

check("Job completed", status == "completed", f"status={status}, progress={progress}%")

print("  [6/7] Verifying recording processing...")
r = api("GET", f"/api/v1/journeys/{journey_id}/jobs/{job_id}/logs?step_name=process_recordings&limit=50")
data = r.get("data", {})
logs = data.get("logs", []) if isinstance(data, dict) else []
total = data.get("totalLogs", len(logs)) if isinstance(data, dict) else 0
ok_count = sum(1 for l in logs if "processed successfully" in l.get("message", "").lower())
err_count = sum(1 for l in logs if "completed with errors" in l.get("message", ""))
dedup = any("No new tasks" in l.get("message", "") for l in logs)

if ok_count > 0:
    check("Recordings", True, f"{ok_count} processed, {err_count} errors")
elif dedup:
    warn("Recordings", "All tasks already processed (deduplication)")
elif total > 0:
    warn("Recordings", f"{total} logs, {err_count} errors")
else:
    warn("Recordings", "No logs found")

print("  [7/7] Checking Processed Calls API...")
r = api("GET", "/api/v1/calls/?page=1&page_size=1")
calls = r.get("data", [])
if isinstance(calls, list) and len(calls) > 0:
    check("Processed Calls", True, "Calls found in Glue")
elif "error" in str(r).lower():
    check("Processed Calls", False, f"API error: {str(r)[:80]}")
else:
    warn("Processed Calls", "No calls yet (Glue registration may be pending)")

print(f"\n  Pipeline E2E: {PASS} passed, {FAIL} failed, {WARN} warnings")
sys.exit(1 if FAIL > 0 else 0)
PIPELINE_EOF
    phase_result "Pipeline" $?
else
    PHASE_SKIP=$((PHASE_SKIP + 1))
fi

# ================================================================
# Phase 6: Operator-Managed K8s State
# ================================================================
if should_run "operator-state"; then
    phase_header "6/8" "Operator-Managed K8s State (ConfigMap, Secrets, STS env)"

    P6_PASS=0
    P6_FAIL=0
    P6_WARN=0
    p6_check() { local s=$1; local n=$2; local d=${3:-}
        if [ "$s" = "PASS" ]; then echo "  [PASS] $n${d:+ - $d}"; P6_PASS=$((P6_PASS+1));
        elif [ "$s" = "WARN" ]; then echo -e "  ${YELLOW}[WARN]${NC} $n${d:+ - $d}"; P6_WARN=$((P6_WARN+1));
        else echo -e "  ${RED}[FAIL]${NC} $n${d:+ - $d}"; P6_FAIL=$((P6_FAIL+1)); fi
    }

    # 6a. Frontend ConfigMap has docs auth blocks
    CM_NAME="${CAP_PREFIX}-frontend-config"
    CM_NGINX=$(kubectl ${KCTX_FLAG} -n "${NAMESPACE}" get cm "${CM_NAME}" -o jsonpath='{.data.nginx\.conf}' 2>/dev/null || echo "")
    if [ -z "$CM_NGINX" ]; then
        p6_check FAIL "Frontend ConfigMap '${CM_NAME}'" "missing or empty nginx.conf key"
    else
        for token in '_auth_check' 'auth_request' 'docs_login_redirect' 'absolute_redirect off' 'next=$request_uri'; do
            if echo "$CM_NGINX" | grep -qF "$token"; then
                p6_check PASS "ConfigMap nginx contains '${token}'"
            else
                p6_check FAIL "ConfigMap nginx missing '${token}'" "operator may be on old image"
            fi
        done
    fi

    # 6b. bssmagic K8s Secret bootstrapped from AWS SM
    AXWAY_SEC="${CAP_PREFIX}-bssmagic-axway"
    AXWAY_KEY_COUNT=$(kubectl ${KCTX_FLAG} -n "${NAMESPACE}" get secret "${AXWAY_SEC}" \
        -o jsonpath='{.data}' 2>/dev/null | tr ',' '\n' | grep -c 'AXWAY_' || true)
    if [ "${AXWAY_KEY_COUNT:-0}" -ge 10 ]; then
        p6_check PASS "K8s Secret '${AXWAY_SEC}'" "${AXWAY_KEY_COUNT} AXWAY_* keys"
    elif [ "${AXWAY_KEY_COUNT:-0}" -gt 0 ]; then
        p6_check WARN "K8s Secret '${AXWAY_SEC}'" "${AXWAY_KEY_COUNT} keys (expected 10)"
    else
        p6_check WARN "K8s Secret '${AXWAY_SEC}'" "missing — bootstrap may not have run, or this env doesn't use Axway"
    fi

    # 6c. bssmagic StatefulSet env: AXWAY_* via secretKeyRef, no inlined values
    STS_NAME="${CAP_PREFIX}-bssmagic"
    STS_JSON=$(kubectl ${KCTX_FLAG} -n "${NAMESPACE}" get sts "${STS_NAME}" -o json 2>/dev/null || echo "{}")
    if [ "$STS_JSON" = "{}" ]; then
        p6_check WARN "StatefulSet '${STS_NAME}'" "not found — bssmagic may be disabled in this env"
    else
        SEC_REF_COUNT=$(echo "$STS_JSON" | jq '[.spec.template.spec.containers[].env[]?]
            | map(select(.name|tostring|startswith("AXWAY")))
            | map(select(.valueFrom!=null)) | length' 2>/dev/null || echo 0)
        INLINE_COUNT=$(echo "$STS_JSON" | jq '[.spec.template.spec.containers[].env[]?]
            | map(select(.name|tostring|startswith("AXWAY")))
            | map(select(.value!=null and .valueFrom==null)) | length' 2>/dev/null || echo 0)
        if [ "${INLINE_COUNT:-0}" -eq 0 ] && [ "${SEC_REF_COUNT:-0}" -ge 1 ]; then
            p6_check PASS "STS AXWAY_* env" "${SEC_REF_COUNT} via secretKeyRef, 0 inlined"
        elif [ "${INLINE_COUNT:-0}" -gt 0 ]; then
            p6_check FAIL "STS AXWAY_* env" "${INLINE_COUNT} still inlined — operator did not switch to secretKeyRef"
        else
            p6_check WARN "STS AXWAY_* env" "no AXWAY_* env vars found"
        fi

        FDW_MODE=$(echo "$STS_JSON" | jq -r '[.spec.template.spec.containers[].env[]?]
            | map(select(.name=="BSSMAGIC_FDW_MODE")) | .[0].value // ""' 2>/dev/null || echo "")
        if [ -n "$FDW_MODE" ]; then
            p6_check PASS "STS BSSMAGIC_FDW_MODE" "value='$FDW_MODE'"
        else
            p6_check WARN "STS BSSMAGIC_FDW_MODE" "env var not set"
        fi
    fi

    echo ""
    echo "  Phase 6: ${P6_PASS} passed, ${P6_FAIL} failed, ${P6_WARN} warnings"
    [ "$P6_FAIL" -eq 0 ]
    phase_result "OperatorState" $?
else
    PHASE_SKIP=$((PHASE_SKIP + 1))
fi

# ================================================================
# Phase 7: Public Auth Gate (/docs/ external check)
# ================================================================
if should_run "auth-gate"; then
    if [ -z "$EXTERNAL_URL" ]; then
        echo ""
        echo -e "${CYAN}  Phase 7/8 — AuthGate: SKIPPED (use --external-url to enable)${NC}"
        echo ""
        PHASE_SKIP=$((PHASE_SKIP + 1))
    else
        phase_header "7/8" "Public Auth Gate (/docs/ → /login?next=)"

        # Strip trailing slash for clean concat
        BASE_URL="${EXTERNAL_URL%/}"

        P7_FAIL=0
        for path in /docs/ /docs/index.html /docs/operational/; do
            CODE=$(curl -s -o /dev/null -w "%{http_code}" -I "${BASE_URL}${path}" 2>/dev/null || echo "000")
            LOC=$(curl -s -o /dev/null -w "%{redirect_url}" -I "${BASE_URL}${path}" 2>/dev/null || echo "")
            if [ "$CODE" = "302" ] && echo "$LOC" | grep -q "/login?next="; then
                echo "  [PASS] GET ${path} -> 302 ${LOC}"
            else
                echo -e "  ${RED}[FAIL]${NC} GET ${path} -> ${CODE} ${LOC}"
                P7_FAIL=$((P7_FAIL+1))
            fi
        done

        # Invalid cookie still rejected
        CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Cookie: nexus_session=invalid" -I "${BASE_URL}/docs/" 2>/dev/null || echo "000")
        if [ "$CODE" = "302" ]; then
            echo "  [PASS] /docs/ with invalid cookie -> 302"
        else
            echo -e "  ${RED}[FAIL]${NC} /docs/ with invalid cookie -> ${CODE}"
            P7_FAIL=$((P7_FAIL+1))
        fi

        [ "$P7_FAIL" -eq 0 ]
        phase_result "AuthGate" $?
    fi
else
    PHASE_SKIP=$((PHASE_SKIP + 1))
fi

# ================================================================
# Phase 8: CPQ Runtime Connector
# ================================================================
if should_run "cpq-runtime"; then
    phase_header "8/8" "CPQ Runtime Connector (config + diagnostics endpoints)"

    kubectl ${KCTX_FLAG} exec -i -n "${NAMESPACE}" "${POD}" -- python3 << 'CPQ_EOF'
import json, sys, urllib.request, urllib.error

BASE = "http://localhost:8000"
PASS = 0
FAIL = 0
WARN = 0

def hit(method, path):
    """Returns (status_code, body_or_none). Treats any 2xx/4xx as 'reachable',
    network errors / 5xx as 'broken'."""
    req = urllib.request.Request(f"{BASE}{path}", method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try: body = json.loads(e.read().decode())
        except Exception: body = None
        return e.code, body
    except Exception as e:
        return 0, {"error": str(e)}

# /config — public for the SPA, returns mode/internal_transport flags
code, body = hit("GET", "/api/v1/cpq-runtime/config")
if code == 200 and isinstance(body, dict):
    expected = {"mode", "internal_transport", "has_api_key", "has_direct_credentials", "has_axway_credentials"}
    missing = expected - set(body.keys())
    if not missing:
        PASS += 1
        print(f"  [PASS] GET /api/v1/cpq-runtime/config -> 200 mode={body.get('mode')} transport={body.get('internal_transport')} has_api_key={body.get('has_api_key')} has_axway={body.get('has_axway_credentials')}")
    else:
        FAIL += 1
        print(f"  [FAIL] GET /api/v1/cpq-runtime/config -> 200 missing fields: {missing}")
elif code in (401, 403):
    WARN += 1
    print(f"  [WARN] GET /api/v1/cpq-runtime/config -> {code} (admin-gated; cannot validate shape from inside pod)")
elif code == 0:
    FAIL += 1
    print(f"  [FAIL] GET /api/v1/cpq-runtime/config -> network error: {body}")
elif code in (404, 500, 502, 503, 504):
    FAIL += 1
    print(f"  [FAIL] GET /api/v1/cpq-runtime/config -> {code}")
else:
    WARN += 1
    print(f"  [WARN] GET /api/v1/cpq-runtime/config -> {code}")

# /diagnostics — admin-gated; we only check it's reachable, not 404/500
code, body = hit("POST", "/api/v1/cpq-runtime/diagnostics")
if code in (200, 401, 403):
    PASS += 1
    detail = "OK" if code == 200 else f"reachable (gated, {code})"
    print(f"  [PASS] POST /api/v1/cpq-runtime/diagnostics -> {code} ({detail})")
elif code == 0:
    FAIL += 1
    print(f"  [FAIL] POST /api/v1/cpq-runtime/diagnostics -> network error: {body}")
elif code in (404, 500, 502, 503, 504):
    FAIL += 1
    print(f"  [FAIL] POST /api/v1/cpq-runtime/diagnostics -> {code}")
else:
    WARN += 1
    print(f"  [WARN] POST /api/v1/cpq-runtime/diagnostics -> {code}")

# /apply-transport — admin-gated; reachability only (don't actually trigger restart)
code, body = hit("GET", "/api/v1/cpq-runtime/apply-transport")
# GET should be 405 Method Not Allowed (only POST defined) → endpoint exists
if code in (200, 401, 403, 405):
    PASS += 1
    print(f"  [PASS] /api/v1/cpq-runtime/apply-transport route registered ({code})")
elif code == 404:
    FAIL += 1
    print(f"  [FAIL] /api/v1/cpq-runtime/apply-transport -> 404 (route not registered)")
else:
    WARN += 1
    print(f"  [WARN] /api/v1/cpq-runtime/apply-transport -> {code}")

print(f"\n  CPQ Runtime: {PASS} passed, {FAIL} failed, {WARN} warnings")
sys.exit(1 if FAIL > 0 else 0)
CPQ_EOF
    phase_result "CpqRuntimeConnector" $?
else
    PHASE_SKIP=$((PHASE_SKIP + 1))
fi

# ================================================================
# Summary
# ================================================================
print_summary

exit $PHASE_FAIL

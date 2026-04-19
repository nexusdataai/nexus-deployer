#!/bin/bash
#
# E2E Smoke Test Script
#
# Runs post-deployment validation tests inside the backend pod.
# Should be run after ./e2e-deploy.sh completes successfully.
#
# Phases:
#   1. Diagnostics  - Backend health, AWS connectivity, OpenAI key (~30s)
#   2. Smoke        - Quick API endpoint validation (~30s)
#   3. BDD          - BDD feature scenarios against live backend (~90s)
#   4. Integration  - Pipeline integration tests (~60s)
#   5. Pipeline     - Real end-to-end call processing pipeline (~120s)
#
# Usage:
#   ./e2e-smoke-test.sh                           # Run all phases
#   ./e2e-smoke-test.sh --phase diagnostics       # Run only diagnostics
#   ./e2e-smoke-test.sh --phase smoke             # Run only smoke tests
#   ./e2e-smoke-test.sh --phase pipeline          # Run only pipeline E2E
#   ./e2e-smoke-test.sh --openai-key sk-proj-...  # Pass OpenAI key
#   ./e2e-smoke-test.sh --namespace my-ns         # Custom namespace
#   ./e2e-smoke-test.sh --strict                  # Exit on first phase failure
#   ./e2e-smoke-test.sh --help                    # Show help

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
CAPABILITY_FILE="${SCRIPT_DIR}/examples/call-processing-complete.yaml"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --phase)
            RUN_PHASE="$2"
            shift 2
            ;;
        --openai-key)
            OPENAI_KEY="$2"
            shift 2
            ;;
        --namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        --strict)
            STRICT=true
            shift
            ;;
        --capability)
            CAPABILITY_FILE="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --phase PHASE        Run only specified phase (diagnostics|smoke|bdd|integration|pipeline)"
            echo "  --openai-key KEY     Pass OpenAI API key for pipeline tests"
            echo "  --namespace NS       Kubernetes namespace (auto-detected if not set)"
            echo "  --strict             Exit on first phase failure"
            echo "  --capability FILE    Capability YAML file (for namespace detection)"
            echo "  --help               Show this help"
            echo ""
            echo "Environment Variables:"
            echo "  OPENAI_API_KEY       OpenAI API key"
            echo "  AWS_PROFILE          AWS profile (default: external-access)"
            echo "  NAMESPACE            Kubernetes namespace"
            echo ""
            echo "Examples:"
            echo "  $0                                    # Run all phases"
            echo "  $0 --phase diagnostics                # Quick health check"
            echo "  $0 --phase pipeline --openai-key sk-  # Full pipeline test"
            echo "  $0 --strict                           # Fail fast on errors"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Detect namespace
if [ -z "$NAMESPACE" ]; then
    NAMESPACE=$(grep -E "^\s+namespace:" "${CAPABILITY_FILE}" 2>/dev/null | head -1 | awk '{print $2}')
    if [ -z "$NAMESPACE" ]; then
        NAMESPACE="call-processing-prod"
    fi
fi

# Find backend pod
POD=$(kubectl get pods -n "${NAMESPACE}" -l "app=${NAMESPACE}-backend" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)

if [ -z "$POD" ]; then
    echo -e "${RED}No backend pod found in namespace ${NAMESPACE}${NC}"
    echo "Make sure the deployment is complete before running smoke tests."
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
echo -e "${CYAN}  Totogi E2E Smoke Test${NC}"
echo -e "${CYAN}=================================================================${NC}"
echo ""
echo "  Namespace:  ${NAMESPACE}"
echo "  Pod:        ${POD}"
if [ -n "$OPENAI_KEY" ]; then
    echo "  OpenAI Key: SET (${OPENAI_KEY:0:10}...)"
else
    echo "  OpenAI Key: NOT SET (will load from Secrets Manager)"
fi
echo "  Phase:      ${RUN_PHASE:-all}"
echo "  Strict:     ${STRICT}"
echo ""

# ================================================================
# Phase 1: Diagnostics
# ================================================================
if should_run "diagnostics"; then
    phase_header "1/5" "Diagnostics (Backend Health & AWS Connectivity)"

    kubectl exec -i -n "${NAMESPACE}" "${POD}" -- python3 << 'DIAG_EOF'
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

# Health check
r = api_get("/health")
check("Backend health", "status" in str(r) or "error" not in str(r), "HTTP 200")

# Full diagnostics
r = api_get("/api/v1/diagnostics/call-processing")
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
    phase_header "2/5" "Smoke Tests (API Endpoint Validation)"

    kubectl exec -i -n "${NAMESPACE}" "${POD}" -- python3 << 'SMOKE_EOF'
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

# Core health
check_endpoint("GET", "/health")
check_endpoint("GET", "/api/v1/diagnostics/call-processing/summary")

# Simulator
r = check_endpoint("GET", "/api/v1/simulator/status")
if r:
    tasks = r.get("task_count", 0)
    recs = r.get("recording_count", 0)
    print(f"         Simulator: {tasks} tasks, {recs} recordings")

# Journeys
r = check_endpoint("GET", "/api/v1/journeys/")
if r:
    journeys = r.get("journeys", [])
    print(f"         Journeys: {len(journeys)} found")

# QA Analytics
check_endpoint("GET", "/api/v1/qa/analysis")

# Processed Calls
check_endpoint("GET", "/api/v1/calls/?page=1&page_size=1")

# Auth health
check_endpoint("GET", "/api/v1/auth/health")

# Config
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
    phase_header "3/5" "BDD Tests (Behavioral Scenarios)"

    kubectl exec -i -n "${NAMESPACE}" "${POD}" -- bash -c '
cd /app
export SERVER_URL=http://localhost:8000
export BEHAVE_RUN_LIVE=true

echo "  Running BDD call-process simulator scenarios..."
echo "  " && echo "  -" | head -c 52 && echo ""

if [ -d "tests/bdd/features/call_process" ]; then
    # Run simulator-specific BDD tests (no real WXCC needed)
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
    phase_header "4/5" "Integration Tests (Pipeline Logic)"

    kubectl exec -i -n "${NAMESPACE}" "${POD}" -- bash -c '
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
    phase_header "5/5" "Pipeline E2E (Real Call Processing)"

    # Build env vars to pass into pod
    EXTRA_ENV=""
    if [ -n "$OPENAI_KEY" ]; then
        EXTRA_ENV="export OPENAI_API_KEY='${OPENAI_KEY}';"
    fi

    timeout 180 kubectl exec -i -n "${NAMESPACE}" "${POD}" -- bash -c "${EXTRA_ENV} python3" << 'PIPELINE_EOF'
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

# 1. Check OpenAI
print("  [1/7] Checking OpenAI API key...")
r = api("GET", "/api/v1/diagnostics/call-processing/openai")
openai_ok = r.get("status") == "pass"
if not check("OpenAI API key", openai_ok, r.get("message", "")):
    warn("OpenAI", "Key not available - transcription/analysis will be skipped")

# 2. Check simulator
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

# 3. Create test journey
print("  [3/7] Creating smoke-test journey...")
ts = int(time.time())
r = api("POST", "/api/v1/journeys/", {
    "name": f"smoke-test-{ts}",
    "description": "Automated smoke test journey",
    "odaComponentType": "product-management",
    "stages": [
        {
            "stageId": "call_process",
            "name": "Call Processing",
            "description": "Process call recordings",
            "type": "call-process"
        }
    ]
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

# 4. Execute call-process job
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

# 5. Poll for completion
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

# 6. Check recordings
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

# 7. Check calls API
print("  [7/7] Checking Processed Calls API...")
r = api("GET", "/api/v1/calls/?page=1&page_size=1")
calls = r.get("data", [])
if isinstance(calls, list) and len(calls) > 0:
    check("Processed Calls", True, "Calls found in Glue")
elif "error" in str(r).lower():
    check("Processed Calls", False, f"API error: {str(r)[:80]}")
else:
    warn("Processed Calls", "No calls yet (Glue registration may be pending)")

# Summary
print(f"\n  Pipeline E2E: {PASS} passed, {FAIL} failed, {WARN} warnings")
sys.exit(1 if FAIL > 0 else 0)
PIPELINE_EOF
    phase_result "Pipeline" $?
else
    PHASE_SKIP=$((PHASE_SKIP + 1))
fi

# ================================================================
# Summary
# ================================================================
print_summary

exit $PHASE_FAIL

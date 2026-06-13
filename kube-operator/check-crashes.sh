#!/bin/sh
# Pod Crash Investigator
#
# For every pod in the capability namespace with restartCount > 0, prints:
#   - container last-state (exit code, signal, reason, finishedAt, termination msg)
#   - last N lines of the *previous* container's stdout/stderr (the crash log)
#   - recent Pod Events (BackOff, OOMKilled, probe failures, image pulls, ...)
#   - liveness / readiness / startup probe config + resource limits
#
# Runs from a workstation or jumpbox with kubectl access to the cluster.
#
# Usage:
#   sh check-crashes.sh                              # All restarted pods (all components)
#   sh check-crashes.sh backend                      # Backend pods only
#   sh check-crashes.sh --pod NAME                   # Drill into a single named pod
#   sh check-crashes.sh --tail 500 all               # 500 lines of prev-container log
#   sh check-crashes.sh --save /tmp/crashes all      # Save per-pod artifacts
#   sh check-crashes.sh --env stage backend          # Override env
#   sh check-crashes.sh --cloudwatch all             # Also scan CloudWatch ERROR

set -e

# ── Colors ────────────────────────────────────────────────────────
GREEN="\033[32m"
RED="\033[31m"
YELLOW="\033[33m"
CYAN="\033[36m"
BOLD="\033[1m"
DIM="\033[2m"
RESET="\033[0m"

# ── Defaults ──────────────────────────────────────────────────────
CAPABILITY="nexus-ai"
ENV="dev"
NAMESPACE=""
TAIL="200"
SAVE_DIR=""
SPECIFIC_POD=""
COMPONENTS=""
CW_SCAN=0
CW_SINCE="1h"
WATCH_MODE=0
WATCH_INTERVAL=30
WATCH_CW=0
AWS_PROFILE="${AWS_PROFILE:-external-access}"
AWS_REGION="${AWS_REGION:-us-east-1}"

# ── Load .env.local (overrides defaults; CLI args override these) ─
_script_dir="$(cd "$(dirname "$0")" && pwd)"
_env_local="${_script_dir}/.env.local"
[ -f "$_env_local" ] && . "$_env_local"
unset _script_dir _env_local

# ── Argument parsing ──────────────────────────────────────────────
while [ $# -gt 0 ]; do
    case "$1" in
        --capability)    CAPABILITY="$2"; shift 2 ;;
        --env)           ENV="$2"; shift 2 ;;
        --namespace|-n)  NAMESPACE="$2"; shift 2 ;;
        --pod)           SPECIFIC_POD="$2"; shift 2 ;;
        --tail)          TAIL="$2"; shift 2 ;;
        --save)          SAVE_DIR="$2"; shift 2 ;;
        --cloudwatch|--cw) CW_SCAN=1; shift ;;
        --cw-since)      CW_SINCE="$2"; shift 2 ;;
        --watch|-w)      WATCH_MODE=1; shift ;;
        --interval)      WATCH_INTERVAL="$2"; shift 2 ;;
        --watch-cw)      WATCH_CW=1; shift ;;
        --help|-h)
            cat <<'EOF'
Pod Crash Investigator

Usage: sh check-crashes.sh [OPTIONS] [COMPONENT...]

Components: backend, frontend, bssmagic, all (default: all)

Options:
  --capability NAME   Capability name (default: nexus-ai)
  --env ENV           Environment (default: from .env.local or 'dev')
  --namespace NS      Override namespace (default: {capability}-{env})
  --pod NAME          Investigate one specific pod (skips restart filter)
  --tail LINES        Lines of previous-container log to show (default: 200)
  --save DIR          Save per-pod artifacts (yaml, describe, prev log, events) to DIR
  --cloudwatch        Also scan CloudWatch log group /nexus/{cap}/{env} for ERROR
  --cw-since DURATION CloudWatch scan window (default: 1h)
  --watch, -w         Watch one pod and dump each NEW crash as it happens (Ctrl-C to stop)
  --interval N        Poll interval in seconds for --watch (default: 30)
  --watch-cw          Stream NEW ERROR lines from CloudWatch (Fluent Bit log group)
  --help, -h          Show this help

Lists every pod with restartCount > 0 in the namespace matching the requested
component(s), and for each one prints:
  • last-state of each container (exit code / signal / reason)
  • last N lines of the previous container's stdout/stderr (the crash log)
  • recent Pod events (BackOff, OOMKilled, probe failures, image pulls, ...)
  • livenessProbe / readinessProbe / startupProbe / resources

In --watch mode, the script polls a single pod and prints the just-crashed
container's exit details + previous-container log every time restartCount
increases. Auto-picks the pod if exactly one crashed pod matches the component
filter, otherwise requires --pod NAME.

In --watch-cw mode, streams new ERROR lines live from the Fluent-Bit log group
/nexus/{cap}/{env}. Filter pattern is built from --pod or the first component.
Useful when SIGKILL'd containers never flush stdout to kubelet but Fluent Bit
already shipped the line. Mutually exclusive with --watch.

Examples:
  sh check-crashes.sh                              # All restarted pods
  sh check-crashes.sh backend                      # Backend only
  sh check-crashes.sh --pod backend-abc-xyz        # Drill into one pod
  sh check-crashes.sh --tail 500 --save /tmp/cs    # Deep dump
  sh check-crashes.sh --env stage backend          # Override env
  sh check-crashes.sh --cloudwatch all             # Add CW ERROR scan (one-shot)
  sh check-crashes.sh --watch --pod backend-xyz    # Live-capture each new crash
  sh check-crashes.sh -w --interval 10 backend     # Auto-pick, poll every 10s
  sh check-crashes.sh --watch-cw --pod backend-xyz # Stream ERROR lines from CW
  sh check-crashes.sh --watch-cw backend           # Stream ERRORs for all backend pods
EOF
            exit 0
            ;;
        backend|frontend|bssmagic|all)
            COMPONENTS="${COMPONENTS} $1"; shift
            ;;
        *)
            echo "Unknown argument: $1  (try --help)" >&2
            exit 2
            ;;
    esac
done

# Normalize / default the component list.
COMPONENTS=$(echo "$COMPONENTS" | tr -s ' ' | sed 's/^ //;s/ $//')
[ -z "$COMPONENTS" ] && COMPONENTS="all"
case " $COMPONENTS " in
    *" all "*) COMPONENTS="backend frontend bssmagic" ;;
esac

NAMESPACE="${NAMESPACE:-${CAPABILITY}-${ENV}}"

if [ "$WATCH_MODE" = "1" ] && [ "$WATCH_CW" = "1" ]; then
    echo "--watch and --watch-cw are mutually exclusive (both are blocking loops)." >&2
    echo "Run them in two terminals if you want both views." >&2
    exit 2
fi

# ── Helpers ───────────────────────────────────────────────────────
hr()      { printf "${DIM}--------------------------------------------------------------------${RESET}\n"; }
header()  { echo ""; printf "${BOLD}${CYAN}== %s ==${RESET}\n" "$1"; }
sub()     { printf "${BOLD}%s${RESET}\n" "$1"; }
red()     { printf "${RED}%s${RESET}\n" "$1"; }
yellow()  { printf "${YELLOW}%s${RESET}\n" "$1"; }
green()   { printf "${GREEN}%s${RESET}\n" "$1"; }

[ -n "$SAVE_DIR" ] && mkdir -p "$SAVE_DIR"

# Match a component label against a pod name. Handles Deployment hash suffixes
# (-backend-<hash>-<rand>) and StatefulSet ordinals (-bssmagic-0).
match_component() {
    pod="$1"; comp="$2"
    case "$pod" in
        *-${comp}-*|*-${comp}|${comp}-*) return 0 ;;
        *) return 1 ;;
    esac
}

# Print last-state of a specific container as a short block.
print_last_state() {
    pod="$1"; container="$2"
    kubectl -n "$NAMESPACE" get pod "$pod" -o json 2>/dev/null \
      | python3 -c "
import sys, json
d = json.load(sys.stdin)
for cs in d.get('status', {}).get('containerStatuses', []):
    if cs.get('name') != '$container':
        continue
    ls = cs.get('lastState', {}).get('terminated') or {}
    cur = cs.get('state', {})
    rc = cs.get('restartCount', 0)
    ready = cs.get('ready', False)
    cur_state = list(cur.keys())[0] if cur else '?'
    if ls:
        print(f\"    restartCount={rc}  ready={ready}  current={cur_state}\")
        print(f\"    lastTerminated: exitCode={ls.get('exitCode')}  signal={ls.get('signal')}  reason={ls.get('reason')}\")
        print(f\"                    startedAt={ls.get('startedAt')}  finishedAt={ls.get('finishedAt')}\")
        msg = (ls.get('message') or '').strip()
        if msg:
            print('    terminationMessage:')
            for line in msg.splitlines()[:20]:
                print('      ' + line)
    else:
        print(f\"    restartCount={rc}  ready={ready}  current={cur_state}  (no previous-termination state recorded)\")
" 2>/dev/null
}

# ── Pre-flight ────────────────────────────────────────────────────
header "Crash Investigator  Namespace: ${NAMESPACE}  $(date)"

if ! command -v kubectl >/dev/null 2>&1; then
    red "kubectl not on PATH"; exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    red "python3 not on PATH (used for JSON parsing)"; exit 1
fi
if ! kubectl get ns "$NAMESPACE" >/dev/null 2>&1; then
    red "Namespace '$NAMESPACE' not found in context $(kubectl config current-context 2>/dev/null)"
    exit 1
fi

# ── Resolve target pods ──────────────────────────────────────────
if [ -n "$SPECIFIC_POD" ]; then
    TARGET_PODS="$SPECIFIC_POD"
else
    ALL_RESTARTED=$(kubectl -n "$NAMESPACE" get pods -o json 2>/dev/null \
      | python3 -c "
import sys, json
d = json.load(sys.stdin)
for p in d.get('items', []):
    name = p['metadata']['name']
    rc = sum(cs.get('restartCount', 0) for cs in (p.get('status', {}).get('containerStatuses') or []))
    if rc > 0:
        print(name)
")
    TARGET_PODS=""
    for p in $ALL_RESTARTED; do
        for c in $COMPONENTS; do
            if match_component "$p" "$c"; then
                TARGET_PODS="${TARGET_PODS} $p"
                break
            fi
        done
    done
fi

TARGET_PODS=$(echo "$TARGET_PODS" | tr -s ' ' | sed 's/^ //;s/ $//')

if [ -z "$TARGET_PODS" ] && [ "$WATCH_MODE" = "0" ]; then
    green "✓ No restarted pods matching components: $COMPONENTS"
    [ "$CW_SCAN" = "0" ] && exit 0
fi

# ── Watch mode (live-capture each new crash on ONE pod) ──────────
if [ "$WATCH_MODE" = "1" ]; then
    # Resolve the single pod to watch.
    if [ -z "$SPECIFIC_POD" ]; then
        case "$TARGET_PODS" in
            "")
                red "Watch mode: no crashed pod found to auto-pick. Pass --pod NAME."
                exit 1
                ;;
            *" "*)
                red "Watch mode: multiple crashed pods match (${TARGET_PODS})."
                red "Re-run with --pod NAME to pick one."
                exit 1
                ;;
            *)
                SPECIFIC_POD="$TARGET_PODS"
                ;;
        esac
    fi
    WPOD="$SPECIFIC_POD"

    # Returns one line per container: "ctrname=restartCount"
    get_counts() {
        kubectl -n "$NAMESPACE" get pod "$WPOD" -o json 2>/dev/null \
          | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for cs in d.get('status', {}).get('containerStatuses', []) or []:
    print(cs.get('name', '?') + '=' + str(cs.get('restartCount', 0)))
"
    }

    PREV_COUNTS=$(get_counts)
    if [ -z "$PREV_COUNTS" ]; then
        red "Pod $WPOD not found in namespace $NAMESPACE"
        exit 1
    fi

    header "Watch  Pod: ${WPOD}  interval=${WATCH_INTERVAL}s  $(date)"
    sub "Baseline restart counts:"
    echo "$PREV_COUNTS" | sed 's/^/  /'
    yellow "  (Ctrl-C to stop. New crashes will print here as they happen.)"

    while true; do
        sleep "$WATCH_INTERVAL"
        CUR_COUNTS=$(get_counts)
        if [ -z "$CUR_COUNTS" ]; then
            red "[$(date '+%Y-%m-%d %H:%M:%S')] Pod ${WPOD} disappeared (replaced or namespace gone). Exiting watch."
            exit 0
        fi

        # Find containers whose restartCount increased since the last poll.
        CHANGED=""
        for line in $CUR_COUNTS; do
            ctr=$(echo "$line" | cut -d= -f1)
            cur=$(echo "$line" | cut -d= -f2)
            prev=$(echo "$PREV_COUNTS" | grep "^${ctr}=" | cut -d= -f2 || true)
            prev=${prev:-0}
            if [ "$cur" -gt "$prev" ]; then
                CHANGED="${CHANGED}${ctr}:${prev}->${cur} "
            fi
        done

        if [ -n "$CHANGED" ]; then
            hr
            red "[$(date '+%Y-%m-%d %H:%M:%S')] NEW CRASH on ${WPOD}: ${CHANGED}"
            for entry in $CHANGED; do
                CTR=$(echo "$entry" | cut -d: -f1)
                echo ""
                printf "  ${BOLD}container=${CTR}${RESET}\n"
                print_last_state "$WPOD" "$CTR"
                echo ""
                printf "  ${BOLD}previous container log (--previous --tail=${TAIL}):${RESET}\n"
                PREV_LOG=$(kubectl -n "$NAMESPACE" logs "$WPOD" -c "$CTR" --previous --tail="$TAIL" 2>&1 || true)
                if echo "$PREV_LOG" | grep -q "previous terminated container .* not found"; then
                    yellow "    (no previous-container log — kubelet rotated already)"
                else
                    echo "$PREV_LOG" | sed 's/^/    /'
                fi
                if [ -n "$SAVE_DIR" ]; then
                    ts=$(date '+%Y%m%d-%H%M%S')
                    mkdir -p "${SAVE_DIR}/${WPOD}/crashes"
                    echo "$PREV_LOG" > "${SAVE_DIR}/${WPOD}/crashes/${ts}-${CTR}.log"
                fi
            done
            echo ""
            printf "  ${BOLD}recent events (last 10):${RESET}\n"
            kubectl -n "$NAMESPACE" get events \
                --field-selector "involvedObject.name=${WPOD}" \
                --sort-by='.lastTimestamp' 2>&1 | tail -10 | sed 's/^/    /'
            hr
        else
            line_summary=$(echo "$CUR_COUNTS" | tr '\n' ' ')
            printf "${DIM}[%s] no new crash (counts: %s)${RESET}\n" "$(date '+%H:%M:%S')" "$line_summary"
        fi
        PREV_COUNTS="$CUR_COUNTS"
    done
fi

# ── Watch mode: stream new ERROR lines from CloudWatch ──────────
if [ "$WATCH_CW" = "1" ]; then
    if ! command -v aws >/dev/null 2>&1; then
        red "aws CLI not on PATH (required for --watch-cw)"; exit 1
    fi

    LOG_GROUP="/nexus/${CAPABILITY}/${ENV}"

    # Build a CloudWatch Logs filter pattern.
    # Filter-pattern AND-combines quoted substrings; we always require "ERROR",
    # then optionally narrow by pod name or by the first selected component.
    PATTERN='"ERROR"'
    NARROW=""
    if [ -n "$SPECIFIC_POD" ]; then
        NARROW="$SPECIFIC_POD"
        PATTERN="\"ERROR\" \"${SPECIFIC_POD}\""
    else
        first_comp=$(echo "$COMPONENTS" | awk '{print $1}')
        case "$first_comp" in
            backend|frontend|bssmagic)
                NARROW="-${first_comp}-"
                PATTERN="\"ERROR\" \"-${first_comp}-\""
                ;;
        esac
    fi

    header "CloudWatch ERROR watch  Group: ${LOG_GROUP}  Narrow: ${NARROW:-<none>}  $(date)"
    sub "Filter pattern: ${PATTERN}"
    yellow "  (Ctrl-C to stop. Backfilling last ${CW_SINCE}, then streaming live.)"

    # aws logs tail --follow streams indefinitely; output format "short" gives
    # "<timestamp> <stream> <message>" which is what we want.
    exec aws logs tail "${LOG_GROUP}" \
        --since "${CW_SINCE}" \
        --follow \
        --filter-pattern "${PATTERN}" \
        --format short \
        --profile "${AWS_PROFILE}" \
        --region "${AWS_REGION}"
fi

# ── Per-pod investigation ────────────────────────────────────────
CRASH_COUNT=0
for POD in $TARGET_PODS; do
    CRASH_COUNT=$((CRASH_COUNT + 1))
    POD_SAVE_DIR=""
    if [ -n "$SAVE_DIR" ]; then
        POD_SAVE_DIR="${SAVE_DIR}/${POD}"
        mkdir -p "$POD_SAVE_DIR"
    fi

    hr
    sub "Pod: ${POD}"

    CONTAINERS=$(kubectl -n "$NAMESPACE" get pod "$POD" \
        -o jsonpath='{range .spec.containers[*]}{.name}{"\n"}{end}' 2>/dev/null)

    for CTR in $CONTAINERS; do
        echo ""
        printf "  ${BOLD}container=${CTR}${RESET}\n"
        print_last_state "$POD" "$CTR"

        echo ""
        printf "  ${BOLD}previous container log (--previous --tail=${TAIL}):${RESET}\n"
        PREV_LOG=$(kubectl -n "$NAMESPACE" logs "$POD" -c "$CTR" --previous --tail="$TAIL" 2>&1 || true)
        if echo "$PREV_LOG" | grep -q "previous terminated container .* not found"; then
            yellow "    (no previous-container log retained by kubelet — try --cloudwatch fallback)"
        elif [ -z "$PREV_LOG" ]; then
            yellow "    (previous-container log empty)"
        else
            echo "$PREV_LOG" | sed 's/^/    /'
        fi
        [ -n "$POD_SAVE_DIR" ] && echo "$PREV_LOG" > "${POD_SAVE_DIR}/${CTR}-previous.log"
    done

    echo ""
    printf "  ${BOLD}pod events (newest first, last 20):${RESET}\n"
    EVENTS=$(kubectl -n "$NAMESPACE" get events \
        --field-selector "involvedObject.name=${POD}" \
        --sort-by='.lastTimestamp' 2>&1 | tail -20)
    if [ -z "$EVENTS" ] || echo "$EVENTS" | grep -q "No resources found"; then
        yellow "    (no events retained for this pod)"
    else
        echo "$EVENTS" | sed 's/^/    /'
    fi
    [ -n "$POD_SAVE_DIR" ] && echo "$EVENTS" > "${POD_SAVE_DIR}/events.txt"

    echo ""
    printf "  ${BOLD}probes & resource limits:${RESET}\n"
    kubectl -n "$NAMESPACE" get pod "$POD" -o json 2>/dev/null \
      | python3 -c "
import sys, json
d = json.load(sys.stdin)
for c in d.get('spec', {}).get('containers', []):
    print('    container=' + c.get('name','?'))
    for probe in ('livenessProbe','readinessProbe','startupProbe'):
        if c.get(probe):
            print('      ' + probe + ': ' + json.dumps(c[probe], separators=(',', ':')))
    if c.get('resources'):
        print('      resources: ' + json.dumps(c['resources'], separators=(',', ':')))
" 2>/dev/null

    if [ -n "$POD_SAVE_DIR" ]; then
        kubectl -n "$NAMESPACE" get pod "$POD" -o yaml > "${POD_SAVE_DIR}/pod.yaml" 2>/dev/null
        kubectl -n "$NAMESPACE" describe pod "$POD" > "${POD_SAVE_DIR}/describe.txt" 2>/dev/null
    fi
done

# ── CloudWatch fallback scan ─────────────────────────────────────
if [ "$CW_SCAN" = "1" ]; then
    hr
    sub "CloudWatch ERROR scan (last ${CW_SINCE}, log group /nexus/${CAPABILITY}/${ENV})"
    if command -v aws >/dev/null 2>&1; then
        aws logs tail "/nexus/${CAPABILITY}/${ENV}" \
            --since "${CW_SINCE}" \
            --filter-pattern "ERROR" \
            --profile "${AWS_PROFILE}" \
            --region "${AWS_REGION}" 2>&1 | tail -200 | sed 's/^/  /'
    else
        yellow "  (aws CLI not on PATH — skipping CloudWatch scan)"
    fi
fi

# ── Summary ──────────────────────────────────────────────────────
echo ""
hr
if [ "$CRASH_COUNT" -gt 0 ]; then
    printf "${RED}${BOLD}Crashed pods inspected: %s${RESET}\n" "$CRASH_COUNT"
    [ -n "$SAVE_DIR" ] && printf "Artifacts saved under: %s\n" "$SAVE_DIR"
else
    green "No restarted pods in scope."
fi

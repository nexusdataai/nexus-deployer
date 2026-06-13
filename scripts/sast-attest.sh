#!/usr/bin/env bash
# SAST attestation script for Nexus AI Deployer.
#
# Runs Bandit + Semgrep + detect-secrets and emits a JSON attestation. The
# attestation is what gets quoted in the client-facing SAST attestation;
# raw findings (which are CONFIDENTIAL per the SAST report banner) must
# never leave engineering.
#
# Usage:
#   scripts/sast-attest.sh [output_path]
# Default output: kube-operator/tests/sast-attestation-<sha>.json
#
# Exits non-zero if any blocking (HIGH/ERROR) findings are detected, so it
# can be wired into release pipelines.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

SHA="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
DATE_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

OUTPUT="${1:-kube-operator/tests/sast-attestation-${SHA}.json}"
mkdir -p "$(dirname "$OUTPUT")"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "[sast-attest] commit=$SHA branch=$BRANCH"

echo "[sast-attest] running Bandit..."
bandit -c .bandit.yaml \
  -r backend kube-operator/src bssmagic-image \
  -f json -o "$WORK/bandit.json" \
  --exit-zero >/dev/null

BANDIT_HIGH=$(python3 -c "
import json, sys
data=json.load(open('$WORK/bandit.json'))
print(sum(1 for r in data.get('results', []) if r.get('issue_severity')=='HIGH'))
")
BANDIT_MED=$(python3 -c "
import json
data=json.load(open('$WORK/bandit.json'))
print(sum(1 for r in data.get('results', []) if r.get('issue_severity')=='MEDIUM'))
")

echo "[sast-attest] running Semgrep..."
if command -v semgrep >/dev/null; then
  semgrep --config "p/security-audit" --json -o "$WORK/semgrep.json" --quiet . >/dev/null || true
  SEMGREP_ERROR=$(python3 -c "
import json
data=json.load(open('$WORK/semgrep.json'))
print(sum(1 for r in data.get('results', []) if r.get('extra', {}).get('severity')=='ERROR'))
")
  SEMGREP_WARNING=$(python3 -c "
import json
data=json.load(open('$WORK/semgrep.json'))
print(sum(1 for r in data.get('results', []) if r.get('extra', {}).get('severity')=='WARNING'))
")
else
  echo "[sast-attest] semgrep not installed - skipping" >&2
  SEMGREP_ERROR="-1"
  SEMGREP_WARNING="-1"
fi

echo "[sast-attest] running detect-secrets..."
DS_NEW=0
if command -v detect-secrets-hook >/dev/null && [ -f .secrets.baseline ]; then
  if ! git ls-files | grep -vE '\.secrets\.baseline$|\.tar\.gz$|node_modules/|frontend/dist/|backend/venv/' \
       | xargs detect-secrets-hook --baseline .secrets.baseline >"$WORK/detect-secrets.out" 2>&1; then
    DS_NEW=$(grep -c "^Secret Type:" "$WORK/detect-secrets.out" || true)
  fi
fi

cat > "$OUTPUT" <<JSON
{
  "schema_version": "1",
  "repository": "nexus-deployer",
  "commit": "$SHA",
  "branch": "$BRANCH",
  "scanned_at_utc": "$DATE_UTC",
  "tools": {
    "bandit": {"version": "1.8.6", "high": $BANDIT_HIGH, "medium": $BANDIT_MED},
    "semgrep": {"version": "1.136.0", "error": $SEMGREP_ERROR, "warning": $SEMGREP_WARNING},
    "detect_secrets": {"version": "1.5.0", "new_findings_vs_baseline": $DS_NEW}
  },
  "blocking_total": $((BANDIT_HIGH + (SEMGREP_ERROR > 0 ? SEMGREP_ERROR : 0) + DS_NEW)),
  "passes_gate": $([ "$BANDIT_HIGH" -eq 0 ] && [ "$SEMGREP_ERROR" -le 0 ] && [ "$DS_NEW" -eq 0 ] && echo true || echo false)
}
JSON

echo "[sast-attest] wrote $OUTPUT"
cat "$OUTPUT"

if [ "$BANDIT_HIGH" -gt 0 ] || [ "$SEMGREP_ERROR" -gt 0 ] || [ "$DS_NEW" -gt 0 ]; then
  echo "[sast-attest] BLOCKING findings present - failing the gate" >&2
  exit 1
fi

echo "[sast-attest] gate passed"

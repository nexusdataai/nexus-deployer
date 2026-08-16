#!/usr/bin/env python3
"""
Run the Knowledge Processor (semantic_rag stage) on a target cluster after DR.

Discovers the journey via kubectl exec, starts the job, polls until complete,
and writes a JSON result file for dr_verify tier 5.

Exit 0 on success; exit 1 on failure.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tarfile
import time
from typing import Any, Dict, List, Optional, Tuple


def _kubectl_curl(
    namespace: str, deployment: str, method: str, path: str, timeout: int = 60,
) -> Tuple[int, str]:
    url = f"http://127.0.0.1:8000{path}"
    cmd = [
        "kubectl", "exec", "-n", namespace, f"deploy/{deployment}", "--",
        "curl", "-sS", "-X", method, "-w", "\n%{http_code}",
        "--max-time", str(timeout), url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return 0, proc.stderr.strip() or proc.stdout.strip()
    lines = proc.stdout.rsplit("\n", 1)
    if len(lines) == 2:
        body, code_str = lines[0], lines[1].strip()
    else:
        body, code_str = proc.stdout, "0"
    try:
        code = int(code_str)
    except ValueError:
        code = 0
        body = proc.stdout
    return code, body


def _parse_json(body: str) -> Any:
    if not body or not body.strip():
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {}


def _journey_has_semantic_rag(journey: Dict[str, Any]) -> bool:
    title = (journey.get("title") or journey.get("name") or "").lower()
    if "knowledge processor" in title:
        return True
    stages = journey.get("stages") or journey.get("stage_definitions") or []
    for st in stages:
        sid = st.get("stage_id") or st.get("id") or st.get("stageId") or ""
        if sid == "semantic_rag":
            return True
        name = (st.get("name") or "").lower()
        if "semantic" in name and "rag" in name:
            return True
    return False


def _discover_from_api(namespace: str, deployment: str) -> Optional[str]:
    code, body = _kubectl_curl(namespace, deployment, "GET", "/api/v1/journeys/?limit=1000")
    if code != 200:
        return None
    data = _parse_json(body)
    journeys: List[Dict[str, Any]] = []
    if isinstance(data, dict):
        journeys = data.get("items") or data.get("journeys") or data.get("data") or []
    elif isinstance(data, list):
        journeys = data

    for j in journeys:
        if _journey_has_semantic_rag(j):
            jid = j.get("journey_id") or j.get("journeyId") or j.get("id")
            if jid:
                return str(jid)
        name = (j.get("name") or j.get("title") or "").lower()
        if name in ("knowledge-processor", "knowledge_processor", "semantic-rag", "semantic_rag"):
            jid = j.get("journey_id") or j.get("journeyId") or j.get("id")
            if jid:
                return str(jid)
    return None


def _discover_from_tarball(transform_tar: str) -> Optional[str]:
    try:
        with tarfile.open(transform_tar, "r:gz") as tar:
            member = tar.getmember("items.jsonl")
            fh = tar.extractfile(member)
            if not fh:
                return None
            for line in fh:
                line = line.decode("utf-8").strip()
                if not line:
                    continue
                item = json.loads(line)
                gsi = item.get("GSI1PK") or ""
                if gsi != "JOURNEYS":
                    continue
                stages_raw = item.get("stages") or item.get("stage_definitions") or "[]"
                if isinstance(stages_raw, str):
                    try:
                        stages = json.loads(stages_raw)
                    except json.JSONDecodeError:
                        stages = []
                else:
                    stages = stages_raw
                for st in stages or []:
                    sid = st.get("stage_id") or st.get("id") or ""
                    if sid == "semantic_rag":
                        return item.get("journey_id") or item.get("PK", "").replace("JOURNEY#", "")
    except (OSError, KeyError, tarfile.TarError):
        pass
    return None


def discover_journey_id(
    namespace: str,
    deployment: str,
    override: Optional[str] = None,
    transform_tar: Optional[str] = None,
) -> Optional[str]:
    if override:
        return override
    jid = _discover_from_api(namespace, deployment)
    if jid:
        return jid
    if transform_tar:
        return _discover_from_tarball(transform_tar)
    return None


def _extract_metrics(status: Dict[str, Any]) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {}
    for key in ("validation_avg_score", "total_embeddings", "embeddings"):
        if key in status:
            metrics[key] = status[key]
    data = status.get("data") or {}
    if isinstance(data, dict):
        for key in ("validation_avg_score", "total_embeddings", "metrics", "summary"):
            if key in data:
                metrics[key] = data[key]
        inner = data.get("metrics") or data.get("summary") or {}
        if isinstance(inner, dict):
            for k, v in inner.items():
                metrics.setdefault(k, v)
    result = status.get("result") or {}
    if isinstance(result, dict):
        report = result.get("report") or {}
        if isinstance(report, dict):
            metrics.setdefault("validation_avg_score", report.get("average_score"))
            metrics.setdefault("tests_passed", report.get("tests_passed"))
            metrics.setdefault("total_tests", report.get("total_tests"))
    return metrics


def run_semantic_rag(args: argparse.Namespace) -> int:
    ns = args.namespace
    dep = args.deployment

    print(f"  namespace:   {ns}")
    print(f"  deployment:  {dep}")
    print(f"  timeout:     {args.timeout}s")
    print()

    journey_id = discover_journey_id(ns, dep, args.journey_id, args.transform_tar)
    if not journey_id:
        print("  ERROR: could not discover Knowledge Processor journey (semantic_rag)")
        print("         Provide --journey-id or restore transformation-system backup first.")
        return 1

    print(f"  journey_id:  {journey_id}")
    path = (
        f"/api/v1/journeys/{journey_id}/jobs"
        f"?stage_id=semantic_rag&triggered_by=context-dr"
    )
    code, body = _kubectl_curl(ns, dep, "POST", path, timeout=120)
    if code not in (200, 201, 202):
        print(f"  ERROR: start job failed HTTP {code}")
        print(f"         {body[:400]}")
        return 1

    resp = _parse_json(body)
    job_id = resp.get("job_id") or (resp.get("data") or {}).get("job_id")
    if not job_id:
        print(f"  ERROR: no job_id in response: {body[:400]}")
        return 1

    print(f"  job_id:      {job_id}")
    print(f"  polling status every {args.poll_interval}s ...")
    print()

    deadline = time.monotonic() + args.timeout
    last_status: Dict[str, Any] = {}
    terminal = {"completed", "failed", "cancelled", "error"}

    while time.monotonic() < deadline:
        scode, sbody = _kubectl_curl(
            ns, dep, "GET",
            f"/api/v1/journeys/{journey_id}/jobs/{job_id}/status",
        )
        if scode == 200:
            last_status = _parse_json(sbody)
            if not isinstance(last_status, dict):
                last_status = {}
            state = (
                last_status.get("status")
                or last_status.get("job_status")
                or (last_status.get("data") or {}).get("status")
                or ""
            ).lower()
            step = last_status.get("current_step") or last_status.get("step") or ""
            progress = last_status.get("progress") or last_status.get("step_progress")
            line = f"  status={state}"
            if step:
                line += f" step={step}"
            if progress is not None:
                line += f" progress={progress}"
            print(line, flush=True)

            if state in terminal:
                break
        time.sleep(args.poll_interval)
    else:
        print(f"  ERROR: timed out after {args.timeout}s")
        _write_result(args.output, {
            "success": False,
            "journey_id": journey_id,
            "job_id": job_id,
            "error": "timeout",
            "last_status": last_status,
        })
        return 1

    state = (
        last_status.get("status")
        or last_status.get("job_status")
        or (last_status.get("data") or {}).get("status")
        or "unknown"
    ).lower()
    metrics = _extract_metrics(last_status)

    result = {
        "success": state == "completed",
        "journey_id": journey_id,
        "job_id": job_id,
        "status": state,
        "metrics": metrics,
        "validation_avg_score": metrics.get("validation_avg_score"),
        "tests_passed": metrics.get("tests_passed"),
        "total_embeddings": metrics.get("total_embeddings") or metrics.get("embeddings"),
    }
    if args.output:
        _write_result(args.output, result)

    if state != "completed":
        print()
        print(f"  ERROR: semantic_rag job ended with status={state}")
        return 1

    score = metrics.get("validation_avg_score")
    print()
    if score is not None:
        print(f"  OK: semantic_rag completed (validation_avg_score={score})")
    else:
        print("  OK: semantic_rag completed")
    if score is not None and float(score) < 4.0:
        print(f"  WARN: validation score {score} below 4.0 threshold")
    return 0


def _write_result(path: Optional[str], data: Dict[str, Any]) -> None:
    if not path:
        return
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def main() -> int:
    p = argparse.ArgumentParser(description="Run semantic_rag on target after DR")
    p.add_argument("--namespace", required=True)
    p.add_argument("--deployment", required=True)
    p.add_argument("--journey-id", default=None, help="Override auto-discovery")
    p.add_argument("--transform-tar", default=None, help="Fallback journey discovery")
    p.add_argument("--timeout", type=int, default=2700, help="Poll timeout seconds (default 45m)")
    p.add_argument("--poll-interval", type=int, default=10)
    p.add_argument("--output", default=None, help="Write JSON result to this path")
    return run_semantic_rag(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())

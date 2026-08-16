#!/usr/bin/env python3
"""
Preflight checks for context-dr.sh — validate target (or source) readiness
before backup/restore.

Exit 0 when all required checks pass; exit 1 on failure.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

# S3-backed simulator bucket suffixes (operator naming)
S3_SIMULATOR_SUFFIXES = [
    "sfdc-simulator",
    "oracle-erp-simulator",
    "sap-simulator",
    "wxcc-simulator",
    "external-simulator",
]

DDB_TABLE_SUFFIXES = ["foundry-workspace", "transformation-system"]


def _resolve_bucket_name(
    s3: Any, capability: str, env: str, suffix: str, account_id: str,
) -> Optional[str]:
    candidates = [
        f"{capability}-{env}-{suffix}-{account_id}",
        f"{capability}-{env}-{suffix}",
    ]
    for bucket in candidates:
        try:
            s3.head_bucket(Bucket=bucket)
            return bucket
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in ("404", "NoSuchBucket", "NotFound") or status == 404:
                continue
            raise
    return None


def _run(cmd: List[str], timeout: int = 30) -> Tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip()


def _check_aws(profile: Optional[str], region: str) -> Tuple[bool, str, str]:
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    sts = session.client("sts", region_name=region)
    ident = sts.get_caller_identity()
    return True, ident["Account"], ident.get("Arn", "")


def _check_kubectl_namespace(namespace: str) -> Tuple[bool, str]:
    rc, out = _run(["kubectl", "get", "ns", namespace, "-o", "name"])
    if rc != 0:
        return False, out or f"namespace {namespace} not found"
    return True, "OK"


def _check_backend_ready(namespace: str, deployment: str) -> Tuple[bool, str]:
    rc, out = _run([
        "kubectl", "get", "deployment", deployment, "-n", namespace,
        "-o", "jsonpath={.status.readyReplicas}/{.spec.replicas}",
    ])
    if rc != 0:
        return False, out or f"deployment {deployment} not found"
    parts = out.split("/")
    if len(parts) == 2 and parts[0] == parts[1] and parts[0] not in ("", "0"):
        return True, f"ready {out}"
    return False, f"deployment not ready: {out or 'unknown'}"


def _check_ddb_table(
    profile: Optional[str], region: str, table_name: str,
) -> Tuple[bool, str]:
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    ddb = session.client("dynamodb", region_name=region)
    try:
        ddb.describe_table(TableName=table_name)
        return True, "exists"
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "ResourceNotFoundException":
            return False, "not found — deploy CR with dataServices enabled"
        return False, str(e)


def _check_ssm_journey_hint(
    profile: Optional[str], region: str, capability: str, env: str,
) -> Tuple[bool, str]:
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    ssm = session.client("ssm", region_name=region)
    prefixes = [
        f"/{capability}/{env}/",
        f"/{capability.replace('-', '_')}/{env}/",
    ]
    found = 0
    for prefix in prefixes:
        try:
            resp = ssm.get_parameters_by_path(Path=prefix, Recursive=True, MaxResults=10)
            found += len(resp.get("Parameters") or [])
        except ClientError:
            pass
    if found > 0:
        return True, f"{found} params under {prefixes[0]}"
    return False, f"no SSM params under {prefixes[0]} (warn only)"


def _check_pgvector(namespace: str, deployment: str) -> Tuple[bool, str]:
    rc, fdw_host = _run([
        "kubectl", "get", "deployment", deployment, "-n", namespace,
        "-o", "jsonpath={.spec.template.spec.containers[0].env[?(@.name=='FDW_PG_HOST')].value}",
    ])
    if rc == 0 and fdw_host.strip():
        return True, f"FDW_PG_HOST={fdw_host.strip()}"

    rc, sts = _run([
        "kubectl", "get", "statefulset", "pgvector", "-n", namespace,
        "-o", "jsonpath={.status.readyReplicas}/{.spec.replicas}",
    ])
    if rc == 0 and sts.strip() in ("1/1", "1"):
        return True, "pgvector StatefulSet ready (FDW env will be set by DR)"

    return False, "no FDW_PG_HOST and no pgvector StatefulSet — semantic_rag will fail"


def run_preflight(args: argparse.Namespace) -> int:
    capability = args.capability
    env = args.env
    profile = args.profile
    region = args.region
    namespace = args.namespace or f"{capability}-{env}"
    deployment = args.deployment or f"{namespace}-backend"

    print(f"  capability:  {capability}")
    print(f"  env:         {env}")
    print(f"  namespace:   {namespace}")
    print(f"  profile:     {profile or '(default)'}")
    print(f"  region:      {region}")
    print(f"  simulators:  {'required' if args.require_simulators else 'optional'}")
    print()

    failed = 0
    warned = 0

    def ok(name: str, detail: str = "") -> None:
        print(f"  OK    {name:24s} {detail}".rstrip())

    def fail(name: str, detail: str) -> None:
        nonlocal failed
        print(f"  FAIL  {name:24s} {detail}")
        failed += 1

    def warn(name: str, detail: str) -> None:
        nonlocal warned
        print(f"  WARN  {name:24s} {detail}")
        warned += 1

    # AWS session
    try:
        _, account_id, arn = _check_aws(profile, region)
        ok("aws-session", f"account={account_id}")
    except Exception as e:
        fail("aws-session", str(e))
        print()
        print(f"  Preflight: FAILED ({failed} errors)")
        return 1

    # Kube namespace
    if shutil.which("kubectl"):
        ns_ok, ns_msg = _check_kubectl_namespace(namespace)
        if ns_ok:
            ok("kubectl-namespace", namespace)
        else:
            fail("kubectl-namespace", ns_msg)

        dep_ok, dep_msg = _check_backend_ready(namespace, deployment)
        if dep_ok:
            ok("backend-deployment", dep_msg)
        else:
            fail("backend-deployment", dep_msg)

        if args.require_postgres:
            pg_ok, pg_msg = _check_pgvector(namespace, deployment)
            if pg_ok:
                ok("pgvector", pg_msg)
            else:
                fail("pgvector", pg_msg)
    else:
        warn("kubectl", "not on PATH — skipping cluster checks")

    # DDB tables
    for suffix in DDB_TABLE_SUFFIXES:
        table = f"{capability}-{env}-{suffix}"
        t_ok, t_msg = _check_ddb_table(profile, region, table)
        if t_ok:
            ok(f"ddb-{suffix}", table)
        else:
            fail(f"ddb-{suffix}", t_msg)

    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    s3 = session.client("s3", region_name=region)

    # Journey logs bucket (required for semantic_rag)
    journey_bucket = _resolve_bucket_name(
        s3, capability, env, "journey-logs", account_id,
    )
    if journey_bucket:
        ok("journey-logs-s3", journey_bucket)
    else:
        fail(
            "journey-logs-s3",
            f"{capability}-{env}-journey-logs-{account_id} missing — blocks semantic_rag",
        )

    # Simulator buckets
    sim_missing: List[str] = []
    for suffix in S3_SIMULATOR_SUFFIXES:
        bucket = _resolve_bucket_name(s3, capability, env, suffix, account_id)
        label = suffix.replace("-simulator", "").replace("external-", "external-")
        if bucket:
            ok(f"s3-{suffix[:20]}", bucket)
        else:
            sim_missing.append(suffix)
            if args.require_simulators:
                fail(f"s3-{suffix[:20]}", "not provisioned")
            else:
                warn(f"s3-{suffix[:20]}", "not provisioned")

    # SSM hint
    ssm_ok, ssm_msg = _check_ssm_journey_hint(profile, region, capability, env)
    if ssm_ok:
        ok("ssm-params", ssm_msg)
    else:
        warn("ssm-params", ssm_msg)

    print()
    if failed:
        print(f"  Preflight: FAILED ({failed} errors, {warned} warnings)")
        print()
        print("  Hint: deploy capability with dataServices enabled and wait for operator reconcile.")
        return 1
    print(f"  Preflight: PASSED ({warned} warnings)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Preflight checks for context-dr.sh")
    p.add_argument("--capability", required=True)
    p.add_argument("--env", required=True)
    p.add_argument("--profile", default=None)
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--namespace", default=None)
    p.add_argument("--deployment", default=None)
    p.add_argument(
        "--require-simulators", action="store_true",
        help="Fail if simulator S3 buckets are missing",
    )
    p.add_argument(
        "--skip-simulators", action="store_true",
        help="Do not require simulator buckets",
    )
    p.add_argument(
        "--require-postgres", action="store_true",
        help="Fail if pgvector / FDW_PG_* is not configured",
    )
    args = p.parse_args()
    args.require_simulators = args.require_simulators and not args.skip_simulators
    return run_preflight(args)


if __name__ == "__main__":
    sys.exit(main())

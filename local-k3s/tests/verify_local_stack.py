#!/usr/bin/env python3
"""Comprehensive nexus-local stack verification with per-API reporting.

AWS APIs (emphasis): DynamoDB (Scylla), S3 (MinIO), SSM, Secrets Manager,
Athena, Glue, STS — via MiniStack / Alternator / MinIO.

Data plane: Redis, Postgres, pgvector, GraphStore (AGE graphs/store/query/display), Trino, Mimir.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import struct
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

RUN_ID = uuid.uuid4().hex[:8]
PREFIX = f"nexus-verify-{RUN_ID}"

# ── ANSI ────────────────────────────────────────────────────────────────────

USE_COLOR = os.environ.get("NO_COLOR", "") == "" and (
    sys.stdout.isatty() or os.environ.get("FORCE_COLOR", "1") == "1"
)


def _c(code: str, text: str) -> str:
    if not USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def green(t: str) -> str:
    return _c("32", t)


def red(t: str) -> str:
    return _c("31", t)


def yellow(t: str) -> str:
    return _c("33", t)


def cyan(t: str) -> str:
    return _c("36", t)


def bold(t: str) -> str:
    return _c("1", t)


def dim(t: str) -> str:
    return _c("2", t)


class Skip(Exception):
    """Feature not available (e.g. AGE not in image)."""


@dataclass
class Check:
    category: str  # AWS | DATA
    service: str
    api: str
    ok: bool
    skipped: bool = False
    elapsed_ms: int = 0
    detail: str = ""

    @property
    def status(self) -> str:
        if self.skipped:
            return "SKIP"
        return "PASS" if self.ok else "FAIL"


@dataclass
class Report:
    checks: List[Check] = field(default_factory=list)

    def _emit(self, check: Check) -> None:
        self.checks.append(check)
        tag = check.status
        if tag == "PASS":
            tag_s = green(f"{tag:4}")
        elif tag == "FAIL":
            tag_s = red(f"{tag:4}")
        else:
            tag_s = yellow(f"{tag:4}")
        print(
            f"    {tag_s}  {check.service:<12} {check.api:<28} {check.elapsed_ms:>6} ms  {check.detail}",
            flush=True,
        )

    def run(
        self,
        category: str,
        service: str,
        api: str,
        fn: Callable[[], str],
        skip_if_missing: Optional[str] = None,
    ) -> None:
        if skip_if_missing:
            host, _, port_s = skip_if_missing.partition(":")
            if not tcp_open(host, int(port_s or "0"), timeout=2.0):
                self._emit(Check(category, service, api, True, True, 0, f"{skip_if_missing} unreachable"))
                return
        t0 = time.perf_counter()
        try:
            detail = fn() or "ok"
            ms = int((time.perf_counter() - t0) * 1000)
            self._emit(Check(category, service, api, True, False, ms, detail))
        except Skip as exc:
            ms = int((time.perf_counter() - t0) * 1000)
            self._emit(Check(category, service, api, True, True, ms, str(exc)))
        except Exception as exc:  # noqa: BLE001
            ms = int((time.perf_counter() - t0) * 1000)
            self._emit(Check(category, service, api, False, False, ms, _err(exc)))

    def counts(self, subset: Optional[List[Check]] = None) -> Tuple[int, int, int]:
        items = subset if subset is not None else self.checks
        p = sum(1 for c in items if c.ok and not c.skipped)
        f = sum(1 for c in items if not c.ok)
        s = sum(1 for c in items if c.skipped)
        return p, f, s


def _err(exc: BaseException) -> str:
    msg = str(exc).replace("\n", " ")
    if "An error occurred" in msg:
        # boto ClientError: An error occurred (Code) when calling the X: ...
        return msg.replace("An error occurred ", "")[:120]
    return msg[:120]


def tcp_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_get(url: str, timeout: float = 15.0, headers: Optional[dict] = None) -> str:
    req = Request(url, headers=headers or {})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def http_post(url: str, data: bytes, headers: Optional[dict] = None, timeout: float = 20.0) -> bytes:
    req = Request(url, data=data, method="POST", headers=headers or {})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:180]
        raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {body}".strip()) from exc


def boto_client(service: str, endpoint: str, access: str = "test", secret: str = "test"):
    import boto3
    from botocore.config import Config

    return boto3.client(
        service,
        endpoint_url=endpoint,
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        config=Config(
            retries={"max_attempts": 3, "mode": "standard"},
            s3={"addressing_style": "path"},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def host_port(url_or_host: str, default_port: str) -> str:
    raw = url_or_host.split("://", 1)[-1].split("/")[0]
    return raw if ":" in raw else f"{raw}:{default_port}"


def _clip(text: str, width: int) -> str:
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    return text[: max(0, width - 1)] + "…"


def _status_cell(st: str) -> str:
    raw = f"{st:^6}"
    if st == "PASS":
        return green(raw)
    if st == "FAIL":
        return red(raw)
    return yellow(raw)


def _rule(cols: List[int], left: str, mid: str, right: str, fill: str = "─") -> str:
    parts = [fill * (w + 2) for w in cols]
    return left + mid.join(parts) + right


def _row(vals: List[str], cols: List[int], aligns: Optional[List[str]] = None) -> str:
    cells = []
    for i, (v, w) in enumerate(zip(vals, cols)):
        align = (aligns or ["l"] * len(cols))[i]
        v = _clip(v, w)
        cells.append(v.rjust(w) if align == "r" else v.ljust(w))
    return "│ " + " │ ".join(cells) + " │"


# ── AWS: DynamoDB (Scylla Alternator) ───────────────────────────────────────

def suite_dynamodb(rep: Report, endpoint: str, n_items: int, skip_hp: str) -> None:
    ddb = boto_client("dynamodb", endpoint)
    table = PREFIX.replace("-", "_")[:255]
    state: Dict[str, object] = {}

    def create() -> str:
        ddb.create_table(
            TableName=table,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[{
                "IndexName": "GSI1",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }],
            BillingMode="PAY_PER_REQUEST",
        )
        ddb.get_waiter("table_exists").wait(TableName=table, WaiterConfig={"Delay": 1, "MaxAttempts": 30})
        return table

    def describe() -> str:
        desc = ddb.describe_table(TableName=table)["Table"]
        return f"status={desc.get('TableStatus')} gs=1"

    def list_tables() -> str:
        names = ddb.list_tables().get("TableNames", [])
        if table not in names:
            raise AssertionError(f"{table} not in ListTables ({len(names)} tables)")
        return f"count={len(names)} includes probe table"

    def put() -> str:
        ddb.put_item(
            TableName=table,
            Item={
                "PK": {"S": "CAP#ontology"},
                "SK": {"S": "ITEM#probe"},
                "GSI1PK": {"S": "TYPE#probe"},
                "GSI1SK": {"S": "ITEM#probe"},
                "payload": {"S": "hello-dynamodb"},
            },
        )
        return "item written"

    def get() -> str:
        got = ddb.get_item(TableName=table, Key={"PK": {"S": "CAP#ontology"}, "SK": {"S": "ITEM#probe"}})
        val = got.get("Item", {}).get("payload", {}).get("S")
        if val != "hello-dynamodb":
            raise AssertionError(f"got {val!r}")
        return "payload=hello-dynamodb"

    def update() -> str:
        ddb.update_item(
            TableName=table,
            Key={"PK": {"S": "CAP#ontology"}, "SK": {"S": "ITEM#probe"}},
            UpdateExpression="SET payload = :v, n = :n",
            ExpressionAttributeValues={":v": {"S": "updated"}, ":n": {"N": "1"}},
        )
        got = ddb.get_item(TableName=table, Key={"PK": {"S": "CAP#ontology"}, "SK": {"S": "ITEM#probe"}})
        if got["Item"]["payload"]["S"] != "updated":
            raise AssertionError("update not persisted")
        return "SET payload+n"

    def batch_write() -> str:
        t0 = time.perf_counter()
        written = 0
        batch: List[dict] = []
        for i in range(n_items):
            batch.append({
                "PutRequest": {
                    "Item": {
                        "PK": {"S": "CAP#load"},
                        "SK": {"S": f"ITEM#{i:04d}"},
                        "GSI1PK": {"S": "TYPE#load"},
                        "GSI1SK": {"S": f"ITEM#{i:04d}"},
                        "n": {"N": str(i)},
                    }
                }
            })
            if len(batch) == 25 or i == n_items - 1:
                ddb.batch_write_item(RequestItems={table: batch})
                written += len(batch)
                batch = []
        dt = time.perf_counter() - t0
        qps = written / dt if dt > 0 else 0
        state["qps"] = qps
        return f"{written} items in {dt:.2f}s ({qps:.0f}/s)"

    def batch_get() -> str:
        keys = [{"PK": {"S": "CAP#load"}, "SK": {"S": f"ITEM#{i:04d}"}} for i in range(min(n_items, 8))]
        resp = ddb.batch_get_item(RequestItems={table: {"Keys": keys}})
        got = resp.get("Responses", {}).get(table, [])
        if len(got) < len(keys):
            raise AssertionError(f"got {len(got)}/{len(keys)}")
        return f"{len(got)} items"

    def query_pk() -> str:
        q = ddb.query(
            TableName=table,
            KeyConditionExpression="PK = :pk",
            ExpressionAttributeValues={":pk": {"S": "CAP#load"}},
        )
        if q.get("Count", 0) < n_items:
            raise AssertionError(f"Count={q.get('Count')} expected {n_items}")
        return f"Count={q['Count']}"

    def query_gsi() -> str:
        q = ddb.query(
            TableName=table,
            IndexName="GSI1",
            KeyConditionExpression="GSI1PK = :pk",
            ExpressionAttributeValues={":pk": {"S": "TYPE#load"}},
        )
        if q.get("Count", 0) < n_items:
            raise AssertionError(f"Count={q.get('Count')} expected {n_items}")
        return f"GSI1 Count={q['Count']}"

    def scan() -> str:
        s = ddb.scan(TableName=table, Select="COUNT")
        return f"Count={s.get('Count')}"

    def delete_item() -> str:
        ddb.delete_item(TableName=table, Key={"PK": {"S": "CAP#ontology"}, "SK": {"S": "ITEM#probe"}})
        got = ddb.get_item(TableName=table, Key={"PK": {"S": "CAP#ontology"}, "SK": {"S": "ITEM#probe"}})
        if got.get("Item"):
            raise AssertionError("item still present")
        return "deleted"

    def delete_table() -> str:
        ddb.delete_table(TableName=table)
        return "dropped"

    apis = [
        ("CreateTable", create),
        ("DescribeTable", describe),
        ("ListTables", list_tables),
        ("PutItem", put),
        ("GetItem", get),
        ("UpdateItem", update),
        ("BatchWriteItem", batch_write),
        ("BatchGetItem", batch_get),
        ("Query", query_pk),
        ("Query (GSI)", query_gsi),
        ("Scan", scan),
        ("DeleteItem", delete_item),
        ("DeleteTable", delete_table),
    ]
    print(cyan(f"  ▶ DynamoDB  ({endpoint})"))
    for api, fn in apis:
        rep.run("AWS", "DynamoDB", api, fn, skip_if_missing=skip_hp)


# ── AWS: S3 (MinIO) ─────────────────────────────────────────────────────────

def suite_s3(rep: Report, endpoint: str, access: str, secret: str, n_objects: int, obj_kb: int, skip_hp: str) -> None:
    s3 = boto_client("s3", endpoint, access, secret)
    bucket = PREFIX
    payload = os.urandom(max(obj_kb, 1) * 1024)

    def create_bucket() -> str:
        s3.create_bucket(Bucket=bucket)
        return bucket

    def head_bucket() -> str:
        s3.head_bucket(Bucket=bucket)
        return "exists"

    def put_object() -> str:
        s3.put_object(Bucket=bucket, Key=f"{PREFIX}/probe.bin", Body=payload, ContentType="application/octet-stream")
        return f"{len(payload)} bytes"

    def get_object() -> str:
        body = s3.get_object(Bucket=bucket, Key=f"{PREFIX}/probe.bin")["Body"].read()
        if body != payload:
            raise AssertionError("body mismatch")
        return f"{len(body)} bytes"

    def head_object() -> str:
        h = s3.head_object(Bucket=bucket, Key=f"{PREFIX}/probe.bin")
        return f"ContentLength={h.get('ContentLength')}"

    def list_objects() -> str:
        listed = s3.list_objects_v2(Bucket=bucket, Prefix=f"{PREFIX}/")
        n = listed.get("KeyCount", 0)
        if n < 1:
            raise AssertionError("no keys")
        return f"KeyCount={n}"

    def copy_object() -> str:
        s3.copy_object(
            Bucket=bucket,
            Key=f"{PREFIX}/probe-copy.bin",
            CopySource={"Bucket": bucket, "Key": f"{PREFIX}/probe.bin"},
        )
        return "probe-copy.bin"

    def load() -> str:
        t0 = time.perf_counter()

        def _put(i: int) -> None:
            s3.put_object(Bucket=bucket, Key=f"{PREFIX}/load/{i:04d}.dat", Body=payload)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(_put, range(n_objects)))
        dt = time.perf_counter() - t0
        mib = (n_objects * obj_kb / 1024) / dt if dt > 0 else 0
        listed = s3.list_objects_v2(Bucket=bucket, Prefix=f"{PREFIX}/load/", MaxKeys=1000)
        if listed.get("KeyCount", 0) < n_objects:
            raise AssertionError(f"listed {listed.get('KeyCount')} < {n_objects}")
        return f"{n_objects}×{obj_kb}KiB in {dt:.2f}s ({mib:.1f} MiB/s)"

    def delete_object() -> str:
        keys = [o["Key"] for o in s3.list_objects_v2(Bucket=bucket).get("Contents") or []]
        for k in keys:
            s3.delete_object(Bucket=bucket, Key=k)
        return f"deleted {len(keys)} keys"

    def delete_bucket() -> str:
        s3.delete_bucket(Bucket=bucket)
        return "dropped"

    print(cyan(f"  ▶ S3 / MinIO  ({endpoint})"))
    for api, fn in [
        ("CreateBucket", create_bucket),
        ("HeadBucket", head_bucket),
        ("PutObject", put_object),
        ("GetObject", get_object),
        ("HeadObject", head_object),
        ("ListObjectsV2", list_objects),
        ("CopyObject", copy_object),
        ("PutObject (load)", load),
        ("DeleteObject", delete_object),
        ("DeleteBucket", delete_bucket),
    ]:
        rep.run("AWS", "S3", api, fn, skip_if_missing=skip_hp)


# ── AWS: SSM / Secrets / STS / Glue / Athena via MiniStack ──────────────────

def suite_ssm(rep: Report, endpoint: str, skip_hp: str) -> None:
    ssm = boto_client("ssm", endpoint)
    p1 = f"/{PREFIX}/app/endpoint"
    p2 = f"/{PREFIX}/app/token"

    def put() -> str:
        ssm.put_parameter(Name=p1, Value="https://example.local", Type="String", Overwrite=True)
        ssm.put_parameter(Name=p2, Value="secret-token", Type="SecureString", Overwrite=True)
        return "2 parameters"

    def get() -> str:
        v = ssm.get_parameter(Name=p1, WithDecryption=True)["Parameter"]["Value"]
        if v != "https://example.local":
            raise AssertionError(v)
        return v

    def get_many() -> str:
        r = ssm.get_parameters(Names=[p1, p2], WithDecryption=True)
        n = len(r.get("Parameters") or [])
        if n < 2:
            raise AssertionError(f"got {n} Invalid={r.get('InvalidParameters')}")
        return f"{n} parameters"

    def by_path() -> str:
        r = ssm.get_parameters_by_path(Path=f"/{PREFIX}/app", Recursive=True, WithDecryption=True)
        n = len(r.get("Parameters") or [])
        if n < 2:
            raise AssertionError(f"got {n}")
        return f"{n} under /{PREFIX}/app"

    def describe() -> str:
        r = ssm.describe_parameters(
            ParameterFilters=[{"Key": "Name", "Option": "BeginsWith", "Values": [f"/{PREFIX}"]}]
        )
        n = len(r.get("Parameters") or [])
        return f"{n} described"

    def delete() -> str:
        ssm.delete_parameter(Name=p1)
        ssm.delete_parameter(Name=p2)
        return "deleted 2"

    print(cyan(f"  ▶ SSM  ({endpoint})"))
    for api, fn in [
        ("PutParameter", put),
        ("GetParameter", get),
        ("GetParameters", get_many),
        ("GetParametersByPath", by_path),
        ("DescribeParameters", describe),
        ("DeleteParameter", delete),
    ]:
        rep.run("AWS", "SSM", api, fn, skip_if_missing=skip_hp)


def suite_secrets(rep: Report, endpoint: str, skip_hp: str) -> None:
    sm = boto_client("secretsmanager", endpoint)
    name = f"{PREFIX}/db-credentials"
    arn: Dict[str, str] = {}

    def create() -> str:
        r = sm.create_secret(Name=name, SecretString=json.dumps({"user": "nexus", "pass": "nexus"}))
        arn["arn"] = r.get("ARN") or name
        return r.get("Name") or name

    def describe() -> str:
        d = sm.describe_secret(SecretId=name)
        return d.get("Name") or name

    def get() -> str:
        raw = sm.get_secret_value(SecretId=name)["SecretString"]
        data = json.loads(raw)
        if data.get("user") != "nexus":
            raise AssertionError(raw[:80])
        return "json user=nexus"

    def put() -> str:
        sm.put_secret_value(SecretId=name, SecretString=json.dumps({"user": "nexus", "pass": "rotated"}))
        raw = json.loads(sm.get_secret_value(SecretId=name)["SecretString"])
        if raw.get("pass") != "rotated":
            raise AssertionError("rotation not persisted")
        return "rotated"

    def list_secrets() -> str:
        r = sm.list_secrets()
        names = [s.get("Name") for s in r.get("SecretList") or []]
        if name not in names:
            raise AssertionError(f"probe secret missing ({len(names)} listed)")
        return f"{len(names)} secrets"

    def delete() -> str:
        sm.delete_secret(SecretId=name, ForceDeleteWithoutRecovery=True)
        return "force-deleted"

    print(cyan(f"  ▶ Secrets Manager  ({endpoint})"))
    for api, fn in [
        ("CreateSecret", create),
        ("DescribeSecret", describe),
        ("GetSecretValue", get),
        ("PutSecretValue", put),
        ("ListSecrets", list_secrets),
        ("DeleteSecret", delete),
    ]:
        rep.run("AWS", "Secrets Manager", api, fn, skip_if_missing=skip_hp)


def suite_sts(rep: Report, endpoint: str, skip_hp: str) -> None:
    sts = boto_client("sts", endpoint)

    def ident() -> str:
        r = sts.get_caller_identity()
        return f"Account={r.get('Account')} Arn={r.get('Arn', '')[-40:]}"

    print(cyan("  ▶ STS"))
    rep.run("AWS", "STS", "GetCallerIdentity", ident, skip_if_missing=skip_hp)


def suite_glue_athena(rep: Report, ms_ep: str, minio_ep: str, access: str, secret: str, skip_hp: str) -> None:
    glue = boto_client("glue", ms_ep)
    athena = boto_client("athena", ms_ep)
    s3_ms = boto_client("s3", ms_ep, access, secret)
    db = f"verify_{RUN_ID}".replace("-", "_")
    tbl = "smoke"
    bucket = f"{PREFIX}-athena"
    output = f"s3://{bucket}/results/"
    qid: Dict[str, str] = {}

    def create_db() -> str:
        glue.create_database(DatabaseInput={"Name": db, "Description": "nexus-verify"})
        return db

    def get_db() -> str:
        r = glue.get_database(Name=db)
        return r["Database"]["Name"]

    def ensure_bucket() -> str:
        try:
            s3_ms.head_bucket(Bucket=bucket)
        except Exception:
            s3_ms.create_bucket(Bucket=bucket)
        return bucket

    def create_table() -> str:
        glue.create_table(
            DatabaseName=db,
            TableInput={
                "Name": tbl,
                "TableType": "EXTERNAL_TABLE",
                "StorageDescriptor": {
                    "Columns": [{"Name": "ok", "Type": "int"}],
                    "Location": f"s3://{bucket}/tables/{tbl}/",
                    "InputFormat": "org.apache.hadoop.mapred.TextInputFormat",
                    "OutputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
                    "SerdeInfo": {
                        "SerializationLibrary": "org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe",
                        "Parameters": {"field.delim": ","},
                    },
                },
            },
        )
        return tbl

    def get_table() -> str:
        r = glue.get_table(DatabaseName=db, Name=tbl)
        return r["Table"]["Name"]

    def get_tables() -> str:
        r = glue.get_tables(DatabaseName=db)
        n = len(r.get("TableList") or [])
        return f"{n} tables"

    def start_q() -> str:
        r = athena.start_query_execution(
            QueryString="SELECT 1 AS ok",
            QueryExecutionContext={"Database": db},
            ResultConfiguration={"OutputLocation": output},
        )
        qid["id"] = r["QueryExecutionId"]
        return qid["id"][:16]

    def get_exec() -> str:
        if "id" not in qid:
            raise Skip("no QueryExecutionId")
        state = "RUNNING"
        reason = ""
        for i in range(20):
            r = athena.get_query_execution(QueryExecutionId=qid["id"])
            st = r["QueryExecution"]["Status"]
            state = st["State"]
            reason = st.get("StateChangeReason", "")
            if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
                break
            if i in (0, 4, 9, 14):
                print(dim(f"      … Athena state={state} ({i + 1}s)"), flush=True)
            time.sleep(1)
        if state != "SUCCEEDED":
            raise AssertionError(f"{state} {reason}".strip() or "did not succeed within 20s")
        return state

    def get_results() -> str:
        if "id" not in qid:
            raise Skip("no QueryExecutionId")
        r = athena.get_query_results(QueryExecutionId=qid["id"], MaxResults=10)
        rows = r.get("ResultSet", {}).get("Rows") or []
        if len(rows) < 2:
            raise AssertionError(f"rows={len(rows)} (want header+data)")
        return f"rows={len(rows)}"

    def list_q() -> str:
        r = athena.list_query_executions()
        ids = r.get("QueryExecutionIds") or []
        return f"{len(ids)} executions"

    def drop_table() -> str:
        glue.delete_table(DatabaseName=db, Name=tbl)
        return "dropped"

    def drop_db() -> str:
        glue.delete_database(Name=db)
        return "dropped"

    print(cyan(f"  ▶ Glue / Athena  ({ms_ep})"))
    glue_apis = [
        ("CreateDatabase", create_db),
        ("GetDatabase", get_db),
        ("S3 CreateBucket (results)", ensure_bucket),
        ("CreateTable", create_table),
        ("GetTable", get_table),
        ("GetTables", get_tables),
    ]
    for api, fn in glue_apis:
        svc = "S3" if api.startswith("S3") else "Glue"
        rep.run("AWS", svc if svc == "S3" else "Glue", api.replace("S3 ", ""), fn, skip_if_missing=skip_hp)

    for api, fn in [
        ("StartQueryExecution", start_q),
        ("GetQueryExecution", get_exec),
        ("GetQueryResults", get_results),
        ("ListQueryExecutions", list_q),
    ]:
        rep.run("AWS", "Athena", api, fn, skip_if_missing=skip_hp)

    for api, fn in [("DeleteTable", drop_table), ("DeleteDatabase", drop_db)]:
        rep.run("AWS", "Glue", api, fn, skip_if_missing=skip_hp)


# ── Data plane ──────────────────────────────────────────────────────────────

def suite_trino(rep: Report, host: str, port: int, n_rows: int, skip_hp: str) -> None:
    print(cyan(f"  ▶ Trino  ({host}:{port})"))

    def run() -> str:
        from trino.dbapi import connect

        conn = connect(host=host, port=port, user="nexus-verify", catalog="memory", schema="default")
        cur = conn.cursor()
        cur.execute("SELECT node_version FROM system.runtime.nodes LIMIT 1")
        version = cur.fetchone()[0]
        schema = f"verify_{RUN_ID}"
        table = f"{schema}.items"
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS memory.{schema}")
        cur.execute(f"CREATE TABLE memory.{table} (id bigint, name varchar, n bigint)")
        values = ", ".join(f"({i}, 'row-{i}', {i * 10})" for i in range(n_rows))
        cur.execute(f"INSERT INTO memory.{table} (id, name, n) VALUES {values}")
        cur.execute(f"SELECT count(*) FROM memory.{table}")
        count = int(cur.fetchone()[0])
        if count != n_rows:
            raise AssertionError(f"count {count} != {n_rows}")
        cur.execute(f"DROP TABLE memory.{table}")
        cur.execute(f"DROP SCHEMA memory.{schema}")
        cur.close()
        conn.close()
        return f"trino {version}; {n_rows} rows"

    rep.run("DATA", "Trino", "CREATE/INSERT/SELECT", run, skip_if_missing=skip_hp)


def suite_redis(rep: Report, host: str, port: int, n_keys: int, skip_hp: str) -> None:
    print(cyan(f"  ▶ Redis  ({host}:{port})"))
    r = None

    def ping() -> str:
        nonlocal r
        import redis

        r = redis.Redis(host=host, port=port, decode_responses=True, socket_timeout=10)
        if r.ping() is not True:
            raise AssertionError("PING failed")
        return "PONG"

    def kv() -> str:
        r.set(f"{PREFIX}:k", "v", ex=120)
        if r.get(f"{PREFIX}:k") != "v":
            raise AssertionError("GET mismatch")
        return "SET/GET"

    def incr() -> str:
        n = r.incr(f"{PREFIX}:n")
        return f"INCR={n}"

    def hash_list() -> str:
        r.hset(f"{PREFIX}:h", mapping={"a": "1"})
        r.lpush(f"{PREFIX}:l", "x", "y")
        return f"HGET={r.hget(f'{PREFIX}:h', 'a')} LLEN={r.llen(f'{PREFIX}:l')}"

    def pipeline() -> str:
        pipe = r.pipeline(transaction=False)
        t0 = time.perf_counter()
        for i in range(n_keys):
            pipe.set(f"{PREFIX}:p:{i}", f"v{i}", ex=120)
        pipe.execute()
        pipe = r.pipeline(transaction=False)
        for i in range(n_keys):
            pipe.get(f"{PREFIX}:p:{i}")
        vals = pipe.execute()
        dt = time.perf_counter() - t0
        if vals[0] != "v0" or vals[-1] != f"v{n_keys - 1}":
            raise AssertionError("pipeline mismatch")
        r.delete(*([f"{PREFIX}:k", f"{PREFIX}:n", f"{PREFIX}:h", f"{PREFIX}:l"] + [f"{PREFIX}:p:{i}" for i in range(n_keys)]))
        qps = (n_keys * 2) / dt if dt > 0 else 0
        return f"{n_keys} set+get in {dt:.2f}s ({qps:.0f} ops/s)"

    for api, fn in [("PING", ping), ("SET/GET", kv), ("INCR", incr), ("HSET/LPUSH", hash_list), ("Pipeline load", pipeline)]:
        rep.run("DATA", "Redis", api, fn, skip_if_missing=skip_hp)


def suite_postgres(rep: Report, host: str, port: int, user: str, password: str, database: str, n_rows: int, age_graph: str, skip_age: bool, skip_hp: str) -> None:
    print(cyan(f"  ▶ Postgres  ({host}:{port}/{database})"))

    def connect_info() -> str:
        import psycopg2

        conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname=database, connect_timeout=10)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT version()")
        ver = cur.fetchone()[0].split(",")[0]
        cur.close()
        conn.close()
        return ver

    def crud() -> str:
        import psycopg2

        conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname=database, connect_timeout=10)
        conn.autocommit = True
        cur = conn.cursor()
        table = f"nexus_verify_{RUN_ID}"
        cur.execute(f"CREATE TABLE {table} (id SERIAL PRIMARY KEY, name TEXT, payload JSONB DEFAULT '{{}}')")
        cur.execute(f"INSERT INTO {table} (name, payload) VALUES (%s, %s::jsonb)", ("probe", json.dumps({"ok": True})))
        rows = [(f"r{i}", json.dumps({"i": i})) for i in range(n_rows)]
        t0 = time.perf_counter()
        cur.executemany(f"INSERT INTO {table} (name, payload) VALUES (%s, %s::jsonb)", rows)
        dt = time.perf_counter() - t0
        cur.execute(f"SELECT count(*) FROM {table}")
        c = cur.fetchone()[0]
        cur.execute(f"DROP TABLE {table}")
        cur.close()
        conn.close()
        return f"{c} rows in {dt:.2f}s"

    def pgvector() -> str:
        import psycopg2

        conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname=database, connect_timeout=10)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ver = cur.fetchone()
        if not ver:
            raise AssertionError("vector extension missing")
        table = f"nexus_verify_vec_{RUN_ID}"
        cur.execute(f"CREATE TABLE {table} (id int PRIMARY KEY, embedding vector(8))")
        n = min(n_rows, 32)
        for i in range(n):
            v = "[" + ",".join(str(float((i + j) % 10)) for j in range(8)) + "]"
            cur.execute(f"INSERT INTO {table} (id, embedding) VALUES (%s, %s::vector)", (i, v))
        probe = "[" + ",".join("0" for _ in range(8)) + "]"
        cur.execute(f"SELECT id FROM {table} ORDER BY embedding <-> %s::vector LIMIT 3", (probe,))
        nearest = [row[0] for row in cur.fetchall()]
        cur.execute(f"DROP TABLE {table}")
        cur.close()
        conn.close()
        return f"vector {ver[0]}; knn={nearest}"

    for api, fn in [
        ("Connect / version", connect_info),
        ("INSERT/SELECT/JSONB", crud),
        ("pgvector kNN", pgvector),
    ]:
        rep.run("DATA", "Postgres", api, fn, skip_if_missing=skip_hp)

    suite_age(rep, host, port, user, password, database, age_graph, skip_age, skip_hp)


def suite_age(
    rep: Report,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    graph: str,
    skip_age: bool,
    skip_hp: str,
) -> None:
    """Exercise GraphStore paths: catalog, MERGE store, hop query, display JSON."""
    print(cyan(f"  ▶ GraphStore / AGE  ({graph})"))

    prefix = f"verify_{RUN_ID}"
    policy = f"{prefix}:policy"
    workflow = f"{prefix}:workflow"
    mapping = f"{prefix}:mapping"
    system = f"{prefix}:system"
    node_ids = (policy, workflow, mapping, system)

    def _ag_str(val: object) -> str:
        text = str(val).strip()
        if text.startswith('"') and text.endswith('"'):
            return text[1:-1]
        return text

    def _open():
        import psycopg2

        if skip_age:
            raise Skip("--skip-age")
        conn = psycopg2.connect(
            host=host, port=port, user=user, password=password, dbname=database, connect_timeout=10
        )
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM pg_available_extensions WHERE name = 'age'")
        if int(cur.fetchone()[0]) == 0:
            cur.close()
            conn.close()
            raise AssertionError("Apache AGE is not in this Postgres image (expected nexus-sre-postgres)")
        cur.execute("CREATE EXTENSION IF NOT EXISTS age")
        cur.execute("LOAD 'age'")
        cur.execute("SET search_path = ag_catalog, public")
        return conn, cur

    def _cypher(cur, stmt: str, cols: List[str]) -> list:
        aliases = ", ".join(f"{c} agtype" for c in cols)
        cur.execute(f"SELECT * FROM cypher(%s, $$ {stmt} $$) AS ({aliases})", (graph,))
        return cur.fetchall()

    def _purge(cur) -> None:
        for oid in node_ids:
            _cypher(cur, f"MATCH (n:Entity {{onto_id: '{oid}'}}) DETACH DELETE n RETURN count(n)", ["c"])

    def graphs() -> str:
        conn, cur = _open()
        try:
            cur.execute("SELECT name FROM ag_catalog.ag_graph ORDER BY name")
            names = [row[0] for row in cur.fetchall()]
            if graph not in names:
                cur.execute("SELECT create_graph(%s)", (graph,))
                names.append(graph)
            rows = _cypher(cur, "MATCH (n) RETURN count(n)", ["cnt"])
            total = _ag_str(rows[0][0]) if rows else "0"
            return f"graphs={names} active={graph} nodes={total}"
        finally:
            cur.close()
            conn.close()

    def store() -> str:
        # Same MERGE shape as graph_loader._load_age + GraphStore Entity/onto_id.
        conn, cur = _open()
        try:
            _purge(cur)
            specs = [
                (policy, "policy", "Salesforce", "high"),
                (workflow, "workflow", "Salesforce", "medium"),
                (mapping, "mapping", "Oracle", "low"),
                (system, "system", "Oracle", "low"),
            ]
            for oid, kind, sysname, risk in specs:
                _cypher(
                    cur,
                    f"MERGE (n:Entity {{onto_id: '{oid}'}}) "
                    f"SET n.kind = '{kind}', n.system = '{sysname}', n.risk_level = '{risk}' "
                    f"RETURN n.onto_id",
                    ["id"],
                )
            rels = [
                (policy, "CONSTRAINED_BY", workflow),
                (workflow, "DEPENDS_ON", system),
                (policy, "IMPLEMENTS", mapping),
                (mapping, "SYNCS_TO", system),
            ]
            for src, rel, tgt in rels:
                _cypher(
                    cur,
                    f"MATCH (a:Entity {{onto_id: '{src}'}}), (b:Entity {{onto_id: '{tgt}'}}) "
                    f"MERGE (a)-[r:{rel}]->(b) RETURN type(r)",
                    ["t"],
                )
            n_rows = _cypher(
                cur,
                f"MATCH (n:Entity) WHERE n.onto_id IN "
                f"['{policy}','{workflow}','{mapping}','{system}'] RETURN count(n)",
                ["c"],
            )
            e_rows = _cypher(
                cur,
                f"MATCH (a:Entity)-[r]->(b:Entity) WHERE a.onto_id IN "
                f"['{policy}','{workflow}','{mapping}','{system}'] RETURN count(r)",
                ["c"],
            )
            n_count = int(_ag_str(n_rows[0][0]))
            e_count = int(_ag_str(e_rows[0][0]))
            if n_count != 4 or e_count != 4:
                raise AssertionError(f"stored nodes={n_count} edges={e_count} (want 4/4)")
            return f"MERGE 4 Entity + 4 edges on {graph}"
        finally:
            cur.close()
            conn.close()

    def query() -> str:
        # Same Cypher GraphStore._expand_age uses for hop=1 and hop=2.
        conn, cur = _open()
        try:
            hop1 = _cypher(
                cur,
                f"MATCH (a:Entity {{onto_id: '{policy}'}})-[r]->(b:Entity) "
                f"RETURN DISTINCT b.onto_id AS neighbor, type(r) AS rel_type",
                ["neighbor", "rel_type"],
            )
            hop1_ids = {_ag_str(r[0]) for r in hop1}
            hop1_rels = {_ag_str(r[1]) for r in hop1}
            if hop1_ids != {workflow, mapping}:
                raise AssertionError(f"1-hop neighbors={hop1_ids} rels={hop1_rels}")
            if "CONSTRAINED_BY" not in hop1_rels or "IMPLEMENTS" not in hop1_rels:
                raise AssertionError(f"1-hop rels={hop1_rels}")
            hop2 = _cypher(
                cur,
                f"MATCH (a:Entity {{onto_id: '{policy}'}})-[]->(mid)-[r2]->(b:Entity) "
                f"WHERE a <> b "
                f"RETURN DISTINCT b.onto_id AS neighbor, type(r2) AS rel_type",
                ["neighbor", "rel_type"],
            )
            hop2_ids = {_ag_str(r[0]) for r in hop2}
            if system not in hop2_ids:
                raise AssertionError(f"2-hop neighbors={hop2_ids} (missing {system})")
            return f"1-hop={sorted(hop1_rels)} 2-hop includes system"
        finally:
            cur.close()
            conn.close()

    def display() -> str:
        # Payload shape of GraphStore.get_subgraph / GET /graph/{onto_id} for KnowledgeGraphView.
        conn, cur = _open()
        try:
            out_rows = _cypher(
                cur,
                f"MATCH (a:Entity {{onto_id: '{policy}'}})-[r]->(b:Entity) "
                f"RETURN a.onto_id, type(r), b.onto_id",
                ["src", "rel", "tgt"],
            )
            in_rows = _cypher(
                cur,
                f"MATCH (a:Entity)-[r]->(b:Entity {{onto_id: '{policy}'}}) "
                f"RETURN a.onto_id, type(r), b.onto_id",
                ["src", "rel", "tgt"],
            )
            edges = []
            seen = set()
            nodes = {policy}
            for src, rel, tgt in list(out_rows) + list(in_rows):
                edge = {
                    "source": _ag_str(src),
                    "target": _ag_str(tgt),
                    "type": _ag_str(rel),
                    "description": "",
                }
                key = (edge["source"], edge["type"], edge["target"])
                if key in seen:
                    continue
                seen.add(key)
                edges.append(edge)
                nodes.add(edge["source"])
                nodes.add(edge["target"])
            payload = {
                "center": policy,
                "hops": 1,
                "nodes": [{"id": n} for n in sorted(nodes)],
                "edges": edges,
                "neighbor_count": len(nodes) - 1,
            }
            if len(payload["nodes"]) < 3:
                raise AssertionError(f"display nodes={payload['nodes']}")
            if len(payload["edges"]) < 2:
                raise AssertionError(f"display edges={payload['edges']}")
            types = {e["type"] for e in payload["edges"]}
            if not {"CONSTRAINED_BY", "IMPLEMENTS"} <= types:
                raise AssertionError(f"display edge types={types}")
            _purge(cur)
            return (
                f"center={policy.split(':')[-1]} nodes={len(payload['nodes'])} "
                f"edges={len(payload['edges'])} types={sorted(types)}"
            )
        finally:
            cur.close()
            conn.close()

    for api, fn in [
        ("Graphs catalog", graphs),
        ("Store MERGE nodes/edges", store),
        ("Query 1/2-hop expand", query),
        ("Display subgraph JSON", display),
    ]:
        rep.run("DATA", "GraphStore", api, fn, skip_if_missing=skip_hp)


def suite_mimir(rep: Report, base: str, skip_hp: str) -> None:
    print(cyan(f"  ▶ Mimir  ({base})"))

    def ready() -> str:
        return http_get(f"{base.rstrip('/')}/ready").strip() or "ok"

    def query() -> str:
        q = http_get(
            f"{base.rstrip('/')}/prometheus/api/v1/query?query=up",
            headers={"X-Scope-OrgID": "anonymous"},
        )
        return f"status={json.loads(q).get('status')}"

    def remote_write() -> str:
        ts_ms = int(time.time() * 1000)
        metric = "nexus_verify_up"

        def varint(n: int) -> bytes:
            out = bytearray()
            while True:
                b = n & 0x7F
                n >>= 7
                if n:
                    out.append(b | 0x80)
                else:
                    out.append(b)
                    return bytes(out)

        def tag(field: int, wire: int) -> bytes:
            return varint((field << 3) | wire)

        def ld(field: int, payload: bytes) -> bytes:
            return tag(field, 2) + varint(len(payload)) + payload

        def str_f(field: int, s: str) -> bytes:
            return ld(field, s.encode())

        # Sample: double value = 1 (fixed64); int64 timestamp = 2 (varint), same as mimir_client.py
        sample = tag(1, 1) + struct.pack("<d", 1.0) + tag(2, 0) + varint(ts_ms)
        series = ld(1, str_f(1, "__name__") + str_f(2, metric)) + ld(2, sample)
        payload = ld(1, series)

        compressed = None
        try:
            import cramjam  # type: ignore

            raw = getattr(cramjam.snappy, "compress_raw", None)
            if raw is None:
                raise Skip("cramjam.snappy.compress_raw missing")
            compressed = bytes(raw(payload))
        except Skip:
            raise
        except Exception:
            try:
                import snappy  # type: ignore

                compressed = snappy.compress(payload)
            except Exception as exc:
                raise Skip(f"no snappy block codec ({exc})") from exc

        http_post(
            f"{base.rstrip('/')}/api/v1/push",
            compressed,
            headers={
                "X-Scope-OrgID": "anonymous",
                "Content-Type": "application/x-protobuf",
                "Content-Encoding": "snappy",
                "X-Prometheus-Remote-Write-Version": "0.1.0",
            },
        )

        # Round-trip: ingester should serve the sample immediately.
        qurl = f"{base.rstrip('/')}/prometheus/api/v1/query?query={metric}"
        last = ""
        for _ in range(8):
            raw = http_get(qurl, headers={"X-Scope-OrgID": "anonymous"})
            last = raw[:160]
            data = json.loads(raw)
            results = (data.get("data") or {}).get("result") or []
            if results:
                val = results[0].get("value", [None, None])[1]
                return f"pushed+queried {metric}={val}"
            time.sleep(0.25)
        raise AssertionError(f"write 204/2xx but query empty: {last}")

    for api, fn in [("/ready", ready), ("PromQL query", query), ("Remote write", remote_write)]:
        rep.run("DATA", "Mimir", api, fn, skip_if_missing=skip_hp)


# ── Report printer ──────────────────────────────────────────────────────────

def print_report(rep: Report, meta: Dict[str, str]) -> int:
    p, f, s = rep.counts()
    overall = "PASS" if f == 0 else "FAIL"
    overall_s = green(bold("PASS")) if f == 0 else red(bold("FAIL"))

    width = 94
    print("")
    print("╔" + "═" * width + "╗")
    title = "NEXUS LOCAL STACK VERIFICATION REPORT"
    print("║ " + bold(title.ljust(width - 1)) + "║")
    sub = f"run={meta['run']}   {meta['when']}   load_items={meta['load']}"
    print("║ " + dim(sub.ljust(width - 1)) + "║")
    print("╚" + "═" * width + "╝")

    print("")
    print(bold("ENDPOINTS"))
    for k, v in meta["endpoints"]:
        print(f"  {k:<16} {v}")

    # Summary by service
    print("")
    print(bold("SUMMARY BY SERVICE"))
    cols = [18, 6, 6, 6, 10, 8]
    print(_rule(cols, "┌", "┬", "┐"))
    print(_row(["Service", "Pass", "Fail", "Skip", "Time", "Result"], cols, ["l", "r", "r", "r", "r", "l"]))
    print(_rule(cols, "├", "┼", "┤"))
    by_svc: Dict[str, List[Check]] = {}
    for c in rep.checks:
        by_svc.setdefault(c.service, []).append(c)
    for svc, items in by_svc.items():
        sp, sf, ss = rep.counts(items)
        ms = sum(c.elapsed_ms for c in items)
        result = "FAIL" if sf else ("SKIP" if sp == 0 and ss else "PASS")
        print(_row(
            [svc, str(sp), str(sf), str(ss), f"{ms} ms", result],
            cols,
            ["l", "r", "r", "r", "r", "l"],
        ).replace(f" {result} ", f" {_status_cell(result)} "))
    print(_rule(cols, "└", "┴", "┘"))

    def print_api_table(title: str, items: List[Check]) -> None:
        print("")
        print(bold(title))
        cols2 = [18, 28, 6, 8, 26]
        print(_rule(cols2, "┌", "┬", "┐"))
        print(_row(["Service", "API", "Status", "Latency", "Detail"], cols2, ["l", "l", "l", "r", "l"]))
        print(_rule(cols2, "├", "┼", "┤"))
        last = None
        for c in items:
            svc = c.service if c.service != last else ""
            last = c.service
            line = _row(
                [svc, c.api, c.status, f"{c.elapsed_ms} ms", c.detail],
                cols2,
                ["l", "l", "l", "r", "l"],
            )
            line = line.replace(f" {c.status:6} ", f" {_status_cell(c.status)} ", 1)
            print(line)
        print(_rule(cols2, "└", "┴", "┘"))

    aws = [c for c in rep.checks if c.category == "AWS"]
    data = [c for c in rep.checks if c.category == "DATA"]
    print_api_table("AWS API MATRIX  (DynamoDB · S3 · SSM · Secrets · Athena · Glue · STS)", aws)
    print_api_table("DATA PLANE  (Redis · Postgres · pgvector · GraphStore/AGE · Trino · Mimir)", data)

    fails = [c for c in rep.checks if not c.ok]
    skips = [c for c in rep.checks if c.skipped]
    if fails:
        print("")
        print(bold(red("FAILURES")))
        for c in fails:
            print(f"  • {c.service:18} {c.api:28} {c.detail}")
    if skips:
        print("")
        print(bold(yellow("SKIPPED")))
        for c in skips:
            print(f"  • {c.service:18} {c.api:28} {c.detail}")

    print("")
    print("─" * (width + 2))
    print(
        f"  TOTAL  {green(str(p) + ' passed')}   "
        f"{red(str(f) + ' failed') if f else dim(str(f) + ' failed')}   "
        f"{yellow(str(s) + ' skipped')}   "
        f"APIs={len(rep.checks)}   OVERALL {overall_s}"
    )
    print("─" * (width + 2))
    print("", flush=True)
    sys.stdout.flush()
    return 0 if f == 0 else 1


# ── main ────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Comprehensive nexus-local stack + AWS API verification")
    p.add_argument("--namespace", default=os.environ.get("NAMESPACE", "nexus-local"))
    p.add_argument("--load-items", type=int, default=40)
    p.add_argument("--minio-object-kb", type=int, default=32)
    p.add_argument("--minio-endpoint", default="")
    p.add_argument("--scylla-endpoint", default="")
    p.add_argument("--trino-host", default="")
    p.add_argument("--trino-port", type=int, default=8080)
    p.add_argument("--redis-host", default="")
    p.add_argument("--redis-port", type=int, default=6379)
    p.add_argument("--pg-host", default="")
    p.add_argument("--pg-port", type=int, default=5432)
    p.add_argument("--pg-user", default="nexus")
    p.add_argument("--pg-password", default="nexus")
    p.add_argument("--pg-database", default="ontology_cp")
    p.add_argument("--age-graph", default="enterprise_onto")
    p.add_argument("--ministack-endpoint", default="")
    p.add_argument("--mimir-url", default="")
    p.add_argument("--minio-access-key", default="minioadmin")
    p.add_argument("--minio-secret-key", default="minioadmin")
    p.add_argument("--skip-age", action="store_true")
    p.add_argument("--skip-mimir", action="store_true")
    p.add_argument("--skip-athena", action="store_true")
    p.add_argument("--skip-ministack", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    ns = args.namespace
    n = args.load_items
    minio_ep = args.minio_endpoint or f"http://minio-svc.{ns}.svc.cluster.local:9000"
    scylla_ep = args.scylla_endpoint or f"http://scylla-svc.{ns}.svc.cluster.local:8000"
    trino_host = args.trino_host or f"trino-svc.{ns}.svc.cluster.local"
    redis_host = args.redis_host or f"redis-svc.{ns}.svc.cluster.local"
    pg_host = args.pg_host or f"pgvector-svc.{ns}.svc.cluster.local"
    ms_ep = args.ministack_endpoint or f"http://ministack-svc.{ns}.svc.cluster.local:4566"
    mimir_url = args.mimir_url or f"http://mimir-svc.{ns}.svc.cluster.local:8080"

    when = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    print(bold("Running verification suites…"))
    print(dim(f"  run={RUN_ID}  load_items={n}  {when}"))
    print("")

    rep = Report()
    suite_dynamodb(rep, scylla_ep, n, host_port(scylla_ep, "8000"))
    suite_s3(rep, minio_ep, args.minio_access_key, args.minio_secret_key, n, args.minio_object_kb, host_port(minio_ep, "9000"))
    if not args.skip_ministack:
        suite_sts(rep, ms_ep, host_port(ms_ep, "4566"))
        suite_ssm(rep, ms_ep, host_port(ms_ep, "4566"))
        suite_secrets(rep, ms_ep, host_port(ms_ep, "4566"))
        if not args.skip_athena:
            suite_glue_athena(rep, ms_ep, minio_ep, args.minio_access_key, args.minio_secret_key, host_port(ms_ep, "4566"))
    suite_trino(rep, trino_host, args.trino_port, n, f"{trino_host}:{args.trino_port}")
    suite_redis(rep, redis_host, args.redis_port, max(n * 5, 200), f"{redis_host}:{args.redis_port}")
    suite_postgres(
        rep, pg_host, args.pg_port, args.pg_user, args.pg_password, args.pg_database,
        n, args.age_graph, args.skip_age, f"{pg_host}:{args.pg_port}",
    )
    if not args.skip_mimir:
        suite_mimir(rep, mimir_url, host_port(mimir_url, "8080"))

    return print_report(rep, {
        "run": RUN_ID,
        "when": when,
        "load": str(n),
        "endpoints": [
            ("DynamoDB", scylla_ep + "  (Scylla Alternator)"),
            ("S3", minio_ep + "  (MinIO)"),
            ("MiniStack", ms_ep + "  (SSM / Secrets / Athena / Glue / STS)"),
            ("Trino", f"{trino_host}:{args.trino_port}"),
            ("Redis", f"{redis_host}:{args.redis_port}"),
            ("Postgres", f"{pg_host}:{args.pg_port}/{args.pg_database}"),
            ("Mimir", mimir_url),
        ],
    })


if __name__ == "__main__":
    sys.exit(main())

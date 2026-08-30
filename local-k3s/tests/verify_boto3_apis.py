#!/usr/bin/env python3
"""Verify local K3s boto3 AWS APIs (DynamoDB / Athena / Glue / S3 / STS).

Mirrors nexus-ontology and nexus-ai localEmulation:
  DynamoDB -> Scylla Alternator
  Athena/Glue/STS -> MiniStack
  S3 (Athena results) -> MiniStack + MinIO

Functional checks plus concurrent stress, a 1-minute endurance run,
and a tabulated AWS API usage report (call counts + latency).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_SCRIPTS = _SCRIPT_DIR.parents[1] / "kube-operator" / "scripts"
_INIT_DIR = _SCRIPT_DIR if (_SCRIPT_DIR / "local_init_aws.py").exists() else _REPO_SCRIPTS
sys.path.insert(0, str(_INIT_DIR))
from local_init_aws import CAPABILITY_TABLES, LocalNaming, TABLE_SCHEMAS  # noqa: E402

RUN_ID = uuid.uuid4().hex[:8]

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


def _clip(text: str, width: int) -> str:
    text = " ".join(str(text).split())
    if len(text) <= width:
        return text
    return text[: max(0, width - 1)] + "…"


def _rule(cols: List[int], left: str, mid: str, right: str, fill: str = "─") -> str:
    return left + mid.join(fill * (w + 2) for w in cols) + right


def _row(vals: List[str], cols: List[int], aligns: Optional[List[str]] = None) -> str:
    cells = []
    for i, (v, w) in enumerate(zip(vals, cols)):
        align = (aligns or ["l"] * len(cols))[i]
        v = _clip(v, w)
        cells.append(v.rjust(w) if align == "r" else v.ljust(w))
    return "│ " + " │ ".join(cells) + " │"


def _status_cell(st: str) -> str:
    raw = f"{st:^6}"
    if st == "PASS":
        return green(raw)
    if st == "FAIL":
        return red(raw)
    return yellow(raw)


# ── tracking ────────────────────────────────────────────────────────────────


@dataclass
class Check:
    category: str
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
            f"    {tag_s}  {check.service:<12} {check.api:<36} {check.elapsed_ms:>6} ms  {check.detail}",
            flush=True,
        )

    def run(self, category: str, service: str, api: str, fn: Callable[[], str]) -> None:
        t0 = time.perf_counter()
        try:
            detail = fn() or "ok"
            ms = int((time.perf_counter() - t0) * 1000)
            skipped = str(detail).lower().startswith("skipped")
            self._emit(Check(category, service, api, True, skipped, ms, detail))
        except Exception as exc:  # noqa: BLE001
            ms = int((time.perf_counter() - t0) * 1000)
            msg = str(exc).replace("\n", " ")[:120]
            self._emit(Check(category, service, api, False, False, ms, msg))

    def counts(self, subset: Optional[List[Check]] = None) -> Tuple[int, int, int]:
        items = subset if subset is not None else self.checks
        p = sum(1 for c in items if c.ok and not c.skipped)
        f = sum(1 for c in items if not c.ok)
        s = sum(1 for c in items if c.skipped)
        return p, f, s


class ApiUsage:
    """Per AWS API call counters + latency samples (from botocore events)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.ok: Dict[Tuple[str, str], int] = {}
        self.fail: Dict[Tuple[str, str], int] = {}
        self.samples: Dict[Tuple[str, str], List[float]] = {}
        self._inflight: Dict[int, List[Tuple[str, str, float]]] = {}

    def begin(self, service: str, api: str) -> None:
        tid = threading.get_ident()
        with self._lock:
            self._inflight.setdefault(tid, []).append((service, api, time.perf_counter()))

    def end(self, ok: bool) -> None:
        tid = threading.get_ident()
        with self._lock:
            stack = self._inflight.get(tid)
            if not stack:
                return
            service, api, t0 = stack.pop()
            ms = (time.perf_counter() - t0) * 1000.0
            key = (service, api)
            self.samples.setdefault(key, []).append(ms)
            if ok:
                self.ok[key] = self.ok.get(key, 0) + 1
            else:
                self.fail[key] = self.fail.get(key, 0) + 1

    def rows(self) -> List[Dict[str, Any]]:
        keys = sorted(set(self.ok) | set(self.fail) | set(self.samples))
        out = []
        for key in keys:
            samples = sorted(self.samples.get(key, []))
            n = len(samples)
            p50 = samples[int(0.50 * (n - 1))] if n else 0.0
            p99 = samples[int(0.99 * (n - 1))] if n else 0.0
            out.append({
                "service": key[0],
                "api": key[1],
                "ok": self.ok.get(key, 0),
                "fail": self.fail.get(key, 0),
                "calls": self.ok.get(key, 0) + self.fail.get(key, 0),
                "avg_ms": (sum(samples) / n) if n else 0.0,
                "p50_ms": p50,
                "p99_ms": p99,
                "max_ms": samples[-1] if samples else 0.0,
            })
        return out


USAGE = ApiUsage()
_BOTO_CFG = BotoConfig(
    retries={"max_attempts": 3, "mode": "standard"},
    connect_timeout=5,
    read_timeout=30,
)


def _attach_usage(client: Any, service: str) -> Any:
    events = client.meta.events

    def before(model=None, **kw):  # noqa: ANN001
        name = getattr(model, "name", None) or kw.get("event_name", "Unknown")
        USAGE.begin(service, str(name))

    def after(**_kw):  # noqa: ANN003
        USAGE.end(True)

    def after_error(**_kw):  # noqa: ANN003
        USAGE.end(False)

    events.register("before-call.*.*", before)
    events.register("after-call.*.*", after)
    events.register("after-call-error.*.*", after_error)
    return client


def _client(service: str, endpoint: str, region: str):
    return _attach_usage(
        boto3.client(
            service,
            region_name=region,
            endpoint_url=endpoint,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "minioadmin"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "minioadmin"),
            config=_BOTO_CFG,
        ),
        service,
    )


def _resource(service: str, endpoint: str, region: str):
    res = boto3.resource(
        service,
        region_name=region,
        endpoint_url=endpoint,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "minioadmin"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "minioadmin"),
        config=_BOTO_CFG,
    )
    _attach_usage(res.meta.client, service)
    return res


def _hash_attr(schema: Dict[str, Any]) -> str:
    return next(k["AttributeName"] for k in schema["KeySchema"] if k["KeyType"] == "HASH")


def _range_attr(schema: Dict[str, Any]) -> Optional[str]:
    for k in schema["KeySchema"]:
        if k["KeyType"] == "RANGE":
            return k["AttributeName"]
    return None


def _gsi_indexes(schema: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(schema.get("GlobalSecondaryIndexes") or [])


def _table_purposes(capability: str) -> List[str]:
    key = capability.strip().lower()
    return list(CAPABILITY_TABLES.get(key, TABLE_SCHEMAS.keys()))


def _item_and_key(schema: Dict[str, Any], run_id: str) -> Tuple[Dict[str, Any], Dict[str, str]]:
    hk = _hash_attr(schema)
    rk = _range_attr(schema)
    hv = f"VERIFY#{run_id}"
    item: Dict[str, Any] = {hk: hv, "status": "created", "run_id": run_id}
    key: Dict[str, str] = {hk: hv}
    if rk:
        rv = f"META#{run_id}"
        item[rk] = rv
        key[rk] = rv
    for gsi in _gsi_indexes(schema):
        for ks in gsi.get("KeySchema") or []:
            name = ks["AttributeName"]
            if name not in item:
                item[name] = f"{name}#{run_id}"
    return item, key


# ── DynamoDB ────────────────────────────────────────────────────────────────


class DynamoDBVerifier:
    def __init__(self, endpoint: str, region: str, report: Report):
        self.ddb = _client("dynamodb", endpoint, region)
        self.table_res = _resource("dynamodb", endpoint, region)
        self.report = report
        self.load_target: Optional[Tuple[str, Dict[str, Any]]] = None

    def verify_capability_tables(self, capability: str, environment: str) -> None:
        naming = LocalNaming(capability, environment, account_id="000000000000")
        print(cyan(f"  ▶ DynamoDB  ({capability}/{environment})"))
        listed: List[str] = []

        def list_tables() -> str:
            names = self.ddb.list_tables().get("TableNames") or []
            listed.clear()
            listed.extend(names)
            return f"{len(names)} tables"

        self.report.run("FUNC", "DynamoDB", f"{capability} ListTables", list_tables)
        prefix = f"{capability}/{environment}"
        for purpose in _table_purposes(capability):
            schema = TABLE_SCHEMAS[purpose]
            table_name = naming.dynamodb_table(purpose)
            put_ok_before = len(self.report.checks)
            self._verify_table(prefix, purpose, table_name, schema, listed)
            if self.load_target is None and _range_attr(schema) and _hash_attr(schema) == "PK":
                added = self.report.checks[put_ok_before:]
                if any(c.ok and c.api.endswith("PutItem") for c in added):
                    self.load_target = (table_name, schema)

    def _verify_table(
        self,
        prefix: str,
        purpose: str,
        table_name: str,
        schema: Dict[str, Any],
        listed: List[str],
    ) -> None:
        svc_api = f"{prefix} {purpose}"

        def describe() -> str:
            if listed and table_name not in listed:
                raise AssertionError("not in ListTables")
            desc = self.ddb.describe_table(TableName=table_name)
            return desc["Table"]["TableStatus"]

        self.report.run("FUNC", "DynamoDB", f"{svc_api} DescribeTable", describe)
        if not self.report.checks[-1].ok:
            return

        table = self.table_res.Table(table_name)
        run_id = uuid.uuid4().hex[:8]
        item, key = _item_and_key(schema, run_id)
        hk = _hash_attr(schema)
        rk = _range_attr(schema)

        def put() -> str:
            table.put_item(Item=item)
            return "written"

        def get() -> str:
            got = table.get_item(Key=key)
            if "Item" not in got:
                raise AssertionError("missing item")
            return "hit"

        def update() -> str:
            table.update_item(
                Key=key,
                UpdateExpression="SET #s = :v",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":v": "updated"},
            )
            return "SET status"

        def query_pk() -> str:
            cond = Key(hk).eq(item[hk])
            if rk:
                cond = cond & Key(rk).eq(item[rk])
            resp = table.query(KeyConditionExpression=cond)
            if resp.get("Count", 0) < 1:
                raise AssertionError("no rows")
            return f"count={resp['Count']}"

        def query_gsi() -> str:
            gsis = _gsi_indexes(schema)
            if not gsis:
                return "skipped (no GSI)"
            gsi = gsis[0]
            idx = gsi["IndexName"]
            gsi_hk = next(k["AttributeName"] for k in gsi["KeySchema"] if k["KeyType"] == "HASH")
            last = 0
            for _ in range(5):
                resp = table.query(
                    IndexName=idx,
                    KeyConditionExpression=Key(gsi_hk).eq(item[gsi_hk]),
                )
                last = resp.get("Count", 0)
                if last >= 1:
                    return f"{idx} count={last}"
                time.sleep(0.2)
            raise AssertionError(f"{idx} no rows")

        def scan() -> str:
            resp = table.scan(Limit=1)
            return f"count={resp.get('Count', 0)}"

        def batch() -> str:
            with table.batch_writer() as bw:
                bw.put_item(Item={**item, "batch": True})
            return "put"

        def delete() -> str:
            table.delete_item(Key=key)
            return "deleted"

        for api, fn in [
            (f"{svc_api} PutItem", put),
            (f"{svc_api} GetItem", get),
            (f"{svc_api} UpdateItem", update),
            (f"{svc_api} Query PK", query_pk),
            (f"{svc_api} Query GSI", query_gsi),
            (f"{svc_api} Scan", scan),
            (f"{svc_api} BatchWriteItem", batch),
            (f"{svc_api} DeleteItem", delete),
        ]:
            self.report.run("FUNC", "DynamoDB", api, fn)


# ── Athena / Glue / S3 ──────────────────────────────────────────────────────


class AthenaVerifier:
    def __init__(self, ministack_endpoint: str, minio_endpoint: str, region: str, report: Report):
        self.glue = _client("glue", ministack_endpoint, region)
        self.athena = _client("athena", ministack_endpoint, region)
        self.s3_minio = _client("s3", minio_endpoint, region)
        self.s3_ministack = _client("s3", ministack_endpoint, region)
        self.sts = _client("sts", ministack_endpoint, region)
        self.report = report

    def verify_sts(self) -> None:
        print(cyan("  ▶ STS"))

        def ident() -> str:
            r = self.sts.get_caller_identity()
            return f"Account={r.get('Account')} Arn={str(r.get('Arn', ''))[-40:]}"

        self.report.run("FUNC", "STS", "GetCallerIdentity", ident)

    def verify_capability(self, capability: str, environment: str) -> None:
        naming = LocalNaming(capability, environment, account_id="000000000000")
        db_name = naming.glue_database()
        output_bucket = f"{capability}-{environment}-athena-results"
        prefix = f"{capability}/{environment}"
        print(cyan(f"  ▶ Athena/Glue  ({prefix})"))

        def get_db() -> str:
            self.glue.get_database(Name=db_name)
            return db_name

        self.report.run("FUNC", "Glue", f"{prefix} GetDatabase", get_db)
        if not self.report.checks[-1].ok:
            return

        self._ensure_bucket(output_bucket, prefix)
        output_location = f"s3://{output_bucket}/verify/"

        def start_select1() -> str:
            resp = self.athena.start_query_execution(
                QueryString="SELECT 1 AS ok",
                QueryExecutionContext={"Database": db_name},
                ResultConfiguration={"OutputLocation": output_location},
            )
            return resp["QueryExecutionId"]

        self.report.run("FUNC", "Athena", f"{prefix} StartQueryExecution", start_select1)
        if not self.report.checks[-1].ok:
            return
        qid = self.report.checks[-1].detail

        def poll() -> str:
            state = self._poll(qid)
            if state != "SUCCEEDED":
                raise AssertionError(state)
            return state

        self.report.run("FUNC", "Athena", f"{prefix} GetQueryExecution", poll)
        if not self.report.checks[-1].ok:
            return

        def results() -> str:
            r = self.athena.get_query_results(QueryExecutionId=qid, MaxResults=10)
            rows = r.get("ResultSet", {}).get("Rows") or []
            if len(rows) < 2:
                raise AssertionError(f"rows={len(rows)} (want header+data)")
            return f"rows={len(rows)}"

        self.report.run("FUNC", "Athena", f"{prefix} GetQueryResults", results)

        table_name = "verify_smoke"
        self._ensure_glue_table(db_name, table_name, output_bucket, prefix)

        def table_q() -> str:
            resp = self.athena.start_query_execution(
                QueryString=f'SELECT * FROM "{table_name}" LIMIT 1',
                QueryExecutionContext={"Database": db_name},
                ResultConfiguration={"OutputLocation": output_location},
            )
            state = self._poll(resp["QueryExecutionId"])
            if state != "SUCCEEDED":
                raise AssertionError(state)
            return table_name

        self.report.run("FUNC", "Athena", f"{prefix} table query", table_q)

    def _ensure_bucket(self, bucket: str, prefix: str) -> None:
        for label, s3 in (("MiniStack", self.s3_ministack), ("MinIO", self.s3_minio)):
            def head(s3_client=s3, b=bucket) -> str:
                try:
                    s3_client.head_bucket(Bucket=b)
                    return "exists"
                except ClientError:
                    s3_client.create_bucket(Bucket=b)
                    return "created"

            self.report.run("FUNC", "S3", f"{prefix} Head/CreateBucket ({label})", head)

    def _ensure_glue_table(self, db_name: str, table_name: str, bucket: str, prefix: str) -> None:
        def ensure() -> str:
            try:
                self.glue.get_table(DatabaseName=db_name, Name=table_name)
                return f"exists {table_name}"
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "EntityNotFoundException":
                    raise
            self.glue.create_table(
                DatabaseName=db_name,
                TableInput={
                    "Name": table_name,
                    "TableType": "EXTERNAL_TABLE",
                    "StorageDescriptor": {
                        "Columns": [{"Name": "ok", "Type": "int"}],
                        "Location": f"s3://{bucket}/verify/{table_name}/",
                        "InputFormat": "org.apache.hadoop.mapred.TextInputFormat",
                        "OutputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
                        "SerdeInfo": {
                            "SerializationLibrary": "org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe",
                            "Parameters": {"field.delim": ","},
                        },
                    },
                    "Parameters": {"classification": "csv"},
                },
            )
            return f"created {table_name}"

        self.report.run("FUNC", "Glue", f"{prefix} Get/CreateTable", ensure)

    def _poll(self, qid: str) -> str:
        for _ in range(60):
            resp = self.athena.get_query_execution(QueryExecutionId=qid)
            state = resp["QueryExecution"]["Status"]["State"]
            if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
                if state != "SUCCEEDED":
                    reason = resp["QueryExecution"]["Status"].get("StateChangeReason", state)
                    return f"{state} {reason}".strip()
                return state
            time.sleep(0.5)
        return "TIMEOUT"


# ── load / endurance ────────────────────────────────────────────────────────


class LoadRunner:
    def __init__(self, table_name: str, schema: Dict[str, Any], ddb_resource: Any, report: Report):
        self.table_name = table_name
        self.schema = schema
        self.table = ddb_resource.Table(table_name)
        self.report = report
        self.hk = _hash_attr(schema)
        self.rk = _range_attr(schema)

    def _keys(self, worker: int, i: int) -> Tuple[Dict[str, Any], Dict[str, str]]:
        hv = f"LOAD#{RUN_ID}#{worker}"
        item: Dict[str, Any] = {self.hk: hv, "n": i, "w": worker, "status": "load"}
        key: Dict[str, str] = {self.hk: hv}
        if self.rk:
            rv = f"ITEM#{i:06d}"
            item[self.rk] = rv
            key[self.rk] = rv
        return item, key

    def stress_concurrency(self, workers: int, iterations: int) -> None:
        print(cyan(f"  ▶ Stress / concurrency  ({workers} workers × {iterations} put+get+delete)"))
        errors: List[str] = []
        latencies: List[float] = []
        lock = threading.Lock()

        def worker(wid: int) -> int:
            ok = 0
            for i in range(iterations):
                item, key = self._keys(wid, i)
                t0 = time.perf_counter()
                try:
                    self.table.put_item(Item=item)
                    got = self.table.get_item(Key=key)
                    if "Item" not in got:
                        raise AssertionError("miss")
                    self.table.delete_item(Key=key)
                    ok += 1
                except Exception as exc:  # noqa: BLE001
                    with lock:
                        if len(errors) < 5:
                            errors.append(str(exc)[:80])
                finally:
                    with lock:
                        latencies.append((time.perf_counter() - t0) * 1000)
            return ok

        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(worker, w) for w in range(workers)]
            total_ok = sum(f.result() for f in as_completed(futs))
        dt = time.perf_counter() - t0
        total = workers * iterations
        qps = total / dt if dt else 0
        p99 = sorted(latencies)[int(0.99 * (len(latencies) - 1))] if latencies else 0

        def summary() -> str:
            if total_ok < total:
                raise AssertionError(f"{total_ok}/{total} ok; err={errors[:2]}")
            return f"{total_ok}/{total} cycles in {dt:.2f}s ({qps:.0f} qps) p99={p99:.0f}ms"

        self.report.run("LOAD", "DynamoDB", f"Concurrent put/get/delete x{workers}", summary)

    def endurance(self, seconds: int, workers: int) -> None:
        print(cyan(f"  ▶ Endurance  ({seconds}s, {workers} workers, mixed put/get/query/delete)"))
        stop_at = time.time() + seconds
        stats = {"ok": 0, "fail": 0, "abort": False}
        lock = threading.Lock()
        started = time.time()

        def worker(wid: int) -> None:
            i = 0
            while time.time() < stop_at:
                with lock:
                    if stats["abort"]:
                        return
                item, key = self._keys(wid, i)
                try:
                    self.table.put_item(Item=item)
                    self.table.get_item(Key=key)
                    if self.rk:
                        self.table.query(
                            KeyConditionExpression=Key(self.hk).eq(item[self.hk]) & Key(self.rk).begins_with("ITEM"),
                            Limit=5,
                        )
                    self.table.delete_item(Key=key)
                    with lock:
                        stats["ok"] += 1
                except Exception:  # noqa: BLE001
                    with lock:
                        stats["fail"] += 1
                        if stats["ok"] == 0 and stats["fail"] >= 20 and (time.time() - started) >= 8:
                            stats["abort"] = True
                            return
                i += 1

        def ticker() -> None:
            while time.time() < stop_at:
                time.sleep(10)
                with lock:
                    if stats["abort"]:
                        return
                    ops = stats["ok"] + stats["fail"]
                    err = stats["fail"]
                elapsed = time.time() - started
                qps = ops / elapsed if elapsed else 0
                print(dim(f"      … {elapsed:4.0f}s  ops={ops}  err={err}  {qps:.0f} ops/s"), flush=True)

        t0 = time.perf_counter()
        threading.Thread(target=ticker, daemon=True).start()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(worker, w) for w in range(workers)]
            for f in futs:
                f.result()
        dt = time.perf_counter() - t0
        ops = stats["ok"] + stats["fail"]
        qps = ops / dt if dt else 0
        err_rate = (100.0 * stats["fail"] / ops) if ops else 100.0

        def summary() -> str:
            if stats["abort"]:
                raise AssertionError(f"aborted after {dt:.1f}s — zero successes ({stats['fail']} failed)")
            if stats["ok"] < 1:
                raise AssertionError("zero successful ops")
            if err_rate > 5.0:
                raise AssertionError(f"error rate {err_rate:.1f}% ({stats['fail']}/{ops})")
            return (
                f"{ops} ops in {dt:.1f}s ({qps:.0f} ops/s) "
                f"ok={stats['ok']} fail={stats['fail']} err={err_rate:.2f}%"
            )

        self.report.run("LOAD", "DynamoDB", f"Endurance {seconds}s mixed CRUD", summary)


# ── report ──────────────────────────────────────────────────────────────────


def print_report(rep: Report, meta: Dict[str, Any]) -> int:
    p, f, s = rep.counts()
    overall_s = green(bold("PASS")) if f == 0 else red(bold("FAIL"))
    width = 98

    print("")
    print("╔" + "═" * width + "╗")
    print("║ " + bold("NEXUS LOCAL BOTO3 AWS API REPORT".ljust(width - 1)) + "║")
    sub = f"run={meta['run']}   {meta['when']}   caps={meta['caps']}   env={meta['env']}"
    print("║ " + dim(sub.ljust(width - 1)) + "║")
    print("╚" + "═" * width + "╝")

    print("")
    print(bold("ENDPOINTS"))
    for k, v in meta["endpoints"]:
        print(f"  {k:<16} {v}")

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
        if not items:
            return
        print("")
        print(bold(title))
        cols2 = [12, 50, 6, 8, 24]
        print(_rule(cols2, "┌", "┬", "┐"))
        print(_row(["Service", "Check", "Status", "Latency", "Detail"], cols2, ["l", "l", "l", "r", "l"]))
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

    print_api_table(
        "FUNCTIONAL CHECKS  (Describe/Put/Get/Update/Query/Scan/Batch/Delete · Glue · Athena · S3 · STS)",
        [c for c in rep.checks if c.category == "FUNC"],
    )
    print_api_table(
        "LOAD  (concurrency stress · 1-minute endurance)",
        [c for c in rep.checks if c.category == "LOAD"],
    )

    usage = USAGE.rows()
    print("")
    print(bold("AWS API USAGE  (every boto3 call: count, errors, latency)"))
    cols3 = [12, 22, 8, 7, 10, 10, 10, 10]
    print(_rule(cols3, "┌", "┬", "┐"))
    print(_row(
        ["Service", "API", "Calls", "Fail", "Avg", "p50", "p99", "Max"],
        cols3,
        ["l", "l", "r", "r", "r", "r", "r", "r"],
    ))
    print(_rule(cols3, "├", "┼", "┤"))
    total_calls = total_fail = 0
    last = None
    for row in usage:
        total_calls += row["calls"]
        total_fail += row["fail"]
        svc = row["service"] if row["service"] != last else ""
        last = row["service"]
        print(_row(
            [
                svc,
                row["api"],
                str(row["calls"]),
                str(row["fail"]),
                f"{row['avg_ms']:.1f} ms",
                f"{row['p50_ms']:.1f} ms",
                f"{row['p99_ms']:.1f} ms",
                f"{row['max_ms']:.1f} ms",
            ],
            cols3,
            ["l", "l", "r", "r", "r", "r", "r", "r"],
        ))
    print(_rule(cols3, "├", "┼", "┤"))
    print(_row(
        ["TOTAL", f"{len(usage)} APIs", str(total_calls), str(total_fail), "", "", "", ""],
        cols3,
        ["l", "l", "r", "r", "r", "r", "r", "r"],
    ))
    print(_rule(cols3, "└", "┴", "┘"))

    fails = [c for c in rep.checks if not c.ok]
    if fails:
        print("")
        print(bold(red("FAILURES")))
        for c in fails:
            print(f"  • {c.service:12} {c.api:42} {c.detail}")

    print("")
    print("─" * (width + 2))
    print(
        f"  CHECKS  {green(str(p) + ' passed')}   "
        f"{red(str(f) + ' failed') if f else dim(str(f) + ' failed')}   "
        f"{yellow(str(s) + ' skipped')}   "
        f"boto3 calls={total_calls} ({total_fail} failed)   OVERALL {overall_s}"
    )
    print("─" * (width + 2))
    print("", flush=True)
    return 0 if f == 0 else 1


# ── main ────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify local K3s boto3 DynamoDB/Athena APIs")
    parser.add_argument("--capabilities", default="ontology,nexus-ai")
    parser.add_argument("--environment", default="local")
    parser.add_argument("--region", default=os.getenv("AWS_REGION", "us-east-1"))
    parser.add_argument(
        "--scylla-endpoint",
        default="http://scylla-svc.nexus-local.svc.cluster.local:8000",
    )
    parser.add_argument(
        "--ministack-endpoint",
        default="http://ministack-svc.nexus-local.svc.cluster.local:4566",
    )
    parser.add_argument(
        "--minio-endpoint",
        default="http://minio-svc.nexus-local.svc.cluster.local:9000",
    )
    parser.add_argument("--skip-athena", action="store_true")
    parser.add_argument("--skip-load", action="store_true", help="Skip concurrency + endurance")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--stress-iterations", type=int, default=25)
    parser.add_argument("--endurance-seconds", type=int, default=60)
    parser.add_argument("--endurance-workers", type=int, default=4)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    caps = [c.strip() for c in args.capabilities.split(",") if c.strip()]
    when = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    print(bold("Running boto3 AWS API verification…"))
    print(dim(f"  run={RUN_ID}  caps={','.join(caps)}  {when}"))
    print("")

    report = Report()
    ddb = DynamoDBVerifier(args.scylla_endpoint, args.region, report)
    for cap in caps:
        ddb.verify_capability_tables(cap, args.environment)

    if not args.skip_athena:
        athena = AthenaVerifier(args.ministack_endpoint, args.minio_endpoint, args.region, report)
        athena.verify_sts()
        for cap in caps:
            athena.verify_capability(cap, args.environment)

    if not args.skip_load:
        if ddb.load_target is None:
            report._emit(Check("LOAD", "DynamoDB", "Stress/endurance", False, False, 0, "no PK/SK table for load"))
        else:
            table_name, schema = ddb.load_target
            runner = LoadRunner(table_name, schema, ddb.table_res, report)
            runner.stress_concurrency(args.workers, args.stress_iterations)
            stress_ok = bool(report.checks) and report.checks[-1].ok
            if args.endurance_seconds > 0:
                if not stress_ok:
                    report._emit(Check(
                        "LOAD", "DynamoDB", f"Endurance {args.endurance_seconds}s mixed CRUD",
                        True, True, 0, "skipped (stress failed)",
                    ))
                else:
                    runner.endurance(args.endurance_seconds, args.endurance_workers)

    meta = {
        "run": RUN_ID,
        "when": when,
        "caps": ",".join(caps),
        "env": args.environment,
        "endpoints": [
            ("DynamoDB", args.scylla_endpoint + "  (Scylla Alternator)"),
            ("MiniStack", args.ministack_endpoint + "  (Athena / Glue / STS / S3)"),
            ("MinIO", args.minio_endpoint + "  (S3)"),
        ],
    }

    if args.json:
        print(json.dumps({
            "run": RUN_ID,
            "passed": report.counts()[0],
            "failed": report.counts()[1],
            "checks": [
                {"service": c.service, "api": c.api, "ok": c.ok, "ms": c.elapsed_ms, "detail": c.detail}
                for c in report.checks
            ],
            "usage": USAGE.rows(),
        }, indent=2))
        return 0 if report.counts()[1] == 0 else 1

    return print_report(report, meta)


if __name__ == "__main__":
    raise SystemExit(main())

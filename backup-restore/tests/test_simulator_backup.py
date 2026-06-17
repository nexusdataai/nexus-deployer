"""
Unit tests for simulator_backup.py (Stage 1 DR rewrite).

Uses moto's mock_aws to stand up fake S3 + STS, exercises the backup
command end-to-end into a temporary tarball, then exercises restore
against a different "target account" by swapping the moto session.

Coverage:
  - Backup walks all 7 simulator buckets, packs into a tarball
  - Manifest carries source capability/env/account/region + per-sim counts
  - Empty buckets are recorded but produce no s3/<sim>/ directory
  - Restore round-trips keys back into target buckets (cross-env rename)
  - Restore --dry-run reports counts without making S3 writes
  - Restore fails fast when target bucket doesn't exist
"""

from __future__ import annotations

import os
import sys
import tarfile
import tempfile
from pathlib import Path

import boto3
import pytest

# moto v5 introduced `mock_aws`; older versions used `mock_s3`/`mock_sts`.
try:
    from moto import mock_aws
except ImportError:  # pragma: no cover - environment guard
    pytest.skip("moto>=5 not installed; skipping simulator_backup tests",
                allow_module_level=True)

PARENT = Path(__file__).resolve().parent.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

import simulator_backup as sb  # noqa: E402


SOURCE_CAP = "nexus-ai"
SOURCE_ENV = "dev"
SOURCE_ACCOUNT = "111111111111"
REGION = "us-east-1"

TARGET_CAP = "nexus-ai"
TARGET_ENV = "test"
TARGET_ACCOUNT = "222222222222"


def _bucket_name(cap: str, env: str, suffix: str, account_id: str) -> str:
    return f"{cap}-{env}-{suffix}-{account_id}"


def _seed_source_buckets(account_id: str) -> dict:
    """Create all 7 source buckets and seed one row in three of them."""
    s3 = boto3.client("s3", region_name=REGION)
    seeded = {}
    for sim in sb.SIMULATORS:
        bucket = _bucket_name(SOURCE_CAP, SOURCE_ENV, sim["suffix"], account_id)
        s3.create_bucket(Bucket=bucket)
        seeded[sim["name"]] = bucket
    # Populate three of the seven so we can assert both populated and empty.
    s3.put_object(Bucket=seeded["sfdc-simulator"],
                  Key="objects/sfdc_itxp2dev/account.csv",
                  Body=b"Id,Name\n001,Acme\n002,Globex\n")
    s3.put_object(Bucket=seeded["oracle-erp-simulator"],
                  Key="schemas/finance/ledger.json",
                  Body=b'{"rows":[{"account":"GL-100","amount":12345}]}')
    s3.put_object(Bucket=seeded["external-sources"],
                  Key="raw/social_listening/2026-06-10.csv",
                  Body=b"timestamp,signal,score\n2026-06-10T00:00:00Z,neg,0.92\n")
    return seeded


def _seed_target_buckets(account_id: str) -> dict:
    """The operator would have already provisioned empty target buckets."""
    s3 = boto3.client("s3", region_name=REGION)
    targets = {}
    for sim in sb.SIMULATORS:
        bucket = _bucket_name(TARGET_CAP, TARGET_ENV, sim["suffix"], account_id)
        s3.create_bucket(Bucket=bucket)
        targets[sim["name"]] = bucket
    return targets


def _run_backup(output_path: Path, account_id: str) -> int:
    return sb.main([
        "backup",
        "--capability", SOURCE_CAP,
        "--env", SOURCE_ENV,
        "--region", REGION,
        "-o", str(output_path),
    ])


def _run_restore(
    input_path: Path,
    dry_run: bool = False,
    no_clean: bool = False,
    no_hydrate: bool = True,
) -> int:
    """
    Default `no_hydrate=True` so existing tests don't try to spawn
    kubectl. New tests can opt into hydrate explicitly.
    """
    argv = [
        "restore",
        "-i", str(input_path),
        "--target-capability", TARGET_CAP,
        "--target-env", TARGET_ENV,
        "--region", REGION,
    ]
    if dry_run:
        argv.append("--dry-run")
    if no_clean:
        argv.append("--no-clean")
    if no_hydrate:
        argv.append("--no-hydrate")
    return sb.main(argv)


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

@mock_aws
def test_backup_produces_tarball_with_manifest_and_per_sim_dirs(tmp_path, monkeypatch):
    # Force a deterministic STS account
    sts = boto3.client("sts", region_name=REGION)
    monkeypatch.setenv("MOTO_ACCOUNT_ID", SOURCE_ACCOUNT)
    real_account = sts.get_caller_identity()["Account"]
    seeded = _seed_source_buckets(real_account)

    out = tmp_path / "sim.tar.gz"
    rc = _run_backup(out, real_account)
    assert rc == 0, "backup command should exit 0"
    assert out.exists()

    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()

    # Manifest must be present
    manifest_entries = [n for n in names if n.endswith("/manifest.json")]
    assert len(manifest_entries) == 1
    # The 3 populated sims should have files; the 4 empty ones should NOT
    # appear as s3/<sim>/ directories (download_keys_parallel skips empty
    # lists, so no directory is created).
    assert any("s3/sfdc-simulator/objects/sfdc_itxp2dev/account.csv" in n for n in names)
    assert any("s3/oracle-erp-simulator/schemas/finance/ledger.json" in n for n in names)
    assert any("s3/external-sources/raw/social_listening/2026-06-10.csv" in n for n in names)
    assert not any("s3/sap-simulator/" in n for n in names)  # empty


@mock_aws
def test_manifest_records_source_metadata_and_counts(tmp_path):
    import json
    sts = boto3.client("sts", region_name=REGION)
    real_account = sts.get_caller_identity()["Account"]
    _seed_source_buckets(real_account)

    out = tmp_path / "sim.tar.gz"
    _run_backup(out, real_account)

    with tempfile.TemporaryDirectory() as tmpd:
        with tarfile.open(out, "r:gz") as tar:
            tar.extractall(tmpd)
        root = next(p for p in Path(tmpd).iterdir() if p.is_dir())
        manifest = json.loads((root / "manifest.json").read_text())

    assert manifest["schema_version"] == sb.MANIFEST_SCHEMA_VERSION
    assert manifest["source_capability"] == SOURCE_CAP
    assert manifest["source_env"] == SOURCE_ENV
    assert manifest["source_account_id"] == real_account
    assert manifest["source_region"] == REGION

    by_name = {s["name"]: s for s in manifest["simulators"]}
    assert by_name["sfdc-simulator"]["key_count"] == 1
    assert by_name["oracle-erp-simulator"]["key_count"] == 1
    assert by_name["external-sources"]["key_count"] == 1
    assert by_name["sap-simulator"]["key_count"] == 0
    assert by_name["sap-simulator"]["bytes"] == 0


@mock_aws
def test_backup_then_restore_round_trip_into_target_env(tmp_path):
    sts = boto3.client("sts", region_name=REGION)
    account_id = sts.get_caller_identity()["Account"]
    seeded = _seed_source_buckets(account_id)
    targets = _seed_target_buckets(account_id)

    out = tmp_path / "sim.tar.gz"
    assert _run_backup(out, account_id) == 0
    assert _run_restore(out) == 0

    s3 = boto3.client("s3", region_name=REGION)

    # Verify that target buckets received the same keys
    objs = s3.list_objects_v2(Bucket=targets["sfdc-simulator"])
    keys = [o["Key"] for o in objs.get("Contents", [])]
    assert "objects/sfdc_itxp2dev/account.csv" in keys

    objs = s3.list_objects_v2(Bucket=targets["oracle-erp-simulator"])
    keys = [o["Key"] for o in objs.get("Contents", [])]
    assert "schemas/finance/ledger.json" in keys

    # Content must round-trip byte-for-byte
    body = s3.get_object(
        Bucket=targets["sfdc-simulator"],
        Key="objects/sfdc_itxp2dev/account.csv",
    )["Body"].read()
    assert body == b"Id,Name\n001,Acme\n002,Globex\n"


@mock_aws
def test_dry_run_restore_does_not_upload(tmp_path):
    sts = boto3.client("sts", region_name=REGION)
    account_id = sts.get_caller_identity()["Account"]
    _seed_source_buckets(account_id)
    targets = _seed_target_buckets(account_id)

    out = tmp_path / "sim.tar.gz"
    _run_backup(out, account_id)
    rc = _run_restore(out, dry_run=True)
    assert rc == 0

    s3 = boto3.client("s3", region_name=REGION)
    for name in ("sfdc-simulator", "oracle-erp-simulator", "external-sources"):
        objs = s3.list_objects_v2(Bucket=targets[name])
        assert "Contents" not in objs, (
            f"--dry-run must not upload anything to {targets[name]}, "
            f"but found {len(objs.get('Contents', []))} keys"
        )


@mock_aws
def test_restore_fails_when_target_bucket_missing(tmp_path):
    sts = boto3.client("sts", region_name=REGION)
    account_id = sts.get_caller_identity()["Account"]
    _seed_source_buckets(account_id)
    # Intentionally do NOT seed target buckets — restore must fail fast.

    out = tmp_path / "sim.tar.gz"
    _run_backup(out, account_id)

    with pytest.raises(SystemExit):
        _run_restore(out)


@mock_aws
def test_backup_skips_simulator_buckets_that_are_not_provisioned(tmp_path):
    """
    Regression for the dev-cluster failure where only 4 of 7 simulator
    buckets exist. resolve_bucket_name now returns None for genuine 404s
    and cmd_backup records an empty manifest entry instead of crashing.
    """
    import json
    sts = boto3.client("sts", region_name=REGION)
    account_id = sts.get_caller_identity()["Account"]

    # Provision only the first 4 simulators (matching the user's dev cluster).
    s3 = boto3.client("s3", region_name=REGION)
    provisioned = {}
    for sim in sb.SIMULATORS[:4]:
        bucket = _bucket_name(SOURCE_CAP, SOURCE_ENV, sim["suffix"], account_id)
        s3.create_bucket(Bucket=bucket)
        provisioned[sim["name"]] = bucket
    s3.put_object(Bucket=provisioned["sfdc-simulator"], Key="x.csv", Body=b"a,b\n1,2\n")

    out = tmp_path / "sim.tar.gz"
    rc = _run_backup(out, account_id)
    assert rc == 0, "backup must complete despite some simulators having no bucket"

    with tempfile.TemporaryDirectory() as tmpd:
        with tarfile.open(out, "r:gz") as tar:
            tar.extractall(tmpd)
        root = next(p for p in Path(tmpd).iterdir() if p.is_dir())
        manifest = json.loads((root / "manifest.json").read_text())

    by_name = {s["name"]: s for s in manifest["simulators"]}
    # First 4: provisioned, bucket set
    for sim in sb.SIMULATORS[:4]:
        e = by_name[sim["name"]]
        assert e["bucket"] is not None, f"{sim['name']} should have a bucket"
    # Last 3: absent, bucket=None, counts=0
    for sim in sb.SIMULATORS[4:]:
        e = by_name[sim["name"]]
        assert e["bucket"] is None, f"{sim['name']} should be recorded as not provisioned"
        assert e["key_count"] == 0
        assert e["bytes"] == 0


def test_hydrate_posts_to_each_s3_backed_simulator(monkeypatch, capsys):
    """
    hydrate finds a Running backend pod, then POSTs to /load on each of the
    4 S3-backed simulators and polls /load/status until running=False.
    Synthetic / legacy simulators are skipped without a network call.
    """
    monkeypatch.setattr(sb.shutil, "which", lambda _x: "/usr/bin/kubectl")

    monkeypatch.setattr(sb, "_find_backend_pod", lambda ns, sel, timeout=30: "backend-abc")

    posts_seen: list[str] = []
    status_seen: list[str] = []

    def fake_exec_curl(namespace, pod, url, *, method="GET", timeout=30):
        if method == "POST":
            posts_seen.append(url)
            return 0, '{"status":"started"}\n__HTTP_STATUS=202'
        status_seen.append(url)
        return 0, ('{"running": false, "loaded": true, "tables_with_data": 12, '
                   '"total_rows": 4144}\n__HTTP_STATUS=200')

    monkeypatch.setattr(sb, "_exec_curl", fake_exec_curl)
    # Don't actually sleep between polls in the test.
    monkeypatch.setattr(sb.time, "sleep", lambda _s: None)

    rc = sb.main([
        "hydrate",
        "--capability", "nexus-ai",
        "--env", "prod",
        "--timeout", "5",
    ])
    assert rc == 0

    # Should have POSTed to all 4 S3-backed endpoints (sfdc, oracle-erp, sap, external)
    assert len(posts_seen) == 4
    assert any("sfdc-simulator/load" in u for u in posts_seen)
    assert any("oracle-erp-simulator/load" in u for u in posts_seen)
    assert any("sap-simulator/load" in u for u in posts_seen)
    assert any("external-simulator/load" in u for u in posts_seen)
    # NOT to wxcc, tpm, sourcing
    assert not any("wxcc" in u for u in posts_seen)
    assert not any("tpm-simulator/load" in u for u in posts_seen)
    assert not any("sourcing-simulator/load" in u for u in posts_seen)

    # And polled status for each
    assert len(status_seen) == 4

    out = capsys.readouterr().out
    assert "OK: hydrated 4 simulator(s)" in out


def test_hydrate_fails_clearly_when_no_pod_found(monkeypatch):
    monkeypatch.setattr(sb.shutil, "which", lambda _x: "/usr/bin/kubectl")
    monkeypatch.setattr(sb, "_find_backend_pod", lambda ns, sel, timeout=30: None)

    with pytest.raises(SystemExit) as exc:
        sb.main([
            "hydrate",
            "--capability", "nexus-ai",
            "--env", "prod",
        ])
    msg = str(exc.value)
    assert "no Running pod found" in msg or "nexus-ai-prod" in msg


def test_hydrate_subset_via_simulators_flag(monkeypatch, capsys):
    monkeypatch.setattr(sb.shutil, "which", lambda _x: "/usr/bin/kubectl")
    monkeypatch.setattr(sb, "_find_backend_pod", lambda ns, sel, timeout=30: "backend-abc")
    monkeypatch.setattr(sb.time, "sleep", lambda _s: None)

    posts: list[str] = []
    def fake_exec_curl(namespace, pod, url, *, method="GET", timeout=30):
        if method == "POST":
            posts.append(url)
            return 0, '{}\n__HTTP_STATUS=202'
        return 0, '{"running": false, "loaded": true}\n__HTTP_STATUS=200'
    monkeypatch.setattr(sb, "_exec_curl", fake_exec_curl)

    rc = sb.main([
        "hydrate",
        "--capability", "nexus-ai",
        "--env", "prod",
        "--simulators", "sfdc-simulator,oracle-erp-simulator",
        "--no-wait",
    ])
    assert rc == 0
    assert len(posts) == 2
    assert all(("sfdc-simulator" in u or "oracle-erp-simulator" in u) for u in posts)


@mock_aws
def test_restore_cleans_stale_legacy_keys_under_target_prefix(tmp_path):
    """
    Regression for the prod failure where a previous tenant's dump
    (1661-table `starhub_itxp2dev` schema) survived a restore of a fresh
    dev backup (245-table `sfdc_itxp2dev` schema) because the restore
    only uploaded the new keys without deleting the old ones.

    With the default --clean=on behaviour, the target prefix is wiped
    before upload so the simulator can't load a confused mix of new
    data files + old tables.json.
    """
    sts = boto3.client("sts", region_name=REGION)
    account_id = sts.get_caller_identity()["Account"]
    _seed_source_buckets(account_id)
    targets = _seed_target_buckets(account_id)

    # Plant a "legacy" stale key under sfdc-simulator/ that should be
    # wiped by the restore.
    s3 = boto3.client("s3", region_name=REGION)
    s3.put_object(
        Bucket=targets["sfdc-simulator"],
        Key="sfdc-simulator/tables.json",
        Body=b'[{"schemaName":"starhub_itxp2dev","tableName":"LegacyTable"}]',
    )
    s3.put_object(
        Bucket=targets["sfdc-simulator"],
        Key="sfdc-simulator/data/starhub_itxp2dev.LegacyTable.json",
        Body=b'[{"id":1}]',
    )

    # Sanity: the stale keys exist before restore.
    objs = s3.list_objects_v2(Bucket=targets["sfdc-simulator"])
    pre_keys = {o["Key"] for o in objs.get("Contents", [])}
    assert "sfdc-simulator/tables.json" in pre_keys

    out = tmp_path / "sim.tar.gz"
    assert _run_backup(out, account_id) == 0
    assert _run_restore(out) == 0  # clean=on by default

    # After restore: BOTH legacy stale keys must be gone.
    objs = s3.list_objects_v2(Bucket=targets["sfdc-simulator"])
    post_keys = {o["Key"] for o in objs.get("Contents", [])}
    legacy_data = "sfdc-simulator/data/starhub_itxp2dev.LegacyTable.json"
    legacy_tables = "sfdc-simulator/tables.json"
    assert legacy_data not in post_keys, (
        f"legacy stale key {legacy_data!r} should have been deleted by --clean; "
        f"surviving keys: {sorted(post_keys)}"
    )
    # The legacy tables.json must also be gone. The dev backup fixture
    # doesn't write a replacement tables.json (it only stages a few data
    # objects), so the post-restore bucket should have NO tables.json at
    # all — proving clean+upload doesn't leave the old content stitched
    # behind the new data.
    assert legacy_tables not in post_keys, (
        f"legacy tables.json should have been deleted by --clean; "
        f"surviving keys: {sorted(post_keys)}"
    )


@mock_aws
def test_restore_no_clean_preserves_stale_keys(tmp_path):
    """The --no-clean opt-out leaves pre-existing keys alone."""
    sts = boto3.client("sts", region_name=REGION)
    account_id = sts.get_caller_identity()["Account"]
    _seed_source_buckets(account_id)
    targets = _seed_target_buckets(account_id)

    s3 = boto3.client("s3", region_name=REGION)
    s3.put_object(
        Bucket=targets["sfdc-simulator"],
        Key="sfdc-simulator/keep-me.txt",
        Body=b"do-not-delete",
    )

    out = tmp_path / "sim.tar.gz"
    assert _run_backup(out, account_id) == 0
    assert _run_restore(out, no_clean=True) == 0

    # The opt-out preserved the stale key.
    objs = s3.list_objects_v2(Bucket=targets["sfdc-simulator"])
    post_keys = {o["Key"] for o in objs.get("Contents", [])}
    assert "sfdc-simulator/keep-me.txt" in post_keys


@mock_aws
def test_restore_dry_run_reports_clean_count_without_deleting(tmp_path, capsys):
    sts = boto3.client("sts", region_name=REGION)
    account_id = sts.get_caller_identity()["Account"]
    _seed_source_buckets(account_id)
    targets = _seed_target_buckets(account_id)

    s3 = boto3.client("s3", region_name=REGION)
    for i in range(3):
        s3.put_object(
            Bucket=targets["sfdc-simulator"],
            Key=f"sfdc-simulator/old-{i}.json",
            Body=b"{}",
        )

    out = tmp_path / "sim.tar.gz"
    _run_backup(out, account_id)
    rc = _run_restore(out, dry_run=True)
    assert rc == 0

    # All three stale keys must still be there after dry-run.
    objs = s3.list_objects_v2(Bucket=targets["sfdc-simulator"])
    post_keys = {o["Key"] for o in objs.get("Contents", [])}
    for i in range(3):
        assert f"sfdc-simulator/old-{i}.json" in post_keys


def test_restore_auto_hydrate_invokes_hydrate_pipeline(monkeypatch, tmp_path):
    """
    With default hydrate=on, after a successful upload restore should
    drive the same kubectl-exec pipeline used by the standalone
    `hydrate` subcommand. We mock kubectl + curl so the test exercises
    the wiring without requiring a real cluster.
    """
    # Stand up moto for S3 only — the hydrate step is fully mocked below.
    from moto import mock_aws as _mock_aws
    with _mock_aws():
        sts = boto3.client("sts", region_name=REGION)
        account_id = sts.get_caller_identity()["Account"]
        _seed_source_buckets(account_id)
        _seed_target_buckets(account_id)
        out = tmp_path / "sim.tar.gz"
        _run_backup(out, account_id)

        # Mock kubectl availability + helpers.
        monkeypatch.setattr(sb.shutil, "which", lambda _x: "/usr/bin/kubectl")
        monkeypatch.setattr(sb, "_find_backend_pod", lambda ns, sel, timeout=30: "backend-abc")
        monkeypatch.setattr(sb.time, "sleep", lambda _s: None)

        posts: list[str] = []
        polls: list[str] = []

        def fake_exec_curl(namespace, pod, url, *, method="GET", timeout=30):
            if method == "POST":
                posts.append(url)
                return 0, '{"status":"started"}\n__HTTP_STATUS=202'
            polls.append(url)
            return 0, ('{"running": false, "loaded": true, "tables_with_data": 7, '
                       '"total_rows": 2830}\n__HTTP_STATUS=200')

        monkeypatch.setattr(sb, "_exec_curl", fake_exec_curl)

        rc = sb.main([
            "restore",
            "-i", str(out),
            "--target-capability", TARGET_CAP,
            "--target-env", TARGET_ENV,
            "--region", REGION,
        ])
        assert rc == 0

    # Should have POSTed to all 4 S3-backed hydrate endpoints.
    assert len(posts) == 4
    assert any("sfdc-simulator/load" in u for u in posts)
    assert any("oracle-erp-simulator/load" in u for u in posts)
    assert any("sap-simulator/load" in u for u in posts)
    assert any("external-simulator/load" in u for u in posts)
    assert len(polls) == 4  # one /load/status poll per simulator


@mock_aws
def test_restore_no_hydrate_skips_kubectl_step(monkeypatch, tmp_path):
    """The --no-hydrate opt-out leaves the kubectl pipeline alone."""
    sts = boto3.client("sts", region_name=REGION)
    account_id = sts.get_caller_identity()["Account"]
    _seed_source_buckets(account_id)
    _seed_target_buckets(account_id)
    out = tmp_path / "sim.tar.gz"
    _run_backup(out, account_id)

    # If hydrate is wrongly invoked, _exec_curl would be called and the test
    # would fail because there's no kubectl in the env.
    called = []
    monkeypatch.setattr(sb, "_exec_curl",
                        lambda *a, **k: called.append(a) or (0, ""))
    monkeypatch.setattr(sb.shutil, "which", lambda _x: "/usr/bin/kubectl")
    monkeypatch.setattr(sb, "_find_backend_pod", lambda *a, **k: "backend-abc")

    rc = _run_restore(out, no_hydrate=True)
    assert rc == 0
    assert called == []   # hydrate pipeline must not have been entered


@mock_aws
def test_force_required_to_overwrite_existing_output(tmp_path):
    sts = boto3.client("sts", region_name=REGION)
    account_id = sts.get_caller_identity()["Account"]
    _seed_source_buckets(account_id)

    out = tmp_path / "sim.tar.gz"
    out.write_bytes(b"existing")

    with pytest.raises(SystemExit):
        _run_backup(out, account_id)

    # With --force it should succeed
    rc = sb.main([
        "backup",
        "--capability", SOURCE_CAP,
        "--env", SOURCE_ENV,
        "--region", REGION,
        "-o", str(out),
        "--force",
    ])
    assert rc == 0
    # The new file is a real tarball, not the stale content
    assert out.read_bytes()[:2] == b"\x1f\x8b"  # gzip magic

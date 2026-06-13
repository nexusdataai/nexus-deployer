"""moto-based unit tests for the logical-entity backup model.

Covers:
  - preset expansion and entity validation (_resolve_entities)
  - filter-key uniqueness for the de-dup index (_filter_key)
  - GSI1 Query path for foundry-workspace entity isolation
  - Scan fallback when the GSI is absent (older operator-provisioned table)
  - JSONL filename convention (legacy vs entity-tagged)
  - de-dup of overlapping entities (react-tools + tools-registry)
  - backup -> restore round-trip with manifest 2.1
  - manifest 2.0 backwards compatibility on restore
"""
import json
import sys
from decimal import Decimal
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

import backup_restore as br
from config import (
    LOGICAL_ENTITIES,
    MANIFEST_SCHEMA_VERSION,
    NOOP_ENTITIES,
    PRESETS,
)


# ---------------------------------------------------------------------------
# Fixtures: foundry-workspace table with GSI1, and a no-GSI table for fallback
# ---------------------------------------------------------------------------

FOUNDRY_TABLE_NAME = "nexus-ai-dev-foundry-workspace"
MAPPING_TABLE_NAME = "mapping-rules"  # uses default_name (no env suffix)


def _create_foundry_with_gsi1(ddb_client):
    """Create a foundry-workspace table with GSI1 mirroring the runtime schema."""
    ddb_client.create_table(
        TableName=FOUNDRY_TABLE_NAME,
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[{
            "IndexName": "GSI1",
            "KeySchema": [
                {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
            "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        }],
        BillingMode="PROVISIONED",
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )


def _create_mapping_rules_table(ddb_client):
    ddb_client.create_table(
        TableName=MAPPING_TABLE_NAME,
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
    )


def _seed_foundry(ddb_resource):
    """Insert one row per GSI1PK value we care about, plus a couple of multi-version rows."""
    table = ddb_resource.Table(FOUNDRY_TABLE_NAME)
    rows = [
        {"PK": "SOLUTION#sol-1", "SK": "META", "GSI1PK": "SOLUTION", "GSI1SK": "alpha", "name": "Alpha"},
        {"PK": "SOLUTION#sol-2", "SK": "META", "GSI1PK": "SOLUTION", "GSI1SK": "beta",  "name": "Beta"},
        {"PK": "TOOL#tool-1",    "SK": "META", "GSI1PK": "TOOL",     "GSI1SK": "t1",    "name": "Tool One"},
        {"PK": "TOOL#tool-1",    "SK": "VERSION#1", "GSI1PK": "TOOL_VERSION", "GSI1SK": "t1#v1"},
        {"PK": "TOOL#tool-1",    "SK": "VERSION#2", "GSI1PK": "TOOL_VERSION", "GSI1SK": "t1#v2"},
        {"PK": "DASHBOARD#dash-1", "SK": "META", "GSI1PK": "DASHBOARD", "GSI1SK": "dash-1"},
        {"PK": "VIEW#view-1",    "SK": "META", "GSI1PK": "VIEW",     "GSI1SK": "view-1"},
        {"PK": "JOURNEY#j-1",    "SK": "META", "GSI1PK": "JOURNEY",  "GSI1SK": "j-1"},
        {"PK": "JOURNEY#j-2",    "SK": "META", "GSI1PK": "JOURNEY",  "GSI1SK": "j-2"},
    ]
    with table.batch_writer() as w:
        for r in rows:
            w.put_item(Item=r)


def _seed_mapping_rules(ddb_resource):
    table = ddb_resource.Table(MAPPING_TABLE_NAME)
    with table.batch_writer() as w:
        for i in range(3):
            w.put_item(Item={"id": f"MR-{i}", "virtualEntity": "Account", "status": "ACTIVE"})


# ---------------------------------------------------------------------------
# Entity resolution + filter-key (pure unit tests, no AWS)
# ---------------------------------------------------------------------------

def test_preset_business_expands_to_full_entity_list():
    out = br._resolve_entities(None, "business")
    assert out == PRESETS["business"]
    # No noops smuggled in.
    for ent in out:
        assert ent in LOGICAL_ENTITIES


def test_resolve_entities_validates_unknown():
    with pytest.raises(SystemExit):
        br._resolve_entities("not-a-thing", None)


def test_resolve_entities_accepts_noop_silently():
    # noop entities are valid CLI inputs even though they're a no-op at runtime
    out = br._resolve_entities("ai-automations,connector-apis", None)
    assert set(out) == {"ai-automations", "connector-apis"}


def test_resolve_entities_all_excludes_noops():
    out = br._resolve_entities("all", None)
    assert set(out) == set(LOGICAL_ENTITIES.keys())
    for ent in out:
        assert ent not in NOOP_ENTITIES


def test_resolve_entities_preset_plus_entities_dedup():
    # business preset already includes 'audit' — re-adding it via --entities is a no-op
    out = br._resolve_entities("audit,workflows", "business")
    assert out.count("audit") == 1
    assert out.count("workflows") == 1


def test_filter_key_distinguishes_filter_shapes():
    assert br._filter_key(None) is None
    assert br._filter_key({"gsi1pk": "SOLUTION"}) == "gsi1pk=SOLUTION"
    assert br._filter_key({"gsi1pk": "TOOL"}) != br._filter_key({"gsi1pk": "SOLUTION"})


def test_filter_key_order_invariant_for_gsi1pk_in():
    a = br._filter_key({"gsi1pk_in": ["TOOL", "TOOL_VERSION"]})
    b = br._filter_key({"gsi1pk_in": ["TOOL_VERSION", "TOOL"]})
    assert a == b
    assert a == "gsi1pk_in=TOOL,TOOL_VERSION"


# ---------------------------------------------------------------------------
# backup_ddb_filtered: GSI1 Query path
# ---------------------------------------------------------------------------

@mock_aws
def test_gsi1_query_isolates_solutions(tmp_path: Path):
    region = "us-east-1"
    client = boto3.client("dynamodb", region_name=region)
    resource = boto3.resource("dynamodb", region_name=region)
    _create_foundry_with_gsi1(client)
    _seed_foundry(resource)

    src = {"name": "foundry-workspace", "table_env": "FOUNDRY_WORKSPACE_TABLE",
           "default_suffix": "foundry-workspace"}
    result = br.backup_ddb_filtered(
        resource, src, "nexus-ai", "dev", tmp_path,
        entity="solutions", filter_spec={"gsi1pk": "SOLUTION"},
    )

    assert result["entity"] == "solutions"
    assert result["file"] == "dynamodb/foundry-workspace.solutions.jsonl"
    assert result["items"] == 2  # only the two SOLUTION rows

    out = tmp_path / "dynamodb" / "foundry-workspace.solutions.jsonl"
    lines = [json.loads(l) for l in out.read_text().splitlines() if l]
    assert {r["PK"] for r in lines} == {"SOLUTION#sol-1", "SOLUTION#sol-2"}
    # Nothing else snuck in.
    assert all(r["GSI1PK"] == "SOLUTION" for r in lines)


@mock_aws
def test_gsi1_query_gsi1pk_in_picks_multiple_values(tmp_path: Path):
    region = "us-east-1"
    client = boto3.client("dynamodb", region_name=region)
    resource = boto3.resource("dynamodb", region_name=region)
    _create_foundry_with_gsi1(client)
    _seed_foundry(resource)

    src = {"name": "foundry-workspace", "table_env": "FOUNDRY_WORKSPACE_TABLE",
           "default_suffix": "foundry-workspace"}
    result = br.backup_ddb_filtered(
        resource, src, "nexus-ai", "dev", tmp_path,
        entity="react-tools",
        filter_spec={"gsi1pk_in": ["TOOL", "TOOL_VERSION"]},
    )

    assert result["items"] == 3  # 1 TOOL + 2 TOOL_VERSION rows
    out = tmp_path / "dynamodb" / "foundry-workspace.react-tools.jsonl"
    lines = [json.loads(l) for l in out.read_text().splitlines() if l]
    assert {r["GSI1PK"] for r in lines} == {"TOOL", "TOOL_VERSION"}


# ---------------------------------------------------------------------------
# Scan fallback for tables that lack GSI1
# ---------------------------------------------------------------------------

@mock_aws
def test_scan_fallback_when_no_gsi1(tmp_path: Path):
    """A foundry-workspace clone without the GSI1 index should still resolve
    entity filters via a Scan + in-process GSI1PK match."""
    region = "us-east-1"
    client = boto3.client("dynamodb", region_name=region)
    resource = boto3.resource("dynamodb", region_name=region)

    # Bare table — no GSI1.
    legacy_name = "nexus-ai-dev-foundry-workspace-legacy"
    client.create_table(
        TableName=legacy_name,
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table = resource.Table(legacy_name)
    with table.batch_writer() as w:
        w.put_item(Item={"PK": "SOLUTION#a", "SK": "META", "GSI1PK": "SOLUTION"})
        w.put_item(Item={"PK": "TOOL#a",     "SK": "META", "GSI1PK": "TOOL"})

    src = {"name": "foundry-workspace", "default_name": legacy_name}
    result = br.backup_ddb_filtered(
        resource, src, "nexus-ai", "dev", tmp_path,
        entity="solutions", filter_spec={"gsi1pk": "SOLUTION"},
    )

    assert result["items"] == 1
    out = tmp_path / "dynamodb" / "foundry-workspace.solutions.jsonl"
    rows = [json.loads(l) for l in out.read_text().splitlines() if l]
    assert rows[0]["PK"] == "SOLUTION#a"


# ---------------------------------------------------------------------------
# Filename / shape conventions
# ---------------------------------------------------------------------------

@mock_aws
def test_filter_none_uses_legacy_filename(tmp_path: Path):
    """Whole-table backup (filter_spec=None) writes the legacy {name}.jsonl path,
    even when an entity name is supplied — so single-table entities like
    'mapping-rules' don't get a redundant '.mapping-rules' suffix."""
    region = "us-east-1"
    client = boto3.client("dynamodb", region_name=region)
    resource = boto3.resource("dynamodb", region_name=region)
    _create_mapping_rules_table(client)
    _seed_mapping_rules(resource)

    src = {"name": "mapping-rules", "table_env": "MAPPING_RULES_TABLE_NAME",
           "default_name": "mapping-rules"}
    result = br.backup_ddb_filtered(
        resource, src, "nexus-ai", "dev", tmp_path,
        entity="mapping-rules", filter_spec=None,
    )

    assert result["items"] == 3
    # No 'entity' field on the result when filter_spec is None (preserves 2.0 shape)
    assert "filter" not in result
    # Legacy filename
    assert (tmp_path / "dynamodb" / "mapping-rules.jsonl").exists()
    assert not (tmp_path / "dynamodb" / "mapping-rules.mapping-rules.jsonl").exists()


# ---------------------------------------------------------------------------
# De-dup in cmd_backup-style dispatch
# ---------------------------------------------------------------------------

def test_react_tools_and_tools_registry_collapse_to_single_job():
    """react-tools and tools-registry hit the same (foundry-workspace, gsi1pk_in=[TOOL,TOOL_VERSION])
    pair — the dispatch should produce ONE job, not two."""
    seen = {}
    for ent_name in ("react-tools", "tools-registry"):
        for tbl_name, flt in LOGICAL_ENTITIES[ent_name]["tables"]:
            key = (tbl_name, br._filter_key(flt))
            if key not in seen:
                seen[key] = ent_name
    assert len(seen) == 1
    only_key = list(seen.keys())[0]
    assert only_key == ("foundry-workspace", "gsi1pk_in=TOOL,TOOL_VERSION")


# ---------------------------------------------------------------------------
# Round-trip: backup -> restore preserves only the requested entity's rows
# ---------------------------------------------------------------------------

@mock_aws
def test_backup_restore_round_trip_solutions_only(tmp_path: Path):
    region = "us-east-1"
    client = boto3.client("dynamodb", region_name=region)
    resource = boto3.resource("dynamodb", region_name=region)
    _create_foundry_with_gsi1(client)
    _seed_foundry(resource)

    src = {"name": "foundry-workspace", "table_env": "FOUNDRY_WORKSPACE_TABLE",
           "default_suffix": "foundry-workspace"}

    # Backup
    backup_root = tmp_path / "backup"
    backup_root.mkdir()
    result = br.backup_ddb_filtered(
        resource, src, "nexus-ai", "dev", backup_root,
        entity="solutions", filter_spec={"gsi1pk": "SOLUTION"},
    )
    assert result["items"] == 2

    # New target table (different env namespace), drop+create
    target_name = "nexus-ai-test-foundry-workspace"
    client.create_table(
        TableName=target_name,
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    # Build a minimal manifest entry that restore consumes
    meta = {
        "name": "foundry-workspace",
        "entity": "solutions",
        "filter": {"gsi1pk": "SOLUTION"},
        "file": "dynamodb/foundry-workspace.solutions.jsonl",
        "items": 2,
    }
    res = br.restore_ddb_source(
        resource, meta, backup_root, "nexus-ai", "test",
        src_cap="nexus-ai", src_env="dev",
        src_acct="111", tgt_acct="222",
    )
    assert res["written"] == 2

    # Target table now has the 2 solutions and nothing else.
    target = resource.Table(target_name)
    scan = target.scan()
    assert scan["Count"] == 2
    assert {it["GSI1PK"] for it in scan["Items"]} == {"SOLUTION"}


# ---------------------------------------------------------------------------
# Back-compat: manifest 2.0 entries (no 'file', no 'entity') still restore
# ---------------------------------------------------------------------------

@mock_aws
def test_restore_reads_manifest_v20_entries(tmp_path: Path):
    region = "us-east-1"
    client = boto3.client("dynamodb", region_name=region)
    resource = boto3.resource("dynamodb", region_name=region)
    _create_mapping_rules_table(client)

    # Seed a JSONL in the v2.0 layout (dynamodb/{name}.jsonl, no entity tag)
    backup_root = tmp_path / "old-backup"
    (backup_root / "dynamodb").mkdir(parents=True)
    (backup_root / "dynamodb" / "mapping-rules.jsonl").write_text(
        json.dumps({"id": "MR-legacy", "virtualEntity": "Account"}) + "\n"
    )

    meta = {"name": "mapping-rules", "items": 1}  # v2.0-shaped entry
    res = br.restore_ddb_source(
        resource, meta, backup_root, "nexus-ai", "dev",
        src_cap="nexus-ai", src_env="dev",
        src_acct="111", tgt_acct="111",
    )
    assert res["written"] == 1
    target = resource.Table(MAPPING_TABLE_NAME)
    assert target.scan()["Count"] == 1


# ---------------------------------------------------------------------------
# Manifest schema version is the new one
# ---------------------------------------------------------------------------

def test_manifest_schema_version_bumped():
    assert MANIFEST_SCHEMA_VERSION == "2.1"


# ---------------------------------------------------------------------------
# Regression: --entities/--preset composes ADDITIVELY with --include
# ---------------------------------------------------------------------------

def _resolve_components(args_namespace):
    """Mirror the resolution logic from cmd_backup / cmd_restore so we can
    unit-test it without spinning up moto + a fake AWS session."""
    from config import COMPONENTS, DEFAULT_COMPONENTS

    entities = br._resolve_entities(
        getattr(args_namespace, "entities", None),
        getattr(args_namespace, "preset", None),
    )
    user_include = br._parse_csv(
        getattr(args_namespace, "include", None), COMPONENTS, "component"
    )
    if entities:
        components = {"s3", "dynamodb"} | (user_include or set())
    else:
        components = user_include if user_include is not None else DEFAULT_COMPONENTS.copy()
    excluded = br._parse_csv(
        getattr(args_namespace, "exclude", None), COMPONENTS, "component"
    ) or set()
    return components - excluded


class _Args:
    def __init__(self, **kw):
        self.entities = kw.get("entities")
        self.preset = kw.get("preset")
        self.include = kw.get("include")
        self.exclude = kw.get("exclude")


def test_preset_plus_include_composes_additively():
    """The reported bug: --preset business --include ssm,secrets,glue
    must keep s3 + dynamodb AND add the infra components, not replace."""
    comps = _resolve_components(_Args(preset="business", include="ssm,secrets,glue"))
    assert comps == {"s3", "dynamodb", "ssm", "secrets", "glue"}


def test_entities_alone_defaults_to_s3_dynamodb():
    comps = _resolve_components(_Args(entities="solutions,workflows"))
    assert comps == {"s3", "dynamodb"}


def test_entities_plus_exclude_drops_component():
    comps = _resolve_components(_Args(preset="business", exclude="s3"))
    assert comps == {"dynamodb"}


def test_no_entities_include_still_replaces_default():
    """Back-compat: without --entities, --include replaces DEFAULT_COMPONENTS."""
    comps = _resolve_components(_Args(include="ssm"))
    assert comps == {"ssm"}


def test_no_entities_no_include_uses_default_components():
    from config import DEFAULT_COMPONENTS
    comps = _resolve_components(_Args())
    assert comps == DEFAULT_COMPONENTS

"""
Backup source definitions for all S3 buckets, DynamoDB tables, SSM
parameters, AWS Secrets Manager secrets, Glue catalog, Cognito pools,
Kubernetes state (via Velero), and the BSS Magic Postgres dump.

Bucket names follow two conventions depending on provisioner version:
  - New:  {capability}-{env}-{suffix}-{account_id}
  - Old:  {capability}-{env}-{suffix}

The tool auto-discovers which exists via a HeadBucket probe.

Resource-name conventions (per kube-operator ResourceNaming, see
nexus-deployer/kube-operator/src/nexus_operator/utils/naming.py):
  DynamoDB  : {capability}-{env}-{purpose}
  S3 bucket : {capability}-{env}-{purpose}[-{account_id}]
  SSM path  : /{capability}/{env}/{category}/{key}
  Secrets   : {capability}/{env}/{secret-type}
  Glue DB   : {capability}_{env}_db
  Cognito   : {capability}-{env}
"""

from typing import Dict, List, Optional, Set

CAPABILITY = "nexus-ai"
MANIFEST_SCHEMA_VERSION = "2.1"

# ----------------------------------------------------------------------------
# "Groups" = logical groupings of S3 + DynamoDB sources (--only flag)
# "Components" = top-level resource categories (--include / --exclude flag)
# ----------------------------------------------------------------------------

GROUPS: Set[str] = {"simulators", "knowledge", "journeys", "config", "observability"}

COMPONENTS: Set[str] = {
    "s3",
    "dynamodb",
    "ssm",
    "secrets",
    "glue",
    "cognito",
    "kubernetes",
    "postgres",
}

DEFAULT_COMPONENTS: Set[str] = {
    "s3", "dynamodb", "ssm", "secrets", "glue", "kubernetes", "postgres",
    # cognito is optional: only meaningful when the capability enables auth
}

# ----------------------------------------------------------------------------
# S3 sources — buckets the operator provisions per capability/env
# ----------------------------------------------------------------------------

S3_SOURCES: List[Dict] = [
    # ── Simulator dumps ──────────────────────────────────────────────────
    {
        "name": "sfdc-simulator",
        "bucket_env": "SFDC_SIMULATOR_BUCKET",
        "prefix_env": "SFDC_SIMULATOR_PREFIX",
        "default_suffix": "sfdc-simulator",
        "default_prefix": "sfdc-simulator",
        "group": "simulators",
    },
    {
        "name": "oracle-erp-simulator",
        "bucket_env": "ORACLE_ERP_SIMULATOR_BUCKET",
        "prefix_env": "ORACLE_ERP_SIMULATOR_PREFIX",
        "default_suffix": "oracle-erp-simulator",
        "default_prefix": "oracle-erp-simulator",
        "group": "simulators",
    },
    {
        "name": "sap-simulator",
        "bucket_env": "SAP_SIMULATOR_BUCKET",
        "prefix_env": "SAP_SIMULATOR_PREFIX",
        "default_suffix": "sap-simulator",
        "default_prefix": "sap-simulator",
        "group": "simulators",
    },
    {
        "name": "wxcc-simulator",
        "bucket_env": "WXCC_SIMULATOR_BUCKET",
        "prefix_env": "WXCC_SIMULATOR_PREFIX",
        "default_suffix": "wxcc-simulator",
        "default_prefix": "wxcc-simulator",
        "group": "simulators",
    },
    {
        "name": "external-sources",
        "bucket_env": "EXTERNAL_SIMULATOR_BUCKET",
        "prefix_env": "EXTERNAL_SIMULATOR_PREFIX",
        "default_suffix": "external-simulator",
        "default_prefix": "external-sources",
        "group": "simulators",
    },
    {
        "name": "tpm-simulator",
        "bucket_env": "TPM_SIMULATOR_BUCKET",
        "prefix_env": "TPM_SIMULATOR_PREFIX",
        "default_suffix": "tpm-simulator",
        "default_prefix": "tpm-simulator",
        "group": "simulators",
    },
    {
        "name": "sourcing-simulator",
        "bucket_env": "SOURCING_SIMULATOR_BUCKET",
        "prefix_env": "SOURCING_SIMULATOR_PREFIX",
        "default_suffix": "sourcing-simulator",
        "default_prefix": "sourcing-simulator",
        "group": "simulators",
    },
    # NOTE: The historical `call-data` bucket source was removed when
    # call processing was retired as a feature. Its `include_prefixes`
    # subdirectories (onto-data/, onto-bundles/, o2c-kpis/, app-data/)
    # are not preserved by this DR tool.
    # ── Journey artifacts ────────────────────────────────────────────────
    {
        "name": "journey-logs",
        "bucket_env": "S3_JOURNEY_LOGS_BUCKET",
        "default_suffix": "journey-logs",
        "default_prefix": "",
        "group": "journeys",
    },
    {
        "name": "journey-reports",
        "bucket_env": "S3_JOURNEY_REPORTS_BUCKET",
        "default_suffix": "journey-reports",
        "default_prefix": "",
        "group": "journeys",
    },
    {
        "name": "solution-results",
        "bucket_env": "SOLUTION_RESULTS_BUCKET",
        "default_suffix": "solution-results",
        "default_prefix": "",
        "group": "journeys",
    },
    # ── BSS Magic dumps (Postgres snapshots produced by bssmagic) ────────
    {
        "name": "bssmagic-dumps",
        "default_suffix": "bssmagic-dumps",
        "default_prefix": "",
        "group": "knowledge",
    },
    # ── Observability (Mimir TSDB blocks) ────────────────────────────────
    {
        "name": "mimir-blocks",
        "default_suffix": "mimir-blocks",
        "default_prefix": "",
        "group": "observability",
    },
]

# ----------------------------------------------------------------------------
# DynamoDB sources — tables the operator provisions per capability/env
# ----------------------------------------------------------------------------

DYNAMODB_SOURCES: List[Dict] = [
    # ── Core journey + foundry state ─────────────────────────────────────
    {"name": "transformation-system", "table_env": "DYNAMODB_TABLE",
     "default_suffix": "transformation-system", "group": "journeys"},
    {"name": "foundry-workspace", "table_env": "FOUNDRY_WORKSPACE_TABLE",
     "default_suffix": "foundry-workspace", "group": "journeys"},
    # ── Configuration / control plane ────────────────────────────────────
    {"name": "license", "table_env": "LICENSE_TABLE",
     "default_suffix": "license", "group": "config"},
    {"name": "wxcc-task-tracking", "table_env": "WXCC_TASK_TABLE",
     "default_suffix": "wxcc-task-tracking", "group": "config"},
    {"name": "sessions", "table_env": "SESSIONS_TABLE",
     "default_suffix": "sessions", "group": "config"},
    {"name": "audit-log", "table_env": "AUDIT_LOG_TABLE",
     "default_suffix": "audit-log", "group": "config"},
    {"name": "lead-opportunity-tracking", "table_env": "LEAD_TRACKING_TABLE",
     "default_suffix": "lead-opportunity-tracking", "group": "config"},
    {"name": "rbac", "default_suffix": "rbac", "group": "config"},
    {"name": "connector-settings", "default_suffix": "connector-settings",
     "group": "config"},
    # ── Tables that historically used unprefixed default names ───────────
    {"name": "mapping-rules", "table_env": "MAPPING_RULES_TABLE_NAME",
     "default_name": "mapping-rules", "group": "config"},
    {"name": "data-planes", "default_name": "data-planes", "group": "config"},
    # ── Control-plane audit log (added with the logical-entity model) ────
    {"name": "control-plane-audit", "table_env": "CONTROL_PLANE_AUDIT_TABLE",
     "default_suffix": "control-plane-audit", "group": "config"},
]

# ----------------------------------------------------------------------------
# Logical entity model
# ----------------------------------------------------------------------------
#
# Lets the operator say "back up workflows / solutions / connectors / ..."
# instead of "back up these specific tables and S3 buckets". Each logical
# entity expands to a list of (table, filter_spec) pairs and/or S3 bucket
# source names from the structures above.
#
# Filter-spec dict shapes accepted by backup_ddb_filtered:
#   None                          -> full table scan (legacy behaviour)
#   {"gsi1pk": "<value>"}         -> Query(IndexName="GSI1",
#                                          KeyConditionExpression=GSI1PK eq <value>)
#   {"gsi1pk_in": [<value>, ...]} -> one Query per value, results concatenated
#
# If the table has no GSI1, the runtime falls back to a Scan with an
# in-process filter on the GSI1PK attribute, so the entity model still
# works on older operator-provisioned tables.
#
# Tables referenced here are looked up by "name" against DYNAMODB_SOURCES;
# buckets are looked up by "name" against S3_SOURCES.

LOGICAL_ENTITIES: Dict[str, Dict] = {
    "virtual-data": {
        "tables": [("mapping-rules", None)],
        "buckets": ["sfdc-simulator", "oracle-erp-simulator", "sap-simulator",
                    "wxcc-simulator", "external-sources", "tpm-simulator",
                    "sourcing-simulator"],
    },
    "mapping-rules": {
        "tables": [("mapping-rules", None)],
    },
    "connectors": {
        "tables": [("data-planes", None), ("connector-settings", None)],
    },
    "policies": {
        # Business policy docs live in repo YAML (enterprise-knowledge/policies/*.md)
        # and are not DR-backed. Only RBAC config is on the DDB side.
        "tables": [("rbac", None)],
    },
    "workflows": {
        # Saved/builder defs in foundry-workspace (GSI1PK=JOURNEY) +
        # runtime execution state in transformation-system. The latter is
        # a whole-table scan; expect this to be slow on busy clusters.
        "tables": [
            ("foundry-workspace", {"gsi1pk": "JOURNEY"}),
            ("transformation-system", None),
        ],
    },
    "react-tools": {
        "tables": [("foundry-workspace", {"gsi1pk_in": ["TOOL", "TOOL_VERSION"]})],
    },
    "tools-registry": {
        # Alias of react-tools — same DDB rows.
        "tables": [("foundry-workspace", {"gsi1pk_in": ["TOOL", "TOOL_VERSION"]})],
    },
    "solutions": {
        "tables": [("foundry-workspace", {"gsi1pk": "SOLUTION"})],
    },
    "analytics": {
        "tables": [("foundry-workspace", {"gsi1pk_in": ["DASHBOARD", "VIEW"]})],
        "buckets": ["solution-results"],
    },
    "audit": {
        "tables": [("control-plane-audit", None)],
    },
}

# Entities whose source-of-truth is the git repo / container image rather
# than DynamoDB or S3. Accepted on the CLI but logged-and-skipped at
# runtime — restore happens implicitly by deploying the same image.
NOOP_ENTITIES: Set[str] = {
    "integration-rules",
    "ai-automations",
    "connector-apis",
    "business-policies",
    "workflow-templates",
}

# Curated bundles for the --preset flag.
PRESETS: Dict[str, List[str]] = {
    "business": [
        "virtual-data", "mapping-rules", "connectors", "policies",
        "workflows", "react-tools", "tools-registry", "solutions",
        "analytics", "audit",
    ],
}

# ----------------------------------------------------------------------------
# SSM Parameter Store
# ----------------------------------------------------------------------------

def ssm_prefix(capability: str, env: str) -> str:
    """Recursive Parameter Store prefix for backup/restore."""
    return f"/{capability}/{env}/"


# ----------------------------------------------------------------------------
# Secrets Manager
# ----------------------------------------------------------------------------

# Operator-provisioned secret types. Naming pattern: {capability}/{env}/{type}
# See nexus-deployer/kube-operator/src/nexus_operator/resources/secrets.py
SECRET_TYPES: List[str] = [
    "api-keys",
    "wxcc",
    "openai",
    "license",
    "anthropic",
    "github",
    "bssmagic-credentials",   # binary zip
    "bssmagic-axway-config",
]

# Secret types whose value is binary (base64-encoded into tarball JSON)
BINARY_SECRET_TYPES: Set[str] = {"bssmagic-credentials"}


def secret_name(capability: str, env: str, secret_type: str) -> str:
    return f"{capability}/{env}/{secret_type}"


def secrets_prefix(capability: str, env: str) -> str:
    """Filter prefix used by ListSecrets."""
    return f"{capability}/{env}/"


# ----------------------------------------------------------------------------
# Glue
# ----------------------------------------------------------------------------

def glue_database_name(capability: str, env: str) -> str:
    """Glue uses underscores (DBs can't have hyphens)."""
    return f"{capability.replace('-', '_')}_{env}_db"


# ----------------------------------------------------------------------------
# Cognito
# ----------------------------------------------------------------------------

def cognito_pool_name(capability: str, env: str) -> str:
    return f"{capability}-{env}"


# ----------------------------------------------------------------------------
# Kubernetes
# ----------------------------------------------------------------------------

def k8s_namespace(capability: str, env: str) -> str:
    return f"{capability}-{env}"


def nexus_capability_name(capability: str, env: str) -> str:
    """Name of the NexusCapability CR."""
    return f"{capability}-{env}"


# ----------------------------------------------------------------------------
# BSS Magic Postgres
# ----------------------------------------------------------------------------

def bssmagic_statefulset_pod(capability: str, env: str, ordinal: int = 0) -> str:
    return f"{capability}-{env}-bssmagic-{ordinal}"


BSSMAGIC_PG_DATABASE = "bssmagic"
BSSMAGIC_PG_USER = "postgres"
BSSMAGIC_PG_PORT = 5432


# ----------------------------------------------------------------------------
# Name resolvers (env aware)
# ----------------------------------------------------------------------------

def _env(key: str) -> str:
    import os
    return os.environ.get(key, "")


def resolve_bucket_name(src: Dict, capability: str, env: str,
                        account_id: Optional[str] = None,
                        s3_client=None) -> str:
    """Resolve the real S3 bucket name, probing with account-ID suffix first."""
    env_val = _env(src.get("bucket_env", ""))
    if env_val:
        return env_val

    base = f"{capability}-{env}-{src['default_suffix']}"

    if not account_id or not s3_client:
        return base

    candidates = [f"{base}-{account_id}", base]
    for candidate in candidates:
        try:
            s3_client.head_bucket(Bucket=candidate)
            return candidate
        except Exception:
            continue
    return base


def resolve_prefix(src: Dict) -> str:
    env_key = src.get("prefix_env", "")
    if env_key:
        val = _env(env_key)
        if val:
            return val
    return src.get("default_prefix", "")


def resolve_table_name(src: Dict, capability: str, env: str) -> str:
    env_key = src.get("table_env", "")
    if env_key:
        val = _env(env_key)
        if val:
            return val
    if "default_name" in src:
        return src["default_name"]
    return f"{capability}-{env}-{src['default_suffix']}"

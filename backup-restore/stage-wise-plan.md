# Plane-scoped backup/restore for Nexus AI

Reference: [nexus-docs/docs/architecture/data-organization.md](../../nexus-docs/docs/architecture/data-organization.md)

The DR layout mirrors the data-organization spec's five planes. Each
plane produces one tarball; restore walks them in the order AI-Ops →
Data → Control → Reasoning → Workspace.

```
plane_backup.py backup --plane ai_ops   --out plane-ai-ops.tar.gz
plane_backup.py backup --plane data     --out plane-data.tar.gz
plane_backup.py backup --plane control  --out plane-control.tar.gz
plane_backup.py backup --plane reasoning --out plane-reasoning.tar.gz
plane_backup.py backup --plane workspace --out plane-workspace.tar.gz
plane_backup.py backup --all --out-dir ./out
plane_backup.py restore-all --dir ./out --target-capability nexus-ai --target-env stage
```

The plane-to-content mapping is authoritative in
`nexus-backend/src/services/planes.py` and mirrored in
`plane_backup.py::PLANE_PREFIXES` + `PLANE_EXTERNAL_TABLES`.

---

## AI-OPs plane

Consists of: **Simulators + Simulated Data + AI Diagnostic Data + AI Health Central Data.**

Simulator generated data is stored in S3; served through Redis (Redis
initializes the simulator data at bootstrap). AI diagnostics + AI Health
are automated workflows defined in the AI engine.

**Where it is persisted:**
- Simulator identity + per-table shape metadata: DynamoDB `SIM#` in
  foundry-workspace.
- Simulator row data: S3 per-simulator buckets + Redis warm store.
- AI diagnostics history: DynamoDB `{capability}-{env}-diagnostics` table.
- AI Health snapshots: DynamoDB `{capability}-{env}-health` table.

**Backup:** TAR of SIM# rows + diagnostics + health tables + the S3
simulator buckets via `simulator_backup.py`. Redis is not backed up
(rebuilt via `POST /api/v1/{sim}/load` after S3 restore).

## Data plane

Consists of: **Data Plane Definition Metadata + Data Sources Definition
Metadata + Virtual Data + Virtual Data API Registry + Mapping Rules +
Connectors + Connector-Settings + Connector API Registry + Connector
Diagnostics.**

The FDW Runtime routes across simulator / ERP DB / Athena / File / Social
/ TimeSeries. VDL APIs act on virtual entities and dispatch to Connector
APIs, which in turn either issue SQL via FDW or call third-party REST.

**Where it is persisted:** all of the above in DynamoDB foundry-workspace
rows: `DATAPLANE#`, `DATASOURCE#`, `VDLENTITY#`, `VDLAPI#`, `CONNECTOR#`,
`CONNAPI#` (+ `AUDIT#…` for connector diagnostics), `CONNECTORSETTING#`,
`MAPPINGRULE#`. Per-source `simulator | real` mode toggles live in SSM
under `/{capability}/{env}/data_source_mode/`.

**Backup:** TAR of the above prefixes + an SSM export of
`data_source_mode/*`. Connector audit rows travel with `CONNAPI#`.

## Control plane

Consists of: **Knowledge Pipeline + Knowledge Index + Knowledge Graph +
Policy Editor + Workflow Editor + Integration Rules Editor + ReAct Tools
Registry.**

**Where it is persisted:**
- Policies / workflows / integration rules → foundry-workspace
  `POLICY#`, `WORKFLOWDEF#`, `INTEGRATIONDEF#`.
- Knowledge pipeline metadata + run history → foundry-workspace `KP#`.
- Knowledge Index → pgvector `control_plane_embeddings` (regenerated).
- Knowledge Graph → Apache AGE `enterprise_onto` (regenerated).

**Backup:** TAR of `POLICY#`, `WORKFLOWDEF#`, `INTEGRATIONDEF#`, `KP#`.
pgvector + Apache AGE are excluded by design - the Knowledge Processor
rebuilds them post-restore.

## Reasoning plane

Consists of: **AI Co-Pilot + Planning Playground + ReAct Tools + Tools
Registry + Tool Builder.** Co-Pilot and Planning Playground are
transient (Redis with TTL, not backed up).

**Where it is persisted:**
- ReAct Tools catalog (built-ins + user tools): foundry-workspace
  `TOOLREG#` (registry projection) + `TOOL#` (user Tool Builder rows).

**Backup:** TAR of `TOOLREG#` + `TOOL#` rows (with VERSION/TAG
sub-rows). Copilot Redis sessions are ephemeral.

## Workspace plane

Consists of: **AI Automations + AI Analytics/Dashboards + AI Solutions +
Role Based Access Control.**

**Where it is persisted:**
- Solutions view mapping → foundry-workspace `SOLUTION#`.
- Solutions YAML (NLP-indexed) → foundry-workspace `SOLUTIONYAML#`.
- Analytics: `VIEW#`, `DASHBOARD#`.
- Automations: `AUTOMATION#` (playbooks) + `JOURNEY#` (Copilot saved).
- RBAC: dedicated `{capability}-{env}-rbac` table.

**Backup:** TAR of the above prefixes plus a full dump of the `rbac`
table.

---

## How to go about it

Rollout follows the spec's ordering:

1. AI-Ops first (S3 buckets + SIM# + diagnostics + health).
2. Data / Control / Reasoning planes (foundry-workspace slices).
3. Workspace last (solutions + views + dashboards + journeys + RBAC).

`plane_backup.py restore-all --dir ./out` runs them in that order. The
legacy `foundry_backup.py` and `simulator_backup.py` are kept as
deprecation shims that forward to `plane_backup.py`.

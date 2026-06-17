# Nexus Data Backup & Restore

A staged rewrite of the original kitchen-sink DR tool. The new design separates
**data** (what the user owns) from **infrastructure** (what the operator
provisions from the CR). The DR tool's job is the former; the latter is
already idempotent via `kubectl apply -f nexus-ai-capability.yaml`.

| Stage | Tool | Scope |
|---|---|---|
| **Stage 1 (this PR)** | `simulator_backup.py` | Simulator S3 data (5 active buckets + 2 synthetic placeholders) + post-restore Redis hydration |
| **Stage 2 (next)**    | `entities_backup.py`  | Business entities (DynamoDB + dependent S3) |
| **Future**            | (no tooling planned)  | SSM / Secrets / Glue / Cognito / Velero / Postgres — covered by re-applying the operator's CR on the target cluster |

The original kitchen-sink CLI is preserved unchanged in [`_archive/`](_archive/)
for reference and will be deleted once Stage 2 lands.

---

## Stage 1 — Simulator Data Backup & Restore

### What gets backed up

The DR tool enumerates seven simulators, but they fall into three categories
based on how their backend stores data. **Only categories 1 and 2 produce
real bytes in a backup.**

| Category | Logical name | Bucket suffix | UI sources it serves | Why |
|---|---|---|---|---|
| 1. S3-backed (real exported data) | `sfdc-simulator`       | `sfdc-simulator`       | Salesforce CRM       | Multi-MB SFDC export, persistent across pod restarts |
| 1. S3-backed (real exported data) | `oracle-erp-simulator` | `oracle-erp-simulator` | Oracle ERP           | Multi-MB Oracle ERP export |
| 1. S3-backed (real exported data) | `sap-simulator`        | `sap-simulator`        | SAP S/4HANA          | SAP master data export |
| 1. S3-backed (legacy)             | `wxcc-simulator`       | `wxcc-simulator`       | (internal WxCC)      | Legacy contact-center data |
| 2. S3-backed (user-loaded)        | `external-sources`     | `external-simulator`   | File Uploads / Google Drive / Social Listening | Single bucket, separate prefixes per UI source. Often empty on fresh clusters until users upload. |
| 3. Synthetic Redis-only           | `tpm-simulator`        | `tpm-simulator`        | TPM Simulator        | Generated from `random.seed(42)` on every pod boot — see `tpm_simulator_service.py:seed_data()`. **Operator never provisions this bucket.** |
| 3. Synthetic Redis-only           | `sourcing-simulator`   | `sourcing-simulator`   | Sourcing Simulator   | Same pattern as TPM. **Operator never provisions this bucket.** |

Real bucket names follow `{capability}-{env}-{suffix}-{account_id}` (with
`{capability}-{env}-{suffix}` as a legacy fallback). Both variants are probed
at runtime.

Category 3 simulators are listed in the manifest with `bucket: null` and
`key_count: 0`. They cost nothing to enumerate and serve as a record that
they were considered. **Their data is not lost across DR** — it
regenerates deterministically on the target cluster when the pod boots.

Buckets that are configured but absent on a particular cluster (e.g.
`external-simulator` on older operator versions, or any of the simulators
on a partially-provisioned dev cluster) are gracefully skipped with a
clear "not provisioned" log line, not treated as an error.

### What is NOT included

- DynamoDB tables (mapping rules, connectors, solutions, workflows, etc.) →
  **Stage 2**.
- Simulator DB schemas (`sfdc_itxp2dev`, etc. in Postgres) — the simulator
  backend regenerates these from the S3 dumps on first boot.
- SSM, Secrets Manager, Glue, Cognito, Velero, Postgres dumps — out of scope.
  These are deterministically reconstructable from the operator's CR on the
  target cluster.

### Backup

```bash
python3 simulator_backup.py backup \
    --capability nexus-ai \
    --env prod \
    --profile promode2 \
    -o sim-backup-prod-$(date +%Y%m%d).tar.gz
```

Output is one `.tar.gz` shaped like:

```
sim-backup-prod-20260615/
  manifest.json
  s3/
    sfdc-simulator/objects/sfdc_itxp2dev/account.csv
    sfdc-simulator/objects/sfdc_itxp2dev/...
    oracle-erp-simulator/schemas/...
    sap-simulator/...
    wxcc-simulator/...
    external-sources/...
    tpm-simulator/...
    sourcing-simulator/...
```

Empty buckets are recorded in the manifest with `key_count: 0` but produce no
sub-directory in the tarball.

### Restore

Always do a dry-run first when crossing accounts or environments:

```bash
python3 simulator_backup.py restore \
    -i sim-backup-prod-20260615.tar.gz \
    --target-capability nexus-ai \
    --target-env test \
    --target-profile new-account \
    --dry-run
```

Once the output looks right, drop `--dry-run`. The restore is:

- **Idempotent** — keys are uploaded by path; re-running overwrites.
- **All-or-nothing** — there is no per-simulator selection (use the operator's
  S3 lifecycle policies if you need finer control).
- **Refusing to create buckets** — the target buckets must already exist
  (operator provisions them). Restore fails fast with a clear error if any are
  missing.
- **Clean + hydrate by default** — see below.

Cross-account / cross-env rename happens implicitly: bucket names are resolved
fresh on the target side from `{target_capability}-{target_env}-{suffix}-{target_account_id}`.

#### Clean target prefix before upload (default ON)

Before uploading, restore lists every key under each target bucket's
`{simulator-name}/` prefix and deletes them. This prevents the failure
mode where a previous tenant's dump (e.g. a 1661-table `starhub_itxp2dev`
catalog) survives alongside a fresh restore of a different tenant's
245-table `sfdc_itxp2dev` dump — the simulator pods would otherwise
load a confused mix of new data files and old `tables.json` / catalog
metadata.

| Flag         | Behaviour |
|--------------|-----------|
| (default)    | Delete every key under the prefix before upload |
| `--no-clean` | Leave pre-existing keys alone (use when you've manually staged something you want preserved) |
| `--dry-run`  | Print "would delete N stale keys" without deleting |

#### Auto-hydrate target simulators after upload (default ON)

The simulator pods cache their S3-derived catalog in memory at first
read. Once `_loaded = True` is set, the pod will NOT re-read S3 even
when its row counts are zero. So a restore that successfully writes
to S3 still leaves the pods showing stale data until they restart.

By default, after upload completes, restore invokes the same logic as
the `hydrate` subcommand — `kubectl exec` into a Running backend pod
and POSTs to `/api/v1/{simulator}/load` for each S3-backed simulator,
polling `/load/status` until each reports `running=false`.

| Flag                | Behaviour |
|---------------------|-----------|
| (default)           | Hydrate all 4 S3-backed simulators after upload |
| `--no-hydrate`      | Skip the kubectl step (use when running from a CI box without cluster access; remember to run `simulator_backup.py hydrate ...` later) |
| `--hydrate-timeout` | Per-simulator status-poll timeout in seconds (default 300) |

The hydrate step uses the local `kubectl` context, so ensure your
kubeconfig points at the target cluster:

```bash
aws eks update-kubeconfig --name {target-cluster} --profile {target-profile}
```

If `kubectl` is not on PATH, restore prints a clear "skipped, run
hydrate manually" message instead of failing.

### Hydrate (post-restore — important!)

A successful `restore` writes objects into S3, but the simulator services
have an in-memory `_loaded` flag that's sticky for the lifetime of the
backend pod. Pods that were running *before* the restore have already
cached "no S3 data available" and won't auto re-check the bucket. You must
explicitly tell each simulator to (re-)hydrate from S3 into Redis:

```bash
python3 simulator_backup.py hydrate \
    --capability nexus-ai \
    --env prod
```

By default this targets all four S3-backed simulators (`sfdc-simulator`,
`oracle-erp-simulator`, `sap-simulator`, `external-sources`) on the
kubectl context's current cluster. It POSTs to each simulator's
`/api/v1/{simulator}/load` admin endpoint via `kubectl exec` against a
Running backend pod, then polls `/load/status` until each simulator
reports `running=false`.

| Flag                | Purpose |
|---------------------|---------|
| `--capability NAME` | Used to derive defaults (default `nexus-ai`) |
| `--env ENV`         | Target environment (required) |
| `--namespace NS`    | Override the `{capability}-{env}` namespace default |
| `--label-selector S`| Override the `app={capability}-{env}-backend` pod selector |
| `--simulators a,b`  | Comma-separated subset (default: all 4 S3-backed) |
| `--timeout N`       | Per-simulator status-poll timeout in seconds (default 300) |
| `--no-wait`         | Fire POST and return immediately; don't poll status |

`hydrate` requires the local `kubectl` to be authenticated against the
target cluster. Use `aws eks update-kubeconfig --name <cluster> --profile <profile>`
first if needed.

Alternatives if `kubectl exec` isn't an option:

- **From the UI**: open the *Simulators* page in the backend UI and click
  the **Load Data** button on each simulator tab.
- **Force re-init by restarting backend pods**: `kubectl -n {ns} rollout
  restart deployment/{cap}-{env}-backend`. On their first request after
  restart the simulators will auto-load from S3.

### Pre-requisites on the target cluster

The DR tool restores **data**, not infrastructure. Before you run `restore`,
make sure the target installation is healthy:

1. Target EKS cluster created and reachable
2. Operator deployed and reconciling
3. `NexusCapability` CR applied with the target env (operator provisions the
   empty target buckets, IAM roles, etc.)
4. The simulator pods can be in any state — restore writes directly to S3, the
   simulator backend rehydrates from the buckets on its next boot

### Manifest schema

```json
{
  "schema_version": "stage1.simulator.v1",
  "created_at": "2026-06-15T18:30:00+00:00",
  "source_capability": "nexus-ai",
  "source_env": "prod",
  "source_account_id": "040740747817",
  "source_region": "us-east-1",
  "simulators": [
    {
      "name": "sfdc-simulator",
      "bucket": "nexus-ai-prod-sfdc-simulator-040740747817",
      "key_count": 142,
      "bytes": 9384210
    },
    ...
  ]
}
```

A future Stage 2 tarball will use schema `stage2.entities.v1` and live next to
this one in the same archive directory.

### CLI reference

```text
simulator_backup.py backup
  --capability    Capability name        (default: nexus-ai)
  --env           Source env             (required)
  --profile       AWS profile            (boto3 default if omitted)
  --region        AWS region             (boto3 default if omitted)
  --max-workers   Parallel S3 transfers  (default: 16)
  -o, --output    Destination .tar.gz    (required)
  --force         Overwrite existing output

simulator_backup.py restore
  -i, --input              Source .tar.gz                (required)
  --target-capability      Target capability             (default: same as source)
  --target-env             Target env                    (default: same as source)
  --target-profile         AWS profile for target        (boto3 default if omitted)
  --region                 AWS region                    (boto3 default if omitted)
  --max-workers            Parallel S3 transfers         (default: 16)
  --dry-run                Print what would happen, write nothing
  --no-clean               Skip deleting stale keys under the target prefix (default: clean)
  --no-hydrate             Skip the post-upload kubectl hydrate step (default: hydrate)
  --hydrate-timeout        Per-sim status-poll timeout (s) (default: 300)

simulator_backup.py hydrate
  --capability             Capability name               (default: nexus-ai)
  --env                    Target env                    (required)
  --namespace              K8s namespace                 (default: {cap}-{env})
  --label-selector         Pod selector                  (default: app={cap}-{env}-backend)
  --simulators             Comma-separated subset        (default: all 4 S3-backed)
  --timeout                Per-sim poll timeout (s)      (default: 300)
  --no-wait                Fire POST and return; no poll
```

---

## Tests

```bash
cd nexus-deployer/backup-restore
python3 -m pytest tests/ -v
```

Uses `moto >= 5` to mock S3 + STS in-process. No AWS credentials needed.

---

## Roadmap — Stage 2 (DynamoDB-backed business entities)

The Stage 2 deliverable (`entities_backup.py`) will let you back up / restore
the following logical business entities, each mapped to its DynamoDB storage:

| Entity              | Storage |
|---------------------|---|
| `virtual-data`      | `foundry-workspace#VDLENTITY` + `#MAPPINGRULE` (+ simulator buckets, via Stage 1) |
| `mapping-rules`     | `foundry-workspace#MAPPINGRULE` |
| `connectors`        | `foundry-workspace#CONNECTOR` + `#CONNECTORSETTING` |
| `connector-settings`| folded into `connectors` |
| `connector-apis`    | `foundry-workspace#CONNECTOR/SK=API#…` |
| `solutions`         | `foundry-workspace#SOLUTION` |
| `analytics`         | `foundry-workspace#DASHBOARD` + `#VIEW` + `solution-results` S3 |
| `workflows`         | `foundry-workspace#JOURNEY` + `transformation-system` |
| `react-tools` / `tools-registry` | `foundry-workspace#TOOL` + `#TOOL_VERSION` |
| `policies` / `rbac` | `rbac` DDB |
| `integration-rules` | repo YAML (no-op — restored implicitly by deploying the same image) |
| `ai-automations`    | repo YAML (no-op) |

Stage 2 will reuse Stage 1's tarball/manifest patterns and CLI conventions.

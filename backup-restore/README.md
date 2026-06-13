# Nexus DR Backup & Restore

A single Python CLI that produces a portable tarball containing **everything**
needed to clone a Nexus capability (`nexus-ai-dev`, etc.) into another AWS
account and EKS cluster:

- S3 buckets (simulator dumps, journey logs/reports, bssmagic-dumps, mimir blocks)
- DynamoDB tables (transformation-system, foundry-workspace, license, …)
- SSM Parameter Store (`/nexus-ai/dev/*`)
- AWS Secrets Manager (`nexus-ai/dev/*`)
- Glue catalog (database + tables + partitions)
- Cognito user pool (config + groups + clients + users)
- Kubernetes state via Velero (Deployments, Services, ConfigMaps, CRs, **PVCs**)
- BSS Magic Postgres `pg_dump` (belt-and-suspenders on top of Velero PV)

On restore, all env-bearing resource names are rewritten
(`{capability}-{src-env}-…` → `{capability}-{tgt-env}-…`) and account IDs in
ARNs/URIs are swapped, so the same tarball can populate dev → test, dev →
prod, or dev-in-account-A → dev-in-account-B.

> **Prerequisites**: `kubectl`, `velero` CLI v1.14+, and `boto3` on the
> workstation. Velero must be installed in both source and target clusters
> (one-time bootstrap — see
> [`nexus-deployer/deploy/eks/USAGE.md`](../../../nexus-deployer/deploy/eks/USAGE.md#dr--backup-restore-prerequisite--install-velero)).

---

## Quick reference

```bash
# Full backup (source side)
python3 backup_restore.py backup \
    --env dev --capability nexus-ai \
    --profile ptr-tech \
    --cluster nexus-dev \
    --velero-bucket nexus-velero-backups-654654554404 \
    -o nexus-dr-dev-$(date +%Y%m%d).tar.gz

# Cross-account restore (env rename dev → test)
python3 backup_restore.py restore \
    -i nexus-dr-dev-20260531.tar.gz \
    --target-env test \
    --target-profile new-account \
    --target-cluster nexus-test \
    --target-velero-bucket nexus-velero-backups-NEWACCT \
    --dry-run    # ALWAYS run dry-run first
# … review output, then re-run without --dry-run
```

---

## Logical entity backup

For day-to-day business-data clones (e.g. dev → test, snapshotting your
Solutions + Workflows + Connectors before a migration) you usually don't
need bssmagic Postgres dumps, Mimir TSDB blocks, or Velero PVCs — those
are either regenerable from source or operationally expensive. The
`--entities` / `--preset` flags let you say *what business stuff to back
up* instead of *which physical tables and buckets*.

### Entity → storage map

| Entity | What gets backed up |
|---|---|
| `virtual-data` | `mapping-rules` DDB + all 7 simulator S3 buckets |
| `mapping-rules` | `mapping-rules` DDB |
| `connectors` | `data-planes` + `connector-settings` DDB |
| `policies` | `rbac` DDB (business policy docs live in repo YAML, not DR) |
| `workflows` | `foundry-workspace` (`GSI1PK=JOURNEY`) + `transformation-system` (whole table) |
| `react-tools` / `tools-registry` | `foundry-workspace` (`GSI1PK in TOOL, TOOL_VERSION`) |
| `solutions` | `foundry-workspace` (`GSI1PK=SOLUTION`) |
| `analytics` | `foundry-workspace` (`GSI1PK in DASHBOARD, VIEW`) + `solution-results` S3 |
| `audit` | `control-plane-audit` DDB |
| `integration-rules`, `ai-automations`, `connector-apis`, `business-policies`, `workflow-templates` | **noop** — source-of-truth is `enterprise-knowledge/*.yaml` in the container image; restored implicitly by deploying the same image |

Preset `business` = `virtual-data, mapping-rules, connectors, policies, workflows, react-tools, tools-registry, solutions, analytics, audit`.

### Examples

```bash
# Business data only (S3 + DDB; no bssmagic, no mimir, no Velero)
python3 backup_restore.py backup --env dev --capability nexus-ai \
    --profile ptr-tech --cluster nexus-dev \
    --preset business \
    -o business.tar.gz

# Business data + infra (SSM/Secrets/Glue) for cross-account clone
python3 backup_restore.py backup --env dev --preset business \
    --include ssm,secrets,glue \
    --profile ptr-tech -o full-business.tar.gz

# Just workflows + solutions
python3 backup_restore.py backup --env dev \
    --entities workflows,solutions \
    --profile ptr-tech -o subset.tar.gz

# Restore only the workflows from a business backup
python3 backup_restore.py restore -i business.tar.gz \
    --target-env test --target-profile new-account \
    --entities workflows
```

`--entities` and `--preset` are mutually exclusive with `--only` (the
legacy storage-group filter). They compose additively with `--include`
when you also need infra components.

When `--entities`/`--preset` is set, the per-entity DDB filter writes
JSONL to `dynamodb/{table}.{entity}.jsonl` so multiple entities pulled
from the same physical table (e.g. `solutions` + `react-tools` from
`foundry-workspace`) don't collide. Whole-table entities (no filter,
e.g. `mapping-rules`) keep the legacy `dynamodb/{table}.jsonl` path. The
manifest records each entity's filter so selective restore works
without re-querying the source.

---

## Tarball layout

```
nexus-backup-nexus-ai-dev-20260531T120000Z/
  manifest.json
  s3/
    sfdc-simulator/                  one dir per bucket, mirrors S3 keys
    sap-simulator/
    tpm-simulator/
    sourcing-simulator/
    journey-logs/
    journey-reports/
    solution-results/
    bssmagic-dumps/
    mimir-blocks/
  dynamodb/
    transformation-system.jsonl      one Item per line
    foundry-workspace.jsonl
    license.jsonl
    …
  ssm/
    parameters.json                  [{Name, Type, Value, …}]
  secrets/
    secrets.json                     [{Name, SecretString | SecretBinary_b64}]
  glue/
    database.json
    tables.json
    partitions.json
  cognito/
    pool.json
    groups.json
    app_clients.json
    domain.json
    users.jsonl
  kubernetes/
    nexuscapability.yaml             the source NexusCapability CR
    download/
      velero-backup.json             velero metadata
      <name>.tar.gz                  the velero backup archive
      kopia-repo/…                   kopia repo files (for PV restore)
  postgres/
    bssmagic.dump                    pg_dump -Fc output
```

The `manifest.json` declares which components are present and the source
env/capability/account so restore can do the correct renames.

---

## Components & groups

**Components** are top-level resource categories selectable via `--include` /
`--exclude`:

| Component | Default | Backed up via |
|---|---|---|
| `s3`         | yes | boto3 list/get_object |
| `dynamodb`   | yes | boto3 scan |
| `ssm`        | yes | get_parameters_by_path (recursive) |
| `secrets`    | yes | list_secrets + get_secret_value |
| `glue`       | yes | get_database / get_tables / get_partitions |
| `cognito`    | NO  | describe_user_pool + list_users |
| `kubernetes` | yes | `velero backup create` + S3 download of artifacts |
| `postgres`   | yes | `kubectl exec pg_dump -Fc` |

`cognito` is opt-in because most envs don't enable auth in the CR.

**Groups** are sub-selectors for the S3 + DynamoDB components only
(`--only`):

| Group | Members |
|---|---|
| `simulators`   | sfdc/oracle/sap/wxcc/external/tpm/sourcing simulator buckets |
| `knowledge`    | bssmagic-dumps |
| `journeys`     | journey-logs, journey-reports, solution-results, transformation-system, foundry-workspace tables |
| `config`       | license, rbac, sessions, audit-log, mapping-rules, … tables |
| `observability`| mimir-blocks |

---

## Pre-restore on the target cluster (in order)

The DR tool restores **data**, not infrastructure. Before you run restore,
provision the empty target cluster:

1. **Create the target EKS cluster**
   ```bash
   cd nexus-deployer/deploy/eks
   ./create-hardened-eks-cluster.sh --name nexus-test \
       --network-profile lowest-cost --profile new-account
   ```
2. **Install the operator** (CRDs, RBAC, deployment)
   ```bash
   kubectl apply -f nexus-deployer/kube-operator/manifests/crd.yaml
   kubectl apply -f nexus-deployer/kube-operator/manifests/network-config-crd.yaml
   # Substitute ${ACCOUNT_ID} in rbac.yaml first (see file header).
   sed "s|\${ACCOUNT_ID}|$(aws sts get-caller-identity --profile new-account --query Account --output text)|g" \
       nexus-deployer/kube-operator/manifests/rbac.yaml | kubectl apply -f -
   kubectl apply -f nexus-deployer/kube-operator/manifests/deployment.yaml
   ```
3. **Install Velero** on the target — see
   [`deploy/eks/USAGE.md`](../../../nexus-deployer/deploy/eks/USAGE.md#dr--backup-restore-prerequisite--install-velero).
   Create a bucket like `nexus-velero-backups-${TARGET_ACCOUNT_ID}` and pass it
   as `--target-velero-bucket` to restore.
4. **Apply NexusCapability CR** so the operator creates EMPTY DynamoDB tables,
   S3 buckets, SSM parameters, Secrets, IAM roles, K8s namespace/SA/Deployments.
   The DR tool itself will then **overwrite** the empty data with the backup
   contents.
   ```bash
   kubectl apply -f nexus-deployer/kube-operator/examples/nexus-ai-capability.yaml
   # Watch the operator provision:
   kubectl get nexuscapability -A -w
   ```
5. **Run the restore** (`python3 backup_restore.py restore ...`).
6. **Force a final reconcile** so the backend rolls with restored data:
   ```bash
   kubectl annotate nexuscapability nexus-ai-test -n nexus-ai-test \
       reconcile=$(date +%s) --overwrite
   ```

---

## Env-rename details

Restore rewrites these substrings everywhere they appear:

| From | To |
|---|---|
| `{cap}-{src-env}-` (bucket / table / IAM role names) | `{cap}-{tgt-env}-` |
| `/{cap}/{src-env}/` (SSM paths) | `/{cap}/{tgt-env}/` |
| `{cap}/{src-env}/` (secret names) | `{cap}/{tgt-env}/` |
| `{cap_underscored}_{src-env}_` (Glue DB) | `{cap_underscored}_{tgt-env}_` |
| `{src-account-id}` (account IDs in ARNs, bucket suffixes) | `{tgt-account-id}` |
| `{src-cap}-{src-env}` namespace | `{tgt-cap}-{tgt-env}` (Velero `--namespace-mappings`) |

This rewrite runs in:
- SSM parameter names AND values
- Secrets Manager secret names; SecretString values **only if they parse as JSON** (opaque blobs / JWTs are left alone)
- DynamoDB item values (recursive string scan)
- Glue table `Location` URIs
- Cognito app-client `CallbackURLs` / `LogoutURLs`
- NexusCapability CR `metadata.name`, `metadata.namespace`, `spec.environment`

---

## Restore execution order (important)

```
1. SSM           (operator wrote defaults; backup overwrites)
2. Secrets       (operator created empty placeholders; backup overwrites)
3. DynamoDB      (table exists empty; batch_write_item)
4. S3            (bucket exists empty; sync via boto3)
5. Glue          (DB exists; create_table + create_partition with new Locations)
6. Cognito       (pool exists; users via admin_create_user)
7. NexusCap CR   (re-apply with target env so operator's IRSA SA points at new account)
8. Velero        (PVCs reconstructed; deployments restored with namespace rename)
9. Postgres      (after Velero brings PV + pod back, pg_restore --clean --if-exists)
```

If any step fails mid-way, the DR tool exits non-zero and you can re-run with
`--include <component>` to retry just that one piece.

---

## Cross-account considerations

| Resource | What crosses the account boundary |
|---|---|
| S3 / DDB / SSM / Secrets / Glue / Cognito | Data flows via the local DR tarball; no cross-account IAM needed beyond the operator's source-profile and target-profile credentials. |
| Velero backup files | DR tool downloads them on backup, uploads to TARGET bucket on restore. No cross-account S3 sharing required. |
| Velero PV snapshots | Using **Kopia** uploader (default in our `velero install` example) — re-encrypts on upload with a passphrase, so target account can decrypt. No cross-account KMS sharing required. |
| IAM roles / IRSA | NOT in scope of this tool. The operator regenerates them per env from `nexus-deployer/kube-operator/permissions/`. |
| Cognito passwords | NOT exportable from AWS. Restored users get a temporary password and must reset on first login. |

---

## Dry-run

`--dry-run` is honored by every component. It prints what would happen
without making AWS API writes, kubectl apply calls, or Velero invocations.
Always run it first when moving across accounts.

---

## Troubleshooting

**`KMS access denied` on DDB items.** Some operator-provisioned tables use a
customer-managed CMK that isn't shared with the target account. Either share
the CMK or recreate the table on the target with the target's KMS key, then
re-run restore with `--include dynamodb`.

**Velero backup phase = `PartiallyFailed`.** Usually a single PVC failed to
upload. Check `velero backup describe <name> --details`; common cause is a
PVC that's actively being written (Postgres). The pg_dump+pg_restore path
gives you a fallback for the BSS Magic data.

**Cognito users get `UsernameExistsException` on restore.** Safe — they
already exist in the target pool from a previous restore run.

**Glue `EntityNotFoundException` on partition restore.** The table wasn't
created yet (it was skipped due to a prior error). Re-run the same command —
operations are idempotent.

**`kubernetes_velero` says velero backup name not found.** The Velero
controller polls the bucket every 1 min by default; the tool waits up to 2
min. If you're being patient, increase `WAIT_TIMEOUT_S` in
`kubernetes_velero.py`.

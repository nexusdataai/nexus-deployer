# K3s Local Dev Stack

Shared infrastructure for running Nexus capabilities locally without AWS. **All common services live in the `nexus-local` namespace**; capability namespaces (`ontology-local`, `ai-engine-local`, …) run only application pods (backend/frontend).

## Components (`nexus-local` namespace)

| Service | DNS (in-cluster) | Port | Role |
|---------|------------------|------|------|
| `ministack-svc` | `ministack-svc.nexus-local.svc.cluster.local` | 4566 | AWS API gateway (SSM, Secrets Manager, Glue, STS, Athena API, S3 API) |
| `minio-svc` | `minio-svc.nexus-local.svc.cluster.local` | 9000 | Object storage (200Gi PVC) |
| `scylla-svc` | `scylla-svc.nexus-local.svc.cluster.local` | 8000 | DynamoDB API (Alternator) |
| `trino-svc` | `trino-svc.nexus-local.svc.cluster.local` | 8080 | SQL analytics over MinIO (adhoc; apps use MiniStack Athena API) |
| `redis-svc` | `redis-svc.nexus-local.svc.cluster.local` | 6379 | Cache |
| `mimir-svc` | `mimir-svc.nexus-local.svc.cluster.local` | 8080 | Grafana Mimir (TSDB blocks in MinIO) |
| `pgvector-svc` | `pgvector-svc.nexus-local.svc.cluster.local` | 5432 | Postgres + pgvector (+ Apache AGE with `nexus-sre-postgres` image) |

Init jobs:

- `nexus-local-init` — DynamoDB tables, S3 buckets, Glue DBs, SSM params, Secrets Manager secrets
- `postgres-init-extensions` — `vector` extension, embedding tables, optional AGE graph

## Deploy shared stack

```bash
cd /opt/mycode/nexus/nexus-deployer/local-k3s

# Full shared infra (AWS emulation + Mimir + Postgres)
./deploy-local-aws-stack.sh --kube-context local-cluster
./tests/verify-local-stack.sh --kube-context local-cluster
# Optional: heavier load loops
# ./tests/verify-local-stack.sh --kube-context local-cluster --load-items 100

# boto3 API smoke tests
./tests/verify-local-boto3-apis.sh --kube-context local-cluster
```

### Helm values (`../kube-operator/charts/nexus-local-aws-stack/values.yaml`)

Disable components if not needed:

```yaml
mimir:
  enabled: true
  blocksBucket: shared-local-mimir-blocks-000000000000

postgres:
  enabled: true
  image: pgvector/pgvector:pg16          # vector only
  # image: nexus-sre-postgres:latest     # pgvector + Apache AGE
  initExtensions: true
  ageGraphName: enterprise_onto
```

Build the AGE-enabled image:

```bash
cd ../kube-operator && ./package-images.sh --only-sre-postgres
# Then set postgres.image in values-k3s.yaml and redeploy the stack
```

## Operator `localEmulation`

Capability CRs **must disable per-namespace infra** and point at `nexus-local`:

```yaml
localEmulation:
  enabled: true
  namespace: nexus-local

dataServices:
  dynamodb: { enabled: false }
  s3:       { enabled: false }
  glue:     { enabled: false }

redis:
  enabled: false    # → shared redis-svc.nexus-local

mimir:
  enabled: false    # → shared mimir-svc.nexus-local

postgres:
  enabled: false    # → shared pgvector-svc.nexus-local (ontology / nexus-ai)
```

Backend env injected automatically:

| Env var | Target |
|---------|--------|
| `USE_LOCALSTACK` / `AWS_ENDPOINT_URL_*` | MiniStack, Scylla, MinIO, SSM, Secrets Manager |
| `REDIS_URL` | `redis-svc.nexus-local` |
| `MIMIR_URL` | `http://mimir-svc.nexus-local:8080` |
| `FDW_PG_HOST` | `pgvector-svc.nexus-local.svc.cluster.local` |
| `SSM_PARAMETER_PREFIX` / `SECRETS_PREFIX` | MiniStack (when `skipSsmSecrets: false`) |

## Full bootstrap

```bash
cd /opt/mycode/nexus/nexus-deployer/local-k3s
./bootstrap-local-dev.sh --product local-ontology --env local
```

## Host-run dev (port-forward)

```bash
cd nexus-ontology
./scripts/port-forward-k3s-dev.sh
cp backend/.env.local.k3s.example backend/.env.local
```

| Local port | Service |
|------------|---------|
| 8001 | Scylla (DynamoDB) |
| 4566 | MiniStack |
| 9000 | MinIO |
| 6379 | Redis |
| 5432 | Postgres |
| 9090 | Mimir |

## Namespace layout

```
nexus-local/          ← shared infra (Helm)
ontology-local/       ← app pods only
ai-engine-local/      ← app pods only
```

## Example CRs

See `../kube-operator/examples/`:

- `nexus-ontology-local.yaml`
- `nexus-ai-local.yaml`
- `nexus-ai-engine-local.yaml`

Products: `local-ontology`, `local-nexus-ai`, `local-ai-engine` (via `../kube-operator/deploy-capability.sh`)

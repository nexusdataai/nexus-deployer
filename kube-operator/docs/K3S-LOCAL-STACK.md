# K3s Local AWS Emulation Stack

Shared infrastructure for running Nexus capabilities locally without AWS.

## Components (`nexus-local` namespace)

| Service | Port | Role |
|---------|------|------|
| `ministack-svc` | 4566 | AWS API gateway (Glue, STS, Athena API, S3 API) |
| `minio-svc` | 9000 | Object storage (200Gi PVC) |
| `scylla-svc` | 8000 | DynamoDB API (Alternator) |
| `trino-svc` | 8080 | SQL analytics over MinIO (adhoc; apps use MiniStack Athena API) |
| `redis-svc` | 6379 | Cache + MiniStack Redis |

## Deploy

```bash
./deploy-local-aws-stack.sh --kube-context local-cluster
./verify-local-stack.sh --kube-context local-cluster
```

## Operator `localEmulation`

Set on NexusCapability CR:

```yaml
localEmulation:
  enabled: true
  namespace: nexus-local
dataServices:
  dynamodb: { enabled: false }
  s3: { enabled: false }
  glue: { enabled: false }
mimir:
  enabled: true   # default for local — blocks stored in MinIO
redis:
  enabled: false  # use shared nexus-local Redis
```

Backend env injected automatically:

- `USE_LOCALSTACK=true` → MiniStack
- `AWS_ENDPOINT_URL_DYNAMODB` → Scylla
- `AWS_ENDPOINT_URL_S3` → MinIO
- `REDIS_URL` → shared Redis

## Athena vs Trino

Nexus apps call **boto3 Athena API** (`StartQueryExecution`, …). **MiniStack** satisfies that. **Trino** is for manual/large SQL over MinIO — not a drop-in Athena API replacement.

## Example CRs

- `examples/nexus-ontology-local.yaml`
- `examples/nexus-ai-local.yaml`

Products: `local-ontology`, `local-nexus-ai`

## NodePort access (local K3s)

| Service | NodePort |
|---------|----------|
| Backend | 30800 |
| Frontend | 30808 |

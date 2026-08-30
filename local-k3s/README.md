# Local K3s cluster for Nexus dev

Automated scripts to install a single-node [K3s](https://k3s.io/) cluster for local development, mirroring the EKS workflow under `aws-eks/`.

## Requirements

| Resource | Minimum |
|----------|---------|
| RAM | 12 GB recommended |
| Disk | 300 GB free (200 GB MinIO + Scylla + images) |
| OS | Linux with sudo |

## Quick start

```bash
cd /opt/mycode/nexus/nexus-deployer/local-k3s
./create-local-k3s-cluster.sh
export KUBECONFIG=/opt/mycode/nexus/nexus-deployer/aws-login/.kube/config
kubectl config use-context local-cluster

# Deploy operator + shared AWS emulation stack
cd ../kube-operator
./operator.sh deploy
cd ../local-k3s
./deploy-local-aws-stack.sh --kube-context local-cluster
./tests/verify-local-stack.sh --kube-context local-cluster

# Deploy a capability (after loading images)
cd ../kube-operator
./deploy-capability.sh --product local-ontology --env local --skip-images --skip-iam
```

## Bootstrap (K3s + operator + stack + capability)

```bash
./bootstrap-local-dev.sh --product local-ontology --env local
```

## Verify boto3 APIs (DynamoDB + Athena)

After the Helm stack and init job complete:

```bash
./tests/verify-local-boto3-apis.sh --kube-context local-cluster
```

This runs inside the cluster and checks:

- **DynamoDB (Scylla):** `describe_table`, `put_item`, `get_item`, `update_item`, `delete_item`, `query` (PK + GSI1), `scan`, `batch_writer` on all init-provisioned tables for `ontology-local` and `nexus-ai-local`
- **Athena (MiniStack):** `start_query_execution`, `get_query_execution`, `get_query_results`, plus Glue database/table checks (ontology path; nexus-ai uses VDL over HTTP for analytics)

From the host (with port-forwards to Scylla/MiniStack/MinIO):

```bash
kubectl port-forward -n nexus-local svc/scylla-svc 8000:8000 &
kubectl port-forward -n nexus-local svc/ministack-svc 4566:4566 &
kubectl port-forward -n nexus-local svc/minio-svc 9000:9000 &
./tests/verify-local-boto3-apis.sh --host
```

## Scripts

| Script | Purpose |
|--------|---------|
| `deploy-local-aws-stack.sh` | Deploy shared nexus-local stack (Helm) |
| `create-local-k3s-cluster.sh` | Install K3s, export kubeconfig |
| `delete-local-k3s-cluster.sh` | Uninstall K3s (`--purge-data` wipes `/var/lib/rancher/k3s`) |
| `bootstrap-local-dev.sh` | K3s → operator → Helm stack → optional capability |

## Tests (`tests/`)

| Script | Purpose |
|--------|---------|
| `tests/verify-local-k3s-cluster.sh` | Node Ready, storage, sample pod |
| `tests/verify-local-stack.sh` | In-cluster R/W + light load: MinIO, Scylla, Trino, Redis, Postgres, pgvector, AGE, MiniStack, Mimir |
| `tests/verify-local-boto3-apis.sh` | boto3 DynamoDB (Scylla) + Athena (MiniStack) API smoke tests |
| `tests/verify_boto3_apis.py` | Python helper used by `verify-local-boto3-apis.sh` |

## Architecture

- **K3s** provides Kubernetes with `local-path` StorageClass
- **`nexus-local` namespace** (Helm): MiniStack, MinIO, Scylla, Trino, Redis, **Mimir**, **Postgres (pgvector/AGE)**
- **Capability namespaces** (`ontology-local`, …): backend + frontend only — shared infra via `localEmulation`

See [docs/K3S-LOCAL-STACK.md](docs/K3S-LOCAL-STACK.md) for full details.

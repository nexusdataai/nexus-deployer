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
./deploy-local-aws-stack.sh

# Deploy a capability (after loading images)
./deploy-capability.sh --product local-ontology --env local --skip-images --skip-iam
```

## One-command orchestrator

```bash
./deploy-local-full-stack.sh --product local-ontology --env local
```

## Scripts

| Script | Purpose |
|--------|---------|
| `create-local-k3s-cluster.sh` | Install K3s, export kubeconfig |
| `delete-local-k3s-cluster.sh` | Uninstall K3s (`--purge-data` wipes `/var/lib/rancher/k3s`) |
| `verify-local-k3s-cluster.sh` | Node Ready, storage, sample pod |
| `deploy-local-full-stack.sh` | K3s → operator → Helm stack → optional capability |

## Architecture

- **K3s** provides Kubernetes with `local-path` StorageClass
- **`nexus-local` namespace** (Helm): MiniStack, MinIO (200Gi), Scylla Alternator, Trino, Redis
- **Capability namespaces** (`ontology-local`, …): backend + frontend + Mimir via operator `localEmulation`

See [../kube-operator/docs/K3S-LOCAL-STACK.md](../kube-operator/docs/K3S-LOCAL-STACK.md) for full details.

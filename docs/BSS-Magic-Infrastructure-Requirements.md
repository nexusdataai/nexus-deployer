# BSS Magic — Infrastructure Changes & Requirements

**Date:** 2026-02-13
**Author:** CloudSense / BSS Magic Team
**Applies to:** Any EKS cluster running the `nexus-deployer` with BSS Magic enabled

---

## 1. Executive Summary

BSS Magic adds a **PostgreSQL-backed StatefulSet** to the existing `nexus-deployer` architecture. The existing deployer only provisions **stateless** workloads (frontend Deployment, backend Deployment) that don't require persistent storage. The addition of PostgreSQL introduces two new infrastructure requirements:

1. **EBS CSI Driver** — EKS add-on for dynamic EBS volume provisioning
2. **IAM Role for EBS CSI Driver** — IRSA-based role so the CSI controller can create/attach EBS volumes

There are also **Kubernetes-level changes** to the operator's ClusterRole (adding `statefulsets` permission) and capability YAML (specifying `storageClass`), but these are handled automatically by the deployer code — no infra team action required.

---

## 2. Why BSS Magic Needs Persistent Storage

### Before BSS Magic (Existing Architecture)

| Component | Workload Type | Storage |
|-----------|--------------|---------|
| Frontend (nexus-ui) | Deployment (stateless) | None — serves static assets |
| Backend (ai-job-engine) | Deployment (stateless) | None — uses DynamoDB/S3 |
| Totogi Operator | Deployment (stateless) | None — watches CRDs |

All existing workloads are **stateless Deployments**. If a pod dies, Kubernetes recreates it with zero data loss because there is no local data.

### With BSS Magic (New Architecture)

| Component | Workload Type | Replicas | Storage |
|-----------|--------------|----------|---------|
| Frontend | Deployment (stateless) | 3 | None |
| Backend | Deployment (stateless) | 3 | None |
| Operator | Deployment (stateless) | 1 | None |
| **BSS Magic** | **StatefulSet** | **1** | **20Gi EBS PersistentVolume** |

BSS Magic runs **PostgreSQL** with:
- 1,661 foreign tables (Salesforce schema mapped through Axway FDW)
- 6 TMF views
- 4 INSTEAD OF triggers (for write-through to Axway/Salesforce)
- TMF API proxy (Python, port 8000 — proxies GETs to internal TMF Server on 8001)

PostgreSQL **requires persistent storage** — if the pod restarts, the database files on disk must survive. Without a PersistentVolume, every restart would require a full schema restore from the dump (~1,661 tables), which takes several minutes and is unacceptable for production.

### Why BSS Magic is 1 Replica (Not 3 Like Frontend/Backend)

**Frontend and Backend run 3 replicas** because they are **stateless**. Every replica is identical — there is no local data. The ALB distributes traffic across all 3. If one pod dies, the other 2 continue serving with zero impact. More replicas = more throughput + higher availability.

**BSS Magic must remain at 1 replica** because it runs **PostgreSQL** as a StatefulSet. Setting `replicas: 3` would create three **independent, unconnected** PostgreSQL instances (`bssmagic-0`, `bssmagic-1`, `bssmagic-2`), each with its own PVC and its own separate database. They would **not** share data or replicate to each other. The Kubernetes Service would round-robin requests across them, returning **inconsistent results** depending on which pod responds. This would also consume 3x the EBS storage (60Gi) and 3x the CPU/memory for zero benefit.

Multi-replica PostgreSQL requires streaming replication tooling (Patroni, pgpool, Crunchy Data Operator, etc.) that is not part of the BSS Magic image.

**Availability is still acceptable at 1 replica** because:
1. BSS Magic data is **not stored locally** — it is proxied through Axway FDW to Salesforce. No local data is lost on pod restart.
2. The PVC survives pod restarts — PostgreSQL schema definitions (1,661 foreign tables, views, triggers) persist on the EBS volume.
3. If the pod dies, Kubernetes recreates it in ~30 seconds. PostgreSQL starts and reconnects to Axway immediately.
4. BSS Magic is an **internal-only** service (ClusterIP, no external exposure). Only the backend calls it. A brief restart window is acceptable for this use case.
5. The backend should handle BSS Magic unavailability gracefully (retry logic, timeout handling).

---

## 3. Why EBS? Can It Work Without It?

### Short Answer

**No.** Without the EBS CSI Driver, the BSS Magic StatefulSet cannot start. The pod will remain in `Pending` state indefinitely because Kubernetes cannot provision the PersistentVolume.

### Technical Explanation

Kubernetes uses **PersistentVolumeClaims (PVCs)** to request storage. The PVC says "I need 20Gi of ReadWriteOnce storage." A **StorageClass** defines *how* that storage is created. On EKS, the default StorageClass `gp2` uses **Amazon EBS** (Elastic Block Store).

```
Pod (BSS Magic) → PVC (20Gi) → StorageClass (gp2) → EBS CSI Driver → AWS API → EBS Volume
```

The **EBS CSI Driver** is the component that actually calls the AWS API to:
1. Create an EBS volume (`ec2:CreateVolume`)
2. Attach it to the EC2 node (`ec2:AttachVolume`)
3. Format and mount it as a filesystem inside the pod

**Without the CSI driver, there is nothing to fulfill the PVC request.** Kubernetes will keep the pod in `Pending` with the event:

```
Warning  FailedScheduling  pod has unbound immediate PersistentVolumeClaims
```

### Why Wasn't This Needed Before?

The existing frontend and backend are **Deployments** (stateless). They don't request any PersistentVolumeClaims. No PVC = no need for a storage provisioner = no need for the EBS CSI Driver.

### Alternatives to EBS

| Option | Viable? | Notes |
|--------|---------|-------|
| **EBS (gp2/gp3)** | **Yes — recommended** | Default on EKS, simple, performant for single-pod databases |
| EFS (Elastic File System) | Technically yes | Overkill and slower for a single-pod PostgreSQL. EFS is for shared multi-pod access. Requires its own CSI driver anyway. |
| Local node storage (hostPath) | Not recommended | Data is lost if pod moves to a different node. Not production-safe. |
| No persistent storage | **No** | PostgreSQL requires durable storage. Without it, every restart loses all data. |

**EBS is the correct and simplest choice.** It's the EKS default and requires minimal setup.

---

## 4. Infrastructure Requirements (Infra Team Action Items)

### 4.1 IAM Role: AmazonEKS_EBS_CSI_DriverRole

**Purpose:** Allows the EBS CSI Driver pods (running in `kube-system`) to call AWS APIs to create, attach, and manage EBS volumes.

**Type:** IRSA (IAM Roles for Service Accounts) — the role is assumed by a specific Kubernetes service account, not by the EC2 node.

#### Trust Policy

The trust policy must reference the cluster's OIDC provider. Replace `<ACCOUNT_ID>`, `<REGION>`, and `<OIDC_ID>` with actual values.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/oidc.eks.<REGION>.amazonaws.com/id/<OIDC_ID>"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "oidc.eks.<REGION>.amazonaws.com/id/<OIDC_ID>:aud": "sts.amazonaws.com",
          "oidc.eks.<REGION>.amazonaws.com/id/<OIDC_ID>:sub": "system:serviceaccount:kube-system:ebs-csi-controller-sa"
        }
      }
    }
  ]
}
```

#### To get the OIDC ID for a cluster:

```bash
aws eks describe-cluster --name <CLUSTER_NAME> --region <REGION> \
  --query "cluster.identity.oidc.issuer" --output text | awk -F'/' '{print $NF}'
```

#### Attached Policy

| Policy ARN | Type |
|-----------|------|
| `arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy` | AWS Managed |

This is a standard AWS-managed policy. It grants:
- `ec2:CreateVolume`, `ec2:DeleteVolume`, `ec2:AttachVolume`, `ec2:DetachVolume`
- `ec2:CreateSnapshot`, `ec2:DeleteSnapshot`
- `ec2:DescribeVolumes`, `ec2:DescribeInstances`, `ec2:DescribeSnapshots`
- `ec2:CreateTags` (for volume tagging)

No custom policies are needed.

#### CLI Commands (if creating manually):

```bash
# 1. Get OIDC ID
OIDC_ID=$(aws eks describe-cluster --name <CLUSTER_NAME> --region <REGION> \
  --query "cluster.identity.oidc.issuer" --output text | awk -F'/' '{print $NF}')

# 2. Create IAM role with trust policy
aws iam create-role \
  --role-name AmazonEKS_EBS_CSI_DriverRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/oidc.eks.<REGION>.amazonaws.com/id/'$OIDC_ID'"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "oidc.eks.<REGION>.amazonaws.com/id/'$OIDC_ID':aud": "sts.amazonaws.com",
          "oidc.eks.<REGION>.amazonaws.com/id/'$OIDC_ID':sub": "system:serviceaccount:kube-system:ebs-csi-controller-sa"
        }
      }
    }]
  }'

# 3. Attach the managed policy
aws iam attach-role-policy \
  --role-name AmazonEKS_EBS_CSI_DriverRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy
```

### 4.2 EKS Add-on: aws-ebs-csi-driver

**Purpose:** Runs controller pods in `kube-system` that watch for PVC requests and dynamically create/attach EBS volumes.

```bash
aws eks create-addon \
  --cluster-name <CLUSTER_NAME> \
  --addon-name aws-ebs-csi-driver \
  --service-account-role-arn arn:aws:iam::<ACCOUNT_ID>:role/AmazonEKS_EBS_CSI_DriverRole \
  --region <REGION>
```

**Verification:**

```bash
# Check add-on status (should be ACTIVE)
aws eks describe-addon \
  --cluster-name <CLUSTER_NAME> \
  --addon-name aws-ebs-csi-driver \
  --query "addon.status" --output text \
  --region <REGION>

# Check pods are running
kubectl get pods -n kube-system -l app.kubernetes.io/name=aws-ebs-csi-driver
```

Expected output: 2 controller pods + 1 node pod per node, all `Running`.

### 4.3 StorageClass: gp2 (Verify Exists)

EKS creates a `gp2` StorageClass by default. No action needed unless it was deleted.

```bash
# Verify it exists
kubectl get storageclass gp2

# Optional: mark as default (if no default StorageClass exists)
kubectl annotate storageclass gp2 \
  storageclass.kubernetes.io/is-default-class=true
```

The BSS Magic capability YAML explicitly specifies `storageClass: "gp2"`, so marking it as default is optional but recommended for other workloads.

---

## 5. Kubernetes RBAC Changes (No Infra Action Required)

These changes are handled **automatically** by the deployer code. Documented here for completeness.

### 5.1 ClusterRole: statefulsets Permission

**What changed:** Added `statefulsets` to the `apps` apiGroup in the operator's ClusterRole.

**Before (frontend + backend only):**

```yaml
- apiGroups: ["apps"]
  resources: ["deployments", "replicasets"]
  verbs: ["*"]
```

**After (with BSS Magic):**

```yaml
- apiGroups: ["apps"]
  resources: ["deployments", "replicasets", "statefulsets"]
  verbs: ["*"]
```

**Why:** The operator needs permission to create StatefulSets. Without this, the operator gets a `403 Forbidden` error when trying to deploy BSS Magic.

**Where this is defined:**
- Code: `nexus-deployer/backend/app/services/operator_deployment_service.py` (line 838-841)
- Manifest: `nexus-deployer/kube-operator/manifests/rbac.yaml` (line 53-56)

**Who applies it:** The `deploy_operator_to_cluster.py` script automatically creates/replaces the ClusterRole during Step 5 of `e2e-deploy.sh`. No manual action needed.

### 5.2 ClusterRole Update Method: replace vs patch

**What changed:** The operator deployment script now uses `replace_cluster_role` instead of `patch_cluster_role` when the ClusterRole already exists.

**Why:** `patch` does a strategic merge that can leave stale rules. `replace` does a full replacement, ensuring the ClusterRole exactly matches the code definition. This prevents situations where a previous deployment left a ClusterRole missing `statefulsets` and a subsequent `patch` didn't add it.

**Where:** `nexus-deployer/backend/app/services/operator_deployment_service.py` (line 866)

---

## 6. What the Deployer Handles Automatically

The following are **not** infra team responsibilities. They are handled by `e2e-deploy.sh`:

| Item | Handled By | When |
|------|-----------|------|
| ClusterRole with `statefulsets` | `deploy_operator_to_cluster.py` | Step 5: Deploy operator |
| Namespace creation | `e2e-deploy.sh` | Step 6: Apply capability |
| ECR repositories (frontend, backend, bssmagic, operator) | `build-and-push.sh` / `e2e-deploy.sh` | Steps 2-4 |
| AWS Secrets Manager secrets (credentials, Axway config) | Operator (Kopf handler) | On TotogiCapability CR creation |
| StatefulSet creation with correct PGDATA, probes | Operator (kubernetes.py) | On TotogiCapability CR creation |
| PVC request (triggers EBS volume creation) | Kubernetes + EBS CSI Driver | Automatic when StatefulSet creates pod |

---

## 7. Summary: What Needs an SR

> **UPDATE:** As of 2026-02-13, the EBS CSI Driver setup is **fully automated** in
> `e2e-deploy.sh` (Step 2). The script creates the IAM role, installs the EKS add-on,
> and marks gp2 as the default StorageClass — all idempotent. No manual infra action
> is required **if the deploying user has IAM permissions to create roles and EKS add-ons.**
>
> An SR is only needed if the deploying user does NOT have these IAM permissions
> (e.g., in a locked-down production account where only the infra team can create IAM roles).

| # | Item | Type | One-Time? | Automated? |
|---|------|------|-----------|------------|
| 1 | IAM Role: `AmazonEKS_EBS_CSI_DriverRole` | IAM Role + IRSA Trust | Yes, per cluster | **Yes** (e2e-deploy.sh Step 2) |
| 2 | EKS Add-on: `aws-ebs-csi-driver` | EKS Add-on | Yes, per cluster | **Yes** (e2e-deploy.sh Step 2) |
| 3 | StorageClass `gp2` default annotation | kubectl annotate | Yes, per cluster | **Yes** (e2e-deploy.sh Step 2) |

**Total new IAM roles:** 1 (AmazonEKS_EBS_CSI_DriverRole)
**Total new IAM policies:** 0 (uses AWS-managed `AmazonEBSCSIDriverPolicy`)
**Total new EKS add-ons:** 1 (aws-ebs-csi-driver)
**Impact on existing workloads:** None — the EBS CSI driver only activates when a PVC is created.

---

## 8. Per-Cluster Checklist

Use this checklist when setting up a new EKS cluster for BSS Magic.
Items marked **(auto)** are handled by `e2e-deploy.sh` automatically.

- [ ] OIDC provider registered in IAM for the cluster **(auto** — deployer's `fix-irsa`**)**
- [ ] IAM role `AmazonEKS_EBS_CSI_DriverRole` created with IRSA trust policy **(auto** — e2e Step 2**)**
- [ ] `AmazonEBSCSIDriverPolicy` attached to the role **(auto** — e2e Step 2**)**
- [ ] `aws-ebs-csi-driver` EKS add-on installed with the role ARN **(auto** — e2e Step 2**)**
- [ ] Add-on status is `ACTIVE` **(auto** — e2e Step 2 waits up to 3 min**)**
- [ ] StorageClass `gp2` marked as default **(auto** — e2e Step 2**)**
- [ ] `credentials.zip` placed at `bssmagic-image/secrets/credentials.zip` **(manual** — one-time per repo clone**)**
- [ ] Secrets Manager: credentials.zip uploaded **(auto** — e2e Step 3, from file above**)**
- [ ] Secrets Manager: Axway config with UAT credentials **(auto** — operator creates with real UAT defaults**)**
- [ ] For production: update Axway secret with production `AXWAY_CLIENT_ID`, `AXWAY_CLIENT_SECRET`, `AXWAY_KEY_ID`, `AXWAY_PROVIDER_ORG` **(manual)**

---

## 9. Architecture Diagram

```
                            ┌──────────────────────────────────────────────┐
                            │              EKS Cluster                     │
                            │                                              │
  Internet ──► ALB ──────┬──┤  ┌──────────────┐   ┌──────────────────┐    │
                         │  │  │ Frontend x3  │   │  Backend x3      │    │
                         │  │  │ (Deployment) │   │  (Deployment)    │    │
                         │  │  │ Port 8080    │   │  Port 8000       │    │
                         │  │  │ stateless    │   │  stateless       │    │
                         │  │  └──────────────┘   └────────┬─────────┘    │
                         │  │                              │              │
                         │  │                      K8s DNS │ (internal)   │
                         │  │                              ▼              │
                         │  │               ┌──────────────────────────┐  │
                         │  │               │  BSS Magic x1            │  │
                         │  │               │  (StatefulSet — NOT      │  │
                         │  │               │   horizontally scalable) │  │
                         │  │               │  ┌────────────────────┐  │  │
                         │  │               │  │ PostgreSQL :5432   │  │  │
                         │  │               │  │ 1661 FDW tables    │  │  │
                         │  │               │  │ 6 TMF views        │  │  │
                         │  │               │  │ 4 triggers         │  │  │
                         │  │               │  └────────────────────┘  │  │
                         │  │               │  TMF API Proxy :8000     │  │
                         │  │               │  TMF Server    :8001 int │  │
                         │  │               │  Controller    :3000     │  │
   NOT exposed ─ ─ ─ ─ ─┘  │               └────────────┬─────────────┘  │
   externally               │                            │                │
                            │                     ┌──────▼──────┐         │
                            │                     │ EBS Volume  │         │
                            │                     │ 20Gi (gp2)  │         │
                            │                     │ via CSI ◄───┼──── AWS API
                            │                     └─────────────┘         │
                            └──────────────────────────────────────────────┘
```

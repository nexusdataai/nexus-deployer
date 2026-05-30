# Quick Usage Guide - Hardened EKS Cluster Creation

## Network profile (cost tier)

Pick a `--network-profile` based on your environment and budget.

```bash
# Production with full PrivateLink (default)
./create-hardened-eks-cluster.sh --name nexus-prod --network-profile higher-cost

# Production HA hybrid (S3/DDB gateway + NAT per AZ, ~$12-18/mo)
./create-hardened-eks-cluster.sh --name nexus-stg --network-profile moderate

# Lowest-cost hybrid (single NAT instance, ~$3-5/mo; not AZ-tolerant)
./create-hardened-eks-cluster.sh --name nexus-dev --network-profile lowest-cost

# Dev sandbox, no NAT, nodes carry public IPs (~$0/mo)
./create-hardened-eks-cluster.sh --name nexus-dev --network-profile public-nodes
```

## Switching profiles on a running cluster

`create-hardened-eks-cluster.sh` is for fresh deployments. For in-place
migration of an existing live cluster, use the companion helper:

```bash
# Phase A — provision NAT + tag VPC + print next steps (idempotent)
./migrate-network-profile.sh --name nexus-dev --target-profile lowest-cost

# Phase B — smoke-test the NAT independently (commands printed by the helper)
kubectl run nat-probe --rm -it --image=amazonlinux:2023 --restart=Never -- bash -lc \
    "curl -sS https://sts.us-east-1.amazonaws.com -o /dev/null -w 'STS: %{http_code}\n'"

# Phase C — flip the operator-watched CR
kubectl patch nexusnetworkconfig vpc-endpoints --type=merge \
    -p '{"spec":{"awsAccessMode":"lowest-cost"}}'
kubectl annotate nexuscapability nexus-ai-dev reconcile=$(date +%s) --overwrite

# Phase D — verify
kubectl port-forward svc/nexus-ai-dev-backend 8000:8000 &
curl -s http://localhost:8000/api/v1/health/aws | jq .
```

The helper handles infra (AWS) changes. Pod restart + CR patch are kept manual
so they're explicitly gated behind human verification of the NAT smoke test.

Rollback (any phase):

```bash
./migrate-network-profile.sh --name nexus-dev --target-profile higher-cost
# Tears down the NAT, restamps the VPC tag, then you flip the CR back manually.
```

`--dry-run` shows the planned actions without changing AWS. See `README.md` for
the cost table and per-mode topology.

## 🚀 Non-Interactive Mode (For Automation)

**Perfect for CI/CD pipelines - NO keyboard input required!**

```bash
cd /opt/mycode/nexus/nexus-deployer/deploy/eks

# Set AUTO_APPROVE to skip all prompts
export AUTO_APPROVE=yes

# Run the script
./create-hardened-eks-cluster.sh nexus-dev
```

**The script will:**
- ✅ Run completely unattended
- ✅ Delete existing cluster (if it exists)
- ✅ Create new EKS 1.34 cluster
- ✅ Deploy 2 nodes with EKS-optimized AMI
- ✅ Apply CIS Level 2 hardening
- ✅ Verify everything works
- ✅ Complete in 15-20 minutes

**Output:**
- Clean, minimal console output
- No long JSON dumps
- Progress indicators show status
- Final summary at the end

---

## 🔧 Interactive Mode (For Manual Operation)

```bash
./create-hardened-eks-cluster.sh nexus-dev
```

**The script will:**
- ⚠️ Ask for confirmation before deleting existing cluster
- Then proceed as normal

---

## 📋 What Gets Created

### EKS Cluster
- Name: nexus-dev (or your custom name)
- Version: 1.34
- Auth Mode: API_AND_CONFIG_MAP
- Logging: All types enabled
- Region: us-east-1

### Node Group
- Name: eks-optimized-nodes
- Nodes: 2 (min), 4 (max), 2 (desired)
- Instance Type: c6a.large
- AMI: EKS-optimized Amazon Linux 2023
- Auto-scaling: Enabled

### Security Hardening (CIS Level 2)
- Kernel security parameters
- SSH hardening (no root, no passwords)
- Audit logging (40+ rules)
- File permissions
- Password policies
- Network security
- Service hardening

**Compliance:** 75-80% of CIS Level 2 controls

---

## ⏱️ Timing

| Phase | Duration |
|-------|----------|
| Cluster Creation | 10-15 minutes |
| Node Deployment | 3-5 minutes |
| CIS Hardening | 3-5 minutes |
| **Total** | **15-25 minutes** |

---

## ✅ Verification

After script completes:

```bash
# Check cluster
kubectl get nodes

# Check pods
kubectl get pods -A

# Deploy test workload
kubectl run test --image=nginx --restart=Never
kubectl get pod test
kubectl delete pod test
```

**Expected:** All nodes Ready, all pods Running ✅

---

## 🔄 CI/CD Integration

### GitHub Actions Example

```yaml
name: Deploy EKS Cluster
on: workflow_dispatch

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Configure AWS
        uses: aws-actions/configure-aws-credentials@v2
        with:
          role-to-assume: ${{ secrets.AWS_ROLE }}
          aws-region: us-east-1
      
      - name: Create Hardened EKS Cluster
        run: |
          export AUTO_APPROVE=yes
          cd nexus-deployer/deploy/eks
          ./create-hardened-eks-cluster.sh nexus-prod
```

### Jenkins Example

```groovy
pipeline {
    agent any
    environment {
        AUTO_APPROVE = 'yes'
        AWS_PROFILE = 'ptr-tech'
    }
    stages {
        stage('Deploy EKS') {
            steps {
                dir('nexus-deployer/deploy/eks') {
                    sh './create-hardened-eks-cluster.sh nexus-prod'
                }
            }
        }
    }
}
```

### GitLab CI Example

```yaml
deploy-eks:
  stage: deploy
  script:
    - export AUTO_APPROVE=yes
    - cd nexus-deployer/deploy/eks
    - ./create-hardened-eks-cluster.sh nexus-prod
  only:
    - main
```

---

## 🛠️ Customization

Edit these variables in the script:

```bash
CLUSTER_NAME="your-cluster"
REGION="your-region"
K8S_VERSION="1.34"
NODE_INSTANCE_TYPE="c6a.large"
NODE_COUNT_MIN=2
NODE_COUNT_MAX=4
NODE_COUNT_DESIRED=2
CLUSTER_ROLE_ARN="arn:aws:iam::ACCOUNT:role/YOUR-CLUSTER-ROLE"
NODE_ROLE_ARN="arn:aws:iam::ACCOUNT:role/YOUR-NODE-ROLE"
SUBNETS="subnet-xxx,subnet-yyy,subnet-zzz"
AWS_PROFILE="your-profile"
```

---

## 📁 Files

| File | Purpose |
|------|---------|
| `create-hardened-eks-cluster.sh` | Main creation script |
| `cis-level2-full-hardening.sh` | CIS hardening to apply |
| `README.md` | Detailed documentation |
| `USAGE.md` | This quick reference |

---

## ✅ Success Indicators

Script completed successfully when you see:

```
╔════════════════════════════════════════════════════════════════╗
║              ✅ EKS CLUSTER CREATION COMPLETE                  ║
╚════════════════════════════════════════════════════════════════╝
```

And:
- All nodes show "Ready" ✅
- System pods are "Running" ✅
- Test workload deploys successfully ✅

---

## 🎯 Result

**You get:**
- Production-ready EKS 1.34 cluster
- CIS Level 2 hardened nodes (75-80%)
- Full Kubernetes functionality
- Complete documentation

**Ready to deploy your applications!** 🚀

# Operator Deployment Scripts

## 📚 Documentation

**Complete operator documentation is located at**:

```
nexus-deployer/doc/operator/README.md
```

---

## 🚀 Quick Reference

### 1. Create EKS Cluster (if needed)

EKS cluster creation scripts live in `nexus-deployer/deploy/eks/`:

```bash
cd /opt/mycode/nexus/nexus-deployer/deploy/eks
./create-hardened-eks-cluster.sh --name nexus-dev --region us-east-1
```

See `deploy/eks/README.md` and `deploy/eks/USAGE.md` for full details.

### 2. Prepare Cluster for Operator

```bash
python prepare_cluster_for_operator.py
```

### 3. Deploy Operator

```bash
python deploy_operator_to_cluster.py
```

### 4. Clean Up

```bash
python cleanup_operator.py
```

---

## 📁 Scripts in This Directory

| Script | Purpose |
|--------|---------|
| `prepare_cluster_for_operator.py` | Pre-check cluster access and readiness |
| `deploy_operator_to_cluster.py` | Deploy operator to EKS cluster |
| `cleanup_operator.py` | Clean up operator resources |

## 📁 Related: EKS Cluster Creation

| Location | Purpose |
|----------|---------|
| `deploy/eks/create-hardened-eks-cluster.sh` | Create EKS cluster with CIS Level 2 hardening |
| `deploy/eks/cis-level2-full-hardening.sh` | Standalone CIS hardening for EKS nodes |

---

## 📖 For Full Documentation

See: `nexus-deployer/doc/operator/README.md`

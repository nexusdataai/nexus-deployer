# Operator Deployment Scripts

## 📚 Documentation

**Complete operator documentation is located at**:

```
/opt/mycode/trilogy/starhub-deployer/doc/operator/README.md
```

---

## 🚀 Quick Reference

### Deploy Operator

```bash
cd /opt/mycode/trilogy/starhub-deployer
./operator-starhub-test.sh deploy
```

### Check Status

```bash
./operator-starhub-test.sh status
```

### Clean Up

```bash
./operator-starhub-test.sh delete
```

---

## 📁 Scripts in This Directory

| Script | Purpose |
|--------|---------|
| `deploy_operator_to_cluster.py` | Deploy operator (Python) |
| `cleanup_operator.py` | Clean up operator (Python) |
| `prepare_cluster_for_operator.py` | Pre-check cluster (Python) |

---

## 📖 For Full Documentation

See: `/opt/mycode/trilogy/starhub-deployer/doc/operator/README.md`

Or use the management script:
```bash
cd /opt/mycode/trilogy/starhub-deployer
./operator-starhub-test.sh help
```

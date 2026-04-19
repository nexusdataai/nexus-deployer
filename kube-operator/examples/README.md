# TotogiCapability Examples

## Available Examples

| File | Namespace | Description | Complexity |
|------|-----------|-------------|------------|
| `test-app-8080.yaml` | `test-app-dev` | Minimal working example (frontend only) | ⭐ Simple |
| `test-capability-simple.yaml` | `simple-test-dev` | Basic test with nginx | ⭐ Simple |
| `test-capability.yaml` | `call-processing-dev` | Frontend + backend | ⭐⭐ Medium |
| `call-processing.yaml` | `call-processing-prod` | Production example | ⭐⭐⭐ Advanced |

---

## ⚠️ Important: CRD Schema Limitations

The current CRD schema is **minimal** and only supports these fields:

### ✅ Supported Fields

```yaml
spec:
  capabilityName: string
  version: string
  environment: "dev" | "staging" | "prod"
  region: string (default: "us-east-1")
  deletionPolicy: "Delete" | "Retain" (default: "Delete")
  
  frontend:
    image: string
    replicas: integer (default: 2)
    resources: object  # Not validated - keep empty or simple
  
  backend:
    image: string
    replicas: integer (default: 2)
    resources: object  # Not validated - keep empty or simple
  
  dataServices:
    dynamodb: object  # Not validated - keep empty {}
    s3: object        # Not validated - keep empty {}
    glue: object      # Not validated - keep empty {}
```

### ❌ NOT Supported (Will Cause Errors)

These fields will cause `BadRequest: unknown field` errors:

```yaml
# Don't use these:
enabled: true                    # Not in schema
port: 8080                       # Not in schema
env: [...]                       # Not in schema
resources.requests: {...}        # Nested not validated
resources.limits: {...}          # Nested not validated
livenessProbe: {...}             # Not in schema
readinessProbe: {...}            # Not in schema
ingress: {...}                   # Not in schema
hpa: {...}                       # Not in schema
pdb: {...}                       # Not in schema
dataServices.dynamodb.enabled    # Nested not validated
dataServices.dynamodb.tables     # Nested not validated
dataServices.s3.buckets          # Nested not validated
```

### 🔧 What Operator Actually Does

Even though you can't specify these in the CR, the operator hardcodes:

**Frontend:**
- Container port: **8080**
- Health check: `GET /` on port 8080
- Service: LoadBalancer on port 8080

**Backend:**
- Container port: **8000**
- Health check: `GET /health` on port 8000
- Service: LoadBalancer on port 8000

**Your containers MUST match these ports!**

---

# TotogiCapability Examples

Example Custom Resources for testing the Totogi Operator.

## Prerequisites

1. **Operator must be installed** on the cluster:
   ```bash
   kubectl -n totogi-system get deployment totogi-operator
   ```

2. **Check CRD is registered**:
   ```bash
   kubectl get crd totogicapabilities.totogi.com
   ```

3. **Verify operator is running**:
   ```bash
   kubectl -n totogi-system logs -f deployment/totogi-operator
   ```

## Example 1: Basic Test Capability

File: `test-capability.yaml`

Minimal deployment for testing operator functionality.

### Apply

```bash
kubectl apply -f test-capability.yaml
```

### Watch Status

```bash
# List all capabilities
kubectl get totogicapabilities -A

# Watch for changes
kubectl get totogicapabilities -A -w

# Get detailed status
kubectl describe totogicapability test-capability

# Check operator logs
kubectl -n totogi-system logs -f deployment/totogi-operator
```

### Expected Resources Created

The operator will create:

1. **AWS Resources:**
   - DynamoDB Tables:
     - `call-processing-dev-transformation-system`
     - `call-processing-dev-license`
     - `call-processing-dev-wxcc-task-tracking`
   - S3 Buckets:
     - `call-processing-dev-call-data-{account-id}`
     - `call-processing-dev-wxcc-simulator-{account-id}`
     - `call-processing-dev-journey-logs-{account-id}`
     - `call-processing-dev-journey-reports-{account-id}`
   - Glue Database: `call_processing_dev_db`
   - SSM Parameters under: `/call-processing/dev/`
   - Secrets Manager secrets under: `call-processing/dev/`
   - IAM Role: `call-processing-dev-app-role` (with IRSA)

2. **Kubernetes Resources:**
   - Namespace: `call-processing-dev`
   - ServiceAccount: `call-processing-dev-app-sa` (with IRSA annotation)
   - Backend Deployment: `call-processing-dev-backend`
   - Backend Service: `call-processing-dev-backend-svc` (LoadBalancer)
   - Frontend Deployment: `call-processing-dev-frontend`
   - Frontend Service: `call-processing-dev-frontend-svc` (LoadBalancer)

### Check Status

```bash
# Get capability status
kubectl get totogicapability test-capability -o yaml

# Check phase
kubectl get totogicapability test-capability -o jsonpath='{.status.phase}'

# Get frontend URL
kubectl get totogicapability test-capability -o jsonpath='{.status.frontendUrl}'

# Get backend URL
kubectl get totogicapability test-capability -o jsonpath='{.status.backendUrl}'
```

### Verify Kubernetes Resources

```bash
# Check namespace was created
kubectl get namespace call-processing-dev

# Check service account
kubectl -n call-processing-dev get serviceaccount

# Check deployments
kubectl -n call-processing-dev get deployments

# Check services (LoadBalancers)
kubectl -n call-processing-dev get services

# Check pods
kubectl -n call-processing-dev get pods
```

### Verify AWS Resources

```bash
# DynamoDB tables
aws dynamodb list-tables --region ap-southeast-1 | grep call-processing-dev

# S3 buckets
aws s3 ls | grep call-processing-dev

# Glue database
aws glue get-database --name call_processing_dev_db --region ap-southeast-1

# SSM parameters
aws ssm get-parameters-by-path --path /call-processing/dev/ --region ap-southeast-1

# Secrets
aws secretsmanager list-secrets --region ap-southeast-1 --filters Key=name,Values=call-processing/dev/

# IAM role
aws iam get-role --role-name call-processing-dev-app-role
```

## Example 2: Production Capability

File: `production-capability.yaml` (to be created)

Full production deployment with:
- Multiple replicas
- HPA enabled
- PDB configured
- Ingress with ALB
- TLS/SSL
- Custom domain

```yaml
apiVersion: totogi.com/v1
kind: TotogiCapability
metadata:
  name: call-processing-prod
  namespace: call-processing-prod
spec:
  capabilityName: call-processing
  version: "1.0.0"
  environment: prod
  region: ap-southeast-1
  
  frontend:
    enabled: true
    replicas: 3
    image: "123456789012.dkr.ecr.ap-southeast-1.amazonaws.com/totogi-frontend:1.0.0"
    resources:
      requests:
        cpu: "500m"
        memory: "512Mi"
      limits:
        cpu: "2000m"
        memory: "2Gi"
  
  backend:
    enabled: true
    replicas: 3
    image: "123456789012.dkr.ecr.ap-southeast-1.amazonaws.com/totogi-backend:1.0.0"
    resources:
      requests:
        cpu: "1000m"
        memory: "1Gi"
      limits:
        cpu: "4000m"
        memory: "4Gi"
  
  dataServices:
    dynamodb:
      enabled: true
    s3:
      enabled: true
    glue:
      enabled: true
  
  deletionPolicy: Retain  # Keep AWS resources if CR is deleted
  
  ingress:
    enabled: true
    className: "alb"
    annotations:
      alb.ingress.kubernetes.io/scheme: internet-facing
      alb.ingress.kubernetes.io/target-type: ip
      alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:ap-southeast-1:123456789012:certificate/xxx
    tls:
      enabled: true
      certificateArn: arn:aws:acm:ap-southeast-1:123456789012:certificate/xxx
    customDomain: call-processing.example.com
  
  hpa:
    enabled: true
    minReplicas: 3
    maxReplicas: 20
    targetCPUUtilization: 70
  
  pdb:
    enabled: true
    minAvailable: 2
```

## Updating a Capability

To update a capability, modify the YAML and reapply:

```bash
# Edit the capability
kubectl edit totogicapability test-capability

# Or apply updated YAML
kubectl apply -f test-capability-updated.yaml
```

The operator will perform a rolling update of changed resources.

## Deleting a Capability

```bash
kubectl delete totogicapability test-capability
```

Based on `deletionPolicy`:
- **Delete** (default): Removes all AWS resources and Kubernetes resources
- **Retain**: Removes only Kubernetes resources, keeps AWS resources

## Troubleshooting

### Check Operator Logs

```bash
kubectl -n totogi-system logs -f deployment/totogi-operator
```

### Check Capability Events

```bash
kubectl describe totogicapability test-capability
```

### Check Pod Status

```bash
kubectl -n call-processing-dev get pods
kubectl -n call-processing-dev describe pod <pod-name>
kubectl -n call-processing-dev logs <pod-name>
```

### Common Issues

#### 1. Capability stuck in "Provisioning"

- Check operator logs for errors
- Verify AWS credentials/IRSA is working
- Check IAM role has required permissions

#### 2. Pods not starting

- Check image pull errors: `kubectl -n call-processing-dev describe pod <pod-name>`
- Verify ECR credentials
- Check ServiceAccount IRSA annotation

#### 3. LoadBalancer services pending

- Verify AWS Load Balancer Controller is installed
- Check security groups allow traffic
- Verify subnets are tagged for ELB

#### 4. AWS resources not created

- Check operator has IAM permissions
- View operator logs for AWS API errors
- Verify region is correct

## Cleanup

### Delete Single Capability

```bash
kubectl delete -f test-capability.yaml
```

### Delete All Capabilities

```bash
kubectl delete totogicapabilities --all -A
```

### Verify Cleanup

```bash
# Check Kubernetes resources
kubectl get totogicapabilities -A
kubectl get namespaces | grep call-processing

# Check AWS resources (should be deleted if deletionPolicy: Delete)
aws dynamodb list-tables | grep call-processing
aws s3 ls | grep call-processing
```

## Additional Resources

- [Operator Deployment Guide](../../backend/scripts/README_OPERATOR_DEPLOYMENT.md)
- [CRD Specification](../manifests/crd.yaml)
- [Operator Source Code](../src/totogi_operator/)

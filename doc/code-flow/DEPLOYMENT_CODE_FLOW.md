# Deployment Code Flow

This document explains the complete deployment flow from user click to resource creation in the Nexus AI Installer. The system supports two deployment architectures: **CloudFormation-based** (traditional) and **EKS Kubernetes Operator-based** (pure-eks-deployment).

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           NEXUS AI INSTALLER ARCHITECTURE                            │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                      │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────────────────────┐ │
│  │   Electron   │────▶│    React     │────▶│         Python Backend               │ │
│  │   (main.js)  │     │   Frontend   │     │         (FastAPI)                    │ │
│  │              │     │   (api.ts)   │     │                                      │ │
│  └──────────────┘     └──────────────┘     └──────────────────────────────────────┘ │
│         │                    │                           │                          │
│         │                    │              ┌────────────┴────────────┐             │
│         │                    │              │                         │             │
│         │                    │              ▼                         ▼             │
│         │                    │  ┌─────────────────────┐  ┌─────────────────────────┐│
│         │                    │  │  CloudFormation     │  │  EKS Operator           ││
│         │                    │  │  Deployment Service │  │  Deployment Service     ││
│         │                    │  └─────────────────────┘  └─────────────────────────┘│
│         │                    │              │                         │             │
│         │                    │              ▼                         ▼             │
│         │                    │  ┌─────────────────────┐  ┌─────────────────────────┐│
│         │                    │  │  AWS CloudFormation │  │  Kubernetes Operator    ││
│         │                    │  │  (10 Stacks)        │  │  (NexusCapability CR)  ││
│         │                    │  └─────────────────────┘  └─────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## Deployment Architecture Selection

The system supports two deployment paths based on user selection in the Architecture Selection step:

| Architecture | Frontend Service | Backend Service | Deployment Method |
|-------------|------------------|-----------------|-------------------|
| **Serverless** | CloudFront + S3 | ECS Fargate | CloudFormation |
| **EKS** | EKS Ingress | EKS Pods | Kubernetes Operator |

---

## Path 1: CloudFormation Deployment (Traditional)

### Layer 1: User Interface (Electron + React)

#### Electron Main Process
**File:** `electron/main.js`

- Starts the Electron application
- Spawns the Python backend as a child process
- Serves the React frontend
- Handles IPC communication between frontend and backend

#### React Frontend
**File:** `frontend/src/components/DeploymentExecution.tsx`

- User clicks "Deploy" button
- Calls `deploymentApi.startDeployment(config)`
- Displays real-time deployment logs via polling

**File:** `frontend/src/services/api.ts`

- Makes HTTP POST to `/api/deployment/start`
- Polls deployment status via `/api/deployment/{id}`
- Streams deployment logs via `/api/deployment/{id}/logs`

### Layer 2: Backend API (FastAPI)

#### Deploy Router
**File:** `backend/app/routers/deployment.py`

```python
@router.post("/start", response_model=DeploymentResponse)
async def start_deployment(request: DeploymentRequest, background_tasks: BackgroundTasks):
    # Create deployment record
    deployment_id = deployment_service.create_deployment(request)
    
    # Start deployment in background
    background_tasks.add_task(deployment_service.start_deployment, deployment_id)
    
    return deployment
```

Key endpoints:
- `POST /api/deployment/start` - Start deployment
- `GET /api/deployment/{id}` - Get status
- `GET /api/deployment/{id}/logs` - Get logs
- `POST /api/deployment/{id}/cancel` - Cancel deployment
- `POST /api/deployment/validate` - Dry-run validation
- `POST /api/deployment/detect-stacks` - Detect existing stacks

### Layer 3: Deployment Orchestration

#### Main Orchestrator
**File:** `backend/app/services/deployment_orchestrator.py`

```python
class DeploymentOrchestrator:
    def deploy(self, config, callback):
        # Step 1: Infrastructure Provisioning
        self.provision_infrastructure(config, callback)
        
        # Step 2: Template Validation
        self.run_comprehensive_template_validation(config, callback)
        
        # Step 3: Dependency Validation
        self.validate_stack_dependencies(config, callback)
        
        # Step 4: Pre-deployment Validation
        self.run_pre_deployment_validation(config, callback)
        
        # Step 5: Deploy CloudFormation Stacks
        self.cfn_service.deploy_all_stacks(config, callback)
```

### Layer 4: CloudFormation Service

**File:** `backend/app/services/cloudformation_service.py`

```python
class CloudFormationDeploymentService:
    STACK_ORDER = [
        "backend-foundation",      # CloudWatch, basic infrastructure
        "backend-iam-roles",       # IAM roles and policies
        "backend-regional-cert",   # SSL certificates
        "backend-storage",         # DynamoDB, S3, ECR
        "backend-network",         # VPC, subnets, security groups
        "backend-service",         # ECS service, ALB
        "backend-domain",          # Route53, SSL cert
        "frontend-global",         # CloudFront, WAF (us-east-1)
        "frontend-cognito",        # Cognito User Pool
        "frontend-regional",       # S3 bucket, CloudFront origin
    ]
```

---

## Path 2: EKS Kubernetes Operator Deployment

### Overview

The EKS deployment path uses a Kubernetes Operator pattern to provision AWS resources and deploy workloads. This provides a cloud-native, declarative approach to capability deployment.

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                        EKS OPERATOR DEPLOYMENT FLOW                                  │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                      │
│  User Click ──▶ Frontend ──▶ Backend API ──▶ EKS Service ──▶ Operator Service       │
│                                                                                      │
│                                    │                                                 │
│                                    ▼                                                 │
│                         ┌─────────────────────┐                                      │
│                         │  1. Deploy Operator │                                      │
│                         │     to EKS Cluster  │                                      │
│                         └──────────┬──────────┘                                      │
│                                    │                                                 │
│                                    ▼                                                 │
│                         ┌─────────────────────┐                                      │
│                         │  2. Create          │                                      │
│                         │  NexusCapability CR│                                      │
│                         └──────────┬──────────┘                                      │
│                                    │                                                 │
│                                    ▼                                                 │
│                         ┌─────────────────────┐                                      │
│                         │  3. Operator        │                                      │
│                         │  Reconciles CR      │                                      │
│                         └──────────┬──────────┘                                      │
│                                    │                                                 │
│                    ┌───────────────┼───────────────┐                                 │
│                    ▼               ▼               ▼                                 │
│            ┌─────────────┐ ┌─────────────┐ ┌─────────────┐                           │
│            │  DynamoDB   │ │    S3       │ │   Glue      │                           │
│            │  Tables     │ │  Buckets    │ │  Database   │                           │
│            └─────────────┘ └─────────────┘ └─────────────┘                           │
│                    │               │               │                                 │
│                    └───────────────┼───────────────┘                                 │
│                                    ▼                                                 │
│                         ┌─────────────────────┐                                      │
│                         │  4. Deploy K8s      │                                      │
│                         │  Workloads          │                                      │
│                         └─────────────────────┘                                      │
│                                                                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### Layer 1: Frontend EKS Deployment Handler

**File:** `frontend/src/components/DeploymentExecution.tsx`

```typescript
const handleStartEKSDeployment = async () => {
  // Stage 1: Check/Deploy Operator (0-30%)
  const operatorStatus = await eksApi.checkOperatorStatus(clusterName, awsSessionId);
  
  if (!operatorStatus.operator_installed) {
    await eksApi.deployOperator({ cluster_name: clusterName });
  }
  
  // Stage 2: Create NexusCapability CR (30-50%)
  const crResult = await eksApi.deployCapability({
    cluster_name: clusterName,
    capability_name: capabilityName,
    capability_version: version,
    environment: environment,
    namespace: namespace,
    config: capabilityConfig,
  });
  
  // Stage 3: Poll for reconciliation progress (50-100%)
  while (attempts < maxAttempts) {
    const status = await eksApi.getCapabilityStatus(clusterName, crName, namespace);
    
    if (status.phase === 'Running') {
      // Deployment complete
      break;
    }
  }
};
```

### Layer 2: EKS API Router

**File:** `backend/app/routers/eks.py`

Key endpoints:
- `GET /api/eks/clusters` - List EKS clusters
- `GET /api/eks/clusters/{name}` - Get cluster details
- `GET /api/eks/clusters/{name}/operator-status` - Check operator installation
- `POST /api/eks/clusters/{name}/deploy-operator` - Deploy Nexus AI Operator
- `POST /api/eks/clusters/{name}/deploy-capability` - Create NexusCapability CR
- `GET /api/eks/clusters/{name}/capability/{cr_name}/status` - Get capability status

### Layer 3: EKS Service

**File:** `backend/app/services/eks_service.py`

```python
class EKSService:
    async def list_clusters(self) -> List[EKSClusterInfo]:
        """List all EKS clusters in the region."""
        
    async def deploy_operator(self, cluster_name: str, operator_version: Optional[str] = None):
        """Deploy the Nexus AI Operator to the cluster."""
        service = get_operator_deployment_service(aws_session_id, region)
        return await service.deploy_operator(cluster_name, operator_version)
    
    async def deploy_capability(self, cluster_name: str, capability_name: str, ...):
        """Deploy a capability by creating a NexusCapability CR."""
        service = get_operator_deployment_service(aws_session_id, region)
        return await service.create_capability_cr(...)
```

### Layer 4: Operator Deployment Service

**File:** `backend/app/services/operator_deployment_service.py`

```python
class OperatorDeploymentService:
    async def deploy_operator(self, cluster_name: str, operator_version: Optional[str] = None):
        """
        Deploy the Nexus AI Operator to an EKS cluster.
        
        Steps:
        1. Create nexus-system namespace
        2. Create IAM role with IRSA trust policy
        3. Create ServiceAccount with IAM role annotation
        4. Apply CRD (NexusCapability)
        5. Create RBAC (ClusterRole, ClusterRoleBinding)
        6. Deploy operator Deployment
        """
        
    async def create_capability_cr(self, cluster_name: str, capability_name: str, ...):
        """Create a NexusCapability Custom Resource."""
        cr = {
            "apiVersion": "nexus.ai/v1",
            "kind": "NexusCapability",
            "metadata": {"name": cr_name, "namespace": namespace},
            "spec": {
                "capabilityName": capability_name,
                "version": capability_version,
                "environment": environment,
                "region": region,
                "deletionPolicy": "Delete",
                "frontend": {...},
                "backend": {...},
                "dataServices": {
                    "dynamodb": {"enabled": True},
                    "s3": {"enabled": True},
                    "glue": {"enabled": True}
                }
            }
        }
```

### Layer 5: Kubernetes Operator (kopf-based)

**File:** `kube-operator/src/nexus_operator/main.py`

The operator uses [kopf](https://kopf.readthedocs.io/) framework to watch for NexusCapability CRs and reconcile them.

```python
@kopf.on.create("nexus.ai", "v1", "nexuscapabilities")
async def create_capability(spec: dict, name: str, namespace: str, ...):
    """
    Handle NexusCapability creation.
    
    Phases:
    1. Provisioning - Create AWS data services
    2. Deploying - Deploy Kubernetes workloads
    3. Running - Deployment complete
    """
    
    # Phase 1: Provisioning AWS Data Services
    patch.status["phase"] = "Provisioning"
    
    # DynamoDB tables
    dynamodb = DynamoDBProvisioner(naming, region)
    await dynamodb.provision_all()
    
    # S3 buckets
    s3 = S3Provisioner(naming, region)
    await s3.provision_all()
    
    # Glue database
    glue = GlueProvisioner(naming, region)
    await glue.provision_all()
    
    # SSM parameters
    ssm = SSMProvisioner(naming, region)
    await ssm.provision_all(resources)
    
    # Secrets Manager
    secrets = SecretsProvisioner(naming, region)
    await secrets.provision_all()
    
    # IAM role
    iam = IAMProvisioner(naming, region)
    await iam.create_application_role(resources)
    
    # Phase 2: Deploying Kubernetes Resources
    patch.status["phase"] = "Deploying"
    
    k8s = KubernetesResourceCreator(namespace)
    await k8s.create_namespace_if_needed(naming)
    await k8s.create_service_account(naming, role_arn)
    await k8s.deploy_backend(...)
    await k8s.deploy_frontend(...)
    
    # Phase 3: Complete
    return {"phase": "Running", "message": "Deployment complete"}
```

### Operator Resource Provisioners

**Directory:** `kube-operator/src/nexus_operator/resources/`

| File | Purpose |
|------|---------|
| `dynamodb.py` | Provision DynamoDB tables |
| `s3.py` | Provision S3 buckets with lifecycle policies |
| `glue.py` | Provision Glue database and tables |
| `ssm.py` | Provision SSM parameters |
| `secrets.py` | Provision Secrets Manager secrets |
| `iam.py` | Create IAM roles with IRSA trust policy |
| `kubernetes.py` | Create K8s resources (Deployments, Services, Ingress) |

### NexusCapability CRD Schema

```yaml
apiVersion: nexus.ai/v1
kind: NexusCapability
metadata:
  name: call-processing-dev
  namespace: nexus-apps
spec:
  capabilityName: call-processing
  version: "1.0.0"
  environment: dev  # dev | staging | prod
  region: us-east-1
  deletionPolicy: Delete  # Delete | Retain
  
  frontend:
    image: "123456789.dkr.ecr.us-east-1.amazonaws.com/frontend:latest"
    replicas: 2
    resources:
      requests: { cpu: "100m", memory: "256Mi" }
      limits: { cpu: "500m", memory: "512Mi" }
  
  backend:
    image: "123456789.dkr.ecr.us-east-1.amazonaws.com/backend:latest"
    replicas: 2
    resources:
      requests: { cpu: "200m", memory: "512Mi" }
      limits: { cpu: "1000m", memory: "1Gi" }
  
  dataServices:
    dynamodb:
      enabled: true
    s3:
      enabled: true
    glue:
      enabled: true

status:
  phase: Running  # Provisioning | Deploying | Running | Failed
  message: "Deployment complete"
  frontendUrl: "https://app.example.com"
  backendUrl: "https://api.example.com"
  resources:
    dynamodbTables: ["call-processing-dev-calls", "call-processing-dev-sessions"]
    s3Buckets: ["call-processing-dev-data", "call-processing-dev-logs"]
    glueDatabase: "call-processing-dev-analytics"
    ssmParameters: ["/call-processing/dev/config/..."]
    secrets: ["call-processing-dev-api-keys"]
    iamRoles: ["arn:aws:iam::123456789:role/call-processing-dev-app-role"]
  lastReconcileTime: "2024-01-15T10:30:00Z"
```

---

## Complete Flow Diagrams

### CloudFormation Deployment Flow

```
User clicks Deploy
       │
       ▼
React Frontend (DeploymentExecution.tsx)
       │
       ▼
FastAPI Backend (POST /api/deployment/start)
       │
       ▼
DeploymentOrchestrator.deploy()
       │
       ├──▶ provision_infrastructure()
       │         └── SSM, Secrets, Glue, CloudWatch
       │
       ├──▶ run_comprehensive_template_validation()
       │         └── PreDeploymentChecker.validate_deployment()
       │
       ├──▶ validate_stack_dependencies()
       │         └── DependencyValidator.validate_dependencies()
       │
       ├──▶ run_pre_deployment_validation()
       │         └── Check stack states, orphaned resources
       │
       └──▶ CloudFormationDeploymentService.deploy_all_stacks()
                 │
                 └── For each stack in STACK_ORDER:
                          ├── build_parameters()
                          ├── create_or_update_stack()
                          └── wait_for_stack()
```

### EKS Operator Deployment Flow

```
User clicks Deploy (EKS mode)
       │
       ▼
React Frontend (handleStartEKSDeployment)
       │
       ├──▶ eksApi.checkOperatorStatus()
       │         └── GET /api/eks/clusters/{name}/operator-status
       │
       ├──▶ eksApi.deployOperator() [if not installed]
       │         └── POST /api/eks/clusters/{name}/deploy-operator
       │                  │
       │                  └── OperatorDeploymentService.deploy_operator()
       │                           ├── Create namespace (nexus-system)
       │                           ├── Create IAM role with IRSA
       │                           ├── Create ServiceAccount
       │                           ├── Apply NexusCapability CRD
       │                           ├── Create RBAC
       │                           └── Deploy operator Deployment
       │
       ├──▶ eksApi.deployCapability()
       │         └── POST /api/eks/clusters/{name}/deploy-capability
       │                  │
       │                  └── OperatorDeploymentService.create_capability_cr()
       │                           └── Create NexusCapability CR
       │
       └──▶ Poll eksApi.getCapabilityStatus()
                 └── GET /api/eks/clusters/{name}/capability/{cr}/status
                          │
                          └── Operator reconciles CR:
                                   ├── Phase: Provisioning
                                   │    ├── DynamoDB tables
                                   │    ├── S3 buckets
                                   │    ├── Glue database
                                   │    ├── SSM parameters
                                   │    ├── Secrets
                                   │    └── IAM role
                                   │
                                   ├── Phase: Deploying
                                   │    ├── Namespace
                                   │    ├── ServiceAccount
                                   │    ├── Backend Deployment + Service
                                   │    └── Frontend Deployment + Service
                                   │
                                   └── Phase: Running
                                        └── Deployment complete
```

---

## Validation Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                    VALIDATION PIPELINE                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────┐                                        │
│  │  cfn_yaml_loader.py │  Parse YAML with CloudFormation tags   │
│  │  (!Ref, !Sub, etc.) │                                        │
│  └──────────┬──────────┘                                        │
│             ▼                                                    │
│  ┌─────────────────────┐                                        │
│  │ template_validator  │  Validate structure, parameters,       │
│  │        .py          │  conditions, mappings, outputs         │
│  └──────────┬──────────┘                                        │
│             ▼                                                    │
│  ┌─────────────────────┐                                        │
│  │ reference_validator │  Filter false positives for !Ref       │
│  │        .py          │  to resources in same template         │
│  └──────────┬──────────┘                                        │
│             ▼                                                    │
│  ┌─────────────────────┐                                        │
│  │ dependency_validator│  Check cross-stack dependencies,       │
│  │        .py          │  circular deps, deployment order       │
│  └──────────┬──────────┘                                        │
│             ▼                                                    │
│  ┌─────────────────────┐                                        │
│  │pre_deployment_checker│  Orchestrate all validations,         │
│  │        .py          │  generate comprehensive report         │
│  └─────────────────────┘                                        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Files Reference

### Frontend
| File | Purpose |
|------|---------|
| `frontend/src/components/DeploymentExecution.tsx` | Main deployment UI with CFN and EKS handlers |
| `frontend/src/components/ArchitectureSelection.tsx` | Architecture selection (Serverless vs EKS) |
| `frontend/src/components/EKSClusterSelector.tsx` | EKS cluster selection UI |
| `frontend/src/services/api.ts` | API client for deployment and EKS endpoints |

### Backend Routers
| File | Purpose |
|------|---------|
| `backend/app/routers/deployment.py` | CloudFormation deployment endpoints |
| `backend/app/routers/eks.py` | EKS cluster and operator endpoints |
| `backend/app/routers/aws.py` | AWS authentication and session management |

### Backend Services
| File | Purpose |
|------|---------|
| `backend/app/services/deployment_service.py` | Deployment job management |
| `backend/app/services/deployment_orchestrator.py` | CloudFormation deployment orchestration |
| `backend/app/services/cloudformation_service.py` | CloudFormation stack operations |
| `backend/app/services/eks_service.py` | EKS cluster discovery and management |
| `backend/app/services/operator_deployment_service.py` | Operator deployment to EKS |

### Kubernetes Operator
| File | Purpose |
|------|---------|
| `kube-operator/src/nexus_operator/main.py` | Operator entry point and kopf handlers |
| `kube-operator/src/nexus_operator/resources/dynamodb.py` | DynamoDB provisioner |
| `kube-operator/src/nexus_operator/resources/s3.py` | S3 provisioner |
| `kube-operator/src/nexus_operator/resources/glue.py` | Glue provisioner |
| `kube-operator/src/nexus_operator/resources/ssm.py` | SSM parameter provisioner |
| `kube-operator/src/nexus_operator/resources/secrets.py` | Secrets Manager provisioner |
| `kube-operator/src/nexus_operator/resources/iam.py` | IAM role provisioner |
| `kube-operator/src/nexus_operator/resources/kubernetes.py` | K8s resource creator |
| `kube-operator/src/nexus_operator/utils/naming.py` | Resource naming conventions |

### Operator Manifests
| File | Purpose |
|------|---------|
| `kube-operator/manifests/crd.yaml` | NexusCapability CRD definition |
| `kube-operator/manifests/rbac.yaml` | Operator RBAC configuration |
| `kube-operator/manifests/deployment.yaml` | Operator deployment manifest |

---

## Error Handling

### CloudFormation Stack Failure Recovery

When a stack is in a failed state (ROLLBACK_COMPLETE, DELETE_FAILED), the system:

1. Detects the failed state
2. Deletes the failed stack
3. Cleans up orphaned resources
4. Recreates the stack from scratch

### EKS Operator Error Handling

The operator handles errors at multiple levels:

1. **CR Creation Failure**: Returns error to frontend, user can retry
2. **Provisioning Failure**: Updates CR status to "Failed" with error message
3. **Deployment Failure**: Emits Kubernetes Warning event, updates status
4. **Deletion Failure**: Logs error, emits Warning event

### Orphaned Resource Cleanup

| Stack Type | Orphaned Resources Cleaned |
|------------|---------------------------|
| backend-service | ALB, Target Groups |
| backend-storage | DynamoDB tables, S3 buckets, ECR repos |
| backend-foundation | CloudWatch log groups |
| frontend-global | WAF log groups |

---

## Logging and Progress Reporting

### CloudFormation Deployment Logs
```
[10:50:02 PM] [LAUNCH] Starting deployment process...
[10:50:02 PM] Capability: Call Processing
[10:50:02 PM] Environment: dev
[10:50:02 PM] Region: ap-southeast-1
[10:50:09 PM] [TPL] Validating CloudFormation templates...
[10:50:10 PM] [OK] Template validation passed
[10:50:19 PM] [OK] Pre-deployment validation passed
[10:50:19 PM] [LINK] Validating stack dependencies...
[10:50:20 PM] [OK] Dependency validation passed
[10:50:25 PM] [STACK] Creating backend-foundation...
```

### EKS Operator Deployment Logs
```
[10:50:02 PM] Checking if Nexus AI Operator is installed on cluster...
[10:50:05 PM] Operator already installed (version: latest)
[10:50:06 PM] Creating NexusCapability Custom Resource...
[10:50:08 PM] NexusCapability 'call-processing-dev' created in namespace 'nexus-apps'
[10:50:10 PM] [Provisioning] Provisioning AWS data services
[10:50:25 PM] [Provisioning] DynamoDB tables created
[10:50:35 PM] [Provisioning] S3 buckets created
[10:50:45 PM] [Deploying] Deploying Kubernetes workloads
[10:51:00 PM] [Running] All resources provisioned successfully
[10:51:00 PM] Frontend URL: https://app.example.com
[10:51:00 PM] Backend URL: https://api.example.com
```

---

## Related Documentation

- [DEPLOYMENT_STRATEGY_GUIDE.md](../DEPLOYMENT_STRATEGY_GUIDE.md) - Deployment strategies
- [STARTUP_GUIDE.md](../STARTUP_GUIDE.md) - Application startup
- [kube-operator/README.md](../kube-operator/README.md) - Kubernetes Operator documentation
- [README.md](../README.md) - Project overview

# Pure-Kubernetes (EKS) Deployment Path

This document describes the end-to-end Pure-EKS deployment path in the
Totogi Capability Installer: how the wizard, backend, and `kube-operator`
interact when the user chooses to install a capability into an existing
Amazon EKS cluster instead of running it on ECS/Fargate behind
CloudFormation.

The Pure-EKS path is implemented across four components:

- **Frontend wizard** (`nexus-deployer/frontend/src`) - architecture
  selection, EKS-specific configuration panel, path-aware preflight UI.
- **Backend FastAPI service** (`nexus-deployer/backend/app`) -
  per-target preflight, deployment orchestration, operator install,
  TotogiCapability CR apply.
- **kube-operator** (`nexus-deployer/kube-operator`) - Python/Kopf
  operator that owns the `TotogiCapability` CRD and reconciles AWS
  resources + Kubernetes workloads on the user's cluster.
- **Capability catalogue** (`nexus-deployer/backend/capabilities/capabilities.json`)
  - declares which deployment targets each capability supports via
  `supports_targets`.

## 10-step deployment pipeline

The Pure-EKS path is structured as a 10-step pipeline mirroring
`kube-operator/operator-nexus.sh` and `kube-operator/inspect-capability.sh`:

1. **Cluster readiness** - 10-check scan via the `EksPipelineOrchestrator`
   (see [docs/cluster-preflight.md](cluster-preflight.md)).
2. **Controllers (ALB + EBS CSI)** - install in `managed` IAM mode;
   detect-only in `preprovisioned` (admin handles entire stack).
3. **IRSA mapping** - verify each role's trust policy + attached policies.
4. **IAM audit** - `iam:SimulatePrincipalPolicy` in managed mode;
   role+trust verification in preprovisioned mode.
5. **Operator install/update** - existing `OperatorDeploymentService.deploy_operator`
   (idempotent: create-or-409-then-patch).
6. **VPC private endpoints** - apply cluster-scoped `TotogiNetworkConfig` CR
   `vpc-endpoints`; operator's `VPCEndpointProvisioner` does the EC2 work.
7. **Reachability probe** - one-shot diagnostic Pod in the capability
   namespace using the per-capability ServiceAccount (so IRSA reflects
   workload identity); DNS + TLS + IAM probes per AWS service.
8. **Provision data services** - operator handles per-CR
   (DynamoDB, S3, Glue, Athena, SSM, Secrets Manager).
9. **Deploy frontend / backend / bssmagic** - operator handles per-CR
   via `KubernetesResourceCreator`.
10. **Full capability inspection** - 17-section report mirroring
    `inspect-capability.sh` (see [docs/capability-inspection.md](capability-inspection.md)).

Wizard step ordering on the Pure-EKS path:

```
WELCOME -> CAPABILITY_SELECTION -> ARCHITECTURE_SELECTION ->
UNIFIED_ENVIRONMENT_CONFIG -> AWS_CONFIGURATION -> EKS_CLUSTER_SELECTION ->
CLUSTER_PREFLIGHT  (steps 1-4 + 6) ->
PERMISSION_VERIFICATION -> STRATEGY_SELECTION ->
DEPLOYMENT_EXECUTION  (steps 5, 8, 9; step 7 runs after operator phase Ready) ->
POST_VERIFICATION  (links to step 10 inspection) -> RESULTS
```

Backend pipeline endpoints (under `/api/eks/pipeline/`):

| Step | Endpoint |
|---|---|
| 1 | `GET    /clusters/{cluster}/readiness` |
| 2 | `POST   /clusters/{cluster}/controllers` |
| 3 | `GET    /clusters/{cluster}/irsa` |
| 4 | `GET    /clusters/{cluster}/iam-audit` |
| 6 | `POST   /clusters/{cluster}/network-config` |
| 7 | `POST   /clusters/{cluster}/reachability` |
| 10 | `GET   /clusters/{cluster}/capability/{cr}/inspect` |

Steps 5, 8, 9 are driven through the existing
`/api/eks/clusters/{cluster}/deploy-operator` and `/deploy-capability`
endpoints (operator-driven CR apply), unchanged from the prior
implementation.

## When to use Pure EKS

Pick Pure EKS when you already operate one or more EKS clusters and want
to install a capability as native Kubernetes workloads (Deployments,
Services, Ingress) under your own cluster autoscaling and RBAC. Pure EKS:

- Skips CloudFormation entirely. No app stacks are created.
- Skips ECS / Fargate / ALB-via-CFN. AWS Load Balancer Controller in your
  cluster provisions the ALBs from `Ingress` resources.
- Still provisions per-capability AWS resources (DynamoDB, S3, SSM,
  Secrets Manager, IAM/IRSA, optional Cognito) - but via the operator's
  boto3 logic, not CloudFormation.

If you need a fully cloud-agnostic install (GKE, AKS, on-prem), Pure EKS
is not the right fit; see the operator's `resources/` directory for the
AWS-specific provisioners that would need to be abstracted.

## Architecture

```
+---------------+        +-----------------------+        +--------------------------+
| Wizard        |  HTTPS |  Backend FastAPI      |  K8s   | TotogiOperator (Kopf)    |
|  - Arch       +-------->  - DeploymentTarget   +-------->  - Reconciles            |
|    Select     |        |    enum gating        |  CR    |    TotogiCapability      |
|  - EKS Config |        |  - operator_deploy.   |        |  - HPA / PDB / Ingress    |
|    Panel      |        |    service            |        |  - DynamoDB / S3 / Glue  |
|  - Permission |        |  - DeploymentOrchestr.|        |  - Cognito / IRSA        |
|    Verify     |        |    Pure-EKS branch    |        |                          |
+---------------+        +-----------+-----------+        +-----+--------------------+
                                     |                          |
                                     |   AWS API (boto3)        |  AWS API (boto3)
                                     v                          v
                               +-----------------------------------+
                               |  AWS account (DynamoDB / S3 / IAM /|
                               |  SSM / Secrets / Cognito / EKS)    |
                               +-----------------------------------+
```

## DeploymentTarget enum

The single source of truth for "which path are we on" is
`DeploymentTarget` in
[backend/app/models/deployment.py](../backend/app/models/deployment.py):

| Value                | Pipeline                                         |
| -------------------- | ------------------------------------------------ |
| `ecs_cloudformation` | Default. CloudFormation `STACK_ORDER` loop.      |
| `pure_eks`           | `_deploy_via_operator` -> apply CR -> poll status |

`DeploymentRequest` carries `deployment_target` and the Pure-EKS-only
`eks_cluster_name` / `eks_namespace`. Existing clients that pre-date
the field default to `ecs_cloudformation`, preserving the legacy
behaviour.

## End-to-end flow

1. **Architecture selection.** The user picks frontend = `Pure EKS` and
   backend = `EKS` on `ArchitectureSelection`. Selecting either side
   forces the other to EKS (mutual lock); mixed paths are not supported.
2. **Capability config.** The wizard renders `EKSConfigurationPanel` with
   tabs that mirror the `TotogiCapability` CRD: Namespace, Replicas,
   Resources, Auto Scaling (HPA + PDB), Ingress & TLS, Internal Ingress,
   Data Services, Cognito, BSS Magic.
3. **AWS auth + preflight.** `PermissionVerification` calls
   `/api/aws/verify-permissions-detailed` with
   `deployment_target: "pure_eks"`. The backend strips ECS / ALB /
   CloudFormation / CloudFront / WAF / Application Auto Scaling from the
   service matrix, runs only the EKS / ECR / IAM / data-service checks,
   and skips `verify-limits` (which counts ECS clusters).
4. **Cluster + operator.** The wizard selects the target EKS cluster
   (`EKSClusterSelector`), confirms `aws-load-balancer-controller` is
   ready (`/api/eks/clusters/{name}/alb-controller-status`), and ensures
   the operator is installed (`POST /api/eks/.../deploy-operator` if
   missing). The operator manifests are bundled with the installer (see
   `backend/backend.spec` `datas`).
5. **Deploy.** `DeploymentOrchestrator.deploy_capability` short-circuits
   into `_deploy_via_operator`, which calls
   `OperatorDeploymentService.create_capability_cr` to apply (or patch
   on `409`) the `TotogiCapability` CR, then polls
   `get_capability_status` every 5s for up to ~20 minutes.
6. **Reconciliation.** The operator goes through its phases (Pending ->
   Provisioning -> ProvisioningDataServices -> ProvisioningSSM ->
   ProvisioningSecrets -> ProvisioningIAM -> Deploying* ->
   CreatingServices -> Running -> Ready). The backend exposes the same
   phases and per-step records to the wizard via
   `eksApi.getCapabilityStatus`.
7. **Post-verification.** `PostVerification` no longer runs the mock ECS
   health checks on this path; it queries
   `eksApi.getCapabilityStatus` directly and confirms `phase` is
   `Ready` or `Running`.

## CRD shape

The CR is defined in
[kube-operator/manifests/crd.yaml](../kube-operator/manifests/crd.yaml).
Key spec fields the wizard exposes verbatim:

- `capabilityName`, `version`, `environment`, `region`, `deletionPolicy`
- `frontend` / `backend`: `{ enabled, replicas, image, resources.{requests,limits}.{cpu,memory} }`
- `enableCognito`, `adminEmail`, `cognito.{frontendUrl, callbackUrls[]}`
- `dataServices.{dynamodb,s3,glue}.enabled`
- `ingress`, `internalIngress`
- `hpa.{enabled,minReplicas,maxReplicas,targetCPUUtilization}` - reconciled by `resources/hpa.py`
- `pdb.{enabled,minAvailable|maxUnavailable}` - reconciled by `resources/pdb.py`
- `bssmagic.{enabled,image,replicas,credentialsSecretName,...}`

Backwards compatibility:
- The operator accepts both nested
  `resources.{requests,limits}.{cpu,memory}` (CRD-aligned) and the legacy
  flat `{cpu,memory,cpuLimit,memoryLimit}` shape, logging a deprecation
  warning for flat input.
- The Cognito sub-object is now declared in the CRD. The legacy
  top-level `frontendUrl` / `cognitoCallbackUrls` keys still work but are
  marked for removal; use `spec.cognito` going forward.

## Local state and migrations

TinyDB rows previously stored `deployment_type: "eks"`; this has been
renamed to `"pure_eks"`. A one-time migration in
`tinydb_deployment_state_service.__init__` rewrites legacy rows on first
boot. Read paths accept both values during the deprecation window.

## Tests

- `backend/tests/test_orchestrator_target_branch.py` - asserts Pure EKS
  never invokes `cfn_service`.
- `backend/tests/test_aws_preflight_target_aware.py` - asserts the
  service matrix is filtered to EKS-only when `deployment_target` is
  `pure_eks`.
- `backend/tests/test_operator_deployment_service.py` - asserts the CR
  body builder round-trips every supported field and drops unknown keys.
- `kube-operator/tests/test_hpa_reconciler.py` /
  `test_pdb_reconciler.py` - smoke tests for the new reconcilers.
- `kube-operator/tests/test_cr_schema_validation.py` - validates each
  example YAML against the live CRD OpenAPI; catches schema-drift
  regressions.

## Open questions / out of scope

- Cloud-agnostic Kubernetes (GKE / AKS / on-prem) is not supported. The
  operator is AWS-locked because every `resources/*.py` provisioner uses
  boto3 and IRSA.
- The deployer does not auto-install the AWS Load Balancer Controller.
  The wizard surfaces a hard prerequisite via
  `/api/eks/clusters/{name}/alb-controller-status`.
- Mixed architectures (CloudFront + EKS backend, etc.) are intentionally
  blocked by `ArchitectureSelection`; the hybrid case was previously
  unreachable because `EKSClusterSelector` was only mounted for the full
  Pure EKS configuration.

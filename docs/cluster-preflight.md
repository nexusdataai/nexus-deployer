# Pre-deployment Verification (Pure-EKS)

The wizard's **Pre-deployment Verification** step is the single screen between
EKS cluster selection and deploy. It mirrors `kube-operator/operator-nexus.sh`
in Python and folds in container-image verification + existing-capability
detection that previously lived in the legacy ECS-era PermissionVerification
screen. Each check returns `pass`, `warn`, `fail`, or `skipped` with a
remediation hint.

For Pure EKS the legacy PermissionVerification screen is bypassed entirely:
account access, network resources (AZs/VPCs/NAT), and the IAM-permissions
catalog are not re-checked - the landing-zone cluster is assumed properly
configured by the platform team.

The pipeline endpoints live under `/api/eks/pipeline/...` (see
[backend/app/routers/eks_pipeline.py](../backend/app/routers/eks_pipeline.py));
container-image verification reuses `POST /api/aws/verify-artifact`.

## 1. Cluster readiness

Probes 10 facts about the target cluster:

| Check | Pass criteria | Remediation when failing |
|---|---|---|
| `cluster_active` | `eks:DescribeCluster` returns `status=ACTIVE`, version >= 1.23 | Wait for cluster to finish creating, or upgrade the control plane |
| `oidc_provider` | OIDC issuer present + registered in IAM with `sts.amazonaws.com` audience | `eksctl utils associate-iam-oidc-provider --cluster <name> --approve` |
| `operator_iam_role` (preprovisioned only) | `nexus-operator-role` exists with IRSA trust | Admin creates role using `kube-operator/permissions/operator-policy.json` + `operator-trust-policy.json` |
| `auth_mode` | `API` or `API_AND_CONFIG_MAP` | Switch the cluster auth mode away from CONFIG_MAP-only |
| `access_entry` | Deployer principal has an Access Entry with policies attached | Deployer auto-creates during install (managed) or admin attaches |
| `node_groups` | At least one node group, each node IAM role has `AmazonEC2ContainerRegistryReadOnly` + `AmazonEKSWorkerNodePolicy` + `AmazonEKS_CNI_Policy` | Create a managed node group; attach the missing policies |
| `ecr_operator_image` | Repository `nexus-operator` exists with the `latest` tag | `./build-and-push.sh latest` from `kube-operator/` |
| `k8s_api_access` | Python kubernetes-client can `list_namespace` | Confirm Access Entry / aws-auth mapping for the deployer principal |
| `alb_controller` | `kube-system/aws-load-balancer-controller` Deployment ready | Step 2 (managed) installs it; admin installs it (preprovisioned) |
| `operator_status` | `nexus-system/nexus-operator` Deployment ready | Step 5 installs / updates it |

Endpoint: `GET /api/eks/pipeline/clusters/{cluster_name}/readiness`.

## 2. Controllers (ALB + EBS CSI)

Detect the AWS Load Balancer Controller and the EBS CSI Driver addon. In
`managed` IAM mode, missing controllers are installed (helm for ALB, EKS
managed Addon API for EBS CSI). In `preprovisioned` mode, missing controllers
return `fail` with admin-action remediation.

Endpoint: `POST /api/eks/pipeline/clusters/{cluster_name}/controllers`.

## 3. IRSA mapping

For each role (operator, ALB controller, EBS CSI, optional per-capability
app role), verifies:

1. Role exists.
2. Trust policy federates the cluster's OIDC provider.
3. `:sub` condition matches `system:serviceaccount:<ns>:<sa>`.
4. Required AWS-managed or inline policies are attached.

Endpoint: `GET /api/eks/pipeline/clusters/{cluster_name}/irsa`.

## 4. IAM audit

- **managed mode**: probes whether the deployer principal has the IAM /
  EKS mutating actions the pipeline needs (via `iam:SimulatePrincipalPolicy`).
  When `SimulatePrincipalPolicy` itself is denied, the audit softens to
  `warn` and the pipeline proceeds — real failures will surface during
  install with their original error.
- **preprovisioned mode**: confirms each of the four expected roles exists
  with correct trust + attached policies. Failure messages point at the
  canonical JSON files in `kube-operator/permissions/`.

Endpoint: `GET /api/eks/pipeline/clusters/{cluster_name}/iam-audit`.

## 6. VPC private endpoints

Provisions the 13 region-prefixed VPC endpoints **directly via boto3 EC2
calls** (see [`vpc_endpoint_provisioner.py`](../backend/app/services/vpc_endpoint_provisioner.py)).
The deployer does this itself rather than driving the operator's
`NexusNetworkConfig` CR because step 6 runs in the pre-flight wizard
step, before the operator (and its CRDs) are installed.

For region `R` (e.g. `us-east-1`) the deployer ensures:

- **Gateway endpoints** (attached to all VPC route tables):
  `com.amazonaws.R.s3`, `com.amazonaws.R.dynamodb`.
- **Interface endpoints** (attached to all cluster subnets, with the
  cluster security group, private DNS enabled):
  `com.amazonaws.R.ec2`, `.sts`, `.ssm`, `.glue`, `.ecr.api`,
  `.ecr.dkr`, `.secretsmanager`, `.logs`, `.cognito-idp`, `.athena`,
  `.events`.

Idempotent: an endpoint with the same `ServiceName` already in the VPC
is reused unchanged. Per-endpoint creation failures are surfaced as
`fail` rows; other endpoints continue.

Endpoint: `POST /api/eks/pipeline/clusters/{cluster_name}/network-config`.

The wizard reports phase `Ready` once all endpoints are in `available`
state. New interface endpoints transition `pending` -> `available` over
~1-2 minutes; while pending the step reports `Provisioning` (warn) and
deploy may proceed.

## 5. Container images

Verifies the capability's frontend and backend ECR images are pullable from
the wizard's session. Image URIs come from
`selectedCapability.eks_artifacts.frontend_ecr_uri` /
`backend_ecr_uri`. A capability whose `requirements.frontend` or
`requirements.backend` is `false` produces a `skipped` row.

Endpoint: `POST /api/aws/verify-artifact`.

## Step ordering

```
EKS_CLUSTER_SELECTION -> CLUSTER_PREFLIGHT -> STRATEGY_SELECTION (existing) /
DEPLOYMENT_EXECUTION (fresh) -> POST_VERIFICATION -> RESULTS
```

On Continue the screen runs `POST /api/deployment/detect-stacks`
(target-aware - returns Pure-EKS `NexusCapability` CRs as well as
CloudFormation stacks), persists the result in wizard context, and
routes to STRATEGY_SELECTION when `has_existing_stacks=true` or
DEPLOYMENT_EXECUTION when the cluster is fresh.

Continue is gated on every check returning `can_proceed=true`.
Warnings allow Continue. Failures block.

# Permissions & Connectivity Troubleshooting Guide

This guide covers how to diagnose and fix IAM permission failures, IRSA
misconfigurations, and VPC endpoint connectivity issues for the Totogi
operator and capability deployments.

---

## 0. AWS Access Mode (network profile)

The cluster VPC topology is owned by the provisioning script
[`deploy/eks/create-hardened-eks-cluster.sh`](../../deploy/eks/create-hardened-eks-cluster.sh).
The operator only validates that the topology matches the declared
`NexusNetworkConfig.spec.awsAccessMode` and projects the matching env vars
(`AWS_ACCESS_MODE`, `AWS_DISABLE_EXPLICIT_SERVICE_ENDPOINTS`) into backend pods.

### Quick checks

```bash
# Inspect the CR (Mode column comes from status.activeMode)
kubectl get nexusnetworkconfigs.nexus.ai vpc-endpoints

# Read full status (phase, validation.missing, endpoints)
kubectl describe nexusnetworkconfigs.nexus.ai vpc-endpoints

# Verify the backend pod is running the expected mode
kubectl port-forward svc/nexus-ai-dev-backend 8000:8000 &
curl -s http://localhost:8000/api/v1/health/aws | jq .
# {
#   "aws_access_mode": "lowest-cost",
#   "explicit_endpoints_disabled": true,
#   "region": "us-east-1",
#   "sts_identity": { "account": "111122223333", "arn": "...", "userId": "..." }
# }
```

### Common failures

| Symptom | Cause | Fix |
|---|---|---|
| `phase=Error`, `validation.missing=["interface:sts",...]` | `awsAccessMode=higher-cost` but interface endpoints were never provisioned | Re-run `create-hardened-eks-cluster.sh --network-profile higher-cost --vpc-id <existing>` |
| `phase=Error`, `validation.missing=["nat-instance:expected=2,found=1"]` | `awsAccessMode=moderate` but only single NAT was provisioned (AZ2 ASG didn't come up) | `aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names <cluster>-nat-az2` and check `Instances[].HealthStatus`; fall back to `lowest-cost` if AMI is unavailable in that AZ |
| Backend pod still uses old endpoints after flipping mode | Operator hasn't re-reconciled the capability yet | `kubectl annotate nexuscapability nexus-ai-dev reconcile=$(date +%s) --overwrite` |
| `validation.actual != validation.expected` | VPC tag `nexus:network-profile` is stale (cluster created on a different profile) | Re-run the provisioning script with the matching `--network-profile`; or update the tag manually: `aws ec2 create-tags --resources <vpc-id> --tags Key=nexus:network-profile,Value=<mode>` |
| `OPERATOR_PROVISION_LEGACY=true` on a script-provisioned cluster | Operator may try to re-create endpoints that the script already owns | Set the env var to `false` in `deployment.yaml` and roll the operator |

### Switching modes — step by step

```bash
# 1. Provisioning script: rewires topology in place (idempotent)
./deploy/eks/create-hardened-eks-cluster.sh \
    --name nexus-dev --network-profile lowest-cost --vpc-id $(
      aws eks describe-cluster --name nexus-dev --query 'cluster.resourcesVpcConfig.vpcId' --output text
    )

# 2. Operator: flip the declared mode
kubectl patch nexusnetworkconfig vpc-endpoints --type=merge \
    -p '{"spec":{"awsAccessMode":"lowest-cost"}}'

# 3. Wait for revalidation (operator timer fires every 5 min, or annotate to force)
kubectl annotate nexuscapability nexus-ai-dev reconcile=$(date +%s) --overwrite

# 4. Confirm
kubectl get nexusnetworkconfig vpc-endpoints
curl -s http://localhost:8000/api/v1/health/aws | jq .aws_access_mode
```

---

## 1. Quick Reference — Available Check Commands

All commands are run from the `kube-operator/` directory.

| Command | Alias | What It Does |
|---|---|---|
| `./operator-starhub-test.sh check-operator-permissions` | `check-operator` | Runs a Job in `totogi-system` as the operator SA — validates every IAM permission from `operator-policy.json` and tests reachability of 15 VPC endpoints |
| `./operator-starhub-test.sh check-app-permissions` | `check-app` | Creates a temporary Job in `call-processing-{env}` as the app SA — validates every IAM permission from `app-policy.json` and tests reachability of 15 VPC endpoints |
| `./operator-starhub-test.sh check-endpoints` | `endpoints-status` | Displays the status of the `TotogiNetworkConfig` CR (read-only kubectl output) |
| `./operator-starhub-test.sh setup-endpoints` | `endpoints` | Applies the `TotogiNetworkConfig` CRD and CR, then monitors the operator as it provisions VPC endpoints |

---

## 2. Using the Permission Check Tools

### 2.1 Operator Permission Check

```bash
./operator-starhub-test.sh check-operator
```

**What happens under the hood:**

1. Reads the operator deployment in `totogi-system` to discover its ServiceAccount name and IRSA role ARN.
2. Creates a ConfigMap `operator-perm-check` from `check-operator-permissions.py`.
3. Launches a Kubernetes Job `check-operator-permissions` using the operator's ServiceAccount (so the Job assumes the same IRSA role as the operator pod).
4. Streams the Job's logs in real-time and waits up to ~3 minutes for completion.
5. Deletes the Job and ConfigMap.

**How to read the output:**

The script tests each permission group (matching the Sids in `operator-policy.json`) and prints a verdict per API call:

| Verdict | Meaning |
|---|---|
| `[OK]` | API call succeeded or returned a safe "not found" error — permission is granted |
| `[DENIED]` | `AccessDenied` / `AccessDeniedException` — the IAM policy is missing this permission |
| `[NO ENDPOINT]` | Call timed out or connection was refused — VPC endpoint for this service does not exist or is unreachable |
| `[ERROR]` | Unexpected error (client initialization failure, malformed response, etc.) |

The second section tests VPC endpoint reachability with `[REACHABLE]` / `[UNREACHABLE]` verdicts.

**Summary lines:**

```
PERMISSIONS:  23 OK  |  0 DENIED  |  0 NO ENDPOINT  |  0 ERROR
ENDPOINTS:    15 REACHABLE  |  0 UNREACHABLE
```

A clean run shows all permissions OK and all endpoints REACHABLE.

To run the same logic **interactively** (exec into the operator pod, copy `check-operator-permissions.py`, or use a one-off pod with the AWS CLI), see **Section 3.3**.

### 2.2 App Permission Check

```bash
./operator-starhub-test.sh check-app
```

Same pattern as the operator check, with these differences:

- **Namespace:** `call-processing-{env}` (e.g. `call-processing-stage`)
- **ServiceAccount:** `call-processing-{env}-app-sa` with IRSA annotation pointing to `call-processing-{env}-app-role`
- The script creates the namespace and SA if they do not exist, and cleans them up after the Job completes (only if the script created them).
- Environment variables `CAPABILITY`, `ENV`, `REGION` are injected into the Job so the check script tests capability-specific resource ARNs (table names, S3 buckets, SSM paths, Glue databases, etc.).
- **Exit code:** 0 if all permissions pass and all endpoints are reachable, 1 otherwise.

For interactive **app** checks (exec, `kubectl cp`, or AWS CLI with the app ServiceAccount), see **Section 3.3**.

### 2.3 If the Job Fails to Start

If the Job pod stays in `Pending`:

```bash
kubectl describe pod -l job-name=check-operator-permissions -n totogi-system
kubectl describe pod -l job-name=check-app-permissions -n call-processing-stage
```

Common causes: ECR image not found (check `ai-job-engine:latest` exists), insufficient node resources, or image pull errors (missing `ecr.dkr` / `ecr.api` VPC endpoints).

---

## 3. Interactive Debugging Commands

When the automated check scripts are unavailable or you need ad-hoc verification.

### 3.1 From the Jumpbox

**Verify your current identity:**

```bash
aws sts get-caller-identity
```

**Check if kubectl works:**

```bash
kubectl get nodes
kubectl auth whoami   # EKS 1.24+
```

**Test Kubernetes RBAC for a ServiceAccount:**

```bash
# Can the operator SA create DynamoDB tables?
kubectl auth can-i create dynamodbtables --as=system:serviceaccount:totogi-system:totogi-operator

# Can the app SA list pods in its namespace?
kubectl auth can-i list pods --as=system:serviceaccount:call-processing-stage:call-processing-stage-app-sa \
  -n call-processing-stage
```

**Verify IRSA annotation on a ServiceAccount:**

```bash
# Operator SA
kubectl get sa totogi-operator -n totogi-system -o jsonpath='{.metadata.annotations.eks\.amazonaws\.com/role-arn}'

# App SA
kubectl get sa call-processing-stage-app-sa -n call-processing-stage \
  -o jsonpath='{.metadata.annotations.eks\.amazonaws\.com/role-arn}'
```

**Launch a temporary pod with a specific ServiceAccount for manual testing:**

```bash
# Operator role
kubectl run perm-debug --rm -it --restart=Never \
  -n totogi-system \
  --overrides='{"spec":{"serviceAccountName":"totogi-operator"}}' \
  --image=python:3.11-slim -- bash

# Inside the pod:
pip install boto3 && python3 -c "
import boto3
sts = boto3.client('sts', region_name='ap-southeast-1')
print(sts.get_caller_identity()['Arn'])
"
```

**Quick exec into the running operator pod:**

```bash
POD=$(kubectl get pod -n totogi-system -l app.kubernetes.io/name=totogi-operator \
  -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n totogi-system $POD -c operator -- python3 -c "
import boto3
sts = boto3.client('sts', region_name='ap-southeast-1')
print(sts.get_caller_identity()['Arn'])
"
```

### 3.2 From Inside a Pod

**Test a specific AWS service with Python:**

```python
import boto3
from botocore.config import Config

cfg = Config(connect_timeout=5, read_timeout=5, retries={"max_attempts": 0})
region = "ap-southeast-1"

# DynamoDB
ddb = boto3.client("dynamodb", region_name=region, config=cfg)
print(ddb.list_tables(Limit=1))

# S3
s3 = boto3.client("s3", region_name=region, config=cfg)
print(s3.list_buckets())

# SSM
ssm = boto3.client("ssm", region_name=region, config=cfg)
print(ssm.get_parameters_by_path(Path="/call-processing/stage/", MaxResults=1))

# Secrets Manager
sm = boto3.client("secretsmanager", region_name=region, config=cfg)
print(sm.list_secrets(MaxResults=1))

# Glue
glue = boto3.client("glue", region_name=region, config=cfg)
print(glue.get_databases(MaxResults=1))
```

**Test VPC endpoint DNS resolution (from any pod with curl/nslookup):**

```bash
# Interface endpoints resolve via private DNS
nslookup dynamodb.ap-southeast-1.amazonaws.com
nslookup ssm.ap-southeast-1.amazonaws.com
nslookup sts.ap-southeast-1.amazonaws.com

# S3 (gateway endpoint — uses public DNS, routed via VPC route table)
nslookup s3.ap-southeast-1.amazonaws.com

# Test HTTPS connectivity to an interface endpoint
curl -s -o /dev/null -w "%{http_code}" https://sts.ap-southeast-1.amazonaws.com/
```

### 3.3 Interactive operator / app pods and AWS CLI checks

Use this when you want a shell inside the cluster with the **same IRSA identity** as the operator or app, without going through the Batch Job wrapper.

**Defaults used below:** adjust `REGION`, namespace, ServiceAccount, and IAM role names to match your cluster. The automated scripts use `totogi-system` / `totogi-operator` (operator) and `call-processing-{env}` / `call-processing-{env}-app-sa` (app), with `REGION` from `operator-starhub-test.sh` (often `ap-southeast-1`).

#### 3.3.1 Run the official Python check inside the running operator pod

The operator container is named `operator`. It includes Python and the operator dependencies (boto3). This matches what `check-operator` does, except you run the script by hand.

```bash
cd kube-operator

OP_POD=$(kubectl get pod -n totogi-system -l app.kubernetes.io/name=totogi-operator \
  -o jsonpath='{.items[0].metadata.name}')

kubectl cp check-operator-permissions.py "totogi-system/${OP_POD}:/tmp/check-operator-permissions.py" -c operator

kubectl exec -n totogi-system -c operator "$OP_POD" -- python3 /tmp/check-operator-permissions.py
```

`check-operator-permissions.py` has a fixed `REGION = "ap-southeast-1"` at the top; edit that line if your cluster is in another region, or rely on `./operator-starhub-test.sh check-operator` (which uses the script from the repo without editing the pod copy).

#### 3.3.2 Interactive shell on the operator pod

```bash
kubectl exec -n totogi-system deploy/totogi-operator -c operator -it -- /bin/sh
# If /bin/sh is missing, try: -- python3 (no TTY) or use a debug pod below.
```

From there you can run short boto3 one-liners (same as Section 3.2) using the pod’s IRSA credentials.

#### 3.3.3 App role: Python check or shell in an app pod

If a capability workload is already running, exec into one of its pods that uses `call-processing-{env}-app-sa` (or your capability’s app ServiceAccount) and run boto3 checks.

To run the **same script as `check-app`** without the Job:

```bash
cd kube-operator

CAP=call-processing
ENV=stage   # must match DEPLOY_ENV / namespace suffix
APP_NS="${CAP}-${ENV}"
APP_SA="${CAP}-${ENV}-app-sa"

APP_POD=$(kubectl get pod -n "$APP_NS" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
# Pick a pod whose spec.serviceAccountName matches APP_SA if you have multiple workloads.

kubectl cp check-app-permissions.py "${APP_NS}/${APP_POD}:/tmp/check-app-permissions.py"

kubectl exec -n "$APP_NS" "$APP_POD" -- env CAPABILITY="$CAP" ENV="$ENV" REGION="ap-southeast-1" \
  python3 /tmp/check-app-permissions.py
```

Set `REGION` to your cluster region. `CAPABILITY`, `ENV`, and `REGION` must match what the Job injects (see `check-app` in `operator-starhub-test.sh`).

If no app pod exists yet, use a one-off debug pod with the app ServiceAccount (next subsection).

#### 3.3.4 One-off pod with AWS CLI (operator or app IRSA)

EKS injects `AWS_WEB_IDENTITY_TOKEN_FILE` and `AWS_ROLE_ARN` for the pod’s ServiceAccount. An **AWS CLI v2** image will use them automatically—no access keys.

**Do not use `--serviceaccount`** (deprecated in current `kubectl run` and **has no effect**). Set the account with **`--overrides`** and `spec.serviceAccountName` instead (same pattern as Section 3.1).

**App ServiceAccount must exist.** `./operator-starhub-test.sh check-app` may **delete** `call-processing-stage-app-sa` afterward if the script created it only for the Job. If `kubectl` reports `serviceaccount ... not found`, create the namespace (if needed) and apply a ServiceAccount with your IRSA role ARN:

```bash
# Replace ACCOUNT_ID with your AWS account ID
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: ServiceAccount
metadata:
  name: call-processing-stage-app-sa
  namespace: call-processing-stage
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT_ID:role/call-processing-stage-app-role
EOF
```

**`timed out waiting for the condition` / pod deleted with no output:** `kubectl run -it --rm` waits for the pod to be **running** before attach. The default **`--pod-running-timeout` is only ~1 minute**. On private EKS clusters, pulling `public.ecr.aws/aws-cli/aws-cli` often needs outbound path or cache and can exceed that—kubectl gives up and deletes the pod (`--rm`). **Fix:** pass a longer timeout, e.g. `--pod-running-timeout=5m` (or `10m`), or use the **no-attach** flow below so you can `kubectl describe pod` while it is `Pending`.

**Recommended (no TTY; works when attach times out):** use a unique pod name, wait until phase is `Succeeded` or `Failed`, then read logs.

```bash
POD="aws-cli-app-$(date +%s)"
kubectl run "$POD" --restart=Never -n call-processing-stage \
  --image=public.ecr.aws/aws-cli/aws-cli \
  --overrides='{"spec":{"serviceAccountName":"call-processing-stage-app-sa"}}' \
  --command -- aws sts get-caller-identity

for _ in $(seq 1 90); do
  phase=$(kubectl get pod "$POD" -n call-processing-stage -o jsonpath='{.status.phase}' 2>/dev/null)
  [ "$phase" = "Succeeded" ] || [ "$phase" = "Failed" ] && break
  sleep 2
done
kubectl logs "pod/$POD" -n call-processing-stage
kubectl delete pod "$POD" -n call-processing-stage --ignore-not-found
```

If phase stays **`Pending`** for the whole loop, run **`kubectl describe pod "$POD" -n call-processing-stage`** (image pull / `ImagePullBackOff`, quota, Pod Security). Pulling from `public.ecr.aws` requires a path to the internet or an **ECR pull-through cache** / mirror on private clusters.

**Operator identity** (attach + longer running timeout):

```bash
kubectl run aws-cli-operator --rm -it --restart=Never \
  -n totogi-system \
  --image=public.ecr.aws/aws-cli/aws-cli \
  --overrides='{"spec":{"serviceAccountName":"totogi-operator"}}' \
  --pod-running-timeout=5m \
  --command -- aws sts get-caller-identity
```

**App identity** (same pattern):

```bash
kubectl run aws-cli-app --rm -it --restart=Never \
  -n call-processing-stage \
  --image=public.ecr.aws/aws-cli/aws-cli \
  --overrides='{"spec":{"serviceAccountName":"call-processing-stage-app-sa"}}' \
  --pod-running-timeout=5m \
  --command -- aws sts get-caller-identity
```

For an interactive shell, omit `--command` and trailing args (cluster policy permitting); still add **`--pod-running-timeout=5m`** if the shell hangs or times out:

```bash
kubectl run aws-cli-debug --rm -it --restart=Never \
  -n totogi-system \
  --image=public.ecr.aws/aws-cli/aws-cli \
  --overrides='{"spec":{"serviceAccountName":"totogi-operator"}}' \
  --pod-running-timeout=5m
```

If your cluster enforces **restricted Pod Security Standards**, `kubectl run` may be blocked or the image may need an explicit `securityContext`. In that case prefer `kubectl exec` on an existing pod (Sections 3.3.1–3.3.2) or apply a small `debug-pod.yaml` with your platform team’s required fields.

#### 3.3.5 AWS CLI: read-only probes aligned with operator policy

Run inside the operator IRSA pod (Section 3.3.4). Replace `REGION` and `totogi-operator-role` if yours differ. These mirror the checks in `check-operator-permissions.py` / `operator-policy.json`; expect `AccessDenied` or “not found” messages when IAM or resources are missing—that still proves **network + credentials** reached the API.

```bash
export AWS_REGION=ap-southeast-1   # or pass --region ap-southeast-1 on each command

aws sts get-caller-identity

aws dynamodb list-tables --max-items 1
aws dynamodb describe-table --table-name nonexistent-check-12345 2>&1 | head -5

aws s3 ls
aws s3api get-bucket-location --bucket nonexistent-check-12345 2>&1 | head -3

aws ssm get-parameter --name /nonexistent/check/12345 2>&1 | head -3
aws ssm get-parameters-by-path --path /nonexistent/check --max-results 1 2>&1 | head -5

aws secretsmanager list-secrets --max-items 1 2>&1 | head -5
aws secretsmanager describe-secret --secret-id nonexistent-check-12345 2>&1 | head -5

aws glue get-databases --max-items 1
aws glue get-database --name nonexistent_check_12345 2>&1 | head -5

aws iam get-role --role-name totogi-operator-role 2>&1 | head -5
aws iam get-role-policy --role-name totogi-operator-role --policy-name totogi-operator-policy 2>&1 | head -5

aws eks list-clusters
aws eks describe-cluster --name nonexistent-check-12345 2>&1 | head -5

aws cognito-idp list-user-pools --max-results 1

aws ec2 describe-vpcs --max-results 5
aws ec2 describe-vpc-endpoints --max-results 5
aws ec2 describe-subnets --max-results 5
aws ec2 describe-security-groups --max-results 5
aws ec2 describe-route-tables --max-results 5

aws athena list-work-groups --max-results 1 2>&1 | head -5
aws events list-event-buses 2>&1 | head -5
```

**Note:** `iam.amazonaws.com` and (without a VPC interface endpoint) some regional APIs may fail with timeouts or TLS errors from private subnets; compare with Section 4.7 and the VPC endpoint list in Section 5.

#### 3.3.6 AWS CLI: read-only probes aligned with app policy

Run inside the app IRSA pod. Set `CAP`, `ENV`, and `REGION`. Table/bucket/SSM paths match `check-app-permissions.py`.

```bash
export AWS_REGION=ap-southeast-1
CAP=call-processing
ENV=stage
PREFIX="${CAP}-${ENV}"

aws sts get-caller-identity

aws dynamodb list-tables --max-items 1
aws dynamodb describe-table --table-name "${PREFIX}-transformation-system" 2>&1 | head -5

aws s3 ls
aws s3api get-bucket-location --bucket "${PREFIX}-journey-logs-000000000000" 2>&1 | head -3

aws ssm get-parameters-by-path --path "/${CAP}/${ENV}/" --max-results 1 2>&1 | head -5
aws ssm get-parameter --name "/${CAP}/${ENV}/test-nonexistent" 2>&1 | head -3

aws secretsmanager list-secrets --max-items 1 2>&1 | head -5
aws secretsmanager describe-secret --secret-id "${CAP}/${ENV}/api-keys" 2>&1 | head -5

DB_NAME="${CAP//-/_}_${ENV//-/_}_db"
aws glue get-databases --max-items 1
aws glue get-database --name "$DB_NAME" 2>&1 | head -5

aws athena list-work-groups --max-results 1 2>&1 | head -5
aws cognito-idp list-user-pools --max-results 1
aws logs describe-log-groups --limit 1 2>&1 | head -5
```

For a full pass/fail report (including VPC endpoint reachability rows), prefer `./operator-starhub-test.sh check-operator` or `check-app` from `kube-operator/`.

---

## 4. Common Errors and Fixes

### 4.1 `[DENIED]` on All Permission Checks

**Symptom:** Every API call returns `AccessDenied`.

**Cause:** The pod is not assuming the IRSA role. It falls back to the EC2 instance role (node role), which has no application permissions.

**Fix:**

1. Verify the ServiceAccount has the IRSA annotation:
   ```bash
   kubectl get sa <sa-name> -n <namespace> -o yaml | grep role-arn
   ```
2. Verify the IAM role exists:
   ```bash
   aws iam get-role --role-name <role-name>
   ```
3. Verify the trust policy allows the correct ServiceAccount:
   ```bash
   aws iam get-role --role-name <role-name> --query "Role.AssumeRolePolicyDocument"
   ```
   The `sub` condition must match `system:serviceaccount:<namespace>:<sa-name>`.

### 4.2 `[NO ENDPOINT]` on All Permission Checks

**Symptom:** Every API call times out after 8 seconds.

**Cause:** The cluster runs in a private VPC without NAT Gateway and the required VPC endpoints have not been created.

**Fix:**

1. Check existing VPC endpoints:
   ```bash
   aws ec2 describe-vpc-endpoints \
     --filters "Name=vpc-id,Values=<vpc-id>" \
     --query "VpcEndpoints[].{Service:ServiceName,State:State,Type:VpcEndpointType}" \
     --output table
   ```
2. Ask the admin to create missing endpoints (see Section 5 below).
3. Verify security groups on interface endpoints allow inbound TCP 443 from the cluster's CIDR.

### 4.3 `AssumeRoleWithWebIdentity` Access Denied

**Symptom:** Pod logs show `An error occurred (AccessDenied) when calling the AssumeRoleWithWebIdentity operation`.

**Cause:** The IAM role's trust policy does not match the pod's ServiceAccount token. Common sub-causes:

- Trust policy uses `StringEquals` for the `sub` condition but the value contains a wildcard (`*`). Wildcards only work with `StringLike`.
- The OIDC provider ARN in the trust policy does not match the cluster's OIDC issuer.
- The ServiceAccount namespace or name in the `sub` condition is wrong.

**Fix:**

For roles where the `sub` condition uses a wildcard (e.g. app roles):
```json
"Condition": {
  "StringLike": {
    "oidc.eks.<region>.amazonaws.com/id/<ID>:sub":
      "system:serviceaccount:<namespace>:*"
  },
  "StringEquals": {
    "oidc.eks.<region>.amazonaws.com/id/<ID>:aud": "sts.amazonaws.com"
  }
}
```

For roles with an exact SA match (e.g. operator role), `StringEquals` is correct:
```json
"StringEquals": {
  "oidc.eks.<region>.amazonaws.com/id/<ID>:sub":
    "system:serviceaccount:totogi-system:totogi-operator"
}
```

**`check-app` and `call-processing-{env}-app-role` (most common):**

The Job uses namespace **`call-processing-{env}`** and ServiceAccount **`call-processing-{env}-app-sa`** (e.g. `call-processing-stage` / `call-processing-stage-app-sa`). The JWT `sub` claim is:

`system:serviceaccount:call-processing-stage:call-processing-stage-app-sa`

The template in `app-trust-policy.json` allows any SA in that namespace via:

`system:serviceaccount:call-processing-stage:*`

If you still see **`AssumeRoleWithWebIdentity` / Not authorized**, the role is almost always trusting the **wrong OIDC issuer** (cluster ID) — for example the role was created when the workload pointed at another cluster, or the issuer in IAM does not match **this** EKS cluster’s issuer.

Verify and fix from a machine with IAM + EKS API access:

```bash
export CLUSTER_NAME="SH-BSS-Magic-DEV-EKS-Cluster-Green"   # your cluster
export REGION="ap-southeast-1"
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export OIDC_PROVIDER=$(aws eks describe-cluster --name "$CLUSTER_NAME" --region "$REGION" \
  --query "cluster.identity.oidc.issuer" --output text | sed 's|https://||')

echo "Issuer (no https): $OIDC_PROVIDER"

aws iam get-role --role-name call-processing-stage-app-role \
  --query "Role.AssumeRolePolicyDocument" --output json
```

Confirm the **`Federated` ARN** uses `oidc-provider/${OIDC_PROVIDER}` with the **same** `OIDC_PROVIDER` as above. Condition keys must use the same host (`oidc.eks.<region>.amazonaws.com/id/<same-id>:sub` and `:aud`).

Re-apply trust (after editing placeholders with `sed` as in `ADMIN-SETUP.md` Step 5):

```bash
export CAPABILITY="call-processing"
export ENV="stage"
export ROLE_NAME="${CAPABILITY}-${ENV}-app-role"
sed -e "s|\${ACCOUNT_ID}|${ACCOUNT_ID}|g" \
    -e "s|\${OIDC_PROVIDER}|${OIDC_PROVIDER}|g" \
    -e "s|\${CAPABILITY}|${CAPABILITY}|g" \
    -e "s|\${ENV}|${ENV}|g" \
    permissions/app-trust-policy.json > /tmp/app-trust.json

aws iam update-assume-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-document file:///tmp/app-trust.json
```

Also confirm the IAM OIDC provider exists and includes audience **`sts.amazonaws.com`** (see `ADMIN-SETUP.md` Step 1).

### 4.4 `401 Unauthorized` from kubectl

**Symptom:** `kubectl get nodes` returns `error: You must be logged in to the server (Unauthorized)`.

**Cause:** The IAM role used by kubectl is not in the cluster's `aws-auth` ConfigMap or EKS access entries.

**Fix (admin action):**

```bash
# Option A: EKS Access Entry (if cluster auth mode is API or API_AND_CONFIG_MAP)
aws eks create-access-entry \
  --cluster-name <cluster-name> \
  --principal-arn arn:aws:iam::<account>:role/<role-name> \
  --type STANDARD

aws eks associate-access-policy \
  --cluster-name <cluster-name> \
  --principal-arn arn:aws:iam::<account>:role/<role-name> \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy \
  --access-scope type=cluster

# Option B: aws-auth ConfigMap (if cluster auth mode is CONFIG_MAP)
kubectl edit configmap aws-auth -n kube-system
# Add the role ARN under mapRoles with system:masters group
```

### 4.5 Job Pod Stuck in `Pending`

**Symptom:** `kubectl get pod -l job-name=check-operator-permissions -n totogi-system` shows `Pending`.

**Cause (most common):**

| Sub-cause | How to Identify | Fix |
|---|---|---|
| ECR image not found | `kubectl describe pod ...` shows `ErrImagePull` | Push `ai-job-engine:latest` to ECR: `aws ecr create-repository ...` then `crane push ...` |
| ECR endpoints missing | `Failed to pull image ... i/o timeout` | Create `ecr.api` and `ecr.dkr` VPC endpoints |
| Node resources exhausted | Events show `Insufficient cpu` or `Insufficient memory` | Scale the node group or reduce other workloads |

### 4.6 Operator Pod in `CrashLoopBackOff`

**Symptom:** `kubectl get pods -n totogi-system` shows the operator with many restarts and `CrashLoopBackOff`.

**Cause:** A pending `TotogiCapability` CR triggers the operator's reconciliation loop. Without VPC endpoints, the operator cannot reach DynamoDB/Glue/S3 and eventually gets OOM-killed (exit code 137).

**Fix:**

```bash
# 1. Remove the pending capability to stop the crash loop
kubectl delete totogicapability <name> -n <namespace> --timeout=30s 2>/dev/null || \
  kubectl patch totogicapability <name> -n <namespace> \
    --type merge -p '{"metadata":{"finalizers":[]}}'

# 2. Delete the crashing pod (deployment will recreate it)
kubectl delete pod -n totogi-system -l app.kubernetes.io/name=totogi-operator

# 3. Wait for the new pod to stabilize (no pending capability = no crash)
sleep 30 && kubectl get pods -n totogi-system
```

Once stable, create the required VPC endpoints before re-applying any capability.

### 4.7 IAM API Unreachable from Jumpbox

**Symptom:** `aws iam get-role ...` returns `Connection was closed before we received a valid response from endpoint URL: "https://iam.amazonaws.com/"`.

**Cause:** IAM is a global service (`iam.amazonaws.com`). There is no regional VPC endpoint for IAM in most setups. The jumpbox has no NAT Gateway or internet route.

**Fix:** IAM operations must be performed from a machine with internet access (admin workstation or AWS Console). See `ADMIN-SETUP.md` for the full list of admin steps.

Note: The `iam` VPC Interface endpoint (`com.amazonaws.<region>.iam`) does exist as a PrivateLink service but is rarely configured. If your cluster needs IAM API access from within the VPC, the admin can create it (see Section 5).

### 4.8 `[DENIED]` on Only Some Checks

**Symptom:** Most checks pass but a few specific Sids show `[DENIED]`.

**Fix:** Compare the denied actions against the relevant policy file:

| Role | Policy File |
|---|---|
| Operator | `permissions/operator-policy.json` |
| App | `permissions/app-policy.json` |

Update the IAM role's inline policy:
```bash
aws iam put-role-policy \
  --role-name <role-name> \
  --policy-name <policy-name> \
  --policy-document file://permissions/<policy-file>.json
```

### 4.9 `SSLError` / certificate verify failed on IAM or Athena (VPC endpoint shows REACHABLE)

**Symptom:** Permission or endpoint checks report **`SSLError: SSL validation failed`** for `https://iam.amazonaws.com/` or `https://athena.<region>.amazonaws.com/`, while the VPC endpoint table still marks **`com.amazonaws.<region>.iam`** or **`athena`** as REACHABLE (often with note `SSLError (TLS/route?)`).

**What that means:** TCP connectivity to the interface endpoint is working (you are not timing out). TLS starts, but **Python’s OpenSSL rejects the server certificate** (or the hostname check fails). That is different from “no endpoint”.

**Typical root causes:**

| Cause | Why |
|---|---|
| **Stale CA bundle in the container image** | Old `certifi` / OS trust store does not include a root that signs AWS’s current certs. |
| **TLS inspection (corporate proxy / firewall)** | A middlebox terminates TLS and presents a **private CA** cert; the pod trusts only public roots → verify fails. |
| **Hostname / SNI mismatch** | Less common with PrivateLink; can occur with mis-routed DNS or non-standard proxies. |

**Preferred fixes (production):**

1. **Refresh the workload image** (rebuild `ai-job-engine` / operator base with current `ca-certificates` and `certifi`).
2. If you use **SSL inspection**, install your org’s **root CA** into the image or mount it and set `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` so botocore trusts it.
3. Confirm **private DNS** for the interface endpoint matches AWS docs (no split-horizon DNS pointing the same name elsewhere).

**Debug-only bypass (not for production):** The check scripts honor environment variable **`PERM_CHECK_SSL_VERIFY`**. When set to `0`, `false`, `no`, or `off`, boto3 uses `verify=False` (TLS encryption still on; certificate identity is not checked).

```bash
PERM_CHECK_SSL_VERIFY=0 ./operator-starhub-test.sh check-operator
PERM_CHECK_SSL_VERIFY=0 ./operator-starhub-test.sh check-app
```

The Job manifests pass `PERM_CHECK_SSL_VERIFY` through from your shell (default `1` = normal verification).

### 4.10 Operator: `cannot list resource "totoginetworkconfigs"` (403) after redeploy

**Symptom:** Kopf logs show `User "system:serviceaccount:totogi-system:totogi-operator" cannot list resource "totoginetworkconfigs" ... at the cluster scope`.

**Cause:** `./operator-starhub-test.sh deploy` runs `backend/scripts/deploy_operator_to_cluster.py`, which creates/replaces **ClusterRole `totogi-operator-role`** (and binding `totogi-operator-binding`). That role is **not** the same object as **`ClusterRole/totogi-operator`** in `kube-operator/manifests/rbac.yaml`. If the Python deploy path never included `totoginetworkconfigs`, every redeploy kept a role **without** those permissions—applying `rbac.yaml` alone does not update `totogi-operator-role` unless you also bind the SA to that separate role.

**Fix:** Deploy from a tree where `operator_deployment_service._create_rbac()` includes **`totoginetworkconfigs`** (and subresources), then re-run deploy with **`--force`**, or patch the live role:

```bash
kubectl get clusterrole totogi-operator-role -o yaml   # confirm rules
# Re-run: cd ../backend && python3 scripts/deploy_operator_to_cluster.py --cluster <name> --region <region> --profile <profile> --force
kubectl rollout restart deployment/totogi-operator -n totogi-system
```

**Verify:**

```bash
kubectl auth can-i list totoginetworkconfigs --as=system:serviceaccount:totogi-system:totogi-operator
```

### 4.11 `InvalidIdentityToken` / No OpenIDConnect provider for `oidc.eks.../id/...`

**Symptom:** Operator logs during capability reconcile show:

`AssumeRoleWithWebIdentity ... InvalidIdentityTokenException: No OpenIDConnect provider found in your account for https://oidc.eks.<region>.amazonaws.com/id/<OIDC_ID>`

**Cause:** The pod’s projected service-account token names your cluster’s **OIDC issuer URL**, but **IAM in that AWS account has no OIDC identity provider** registered for that URL. IRSA always fails until the provider exists (with audience `sts.amazonaws.com`). This is unrelated to Kubernetes RBAC.

**Common situations:**

| Situation | What to check |
|---|---|
| Provider never created | Run IAM setup from `ADMIN-SETUP.md` Step 1 or `./operator-starhub-test.sh fix-irsa` (from a machine with IAM API access). |
| **Wrong cluster / Blue–Green** | The token’s `<OIDC_ID>` must match **this** EKS cluster. Compare `aws eks describe-cluster --name <cluster> --query cluster.identity.oidc.issuer` with the URL in the error. If you moved workloads to a new cluster, register **that** cluster’s issuer and update role trust policies. |
| **Wrong AWS account** | OIDC provider must exist in the **same account** as `totogi-operator-role`. |

**Verify (replace account and issuer path):**

```bash
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export CLUSTER_NAME="<your-cluster-name>"
export REGION="ap-southeast-1"
export OIDC_ISSUER=$(aws eks describe-cluster --name "$CLUSTER_NAME" --region "$REGION" \
  --query "cluster.identity.oidc.issuer" --output text)
export OIDC_HOSTPATH="${OIDC_ISSUER#https://}"

aws iam get-open-id-connect-provider \
  --open-id-connect-provider-arn "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/${OIDC_HOSTPATH}"
```

`NoSuchEntity` means you must **create** the provider (see `ADMIN-SETUP.md` Step 1 — thumbprint + `create-open-id-connect-provider`, audience `sts.amazonaws.com`).

**After the provider exists**, restart the operator pod so boto3 refreshes credentials: `kubectl rollout restart deployment/totogi-operator -n totogi-system`.

---

## 5. VPC Endpoint Diagnostics

### 5.1 Required Endpoints (15 Total)

The check scripts test reachability of all 15 endpoints. The operator's VPC endpoint provisioner (`setup-endpoints`) auto-creates 12 of these; the remaining 3 (`ec2`, `eks`, `iam`) must be created by the admin if needed.

**Gateway Endpoints (2)** — route table-based, no security group needed:

| Service | Endpoint Name | Used By |
|---|---|---|
| S3 | `com.amazonaws.<region>.s3` | Operator + App |
| DynamoDB | `com.amazonaws.<region>.dynamodb` | Operator + App |

**Interface Endpoints (13)** — ENI-based, require security group allowing TCP 443:

| Service | Endpoint Name | Used By | Auto-Created by Operator |
|---|---|---|---|
| EC2 | `com.amazonaws.<region>.ec2` | Operator (VPC endpoint management) | No (bootstrap dependency) |
| STS | `com.amazonaws.<region>.sts` | Operator + App (IRSA token exchange) | Yes |
| SSM | `com.amazonaws.<region>.ssm` | Operator + App | Yes |
| Secrets Manager | `com.amazonaws.<region>.secretsmanager` | Operator + App | Yes |
| Glue | `com.amazonaws.<region>.glue` | Operator + App | Yes |
| ECR API | `com.amazonaws.<region>.ecr.api` | EKS (image pulls) | Yes |
| ECR Docker | `com.amazonaws.<region>.ecr.dkr` | EKS (image pulls) | Yes |
| CloudWatch Logs | `com.amazonaws.<region>.logs` | App (audit trail, logging) | Yes |
| Cognito IDP | `com.amazonaws.<region>.cognito-idp` | Operator + App | Yes |
| Athena | `com.amazonaws.<region>.athena` | App | Yes |
| EventBridge | `com.amazonaws.<region>.events` | Operator + App | Yes |
| EKS | `com.amazonaws.<region>.eks` | Operator (cluster API) | No |
| IAM | `com.amazonaws.<region>.iam` | Operator (role management) | No |

### 5.2 Check Existing Endpoints

```bash
# Get the VPC ID for the cluster
VPC_ID=$(aws eks describe-cluster \
  --name <cluster-name> \
  --query "cluster.resourcesVpcConfig.vpcId" --output text)

# List all endpoints in the VPC
aws ec2 describe-vpc-endpoints \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query "VpcEndpoints[].{Service:ServiceName,State:State,Type:VpcEndpointType,Id:VpcEndpointId}" \
  --output table

# Count endpoints
aws ec2 describe-vpc-endpoints \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query "length(VpcEndpoints)" --output text
```

### 5.3 Check a Specific Endpoint

```bash
# Check if the STS endpoint exists and is available
aws ec2 describe-vpc-endpoints \
  --filters "Name=vpc-id,Values=$VPC_ID" \
            "Name=service-name,Values=com.amazonaws.ap-southeast-1.sts" \
  --query "VpcEndpoints[0].{State:State,DNS:DnsEntries[0].DnsName,SGs:Groups[*].GroupId}" \
  --output json
```

### 5.4 Verify DNS Resolution

From a pod or jumpbox inside the VPC:

```bash
# Interface endpoints use private hosted zones
# A successful resolution returns a private IP (10.x.x.x or 172.x.x.x)
nslookup sts.ap-southeast-1.amazonaws.com
nslookup ssm.ap-southeast-1.amazonaws.com
nslookup secretsmanager.ap-southeast-1.amazonaws.com

# If DNS returns a public IP, the interface endpoint is missing or
# "Private DNS" is not enabled on the endpoint
```

### 5.5 Security Group Requirements

Interface endpoints need a security group that allows inbound HTTPS from the cluster:

```bash
# Get cluster security group
CLUSTER_SG=$(aws eks describe-cluster --name <cluster-name> \
  --query "cluster.resourcesVpcConfig.clusterSecurityGroupId" --output text)

# Get cluster CIDR (from the VPC)
VPC_CIDR=$(aws ec2 describe-vpcs --vpc-ids $VPC_ID \
  --query "Vpcs[0].CidrBlock" --output text)

# Verify the endpoint's security group allows 443 from the VPC CIDR
aws ec2 describe-security-groups \
  --group-ids <endpoint-sg-id> \
  --query "SecurityGroups[0].IpPermissions[?ToPort==\`443\`]"
```

If missing, the admin should add an inbound rule:
- Protocol: TCP
- Port: 443
- Source: VPC CIDR (e.g. `10.0.0.0/16`) or the cluster security group

### 5.6 Gateway vs Interface — Key Differences

| Aspect | Gateway Endpoint | Interface Endpoint |
|---|---|---|
| Services | S3, DynamoDB only | All other services |
| Mechanism | Route table entry | ENI in subnet + private DNS |
| Security Group | Not applicable | Required (TCP 443 inbound) |
| Cost | Free | Per-hour + per-GB data processing |
| DNS | Uses public DNS, traffic routed internally | Private hosted zone overrides public DNS |
| Subnet placement | N/A | Must be in the same subnets as the cluster nodes |

### 5.7 Admin Creation — Quick Reference

For the full step-by-step, see `ADMIN-SETUP.md` and `aws-prerequisites.md`.

**Create a gateway endpoint (S3 example):**

```bash
ROUTE_TABLE_IDS=$(aws ec2 describe-route-tables \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query "RouteTables[].RouteTableId" --output text | tr '\t' ',')

aws ec2 create-vpc-endpoint \
  --vpc-id $VPC_ID \
  --service-name com.amazonaws.ap-southeast-1.s3 \
  --vpc-endpoint-type Gateway \
  --route-table-ids $(echo $ROUTE_TABLE_IDS | tr ',' ' ')
```

**Create an interface endpoint (STS example):**

```bash
SUBNET_IDS=$(aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query "Subnets[?MapPublicIpOnLaunch==\`false\`].SubnetId" --output text)

aws ec2 create-vpc-endpoint \
  --vpc-id $VPC_ID \
  --service-name com.amazonaws.ap-southeast-1.sts \
  --vpc-endpoint-type Interface \
  --subnet-ids $SUBNET_IDS \
  --security-group-ids <sg-id> \
  --private-dns-enabled
```

---

## 6. ALB and internal Ingress (AWS Load Balancer Controller)

### Symptom

`inspect-capability.sh` shows **no Ingress** in the capability namespace, **frontend/backend Services are `LoadBalancer`**, and **ALB: NOT FOUND** for names like `call-processing-<env>` and `call-processing-<env>-internal`.

### Most common cause

**`spec.internalIngress.enabled` is true but `spec.ingress.enabled` is false or missing.**  
The operator only creates Kubernetes `Ingress` objects (and thus ALBs via the AWS Load Balancer Controller) when **`ingress.enabled: true`**. The internal ALB is a *second* Ingress; it is never created unless the public Ingress path is enabled.

Fix: set both in the `TotogiCapability` spec:

```yaml
ingress:
  enabled: true
  scheme: internet-facing   # or internal for a single private ALB only
  # certificateArn, healthCheckPath, subnets as needed
internalIngress:
  enabled: true
  # subnets, annotations (e.g. security-groups), certificateArn as needed
```

Then re-apply the CR and wait for phase **Running** (or watch operator logs for the new warning if `internalIngress` is enabled without `ingress`).

### After Ingress objects exist but ALB still missing

1. **Controller installed and running**

   ```bash
   kubectl get deploy -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller
   kubectl logs -n kube-system deploy/aws-load-balancer-controller --tail=100
   ```

2. **Ingress events and status**

   ```bash
   kubectl get ingress -n call-processing-<env> -o wide
   kubectl describe ingress -n call-processing-<env>
   ```

   Look for errors about subnets, security groups, certificates, or permissions.

3. **Subnets / security groups** (internal ALB): subnets must be **in the cluster VPC** (usually private subnets for `scheme: internal`). The security group must allow traffic from clients to the ALB and from the ALB to pod targets. The **Load Balancer Controller’s** IAM role must be allowed to create/manage ALBs and use those subnets/SGs—not the Totogi app role.

4. **`AmazonEKSLoadBalancerControllerRole` NOT FOUND** in inspect: the script checks a **fixed role name**; your cluster may use a different IAM role for the controller. Confirm the controller’s actual service account annotation (`eks.amazonaws.com/role-arn`) instead.

---

## 7. Policy Files Reference

| File | Role / Resource | Purpose | Validated By |
|------|-----------------|---------|--------------|
| `operator-policy.json` | `totogi-operator-role` (inline policy) | DynamoDB, S3, SSM, Secrets, Glue, IAM, EKS, Cognito, EC2/VPC | `check-operator-permissions.py` |
| `operator-trust-policy.json` | `totogi-operator-role` (trust relationship) | IRSA trust for SA `totogi-system:totogi-operator` | `check-operator` (identity check) |
| `app-policy.json` | `<cap>-<env>-app-role` (inline policy) | DynamoDB, S3, SSM, Secrets, Glue, Athena, Cognito, CloudWatch Logs | `check-app-permissions.py` |
| `app-trust-policy.json` | `<cap>-<env>-app-role` (trust relationship) | IRSA trust for SA `<cap>-<env>:<cap>-<env>-app-sa` | `check-app` (identity check) |
| `deployer-policy.json` | Jumpbox role (e.g. `SH-Role-EKS-JH`) | EKS, ECR, IAM read/pass, SSM, Secrets, Cognito, S3, Logs, ACM | N/A (jumpbox CLI) |
| `ebs-csi-trust-policy.json` | `AmazonEKS_EBS_CSI_DriverRole` (trust) | IRSA trust for SA `kube-system:ebs-csi-controller-sa` | N/A (AWS-managed addon) |
| `velero-backup-policy.json` | `VeleroBackupPolicy` (managed policy) | EC2 snapshots + S3 backup bucket | N/A (Velero) |
| `velero-backup-trust-policy.json` | `velero-backup-role` (trust) | IRSA trust for SA `velero:velero` | N/A (Velero) |
| `ADMIN-SETUP.md` | Documentation | Step-by-step admin instructions for creating all roles | N/A |

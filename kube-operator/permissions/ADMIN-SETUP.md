# Admin IAM Setup Instructions

One-time setup steps for the AWS administrator before the deployment team can run `e2e-deploy.sh`.

All steps include both AWS Console instructions and equivalent CLI commands.
CLI commands require IAM API access (internet-routable machine, not a private jumpbox).

## Values to Replace

Before using any policy file, replace these placeholders with actual values:

| Placeholder | Example Value | How to Find |
|---|---|---|
| `${ACCOUNT_ID}` | `433193941624` | `aws sts get-caller-identity --query Account --output text` |
| `${OIDC_PROVIDER}` | `oidc.eks.ap-southeast-1.amazonaws.com/id/98DAC2C48D003C3A23F43EF39C854FCF` | `aws eks describe-cluster --name <cluster> --query "cluster.identity.oidc.issuer" --output text` (strip `https://`) |
| `<region>` | `ap-southeast-1` | Your AWS region |
| `<account-id>` | `433193941624` | Same as `${ACCOUNT_ID}` |
| `<capability>` | `call-processing` | The capability name from the TotogiCapability manifest |
| `<env>` | `dev`, `stage`, or `prod` | The environment name |

### Set variables (used by all CLI commands below)

```bash
export ACCOUNT_ID="433193941624"
export REGION="ap-southeast-1"
export CLUSTER_NAME="SH-BSS-Magic-DEV-EKS-Cluster-Green"
export OIDC_PROVIDER=$(aws eks describe-cluster --name $CLUSTER_NAME \
  --query "cluster.identity.oidc.issuer" --output text | sed 's|https://||')
echo "OIDC Provider: $OIDC_PROVIDER"
```

---

## Step 1: Verify OIDC Provider is Registered in IAM

The EKS cluster already has an OIDC issuer configured. However, the OIDC provider must also be **registered in IAM** for IRSA (IAM Roles for Service Accounts) to work. Without this, the operator and app pods cannot assume their IAM roles.

### How to get the OIDC issuer URL

From the jumpbox (or any machine with EKS access):

```bash
aws eks describe-cluster \
  --name $CLUSTER_NAME \
  --query "cluster.identity.oidc.issuer" --output text
```

Expected output: `https://oidc.eks.ap-southeast-1.amazonaws.com/id/98DAC2C48D003C3A23F43EF39C854FCF`

### Verify it is registered in IAM

**Console:** IAM -> Identity providers -> look for `oidc.eks.ap-southeast-1.amazonaws.com/id/98DAC...`

**CLI:**

```bash
aws iam get-open-id-connect-provider \
  --open-id-connect-provider-arn "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/${OIDC_PROVIDER}"
```

A successful response with `ThumbprintList` and `ClientIDList` confirms registration. A `NoSuchEntity` error means it is not registered.

> **Note:** The `cluster-access.sh check` script may show a false positive for OIDC registration when run from a private jumpbox. The IAM call times out silently and the script interprets the non-`NoSuchEntity` response as success. Always verify via Console or CLI from a machine with IAM access.

### If NOT registered -- create it

**Console:** IAM -> Identity providers -> Add provider -> OpenID Connect -> Provider URL: `https://oidc.eks.ap-southeast-1.amazonaws.com/id/98DAC...` -> Audience: `sts.amazonaws.com` -> Add provider

**CLI:**

```bash
# Get the thumbprint for the OIDC issuer
THUMBPRINT=$(echo | openssl s_client -servername oidc.eks.${REGION}.amazonaws.com \
  -connect oidc.eks.${REGION}.amazonaws.com:443 2>/dev/null \
  | openssl x509 -fingerprint -sha1 -noout \
  | sed 's/sha1 Fingerprint=//;s/://g' | tr '[:upper:]' '[:lower:]')

aws iam create-open-id-connect-provider \
  --url "https://${OIDC_PROVIDER}" \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list "${THUMBPRINT}"
```

### If registered but missing STS audience

**Console:** IAM -> Identity providers -> click the provider -> Audiences -> Add audience -> `sts.amazonaws.com`

**CLI:**

```bash
aws iam add-client-id-to-open-id-connect-provider \
  --open-id-connect-provider-arn "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/${OIDC_PROVIDER}" \
  --client-id sts.amazonaws.com
```

---

## Step 2: Create `totogi-operator-role`

This role is used by the operator pod running inside EKS via IRSA.

> **Note:** The operator policy includes EC2/VPC permissions (`ec2:CreateVpcEndpoint`, `ec2:DescribeVpcEndpoints`, etc.) so the operator can auto-create VPC Gateway and Interface endpoints on private clusters. This runs as the first provisioning step before creating DynamoDB tables, S3 buckets, etc. If endpoints already exist (admin-created or from a previous run), they are detected and skipped.

**Console:**

1. IAM -> Roles -> Create role
2. Trusted entity: **Custom trust policy**
3. Paste the content from **`operator-trust-policy.json`** (replace `${ACCOUNT_ID}` and `${OIDC_PROVIDER}`)
4. Click Next -> Create inline policy -> JSON tab
5. Paste the content from **`operator-policy.json`** (replace `<region>` and `<account-id>`)
6. Policy name: `totogi-operator-policy`
7. Role name: **`totogi-operator-role`** (must be this exact name)

**CLI:**

```bash
# Prepare trust policy with actual values
sed -e "s|\${ACCOUNT_ID}|${ACCOUNT_ID}|g" \
    -e "s|\${OIDC_PROVIDER}|${OIDC_PROVIDER}|g" \
    permissions/operator-trust-policy.json > /tmp/operator-trust.json

# Prepare permissions policy with actual values
sed -e "s|<region>|${REGION}|g" \
    -e "s|<account-id>|${ACCOUNT_ID}|g" \
    permissions/operator-policy.json > /tmp/operator-perms.json

# Create the role
aws iam create-role \
  --role-name totogi-operator-role \
  --assume-role-policy-document file:///tmp/operator-trust.json \
  --description "IAM role for Totogi Operator pod (IRSA)"

# Attach the inline permissions policy
aws iam put-role-policy \
  --role-name totogi-operator-role \
  --policy-name totogi-operator-policy \
  --policy-document file:///tmp/operator-perms.json

# Verify
aws iam get-role --role-name totogi-operator-role \
  --query "Role.{Arn:Arn,CreateDate:CreateDate}" --output table
```

---

## Step 3: Create `AmazonEKS_EBS_CSI_DriverRole`

This role is used by the EBS CSI controller for persistent volume support.

**Console:**

1. IAM -> Roles -> Create role
2. Trusted entity: **Custom trust policy**
3. Paste the content from **`ebs-csi-trust-policy.json`** (replace `${ACCOUNT_ID}` and `${OIDC_PROVIDER}`)
4. Click Next -> search for managed policy **`AmazonEBSCSIDriverPolicy`** -> select it
5. Role name: **`AmazonEKS_EBS_CSI_DriverRole`**

**CLI:**

```bash
# Prepare trust policy with actual values
sed -e "s|\${ACCOUNT_ID}|${ACCOUNT_ID}|g" \
    -e "s|\${OIDC_PROVIDER}|${OIDC_PROVIDER}|g" \
    permissions/ebs-csi-trust-policy.json > /tmp/ebs-csi-trust.json

# Create the role
aws iam create-role \
  --role-name AmazonEKS_EBS_CSI_DriverRole \
  --assume-role-policy-document file:///tmp/ebs-csi-trust.json \
  --description "IAM role for EBS CSI Driver (IRSA)"

# Attach the AWS managed policy
aws iam attach-role-policy \
  --role-name AmazonEKS_EBS_CSI_DriverRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy

# Verify
aws iam get-role --role-name AmazonEKS_EBS_CSI_DriverRole \
  --query "Role.{Arn:Arn,CreateDate:CreateDate}" --output table
```

### Install the EBS CSI addon

**Console:** EKS -> Cluster -> Add-ons -> Get more add-ons -> Amazon EBS CSI Driver -> select role `AmazonEKS_EBS_CSI_DriverRole`

**CLI (works from jumpbox -- uses EKS API, not IAM):**

```bash
aws eks create-addon \
  --cluster-name $CLUSTER_NAME \
  --addon-name aws-ebs-csi-driver \
  --service-account-role-arn "arn:aws:iam::${ACCOUNT_ID}:role/AmazonEKS_EBS_CSI_DriverRole" \
  --resolve-conflicts OVERWRITE

# Verify (works from jumpbox)
aws eks describe-addon \
  --cluster-name $CLUSTER_NAME \
  --addon-name aws-ebs-csi-driver \
  --query "addon.{Status:status,Role:serviceAccountRoleArn}" --output table
```

---

## Step 4: Create `velero-backup-role` (for cluster backups)

This role is used by the Velero backup controller pod for backing up Kubernetes resources and EBS volumes to S3.

> **Note:** Replace `${BUCKET_NAME}` with your backup bucket name (default: `callsense-stage-cluster-backup`).

**Console:**

1. IAM -> Policies -> Create policy -> JSON tab
2. Paste the content from **`velero-backup-policy.json`** (replace `${BUCKET_NAME}`)
3. Policy name: **`VeleroBackupPolicy`**
4. IAM -> Roles -> Create role
5. Trusted entity: **Custom trust policy**
6. Paste the content from **`velero-backup-trust-policy.json`** (replace `${ACCOUNT_ID}` and `${OIDC_PROVIDER}`)
7. Click Next -> search for **`VeleroBackupPolicy`** (the policy you just created) -> select it
8. Role name: **`velero-backup-role`**

**CLI:**

```bash
export BUCKET_NAME="callsense-stage-cluster-backup"

# Prepare policy with actual bucket name
sed -e "s|\${BUCKET_NAME}|${BUCKET_NAME}|g" \
    permissions/velero-backup-policy.json > /tmp/velero-policy.json

# Create the managed policy
aws iam create-policy \
  --policy-name VeleroBackupPolicy \
  --policy-document file:///tmp/velero-policy.json

# Prepare trust policy with actual values
sed -e "s|\${ACCOUNT_ID}|${ACCOUNT_ID}|g" \
    -e "s|\${OIDC_PROVIDER}|${OIDC_PROVIDER}|g" \
    permissions/velero-backup-trust-policy.json > /tmp/velero-trust.json

# Create the role
aws iam create-role \
  --role-name velero-backup-role \
  --assume-role-policy-document file:///tmp/velero-trust.json \
  --description "IAM role for Velero backup controller (IRSA)"

# Attach the policy to the role
aws iam attach-role-policy \
  --role-name velero-backup-role \
  --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/VeleroBackupPolicy"

# Verify
aws iam get-role --role-name velero-backup-role \
  --query "Role.{Arn:Arn,CreateDate:CreateDate}" --output table
```

After creating the role, run Velero setup from the jumpbox:

```bash
./setup-velero-backup.sh setup
```

The script will detect the role and policy already exist and skip IAM creation, proceeding directly to install Velero.

---

## Step 5: Create App Role(s)

Create one role per capability/environment combination. The operator updates these roles at runtime but does not create them.

**Example: `call-processing` in `dev`**

**Console:**

1. IAM -> Roles -> Create role
2. Trusted entity: **Custom trust policy**
3. Paste the content from **`app-trust-policy.json`** (replace `${ACCOUNT_ID}`, `${OIDC_PROVIDER}`, `${CAPABILITY}`, `${ENV}`)
4. Click Next -> Create inline policy -> JSON tab
5. Paste the content from **`app-policy.json`** (replace `<region>`, `<account-id>`, `<capability>`, `<env>`)
6. Policy name: `call-processing-dev-app-role-policy`
7. Role name: **`call-processing-dev-app-role`**

**CLI (repeat for each capability/env combination):**

```bash
# Set capability and environment
export CAPABILITY="call-processing"
export ENV="dev"
export ROLE_NAME="${CAPABILITY}-${ENV}-app-role"

# Prepare trust policy with actual values
sed -e "s|\${ACCOUNT_ID}|${ACCOUNT_ID}|g" \
    -e "s|\${OIDC_PROVIDER}|${OIDC_PROVIDER}|g" \
    -e "s|\${CAPABILITY}|${CAPABILITY}|g" \
    -e "s|\${ENV}|${ENV}|g" \
    permissions/app-trust-policy.json > /tmp/app-trust.json

# Prepare permissions policy with actual values
sed -e "s|<region>|${REGION}|g" \
    -e "s|<account-id>|${ACCOUNT_ID}|g" \
    -e "s|<capability>|${CAPABILITY}|g" \
    -e "s|<env>|${ENV}|g" \
    permissions/app-policy.json > /tmp/app-perms.json

# Create the role
aws iam create-role \
  --role-name "${ROLE_NAME}" \
  --assume-role-policy-document file:///tmp/app-trust.json \
  --description "App role for ${CAPABILITY} in ${ENV} (IRSA)"

# Attach the inline permissions policy
aws iam put-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-name "${ROLE_NAME}-policy" \
  --policy-document file:///tmp/app-perms.json

# Verify
aws iam get-role --role-name "${ROLE_NAME}" \
  --query "Role.{Arn:Arn,CreateDate:CreateDate}" --output table
```

**Roles to create (repeat the CLI block above, changing `CAPABILITY` and `ENV`):**

| Capability | Env | Role Name | `export` values |
|---|---|---|---|
| `call-processing` | `dev` | `call-processing-dev-app-role` | `CAPABILITY=call-processing ENV=dev` |
| `call-processing` | `stage` | `call-processing-stage-app-role` | `CAPABILITY=call-processing ENV=stage` |
| `call-processing` | `prod` | `call-processing-prod-app-role` | `CAPABILITY=call-processing ENV=prod` |

---

## Step 6: Update Deployer Role

The jumpbox role (e.g., `SH-Role-EKS-JH`) needs permissions to run deployment scripts. This role does NOT create or delete IAM roles -- it only reads and updates existing ones.

**Console:**

1. IAM -> Roles -> `SH-Role-EKS-JH` (or your jumpbox role)
2. Add permissions -> Create inline policy -> JSON tab
3. Paste the content from **`deployer-policy.json`**
4. Policy name: `deployer-full-access`

**CLI:**

```bash
aws iam put-role-policy \
  --role-name SH-Role-EKS-JH \
  --policy-name deployer-full-access \
  --policy-document file://permissions/deployer-policy.json

# Verify
aws iam get-role-policy \
  --role-name SH-Role-EKS-JH \
  --policy-name deployer-full-access \
  --query "PolicyName" --output text
```

---

## Verification

### From the jumpbox (works without IAM access)

```bash
# Check credentials
aws sts get-caller-identity

# Check OIDC issuer (EKS API)
aws eks describe-cluster --name $CLUSTER_NAME \
  --query "cluster.identity.oidc.issuer" --output text

# Check EBS CSI addon (EKS API)
aws eks describe-addon --cluster-name $CLUSTER_NAME \
  --addon-name aws-ebs-csi-driver \
  --query "addon.{Status:status,Role:serviceAccountRoleArn}" \
  --output table

# Check kubectl access
kubectl get nodes
```

### From a machine with IAM access (or admin's workstation)

```bash
# Check all roles exist
for role in totogi-operator-role AmazonEKS_EBS_CSI_DriverRole velero-backup-role call-processing-dev-app-role; do
  echo -n "${role}: "
  aws iam get-role --role-name $role --query "Role.Arn" --output text 2>/dev/null || echo "NOT FOUND"
done

# Check OIDC provider
aws iam get-open-id-connect-provider \
  --open-id-connect-provider-arn "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/${OIDC_PROVIDER}" \
  --query "{ClientIDs:ClientIDList,Created:CreateDate}" --output table

# Check deployer policy is attached
aws iam get-role-policy \
  --role-name SH-Role-EKS-JH \
  --policy-name deployer-full-access \
  --query "PolicyName" --output text
```

---

## Policy Files Reference

| File | Used For | Applied To |
|---|---|---|
| `deployer-policy.json` | Jumpbox deployment permissions (no IAM create/delete) | `SH-Role-EKS-JH` |
| `operator-policy.json` | Operator pod permissions (no IAM create/delete) | `totogi-operator-role` |
| `operator-trust-policy.json` | IRSA trust for operator ServiceAccount | `totogi-operator-role` (trust) |
| `ebs-csi-trust-policy.json` | IRSA trust for EBS CSI controller | `AmazonEKS_EBS_CSI_DriverRole` (trust) |
| `velero-backup-policy.json` | Velero S3 + EC2 snapshot permissions (template) | `VeleroBackupPolicy` (managed policy) |
| `velero-backup-trust-policy.json` | IRSA trust for Velero ServiceAccount | `velero-backup-role` (trust) |
| `app-trust-policy.json` | IRSA trust for capability namespace (template) | `<capability>-<env>-app-role` (trust) |
| `app-policy.json` | App pod permissions (template) | `<capability>-<env>-app-role` |

---

## After Setup

Once all roles are created, the deployment team can run:

```bash
export AWS_PROFILE=default    # required on jumpbox (uses instance role)
cd kube-operator
./e2e-deploy.sh
```

This will deploy the operator, apply capabilities, and configure all resources -- without needing IAM role creation permissions.

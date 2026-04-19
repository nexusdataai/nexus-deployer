# IAM Permissions for Business Capability Deployment

## Overview

This document describes the IAM permissions required to deploy business capabilities to any AWS account using the layered deployment system. The deployment requires extensive permissions to create and manage various AWS services.

## Quick Setup

### Option 1: Deploy the IAM Role Stack (Recommended)

Deploy the provided CloudFormation template in the **target account**:

```bash
aws cloudformation create-stack \
  --stack-name BusinessCapabilityDeploymentRole \
  --template-body file://deployment-role-stack.yaml \
  --parameters \
    ParameterKey=TrustedAccountId,ParameterValue=123456789012 \
    ParameterKey=ExternalId,ParameterValue=my-secure-external-id \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

### Option 2: Create Role Manually

1. Create an IAM role in the target account
2. Attach the trust policy from `deployment-role-trust-policy.json`
3. Attach the permissions policy from `deployment-role-policy.json`

## Minimum Required Permissions

### Core Services

The deployment process requires full or near-full access to the following services:

| Service | Purpose | Minimum Actions Required |
|---------|---------|-------------------------|
| **CloudFormation** | Stack management | Create, Update, Delete, Describe stacks |
| **S3** | Frontend hosting, artifacts, logs | Create/manage buckets, upload objects |
| **CloudFront** | CDN distribution | Create/manage distributions, invalidations |
| **WAF** | Web application firewall | Create/manage WebACLs, rules |
| **ACM** | SSL certificates | Request, validate, describe certificates |
| **Route53** | DNS management | Create/update record sets |
| **VPC** | Networking | Create VPC, subnets, gateways, routes |
| **EC2** | Security groups, network interfaces | Create/manage security groups |
| **ECS** | Container orchestration | Create clusters, services, task definitions |
| **ECR** | Container registry | Create repos, push/pull images |
| **ALB** | Load balancing | Create/manage load balancers, target groups |
| **IAM** | Service roles | Create ECS task roles, pass roles |
| **DynamoDB** | Database tables | Create/manage tables, indexes |
| **Secrets Manager** | Secrets storage | Create/manage secrets |
| **KMS** | Encryption keys | Create/use encryption keys |
| **CloudWatch Logs** | Logging | Create log groups, set retention |
| **Application Auto Scaling** | ECS scaling | Create scaling policies |

### Detailed Permission Categories

#### 1. CloudFormation Operations
```json
"cloudformation:CreateStack",
"cloudformation:UpdateStack",
"cloudformation:DeleteStack",
"cloudformation:DescribeStacks",
"cloudformation:DescribeStackEvents",
"cloudformation:GetTemplate",
"cloudformation:ValidateTemplate"
```

#### 2. Frontend Infrastructure
```json
// S3 Operations
"s3:CreateBucket",
"s3:PutBucketPolicy",
"s3:PutBucketEncryption",
"s3:PutBucketVersioning",
"s3:PutObject",
"s3:GetObject",

// CloudFront Operations
"cloudfront:CreateDistribution",
"cloudfront:UpdateDistribution",
"cloudfront:CreateInvalidation",
"cloudfront:CreateCloudFrontOriginAccessIdentity",

// WAF Operations
"wafv2:CreateWebACL",
"wafv2:AssociateWebACL",

// Certificate Operations
"acm:RequestCertificate",
"acm:DescribeCertificate",

// Route53 Operations
"route53:ChangeResourceRecordSets",
"route53:GetChange"
```

#### 3. Backend Infrastructure
```json
// VPC and Networking
"ec2:CreateVpc",
"ec2:CreateSubnet",
"ec2:CreateInternetGateway",
"ec2:CreateNatGateway",
"ec2:CreateSecurityGroup",
"ec2:AuthorizeSecurityGroupIngress",

// ECS Operations
"ecs:CreateCluster",
"ecs:RegisterTaskDefinition",
"ecs:CreateService",
"ecs:UpdateService",

// Load Balancer Operations
"elasticloadbalancing:CreateLoadBalancer",
"elasticloadbalancing:CreateTargetGroup",
"elasticloadbalancing:CreateListener",

// IAM Operations
"iam:CreateRole",
"iam:PutRolePolicy",
"iam:AttachRolePolicy",
"iam:PassRole"
```

#### 4. Data and Storage
```json
// DynamoDB Operations
"dynamodb:CreateTable",
"dynamodb:UpdateTimeToLive",
"dynamodb:UpdateContinuousBackups",

// Secrets Manager
"secretsmanager:CreateSecret",
"secretsmanager:PutSecretValue",

// ECR Operations
"ecr:CreateRepository",
"ecr:PutLifecyclePolicy",
"ecr:GetAuthorizationToken",
"ecr:BatchGetImage"
```

## Cross-Account Deployment

### Setting Up Cross-Account Access

1. **In the Target Account:**

   Create the deployment role using the CloudFormation template:

   ```bash
   aws cloudformation create-stack \
     --stack-name BusinessCapabilityDeploymentRole \
     --template-body file://deployment-role-stack.yaml \
     --parameters \
       ParameterKey=TrustedAccountId,ParameterValue=SOURCE_ACCOUNT_ID \
       ParameterKey=ExternalId,ParameterValue=SECURE_EXTERNAL_ID \
     --capabilities CAPABILITY_NAMED_IAM
   ```

2. **In the Source Account:**

   Ensure the user/role has permission to assume the target role:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Action": "sts:AssumeRole",
       "Resource": "arn:aws:iam::TARGET_ACCOUNT:role/BusinessCapabilityDeploymentRole"
     }]
   }
   ```

3. **Deploy Using the Cross-Account Role:**

   ```bash
   ./deploy-capability-layered.sh \
     -c config/prod-config.yaml \
     --role-arn arn:aws:iam::TARGET_ACCOUNT:role/BusinessCapabilityDeploymentRole
   ```

## Security Best Practices

### 1. Use External ID

Always use an external ID for cross-account roles to prevent confused deputy attacks:

```json
{
  "Condition": {
    "StringEquals": {
      "sts:ExternalId": "unique-external-id-here"
    }
  }
}
```

### 2. Restrict by Resource Name

Limit permissions to resources matching your naming convention:

```json
{
  "Resource": "arn:aws:s3:::my-app-*"
}
```

### 3. Environment Restrictions

Use the CloudFormation template parameters to restrict deployments:

```yaml
EnvironmentRestriction: prod  # Only allow production deployments
CapabilityNameRestriction: my-app-*  # Only allow specific apps
```

### 4. Time-Limited Sessions

Set appropriate session duration (default 1 hour):

```yaml
MaxSessionDuration: 3600  # 1 hour
```

### 5. MFA Requirement

For production deployments, require MFA:

```json
{
  "Condition": {
    "Bool": {
      "aws:MultiFactorAuthPresent": "true"
    }
  }
}
```

## Minimal Permission Set

If you need the absolute minimum permissions, you can start with these and add as needed:

### Essential Permissions Only

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EssentialCloudFormation",
      "Effect": "Allow",
      "Action": [
        "cloudformation:CreateStack",
        "cloudformation:UpdateStack",
        "cloudformation:DescribeStacks",
        "cloudformation:DescribeStackEvents"
      ],
      "Resource": "arn:aws:cloudformation:*:*:stack/my-app-*/*"
    },
    {
      "Sid": "EssentialIAM",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:AttachRolePolicy",
        "iam:PutRolePolicy",
        "iam:PassRole",
        "iam:GetRole"
      ],
      "Resource": [
        "arn:aws:iam::*:role/my-app-*",
        "arn:aws:iam::*:role/aws-service-role/*"
      ]
    },
    {
      "Sid": "ReadOnlyDiscovery",
      "Effect": "Allow",
      "Action": [
        "ec2:Describe*",
        "ecs:Describe*",
        "ecs:List*",
        "s3:List*",
        "s3:GetBucket*",
        "elasticloadbalancing:Describe*"
      ],
      "Resource": "*"
    }
  ]
}
```

**Note:** This minimal set will likely fail. CloudFormation needs permissions to create the actual resources, not just manage stacks.

## Testing Permissions

### Using the Installation Wizard (Recommended)

The installation wizard provides comprehensive permission verification:

1. Navigate to the AWS Configuration step
2. Enter your Role ARN and credentials
3. Click "Test Credentials" to verify access
4. The wizard will show:
   - Which permissions are available
   - Which permissions are missing
   - Remediation suggestions for missing permissions
   - One-click policy download for missing permissions

### Using Validation Scripts

Run the validation scripts to check permissions from the command line:

```bash
# Linux/macOS
./scripts/validate-permissions.sh

# Windows PowerShell
.\scripts\validate-permissions.ps1
```

The scripts will check access to all required AWS services and report:
- ✓ Services with proper access
- ✗ Services with missing permissions
- ⚠ Optional services that may not be required

### Verify Role Access

Test that you can assume the role:

```bash
aws sts assume-role \
  --role-arn arn:aws:iam::TARGET_ACCOUNT:role/BusinessCapabilityDeploymentRole \
  --role-session-name test-session
```

### Dry Run Deployment

Test permissions without creating resources:

```bash
./deploy-capability-layered.sh \
  -c config/test-config.yaml \
  --role-arn arn:aws:iam::TARGET_ACCOUNT:role/BusinessCapabilityDeploymentRole \
  --dry-run
```

## Troubleshooting

### Common Permission Errors

1. **"User is not authorized to perform: iam:PassRole"**
   - The deployment role needs `iam:PassRole` permission for service-linked roles

2. **"Access Denied" on CloudFormation**
   - Ensure the role has permissions for all resources the stack creates
   - Check if stack tags require additional permissions

3. **"Invalid principal in policy"**
   - Verify the trusted account ID is correct
   - Ensure the role ARN in trust policy is valid

4. **"The security token included in the request is expired"**
   - Session has expired, re-assume the role
   - Increase `MaxSessionDuration` if needed

### Permission Debugging

Enable CloudTrail to see exactly which API calls are being made:

```bash
# Check CloudTrail for access denied events
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=AssumeRole \
  --max-items 10
```

## Cost Considerations

Some permissions can lead to cost implications:

- **VPC**: NAT Gateways cost ~$45/month
- **ALB**: Application Load Balancers cost ~$20/month
- **CloudFront**: Data transfer costs apply
- **ECS Fargate**: Compute costs based on CPU/memory

Consider using the `EnvironmentRestriction` to prevent accidental production deployments.

## Support

For permission-related issues:

1. Check CloudFormation events for specific permission errors
2. Review CloudTrail logs for denied API calls
3. Verify the role trust relationship
4. Ensure all required service-linked roles exist

## Files in This Directory

- `deployment-role-policy.json` - Complete IAM policy with all required permissions
- `deployment-role-trust-policy.json` - Trust relationship template
- `deployment-role-stack.yaml` - CloudFormation template to create the role
- `README.md` - This documentation

---

*Last Updated: November 2024*
*Version: 1.0.0*

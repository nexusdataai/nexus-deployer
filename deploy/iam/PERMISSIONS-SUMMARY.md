# Minimum IAM Permissions Summary

## Quick Reference

To execute the complete deployment with a role ARN to any AWS account, you need permissions for **20+ AWS services**. The deployment creates and manages over **50 different types of AWS resources**.

## Three Options for Setup

### Option 1: Full Administrator Access (Simplest)
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "*",
    "Resource": "*"
  }]
}
```
**Pros:** Guaranteed to work
**Cons:** Over-privileged, not recommended for production

### Option 2: Use Our CloudFormation Template (Recommended)
```bash
# In target account:
cd /opt/mycode/nexus/nexus-deployer/deploy
./scripts/setup-deployment-role.sh \
  --source-account 123456789012 \
  --external-id my-secure-id
```
**Pros:** Properly scoped permissions, security best practices
**Cons:** Requires CloudFormation access to set up initially

### Option 3: Use the Provided Policy Document (Manual)
Attach the policy from `deployment-role-policy.json` to your IAM role.
**Pros:** Full control over setup
**Cons:** Manual process, may miss updates

## Core Service Permissions Required

| Category | Services | Why Needed |
|----------|----------|------------|
| **Infrastructure** | CloudFormation | Manages all stacks |
| **Frontend** | S3, CloudFront, WAF, ACM, Route53 | Static hosting, CDN, security |
| **Backend** | ECS, ECR, ALB | Container orchestration |
| **Networking** | VPC, EC2 (Security Groups) | Network infrastructure |
| **Data** | DynamoDB, Secrets Manager, KMS | Storage and secrets |
| **IAM** | Roles, Policies | Service permissions |
| **Monitoring** | CloudWatch, X-Ray | Logs and metrics |

## Minimum Actions by Service

### Critical Permissions (Must Have)
```
cloudformation:*Stack*
s3:*Bucket*, s3:*Object*
iam:CreateRole, iam:PassRole
ecs:CreateCluster, ecs:CreateService
ec2:CreateVpc, ec2:CreateSecurityGroup
elasticloadbalancing:CreateLoadBalancer
```

### Important Permissions (Highly Recommended)
```
acm:RequestCertificate
route53:ChangeResourceRecordSets
wafv2:CreateWebACL
cloudfront:CreateDistribution
dynamodb:CreateTable
secretsmanager:CreateSecret
```

## Cross-Account Deployment

### Trust Relationship (in Target Account)
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "AWS": "arn:aws:iam::SOURCE_ACCOUNT:root"
    },
    "Action": "sts:AssumeRole",
    "Condition": {
      "StringEquals": {
        "sts:ExternalId": "unique-external-id"
      }
    }
  }]
}
```

### Assume Role Permission (in Source Account)
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "sts:AssumeRole",
    "Resource": "arn:aws:iam::TARGET_ACCOUNT:role/DeploymentRole"
  }]
}
```

## Resource Estimation

The deployment will create approximately:

- **10-15 CloudFormation Stacks**
- **2-3 S3 Buckets**
- **1 CloudFront Distribution**
- **1 WAF WebACL**
- **2 ACM Certificates**
- **2-4 Route53 Record Sets**
- **1 VPC with 4 Subnets**
- **3-4 Security Groups**
- **1 ECS Cluster**
- **1 ECS Service with Task Definition**
- **1 Application Load Balancer**
- **2 Target Groups**
- **3-4 IAM Roles**
- **2-3 DynamoDB Tables**
- **2 Secrets in Secrets Manager**
- **1 ECR Repository**
- **2-3 CloudWatch Log Groups**

## Security Recommendations

### 1. Use Least Privilege
- Restrict to specific resource patterns: `arn:aws:s3:::my-app-*`
- Limit to specific environments: `dev`, `stage`, `prod`

### 2. Require External ID
Prevents confused deputy attacks in cross-account scenarios

### 3. Set Session Limits
Default 1 hour, maximum 12 hours

### 4. Enable CloudTrail
Monitor all API calls made by the deployment role

### 5. Use Temporary Credentials
Never use long-term access keys for deployments

## Quick Validation

Test if you have the required permissions:

### Using the Installation Wizard (Recommended)
The installation wizard includes built-in permission verification and provides:
- Real-time permission checking
- Missing permission identification with remediation guidance
- One-click policy download for missing permissions
- Cross-account setup guidance

### Using Command Line Scripts
```bash
# Linux/macOS
cd /opt/mycode/nexus/nexus-deployer/deploy
./scripts/validate-permissions.sh

# Windows PowerShell
cd C:\path\to\nexus-deployer\deploy
.\scripts\validate-permissions.ps1
```

## Wizard-Based Setup

The installation wizard provides comprehensive IAM guidance:

1. **IAM Permission Panel** - View all required permissions by category
2. **Setup Guide Modal** - Step-by-step instructions for CloudFormation, CLI, or manual setup
3. **Cost Estimation** - Estimated monthly costs by environment
4. **Permission Verification** - Real-time validation with remediation suggestions

Access these features in the AWS Configuration step of the installation wizard.

## Deployment Command

Once the role is set up:
```bash
./deploy-capability-layered.sh \
  -c config/prod-config.yaml \
  --role-arn arn:aws:iam::TARGET_ACCOUNT:role/DeploymentRole
```

## Common Issues

1. **Missing iam:PassRole** - Required for ECS tasks
2. **Missing ec2:DescribeAvailabilityZones** - Required for VPC creation
3. **Certificate validation fails** - Needs route53:ChangeResourceRecordSets
4. **Stack rollback** - Usually missing permissions for specific resources

## Cost Implications

These permissions allow creation of resources that incur costs:
- NAT Gateway: ~$45/month
- ALB: ~$20/month
- ECS Fargate: Variable based on usage
- CloudFront: Data transfer charges

Consider using environment restrictions to prevent accidental production deployments.

---

**Bottom Line:** The deployment requires extensive AWS permissions. Use our CloudFormation template for the safest, most maintainable approach.

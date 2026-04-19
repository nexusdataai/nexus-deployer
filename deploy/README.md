# Business Capability Layered Deployment System

## Overview

This deployment system provides a production-ready, layered approach to deploying business capabilities to AWS. It uses CloudFormation templates organized in logical layers for better control, troubleshooting, and reusability.

## Table of Contents

- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Deployment Process](#deployment-process)
- [Stack Layers](#stack-layers)
- [Troubleshooting](#troubleshooting)
- [Advanced Usage](#advanced-usage)
- [Cost Optimization](#cost-optimization)
- [Security Considerations](#security-considerations)

## Architecture

The system deploys infrastructure in the following layers:

```
Frontend Infrastructure:
├── Global Stack (us-east-1)
│   ├── S3 Bucket
│   ├── WAF Rules
│   ├── ACM Certificate
│   └── Route53 Records
└── Regional Stack
    ├── CloudFront Distribution
    └── Cache Behaviors

Backend Infrastructure:
├── Foundation Stack
│   ├── IAM Roles
│   ├── ACM Certificate
│   └── CloudWatch Logs
├── Storage Stack
│   ├── S3 Buckets
│   ├── DynamoDB Tables
│   ├── Secrets Manager
│   └── ECR Repository
├── Network Stack
│   ├── VPC & Subnets
│   ├── Security Groups
│   └── ECS Cluster
└── Service Stack
    ├── ALB
    ├── ECS Service
    └── Auto-scaling
```

## Prerequisites

### Required Software

1. **AWS CLI v2**
   ```bash
   # Install AWS CLI
   curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
   unzip awscliv2.zip
   sudo ./aws/install
   ```

2. **Docker** (for container operations)
   ```bash
   # Install Docker
   curl -fsSL https://get.docker.com -o get-docker.sh
   sh get-docker.sh
   ```

3. **YAML Parser** (choose one)
   ```bash
   # Option 1: Install yq
   wget https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 -O /usr/bin/yq
   chmod +x /usr/bin/yq
   
   # Option 2: Install Python with PyYAML
   pip3 install pyyaml
   ```

### AWS Permissions

The deployment user/role needs the following permissions:
- CloudFormation full access
- IAM role and policy creation
- VPC and networking resources
- ECS and ECR access
- S3 bucket operations
- DynamoDB table creation
- Secrets Manager access
- Route53 record management
- ACM certificate validation
- CloudFront distribution management
- WAF rule configuration

### Pre-deployment Setup

1. **Prepare Source Artifacts**
   - Frontend: Build and zip your frontend application
   - Backend: Build and push Docker container to ECR

2. **Configure DNS**
   - Ensure you have a Route53 hosted zone for your domain
   - Note the Hosted Zone ID

3. **Set AWS Credentials**
   ```bash
   aws configure
   # OR
   export AWS_ACCESS_KEY_ID=your_key
   export AWS_SECRET_ACCESS_KEY=your_secret
   export AWS_REGION=us-west-2
   ```

## Quick Start

### 1. Clone and Navigate
```bash
cd /opt/mycode/trilogy/starhub-deployer/deploy
```

### 2. Create Configuration
```bash
cp config/example-config.yaml config/my-deployment.yaml
# Edit the configuration file with your values
nano config/my-deployment.yaml
```

### 3. Deploy
```bash
# Full deployment
./deploy-capability-layered.sh -c config/my-deployment.yaml

# Frontend only
./deploy-capability-layered.sh -c config/my-deployment.yaml --frontend-only

# Backend only
./deploy-capability-layered.sh -c config/my-deployment.yaml --backend-only

# Dry run (validate without deploying)
./deploy-capability-layered.sh -c config/my-deployment.yaml --dry-run
```

## Configuration

### Configuration File Structure

The configuration file (`config/*.yaml`) defines all deployment parameters:

```yaml
capability:
  name: my-app              # Capability name (lowercase, hyphens)
  version: 1.0.0           # Version being deployed
  
source:
  frontend:
    s3_uri: s3://bucket/path/dist.zip  # Frontend artifact location
  backend:
    ecr_uri: account.dkr.ecr.region.amazonaws.com/repo:tag  # Container image
    
target:
  account_id: "123456789012"  # Target AWS account
  region: us-west-2           # Deployment region
  environment: prod           # dev, stage, or prod
  role_arn: ""               # Optional cross-account role
  
infrastructure:
  domain:
    base: example.com         # Base domain
    frontend_subdomain: app   # app.example.com
    backend_subdomain: api    # api.example.com
    hosted_zone_id: Z123...   # Route53 zone ID
```

### Environment-Specific Configurations

Create separate config files for each environment:
- `config/dev-config.yaml` - Development settings
- `config/stage-config.yaml` - Staging settings
- `config/prod-config.yaml` - Production settings

## Deployment Process

### Step-by-Step Deployment

1. **Validate Configuration**
   ```bash
   ./deploy-capability-layered.sh -c config/my-deployment.yaml --dry-run
   ```

2. **Deploy Frontend** (if needed)
   ```bash
   # Frontend global resources (us-east-1)
   # Frontend regional resources
   # Static file upload to S3
   # CloudFront distribution creation
   ```

3. **Deploy Backend** (if needed)
   ```bash
   # Foundation resources (IAM, certs, logs)
   # Storage resources (S3, DynamoDB, Secrets)
   # Network resources (VPC, subnets, security groups)
   # Service resources (ALB, ECS, auto-scaling)
   ```

4. **Verify Deployment**
   ```bash
   # The script automatically verifies:
   # - Stack creation status
   # - Health check endpoints
   # - DNS resolution
   # - Service availability
   ```

### Deployment Order

Stacks are deployed in this order to ensure dependencies are met:

1. Frontend Global (us-east-1 only)
2. Frontend Regional
3. Backend Foundation
4. Backend Regional Certificate (if cross-region)
5. Backend Storage
6. Backend Network
7. Backend Service

## Authentication Methods and Execution Options

The deployment script supports multiple authentication methods and execution modes to accommodate various deployment scenarios.

### Authentication Methods

#### 1. Direct AWS Credentials (Default)
Uses your current AWS credentials from the environment or AWS CLI configuration:
```bash
./deploy-capability-layered.sh -c config/prod-config.yaml
```

#### 2. Cross-Account Role ARN
For deploying to a different AWS account using an IAM role:
```bash
./deploy-capability-layered.sh -c config/prod-config.yaml \
  --role-arn arn:aws:iam::987654321098:role/DeploymentRole
```

#### 3. AWS Profile
Using named profiles configured in `~/.aws/credentials`:
```bash
AWS_PROFILE=production ./deploy-capability-layered.sh -c config/prod-config.yaml
```

#### 4. Environment Variables
Setting AWS credentials directly via environment variables:
```bash
export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
export AWS_SESSION_TOKEN=token_if_using_temporary_credentials
export AWS_REGION=us-west-2
./deploy-capability-layered.sh -c config/prod-config.yaml
```

#### 5. EC2 Instance Profile
When running from an EC2 instance with an attached IAM role:
```bash
# No credentials needed - uses instance metadata service
./deploy-capability-layered.sh -c config/prod-config.yaml
```

#### 6. ECS Task Role
When running from an ECS task with a task role:
```bash
# Automatically uses the task role credentials
./deploy-capability-layered.sh -c config/prod-config.yaml
```

#### 7. AWS SSO (IAM Identity Center)
After configuring and logging in via AWS SSO:
```bash
# First, configure SSO profile
aws configure sso

# Login to SSO
aws sso login --profile my-sso-profile

# Run deployment with SSO profile
AWS_PROFILE=my-sso-profile ./deploy-capability-layered.sh -c config/prod-config.yaml
```

#### 8. Temporary Credentials from STS
Using temporary credentials obtained from AWS STS:
```bash
# Get temporary credentials and export them
eval $(aws sts assume-role \
  --role-arn arn:aws:iam::123456789012:role/TempRole \
  --role-session-name temp-session \
  --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' \
  --output text | awk '{print "export AWS_ACCESS_KEY_ID="$1"\nexport AWS_SECRET_ACCESS_KEY="$2"\nexport AWS_SESSION_TOKEN="$3}')

# Run deployment with temporary credentials
./deploy-capability-layered.sh -c config/prod-config.yaml
```

#### 9. Docker with AWS Credentials
Running the script from a Docker container:
```bash
docker run -it \
  -v ~/.aws:/root/.aws:ro \
  -v $(pwd):/deployment \
  -e AWS_PROFILE=production \
  -w /deployment \
  amazon/aws-cli:latest \
  ./deploy-capability-layered.sh -c config/prod-config.yaml
```

### Execution Modes

The script supports various execution modes to control deployment behavior:

#### Frontend Only Deployment
Deploy only the frontend infrastructure:
```bash
./deploy-capability-layered.sh -c config/prod-config.yaml --frontend-only
```

#### Backend Only Deployment
Deploy only the backend infrastructure:
```bash
./deploy-capability-layered.sh -c config/prod-config.yaml --backend-only
```

#### Dry Run Mode
Validate configuration and permissions without deploying:
```bash
./deploy-capability-layered.sh -c config/prod-config.yaml --dry-run
```

#### Skip Artifact Verification
Skip checking if frontend/backend artifacts exist (useful for testing):
```bash
./deploy-capability-layered.sh -c config/prod-config.yaml --skip-verification
```

#### Verbose Mode
Enable detailed output for debugging:
```bash
./deploy-capability-layered.sh -c config/prod-config.yaml --verbose
```

#### Combined Options
You can combine multiple options:
```bash
# Deploy backend only with verbose output using SSO profile
AWS_PROFILE=prod-sso ./deploy-capability-layered.sh \
  -c config/prod-config.yaml \
  --backend-only \
  --verbose
```

### Authentication Priority Chain

The script follows AWS SDK's standard credential provider chain in this order:

1. **Explicit `--role-arn` parameter** (highest priority)
2. **Environment variables** (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`)
3. **AWS Profile** (from `AWS_PROFILE` environment variable)
4. **Shared credentials file** (`~/.aws/credentials` default profile)
5. **AWS SSO credentials** (if configured)
6. **EC2 Instance Metadata Service** (for EC2 instances)
7. **ECS container credentials** (for ECS tasks)

### Security Best Practices

#### Production Recommendations

1. **Use IAM Roles Instead of Keys**
   - EC2/ECS instance profiles for compute resources
   - Cross-account roles with external IDs for deployments

2. **AWS SSO for Human Users**
   - Temporary credentials with MFA
   - Centralized access management

3. **Implement Least Privilege**
   - Use the provided IAM role template with restrictions
   - Limit by environment and resource names

#### Example: Secure Production Deployment

```bash
# 1. Setup cross-account role with external ID (one-time)
./scripts/setup-deployment-role.sh \
  --source-account 123456789012 \
  --external-id $(openssl rand -hex 32) \
  --environment prod \
  --capability-prefix my-app

# 2. Deploy using the role
./deploy-capability-layered.sh \
  -c config/prod-config.yaml \
  --role-arn arn:aws:iam::987654321098:role/BusinessCapabilityDeploymentRole
```

### Validation and Testing

Before deployment, validate your authentication:

```bash
# Test current AWS identity
aws sts get-caller-identity

# Validate permissions for deployment
./scripts/validate-permissions.sh

# Test deployment in dry-run mode
./deploy-capability-layered.sh -c config/test-config.yaml --dry-run
```

## Stack Layers

### Frontend Stacks

#### Frontend Global Stack (`templates/frontend/global-stack.yaml`)
- **Region**: Always us-east-1 (CloudFront requirement)
- **Resources**:
  - S3 bucket for static content
  - WAF WebACL for protection
  - ACM certificate for HTTPS
  - CloudFront Origin Access Identity
  - Route53 placeholder records

#### Frontend Regional Stack (`templates/frontend/regional-stack.yaml`)
- **Region**: Target deployment region
- **Resources**:
  - CloudFront distribution
  - Response headers policy
  - Cache policies
  - Route53 alias records

### Backend Stacks

#### Backend Foundation Stack (`templates/backend/foundation-stack.yaml`)
- **Resources**:
  - ECS Task Execution Role
  - ECS Task Role
  - Auto-scaling Role
  - CloudWatch Log Groups
  - ACM Certificate (if same region)
  - Route53 placeholder

#### Backend Storage Stack (`templates/backend/storage-stack.yaml`)
- **Resources**:
  - S3 data bucket
  - DynamoDB tables
  - Secrets Manager secrets
  - ECR repository
  - KMS keys (production only)

#### Backend Network Stack (`templates/backend/network-stack.yaml`)
- **Resources**:
  - VPC (or use existing)
  - Public/Private subnets
  - Internet/NAT gateways
  - Security groups
  - ECS cluster

#### Backend Service Stack (`templates/backend/service-stack.yaml`)
- **Resources**:
  - Application Load Balancer
  - Target groups
  - ECS task definition
  - ECS service
  - Auto-scaling configuration
  - Route53 alias update

## Troubleshooting

### Common Issues and Solutions

#### 1. Certificate Validation Fails
**Problem**: ACM certificate stuck in pending validation
**Solution**:
- Check Route53 hosted zone ID is correct
- Verify domain ownership
- Check DNS propagation: `dig _acme-challenge.yourdomain.com`
- Manually create CNAME records if needed

#### 2. ECS Tasks Not Starting
**Problem**: ECS service tasks keep stopping
**Solutions**:
- Check CloudWatch logs: `/ecs/capability-name-environment`
- Verify container image exists in ECR
- Check task execution role permissions
- Ensure health check endpoint responds correctly
- Verify security group rules allow traffic

#### 3. CloudFront 403 Errors
**Problem**: CloudFront returns 403 Forbidden
**Solutions**:
- Check S3 bucket policy allows CloudFront OAI
- Verify CloudFront origin configuration
- Check WAF rules aren't blocking legitimate traffic
- Ensure index.html exists in S3

#### 4. Cross-Region Deployment Issues
**Problem**: Certificate errors when deploying outside us-east-1
**Solution**:
- Regional certificate stack is automatically created
- Verify certificate is validated in target region
- Check ALB is using correct certificate ARN

#### 5. Stack Rollback on Update
**Problem**: CloudFormation rolls back on stack update
**Solutions**:
- Check CloudFormation events for specific error
- Verify parameter changes are valid
- Check resource limits haven't been exceeded
- Review IAM permissions

### Debug Commands

```bash
# Check stack status
aws cloudformation describe-stacks --stack-name capability-env-type

# View stack events
aws cloudformation describe-stack-events --stack-name capability-env-type

# Check ECS service
aws ecs describe-services --cluster capability-env-cluster --services capability-env-service

# View CloudWatch logs
aws logs tail /ecs/capability-env --follow

# Test endpoints
curl -I https://app.example.com  # Frontend
curl https://api.example.com/health  # Backend API
```

## Advanced Usage

### Cross-Account Deployment

```bash
# Deploy to different AWS account
./deploy-capability-layered.sh \
  -c config/prod-config.yaml \
  --role-arn arn:aws:iam::987654321098:role/DeploymentRole
```

### Using Existing VPC

In your configuration file:
```yaml
infrastructure:
  backend:
    vpc:
      create_new: false
      vpc_id: vpc-12345678
      subnets:
        public: [subnet-1234, subnet-5678]
        private: [subnet-9012, subnet-3456]
```

### Custom Parameters

```bash
# Override specific parameters
./deploy-capability-layered.sh \
  -c config/base-config.yaml \
  -e prod \
  -r us-west-2 \
  --frontend-source s3://my-bucket/frontend-v2.zip \
  --backend-source 123456789.dkr.ecr.us-west-2.amazonaws.com/backend:v2
```

### Partial Updates

```bash
# Update only backend service (skip other layers)
aws cloudformation update-stack \
  --stack-name capability-prod-backend-service \
  --use-previous-template \
  --parameters ParameterKey=ContainerImage,ParameterValue=new-image:tag
```

## Cost Optimization

### Recommendations

1. **Development Environment**
   - Disable NAT Gateway (use public subnets only)
   - Use FARGATE_SPOT for ECS tasks
   - Set minimum auto-scaling to 0
   - Use on-demand DynamoDB billing

2. **Production Environment**
   - Use Reserved Instances for predictable workloads
   - Enable S3 lifecycle policies
   - Use CloudFront caching effectively
   - Consider Aurora Serverless for databases

### Estimated Costs (Monthly)

| Component | Dev | Prod |
|-----------|-----|------|
| CloudFront | $5 | $50+ |
| ALB | $20 | $20 |
| ECS Fargate | $10 | $100+ |
| NAT Gateway | $0 | $45 |
| S3 Storage | $1 | $10+ |
| DynamoDB | $5 | $25+ |
| **Total** | **$41** | **$250+** |

## Security Considerations

### Best Practices Implemented

1. **Network Security**
   - Private subnets for backend services
   - Security groups with least privilege
   - WAF protection for web applications

2. **Data Security**
   - Encryption at rest (S3, DynamoDB, RDS)
   - Encryption in transit (HTTPS only)
   - Secrets in AWS Secrets Manager

3. **Access Control**
   - IAM roles with minimal permissions
   - No hardcoded credentials
   - CloudTrail logging enabled

4. **Compliance**
   - Backup and recovery procedures
   - Log retention policies
   - Multi-AZ deployment for HA

### Security Checklist

- [ ] SSL/TLS certificates valid and auto-renewing
- [ ] WAF rules enabled and configured
- [ ] Security groups reviewed and restricted
- [ ] Secrets rotated regularly
- [ ] Backups tested and verified
- [ ] CloudTrail logging enabled
- [ ] VPC Flow Logs enabled (production)
- [ ] Container images scanned for vulnerabilities

## Maintenance

### Regular Tasks

1. **Weekly**
   - Review CloudWatch alarms
   - Check auto-scaling metrics
   - Monitor costs

2. **Monthly**
   - Update container images
   - Review and rotate secrets
   - Analyze logs for issues

3. **Quarterly**
   - Security audit
   - Disaster recovery test
   - Performance optimization review

## Support

For issues or questions:
1. Check the [Troubleshooting](#troubleshooting) section
2. Review CloudFormation events and CloudWatch logs
3. Consult AWS documentation
4. Contact your DevOps team

## License

This deployment system is proprietary to StarHub/Totogi.

---

*Last Updated: November 2024*
*Version: 1.0.0*

# Complete Layered Business Capability Deployment Plan

## Executive Summary

This document outlines a comprehensive plan for creating an automated deployment system for business capabilities in the Nexus AI Customer Toolkit. The system will deploy complete business capabilities (frontend and backend) to any AWS environment using a layered, incremental approach with proper separation of concerns.

## Table of Contents

1. [Objective](#objective)
2. [Architecture Overview](#architecture-overview)
3. [Stack Layers](#stack-layers)
4. [Implementation Plan](#implementation-plan)
5. [Directory Structure](#directory-structure)
6. [Deployment Workflow](#deployment-workflow)
7. [Configuration Management](#configuration-management)
8. [Cross-Account and Cross-Region Support](#cross-account-and-cross-region-support)
9. [Security Considerations](#security-considerations)
10. [Testing Strategy](#testing-strategy)
11. [Documentation Requirements](#documentation-requirements)

## Objective

Create a modular, reusable deployment automation system that:
- Deploys business capabilities from pre-built artifacts (S3 for frontend, ECR for backend)
- Supports multiple AWS accounts and regions
- Uses layered CloudFormation stacks for better control and troubleshooting
- Provides rollback capabilities and health checks
- Maintains security best practices with proper IAM roles and encryption

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│              Business Capability                      │
├───────────────────────────┬───────────────────────────┤
│        Frontend           │         Backend           │
├───────────────────────────┼───────────────────────────┤
│   Source Artifacts:       │   Source Artifacts:       │
│   S3: dist.zip           │   ECR: container:tag      │
└───────────────────────────┴───────────────────────────┘
                    ↓
        Layered Deployment Automation
                    ↓
┌─────────────────────────────────────────────────────┐
│            Target AWS Environment                    │
├─────────────────────────────────────────────────────┤
│ Frontend Infrastructure  │ Backend Infrastructure    │
│ ├─ CloudFront CDN       │ ├─ ECS Fargate           │
│ ├─ S3 Static Hosting    │ ├─ Application LB        │
│ ├─ WAF Protection       │ ├─ Auto-scaling          │
│ └─ Route53 DNS          │ └─ RDS/DynamoDB          │
└─────────────────────────────────────────────────────┘
```

## Stack Layers

### Frontend Stacks

#### 1. Frontend Global Stack (us-east-1)
**File**: `templates/frontend/global-stack.yaml`
**Resources**:
- S3 bucket for static content
- WAF WebACL for CloudFront protection
- ACM Certificate (must be in us-east-1 for CloudFront)
- Route53 DNS records for frontend domain

#### 2. Frontend Regional Stack
**File**: `templates/frontend/regional-stack.yaml`
**Resources**:
- CloudFront distribution
- Origin Access Identity (OAI)
- Cache behaviors and error pages
- Lambda@Edge functions (optional)

### Backend Stacks

#### 3. Backend Foundation Stack
**File**: `templates/backend/foundation-stack.yaml`
**Resources**:
- IAM Task Execution Role (for ECS)
- IAM Task Role (for application)
- IAM Auto-scaling Role
- CloudWatch Log Groups
- Route53 placeholder records

#### 4. Backend Regional Certificate Stack (Conditional)
**File**: `templates/backend/regional-cert-stack.yaml`
**Resources**:
- ACM Certificate for ALB (when deploying outside us-east-1)

#### 5. Backend Storage Stack
**File**: `templates/backend/storage-stack.yaml`
**Resources**:
- S3 buckets for application data
- DynamoDB tables
- Secrets Manager secrets
- ECR repository
- Parameter Store configurations

#### 6. Backend Network Stack
**File**: `templates/backend/network-stack.yaml`
**Resources**:
- VPC (or use existing)
- Public/Private Subnets
- Internet Gateway
- NAT Gateway (optional)
- Security Groups
- ECS Cluster

#### 7. Backend Service Stack
**File**: `templates/backend/service-stack.yaml`
**Resources**:
- Application Load Balancer
- Target Groups
- ECS Task Definition
- ECS Service
- Auto-scaling configuration
- Route53 alias records

## Implementation Plan

### Phase 1: Core Infrastructure (Week 1)

#### Task 1.1: Create Main Orchestrator Script
**File**: `deploy-capability-layered.sh`
**Components**:
```bash
- Configuration loading
- Stack deployment orchestration
- Parameter management
- Error handling and rollback
- Output aggregation
```

#### Task 1.2: Create Helper Scripts
**Files**:
- `scripts/assume-role.sh` - Cross-account role assumption
- `scripts/validate-config.sh` - Configuration validation
- `scripts/copy-artifacts.sh` - Artifact management
- `scripts/health-check.sh` - Deployment verification

#### Task 1.3: Create Library Functions
**Files**:
- `lib/colors.sh` - Terminal output formatting
- `lib/logging.sh` - Structured logging
- `lib/aws-helpers.sh` - AWS CLI wrappers
- `lib/stack-helpers.sh` - CloudFormation utilities

### Phase 2: Frontend Infrastructure (Week 2)

#### Task 2.1: Frontend Global Stack Template
**Deliverables**:
- CloudFormation template for global resources
- Parameter definitions
- Output exports for cross-stack references
- Conditional logic for environments

#### Task 2.2: Frontend Regional Stack Template
**Deliverables**:
- CloudFormation template for regional resources
- Import values from global stack
- CloudFront configuration with best practices
- Cache behavior optimization

#### Task 2.3: Frontend Deployment Functions
**Deliverables**:
- Artifact download from source S3
- Static file upload to target S3
- CloudFront cache invalidation
- DNS verification

### Phase 3: Backend Infrastructure (Week 3-4)

#### Task 3.1: Backend Foundation Stack Template
**Deliverables**:
- IAM roles with least privilege
- Cross-region certificate handling
- Log group configuration
- Route53 initial setup

#### Task 3.2: Backend Storage Stack Template
**Deliverables**:
- S3 bucket with encryption and versioning
- DynamoDB with backup configuration
- Secrets rotation policies
- ECR lifecycle policies

#### Task 3.3: Backend Network Stack Template
**Deliverables**:
- VPC with proper CIDR planning
- Subnet distribution across AZs
- Security group rules
- Optional existing VPC support

#### Task 3.4: Backend Service Stack Template
**Deliverables**:
- ECS task definition with proper resource allocation
- ALB with health checks
- Auto-scaling policies
- Service discovery integration

### Phase 4: Integration and Testing (Week 5)

#### Task 4.1: Configuration Management
**Deliverables**:
- YAML configuration schema
- Environment-specific configs
- Configuration validation
- Secret management integration

#### Task 4.2: Cross-Account/Region Support
**Deliverables**:
- Role assumption logic
- Cross-region artifact copying
- Certificate management for regions
- DNS delegation handling

#### Task 4.3: Testing and Validation
**Deliverables**:
- Unit tests for functions
- Integration tests for stacks
- End-to-end deployment tests
- Rollback scenarios

### Phase 5: Documentation and Finalization (Week 6)

#### Task 5.1: User Documentation
**Deliverables**:
- README with quick start
- Configuration guide
- Troubleshooting guide
- Best practices document

#### Task 5.2: Technical Documentation
**Deliverables**:
- Architecture diagrams
- API documentation
- CloudFormation parameter reference
- Security documentation

## Directory Structure

```
/opt/mycode/nexus/nexus-deployer/deploy/
├── deploy-capability-layered.sh      # Main orchestrator script
├── plan.md                           # This deployment plan
├── README.md                         # User documentation
├── config/
│   ├── capability-config-schema.yaml # Configuration schema
│   ├── example-config.yaml          # Example configuration
│   ├── dev-config.yaml              # Development environment
│   ├── stage-config.yaml            # Staging environment
│   └── prod-config.yaml             # Production environment
├── templates/
│   ├── frontend/
│   │   ├── global-stack.yaml        # Frontend global resources
│   │   └── regional-stack.yaml      # Frontend regional resources
│   └── backend/
│       ├── foundation-stack.yaml    # IAM, certificates, Route53
│       ├── regional-cert-stack.yaml # Regional certificates
│       ├── storage-stack.yaml       # S3, DynamoDB, Secrets
│       ├── network-stack.yaml       # VPC, subnets, security
│       └── service-stack.yaml       # ECS, ALB, auto-scaling
├── scripts/
│   ├── assume-role.sh               # Role assumption helper
│   ├── validate-config.sh          # Configuration validator
│   ├── copy-artifacts.sh           # Artifact management
│   ├── health-check.sh             # Health verification
│   └── rollback.sh                 # Rollback automation
├── lib/
│   ├── colors.sh                   # Terminal colors
│   ├── logging.sh                  # Logging utilities
│   ├── aws-helpers.sh              # AWS CLI helpers
│   └── stack-helpers.sh            # CloudFormation helpers
├── tests/
│   ├── unit/                       # Unit tests
│   ├── integration/                # Integration tests
│   └── e2e/                        # End-to-end tests
└── docs/
    ├── architecture.md              # Architecture details
    ├── configuration.md             # Configuration guide
    ├── troubleshooting.md          # Troubleshooting guide
    └── security.md                 # Security documentation
```

## Deployment Workflow

### 1. Pre-Deployment Phase

```bash
# Validate prerequisites
check_aws_cli_version
check_required_permissions
validate_configuration

# Assume deployment role if needed
assume_cross_account_role

# Validate source artifacts exist
verify_frontend_artifacts
verify_backend_container
```

### 2. Frontend Deployment

```bash
# Deploy global resources (us-east-1)
deploy_stack "frontend-global" "us-east-1"

# Deploy regional resources
deploy_stack "frontend-regional" "$TARGET_REGION"

# Upload static content
download_frontend_artifacts
upload_to_s3_bucket
create_cloudfront_invalidation
```

### 3. Backend Deployment

```bash
# Deploy foundation resources
deploy_stack "backend-foundation" "$TARGET_REGION"

# Deploy regional certificate if needed
if [[ "$TARGET_REGION" != "us-east-1" ]]; then
  deploy_stack "backend-regional-cert" "$TARGET_REGION"
fi

# Deploy infrastructure layers
deploy_stack "backend-storage" "$TARGET_REGION"
deploy_stack "backend-network" "$TARGET_REGION"

# Copy container image
copy_ecr_image_cross_account

# Deploy service
deploy_stack "backend-service" "$TARGET_REGION"

# Update Route53 alias
update_route53_to_alb
```

### 4. Post-Deployment Phase

```bash
# Verify deployment
run_health_checks
verify_dns_resolution
test_application_endpoints

# Generate outputs report
aggregate_stack_outputs
generate_deployment_report
send_notification
```

## Configuration Management

### Configuration Schema

```yaml
# capability-config.yaml
capability:
  name: string                    # Capability identifier
  version: string                 # Semantic version
  description: string            # Business description

source:
  frontend:
    s3_uri: string               # S3 URI for frontend dist
    s3_region: string           # Source bucket region
  backend:
    ecr_uri: string             # ECR URI with tag
    ecr_region: string          # Source ECR region

target:
  account_id: string            # Target AWS account
  region: string                # Target deployment region
  role_arn: string              # Cross-account role (optional)
  environment: enum             # dev|stage|prod

infrastructure:
  domain:
    base: string                # Base domain (e.g., example.com)
    frontend_subdomain: string  # Frontend subdomain
    backend_subdomain: string   # API subdomain
    hosted_zone_id: string      # Route53 zone ID
  
  frontend:
    s3_bucket_name: string      # Static content bucket
    cloudfront:
      enabled: boolean          # Enable CloudFront
      price_class: string       # CloudFront price class
      waf_enabled: boolean      # Enable WAF protection
      cache_ttl: integer        # Default cache TTL
  
  backend:
    vpc:
      create_new: boolean       # Create new VPC
      vpc_id: string           # Existing VPC ID
      cidr: string             # VPC CIDR (if creating)
      subnets:
        public: array          # Public subnet IDs
        private: array         # Private subnet IDs
    
    ecs:
      cluster_name: string     # ECS cluster name
      task_cpu: integer        # CPU units (256-4096)
      task_memory: integer     # Memory in MiB
      desired_count: integer   # Number of tasks
      
    autoscaling:
      enabled: boolean         # Enable auto-scaling
      min_capacity: integer    # Minimum tasks
      max_capacity: integer    # Maximum tasks
      target_cpu: integer      # Target CPU percentage
    
    storage:
      s3_data_bucket: string   # Data bucket name
      dynamodb_tables: array   # DynamoDB table configs
      enable_backups: boolean  # Enable automated backups

monitoring:
  cloudwatch:
    log_retention_days: integer  # Log retention period
    detailed_metrics: boolean    # Enable detailed metrics
  alarms:
    enabled: boolean             # Enable CloudWatch alarms
    sns_topic: string           # SNS topic for alerts
  xray:
    enabled: boolean            # Enable X-Ray tracing

tags:
  common:                      # Tags applied to all resources
    Project: string
    Environment: string
    ManagedBy: string
  custom: object              # Additional custom tags
```

### Environment-Specific Overrides

```yaml
# dev-config.yaml
include: capability-config.yaml

target:
  environment: dev
  region: us-east-1

infrastructure:
  backend:
    ecs:
      desired_count: 1
      task_cpu: 512
      task_memory: 1024
    autoscaling:
      enabled: false

monitoring:
  cloudwatch:
    log_retention_days: 7
```

## Cross-Account and Cross-Region Support

### Cross-Account Deployment

```bash
# Role assumption function
assume_role() {
  local role_arn=$1
  local session_name="capability-deployment-$(date +%s)"
  
  # Get temporary credentials
  credentials=$(aws sts assume-role \
    --role-arn "$role_arn" \
    --role-session-name "$session_name" \
    --duration-seconds 3600 \
    --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' \
    --output text)
  
  # Export credentials
  export AWS_ACCESS_KEY_ID=$(echo $credentials | cut -d' ' -f1)
  export AWS_SECRET_ACCESS_KEY=$(echo $credentials | cut -d' ' -f2)
  export AWS_SESSION_TOKEN=$(echo $credentials | cut -d' ' -f3)
}

# Cross-account artifact copy
copy_cross_account_artifacts() {
  local source_bucket=$1
  local target_bucket=$2
  
  # Use assume role for source account
  assume_role "$SOURCE_ROLE_ARN"
  
  # Copy with appropriate permissions
  aws s3 cp "s3://${source_bucket}/" "s3://${target_bucket}/" \
    --recursive \
    --acl bucket-owner-full-control \
    --metadata-directive REPLACE
}
```

### Cross-Region Considerations

1. **Certificates**: ACM certificates for CloudFront must be in us-east-1
2. **ECR Images**: Must be copied to target region
3. **S3 Buckets**: Region-specific, require cross-region replication if needed
4. **Route53**: Global service, no region considerations
5. **CloudWatch Logs**: Region-specific, consider centralization

## Security Considerations

### IAM Permissions

#### Minimum Deployment Role Permissions
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "cloudformation:*",
        "iam:CreateRole",
        "iam:AttachRolePolicy",
        "iam:PutRolePolicy",
        "iam:PassRole",
        "s3:CreateBucket",
        "s3:PutObject",
        "s3:GetObject",
        "ec2:*",
        "ecs:*",
        "elasticloadbalancing:*",
        "acm:RequestCertificate",
        "acm:DescribeCertificate",
        "route53:ChangeResourceRecordSets",
        "cloudfront:CreateDistribution",
        "cloudfront:UpdateDistribution",
        "wafv2:CreateWebACL",
        "logs:CreateLogGroup",
        "secretsmanager:CreateSecret"
      ],
      "Resource": "*"
    }
  ]
}
```

### Encryption

- **S3**: Server-side encryption with AWS managed keys (SSE-S3)
- **EBS**: Volume encryption for ECS hosts
- **Secrets Manager**: Automatic encryption for secrets
- **Transit**: TLS 1.2+ for all data in transit

### Network Security

- **Security Groups**: Least privilege access
- **NACLs**: Additional network layer protection
- **Private Subnets**: Backend services in private subnets
- **WAF**: Protection against common web exploits

## Testing Strategy

### Unit Tests

```bash
# Test configuration validation
./tests/unit/test_config_validation.sh

# Test AWS helper functions
./tests/unit/test_aws_helpers.sh

# Test stack deployment functions
./tests/unit/test_stack_deployment.sh
```

### Integration Tests

```bash
# Test CloudFormation template validation
./tests/integration/test_template_validation.sh

# Test cross-stack references
./tests/integration/test_stack_dependencies.sh

# Test artifact management
./tests/integration/test_artifact_copy.sh
```

### End-to-End Tests

```bash
# Full deployment test
./tests/e2e/test_complete_deployment.sh

# Rollback test
./tests/e2e/test_rollback_scenario.sh

# Cross-region test
./tests/e2e/test_cross_region_deployment.sh
```

## Documentation Requirements

### User Documentation

1. **Quick Start Guide**
   - Prerequisites
   - Basic configuration
   - First deployment
   - Verification steps

2. **Configuration Reference**
   - All configuration options
   - Examples for common scenarios
   - Best practices

3. **Troubleshooting Guide**
   - Common errors and solutions
   - Debug mode usage
   - Log analysis

### Technical Documentation

1. **Architecture Document**
   - System design
   - Component interactions
   - Data flow diagrams

2. **API Reference**
   - Script parameters
   - Function documentation
   - Exit codes

3. **Security Guide**
   - IAM configuration
   - Network security
   - Compliance considerations

## Success Metrics

- **Deployment Time**: < 30 minutes for complete capability
- **Success Rate**: > 95% successful deployments
- **Rollback Time**: < 10 minutes
- **Cross-Region Support**: All AWS regions
- **Cost Optimization**: 20% reduction vs manual deployment

## Timeline

| Week | Phase | Deliverables |
|------|-------|--------------|
| 1 | Core Infrastructure | Orchestrator script, helper functions |
| 2 | Frontend Infrastructure | Global and regional stacks |
| 3-4 | Backend Infrastructure | All backend stack layers |
| 5 | Integration & Testing | Cross-account support, tests |
| 6 | Documentation | User and technical docs |

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| CloudFormation limits | Split into smaller stacks |
| Cross-region complexity | Automated certificate handling |
| IAM permission issues | Comprehensive permission validator |
| Rollback failures | Stack-level rollback strategy |
| Artifact accessibility | Pre-deployment validation |

## Conclusion

This layered deployment approach provides a robust, scalable, and maintainable solution for deploying business capabilities across AWS environments. The modular design ensures flexibility while maintaining security and operational best practices.

## Next Steps

1. Review and approve this plan
2. Set up development environment
3. Begin Phase 1 implementation
4. Schedule weekly progress reviews
5. Prepare testing environments

---

*Document Version: 1.0*  
*Last Updated: November 2024*  
*Author: DevOps Team*

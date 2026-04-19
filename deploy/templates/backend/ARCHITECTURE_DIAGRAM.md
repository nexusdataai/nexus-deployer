# Backend Stack Architecture Diagram

## Stack Dependency Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DEPLOYMENT ORDER                             │
└─────────────────────────────────────────────────────────────────────┘

    ┌──────────────────┐
    │  1. Foundation   │  CloudWatch Logs, KMS Keys
    │     Stack        │  (No dependencies)
    └────────┬─────────┘
             │
             │ Exports: Log Groups, KMS Keys
             │
    ┌────────▼─────────┐
    │  2. IAM Roles    │  Task Execution, Task, Auto Scaling Roles
    │     Stack        │  (No dependencies)
    └────────┬─────────┘
             │
             │ Exports: Role ARNs
             │
    ┌────────▼─────────┐
    │  3. Network      │  VPC, Subnets, Security Groups, ECS Cluster
    │     Stack        │  (No dependencies)
    └────────┬─────────┘
             │
             │ Exports: VPC ID, Subnets, Security Groups, Cluster
             │
    ┌────────▼─────────┐
    │  4. Storage      │  S3, DynamoDB, Secrets, ECR
    │     Stack        │  Depends on: Foundation (for KMS permissions)
    └────────┬─────────┘
             │
             │ Exports: Bucket Names, Table Names, Secret ARNs
             │
    ┌────────▼─────────┐
    │  5. Regional     │  SSL Certificate (Optional)
    │  Certificate     │  (No dependencies)
    │     Stack        │
    └────────┬─────────┘
             │
             │ Exports: Certificate ARN
             │
    ┌────────▼─────────────────────────────────────────────┐
    │  6. Service Stack                                     │
    │  ALB, ECS Service, Task Definition, Auto Scaling      │
    │  Depends on: Foundation, IAM Roles, Network,          │
    │              Storage, Domain/Regional Cert            │
    └────────┬──────────────────────────────────────────────┘
             │
             │ Exports: ALB DNS, Service ARN, Target Group
             │
    ┌────────▼─────────┐
    │  7. Domain       │  Route53 Records, SSL Certificate, Health Checks
    │     Stack        │  Depends on: Service (for ALB DNS)
    └──────────────────┘

             Exports: API Domain, Certificate ARN, Health Check ID
```

---

## Resource Relationships

```
┌─────────────────────────────────────────────────────────────────────┐
│                      RESOURCE DEPENDENCIES                           │
└─────────────────────────────────────────────────────────────────────┘

Foundation Stack
├── CloudWatch Log Group (ECS)
│   └── Used by: ECS Task Definition
├── CloudWatch Log Group (Application)
│   └── Used by: Application logging
└── KMS Key (Logs)
    └── Used by: CloudWatch Logs encryption

IAM Roles Stack
├── Task Execution Role
│   ├── Used by: ECS Task Definition
│   └── Permissions: ECR, Secrets Manager, CloudWatch Logs
├── Task Role
│   ├── Used by: ECS Task Definition
│   └── Permissions: S3, DynamoDB, CloudWatch, SQS, SNS
└── Auto Scaling Role
    └── Used by: ECS Service Auto Scaling

Network Stack
├── VPC
│   ├── Public Subnets
│   │   └── Used by: ALB
│   └── Private Subnets
│       └── Used by: ECS Tasks
├── Security Group (ALB)
│   ├── Ingress: 80, 443 from Internet
│   └── Egress: To ECS Security Group
├── Security Group (ECS)
│   ├── Ingress: From ALB Security Group
│   └── Egress: To Internet (via NAT)
└── ECS Cluster
    └── Used by: ECS Service

Storage Stack
├── S3 Bucket (Data)
│   └── Used by: Application (via Task Role)
├── S3 Bucket (Backups)
│   └── Used by: Backup processes
├── DynamoDB Table (State)
│   └── Used by: Application (via Task Role)
├── DynamoDB Table (Sessions)
│   └── Used by: Application (via Task Role)
├── Secrets Manager (App Secrets)
│   └── Used by: ECS Task Definition
├── Secrets Manager (DB Secrets)
│   └── Used by: ECS Task Definition
└── ECR Repository
    └── Used by: ECS Task Definition

Domain Stack
├── ACM Certificate
│   └── Used by: ALB HTTPS Listener
├── Route53 A Record
│   └── Points to: ALB
└── Route53 Health Check
    └── Monitors: API endpoint

Service Stack
├── Application Load Balancer
│   ├── Uses: Public Subnets, ALB Security Group
│   └── Certificate: From Domain Stack or Regional Cert Stack
├── Target Group
│   ├── Uses: VPC
│   └── Targets: ECS Tasks
├── ECS Task Definition
│   ├── Uses: Task Execution Role, Task Role
│   ├── Uses: Container Image from ECR
│   ├── Uses: Secrets from Secrets Manager
│   └── Logs to: CloudWatch Log Group
└── ECS Service
    ├── Uses: ECS Cluster, Private Subnets, ECS Security Group
    ├── Uses: Task Definition
    ├── Uses: Target Group
    └── Auto Scaling: Uses Auto Scaling Role
```

---

## Network Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         TRAFFIC FLOW                                 │
└─────────────────────────────────────────────────────────────────────┘

Internet
   │
   │ HTTPS (443)
   │
   ▼
┌──────────────────────┐
│  Route53 DNS         │  api.example.com → ALB DNS
│  (Domain Stack)      │
└──────────┬───────────┘
           │
           │ DNS Resolution
           │
           ▼
┌──────────────────────┐
│  Application Load    │  Public Subnets (Multi-AZ)
│  Balancer            │  Security Group: Allow 80, 443 from Internet
│  (Service Stack)     │
└──────────┬───────────┘
           │
           │ HTTP (Container Port)
           │ Security Group: ALB → ECS
           │
           ▼
┌──────────────────────┐
│  ECS Tasks           │  Private Subnets (Multi-AZ)
│  (Service Stack)     │  Security Group: Allow from ALB only
│                      │
│  ┌────────────────┐  │
│  │  Container     │  │
│  │  - App Code    │  │
│  │  - Port 8080   │  │
│  └────────────────┘  │
└──────────┬───────────┘
           │
           │ Outbound Connections
           │ (via NAT Gateway)
           │
           ├─────────────────────────────────────┐
           │                                     │
           ▼                                     ▼
┌──────────────────────┐              ┌──────────────────────┐
│  AWS Services        │              │  Internet            │
│  - S3                │              │  - External APIs     │
│  - DynamoDB          │              │  - Third-party       │
│  - Secrets Manager   │              │    Services          │
│  - CloudWatch        │              │                      │
└──────────────────────┘              └──────────────────────┘
```

---

## Security Boundaries

```
┌─────────────────────────────────────────────────────────────────────┐
│                      SECURITY ARCHITECTURE                           │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  PUBLIC ZONE (Internet-facing)                                       │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  Application Load Balancer                                      │ │
│  │  - SSL/TLS Termination                                          │ │
│  │  - WAF (Optional)                                               │ │
│  │  - Security Group: 80, 443 from 0.0.0.0/0                       │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                       │
└───────────────────────────────┬───────────────────────────────────────┘
                                │
                                │ Encrypted Connection
                                │
┌───────────────────────────────▼───────────────────────────────────────┐
│  PRIVATE ZONE (Application Tier)                                      │
│                                                                        │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  ECS Tasks (Fargate)                                            │  │
│  │  - No Public IP                                                 │  │
│  │  - Security Group: Only from ALB                                │  │
│  │  - IAM Task Role: Least Privilege                               │  │
│  │  - Secrets: From Secrets Manager                                │  │
│  │  - Logs: Encrypted CloudWatch Logs                              │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                        │
└───────────────────────────────┬────────────────────────────────────────┘
                                │
                                │ IAM Role-based Access
                                │
┌───────────────────────────────▼────────────────────────────────────────┐
│  DATA ZONE (Storage & Services)                                        │
│                                                                         │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │  S3 Buckets                                                     │   │
│  │  - Private (Block Public Access)                                │   │
│  │  - Encrypted at Rest (AES-256)                                  │   │
│  │  - Versioning Enabled                                           │   │
│  │  - Access: IAM Task Role only                                   │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │  DynamoDB Tables                                                │   │
│  │  - Encrypted at Rest (KMS)                                      │   │
│  │  - Point-in-Time Recovery                                       │   │
│  │  - Access: IAM Task Role only                                   │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │  Secrets Manager                                                │   │
│  │  - Encrypted at Rest (KMS)                                      │   │
│  │  - Automatic Rotation (Optional)                                │   │
│  │  - Access: IAM Task Execution Role only                         │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  MANAGEMENT ZONE (Logging & Monitoring)                              │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  CloudWatch Logs                                                │ │
│  │  - Encrypted at Rest (KMS - Production)                         │ │
│  │  - Retention Policy                                             │ │
│  │  - Access: IAM Task Execution Role                              │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  CloudWatch Metrics & Alarms                                    │ │
│  │  - Service Health Monitoring                                    │ │
│  │  - Auto Scaling Triggers                                        │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## IAM Permission Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                      IAM ROLES & PERMISSIONS                         │
└─────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  Task Execution Role (IAM Roles Stack)                           │
│  Used by: ECS to start tasks                                     │
│                                                                   │
│  Permissions:                                                     │
│  ├── ECR: Pull container images                                  │
│  ├── Secrets Manager: Read secrets                               │
│  ├── SSM Parameter Store: Read parameters                        │
│  └── CloudWatch Logs: Write logs                                 │
│                                                                   │
│  Trust Policy: ecs-tasks.amazonaws.com                           │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  Task Role (IAM Roles Stack)                                     │
│  Used by: Application code running in container                  │
│                                                                   │
│  Permissions:                                                     │
│  ├── S3: Read/Write to data bucket                               │
│  ├── DynamoDB: CRUD operations on tables                         │
│  ├── CloudWatch: Put metrics                                     │
│  ├── X-Ray: Put trace segments                                   │
│  ├── SQS: Send/Receive messages                                  │
│  ├── SNS: Publish notifications                                  │
│  ├── EventBridge: Put events                                     │
│  └── KMS: Encrypt/Decrypt (via S3, DynamoDB)                     │
│                                                                   │
│  Trust Policy: ecs-tasks.amazonaws.com                           │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  Auto Scaling Role (IAM Roles Stack)                             │
│  Used by: Application Auto Scaling service                       │
│                                                                   │
│  Permissions:                                                     │
│  ├── ECS: Describe services                                      │
│  ├── ECS: Update service desired count                           │
│  ├── CloudWatch: Read metrics                                    │
│  └── CloudWatch: Describe alarms                                 │
│                                                                   │
│  Trust Policy: application-autoscaling.amazonaws.com             │
└──────────────────────────────────────────────────────────────────┘
```

---

## Deployment Sequence Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                    DEPLOYMENT SEQUENCE                               │
└─────────────────────────────────────────────────────────────────────┘

Time
 │
 │  ┌─────────────────────────────────────────────────────────────┐
 ├─▶│ 1. Deploy Foundation Stack                                  │
 │  │    - Create CloudWatch Log Groups                           │
 │  │    - Create KMS Keys (prod)                                 │
 │  │    Duration: ~2-3 minutes                                   │
 │  └─────────────────────────────────────────────────────────────┘
 │
 │  ┌─────────────────────────────────────────────────────────────┐
 ├─▶│ 2. Deploy IAM Roles Stack                                   │
 │  │    - Create Task Execution Role                             │
 │  │    - Create Task Role                                       │
 │  │    - Create Auto Scaling Role                               │
 │  │    Duration: ~2-3 minutes                                   │
 │  └─────────────────────────────────────────────────────────────┘
 │
 │  ┌─────────────────────────────────────────────────────────────┐
 ├─▶│ 3. Deploy Network Stack                                     │
 │  │    - Create VPC                                             │
 │  │    - Create Subnets (Public & Private)                      │
 │  │    - Create Internet Gateway                                │
 │  │    - Create NAT Gateways                                    │
 │  │    - Create Security Groups                                 │
 │  │    - Create ECS Cluster                                     │
 │  │    Duration: ~5-7 minutes                                   │
 │  └─────────────────────────────────────────────────────────────┘
 │
 │  ┌─────────────────────────────────────────────────────────────┐
 ├─▶│ 4. Deploy Storage Stack                                     │
 │  │    - Create S3 Buckets                                      │
 │  │    - Create DynamoDB Tables                                 │
 │  │    - Create Secrets Manager Secrets                         │
 │  │    - Create ECR Repository                                  │
 │  │    - Create KMS Keys (prod)                                 │
 │  │    Duration: ~3-5 minutes                                   │
 │  └─────────────────────────────────────────────────────────────┘
 │
 │  ┌─────────────────────────────────────────────────────────────┐
 ├─▶│ 5. Deploy Regional Certificate Stack (Optional)             │
 │  │    - Create ACM Certificate                                 │
 │  │    - Wait for DNS Validation                                │
 │  │    Duration: ~5-10 minutes (validation time)                │
 │  └─────────────────────────────────────────────────────────────┘
 │
 │  ┌─────────────────────────────────────────────────────────────┐
 ├─▶│ 6. Deploy Service Stack                                     │
 │  │    - Create Application Load Balancer                       │
 │  │    - Create Target Group                                    │
 │  │    - Create HTTPS Listener                                  │
 │  │    - Create HTTP Listener (redirect)                        │
 │  │    - Create ECS Task Definition                             │
 │  │    - Create ECS Service                                     │
 │  │    - Create Auto Scaling Policies                           │
 │  │    - Wait for tasks to be healthy                           │
 │  │    Duration: ~10-15 minutes                                 │
 │  └─────────────────────────────────────────────────────────────┘
 │
 │  ┌─────────────────────────────────────────────────────────────┐
 ├─▶│ 7. Deploy Domain Stack                                      │
 │  │    - Create ACM Certificate (if needed)                     │
 │  │    - Wait for DNS Validation                                │
 │  │    - Create Route53 A Record                                │
 │  │    - Create Health Check (optional)                         │
 │  │    Duration: ~5-10 minutes                                  │
 │  └─────────────────────────────────────────────────────────────┘
 │
 ▼
Complete

Total Duration: ~30-45 minutes
```

---

## Stack Size Comparison

```
┌─────────────────────────────────────────────────────────────────────┐
│                    BEFORE vs AFTER                                   │
└─────────────────────────────────────────────────────────────────────┘

BEFORE (Monolithic)
┌────────────────────────────────────────────────────────────────┐
│  foundation-stack.yaml (Large - 500+ lines)                    │
│  ├── IAM Roles (3 resources)                                   │
│  ├── SSL Certificates (1 resource)                             │
│  ├── Route53 Records (1 resource)                              │
│  ├── CloudWatch Log Groups (2 resources)                       │
│  └── KMS Keys (2 resources)                                    │
│                                                                 │
│  Total: 9 resources in 1 stack                                 │
└────────────────────────────────────────────────────────────────┘

AFTER (Modular)
┌────────────────────────────────────────────────────────────────┐
│  foundation-stack.yaml (Small - 150 lines)                     │
│  ├── CloudWatch Log Groups (2 resources)                       │
│  └── KMS Keys (2 resources)                                    │
│                                                                 │
│  Total: 4 resources                                            │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│  iam-roles-stack.yaml (Medium - 200 lines)                     │
│  ├── Task Execution Role (1 resource)                          │
│  ├── Task Role (1 resource)                                    │
│  └── Auto Scaling Role (1 resource)                            │
│                                                                 │
│  Total: 3 resources                                            │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│  domain-stack.yaml (Medium - 250 lines)                        │
│  ├── ACM Certificate (1 resource)                              │
│  ├── Route53 A Record (1 resource)                             │
│  ├── Route53 Health Check Record (1 resource)                  │
│  └── Route53 Health Check (1 resource)                         │
│                                                                 │
│  Total: 4 resources                                            │
└────────────────────────────────────────────────────────────────┘

Benefits:
✅ Smaller, focused templates
✅ Easier to understand
✅ Faster to update
✅ Better separation of concerns
```

---

## Legend

```
┌─────────────────────────────────────────────────────────────────────┐
│                           SYMBOLS                                    │
└─────────────────────────────────────────────────────────────────────┘

│  Vertical line (connection)
├  Branch point
└  End point
▼  Flow direction (downward)
▶  Flow direction (rightward)
┌─┐  Box corners
─  Horizontal line
```

---

**Note:** These diagrams provide a visual representation of the modular backend stack architecture. For detailed implementation, refer to the CloudFormation templates and documentation.

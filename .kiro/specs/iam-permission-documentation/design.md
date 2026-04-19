# Design Document: IAM Permission Documentation

## Overview

This design adds comprehensive IAM permission documentation and guidance to the installation wizard. The implementation introduces new UI components that provide contextual help, setup guides, and validation tools to help users configure AWS IAM roles correctly for capability deployment and deletion.

The design follows the existing wizard architecture, adding new components that integrate seamlessly with the current flow while providing detailed IAM guidance at appropriate steps.

## Architecture

The feature consists of three main architectural layers:

```mermaid
graph TB
    subgraph "Frontend Components"
        AWSConfig[AWSConfigurationEnhanced]
        PermVerify[PermissionVerification]
        IAMPanel[IAMPermissionPanel]
        SetupGuide[IAMSetupGuideModal]
        CostPanel[CostEstimationPanel]
        Tooltips[IAMTooltips]
    end
    
    subgraph "Data Layer"
        PermData[permission-data.ts]
        CostData[cost-data.ts]
        PolicyGen[policy-generator.ts]
    end
    
    subgraph "Backend API"
        VerifyAPI[/api/aws/verify-permissions]
        CrossAcctAPI[/api/aws/verify-cross-account]
    end
    
    AWSConfig --> IAMPanel
    AWSConfig --> SetupGuide
    AWSConfig --> CostPanel
    AWSConfig --> Tooltips
    PermVerify --> PolicyGen
    IAMPanel --> PermData
    CostPanel --> CostData
    PolicyGen --> PermData
    PermVerify --> VerifyAPI
    AWSConfig --> CrossAcctAPI
```

## Components and Interfaces

### IAMPermissionPanel Component

A collapsible panel displaying categorized IAM permissions required for deployment.

```typescript
interface IAMPermissionPanelProps {
  expanded: boolean;
  onToggle: () => void;
  selectedCapability?: Capability;
}

interface PermissionCategory {
  name: string;
  description: string;
  services: ServicePermission[];
}

interface ServicePermission {
  service: string;
  purpose: string;
  keyActions: string[];
  allActions: string[];
}
```

### IAMSetupGuideModal Component

A modal dialog providing step-by-step IAM role setup instructions.

```typescript
interface IAMSetupGuideModalProps {
  isOpen: boolean;
  onClose: () => void;
  sourceAccountId: string;
  targetAccountId?: string;
  isCrossAccount: boolean;
}

type SetupMethod = 'cloudformation' | 'cli' | 'manual';

interface SetupGuideState {
  selectedMethod: SetupMethod;
  externalId: string;
  roleName: string;
}
```

### CostEstimationPanel Component

Displays estimated monthly costs for the deployment.

```typescript
interface CostEstimationPanelProps {
  environment: 'dev' | 'stage' | 'prod';
  enableNATGateway: boolean;
  selectedCapability?: Capability;
}

interface CostEstimate {
  resource: string;
  description: string;
  monthlyCostMin: number;
  monthlyCostMax: number;
  pricingLink: string;
}
```

### IAMTooltip Component

Contextual help tooltips for IAM-related fields.

```typescript
interface IAMTooltipProps {
  field: 'roleArn' | 'region' | 'externalId' | 'accountId';
  children: React.ReactNode;
}

interface TooltipContent {
  title: string;
  description: string;
  example?: string;
  learnMoreLink?: string;
}
```

### Policy Generator Utility

Generates minimal IAM policies for missing permissions.

```typescript
interface PolicyGeneratorInput {
  missingPermissions: MissingPermission[];
  resourcePatterns?: ResourcePattern[];
}

interface MissingPermission {
  service: string;
  action: string;
  resource?: string;
}

interface GeneratedPolicy {
  Version: string;
  Statement: PolicyStatement[];
}

function generateMinimalPolicy(input: PolicyGeneratorInput): GeneratedPolicy;
function formatPolicyForDownload(policy: GeneratedPolicy): string;
```

## Data Models

### Permission Data Structure

```typescript
// permission-data.ts
export const PERMISSION_CATEGORIES: PermissionCategory[] = [
  {
    name: 'Infrastructure',
    description: 'Core infrastructure management',
    services: [
      {
        service: 'CloudFormation',
        purpose: 'Manages all deployment stacks',
        keyActions: ['CreateStack', 'UpdateStack', 'DeleteStack', 'DescribeStacks'],
        allActions: [/* full list from deployment-role-policy.json */]
      },
      {
        service: 'IAM',
        purpose: 'Creates service roles for ECS tasks',
        keyActions: ['CreateRole', 'AttachRolePolicy', 'PassRole'],
        allActions: [/* full list */]
      }
    ]
  },
  {
    name: 'Frontend',
    description: 'Static hosting and CDN',
    services: [
      {
        service: 'S3',
        purpose: 'Frontend static file hosting',
        keyActions: ['CreateBucket', 'PutObject', 'PutBucketPolicy'],
        allActions: [/* full list */]
      },
      {
        service: 'CloudFront',
        purpose: 'CDN distribution',
        keyActions: ['CreateDistribution', 'CreateInvalidation'],
        allActions: [/* full list */]
      },
      {
        service: 'WAF',
        purpose: 'Web application firewall',
        keyActions: ['CreateWebACL', 'AssociateWebACL'],
        allActions: [/* full list */]
      },
      {
        service: 'ACM',
        purpose: 'SSL certificates',
        keyActions: ['RequestCertificate', 'DescribeCertificate'],
        allActions: [/* full list */]
      },
      {
        service: 'Route53',
        purpose: 'DNS management',
        keyActions: ['ChangeResourceRecordSets', 'GetChange'],
        allActions: [/* full list */]
      }
    ]
  },
  {
    name: 'Backend',
    description: 'Container orchestration and networking',
    services: [
      {
        service: 'ECS',
        purpose: 'Container orchestration',
        keyActions: ['CreateCluster', 'CreateService', 'RegisterTaskDefinition'],
        allActions: [/* full list */]
      },
      {
        service: 'ECR',
        purpose: 'Container registry',
        keyActions: ['CreateRepository', 'GetAuthorizationToken', 'PutImage'],
        allActions: [/* full list */]
      },
      {
        service: 'EC2',
        purpose: 'VPC and security groups',
        keyActions: ['CreateVpc', 'CreateSecurityGroup', 'CreateSubnet'],
        allActions: [/* full list */]
      },
      {
        service: 'ELB',
        purpose: 'Load balancing',
        keyActions: ['CreateLoadBalancer', 'CreateTargetGroup', 'CreateListener'],
        allActions: [/* full list */]
      }
    ]
  },
  {
    name: 'Data',
    description: 'Storage and secrets',
    services: [
      {
        service: 'DynamoDB',
        purpose: 'Database tables',
        keyActions: ['CreateTable', 'UpdateTable', 'DescribeTable'],
        allActions: [/* full list */]
      },
      {
        service: 'Secrets Manager',
        purpose: 'Secrets storage',
        keyActions: ['CreateSecret', 'GetSecretValue', 'PutSecretValue'],
        allActions: [/* full list */]
      },
      {
        service: 'KMS',
        purpose: 'Encryption keys',
        keyActions: ['CreateKey', 'Encrypt', 'Decrypt', 'GenerateDataKey'],
        allActions: [/* full list */]
      }
    ]
  },
  {
    name: 'Monitoring',
    description: 'Logging and metrics',
    services: [
      {
        service: 'CloudWatch Logs',
        purpose: 'Application logging',
        keyActions: ['CreateLogGroup', 'PutLogEvents', 'PutRetentionPolicy'],
        allActions: [/* full list */]
      },
      {
        service: 'CloudWatch',
        purpose: 'Metrics and alarms',
        keyActions: ['PutMetricData', 'PutMetricAlarm'],
        allActions: [/* full list */]
      },
      {
        service: 'Application Auto Scaling',
        purpose: 'ECS auto-scaling',
        keyActions: ['RegisterScalableTarget', 'PutScalingPolicy'],
        allActions: [/* full list */]
      }
    ]
  }
];
```

### Cost Data Structure

```typescript
// cost-data.ts
export const COST_ESTIMATES: Record<string, CostEstimate[]> = {
  dev: [
    {
      resource: 'NAT Gateway',
      description: 'Network address translation for private subnets',
      monthlyCostMin: 45,
      monthlyCostMax: 50,
      pricingLink: 'https://aws.amazon.com/vpc/pricing/'
    },
    {
      resource: 'Application Load Balancer',
      description: 'Load balancing for ECS services',
      monthlyCostMin: 18,
      monthlyCostMax: 25,
      pricingLink: 'https://aws.amazon.com/elasticloadbalancing/pricing/'
    },
    {
      resource: 'ECS Fargate',
      description: 'Container compute (0.5 vCPU, 1GB)',
      monthlyCostMin: 15,
      monthlyCostMax: 30,
      pricingLink: 'https://aws.amazon.com/fargate/pricing/'
    },
    {
      resource: 'CloudFront',
      description: 'CDN data transfer',
      monthlyCostMin: 5,
      monthlyCostMax: 20,
      pricingLink: 'https://aws.amazon.com/cloudfront/pricing/'
    },
    {
      resource: 'DynamoDB',
      description: 'On-demand capacity',
      monthlyCostMin: 1,
      monthlyCostMax: 10,
      pricingLink: 'https://aws.amazon.com/dynamodb/pricing/'
    }
  ],
  prod: [
    // Higher estimates for production with more capacity
  ]
};

export function calculateTotalCost(
  environment: string,
  enableNATGateway: boolean
): { min: number; max: number } {
  const estimates = COST_ESTIMATES[environment] || COST_ESTIMATES.dev;
  let min = 0, max = 0;
  
  for (const estimate of estimates) {
    if (estimate.resource === 'NAT Gateway' && !enableNATGateway) continue;
    min += estimate.monthlyCostMin;
    max += estimate.monthlyCostMax;
  }
  
  return { min, max };
}
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Service Category Data Completeness

*For any* service displayed in the IAM Permission Panel, the service object SHALL contain a non-empty service name, a non-empty purpose description, and at least one key action.

**Validates: Requirements 1.4**

### Property 2: Missing Permissions Display Integrity

*For any* set of missing permissions returned from verification, the display SHALL group all permissions by their AWS service name, and each group SHALL have an associated remediation suggestion.

**Validates: Requirements 3.2, 3.3**

### Property 3: IAM Policy Generation Validity

*For any* set of missing permissions, the generated IAM policy SHALL be valid JSON conforming to AWS IAM policy schema, with each missing action appearing exactly once in the policy statements.

**Validates: Requirements 3.5**

### Property 4: Environment-Specific Cost Estimation

*For any* two different environment selections (dev vs prod), the cost estimation SHALL return different total cost ranges, with production estimates being greater than or equal to development estimates.

**Validates: Requirements 5.3**

### Property 5: Validation Script Comprehensive Output

*For any* set of permissions checked by the validation script, the script output SHALL list each permission with its status (granted/denied), and for denied permissions, SHALL include the specific action name.

**Validates: Requirements 6.2, 6.3**

### Property 6: Error Type Contextual Help Coverage

*For any* error type that can occur during permission verification, there SHALL exist a corresponding contextual help entry with a non-empty description and at least one remediation step.

**Validates: Requirements 7.5**

## Error Handling

### Permission Verification Errors

| Error Type | User Message | Remediation |
|------------|--------------|-------------|
| `AccessDenied` | "Unable to assume the specified role" | Check trust policy, verify external ID |
| `InvalidRoleArn` | "The role ARN format is invalid" | Show correct ARN format example |
| `ExpiredCredentials` | "AWS session has expired" | Re-authenticate and try again |
| `InsufficientPermissions` | "Role lacks required permissions" | Show missing permissions, offer policy download |
| `CrossAccountTrustFailure` | "Cross-account trust not configured" | Show trust policy setup guide |
| `NetworkError` | "Unable to connect to AWS" | Check network connectivity |

### Error Response Structure

```typescript
interface PermissionError {
  type: ErrorType;
  message: string;
  details?: string;
  remediation: RemediationStep[];
  missingPermissions?: MissingPermission[];
}

interface RemediationStep {
  step: number;
  instruction: string;
  command?: string;
  link?: string;
}
```

## Testing Strategy

### Unit Tests

Unit tests will verify specific component behaviors and edge cases:

1. **IAMPermissionPanel Tests**
   - Panel expands/collapses on toggle
   - All permission categories render correctly
   - Download link generates valid policy file

2. **IAMSetupGuideModal Tests**
   - Modal opens/closes correctly
   - All three setup methods display correct content
   - Trust policy template includes correct placeholders
   - External ID is properly escaped in templates

3. **CostEstimationPanel Tests**
   - Cost calculations are correct for each environment
   - NAT Gateway toggle affects total cost
   - All pricing links are valid URLs

4. **Policy Generator Tests**
   - Generated policy is valid JSON
   - All missing permissions appear in output
   - Resource patterns are correctly applied

### Property-Based Tests

Property-based tests will verify universal properties across many generated inputs using fast-check:

1. **Property 1 Test**: Generate random service data and verify completeness invariants
2. **Property 2 Test**: Generate random missing permission sets and verify grouping
3. **Property 3 Test**: Generate random permission lists and verify policy validity
4. **Property 4 Test**: Generate environment pairs and verify cost ordering
5. **Property 5 Test**: Generate permission check results and verify output format
6. **Property 6 Test**: Generate error scenarios and verify help coverage

### Integration Tests

1. **AWS Configuration Flow**
   - Complete flow from role ARN entry to verification
   - Cross-account detection and guidance display
   - Error handling and recovery

2. **Permission Verification Flow**
   - Full verification with mock AWS responses
   - Missing permission display and policy generation
   - Validation script download

### Test Configuration

- Property-based tests: minimum 100 iterations per property
- Test framework: Vitest with fast-check for property testing
- Each property test tagged with: `Feature: iam-permission-documentation, Property N: {property_text}`

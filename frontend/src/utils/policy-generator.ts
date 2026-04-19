/**
 * IAM Policy Generator Utility
 * Generates minimal IAM policies for missing permissions
 */

export interface MissingPermission {
  service: string;
  action: string;
  resource?: string;
}

export interface PolicyStatement {
  Sid?: string;
  Effect: 'Allow' | 'Deny';
  Action: string | string[];
  Resource: string | string[];
}

export interface GeneratedPolicy {
  Version: string;
  Statement: PolicyStatement[];
}

export interface PolicyGeneratorInput {
  missingPermissions: MissingPermission[];
  resourcePatterns?: Record<string, string>;
}

/**
 * Map service names to their AWS service prefixes
 */
const SERVICE_PREFIX_MAP: Record<string, string> = {
  'CloudFormation': 'cloudformation',
  'S3': 's3',
  'CloudFront': 'cloudfront',
  'WAF': 'wafv2',
  'ACM': 'acm',
  'Route53': 'route53',
  'ECS': 'ecs',
  'ECR': 'ecr',
  'EC2': 'ec2',
  'ELB': 'elasticloadbalancing',
  'IAM': 'iam',
  'DynamoDB': 'dynamodb',
  'Secrets Manager': 'secretsmanager',
  'KMS': 'kms',
  'CloudWatch Logs': 'logs',
  'CloudWatch': 'cloudwatch',
  'Application Auto Scaling': 'application-autoscaling',
  'SSM Parameter Store': 'ssm',
  'EventBridge': 'events',
  'X-Ray': 'xray',
  'STS': 'sts'
};

/**
 * Get the AWS service prefix for a service name
 */
function getServicePrefix(serviceName: string): string {
  return SERVICE_PREFIX_MAP[serviceName] || serviceName.toLowerCase().replace(/\s+/g, '');
}

/**
 * Group missing permissions by service
 */
function groupPermissionsByService(permissions: MissingPermission[]): Map<string, string[]> {
  const grouped = new Map<string, string[]>();
  
  for (const perm of permissions) {
    const prefix = getServicePrefix(perm.service);
    const action = perm.action.includes(':') ? perm.action : `${prefix}:${perm.action}`;
    
    if (!grouped.has(perm.service)) {
      grouped.set(perm.service, []);
    }
    grouped.get(perm.service)!.push(action);
  }
  
  return grouped;
}

/**
 * Generate a minimal IAM policy for missing permissions
 */
export function generateMinimalPolicy(input: PolicyGeneratorInput): GeneratedPolicy {
  const { missingPermissions, resourcePatterns = {} } = input;
  
  if (missingPermissions.length === 0) {
    return {
      Version: '2012-10-17',
      Statement: []
    };
  }
  
  const groupedPermissions = groupPermissionsByService(missingPermissions);
  const statements: PolicyStatement[] = [];
  
  let statementIndex = 1;
  for (const [service, actions] of groupedPermissions) {
    // Deduplicate actions
    const uniqueActions = [...new Set(actions)];
    
    // Determine resource pattern
    const prefix = getServicePrefix(service);
    let resource: string | string[] = resourcePatterns[service] || '*';
    
    // Use more specific resource patterns for certain services
    if (prefix === 's3' && resource === '*') {
      resource = ['arn:aws:s3:::*', 'arn:aws:s3:::*/*'];
    } else if (prefix === 'cloudformation' && resource === '*') {
      resource = 'arn:aws:cloudformation:*:*:stack/*/*';
    }
    
    const statement: PolicyStatement = {
      Sid: `${service.replace(/\s+/g, '')}Permissions${statementIndex}`,
      Effect: 'Allow',
      Action: uniqueActions.length === 1 ? uniqueActions[0] : uniqueActions,
      Resource: resource
    };
    
    statements.push(statement);
    statementIndex++;
  }
  
  return {
    Version: '2012-10-17',
    Statement: statements
  };
}

/**
 * Format a policy for download as JSON
 */
export function formatPolicyForDownload(policy: GeneratedPolicy): string {
  return JSON.stringify(policy, null, 2);
}

/**
 * Validate that a policy conforms to AWS IAM policy schema
 */
export function validatePolicy(policy: GeneratedPolicy): { valid: boolean; errors: string[] } {
  const errors: string[] = [];
  
  // Check Version
  if (!policy.Version) {
    errors.push('Policy must have a Version field');
  } else if (policy.Version !== '2012-10-17' && policy.Version !== '2008-10-17') {
    errors.push('Policy Version must be "2012-10-17" or "2008-10-17"');
  }
  
  // Check Statement
  if (!policy.Statement) {
    errors.push('Policy must have a Statement field');
  } else if (!Array.isArray(policy.Statement)) {
    errors.push('Statement must be an array');
  } else {
    for (let i = 0; i < policy.Statement.length; i++) {
      const stmt = policy.Statement[i];
      
      if (!stmt.Effect) {
        errors.push(`Statement ${i + 1}: Missing Effect field`);
      } else if (stmt.Effect !== 'Allow' && stmt.Effect !== 'Deny') {
        errors.push(`Statement ${i + 1}: Effect must be "Allow" or "Deny"`);
      }
      
      if (!stmt.Action) {
        errors.push(`Statement ${i + 1}: Missing Action field`);
      } else {
        const actions = Array.isArray(stmt.Action) ? stmt.Action : [stmt.Action];
        for (const action of actions) {
          if (typeof action !== 'string') {
            errors.push(`Statement ${i + 1}: Action must be a string or array of strings`);
          } else if (!action.includes(':') && action !== '*') {
            errors.push(`Statement ${i + 1}: Action "${action}" must be in format "service:action"`);
          }
        }
      }
      
      if (!stmt.Resource) {
        errors.push(`Statement ${i + 1}: Missing Resource field`);
      }
    }
  }
  
  return {
    valid: errors.length === 0,
    errors
  };
}

/**
 * Generate the full deployment role policy
 */
export function generateFullDeploymentPolicy(): GeneratedPolicy {
  return {
    Version: '2012-10-17',
    Statement: [
      {
        Sid: 'CloudFormationStackOperations',
        Effect: 'Allow',
        Action: [
          'cloudformation:CreateStack',
          'cloudformation:UpdateStack',
          'cloudformation:DeleteStack',
          'cloudformation:DescribeStacks',
          'cloudformation:DescribeStackEvents',
          'cloudformation:DescribeStackResources',
          'cloudformation:GetTemplate',
          'cloudformation:ValidateTemplate',
          'cloudformation:CreateChangeSet',
          'cloudformation:ExecuteChangeSet',
          'cloudformation:DeleteChangeSet',
          'cloudformation:DescribeChangeSet',
          'cloudformation:ListStacks',
          'cloudformation:ListStackResources',
          'cloudformation:GetStackPolicy',
          'cloudformation:SetStackPolicy',
          'cloudformation:CancelUpdateStack',
          'cloudformation:ContinueUpdateRollback'
        ],
        Resource: 'arn:aws:cloudformation:*:*:stack/*/*'
      },
      {
        Sid: 'S3Operations',
        Effect: 'Allow',
        Action: [
          's3:CreateBucket',
          's3:DeleteBucket',
          's3:GetBucketLocation',
          's3:GetBucketPolicy',
          's3:PutBucketPolicy',
          's3:DeleteBucketPolicy',
          's3:GetBucketAcl',
          's3:PutBucketAcl',
          's3:GetBucketVersioning',
          's3:PutBucketVersioning',
          's3:GetBucketEncryption',
          's3:PutBucketEncryption',
          's3:GetBucketPublicAccessBlock',
          's3:PutBucketPublicAccessBlock',
          's3:GetBucketLifecycleConfiguration',
          's3:PutBucketLifecycleConfiguration',
          's3:GetBucketCORS',
          's3:PutBucketCORS',
          's3:GetBucketLogging',
          's3:PutBucketLogging',
          's3:GetBucketTagging',
          's3:PutBucketTagging',
          's3:ListBucket',
          's3:ListBucketVersions',
          's3:GetObject',
          's3:PutObject',
          's3:DeleteObject',
          's3:GetObjectVersion',
          's3:GetObjectAcl',
          's3:PutObjectAcl',
          's3:HeadObject',
          's3:CopyObject'
        ],
        Resource: ['arn:aws:s3:::*', 'arn:aws:s3:::*/*']
      },
      {
        Sid: 'CloudFrontOperations',
        Effect: 'Allow',
        Action: [
          'cloudfront:CreateDistribution',
          'cloudfront:UpdateDistribution',
          'cloudfront:DeleteDistribution',
          'cloudfront:GetDistribution',
          'cloudfront:GetDistributionConfig',
          'cloudfront:ListDistributions',
          'cloudfront:CreateInvalidation',
          'cloudfront:GetInvalidation',
          'cloudfront:ListInvalidations',
          'cloudfront:CreateCloudFrontOriginAccessIdentity',
          'cloudfront:GetCloudFrontOriginAccessIdentity',
          'cloudfront:DeleteCloudFrontOriginAccessIdentity',
          'cloudfront:TagResource',
          'cloudfront:UntagResource',
          'cloudfront:ListTagsForResource'
        ],
        Resource: '*'
      },
      {
        Sid: 'ECSOperations',
        Effect: 'Allow',
        Action: [
          'ecs:CreateCluster',
          'ecs:UpdateCluster',
          'ecs:DeleteCluster',
          'ecs:DescribeClusters',
          'ecs:ListClusters',
          'ecs:RegisterTaskDefinition',
          'ecs:DeregisterTaskDefinition',
          'ecs:DescribeTaskDefinition',
          'ecs:ListTaskDefinitions',
          'ecs:CreateService',
          'ecs:UpdateService',
          'ecs:DeleteService',
          'ecs:DescribeServices',
          'ecs:ListServices',
          'ecs:RunTask',
          'ecs:StopTask',
          'ecs:DescribeTasks',
          'ecs:ListTasks',
          'ecs:TagResource',
          'ecs:UntagResource'
        ],
        Resource: '*'
      },
      {
        Sid: 'EC2NetworkingOperations',
        Effect: 'Allow',
        Action: [
          'ec2:CreateVpc',
          'ec2:DeleteVpc',
          'ec2:DescribeVpcs',
          'ec2:ModifyVpcAttribute',
          'ec2:CreateSubnet',
          'ec2:DeleteSubnet',
          'ec2:DescribeSubnets',
          'ec2:CreateInternetGateway',
          'ec2:DeleteInternetGateway',
          'ec2:AttachInternetGateway',
          'ec2:DetachInternetGateway',
          'ec2:CreateNatGateway',
          'ec2:DeleteNatGateway',
          'ec2:DescribeNatGateways',
          'ec2:AllocateAddress',
          'ec2:ReleaseAddress',
          'ec2:CreateRouteTable',
          'ec2:DeleteRouteTable',
          'ec2:CreateRoute',
          'ec2:DeleteRoute',
          'ec2:AssociateRouteTable',
          'ec2:CreateSecurityGroup',
          'ec2:DeleteSecurityGroup',
          'ec2:DescribeSecurityGroups',
          'ec2:AuthorizeSecurityGroupIngress',
          'ec2:AuthorizeSecurityGroupEgress',
          'ec2:RevokeSecurityGroupIngress',
          'ec2:RevokeSecurityGroupEgress',
          'ec2:CreateTags',
          'ec2:DeleteTags',
          'ec2:DescribeAvailabilityZones'
        ],
        Resource: '*'
      },
      {
        Sid: 'IAMOperations',
        Effect: 'Allow',
        Action: [
          'iam:CreateRole',
          'iam:DeleteRole',
          'iam:GetRole',
          'iam:AttachRolePolicy',
          'iam:DetachRolePolicy',
          'iam:PutRolePolicy',
          'iam:DeleteRolePolicy',
          'iam:PassRole',
          'iam:CreateServiceLinkedRole'
        ],
        Resource: '*'
      },
      {
        Sid: 'OtherServices',
        Effect: 'Allow',
        Action: [
          'elasticloadbalancing:*',
          'ecr:*',
          'dynamodb:*',
          'secretsmanager:*',
          'kms:*',
          'logs:*',
          'cloudwatch:*',
          'application-autoscaling:*',
          'wafv2:*',
          'acm:*',
          'route53:*',
          'ssm:*',
          'events:*',
          'xray:*'
        ],
        Resource: '*'
      },
      {
        Sid: 'STSOperations',
        Effect: 'Allow',
        Action: [
          'sts:GetCallerIdentity',
          'sts:AssumeRole'
        ],
        Resource: '*'
      }
    ]
  };
}

/**
 * Create a downloadable blob URL for a policy
 */
export function createPolicyDownloadUrl(policy: GeneratedPolicy): string {
  const json = formatPolicyForDownload(policy);
  const blob = new Blob([json], { type: 'application/json' });
  return URL.createObjectURL(blob);
}

/**
 * Trigger download of a policy file
 */
export function downloadPolicy(policy: GeneratedPolicy, filename: string = 'iam-policy.json'): void {
  const url = createPolicyDownloadUrl(policy);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

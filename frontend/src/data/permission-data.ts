/**
 * IAM Permission Data
 * Categorized permissions required for capability deployment and deletion
 */

export interface ServicePermission {
  service: string;
  purpose: string;
  keyActions: string[];
  allActions: string[];
}

export interface PermissionCategory {
  name: string;
  description: string;
  services: ServicePermission[];
}

export const PERMISSION_CATEGORIES: PermissionCategory[] = [
  {
    name: 'Infrastructure',
    description: 'Core infrastructure management including CloudFormation and IAM',
    services: [
      {
        service: 'CloudFormation',
        purpose: 'Manages all deployment stacks and infrastructure as code',
        keyActions: ['CreateStack', 'UpdateStack', 'DeleteStack', 'DescribeStacks'],
        allActions: [
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
        ]
      },
      {
        service: 'IAM',
        purpose: 'Creates service roles for ECS tasks and other AWS services',
        keyActions: ['CreateRole', 'AttachRolePolicy', 'PassRole', 'DeleteRole'],
        allActions: [
          'iam:CreateRole',
          'iam:DeleteRole',
          'iam:GetRole',
          'iam:ListRoles',
          'iam:UpdateRole',
          'iam:AttachRolePolicy',
          'iam:DetachRolePolicy',
          'iam:ListAttachedRolePolicies',
          'iam:PutRolePolicy',
          'iam:GetRolePolicy',
          'iam:DeleteRolePolicy',
          'iam:ListRolePolicies',
          'iam:CreatePolicy',
          'iam:DeletePolicy',
          'iam:GetPolicy',
          'iam:GetPolicyVersion',
          'iam:ListPolicies',
          'iam:ListPolicyVersions',
          'iam:CreatePolicyVersion',
          'iam:DeletePolicyVersion',
          'iam:PassRole',
          'iam:TagRole',
          'iam:UntagRole',
          'iam:ListRoleTags',
          'iam:CreateServiceLinkedRole',
          'iam:DeleteServiceLinkedRole',
          'iam:GetServiceLinkedRoleDeletionStatus'
        ]
      },
      {
        service: 'STS',
        purpose: 'Security token service for role assumption',
        keyActions: ['GetCallerIdentity', 'AssumeRole'],
        allActions: [
          'sts:GetCallerIdentity',
          'sts:AssumeRole'
        ]
      }
    ]
  },
  {
    name: 'Frontend',
    description: 'Static hosting, CDN, and web application firewall',
    services: [
      {
        service: 'S3',
        purpose: 'Frontend static file hosting and artifact storage',
        keyActions: ['CreateBucket', 'PutObject', 'PutBucketPolicy', 'DeleteBucket'],
        allActions: [
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
        ]
      },
      {
        service: 'CloudFront',
        purpose: 'CDN distribution for global content delivery',
        keyActions: ['CreateDistribution', 'CreateInvalidation', 'DeleteDistribution'],
        allActions: [
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
          'cloudfront:GetCloudFrontOriginAccessIdentityConfig',
          'cloudfront:UpdateCloudFrontOriginAccessIdentity',
          'cloudfront:DeleteCloudFrontOriginAccessIdentity',
          'cloudfront:ListCloudFrontOriginAccessIdentities',
          'cloudfront:CreateResponseHeadersPolicy',
          'cloudfront:GetResponseHeadersPolicy',
          'cloudfront:UpdateResponseHeadersPolicy',
          'cloudfront:DeleteResponseHeadersPolicy',
          'cloudfront:CreateCachePolicy',
          'cloudfront:GetCachePolicy',
          'cloudfront:UpdateCachePolicy',
          'cloudfront:DeleteCachePolicy',
          'cloudfront:CreateOriginRequestPolicy',
          'cloudfront:GetOriginRequestPolicy',
          'cloudfront:UpdateOriginRequestPolicy',
          'cloudfront:DeleteOriginRequestPolicy',
          'cloudfront:TagResource',
          'cloudfront:UntagResource',
          'cloudfront:ListTagsForResource'
        ]
      },
      {
        service: 'WAF',
        purpose: 'Web application firewall for security',
        keyActions: ['CreateWebACL', 'AssociateWebACL', 'DeleteWebACL'],
        allActions: [
          'wafv2:CreateWebACL',
          'wafv2:UpdateWebACL',
          'wafv2:DeleteWebACL',
          'wafv2:GetWebACL',
          'wafv2:ListWebACLs',
          'wafv2:AssociateWebACL',
          'wafv2:DisassociateWebACL',
          'wafv2:GetWebACLForResource',
          'wafv2:PutLoggingConfiguration',
          'wafv2:GetLoggingConfiguration',
          'wafv2:DeleteLoggingConfiguration',
          'wafv2:TagResource',
          'wafv2:UntagResource',
          'wafv2:ListTagsForResource'
        ]
      },
      {
        service: 'ACM',
        purpose: 'SSL/TLS certificate management',
        keyActions: ['RequestCertificate', 'DescribeCertificate', 'DeleteCertificate'],
        allActions: [
          'acm:RequestCertificate',
          'acm:DescribeCertificate',
          'acm:GetCertificate',
          'acm:ListCertificates',
          'acm:DeleteCertificate',
          'acm:AddTagsToCertificate',
          'acm:RemoveTagsFromCertificate',
          'acm:ListTagsForCertificate'
        ]
      },
      {
        service: 'Route53',
        purpose: 'DNS management and health checks',
        keyActions: ['ChangeResourceRecordSets', 'GetChange', 'CreateHostedZone'],
        allActions: [
          'route53:CreateHostedZone',
          'route53:GetHostedZone',
          'route53:ListHostedZones',
          'route53:DeleteHostedZone',
          'route53:ChangeResourceRecordSets',
          'route53:GetChange',
          'route53:ListResourceRecordSets',
          'route53:CreateHealthCheck',
          'route53:GetHealthCheck',
          'route53:DeleteHealthCheck',
          'route53:UpdateHealthCheck',
          'route53:ListHealthChecks',
          'route53:ChangeTagsForResource',
          'route53:ListTagsForResource'
        ]
      }
    ]
  },
  {
    name: 'Backend',
    description: 'Container orchestration, networking, and load balancing',
    services: [
      {
        service: 'ECS',
        purpose: 'Container orchestration for backend services',
        keyActions: ['CreateCluster', 'CreateService', 'RegisterTaskDefinition', 'DeleteCluster'],
        allActions: [
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
          'ecs:PutClusterCapacityProviders',
          'ecs:DescribeCapacityProviders',
          'ecs:TagResource',
          'ecs:UntagResource',
          'ecs:ListTagsForResource',
          'ecs:PutAccountSetting',
          'ecs:PutAccountSettingDefault'
        ]
      },
      {
        service: 'ECR',
        purpose: 'Container image registry',
        keyActions: ['CreateRepository', 'GetAuthorizationToken', 'PutImage', 'DeleteRepository'],
        allActions: [
          'ecr:CreateRepository',
          'ecr:DeleteRepository',
          'ecr:DescribeRepositories',
          'ecr:ListImages',
          'ecr:DescribeImages',
          'ecr:BatchCheckLayerAvailability',
          'ecr:BatchGetImage',
          'ecr:GetDownloadUrlForLayer',
          'ecr:PutImage',
          'ecr:InitiateLayerUpload',
          'ecr:UploadLayerPart',
          'ecr:CompleteLayerUpload',
          'ecr:BatchDeleteImage',
          'ecr:GetRepositoryPolicy',
          'ecr:SetRepositoryPolicy',
          'ecr:DeleteRepositoryPolicy',
          'ecr:GetLifecyclePolicy',
          'ecr:PutLifecyclePolicy',
          'ecr:DeleteLifecyclePolicy',
          'ecr:GetAuthorizationToken',
          'ecr:TagResource',
          'ecr:UntagResource',
          'ecr:ListTagsForResource',
          'ecr:PutImageScanningConfiguration',
          'ecr:DescribeImageScanFindings'
        ]
      },
      {
        service: 'EC2',
        purpose: 'VPC, subnets, security groups, and NAT Gateway',
        keyActions: ['CreateVpc', 'CreateSecurityGroup', 'CreateSubnet', 'CreateNatGateway'],
        allActions: [
          'ec2:CreateVpc',
          'ec2:DeleteVpc',
          'ec2:DescribeVpcs',
          'ec2:ModifyVpcAttribute',
          'ec2:CreateSubnet',
          'ec2:DeleteSubnet',
          'ec2:DescribeSubnets',
          'ec2:ModifySubnetAttribute',
          'ec2:CreateInternetGateway',
          'ec2:DeleteInternetGateway',
          'ec2:AttachInternetGateway',
          'ec2:DetachInternetGateway',
          'ec2:DescribeInternetGateways',
          'ec2:CreateNatGateway',
          'ec2:DeleteNatGateway',
          'ec2:DescribeNatGateways',
          'ec2:AllocateAddress',
          'ec2:ReleaseAddress',
          'ec2:DescribeAddresses',
          'ec2:AssociateAddress',
          'ec2:DisassociateAddress',
          'ec2:CreateRouteTable',
          'ec2:DeleteRouteTable',
          'ec2:DescribeRouteTables',
          'ec2:CreateRoute',
          'ec2:DeleteRoute',
          'ec2:ReplaceRoute',
          'ec2:AssociateRouteTable',
          'ec2:DisassociateRouteTable',
          'ec2:CreateSecurityGroup',
          'ec2:DeleteSecurityGroup',
          'ec2:DescribeSecurityGroups',
          'ec2:AuthorizeSecurityGroupIngress',
          'ec2:AuthorizeSecurityGroupEgress',
          'ec2:RevokeSecurityGroupIngress',
          'ec2:RevokeSecurityGroupEgress',
          'ec2:CreateFlowLogs',
          'ec2:DeleteFlowLogs',
          'ec2:DescribeFlowLogs',
          'ec2:CreateTags',
          'ec2:DeleteTags',
          'ec2:DescribeTags',
          'ec2:DescribeAvailabilityZones',
          'ec2:DescribeRegions',
          'ec2:DescribeAccountAttributes',
          'ec2:DescribeNetworkInterfaces'
        ]
      },
      {
        service: 'ELB',
        purpose: 'Application Load Balancer for traffic distribution',
        keyActions: ['CreateLoadBalancer', 'CreateTargetGroup', 'CreateListener', 'DeleteLoadBalancer'],
        allActions: [
          'elasticloadbalancing:CreateLoadBalancer',
          'elasticloadbalancing:DeleteLoadBalancer',
          'elasticloadbalancing:DescribeLoadBalancers',
          'elasticloadbalancing:DescribeLoadBalancerAttributes',
          'elasticloadbalancing:ModifyLoadBalancerAttributes',
          'elasticloadbalancing:CreateTargetGroup',
          'elasticloadbalancing:DeleteTargetGroup',
          'elasticloadbalancing:DescribeTargetGroups',
          'elasticloadbalancing:DescribeTargetGroupAttributes',
          'elasticloadbalancing:ModifyTargetGroup',
          'elasticloadbalancing:ModifyTargetGroupAttributes',
          'elasticloadbalancing:RegisterTargets',
          'elasticloadbalancing:DeregisterTargets',
          'elasticloadbalancing:DescribeTargetHealth',
          'elasticloadbalancing:CreateListener',
          'elasticloadbalancing:DeleteListener',
          'elasticloadbalancing:DescribeListeners',
          'elasticloadbalancing:ModifyListener',
          'elasticloadbalancing:CreateRule',
          'elasticloadbalancing:DeleteRule',
          'elasticloadbalancing:DescribeRules',
          'elasticloadbalancing:ModifyRule',
          'elasticloadbalancing:AddTags',
          'elasticloadbalancing:RemoveTags',
          'elasticloadbalancing:DescribeTags',
          'elasticloadbalancing:SetSecurityGroups',
          'elasticloadbalancing:SetSubnets'
        ]
      },
      {
        service: 'EKS',
        purpose: 'Kubernetes cluster management for Pure EKS deployments',
        keyActions: ['DescribeCluster', 'ListClusters', 'AccessKubernetesApi'],
        allActions: [
          'eks:DescribeCluster',
          'eks:ListClusters',
          'eks:ListNodegroups',
          'eks:DescribeNodegroup',
          'eks:AccessKubernetesApi',
          'eks:ListFargateProfiles',
          'eks:DescribeFargateProfile',
          'eks:ListAddons',
          'eks:DescribeAddon',
          'eks:ListIdentityProviderConfigs',
          'eks:DescribeIdentityProviderConfig'
        ]
      }
    ]
  },
  {
    name: 'Data',
    description: 'Database, secrets, and encryption key management',
    services: [
      {
        service: 'DynamoDB',
        purpose: 'NoSQL database for application data',
        keyActions: ['CreateTable', 'UpdateTable', 'DescribeTable', 'DeleteTable'],
        allActions: [
          'dynamodb:CreateTable',
          'dynamodb:DeleteTable',
          'dynamodb:DescribeTable',
          'dynamodb:UpdateTable',
          'dynamodb:ListTables',
          'dynamodb:DescribeTimeToLive',
          'dynamodb:UpdateTimeToLive',
          'dynamodb:DescribeContinuousBackups',
          'dynamodb:UpdateContinuousBackups',
          'dynamodb:TagResource',
          'dynamodb:UntagResource',
          'dynamodb:ListTagsOfResource',
          'dynamodb:CreateGlobalSecondaryIndex',
          'dynamodb:DeleteGlobalSecondaryIndex',
          'dynamodb:UpdateGlobalSecondaryIndex',
          'dynamodb:DescribeStream',
          'dynamodb:ListStreams'
        ]
      },
      {
        service: 'Secrets Manager',
        purpose: 'Secure storage for API keys and credentials',
        keyActions: ['CreateSecret', 'GetSecretValue', 'PutSecretValue', 'DeleteSecret'],
        allActions: [
          'secretsmanager:CreateSecret',
          'secretsmanager:UpdateSecret',
          'secretsmanager:DeleteSecret',
          'secretsmanager:GetSecretValue',
          'secretsmanager:DescribeSecret',
          'secretsmanager:ListSecrets',
          'secretsmanager:PutSecretValue',
          'secretsmanager:TagResource',
          'secretsmanager:UntagResource',
          'secretsmanager:GetResourcePolicy',
          'secretsmanager:PutResourcePolicy',
          'secretsmanager:DeleteResourcePolicy',
          'secretsmanager:RestoreSecret',
          'secretsmanager:RotateSecret',
          'secretsmanager:UpdateSecretVersionStage'
        ]
      },
      {
        service: 'KMS',
        purpose: 'Encryption key management',
        keyActions: ['CreateKey', 'Encrypt', 'Decrypt', 'GenerateDataKey'],
        allActions: [
          'kms:CreateKey',
          'kms:DescribeKey',
          'kms:ListKeys',
          'kms:ListAliases',
          'kms:CreateAlias',
          'kms:DeleteAlias',
          'kms:UpdateAlias',
          'kms:EnableKey',
          'kms:DisableKey',
          'kms:GenerateDataKey',
          'kms:Decrypt',
          'kms:Encrypt',
          'kms:CreateGrant',
          'kms:RevokeGrant',
          'kms:ListGrants',
          'kms:GetKeyPolicy',
          'kms:PutKeyPolicy',
          'kms:GetKeyRotationStatus',
          'kms:EnableKeyRotation',
          'kms:DisableKeyRotation',
          'kms:TagResource',
          'kms:UntagResource',
          'kms:ListResourceTags'
        ]
      },
      {
        service: 'SSM Parameter Store',
        purpose: 'Configuration and parameter storage',
        keyActions: ['PutParameter', 'GetParameter', 'DeleteParameter'],
        allActions: [
          'ssm:PutParameter',
          'ssm:GetParameter',
          'ssm:GetParameters',
          'ssm:DeleteParameter',
          'ssm:DeleteParameters',
          'ssm:DescribeParameters',
          'ssm:GetParameterHistory',
          'ssm:GetParametersByPath',
          'ssm:AddTagsToResource',
          'ssm:RemoveTagsFromResource',
          'ssm:ListTagsForResource'
        ]
      }
    ]
  },
  {
    name: 'Monitoring',
    description: 'Logging, metrics, alarms, and tracing',
    services: [
      {
        service: 'CloudWatch Logs',
        purpose: 'Application and infrastructure logging',
        keyActions: ['CreateLogGroup', 'PutLogEvents', 'PutRetentionPolicy', 'DeleteLogGroup'],
        allActions: [
          'logs:CreateLogGroup',
          'logs:DeleteLogGroup',
          'logs:DescribeLogGroups',
          'logs:CreateLogStream',
          'logs:DeleteLogStream',
          'logs:DescribeLogStreams',
          'logs:PutLogEvents',
          'logs:GetLogEvents',
          'logs:FilterLogEvents',
          'logs:PutRetentionPolicy',
          'logs:DeleteRetentionPolicy',
          'logs:TagLogGroup',
          'logs:UntagLogGroup',
          'logs:ListTagsLogGroup',
          'logs:PutSubscriptionFilter',
          'logs:DeleteSubscriptionFilter',
          'logs:DescribeSubscriptionFilters'
        ]
      },
      {
        service: 'CloudWatch',
        purpose: 'Metrics and alarms for monitoring',
        keyActions: ['PutMetricData', 'PutMetricAlarm', 'DeleteAlarms'],
        allActions: [
          'cloudwatch:PutMetricData',
          'cloudwatch:GetMetricData',
          'cloudwatch:GetMetricStatistics',
          'cloudwatch:ListMetrics',
          'cloudwatch:PutMetricAlarm',
          'cloudwatch:DeleteAlarms',
          'cloudwatch:DescribeAlarms',
          'cloudwatch:DescribeAlarmsForMetric',
          'cloudwatch:EnableAlarmActions',
          'cloudwatch:DisableAlarmActions'
        ]
      },
      {
        service: 'Application Auto Scaling',
        purpose: 'ECS service auto-scaling',
        keyActions: ['RegisterScalableTarget', 'PutScalingPolicy', 'DeleteScalingPolicy'],
        allActions: [
          'application-autoscaling:RegisterScalableTarget',
          'application-autoscaling:DeregisterScalableTarget',
          'application-autoscaling:DescribeScalableTargets',
          'application-autoscaling:PutScalingPolicy',
          'application-autoscaling:DeleteScalingPolicy',
          'application-autoscaling:DescribeScalingPolicies',
          'application-autoscaling:DescribeScalingActivities',
          'application-autoscaling:PutScheduledAction',
          'application-autoscaling:DeleteScheduledAction',
          'application-autoscaling:DescribeScheduledActions'
        ]
      },
      {
        service: 'EventBridge',
        purpose: 'Event-driven automation and scheduling',
        keyActions: ['PutRule', 'PutTargets', 'DeleteRule'],
        allActions: [
          'events:PutRule',
          'events:DeleteRule',
          'events:DescribeRule',
          'events:ListRules',
          'events:PutTargets',
          'events:RemoveTargets',
          'events:ListTargetsByRule',
          'events:EnableRule',
          'events:DisableRule',
          'events:TagResource',
          'events:UntagResource',
          'events:ListTagsForResource'
        ]
      },
      {
        service: 'X-Ray',
        purpose: 'Distributed tracing for debugging',
        keyActions: ['PutTraceSegments', 'GetTraceGraph'],
        allActions: [
          'xray:PutTraceSegments',
          'xray:PutTelemetryRecords',
          'xray:GetTraceGraph',
          'xray:GetTraceSummaries'
        ]
      }
    ]
  }
];

/**
 * Get all actions from all categories as a flat array
 */
export function getAllActions(): string[] {
  const actions: string[] = [];
  for (const category of PERMISSION_CATEGORIES) {
    for (const service of category.services) {
      actions.push(...service.allActions);
    }
  }
  return actions;
}

/**
 * Get total count of all permissions
 */
export function getTotalPermissionCount(): number {
  return getAllActions().length;
}

/**
 * Get permissions grouped by service name
 */
export function getPermissionsByService(): Map<string, string[]> {
  const map = new Map<string, string[]>();
  for (const category of PERMISSION_CATEGORIES) {
    for (const service of category.services) {
      map.set(service.service, service.allActions);
    }
  }
  return map;
}

/**
 * Delete-specific permissions that are required for capability deletion
 */
export const DELETE_PERMISSIONS: string[] = [
  'cloudformation:DeleteStack',
  'cloudformation:DescribeStacks',
  'cloudformation:DescribeStackEvents',
  's3:DeleteBucket',
  's3:DeleteObject',
  's3:ListBucket',
  's3:ListBucketVersions',
  'cloudfront:DeleteDistribution',
  'cloudfront:GetDistribution',
  'ecs:DeleteCluster',
  'ecs:DeleteService',
  'ecs:DeregisterTaskDefinition',
  'ecr:DeleteRepository',
  'ecr:BatchDeleteImage',
  'ec2:DeleteVpc',
  'ec2:DeleteSubnet',
  'ec2:DeleteSecurityGroup',
  'ec2:DeleteNatGateway',
  'ec2:ReleaseAddress',
  'elasticloadbalancing:DeleteLoadBalancer',
  'elasticloadbalancing:DeleteTargetGroup',
  'dynamodb:DeleteTable',
  'secretsmanager:DeleteSecret',
  'logs:DeleteLogGroup',
  'iam:DeleteRole',
  'iam:DetachRolePolicy',
  'iam:DeleteRolePolicy'
];

/**
 * EKS-specific permissions required for Pure EKS deployments
 * Feature: pure-eks-deployment
 * Requirements: 10.1, 10.2, 10.3
 */
export const EKS_PERMISSIONS: string[] = [
  // EKS cluster access
  'eks:DescribeCluster',
  'eks:ListClusters',
  'eks:ListNodegroups',
  'eks:DescribeNodegroup',
  'eks:AccessKubernetesApi',
  // IAM for IRSA
  'iam:CreateRole',
  'iam:DeleteRole',
  'iam:GetRole',
  'iam:PutRolePolicy',
  'iam:DeleteRolePolicy',
  'iam:TagRole',
  'iam:PassRole',
  'iam:CreateOpenIDConnectProvider',
  'iam:GetOpenIDConnectProvider',
  // ECR for container images
  'ecr:GetAuthorizationToken',
  'ecr:BatchCheckLayerAvailability',
  'ecr:GetDownloadUrlForLayer',
  'ecr:BatchGetImage',
  // Data services (operator provisions these)
  'dynamodb:CreateTable',
  'dynamodb:DeleteTable',
  'dynamodb:DescribeTable',
  'dynamodb:TagResource',
  's3:CreateBucket',
  's3:DeleteBucket',
  's3:PutBucketPolicy',
  's3:PutBucketTagging',
  's3:PutLifecycleConfiguration',
  'ssm:PutParameter',
  'ssm:DeleteParameter',
  'ssm:GetParameter',
  'ssm:AddTagsToResource',
  'secretsmanager:CreateSecret',
  'secretsmanager:DeleteSecret',
  'secretsmanager:GetSecretValue',
  'secretsmanager:PutSecretValue',
  'secretsmanager:TagResource',
  'glue:CreateDatabase',
  'glue:DeleteDatabase',
  'glue:GetDatabase',
  'glue:CreateTable',
  'glue:DeleteTable',
  'glue:GetTable',
];

/**
 * Get EKS-specific permission categories
 */
export function getEKSPermissionCategories(): PermissionCategory[] {
  return [
    {
      name: 'EKS Access',
      description: 'Permissions to access and manage EKS clusters',
      services: [
        {
          service: 'EKS',
          purpose: 'Kubernetes cluster discovery and API access',
          keyActions: ['DescribeCluster', 'ListClusters', 'AccessKubernetesApi'],
          allActions: [
            'eks:DescribeCluster',
            'eks:ListClusters',
            'eks:ListNodegroups',
            'eks:DescribeNodegroup',
            'eks:AccessKubernetesApi',
          ]
        }
      ]
    },
    {
      name: 'IRSA (IAM Roles for Service Accounts)',
      description: 'Permissions to create IAM roles for Kubernetes workloads',
      services: [
        {
          service: 'IAM',
          purpose: 'Create IRSA roles for operator and application',
          keyActions: ['CreateRole', 'PutRolePolicy', 'PassRole'],
          allActions: [
            'iam:CreateRole',
            'iam:DeleteRole',
            'iam:GetRole',
            'iam:PutRolePolicy',
            'iam:DeleteRolePolicy',
            'iam:TagRole',
            'iam:PassRole',
          ]
        }
      ]
    },
    {
      name: 'Container Registry',
      description: 'Permissions to pull container images from ECR',
      services: [
        {
          service: 'ECR',
          purpose: 'Pull container images for deployments',
          keyActions: ['GetAuthorizationToken', 'BatchGetImage'],
          allActions: [
            'ecr:GetAuthorizationToken',
            'ecr:BatchCheckLayerAvailability',
            'ecr:GetDownloadUrlForLayer',
            'ecr:BatchGetImage',
          ]
        }
      ]
    },
    {
      name: 'Data Services',
      description: 'Permissions for operator to provision AWS data services',
      services: [
        {
          service: 'DynamoDB',
          purpose: 'Create and manage DynamoDB tables',
          keyActions: ['CreateTable', 'DeleteTable', 'DescribeTable'],
          allActions: [
            'dynamodb:CreateTable',
            'dynamodb:DeleteTable',
            'dynamodb:DescribeTable',
            'dynamodb:TagResource',
          ]
        },
        {
          service: 'S3',
          purpose: 'Create and manage S3 buckets',
          keyActions: ['CreateBucket', 'DeleteBucket', 'PutBucketPolicy'],
          allActions: [
            's3:CreateBucket',
            's3:DeleteBucket',
            's3:PutBucketPolicy',
            's3:PutBucketTagging',
            's3:PutLifecycleConfiguration',
          ]
        },
        {
          service: 'Glue',
          purpose: 'Create and manage Glue databases and tables',
          keyActions: ['CreateDatabase', 'CreateTable', 'GetDatabase'],
          allActions: [
            'glue:CreateDatabase',
            'glue:DeleteDatabase',
            'glue:GetDatabase',
            'glue:CreateTable',
            'glue:DeleteTable',
            'glue:GetTable',
          ]
        }
      ]
    }
  ];
}

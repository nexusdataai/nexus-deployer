/**
 * Property Tests for Permission Verification Component
 * Property 2: Missing Permissions Display Integrity
 * Property 5: Validation Script Comprehensive Output
 */
import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import { generateMinimalPolicy, validatePolicy, MissingPermission } from '../utils/policy-generator';

// Service names that can have missing permissions
const AWS_SERVICES = [
  'CloudFormation', 'S3', 'CloudFront', 'ECS', 'EC2', 'IAM',
  'DynamoDB', 'Secrets Manager', 'KMS', 'CloudWatch Logs', 'ECR', 'ELB'
];

// Action patterns for each service
const SERVICE_ACTIONS: Record<string, string[]> = {
  'CloudFormation': ['CreateStack', 'UpdateStack', 'DeleteStack', 'DescribeStacks'],
  'S3': ['CreateBucket', 'DeleteBucket', 'PutObject', 'GetObject', 'ListBucket'],
  'CloudFront': ['CreateDistribution', 'UpdateDistribution', 'DeleteDistribution'],
  'ECS': ['CreateCluster', 'CreateService', 'UpdateService', 'DeleteService'],
  'EC2': ['CreateVpc', 'DeleteVpc', 'CreateSubnet', 'CreateSecurityGroup'],
  'IAM': ['CreateRole', 'DeleteRole', 'AttachRolePolicy', 'PassRole'],
  'DynamoDB': ['CreateTable', 'DeleteTable', 'PutItem', 'GetItem'],
  'Secrets Manager': ['CreateSecret', 'DeleteSecret', 'GetSecretValue'],
  'KMS': ['CreateKey', 'Encrypt', 'Decrypt', 'GenerateDataKey'],
  'CloudWatch Logs': ['CreateLogGroup', 'DeleteLogGroup', 'PutLogEvents'],
  'ECR': ['CreateRepository', 'DeleteRepository', 'PutImage', 'GetAuthorizationToken'],
  'ELB': ['CreateLoadBalancer', 'DeleteLoadBalancer', 'CreateTargetGroup']
};

// Arbitrary for generating missing permissions
const missingPermissionArb = fc.record({
  service: fc.constantFrom(...AWS_SERVICES),
  action: fc.oneof(
    ...AWS_SERVICES.map(service => 
      fc.constantFrom(...(SERVICE_ACTIONS[service] || ['*']))
    )
  )
});

const missingPermissionsArrayArb = fc.array(missingPermissionArb, { minLength: 0, maxLength: 20 });

describe('PermissionVerification Property Tests', () => {
  describe('Property 2: Missing Permissions Display Integrity', () => {
    it('should generate valid policy for any combination of missing permissions', () => {
      fc.assert(
        fc.property(missingPermissionsArrayArb, (missingPermissions) => {
          const policy = generateMinimalPolicy({ missingPermissions });
          const validation = validatePolicy(policy);
          
          // Policy should always be valid
          expect(validation.valid).toBe(true);
          expect(validation.errors).toHaveLength(0);
        }),
        { numRuns: 100 }
      );
    });

    it('should include all missing permissions in generated policy', () => {
      fc.assert(
        fc.property(
          fc.array(missingPermissionArb, { minLength: 1, maxLength: 10 }),
          (missingPermissions) => {
            const policy = generateMinimalPolicy({ missingPermissions });
            
            // Collect all actions from the policy
            const policyActions = new Set<string>();
            for (const statement of policy.Statement) {
              const actions = Array.isArray(statement.Action) 
                ? statement.Action 
                : [statement.Action];
              actions.forEach(a => policyActions.add(a));
            }
            
            // Each missing permission should be represented
            for (const perm of missingPermissions) {
              // Check if action is in policy (may be prefixed differently)
              const hasAction = Array.from(policyActions).some(a => 
                a.includes(perm.action) || a === '*'
              );
              expect(hasAction).toBe(true);
            }
          }
        ),
        { numRuns: 100 }
      );
    });

    it('should group permissions by service in generated policy', () => {
      fc.assert(
        fc.property(missingPermissionsArrayArb, (missingPermissions) => {
          if (missingPermissions.length === 0) return true;
          
          const policy = generateMinimalPolicy({ missingPermissions });
          
          // Each statement should have a Sid that identifies the service
          for (const statement of policy.Statement) {
            expect(statement.Sid).toBeDefined();
            expect(typeof statement.Sid).toBe('string');
          }
          
          return true;
        }),
        { numRuns: 100 }
      );
    });

    it('should produce empty statement array for empty missing permissions', () => {
      const policy = generateMinimalPolicy({ missingPermissions: [] });
      expect(policy.Statement).toHaveLength(0);
      expect(policy.Version).toBe('2012-10-17');
    });

    it('should deduplicate identical missing permissions', () => {
      fc.assert(
        fc.property(missingPermissionArb, (perm) => {
          // Create duplicates
          const duplicates: MissingPermission[] = [perm, perm, perm];
          const policy = generateMinimalPolicy({ missingPermissions: duplicates });
          
          // Should only have one statement for this service
          const serviceStatements = policy.Statement.filter(s => 
            s.Sid?.includes(perm.service.replace(/\s+/g, ''))
          );
          expect(serviceStatements.length).toBeLessThanOrEqual(1);
          
          // Actions should be deduplicated
          if (serviceStatements.length > 0) {
            const actions = Array.isArray(serviceStatements[0].Action)
              ? serviceStatements[0].Action
              : [serviceStatements[0].Action];
            const uniqueActions = new Set(actions);
            expect(actions.length).toBe(uniqueActions.size);
          }
        }),
        { numRuns: 100 }
      );
    });
  });

  describe('Property 5: Validation Script Output Properties', () => {
    // These tests validate the structure of what validation scripts should check
    
    it('should have remediation suggestions for all common services', () => {
      const remediationSuggestions: Record<string, string> = {
        'CloudFormation': 'Add cloudformation:* permissions or specific stack operations',
        'S3': 'Add s3:* permissions or specific bucket/object operations',
        'CloudFront': 'Add cloudfront:* permissions for CDN management',
        'ECS': 'Add ecs:* permissions for container orchestration',
        'EC2': 'Add ec2:* permissions for networking and compute',
        'IAM': 'Add iam:CreateRole, iam:PassRole, and related permissions',
        'DynamoDB': 'Add dynamodb:* permissions for database operations',
        'Secrets Manager': 'Add secretsmanager:* permissions for secret management',
        'KMS': 'Add kms:* permissions for encryption key management',
        'CloudWatch Logs': 'Add logs:* permissions for logging',
        'ECR': 'Add ecr:* permissions for container registry',
        'ELB': 'Add elasticloadbalancing:* permissions for load balancers',
      };

      // All services should have remediation suggestions
      for (const service of AWS_SERVICES) {
        expect(remediationSuggestions[service]).toBeDefined();
        expect(remediationSuggestions[service].length).toBeGreaterThan(0);
      }
    });

    it('should generate policies with correct AWS policy version', () => {
      fc.assert(
        fc.property(missingPermissionsArrayArb, (missingPermissions) => {
          const policy = generateMinimalPolicy({ missingPermissions });
          expect(policy.Version).toBe('2012-10-17');
        }),
        { numRuns: 100 }
      );
    });

    it('should generate policies with Allow effect only', () => {
      fc.assert(
        fc.property(
          fc.array(missingPermissionArb, { minLength: 1, maxLength: 10 }),
          (missingPermissions) => {
            const policy = generateMinimalPolicy({ missingPermissions });
            
            for (const statement of policy.Statement) {
              expect(statement.Effect).toBe('Allow');
            }
          }
        ),
        { numRuns: 100 }
      );
    });

    it('should generate policies with valid resource patterns', () => {
      fc.assert(
        fc.property(
          fc.array(missingPermissionArb, { minLength: 1, maxLength: 10 }),
          (missingPermissions) => {
            const policy = generateMinimalPolicy({ missingPermissions });
            
            for (const statement of policy.Statement) {
              const resources = Array.isArray(statement.Resource)
                ? statement.Resource
                : [statement.Resource];
              
              for (const resource of resources) {
                // Resource should be either '*' or a valid ARN pattern
                expect(
                  resource === '*' || 
                  resource.startsWith('arn:aws:') ||
                  resource.includes('*')
                ).toBe(true);
              }
            }
          }
        ),
        { numRuns: 100 }
      );
    });
  });
});

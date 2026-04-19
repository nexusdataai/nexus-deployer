/**
 * Property-Based Tests for IAM Policy Generator
 * Feature: iam-permission-documentation
 * 
 * These tests validate universal correctness properties across many generated inputs
 */
import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import {
  generateMinimalPolicy,
  validatePolicy,
  formatPolicyForDownload,
  MissingPermission,
  GeneratedPolicy
} from './policy-generator';

// Arbitrary generators for test data
const serviceNameArb = fc.constantFrom(
  'CloudFormation', 'S3', 'CloudFront', 'WAF', 'ACM', 'Route53',
  'ECS', 'ECR', 'EC2', 'ELB', 'IAM', 'DynamoDB', 'Secrets Manager',
  'KMS', 'CloudWatch Logs', 'CloudWatch', 'Application Auto Scaling',
  'SSM Parameter Store', 'EventBridge', 'X-Ray', 'STS'
);

const actionNameArb = fc.stringOf(
  fc.constantFrom(...'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'.split('')),
  { minLength: 3, maxLength: 30 }
);

const missingPermissionArb: fc.Arbitrary<MissingPermission> = fc.record({
  service: serviceNameArb,
  action: actionNameArb,
  resource: fc.option(fc.constant('*'), { nil: undefined })
});

const missingPermissionsArrayArb = fc.array(missingPermissionArb, { minLength: 1, maxLength: 20 });

describe('Policy Generator - Property Tests', () => {
  /**
   * Property 3: IAM Policy Generation Validity
   * For any set of missing permissions, the generated IAM policy SHALL be valid JSON
   * conforming to AWS IAM policy schema, with each missing action appearing exactly
   * once in the policy statements.
   * 
   * Validates: Requirements 3.5
   */
  describe('Property 3: IAM Policy Generation Validity', () => {
    it('generated policy is always valid JSON conforming to AWS IAM policy schema', () => {
      fc.assert(
        fc.property(missingPermissionsArrayArb, (missingPermissions) => {
          const policy = generateMinimalPolicy({ missingPermissions });
          
          // Policy must have correct version
          expect(policy.Version).toBe('2012-10-17');
          
          // Policy must have Statement array
          expect(Array.isArray(policy.Statement)).toBe(true);
          
          // Each statement must have required fields
          for (const stmt of policy.Statement) {
            expect(stmt.Effect).toBe('Allow');
            expect(stmt.Action).toBeDefined();
            expect(stmt.Resource).toBeDefined();
            
            // Actions must be strings or array of strings
            const actions = Array.isArray(stmt.Action) ? stmt.Action : [stmt.Action];
            for (const action of actions) {
              expect(typeof action).toBe('string');
              // Actions must contain colon (service:action format)
              expect(action).toContain(':');
            }
          }
          
          // Validate using our validator
          const validation = validatePolicy(policy);
          expect(validation.valid).toBe(true);
          expect(validation.errors).toHaveLength(0);
        }),
        { numRuns: 100 }
      );
    });

    it('each missing action appears exactly once in the policy statements', () => {
      fc.assert(
        fc.property(missingPermissionsArrayArb, (missingPermissions) => {
          const policy = generateMinimalPolicy({ missingPermissions });
          
          // Collect all actions from the policy
          const policyActions: string[] = [];
          for (const stmt of policy.Statement) {
            const actions = Array.isArray(stmt.Action) ? stmt.Action : [stmt.Action];
            policyActions.push(...actions);
          }
          
          // Each unique action from input should appear exactly once
          const uniqueInputActions = new Set<string>();
          for (const perm of missingPermissions) {
            const prefix = getServicePrefix(perm.service);
            const action = perm.action.includes(':') ? perm.action : `${prefix}:${perm.action}`;
            uniqueInputActions.add(action);
          }
          
          // Count occurrences of each action in policy
          const actionCounts = new Map<string, number>();
          for (const action of policyActions) {
            actionCounts.set(action, (actionCounts.get(action) || 0) + 1);
          }
          
          // Each unique action should appear exactly once
          for (const action of uniqueInputActions) {
            expect(actionCounts.get(action)).toBe(1);
          }
        }),
        { numRuns: 100 }
      );
    });

    it('generated policy can be serialized to valid JSON', () => {
      fc.assert(
        fc.property(missingPermissionsArrayArb, (missingPermissions) => {
          const policy = generateMinimalPolicy({ missingPermissions });
          const json = formatPolicyForDownload(policy);
          
          // Must be valid JSON
          expect(() => JSON.parse(json)).not.toThrow();
          
          // Parsed JSON should match original policy
          const parsed = JSON.parse(json) as GeneratedPolicy;
          expect(parsed.Version).toBe(policy.Version);
          expect(parsed.Statement.length).toBe(policy.Statement.length);
        }),
        { numRuns: 100 }
      );
    });

    it('empty permissions array generates empty statement array', () => {
      const policy = generateMinimalPolicy({ missingPermissions: [] });
      expect(policy.Version).toBe('2012-10-17');
      expect(policy.Statement).toHaveLength(0);
    });

    it('policy statements are grouped by service', () => {
      fc.assert(
        fc.property(missingPermissionsArrayArb, (missingPermissions) => {
          const policy = generateMinimalPolicy({ missingPermissions });
          
          // Get unique services from input
          const uniqueServices = new Set(missingPermissions.map(p => p.service));
          
          // Number of statements should equal number of unique services
          expect(policy.Statement.length).toBe(uniqueServices.size);
          
          // Each statement Sid should contain a service name
          for (const stmt of policy.Statement) {
            if (stmt.Sid) {
              // Sid should be non-empty
              expect(stmt.Sid.length).toBeGreaterThan(0);
            }
          }
        }),
        { numRuns: 100 }
      );
    });
  });

  describe('Policy Validation', () => {
    it('rejects policies with invalid version', () => {
      const invalidPolicy: GeneratedPolicy = {
        Version: 'invalid-version',
        Statement: []
      };
      const result = validatePolicy(invalidPolicy);
      expect(result.valid).toBe(false);
      expect(result.errors.some(e => e.includes('Version'))).toBe(true);
    });

    it('rejects policies without Statement', () => {
      const invalidPolicy = {
        Version: '2012-10-17'
      } as GeneratedPolicy;
      const result = validatePolicy(invalidPolicy);
      expect(result.valid).toBe(false);
      expect(result.errors.some(e => e.includes('Statement'))).toBe(true);
    });

    it('rejects statements without Effect', () => {
      const invalidPolicy: GeneratedPolicy = {
        Version: '2012-10-17',
        Statement: [
          { Action: 's3:GetObject', Resource: '*' } as any
        ]
      };
      const result = validatePolicy(invalidPolicy);
      expect(result.valid).toBe(false);
      expect(result.errors.some(e => e.includes('Effect'))).toBe(true);
    });

    it('rejects statements without Action', () => {
      const invalidPolicy: GeneratedPolicy = {
        Version: '2012-10-17',
        Statement: [
          { Effect: 'Allow', Resource: '*' } as any
        ]
      };
      const result = validatePolicy(invalidPolicy);
      expect(result.valid).toBe(false);
      expect(result.errors.some(e => e.includes('Action'))).toBe(true);
    });

    it('rejects actions without service prefix', () => {
      const invalidPolicy: GeneratedPolicy = {
        Version: '2012-10-17',
        Statement: [
          { Effect: 'Allow', Action: 'GetObject', Resource: '*' }
        ]
      };
      const result = validatePolicy(invalidPolicy);
      expect(result.valid).toBe(false);
      expect(result.errors.some(e => e.includes('service:action'))).toBe(true);
    });
  });
});

// Helper function to match the one in policy-generator.ts
function getServicePrefix(serviceName: string): string {
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
  return SERVICE_PREFIX_MAP[serviceName] || serviceName.toLowerCase().replace(/\s+/g, '');
}

/**
 * Property-based tests for field permissions
 * Feature: unified-environment-config, Property 5: Field Editability Consistency
 * Validates: Requirements 4.1, 4.2, 5.1-5.7
 */
import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import {
  OVERRIDABLE_FIELDS,
  READ_ONLY_FIELDS,
  isFieldOverridable,
  isFieldReadOnly,
  getFieldPermissions,
} from './fieldPermissions';
import { EnvironmentType } from './EnvironmentBox';

describe('Field Permissions - Property Tests', () => {
  /**
   * Property 5: Field Editability Consistency
   * For any configuration field, if the field path is in the overridable list,
   * the field input SHALL be enabled; if the field path is in the read-only list,
   * the field input SHALL be disabled.
   */
  it('should correctly identify overridable fields as editable', () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...OVERRIDABLE_FIELDS),
        (fieldPath) => {
          expect(isFieldOverridable(fieldPath)).toBe(true);
          expect(isFieldReadOnly(fieldPath)).toBe(false);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('should correctly identify read-only fields as non-editable', () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...READ_ONLY_FIELDS),
        (fieldPath) => {
          expect(isFieldReadOnly(fieldPath)).toBe(true);
          expect(isFieldOverridable(fieldPath)).toBe(false);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('should have no overlap between overridable and read-only fields', () => {
    const overridableSet = new Set(OVERRIDABLE_FIELDS);
    const readOnlySet = new Set(READ_ONLY_FIELDS);
    
    // Check no field is in both lists
    for (const field of OVERRIDABLE_FIELDS) {
      expect(readOnlySet.has(field)).toBe(false);
    }
    
    for (const field of READ_ONLY_FIELDS) {
      expect(overridableSet.has(field)).toBe(false);
    }
  });

  it('should return consistent permissions for all environment types', () => {
    fc.assert(
      fc.property(
        fc.constantFrom<EnvironmentType>('dev', 'test', 'stage', 'prod'),
        (envType) => {
          const permissions = getFieldPermissions(envType);
          
          // Verify structure
          expect(permissions).toHaveProperty('overridable');
          expect(permissions).toHaveProperty('readOnly');
          expect(Array.isArray(permissions.overridable)).toBe(true);
          expect(Array.isArray(permissions.readOnly)).toBe(true);
          
          // Verify content matches expected
          expect(permissions.overridable).toEqual(OVERRIDABLE_FIELDS);
          expect(permissions.readOnly).toEqual(READ_ONLY_FIELDS);
        }
      ),
      { numRuns: 100 }
    );
  });

  // Verify specific field categories are correctly classified
  describe('Field Category Classification', () => {
    it('should mark domain fields as overridable (Requirement 5.1)', () => {
      const domainFields = [
        'infrastructure.domain.base',
        'infrastructure.domain.hosted_zone_id',
        'infrastructure.domain.frontend_subdomain',
        'infrastructure.domain.backend_subdomain',
      ];
      
      domainFields.forEach(field => {
        expect(isFieldOverridable(field)).toBe(true);
      });
    });

    it('should mark CloudFront CDN fields as overridable (Requirement 5.2)', () => {
      const cdnFields = [
        'infrastructure.frontend.cloudfront.enabled',
        'infrastructure.frontend.cloudfront.waf_enabled',
        'infrastructure.frontend.cloudfront.price_class',
        'infrastructure.frontend.cloudfront.cache_ttl',
        'infrastructure.frontend.cloudfront.rate_limit',
      ];
      
      cdnFields.forEach(field => {
        expect(isFieldOverridable(field)).toBe(true);
      });
    });

    it('should mark ECS fields as overridable (Requirement 5.3)', () => {
      const ecsFields = [
        'infrastructure.backend.ecs.task_cpu',
        'infrastructure.backend.ecs.task_memory',
        'infrastructure.backend.ecs.desired_count',
      ];
      
      ecsFields.forEach(field => {
        expect(isFieldOverridable(field)).toBe(true);
      });
    });

    it('should mark autoscaling fields as overridable (Requirement 5.4)', () => {
      const autoscalingFields = [
        'infrastructure.backend.autoscaling.enabled',
        'infrastructure.backend.autoscaling.min_capacity',
        'infrastructure.backend.autoscaling.max_capacity',
        'infrastructure.backend.autoscaling.target_cpu',
        'infrastructure.backend.autoscaling.target_memory',
      ];
      
      autoscalingFields.forEach(field => {
        expect(isFieldOverridable(field)).toBe(true);
      });
    });

    it('should mark monitoring fields as overridable (Requirement 5.5)', () => {
      const monitoringFields = [
        'infrastructure.monitoring.cloudwatch.log_retention_days',
        'infrastructure.monitoring.cloudwatch.container_insights',
      ];
      
      monitoringFields.forEach(field => {
        expect(isFieldOverridable(field)).toBe(true);
      });
    });

    it('should mark tags as overridable (Requirement 5.6)', () => {
      expect(isFieldOverridable('infrastructure.tags.common')).toBe(true);
    });

    it('should mark VPC fields as read-only (Requirement 5.7)', () => {
      const vpcFields = [
        'infrastructure.backend.vpc.create_new',
        'infrastructure.backend.vpc.vpc_cidr',
        'infrastructure.backend.vpc.enable_nat_gateway',
        'infrastructure.backend.vpc.enable_flow_logs',
      ];
      
      vpcFields.forEach(field => {
        expect(isFieldReadOnly(field)).toBe(true);
      });
    });

    it('should mark storage fields as read-only (Requirement 5.7)', () => {
      const storageFields = [
        'infrastructure.backend.storage.dynamodb_billing_mode',
        'infrastructure.backend.storage.enable_backup',
        'infrastructure.backend.storage.enable_point_in_time_recovery',
      ];
      
      storageFields.forEach(field => {
        expect(isFieldReadOnly(field)).toBe(true);
      });
    });
  });
});

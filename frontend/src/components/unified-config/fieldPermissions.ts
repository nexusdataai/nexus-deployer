/**
 * Field Permissions Configuration
 * Defines which configuration fields are overridable vs read-only
 */

import { EnvironmentType } from './EnvironmentBox';

export interface FieldPermissions {
  overridable: string[];
  readOnly: string[];
}

/**
 * Overridable fields - users can modify these values
 * Paths use dot notation matching the EnvironmentConfig structure
 */
export const OVERRIDABLE_FIELDS: string[] = [
  // Domain Configuration (Requirement 5.1)
  'infrastructure.domain.base',
  'infrastructure.domain.hosted_zone_id',
  'infrastructure.domain.frontend_subdomain',
  'infrastructure.domain.backend_subdomain',
  
  // CloudFront CDN Settings (Requirement 5.2)
  'infrastructure.frontend.cloudfront.enabled',
  'infrastructure.frontend.cloudfront.waf_enabled',
  'infrastructure.frontend.cloudfront.price_class',
  'infrastructure.frontend.cloudfront.cache_ttl',
  'infrastructure.frontend.cloudfront.rate_limit',
  'infrastructure.frontend.cloudfront.enable_logging',
  'infrastructure.frontend.cloudfront.enable_ipv6',
  
  // ECS Task Sizing (Requirement 5.3)
  'infrastructure.backend.ecs.task_cpu',
  'infrastructure.backend.ecs.task_memory',
  'infrastructure.backend.ecs.desired_count',
  'infrastructure.backend.ecs.container_port',
  'infrastructure.backend.ecs.health_check_path',
  
  // Auto Scaling Settings (Requirement 5.4)
  'infrastructure.backend.autoscaling.enabled',
  'infrastructure.backend.autoscaling.min_capacity',
  'infrastructure.backend.autoscaling.max_capacity',
  'infrastructure.backend.autoscaling.target_cpu',
  'infrastructure.backend.autoscaling.target_memory',
  
  // VPC Configuration - now editable to support existing VPC
  'infrastructure.backend.vpc.create_new',
  'infrastructure.backend.vpc.vpc_cidr',
  'infrastructure.backend.vpc.enable_nat_gateway',
  'infrastructure.backend.vpc.enable_flow_logs',
  'infrastructure.backend.vpc.vpc_id',
  'infrastructure.backend.vpc.public_subnets',
  'infrastructure.backend.vpc.private_subnets',
  'infrastructure.backend.vpc.public_subnet_1',
  'infrastructure.backend.vpc.public_subnet_2',
  'infrastructure.backend.vpc.private_subnet_1',
  'infrastructure.backend.vpc.private_subnet_2',
  
  // Monitoring Settings (Requirement 5.5)
  'infrastructure.monitoring.cloudwatch.log_retention_days',
  'infrastructure.monitoring.cloudwatch.container_insights',
  
  // Tags (Requirement 5.6)
  'infrastructure.tags.common',
];

/**
 * Read-only fields - users cannot modify these values
 * These are set based on environment presets
 */
export const READ_ONLY_FIELDS: string[] = [
  // Storage Configuration (Requirement 5.7)
  'infrastructure.backend.storage.dynamodb_billing_mode',
  'infrastructure.backend.storage.dynamodb_read_capacity',
  'infrastructure.backend.storage.dynamodb_write_capacity',
  'infrastructure.backend.storage.enable_backup',
  'infrastructure.backend.storage.enable_point_in_time_recovery',
  'infrastructure.backend.storage.ecr_image_scan_on_push',
  'infrastructure.backend.storage.ecr_image_retention_days',
  
  // ALB Configuration
  'infrastructure.backend.alb.enable_access_logs',
  'infrastructure.backend.alb.deregistration_delay',
  'infrastructure.backend.alb.health_check_interval',
  'infrastructure.backend.alb.health_check_timeout',
  'infrastructure.backend.alb.healthy_threshold',
  'infrastructure.backend.alb.unhealthy_threshold',
  
  // Certificate Configuration
  'infrastructure.backend.certificate.create_in_foundation',
];

/**
 * Check if a field path is overridable
 * @param fieldPath - Dot-notation path to the field
 * @returns true if the field can be edited by the user
 */
export function isFieldOverridable(fieldPath: string): boolean {
  // Check exact match
  if (OVERRIDABLE_FIELDS.includes(fieldPath)) {
    return true;
  }
  
  // Check if any overridable field is a parent (for nested objects like tags)
  for (const overridable of OVERRIDABLE_FIELDS) {
    if (fieldPath.startsWith(overridable + '.')) {
      return true;
    }
  }
  
  return false;
}

/**
 * Check if a field path is read-only
 * @param fieldPath - Dot-notation path to the field
 * @returns true if the field cannot be edited by the user
 */
export function isFieldReadOnly(fieldPath: string): boolean {
  // Check exact match
  if (READ_ONLY_FIELDS.includes(fieldPath)) {
    return true;
  }
  
  // Check if any read-only field is a parent
  for (const readOnly of READ_ONLY_FIELDS) {
    if (fieldPath.startsWith(readOnly + '.')) {
      return true;
    }
  }
  
  return false;
}

/**
 * Get field permissions for a specific environment
 * Currently all environments have the same permissions, but this allows
 * for future customization per environment
 */
export function getFieldPermissions(_environment: EnvironmentType): FieldPermissions {
  return {
    overridable: OVERRIDABLE_FIELDS,
    readOnly: READ_ONLY_FIELDS,
  };
}

/**
 * Get the CSS class for a field based on its editability
 */
export function getFieldClassName(fieldPath: string, baseClass: string = ''): string {
  if (isFieldReadOnly(fieldPath)) {
    return `${baseClass} bg-gray-100 text-gray-500 cursor-not-allowed`;
  }
  return baseClass;
}

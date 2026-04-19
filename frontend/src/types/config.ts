/**
 * Infrastructure configuration types
 */

export interface DomainConfig {
  base: string;
  frontend_subdomain: string;
  backend_subdomain: string;
  hosted_zone_id: string;
}

export interface CloudFrontConfig {
  enabled: boolean;
  price_class: string;
  waf_enabled: boolean;
  cache_ttl: number;
  enable_logging: boolean;
  enable_ipv6: boolean;
  rate_limit: number;
}

export interface FrontendConfig {
  cloudfront: CloudFrontConfig;
}

export interface VPCConfig {
  create_new: boolean;
  vpc_cidr?: string;
  enable_nat_gateway: boolean;
  enable_flow_logs: boolean;
  vpc_id?: string;
  public_subnets?: string[];
  private_subnets?: string[];
}

export interface ECSConfig {
  cluster_name?: string;
  container_port: number;
  task_cpu: number;
  task_memory: number;
  desired_count: number;
  health_check_path: string;
}

export interface AutoScalingConfig {
  enabled: boolean;
  min_capacity: number;
  max_capacity: number;
  target_cpu: number;
  target_memory: number;
}

export interface StorageConfig {
  dynamodb_billing_mode: string;
  dynamodb_read_capacity?: number;
  dynamodb_write_capacity?: number;
  enable_backup: boolean;
  enable_point_in_time_recovery: boolean;
  ecr_image_scan_on_push: boolean;
  ecr_image_retention_days: number;
}

export interface CertificateConfig {
  create_in_foundation: boolean;
}

export interface ALBConfig {
  enable_access_logs: boolean;
  deregistration_delay: number;
  health_check_interval: number;
  health_check_timeout: number;
  healthy_threshold: number;
  unhealthy_threshold: number;
}

export interface BackendConfig {
  vpc: VPCConfig;
  ecs: ECSConfig;
  autoscaling: AutoScalingConfig;
  storage: StorageConfig;
  certificate: CertificateConfig;
  alb: ALBConfig;
}

export interface CloudWatchConfig {
  log_retention_days: number;
  container_insights: boolean;
}

export interface MonitoringConfig {
  cloudwatch: CloudWatchConfig;
}

export interface TagsConfig {
  common: Record<string, string>;
}

export interface InfrastructureConfig {
  domain: DomainConfig;
  frontend: FrontendConfig;
  backend: BackendConfig;
  monitoring: MonitoringConfig;
  tags: TagsConfig;
}

export interface EnvironmentConfig {
  infrastructure: InfrastructureConfig;
}

export interface ConfigResponse {
  success: boolean;
  message: string;
  config?: EnvironmentConfig;
}

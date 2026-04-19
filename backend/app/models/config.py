"""
Infrastructure configuration models
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class DomainConfig(BaseModel):
    """Domain configuration"""
    base: str = Field(default="totogicore.com", description="Base domain")
    frontend_subdomain: str = Field(default="call", description="Frontend subdomain")
    backend_subdomain: str = Field(default="call-api", description="Backend API subdomain")
    hosted_zone_id: str = Field(default="Z084501638STQ2EKKSIA", description="Route53 Hosted Zone ID")


class CloudFrontConfig(BaseModel):
    """CloudFront CDN configuration"""
    enabled: bool = Field(default=True, description="Enable CloudFront CDN")
    price_class: str = Field(default="PriceClass_100", description="CloudFront price class")
    waf_enabled: bool = Field(default=True, description="Enable WAF protection")
    cache_ttl: int = Field(default=86400, description="Default cache TTL in seconds")
    enable_logging: bool = Field(default=True, description="Enable CloudFront access logs")
    enable_ipv6: bool = Field(default=True, description="Enable IPv6 support")
    rate_limit: int = Field(default=2000, description="Rate limit per IP (requests per 5 minutes)")


class FrontendConfig(BaseModel):
    """Frontend infrastructure configuration"""
    cloudfront: CloudFrontConfig = Field(default_factory=CloudFrontConfig)


class VPCConfig(BaseModel):
    """VPC configuration"""
    create_new: bool = Field(default=True, description="Create a new VPC")
    vpc_cidr: Optional[str] = Field(default="10.0.0.0/16", description="CIDR for new VPC")
    enable_nat_gateway: bool = Field(default=True, description="Enable NAT Gateway")
    enable_flow_logs: bool = Field(default=False, description="Enable VPC Flow Logs")
    
    # For existing VPC
    vpc_id: Optional[str] = Field(default=None, description="Existing VPC ID")
    public_subnets: Optional[List[str]] = Field(default=None, description="Public subnet IDs")
    private_subnets: Optional[List[str]] = Field(default=None, description="Private subnet IDs")
    # Individual subnet fields for UI
    public_subnet_1: Optional[str] = Field(default=None, description="Public subnet 1 ID")
    public_subnet_2: Optional[str] = Field(default=None, description="Public subnet 2 ID")
    private_subnet_1: Optional[str] = Field(default=None, description="Private subnet 1 ID")
    private_subnet_2: Optional[str] = Field(default=None, description="Private subnet 2 ID")


class ECSConfig(BaseModel):
    """ECS service configuration"""
    cluster_name: Optional[str] = Field(default=None, description="ECS cluster name")
    container_port: int = Field(default=8000, description="Container port")
    task_cpu: int = Field(default=1024, description="CPU units (256, 512, 1024, 2048, 4096)")
    task_memory: int = Field(default=2048, description="Memory in MiB")
    desired_count: int = Field(default=2, description="Number of tasks to run")
    health_check_path: str = Field(default="/health", description="Health check endpoint")


class AutoScalingConfig(BaseModel):
    """Auto-scaling configuration"""
    enabled: bool = Field(default=True, description="Enable auto-scaling")
    min_capacity: int = Field(default=1, description="Minimum number of tasks")
    max_capacity: int = Field(default=5, ge=1, le=20, description="Maximum number of tasks (hard limit: 20)")
    target_cpu: int = Field(default=70, description="Target CPU utilization %")
    target_memory: int = Field(default=80, description="Target memory utilization %")


class StorageConfig(BaseModel):
    """Storage configuration"""
    dynamodb_billing_mode: str = Field(default="PAY_PER_REQUEST", description="DynamoDB billing mode")
    dynamodb_read_capacity: Optional[int] = Field(default=None, description="Read capacity units (if PROVISIONED)")
    dynamodb_write_capacity: Optional[int] = Field(default=None, description="Write capacity units (if PROVISIONED)")
    enable_backup: bool = Field(default=True, description="Enable automated backups")
    enable_point_in_time_recovery: bool = Field(default=True, description="Enable DynamoDB PITR")
    ecr_image_scan_on_push: bool = Field(default=True, description="Scan images for vulnerabilities")
    ecr_image_retention_days: int = Field(default=7, description="Days to keep untagged images")


class CertificateConfig(BaseModel):
    """Certificate configuration"""
    create_in_foundation: bool = Field(default=True, description="Create cert in foundation stack")


class ALBConfig(BaseModel):
    """Application Load Balancer configuration"""
    enable_access_logs: bool = Field(default=False, description="Enable ALB access logs")
    deregistration_delay: int = Field(default=30, description="Seconds to wait before deregistering")
    health_check_interval: int = Field(default=30, description="Health check interval in seconds")
    health_check_timeout: int = Field(default=10, description="Health check timeout in seconds")
    healthy_threshold: int = Field(default=2, description="Consecutive successful checks")
    unhealthy_threshold: int = Field(default=3, description="Consecutive failed checks")


class BackendConfig(BaseModel):
    """Backend infrastructure configuration"""
    vpc: VPCConfig = Field(default_factory=VPCConfig)
    ecs: ECSConfig = Field(default_factory=ECSConfig)
    autoscaling: AutoScalingConfig = Field(default_factory=AutoScalingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    certificate: CertificateConfig = Field(default_factory=CertificateConfig)
    alb: ALBConfig = Field(default_factory=ALBConfig)


class CloudWatchConfig(BaseModel):
    """CloudWatch monitoring configuration"""
    log_retention_days: int = Field(default=7, description="Log retention period")
    container_insights: bool = Field(default=True, description="Enable Container Insights for ECS")


class MonitoringConfig(BaseModel):
    """Monitoring configuration"""
    cloudwatch: CloudWatchConfig = Field(default_factory=CloudWatchConfig)


class TagsConfig(BaseModel):
    """AWS resource tags configuration"""
    common: Dict[str, str] = Field(
        default_factory=lambda: {
            "Project": "",
            "Environment": "",
            "ManagedBy": "CloudFormation",
            "Team": "",
            "Application": "",
            "CostCenter": "",
        },
        description="Common tags applied to all resources"
    )


class InfrastructureConfig(BaseModel):
    """Complete infrastructure configuration"""
    domain: DomainConfig
    frontend: FrontendConfig = Field(default_factory=FrontendConfig)
    backend: BackendConfig = Field(default_factory=BackendConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    tags: TagsConfig = Field(default_factory=TagsConfig)


class EnvironmentConfig(BaseModel):
    """Complete environment configuration"""
    infrastructure: InfrastructureConfig
    
    class Config:
        json_schema_extra = {
            "example": {
                "infrastructure": {
                    "domain": {
                        "base": "totogicore.com",
                        "frontend_subdomain": "call",
                        "backend_subdomain": "call-api",
                        "hosted_zone_id": "Z084501638STQ2EKKSIA"
                    },
                    "frontend": {
                        "cloudfront": {
                            "enabled": True,
                            "price_class": "PriceClass_100",
                            "waf_enabled": True
                        }
                    },
                    "backend": {
                        "vpc": {
                            "create_new": True,
                            "vpc_cidr": "10.0.0.0/16"
                        },
                        "ecs": {
                            "container_port": 8000,
                            "task_cpu": 1024,
                            "task_memory": 2048,
                            "desired_count": 2
                        }
                    }
                }
            }
        }


class ConfigSaveRequest(BaseModel):
    """Request to save configuration"""
    capability_name: str
    environment: str
    config: EnvironmentConfig


class ConfigResponse(BaseModel):
    """Response for configuration operations"""
    success: bool
    message: str
    config: Optional[EnvironmentConfig] = None

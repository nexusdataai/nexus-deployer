"""
UI Config Generator Service
Generates config.json from CloudFormation stack outputs and uploads to S3
"""
import boto3
import json
import logging
from typing import Dict, Optional, Any, Callable
from datetime import datetime
from botocore.exceptions import ClientError

from app.utils.aws_vpc_endpoints import merge_vpc_boto3_kwargs

logger = logging.getLogger(__name__)


class UIConfigGenerator:
    """Service for generating and deploying UI config.json from stack outputs"""
    
    CONFIG_VERSION = "1.0.0"
    
    def __init__(self, credentials: Optional[Dict[str, str]] = None):
        """
        Initialize UI config generator
        
        Args:
            credentials: Optional AWS credentials dict
        """
        self.credentials = credentials or {}
    
    def _get_client(self, service: str, region: str) -> Any:
        """Get boto3 client with credentials"""
        kw = {"region_name": region, **self.credentials}
        return boto3.client(service, **merge_vpc_boto3_kwargs(service, region, kw))
    
    def get_stack_outputs(self, stack_name: str, region: str) -> Dict[str, str]:
        """
        Get outputs from a CloudFormation stack
        
        Args:
            stack_name: Name of the CloudFormation stack
            region: AWS region
            
        Returns:
            Dict of output key-value pairs
        """
        try:
            cfn_client = self._get_client('cloudformation', region)
            response = cfn_client.describe_stacks(StackName=stack_name)
            
            if not response.get('Stacks'):
                logger.warning(f"Stack {stack_name} not found in {region}")
                return {}
            
            stack = response['Stacks'][0]
            outputs = {}
            
            for output in stack.get('Outputs', []):
                outputs[output['OutputKey']] = output['OutputValue']
            
            return outputs
            
        except ClientError as e:
            logger.warning(f"Error getting stack outputs for {stack_name}: {e}")
            return {}
    
    def generate_config(
        self,
        stack_outputs: Dict[str, Dict[str, str]],
        region: str,
        callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        Generate config.json content from stack outputs
        
        Args:
            stack_outputs: Dict of stack type -> outputs
            region: AWS region for Cognito
            callback: Optional progress callback
            
        Returns:
            Config dict ready for JSON serialization
        """
        # Extract values from stack outputs
        cognito_outputs = stack_outputs.get('frontend-cognito', {})
        global_outputs = stack_outputs.get('frontend-global', {})
        service_outputs = stack_outputs.get('backend-service', {})
        domain_outputs = stack_outputs.get('backend-domain', {})
        
        # Get API URL - prefer custom domain, fallback to ALB/API Gateway URL
        api_url = (
            domain_outputs.get('ApiUrl') or
            service_outputs.get('ServiceURL') or
            service_outputs.get('ApiEndpoint') or
            service_outputs.get('ApiGatewayUrl') or
            ""
        )
        
        # Get frontend domain for redirect URIs
        frontend_domain = global_outputs.get('FrontendDomainName', '')
        
        # Build redirect URIs
        if frontend_domain:
            if not frontend_domain.startswith('http'):
                frontend_domain = f"https://{frontend_domain}"
            redirect_sign_in = f"{frontend_domain}/auth/callback"
            redirect_sign_out = frontend_domain
        else:
            redirect_sign_in = ""
            redirect_sign_out = ""
        
        # Get Cognito config
        user_pool_id = cognito_outputs.get('UserPoolId', '')
        client_id = cognito_outputs.get('UserPoolClientId', '')
        cognito_domain = cognito_outputs.get('UserPoolDomain', '')
        
        if callback:
            callback(f"  API URL: {api_url or 'NOT FOUND'}")
            callback(f"  User Pool ID: {user_pool_id or 'NOT FOUND'}")
            callback(f"  Client ID: {client_id or 'NOT FOUND'}")
            callback(f"  Cognito Domain: {cognito_domain or 'NOT FOUND'}")
            callback(f"  Frontend Domain: {frontend_domain or 'NOT FOUND'}")
        
        # Build config structure
        config = {
            "version": self.CONFIG_VERSION,
            "api": {
                "baseUrl": api_url,
                "timeout": 30000
            },
            "gateway": {
                "apiKey": ""
            },
            "dataSource": "api",
            "enableFallback": True,
            "cognito": {
                "region": region,
                "userPoolId": user_pool_id,
                "clientId": client_id,
                "domain": cognito_domain,
                "redirectSignIn": redirect_sign_in,
                "redirectSignOut": redirect_sign_out
            }
        }
        
        return config
    
    def upload_config_to_s3(
        self,
        config: Dict[str, Any],
        bucket: str,
        region: str,
        backup: bool = True,
        callback: Optional[Callable] = None
    ) -> bool:
        """
        Upload config.json to S3 bucket
        
        Args:
            config: Config dict to upload
            bucket: S3 bucket name
            region: AWS region
            backup: Whether to backup existing config
            callback: Optional progress callback
            
        Returns:
            True if successful
        """
        try:
            s3_client = self._get_client('s3', region)
            config_key = 'config.json'
            
            # Backup existing config if requested
            if backup:
                try:
                    s3_client.head_object(Bucket=bucket, Key=config_key)
                    # Config exists, create backup
                    timestamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
                    backup_key = f"config.json.backup.{timestamp}"
                    
                    if callback:
                        callback(f"Backing up existing config to {backup_key}...")
                    
                    s3_client.copy_object(
                        Bucket=bucket,
                        CopySource={'Bucket': bucket, 'Key': config_key},
                        Key=backup_key
                    )
                    
                    if callback:
                        callback(f"[OK] Backup created: {backup_key}")
                        
                except ClientError as e:
                    if e.response['Error']['Code'] != '404':
                        if callback:
                            callback(f"[!] Backup warning: {e}")
            
            # Upload new config
            config_json = json.dumps(config, indent=2)
            
            if callback:
                callback(f"Uploading config.json to s3://{bucket}/{config_key}...")
            
            s3_client.put_object(
                Bucket=bucket,
                Key=config_key,
                Body=config_json.encode('utf-8'),
                ContentType='application/json',
                CacheControl='no-cache, no-store, must-revalidate'
            )
            
            if callback:
                callback(f"[OK] config.json uploaded successfully")
            
            return True
            
        except ClientError as e:
            if callback:
                callback(f"[X] Failed to upload config.json: {e}")
            logger.error(f"Failed to upload config.json to {bucket}: {e}")
            return False
        except Exception as e:
            if callback:
                callback(f"[X] Error uploading config.json: {e}")
            logger.error(f"Error uploading config.json: {e}")
            return False
    
    def invalidate_cloudfront(
        self,
        distribution_id: str,
        callback: Optional[Callable] = None
    ) -> bool:
        """
        Invalidate CloudFront cache for config.json
        
        Args:
            distribution_id: CloudFront distribution ID
            callback: Optional progress callback
            
        Returns:
            True if successful
        """
        try:
            # CloudFront API is global, use us-east-1
            cf_client = self._get_client('cloudfront', 'us-east-1')
            
            if callback:
                callback(f"Creating CloudFront invalidation for /config.json...")
            
            import time
            caller_reference = f"config-{int(time.time())}"
            
            response = cf_client.create_invalidation(
                DistributionId=distribution_id,
                InvalidationBatch={
                    'Paths': {
                        'Quantity': 1,
                        'Items': ['/config.json']
                    },
                    'CallerReference': caller_reference
                }
            )
            
            invalidation_id = response['Invalidation']['Id']
            
            if callback:
                callback(f"[OK] CloudFront invalidation created: {invalidation_id}")
            
            return True
            
        except ClientError as e:
            if callback:
                callback(f"[!] CloudFront invalidation failed: {e}")
            logger.warning(f"CloudFront invalidation failed: {e}")
            return False
        except Exception as e:
            if callback:
                callback(f"[!] CloudFront invalidation error: {e}")
            logger.warning(f"CloudFront invalidation error: {e}")
            return False
    
    def generate_and_deploy_config(
        self,
        stack_outputs: Dict[str, Dict[str, str]],
        region: str,
        callback: Optional[Callable] = None
    ) -> bool:
        """
        Complete workflow: generate config.json from stack outputs and deploy to S3
        
        Args:
            stack_outputs: Dict of stack type -> outputs
            region: AWS region
            callback: Optional progress callback
            
        Returns:
            True if successful
        """
        if callback:
            callback("[NOTE] Generating config.json from stack outputs...")
        
        # Get S3 bucket and CloudFront distribution from regional stack
        regional_outputs = stack_outputs.get('frontend-regional', {})
        target_bucket = regional_outputs.get('S3BucketName')
        distribution_id = regional_outputs.get('CloudFrontDistributionId')
        
        if not target_bucket:
            if callback:
                callback("[X] Cannot generate config.json: S3BucketName not found in frontend-regional stack")
            return False
        
        # Generate config
        config = self.generate_config(stack_outputs, region, callback)
        
        # Validate config has required fields
        cognito = config.get('cognito', {})
        if not cognito.get('userPoolId') or not cognito.get('clientId'):
            if callback:
                callback("[!] Warning: Cognito configuration incomplete in config.json")
        
        if not config.get('api', {}).get('baseUrl'):
            if callback:
                callback("[!] Warning: API baseUrl not found in config.json")
        
        # Upload to S3
        if not self.upload_config_to_s3(config, target_bucket, region, backup=True, callback=callback):
            return False
        
        # Invalidate CloudFront cache
        if distribution_id:
            self.invalidate_cloudfront(distribution_id, callback)
        else:
            if callback:
                callback("[!] CloudFront distribution ID not found, skipping invalidation")
        
        if callback:
            callback("[OK] config.json generation and deployment complete")
        
        return True

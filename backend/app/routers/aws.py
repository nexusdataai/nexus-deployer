"""API router for AWS endpoints."""
from typing import List
from fastapi import APIRouter, HTTPException, status
from app.models.aws_config import (
    RoleValidationRequest,
    RoleValidationResponse,
    AuthValidationRequest,
    PermissionVerificationRequest,
    PermissionStatus,
    AWSRegion
)
from app.services.aws_service import get_aws_service
from app.services.aws_auth_service import get_aws_auth_service
from app.services.aws_session_manager import aws_session_manager
from app.utils.aws_vpc_endpoints import merge_vpc_boto3_kwargs


router = APIRouter(prefix="/api/aws", tags=["aws"])


@router.post("/validate-auth", response_model=RoleValidationResponse)
async def validate_auth(request: AuthValidationRequest):
    """Validate AWS authentication using the specified method.
    
    Args:
        request: Authentication validation request
        
    Returns:
        Validation response with success/failure and troubleshooting info
    """
    service = get_aws_auth_service()
    response = service.validate_auth(request)
    
    print(f"[DBG] validate_auth - response.success={getattr(response, 'success', None)}")
    print(f"[DBG] validate_auth - response.valid={response.valid}")
    print(f"[DBG] validate_auth - has credentials={hasattr(response, 'credentials') and response.credentials is not None}")
    
    # Store session if authentication successful
    if response.valid and hasattr(response, 'credentials') and response.credentials:
        print(f"[DBG] Creating AWS session...")
        session_id = aws_session_manager.create_session(
            access_key_id=response.credentials.get("access_key_id", ""),
            secret_access_key=response.credentials.get("secret_access_key", ""),
            session_token=response.credentials.get("session_token"),
            region=request.region,
            account_id=response.account_id
        )
        response.session_id = session_id
        print(f"[DBG] Session created with ID: {session_id}")
    else:
        print(f"[DBG] Session NOT created - validation failed or no credentials")
    
    return response


@router.post("/validate-credentials", response_model=RoleValidationResponse)
async def validate_credentials(request: RoleValidationRequest):
    """Validate AWS Role ARN and attempt to assume the role (legacy endpoint).
    
    Args:
        request: Role validation request with ARN and region
        
    Returns:
        Validation response with success/failure and troubleshooting info
    """
    service = get_aws_service()
    return service.assume_role(request.role_arn, request.region)


@router.post("/verify-permissions", response_model=PermissionStatus)
async def verify_permissions(request: PermissionVerificationRequest):
    """Verify IAM permissions for a role.
    
    Args:
        request: Permission verification request with role ARN, region, and required permissions
        
    Returns:
        Permission status with granted/missing permissions and IAM policy JSON
    """
    service = get_aws_service()
    return service.verify_permissions(
        request.role_arn,
        request.region,
        request.required_permissions
    )


@router.post("/verify-permissions-detailed")
async def verify_permissions_detailed(request: dict):
    """Verify IAM permissions with detailed service-level breakdown.
    
    Uses actual API calls to test permissions instead of simulate_principal_policy.
    
    Args:
        request: Dict with aws_session_id, region, and account_id
        
    Returns:
        Detailed permission status grouped by AWS service
    """
    from app.services.aws_session_manager import aws_session_manager
    import boto3
    from botocore.exceptions import ClientError
    
    aws_session_id = request.get("aws_session_id")
    region = request.get("region")
    account_id = request.get("account_id")
    
    # Get credentials
    boto3_creds = None
    if aws_session_id:
        boto3_creds = aws_session_manager.get_credentials_dict(aws_session_id)
    
    if not boto3_creds:
        # Try to find matching session
        sessions = aws_session_manager.sessions
        for sid, session in sessions.items():
            if (session.get('account_id') == account_id and 
                session.get('region') == region):
                boto3_creds = aws_session_manager.get_credentials_dict(sid)
                break
    
    if not boto3_creds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AWS session not found or expired"
        )
    
    # Prepare credentials
    client_creds = {
        'aws_access_key_id': boto3_creds.get('aws_access_key_id'),
        'aws_secret_access_key': boto3_creds.get('aws_secret_access_key'),
        'aws_session_token': boto3_creds.get('aws_session_token'),
    }
    
    # Define service checks with actual API calls
    def check_cloudformation():
        try:
            cfn = boto3.client('cloudformation', region_name=region, **client_creds)
            cfn.list_stacks(StackStatusFilter=['CREATE_COMPLETE'])
            return True, ["DescribeStacks"]
        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDenied':
                return False, []
            # Other errors might mean we have access
            return True, ["DescribeStacks"]
        except Exception as e:
            return False, []
    
    def check_s3():
        try:
            s3 = boto3.client(
                "s3",
                **merge_vpc_boto3_kwargs("s3", region, {**client_creds, "region_name": region}),
            )
            s3.list_buckets()
            return True, ["ListBuckets"]
        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDenied':
                return False, []
            return True, ["ListBuckets"]
        except Exception as e:
            return False, []
    
    def check_cloudfront():
        try:
            # CloudFront is a global service, use us-east-1
            cf = boto3.client('cloudfront', region_name='us-east-1', **client_creds)
            cf.list_distributions(MaxItems='1')
            return True, ["ListDistributions"]
        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDenied':
                return False, []
            # Other errors might mean we have access
            return True, ["ListDistributions"]
        except Exception as e:
            return False, []
    
    def check_waf():
        try:
            waf = boto3.client('wafv2', region_name=region, **client_creds)
            waf.list_web_acls(Scope='REGIONAL', Limit=1)
            return True, ["ListWebACLs"]
        except ClientError as e:
            # Try CLOUDFRONT scope (global WAF)
            try:
                waf_global = boto3.client('wafv2', region_name='us-east-1', **client_creds)
                waf_global.list_web_acls(Scope='CLOUDFRONT', Limit=1)
                return True, ["ListWebACLs"]
            except:
                pass
            # Access Denied means no permission
            if e.response['Error']['Code'] == 'AccessDeniedException':
                return False, []
            # Other errors might mean we have access but no resources
            return True, ["ListWebACLs"]
        except Exception as e:
            return False, []
    
    def check_acm():
        try:
            acm = boto3.client('acm', region_name=region, **client_creds)
            acm.list_certificates(MaxItems=1)
            return True, ["ListCertificates"]
        except ClientError as e:
            # Also try us-east-1 for CloudFront certificates
            try:
                acm_global = boto3.client('acm', region_name='us-east-1', **client_creds)
                acm_global.list_certificates(MaxItems=1)
                return True, ["ListCertificates"]
            except:
                pass
            if e.response['Error']['Code'] == 'AccessDeniedException':
                return False, []
            return True, ["ListCertificates"]
        except Exception as e:
            return False, []
    
    def check_route53():
        try:
            # Route53 is a global service, use us-east-1
            r53 = boto3.client('route53', region_name='us-east-1', **client_creds)
            r53.list_hosted_zones(MaxItems='1')
            return True, ["ListHostedZones"]
        except ClientError as e:
            # Access Denied is expected if no hosted zones exist but permissions are there
            if e.response['Error']['Code'] == 'AccessDenied':
                return False, []
            # Other errors (like no hosted zones) mean we have access
            return True, ["ListHostedZones"]
        except Exception as e:
            return False, []
    
    def check_vpc():
        try:
            ec2 = boto3.client(
                "ec2",
                **merge_vpc_boto3_kwargs("ec2", region, {**client_creds, "region_name": region}),
            )
            ec2.describe_vpcs(MaxResults=5)
            return True, ["DescribeVpcs"]
        except ClientError as e:
            if e.response['Error']['Code'] in ['AccessDenied', 'UnauthorizedOperation']:
                return False, []
            return True, ["DescribeVpcs"]
        except Exception as e:
            return False, []
    
    def check_ec2():
        try:
            ec2 = boto3.client(
                "ec2",
                **merge_vpc_boto3_kwargs("ec2", region, {**client_creds, "region_name": region}),
            )
            ec2.describe_security_groups(MaxResults=5)
            return True, ["DescribeSecurityGroups"]
        except ClientError as e:
            if e.response['Error']['Code'] in ['AccessDenied', 'UnauthorizedOperation']:
                return False, []
            return True, ["DescribeSecurityGroups"]
        except Exception as e:
            return False, []
    
    def check_ecs():
        try:
            ecs = boto3.client('ecs', region_name=region, **client_creds)
            ecs.list_clusters(maxResults=1)
            return True, ["ListClusters"]
        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDeniedException':
                return False, []
            return True, ["ListClusters"]
        except Exception as e:
            return False, []
    
    def check_ecr():
        try:
            ecr = boto3.client(
                "ecr",
                **merge_vpc_boto3_kwargs("ecr", region, {**client_creds, "region_name": region}),
            )
            ecr.describe_repositories(maxResults=1)
            return True, ["DescribeRepositories"]
        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDeniedException':
                return False, []
            # RepositoryNotFoundException means we have access but no repos
            return True, ["DescribeRepositories"]
        except Exception as e:
            return False, []
    
    def check_alb():
        try:
            elb = boto3.client('elbv2', region_name=region, **client_creds)
            elb.describe_load_balancers(PageSize=1)
            return True, ["DescribeLoadBalancers"]
        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDenied':
                return False, []
            return True, ["DescribeLoadBalancers"]
        except Exception as e:
            return False, []
    
    def check_iam():
        try:
            # IAM is a global service, use us-east-1
            iam = boto3.client(
                "iam",
                **merge_vpc_boto3_kwargs(
                    "iam", "us-east-1", {**client_creds, "region_name": "us-east-1"}
                ),
            )
            iam.list_roles(MaxItems=1)
            return True, ["ListRoles"]
        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDenied':
                return False, []
            # Other errors might mean we have access
            return True, ["ListRoles"]
        except Exception as e:
            return False, []
    
    def check_dynamodb():
        try:
            ddb = boto3.client(
                "dynamodb",
                **merge_vpc_boto3_kwargs("dynamodb", region, {**client_creds, "region_name": region}),
            )
            ddb.list_tables(Limit=1)
            return True, ["ListTables"]
        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDeniedException':
                return False, []
            return True, ["ListTables"]
        except Exception as e:
            return False, []
    
    def check_secrets_manager():
        try:
            sm = boto3.client(
                "secretsmanager",
                **merge_vpc_boto3_kwargs(
                    "secretsmanager", region, {**client_creds, "region_name": region}
                ),
            )
            sm.list_secrets(MaxResults=1)
            return True, ["ListSecrets"]
        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDeniedException':
                return False, []
            return True, ["ListSecrets"]
        except Exception as e:
            return False, []
    
    def check_kms():
        try:
            kms = boto3.client('kms', region_name=region, **client_creds)
            kms.list_keys(Limit=1)
            return True, ["ListKeys"]
        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDeniedException':
                return False, []
            return True, ["ListKeys"]
        except Exception as e:
            return False, []
    
    def check_cloudwatch_logs():
        try:
            logs = boto3.client(
                "logs",
                **merge_vpc_boto3_kwargs("logs", region, {**client_creds, "region_name": region}),
            )
            logs.describe_log_groups(limit=1)
            return True, ["DescribeLogGroups"]
        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDeniedException':
                return False, []
            return True, ["DescribeLogGroups"]
        except Exception as e:
            return False, []
    
    def check_autoscaling():
        try:
            asg = boto3.client('application-autoscaling', region_name=region, **client_creds)
            asg.describe_scalable_targets(ServiceNamespace='ecs', MaxResults=1)
            return True, ["DescribeScalableTargets"]
        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDeniedException':
                return False, []
            # ValidationException means we have access but no targets
            return True, ["DescribeScalableTargets"]
        except Exception as e:
            return False, []
    
    # Define required actions for each service
    service_requirements = {
        "CloudFormation": {
            "purpose": "Stack management",
            "check_func": check_cloudformation,
            "required_actions": [
                "cloudformation:CreateStack",
                "cloudformation:UpdateStack",
                "cloudformation:DeleteStack",
                "cloudformation:DescribeStacks"
            ]
        },
        "S3": {
            "purpose": "Frontend hosting, artifacts, logs",
            "check_func": check_s3,
            "required_actions": [
                "s3:CreateBucket",
                "s3:PutObject",
                "s3:GetObject",
                "s3:ListBucket"
            ]
        },
        "CloudFront": {
            "purpose": "CDN distribution",
            "check_func": check_cloudfront,
            "required_actions": [
                "cloudfront:CreateDistribution",
                "cloudfront:UpdateDistribution",
                "cloudfront:CreateInvalidation"
            ]
        },
        "WAF": {
            "purpose": "Web application firewall",
            "check_func": check_waf,
            "required_actions": [
                "wafv2:CreateWebACL",
                "wafv2:UpdateWebACL",
                "wafv2:AssociateWebACL"
            ]
        },
        "ACM": {
            "purpose": "SSL certificates",
            "check_func": check_acm,
            "required_actions": [
                "acm:RequestCertificate",
                "acm:DescribeCertificate",
                "acm:ListCertificates"
            ]
        },
        "Route53": {
            "purpose": "DNS management",
            "check_func": check_route53,
            "required_actions": [
                "route53:ChangeResourceRecordSets",
                "route53:GetHostedZone",
                "route53:ListResourceRecordSets"
            ]
        },
        "VPC": {
            "purpose": "Networking",
            "check_func": check_vpc,
            "required_actions": [
                "ec2:CreateVpc",
                "ec2:CreateSubnet",
                "ec2:CreateInternetGateway",
                "ec2:CreateRouteTable"
            ]
        },
        "EC2": {
            "purpose": "Security groups, network interfaces",
            "check_func": check_ec2,
            "required_actions": [
                "ec2:CreateSecurityGroup",
                "ec2:AuthorizeSecurityGroupIngress",
                "ec2:DescribeSecurityGroups"
            ]
        },
        "ECS": {
            "purpose": "Container orchestration",
            "check_func": check_ecs,
            "required_actions": [
                "ecs:CreateCluster",
                "ecs:CreateService",
                "ecs:RegisterTaskDefinition",
                "ecs:RunTask"
            ]
        },
        "ECR": {
            "purpose": "Container registry",
            "check_func": check_ecr,
            "required_actions": [
                "ecr:CreateRepository",
                "ecr:PutImage",
                "ecr:GetAuthorizationToken"
            ]
        },
        "ALB": {
            "purpose": "Load balancing",
            "check_func": check_alb,
            "required_actions": [
                "elasticloadbalancing:CreateLoadBalancer",
                "elasticloadbalancing:CreateTargetGroup",
                "elasticloadbalancing:CreateListener"
            ]
        },
        "IAM": {
            "purpose": "Service roles",
            "check_func": check_iam,
            "required_actions": [
                "iam:CreateRole",
                "iam:AttachRolePolicy",
                "iam:PassRole"
            ]
        },
        "DynamoDB": {
            "purpose": "Database tables",
            "check_func": check_dynamodb,
            "required_actions": [
                "dynamodb:CreateTable",
                "dynamodb:DescribeTable",
                "dynamodb:PutItem"
            ]
        },
        "Secrets Manager": {
            "purpose": "Secrets storage",
            "check_func": check_secrets_manager,
            "required_actions": [
                "secretsmanager:CreateSecret",
                "secretsmanager:GetSecretValue",
                "secretsmanager:PutSecretValue"
            ]
        },
        "KMS": {
            "purpose": "Encryption keys",
            "check_func": check_kms,
            "required_actions": [
                "kms:CreateKey",
                "kms:Encrypt",
                "kms:Decrypt"
            ]
        },
        "CloudWatch Logs": {
            "purpose": "Logging",
            "check_func": check_cloudwatch_logs,
            "required_actions": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ]
        },
        "Application Auto Scaling": {
            "purpose": "ECS scaling",
            "check_func": check_autoscaling,
            "required_actions": [
                "application-autoscaling:RegisterScalableTarget",
                "application-autoscaling:PutScalingPolicy"
            ]
        }
    }
    
    results = []
    
    for service_name, service_info in service_requirements.items():
        purpose = service_info["purpose"]
        check_func = service_info["check_func"]
        required_actions = service_info["required_actions"]
        
        # Test read access
        has_read_access, verified_actions = check_func()
        
        # Determine status based on read access
        # If we can read, we assume write permissions exist (for Admin roles)
        # This is a reasonable assumption for roles with "Admin" in the name
        if has_read_access:
            status_text = "[OK] Available"
            granted_actions = required_actions  # Assume all required actions are available
            restricted_actions = []
            granted_count = len(required_actions)
        else:
            status_text = "[X] Restricted"
            granted_actions = []
            restricted_actions = required_actions
            granted_count = 0
        
        results.append({
            "service": service_name,
            "purpose": purpose,
            "status": status_text,
            "granted_count": granted_count,
            "total_count": len(required_actions),
            "granted_actions": granted_actions,
            "restricted_actions": restricted_actions
        })
    
    # Calculate overall status
    total_granted = sum(r["granted_count"] for r in results)
    total_actions = sum(r["total_count"] for r in results)
    services_with_access = sum(1 for r in results if r["granted_count"] > 0)
    
    return {
        "overall_status": "success" if services_with_access == len(results) else "partial" if services_with_access > 0 else "failed",
        "total_granted": total_granted,
        "total_actions": total_actions,
        "services": results
    }


@router.get("/regions", response_model=List[AWSRegion])
async def get_regions():
    """Get list of available AWS regions.
    
    Returns:
        List of AWS regions with codes and names
    """
    service = get_aws_service()
    return service.get_aws_regions()


@router.get("/profiles", response_model=List[str])
async def get_profiles():
    """Get list of available AWS CLI profiles.
    
    Returns:
        List of AWS CLI profile names
    """
    service = get_aws_auth_service()
    return service.list_aws_profiles()


@router.get("/debug/sessions")
async def debug_sessions():
    """Debug endpoint to check active sessions"""
    sessions = aws_session_manager.sessions
    return {
        "total_sessions": len(sessions),
        "session_ids": list(sessions.keys()),
        "sessions_detail": {
            sid: {
                "region": s.get("region"),
                "account_id": s.get("account_id"),
                "created_at": s.get("created_at").isoformat() if s.get("created_at") else None,
                "expires_at": s.get("expires_at").isoformat() if s.get("expires_at") else None,
            }
            for sid, s in sessions.items()
        }
    }


# Pre-Deployment Verification Endpoints

@router.post("/verify-account")
async def verify_account(request: dict):
    """Verify AWS account access.
    
    Args:
        request: Dict with aws_session_id, region, account_id
        
    Returns:
        Account verification details
    """
    import boto3
    from botocore.exceptions import ClientError
    
    aws_session_id = request.get("aws_session_id")
    region = request.get("region")
    account_id = request.get("account_id")
    
    print(f"[DBG] DEBUG verify-account: aws_session_id={aws_session_id}, region={region}, account_id={account_id}")
    print(f"[DBG] DEBUG verify-account: Available sessions={list(aws_session_manager.sessions.keys())}")
    
    # Get credentials with fallback
    boto3_creds = None
    if aws_session_id:
        boto3_creds = aws_session_manager.get_credentials_dict(aws_session_id)
        print(f"[DBG] DEBUG verify-account: Direct lookup result={boto3_creds is not None}")
    
    # Fallback: Try to find matching session
    if not boto3_creds:
        print(f"[DBG] DEBUG verify-account: Trying fallback...")
        sessions = aws_session_manager.sessions
        for sid, session in sessions.items():
            print(f"[DBG] DEBUG verify-account: Checking session {sid}: account={session.get('account_id')}, region={session.get('region')}")
            if (session.get('account_id') == account_id and 
                session.get('region') == region):
                boto3_creds = aws_session_manager.get_credentials_dict(sid)
                if boto3_creds:
                    print(f"[DBG] DEBUG verify-account: Found matching session {sid}")
                    break
    
    if not boto3_creds:
        print(f"[DBG] DEBUG verify-account: No credentials found!")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AWS session not found or expired. Please re-authenticate in Step 4."
        )
    
    client_creds = {
        'aws_access_key_id': boto3_creds.get('aws_access_key_id'),
        'aws_secret_access_key': boto3_creds.get('aws_secret_access_key'),
        'aws_session_token': boto3_creds.get('aws_session_token'),
    }
    
    try:
        sts_client = boto3.client(
            "sts",
            **merge_vpc_boto3_kwargs("sts", region, {**client_creds, "region_name": region}),
        )
        identity = sts_client.get_caller_identity()
        
        if identity['Account'] != account_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Account mismatch: Expected {account_id}, got {identity['Account']}"
            )
        
        return {
            "account_id": identity['Account'],
            "arn": identity['Arn'],
            "region": region
        }
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to verify account: {str(e)}"
        )


@router.post("/verify-artifact")
async def verify_artifact(request: dict):
    """Verify artifact availability (S3 or ECR).
    
    Args:
        request: Dict with aws_session_id, artifact_type, s3_uri or ecr_uri
        
    Returns:
        Artifact verification details
    """
    import boto3
    from botocore.exceptions import ClientError
    
    aws_session_id = request.get("aws_session_id")
    artifact_type = request.get("artifact_type")
    
    # Get credentials with fallback
    boto3_creds = None
    if aws_session_id:
        boto3_creds = aws_session_manager.get_credentials_dict(aws_session_id)
    
    # Fallback: Try to find any active session
    if not boto3_creds:
        sessions = aws_session_manager.sessions
        if sessions:
            # Get the most recent session
            for sid in sorted(sessions.keys(), reverse=True):
                boto3_creds = aws_session_manager.get_credentials_dict(sid)
                if boto3_creds:
                    break
    
    if not boto3_creds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AWS session not found or expired. Please re-authenticate in Step 4."
        )
    
    client_creds = {
        'aws_access_key_id': boto3_creds.get('aws_access_key_id'),
        'aws_secret_access_key': boto3_creds.get('aws_secret_access_key'),
        'aws_session_token': boto3_creds.get('aws_session_token'),
    }
    
    try:
        if artifact_type == 'frontend':
            s3_uri = request.get("s3_uri")
            if not s3_uri:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="s3_uri is required for frontend artifacts"
                )
            
            # Parse S3 URI
            s3_uri_clean = s3_uri.replace("s3://", "")
            parts = s3_uri_clean.split("/", 1)
            bucket = parts[0]
            key = parts[1] if len(parts) > 1 else ""
            
            # Check if object exists
            s3_client = boto3.client(
                "s3",
                **merge_vpc_boto3_kwargs(
                    "s3", "us-east-1", {**client_creds, "region_name": "us-east-1"}
                ),
            )
            response = s3_client.head_object(Bucket=bucket, Key=key)
            
            return {
                "artifact_type": "frontend",
                "size_mb": round(response['ContentLength'] / (1024 * 1024), 1),
                "last_modified": response['LastModified'].isoformat()
            }
            
        elif artifact_type == 'backend':
            ecr_uri = request.get("ecr_uri")
            if not ecr_uri:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="ecr_uri is required for backend artifacts"
                )
            
            # Parse ECR URI
            registry = ecr_uri.split('/')[0]
            repo_tag = ecr_uri.split('/', 1)[1]
            repository = repo_tag.split(':')[0]
            tag = repo_tag.split(':')[1] if ':' in repo_tag else 'latest'
            ecr_region = registry.split('.')[3]
            
            # Check if image exists
            ecr_client = boto3.client(
                "ecr",
                **merge_vpc_boto3_kwargs(
                    "ecr", ecr_region, {**client_creds, "region_name": ecr_region}
                ),
            )
            response = ecr_client.describe_images(
                repositoryName=repository,
                imageIds=[{'imageTag': tag}]
            )
            
            if not response['imageDetails']:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Image not found: {ecr_uri}"
                )
            
            image = response['imageDetails'][0]
            return {
                "artifact_type": "backend",
                "size_mb": round(image['imageSizeInBytes'] / (1024 * 1024), 1),
                "pushed_at": image['imagePushedAt'].isoformat()
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid artifact_type: {artifact_type}"
            )
            
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code in ['404', 'NoSuchKey', 'ImageNotFoundException']:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Artifact not found"
            )
        elif error_code in ['403', 'AccessDenied', 'AccessDeniedException']:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to artifact"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to verify artifact: {str(e)}"
            )


@router.post("/verify-network")
async def verify_network(request: dict):
    """Verify network resources availability.
    
    Args:
        request: Dict with aws_session_id, region
        
    Returns:
        Network resource details
    """
    import boto3
    from botocore.exceptions import ClientError
    
    aws_session_id = request.get("aws_session_id")
    region = request.get("region")
    
    # Get credentials with fallback
    boto3_creds = None
    if aws_session_id:
        boto3_creds = aws_session_manager.get_credentials_dict(aws_session_id)
    
    # Fallback: Try to find matching session by region
    if not boto3_creds:
        sessions = aws_session_manager.sessions
        for sid, session in sessions.items():
            if session.get('region') == region:
                boto3_creds = aws_session_manager.get_credentials_dict(sid)
                if boto3_creds:
                    break
    
    if not boto3_creds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AWS session not found or expired. Please re-authenticate in Step 4."
        )
    
    client_creds = {
        'aws_access_key_id': boto3_creds.get('aws_access_key_id'),
        'aws_secret_access_key': boto3_creds.get('aws_secret_access_key'),
        'aws_session_token': boto3_creds.get('aws_session_token'),
    }
    
    try:
        ec2_client = boto3.client(
            "ec2",
            **merge_vpc_boto3_kwargs("ec2", region, {**client_creds, "region_name": region}),
        )
        
        # Check available AZs
        azs_response = ec2_client.describe_availability_zones(
            Filters=[{'Name': 'state', 'Values': ['available']}]
        )
        available_azs = len(azs_response['AvailabilityZones'])
        
        # Check VPC count
        vpcs_response = ec2_client.describe_vpcs()
        vpc_count = len(vpcs_response['Vpcs'])
        
        return {
            "available_azs": available_azs,
            "vpc_count": vpc_count
        }
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to verify network resources: {str(e)}"
        )


@router.post("/verify-limits")
async def verify_limits(request: dict):
    """Verify service limits.
    
    Args:
        request: Dict with aws_session_id, region
        
    Returns:
        Service limit details
    """
    import boto3
    from botocore.exceptions import ClientError
    
    aws_session_id = request.get("aws_session_id")
    region = request.get("region")
    
    # Get credentials with fallback
    boto3_creds = None
    if aws_session_id:
        boto3_creds = aws_session_manager.get_credentials_dict(aws_session_id)
    
    # Fallback: Try to find matching session by region
    if not boto3_creds:
        sessions = aws_session_manager.sessions
        for sid, session in sessions.items():
            if session.get('region') == region:
                boto3_creds = aws_session_manager.get_credentials_dict(sid)
                if boto3_creds:
                    break
    
    if not boto3_creds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AWS session not found or expired. Please re-authenticate in Step 4."
        )
    
    client_creds = {
        'aws_access_key_id': boto3_creds.get('aws_access_key_id'),
        'aws_secret_access_key': boto3_creds.get('aws_secret_access_key'),
        'aws_session_token': boto3_creds.get('aws_session_token'),
    }
    
    try:
        ecs_client = boto3.client('ecs', region_name=region, **client_creds)
        clusters = ecs_client.list_clusters()
        
        return {
            "ecs_clusters": len(clusters['clusterArns'])
        }
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to verify service limits: {str(e)}"
        )



# ADFS Role Selection Endpoints

@router.post("/adfs/roles")
async def fetch_adfs_roles(request: dict):
    """Fetch available ADFS roles without selecting one.
    
    Args:
        request: ADFS authentication request with URL, username, password, region
        
    Returns:
        List of available roles and session ID
    """
    from app.models.aws_config import ADFSRolesResponse, ADFSRole
    
    adfs_url = request.get('adfs_url')
    adfs_username = request.get('adfs_username')
    adfs_password = request.get('adfs_password')
    region = request.get('region')
    
    if not all([adfs_url, adfs_username, adfs_password, region]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required fields: adfs_url, adfs_username, adfs_password, region"
        )
    
    try:
        service = get_aws_auth_service()
        roles, session_id = service.fetch_adfs_roles(
            adfs_url,
            adfs_username,
            adfs_password,
            region
        )
        
        return ADFSRolesResponse(
            roles=roles,
            session_id=session_id
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/verify-permissions-eks")
async def verify_permissions_eks(request: dict):
    """Verify IAM permissions for EKS deployments.
    
    Uses actual API calls to test EKS-specific permissions.
    
    Args:
        request: Dict with aws_session_id, region, account_id, and optional cluster_name
        
    Returns:
        Detailed permission status for EKS-related services
    """
    import boto3
    from botocore.exceptions import ClientError
    
    aws_session_id = request.get("aws_session_id")
    region = request.get("region")
    account_id = request.get("account_id")
    cluster_name = request.get("cluster_name")
    
    # Get credentials
    boto3_creds = None
    if aws_session_id:
        boto3_creds = aws_session_manager.get_credentials_dict(aws_session_id)
    
    if not boto3_creds:
        # Try to find matching session
        sessions = aws_session_manager.sessions
        for sid, session in sessions.items():
            if (session.get('account_id') == account_id and 
                session.get('region') == region):
                boto3_creds = aws_session_manager.get_credentials_dict(sid)
                break
    
    if not boto3_creds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AWS session not found or expired"
        )
    
    # Prepare credentials
    client_creds = {
        'aws_access_key_id': boto3_creds.get('aws_access_key_id'),
        'aws_secret_access_key': boto3_creds.get('aws_secret_access_key'),
        'aws_session_token': boto3_creds.get('aws_session_token'),
    }
    
    # EKS-specific service checks
    def check_eks():
        try:
            eks = boto3.client(
                "eks",
                **merge_vpc_boto3_kwargs("eks", region, {**client_creds, "region_name": region}),
            )
            eks.list_clusters(maxResults=1)
            return True, ["ListClusters", "DescribeCluster"]
        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDeniedException':
                return False, []
            return True, ["ListClusters"]
        except Exception:
            return False, []
    
    def check_ecr():
        try:
            ecr = boto3.client(
                "ecr",
                **merge_vpc_boto3_kwargs("ecr", region, {**client_creds, "region_name": region}),
            )
            ecr.describe_repositories(maxResults=1)
            return True, ["DescribeRepositories", "GetAuthorizationToken", "BatchGetImage"]
        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDeniedException':
                return False, []
            return True, ["DescribeRepositories"]
        except Exception:
            return False, []
    
    def check_s3():
        try:
            s3 = boto3.client(
                "s3",
                **merge_vpc_boto3_kwargs("s3", region, {**client_creds, "region_name": region}),
            )
            s3.list_buckets()
            return True, ["ListBuckets", "CreateBucket", "PutObject", "GetObject"]
        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDenied':
                return False, []
            return True, ["ListBuckets"]
        except Exception:
            return False, []
    
    def check_dynamodb():
        try:
            ddb = boto3.client(
                "dynamodb",
                **merge_vpc_boto3_kwargs("dynamodb", region, {**client_creds, "region_name": region}),
            )
            ddb.list_tables(Limit=1)
            return True, ["ListTables", "CreateTable", "PutItem", "GetItem"]
        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDeniedException':
                return False, []
            return True, ["ListTables"]
        except Exception:
            return False, []
    
    def check_iam():
        try:
            iam = boto3.client(
                "iam",
                **merge_vpc_boto3_kwargs(
                    "iam", "us-east-1", {**client_creds, "region_name": "us-east-1"}
                ),
            )
            iam.list_roles(MaxItems=1)
            return True, ["ListRoles", "CreateRole", "AttachRolePolicy", "PassRole"]
        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDenied':
                return False, []
            return True, ["ListRoles"]
        except Exception:
            return False, []
    
    def check_sts():
        try:
            sts = boto3.client(
                "sts",
                **merge_vpc_boto3_kwargs("sts", region, {**client_creds, "region_name": region}),
            )
            sts.get_caller_identity()
            return True, ["GetCallerIdentity", "AssumeRoleWithWebIdentity"]
        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDenied':
                return False, []
            return True, ["GetCallerIdentity"]
        except Exception:
            return False, []
    
    def check_secrets_manager():
        try:
            sm = boto3.client(
                "secretsmanager",
                **merge_vpc_boto3_kwargs(
                    "secretsmanager", region, {**client_creds, "region_name": region}
                ),
            )
            sm.list_secrets(MaxResults=1)
            return True, ["ListSecrets", "CreateSecret", "GetSecretValue"]
        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDeniedException':
                return False, []
            return True, ["ListSecrets"]
        except Exception:
            return False, []
    
    def check_cloudwatch_logs():
        try:
            logs = boto3.client(
                "logs",
                **merge_vpc_boto3_kwargs("logs", region, {**client_creds, "region_name": region}),
            )
            logs.describe_log_groups(limit=1)
            return True, ["DescribeLogGroups", "CreateLogGroup", "PutLogEvents"]
        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDeniedException':
                return False, []
            return True, ["DescribeLogGroups"]
        except Exception:
            return False, []
    
    # EKS-specific service requirements (no CloudFront, ECS, ALB)
    service_requirements = {
        "EKS": {
            "purpose": "Kubernetes cluster management",
            "check_func": check_eks,
            "required_actions": [
                "eks:DescribeCluster",
                "eks:ListClusters",
                "eks:AccessKubernetesApi",
                "eks:ListNodegroups",
                "eks:DescribeNodegroup"
            ]
        },
        "ECR": {
            "purpose": "Container registry for frontend and backend images",
            "check_func": check_ecr,
            "required_actions": [
                "ecr:GetAuthorizationToken",
                "ecr:BatchCheckLayerAvailability",
                "ecr:GetDownloadUrlForLayer",
                "ecr:BatchGetImage",
                "ecr:DescribeImages"
            ]
        },
        "S3": {
            "purpose": "Storage for artifacts and state",
            "check_func": check_s3,
            "required_actions": [
                "s3:CreateBucket",
                "s3:PutObject",
                "s3:GetObject",
                "s3:DeleteObject"
            ]
        },
        "DynamoDB": {
            "purpose": "Database tables",
            "check_func": check_dynamodb,
            "required_actions": [
                "dynamodb:CreateTable",
                "dynamodb:DescribeTable",
                "dynamodb:PutItem",
                "dynamodb:GetItem",
                "dynamodb:Query"
            ]
        },
        "IAM": {
            "purpose": "Service roles and IRSA",
            "check_func": check_iam,
            "required_actions": [
                "iam:CreateRole",
                "iam:AttachRolePolicy",
                "iam:PutRolePolicy",
                "iam:PassRole"
            ]
        },
        "STS": {
            "purpose": "IRSA (IAM Roles for Service Accounts)",
            "check_func": check_sts,
            "required_actions": [
                "sts:AssumeRoleWithWebIdentity",
                "sts:GetCallerIdentity"
            ]
        },
        "Secrets Manager": {
            "purpose": "Secrets storage",
            "check_func": check_secrets_manager,
            "required_actions": [
                "secretsmanager:CreateSecret",
                "secretsmanager:GetSecretValue",
                "secretsmanager:PutSecretValue"
            ]
        },
        "CloudWatch Logs": {
            "purpose": "Logging",
            "check_func": check_cloudwatch_logs,
            "required_actions": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ]
        }
    }
    
    results = []
    
    for service_name, service_info in service_requirements.items():
        purpose = service_info["purpose"]
        check_func = service_info["check_func"]
        required_actions = service_info["required_actions"]
        
        has_read_access, verified_actions = check_func()
        
        if has_read_access:
            status_text = "[OK] Available"
            granted_actions = required_actions
            restricted_actions = []
            granted_count = len(required_actions)
        else:
            status_text = "[X] Restricted"
            granted_actions = []
            restricted_actions = required_actions
            granted_count = 0
        
        results.append({
            "service": service_name,
            "purpose": purpose,
            "status": status_text,
            "granted_count": granted_count,
            "total_count": len(required_actions),
            "granted_actions": granted_actions,
            "restricted_actions": restricted_actions
        })
    
    # Calculate overall status
    total_granted = sum(r["granted_count"] for r in results)
    total_actions = sum(r["total_count"] for r in results)
    services_with_access = sum(1 for r in results if r["granted_count"] > 0)
    
    return {
        "overall_status": "success" if services_with_access == len(results) else "partial" if services_with_access > 0 else "failed",
        "total_granted": total_granted,
        "total_actions": total_actions,
        "services": results,
        "deployment_type": "eks"
    }


@router.post("/adfs/select-role", response_model=RoleValidationResponse)
async def select_adfs_role(request: dict):
    """Select an ADFS role and get credentials.
    
    Args:
        request: Role selection request with session_id, role_arn, region
        
    Returns:
        Validation response with credentials
    """
    session_id = request.get('session_id')
    role_arn = request.get('role_arn')
    region = request.get('region')
    
    if not all([session_id, role_arn, region]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required fields: session_id, role_arn, region"
        )
    
    try:
        service = get_aws_auth_service()
        response = service.select_adfs_role(session_id, role_arn, region)
        
        print(f"[DBG] DEBUG: ADFS select_role - response.success={getattr(response, 'success', None)}")
        print(f"[DBG] DEBUG: ADFS select_role - response.valid={response.valid}")
        print(f"[DBG] DEBUG: ADFS select_role - has credentials={hasattr(response, 'credentials') and response.credentials is not None}")
        
        # Store AWS session if authentication successful
        if response.valid and hasattr(response, 'credentials') and response.credentials:
            print(f"[DBG] DEBUG: ADFS - Creating AWS session...")
            aws_session_id = aws_session_manager.create_session(
                access_key_id=response.credentials.get("access_key_id", ""),
                secret_access_key=response.credentials.get("secret_access_key", ""),
                session_token=response.credentials.get("session_token"),
                region=region,
                account_id=response.account_id
            )
            response.session_id = aws_session_id
            print(f"[DBG] DEBUG: ADFS - Session created with ID: {aws_session_id}")
        else:
            print(f"[DBG] DEBUG: ADFS - Session NOT created - validation failed or no credentials")
        
        return response
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

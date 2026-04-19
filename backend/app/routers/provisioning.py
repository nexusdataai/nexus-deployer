"""
Provisioning API endpoints for infrastructure resource management.

Provides REST API access to provision, verify, and manage
call-processing infrastructure resources (DynamoDB, S3, SSM, Secrets, Glue, CloudWatch).
"""
import uuid
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/provisioning", tags=["provisioning"])

# In-memory storage for provisioning jobs
_provisioning_jobs: Dict[str, Dict[str, Any]] = {}


class ProvisioningStatus(str, Enum):
    """Status of a provisioning operation."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ResourceTypeEnum(str, Enum):
    """Resource types that can be provisioned."""
    DYNAMODB = "dynamodb"
    S3 = "s3"
    SSM = "ssm"
    SECRETS = "secrets"
    GLUE = "glue"
    CLOUDWATCH = "cloudwatch"


class ProvisioningRequest(BaseModel):
    """Request model for provisioning operations."""
    environment: str = Field(..., description="Target environment (dev, stage, test, prod)")
    region: str = Field(default="ap-southeast-1", description="AWS region")
    resource_types: Optional[List[ResourceTypeEnum]] = Field(
        default=None, 
        description="Specific resource types to provision. None = all types"
    )
    aws_session_id: Optional[str] = Field(
        default=None,
        description="AWS session ID for using wizard's credentials"
    )
    endpoint_url: Optional[str] = Field(
        default=None,
        description="Custom AWS endpoint URL (for LocalStack)"
    )


class ResourceStatusItem(BaseModel):
    """Status of a single provisioned resource."""
    resource_type: str
    resource_name: str
    status: str
    message: str
    created_at: Optional[str] = None
    error: Optional[str] = None


class ProvisioningStatusResponse(BaseModel):
    """Response model for provisioning status."""
    provisioning_id: str
    status: ProvisioningStatus
    progress: int = Field(..., ge=0, le=100, description="Progress percentage 0-100")
    current_stage: str
    environment: str
    region: str
    resources_completed: List[ResourceStatusItem] = []
    resources_pending: List[str] = []
    errors: List[str] = []
    report: Optional[Dict[str, Any]] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class VerificationResultItem(BaseModel):
    """Result of verifying a single resource."""
    resource_type: str
    resource_name: str
    status: str
    details: str
    error: Optional[str] = None


class VerificationResponse(BaseModel):
    """Response model for verification operations."""
    environment: str
    region: str
    verified_at: str
    results: List[VerificationResultItem]
    passed_count: int
    failed_count: int
    all_passed: bool


class DryRunResponse(BaseModel):
    """Response model for dry-run operations."""
    environment: str
    region: str
    resources_to_create: List[ResourceStatusItem]
    total_count: int


def _run_provisioning_job(
    provisioning_id: str,
    environment: str,
    region: str,
    resource_types: Optional[List[str]],
    endpoint_url: Optional[str],
    credentials: Optional[Dict[str, str]]
):
    """Background task to run provisioning."""
    from app.services.infra_provisioning.orchestrator import ProvisioningOrchestrator
    from app.services.infra_provisioning.models import ResourceStatusType
    
    job = _provisioning_jobs.get(provisioning_id)
    if not job:
        return
    
    job['status'] = ProvisioningStatus.RUNNING
    job['started_at'] = datetime.utcnow().isoformat()
    
    try:
        # Create orchestrator
        orchestrator = ProvisioningOrchestrator(
            environment=environment,
            region=region,
            dry_run=False,
            endpoint_url=endpoint_url,
        )
        
        all_results = []
        stages = [
            ("dynamodb", "Provisioning DynamoDB tables", orchestrator.provision_dynamodb),
            ("s3", "Provisioning S3 buckets", orchestrator.provision_s3),
            ("ssm", "Provisioning SSM parameters", orchestrator.provision_ssm),
            ("secrets", "Provisioning Secrets Manager secrets", orchestrator.provision_secrets),
            ("glue", "Provisioning Glue resources", orchestrator.provision_glue),
            ("cloudwatch", "Provisioning CloudWatch log groups", orchestrator.provision_cloudwatch),
        ]
        
        total_stages = len(stages)
        completed_stages = 0
        
        for stage_name, stage_desc, provision_func in stages:
            # Skip if specific resource types requested and this isn't one of them
            if resource_types and stage_name not in resource_types:
                completed_stages += 1
                continue
            
            job['current_stage'] = stage_desc
            job['progress'] = int((completed_stages / total_stages) * 100)
            
            try:
                results = provision_func()
                for result in results:
                    resource_item = ResourceStatusItem(
                        resource_type=result.resource_type.value if hasattr(result.resource_type, 'value') else str(result.resource_type),
                        resource_name=result.resource_name,
                        status=result.status.value if hasattr(result.status, 'value') else str(result.status),
                        message=result.message,
                        created_at=result.created_at.isoformat() if result.created_at else None,
                        error=result.error,
                    )
                    all_results.append(resource_item)
                    job['resources_completed'].append(resource_item.model_dump())
                    
                    if result.status == ResourceStatusType.FAILED:
                        job['errors'].append(f"{result.resource_name}: {result.error or result.message}")
                        
            except Exception as e:
                logger.error(f"Error provisioning {stage_name}: {e}")
                job['errors'].append(f"{stage_name}: {str(e)}")
            
            completed_stages += 1
            
            # Update pending list
            remaining = [s[0] for s in stages[completed_stages:] if not resource_types or s[0] in resource_types]
            job['resources_pending'] = remaining
        
        # Final status
        job['progress'] = 100
        job['current_stage'] = "Completed"
        job['status'] = ProvisioningStatus.COMPLETED if not job['errors'] else ProvisioningStatus.FAILED
        job['completed_at'] = datetime.utcnow().isoformat()
        
        # Build report
        success_count = sum(1 for r in all_results if r.status in ['created', 'updated'])
        already_existed_count = sum(1 for r in all_results if r.status == 'already_exists')
        failed_count = sum(1 for r in all_results if r.status == 'failed')
        
        job['report'] = {
            'environment': environment,
            'region': region,
            'total_resources': len(all_results),
            'success_count': success_count,
            'already_existed_count': already_existed_count,
            'failed_count': failed_count,
            'overall_success': failed_count == 0,
        }
        
    except Exception as e:
        logger.error(f"Provisioning job {provisioning_id} failed: {e}")
        job['status'] = ProvisioningStatus.FAILED
        job['errors'].append(str(e))
        job['completed_at'] = datetime.utcnow().isoformat()


@router.post("/provision", response_model=ProvisioningStatusResponse)
async def start_provisioning(
    request: ProvisioningRequest,
    background_tasks: BackgroundTasks
):
    """
    Start infrastructure provisioning for an environment.
    
    This endpoint triggers the ProvisioningOrchestrator to create:
    - DynamoDB tables (transformation-system, license, wxcc-task-tracking)
    - S3 buckets (call-data, wxcc-simulator, journey-logs, journey-reports)
    - SSM parameters (aws, server, cognito, wxcc, s3, dynamodb, glue, cloudwatch)
    - Secrets Manager secrets (api-keys, wxcc, openai, license, anthropic, github)
    - Glue database and tables (analytics database, wxcc_calls table)
    - CloudWatch log groups
    
    Returns a provisioning_id that can be used to poll for status.
    """
    # Validate environment
    valid_environments = ["dev", "stage", "test", "prod"]
    if request.environment not in valid_environments:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid environment '{request.environment}'. Must be one of: {valid_environments}"
        )
    
    # Get AWS credentials if session ID provided
    credentials = None
    if request.aws_session_id:
        try:
            from app.services.aws_session_manager import aws_session_manager
            session = aws_session_manager.get_session(request.aws_session_id)
            if session:
                credentials = {
                    'aws_access_key_id': session.get('access_key_id'),
                    'aws_secret_access_key': session.get('secret_access_key'),
                    'aws_session_token': session.get('session_token'),
                }
            else:
                raise HTTPException(
                    status_code=401,
                    detail="AWS session expired or not found. Please re-authenticate."
                )
        except ImportError:
            logger.warning("AWS session manager not available")
    
    # Create provisioning job
    provisioning_id = str(uuid.uuid4())[:8]
    resource_type_values = [rt.value for rt in request.resource_types] if request.resource_types else None
    
    _provisioning_jobs[provisioning_id] = {
        'provisioning_id': provisioning_id,
        'status': ProvisioningStatus.PENDING,
        'progress': 0,
        'current_stage': 'Initializing',
        'environment': request.environment,
        'region': request.region,
        'resources_completed': [],
        'resources_pending': resource_type_values or ['dynamodb', 's3', 'ssm', 'secrets', 'glue', 'cloudwatch'],
        'errors': [],
        'report': None,
        'started_at': None,
        'completed_at': None,
    }
    
    # Start background task
    background_tasks.add_task(
        _run_provisioning_job,
        provisioning_id,
        request.environment,
        request.region,
        resource_type_values,
        request.endpoint_url,
        credentials
    )
    
    job = _provisioning_jobs[provisioning_id]
    return ProvisioningStatusResponse(
        provisioning_id=provisioning_id,
        status=job['status'],
        progress=job['progress'],
        current_stage=job['current_stage'],
        environment=job['environment'],
        region=job['region'],
        resources_completed=[],
        resources_pending=job['resources_pending'],
        errors=[],
    )


@router.get("/{provisioning_id}/status", response_model=ProvisioningStatusResponse)
async def get_provisioning_status(provisioning_id: str):
    """
    Get the current status of a provisioning operation.
    
    Use this endpoint to poll for progress updates during provisioning.
    """
    job = _provisioning_jobs.get(provisioning_id)
    if not job:
        raise HTTPException(status_code=404, detail="Provisioning job not found")
    
    return ProvisioningStatusResponse(
        provisioning_id=provisioning_id,
        status=job['status'],
        progress=job['progress'],
        current_stage=job['current_stage'],
        environment=job['environment'],
        region=job['region'],
        resources_completed=[ResourceStatusItem(**r) for r in job['resources_completed']],
        resources_pending=job['resources_pending'],
        errors=job['errors'],
        report=job['report'],
        started_at=job.get('started_at'),
        completed_at=job.get('completed_at'),
    )


@router.post("/verify", response_model=VerificationResponse)
async def verify_provisioning(request: ProvisioningRequest):
    """
    Verify all provisioned resources exist and are accessible.
    
    This endpoint checks that all infrastructure resources for the specified
    environment have been created and are in the expected state.
    """
    from app.services.infra_provisioning.verification_service import VerificationService
    from app.services.aws_session_manager import aws_session_manager
    
    # Validate environment
    valid_environments = ["dev", "stage", "test", "prod"]
    if request.environment not in valid_environments:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid environment '{request.environment}'. Must be one of: {valid_environments}"
        )
    
    # Get AWS credentials from session if provided
    boto3_creds = None
    if request.aws_session_id:
        boto3_creds = aws_session_manager.get_credentials_dict(request.aws_session_id)
    
    try:
        verifier = VerificationService(
            environment=request.environment,
            region=request.region,
            endpoint_url=request.endpoint_url,
            credentials=boto3_creds,
        )
        
        report = verifier.verify_all()
        
        results = [
            VerificationResultItem(
                resource_type=r.resource_type.value if hasattr(r.resource_type, 'value') else str(r.resource_type),
                resource_name=r.resource_name,
                status=r.status.value if hasattr(r.status, 'value') else str(r.status),
                details=r.details if hasattr(r, 'details') else '',
                error=r.error if hasattr(r, 'error') else None,
            )
            for r in report.results
        ]
        
        return VerificationResponse(
            environment=report.environment,
            region=report.region,
            verified_at=report.verified_at.isoformat() if hasattr(report.verified_at, 'isoformat') else str(report.verified_at),
            results=results,
            passed_count=report.passed_count,
            failed_count=report.failed_count,
            all_passed=report.all_passed,
        )
        
    except Exception as e:
        logger.error(f"Verification failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dry-run", response_model=DryRunResponse)
async def dry_run_provisioning(request: ProvisioningRequest):
    """
    Perform a dry-run to show what would be provisioned.
    
    This endpoint validates the configuration and returns a list of resources
    that would be created, without actually creating them.
    """
    from app.services.infra_provisioning.orchestrator import ProvisioningOrchestrator
    
    # Validate environment
    valid_environments = ["dev", "stage", "test", "prod"]
    if request.environment not in valid_environments:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid environment '{request.environment}'. Must be one of: {valid_environments}"
        )
    
    try:
        orchestrator = ProvisioningOrchestrator(
            environment=request.environment,
            region=request.region,
            dry_run=True,
            endpoint_url=request.endpoint_url,
        )
        
        report = orchestrator.provision_all()
        
        resources = [
            ResourceStatusItem(
                resource_type=r.resource_type.value if hasattr(r.resource_type, 'value') else str(r.resource_type),
                resource_name=r.resource_name,
                status=r.status.value if hasattr(r.status, 'value') else str(r.status),
                message=r.message,
            )
            for r in report.resources
        ]
        
        return DryRunResponse(
            environment=request.environment,
            region=request.region,
            resources_to_create=resources,
            total_count=len(resources),
        )
        
    except Exception as e:
        logger.error(f"Dry-run failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

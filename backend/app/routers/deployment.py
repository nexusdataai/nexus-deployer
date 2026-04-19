"""
Deployment API endpoints
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks, Query as QueryParam
from typing import Optional, List, Dict
from pydantic import BaseModel

from app.models.deployment import (
    DeploymentRequest,
    DeploymentResponse,
    DeploymentLogsResponse,
)
from app.models.stack_detection import (
    StackDetectionRequest,
    StackDetectionResult,
)
from app.services.deployment_service import deployment_service
from app.services.stack_detection_service import StackDetectionService
from app.services.aws_session_manager import aws_session_manager
from app.services.tinydb_deployment_state_service import tinydb_deployment_state_service
from app.services.installation_tracker import get_installation_tracker

router = APIRouter(prefix="/api/deployment", tags=["deployment"])


# Response models for deployment state
class DeploymentStateStack(BaseModel):
    stack_name: str
    stack_type: Optional[str] = None
    region: Optional[str] = None
    deployed_at: Optional[str] = None


class DeploymentStateResponse(BaseModel):
    capability_name: str
    capability_id: Optional[str] = None
    environment: str
    region: str
    stacks: List[DeploymentStateStack]
    last_deployment: Optional[str] = None
    metadata: Optional[dict] = None
    # Requirement 11.2: Indicate which landing zone each capability belongs to
    landing_zone_id: Optional[str] = None
    account_id: Optional[str] = None
    # Strategy field to distinguish discovered vs deployed capabilities
    strategy: Optional[str] = None


class DeploymentStateListResponse(BaseModel):
    deployments: List[DeploymentStateResponse]
    total_count: int


@router.get("/states", response_model=DeploymentStateListResponse)
async def list_deployment_states(
    capability_name: Optional[str] = None,
    environment: Optional[str] = None,
    region: Optional[str] = None,
    landing_zone_id: Optional[str] = QueryParam(None, description="Filter by landing zone ID (Requirement 11.3)")
):
    """
    List all deployment states from TinyDB
    
    This endpoint returns the deployment state for all capabilities that have been
    deployed through the wizard or discovered from AWS. Use this to show which 
    capabilities are already deployed in which environments.
    
    Requirements:
    - 11.2: Include landing_zone_id to indicate which landing zone each capability belongs to
    - 11.3: Allow filtering capabilities by landing zone
    - 11.4: Maintain separate discovery timestamps per landing zone
    - 11.5: Display capabilities with same name in different accounts as separate entries
    """
    try:
        # Get deployments from deployment state service
        deployments = tinydb_deployment_state_service.list_deployments(
            capability_name=capability_name,
            environment=environment,
            region=region
        )
        
        # Get installation tracker to access landing_zone_id and account_id
        tracker = get_installation_tracker()
        
        # Build a lookup map from installations table for landing zone info
        # Key: (capability_name, environment) -> installation record
        installation_lookup: Dict[tuple, dict] = {}
        all_installations = tracker.list_installations(
            capability_name=capability_name,
            environment=environment,
            limit=1000  # Get all relevant installations
        )
        
        for inst in all_installations:
            key = (inst.get("capability_name", "").lower(), inst.get("environment", "").lower())
            # Prefer discovered installations as they have landing_zone_id
            if key not in installation_lookup or inst.get("strategy") == "DISCOVERED":
                installation_lookup[key] = inst
        
        # Convert to response format, merging landing zone info
        deployment_responses = []
        seen_keys = set()  # Track (capability_name, environment, account_id) to handle Requirement 11.5
        
        for dep in deployments:
            cap_name = dep.get('capability_name', '')
            env = dep.get('environment', '')
            lookup_key = (cap_name.lower(), env.lower())
            
            # Get landing zone info from installation record
            inst = installation_lookup.get(lookup_key, {})
            dep_landing_zone_id = inst.get('landing_zone_id')
            dep_account_id = inst.get('account_id')
            dep_strategy = inst.get('strategy')
            
            # Apply landing zone filter (Requirement 11.3)
            if landing_zone_id and dep_landing_zone_id != landing_zone_id:
                continue
            
            # Create unique key for deduplication (Requirement 11.5)
            unique_key = (cap_name.lower(), env.lower(), dep_account_id or '')
            if unique_key in seen_keys:
                continue
            seen_keys.add(unique_key)
            
            stacks = [
                DeploymentStateStack(
                    stack_name=s.get('stack_name', ''),
                    stack_type=s.get('stack_type'),
                    region=s.get('region'),
                    deployed_at=s.get('deployed_at')
                )
                for s in dep.get('stacks', [])
            ]
            
            deployment_responses.append(DeploymentStateResponse(
                capability_name=cap_name,
                capability_id=dep.get('capability_id'),
                environment=env,
                region=dep.get('region', ''),
                stacks=stacks,
                last_deployment=dep.get('last_deployment'),
                metadata=dep.get('metadata'),
                landing_zone_id=dep_landing_zone_id,
                account_id=dep_account_id,
                strategy=dep_strategy
            ))
        
        # Also include discovered installations that may not be in deployments table
        # This ensures discovered capabilities are shown even if not in deployment state
        for inst in all_installations:
            if inst.get('strategy') != 'DISCOVERED':
                continue
                
            cap_name = inst.get('capability_name', '')
            env = inst.get('environment', '')
            inst_landing_zone_id = inst.get('landing_zone_id')
            inst_account_id = inst.get('account_id')
            
            # Apply landing zone filter (Requirement 11.3)
            if landing_zone_id and inst_landing_zone_id != landing_zone_id:
                continue
            
            # Check if already added from deployments
            unique_key = (cap_name.lower(), env.lower(), inst_account_id or '')
            if unique_key in seen_keys:
                continue
            seen_keys.add(unique_key)
            
            # Build stacks from stacks_detail if available
            stacks_detail = inst.get('stacks_detail', [])
            stacks = [
                DeploymentStateStack(
                    stack_name=s.get('stack_name', ''),
                    stack_type=s.get('stack_type'),
                    region=s.get('region'),
                    deployed_at=inst.get('discovered_at')
                )
                for s in stacks_detail
            ]
            
            deployment_responses.append(DeploymentStateResponse(
                capability_name=cap_name,
                capability_id=None,
                environment=env,
                region=inst.get('region', ''),
                stacks=stacks,
                last_deployment=inst.get('discovered_at'),
                metadata=None,
                landing_zone_id=inst_landing_zone_id,
                account_id=inst_account_id,
                strategy='DISCOVERED'
            ))
        
        return DeploymentStateListResponse(
            deployments=deployment_responses,
            total_count=len(deployment_responses)
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/states/{capability_name}/{environment}", response_model=DeploymentStateResponse)
async def get_deployment_state(capability_name: str, environment: str):
    """
    Get deployment state for a specific capability and environment.
    
    Includes landing zone information if available (Requirement 11.2).
    """
    try:
        state = tinydb_deployment_state_service.load_deployment_state(
            capability_name=capability_name,
            environment=environment
        )
        
        if not state:
            raise HTTPException(
                status_code=404,
                detail=f"No deployment state found for {capability_name} in {environment}"
            )
        
        # Get landing zone info from installation tracker
        tracker = get_installation_tracker()
        installations = tracker.list_installations(
            capability_name=capability_name,
            environment=environment,
            limit=1
        )
        
        landing_zone_id = None
        account_id = None
        strategy = None
        
        if installations:
            inst = installations[0]
            landing_zone_id = inst.get('landing_zone_id')
            account_id = inst.get('account_id')
            strategy = inst.get('strategy')
        
        stacks = [
            DeploymentStateStack(
                stack_name=s.get('stack_name', ''),
                stack_type=s.get('stack_type'),
                region=s.get('region'),
                deployed_at=s.get('deployed_at')
            )
            for s in state.get('stacks', [])
        ]
        
        return DeploymentStateResponse(
            capability_name=state.get('capability_name', ''),
            capability_id=state.get('capability_id'),
            environment=state.get('environment', ''),
            region=state.get('region', ''),
            stacks=stacks,
            last_deployment=state.get('last_deployment'),
            metadata=state.get('metadata'),
            landing_zone_id=landing_zone_id,
            account_id=account_id,
            strategy=strategy
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/start", response_model=DeploymentResponse)
async def start_deployment(request: DeploymentRequest, background_tasks: BackgroundTasks):
    """
    Start a new deployment
    """
    try:
        # Create deployment
        deployment_id = deployment_service.create_deployment(request)
        
        # Start deployment in background
        background_tasks.add_task(deployment_service.start_deployment, deployment_id)
        
        # Return initial status
        deployment = deployment_service.get_deployment(deployment_id)
        if not deployment:
            raise HTTPException(status_code=500, detail="Failed to create deployment")
        
        return deployment
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{deployment_id}", response_model=DeploymentResponse)
async def get_deployment_status(deployment_id: str):
    """
    Get deployment status
    """
    deployment = deployment_service.get_deployment(deployment_id)
    
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    
    return deployment


@router.get("/{deployment_id}/logs", response_model=DeploymentLogsResponse)
async def get_deployment_logs(deployment_id: str, limit: Optional[int] = None):
    """
    Get deployment logs
    """
    logs = deployment_service.get_deployment_logs(deployment_id, limit)
    
    return DeploymentLogsResponse(
        deployment_id=deployment_id,
        logs=logs,
        total_count=len(logs),
    )


@router.post("/{deployment_id}/cancel")
async def cancel_deployment(deployment_id: str):
    """
    Cancel a running deployment
    """
    success = deployment_service.cancel_deployment(deployment_id)
    
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Deployment cannot be cancelled (not found or already completed)"
        )
    
    return {"message": "Deployment cancelled successfully"}


@router.post("/detect-stacks", response_model=StackDetectionResult)
async def detect_stacks(request: StackDetectionRequest):
    """
    Detect existing stacks by querying CloudFormation and recommend deployment strategy
    
    This endpoint queries actual CloudFormation stack states and applies the deployment
    decision tree logic to recommend the appropriate strategy (CLEAN_DEPLOY or UPDATE_EXISTING).
    """
    try:
        # Get AWS credentials from session - session manager handles refresh automatically
        credentials = None
        if request.aws_session_id:
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
        
        # Create detection service with credentials
        detection_service = StackDetectionService(credentials=credentials)
        
        # Create detection service with credentials
        detection_service = StackDetectionService(credentials=credentials)
        
        # Detect existing stacks from CloudFormation
        result = detection_service.detect_existing_stacks(
            capability_name=request.capability_name,
            environment=request.environment,
            region=request.region,
            deploy_frontend=request.deploy_frontend,
            deploy_backend=request.deploy_backend
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/complete-cleanup")
async def complete_cleanup(
    capability_name: str,
    environment: str,
    region: str,
    account_id: str,
    aws_session_id: Optional[str] = None,
    installation_id: Optional[str] = None
):
    """
    Nuclear option: Complete cleanup of ALL resources for a capability
    This removes all stacks, S3 buckets, ECR repos, log groups, and state files
    
    If the AWS session expires, it will attempt to re-authenticate using stored
    ADFS credentials if available.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        from app.services.cleanup_service import CleanupService
        from app.services.secure_credential_store import get_credential_store
        
        # Get AWS credentials - session manager handles refresh automatically
        credentials = None
        if aws_session_id:
            session = aws_session_manager.get_session(aws_session_id)
            if session:
                credentials = {
                    'aws_access_key_id': session.get('access_key_id'),
                    'aws_secret_access_key': session.get('secret_access_key'),
                    'aws_session_token': session.get('session_token'),
                }
            else:
                # Session expired - try to re-authenticate using stored ADFS credentials
                logger.info(f"Session expired, attempting ADFS re-authentication...")
                
                credential_store = get_credential_store()
                
                # Try to find an installation_id to use for re-authentication
                # Priority: provided installation_id > search by capability/environment
                target_installation_id = installation_id
                
                if not target_installation_id:
                    # Try to find a recent installation for this capability/environment
                    try:
                        from app.services.installation_tracker import get_installation_tracker
                        tracker = get_installation_tracker()
                        installations = tracker.list_installations(
                            capability_name=capability_name,
                            environment=environment
                        )
                        if installations:
                            # Use the most recent installation
                            target_installation_id = installations[0].get('installation_id')
                            logger.info(f"Found installation for re-auth: {target_installation_id}")
                    except Exception as e:
                        logger.warning(f"Could not find installation: {e}")
                
                # Attempt re-authentication if we have an installation_id
                if target_installation_id and credential_store.can_reauthenticate(target_installation_id):
                    logger.info(f"Attempting ADFS re-authentication for {target_installation_id}")
                    new_creds = credential_store.reauthenticate_adfs(target_installation_id)
                    
                    if new_creds:
                        credentials = {
                            'aws_access_key_id': new_creds.get('access_key_id'),
                            'aws_secret_access_key': new_creds.get('secret_access_key'),
                            'aws_session_token': new_creds.get('session_token'),
                        }
                        logger.info("ADFS re-authentication successful")
                    else:
                        logger.warning("ADFS re-authentication failed")
                
                if not credentials:
                    raise HTTPException(
                        status_code=401,
                        detail="AWS session expired and re-authentication failed. Please re-authenticate in Step 5 (AWS Configuration)."
                    )
        else:
            raise HTTPException(
                status_code=401,
                detail="AWS session ID is required. Please authenticate in Step 5 (AWS Configuration)."
            )
        
        # Create cleanup service
        cleanup_service = CleanupService(credentials=credentials)
        
        # Collect logs
        logs = []
        def log_callback(message: str):
            logs.append(message)
        
        # Perform complete cleanup
        results = cleanup_service.complete_cleanup(
            capability_name=capability_name,
            environment=environment,
            region=region,
            account_id=account_id,
            callback=log_callback
        )
        
        return {
            "success": results['success'],
            "summary": results['summary'],
            "stacks_deleted": results['stacks_deleted'],
            "stacks_failed": results['stacks_failed'],
            "resources_cleaned": results['resources_cleaned'],
            "errors": results['errors'],
            "logs": logs
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# In-memory storage for deletion jobs
_deletion_jobs: Dict[str, Dict] = {}


class DeletionJobRequest(BaseModel):
    capability_name: str
    environment: str
    region: str
    account_id: str
    aws_session_id: Optional[str] = None


class DeletionJobResponse(BaseModel):
    deletion_id: str
    status: str
    progress: int
    message: str


class DeletionLogsResponse(BaseModel):
    deletion_id: str
    logs: List[dict]
    total_count: int


def run_deletion_job(deletion_id: str, capability_name: str, environment: str, 
                     region: str, account_id: str, credentials: dict):
    """Background task to run deletion"""
    import logging
    from datetime import datetime
    from app.services.cleanup_service import CleanupService
    
    logger = logging.getLogger(__name__)
    
    job = _deletion_jobs.get(deletion_id)
    if not job:
        return
    
    job['status'] = 'running'
    job['started_at'] = datetime.utcnow().isoformat()
    
    def log_callback(message: str):
        log_entry = {
            'timestamp': datetime.utcnow().isoformat(),
            'message': message
        }
        job['logs'].append(log_entry)
        
        # Update progress based on message content
        if 'STEP 1' in message:
            job['progress'] = 10
            job['current_stage'] = 'Disabling deletion protection'
        elif 'STEP 2' in message:
            job['progress'] = 20
            job['current_stage'] = 'Cleaning orphaned resources'
        elif 'STEP 3' in message:
            job['progress'] = 30
            job['current_stage'] = 'Emptying S3 buckets'
        elif 'STEP 4' in message:
            job['progress'] = 40
            job['current_stage'] = 'Deleting ECR repositories'
        elif 'STEP 5' in message:
            job['progress'] = 50
            job['current_stage'] = 'Deleting CloudWatch logs'
        elif 'STEP 6' in message:
            job['progress'] = 60
            job['current_stage'] = 'Deleting CloudFormation stacks'
        elif 'STEP 7' in message:
            job['progress'] = 90
            job['current_stage'] = 'Cleaning up state'
        elif 'CLEANUP SUMMARY' in message:
            job['progress'] = 100
            job['current_stage'] = 'Complete'
    
    try:
        cleanup_service = CleanupService(credentials=credentials)
        results = cleanup_service.complete_cleanup(
            capability_name=capability_name,
            environment=environment,
            region=region,
            account_id=account_id,
            callback=log_callback
        )
        
        job['status'] = 'completed' if results['success'] else 'failed'
        job['progress'] = 100
        job['results'] = results
        job['completed_at'] = datetime.utcnow().isoformat()
        
        if not results['success']:
            job['error'] = f"Failed to delete {len(results['stacks_failed'])} stacks"
            
    except Exception as e:
        logger.error(f"Deletion job {deletion_id} failed: {e}")
        job['status'] = 'failed'
        job['error'] = str(e)
        job['completed_at'] = datetime.utcnow().isoformat()


@router.post("/start-deletion", response_model=DeletionJobResponse)
async def start_deletion(request: DeletionJobRequest, background_tasks: BackgroundTasks):
    """
    Start an async deletion job with real-time log polling
    """
    import uuid
    from datetime import datetime
    
    # Validate AWS session
    credentials = None
    if request.aws_session_id:
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
                detail="AWS session expired. Please re-authenticate."
            )
    else:
        raise HTTPException(
            status_code=401,
            detail="AWS session ID is required."
        )
    
    # Create deletion job
    deletion_id = str(uuid.uuid4())[:8]
    _deletion_jobs[deletion_id] = {
        'deletion_id': deletion_id,
        'capability_name': request.capability_name,
        'environment': request.environment,
        'region': request.region,
        'status': 'pending',
        'progress': 0,
        'current_stage': 'Initializing',
        'logs': [],
        'created_at': datetime.utcnow().isoformat(),
        'error': None,
        'results': None
    }
    
    # Start background task
    background_tasks.add_task(
        run_deletion_job,
        deletion_id,
        request.capability_name,
        request.environment,
        request.region,
        request.account_id,
        credentials
    )
    
    return DeletionJobResponse(
        deletion_id=deletion_id,
        status='pending',
        progress=0,
        message='Deletion job started'
    )


@router.get("/deletion/{deletion_id}", response_model=DeletionJobResponse)
async def get_deletion_status(deletion_id: str):
    """Get deletion job status"""
    job = _deletion_jobs.get(deletion_id)
    if not job:
        raise HTTPException(status_code=404, detail="Deletion job not found")
    
    return DeletionJobResponse(
        deletion_id=deletion_id,
        status=job['status'],
        progress=job['progress'],
        message=job.get('current_stage', '') or job.get('error', '')
    )


@router.get("/deletion/{deletion_id}/logs", response_model=DeletionLogsResponse)
async def get_deletion_logs(deletion_id: str):
    """Get deletion job logs"""
    job = _deletion_jobs.get(deletion_id)
    if not job:
        raise HTTPException(status_code=404, detail="Deletion job not found")
    
    return DeletionLogsResponse(
        deletion_id=deletion_id,
        logs=job.get('logs', []),
        total_count=len(job.get('logs', []))
    )


@router.post("/validate")
async def validate_deployment(request: DeploymentRequest):
    """
    Validate deployment dependencies without actually deploying
    
    This endpoint performs a dry-run validation to check:
    - Stack dependencies are satisfied
    - Required exports exist
    - No circular dependencies
    - Certificate configuration is valid
    
    Returns validation results and deployment plan.
    """
    try:
        from app.services.deployment_orchestrator import DeploymentOrchestrator
        
        # Get AWS credentials from session - session manager handles refresh automatically
        credentials = None
        if request.aws_session_id:
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
        
        # Create orchestrator with credentials
        orchestrator = DeploymentOrchestrator(credentials=credentials)
        
        # Build config from request
        config = {
            'capability': {'name': request.capability_name},
            'target': {
                'environment': request.environment,
                'region': request.region
            }
        }
        
        # Collect logs
        logs = []
        def log_callback(message: str):
            logs.append(message)
        
        # Run validation (dry-run mode)
        result = orchestrator.deploy_capability_with_validation(
            config=config,
            deploy_frontend=request.deploy_frontend,
            deploy_backend=request.deploy_backend,
            dry_run=True,
            callback=log_callback
        )
        
        return {
            "success": result.get('success', False),
            "validation_result": result.get('validation_result'),
            "deployment_plan": result.get('deployment_plan'),
            "logs": logs
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/plan")
async def get_deployment_plan(request: DeploymentRequest):
    """
    Get deployment plan without validating against AWS
    
    This endpoint analyzes the CloudFormation templates and returns
    the planned deployment order based on dependencies.
    """
    try:
        from app.services.deployment_orchestrator import DeploymentOrchestrator
        from app.services.stack_dependency_analyzer import StackDependencyAnalyzer
        from app.services.deployment_planner import DeploymentPlanner
        from app.services.cloudformation_service import CloudFormationDeploymentService
        
        # Create services (no credentials needed for template analysis)
        cfn_service = CloudFormationDeploymentService()
        analyzer = StackDependencyAnalyzer()
        planner = DeploymentPlanner()
        
        # Build stack configurations
        stack_configs = []
        templates_dir = cfn_service.templates_dir
        
        for stack_type in cfn_service.STACK_ORDER:
            # Skip based on deployment flags
            if 'frontend' in stack_type and not request.deploy_frontend:
                continue
            if 'backend' in stack_type and not request.deploy_backend:
                continue
            
            stack_name = cfn_service.get_stack_name(
                request.capability_name, 
                request.environment, 
                stack_type
            )
            template_path = templates_dir / cfn_service.TEMPLATE_MAP.get(stack_type, '')
            
            if template_path.exists():
                stack_configs.append({
                    'stack_name': stack_name,
                    'stack_type': stack_type,
                    'template_path': str(template_path)
                })
        
        # Build dependency graph
        from app.services.dependency_validator import DependencyValidator
        validator = DependencyValidator()
        graph = validator.build_dependency_graph(stack_configs)
        
        # Get deployment order
        deployment_order = planner.topological_sort(graph)
        
        # Build plan (without existing stack info)
        plan = planner.create_deployment_plan(graph, {}, None)
        
        return {
            "capability_name": request.capability_name,
            "environment": request.environment,
            "region": request.region,
            "total_stacks": plan.total_stacks,
            "estimated_duration_minutes": plan.estimated_duration_minutes,
            "deployment_order": deployment_order,
            "steps": [
                {
                    "step": step.step_number,
                    "stack": step.stack_name,
                    "type": step.stack_type,
                    "action": step.action.value,
                    "reason": step.reason,
                    "will_provide_exports": step.will_provide_exports
                }
                for step in plan.steps
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

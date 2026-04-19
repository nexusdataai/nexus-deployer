"""
Deployment service for managing capability deployments
"""
import asyncio
import subprocess
import os
import uuid
import tempfile
import yaml
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path

from app.models.deployment import (
    DeploymentRequest,
    DeploymentResponse,
    DeploymentStatus,
    DeploymentStage,
    DeploymentLogEntry,
    LogLevel,
    StackDeploymentInfo,
)

logger = logging.getLogger(__name__)


class DeploymentService:
    """Service for managing deployments with installation tracking"""
    
    def __init__(self):
        self.deployments: Dict[str, Dict[str, Any]] = {}
        self.deployment_logs: Dict[str, List[DeploymentLogEntry]] = {}
        self._installation_tracker = None
        self._credential_store = None
    
    @property
    def installation_tracker(self):
        """Lazy load installation tracker."""
        if self._installation_tracker is None:
            try:
                from app.services.installation_tracker import get_installation_tracker
                self._installation_tracker = get_installation_tracker()
            except Exception as e:
                logger.warning(f"Could not load installation tracker: {e}")
        return self._installation_tracker
    
    @property
    def credential_store(self):
        """Lazy load credential store."""
        if self._credential_store is None:
            try:
                from app.services.secure_credential_store import get_credential_store
                self._credential_store = get_credential_store()
            except Exception as e:
                logger.warning(f"Could not load credential store: {e}")
        return self._credential_store
        
    def create_deployment(self, request: DeploymentRequest) -> str:
        """Create a new deployment with installation tracking"""
        deployment_id = str(uuid.uuid4())
        
        # Create installation record
        installation_id = None
        if self.installation_tracker:
            try:
                installation_id = self.installation_tracker.create_installation(
                    capability_name=request.capability_name,
                    capability_version=request.capability_version,
                    environment=request.environment,
                    region=request.region,
                    account_id=request.account_id,
                    strategy=request.deployment_strategy or "UPDATE_EXISTING",
                    deploy_frontend=request.deploy_frontend,
                    deploy_backend=request.deploy_backend
                )
                logger.info(f"Created installation {installation_id} for deployment {deployment_id}")
                
                # Store ADFS credentials for re-authentication if provided
                if installation_id and request.adfs_url and request.adfs_username and request.adfs_password:
                    try:
                        from app.services.aws_session_manager import aws_session_manager
                        
                        # Get current session credentials
                        session = aws_session_manager.get_session(request.aws_session_id) if request.aws_session_id else None
                        
                        if session and self.credential_store:
                            self.credential_store.store_credentials(
                                installation_id=installation_id,
                                access_key_id=session.get('access_key_id', ''),
                                secret_access_key=session.get('secret_access_key', ''),
                                session_token=session.get('session_token'),
                                region=request.region,
                                account_id=request.account_id,
                                adfs_url=request.adfs_url,
                                adfs_username=request.adfs_username,
                                adfs_password=request.adfs_password,
                                adfs_role_arn=request.adfs_role_arn or request.role_arn,
                                auth_method=request.auth_method or 'adfs_saml'
                            )
                            
                            # Link session to installation for refresh
                            if request.aws_session_id and request.aws_session_id in aws_session_manager.sessions:
                                aws_session_manager.sessions[request.aws_session_id]["installation_id"] = installation_id
                            
                            logger.info(f"Stored ADFS credentials for installation {installation_id}")
                    except Exception as e:
                        logger.warning(f"Failed to store ADFS credentials: {e}")
                        
            except Exception as e:
                logger.warning(f"Failed to create installation record: {e}")
        
        self.deployments[deployment_id] = {
            "id": deployment_id,
            "installation_id": installation_id,
            "status": DeploymentStatus.PENDING,
            "current_stage": None,
            "progress": 0,
            "request": request,
            "started_at": datetime.utcnow(),
            "completed_at": None,
            "stacks": [],
            "error": None,
            "process": None,
        }
        
        self.deployment_logs[deployment_id] = []
        
        return deployment_id
    
    def get_deployment(self, deployment_id: str) -> Optional[DeploymentResponse]:
        """Get deployment status"""
        if deployment_id not in self.deployments:
            return None
        
        deployment = self.deployments[deployment_id]
        request = deployment["request"]
        
        # Convert old stack format to new format for backward compatibility
        stacks = deployment.get("stacks", [])
        normalized_stacks = []
        for stack in stacks:
            # Check if it's old format (has 'name' instead of 'stack_name')
            if isinstance(stack, dict) and 'name' in stack and 'stack_name' not in stack:
                # Convert old format to new format
                name = stack.get('name', '')
                parts = name.split('-')
                stack_type = '-'.join(parts[2:]) if len(parts) > 2 else name
                
                normalized_stacks.append({
                    "stack_name": name,
                    "stack_type": stack_type,
                    "status": stack.get('status', 'unknown'),
                    "region": request.region,
                })
            else:
                # Already in new format
                normalized_stacks.append(stack)
        
        return DeploymentResponse(
            deployment_id=deployment_id,
            status=deployment["status"],
            current_stage=deployment["current_stage"],
            progress=deployment["progress"],
            message=self._get_stage_message(deployment["current_stage"]),
            error=deployment["error"],
            capability_name=request.capability_name,
            environment=request.environment,
            region=request.region,
            started_at=deployment["started_at"],
            completed_at=deployment["completed_at"],
            stacks=normalized_stacks,
            frontend_url=deployment.get("frontend_url"),
            backend_url=deployment.get("backend_url"),
            cognito_config=deployment.get("cognito_config"),
            installation_id=deployment.get("installation_id"),
        )
    
    def get_deployment_logs(self, deployment_id: str, limit: Optional[int] = None) -> List[DeploymentLogEntry]:
        """Get deployment logs"""
        if deployment_id not in self.deployment_logs:
            return []
        
        logs = self.deployment_logs[deployment_id]
        if limit:
            return logs[-limit:]
        return logs
    
    def add_log(self, deployment_id: str, level: LogLevel, message: str, 
                stage: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        """Add a log entry and persist to installation log file"""
        if deployment_id not in self.deployment_logs:
            self.deployment_logs[deployment_id] = []
        
        timestamp = datetime.utcnow()
        
        log_entry = DeploymentLogEntry(
            timestamp=timestamp,
            level=level,
            stage=stage,
            message=message,
            details=details,
        )
        
        self.deployment_logs[deployment_id].append(log_entry)
        
        # Also write to installation log file if installation_id exists
        if deployment_id in self.deployments:
            installation_id = self.deployments[deployment_id].get("installation_id")
            if installation_id:
                try:
                    from app.services.installation_log_writer import get_log_writer
                    log_writer = get_log_writer(installation_id)
                    log_writer.write(level.value, message, timestamp)
                except Exception as e:
                    logger.warning(f"Failed to write to installation log: {e}")
    
    async def start_deployment(self, deployment_id: str):
        """Start the deployment process"""
        if deployment_id not in self.deployments:
            raise ValueError(f"Deployment {deployment_id} not found")
        
        deployment = self.deployments[deployment_id]
        request: DeploymentRequest = deployment["request"]
        
        # Update status
        deployment["status"] = DeploymentStatus.INITIALIZING
        deployment["current_stage"] = DeploymentStage.INITIALIZATION
        deployment["progress"] = 5
        
        self.add_log(deployment_id, LogLevel.INFO, "[LAUNCH] Starting deployment process...")
        self.add_log(deployment_id, LogLevel.INFO, f"Capability: {request.capability_name}")
        self.add_log(deployment_id, LogLevel.INFO, f"Environment: {request.environment}")
        self.add_log(deployment_id, LogLevel.INFO, f"Region: {request.region}")
        self.add_log(deployment_id, LogLevel.INFO, f"Account: {request.account_id}")
        
        try:
            # Run deployment in background
            asyncio.create_task(self._execute_deployment(deployment_id))
            
        except Exception as e:
            deployment["status"] = DeploymentStatus.FAILED
            deployment["error"] = str(e)
            deployment["completed_at"] = datetime.utcnow()
            self.add_log(deployment_id, LogLevel.ERROR, f"[X] Deployment failed: {str(e)}")
    
    async def _execute_deployment(self, deployment_id: str):
        """Execute the actual deployment"""
        deployment = self.deployments[deployment_id]
        request: DeploymentRequest = deployment["request"]
        
        try:
            # STEP 1: Provision infrastructure resources (DynamoDB, S3, SSM, etc.)
            # Normalize capability name for comparison (handle "Call Processing", "call-processing", etc.)
            normalized_capability = request.capability_name.lower().replace(' ', '-').replace('_', '-')
            if normalized_capability == "call-processing":
                provisioning_success = await self._provision_infrastructure(deployment_id, request)
                if not provisioning_success:
                    raise Exception("Infrastructure provisioning failed. Check logs for details.")
            
            # Create config file
            config_path = await self._create_config_file(deployment_id, request)
            
            # Execute deployment script
            deployment["status"] = DeploymentStatus.DEPLOYING
            deployment["progress"] = 20
            self.add_log(deployment_id, LogLevel.INFO, "> Starting CloudFormation deployment...")
            self.add_log(deployment_id, LogLevel.INFO, "  All prerequisites verified in previous step")
            
            # Update installation status to running
            installation_id = deployment.get("installation_id")
            if installation_id and self.installation_tracker:
                self.installation_tracker.update_installation(
                    installation_id, status="running"
                )
            
            success = await self._execute_deployment_script(deployment_id, config_path)
            
            if success:
                # Post-deployment verification: show created resources
                # Normalize capability name for comparison
                normalized_capability = request.capability_name.lower().replace(' ', '-').replace('_', '-')
                if normalized_capability == "call-processing":
                    await self._verify_provisioned_resources(deployment_id, request)
                
                # Complete
                deployment["status"] = DeploymentStatus.COMPLETED
                deployment["current_stage"] = DeploymentStage.COMPLETED
                deployment["progress"] = 100
                deployment["completed_at"] = datetime.utcnow()
                self.add_log(deployment_id, LogLevel.INFO, "[OK] Deployment completed successfully!")
                
                # Update installation with success
                if installation_id and self.installation_tracker:
                    self.installation_tracker.update_installation(
                        installation_id,
                        status="completed",
                        frontend_url=deployment.get("frontend_url"),
                        backend_url=deployment.get("backend_url"),
                        cognito_config=deployment.get("cognito_config")
                    )
                    self.installation_tracker.update_stacks_summary(installation_id)
            else:
                raise Exception("Deployment script failed")
            
            # Clean up config file
            if os.path.exists(config_path):
                os.remove(config_path)
            
            # Cleanup credentials after successful deployment
            if installation_id:
                self._cleanup_deployment_credentials(installation_id)
            
        except Exception as e:
            deployment["status"] = DeploymentStatus.FAILED
            deployment["error"] = str(e)
            deployment["completed_at"] = datetime.utcnow()
            self.add_log(deployment_id, LogLevel.ERROR, f"[X] Deployment failed: {str(e)}")
            
            # Update installation with failure
            installation_id = deployment.get("installation_id")
            if installation_id and self.installation_tracker:
                self.installation_tracker.update_installation(
                    installation_id,
                    status="failed",
                    error=str(e)
                )
                self.installation_tracker.update_stacks_summary(installation_id)
    
    async def _provision_infrastructure(self, deployment_id: str, request: DeploymentRequest) -> bool:
        """
        Provision infrastructure resources (DynamoDB, S3, SSM, Secrets, Glue, CloudWatch).
        
        This runs BEFORE CloudFormation deployment to ensure all required resources exist.
        
        Args:
            deployment_id: Current deployment ID for logging
            request: Deployment request with environment and region
            
        Returns:
            True if provisioning succeeded, False otherwise
        """
        import concurrent.futures
        import queue
        import threading
        from app.services.aws_session_manager import aws_session_manager
        
        deployment = self.deployments[deployment_id]
        
        # Update stage
        deployment["current_stage"] = DeploymentStage.INFRASTRUCTURE_PROVISIONING
        deployment["progress"] = 10
        
        self.add_log(deployment_id, LogLevel.INFO, "")
        self.add_log(deployment_id, LogLevel.INFO, "[BUILD]️ INFRASTRUCTURE PROVISIONING")
        self.add_log(deployment_id, LogLevel.INFO, "=" * 50)
        self.add_log(deployment_id, LogLevel.INFO, f"  Environment: {request.environment}")
        self.add_log(deployment_id, LogLevel.INFO, f"  Region: {request.region}")
        self.add_log(deployment_id, LogLevel.INFO, "")
        
        try:
            # Get AWS credentials
            boto3_creds = None
            if request.aws_session_id:
                boto3_creds = aws_session_manager.get_credentials_dict(request.aws_session_id)
            
            # Fallback: find matching session
            if not boto3_creds:
                for sid, session in aws_session_manager.sessions.items():
                    if (session.get('account_id') == request.account_id and 
                        session.get('region') == request.region):
                        boto3_creds = aws_session_manager.get_credentials_dict(sid)
                        if boto3_creds:
                            break
            
            if not boto3_creds:
                self.add_log(deployment_id, LogLevel.ERROR, "  [X] No AWS credentials found for provisioning")
                return False
            
            # Set up AWS credentials in environment for boto3
            import os
            os.environ['AWS_ACCESS_KEY_ID'] = boto3_creds.get('aws_access_key_id', '')
            os.environ['AWS_SECRET_ACCESS_KEY'] = boto3_creds.get('aws_secret_access_key', '')
            if boto3_creds.get('aws_session_token'):
                os.environ['AWS_SESSION_TOKEN'] = boto3_creds.get('aws_session_token')
            os.environ['AWS_DEFAULT_REGION'] = request.region
            
            # Import orchestrator
            from app.services.infra_provisioning.orchestrator import ProvisioningOrchestrator
            
            # Create a thread-safe queue for progress messages
            progress_queue = queue.Queue()
            
            # Progress callback that puts messages in the queue
            def progress_callback(message: str):
                progress_queue.put(message)
            
            # Run provisioning in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            
            def run_provisioning():
                orchestrator = ProvisioningOrchestrator(
                    environment=request.environment,
                    region=request.region,
                    dry_run=False,
                    progress_callback=progress_callback,
                )
                return orchestrator.provision_all()
            
            deployment["progress"] = 11
            
            # Start provisioning in a thread
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_provisioning)
                
                # Poll for progress messages while provisioning runs
                while not future.done():
                    try:
                        # Get messages from queue with timeout
                        message = progress_queue.get(timeout=0.1)
                        self.add_log(deployment_id, LogLevel.INFO, message)
                    except queue.Empty:
                        pass
                    await asyncio.sleep(0.05)  # Small sleep to avoid busy loop
                
                # Get any remaining messages
                while not progress_queue.empty():
                    try:
                        message = progress_queue.get_nowait()
                        self.add_log(deployment_id, LogLevel.INFO, message)
                    except queue.Empty:
                        break
                
                # Get the result
                report = future.result()
            
            # Log results by resource type
            resource_counts = {}
            for resource in report.resources:
                rtype = str(resource.resource_type).split('.')[-1] if hasattr(resource.resource_type, 'name') else str(resource.resource_type)
                if rtype not in resource_counts:
                    resource_counts[rtype] = {'created': 0, 'existed': 0, 'failed': 0}
                
                status_str = str(resource.status).lower()
                if 'created' in status_str:
                    resource_counts[rtype]['created'] += 1
                elif 'already' in status_str or 'exist' in status_str:
                    resource_counts[rtype]['existed'] += 1
                elif 'failed' in status_str:
                    resource_counts[rtype]['failed'] += 1
                    self.add_log(deployment_id, LogLevel.ERROR, f"  [X] Failed: {resource.resource_name} - {resource.message}")
            
            # Summary logging
            self.add_log(deployment_id, LogLevel.INFO, "")
            self.add_log(deployment_id, LogLevel.INFO, "[CHART] Provisioning Summary:")
            for rtype, counts in resource_counts.items():
                self.add_log(deployment_id, LogLevel.INFO, 
                    f"  {rtype}: {counts['created']} created, {counts['existed']} existed, {counts['failed']} failed")
            
            self.add_log(deployment_id, LogLevel.INFO, "")
            self.add_log(deployment_id, LogLevel.INFO, f"  Total: {report.success_count} created, {report.already_existed_count} already existed, {report.failed_count} failed")
            
            if report.overall_success:
                self.add_log(deployment_id, LogLevel.INFO, "")
                self.add_log(deployment_id, LogLevel.INFO, "[OK] Infrastructure provisioning completed successfully!")
                self.add_log(deployment_id, LogLevel.INFO, "")
                deployment["progress"] = 18
                return True
            else:
                self.add_log(deployment_id, LogLevel.ERROR, "")
                self.add_log(deployment_id, LogLevel.ERROR, f"[X] Infrastructure provisioning failed: {report.failed_count} resources failed")
                self.add_log(deployment_id, LogLevel.ERROR, "")
                return False
                
        except Exception as e:
            self.add_log(deployment_id, LogLevel.ERROR, f"[X] Infrastructure provisioning error: {str(e)}")
            logger.exception(f"Infrastructure provisioning failed for deployment {deployment_id}")
            return False
    
    def _cleanup_deployment_credentials(self, installation_id: str):
        """Cleanup credentials after deployment completes."""
        try:
            from app.services.aws_session_manager import aws_session_manager
            aws_session_manager.cleanup_installation_credentials(installation_id)
            logger.info(f"Cleaned up credentials for installation {installation_id}")
        except Exception as e:
            logger.warning(f"Failed to cleanup credentials: {e}")
    
    async def _verify_provisioned_resources(self, deployment_id: str, request: DeploymentRequest):
        """
        Verify and display all provisioned infrastructure resources.
        
        Shows DynamoDB tables and S3 buckets created during deployment.
        
        Args:
            deployment_id: Current deployment ID for logging
            request: Deployment request with environment and region
        """
        import concurrent.futures
        
        deployment = self.deployments[deployment_id]
        deployment["progress"] = 95
        
        self.add_log(deployment_id, LogLevel.INFO, "")
        self.add_log(deployment_id, LogLevel.INFO, "[DBG] POST-DEPLOYMENT VERIFICATION")
        self.add_log(deployment_id, LogLevel.INFO, "=" * 50)
        
        try:
            from app.services.infra_provisioning.verification_service import VerificationService
            from app.services.infra_provisioning.naming import ResourceNaming
            from app.services.aws_session_manager import aws_session_manager
            
            # Get AWS credentials from session (same as used for deployment)
            boto3_creds = None
            if request.aws_session_id:
                boto3_creds = aws_session_manager.get_credentials_dict(request.aws_session_id)
                if boto3_creds:
                    self.add_log(deployment_id, LogLevel.INFO, "[OK] Using deployment session credentials for verification")
                else:
                    self.add_log(deployment_id, LogLevel.WARNING, "[!] Could not retrieve session credentials, using default")
            
            # Run verification in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            
            def run_verification():
                verification_service = VerificationService(
                    environment=request.environment,
                    region=request.region,
                    credentials=boto3_creds,
                )
                return verification_service.verify_all()
            
            with concurrent.futures.ThreadPoolExecutor() as executor:
                report = await loop.run_in_executor(executor, run_verification)
            
            # Get naming utility for resource names
            naming = ResourceNaming(request.environment)
            
            # Display DynamoDB Tables
            self.add_log(deployment_id, LogLevel.INFO, "")
            self.add_log(deployment_id, LogLevel.INFO, "[PKG] DynamoDB Tables:")
            dynamodb_tables = naming.all_dynamodb_tables()
            for table_name in dynamodb_tables:
                # Find verification result for this table
                table_result = next(
                    (r for r in report.results if r.resource_name == table_name),
                    None
                )
                if table_result and str(table_result.status).lower() == "verified":
                    self.add_log(deployment_id, LogLevel.INFO, f"  [OK] {table_name}")
                elif table_result:
                    self.add_log(deployment_id, LogLevel.WARNING, f"  [!] {table_name} ({table_result.status})")
                else:
                    self.add_log(deployment_id, LogLevel.INFO, f"  * {table_name}")
            
            # Display S3 Buckets
            self.add_log(deployment_id, LogLevel.INFO, "")
            self.add_log(deployment_id, LogLevel.INFO, "[BUCKET] S3 Buckets:")
            s3_buckets = naming.all_s3_buckets()
            for bucket_name in s3_buckets:
                # Find verification result for this bucket
                bucket_result = next(
                    (r for r in report.results if r.resource_name == bucket_name),
                    None
                )
                if bucket_result and str(bucket_result.status).lower() == "verified":
                    self.add_log(deployment_id, LogLevel.INFO, f"  [OK] {bucket_name}")
                elif bucket_result:
                    self.add_log(deployment_id, LogLevel.WARNING, f"  [!] {bucket_name} ({bucket_result.status})")
                else:
                    self.add_log(deployment_id, LogLevel.INFO, f"  * {bucket_name}")
            
            # Summary
            self.add_log(deployment_id, LogLevel.INFO, "")
            if report.all_passed:
                self.add_log(deployment_id, LogLevel.INFO, f"[OK] All {report.passed_count} resources verified successfully!")
            else:
                self.add_log(deployment_id, LogLevel.WARNING, 
                    f"[!] Verification: {report.passed_count} passed, {report.failed_count} failed")
            self.add_log(deployment_id, LogLevel.INFO, "")
            
        except Exception as e:
            self.add_log(deployment_id, LogLevel.WARNING, f"[!] Resource verification skipped: {str(e)}")
            logger.warning(f"Post-deployment verification failed for deployment {deployment_id}: {e}")
    
    async def _create_config_file(self, deployment_id: str, request: DeploymentRequest) -> str:
        """Create deployment configuration file using priority: UI config > Saved config > Template > Request"""
        from app.services.config_service import config_service
        
        # Priority 1: Use infrastructure_config from request if provided
        if request.infrastructure_config:
            self.add_log(deployment_id, LogLevel.INFO, "📄 Using infrastructure configuration from UI")
            infrastructure = request.infrastructure_config.get('infrastructure', {})
        else:
            # Priority 2: Load saved user config or template
            self.add_log(deployment_id, LogLevel.INFO, f"📄 Loading configuration for {request.capability_name} in {request.environment}")
            env_config = config_service.get_config(request.capability_name, request.environment)
            infrastructure = env_config.model_dump()['infrastructure']
            self.add_log(deployment_id, LogLevel.INFO, "[OK] Configuration loaded successfully")
        
        # Build complete config
        config = {
            "capability": {
                "name": request.capability_name,
                "version": request.capability_version,
            },
            "source": {},
            "target": {
                "account_id": request.account_id,
                "region": request.region,
                "environment": request.environment,
            },
            "infrastructure": infrastructure
        }
        
        # Add artifact sources
        if request.frontend_s3_uri:
            config["source"]["frontend"] = {"s3_uri": request.frontend_s3_uri}
        
        if request.backend_ecr_uri:
            config["source"]["backend"] = {"ecr_uri": request.backend_ecr_uri}
        
        if request.role_arn:
            config["target"]["role_arn"] = request.role_arn
        
        # Log key configuration details
        domain_config = infrastructure.get('domain', {})
        ecs_config = infrastructure.get('backend', {}).get('ecs', {})
        
        self.add_log(deployment_id, LogLevel.INFO, f"  Capability: {request.capability_name}")
        self.add_log(deployment_id, LogLevel.INFO, f"  Domain: {domain_config.get('base', 'N/A')}")
        self.add_log(deployment_id, LogLevel.INFO, f"  ECS CPU: {ecs_config.get('task_cpu', 'N/A')}")
        self.add_log(deployment_id, LogLevel.INFO, f"  ECS Memory: {ecs_config.get('task_memory', 'N/A')}")
        self.add_log(deployment_id, LogLevel.INFO, f"  Desired Count: {ecs_config.get('desired_count', 'N/A')}")
        
        # Write to temp file
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
        yaml.dump(config, temp_file, default_flow_style=False)
        temp_file.close()
        
        return temp_file.name
    
    async def _deploy_frontend(self, deployment_id: str, config_path: str):
        """Deploy frontend stacks"""
        deployment = self.deployments[deployment_id]
        
        stages = [
            (DeploymentStage.FRONTEND_GLOBAL, "Deploying frontend global resources", 30),
            (DeploymentStage.FRONTEND_COGNITO, "Deploying Cognito authentication", 45),
            (DeploymentStage.FRONTEND_REGIONAL, "Deploying CloudFront distribution", 60),
            (DeploymentStage.FRONTEND_UPLOAD, "Uploading frontend artifacts", 70),
        ]
        
        for stage, message, progress in stages:
            deployment["current_stage"] = stage
            deployment["progress"] = progress
            self.add_log(deployment_id, LogLevel.INFO, f"> {message}...")
            
            # Simulate deployment
            await asyncio.sleep(3)
            
            self.add_log(deployment_id, LogLevel.INFO, f"[OK] {message} completed")
    
    async def _deploy_backend(self, deployment_id: str, config_path: str):
        """Deploy backend stacks"""
        deployment = self.deployments[deployment_id]
        request: DeploymentRequest = deployment["request"]
        
        stages = [
            (DeploymentStage.BACKEND_FOUNDATION, "Deploying backend foundation", 40 if request.deploy_frontend else 20),
            (DeploymentStage.BACKEND_STORAGE, "Creating storage resources", 55 if request.deploy_frontend else 40),
            (DeploymentStage.BACKEND_NETWORK, "Configuring network infrastructure", 70 if request.deploy_frontend else 60),
            (DeploymentStage.BACKEND_SERVICE, "Deploying ECS service", 85 if request.deploy_frontend else 80),
        ]
        
        for stage, message, progress in stages:
            deployment["current_stage"] = stage
            deployment["progress"] = progress
            self.add_log(deployment_id, LogLevel.INFO, f"> {message}...")
            
            # Simulate deployment
            await asyncio.sleep(4)
            
            self.add_log(deployment_id, LogLevel.INFO, f"[OK] {message} completed")
    
    async def _verify_artifacts(self, deployment_id: str, request: DeploymentRequest):
        """Verify that artifacts exist and are accessible"""
        import boto3
        from botocore.exceptions import ClientError
        from app.services.aws_session_manager import aws_session_manager
        
        try:
            # Get AWS credentials from session
            boto3_creds = None
            
            self.add_log(deployment_id, LogLevel.INFO, "[LIST] Starting comprehensive prerequisite verification...")
            self.add_log(deployment_id, LogLevel.INFO, f"  [DBG] DEBUG: aws_session_id = {request.aws_session_id}")
            
            if request.aws_session_id:
                self.add_log(deployment_id, LogLevel.INFO, f"  [DBG] DEBUG: Attempting to retrieve session...")
                boto3_creds = aws_session_manager.get_credentials_dict(request.aws_session_id)
                
                if not boto3_creds:
                    self.add_log(deployment_id, LogLevel.ERROR, "  [X] AWS session expired or not found")
                    raise Exception("AWS session expired or not found. Please re-authenticate.")
                
                self.add_log(deployment_id, LogLevel.INFO, "  [OK] Using stored AWS credentials")
                self.add_log(deployment_id, LogLevel.INFO, f"  [DBG] DEBUG: Credentials retrieved for region: {boto3_creds.get('region_name', 'N/A')}")
            else:
                self.add_log(deployment_id, LogLevel.WARNING, "  [!] No AWS session ID provided")
                self.add_log(deployment_id, LogLevel.INFO, "  [TOOL] Attempting to find most recent session...")
                
                # WORKAROUND: Try to find a session for this account/region
                sessions = aws_session_manager.sessions
                if sessions:
                    # Find session matching account and region
                    matching_session = None
                    for sid, session in sessions.items():
                        if (session.get('account_id') == request.account_id and 
                            session.get('region') == request.region):
                            matching_session = sid
                            break
                    
                    if matching_session:
                        self.add_log(deployment_id, LogLevel.INFO, f"  [OK] Found matching session: {matching_session}")
                        boto3_creds = aws_session_manager.get_credentials_dict(matching_session)
                        if boto3_creds:
                            self.add_log(deployment_id, LogLevel.INFO, "  [OK] Using found session credentials")
                        else:
                            self.add_log(deployment_id, LogLevel.WARNING, "  [!] Session found but credentials unavailable")
                    else:
                        self.add_log(deployment_id, LogLevel.WARNING, f"  [!] No matching session found for account {request.account_id}")
                        self.add_log(deployment_id, LogLevel.WARNING, "  [!] Using default credentials (may fail)")
                else:
                    self.add_log(deployment_id, LogLevel.WARNING, "  [!] No sessions available")
                    self.add_log(deployment_id, LogLevel.WARNING, "  [!] Using default credentials (may fail)")
            
            # Prepare credentials for boto3 clients
            # Remove region_name from creds to avoid conflicts
            client_creds = {}
            if boto3_creds:
                client_creds = {
                    'aws_access_key_id': boto3_creds.get('aws_access_key_id'),
                    'aws_secret_access_key': boto3_creds.get('aws_secret_access_key'),
                    'aws_session_token': boto3_creds.get('aws_session_token'),
                }
            
            # 1. Verify AWS Account Access
            self.add_log(deployment_id, LogLevel.INFO, "")
            self.add_log(deployment_id, LogLevel.INFO, "1️⃣ Verifying AWS Account Access...")
            try:
                sts_client = boto3.client('sts', region_name=request.region, **client_creds)
                identity = sts_client.get_caller_identity()
                account = identity['Account']
                arn = identity['Arn']
                
                if account != request.account_id:
                    raise Exception(f"Account mismatch: Expected {request.account_id}, got {account}")
                
                self.add_log(deployment_id, LogLevel.INFO, f"  [OK] AWS Account: {account}")
                self.add_log(deployment_id, LogLevel.INFO, f"  [OK] Identity: {arn}")
            except Exception as e:
                self.add_log(deployment_id, LogLevel.ERROR, f"  [X] Account verification failed: {str(e)}")
                raise
            
            # 2. Verify frontend S3 artifact if needed
            if request.deploy_frontend and request.frontend_s3_uri:
                self.add_log(deployment_id, LogLevel.INFO, "")
                self.add_log(deployment_id, LogLevel.INFO, "2️⃣ Verifying Frontend Artifact...")
                self.add_log(deployment_id, LogLevel.INFO, f"  [PKG] S3 URI: {request.frontend_s3_uri}")
                
                # Parse S3 URI
                s3_uri = request.frontend_s3_uri.replace("s3://", "")
                parts = s3_uri.split("/", 1)
                bucket = parts[0]
                key = parts[1] if len(parts) > 1 else ""
                
                # Check if object exists
                s3_client = boto3.client('s3', region_name='us-east-1', **client_creds)
                try:
                    response = s3_client.head_object(Bucket=bucket, Key=key)
                    size_mb = response['ContentLength'] / (1024 * 1024)
                    last_modified = response['LastModified']
                    self.add_log(deployment_id, LogLevel.INFO, f"  [OK] Frontend artifact found")
                    self.add_log(deployment_id, LogLevel.INFO, f"  [OK] Size: {size_mb:.1f} MB")
                    self.add_log(deployment_id, LogLevel.INFO, f"  [OK] Last Modified: {last_modified}")
                except ClientError as e:
                    if e.response['Error']['Code'] == '404':
                        self.add_log(deployment_id, LogLevel.ERROR, f"  [X] Frontend artifact not found")
                        self.add_log(deployment_id, LogLevel.ERROR, f"  [X] Bucket: {bucket}")
                        self.add_log(deployment_id, LogLevel.ERROR, f"  [X] Key: {key}")
                        raise Exception(f"Frontend artifact not found: {request.frontend_s3_uri}")
                    elif e.response['Error']['Code'] == '403':
                        self.add_log(deployment_id, LogLevel.ERROR, f"  [X] Access denied to frontend artifact")
                        raise Exception(f"Access denied to frontend artifact: {request.frontend_s3_uri}")
                    else:
                        self.add_log(deployment_id, LogLevel.ERROR, f"  [X] S3 error: {str(e)}")
                        raise
            
            # 3. Verify backend ECR image if needed
            if request.deploy_backend and request.backend_ecr_uri:
                self.add_log(deployment_id, LogLevel.INFO, "")
                self.add_log(deployment_id, LogLevel.INFO, "3️⃣ Verifying Backend Container Image...")
                self.add_log(deployment_id, LogLevel.INFO, f"  [DOCKER] ECR URI: {request.backend_ecr_uri}")
                
                # Parse ECR URI: account.dkr.ecr.region.amazonaws.com/repository:tag
                registry = request.backend_ecr_uri.split('/')[0]
                repo_tag = request.backend_ecr_uri.split('/', 1)[1]
                repository = repo_tag.split(':')[0]
                tag = repo_tag.split(':')[1] if ':' in repo_tag else 'latest'
                
                # Extract region from registry
                ecr_region = registry.split('.')[3]
                
                self.add_log(deployment_id, LogLevel.INFO, f"  [LOC] ECR Region: {ecr_region}")
                self.add_log(deployment_id, LogLevel.INFO, f"  [PKG] Repository: {repository}")
                self.add_log(deployment_id, LogLevel.INFO, f"  [TAG]️  Tag: {tag}")
                
                # Check if image exists
                ecr_client = boto3.client('ecr', region_name=ecr_region, **client_creds)
                try:
                    response = ecr_client.describe_images(
                        repositoryName=repository,
                        imageIds=[{'imageTag': tag}]
                    )
                    if response['imageDetails']:
                        image = response['imageDetails'][0]
                        size_mb = image['imageSizeInBytes'] / (1024 * 1024)
                        pushed_at = image['imagePushedAt']
                        digest = image['imageDigest'][:20] + "..."
                        
                        self.add_log(deployment_id, LogLevel.INFO, f"  [OK] Backend image found")
                        self.add_log(deployment_id, LogLevel.INFO, f"  [OK] Size: {size_mb:.1f} MB")
                        self.add_log(deployment_id, LogLevel.INFO, f"  [OK] Pushed: {pushed_at}")
                        self.add_log(deployment_id, LogLevel.INFO, f"  [OK] Digest: {digest}")
                except ClientError as e:
                    error_code = e.response['Error']['Code']
                    if error_code == 'ImageNotFoundException':
                        self.add_log(deployment_id, LogLevel.ERROR, f"  [X] Backend image not found")
                        self.add_log(deployment_id, LogLevel.ERROR, f"  [X] Repository: {repository}")
                        self.add_log(deployment_id, LogLevel.ERROR, f"  [X] Tag: {tag}")
                        raise Exception(f"Backend image not found: {request.backend_ecr_uri}")
                    elif error_code == 'RepositoryNotFoundException':
                        self.add_log(deployment_id, LogLevel.ERROR, f"  [X] ECR repository not found: {repository}")
                        raise Exception(f"ECR repository not found: {repository}")
                    elif error_code == 'AccessDeniedException':
                        self.add_log(deployment_id, LogLevel.ERROR, f"  [X] Access denied to ECR repository")
                        raise Exception(f"Access denied to ECR repository: {repository}")
                    else:
                        self.add_log(deployment_id, LogLevel.ERROR, f"  [X] ECR error: {str(e)}")
                        raise
            
            # 4. Verify Route53 Hosted Zone if domain is configured
            if request.base_domain and request.hosted_zone_id:
                self.add_log(deployment_id, LogLevel.INFO, "")
                self.add_log(deployment_id, LogLevel.INFO, "4️⃣ Verifying Route53 Hosted Zone...")
                self.add_log(deployment_id, LogLevel.INFO, f"  [WEB] Domain: {request.base_domain}")
                self.add_log(deployment_id, LogLevel.INFO, f"  [ID] Hosted Zone ID: {request.hosted_zone_id}")
                
                try:
                    route53_client = boto3.client('route53', **client_creds)
                    response = route53_client.get_hosted_zone(Id=request.hosted_zone_id)
                    zone_name = response['HostedZone']['Name'].rstrip('.')
                    
                    if not request.base_domain.endswith(zone_name):
                        self.add_log(deployment_id, LogLevel.WARNING, f"  [!] Domain mismatch: {request.base_domain} not in zone {zone_name}")
                    
                    self.add_log(deployment_id, LogLevel.INFO, f"  [OK] Hosted zone found: {zone_name}")
                except ClientError as e:
                    self.add_log(deployment_id, LogLevel.ERROR, f"  [X] Hosted zone verification failed: {str(e)}")
                    raise Exception(f"Hosted zone not found or inaccessible: {request.hosted_zone_id}")
            
            # 5. Verify VPC and Subnet availability in target region
            self.add_log(deployment_id, LogLevel.INFO, "")
            self.add_log(deployment_id, LogLevel.INFO, "5️⃣ Verifying Network Resources...")
            self.add_log(deployment_id, LogLevel.INFO, f"  [LOC] Region: {request.region}")
            
            try:
                ec2_client = boto3.client('ec2', region_name=request.region, **client_creds)
                
                # Check available AZs
                azs_response = ec2_client.describe_availability_zones(
                    Filters=[{'Name': 'state', 'Values': ['available']}]
                )
                available_azs = [az['ZoneName'] for az in azs_response['AvailabilityZones']]
                
                if len(available_azs) < 2:
                    self.add_log(deployment_id, LogLevel.WARNING, f"  [!] Only {len(available_azs)} AZ(s) available (recommended: 2+)")
                else:
                    self.add_log(deployment_id, LogLevel.INFO, f"  [OK] {len(available_azs)} Availability Zones available")
                
                # Check VPC quota
                vpcs_response = ec2_client.describe_vpcs()
                vpc_count = len(vpcs_response['Vpcs'])
                self.add_log(deployment_id, LogLevel.INFO, f"  [OK] Current VPCs: {vpc_count}/5 (default limit)")
                
            except ClientError as e:
                self.add_log(deployment_id, LogLevel.WARNING, f"  [!] Network verification warning: {str(e)}")
            
            # 6. Verify ECS service limits
            if request.deploy_backend:
                self.add_log(deployment_id, LogLevel.INFO, "")
                self.add_log(deployment_id, LogLevel.INFO, "6️⃣ Verifying ECS Service Limits...")
                
                try:
                    ecs_client = boto3.client('ecs', region_name=request.region, **client_creds)
                    clusters = ecs_client.list_clusters()
                    cluster_count = len(clusters['clusterArns'])
                    
                    self.add_log(deployment_id, LogLevel.INFO, f"  [OK] Current ECS clusters: {cluster_count}")
                    
                except ClientError as e:
                    self.add_log(deployment_id, LogLevel.WARNING, f"  [!] ECS verification warning: {str(e)}")
            
            # Summary
            self.add_log(deployment_id, LogLevel.INFO, "")
            self.add_log(deployment_id, LogLevel.INFO, "[OK] All prerequisite verifications passed!")
            self.add_log(deployment_id, LogLevel.INFO, "")
                    
        except Exception as e:
            self.add_log(deployment_id, LogLevel.ERROR, "")
            self.add_log(deployment_id, LogLevel.ERROR, f"[X] Prerequisite verification failed: {str(e)}")
            self.add_log(deployment_id, LogLevel.ERROR, "")
            raise
    
    async def _execute_deployment_script(self, deployment_id: str, config_path: str) -> bool:
        """Execute the deployment using Python CloudFormation service"""
        deployment = self.deployments[deployment_id]
        request: DeploymentRequest = deployment["request"]
        
        # Use Python-based deployment instead of shell script
        self.add_log(deployment_id, LogLevel.INFO, "> Using Python-based CloudFormation deployment")
        
        try:
            return await self._execute_python_deployment(deployment_id, config_path)
        except Exception as e:
            self.add_log(deployment_id, LogLevel.ERROR, f"Python deployment failed: {str(e)}")
            return False
        
        self.add_log(deployment_id, LogLevel.INFO, f"> Executing deployment script: {script_path}")
        
        try:
            from app.services.aws_session_manager import aws_session_manager
            
            # Get AWS credentials environment variables
            env_vars = os.environ.copy()
            
            self.add_log(deployment_id, LogLevel.INFO, f"  [DBG] DEBUG: Script execution - aws_session_id = {request.aws_session_id}")
            
            session_env = None
            if request.aws_session_id:
                self.add_log(deployment_id, LogLevel.INFO, f"  [DBG] DEBUG: Retrieving session environment variables...")
                session_env = aws_session_manager.get_env_vars(request.aws_session_id)
                
                if session_env:
                    env_vars.update(session_env)
                    self.add_log(deployment_id, LogLevel.INFO, "  [OK] Using stored AWS credentials for deployment")
                    self.add_log(deployment_id, LogLevel.INFO, f"  [DBG] DEBUG: AWS_ACCESS_KEY_ID set: {session_env.get('AWS_ACCESS_KEY_ID', 'N/A')[:10]}...")
                    self.add_log(deployment_id, LogLevel.INFO, f"  [DBG] DEBUG: AWS_DEFAULT_REGION: {session_env.get('AWS_DEFAULT_REGION', 'N/A')}")
                else:
                    self.add_log(deployment_id, LogLevel.ERROR, "  [X] AWS session expired or not found")
                    raise Exception("AWS session expired or not found. Please re-authenticate.")
            else:
                self.add_log(deployment_id, LogLevel.WARNING, "  [!] No AWS session ID provided")
                self.add_log(deployment_id, LogLevel.INFO, "  [TOOL] Attempting to find most recent session...")
                
                # WORKAROUND: Try to find a session for this account/region
                sessions = aws_session_manager.sessions
                if sessions:
                    # Find session matching account and region
                    matching_session = None
                    for sid, session in sessions.items():
                        if (session.get('account_id') == request.account_id and 
                            session.get('region') == request.region):
                            matching_session = sid
                            break
                    
                    if matching_session:
                        self.add_log(deployment_id, LogLevel.INFO, f"  [OK] Found matching session: {matching_session}")
                        session_env = aws_session_manager.get_env_vars(matching_session)
                        if session_env:
                            env_vars.update(session_env)
                            self.add_log(deployment_id, LogLevel.INFO, "  [OK] Using found session credentials")
                            self.add_log(deployment_id, LogLevel.INFO, f"  [DBG] DEBUG: AWS_ACCESS_KEY_ID set: {session_env.get('AWS_ACCESS_KEY_ID', 'N/A')[:10]}...")
                        else:
                            self.add_log(deployment_id, LogLevel.WARNING, "  [!] Session found but credentials unavailable")
                    else:
                        self.add_log(deployment_id, LogLevel.WARNING, f"  [!] No matching session found")
                        self.add_log(deployment_id, LogLevel.WARNING, "  [!] Using default credentials (may fail)")
                else:
                    self.add_log(deployment_id, LogLevel.WARNING, "  [!] No sessions available")
                    self.add_log(deployment_id, LogLevel.WARNING, "  [!] Using default credentials (may fail)")
            
            # Build command
            cmd = [
                str(script_path),
                "--config", config_path,
                "--verbose"
            ]
            
            # Execute with real-time output capture
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(script_path.parent),
                env=env_vars
            )
            
            deployment["process"] = process
            
            # Stream output to logs
            async for line in process.stdout:
                if deployment["status"] == DeploymentStatus.CANCELLED:
                    process.terminate()
                    break
                    
                message = line.decode().strip()
                if message:
                    self.add_log(deployment_id, LogLevel.INFO, message)
                    self._parse_progress(deployment_id, message)
            
            # Wait for completion
            await process.wait()
            
            if process.returncode == 0:
                return True
            else:
                self.add_log(deployment_id, LogLevel.ERROR, f"Script exited with code {process.returncode}")
                return False
                
        except Exception as e:
            self.add_log(deployment_id, LogLevel.ERROR, f"Script execution failed: {str(e)}")
            return False
    
    async def _simulate_deployment(self, deployment_id: str) -> bool:
        """Simulate deployment for testing"""
        deployment = self.deployments[deployment_id]
        request: DeploymentRequest = deployment["request"]
        
        self.add_log(deployment_id, LogLevel.INFO, "[TOOL] Running in simulation mode")
        
        # Deploy frontend if requested
        if request.deploy_frontend:
            await self._deploy_frontend(deployment_id, "")
        
        # Deploy backend if requested
        if request.deploy_backend:
            await self._deploy_backend(deployment_id, "")
        
        # Verification
        deployment["current_stage"] = DeploymentStage.VERIFICATION
        deployment["progress"] = 95
        self.add_log(deployment_id, LogLevel.INFO, "> Running health checks...")
        await asyncio.sleep(2)
        self.add_log(deployment_id, LogLevel.INFO, "[OK] Health checks passed")
        
        return True
    
    def _parse_progress(self, deployment_id: str, message: str):
        """Parse script output to update progress"""
        deployment = self.deployments[deployment_id]
        
        # Map log messages to stages and progress
        stage_patterns = {
            "frontend-global": (DeploymentStage.FRONTEND_GLOBAL, 30),
            "frontend-cognito": (DeploymentStage.FRONTEND_COGNITO, 45),
            "frontend-regional": (DeploymentStage.FRONTEND_REGIONAL, 60),
            "Uploading frontend": (DeploymentStage.FRONTEND_UPLOAD, 70),
            "backend-foundation": (DeploymentStage.BACKEND_FOUNDATION, 40),
            "backend-storage": (DeploymentStage.BACKEND_STORAGE, 55),
            "backend-network": (DeploymentStage.BACKEND_NETWORK, 70),
            "backend-service": (DeploymentStage.BACKEND_SERVICE, 85),
            "Verifying deployment": (DeploymentStage.VERIFICATION, 95),
        }
        
        for pattern, (stage, progress) in stage_patterns.items():
            if pattern.lower() in message.lower():
                deployment["current_stage"] = stage
                deployment["progress"] = progress
                break
    
    def cancel_deployment(self, deployment_id: str) -> bool:
        """Cancel a running deployment"""
        if deployment_id not in self.deployments:
            return False
        
        deployment = self.deployments[deployment_id]
        
        if deployment["status"] not in [DeploymentStatus.PENDING, DeploymentStatus.INITIALIZING, DeploymentStatus.DEPLOYING, DeploymentStatus.VALIDATING]:
            return False
        
        # Set cancellation flag
        deployment["status"] = DeploymentStatus.CANCELLED
        deployment["cancelled"] = True  # Flag for thread to check
        deployment["completed_at"] = datetime.utcnow()
        self.add_log(deployment_id, LogLevel.WARNING, "[!] Deployment cancellation requested by user")
        self.add_log(deployment_id, LogLevel.INFO, "  Waiting for current operation to complete...")
        
        # Kill process if running (for bash script deployments)
        if deployment.get("process"):
            try:
                deployment["process"].terminate()
            except:
                pass
        
        # Note: Thread pool executor will complete current operation
        # but the deployment will check cancelled flag and stop
        
        return True
    
    async def _execute_python_deployment(self, deployment_id: str, config_path: str) -> bool:
        """Execute deployment using Python CloudFormation service"""
        import concurrent.futures
        from app.services.deployment_orchestrator import DeploymentOrchestrator
        from app.services.aws_session_manager import aws_session_manager
        
        deployment = self.deployments[deployment_id]
        request: DeploymentRequest = deployment["request"]
        
        self.add_log(deployment_id, LogLevel.INFO, f"[DBG] DEBUG: Retrieving AWS credentials...")
        self.add_log(deployment_id, LogLevel.INFO, f"  aws_session_id: {request.aws_session_id}")
        self.add_log(deployment_id, LogLevel.INFO, f"  account_id: {request.account_id}")
        self.add_log(deployment_id, LogLevel.INFO, f"  region: {request.region}")
        
        # Get AWS credentials with fallback
        boto3_creds = None
        if request.aws_session_id:
            boto3_creds = aws_session_manager.get_credentials_dict(request.aws_session_id)
            if boto3_creds:
                self.add_log(deployment_id, LogLevel.INFO, "  [OK] Found credentials by session_id")
        
        # Fallback: Try to find matching session
        if not boto3_creds:
            self.add_log(deployment_id, LogLevel.INFO, "  [TOOL] Trying fallback: searching for matching session...")
            sessions = aws_session_manager.sessions
            self.add_log(deployment_id, LogLevel.INFO, f"  Available sessions: {list(sessions.keys())}")
            
            for sid, session in sessions.items():
                self.add_log(deployment_id, LogLevel.INFO, f"  Checking session {sid}: account={session.get('account_id')}, region={session.get('region')}")
                if (session.get('account_id') == request.account_id and 
                    session.get('region') == request.region):
                    boto3_creds = aws_session_manager.get_credentials_dict(sid)
                    if boto3_creds:
                        self.add_log(deployment_id, LogLevel.INFO, f"  [OK] Found matching session: {sid}")
                        break
        
        if not boto3_creds:
            self.add_log(deployment_id, LogLevel.ERROR, "  [X] No AWS credentials found!")
            self.add_log(deployment_id, LogLevel.ERROR, "  Please re-authenticate in Step 4 and try again.")
            raise Exception("Unable to locate credentials. AWS session not found or expired.")
        
        # Prepare credentials for deployment
        client_creds = {
            'aws_access_key_id': boto3_creds.get('aws_access_key_id'),
            'aws_secret_access_key': boto3_creds.get('aws_secret_access_key'),
            'aws_session_token': boto3_creds.get('aws_session_token'),
        }
        
        self.add_log(deployment_id, LogLevel.INFO, "  [OK] AWS credentials retrieved successfully")
        
        # Load config - pass installation_id to enable stack operation logging
        installation_id = deployment.get("installation_id")
        orchestrator = DeploymentOrchestrator(client_creds, installation_id=installation_id)
        config = orchestrator.load_config(config_path)
        
        # Progress callback - runs in thread, so keep it simple
        def progress_callback(message: str):
            # Check for cancellation
            if deployment.get("cancelled"):
                self.add_log(deployment_id, LogLevel.WARNING, "  [!] Cancellation detected, stopping deployment...")
                raise Exception("Deployment cancelled by user")
            
            # Add log entry
            self.add_log(deployment_id, LogLevel.INFO, message)
            
            # Update progress based on message content
            message_lower = message.lower()
            if "frontend-global" in message_lower:
                deployment["progress"] = 20
                deployment["current_stage"] = DeploymentStage.FRONTEND_GLOBAL
            elif "frontend-cognito" in message_lower:
                deployment["progress"] = 30
                deployment["current_stage"] = DeploymentStage.FRONTEND_COGNITO
            elif "frontend-regional" in message_lower:
                deployment["progress"] = 40
                deployment["current_stage"] = DeploymentStage.FRONTEND_REGIONAL
            elif "backend-foundation" in message_lower:
                deployment["progress"] = 50
                deployment["current_stage"] = DeploymentStage.BACKEND_FOUNDATION
            elif "backend-storage" in message_lower:
                deployment["progress"] = 60
                deployment["current_stage"] = DeploymentStage.BACKEND_STORAGE
            elif "backend-network" in message_lower:
                deployment["progress"] = 70
                deployment["current_stage"] = DeploymentStage.BACKEND_NETWORK
            elif "backend-service" in message_lower:
                deployment["progress"] = 85
                deployment["current_stage"] = DeploymentStage.BACKEND_SERVICE
            elif "frontend artifacts" in message_lower or "uploading" in message_lower:
                deployment["progress"] = 95
                deployment["current_stage"] = DeploymentStage.FRONTEND_UPLOAD
        
        # Execute deployment in thread pool to avoid blocking event loop
        # This allows logs to be added in real-time while CloudFormation operations run
        loop = asyncio.get_event_loop()
        
        def run_deployment():
            """Run deployment in thread pool"""
            try:
                # Check if deployment strategy is specified
                if request.deployment_strategy:
                    from app.models.stack_detection import DeploymentStrategy
                    
                    # Convert string to enum
                    strategy = DeploymentStrategy(request.deployment_strategy)
                    self.add_log(deployment_id, LogLevel.INFO, f"[LIST] Using deployment strategy: {strategy.value}")
                    
                    return orchestrator.deploy_capability_with_strategy(
                        config,
                        strategy=strategy,
                        deploy_frontend=request.deploy_frontend,
                        deploy_backend=request.deploy_backend,
                        callback=progress_callback
                    )
                else:
                    # No strategy specified - use normal deployment (backward compatible)
                    return orchestrator.deploy_capability(
                        config,
                        deploy_frontend=request.deploy_frontend,
                        deploy_backend=request.deploy_backend,
                        callback=progress_callback
                    )
            except Exception as e:
                # Check if this was a cancellation
                if "cancelled" in str(e).lower():
                    self.add_log(deployment_id, LogLevel.WARNING, "[OK] Deployment cancelled successfully")
                    return {
                        'success': False,
                        'cancelled': True,
                        'stacks': {},
                        'error': 'Deployment cancelled by user'
                    }
                raise
        
        # Run in thread pool executor
        try:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                result = await loop.run_in_executor(executor, run_deployment)
            
            # Check if cancelled
            if result.get('cancelled'):
                return False
            
            # Store results
            deployment["frontend_url"] = result.get('frontend_url')
            deployment["backend_url"] = result.get('backend_url')
            
            # Convert stacks to proper format for Pydantic model
            stacks_list = []
            for name, info in result.get('stacks', {}).items():
                # Extract stack type from name (e.g., "capability-env-frontend-global" -> "frontend-global")
                parts = name.split('-')
                stack_type = '-'.join(parts[2:]) if len(parts) > 2 else name
                
                stacks_list.append({
                    "stack_name": name,
                    "stack_type": stack_type,
                    "status": "deployed" if info['success'] else "failed",
                    "region": request.region,
                })
            
            deployment["stacks"] = stacks_list
            
            return result.get('success', False)
        except Exception as e:
            # Handle cancellation or other errors
            if deployment.get("cancelled"):
                self.add_log(deployment_id, LogLevel.WARNING, "[OK] Deployment stopped")
                return False
            raise
    
    def _get_stage_message(self, stage: Optional[DeploymentStage]) -> Optional[str]:
        """Get human-readable message for stage"""
        if not stage:
            return None
        
        messages = {
            DeploymentStage.INITIALIZATION: "Initializing deployment",
            DeploymentStage.INFRASTRUCTURE_PROVISIONING: "Provisioning infrastructure resources",
            DeploymentStage.ARTIFACT_VERIFICATION: "Verifying artifacts",
            DeploymentStage.FRONTEND_GLOBAL: "Deploying frontend global resources",
            DeploymentStage.FRONTEND_COGNITO: "Setting up authentication",
            DeploymentStage.FRONTEND_REGIONAL: "Deploying CloudFront distribution",
            DeploymentStage.FRONTEND_UPLOAD: "Uploading frontend artifacts",
            DeploymentStage.BACKEND_FOUNDATION: "Deploying backend foundation",
            DeploymentStage.BACKEND_STORAGE: "Creating storage resources",
            DeploymentStage.BACKEND_NETWORK: "Configuring network",
            DeploymentStage.BACKEND_SERVICE: "Deploying application service",
            DeploymentStage.VERIFICATION: "Verifying deployment",
            DeploymentStage.COMPLETED: "Deployment complete",
        }
        
        return messages.get(stage, str(stage))


# Global service instance
deployment_service = DeploymentService()

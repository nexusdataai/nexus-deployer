"""
Discovery API Router

Provides REST API endpoints for capability discovery operations including:
- Landing zone management (CRUD)
- Capability discovery from CloudFormation stacks
- Discovery status tracking
"""

import uuid
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum

from fastapi import APIRouter, HTTPException, BackgroundTasks, Query as QueryParam
from pydantic import BaseModel, Field

from app.services.aws_session_manager import aws_session_manager
from app.services.discovery.discovery_service import DiscoveryService
from app.services.discovery.landing_zone_manager import LandingZoneManager, get_landing_zone_manager
from app.services.discovery.discovery_sync_service import DiscoverySyncService
from app.services.discovery.models import CloudProvider

import boto3
from botocore.exceptions import ClientError

from app.utils.aws_vpc_endpoints import merge_vpc_boto3_kwargs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/discovery", tags=["discovery"])

# In-memory storage for discovery jobs
_discovery_jobs: Dict[str, Dict[str, Any]] = {}
# In-memory storage for discovery logs
_discovery_logs: Dict[str, List[Dict[str, str]]] = {}


def _add_discovery_log(job_id: str, level: str, message: str):
    """Add a log entry to a discovery job."""
    if job_id not in _discovery_logs:
        _discovery_logs[job_id] = []
    _discovery_logs[job_id].append({
        "timestamp": datetime.utcnow().isoformat(),
        "level": level,
        "message": message,
    })
    # Also update progress_message for backward compat
    if job_id in _discovery_jobs:
        _discovery_jobs[job_id]["progress_message"] = message


# ============================================================================
# Request/Response Models
# ============================================================================

class CloudProviderEnum(str, Enum):
    """Cloud provider options."""
    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"


class CreateLandingZoneRequest(BaseModel):
    """Request to create a landing zone."""
    name: str = Field(..., description="User-friendly name for the landing zone")
    provider: CloudProviderEnum = Field(..., description="Cloud provider (aws, azure, gcp)")
    account_id: str = Field(..., description="Cloud account identifier")
    default_region: str = Field(default="us-east-1", description="Default region for discovery")
    account_alias: Optional[str] = Field(default=None, description="Optional account alias")


class LandingZoneResponse(BaseModel):
    """Landing zone response model."""
    landing_zone_id: str
    name: str
    provider: str
    account_id: str
    account_alias: Optional[str]
    default_region: str
    created_at: str
    last_discovery_at: Optional[str]
    discovery_status: str
    capabilities_count: int


class StartDiscoveryRequest(BaseModel):
    """Request to start capability discovery."""
    landing_zone_id: str = Field(..., description="Landing zone to discover capabilities in")
    aws_session_id: Optional[str] = Field(default=None, description="AWS session ID for credentials")
    regions: Optional[List[str]] = Field(default=None, description="Regions to scan (defaults to landing zone region)")


class DiscoveryStatusResponse(BaseModel):
    """Discovery job status response."""
    job_id: str
    landing_zone_id: str
    status: str
    started_at: str
    completed_at: Optional[str]
    stacks_scanned: int
    capabilities_found: int
    errors: List[str]
    progress_message: str


class DiscoveryLogEntry(BaseModel):
    """Single log entry from a discovery job."""
    timestamp: str
    level: str  # INFO, WARNING, ERROR
    message: str


class DiscoveredCapabilityResponse(BaseModel):
    """Discovered capability response model."""
    capability_name: str
    environment: str
    account_id: str
    primary_region: str
    status: str
    stacks_count: int
    missing_stacks: List[str]
    discovered_at: str
    version: Optional[str]
    frontend_url: Optional[str]
    backend_url: Optional[str]
    landing_zone_id: str


class SyncStatsResponse(BaseModel):
    """Sync statistics response."""
    created: int
    updated: int
    marked_not_found: int


# ============================================================================
# Landing Zone Endpoints
# ============================================================================

@router.post("/landing-zones", response_model=LandingZoneResponse)
async def create_landing_zone(request: CreateLandingZoneRequest):
    """
    Create or update a landing zone configuration.
    
    If a landing zone with the same provider and account_id exists,
    it will be updated instead of creating a duplicate.
    """
    # Only AWS is currently supported
    if request.provider != CloudProviderEnum.AWS:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{request.provider.value}' is not yet supported. Only AWS is currently available."
        )
    
    manager = get_landing_zone_manager()
    landing_zone_id = manager.create_landing_zone(
        name=request.name,
        provider=CloudProvider(request.provider.value),
        account_id=request.account_id,
        default_region=request.default_region,
        account_alias=request.account_alias,
    )
    
    landing_zone = manager.get_landing_zone(landing_zone_id)
    if not landing_zone:
        raise HTTPException(status_code=500, detail="Failed to create landing zone")
    
    return LandingZoneResponse(**landing_zone)


@router.get("/landing-zones", response_model=List[LandingZoneResponse])
async def list_landing_zones(
    provider: Optional[CloudProviderEnum] = QueryParam(default=None, description="Filter by cloud provider")
):
    """List all configured landing zones."""
    manager = get_landing_zone_manager()
    
    cloud_provider = CloudProvider(provider.value) if provider else None
    landing_zones = manager.list_landing_zones(provider=cloud_provider)
    
    return [LandingZoneResponse(**lz) for lz in landing_zones]


@router.get("/landing-zones/{landing_zone_id}", response_model=LandingZoneResponse)
async def get_landing_zone(landing_zone_id: str):
    """Get a specific landing zone by ID."""
    manager = get_landing_zone_manager()
    landing_zone = manager.get_landing_zone(landing_zone_id)
    
    if not landing_zone:
        raise HTTPException(status_code=404, detail="Landing zone not found")
    
    return LandingZoneResponse(**landing_zone)


@router.delete("/landing-zones/{landing_zone_id}")
async def delete_landing_zone(landing_zone_id: str):
    """
    Delete a landing zone configuration.
    
    Note: This does not delete discovered capability records.
    """
    manager = get_landing_zone_manager()
    
    if not manager.delete_landing_zone(landing_zone_id):
        raise HTTPException(status_code=404, detail="Landing zone not found")
    
    return {"message": "Landing zone deleted", "landing_zone_id": landing_zone_id}


# ============================================================================
# Discovery Endpoints
# ============================================================================

@router.post("/discover", response_model=DiscoveryStatusResponse)
async def start_discovery(
    request: StartDiscoveryRequest,
    background_tasks: BackgroundTasks
):
    """
    Start capability discovery for a landing zone.
    
    This scans CloudFormation stacks in the AWS account and identifies
    capabilities based on the stack naming convention.
    """
    manager = get_landing_zone_manager()
    landing_zone = manager.get_landing_zone(request.landing_zone_id)
    
    if not landing_zone:
        raise HTTPException(status_code=404, detail="Landing zone not found")
    
    # Get AWS credentials from session
    credentials = None
    if request.aws_session_id:
        credentials = aws_session_manager.get_credentials_dict(request.aws_session_id)
        if not credentials:
            raise HTTPException(
                status_code=401,
                detail="AWS session expired or not found. Please re-authenticate."
            )
    
    # Create discovery job
    job_id = str(uuid.uuid4())[:8]
    _discovery_jobs[job_id] = {
        "job_id": job_id,
        "landing_zone_id": request.landing_zone_id,
        "status": "pending",
        "started_at": datetime.utcnow().isoformat(),
        "completed_at": None,
        "stacks_scanned": 0,
        "capabilities_found": 0,
        "errors": [],
        "progress_message": "Initializing discovery...",
    }
    
    # Determine regions to scan
    regions = request.regions or [landing_zone["default_region"]]
    
    # Start background discovery task
    background_tasks.add_task(
        _run_discovery,
        job_id,
        request.landing_zone_id,
        landing_zone["account_id"],
        regions,
        credentials,
    )
    
    return DiscoveryStatusResponse(**_discovery_jobs[job_id])


@router.get("/discover/{job_id}/status", response_model=DiscoveryStatusResponse)
async def get_discovery_status(job_id: str):
    """Get the status of a discovery job."""
    if job_id not in _discovery_jobs:
        raise HTTPException(status_code=404, detail="Discovery job not found")
    
    return DiscoveryStatusResponse(**_discovery_jobs[job_id])


@router.get("/discover/{job_id}/logs", response_model=List[DiscoveryLogEntry])
async def get_discovery_logs(
    job_id: str,
    limit: Optional[int] = QueryParam(default=None, description="Max number of log entries to return")
):
    """Get logs for a discovery job."""
    if job_id not in _discovery_jobs:
        raise HTTPException(status_code=404, detail="Discovery job not found")
    
    logs = _discovery_logs.get(job_id, [])
    if limit and limit > 0:
        logs = logs[-limit:]
    return [DiscoveryLogEntry(**entry) for entry in logs]


@router.post("/refresh/{landing_zone_id}", response_model=DiscoveryStatusResponse)
async def refresh_capabilities(
    landing_zone_id: str,
    background_tasks: BackgroundTasks,
    aws_session_id: Optional[str] = QueryParam(default=None, description="AWS session ID")
):
    """
    Refresh capabilities for a landing zone by re-running discovery.
    
    This is a convenience endpoint that starts a new discovery job.
    """
    request = StartDiscoveryRequest(
        landing_zone_id=landing_zone_id,
        aws_session_id=aws_session_id,
    )
    return await start_discovery(request, background_tasks)


@router.get("/capabilities", response_model=List[DiscoveredCapabilityResponse])
async def list_discovered_capabilities(
    landing_zone_id: Optional[str] = QueryParam(default=None, description="Filter by landing zone"),
    account_id: Optional[str] = QueryParam(default=None, description="Filter by account ID")
):
    """List all discovered capabilities."""
    sync_service = DiscoverySyncService()
    capabilities = sync_service.get_discovered_capabilities(
        landing_zone_id=landing_zone_id,
        account_id=account_id,
    )
    
    result = []
    for cap in capabilities:
        result.append(DiscoveredCapabilityResponse(
            capability_name=cap["capability_name"],
            environment=cap["environment"],
            account_id=cap["account_id"],
            primary_region=cap.get("region", "unknown"),
            status=cap["status"],
            stacks_count=cap.get("stacks_summary", {}).get("total", 0),
            missing_stacks=cap.get("missing_stacks", []),
            discovered_at=cap.get("discovered_at", ""),
            version=cap.get("capability_version"),
            frontend_url=cap.get("frontend_url"),
            backend_url=cap.get("backend_url"),
            landing_zone_id=cap.get("landing_zone_id", ""),
        ))
    
    return result


# ============================================================================
# Background Task
# ============================================================================

def _run_discovery(
    job_id: str,
    landing_zone_id: str,
    account_id: str,
    regions: List[str],
    credentials: Optional[Dict[str, str]],
):
    """
    Background task to run capability discovery.
    
    Args:
        job_id: Discovery job ID
        landing_zone_id: Landing zone identifier
        account_id: AWS account ID
        regions: List of regions to scan
        credentials: AWS credentials dict
    """
    job = _discovery_jobs.get(job_id)
    if not job:
        logger.error(f"Discovery job {job_id} not found")
        return
    
    job["status"] = "running"
    _add_discovery_log(job_id, "INFO", f"[LAUNCH] Starting capability discovery for account {account_id}")
    _add_discovery_log(job_id, "INFO", f"Regions to scan: {', '.join(regions)}")
    
    manager = get_landing_zone_manager()
    manager.update_discovery_status(landing_zone_id, "running")
    
    all_capabilities = []
    all_errors = []
    total_stacks = 0
    
    try:
        for region in regions:
            _add_discovery_log(job_id, "INFO", f"")
            _add_discovery_log(job_id, "INFO", f"━━━ Scanning region: {region} ━━━")
            logger.info(f"Discovery job {job_id}: Scanning region {region}")
            
            # Phase 1: CloudFormation Stack Discovery
            _add_discovery_log(job_id, "INFO", f"[CFN] Phase 1: Scanning CloudFormation stacks...")
            
            # Create discovery service for this region
            service = DiscoveryService(
                region=region,
                credentials=credentials,
            )
            
            # Progress callback to update job status and logs
            def progress_callback(msg: str):
                job["progress_message"] = msg
                _add_discovery_log(job_id, "INFO", f"  {msg}")
            
            # Run CloudFormation discovery
            capabilities, errors = service.discover_capabilities(
                landing_zone_id=landing_zone_id,
                account_id=account_id,
                progress_callback=progress_callback,
            )
            
            if capabilities:
                _add_discovery_log(job_id, "INFO", f"[CFN] Found {len(capabilities)} capabilities from CloudFormation stacks")
                for cap in capabilities:
                    status_icon = "✓" if cap.status.value == "healthy" else "⚠" if cap.status.value == "partial" else "✗"
                    _add_discovery_log(job_id, "INFO", f"  {status_icon} {cap.capability_name} ({cap.environment}) - {cap.status.value} - {len(cap.stacks)} stacks")
            else:
                _add_discovery_log(job_id, "INFO", f"[CFN] No capabilities found from CloudFormation stacks")
            
            if errors:
                for err in errors:
                    _add_discovery_log(job_id, "WARNING", f"  ⚠ {err}")
            
            # Phase 2: EKS Cluster Discovery
            _add_discovery_log(job_id, "INFO", f"")
            _add_discovery_log(job_id, "INFO", f"[EKS] Phase 2: Scanning EKS clusters...")
            
            try:
                eks_capabilities, eks_errors = _discover_eks_capabilities(
                    region=region,
                    credentials=credentials,
                    landing_zone_id=landing_zone_id,
                    account_id=account_id,
                    job_id=job_id,
                )
                
                if eks_capabilities:
                    _add_discovery_log(job_id, "INFO", f"[EKS] Found {len(eks_capabilities)} capabilities from EKS clusters")
                    for cap in eks_capabilities:
                        _add_discovery_log(job_id, "INFO", f"  ✓ {cap.capability_name} ({cap.environment}) - EKS - {cap.primary_region}")
                    capabilities.extend(eks_capabilities)
                else:
                    _add_discovery_log(job_id, "INFO", f"[EKS] No capabilities found from EKS clusters")
                
                if eks_errors:
                    for err in eks_errors:
                        _add_discovery_log(job_id, "WARNING", f"  ⚠ {err}")
                    all_errors.extend(eks_errors)
            except Exception as e:
                _add_discovery_log(job_id, "WARNING", f"[EKS] EKS discovery skipped: {str(e)}")
            
            all_capabilities.extend(capabilities)
            all_errors.extend(errors)
            total_stacks += sum(len(c.stacks) for c in capabilities)
            
            _add_discovery_log(job_id, "INFO", f"Region {region} scan complete: {len(capabilities)} capabilities")
            logger.info(f"Discovery job {job_id}: Found {len(capabilities)} capabilities in {region}")
        
        # Sync to TinyDB
        _add_discovery_log(job_id, "INFO", f"")
        _add_discovery_log(job_id, "INFO", f"[SYNC] Syncing {len(all_capabilities)} discovered capabilities to database...")
        sync_service = DiscoverySyncService()
        sync_stats = sync_service.sync_discovered_capabilities(all_capabilities, landing_zone_id)
        
        _add_discovery_log(job_id, "INFO", f"[SYNC] Sync complete - created: {sync_stats.get('created', 0)}, updated: {sync_stats.get('updated', 0)}, not_found: {sync_stats.get('marked_not_found', 0)}")
        logger.info(f"Discovery job {job_id}: Sync complete - {sync_stats}")
        
        # Update job status
        job["status"] = "completed"
        job["completed_at"] = datetime.utcnow().isoformat()
        job["stacks_scanned"] = total_stacks
        job["capabilities_found"] = len(all_capabilities)
        job["errors"] = all_errors
        job["progress_message"] = f"Discovery complete: {len(all_capabilities)} capabilities found across {len(regions)} region(s)"
        
        _add_discovery_log(job_id, "INFO", f"")
        _add_discovery_log(job_id, "INFO", f"[OK] Discovery complete: {len(all_capabilities)} capabilities found across {len(regions)} region(s)")
        
        # Update landing zone
        manager.update_discovery_status(
            landing_zone_id,
            "completed",
            capabilities_count=len(all_capabilities),
        )
        
        logger.info(f"Discovery job {job_id}: Completed successfully")
        
    except Exception as e:
        error_msg = str(e)
        logger.exception(f"Discovery job {job_id} failed: {error_msg}")
        
        job["status"] = "failed"
        job["completed_at"] = datetime.utcnow().isoformat()
        job["errors"].append(error_msg)
        job["progress_message"] = f"Discovery failed: {error_msg}"
        
        _add_discovery_log(job_id, "ERROR", f"[X] Discovery failed: {error_msg}")
        
        manager.update_discovery_status(landing_zone_id, "failed")


def _discover_eks_capabilities(
    region: str,
    credentials: Optional[Dict[str, str]],
    landing_zone_id: str,
    account_id: str,
    job_id: str,
) -> tuple:
    """
    Discover capabilities running inside EKS clusters.
    
    Scans for EKS clusters, then checks for namespaces and deployments
    that match capability naming conventions.
    
    Returns:
        Tuple of (discovered_capabilities, errors)
    """
    from app.services.discovery.models import DiscoveredCapability, DiscoveredStack, CapabilityStatus
    
    capabilities = []
    errors = []
    
    try:
        creds = credentials or {}
        eks_client = boto3.client(
            "eks",
            **merge_vpc_boto3_kwargs("eks", region, {**creds, "region_name": region}),
        )
        
        # List all EKS clusters
        _add_discovery_log(job_id, "INFO", f"  Listing EKS clusters in {region}...")
        
        clusters = []
        paginator = eks_client.get_paginator("list_clusters")
        for page in paginator.paginate():
            clusters.extend(page.get("clusters", []))
        
        if not clusters:
            _add_discovery_log(job_id, "INFO", f"  No EKS clusters found in {region}")
            return capabilities, errors
        
        _add_discovery_log(job_id, "INFO", f"  Found {len(clusters)} EKS cluster(s): {', '.join(clusters)}")
        
        for cluster_name in clusters:
            _add_discovery_log(job_id, "INFO", f"  Inspecting cluster: {cluster_name}")
            
            try:
                # Get cluster details
                cluster_info = eks_client.describe_cluster(name=cluster_name)
                cluster = cluster_info.get("cluster", {})
                cluster_status = cluster.get("status", "UNKNOWN")
                k8s_version = cluster.get("version", "unknown")
                
                _add_discovery_log(job_id, "INFO", f"    Status: {cluster_status}, K8s version: {k8s_version}")
                
                if cluster_status != "ACTIVE":
                    _add_discovery_log(job_id, "WARNING", f"    Skipping cluster {cluster_name} (status: {cluster_status})")
                    continue
                
                # Check cluster tags for capability info
                tags = cluster.get("tags", {})
                capability_name = tags.get("CapabilityName") or tags.get("capability-name") or tags.get("totogi:capability")
                environment = tags.get("Environment") or tags.get("environment") or tags.get("env")
                
                if capability_name and environment:
                    _add_discovery_log(job_id, "INFO", f"    Found capability from tags: {capability_name} ({environment})")
                    
                    # Create a synthetic stack entry for the EKS cluster
                    eks_stack = DiscoveredStack(
                        stack_name=f"eks-{cluster_name}",
                        stack_type="eks-cluster",
                        stack_status=cluster_status,
                        region=region,
                        outputs={"ClusterName": cluster_name, "ClusterEndpoint": cluster.get("endpoint", "")},
                        tags=tags,
                    )
                    
                    version = tags.get("Version") or tags.get("version") or tags.get("CapabilityVersion")
                    
                    capabilities.append(DiscoveredCapability(
                        capability_name=capability_name,
                        environment=environment,
                        landing_zone_id=landing_zone_id,
                        account_id=account_id,
                        primary_region=region,
                        status=CapabilityStatus.HEALTHY,
                        stacks=[eks_stack],
                        missing_stacks=[],
                        discovered_at=datetime.utcnow(),
                        version=version,
                        frontend_url=None,
                        backend_url=cluster.get("endpoint"),
                    ))
                else:
                    # Try to detect capabilities from CloudFormation stacks associated with this cluster
                    # Many EKS clusters are created via CloudFormation
                    cfn_stack_name = tags.get("aws:cloudformation:stack-name")
                    if cfn_stack_name:
                        _add_discovery_log(job_id, "INFO", f"    Cluster managed by CloudFormation stack: {cfn_stack_name}")
                    else:
                        _add_discovery_log(job_id, "INFO", f"    No capability tags found on cluster {cluster_name}, checking nodegroups...")
                    
                    # Check nodegroup tags as fallback
                    try:
                        ng_response = eks_client.list_nodegroups(clusterName=cluster_name)
                        nodegroups = ng_response.get("nodegroups", [])
                        if nodegroups:
                            _add_discovery_log(job_id, "INFO", f"    Nodegroups: {', '.join(nodegroups)}")
                        for ng_name in nodegroups:
                            ng_info = eks_client.describe_nodegroup(clusterName=cluster_name, nodegroupName=ng_name)
                            ng_tags = ng_info.get("nodegroup", {}).get("tags", {})
                            ng_cap = ng_tags.get("CapabilityName") or ng_tags.get("capability-name") or ng_tags.get("totogi:capability")
                            ng_env = ng_tags.get("Environment") or ng_tags.get("environment") or ng_tags.get("env")
                            if ng_cap and ng_env:
                                _add_discovery_log(job_id, "INFO", f"    Found capability from nodegroup {ng_name}: {ng_cap} ({ng_env})")
                                
                                eks_stack = DiscoveredStack(
                                    stack_name=f"eks-{cluster_name}-{ng_name}",
                                    stack_type="eks-nodegroup",
                                    stack_status="ACTIVE",
                                    region=region,
                                    outputs={"ClusterName": cluster_name, "NodegroupName": ng_name},
                                    tags=ng_tags,
                                )
                                
                                capabilities.append(DiscoveredCapability(
                                    capability_name=ng_cap,
                                    environment=ng_env,
                                    landing_zone_id=landing_zone_id,
                                    account_id=account_id,
                                    primary_region=region,
                                    status=CapabilityStatus.HEALTHY,
                                    stacks=[eks_stack],
                                    missing_stacks=[],
                                    discovered_at=datetime.utcnow(),
                                    version=ng_tags.get("Version") or ng_tags.get("version"),
                                    frontend_url=None,
                                    backend_url=None,
                                ))
                    except ClientError as e:
                        _add_discovery_log(job_id, "WARNING", f"    Could not list nodegroups for {cluster_name}: {str(e)}")
                
            except ClientError as e:
                error_msg = f"Error inspecting cluster {cluster_name}: {str(e)}"
                errors.append(error_msg)
                _add_discovery_log(job_id, "WARNING", f"    {error_msg}")
    
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "AccessDeniedException":
            _add_discovery_log(job_id, "WARNING", f"  EKS access denied - skipping EKS discovery (missing eks:ListClusters permission)")
        else:
            error_msg = f"EKS API error [{error_code}]: {str(e)}"
            errors.append(error_msg)
            _add_discovery_log(job_id, "WARNING", f"  {error_msg}")
    except Exception as e:
        error_msg = f"Unexpected error during EKS discovery: {str(e)}"
        errors.append(error_msg)
        _add_discovery_log(job_id, "ERROR", f"  {error_msg}")
    
    return capabilities, errors


# ============================================================================
# Utility Endpoints
# ============================================================================

@router.get("/jobs")
async def list_discovery_jobs():
    """List all discovery jobs (for debugging)."""
    return list(_discovery_jobs.values())


@router.delete("/jobs/{job_id}")
async def delete_discovery_job(job_id: str):
    """Delete a discovery job from memory."""
    if job_id in _discovery_jobs:
        del _discovery_jobs[job_id]
        return {"message": "Job deleted", "job_id": job_id}
    raise HTTPException(status_code=404, detail="Job not found")

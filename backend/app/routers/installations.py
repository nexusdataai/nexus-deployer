"""
Installation history API endpoints
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel

from app.services.installation_tracker import get_installation_tracker


router = APIRouter(prefix="/api/installations", tags=["installations"])


class InstallationSummary(BaseModel):
    """Summary of an installation for list view"""
    installation_id: str
    capability_name: str
    capability_version: str
    environment: str
    region: str
    account_id: str
    strategy: str
    status: str
    started_at: str
    completed_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    error: Optional[str] = None
    stacks_summary: Optional[dict] = None


class InstallationDetail(BaseModel):
    """Full installation details with logs"""
    installation_id: str
    capability_name: str
    capability_version: str
    environment: str
    region: str
    account_id: str
    strategy: str
    deploy_frontend: bool
    deploy_backend: bool
    status: str
    started_at: str
    completed_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    error: Optional[str] = None
    frontend_url: Optional[str] = None
    backend_url: Optional[str] = None
    cognito_config: Optional[dict] = None
    stacks_summary: Optional[dict] = None
    logs: List[dict] = []
    installation_log: Optional[str] = None  # Full deployment log text


class StackOperationLogEntry(BaseModel):
    """Stack operation log entry"""
    log_id: str
    installation_id: str
    stack_name: str
    stack_type: str
    operation: str
    status: str
    region: str
    started_at: str
    completed_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    error_message: Optional[str] = None
    stack_outputs: Optional[dict] = None


class InstallationListResponse(BaseModel):
    """Response for installation list"""
    installations: List[InstallationSummary]
    total: int


class InstallationLogsResponse(BaseModel):
    """Response for installation logs"""
    installation_id: str
    logs: List[StackOperationLogEntry]
    total: int


@router.get("", response_model=InstallationListResponse)
async def list_installations(
    capability_name: Optional[str] = Query(None, description="Filter by capability name"),
    environment: Optional[str] = Query(None, description="Filter by environment"),
    status: Optional[str] = Query(None, description="Filter by status"),
    start_date: Optional[str] = Query(None, description="Filter by start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="Filter by end date (ISO format)"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results to return")
):
    """
    List installations with optional filters.
    
    Results are sorted by started_at in descending order (newest first).
    """
    tracker = get_installation_tracker()
    
    # Parse dates if provided
    start_dt = None
    end_dt = None
    
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format")
    
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format")
    
    installations = tracker.list_installations(
        capability_name=capability_name,
        environment=environment,
        status=status,
        start_date=start_dt,
        end_date=end_dt,
        limit=limit
    )
    
    summaries = [
        InstallationSummary(
            installation_id=i["installation_id"],
            capability_name=i["capability_name"],
            capability_version=i["capability_version"],
            environment=i["environment"],
            region=i["region"],
            account_id=i["account_id"],
            strategy=i["strategy"],
            status=i["status"],
            started_at=i["started_at"],
            completed_at=i.get("completed_at"),
            duration_seconds=i.get("duration_seconds"),
            error=i.get("error"),
            stacks_summary=i.get("stacks_summary")
        )
        for i in installations
    ]
    
    return InstallationListResponse(
        installations=summaries,
        total=len(summaries)
    )


@router.get("/{installation_id}", response_model=InstallationDetail)
async def get_installation(installation_id: str):
    """
    Get installation details with all logs.
    """
    tracker = get_installation_tracker()
    
    installation = tracker.get_installation(installation_id)
    
    if not installation:
        raise HTTPException(status_code=404, detail="Installation not found")
    
    return InstallationDetail(
        installation_id=installation["installation_id"],
        capability_name=installation["capability_name"],
        capability_version=installation["capability_version"],
        environment=installation["environment"],
        region=installation["region"],
        account_id=installation["account_id"],
        strategy=installation["strategy"],
        deploy_frontend=installation["deploy_frontend"],
        deploy_backend=installation["deploy_backend"],
        status=installation["status"],
        started_at=installation["started_at"],
        completed_at=installation.get("completed_at"),
        duration_seconds=installation.get("duration_seconds"),
        error=installation.get("error"),
        frontend_url=installation.get("frontend_url"),
        backend_url=installation.get("backend_url"),
        cognito_config=installation.get("cognito_config"),
        stacks_summary=installation.get("stacks_summary"),
        logs=installation.get("logs", []),
        installation_log=_read_installation_log(installation_id)
    )


def _read_installation_log(installation_id: str) -> Optional[str]:
    """Read installation log file content."""
    try:
        from app.services.installation_log_writer import read_installation_log
        content = read_installation_log(installation_id)
        return content if content else None
    except Exception:
        return None


@router.get("/{installation_id}/logs", response_model=InstallationLogsResponse)
async def get_installation_logs(installation_id: str):
    """
    Get stack operation logs for an installation.
    """
    tracker = get_installation_tracker()
    
    # Verify installation exists
    installation = tracker.get_installation(installation_id)
    if not installation:
        raise HTTPException(status_code=404, detail="Installation not found")
    
    logs = tracker.get_stack_logs(installation_id)
    
    log_entries = [
        StackOperationLogEntry(
            log_id=log["log_id"],
            installation_id=log["installation_id"],
            stack_name=log["stack_name"],
            stack_type=log["stack_type"],
            operation=log["operation"],
            status=log["status"],
            region=log["region"],
            started_at=log["started_at"],
            completed_at=log.get("completed_at"),
            duration_seconds=log.get("duration_seconds"),
            error_message=log.get("error_message"),
            stack_outputs=log.get("stack_outputs")
        )
        for log in logs
    ]
    
    return InstallationLogsResponse(
        installation_id=installation_id,
        logs=log_entries,
        total=len(log_entries)
    )


@router.delete("/{installation_id}")
async def delete_installation(installation_id: str):
    """
    Delete an installation and its logs.
    """
    tracker = get_installation_tracker()
    
    # Verify installation exists
    installation = tracker.get_installation(installation_id)
    if not installation:
        raise HTTPException(status_code=404, detail="Installation not found")
    
    success = tracker.delete_installation(installation_id)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete installation")
    
    return {"message": "Installation deleted successfully"}


@router.get("/{installation_id}/deployment-log")
async def get_deployment_log(installation_id: str):
    """
    Get the full deployment log text for an installation.
    Returns the complete deployment log that was captured during deployment.
    """
    from fastapi.responses import PlainTextResponse
    
    tracker = get_installation_tracker()
    
    # Verify installation exists
    installation = tracker.get_installation(installation_id)
    if not installation:
        raise HTTPException(status_code=404, detail="Installation not found")
    
    log_content = _read_installation_log(installation_id)
    
    if not log_content:
        raise HTTPException(status_code=404, detail="Deployment log not found")
    
    return PlainTextResponse(
        content=log_content,
        media_type="text/plain"
    )


@router.get("/{installation_id}/deployment-log/download")
async def download_deployment_log(installation_id: str):
    """
    Download the deployment log as a file.
    """
    from fastapi.responses import Response
    
    tracker = get_installation_tracker()
    
    # Verify installation exists
    installation = tracker.get_installation(installation_id)
    if not installation:
        raise HTTPException(status_code=404, detail="Installation not found")
    
    log_content = _read_installation_log(installation_id)
    
    if not log_content:
        raise HTTPException(status_code=404, detail="Deployment log not found")
    
    # Create filename from installation details
    capability_name = installation.get("capability_name", "unknown")
    environment = installation.get("environment", "unknown")
    started_at = installation.get("started_at", "")[:10]  # Get date part
    filename = f"deployment-log-{capability_name}-{environment}-{started_at}.txt"
    
    return Response(
        content=log_content,
        media_type="text/plain",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )

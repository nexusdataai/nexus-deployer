"""
Pydantic models for the 10-step Pure-EKS deployment pipeline.

Each step in `EksPipelineOrchestrator` returns a typed report. The
frontend `ClusterPreflight` and `InspectCapability` components render
these reports directly, so field names here are part of the API surface.
"""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


CheckStatus = Literal["pass", "warn", "fail", "skipped"]
OverallStatus = Literal["pass", "warn", "fail"]


class PipelineCheck(BaseModel):
    """One row in any pipeline report.

    Convention:
      - status='pass'    -> green; nothing required.
      - status='warn'    -> amber; user can continue but should know.
      - status='fail'    -> red; wizard 'Continue' is gated until resolved.
      - status='skipped' -> grey; intentionally not run on this path.
    """
    name: str = Field(..., description="Stable machine-readable id, e.g. 'cluster_active'")
    label: str = Field(..., description="Human-readable label for the wizard UI")
    status: CheckStatus
    detail: str = Field("", description="One-line human-readable explanation")
    remediation: Optional[str] = Field(None, description="Actionable hint when status is fail")
    extra: Dict[str, Any] = Field(default_factory=dict, description="Optional structured data")


class ClusterReadinessReport(BaseModel):
    """Step 1 report: cluster scan, 11 (now 10 - kubectl cut) checks."""
    cluster_name: str
    region: str
    overall: OverallStatus
    can_proceed: bool = Field(..., description="Wizard 'Continue' enabled when True")
    checks: List[PipelineCheck]


class ControllerInstallReport(BaseModel):
    """Step 2 report: ALB Controller + EBS CSI Driver state."""
    cluster_name: str
    iam_mode: Literal["managed", "preprovisioned"]
    overall: OverallStatus
    can_proceed: bool
    alb_controller: PipelineCheck
    ebs_csi_driver: PipelineCheck


class IRSAMappingReport(BaseModel):
    """Step 3 report: trust-policy + attached-policy verification per role."""
    cluster_name: str
    overall: OverallStatus
    can_proceed: bool
    roles: List[PipelineCheck]


class IAMAuditReport(BaseModel):
    """Step 4 report: IAM permissions audit."""
    cluster_name: str
    iam_mode: Literal["managed", "preprovisioned"]
    overall: OverallStatus
    can_proceed: bool
    checks: List[PipelineCheck]


class OperatorInstallReport(BaseModel):
    """Step 5 report: operator install / update."""
    cluster_name: str
    operator_installed: bool
    operator_status: str
    operator_version: Optional[str]
    namespace: str
    detail: str


class NetworkConfigReport(BaseModel):
    """Step 6 report: TotogiNetworkConfig CR + VPC endpoint state."""
    cluster_name: str
    cr_name: str = "vpc-endpoints"
    phase: str
    overall: OverallStatus
    can_proceed: bool
    endpoints: List[Dict[str, Any]] = Field(default_factory=list)
    total_endpoints: int = 0
    healthy_endpoints: int = 0
    message: str = ""


class ReachabilityProbeRow(BaseModel):
    """One AWS service row in the reachability report."""
    service: str
    host: str
    ip: Optional[str] = None
    route: Literal["VPCE", "PUBLIC", "DNS_FAIL", "UNKNOWN"] = "UNKNOWN"
    tls_status: str = ""
    can_authenticate: Optional[bool] = None
    detail: str = ""


class ReachabilityReport(BaseModel):
    """Step 7 report: in-cluster DNS + TLS + IAM probe per AWS service."""
    cluster_name: str
    namespace: str
    pod_name: str
    overall: OverallStatus
    rows: List[ReachabilityProbeRow]
    iam_results: Dict[str, Any] = Field(default_factory=dict)


class InspectionSection(BaseModel):
    """One section in the full capability inspection report (step 10)."""
    name: str
    label: str
    status: CheckStatus
    summary: str
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    raw: Optional[str] = None


class CapabilityInspectionReport(BaseModel):
    """Step 10 report: full inspect-capability.sh parity."""
    cluster_name: str
    namespace: str
    capability_name: str
    environment: str
    cr_name: str
    overall: OverallStatus
    sections: List[InspectionSection]

/**
 * Typed client for the 10-step EKS pipeline endpoints
 * (mounted under /api/eks/pipeline by backend/app/routers/eks_pipeline.py).
 */
import { API_BASE } from '../lib/apiBase';
import axios from 'axios';

const baseURL = `${API_BASE}/api/eks/pipeline`;

const http = axios.create({ baseURL });

// ---------- shared shapes ----------

export type CheckStatus = 'pass' | 'warn' | 'fail' | 'skipped';
export type OverallStatus = 'pass' | 'warn' | 'fail';

export interface PipelineCheck {
  name: string;
  label: string;
  status: CheckStatus;
  detail: string;
  remediation?: string;
  extra?: Record<string, unknown>;
}

export interface ClusterReadinessReport {
  cluster_name: string;
  region: string;
  overall: OverallStatus;
  can_proceed: boolean;
  checks: PipelineCheck[];
}

export interface ControllerInstallReport {
  cluster_name: string;
  iam_mode: 'managed' | 'preprovisioned';
  overall: OverallStatus;
  can_proceed: boolean;
  alb_controller: PipelineCheck;
  ebs_csi_driver: PipelineCheck;
}

export interface IRSAMappingReport {
  cluster_name: string;
  overall: OverallStatus;
  can_proceed: boolean;
  roles: PipelineCheck[];
}

export interface IAMAuditReport {
  cluster_name: string;
  iam_mode: 'managed' | 'preprovisioned';
  overall: OverallStatus;
  can_proceed: boolean;
  checks: PipelineCheck[];
}

export interface NetworkConfigReport {
  cluster_name: string;
  cr_name: string;
  phase: string;
  overall: OverallStatus;
  can_proceed: boolean;
  endpoints: Record<string, unknown>[];
  total_endpoints: number;
  healthy_endpoints: number;
  message: string;
}

export interface ReachabilityProbeRow {
  service: string;
  host: string;
  ip: string | null;
  route: 'VPCE' | 'PUBLIC' | 'DNS_FAIL' | 'UNKNOWN';
  tls_status: string;
  can_authenticate: boolean | null;
  detail: string;
}

export interface ReachabilityReport {
  cluster_name: string;
  namespace: string;
  pod_name: string;
  overall: OverallStatus;
  rows: ReachabilityProbeRow[];
  iam_results: Record<string, unknown>;
}

export interface InspectionSection {
  name: string;
  label: string;
  status: CheckStatus;
  summary: string;
  rows: Record<string, unknown>[];
  raw?: string;
}

export interface CapabilityInspectionReport {
  cluster_name: string;
  namespace: string;
  capability_name: string;
  environment: string;
  cr_name: string;
  overall: OverallStatus;
  sections: InspectionSection[];
}

// ---------- API ----------

export const eksPipelineApi = {
  readiness: async (
    clusterName: string,
    iamMode: 'managed' | 'preprovisioned',
    awsSessionId?: string,
  ): Promise<ClusterReadinessReport> => {
    const params: Record<string, string> = { iam_mode: iamMode };
    if (awsSessionId) params.aws_session_id = awsSessionId;
    const res = await http.get<ClusterReadinessReport>(
      `/clusters/${encodeURIComponent(clusterName)}/readiness`,
      { params },
    );
    return res.data;
  },

  installControllers: async (
    clusterName: string,
    iamMode: 'managed' | 'preprovisioned',
    awsSessionId?: string,
  ): Promise<ControllerInstallReport> => {
    const params: Record<string, string> = { iam_mode: iamMode };
    if (awsSessionId) params.aws_session_id = awsSessionId;
    const res = await http.post<ControllerInstallReport>(
      `/clusters/${encodeURIComponent(clusterName)}/controllers`,
      undefined,
      { params },
    );
    return res.data;
  },

  verifyIrsa: async (
    clusterName: string,
    iamMode: 'managed' | 'preprovisioned',
    capabilityNamespace?: string,
    appRoleArn?: string,
    awsSessionId?: string,
  ): Promise<IRSAMappingReport> => {
    const params: Record<string, string> = { iam_mode: iamMode };
    if (capabilityNamespace) params.capability_namespace = capabilityNamespace;
    if (appRoleArn) params.app_role_arn = appRoleArn;
    if (awsSessionId) params.aws_session_id = awsSessionId;
    const res = await http.get<IRSAMappingReport>(
      `/clusters/${encodeURIComponent(clusterName)}/irsa`,
      { params },
    );
    return res.data;
  },

  iamAudit: async (
    clusterName: string,
    iamMode: 'managed' | 'preprovisioned',
    capabilityNamespace?: string,
    appRoleArn?: string,
    awsSessionId?: string,
  ): Promise<IAMAuditReport> => {
    const params: Record<string, string> = { iam_mode: iamMode };
    if (capabilityNamespace) params.capability_namespace = capabilityNamespace;
    if (appRoleArn) params.app_role_arn = appRoleArn;
    if (awsSessionId) params.aws_session_id = awsSessionId;
    const res = await http.get<IAMAuditReport>(
      `/clusters/${encodeURIComponent(clusterName)}/iam-audit`,
      { params },
    );
    return res.data;
  },

  applyNetworkConfig: async (
    clusterName: string,
    waitSeconds = 120,
    awsSessionId?: string,
  ): Promise<NetworkConfigReport> => {
    const params: Record<string, string> = { wait_seconds: String(waitSeconds) };
    if (awsSessionId) params.aws_session_id = awsSessionId;
    const res = await http.post<NetworkConfigReport>(
      `/clusters/${encodeURIComponent(clusterName)}/network-config`,
      undefined,
      { params },
    );
    return res.data;
  },

  reachability: async (
    clusterName: string,
    namespace: string,
    capabilityName: string,
    environment: string,
    awsSessionId?: string,
  ): Promise<ReachabilityReport> => {
    const params: Record<string, string> = {
      namespace,
      capability_name: capabilityName,
      environment,
    };
    if (awsSessionId) params.aws_session_id = awsSessionId;
    const res = await http.post<ReachabilityReport>(
      `/clusters/${encodeURIComponent(clusterName)}/reachability`,
      undefined,
      { params },
    );
    return res.data;
  },

  inspect: async (
    clusterName: string,
    crName: string,
    namespace: string,
    capabilityName: string,
    environment: string,
    awsSessionId?: string,
  ): Promise<CapabilityInspectionReport> => {
    const params: Record<string, string> = {
      namespace,
      capability_name: capabilityName,
      environment,
    };
    if (awsSessionId) params.aws_session_id = awsSessionId;
    const res = await http.get<CapabilityInspectionReport>(
      `/clusters/${encodeURIComponent(clusterName)}/capability/${encodeURIComponent(crName)}/inspect`,
      { params },
    );
    return res.data;
  },
};

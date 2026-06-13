/**
 * API service for backend communication
 * 
 * Includes retry layer for startup-critical endpoints to handle
 * race conditions when backend is still initializing.
 * 
 * Feature: startup-health-check
 * Requirements: 4.1, 4.2, 4.6
 */
import axios from 'axios';
import { Capability } from '../types/capability';
import {
  AWSRegion,
  RoleValidationRequest,
  RoleValidationResponse,
  AuthValidationRequest,
  PermissionVerificationRequest,
  PermissionStatus,
} from '../types/aws';
import { EnvironmentConfig, ConfigResponse } from '../types/config';
import { StackDetectionResult } from '../types/wizard';
import { EKSCluster, EKSNamespace, OperatorStatus } from '../types/eks';
import { withRetry, startupRetryLayer, ApiRetryLayer, RetryAttemptInfo } from './api-retry';

// Use 127.0.0.1 instead of localhost to avoid IPv6 resolution issues on Windows
const API_BASE_URL = 'http://127.0.0.1:8001';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Retry callback for logging startup retries
const logRetryAttempt = (info: RetryAttemptInfo) => {
  console.log(
    `[API] Startup retry ${info.attempt}/${info.maxAttempts}, ` +
    `waiting ${info.delay}ms...`
  );
};

// Capability API - startup-critical, uses retry layer
export const capabilityApi = {
  getAll: async (): Promise<Capability[]> => {
    // Startup-critical: wrap with retry for backend initialization
    return withRetry(
      async () => {
        const response = await api.get<Capability[]>('/api/capabilities');
        return response.data;
      },
      startupRetryLayer,
      logRetryAttempt
    );
  },

  getById: async (id: string): Promise<Capability> => {
    // Startup-critical: wrap with retry for backend initialization
    return withRetry(
      async () => {
        const response = await api.get<Capability>(`/api/capabilities/${id}`);
        return response.data;
      },
      startupRetryLayer,
      logRetryAttempt
    );
  },

  getVersions: async (id: string): Promise<any[]> => {
    const response = await api.get(`/api/capabilities/${id}/versions`);
    return response.data;
  },
};

// AWS API - startup-critical endpoints use retry layer
export const awsApi = {
  validateAuth: async (
    request: AuthValidationRequest
  ): Promise<RoleValidationResponse> => {
    const response = await api.post<RoleValidationResponse>(
      '/api/aws/validate-auth',
      request
    );
    return response.data;
  },

  validateCredentials: async (
    request: RoleValidationRequest
  ): Promise<RoleValidationResponse> => {
    const response = await api.post<RoleValidationResponse>(
      '/api/aws/validate-credentials',
      request
    );
    return response.data;
  },

  verifyPermissions: async (
    request: PermissionVerificationRequest
  ): Promise<PermissionStatus> => {
    const response = await api.post<PermissionStatus>(
      '/api/aws/verify-permissions',
      request
    );
    return response.data;
  },

  getRegions: async (): Promise<AWSRegion[]> => {
    // Startup-critical: wrap with retry for backend initialization
    return withRetry(
      async () => {
        const response = await api.get<AWSRegion[]>('/api/aws/regions');
        return response.data;
      },
      startupRetryLayer,
      logRetryAttempt
    );
  },

  getProfiles: async (): Promise<string[]> => {
    // Startup-critical: wrap with retry for backend initialization
    return withRetry(
      async () => {
        const response = await api.get<string[]>('/api/aws/profiles');
        return response.data;
      },
      startupRetryLayer,
      logRetryAttempt
    );
  },

  // ADFS Role Selection
  fetchADFSRoles: async (
    adfs_url: string,
    adfs_username: string,
    adfs_password: string,
    region: string
  ): Promise<any> => {
    const response = await api.post('/api/aws/adfs/roles', {
      adfs_url,
      adfs_username,
      adfs_password,
      region,
    });
    return response.data;
  },

  selectADFSRole: async (
    session_id: string,
    role_arn: string,
    region: string
  ): Promise<RoleValidationResponse> => {
    const response = await api.post<RoleValidationResponse>(
      '/api/aws/adfs/select-role',
      {
        session_id,
        role_arn,
        region,
      }
    );
    return response.data;
  },
};

// Deployment API
export const deploymentApi = {
  // Get all deployment states from TinyDB
  // Requirement 11.3: Allow filtering capabilities by landing zone
  getDeploymentStates: async (
    capabilityName?: string,
    environment?: string,
    region?: string,
    landingZoneId?: string
  ): Promise<any> => {
    const params: Record<string, string> = {};
    if (capabilityName) params.capability_name = capabilityName;
    if (environment) params.environment = environment;
    if (region) params.region = region;
    if (landingZoneId) params.landing_zone_id = landingZoneId;
    
    const response = await api.get('/api/deployment/states', { params });
    return response.data;
  },

  // Get deployment state for a specific capability/environment
  getDeploymentState: async (
    capabilityName: string,
    environment: string
  ): Promise<any> => {
    const response = await api.get(`/api/deployment/states/${encodeURIComponent(capabilityName)}/${environment}`);
    return response.data;
  },

  detectExistingStacks: async (
    capabilityName: string,
    environment: string,
    region: string,
    awsSessionId?: string,
    deployFrontend: boolean = true,
    deployBackend: boolean = true
  ): Promise<StackDetectionResult> => {
    const response = await api.post<StackDetectionResult>('/api/deployment/detect-stacks', {
      capability_name: capabilityName,
      environment,
      region,
      aws_session_id: awsSessionId,
      deploy_frontend: deployFrontend,
      deploy_backend: deployBackend,
    });
    return response.data;
  },

  startDeployment: async (request: any): Promise<any> => {
    const response = await api.post('/api/deployment/start', request);
    return response.data;
  },

  getDeploymentStatus: async (deploymentId: string): Promise<any> => {
    const response = await api.get(`/api/deployment/${deploymentId}`);
    return response.data;
  },

  getDeploymentLogs: async (deploymentId: string, limit?: number): Promise<any> => {
    const params = limit ? { limit } : {};
    const response = await api.get(`/api/deployment/${deploymentId}/logs`, { params });
    return response.data;
  },

  cancelDeployment: async (deploymentId: string): Promise<any> => {
    const response = await api.post(`/api/deployment/${deploymentId}/cancel`);
    return response.data;
  },

  completeCleanup: async (
    capabilityName: string,
    environment: string,
    region: string,
    accountId: string,
    awsSessionId?: string,
    installationId?: string
  ): Promise<any> => {
    const response = await api.post('/api/deployment/complete-cleanup', null, {
      params: {
        capability_name: capabilityName,
        environment,
        region,
        account_id: accountId,
        aws_session_id: awsSessionId,
        installation_id: installationId,
      },
    });
    return response.data;
  },

  // Async deletion with polling
  startDeletion: async (
    capabilityName: string,
    environment: string,
    region: string,
    accountId: string,
    awsSessionId?: string
  ): Promise<{ deletion_id: string; status: string; progress: number; message: string }> => {
    const response = await api.post('/api/deployment/start-deletion', {
      capability_name: capabilityName,
      environment,
      region,
      account_id: accountId,
      aws_session_id: awsSessionId,
    });
    return response.data;
  },

  getDeletionStatus: async (deletionId: string): Promise<{ deletion_id: string; status: string; progress: number; message: string }> => {
    const response = await api.get(`/api/deployment/deletion/${deletionId}`);
    return response.data;
  },

  getDeletionLogs: async (deletionId: string): Promise<{ deletion_id: string; logs: Array<{ timestamp: string; message: string }>; total_count: number }> => {
    const response = await api.get(`/api/deployment/deletion/${deletionId}/logs`);
    return response.data;
  },

  validateDeployment: async (request: any): Promise<any> => {
    const response = await api.post('/api/deployment/validate', request);
    return response.data;
  },

  getDeploymentPlan: async (request: any): Promise<any> => {
    const response = await api.post('/api/deployment/plan', request);
    return response.data;
  },

  // Cognito drift detection for update workflow
  // Feature: update-workflow-cognito-preservation
  // Requirements: 5.1, 5.2, 5.3
  detectCognitoDrift: async (request: {
    capability_name: string;
    environment: string;
    region: string;
    aws_session_id?: string;
  }): Promise<{
    has_drift: boolean;
    drift_items: Array<{
      setting_name: string;
      template_value: string;
      deployed_value: string;
      category: string;
    }>;
    detection_timestamp: string;
    error_message?: string;
    categories_checked: string[];
  }> => {
    const response = await api.post('/api/deployment/detect-cognito-drift', request);
    return response.data;
  },
};

// Environment Presets Response Types
export interface EnvironmentPresetsResponse {
  success: boolean;
  data: {
    defaults: {
      base_domain: string;
      hosted_zone_id: string;
    };
    presets: Record<string, any>;
  };
}

export interface EnvironmentPresetResponse {
  success: boolean;
  environment: string;
  data: any;
}

// Configuration API - startup-critical endpoints use retry layer
export const configApi = {
  getConfig: async (capabilityName: string, environment: string): Promise<ConfigResponse> => {
    const response = await api.get<ConfigResponse>(
      `/api/config/${capabilityName}/${environment}`
    );
    return response.data;
  },

  saveConfig: async (
    capabilityName: string,
    environment: string,
    config: EnvironmentConfig
  ): Promise<ConfigResponse> => {
    const response = await api.post<ConfigResponse>('/api/config/save', {
      capability_name: capabilityName,
      environment,
      config,
    });
    return response.data;
  },

  deleteConfig: async (capabilityName: string, environment: string): Promise<ConfigResponse> => {
    const response = await api.delete<ConfigResponse>(
      `/api/config/${capabilityName}/${environment}`
    );
    return response.data;
  },

  // Get all environment presets - startup-critical
  getPresets: async (): Promise<EnvironmentPresetsResponse> => {
    return withRetry(
      async () => {
        const response = await api.get<EnvironmentPresetsResponse>('/api/config/presets');
        return response.data;
      },
      startupRetryLayer,
      logRetryAttempt
    );
  },

  // Get preset for a specific environment
  getPreset: async (environment: string): Promise<EnvironmentPresetResponse> => {
    const response = await api.get<EnvironmentPresetResponse>(`/api/config/presets/${environment}`);
    return response.data;
  },

  // Reload presets from JSON file
  reloadPresets: async (): Promise<{ success: boolean; message: string }> => {
    const response = await api.post<{ success: boolean; message: string }>('/api/config/presets/reload');
    return response.data;
  },
};

// Installation History API
export interface InstallationSummary {
  installation_id: string;
  capability_name: string;
  capability_version: string;
  environment: string;
  region: string;
  account_id: string;
  strategy: string;
  status: string;
  started_at: string;
  completed_at?: string;
  duration_seconds?: number;
  error?: string;
  stacks_summary?: {
    created: number;
    updated: number;
    failed: number;
    skipped: number;
  };
}

export interface StackOperationLog {
  log_id: string;
  installation_id: string;
  stack_name: string;
  stack_type: string;
  operation: string;
  status: string;
  region: string;
  started_at: string;
  completed_at?: string;
  duration_seconds?: number;
  error_message?: string;
  stack_outputs?: Record<string, string>;
}

export interface InstallationDetail extends InstallationSummary {
  deploy_frontend: boolean;
  deploy_backend: boolean;
  frontend_url?: string;
  backend_url?: string;
  cognito_config?: Record<string, any>;
  logs: StackOperationLog[];
  installation_log?: string;  // Full deployment log text
}

export const installationApi = {
  // List installations with optional filters
  list: async (params?: {
    capability_name?: string;
    environment?: string;
    status?: string;
    start_date?: string;
    end_date?: string;
    limit?: number;
  }): Promise<{ installations: InstallationSummary[]; total: number }> => {
    const response = await api.get('/api/installations', { params });
    return response.data;
  },

  // Get installation details with logs
  getById: async (installationId: string): Promise<InstallationDetail> => {
    const response = await api.get<InstallationDetail>(`/api/installations/${installationId}`);
    return response.data;
  },

  // Get stack operation logs for an installation
  getLogs: async (installationId: string): Promise<{ logs: StackOperationLog[]; total: number }> => {
    const response = await api.get(`/api/installations/${installationId}/logs`);
    return response.data;
  },

  // Delete an installation record
  delete: async (installationId: string): Promise<{ message: string }> => {
    const response = await api.delete(`/api/installations/${installationId}`);
    return response.data;
  },
};

// Health API Types
export interface ComponentStatus {
  name: string;
  status: 'healthy' | 'degraded' | 'unhealthy' | 'pending';
  message?: string;
  initialized_at?: string;
}

export interface ReadinessResponse {
  ready: boolean;
  phase: string;
  components: ComponentStatus[];
  startup_time_ms?: number;
  message?: string;
}

export interface HealthResponse extends ReadinessResponse {
  uptime_seconds: number;
  version?: string;
}

// Health API - for checking backend readiness
export const healthApi = {
  // Check if backend is ready to serve requests
  checkReady: async (): Promise<ReadinessResponse> => {
    const response = await api.get<ReadinessResponse>('/api/health/ready');
    return response.data;
  },

  // Liveness probe - is the backend process alive
  checkLive: async (): Promise<{ status: string }> => {
    const response = await api.get<{ status: string }>('/api/health/live');
    return response.data;
  },

  // Detailed health with metrics
  getHealth: async (): Promise<HealthResponse> => {
    const response = await api.get<HealthResponse>('/api/health');
    return response.data;
  },

  // Check readiness with retry for startup
  waitForReady: async (
    maxAttempts: number = 10,
    intervalMs: number = 1000
  ): Promise<ReadinessResponse> => {
    const retryLayer = new ApiRetryLayer({
      maxRetries: maxAttempts - 1,
      initialDelayMs: intervalMs,
      maxDelayMs: intervalMs * 2,
      backoffMultiplier: 1.5,
      retryableStatuses: [0, 502, 503, 504],
      retryOnNetworkError: true,
    });
    
    return withRetry(
      async () => {
        const response = await api.get<ReadinessResponse>('/api/health/ready');
        if (!response.data.ready) {
          throw new Error(`Backend not ready: ${response.data.phase}`);
        }
        return response.data;
      },
      retryLayer,
      logRetryAttempt
    );
  },
};

// EKS API - for cluster discovery and operator management
export interface EKSClusterListResponse {
  clusters: EKSCluster[];
  region: string;
}

export interface EKSClusterDetailResponse {
  cluster: EKSCluster;
}

export interface OperatorStatusResponse {
  cluster_name: string;
  operator_installed: boolean;
  operator_status: OperatorStatus;
  operator_version?: string;
  namespace: string;
}

export interface EKSNamespaceListResponse {
  namespaces: EKSNamespace[];
  cluster_name: string;
}

export interface DeployOperatorRequest {
  cluster_name: string;
  operator_version?: string;
}

export interface DeployOperatorResponse {
  success: boolean;
  message: string;
  operator_version: string;
  namespace: string;
}

export interface DeployCapabilityRequest {
  cluster_name: string;
  capability_name: string;
  capability_version: string;
  environment: string;
  namespace: string;
  config: Record<string, any>;
}

export interface DeployCapabilityResponse {
  success: boolean;
  cr_name: string;
  namespace: string;
  message: string;
}

export interface CapabilityStatusResponse {
  cr_name: string;
  namespace: string;
  phase: string;
  message: string;
  frontend_url?: string;
  backend_url?: string;
  resources: Array<{
    type: string;
    name: string;
    status: string;
  }>;
  last_reconcile_time?: string;
}

export const eksApi = {
  // List all EKS clusters in the region
  listClusters: async (awsSessionId?: string, region?: string): Promise<EKSClusterListResponse> => {
    const params: Record<string, string> = {};
    if (awsSessionId) params.aws_session_id = awsSessionId;
    if (region) params.region = region;
    
    const response = await api.get<EKSClusterListResponse>('/api/eks/clusters', { params });
    return response.data;
  },

  // Get details for a specific cluster
  getClusterDetails: async (clusterName: string, awsSessionId?: string): Promise<EKSClusterDetailResponse> => {
    const params: Record<string, string> = {};
    if (awsSessionId) params.aws_session_id = awsSessionId;
    
    const response = await api.get<EKSClusterDetailResponse>(`/api/eks/clusters/${encodeURIComponent(clusterName)}`, { params });
    return response.data;
  },

  // Check operator installation status on a cluster
  checkOperatorStatus: async (clusterName: string, awsSessionId?: string): Promise<OperatorStatusResponse> => {
    const params: Record<string, string> = {};
    if (awsSessionId) params.aws_session_id = awsSessionId;
    
    const response = await api.get<OperatorStatusResponse>(`/api/eks/clusters/${encodeURIComponent(clusterName)}/operator-status`, { params });
    return response.data;
  },

  // List namespaces in a cluster
  listNamespaces: async (clusterName: string, awsSessionId?: string): Promise<EKSNamespaceListResponse> => {
    const params: Record<string, string> = {};
    if (awsSessionId) params.aws_session_id = awsSessionId;
    
    const response = await api.get<EKSNamespaceListResponse>(`/api/eks/clusters/${encodeURIComponent(clusterName)}/namespaces`, { params });
    return response.data;
  },

  // Deploy the Nexus AI Operator to a cluster
  deployOperator: async (request: DeployOperatorRequest, awsSessionId?: string): Promise<DeployOperatorResponse> => {
    const params: Record<string, string> = {};
    if (awsSessionId) params.aws_session_id = awsSessionId;
    
    const response = await api.post<DeployOperatorResponse>(
      `/api/eks/clusters/${encodeURIComponent(request.cluster_name)}/deploy-operator`,
      request,
      { params }
    );
    return response.data;
  },

  // Deploy a capability via NexusCapability CR
  deployCapability: async (request: DeployCapabilityRequest, awsSessionId?: string): Promise<DeployCapabilityResponse> => {
    const params: Record<string, string> = {};
    if (awsSessionId) params.aws_session_id = awsSessionId;
    
    const response = await api.post<DeployCapabilityResponse>(
      `/api/eks/clusters/${encodeURIComponent(request.cluster_name)}/deploy-capability`,
      request,
      { params }
    );
    return response.data;
  },

  // Get capability deployment status
  getCapabilityStatus: async (clusterName: string, crName: string, namespace: string, awsSessionId?: string): Promise<CapabilityStatusResponse> => {
    const params: Record<string, string> = { namespace };
    if (awsSessionId) params.aws_session_id = awsSessionId;
    
    const response = await api.get<CapabilityStatusResponse>(
      `/api/eks/clusters/${encodeURIComponent(clusterName)}/capability/${encodeURIComponent(crName)}/status`,
      { params }
    );
    return response.data;
  },
};

export default api;

// ============================================================================
// Discovery API - for capability discovery from AWS CloudFormation
// ============================================================================

export interface LandingZone {
  landing_zone_id: string;
  name: string;
  provider: 'aws' | 'azure' | 'gcp';
  account_id: string;
  account_alias?: string;
  default_region: string;
  created_at: string;
  last_discovery_at?: string;
  discovery_status: string;
  capabilities_count: number;
}

export interface CreateLandingZoneRequest {
  name: string;
  provider: 'aws' | 'azure' | 'gcp';
  account_id: string;
  default_region?: string;
  account_alias?: string;
}

export interface DiscoveryStatus {
  job_id: string;
  landing_zone_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  started_at: string;
  completed_at?: string;
  stacks_scanned: number;
  capabilities_found: number;
  errors: string[];
  progress_message: string;
}

export interface DiscoveryLogEntry {
  timestamp: string;
  level: string;
  message: string;
}

export interface DiscoveredCapability {
  capability_name: string;
  environment: string;
  account_id: string;
  primary_region: string;
  status: string;
  stacks_count: number;
  missing_stacks: string[];
  discovered_at: string;
  version?: string;
  frontend_url?: string;
  backend_url?: string;
  landing_zone_id: string;
}

export const discoveryApi = {
  // Landing Zone Management
  createLandingZone: async (request: CreateLandingZoneRequest): Promise<LandingZone> => {
    const response = await api.post<LandingZone>('/api/discovery/landing-zones', request);
    return response.data;
  },

  listLandingZones: async (provider?: 'aws' | 'azure' | 'gcp'): Promise<LandingZone[]> => {
    const params = provider ? { provider } : {};
    const response = await api.get<LandingZone[]>('/api/discovery/landing-zones', { params });
    return response.data;
  },

  getLandingZone: async (landingZoneId: string): Promise<LandingZone> => {
    const response = await api.get<LandingZone>(`/api/discovery/landing-zones/${landingZoneId}`);
    return response.data;
  },

  deleteLandingZone: async (landingZoneId: string): Promise<{ message: string }> => {
    const response = await api.delete(`/api/discovery/landing-zones/${landingZoneId}`);
    return response.data;
  },

  // Discovery Operations
  startDiscovery: async (
    landingZoneId: string,
    awsSessionId?: string,
    regions?: string[]
  ): Promise<DiscoveryStatus> => {
    const response = await api.post<DiscoveryStatus>('/api/discovery/discover', {
      landing_zone_id: landingZoneId,
      aws_session_id: awsSessionId,
      regions,
    });
    return response.data;
  },

  getDiscoveryStatus: async (jobId: string): Promise<DiscoveryStatus> => {
    const response = await api.get<DiscoveryStatus>(`/api/discovery/discover/${jobId}/status`);
    return response.data;
  },

  getDiscoveryLogs: async (jobId: string, limit?: number): Promise<DiscoveryLogEntry[]> => {
    const params = limit ? { limit } : {};
    const response = await api.get<DiscoveryLogEntry[]>(`/api/discovery/discover/${jobId}/logs`, { params });
    return response.data;
  },

  refreshCapabilities: async (
    landingZoneId: string,
    awsSessionId?: string
  ): Promise<DiscoveryStatus> => {
    const params = awsSessionId ? { aws_session_id: awsSessionId } : {};
    const response = await api.post<DiscoveryStatus>(
      `/api/discovery/refresh/${landingZoneId}`,
      null,
      { params }
    );
    return response.data;
  },

  // Discovered Capabilities
  listDiscoveredCapabilities: async (
    landingZoneId?: string,
    accountId?: string
  ): Promise<DiscoveredCapability[]> => {
    const params: Record<string, string> = {};
    if (landingZoneId) params.landing_zone_id = landingZoneId;
    if (accountId) params.account_id = accountId;
    const response = await api.get<DiscoveredCapability[]>('/api/discovery/capabilities', { params });
    return response.data;
  },
};

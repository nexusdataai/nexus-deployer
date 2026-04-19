/**
 * EKS types for cluster discovery and configuration
 */

/**
 * EKS cluster status from AWS
 */
export type EKSClusterStatus = 'CREATING' | 'ACTIVE' | 'DELETING' | 'FAILED' | 'UPDATING' | 'PENDING';

/**
 * Totogi Operator installation status
 */
export type OperatorStatus = 'not_installed' | 'installing' | 'installed' | 'failed' | 'unknown';

/**
 * EKS cluster information from AWS
 */
export interface EKSCluster {
  name: string;
  arn: string;
  version: string;
  status: EKSClusterStatus;
  endpoint: string;
  roleArn: string;
  vpcId: string;
  subnetIds: string[];
  securityGroupIds: string[];
  createdAt: string;
  platformVersion: string;
  tags: Record<string, string>;
  // Computed/fetched fields
  nodeCount?: number;
  operatorStatus?: OperatorStatus;
  operatorVersion?: string;
}

/**
 * EKS namespace information
 */
export interface EKSNamespace {
  name: string;
  status: string;
  createdAt: string;
  labels: Record<string, string>;
}

/**
 * Resource configuration for Kubernetes deployments
 */
export interface ResourceConfig {
  cpu: string;
  memory: string;
}

/**
 * Resource requests and limits
 */
export interface ResourceRequirements {
  requests: ResourceConfig;
  limits: ResourceConfig;
}

/**
 * Horizontal Pod Autoscaler configuration
 */
export interface HPAConfig {
  enabled: boolean;
  minReplicas: number;
  maxReplicas: number;
  targetCPUUtilization: number;
}

/**
 * Pod Disruption Budget configuration
 */
export interface PDBConfig {
  enabled: boolean;
  minAvailable?: number;
  maxUnavailable?: number;
}

/**
 * TLS configuration for ingress
 */
export interface TLSConfig {
  enabled: boolean;
  secretName?: string;
  certificateArn?: string;
}

/**
 * Ingress configuration
 */
export interface IngressConfig {
  enabled: boolean;
  className: string;
  annotations: Record<string, string>;
  tls: TLSConfig;
  customDomain?: string;
}

/**
 * EKS deployment configuration stored in wizard state
 */
export interface EKSConfig {
  // Cluster selection
  clusterName: string;
  clusterArn: string;
  clusterEndpoint: string;
  
  // Namespace configuration
  namespace: string;
  createNamespace: boolean;
  
  // Operator configuration
  operatorInstalled: boolean;
  operatorVersion?: string;
  
  // Replica configuration
  frontendReplicas: number;
  backendReplicas: number;
  
  // Resource configuration
  frontendResources: ResourceRequirements;
  backendResources: ResourceRequirements;
  
  // Advanced options
  hpa: HPAConfig;
  pdb: PDBConfig;
  ingress: IngressConfig;
  
  // Deletion policy
  deletionPolicy: 'Delete' | 'Retain';
}

/**
 * Default EKS configuration
 */
export const DEFAULT_EKS_CONFIG: Partial<EKSConfig> = {
  namespace: '',
  createNamespace: true,
  operatorInstalled: false,
  frontendReplicas: 2,
  backendReplicas: 2,
  frontendResources: {
    requests: { cpu: '100m', memory: '128Mi' },
    limits: { cpu: '500m', memory: '512Mi' },
  },
  backendResources: {
    requests: { cpu: '250m', memory: '512Mi' },
    limits: { cpu: '500m', memory: '2Gi' },
  },
  hpa: {
    enabled: false,
    minReplicas: 2,
    maxReplicas: 10,
    targetCPUUtilization: 70,
  },
  pdb: {
    enabled: true,
    minAvailable: 1,
  },
  ingress: {
    enabled: true,
    className: 'alb',
    annotations: {},
    tls: {
      enabled: false,
    },
  },
  deletionPolicy: 'Delete',
};

/**
 * Generate default namespace name from capability and environment
 */
export const generateDefaultNamespace = (capabilityName: string, environment: string): string => {
  const sanitizedCapability = capabilityName.toLowerCase().replace(/[^a-z0-9-]/g, '-');
  const sanitizedEnv = environment.toLowerCase().replace(/[^a-z0-9-]/g, '-');
  return `${sanitizedCapability}-${sanitizedEnv}`;
};

/**
 * Validate Kubernetes namespace name
 * Must be lowercase, alphanumeric, hyphens allowed, max 63 chars
 */
export const isValidNamespace = (namespace: string): boolean => {
  if (!namespace || namespace.length > 63) return false;
  const namespaceRegex = /^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/;
  return namespaceRegex.test(namespace);
};

/**
 * Capability data models for frontend
 */

export interface CapabilityArtifact {
  s3_uri?: string;
  ecr_uri?: string;
  size_mb: number;
}

export interface CapabilityArtifacts {
  frontend?: CapabilityArtifact;
  backend?: CapabilityArtifact;
}

export interface CapabilityRequirements {
  frontend: boolean;
  backend: boolean;
  database: boolean;
  authentication: boolean;
}

export interface AWSOptions {
  frontend: string[];
  backend: string[];
}

/**
 * EKS-specific artifact configuration
 * Used when deploying to Pure EKS architecture
 */
export interface EKSArtifacts {
  frontend_ecr_uri?: string;
  backend_ecr_uri?: string;
  operator_image?: string;
}

export interface Capability {
  id: string;
  name: string;
  version: string;
  description: string;
  icon?: string;
  category: string;
  status?: 'available' | 'coming_soon' | 'deprecated';
  status_message?: string;
  supported_clouds: string[];
  supported_environments: string[];
  requirements: CapabilityRequirements;
  artifacts: CapabilityArtifacts;
  // EKS-specific artifacts (frontend as Docker image)
  eks_artifacts?: EKSArtifacts;
  aws_options?: AWSOptions;
  estimated_deployment_time: number;
  documentation_url?: string;
  required_iam_permissions: string[];
  // EKS-specific permissions
  eks_iam_permissions?: string[];
  prerequisites: string[];
}

export interface CapabilityList {
  capabilities: Capability[];
}

export interface CapabilityVersion {
  version: string;
  release_date: string;
  changelog?: string;
}

/**
 * Architecture types and constants for AWS deployment target selection
 */

/**
 * Supported frontend deployment services
 */
export enum FrontendService {
  S3_CLOUDFRONT = 's3_cloudfront',
  AMPLIFY = 'amplify',
  EKS = 'eks',
}

/**
 * Supported backend deployment services
 */
export enum BackendService {
  ECS = 'ecs',
  EKS = 'eks',
  EC2 = 'ec2',
}

/**
 * Service availability status
 */
export type ServiceAvailability = 'available' | 'coming_soon' | 'deprecated';

/**
 * Cost tier indicator
 */
export type CostTier = 'low' | 'medium' | 'high';

/**
 * Service option metadata
 */
export interface ServiceOptionMeta {
  id: string;
  name: string;
  description: string;
  icon: string;
  availability: ServiceAvailability;
  costTier: CostTier;
  features: string[];
}

/**
 * Architecture configuration stored in wizard state
 */
export interface ArchitectureConfig {
  frontendService: FrontendService;
  backendService: BackendService;
}

/**
 * Default architecture configuration
 */
export const DEFAULT_ARCHITECTURE_CONFIG: ArchitectureConfig = {
  frontendService: FrontendService.S3_CLOUDFRONT,
  backendService: BackendService.ECS,
};

/**
 * Frontend service options with metadata
 */
export const FRONTEND_SERVICE_OPTIONS: Record<FrontendService, ServiceOptionMeta> = {
  [FrontendService.S3_CLOUDFRONT]: {
    id: 's3_cloudfront',
    name: 'S3 + CloudFront',
    description: 'Static hosting with global CDN distribution. Best for static sites and SPAs.',
    icon: 'cloudfront',
    availability: 'available',
    costTier: 'low',
    features: ['Global CDN', 'HTTPS', 'Custom domains', 'Cache optimization'],
  },
  [FrontendService.AMPLIFY]: {
    id: 'amplify',
    name: 'AWS Amplify',
    description: 'Full-stack hosting with CI/CD. Ideal for rapid development.',
    icon: 'amplify',
    availability: 'coming_soon',
    costTier: 'medium',
    features: ['CI/CD built-in', 'Preview branches', 'Backend integration', 'Easy setup'],
  },
  [FrontendService.EKS]: {
    id: 'eks',
    name: 'Pure EKS',
    description: 'Full Kubernetes deployment with both frontend and backend in EKS. Operator-managed infrastructure.',
    icon: 'eks',
    availability: 'available',
    costTier: 'high',
    features: ['Kubernetes native', 'Operator managed', 'Self-healing', 'Declarative config'],
  },
};

/**
 * Backend service options with metadata
 */
export const BACKEND_SERVICE_OPTIONS: Record<BackendService, ServiceOptionMeta> = {
  [BackendService.ECS]: {
    id: 'ecs',
    name: 'ECS (Fargate)',
    description: 'Serverless containers with automatic scaling. No infrastructure management.',
    icon: 'ecs',
    availability: 'available',
    costTier: 'medium',
    features: ['Serverless', 'Auto-scaling', 'Load balancing', 'Service discovery'],
  },
  [BackendService.EKS]: {
    id: 'eks',
    name: 'EKS (Kubernetes)',
    description: 'Managed Kubernetes for complex microservices architectures.',
    icon: 'eks',
    availability: 'available',
    costTier: 'high',
    features: ['Kubernetes native', 'Multi-cloud portable', 'Advanced networking', 'Helm support'],
  },
  [BackendService.EC2]: {
    id: 'ec2',
    name: 'EC2 (Plain Node)',
    description: 'Traditional VM-based deployment with full control.',
    icon: 'ec2',
    availability: 'coming_soon',
    costTier: 'low',
    features: ['Full control', 'Custom AMIs', 'Spot instances', 'Reserved capacity'],
  },
};

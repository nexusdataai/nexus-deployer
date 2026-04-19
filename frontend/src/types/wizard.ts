/**
 * Wizard state types
 */
import { Capability } from './capability';
import { AWSConfiguration, PermissionStatus } from './aws';
import { EnvironmentConfig } from './config';
import { ArchitectureConfig } from './architecture';
import { EKSConfig } from './eks';

export enum WizardStep {
  WELCOME = 'welcome',
  CAPABILITY_SELECTION = 'capability_selection',
  ARCHITECTURE_SELECTION = 'architecture_selection',
  EKS_CLUSTER_SELECTION = 'eks_cluster_selection',
  UNIFIED_ENVIRONMENT_CONFIG = 'unified_environment_config',
  AWS_CONFIGURATION = 'aws_configuration',
  PERMISSION_VERIFICATION = 'permission_verification',
  STRATEGY_SELECTION = 'strategy_selection',
  DEPLOYMENT_EXECUTION = 'deployment_execution',
  DELETION_EXECUTION = 'deletion_execution',
  DISCOVERY_EXECUTION = 'discovery_execution',
  POST_VERIFICATION = 'post_verification',
  RESULTS = 'results',
}

export interface CognitoConfig {
  user_pool_id?: string;
  client_id?: string;
  domain?: string;
  region?: string;
  admin_user_email?: string;
  admin_temp_password?: string;
  test_users_info?: string;
}

export interface DeploymentStatus {
  id: string | null;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress: number;
  currentStage: string;
  error?: string;
  // Deployment outputs
  frontend_url?: string;
  backend_url?: string;
  cognito_user_pool_id?: string;
  cognito_client_id?: string;
  cognito_config?: CognitoConfig;
  cloudfront_distribution_id?: string;
  api_domain?: string;
}

export interface LogEntry {
  timestamp: string;
  level: 'info' | 'warning' | 'error';
  source: string;
  message: string;
}

export interface VerificationResult {
  overallStatus: 'passed' | 'failed';
  checks: VerificationCheck[];
  stackOutputs: Record<string, string>;
  timestamp: string;
}

export interface VerificationCheck {
  name: string;
  status: 'passed' | 'failed';
  message: string;
  details?: string;
}

export enum DeploymentStrategy {
  CLEAN_DEPLOY = 'clean_deploy',
  UPDATE_EXISTING = 'update_existing',
}

export interface StackStatusAnalysis {
  status: string;
  is_updatable: boolean;
  requires_deletion: boolean;
  requires_manual_intervention: boolean;
  recommendation: string;
  warning_message?: string;
}

export interface ExistingStackInfo {
  stack_name: string;
  stack_type: string;
  stack_status: string;
  region: string;
  created_at?: string;
  last_updated_at?: string;
  is_updatable: boolean;
  status_reason?: string;
  classification: string;  // "updatable", "failed", or "in_progress"
}

export interface StackDetectionResult {
  capability_name: string;
  environment: string;
  region: string;
  stacks_found: ExistingStackInfo[];
  has_existing_stacks: boolean;
  has_failed_stacks: boolean;
  has_in_progress_stacks: boolean;
  is_updatable: boolean;
  recommended_strategy?: DeploymentStrategy;
  recommendation_reason: string;
  detection_timestamp: string;
  error_message?: string;
}

export interface WizardState {
  currentStep: WizardStep;
  selectedCapability: Capability | null;
  selectedEnvironment: string | null;
  awsRegion: string | null;
  awsConfig: AWSConfiguration | null;
  architectureConfig: ArchitectureConfig | null;
  eksConfig: EKSConfig | null;
  infrastructureConfig: EnvironmentConfig | null;
  permissionStatus: PermissionStatus | null;
  detectionResult: StackDetectionResult | null;
  selectedStrategy: DeploymentStrategy | null;
  updateOptions: UpdateOptions | null;
  deploymentStatus: DeploymentStatus;
  logs: LogEntry[];
  verificationResults: VerificationResult | null;
  deleteMode: boolean;  // When true, skip strategy selection and go directly to deletion
  discoveryMode: boolean;  // When true, after AWS auth go to discovery instead of deployment
}

/**
 * Update configuration options for Cognito preservation
 * Requirements: 3.1, 3.2, 3.3, 4.1, 4.6, 9.1
 */
export interface UpdateOptions {
  preserveCognito: boolean;
  includeCognitoUpdate: boolean;
  requireUserBackup: boolean;
  selectedStacks: string[] | null;
  skipDriftDetection: boolean;
}

/**
 * Drift detection result from backend
 * Requirements: 5.1, 5.2, 5.3, 5.4
 */
export interface DriftItem {
  setting_name: string;
  template_value: string;
  deployed_value: string;
  category: string;
}

export interface DriftDetectionResult {
  has_drift: boolean;
  drift_items: DriftItem[];
  detection_timestamp: string;
  error_message?: string;
  categories_checked: string[];
}

export interface WizardContextType {
  state: WizardState;
  setStep: (step: WizardStep) => void;
  setCapability: (capability: Capability) => void;
  setEnvironment: (environment: string) => void;
  setAwsRegion: (region: string) => void;
  setAWSConfig: (config: AWSConfiguration) => void;
  setArchitectureConfig: (config: ArchitectureConfig) => void;
  setEKSConfig: (config: EKSConfig) => void;
  setInfrastructureConfig: (config: EnvironmentConfig) => void;
  setPermissionStatus: (status: PermissionStatus) => void;
  setDetectionResult: (result: StackDetectionResult) => void;
  setSelectedStrategy: (strategy: DeploymentStrategy) => void;
  setUpdateOptions: (options: UpdateOptions) => void;
  setDeploymentStatus: (status: DeploymentStatus) => void;
  addLog: (log: LogEntry) => void;
  setVerificationResults: (results: VerificationResult) => void;
  setDeleteMode: (deleteMode: boolean) => void;
  setDiscoveryMode: (discoveryMode: boolean) => void;
  resetWizard: () => void;
  goToNextStep: () => void;
  goToPreviousStep: () => void;
}

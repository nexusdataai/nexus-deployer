/**
 * AWS configuration data models for frontend
 */

export enum AWSAuthMethod {
  ROLE_ARN = 'role_arn',
  ACCESS_KEY = 'access_key',
  ADFS_SAML = 'adfs_saml',
  INSTANCE_PROFILE = 'instance_profile',
  AWS_PROFILE = 'aws_profile',
}

// Source authentication methods for Role ARN assumption
export enum SourceAuthMethod {
  ACCESS_KEY = 'access_key',
  AWS_PROFILE = 'aws_profile',
  INSTANCE_PROFILE = 'instance_profile',
  ENVIRONMENT = 'environment',
}

export interface AWSCredentials {
  access_key_id: string;
  secret_access_key: string;
  session_token?: string;
  expiration?: string;
}

export interface AWSConfiguration {
  auth_method: AWSAuthMethod;
  region: string;
  account_id?: string;
  
  // Role ARN method
  role_arn?: string;
  
  // Source credentials for Role ARN assumption
  source_auth_method?: SourceAuthMethod;
  source_access_key_id?: string;
  source_secret_access_key?: string;
  source_profile_name?: string;
  
  // Access Key method
  access_key_id?: string;
  secret_access_key?: string;
  
  // ADFS/SAML method
  adfs_url?: string;
  adfs_username?: string;
  adfs_password?: string;
  
  // AWS Profile method
  profile_name?: string;
  
  // AWS Session ID (for stored credentials)
  aws_session_id?: string;
  
  // Temporary credentials (result of authentication)
  temporary_credentials?: AWSCredentials;
}

export interface Permission {
  action: string;
  granted: boolean;
  resource?: string;
}

export interface PermissionStatus {
  all_granted: boolean;
  required_permissions: Permission[];
  missing_permissions: string[];
  iam_policy_json?: string;
}

export interface AuthValidationRequest {
  auth_method: AWSAuthMethod;
  region: string;
  
  // Role ARN method
  role_arn?: string;
  
  // Source credentials for Role ARN assumption
  source_auth_method?: SourceAuthMethod;
  source_access_key_id?: string;
  source_secret_access_key?: string;
  source_profile_name?: string;
  
  // Access Key method
  access_key_id?: string;
  secret_access_key?: string;
  
  // ADFS/SAML method
  adfs_url?: string;
  adfs_username?: string;
  adfs_password?: string;
  
  // AWS Profile method
  profile_name?: string;
}

// Legacy support
export interface RoleValidationRequest {
  role_arn: string;
  region: string;
}

// Diagnostic information for troubleshooting authentication issues
export interface DiagnosticInfo {
  timestamp?: string;
  step?: string;
  endpoint_url?: string;
  endpoint_reachable?: boolean;
  http_status_code?: number;
  error_code?: string;
  error_message?: string;
  raw_output?: string;
  network_error?: string;
  ssl_error?: string;
  auth_method_used?: string;
  duration_ms?: number;
  steps?: string;  // Step-by-step diagnostic trail: "step1(status) -> step2(status) -> ..."
}

export interface RoleValidationResponse {
  valid: boolean;
  account_id?: string;
  error?: string;
  troubleshooting?: string[];
  session_id?: string;
  credentials?: any;
  success?: boolean;
  diagnostics?: DiagnosticInfo;
}

export interface PermissionVerificationRequest {
  role_arn: string;
  region: string;
  required_permissions: string[];
}

export interface AWSRegion {
  code: string;
  name: string;
}


// ADFS Role Selection Types

export interface ADFSRole {
  role_arn: string;
  principal_arn: string;
  account_id: string;
  role_name: string;
  account_alias?: string;
}

export interface ADFSRolesResponse {
  roles: ADFSRole[];
  session_id: string;
}

export interface ADFSRolesRequest {
  adfs_url: string;
  adfs_username: string;
  adfs_password: string;
  region: string;
}

export interface ADFSRoleSelectionRequest {
  session_id: string;
  role_arn: string;
  region: string;
}

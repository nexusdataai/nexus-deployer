/**
 * Authentication types for the Totogi Customer Toolkit.
 */

// User roles for RBAC
export type UserRole = 'Administrator' | 'Operator' | 'Viewer';

// MFA methods
export type MFAMethod = 'totp' | 'sms' | 'email';

// User information (without sensitive data)
export interface User {
  id: string;
  username: string;
  email: string;
  roles: UserRole[];
  mfa_enabled?: boolean;
  mfa_method?: MFAMethod;
  require_password_change?: boolean;
}

// Authentication state
export interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: User | null;
  token: string | null;
  refreshToken: string | null;
  expiresAt: number | null;
  error: string | null;
}

// Login request/response
export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  success: boolean;
  requires_mfa: boolean;
  mfa_methods?: string[];
  mfa_session_token?: string;
  token?: string;
  refresh_token?: string;
  expires_in?: number;
  user?: User;
  error?: string;
  error_code?: string;
  lockout_remaining?: number;
}

// Token refresh request/response
export interface TokenRefreshRequest {
  refresh_token: string;
}

export interface TokenRefreshResponse {
  success: boolean;
  token?: string;
  refresh_token?: string;
  expires_in?: number;
  error?: string;
}

// Logout request/response
export interface LogoutResponse {
  success: boolean;
  message?: string;
}

// MFA enrollment request/response
export interface MFAEnrollRequest {
  method: MFAMethod;
  phone_number?: string;
}

export interface MFAEnrollResponse {
  success: boolean;
  qr_code?: string;
  secret?: string;
  message?: string;
  error?: string;
}

// MFA verification request/response
export interface MFAVerifyRequest {
  code: string;
  mfa_session_token: string;
}

export interface MFAVerifyResponse {
  success: boolean;
  token?: string;
  refresh_token?: string;
  expires_in?: number;
  user?: User;
  error?: string;
  error_code?: string;
  retries_remaining?: number;
}

// MFA send code request/response
export interface MFASendCodeRequest {
  mfa_session_token: string;
  method: MFAMethod;
}

export interface MFASendCodeResponse {
  success: boolean;
  message?: string;
  error?: string;
}

// MFA status response
export interface MFAStatusResponse {
  enabled: boolean;
  verified: boolean;
  method: MFAMethod | null;
}

// SSO types
export type SSOProviderType = 'saml' | 'oauth' | 'oidc';

export interface SSOProvider {
  id: string;
  name: string;
  type: SSOProviderType;
  icon_url?: string;
}

export interface SSOConfigResponse {
  enabled: boolean;
  providers: SSOProvider[];
  default_provider?: string;
}

export interface SSOInitiateResponse {
  success: boolean;
  redirect_url?: string;
  error?: string;
}

export interface SSOCallbackResponse {
  success: boolean;
  token?: string;
  refresh_token?: string;
  expires_in?: number;
  user?: User;
  error?: string;
  error_code?: string;
  fallback_available?: boolean;
}

// Auth error codes
export enum AuthErrorCode {
  INVALID_CREDENTIALS = 'AUTH_001',
  ACCOUNT_LOCKED = 'AUTH_002',
  TOKEN_EXPIRED = 'AUTH_003',
  TOKEN_INVALID = 'AUTH_004',
  USER_NOT_FOUND = 'AUTH_005',
  MFA_INVALID_CODE = 'MFA_001',
  MFA_RETRIES_EXHAUSTED = 'MFA_002',
  MFA_NOT_ENABLED = 'MFA_003',
  MFA_ALREADY_ENABLED = 'MFA_004',
  MFA_INVALID_METHOD = 'MFA_005',
  MFA_CODE_DELIVERY_FAILED = 'MFA_006',
  SSO_PROVIDER_NOT_CONFIGURED = 'SSO_001',
  SSO_INVALID_SAML = 'SSO_002',
  SSO_INVALID_OAUTH = 'SSO_003',
  SSO_SIGNATURE_FAILED = 'SSO_004',
  SSO_CLAIMS_FAILED = 'SSO_005',
  SSO_PROVIDER_UNREACHABLE = 'SSO_006',
}

// Helper to check if user has a specific role
export function hasRole(user: User | null, role: UserRole): boolean {
  return user?.roles?.includes(role) ?? false;
}

// Helper to check if user has any of the specified roles
export function hasAnyRole(user: User | null, roles: UserRole[]): boolean {
  return roles.some(role => hasRole(user, role));
}

// Helper to check if user is admin
export function isAdmin(user: User | null): boolean {
  return hasRole(user, 'Administrator');
}

// Helper to check if user can perform operator actions
export function canOperate(user: User | null): boolean {
  return hasAnyRole(user, ['Administrator', 'Operator']);
}

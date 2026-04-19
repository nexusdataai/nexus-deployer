/**
 * Authentication Service
 * Handles all authentication API calls and token management.
 */
import axios, { AxiosInstance } from 'axios';
import {
  LoginRequest,
  LoginResponse,
  TokenRefreshRequest,
  TokenRefreshResponse,
  LogoutResponse,
  MFAEnrollRequest,
  MFAEnrollResponse,
  MFAVerifyRequest,
  MFAVerifyResponse,
  MFASendCodeRequest,
  MFASendCodeResponse,
  MFAStatusResponse,
  SSOConfigResponse,
  SSOInitiateResponse,
  SSOCallbackResponse,
  User,
} from '../types/auth';

// Storage keys
const TOKEN_KEY = 'auth_token';
const REFRESH_TOKEN_KEY = 'auth_refresh_token';
const USER_KEY = 'auth_user';
const EXPIRES_AT_KEY = 'auth_expires_at';

// API base URL - Use 127.0.0.1 instead of localhost to avoid IPv6 resolution issues on Windows
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8001';

class AuthService {
  private api: AxiosInstance;
  private refreshPromise: Promise<TokenRefreshResponse> | null = null;

  constructor() {
    this.api = axios.create({
      baseURL: API_BASE_URL,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Add auth header interceptor
    this.api.interceptors.request.use((config) => {
      const token = this.getToken();
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
      return config;
    });

    // Add response interceptor for token refresh
    this.api.interceptors.response.use(
      (response) => response,
      async (error) => {
        const originalRequest = error.config;

        // If 401 and not already retrying, try to refresh token
        if (error.response?.status === 401 && !originalRequest._retry) {
          originalRequest._retry = true;

          try {
            const refreshToken = this.getRefreshToken();
            if (refreshToken) {
              const result = await this.refreshTokens(refreshToken);
              if (result.success && result.token) {
                originalRequest.headers.Authorization = `Bearer ${result.token}`;
                return this.api(originalRequest);
              }
            }
          } catch {
            // Refresh failed, clear auth state
            this.clearAuth();
          }
        }

        return Promise.reject(error);
      }
    );
  }

  // ==================== Token Storage ====================

  getToken(): string | null {
    return localStorage.getItem(TOKEN_KEY);
  }

  getRefreshToken(): string | null {
    return localStorage.getItem(REFRESH_TOKEN_KEY);
  }

  getUser(): User | null {
    const userJson = localStorage.getItem(USER_KEY);
    if (userJson) {
      try {
        return JSON.parse(userJson);
      } catch {
        return null;
      }
    }
    return null;
  }

  getExpiresAt(): number | null {
    const expiresAt = localStorage.getItem(EXPIRES_AT_KEY);
    return expiresAt ? parseInt(expiresAt, 10) : null;
  }

  isTokenExpired(): boolean {
    const expiresAt = this.getExpiresAt();
    if (!expiresAt) return true;
    // Add 30 second buffer
    return Date.now() >= expiresAt - 30000;
  }

  private setAuth(
    token: string,
    refreshToken: string,
    user: User,
    expiresIn: number
  ): void {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    localStorage.setItem(
      EXPIRES_AT_KEY,
      String(Date.now() + expiresIn * 1000)
    );
  }

  clearAuth(): void {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem(EXPIRES_AT_KEY);
  }

  // ==================== Authentication ====================

  async login(request: LoginRequest): Promise<LoginResponse> {
    try {
      const response = await this.api.post<LoginResponse>(
        '/api/auth/login',
        request
      );
      const data = response.data;

      // If successful and no MFA required, store tokens
      if (data.success && !data.requires_mfa && data.token && data.user) {
        this.setAuth(
          data.token,
          data.refresh_token!,
          data.user,
          data.expires_in || 1800
        );
      }

      return data;
    } catch (error: any) {
      return {
        success: false,
        requires_mfa: false,
        error: error.response?.data?.detail || 'Login failed',
      };
    }
  }

  async logout(): Promise<LogoutResponse> {
    try {
      const response = await this.api.post<LogoutResponse>('/api/auth/logout');
      this.clearAuth();
      return response.data;
    } catch (error: any) {
      this.clearAuth();
      return {
        success: true,
        message: 'Logged out locally',
      };
    }
  }

  async refreshTokens(refreshToken: string): Promise<TokenRefreshResponse> {
    // Prevent multiple simultaneous refresh requests
    if (this.refreshPromise) {
      return this.refreshPromise;
    }

    this.refreshPromise = (async () => {
      try {
        const request: TokenRefreshRequest = { refresh_token: refreshToken };
        const response = await this.api.post<TokenRefreshResponse>(
          '/api/auth/refresh',
          request
        );
        const data = response.data;

        if (data.success && data.token && data.refresh_token) {
          const user = this.getUser();
          if (user) {
            this.setAuth(
              data.token,
              data.refresh_token,
              user,
              data.expires_in || 1800
            );
          }
        }

        return data;
      } catch (error: any) {
        return {
          success: false,
          error: error.response?.data?.detail || 'Token refresh failed',
        };
      } finally {
        this.refreshPromise = null;
      }
    })();

    return this.refreshPromise;
  }

  async validateToken(): Promise<{ valid: boolean; user_id?: string }> {
    try {
      const response = await this.api.post('/api/auth/validate');
      return response.data;
    } catch {
      return { valid: false };
    }
  }

  async getCurrentUser(): Promise<User | null> {
    try {
      const response = await this.api.get<User>('/api/auth/me');
      return response.data;
    } catch {
      return null;
    }
  }

  // ==================== MFA ====================

  async enrollMFA(request: MFAEnrollRequest): Promise<MFAEnrollResponse> {
    try {
      const response = await this.api.post<MFAEnrollResponse>(
        '/api/mfa/enroll',
        request
      );
      return response.data;
    } catch (error: any) {
      return {
        success: false,
        error: error.response?.data?.detail || 'MFA enrollment failed',
      };
    }
  }

  async verifyMFAEnrollment(code: string): Promise<MFAEnrollResponse> {
    try {
      const response = await this.api.post<MFAEnrollResponse>(
        '/api/mfa/verify-enrollment',
        { code }
      );
      return response.data;
    } catch (error: any) {
      return {
        success: false,
        error: error.response?.data?.detail || 'MFA verification failed',
      };
    }
  }

  async verifyMFA(request: MFAVerifyRequest): Promise<MFAVerifyResponse> {
    try {
      const response = await this.api.post<MFAVerifyResponse>(
        '/api/mfa/verify',
        request
      );
      const data = response.data;

      // If successful, store tokens
      if (data.success && data.token && data.user) {
        this.setAuth(
          data.token,
          data.refresh_token!,
          data.user,
          data.expires_in || 1800
        );
      }

      return data;
    } catch (error: any) {
      return {
        success: false,
        error: error.response?.data?.detail || 'MFA verification failed',
      };
    }
  }

  async sendMFACode(request: MFASendCodeRequest): Promise<MFASendCodeResponse> {
    try {
      const response = await this.api.post<MFASendCodeResponse>(
        '/api/mfa/send-code',
        request
      );
      return response.data;
    } catch (error: any) {
      return {
        success: false,
        error: error.response?.data?.detail || 'Failed to send MFA code',
      };
    }
  }

  async getMFAStatus(): Promise<MFAStatusResponse> {
    try {
      const response = await this.api.get<MFAStatusResponse>('/api/mfa/status');
      return response.data;
    } catch {
      return {
        enabled: false,
        verified: false,
        method: null,
      };
    }
  }

  async disableMFA(): Promise<{ success: boolean; message?: string }> {
    try {
      const response = await this.api.post('/api/mfa/disable');
      return response.data;
    } catch (error: any) {
      return {
        success: false,
        message: error.response?.data?.detail || 'Failed to disable MFA',
      };
    }
  }

  // ==================== SSO ====================

  async getSSOConfig(): Promise<SSOConfigResponse> {
    try {
      const response = await this.api.get<SSOConfigResponse>('/api/sso/config');
      return response.data;
    } catch {
      return {
        enabled: false,
        providers: [],
      };
    }
  }

  async initiateSSOLogin(
    providerId: string,
    redirectUri?: string
  ): Promise<SSOInitiateResponse> {
    try {
      const response = await this.api.post<SSOInitiateResponse>(
        '/api/sso/initiate',
        {
          provider_id: providerId,
          redirect_uri: redirectUri || window.location.origin + '/sso/callback',
        }
      );
      return response.data;
    } catch (error: any) {
      return {
        success: false,
        error: error.response?.data?.detail || 'SSO initiation failed',
      };
    }
  }

  async handleSSOCallback(
    code: string,
    state: string
  ): Promise<SSOCallbackResponse> {
    try {
      const response = await this.api.get<SSOCallbackResponse>(
        '/api/sso/callback/oauth',
        {
          params: { code, state },
        }
      );
      const data = response.data;

      // If successful, store tokens
      if (data.success && data.token && data.user) {
        this.setAuth(
          data.token,
          data.refresh_token!,
          data.user,
          data.expires_in || 1800
        );
      }

      return data;
    } catch (error: any) {
      return {
        success: false,
        error: error.response?.data?.detail || 'SSO callback failed',
        fallback_available: true,
      };
    }
  }

  // Redirect to SSO provider
  redirectToSSO(providerId: string): void {
    const redirectUri = encodeURIComponent(
      window.location.origin + '/sso/callback'
    );
    window.location.href = `${API_BASE_URL}/api/sso/initiate/${providerId}?redirect_uri=${redirectUri}`;
  }

  // ==================== Setup ====================

  async getSetupStatus(): Promise<{
    setup_complete: boolean;
    user_count: number;
    admin_exists: boolean;
    requires_initial_setup: boolean;
  }> {
    try {
      const response = await this.api.get('/api/setup/status');
      return response.data;
    } catch {
      return {
        setup_complete: false,
        user_count: 0,
        admin_exists: false,
        requires_initial_setup: true,
      };
    }
  }

  async initializeSetup(): Promise<{
    setup_required: boolean;
    setup_complete: boolean;
    created?: boolean;
    username?: string;
    default_password?: string;
    message?: string;
  }> {
    try {
      const response = await this.api.post('/api/setup/initialize');
      return response.data;
    } catch (error: any) {
      return {
        setup_required: false,
        setup_complete: false,
        message: error.response?.data?.detail || 'Setup initialization failed',
      };
    }
  }

  // ==================== Password Change ====================

  async changePassword(
    currentPassword: string,
    newPassword: string
  ): Promise<{
    success: boolean;
    message?: string;
    error?: string;
    error_code?: string;
  }> {
    try {
      const response = await this.api.post('/api/auth/change-password', {
        current_password: currentPassword,
        new_password: newPassword,
      });
      return response.data;
    } catch (error: any) {
      return {
        success: false,
        error: error.response?.data?.detail || 'Password change failed',
      };
    }
  }
}

// Export singleton instance
export const authService = new AuthService();
export default authService;

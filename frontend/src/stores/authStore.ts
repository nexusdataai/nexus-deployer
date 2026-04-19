/**
 * Authentication Store
 * Zustand store for managing authentication state.
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import {
  AuthState,
  User,
  LoginRequest,
  LoginResponse,
  MFAVerifyRequest,
  MFAVerifyResponse,
  MFAEnrollRequest,
  MFAEnrollResponse,
  SSOProvider,
} from '../types/auth';
import { authService } from '../services/authService';

interface AuthStore extends Omit<AuthState, 'refreshToken'> {
  // Token state (renamed to avoid conflict with action)
  refreshTokenValue: string | null;
  
  // MFA state
  mfaSessionToken: string | null;
  mfaMethods: string[];
  
  // SSO state
  ssoProviders: SSOProvider[];
  ssoEnabled: boolean;
  
  // Actions
  login: (request: LoginRequest) => Promise<LoginResponse>;
  logout: () => Promise<void>;
  refreshTokenAction: () => Promise<boolean>;
  verifyMFA: (code: string) => Promise<MFAVerifyResponse>;
  enrollMFA: (request: MFAEnrollRequest) => Promise<MFAEnrollResponse>;
  verifyMFAEnrollment: (code: string) => Promise<MFAEnrollResponse>;
  disableMFA: () => Promise<boolean>;
  loadSSOConfig: () => Promise<void>;
  initiateSSOLogin: (providerId: string) => void;
  handleSSOCallback: (code: string, state: string) => Promise<boolean>;
  checkAuth: () => Promise<boolean>;
  clearError: () => void;
  setUser: (user: User | null) => void;
}

export const useAuthStore = create<AuthStore>()(
  persist(
    (set, get) => ({
      // Initial state
      isAuthenticated: false,
      isLoading: false,
      user: null,
      token: null,
      refreshTokenValue: null,
      expiresAt: null,
      error: null,
      mfaSessionToken: null,
      mfaMethods: [],
      ssoProviders: [],
      ssoEnabled: false,

      // Login action
      login: async (request: LoginRequest): Promise<LoginResponse> => {
        set({ isLoading: true, error: null });

        try {
          const response = await authService.login(request);

          if (response.success) {
            if (response.requires_mfa) {
              // MFA required - store session token
              set({
                isLoading: false,
                mfaSessionToken: response.mfa_session_token || null,
                mfaMethods: response.mfa_methods || [],
              });
            } else if (response.token && response.user) {
              // Full authentication success
              set({
                isAuthenticated: true,
                isLoading: false,
                user: response.user,
                token: response.token,
                refreshTokenValue: response.refresh_token || null,
                expiresAt: response.expires_in
                  ? Date.now() + response.expires_in * 1000
                  : null,
                mfaSessionToken: null,
                mfaMethods: [],
              });
            }
          } else {
            set({
              isLoading: false,
              error: response.error || 'Login failed',
            });
          }

          return response;
        } catch (error: any) {
          const errorMessage = error.message || 'Login failed';
          set({ isLoading: false, error: errorMessage });
          return {
            success: false,
            requires_mfa: false,
            error: errorMessage,
          };
        }
      },

      // Logout action
      logout: async (): Promise<void> => {
        set({ isLoading: true });

        try {
          await authService.logout();
        } finally {
          set({
            isAuthenticated: false,
            isLoading: false,
            user: null,
            token: null,
            refreshTokenValue: null,
            expiresAt: null,
            error: null,
            mfaSessionToken: null,
            mfaMethods: [],
          });
        }
      },

      // Refresh token action
      refreshTokenAction: async (): Promise<boolean> => {
        const currentRefreshToken = get().refreshTokenValue || authService.getRefreshToken();
        
        if (!currentRefreshToken) {
          return false;
        }

        try {
          const response = await authService.refreshTokens(currentRefreshToken);

          if (response.success && response.token) {
            set({
              token: response.token,
              refreshTokenValue: response.refresh_token || get().refreshTokenValue,
              expiresAt: response.expires_in
                ? Date.now() + response.expires_in * 1000
                : get().expiresAt,
            });
            return true;
          }

          // Refresh failed - clear auth
          set({
            isAuthenticated: false,
            user: null,
            token: null,
            refreshTokenValue: null,
            expiresAt: null,
          });
          return false;
        } catch {
          return false;
        }
      },

      // MFA verification action
      verifyMFA: async (code: string): Promise<MFAVerifyResponse> => {
        const mfaSessionToken = get().mfaSessionToken;
        
        if (!mfaSessionToken) {
          return {
            success: false,
            error: 'No MFA session active',
          };
        }

        set({ isLoading: true, error: null });

        try {
          const request: MFAVerifyRequest = {
            code,
            mfa_session_token: mfaSessionToken,
          };
          const response = await authService.verifyMFA(request);

          if (response.success && response.token && response.user) {
            set({
              isAuthenticated: true,
              isLoading: false,
              user: response.user,
              token: response.token,
              refreshTokenValue: response.refresh_token || null,
              expiresAt: response.expires_in
                ? Date.now() + response.expires_in * 1000
                : null,
              mfaSessionToken: null,
              mfaMethods: [],
            });
          } else {
            set({
              isLoading: false,
              error: response.error || 'MFA verification failed',
            });
          }

          return response;
        } catch (error: any) {
          const errorMessage = error.message || 'MFA verification failed';
          set({ isLoading: false, error: errorMessage });
          return {
            success: false,
            error: errorMessage,
          };
        }
      },

      // MFA enrollment action
      enrollMFA: async (request: MFAEnrollRequest): Promise<MFAEnrollResponse> => {
        set({ isLoading: true, error: null });

        try {
          const response = await authService.enrollMFA(request);

          set({ isLoading: false });

          if (!response.success) {
            set({ error: response.error || 'MFA enrollment failed' });
          }

          return response;
        } catch (error: any) {
          const errorMessage = error.message || 'MFA enrollment failed';
          set({ isLoading: false, error: errorMessage });
          return {
            success: false,
            error: errorMessage,
          };
        }
      },

      // MFA enrollment verification action
      verifyMFAEnrollment: async (code: string): Promise<MFAEnrollResponse> => {
        set({ isLoading: true, error: null });

        try {
          const response = await authService.verifyMFAEnrollment(code);

          set({ isLoading: false });

          if (!response.success) {
            set({ error: response.error || 'MFA verification failed' });
          }

          return response;
        } catch (error: any) {
          const errorMessage = error.message || 'MFA verification failed';
          set({ isLoading: false, error: errorMessage });
          return {
            success: false,
            error: errorMessage,
          };
        }
      },

      // Disable MFA action
      disableMFA: async (): Promise<boolean> => {
        set({ isLoading: true, error: null });

        try {
          const response = await authService.disableMFA();
          set({ isLoading: false });
          return response.success;
        } catch {
          set({ isLoading: false });
          return false;
        }
      },

      // Load SSO configuration
      loadSSOConfig: async (): Promise<void> => {
        try {
          const config = await authService.getSSOConfig();
          set({
            ssoEnabled: config.enabled,
            ssoProviders: config.providers,
          });
        } catch {
          set({
            ssoEnabled: false,
            ssoProviders: [],
          });
        }
      },

      // Initiate SSO login
      initiateSSOLogin: (providerId: string): void => {
        authService.redirectToSSO(providerId);
      },

      // Handle SSO callback
      handleSSOCallback: async (code: string, state: string): Promise<boolean> => {
        set({ isLoading: true, error: null });

        try {
          const response = await authService.handleSSOCallback(code, state);

          if (response.success && response.token && response.user) {
            set({
              isAuthenticated: true,
              isLoading: false,
              user: response.user,
              token: response.token,
              refreshTokenValue: response.refresh_token || null,
              expiresAt: response.expires_in
                ? Date.now() + response.expires_in * 1000
                : null,
            });
            return true;
          }

          set({
            isLoading: false,
            error: response.error || 'SSO authentication failed',
          });
          return false;
        } catch (error: any) {
          set({
            isLoading: false,
            error: error.message || 'SSO authentication failed',
          });
          return false;
        }
      },

      // Check authentication status
      checkAuth: async (): Promise<boolean> => {
        // First check local storage
        const token = authService.getToken();
        const user = authService.getUser();

        if (!token || !user) {
          set({ isAuthenticated: false, user: null, token: null });
          return false;
        }

        // Check if token is expired
        if (authService.isTokenExpired()) {
          // Try to refresh
          const refreshed = await get().refreshTokenAction();
          if (!refreshed) {
            set({ isAuthenticated: false, user: null, token: null });
            return false;
          }
        }

        // Validate token with server
        const validation = await authService.validateToken();
        
        if (validation.valid) {
          set({
            isAuthenticated: true,
            user,
            token,
            refreshTokenValue: authService.getRefreshToken(),
            expiresAt: authService.getExpiresAt(),
          });
          return true;
        }

        // Token invalid - clear auth
        authService.clearAuth();
        set({ isAuthenticated: false, user: null, token: null });
        return false;
      },

      // Clear error
      clearError: (): void => {
        set({ error: null });
      },

      // Set user (for updates)
      setUser: (user: User | null): void => {
        set({ user });
      },
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({
        // Only persist these fields
        isAuthenticated: state.isAuthenticated,
        user: state.user,
        token: state.token,
        refreshTokenValue: state.refreshTokenValue,
        expiresAt: state.expiresAt,
      }),
    }
  )
);

export default useAuthStore;

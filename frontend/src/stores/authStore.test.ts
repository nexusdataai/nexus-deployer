/**
 * AuthStore Property Tests
 * 
 * Feature: user-menu
 * Property 3: Logout Clears Auth State
 * Validates: Requirements 3.4, 3.5
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import fc from 'fast-check';
import { useAuthStore } from './authStore';
import { User, UserRole } from '../types/auth';

// Mock the auth service
vi.mock('../services/authService', () => ({
  authService: {
    logout: vi.fn().mockResolvedValue({ success: true }),
    getToken: vi.fn().mockReturnValue(null),
    getUser: vi.fn().mockReturnValue(null),
    getRefreshToken: vi.fn().mockReturnValue(null),
    getExpiresAt: vi.fn().mockReturnValue(null),
    isTokenExpired: vi.fn().mockReturnValue(true),
    validateToken: vi.fn().mockResolvedValue({ valid: false }),
    clearAuth: vi.fn(),
  },
}));

// Arbitrary for generating random users
const userArbitrary = fc.record({
  id: fc.uuid(),
  username: fc.string({ minLength: 1, maxLength: 50 }),
  email: fc.emailAddress(),
  roles: fc.array(fc.constantFrom<UserRole>('Administrator', 'Operator', 'Viewer'), { minLength: 1, maxLength: 3 }),
  mfa_enabled: fc.boolean(),
  require_password_change: fc.boolean(),
});

// Arbitrary for generating random tokens
const tokenArbitrary = fc.string({ minLength: 20, maxLength: 200 });

describe('AuthStore Properties', () => {
  beforeEach(() => {
    // Reset the store state before each test
    useAuthStore.setState({
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
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  /**
   * Property 3: Logout Clears Auth State
   * For any authenticated state, logout results in isAuthenticated=false, user=null, token=null
   */
  it('logout always clears all auth state regardless of initial state', async () => {
    await fc.assert(
      fc.asyncProperty(
        userArbitrary,
        tokenArbitrary,
        tokenArbitrary,
        fc.integer({ min: Date.now(), max: Date.now() + 86400000 }),
        async (user, token, refreshToken, expiresAt) => {
          // Set up an authenticated state
          useAuthStore.setState({
            isAuthenticated: true,
            user: user as User,
            token,
            refreshTokenValue: refreshToken,
            expiresAt,
            error: null,
          });

          // Verify we're authenticated
          const stateBefore = useAuthStore.getState();
          expect(stateBefore.isAuthenticated).toBe(true);
          expect(stateBefore.user).not.toBeNull();
          expect(stateBefore.token).not.toBeNull();

          // Perform logout
          await useAuthStore.getState().logout();

          // Verify all auth state is cleared
          const stateAfter = useAuthStore.getState();
          
          return (
            stateAfter.isAuthenticated === false &&
            stateAfter.user === null &&
            stateAfter.token === null &&
            stateAfter.refreshTokenValue === null &&
            stateAfter.expiresAt === null &&
            stateAfter.error === null &&
            stateAfter.mfaSessionToken === null &&
            stateAfter.mfaMethods.length === 0
          );
        }
      ),
      { numRuns: 50 }
    );
  });

  /**
   * Property: Logout is idempotent
   * Calling logout multiple times should have the same effect as calling it once
   */
  it('logout is idempotent - multiple calls have same effect', async () => {
    await fc.assert(
      fc.asyncProperty(
        userArbitrary,
        tokenArbitrary,
        fc.integer({ min: 1, max: 5 }),
        async (user, token, logoutCount) => {
          // Set up an authenticated state
          useAuthStore.setState({
            isAuthenticated: true,
            user: user as User,
            token,
            refreshTokenValue: token,
            expiresAt: Date.now() + 3600000,
            error: null,
          });

          // Call logout multiple times
          for (let i = 0; i < logoutCount; i++) {
            await useAuthStore.getState().logout();
          }

          // Verify state is cleared
          const state = useAuthStore.getState();
          
          return (
            state.isAuthenticated === false &&
            state.user === null &&
            state.token === null
          );
        }
      ),
      { numRuns: 30 }
    );
  });
});

describe('AuthStore Unit Tests', () => {
  beforeEach(() => {
    useAuthStore.setState({
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
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('logout clears authenticated state', async () => {
    // Set up authenticated state
    useAuthStore.setState({
      isAuthenticated: true,
      user: {
        id: '1',
        username: 'testuser',
        email: 'test@example.com',
        roles: ['Administrator'],
      },
      token: 'test-token',
      refreshTokenValue: 'test-refresh-token',
      expiresAt: Date.now() + 3600000,
    });

    await useAuthStore.getState().logout();

    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(false);
    expect(state.user).toBeNull();
    expect(state.token).toBeNull();
    expect(state.refreshTokenValue).toBeNull();
    expect(state.expiresAt).toBeNull();
  });

  it('logout clears MFA state', async () => {
    useAuthStore.setState({
      isAuthenticated: true,
      user: { id: '1', username: 'test', email: 'test@test.com', roles: ['Viewer'] },
      token: 'token',
      mfaSessionToken: 'mfa-session',
      mfaMethods: ['totp', 'sms'],
    });

    await useAuthStore.getState().logout();

    const state = useAuthStore.getState();
    expect(state.mfaSessionToken).toBeNull();
    expect(state.mfaMethods).toEqual([]);
  });

  it('logout clears error state', async () => {
    useAuthStore.setState({
      isAuthenticated: true,
      user: { id: '1', username: 'test', email: 'test@test.com', roles: ['Viewer'] },
      token: 'token',
      error: 'Some previous error',
    });

    await useAuthStore.getState().logout();

    const state = useAuthStore.getState();
    expect(state.error).toBeNull();
  });

  it('setUser updates user in state', () => {
    const newUser: User = {
      id: '2',
      username: 'newuser',
      email: 'new@example.com',
      roles: ['Operator'],
    };

    useAuthStore.getState().setUser(newUser);

    expect(useAuthStore.getState().user).toEqual(newUser);
  });

  it('clearError clears error state', () => {
    useAuthStore.setState({ error: 'Test error' });

    useAuthStore.getState().clearError();

    expect(useAuthStore.getState().error).toBeNull();
  });
});

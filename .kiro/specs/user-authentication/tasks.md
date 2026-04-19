# Implementation Plan: User Authentication

## Overview

This implementation plan breaks down the user authentication feature into discrete coding tasks. The implementation follows a bottom-up approach: starting with data models and core services, then building up to API endpoints and frontend integration. Each task builds on previous work to ensure incremental, testable progress.

## Tasks

- [x] 1. Set up authentication data models and user store
  - [x] 1.1 Create user data models in `app/models/auth_models.py`
    - Define User, Session, MFAEnrollment, and SSOProvider Pydantic models
    - Include all fields from design: id, username, email, password_hash, roles, mfa_enabled, etc.
    - _Requirements: 1.1, 1.2, 2.1, 3.2_

  - [x] 1.2 Create TinyDB user store service in `app/services/user_store.py`
    - Implement CRUD operations for users
    - Implement password hashing using argon2
    - Implement user lookup by username, email, and SSO subject
    - _Requirements: 1.1, 1.2_

  - [x] 1.3 Write property tests for user store
    - **Property 1: Valid credentials produce authenticated session**
    - **Property 2: Invalid credentials increment failure counter**
    - **Validates: Requirements 1.1, 1.2**

- [x] 2. Implement JWT service
  - [x] 2.1 Create JWT service in `app/services/jwt_service.py`
    - Implement `create_access_token` with 30-minute expiration
    - Implement `create_refresh_token` with 7-day expiration
    - Implement `validate_token` with signature and expiration checks
    - Implement `is_token_expired` helper
    - _Requirements: 1.4, 1.5_

  - [x] 2.2 Write property tests for JWT service
    - **Property 4: JWT token expiration is thirty minutes**
    - **Property 5: Expired tokens are rejected**
    - **Validates: Requirements 1.4, 1.5**

- [x] 3. Implement account lockout service
  - [x] 3.1 Create account lockout service in `app/services/account_lockout_service.py`
    - Implement `record_failed_attempt` to increment counter
    - Implement `is_account_locked` with 5-attempt threshold and 15-minute duration
    - Implement `reset_failed_attempts` for successful login
    - _Requirements: 1.3, 1.6, 1.7_

  - [x] 3.2 Write property tests for account lockout
    - **Property 3: Account lockout after five failures**
    - **Property 6: Lockout counter reset after expiration**
    - **Property 7: Successful authentication resets failure counter**
    - **Validates: Requirements 1.3, 1.6, 1.7**

- [x] 4. Checkpoint - Core services complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement authentication service
  - [x] 5.1 Create authentication service in `app/services/authentication_service.py`
    - Implement `authenticate` method with password verification
    - Integrate with lockout service for failed attempt tracking
    - Integrate with JWT service for session creation
    - Handle MFA-enabled users (return requires_mfa flag)
    - _Requirements: 1.1, 1.2, 1.3, 1.7, 2.2_

  - [x] 5.2 Create authentication router in `app/routers/auth.py`
    - Implement POST `/api/auth/login` endpoint
    - Implement POST `/api/auth/logout` endpoint
    - Implement POST `/api/auth/refresh` endpoint
    - Add request/response models
    - _Requirements: 1.1, 1.4, 1.5_

  - [x] 5.3 Write integration tests for authentication flow
    - Test full login flow with valid credentials
    - Test login rejection with invalid credentials
    - Test account lockout after 5 failures
    - **Validates: Requirements 1.1, 1.2, 1.3**

- [x] 6. Implement MFA service
  - [x] 6.1 Create MFA service in `app/services/mfa_service.py`
    - Implement `generate_totp_secret` using pyotp
    - Implement `generate_qr_code` using qrcode library
    - Implement `verify_totp` with 30-second window
    - Implement retry tracking (max 3 attempts)
    - Add SMS/email code generation stubs
    - _Requirements: 2.1, 2.3, 2.4, 2.7, 2.8_

  - [x] 6.2 Write property tests for MFA service
    - **Property 8: MFA enrollment produces valid TOTP secret**
    - **Property 10: TOTP verification round-trip**
    - **Property 11: Invalid MFA codes are rejected with retry tracking**
    - **Property 12: MFA retry exhaustion invalidates session**
    - **Property 13: MFA enrollment requires verification**
    - **Validates: Requirements 2.1, 2.3, 2.4, 2.7, 2.8**

  - [x] 6.3 Create MFA router in `app/routers/mfa.py`
    - Implement POST `/api/mfa/enroll` endpoint
    - Implement POST `/api/mfa/verify` endpoint
    - Implement POST `/api/mfa/send-code` endpoint
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [x] 7. Checkpoint - Authentication and MFA complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Implement SSO service
  - [x] 8.1 Create SSO configuration models in `app/models/sso_models.py`
    - Define SAMLConfig, OAuthConfig, OIDCConfig models
    - Define SSOProvider configuration model
    - Define role mapping configuration
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 8.2 Create SSO service in `app/services/sso_service.py`
    - Implement `get_saml_redirect_url` for SAML initiation
    - Implement `validate_saml_assertion` with signature verification
    - Implement `get_oauth_redirect_url` for OAuth/OIDC initiation
    - Implement `exchange_oauth_code` for token exchange
    - Implement `extract_oidc_claims` for ID token parsing
    - Implement `map_external_roles` for role mapping
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.6, 3.7, 3.8_

  - [x] 8.3 Write property tests for SSO service
    - **Property 14: SSO redirect URL generation**
    - **Property 15: SAML assertion creates session with role mapping**
    - **Property 19: SAML signature validation**
    - **Property 20: External role mapping consistency**
    - **Validates: Requirements 3.1, 3.2, 3.6, 3.8**

  - [x] 8.4 Create SSO router in `app/routers/sso.py`
    - Implement GET `/api/sso/config` endpoint
    - Implement GET `/api/sso/initiate/{provider}` endpoint
    - Implement POST `/api/sso/callback/saml` endpoint
    - Implement GET `/api/sso/callback/oauth` endpoint
    - Handle SSO failures with fallback option
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 8.5 Write property tests for SSO error handling
    - **Property 18: SSO failure provides fallback option**
    - **Validates: Requirements 3.5**

- [x] 9. Checkpoint - Backend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Integrate authentication into main application
  - [x] 10.1 Update `app/main.py` to include auth routers
    - Add auth, mfa, and sso routers to FastAPI app
    - Add JWT secret key configuration
    - Add authentication middleware for protected routes
    - _Requirements: 1.1, 2.2, 3.1_

  - [x] 10.2 Create authentication dependency for protected routes
    - Implement `get_current_user` dependency
    - Implement `require_role` dependency for RBAC
    - Apply to existing capability and deployment routes
    - _Requirements: 1.4, 1.5_

- [x] 11. Create frontend authentication components
  - [x] 11.1 Create authentication types in `frontend/src/types/auth.ts`
    - Define LoginRequest, LoginResponse types
    - Define MFAVerifyRequest, MFAVerifyResponse types
    - Define User, Session types
    - _Requirements: 1.1, 2.2_

  - [x] 11.2 Create authentication service in `frontend/src/services/authService.ts`
    - Implement login, logout, refresh API calls
    - Implement MFA verification API calls
    - Implement SSO initiation
    - Handle token storage in localStorage
    - _Requirements: 1.1, 1.4, 2.2, 3.1_

  - [x] 11.3 Create authentication store in `frontend/src/stores/authStore.ts`
    - Use Zustand for auth state management
    - Store current user, token, and auth status
    - Implement login, logout, and refresh actions
    - _Requirements: 1.1, 1.4_

  - [x] 11.4 Create Login component in `frontend/src/components/auth/Login.tsx`
    - Create login form with username/password fields
    - Handle form validation and submission
    - Display error messages for failed login
    - Show account lockout message when applicable
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 11.5 Create MFA verification component in `frontend/src/components/auth/MFAVerify.tsx`
    - Create code input field
    - Display retry count
    - Handle verification submission
    - _Requirements: 2.2, 2.3, 2.4_

  - [x] 11.6 Create SSO login button component in `frontend/src/components/auth/SSOLogin.tsx`
    - Display configured SSO providers
    - Handle SSO initiation redirect
    - Handle SSO callback
    - _Requirements: 3.1, 3.5_

- [x] 12. Integrate authentication into frontend routing
  - [x] 12.1 Create protected route wrapper in `frontend/src/components/auth/ProtectedRoute.tsx`
    - Check authentication status
    - Redirect to login if not authenticated
    - Handle token expiration
    - _Requirements: 1.4, 1.5_

  - [x] 12.2 Update `frontend/src/App.tsx` with auth routes
    - Add /login route
    - Add /mfa-verify route
    - Add /sso/callback route
    - Wrap protected routes with ProtectedRoute
    - _Requirements: 1.1, 2.2, 3.1_

- [x] 13. Final checkpoint - Full integration complete
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- All tasks including property tests are required for comprehensive coverage
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties
- Unit tests validate specific examples and edge cases
- Backend uses Python with FastAPI, frontend uses React with TypeScript
- Property-based testing uses Hypothesis (Python) and fast-check (TypeScript)

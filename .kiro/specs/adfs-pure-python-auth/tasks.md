<!-- (renamed totogi-* -> nexus-* on 2026-06-13; original wording was design-snapshot) -->
# Implementation Plan: ADFS Pure Python Authentication

## Overview

This plan converts the ADFS authentication from subprocess-based aws-adfs.exe to pure Python library implementation. The implementation will modify `aws_auth_service.py` to remove all aws-adfs.exe dependencies and use requests, requests-ntlm, beautifulsoup4, and boto3 directly.

## Tasks

- [x] 1. Remove aws-adfs.exe related code
  - [x] 1.1 Remove _get_aws_adfs_executable method from AWSAuthService
    - Delete the entire method that searches for aws-adfs.exe
    - _Requirements: 1.1, 1.2, 1.3_
  - [x] 1.2 Remove subprocess imports and aws-adfs references
    - Search and remove any remaining subprocess imports used for aws-adfs
    - Remove any remaining aws-adfs.exe path references
    - _Requirements: 1.2, 1.3_

- [x] 2. Implement pure Python fetch_adfs_roles
  - [x] 2.1 Implement ADFS authentication with NTLM and form-based fallback
    - Use requests-ntlm for NTLM authentication
    - Implement form-based authentication as fallback
    - Parse HTML response using BeautifulSoup
    - _Requirements: 2.1, 2.2_
  - [x] 2.2 Implement SAML response parsing
    - Extract SAMLResponse from HTML form
    - Base64 decode and parse XML
    - Extract AWS role attributes from SAML assertion
    - _Requirements: 2.3, 2.4_
  - [x] 2.3 Implement session caching for SAML response
    - Store SAML response in _saml_sessions dict
    - Include expiration timestamp (30 minutes)
    - _Requirements: 2.5_
  - [x] 2.4 Implement error detection and diagnostics
    - Detect invalid credentials from ADFS response
    - Detect no roles found in SAML
    - Return detailed DiagnosticInfo on failure
    - _Requirements: 2.6, 5.1, 5.2, 5.4, 5.5_
  - [x] 2.5 Write property test for SAML parsing
    - **Property 1: SAML Parsing Completeness**
    - **Validates: Requirements 2.3, 2.4**

- [x] 3. Implement pure Python select_adfs_role
  - [x] 3.1 Implement session retrieval and validation
    - Retrieve SAML response from cached session
    - Validate session exists and not expired
    - Find matching role's principal_arn
    - _Requirements: 3.1_
  - [x] 3.2 Implement AWS STS AssumeRoleWithSAML call
    - Use boto3 STS client
    - Call assume_role_with_saml with role_arn, principal_arn, SAMLAssertion
    - Extract credentials from response
    - _Requirements: 3.2, 3.3_
  - [x] 3.3 Implement error handling for STS failures
    - Handle ExpiredTokenException (SAML expired)
    - Handle InvalidIdentityToken
    - Handle AccessDenied
    - _Requirements: 3.4_
  - [x] 3.4 Write property test for credential completeness
    - **Property 3: Credential Completeness**
    - **Validates: Requirements 3.3**

- [x] 4. Implement pure Python _validate_adfs_saml
  - [x] 4.1 Implement ADFS endpoint validation
    - Check endpoint reachability
    - Validate URL is actually an ADFS server (check for federation metadata)
    - _Requirements: 4.2, 5.3_
  - [x] 4.2 Implement credential validation
    - Authenticate with ADFS using pure Python
    - Verify at least one role is available
    - _Requirements: 4.1, 4.3_
  - [x] 4.3 Write property test for ADFS endpoint validation
    - **Property 5: ADFS Endpoint Validation**
    - **Validates: Requirements 4.2, 5.3**

- [x] 5. Checkpoint - Verify no aws-adfs.exe references remain
  - Search codebase for "aws-adfs.exe", "aws_adfs_exe", "_get_aws_adfs_executable"
  - Verify subprocess is not used for ADFS authentication
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Verify backward compatibility
  - [x] 6.1 Verify API compatibility
    - Confirm fetch_adfs_roles accepts same parameters
    - Confirm select_adfs_role accepts same parameters
    - Confirm _validate_adfs_saml accepts same parameters
    - _Requirements: 6.1_
  - [x] 6.2 Verify response compatibility
    - Confirm RoleValidationResponse structure unchanged
    - Confirm ADFSRole structure unchanged
    - _Requirements: 6.2_
  - [x] 6.3 Write integration test for end-to-end flow
    - Test fetch_adfs_roles → select_adfs_role flow
    - Verify credentials are valid
    - _Requirements: 6.3, 6.4_

- [x] 7. Final checkpoint - Ensure all tests pass
  - Run all unit tests
  - Run property-based tests
  - Verify no aws-adfs.exe dependencies
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. **CRITICAL: Rebuild backend executable**
  - The source code is fully converted to pure Python
  - However, the compiled `nexus-installer-backend.exe` in `backend/dist/` is outdated
  - **If running Electron app**: Rebuild the backend executable:
    ```powershell
    cd C:\mycode\nexus\nexus-deployer\backend
    .\venv\Scripts\activate
    pyinstaller backend.spec --clean
    ```
  - **If running in development mode**: Restart the backend server:
    ```powershell
    cd C:\mycode\nexus\nexus-deployer\backend
    .\venv\Scripts\activate
    uvicorn app.main:app --reload --port 8001
    ```
  - The error "aws-adfs not found at ...resources\backend\aws-adfs.exe" indicates an OLD executable is running

## Notes

- All tasks are required for comprehensive implementation
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties
- The implementation should work with existing ADFS configurations without changes

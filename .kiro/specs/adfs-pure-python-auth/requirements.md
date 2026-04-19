# Requirements Document

## Introduction

This feature removes the dependency on the `aws-adfs.exe` executable for ADFS/SAML authentication and replaces it with a pure Python library implementation. The current implementation uses subprocess calls to `aws-adfs.exe` which causes deployment issues when the executable is not bundled correctly with the application. The pure Python approach uses the `requests`, `requests-ntlm`, `beautifulsoup4`, and `boto3` libraries to handle ADFS authentication directly.

## Glossary

- **ADFS**: Active Directory Federation Services - Microsoft's identity federation solution
- **SAML**: Security Assertion Markup Language - XML-based authentication protocol
- **STS**: AWS Security Token Service - AWS service for temporary credentials
- **NTLM**: NT LAN Manager - Windows authentication protocol
- **Principal_ARN**: The ARN of the SAML identity provider in AWS
- **Role_ARN**: The ARN of the IAM role to assume
- **SAML_Response**: Base64-encoded XML assertion from ADFS containing user identity and roles
- **AWSAuthService**: The backend service class handling AWS authentication methods

## Requirements

### Requirement 1: Remove aws-adfs.exe Dependency

**User Story:** As a developer, I want the ADFS authentication to work without requiring aws-adfs.exe, so that the application can be deployed without bundling external executables.

#### Acceptance Criteria

1. THE AWSAuthService SHALL authenticate with ADFS using only Python libraries (requests, requests-ntlm, beautifulsoup4, boto3)
2. THE AWSAuthService SHALL NOT use subprocess calls to aws-adfs or aws-adfs.exe
3. THE AWSAuthService SHALL NOT contain any code that searches for or references aws-adfs.exe
4. WHEN the application starts, THE AWSAuthService SHALL NOT require aws-adfs.exe to be present in any directory

### Requirement 2: ADFS Role Fetching via Pure Python

**User Story:** As a user, I want to fetch available AWS roles from ADFS using my credentials, so that I can select which role to assume.

#### Acceptance Criteria

1. WHEN a user provides ADFS URL, username, and password, THE fetch_adfs_roles method SHALL authenticate with ADFS using NTLM or form-based authentication
2. WHEN NTLM authentication fails, THE fetch_adfs_roles method SHALL fall back to form-based authentication
3. WHEN authentication succeeds, THE fetch_adfs_roles method SHALL parse the SAML response to extract available AWS roles
4. THE fetch_adfs_roles method SHALL return a list of ADFSRole objects containing role_arn, principal_arn, account_id, and role_name
5. THE fetch_adfs_roles method SHALL cache the SAML response in the session for later use in role selection
6. WHEN authentication fails, THE fetch_adfs_roles method SHALL return detailed diagnostic information including error codes and troubleshooting steps

### Requirement 3: ADFS Role Selection via AWS STS

**User Story:** As a user, I want to select an AWS role and obtain temporary credentials, so that I can access AWS resources.

#### Acceptance Criteria

1. WHEN a user selects a role, THE select_adfs_role method SHALL use the cached SAML response from the session
2. THE select_adfs_role method SHALL call AWS STS AssumeRoleWithSAML API with the role_arn, principal_arn, and SAML assertion
3. WHEN STS returns credentials, THE select_adfs_role method SHALL return access_key_id, secret_access_key, and session_token
4. WHEN the SAML assertion has expired, THE select_adfs_role method SHALL return an appropriate error with troubleshooting guidance
5. THE select_adfs_role method SHALL NOT use subprocess calls or aws-adfs.exe

### Requirement 4: ADFS Validation via Pure Python

**User Story:** As a user, I want the system to validate my ADFS credentials, so that I can verify my authentication works before proceeding.

#### Acceptance Criteria

1. WHEN validating ADFS credentials, THE _validate_adfs_saml method SHALL use pure Python libraries
2. THE _validate_adfs_saml method SHALL validate the ADFS endpoint is reachable and is actually an ADFS server
3. THE _validate_adfs_saml method SHALL authenticate and verify at least one AWS role is available
4. THE _validate_adfs_saml method SHALL NOT use subprocess calls or aws-adfs.exe

### Requirement 5: Diagnostic Information

**User Story:** As a user, I want detailed diagnostic information when authentication fails, so that I can troubleshoot issues.

#### Acceptance Criteria

1. WHEN authentication fails, THE AWSAuthService SHALL provide step-by-step diagnostic information
2. THE diagnostic information SHALL include: endpoint URL, reachability status, HTTP status codes, error codes, and error messages
3. WHEN the URL is not an ADFS endpoint, THE AWSAuthService SHALL detect this and provide a specific error message
4. WHEN credentials are invalid, THE AWSAuthService SHALL detect this and provide a specific error message
5. WHEN no roles are found, THE AWSAuthService SHALL detect this and provide a specific error message

### Requirement 6: Backward Compatibility

**User Story:** As a user, I want the new implementation to work with existing ADFS configurations, so that I don't need to change my setup.

#### Acceptance Criteria

1. THE new implementation SHALL accept the same input parameters as the previous implementation (adfs_url, username, password, region)
2. THE new implementation SHALL return the same response structure (RoleValidationResponse with credentials)
3. THE new implementation SHALL support both NTLM and form-based ADFS authentication methods
4. THE new implementation SHALL work with ADFS servers that have self-signed SSL certificates (SSL verification disabled)

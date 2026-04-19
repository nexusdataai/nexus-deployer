/**
 * Enhanced AWS Configuration Component with Multiple Auth Methods
 */
import React, { useState, useEffect } from 'react';
import { useWizard } from '../context/WizardContext';
import { WizardStep } from '../types/wizard';
import { AWSRegion, AWSAuthMethod, SourceAuthMethod, AuthValidationRequest, DiagnosticInfo } from '../types/aws';
import { FrontendService, BackendService } from '../types/architecture';
import { awsApi } from '../services/api';
import IAMPermissionPanel from './IAMPermissionPanel';
import IAMSetupGuideModal from './IAMSetupGuideModal';
import CostEstimationPanel from './CostEstimationPanel';
import IAMTooltip from './IAMTooltip';
import { downloadPolicy, generateFullDeploymentPolicy } from '../utils/policy-generator';

/**
 * Parse diagnostic info embedded in error messages from the backend.
 * Backend embeds diagnostic info in format: "Error message | DIAGNOSTIC_INFO: key=value, key=value"
 */
function parseDiagnosticInfo(
  errorDetail: string,
  endpointUrl: string,
  step: string
): { displayError: string; troubleshooting: string[]; diagnostics: DiagnosticInfo } {
  const diagnostics: DiagnosticInfo = {
    timestamp: new Date().toISOString(),
    step: step,
    auth_method_used: 'adfs_saml',
    endpoint_url: endpointUrl,
  };
  
  let displayError = errorDetail;
  let troubleshooting: string[] = [];
  
  // Check if error contains embedded diagnostic info
  if (typeof errorDetail === 'string' && errorDetail.includes('DIAGNOSTIC_INFO:')) {
    const parts = errorDetail.split('|');
    displayError = parts[0].trim();
    
    // Parse the diagnostic info part
    const diagPart = parts.find(p => p.includes('DIAGNOSTIC_INFO:'));
    if (diagPart) {
      const diagStr = diagPart.replace('DIAGNOSTIC_INFO:', '').trim();
      
      // Parse key=value pairs - handle complex values like steps=[...] and raw_output=...
      // Split on ", " but not within brackets
      let currentKey = '';
      let currentValue = '';
      let bracketDepth = 0;
      let inRawOutput = false;
      
      const pairs: { key: string; value: string }[] = [];
      
      for (let i = 0; i < diagStr.length; i++) {
        const char = diagStr[i];
        
        if (char === '[') bracketDepth++;
        if (char === ']') bracketDepth--;
        
        if (char === '=' && !currentKey && bracketDepth === 0) {
          currentKey = currentValue.trim();
          currentValue = '';
          if (currentKey === 'raw_output') {
            inRawOutput = true;
          }
          continue;
        }
        
        // End of pair - comma followed by space and a key pattern, but not in raw_output
        if (char === ',' && bracketDepth === 0 && !inRawOutput) {
          const remaining = diagStr.substring(i + 1).trim();
          // Check if next part looks like a key (word followed by =)
          if (/^\w+\s*=/.test(remaining)) {
            if (currentKey) {
              pairs.push({ key: currentKey, value: currentValue.trim() });
            }
            currentKey = '';
            currentValue = '';
            continue;
          }
        }
        
        currentValue += char;
      }
      
      // Don't forget the last pair
      if (currentKey) {
        pairs.push({ key: currentKey, value: currentValue.trim() });
      }
      
      for (const { key, value } of pairs) {
        switch (key) {
          case 'endpoint_reachable':
            diagnostics.endpoint_reachable = value === 'true';
            break;
          case 'error_code':
            diagnostics.error_code = value;
            break;
          case 'endpoint_url':
            diagnostics.endpoint_url = value;
            break;
          case 'http_status':
            diagnostics.http_status_code = parseInt(value) || undefined;
            break;
          case 'duration_ms':
            diagnostics.duration_ms = parseInt(value) || undefined;
            break;
          case 'network_error':
            diagnostics.network_error = value;
            break;
          case 'ssl_error':
            diagnostics.ssl_error = value;
            break;
          case 'raw_output':
            diagnostics.raw_output = value;
            break;
          case 'steps':
            // Parse steps array: [step1(status) -> step2(status) -> ...]
            diagnostics.steps = value;
            break;
        }
      }
    }
  }
  
  // Set error message in diagnostics
  diagnostics.error_message = displayError;
  
  // Generate troubleshooting tips based on error code
  const errorCode = diagnostics.error_code || '';
  
  if (errorCode === 'DNS_RESOLUTION_FAILED' || displayError.toLowerCase().includes('dns')) {
    troubleshooting = [
      'DNS resolution failed - the ADFS hostname could not be resolved',
      'Check that the ADFS URL is spelled correctly',
      'Verify you are connected to the correct network (VPN may be required)',
      'Try pinging the ADFS server from command line',
    ];
  } else if (errorCode === 'ENDPOINT_UNREACHABLE' || displayError.toLowerCase().includes('unreachable')) {
    troubleshooting = [
      'The ADFS server is not reachable on port 443',
      'Check network connectivity and firewall rules',
      'Verify you are on the corporate network or VPN',
      'The server may be down or blocking connections',
    ];
  } else if (errorCode === 'SSL_ERROR' || displayError.toLowerCase().includes('ssl') || displayError.toLowerCase().includes('tls')) {
    troubleshooting = [
      'SSL/TLS connection error',
      'The server certificate may be invalid or expired',
      'Check if the ADFS URL is correct',
      'Corporate proxy may be interfering with the connection',
    ];
  } else if (errorCode === 'HTTPS_FAILED') {
    troubleshooting = [
      'HTTPS connection to the ADFS server failed',
      'Verify the ADFS URL is correct',
      'Check if the server is responding',
    ];
  } else if (errorCode === 'NOT_ADFS_ENDPOINT') {
    troubleshooting = [
      'The URL provided is not a valid ADFS endpoint',
      'ADFS URLs typically look like: adfs.yourcompany.com/adfs/ls/idpinitiatedsignon',
      'Contact your IT administrator for the correct ADFS URL',
      'Make sure you are not using a generic website URL',
    ];
  } else if (errorCode === 'INVALID_CREDENTIALS') {
    troubleshooting = [
      'Invalid username or password',
      'Username format should be: DOMAIN\\username (e.g., devfactory\\jsmith)',
      'Verify your password is correct and not expired',
      'Your account may be locked after too many failed attempts',
      'Contact IT support if you continue to have issues',
    ];
  } else if (errorCode === 'ACCOUNT_LOCKED') {
    troubleshooting = [
      'Your account appears to be locked',
      'This usually happens after multiple failed login attempts',
      'Contact your IT administrator to unlock your account',
      'Wait 15-30 minutes and try again',
    ];
  } else if (errorCode === 'MFA_REQUIRED') {
    troubleshooting = [
      'Multi-factor authentication (MFA) is required',
      'This authentication flow does not support MFA',
      'Contact your administrator for alternative authentication methods',
    ];
  } else if (errorCode === 'SAML_ERROR') {
    troubleshooting = [
      'Failed to obtain SAML assertion from ADFS',
      'The ADFS server may not be configured for AWS federation',
      'Contact your administrator to verify AWS trust is configured',
    ];
  } else if (errorCode === 'NO_ROLES_ASSIGNED') {
    troubleshooting = [
      'Your account is authenticated but has no AWS roles assigned',
      'Contact your administrator to assign AWS roles in ADFS',
      'Verify you are using the correct username',
    ];
  } else if (errorCode === 'NO_ROLES_FOUND' || displayError.toLowerCase().includes('no roles')) {
    troubleshooting = [
      'No AWS roles found for this user in ADFS',
      'Contact your administrator to assign AWS roles',
      'Verify you are using the correct username',
    ];
  } else if (errorCode === 'EMPTY_RESPONSE') {
    troubleshooting = [
      'The ADFS server returned an empty response',
      'Authentication may have failed silently',
      'Check your credentials and try again',
      'The ADFS server may be experiencing issues',
    ];
  } else if (errorCode === 'AWS_ADFS_ERROR') {
    troubleshooting = [
      'The aws-adfs tool encountered an error',
      'Check the raw output below for more details',
      'This may be a configuration issue with ADFS',
    ];
  } else {
    // Default troubleshooting
    troubleshooting = [
      'Verify ADFS URL is correct',
      'Check username and password',
      'Ensure user has AWS roles assigned in ADFS',
      'Check network connectivity',
    ];
  }
  
  return { displayError, troubleshooting, diagnostics };
}

const AWSConfigurationEnhanced: React.FC = () => {
  const { state, setAWSConfig, setStep } = useWizard();
  
  // Common state
  const [authMethod, setAuthMethod] = useState<AWSAuthMethod>(AWSAuthMethod.ADFS_SAML);
  const [region, setRegion] = useState(state.awsRegion || ''); // Use region from step 4
  const [regions, setRegions] = useState<AWSRegion[]>([]);
  const [validating, setValidating] = useState(false);
  const [validated, setValidated] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [troubleshooting, setTroubleshooting] = useState<string[]>([]);
  const [diagnostics, setDiagnostics] = useState<any | null>(null);
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  
  // Role ARN state
  const [roleArn, setRoleArn] = useState('');
  
  // Source credentials state for Role ARN assumption
  const [sourceAuthMethod, setSourceAuthMethod] = useState<SourceAuthMethod>(SourceAuthMethod.ACCESS_KEY);
  const [sourceAccessKeyId, setSourceAccessKeyId] = useState('');
  const [sourceSecretAccessKey, setSourceSecretAccessKey] = useState('');
  const [showSourceSecretKey, setShowSourceSecretKey] = useState(false);
  const [sourceProfileName, setSourceProfileName] = useState('');
  
  // Access Key state (direct authentication, not for role assumption)
  const [accessKeyId, setAccessKeyId] = useState('');
  const [secretAccessKey, setSecretAccessKey] = useState('');
  const [showSecretKey, setShowSecretKey] = useState(false);
  
  // AWS Profile state
  const [profileName, setProfileName] = useState('');
  const [profiles, setProfiles] = useState<string[]>([]);
  
  // ADFS state
  const [adfsUrl, setAdfsUrl] = useState('');
  const [adfsUsername, setAdfsUsername] = useState('');
  const [adfsPassword, setAdfsPassword] = useState('');
  const [showAdfsPassword, setShowAdfsPassword] = useState(false);
  
  // ADFS role selection state
  const [adfsRoles, setAdfsRoles] = useState<any[]>([]);
  const [selectedRole, setSelectedRole] = useState<string>('');
  const [sessionId, setSessionId] = useState<string>('');
  const [fetchingRoles, setFetchingRoles] = useState(false);
  const [rolesFetched, setRolesFetched] = useState(false);
  
  // IAM guidance state
  const [showSetupGuide, setShowSetupGuide] = useState(false);
  const [permissionPanelExpanded, setPermissionPanelExpanded] = useState(false);
  
  // Cross-account detection
  const [sourceAccountId, setSourceAccountId] = useState<string | null>(null);
  const [isCrossAccount, setIsCrossAccount] = useState(false);

  // Parse account ID from role ARN
  const parseAccountIdFromArn = (arn: string): string | null => {
    // ARN format: arn:aws:iam::123456789012:role/RoleName
    const match = arn.match(/arn:aws:iam::(\d{12}):role\//);
    return match ? match[1] : null;
  };

  // Detect cross-account scenario when role ARN changes
  useEffect(() => {
    if (roleArn && authMethod === AWSAuthMethod.ROLE_ARN) {
      const targetAccountId = parseAccountIdFromArn(roleArn);
      if (targetAccountId && sourceAccountId && targetAccountId !== sourceAccountId) {
        setIsCrossAccount(true);
      } else {
        setIsCrossAccount(false);
      }
    } else {
      setIsCrossAccount(false);
    }
  }, [roleArn, sourceAccountId, authMethod]);

  useEffect(() => {
    loadRegions();
    loadProfiles();
  }, []);

  const loadRegions = async () => {
    try {
      const data = await awsApi.getRegions();
      setRegions(data);
      // Don't override region if it was already set from step 4
      if (data.length > 0 && !state.awsRegion) {
        setRegion(data[0].code);
      }
    } catch (err) {
      console.error('Error loading regions:', err);
    }
  };

  const loadProfiles = async () => {
    try {
      const data = await awsApi.getProfiles();
      setProfiles(data);
      if (data.length > 0) {
        setProfileName(data[0]);
      }
    } catch (err) {
      console.error('Error loading profiles:', err);
    }
  };

  const handleAuthMethodChange = (method: AWSAuthMethod) => {
    setAuthMethod(method);
    setValidated(false);
    setError(null);
    setTroubleshooting([]);
    setDiagnostics(null);
    setShowDiagnostics(false);
    // Reset ADFS role selection state
    setRolesFetched(false);
    setAdfsRoles([]);
    setSelectedRole('');
    setSessionId('');
  };

  const handleFetchADFSRoles = async () => {
    setError(null);
    setTroubleshooting([]);
    setDiagnostics(null);
    setShowDiagnostics(false);
    
    if (!adfsUrl || !adfsUsername || !adfsPassword) {
      setError('Please enter ADFS URL, username, and password');
      return;
    }
    
    if (!region) {
      setError('Please select a region');
      return;
    }
    
    try {
      setFetchingRoles(true);
      const response = await awsApi.fetchADFSRoles(
        adfsUrl,
        adfsUsername,
        adfsPassword,
        region
      );
      
      setAdfsRoles(response.roles);
      setSessionId(response.session_id);
      setRolesFetched(true);
      
      // Auto-select first role
      if (response.roles.length > 0) {
        setSelectedRole(response.roles[0].role_arn);
      }
    } catch (err: any) {
      const errorDetail = err.response?.data?.detail || 'Failed to fetch ADFS roles';
      
      // Parse diagnostic info embedded in error message from backend
      const parsedDiagnostics = parseDiagnosticInfo(errorDetail, adfsUrl, 'fetch_adfs_roles');
      
      setError(parsedDiagnostics.displayError);
      setTroubleshooting(parsedDiagnostics.troubleshooting);
      setDiagnostics(parsedDiagnostics.diagnostics);
    } finally {
      setFetchingRoles(false);
    }
  };

  const handleSelectADFSRole = async () => {
    setError(null);
    setTroubleshooting([]);
    setDiagnostics(null);
    setShowDiagnostics(false);
    setValidated(false);
    
    if (!selectedRole) {
      setError('Please select a role');
      return;
    }
    
    try {
      setValidating(true);
      const response = await awsApi.selectADFSRole(
        sessionId,
        selectedRole,
        region
      );
      
      console.log('🔍 DEBUG: ADFS role selection response:', response);
      console.log('🔍 DEBUG: session_id from response:', response.session_id);
      
      if (response.valid) {
        setValidated(true);
        setAWSConfig({
          auth_method: AWSAuthMethod.ADFS_SAML,
          region,
          account_id: response.account_id,
          aws_session_id: response.session_id,  // Store the session ID!
          adfs_url: adfsUrl,
          adfs_username: adfsUsername,
          adfs_password: adfsPassword,  // Store password for re-authentication
          role_arn: selectedRole,
        });
        
        console.log('🔍 DEBUG: AWS config set with session_id:', response.session_id);
      } else {
        setError(response.error || 'Failed to authenticate with selected role');
        setTroubleshooting(response.troubleshooting || []);
        // Capture diagnostics from response
        if (response.diagnostics) {
          setDiagnostics(response.diagnostics);
        }
      }
    } catch (err: any) {
      const errorDetail = err.response?.data?.detail || 'Failed to authenticate';
      
      // Parse diagnostic info embedded in error message from backend
      const parsedDiagnostics = parseDiagnosticInfo(errorDetail, adfsUrl, 'select_adfs_role');
      
      setError(parsedDiagnostics.displayError);
      setTroubleshooting(parsedDiagnostics.troubleshooting);
      setDiagnostics(parsedDiagnostics.diagnostics);
    } finally {
      setValidating(false);
    }
  };

  const handleTestCredentials = async () => {
    setError(null);
    setTroubleshooting([]);
    setDiagnostics(null);
    setShowDiagnostics(false);
    setValidated(false);

    // Build validation request based on auth method
    const request: AuthValidationRequest = {
      auth_method: authMethod,
      region,
    };

    // Validate inputs based on auth method
    if (authMethod === AWSAuthMethod.ROLE_ARN) {
      if (!roleArn) {
        setError('Please enter a Role ARN');
        return;
      }
      request.role_arn = roleArn;
      
      // Add source credentials for role assumption
      request.source_auth_method = sourceAuthMethod;
      
      if (sourceAuthMethod === SourceAuthMethod.ACCESS_KEY) {
        if (!sourceAccessKeyId || !sourceSecretAccessKey) {
          setError('Please enter source Access Key credentials to assume the role');
          return;
        }
        request.source_access_key_id = sourceAccessKeyId;
        request.source_secret_access_key = sourceSecretAccessKey;
      } else if (sourceAuthMethod === SourceAuthMethod.AWS_PROFILE) {
        if (!sourceProfileName) {
          setError('Please select a source AWS profile to assume the role');
          return;
        }
        request.source_profile_name = sourceProfileName;
      }
      // For INSTANCE_PROFILE and ENVIRONMENT, no additional credentials needed
      
    } else if (authMethod === AWSAuthMethod.ACCESS_KEY) {
      if (!accessKeyId || !secretAccessKey) {
        setError('Please enter both Access Key ID and Secret Access Key');
        return;
      }
      request.access_key_id = accessKeyId;
      request.secret_access_key = secretAccessKey;
    } else if (authMethod === AWSAuthMethod.AWS_PROFILE) {
      if (!profileName) {
        setError('Please select an AWS profile');
        return;
      }
      request.profile_name = profileName;
    } else if (authMethod === AWSAuthMethod.ADFS_SAML) {
      if (!adfsUrl || !adfsUsername || !adfsPassword) {
        setError('Please enter ADFS URL, username, and password');
        return;
      }
      request.adfs_url = adfsUrl;
      request.adfs_username = adfsUsername;
      request.adfs_password = adfsPassword;
    }

    if (!region) {
      setError('Please select a region');
      return;
    }

    try {
      setValidating(true);
      const response = await awsApi.validateAuth(request);

      if (response.valid) {
        console.log('🔍 DEBUG: Auth response:', response);
        console.log('🔍 DEBUG: session_id from response:', response.session_id);
        
        setValidated(true);
        setSourceAccountId(response.account_id || null); // Store source account for cross-account detection
        setAWSConfig({
          auth_method: authMethod,
          region,
          account_id: response.account_id,
          aws_session_id: response.session_id,
          role_arn: authMethod === AWSAuthMethod.ROLE_ARN ? roleArn : undefined,
          // Store source credentials for Role ARN method
          source_auth_method: authMethod === AWSAuthMethod.ROLE_ARN ? sourceAuthMethod : undefined,
          source_access_key_id: authMethod === AWSAuthMethod.ROLE_ARN && sourceAuthMethod === SourceAuthMethod.ACCESS_KEY ? sourceAccessKeyId : undefined,
          source_secret_access_key: authMethod === AWSAuthMethod.ROLE_ARN && sourceAuthMethod === SourceAuthMethod.ACCESS_KEY ? sourceSecretAccessKey : undefined,
          source_profile_name: authMethod === AWSAuthMethod.ROLE_ARN && sourceAuthMethod === SourceAuthMethod.AWS_PROFILE ? sourceProfileName : undefined,
          access_key_id: authMethod === AWSAuthMethod.ACCESS_KEY ? accessKeyId : undefined,
          secret_access_key: authMethod === AWSAuthMethod.ACCESS_KEY ? secretAccessKey : undefined,
          profile_name: authMethod === AWSAuthMethod.AWS_PROFILE ? profileName : undefined,
          adfs_url: authMethod === AWSAuthMethod.ADFS_SAML ? adfsUrl : undefined,
          adfs_username: authMethod === AWSAuthMethod.ADFS_SAML ? adfsUsername : undefined,
          // Store ADFS password for re-authentication during long-running operations
          adfs_password: authMethod === AWSAuthMethod.ADFS_SAML ? adfsPassword : undefined,
        });
        
        console.log('🔍 DEBUG: AWS config set with session_id:', response.session_id);
      } else {
        setError(response.error || 'Failed to validate credentials');
        setTroubleshooting(response.troubleshooting || []);
        // Capture diagnostics from response
        if (response.diagnostics) {
          setDiagnostics(response.diagnostics);
        }
      }
    } catch (err: any) {
      const errorDetail = err.response?.data?.detail || 'Failed to validate credentials';
      
      // Parse diagnostic info embedded in error message from backend
      const endpointUrl = authMethod === AWSAuthMethod.ADFS_SAML ? adfsUrl : '';
      const parsedDiagnostics = parseDiagnosticInfo(errorDetail, endpointUrl, 'validate_credentials');
      
      setError(parsedDiagnostics.displayError);
      setTroubleshooting(parsedDiagnostics.troubleshooting);
      setDiagnostics(parsedDiagnostics.diagnostics);
    } finally {
      setValidating(false);
    }
  };

  const handleContinue = () => {
    if (validated) {
      // Discovery mode: go to discovery execution
      if (state.discoveryMode) {
        setStep(WizardStep.DISCOVERY_EXECUTION);
        return;
      }
      
      // Check if Pure EKS architecture is selected
      const isPureEKS = state.architectureConfig?.frontendService === FrontendService.EKS && 
                        state.architectureConfig?.backendService === BackendService.EKS;
      
      if (isPureEKS) {
        // For Pure EKS, go to EKS cluster selection (now that we have AWS credentials)
        setStep(WizardStep.EKS_CLUSTER_SELECTION);
      } else {
        // For other architectures, go directly to permission verification
        setStep(WizardStep.PERMISSION_VERIFICATION);
      }
    }
  };

  const renderSourceCredentialsForm = () => {
    return (
      <div className="mt-4 p-4 bg-gray-50 border border-gray-200 rounded-lg">
        <p className="text-sm font-medium text-gray-800 mb-3">
          Source Credentials for Role Assumption
        </p>
        <p className="text-xs text-gray-600 mb-4">
          To assume the target role, you need to provide credentials that have permission to call sts:AssumeRole.
        </p>
        
        {/* Source Auth Method Selection */}
        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Source Credential Type
          </label>
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => {
                setSourceAuthMethod(SourceAuthMethod.ACCESS_KEY);
                setValidated(false);
              }}
              className={`p-3 border-2 rounded-lg text-left text-sm ${
                sourceAuthMethod === SourceAuthMethod.ACCESS_KEY
                  ? 'border-blue-500 bg-blue-50'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <div className="font-medium">Access Keys</div>
              <div className="text-xs text-gray-500">IAM user credentials</div>
            </button>
            <button
              type="button"
              onClick={() => {
                setSourceAuthMethod(SourceAuthMethod.AWS_PROFILE);
                setValidated(false);
              }}
              className={`p-3 border-2 rounded-lg text-left text-sm ${
                sourceAuthMethod === SourceAuthMethod.AWS_PROFILE
                  ? 'border-blue-500 bg-blue-50'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <div className="font-medium">AWS Profile</div>
              <div className="text-xs text-gray-500">CLI profile</div>
            </button>
            <button
              type="button"
              onClick={() => {
                setSourceAuthMethod(SourceAuthMethod.INSTANCE_PROFILE);
                setValidated(false);
              }}
              className={`p-3 border-2 rounded-lg text-left text-sm ${
                sourceAuthMethod === SourceAuthMethod.INSTANCE_PROFILE
                  ? 'border-blue-500 bg-blue-50'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <div className="font-medium">Instance Profile</div>
              <div className="text-xs text-gray-500">EC2/ECS role</div>
            </button>
            <button
              type="button"
              onClick={() => {
                setSourceAuthMethod(SourceAuthMethod.ENVIRONMENT);
                setValidated(false);
              }}
              className={`p-3 border-2 rounded-lg text-left text-sm ${
                sourceAuthMethod === SourceAuthMethod.ENVIRONMENT
                  ? 'border-blue-500 bg-blue-50'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <div className="font-medium">Environment</div>
              <div className="text-xs text-gray-500">Env vars / default</div>
            </button>
          </div>
        </div>
        
        {/* Source Access Key Form */}
        {sourceAuthMethod === SourceAuthMethod.ACCESS_KEY && (
          <>
            <div className="mb-3">
              <label htmlFor="sourceAccessKeyId" className="block text-sm font-medium text-gray-700 mb-1">
                Source Access Key ID <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                id="sourceAccessKeyId"
                value={sourceAccessKeyId}
                onChange={(e) => {
                  setSourceAccessKeyId(e.target.value);
                  setValidated(false);
                  setError(null);
                }}
                placeholder="AKIAIOSFODNN7EXAMPLE"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
              />
            </div>
            <div className="mb-2">
              <label htmlFor="sourceSecretAccessKey" className="block text-sm font-medium text-gray-700 mb-1">
                Source Secret Access Key <span className="text-red-500">*</span>
              </label>
              <div className="relative">
                <input
                  type={showSourceSecretKey ? 'text' : 'password'}
                  id="sourceSecretAccessKey"
                  value={sourceSecretAccessKey}
                  onChange={(e) => {
                    setSourceSecretAccessKey(e.target.value);
                    setValidated(false);
                    setError(null);
                  }}
                  placeholder="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent pr-10 text-sm"
                />
                <button
                  type="button"
                  onClick={() => setShowSourceSecretKey(!showSourceSecretKey)}
                  className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-500 hover:text-gray-700"
                >
                  {showSourceSecretKey ? '👁️' : '👁️‍🗨️'}
                </button>
              </div>
            </div>
          </>
        )}
        
        {/* Source AWS Profile Form */}
        {sourceAuthMethod === SourceAuthMethod.AWS_PROFILE && (
          <div className="mb-2">
            <label htmlFor="sourceProfileName" className="block text-sm font-medium text-gray-700 mb-1">
              Source AWS Profile <span className="text-red-500">*</span>
            </label>
            {profiles.length > 0 ? (
              <select
                id="sourceProfileName"
                value={sourceProfileName}
                onChange={(e) => {
                  setSourceProfileName(e.target.value);
                  setValidated(false);
                }}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
              >
                <option value="">Select a profile...</option>
                {profiles.map((profile) => (
                  <option key={profile} value={profile}>
                    {profile}
                  </option>
                ))}
              </select>
            ) : (
              <div className="text-sm text-gray-600 bg-yellow-50 border border-yellow-200 rounded-lg p-2">
                No AWS profiles found. Run <code className="bg-gray-100 px-1 rounded">aws configure</code> to create one.
              </div>
            )}
          </div>
        )}
        
        {/* Instance Profile Info */}
        {sourceAuthMethod === SourceAuthMethod.INSTANCE_PROFILE && (
          <div className="text-sm text-blue-700 bg-blue-50 border border-blue-200 rounded-lg p-3">
            <p className="font-medium">Instance Profile</p>
            <p className="text-xs mt-1">
              Will use the IAM role attached to this EC2 instance or ECS task.
              Only works when running on AWS infrastructure.
            </p>
          </div>
        )}
        
        {/* Environment Info */}
        {sourceAuthMethod === SourceAuthMethod.ENVIRONMENT && (
          <div className="text-sm text-blue-700 bg-blue-50 border border-blue-200 rounded-lg p-3">
            <p className="font-medium">Environment / Default Credentials</p>
            <p className="text-xs mt-1">
              Will use AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables,
              or the default credential chain (instance profile, config files, etc.).
            </p>
          </div>
        )}
      </div>
    );
  };

  const renderAuthMethodForm = () => {
    switch (authMethod) {
      case AWSAuthMethod.ROLE_ARN:
        return (
          <div className="mb-6">
            <div className="flex items-center justify-between mb-2">
              <IAMTooltip field="roleArn">
                <label htmlFor="roleArn" className="block text-sm font-medium text-gray-700">
                  AWS Role ARN <span className="text-red-500">*</span>
                </label>
              </IAMTooltip>
              <button
                type="button"
                onClick={() => setShowSetupGuide(true)}
                className="text-sm text-blue-600 hover:text-blue-700 flex items-center"
              >
                <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Setup Guide
              </button>
            </div>
            <input
              type="text"
              id="roleArn"
              value={roleArn}
              onChange={(e) => {
                setRoleArn(e.target.value);
                setValidated(false);
                setError(null);
              }}
              placeholder="arn:aws:iam::123456789012:role/MyDeploymentRole"
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <p className="mt-1 text-sm text-gray-500">
              IAM Role ARN that the installer will assume for deployment
            </p>
            
            {/* Source Credentials Section */}
            {renderSourceCredentialsForm()}
            
            {/* Cross-Account Warning */}
            {isCrossAccount && (
              <div className="mt-3 p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
                <div className="flex items-start">
                  <svg className="w-5 h-5 text-yellow-600 mr-2 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                  </svg>
                  <div className="flex-1">
                    <p className="text-sm font-medium text-yellow-800">Cross-Account Deployment Detected</p>
                    <p className="text-xs text-yellow-700 mt-1">
                      The target role is in a different AWS account ({parseAccountIdFromArn(roleArn)}). 
                      You'll need to configure a trust relationship between accounts.
                    </p>
                    <button
                      type="button"
                      onClick={() => setShowSetupGuide(true)}
                      className="mt-2 text-xs text-yellow-800 font-medium hover:text-yellow-900 underline"
                    >
                      View Cross-Account Setup Guide →
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        );

      case AWSAuthMethod.ACCESS_KEY:
        return (
          <>
            <div className="mb-4">
              <label htmlFor="accessKeyId" className="block text-sm font-medium text-gray-700 mb-2">
                AWS Access Key ID <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                id="accessKeyId"
                value={accessKeyId}
                onChange={(e) => {
                  setAccessKeyId(e.target.value);
                  setValidated(false);
                  setError(null);
                }}
                placeholder="AKIAIOSFODNN7EXAMPLE"
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            <div className="mb-6">
              <label htmlFor="secretAccessKey" className="block text-sm font-medium text-gray-700 mb-2">
                AWS Secret Access Key <span className="text-red-500">*</span>
              </label>
              <div className="relative">
                <input
                  type={showSecretKey ? 'text' : 'password'}
                  id="secretAccessKey"
                  value={secretAccessKey}
                  onChange={(e) => {
                    setSecretAccessKey(e.target.value);
                    setValidated(false);
                    setError(null);
                  }}
                  placeholder="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent pr-10"
                />
                <button
                  type="button"
                  onClick={() => setShowSecretKey(!showSecretKey)}
                  className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-500 hover:text-gray-700"
                >
                  {showSecretKey ? '👁️' : '👁️‍🗨️'}
                </button>
              </div>
              <p className="mt-1 text-sm text-gray-500">
                Your secret key will be used securely and not stored
              </p>
            </div>
          </>
        );

      case AWSAuthMethod.AWS_PROFILE:
        return (
          <div className="mb-6">
            <div className="flex items-center justify-between mb-2">
              <label htmlFor="profileName" className="block text-sm font-medium text-gray-700">
                AWS CLI Profile <span className="text-red-500">*</span>
              </label>
              <button
                type="button"
                onClick={() => setShowSetupGuide(true)}
                className="text-sm text-blue-600 hover:text-blue-700 flex items-center"
              >
                <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Setup Guide
              </button>
            </div>
            {profiles.length > 0 ? (
              <select
                id="profileName"
                value={profileName}
                onChange={(e) => {
                  setProfileName(e.target.value);
                  setValidated(false);
                }}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              >
                {profiles.map((profile) => (
                  <option key={profile} value={profile}>
                    {profile}
                  </option>
                ))}
              </select>
            ) : (
              <div className="text-sm text-gray-600 bg-yellow-50 border border-yellow-200 rounded-lg p-3">
                No AWS profiles found. Run <code className="bg-gray-100 px-1 rounded">aws configure</code> to create one.
              </div>
            )}
            <p className="mt-1 text-sm text-gray-500">
              Use credentials from your AWS CLI configuration (~/.aws/credentials)
            </p>
            
            {/* AWS Profile Setup Instructions */}
            <div className="mt-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
              <p className="text-sm font-medium text-blue-800 mb-2">Profile Setup Requirements</p>
              <p className="text-sm text-blue-700 mb-3">
                The AWS profile must be configured with an IAM user or role that has the required deployment permissions.
              </p>
              <div className="space-y-2">
                <div className="flex items-start">
                  <span className="flex items-center justify-center w-5 h-5 bg-blue-100 text-blue-600 rounded-full text-xs font-medium mr-2 mt-0.5">1</span>
                  <span className="text-sm text-blue-700">Create an IAM user with programmatic access or configure SSO</span>
                </div>
                <div className="flex items-start">
                  <span className="flex items-center justify-center w-5 h-5 bg-blue-100 text-blue-600 rounded-full text-xs font-medium mr-2 mt-0.5">2</span>
                  <span className="text-sm text-blue-700">Attach the deployment policy to the user/role</span>
                </div>
                <div className="flex items-start">
                  <span className="flex items-center justify-center w-5 h-5 bg-blue-100 text-blue-600 rounded-full text-xs font-medium mr-2 mt-0.5">3</span>
                  <span className="text-sm text-blue-700">Run <code className="bg-blue-100 px-1 rounded">aws configure --profile &lt;name&gt;</code></span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => downloadPolicy(generateFullDeploymentPolicy(), 'deployment-role-policy.json')}
                className="mt-3 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 flex items-center"
              >
                <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                Download IAM Policy
              </button>
            </div>
          </div>
        );

      case AWSAuthMethod.INSTANCE_PROFILE:
        return (
          <div className="mb-6">
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
              <div className="flex items-center justify-between mb-2">
                <p className="text-sm font-medium text-blue-800">
                  Instance Profile Authentication
                </p>
                <button
                  type="button"
                  onClick={() => setShowSetupGuide(true)}
                  className="text-sm text-blue-600 hover:text-blue-700 flex items-center"
                >
                  <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  Setup Guide
                </button>
              </div>
              <p className="text-sm text-blue-700 mt-2">
                This method uses the IAM role attached to the EC2 instance or ECS task.
                No additional configuration is required in this wizard.
              </p>
              <p className="text-sm text-blue-700 mt-2">
                ⚠️ This only works when running on an AWS EC2 instance or ECS task with an attached IAM role.
              </p>
            </div>
            
            {/* Instance Profile Setup Instructions */}
            <div className="mt-4 p-4 bg-gray-50 border border-gray-200 rounded-lg">
              <p className="text-sm font-medium text-gray-800 mb-2">Instance Profile Requirements</p>
              <p className="text-sm text-gray-600 mb-3">
                The IAM role attached to your EC2 instance or ECS task must have the required deployment permissions.
              </p>
              <div className="space-y-2">
                <div className="flex items-start">
                  <span className="flex items-center justify-center w-5 h-5 bg-gray-200 text-gray-600 rounded-full text-xs font-medium mr-2 mt-0.5">1</span>
                  <span className="text-sm text-gray-700">Create an IAM role for EC2 or ECS task execution</span>
                </div>
                <div className="flex items-start">
                  <span className="flex items-center justify-center w-5 h-5 bg-gray-200 text-gray-600 rounded-full text-xs font-medium mr-2 mt-0.5">2</span>
                  <span className="text-sm text-gray-700">Attach the deployment policy to the role</span>
                </div>
                <div className="flex items-start">
                  <span className="flex items-center justify-center w-5 h-5 bg-gray-200 text-gray-600 rounded-full text-xs font-medium mr-2 mt-0.5">3</span>
                  <span className="text-sm text-gray-700">Attach the role to your EC2 instance or ECS task definition</span>
                </div>
              </div>
              <div className="mt-3 flex space-x-2">
                <button
                  type="button"
                  onClick={() => downloadPolicy(generateFullDeploymentPolicy(), 'deployment-role-policy.json')}
                  className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 flex items-center"
                >
                  <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                  Download IAM Policy
                </button>
              </div>
              
              {/* Trust Policy for Instance Profile */}
              <div className="mt-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
                <p className="text-xs font-medium text-yellow-800 mb-1">Trust Policy Required</p>
                <p className="text-xs text-yellow-700 mb-2">
                  The IAM role must have a trust policy allowing EC2 or ECS to assume it:
                </p>
                <pre className="text-xs bg-gray-900 text-gray-100 p-2 rounded overflow-x-auto">
{`{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Service": ["ec2.amazonaws.com", "ecs-tasks.amazonaws.com"]
    },
    "Action": "sts:AssumeRole"
  }]
}`}
                </pre>
              </div>
            </div>
          </div>
        );

      case AWSAuthMethod.ADFS_SAML:
        return (
          <>
            {/* Step 1: ADFS Credentials */}
            <div className="mb-4">
              <label htmlFor="adfsUrl" className="block text-sm font-medium text-gray-700 mb-2">
                ADFS Endpoint URL <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                id="adfsUrl"
                value={adfsUrl}
                onChange={(e) => {
                  setAdfsUrl(e.target.value);
                  setRolesFetched(false);
                  setValidated(false);
                  setError(null);
                }}
                disabled={rolesFetched}
                placeholder="adfs.example.com/adfs/ls/idpinitiatedsignon"
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100"
              />
              <p className="mt-1 text-sm text-gray-500">
                Enter hostname without https:// (e.g., adfs.devfactory.com/adfs/ls/idpinitiatedsignon)
              </p>
            </div>
            <div className="mb-4">
              <label htmlFor="adfsUsername" className="block text-sm font-medium text-gray-700 mb-2">
                Username <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                id="adfsUsername"
                value={adfsUsername}
                onChange={(e) => {
                  setAdfsUsername(e.target.value);
                  setRolesFetched(false);
                  setValidated(false);
                  setError(null);
                }}
                disabled={rolesFetched}
                placeholder="domain\username"
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100"
              />
            </div>
            <div className="mb-6">
              <label htmlFor="adfsPassword" className="block text-sm font-medium text-gray-700 mb-2">
                Password <span className="text-red-500">*</span>
              </label>
              <div className="relative">
                <input
                  type={showAdfsPassword ? 'text' : 'password'}
                  id="adfsPassword"
                  value={adfsPassword}
                  onChange={(e) => {
                    setAdfsPassword(e.target.value);
                    setRolesFetched(false);
                    setValidated(false);
                    setError(null);
                  }}
                  disabled={rolesFetched}
                  placeholder="••••••••"
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent pr-10 disabled:bg-gray-100"
                />
                <button
                  type="button"
                  onClick={() => setShowAdfsPassword(!showAdfsPassword)}
                  className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-500 hover:text-gray-700"
                  disabled={rolesFetched}
                >
                  {showAdfsPassword ? '👁️' : '👁️‍🗨️'}
                </button>
              </div>
            </div>

            {/* Fetch Roles Button */}
            {!rolesFetched && (
              <div className="mb-6">
                <button
                  onClick={handleFetchADFSRoles}
                  disabled={fetchingRoles || !adfsUrl || !adfsUsername || !adfsPassword || !region}
                  className={`w-full px-6 py-3 rounded-lg font-medium ${
                    fetchingRoles || !adfsUrl || !adfsUsername || !adfsPassword || !region
                      ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                      : 'bg-blue-600 text-white hover:bg-blue-700'
                  }`}
                >
                  {fetchingRoles ? (
                    <span className="flex items-center justify-center">
                      <svg
                        className="animate-spin -ml-1 mr-3 h-5 w-5 text-white"
                        xmlns="http://www.w3.org/2000/svg"
                        fill="none"
                        viewBox="0 0 24 24"
                      >
                        <circle
                          className="opacity-25"
                          cx="12"
                          cy="12"
                          r="10"
                          stroke="currentColor"
                          strokeWidth="4"
                        ></circle>
                        <path
                          className="opacity-75"
                          fill="currentColor"
                          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                        ></path>
                      </svg>
                      Fetching Available Roles...
                    </span>
                  ) : (
                    'Fetch Available Roles'
                  )}
                </button>
              </div>
            )}

            {/* Step 2: Role Selection */}
            {rolesFetched && adfsRoles.length > 0 && (
              <div className="mb-6">
                <div className="flex items-center justify-between mb-3">
                  <label className="block text-sm font-medium text-gray-700">
                    Select AWS Role <span className="text-red-500">*</span>
                  </label>
                  <button
                    onClick={() => {
                      setRolesFetched(false);
                      setAdfsRoles([]);
                      setSelectedRole('');
                      setSessionId('');
                    }}
                    className="text-sm text-blue-600 hover:text-blue-700"
                  >
                    Change Credentials
                  </button>
                </div>
                <div className="space-y-3 max-h-64 overflow-y-auto border border-gray-200 rounded-lg p-4">
                  {adfsRoles.map((role) => (
                    <label
                      key={role.role_arn}
                      className={`flex items-start p-3 border-2 rounded-lg cursor-pointer transition-colors ${
                        selectedRole === role.role_arn
                          ? 'border-blue-500 bg-blue-50'
                          : 'border-gray-200 hover:border-gray-300'
                      }`}
                    >
                      <input
                        type="radio"
                        name="adfsRole"
                        value={role.role_arn}
                        checked={selectedRole === role.role_arn}
                        onChange={(e) => setSelectedRole(e.target.value)}
                        className="mt-1 mr-3"
                      />
                      <div className="flex-1">
                        <div className="font-medium text-gray-900">{role.role_name}</div>
                        <div className="text-sm text-gray-600 mt-1">
                          Account: {role.account_id}
                        </div>
                        {role.account_alias && (
                          <div className="text-sm text-gray-500 mt-1">
                            {role.account_alias}
                          </div>
                        )}
                      </div>
                    </label>
                  ))}
                </div>
                <p className="mt-2 text-sm text-gray-500">
                  {adfsRoles.length} role{adfsRoles.length !== 1 ? 's' : ''} available
                </p>
              </div>
            )}

            <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 mb-4">
              <div className="flex items-center justify-between mb-1">
                <p className="text-sm font-medium text-blue-800">
                  Enterprise SSO Authentication
                </p>
                <button
                  type="button"
                  onClick={() => setShowSetupGuide(true)}
                  className="text-sm text-blue-600 hover:text-blue-700 flex items-center"
                >
                  <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  Setup Guide
                </button>
              </div>
              <p className="text-sm text-blue-700 mt-1">
                {!rolesFetched
                  ? 'Authenticate using your corporate Active Directory credentials through ADFS.'
                  : 'Select the AWS role you want to use for deployment.'}
              </p>
            </div>
            
            {/* ADFS/SAML Setup Instructions */}
            <div className="p-4 bg-gray-50 border border-gray-200 rounded-lg mb-6">
              <p className="text-sm font-medium text-gray-800 mb-2">ADFS/SAML Role Requirements</p>
              <p className="text-sm text-gray-600 mb-3">
                The AWS role you select through ADFS must have the required deployment permissions attached.
              </p>
              <div className="space-y-2">
                <div className="flex items-start">
                  <span className="flex items-center justify-center w-5 h-5 bg-gray-200 text-gray-600 rounded-full text-xs font-medium mr-2 mt-0.5">1</span>
                  <span className="text-sm text-gray-700">Configure ADFS trust with AWS IAM Identity Provider</span>
                </div>
                <div className="flex items-start">
                  <span className="flex items-center justify-center w-5 h-5 bg-gray-200 text-gray-600 rounded-full text-xs font-medium mr-2 mt-0.5">2</span>
                  <span className="text-sm text-gray-700">Create IAM roles with SAML trust relationship</span>
                </div>
                <div className="flex items-start">
                  <span className="flex items-center justify-center w-5 h-5 bg-gray-200 text-gray-600 rounded-full text-xs font-medium mr-2 mt-0.5">3</span>
                  <span className="text-sm text-gray-700">Attach the deployment policy to the SAML role</span>
                </div>
                <div className="flex items-start">
                  <span className="flex items-center justify-center w-5 h-5 bg-gray-200 text-gray-600 rounded-full text-xs font-medium mr-2 mt-0.5">4</span>
                  <span className="text-sm text-gray-700">Map AD groups to AWS roles in ADFS claims</span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => downloadPolicy(generateFullDeploymentPolicy(), 'deployment-role-policy.json')}
                className="mt-3 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 flex items-center"
              >
                <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                Download IAM Policy
              </button>
            </div>
          </>
        );

      default:
        return null;
    }
  };

  return (
    <div className="max-w-4xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">AWS Configuration</h1>
        <p className="text-gray-600">
          Configure AWS credentials and region for deploying {state.selectedCapability?.name} to{' '}
          {state.selectedEnvironment}
        </p>
      </div>

      <div className="bg-white rounded-lg shadow-md p-8 mb-8">
        {/* Authentication Method Selection */}
        <div className="mb-6">
          <label className="block text-sm font-medium text-gray-700 mb-3">
            Authentication Method <span className="text-red-500">*</span>
          </label>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <button
              onClick={() => handleAuthMethodChange(AWSAuthMethod.ADFS_SAML)}
              className={`p-4 border-2 rounded-lg text-left transition-colors ${
                authMethod === AWSAuthMethod.ADFS_SAML
                  ? 'border-blue-500 bg-blue-50'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <div className="font-medium text-gray-900">ADFS/SAML</div>
              <div className="text-sm text-gray-600 mt-1">Federated authentication</div>
            </button>

            <button
              onClick={() => handleAuthMethodChange(AWSAuthMethod.ROLE_ARN)}
              className={`p-4 border-2 rounded-lg text-left transition-colors ${
                authMethod === AWSAuthMethod.ROLE_ARN
                  ? 'border-blue-500 bg-blue-50'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <div className="font-medium text-gray-900">Role ARN</div>
              <div className="text-sm text-gray-600 mt-1">Assume an IAM role</div>
            </button>

            <button
              onClick={() => handleAuthMethodChange(AWSAuthMethod.AWS_PROFILE)}
              className={`p-4 border-2 rounded-lg text-left transition-colors ${
                authMethod === AWSAuthMethod.AWS_PROFILE
                  ? 'border-blue-500 bg-blue-50'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <div className="font-medium text-gray-900">AWS Profile</div>
              <div className="text-sm text-gray-600 mt-1">Use AWS CLI profile</div>
            </button>

            <button
              onClick={() => handleAuthMethodChange(AWSAuthMethod.INSTANCE_PROFILE)}
              className={`p-4 border-2 rounded-lg text-left transition-colors ${
                authMethod === AWSAuthMethod.INSTANCE_PROFILE
                  ? 'border-blue-500 bg-blue-50'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <div className="font-medium text-gray-900">Instance Profile</div>
              <div className="text-sm text-gray-600 mt-1">EC2/ECS IAM role</div>
            </button>

            <button
              onClick={() => handleAuthMethodChange(AWSAuthMethod.ACCESS_KEY)}
              className={`p-4 border-2 rounded-lg text-left transition-colors ${
                authMethod === AWSAuthMethod.ACCESS_KEY
                  ? 'border-blue-500 bg-blue-50'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <div className="font-medium text-gray-900">Access Key</div>
              <div className="text-sm text-gray-600 mt-1">Use Access Key ID & Secret</div>
            </button>
          </div>
        </div>

        {/* Auth Method Specific Form */}
        {renderAuthMethodForm()}

        {/* Region Selection - Pre-selected from Infrastructure Configuration */}
        <div className="mb-6">
          <label htmlFor="region" className="block text-sm font-medium text-gray-700 mb-2">
            AWS Region <span className="text-green-600">(Selected in Step 4)</span>
          </label>
          <div className="w-full px-4 py-3 border-2 border-green-200 bg-green-50 rounded-lg">
            <div className="flex items-center">
              <svg className="w-5 h-5 text-green-600 mr-2" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
              </svg>
              <span className="font-medium text-gray-900">
                {(() => {
                  const regionObj = regions.find(r => r.code === region);
                  if (regionObj) {
                    return `${regionObj.name} (${region})`;
                  }
                  // Fallback region names if API hasn't loaded yet
                  const regionNames: Record<string, string> = {
                    'ap-south-1': 'Asia Pacific (Mumbai)',
                    'ap-northeast-1': 'Asia Pacific (Tokyo)',
                    'ap-northeast-2': 'Asia Pacific (Seoul)',
                    'ap-northeast-3': 'Asia Pacific (Osaka)',
                    'ap-southeast-1': 'Asia Pacific (Singapore)',
                    'ap-southeast-2': 'Asia Pacific (Sydney)',
                    'eu-central-1': 'Europe (Frankfurt)',
                    'eu-west-1': 'Europe (Ireland)',
                    'eu-west-2': 'Europe (London)',
                    'eu-west-3': 'Europe (Paris)',
                    'eu-north-1': 'Europe (Stockholm)',
                    'us-east-1': 'US East (N. Virginia)',
                    'us-east-2': 'US East (Ohio)',
                    'us-west-1': 'US West (N. California)',
                    'us-west-2': 'US West (Oregon)',
                    'ca-central-1': 'Canada (Central)',
                    'sa-east-1': 'South America (São Paulo)',
                  };
                  return `${regionNames[region] || region} (${region})`;
                })()}
              </span>
            </div>
          </div>
          <p className="mt-2 text-sm text-gray-600">
            Region was selected in Infrastructure Configuration. To change it, go back to Step 4.
          </p>
        </div>

        {/* Test Credentials Button (for non-ADFS methods or ADFS with role selected) */}
        {authMethod !== AWSAuthMethod.ADFS_SAML && (
          <div className="mb-6">
            <button
              onClick={handleTestCredentials}
              disabled={validating || !region}
              className={`w-full px-6 py-3 rounded-lg font-medium ${
                validating || !region
                  ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                  : 'bg-blue-600 text-white hover:bg-blue-700'
              }`}
            >
              {validating ? (
                <span className="flex items-center justify-center">
                  <svg
                    className="animate-spin -ml-1 mr-3 h-5 w-5 text-white"
                    xmlns="http://www.w3.org/2000/svg"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    ></circle>
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  ></path>
                  </svg>
                  Testing Credentials...
                </span>
              ) : (
                'Test Credentials'
              )}
            </button>
          </div>
        )}

        {/* Authenticate with Selected Role Button (for ADFS) */}
        {authMethod === AWSAuthMethod.ADFS_SAML && rolesFetched && (
          <div className="mb-6">
            <button
              onClick={handleSelectADFSRole}
              disabled={validating || !selectedRole}
              className={`w-full px-6 py-3 rounded-lg font-medium ${
                validating || !selectedRole
                  ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                  : 'bg-green-600 text-white hover:bg-green-700'
              }`}
            >
              {validating ? (
                <span className="flex items-center justify-center">
                  <svg
                    className="animate-spin -ml-1 mr-3 h-5 w-5 text-white"
                    xmlns="http://www.w3.org/2000/svg"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    ></circle>
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  ></path>
                  </svg>
                  Authenticating...
                </span>
              ) : (
                'Authenticate with Selected Role'
              )}
            </button>
          </div>
        )}

        {/* Validation Success */}
        {validated && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-6">
            <div className="flex items-start">
              <svg
                className="w-5 h-5 text-green-600 mr-3 mt-0.5"
                fill="currentColor"
                viewBox="0 0 20 20"
              >
                <path
                  fillRule="evenodd"
                  d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                  clipRule="evenodd"
                />
              </svg>
              <div>
                <p className="font-medium text-green-800">Credentials Validated Successfully</p>
                <p className="text-sm text-green-700 mt-1">
                  Account ID: {state.awsConfig?.account_id}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Validation Error */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
            <div className="flex items-start">
              <svg
                className="w-5 h-5 text-red-600 mr-3 mt-0.5 flex-shrink-0"
                fill="currentColor"
                viewBox="0 0 20 20"
              >
                <path
                  fillRule="evenodd"
                  d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                  clipRule="evenodd"
                />
              </svg>
              <div className="flex-1">
                <p className="font-medium text-red-800">Validation Failed</p>
                <p className="text-sm text-red-700 mt-1">{error}</p>
                {troubleshooting.length > 0 && (
                  <div className="mt-3">
                    <p className="text-sm font-medium text-red-800 mb-1">Troubleshooting:</p>
                    <ul className="list-disc list-inside space-y-1">
                      {troubleshooting.map((tip, index) => (
                        <li key={index} className="text-sm text-red-700">
                          {tip}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {/* Show Diagnostics Button */}
                {diagnostics && (
                  <div className="mt-3">
                    <button
                      onClick={() => setShowDiagnostics(!showDiagnostics)}
                      className="text-sm text-red-800 font-medium hover:text-red-900 underline flex items-center"
                    >
                      <svg className={`w-4 h-4 mr-1 transition-transform ${showDiagnostics ? 'rotate-90' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                      {showDiagnostics ? 'Hide Diagnostics' : 'Show Diagnostics'}
                    </button>
                    {showDiagnostics && (
                      <div className="mt-2 p-3 bg-red-100 border border-red-300 rounded-lg text-xs font-mono overflow-x-auto">
                        <div className="space-y-1">
                          {diagnostics.timestamp && (
                            <div><span className="text-red-900 font-semibold">Timestamp:</span> <span className="text-red-700">{diagnostics.timestamp}</span></div>
                          )}
                          {diagnostics.step && (
                            <div><span className="text-red-900 font-semibold">Step:</span> <span className="text-red-700">{diagnostics.step}</span></div>
                          )}
                          {diagnostics.auth_method_used && (
                            <div><span className="text-red-900 font-semibold">Auth Method:</span> <span className="text-red-700">{diagnostics.auth_method_used}</span></div>
                          )}
                          {diagnostics.endpoint_url && (
                            <div><span className="text-red-900 font-semibold">Endpoint URL:</span> <span className="text-red-700">{diagnostics.endpoint_url}</span></div>
                          )}
                          {diagnostics.endpoint_reachable !== null && diagnostics.endpoint_reachable !== undefined && (
                            <div><span className="text-red-900 font-semibold">Endpoint Reachable:</span> <span className={diagnostics.endpoint_reachable ? 'text-green-700' : 'text-red-700'}>{diagnostics.endpoint_reachable ? 'Yes' : 'No'}</span></div>
                          )}
                          {diagnostics.http_status_code && (
                            <div><span className="text-red-900 font-semibold">HTTP Status:</span> <span className="text-red-700">{diagnostics.http_status_code}</span></div>
                          )}
                          {diagnostics.error_code && (
                            <div><span className="text-red-900 font-semibold">Error Code:</span> <span className="text-red-700">{diagnostics.error_code}</span></div>
                          )}
                          {diagnostics.error_message && (
                            <div><span className="text-red-900 font-semibold">Error Message:</span> <span className="text-red-700">{diagnostics.error_message}</span></div>
                          )}
                          {diagnostics.network_error && (
                            <div><span className="text-red-900 font-semibold">Network Error:</span> <span className="text-red-700">{diagnostics.network_error}</span></div>
                          )}
                          {diagnostics.ssl_error && (
                            <div><span className="text-red-900 font-semibold">SSL Error:</span> <span className="text-red-700">{diagnostics.ssl_error}</span></div>
                          )}
                          {diagnostics.duration_ms && (
                            <div><span className="text-red-900 font-semibold">Duration:</span> <span className="text-red-700">{diagnostics.duration_ms}ms</span></div>
                          )}
                          {/* Step-by-step diagnostic trail */}
                          {diagnostics.steps && (
                            <div className="mt-2">
                              <span className="text-red-900 font-semibold">Diagnostic Steps:</span>
                              <div className="mt-1 p-2 bg-gray-800 text-gray-100 rounded overflow-x-auto">
                                <div className="flex flex-wrap items-center gap-1">
                                  {diagnostics.steps.replace(/[\[\]]/g, '').split(' -> ').map((step: string, index: number, arr: string[]) => {
                                    const match = step.match(/^(.+)\((.+)\)$/);
                                    const stepName = match ? match[1] : step;
                                    const stepStatus = match ? match[2] : 'unknown';
                                    const isSuccess = stepStatus === 'success';
                                    const isFailed = stepStatus === 'failed';
                                    
                                    return (
                                      <React.Fragment key={index}>
                                        <span className={`px-2 py-0.5 rounded text-xs ${
                                          isSuccess ? 'bg-green-700 text-green-100' : 
                                          isFailed ? 'bg-red-700 text-red-100' : 
                                          'bg-yellow-700 text-yellow-100'
                                        }`}>
                                          {stepName}: {stepStatus}
                                        </span>
                                        {index < arr.length - 1 && (
                                          <span className="text-gray-400">→</span>
                                        )}
                                      </React.Fragment>
                                    );
                                  })}
                                </div>
                              </div>
                            </div>
                          )}
                          {diagnostics.raw_output && (
                            <div className="mt-2">
                              <span className="text-red-900 font-semibold">Raw Output:</span>
                              <pre className="mt-1 p-2 bg-gray-900 text-gray-100 rounded overflow-x-auto whitespace-pre-wrap text-xs max-h-96 overflow-y-auto">{diagnostics.raw_output}</pre>
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* IAM Permission Panel */}
      <div className="bg-white rounded-lg shadow-md p-6 mb-8">
        <IAMPermissionPanel
          expanded={permissionPanelExpanded}
          onToggle={() => setPermissionPanelExpanded(!permissionPanelExpanded)}
        />
      </div>

      {/* Cost Estimation Panel */}
      <div className="bg-white rounded-lg shadow-md p-6 mb-8">
        <CostEstimationPanel
          environment={(state.selectedEnvironment as 'dev' | 'stage' | 'prod') || 'dev'}
          enableNATGateway={state.infrastructureConfig?.infrastructure?.backend?.vpc?.enable_nat_gateway || false}
        />
      </div>

      {/* IAM Setup Guide Modal */}
      <IAMSetupGuideModal
        isOpen={showSetupGuide}
        onClose={() => setShowSetupGuide(false)}
        sourceAccountId={sourceAccountId || state.awsConfig?.account_id}
        targetAccountId={parseAccountIdFromArn(roleArn) || undefined}
        isCrossAccount={isCrossAccount}
      />

      {/* Action Buttons */}
      <div className="flex justify-between">
        <button
          onClick={() => {
            // Discovery mode: go back to capability selection
            if (state.discoveryMode) {
              setStep(WizardStep.CAPABILITY_SELECTION);
              return;
            }
            // If environment was selected, go back to unified environment config (Install flow)
            // If no environment selected, go back to capability selection (Update/Delete flow)
            if (state.selectedEnvironment) {
              setStep(WizardStep.UNIFIED_ENVIRONMENT_CONFIG);
            } else {
              setStep(WizardStep.CAPABILITY_SELECTION);
            }
          }}
          className="px-6 py-3 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50"
        >
          Back
        </button>
        <button
          onClick={handleContinue}
          disabled={!validated}
          className={`px-6 py-3 rounded-lg font-medium ${
            validated
              ? 'bg-blue-600 text-white hover:bg-blue-700'
              : 'bg-gray-300 text-gray-500 cursor-not-allowed'
          }`}
        >
          Continue
        </button>
      </div>
    </div>
  );
};

export default AWSConfigurationEnhanced;

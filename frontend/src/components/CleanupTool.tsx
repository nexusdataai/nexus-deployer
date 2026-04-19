/**
 * Standalone Cleanup Tool Component
 * Allows users to clean up existing installations without going through deployment wizard
 */
import React, { useState, useEffect } from 'react';
import { Capability } from '../types/capability';
import { AWSAuthMethod } from '../types/aws';
import { capabilityApi, awsApi, deploymentApi } from '../services/api';

interface CleanupLog {
  timestamp: string;
  message: string;
  level: 'info' | 'success' | 'warning' | 'error';
}

const CleanupTool: React.FC = () => {
  // Capability selection
  const [capabilities, setCapabilities] = useState<Capability[]>([]);
  const [selectedCapability, setSelectedCapability] = useState<string>('');
  const [environment, setEnvironment] = useState<string>('dev');
  
  // AWS Configuration
  const [authMethod, setAuthMethod] = useState<AWSAuthMethod>(AWSAuthMethod.AWS_PROFILE);
  const [region, setRegion] = useState<string>('ap-southeast-1');
  const [accountId, setAccountId] = useState<string>('');
  const [awsSessionId, setAwsSessionId] = useState<string>('');
  
  // Profile auth
  const [profiles, setProfiles] = useState<string[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<string>('');
  
  // Access key auth
  const [accessKeyId, setAccessKeyId] = useState<string>('');
  const [secretAccessKey, setSecretAccessKey] = useState<string>('');
  
  // Cleanup state
  const [cleaning, setCleaning] = useState(false);
  const [cleanupLogs, setCleanupLogs] = useState<CleanupLog[]>([]);
  const [cleanupComplete, setCleanupComplete] = useState(false);
  const [cleanupSuccess, setCleanupSuccess] = useState(false);

  useEffect(() => {
    loadCapabilities();
    loadProfiles();
  }, []);

  const loadCapabilities = async () => {
    try {
      const data = await capabilityApi.getAll();
      setCapabilities(data);
      if (data.length > 0) {
        setSelectedCapability(data[0].id);
      }
    } catch (err) {
      console.error('Error loading capabilities:', err);
    }
  };

  const loadProfiles = async () => {
    try {
      const data = await awsApi.getProfiles();
      setProfiles(data);
      if (data.length > 0) {
        setSelectedProfile(data[0]);
      }
    } catch (err) {
      console.error('Error loading profiles:', err);
    }
  };

  const addLog = (message: string, level: CleanupLog['level'] = 'info') => {
    setCleanupLogs(prev => [...prev, {
      timestamp: new Date().toLocaleTimeString(),
      message,
      level
    }]);
  };

  const handleAuthenticate = async () => {
    addLog('Authenticating with AWS...', 'info');
    
    try {
      const request: any = {
        auth_method: authMethod,
        region,
      };

      if (authMethod === AWSAuthMethod.AWS_PROFILE) {
        request.profile_name = selectedProfile;
      } else if (authMethod === AWSAuthMethod.ACCESS_KEY) {
        request.access_key_id = accessKeyId;
        request.secret_access_key = secretAccessKey;
      }

      const response = await awsApi.validateAuth(request);

      if (response.valid) {
        setAccountId(response.account_id || '');
        setAwsSessionId(response.session_id || '');
        addLog(`✓ Authenticated successfully (Account: ${response.account_id})`, 'success');
        return true;
      } else {
        addLog(`❌ Authentication failed: ${response.error}`, 'error');
        return false;
      }
    } catch (err: any) {
      addLog(`❌ Authentication error: ${err.message}`, 'error');
      return false;
    }
  };

  const handleCompleteCleanup = async () => {
    if (!selectedCapability || !environment || !region) {
      addLog('❌ Please fill in all required fields', 'error');
      return;
    }

    setCleaning(true);
    setCleanupComplete(false);
    setCleanupLogs([]);

    // Step 1: Authenticate
    const authenticated = await handleAuthenticate();
    if (!authenticated) {
      setCleaning(false);
      return;
    }

    // Step 2: Get capability name
    const capability = capabilities.find(c => c.id === selectedCapability);
    if (!capability) {
      addLog('❌ Capability not found', 'error');
      setCleaning(false);
      return;
    }

    const capabilityName = capability.name.replace(/\s+/g, '-');
    addLog(`Starting complete cleanup for ${capability.name} (${environment})...`, 'info');

    // Step 3: Perform cleanup
    try {
      const response = await deploymentApi.completeCleanup(
        capabilityName,
        environment,
        region,
        accountId,
        awsSessionId
      );

      // Display logs from backend
      if (response.logs && response.logs.length > 0) {
        response.logs.forEach((log: string) => {
          if (log.includes('✓') || log.includes('SUCCESS')) {
            addLog(log, 'success');
          } else if (log.includes('❌') || log.includes('ERROR') || log.includes('Failed')) {
            addLog(log, 'error');
          } else if (log.includes('⚠') || log.includes('WARNING')) {
            addLog(log, 'warning');
          } else {
            addLog(log, 'info');
          }
        });
      }

      // Summary
      if (response.success) {
        addLog(`\n✅ Cleanup completed successfully!`, 'success');
        addLog(`Summary: ${response.summary}`, 'success');
        setCleanupSuccess(true);
      } else {
        addLog(`\n⚠️ Cleanup completed with errors`, 'warning');
        addLog(`Summary: ${response.summary}`, 'warning');
        if (response.errors && response.errors.length > 0) {
          addLog(`Errors encountered: ${response.errors.length}`, 'error');
        }
        setCleanupSuccess(false);
      }

      setCleanupComplete(true);
    } catch (err: any) {
      addLog(`❌ Cleanup failed: ${err.response?.data?.detail || err.message}`, 'error');
      setCleanupSuccess(false);
      setCleanupComplete(true);
    } finally {
      setCleaning(false);
    }
  };

  const getLevelColor = (level: CleanupLog['level']) => {
    switch (level) {
      case 'success': return 'text-green-700';
      case 'warning': return 'text-yellow-700';
      case 'error': return 'text-red-700';
      default: return 'text-gray-700';
    }
  };

  return (
    <div className="max-w-6xl mx-auto p-6">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">Cleanup Tool</h1>
        <p className="text-gray-600">
          Remove existing capability installations from your AWS account
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Configuration Panel */}
        <div className="bg-white rounded-lg shadow-md p-6">
          <h2 className="text-xl font-semibold text-gray-900 mb-4">Configuration</h2>

          {/* Capability Selection */}
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Capability <span className="text-red-500">*</span>
            </label>
            <select
              value={selectedCapability}
              onChange={(e) => setSelectedCapability(e.target.value)}
              disabled={cleaning}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
            >
              {capabilities.map(cap => (
                <option key={cap.id} value={cap.id}>{cap.name}</option>
              ))}
            </select>
          </div>

          {/* Environment Selection */}
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Environment <span className="text-red-500">*</span>
            </label>
            <select
              value={environment}
              onChange={(e) => setEnvironment(e.target.value)}
              disabled={cleaning}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
            >
              <option value="dev">Development</option>
              <option value="test">Test</option>
              <option value="stage">Staging</option>
              <option value="prod">Production</option>
            </select>
          </div>

          {/* Region Selection */}
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              AWS Region <span className="text-red-500">*</span>
            </label>
            <select
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              disabled={cleaning}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
            >
              <option value="ap-southeast-1">Asia Pacific (Singapore)</option>
              <option value="ap-south-1">Asia Pacific (Mumbai)</option>
              <option value="us-east-1">US East (N. Virginia)</option>
              <option value="us-west-2">US West (Oregon)</option>
              <option value="eu-west-1">Europe (Ireland)</option>
            </select>
          </div>

          {/* Auth Method Selection */}
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Authentication Method
            </label>
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={() => setAuthMethod(AWSAuthMethod.AWS_PROFILE)}
                disabled={cleaning}
                className={`p-3 border-2 rounded-lg text-sm ${
                  authMethod === AWSAuthMethod.AWS_PROFILE
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-gray-200'
                } disabled:opacity-50`}
              >
                AWS Profile
              </button>
              <button
                onClick={() => setAuthMethod(AWSAuthMethod.ACCESS_KEY)}
                disabled={cleaning}
                className={`p-3 border-2 rounded-lg text-sm ${
                  authMethod === AWSAuthMethod.ACCESS_KEY
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-gray-200'
                } disabled:opacity-50`}
              >
                Access Key
              </button>
            </div>
          </div>

          {/* Auth Method Fields */}
          {authMethod === AWSAuthMethod.AWS_PROFILE && (
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                AWS Profile
              </label>
              <select
                value={selectedProfile}
                onChange={(e) => setSelectedProfile(e.target.value)}
                disabled={cleaning}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
              >
                {profiles.map(profile => (
                  <option key={profile} value={profile}>{profile}</option>
                ))}
              </select>
            </div>
          )}

          {authMethod === AWSAuthMethod.ACCESS_KEY && (
            <>
              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Access Key ID
                </label>
                <input
                  type="text"
                  value={accessKeyId}
                  onChange={(e) => setAccessKeyId(e.target.value)}
                  disabled={cleaning}
                  placeholder="AKIAIOSFODNN7EXAMPLE"
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
                />
              </div>
              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Secret Access Key
                </label>
                <input
                  type="password"
                  value={secretAccessKey}
                  onChange={(e) => setSecretAccessKey(e.target.value)}
                  disabled={cleaning}
                  placeholder="••••••••"
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
                />
              </div>
            </>
          )}

          {/* Warning Box */}
          <div className="bg-red-50 border-2 border-red-300 rounded-lg p-4 mb-4">
            <div className="flex items-start">
              <svg className="w-6 h-6 text-red-600 mr-2 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
              </svg>
              <div>
                <p className="font-bold text-red-900 text-sm">⚠️ WARNING</p>
                <p className="text-red-800 text-sm mt-1">
                  This will permanently delete ALL resources including stacks, S3 buckets, databases, and configurations.
                  This action cannot be undone.
                </p>
              </div>
            </div>
          </div>

          {/* Cleanup Button */}
          <button
            onClick={handleCompleteCleanup}
            disabled={cleaning || !selectedCapability || !environment || !region}
            className={`w-full px-6 py-3 rounded-lg font-semibold ${
              cleaning || !selectedCapability || !environment || !region
                ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                : 'bg-red-600 text-white hover:bg-red-700'
            }`}
          >
            {cleaning ? (
              <span className="flex items-center justify-center">
                <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Cleaning Up...
              </span>
            ) : (
              '🧹 Start Complete Cleanup'
            )}
          </button>
        </div>

        {/* Logs Panel */}
        <div className="bg-white rounded-lg shadow-md p-6">
          <h2 className="text-xl font-semibold text-gray-900 mb-4">Cleanup Logs</h2>
          
          <div className="bg-gray-900 rounded-lg p-4 h-[600px] overflow-y-auto font-mono text-sm">
            {cleanupLogs.length === 0 ? (
              <p className="text-gray-400">No logs yet. Configure cleanup and click "Start Complete Cleanup".</p>
            ) : (
              cleanupLogs.map((log, index) => (
                <div key={index} className="mb-1">
                  <span className="text-gray-500">[{log.timestamp}]</span>{' '}
                  <span className={getLevelColor(log.level)}>{log.message}</span>
                </div>
              ))
            )}
          </div>

          {cleanupComplete && (
            <div className={`mt-4 p-4 rounded-lg ${
              cleanupSuccess ? 'bg-green-50 border border-green-300' : 'bg-yellow-50 border border-yellow-300'
            }`}>
              <p className={`font-semibold ${cleanupSuccess ? 'text-green-900' : 'text-yellow-900'}`}>
                {cleanupSuccess ? '✅ Cleanup Completed Successfully' : '⚠️ Cleanup Completed with Warnings'}
              </p>
              <p className={`text-sm mt-1 ${cleanupSuccess ? 'text-green-800' : 'text-yellow-800'}`}>
                {cleanupSuccess 
                  ? 'All resources have been removed. You can now deploy fresh infrastructure.'
                  : 'Some resources may require manual cleanup. Check the logs above for details.'}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default CleanupTool;

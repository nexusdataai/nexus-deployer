/**
 * Deployment Execution Component
 * Handles the actual deployment process with real-time progress tracking
 * 
 * Feature: pure-eks-deployment
 * Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7
 */
import React, { useState, useEffect, useRef } from 'react';
import { useWizard } from '../context/WizardContext';
import { WizardStep } from '../types/wizard';
import { deploymentApi, eksApi } from '../services/api';
import { FrontendService, BackendService } from '../types/architecture';

interface ValidationIssue {
  severity: string;
  type: string;
  stack: string;
  description: string;
  action: string;
}

interface ValidationResult {
  success: boolean;
  summary: string;
  issues: ValidationIssue[];
  deployment_order: string[];
}

interface DeploymentPlanStep {
  step: number;
  stack: string;
  type: string;
  action: string;
  reason: string;
}

interface DeploymentPlan {
  total_stacks: number;
  estimated_duration_minutes: number;
  validation_passed: boolean;
  warnings: string[];
  steps: DeploymentPlanStep[];
}

const DeploymentExecution: React.FC = () => {
  const { state, setStep, setDeploymentStatus } = useWizard();
  
  const [isDeploying, setIsDeploying] = useState(false);
  const [deploymentStarted, setDeploymentStarted] = useState(false);
  const [deploymentComplete, setDeploymentComplete] = useState(false);
  const [deploymentId, setDeploymentId] = useState<string | null>(null);
  const [currentStage, setCurrentStage] = useState('');
  const [progress, setProgress] = useState(0);
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastRefreshTime, setLastRefreshTime] = useState<Date | null>(null);
  const logsEndRef = useRef<HTMLDivElement>(null);
  const pollIntervalRef = useRef<number | null>(null);
  
  // Validation state
  const [isValidating, setIsValidating] = useState(false);
  const [validationResult, setValidationResult] = useState<ValidationResult | null>(null);
  const [deploymentPlan, setDeploymentPlan] = useState<DeploymentPlan | null>(null);
  const [validationLogs, setValidationLogs] = useState<string[]>([]);
  const [showValidationDetails, setShowValidationDetails] = useState(false);

  // EKS deployment state
  const [, setEksDeploymentStage] = useState<string>('');
  const [eksResources, setEksResources] = useState<Array<{type: string; name: string; status: string}>>([]);
  const [crName, setCrName] = useState<string>('');

  // Check if this is an EKS deployment
  const isEKSDeployment = state.architectureConfig?.frontendService === FrontendService.EKS ||
                          state.architectureConfig?.backendService === BackendService.EKS;

  // Auto-scroll logs to bottom
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  const formatLogMessage = (log: any): string => {
    const timestamp = new Date(log.timestamp).toLocaleTimeString();
    return `[${timestamp}] ${log.message}`;
  };

  const pollDeploymentStatus = async (depId: string) => {
    try {
      const status = await deploymentApi.getDeploymentStatus(depId);
      
      setProgress(status.progress);
      setCurrentStage(status.message || status.current_stage);
      
      if (status.error) {
        setError(status.error);
      }
      
      // Update wizard context with deployment outputs
      setDeploymentStatus({
        id: depId,
        status: status.status,
        progress: status.progress,
        currentStage: status.current_stage || '',
        error: status.error,
        // Capture deployment outputs
        frontend_url: status.frontend_url,
        backend_url: status.backend_url,
        cognito_user_pool_id: status.cognito_config?.user_pool_id,
        cognito_client_id: status.cognito_config?.client_id,
        cognito_config: status.cognito_config,
        api_domain: status.backend_url ? new URL(status.backend_url).hostname : undefined,
      });
      
      // Get logs
      const logsResponse = await deploymentApi.getDeploymentLogs(depId);
      const formattedLogs = logsResponse.logs.map(formatLogMessage);
      setLogs(formattedLogs);
      
      // Check if deployment is complete
      if (status.status === 'completed') {
        setIsDeploying(false);
        setDeploymentComplete(true);
        if (pollIntervalRef.current) {
          clearInterval(pollIntervalRef.current);
        }
        
        // Don't auto-advance - wait for user to click "Continue" button
        // This allows user to review logs before proceeding
      } else if (status.status === 'failed' || status.status === 'cancelled') {
        setIsDeploying(false);
        if (pollIntervalRef.current) {
          clearInterval(pollIntervalRef.current);
        }
      }
    } catch (err: any) {
      console.error('Error polling deployment status:', err);
    }
  };

  const handleStartDeployment = async () => {
    setIsDeploying(true);
    setDeploymentStarted(true);
    setError(null);
    setProgress(0);

    try {
      // Build deployment request
      console.log('🔍 DEBUG: Building deployment request...');
      console.log('🔍 DEBUG: state.awsConfig:', state.awsConfig);
      console.log('🔍 DEBUG: aws_session_id from state:', state.awsConfig?.aws_session_id);
      console.log('🔍 DEBUG: infrastructureConfig:', state.infrastructureConfig);
      console.log('🔍 DEBUG: updateOptions:', state.updateOptions);
      
      const deploymentRequest = {
        capability_id: state.selectedCapability?.id || '',
        capability_name: state.selectedCapability?.name || '',
        capability_version: state.selectedCapability?.version || '1.0.0',
        environment: state.selectedEnvironment || 'dev',
        region: state.awsConfig?.region || '',
        account_id: state.awsConfig?.account_id || '',
        role_arn: state.awsConfig?.role_arn || null,
        aws_session_id: state.awsConfig?.aws_session_id || null,
        // ADFS credentials for session persistence and re-authentication
        adfs_url: state.awsConfig?.adfs_url || null,
        adfs_username: state.awsConfig?.adfs_username || null,
        adfs_password: state.awsConfig?.adfs_password || null,
        adfs_role_arn: state.awsConfig?.role_arn || null,
        auth_method: state.awsConfig?.auth_method || null,
        frontend_s3_uri: state.selectedCapability?.artifacts?.frontend?.s3_uri || null,
        backend_ecr_uri: state.selectedCapability?.artifacts?.backend?.ecr_uri || null,
        deploy_frontend: state.selectedCapability?.requirements?.frontend || true,
        deploy_backend: state.selectedCapability?.requirements?.backend || true,
        deployment_strategy: state.selectedStrategy || null,
        infrastructure_config: state.infrastructureConfig || null,
        // Update workflow options for Cognito preservation
        // Feature: update-workflow-cognito-preservation
        // Requirements: 2.1, 3.1, 4.1, 9.1
        update_options: state.updateOptions ? {
          preserve_cognito: state.updateOptions.preserveCognito,
          include_cognito_update: state.updateOptions.includeCognitoUpdate,
          require_user_backup: state.updateOptions.requireUserBackup,
          selected_stacks: state.updateOptions.selectedStacks,
          skip_drift_detection: state.updateOptions.skipDriftDetection,
        } : null,
      };
      
      console.log('🔍 DEBUG: Deployment request:', deploymentRequest);
      console.log('🔍 DEBUG: aws_session_id in request:', deploymentRequest.aws_session_id);

      // Start deployment
      const response = await deploymentApi.startDeployment(deploymentRequest);
      setDeploymentId(response.deployment_id);
      
      // Start polling for status
      pollIntervalRef.current = setInterval(() => {
        pollDeploymentStatus(response.deployment_id);
      }, 2000);
      
      // Initial poll
      await pollDeploymentStatus(response.deployment_id);
      
    } catch (err: any) {
      const errorMsg = err.response?.data?.detail || err.message || 'Deployment failed';
      setError(errorMsg);
      setIsDeploying(false);
      
      setDeploymentStatus({
        id: 'deploy-error',
        status: 'failed',
        progress: 0,
        currentStage: 'Failed',
        error: errorMsg,
      });
    }
  };

  /**
   * Handle EKS deployment via Kubernetes Operator
   * Requirements: 8.1, 8.2, 8.3
   */
  const handleStartEKSDeployment = async () => {
    if (!state.eksConfig) {
      setError('EKS configuration is missing');
      return;
    }

    setIsDeploying(true);
    setDeploymentStarted(true);
    setError(null);
    setProgress(0);
    setEksResources([]);

    const addLog = (message: string) => {
      const timestamp = new Date().toLocaleTimeString();
      setLogs(prev => [...prev, `[${timestamp}] ${message}`]);
    };

    try {
      const clusterName = state.eksConfig.clusterName;
      const namespace = state.eksConfig.namespace;
      const awsSessionId = state.awsConfig?.aws_session_id;

      // Stage 1: Check/Deploy Operator (0-30%)
      setEksDeploymentStage('Checking operator status...');
      setCurrentStage('Checking Nexus AI Operator installation');
      addLog('Checking if Nexus AI Operator is installed on cluster...');
      setProgress(5);

      const operatorStatus = await eksApi.checkOperatorStatus(clusterName, awsSessionId || undefined);
      
      if (!operatorStatus.operator_installed || operatorStatus.operator_status !== 'installed') {
        setEksDeploymentStage('Deploying Nexus AI Operator...');
        setCurrentStage('Deploying Nexus AI Operator');
        addLog('Operator not found. Deploying Nexus AI Operator...');
        setProgress(10);

        const deployResult = await eksApi.deployOperator({
          cluster_name: clusterName,
          operator_version: undefined,
        }, awsSessionId || undefined);

        if (!deployResult.success) {
          throw new Error(`Failed to deploy operator: ${deployResult.message}`);
        }

        addLog(`Operator deployed successfully (version: ${deployResult.operator_version})`);
        setProgress(25);

        // Wait for operator to be ready
        addLog('Waiting for operator to become ready...');
        await new Promise(resolve => setTimeout(resolve, 5000));
      } else {
        addLog(`Operator already installed (version: ${operatorStatus.operator_version || 'unknown'})`);
        setProgress(25);
      }

      // Stage 2: Create NexusCapability CR (30-50%)
      setEksDeploymentStage('Creating capability deployment...');
      setCurrentStage('Creating NexusCapability resource');
      addLog('Creating NexusCapability Custom Resource...');
      setProgress(35);

      const capabilityConfig = {
        region: state.awsConfig?.region || 'us-east-1',
        deletionPolicy: state.eksConfig.deletionPolicy,
        frontend: {
          image: state.selectedCapability?.artifacts?.frontend?.ecr_uri || '',
          replicas: state.eksConfig.frontendReplicas,
          resources: state.eksConfig.frontendResources,
        },
        backend: {
          image: state.selectedCapability?.artifacts?.backend?.ecr_uri || '',
          replicas: state.eksConfig.backendReplicas,
          resources: state.eksConfig.backendResources,
        },
        dataServices: {
          dynamodb: { enabled: true },
          s3: { enabled: true },
          glue: { enabled: true },
        },
      };

      const crResult = await eksApi.deployCapability({
        cluster_name: clusterName,
        capability_name: state.selectedCapability?.name || '',
        capability_version: state.selectedCapability?.version || '1.0.0',
        environment: state.selectedEnvironment || 'dev',
        namespace: namespace,
        config: capabilityConfig,
      }, awsSessionId || undefined);

      if (!crResult.success) {
        throw new Error(`Failed to create capability: ${crResult.message}`);
      }

      setCrName(crResult.cr_name);
      addLog(`NexusCapability '${crResult.cr_name}' created in namespace '${namespace}'`);
      setProgress(50);

      // Stage 3: Poll for reconciliation progress (50-100%)
      setEksDeploymentStage('Provisioning resources...');
      setCurrentStage('Operator reconciling resources');
      addLog('Waiting for operator to provision resources...');

      // Poll for CR status
      let attempts = 0;
      const maxAttempts = 60; // 5 minutes with 5s intervals
      
      while (attempts < maxAttempts) {
        await new Promise(resolve => setTimeout(resolve, 5000));
        attempts++;

        try {
          const status = await eksApi.getCapabilityStatus(
            clusterName,
            crResult.cr_name,
            namespace,
            awsSessionId || undefined
          );

          // Update resources display
          if (status.resources && status.resources.length > 0) {
            setEksResources(status.resources);
          }

          // Update progress based on phase
          const phase = status.phase.toLowerCase();
          if (phase === 'provisioning') {
            setProgress(Math.min(50 + attempts, 70));
            setCurrentStage(`Provisioning: ${status.message}`);
            addLog(`[${status.phase}] ${status.message}`);
          } else if (phase === 'deploying') {
            setProgress(Math.min(70 + attempts, 90));
            setCurrentStage(`Deploying: ${status.message}`);
            addLog(`[${status.phase}] ${status.message}`);
          } else if (phase === 'running') {
            setProgress(100);
            setCurrentStage('Deployment complete');
            addLog('✓ All resources provisioned successfully');
            
            // Update deployment status with URLs
            setDeploymentStatus({
              id: crResult.cr_name,
              status: 'completed',
              progress: 100,
              currentStage: 'Complete',
              frontend_url: status.frontend_url || undefined,
              backend_url: status.backend_url || undefined,
            });

            if (status.frontend_url) {
              addLog(`Frontend URL: ${status.frontend_url}`);
            }
            if (status.backend_url) {
              addLog(`Backend URL: ${status.backend_url}`);
            }

            setIsDeploying(false);
            setDeploymentComplete(true);
            return;
          } else if (phase === 'failed') {
            throw new Error(status.message || 'Deployment failed');
          }
        } catch (pollErr: any) {
          // Log but continue polling
          console.warn('Status poll error:', pollErr);
        }
      }

      // Timeout
      throw new Error('Deployment timed out waiting for resources to be ready');

    } catch (err: any) {
      const errorMsg = err.response?.data?.detail || err.message || 'EKS deployment failed';
      setError(errorMsg);
      setIsDeploying(false);
      
      setDeploymentStatus({
        id: crName || 'eks-deploy-error',
        status: 'failed',
        progress,
        currentStage: 'Failed',
        error: errorMsg,
      });
    }
  };

  const handleCancel = async () => {
    if (isDeploying && deploymentId) {
      if (window.confirm('Are you sure you want to cancel the deployment?')) {
        try {
          await deploymentApi.cancelDeployment(deploymentId);
          setIsDeploying(false);
          setError('Deployment cancelled by user');
          
          if (pollIntervalRef.current) {
            clearInterval(pollIntervalRef.current);
          }
          
          setDeploymentStatus({
            id: deploymentId,
            status: 'cancelled',
            progress,
            currentStage: 'Cancelled',
          });
        } catch (err: any) {
          console.error('Error cancelling deployment:', err);
        }
      }
    } else {
      setStep(WizardStep.PERMISSION_VERIFICATION);
    }
  };

  const handleRetry = () => {
    setError(null);
    setLogs([]);
    setProgress(0);
    setCurrentStage('');
    setDeploymentId(null);
    setDeploymentComplete(false);
    
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
    }
    
    // Use the correct deployment method based on architecture
    if (isEKSDeployment) {
      handleStartEKSDeployment();
    } else {
      handleStartDeployment();
    }
  };

  const handleContinue = () => {
    // User has reviewed logs and wants to proceed to next step
    setStep(WizardStep.POST_VERIFICATION);
  };

  const getProgressColor = () => {
    if (error) return 'bg-red-600';
    if (progress === 100) return 'bg-green-600';
    return 'bg-blue-600';
  };

  const handleDownloadLogs = () => {
    // Create log content
    const logContent = logs.join('\n');
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const filename = `deployment-logs-${state.selectedCapability?.name}-${state.selectedEnvironment}-${timestamp}.txt`;
    
    // Create blob and download
    const blob = new Blob([logContent], { type: 'text/plain' });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(url);
  };

  const handleCopyLogs = () => {
    const logContent = logs.join('\n');
    navigator.clipboard.writeText(logContent).then(() => {
      // Could add a toast notification here
      alert('Logs copied to clipboard!');
    }).catch(err => {
      console.error('Failed to copy logs:', err);
      alert('Failed to copy logs to clipboard');
    });
  };

  const handleManualRefresh = async () => {
    if (!deploymentId || isRefreshing) return;
    
    setIsRefreshing(true);
    try {
      await pollDeploymentStatus(deploymentId);
      setLastRefreshTime(new Date());
    } catch (err) {
      console.error('Manual refresh failed:', err);
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleRestartPolling = () => {
    if (!deploymentId) return;
    
    // Clear existing interval
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
    }
    
    // Restart polling
    pollIntervalRef.current = setInterval(() => {
      pollDeploymentStatus(deploymentId);
    }, 2000);
    
    // Immediate refresh
    handleManualRefresh();
  };

  const handleDryRun = async () => {
    setIsValidating(true);
    setValidationResult(null);
    setDeploymentPlan(null);
    setValidationLogs([]);
    setError(null);

    try {
      const validationRequest = {
        capability_id: state.selectedCapability?.id || '',
        capability_name: state.selectedCapability?.name || '',
        capability_version: state.selectedCapability?.version || '1.0.0',
        environment: state.selectedEnvironment || 'dev',
        region: state.awsConfig?.region || '',
        account_id: state.awsConfig?.account_id || '',
        role_arn: state.awsConfig?.role_arn || null,
        aws_session_id: state.awsConfig?.aws_session_id || null,
        deploy_frontend: state.selectedCapability?.requirements?.frontend || true,
        deploy_backend: state.selectedCapability?.requirements?.backend || true,
      };

      const response = await deploymentApi.validateDeployment(validationRequest);
      
      setValidationResult(response.validation_result);
      setDeploymentPlan(response.deployment_plan);
      setValidationLogs(response.logs || []);
      setShowValidationDetails(true);
      
    } catch (err: any) {
      const errorMsg = err.response?.data?.detail || err.message || 'Validation failed';
      setError(errorMsg);
    } finally {
      setIsValidating(false);
    }
  };

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'error': return 'text-red-600 bg-red-50 border-red-200';
      case 'warning': return 'text-yellow-600 bg-yellow-50 border-yellow-200';
      default: return 'text-blue-600 bg-blue-50 border-blue-200';
    }
  };

  const getActionIcon = (action: string) => {
    switch (action) {
      case 'create': return '🆕';
      case 'update': return '🔄';
      case 'skip': return '⏭️';
      default: return '❓';
    }
  };

  return (
    <div className="max-w-6xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">Deployment Execution</h1>
        <p className="text-gray-600">
          Deploy {state.selectedCapability?.name} to your AWS environment
        </p>
      </div>

      {/* Validation Results */}
      {showValidationDetails && validationResult && (
        <div className="bg-white rounded-lg shadow-md p-6 mb-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold text-gray-900">
              Validation Results
            </h2>
            <button
              onClick={() => setShowValidationDetails(false)}
              className="text-gray-400 hover:text-gray-600"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* Validation Status */}
          <div className={`p-4 rounded-lg mb-4 ${validationResult.success ? 'bg-green-50 border border-green-200' : 'bg-red-50 border border-red-200'}`}>
            <div className="flex items-center">
              {validationResult.success ? (
                <svg className="w-6 h-6 text-green-600 mr-3" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                </svg>
              ) : (
                <svg className="w-6 h-6 text-red-600 mr-3" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                </svg>
              )}
              <div>
                <p className={`font-medium ${validationResult.success ? 'text-green-800' : 'text-red-800'}`}>
                  {validationResult.success ? 'Validation Passed' : 'Validation Failed'}
                </p>
                <p className={`text-sm ${validationResult.success ? 'text-green-700' : 'text-red-700'}`}>
                  {validationResult.summary}
                </p>
              </div>
            </div>
          </div>

          {/* Validation Issues */}
          {validationResult.issues && validationResult.issues.length > 0 && (
            <div className="mb-4">
              <h3 className="text-sm font-medium text-gray-700 mb-2">Issues Found</h3>
              <div className="space-y-2">
                {validationResult.issues.map((issue, index) => (
                  <div key={index} className={`p-3 rounded-lg border ${getSeverityColor(issue.severity)}`}>
                    <div className="flex items-start">
                      <span className="font-medium mr-2">
                        {issue.severity === 'error' ? '❌' : '⚠️'}
                      </span>
                      <div className="flex-1">
                        <p className="font-medium">{issue.description}</p>
                        <p className="text-sm mt-1">Stack: {issue.stack}</p>
                        <p className="text-sm mt-1">Suggested action: {issue.action}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Deployment Plan */}
          {deploymentPlan && (
            <div className="mb-4">
              <h3 className="text-sm font-medium text-gray-700 mb-2">Deployment Plan</h3>
              <div className="bg-gray-50 rounded-lg p-4">
                <div className="grid grid-cols-2 gap-4 mb-4">
                  <div>
                    <p className="text-sm text-gray-500">Total Stacks</p>
                    <p className="text-lg font-medium">{deploymentPlan.total_stacks}</p>
                  </div>
                  <div>
                    <p className="text-sm text-gray-500">Estimated Duration</p>
                    <p className="text-lg font-medium">{deploymentPlan.estimated_duration_minutes} minutes</p>
                  </div>
                </div>
                
                <div className="space-y-2">
                  {deploymentPlan.steps.map((step) => (
                    <div key={step.step} className="flex items-center p-2 bg-white rounded border">
                      <span className="w-8 h-8 flex items-center justify-center bg-blue-100 text-blue-800 rounded-full text-sm font-medium mr-3">
                        {step.step}
                      </span>
                      <span className="mr-2">{getActionIcon(step.action)}</span>
                      <div className="flex-1">
                        <p className="font-medium text-sm">{step.stack}</p>
                        <p className="text-xs text-gray-500">{step.type} - {step.reason}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Validation Logs */}
          {validationLogs.length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-gray-700 mb-2">Validation Logs</h3>
              <div className="bg-gray-900 rounded-lg p-4 h-48 overflow-y-auto font-mono text-xs">
                {validationLogs.map((log, index) => (
                  <div key={index} className="text-gray-300 mb-1">{log}</div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Deployment Summary */}
      {!deploymentStarted && (
        <div className="bg-white rounded-lg shadow-md p-6 mb-6">
          <h2 className="text-xl font-semibold text-gray-900 mb-4">Ready to Deploy</h2>
          
          <div className="grid grid-cols-2 gap-6">
            <div>
              <h3 className="text-sm font-medium text-gray-500 mb-2">Capability</h3>
              <p className="text-lg font-medium text-gray-900">
                {state.selectedCapability?.name}
              </p>
              <p className="text-sm text-gray-600">{state.selectedCapability?.version}</p>
            </div>

            <div>
              <h3 className="text-sm font-medium text-gray-500 mb-2">Environment</h3>
              <p className="text-lg font-medium text-gray-900">
                {state.selectedEnvironment}
              </p>
            </div>

            <div>
              <h3 className="text-sm font-medium text-gray-500 mb-2">AWS Region</h3>
              <p className="text-lg font-medium text-gray-900">{state.awsConfig?.region}</p>
            </div>

            <div>
              <h3 className="text-sm font-medium text-gray-500 mb-2">AWS Account</h3>
              <p className="text-lg font-medium text-gray-900">
                {state.awsConfig?.account_id}
              </p>
            </div>

            {/* EKS-specific info */}
            {isEKSDeployment && state.eksConfig && (
              <>
                <div>
                  <h3 className="text-sm font-medium text-gray-500 mb-2">EKS Cluster</h3>
                  <p className="text-lg font-medium text-gray-900">{state.eksConfig.clusterName}</p>
                </div>
                <div>
                  <h3 className="text-sm font-medium text-gray-500 mb-2">Namespace</h3>
                  <p className="text-lg font-medium text-gray-900">{state.eksConfig.namespace}</p>
                </div>
              </>
            )}
          </div>

          {state.awsConfig?.role_arn && (
            <div className="mt-4">
              <h3 className="text-sm font-medium text-gray-500 mb-2">IAM Role</h3>
              <p className="text-sm text-gray-700 break-all">{state.awsConfig.role_arn}</p>
            </div>
          )}

          {/* EKS deployment info box */}
          {isEKSDeployment && (
            <div className="mt-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
              <div className="flex items-start">
                <svg className="w-5 h-5 text-blue-600 mr-3 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
                </svg>
                <div>
                  <p className="text-sm font-medium text-blue-900">Kubernetes Operator Deployment</p>
                  <p className="text-sm text-blue-700 mt-1">
                    This deployment uses the Nexus AI Kubernetes Operator to manage resources.
                    The operator will provision AWS data services (DynamoDB, S3, Glue) and deploy
                    your application to the EKS cluster.
                  </p>
                  <div className="mt-2 text-xs text-blue-600">
                    <span className="inline-flex items-center">
                      <span className="w-2 h-2 bg-blue-500 rounded-full mr-1"></span>
                      Frontend replicas: {state.eksConfig?.frontendReplicas || 2}
                    </span>
                    <span className="inline-flex items-center ml-4">
                      <span className="w-2 h-2 bg-blue-500 rounded-full mr-1"></span>
                      Backend replicas: {state.eksConfig?.backendReplicas || 2}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )}

          <div className="mt-6 p-4 bg-green-50 border border-green-200 rounded-lg">
            <div className="flex items-start">
              <svg
                className="w-5 h-5 text-green-600 mr-3 mt-0.5 flex-shrink-0"
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
                <p className="text-sm font-medium text-green-900">
                  All prerequisites verified ✓
                </p>
                <p className="text-sm text-green-700 mt-1">
                  Estimated deployment time: {state.selectedCapability?.estimated_deployment_time || 15} minutes
                </p>
                <p className="text-sm text-green-700 mt-1">
                  {isEKSDeployment 
                    ? 'Click "Deploy to EKS" to begin deploying via the Kubernetes Operator.'
                    : 'Click "Start Deployment" to begin creating AWS resources in your account.'}
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Deployment Progress */}
      {deploymentStarted && (
        <div className="bg-white rounded-lg shadow-md p-6 mb-6">
          <div className="mb-4">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-xl font-semibold text-gray-900">
                {isDeploying ? 'Deployment in Progress' : error ? 'Deployment Failed' : 'Deployment Complete'}
              </h2>
              <span className="text-sm font-medium text-gray-600">{progress}%</span>
            </div>
            
            <div className="w-full bg-gray-200 rounded-full h-3">
              <div
                className={`h-3 rounded-full transition-all duration-500 ${getProgressColor()}`}
                style={{ width: `${progress}%` }}
              />
            </div>
            
            {currentStage && (
              <p className="text-sm text-gray-600 mt-2">
                {isDeploying && (
                  <span className="inline-block animate-pulse mr-2">●</span>
                )}
                {currentStage}
              </p>
            )}
          </div>

          {/* EKS Resources Panel - shown during EKS deployment */}
          {isEKSDeployment && eksResources.length > 0 && (
            <div className="mb-4 p-4 bg-gray-50 border border-gray-200 rounded-lg">
              <h3 className="text-sm font-medium text-gray-700 mb-3">Provisioned Resources</h3>
              <div className="grid grid-cols-2 gap-2">
                {eksResources.map((resource, index) => (
                  <div key={index} className="flex items-center text-sm">
                    <span className={`w-2 h-2 rounded-full mr-2 ${
                      resource.status === 'created' ? 'bg-green-500' :
                      resource.status === 'failed' ? 'bg-red-500' : 'bg-yellow-500'
                    }`}></span>
                    <span className="text-gray-600">{resource.type}:</span>
                    <span className="ml-1 text-gray-900 truncate">{resource.name}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Error Display */}
          {error && (
            <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg">
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
                <div>
                  <p className="font-medium text-red-800">Deployment Error</p>
                  <p className="text-sm text-red-700 mt-1">{error}</p>
                </div>
              </div>
            </div>
          )}

          {/* Deployment Logs */}
          <div className="mt-4">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-3">
                <h3 className="text-sm font-medium text-gray-700">Deployment Logs</h3>
                {lastRefreshTime && (
                  <span className="text-xs text-gray-500">
                    Last refresh: {lastRefreshTime.toLocaleTimeString()}
                  </span>
                )}
              </div>
              <div className="flex gap-2">
                {/* Refresh Buttons - shown during deployment */}
                {isDeploying && (
                  <>
                    <button
                      onClick={handleManualRefresh}
                      disabled={isRefreshing}
                      className="px-3 py-1 text-xs font-medium text-green-700 bg-green-100 border border-green-300 rounded hover:bg-green-200 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                      title="Refresh logs"
                    >
                      <svg className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                      </svg>
                      {isRefreshing ? 'Refreshing...' : 'Refresh'}
                    </button>
                    <button
                      onClick={handleRestartPolling}
                      className="px-3 py-1 text-xs font-medium text-orange-700 bg-orange-100 border border-orange-300 rounded hover:bg-orange-200 flex items-center gap-1"
                      title="Restart auto-polling"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      Restart Polling
                    </button>
                  </>
                )}
                <button
                  onClick={handleCopyLogs}
                  disabled={logs.length === 0}
                  className="px-3 py-1 text-xs font-medium text-gray-700 bg-white border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                  title="Copy logs to clipboard"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                  </svg>
                  Copy
                </button>
                <button
                  onClick={handleDownloadLogs}
                  disabled={logs.length === 0}
                  className="px-3 py-1 text-xs font-medium text-white bg-blue-600 rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                  title="Download logs as text file"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                  Download
                </button>
              </div>
            </div>
            <div className="bg-gray-900 rounded-lg p-4 h-96 overflow-y-auto font-mono text-sm">
              {logs.map((log, index) => (
                <div key={index} className="text-gray-300 mb-1">
                  {log}
                </div>
              ))}
              <div ref={logsEndRef} />
            </div>
          </div>

          {/* Success Message - shown when deployment completes */}
          {deploymentComplete && !error && (
            <div className="mt-4 p-4 bg-green-50 border border-green-200 rounded-lg">
              <div className="flex items-start">
                <svg
                  className="w-6 h-6 text-green-600 mr-3 mt-0.5 flex-shrink-0"
                  fill="currentColor"
                  viewBox="0 0 20 20"
                >
                  <path
                    fillRule="evenodd"
                    d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                    clipRule="evenodd"
                  />
                </svg>
                <div className="flex-1">
                  <p className="font-medium text-green-900">Deployment Successful!</p>
                  <p className="text-sm text-green-700 mt-1">
                    All stacks have been deployed successfully. Review the logs above if needed, then click "Continue to Verification" to proceed.
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex justify-between">
        <button
          onClick={handleCancel}
          className={`px-6 py-3 rounded-lg font-medium ${
            isDeploying 
              ? 'bg-red-600 text-white hover:bg-red-700' 
              : 'border border-gray-300 text-gray-700 hover:bg-gray-50'
          }`}
        >
          {isDeploying ? 'Cancel Deployment' : 'Back'}
        </button>
        
        <div className="flex gap-3">
          {error && !isDeploying && (
            <button
              onClick={handleRetry}
              className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium"
            >
              Retry Deployment
            </button>
          )}

          {/* Continue button - shown when deployment completes successfully */}
          {deploymentComplete && !error && !isDeploying && (
            <button
              onClick={handleContinue}
              className="px-6 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 font-medium flex items-center"
            >
              <svg
                className="w-5 h-5 mr-2"
                fill="currentColor"
                viewBox="0 0 20 20"
              >
                <path
                  fillRule="evenodd"
                  d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-4.293-4.293a1 1 0 010-1.414z"
                  clipRule="evenodd"
                />
              </svg>
              Continue to Verification
            </button>
          )}
          
          {!deploymentStarted && (
            <>
              <button
                onClick={handleDryRun}
                disabled={isValidating || isEKSDeployment}
                className="px-6 py-3 border border-blue-600 text-blue-600 rounded-lg hover:bg-blue-50 font-medium flex items-center disabled:opacity-50"
                title={isEKSDeployment ? 'Dry run not available for EKS deployments' : ''}
              >
                {isValidating ? (
                  <>
                    <svg className="animate-spin w-5 h-5 mr-2" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    Validating...
                  </>
                ) : (
                  <>
                    <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    Dry Run
                  </>
                )}
              </button>
              <button
                onClick={isEKSDeployment ? handleStartEKSDeployment : handleStartDeployment}
                disabled={isValidating}
                className="px-6 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 font-medium flex items-center disabled:opacity-50"
              >
                <svg
                  className="w-5 h-5 mr-2"
                  fill="currentColor"
                  viewBox="0 0 20 20"
                >
                  <path
                    fillRule="evenodd"
                    d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z"
                    clipRule="evenodd"
                  />
                </svg>
                {isEKSDeployment ? 'Deploy to EKS' : 'Start Deployment'}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default DeploymentExecution;

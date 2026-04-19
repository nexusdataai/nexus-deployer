/**
 * Deletion Execution Component
 * Handles the deletion of all stacks for a capability with real-time log streaming
 */
import React, { useState, useEffect, useRef } from 'react';
import { useWizard } from '../context/WizardContext';
import { WizardStep } from '../types/wizard';
import { deploymentApi } from '../services/api';

interface DeletionLog {
  timestamp: string;
  message: string;
  level: 'info' | 'success' | 'warning' | 'error';
}

const DeletionExecution: React.FC = () => {
  const { state, setStep, setDeleteMode } = useWizard();
  
  const [deleting, setDeleting] = useState(false);
  const [deletionComplete, setDeletionComplete] = useState(false);
  const [deletionSuccess, setDeletionSuccess] = useState(false);
  const [deletionLogs, setDeletionLogs] = useState<DeletionLog[]>([]);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [copySuccess, setCopySuccess] = useState(false);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [progress, setProgress] = useState(0);
  const [currentStage, setCurrentStage] = useState('');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastRefreshTime, setLastRefreshTime] = useState<Date | null>(null);
  const logsEndRef = useRef<HTMLDivElement>(null);
  const pollIntervalRef = useRef<number | null>(null);
  const currentDeletionIdRef = useRef<string | null>(null);

  // Auto-scroll logs
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [deletionLogs]);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  const getLevelFromMessage = (message: string): DeletionLog['level'] => {
    if (message.includes('✓') || message.includes('SUCCESS') || message.includes('Deleted')) {
      return 'success';
    } else if (message.includes('❌') || message.includes('ERROR') || message.includes('Failed')) {
      return 'error';
    } else if (message.includes('⚠') || message.includes('WARNING') || message.includes('Could not')) {
      return 'warning';
    }
    return 'info';
  };

  // Format logs as text for copy/download
  const getLogsAsText = (): string => {
    const header = [
      `Deletion Log - ${state.selectedCapability?.name}`,
      `Environment: ${state.selectedEnvironment}`,
      `Region: ${state.awsConfig?.region}`,
      `Account: ${state.awsConfig?.account_id}`,
      `Date: ${new Date().toISOString()}`,
      '='.repeat(60),
      ''
    ].join('\n');

    const logLines = deletionLogs.map(log => 
      `[${log.timestamp}] [${log.level.toUpperCase()}] ${log.message}`
    ).join('\n');

    return header + logLines;
  };

  const handleCopyLogs = async () => {
    try {
      await navigator.clipboard.writeText(getLogsAsText());
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } catch (err) {
      console.error('Failed to copy logs:', err);
    }
  };

  const handleDownloadLogs = () => {
    const content = getLogsAsText();
    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const capName = state.selectedCapability?.name?.toLowerCase().replace(/\s+/g, '-') || 'capability';
    a.download = `deletion-log-${capName}-${state.selectedEnvironment}-${timestamp}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleManualRefresh = async () => {
    if (!currentDeletionIdRef.current || isRefreshing) return;
    
    setIsRefreshing(true);
    try {
      await pollDeletionStatus(currentDeletionIdRef.current);
      setLastRefreshTime(new Date());
    } catch (err) {
      console.error('Manual refresh failed:', err);
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleRestartPolling = () => {
    if (!currentDeletionIdRef.current) return;
    
    // Clear existing interval
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
    }
    
    // Restart polling
    pollIntervalRef.current = window.setInterval(() => {
      pollDeletionStatus(currentDeletionIdRef.current!);
    }, 2000);
    
    // Immediate refresh
    handleManualRefresh();
  };

  const addLog = (message: string, level: DeletionLog['level'] = 'info') => {
    setDeletionLogs(prev => [...prev, {
      timestamp: new Date().toLocaleTimeString(),
      message,
      level
    }]);
  };

  const pollDeletionStatus = async (delId: string) => {
    try {
      // Get status
      const status = await deploymentApi.getDeletionStatus(delId);
      setProgress(status.progress);
      setCurrentStage(status.message);
      
      // Get logs
      const logsResponse = await deploymentApi.getDeletionLogs(delId);
      
      // Convert backend logs to our format
      const newLogs: DeletionLog[] = logsResponse.logs.map((log: { timestamp: string; message: string }) => ({
        timestamp: new Date(log.timestamp).toLocaleTimeString(),
        message: log.message,
        level: getLevelFromMessage(log.message)
      }));
      
      setDeletionLogs(newLogs);
      
      // Check if complete
      if (status.status === 'completed') {
        setDeleting(false);
        setDeletionComplete(true);
        setDeletionSuccess(true);
        if (pollIntervalRef.current) {
          clearInterval(pollIntervalRef.current);
        }
      } else if (status.status === 'failed') {
        setDeleting(false);
        setDeletionComplete(true);
        setDeletionSuccess(false);
        if (pollIntervalRef.current) {
          clearInterval(pollIntervalRef.current);
        }
      }
    } catch (err: any) {
      console.error('Error polling deletion status:', err);
    }
  };

  const handleStartDeletion = async () => {
    if (!confirmDelete) return;

    setDeleting(true);
    setDeletionComplete(false);
    setDeletionLogs([]);
    setProgress(0);

    const capabilityName = state.selectedCapability?.name?.replace(/\s+/g, '-') || '';
    const environment = state.selectedEnvironment || '';
    const region = state.awsConfig?.region || '';
    const accountId = state.awsConfig?.account_id || '';
    const awsSessionId = state.awsConfig?.aws_session_id;

    addLog(`🗑️ Starting deletion for ${state.selectedCapability?.name} (${environment})...`, 'info');
    addLog(`Region: ${region}`, 'info');
    addLog(`Account: ${accountId}`, 'info');

    if (state.detectionResult?.stacks_found && state.detectionResult.stacks_found.length > 0) {
      addLog(`\n📋 Stacks to delete:`, 'info');
      state.detectionResult.stacks_found.forEach(stack => {
        addLog(`  • ${stack.stack_name} (${stack.stack_type})`, 'info');
      });
      addLog('', 'info');
    }

    try {
      addLog('🔄 Initiating async deletion job...', 'info');
      
      // Start async deletion
      const response = await deploymentApi.startDeletion(
        capabilityName,
        environment,
        region,
        accountId,
        awsSessionId
      );
      
      addLog(`📝 Deletion job started: ${response.deletion_id}`, 'info');
      
      // Store deletion ID for manual refresh
      currentDeletionIdRef.current = response.deletion_id;
      
      // Start polling for status every 2 seconds
      pollIntervalRef.current = window.setInterval(() => {
        pollDeletionStatus(response.deletion_id);
      }, 2000);
      
      // Initial poll
      await pollDeletionStatus(response.deletion_id);
      
    } catch (err: any) {
      const errorMessage = err.response?.data?.detail || err.message;
      addLog(`❌ Deletion failed: ${errorMessage}`, 'error');
      
      if (errorMessage.toLowerCase().includes('session') && 
          (errorMessage.toLowerCase().includes('expired') || errorMessage.toLowerCase().includes('not found'))) {
        setSessionExpired(true);
        addLog('💡 Your AWS session has expired. Please re-authenticate to continue.', 'warning');
      }
      
      setDeletionSuccess(false);
      setDeletionComplete(true);
      setDeleting(false);
    }
  };

  const handleReauthenticate = () => {
    setStep(WizardStep.AWS_CONFIGURATION);
  };

  const handleCancel = () => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
    }
    setDeleteMode(false);
    setStep(WizardStep.CAPABILITY_SELECTION);
  };

  const handleFinish = () => {
    setDeleteMode(false);
    setStep(WizardStep.CAPABILITY_SELECTION);
  };

  const getLevelColor = (level: DeletionLog['level']) => {
    switch (level) {
      case 'success': return 'text-green-400';
      case 'warning': return 'text-yellow-400';
      case 'error': return 'text-red-400';
      default: return 'text-gray-300';
    }
  };

  const getProgressColor = () => {
    if (deletionComplete && !deletionSuccess) return 'bg-red-600';
    if (deletionComplete && deletionSuccess) return 'bg-green-600';
    return 'bg-red-500';
  };

  return (
    <div className="max-w-4xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">🗑️ Delete Installation</h1>
        <p className="text-gray-600">
          Remove all stacks and resources for {state.selectedCapability?.name}
        </p>
      </div>

      {/* Installation Details */}
      <div className="bg-white rounded-lg shadow-md p-6 mb-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Installation Details</h2>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <span className="text-gray-500">Capability:</span>
            <span className="ml-2 font-medium">{state.selectedCapability?.name}</span>
          </div>
          <div>
            <span className="text-gray-500">Environment:</span>
            <span className="ml-2 font-medium">{state.selectedEnvironment?.toUpperCase()}</span>
          </div>
          <div>
            <span className="text-gray-500">Region:</span>
            <span className="ml-2 font-medium">{state.awsConfig?.region}</span>
          </div>
          <div>
            <span className="text-gray-500">Account:</span>
            <span className="ml-2 font-medium">{state.awsConfig?.account_id}</span>
          </div>
        </div>
      </div>

      {/* Stacks to Delete */}
      {state.detectionResult?.stacks_found && state.detectionResult.stacks_found.length > 0 && !deleting && !deletionComplete && (
        <div className="bg-white rounded-lg shadow-md p-6 mb-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">
            Stacks to Delete ({state.detectionResult.stacks_found.length})
          </h2>
          <div className="space-y-2">
            {state.detectionResult.stacks_found.map((stack, idx) => (
              <div key={idx} className="flex items-center justify-between p-3 bg-red-50 border border-red-200 rounded-lg">
                <div>
                  <span className="font-medium text-red-900">{stack.stack_name}</span>
                  <span className="ml-2 text-sm text-red-700">({stack.stack_type})</span>
                </div>
                <span className="text-sm text-red-600">{stack.region}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Warning */}
      {!deletionComplete && !deleting && (
        <div className="bg-red-50 border-2 border-red-300 rounded-lg p-6 mb-6">
          <div className="flex items-start">
            <svg className="w-8 h-8 text-red-600 mr-4 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
            <div>
              <h3 className="text-lg font-bold text-red-900 mb-2">⚠️ WARNING: Permanent Deletion</h3>
              <p className="text-red-800 mb-4">This action will permanently delete ALL resources including:</p>
              <ul className="list-disc list-inside text-red-800 space-y-1 mb-4">
                <li>CloudFormation stacks</li>
                <li>S3 buckets and all contents</li>
                <li>Load Balancers and Target Groups</li>
                <li>ECS services and tasks</li>
                <li>All associated configurations</li>
              </ul>
              <p className="text-red-900 font-bold">This action cannot be undone!</p>
            </div>
          </div>
        </div>
      )}

      {/* Confirmation Checkbox */}
      {!deletionComplete && !deleting && (
        <div className="bg-white rounded-lg shadow-md p-6 mb-6">
          <label className="flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={confirmDelete}
              onChange={(e) => setConfirmDelete(e.target.checked)}
              className="w-5 h-5 text-red-600 border-gray-300 rounded focus:ring-red-500"
            />
            <span className="ml-3 text-gray-900">
              I understand that this will permanently delete all resources and data. This action cannot be undone.
            </span>
          </label>
        </div>
      )}

      {/* Progress Bar */}
      {(deleting || deletionComplete) && (
        <div className="bg-white rounded-lg shadow-md p-6 mb-6">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-lg font-semibold text-gray-900">
              {deleting ? 'Deletion in Progress' : deletionSuccess ? 'Deletion Complete' : 'Deletion Failed'}
            </h2>
            <span className="text-sm font-medium text-gray-600">{progress}%</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-3 mb-2">
            <div
              className={`h-3 rounded-full transition-all duration-500 ${getProgressColor()}`}
              style={{ width: `${progress}%` }}
            />
          </div>
          {currentStage && (
            <p className="text-sm text-gray-600">
              {deleting && <span className="inline-block animate-pulse mr-2">●</span>}
              {currentStage}
            </p>
          )}
        </div>
      )}

      {/* Deletion Logs */}
      {(deleting || deletionComplete || deletionLogs.length > 0) && (
        <div className="bg-white rounded-lg shadow-md p-6 mb-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <h2 className="text-lg font-semibold text-gray-900">Deletion Logs</h2>
              {lastRefreshTime && (
                <span className="text-xs text-gray-500">
                  Last refresh: {lastRefreshTime.toLocaleTimeString()}
                </span>
              )}
            </div>
            {deletionLogs.length > 0 && (
              <div className="flex gap-2">
                {/* Refresh Button */}
                {(deleting || !deletionComplete) && (
                  <>
                    <button
                      onClick={handleManualRefresh}
                      disabled={isRefreshing}
                      className="flex items-center px-3 py-1.5 text-sm bg-green-100 text-green-700 rounded-lg hover:bg-green-200 disabled:opacity-50"
                      title="Refresh logs"
                    >
                      <svg className={`w-4 h-4 mr-1.5 ${isRefreshing ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                      </svg>
                      {isRefreshing ? 'Refreshing...' : 'Refresh'}
                    </button>
                    <button
                      onClick={handleRestartPolling}
                      className="flex items-center px-3 py-1.5 text-sm bg-orange-100 text-orange-700 rounded-lg hover:bg-orange-200"
                      title="Restart auto-polling"
                    >
                      <svg className="w-4 h-4 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      Restart Polling
                    </button>
                  </>
                )}
                <button
                  onClick={handleCopyLogs}
                  className="flex items-center px-3 py-1.5 text-sm bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
                >
                  {copySuccess ? (
                    <><svg className="w-4 h-4 mr-1.5 text-green-600" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" /></svg>Copied!</>
                  ) : (
                    <><svg className="w-4 h-4 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>Copy</>
                  )}
                </button>
                <button
                  onClick={handleDownloadLogs}
                  className="flex items-center px-3 py-1.5 text-sm bg-blue-100 text-blue-700 rounded-lg hover:bg-blue-200"
                >
                  <svg className="w-4 h-4 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>
                  Download
                </button>
              </div>
            )}
          </div>
          <div className="bg-gray-900 rounded-lg p-4 h-96 overflow-y-auto font-mono text-sm">
            {deletionLogs.length === 0 ? (
              <p className="text-gray-500">Waiting for deletion to start...</p>
            ) : (
              deletionLogs.map((log, index) => (
                <div key={index} className="mb-1">
                  <span className="text-gray-500">[{log.timestamp}]</span>{' '}
                  <span className={getLevelColor(log.level)}>{log.message}</span>
                </div>
              ))
            )}
            <div ref={logsEndRef} />
          </div>
        </div>
      )}

      {/* Completion Status */}
      {deletionComplete && (
        <div className={`rounded-lg p-6 mb-6 ${
          deletionSuccess ? 'bg-green-50 border-2 border-green-300' : 
          sessionExpired ? 'bg-orange-50 border-2 border-orange-300' :
          'bg-yellow-50 border-2 border-yellow-300'
        }`}>
          <div className="flex items-start">
            {deletionSuccess ? (
              <svg className="w-8 h-8 text-green-600 mr-4" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
              </svg>
            ) : (
              <svg className="w-8 h-8 text-yellow-600 mr-4" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
              </svg>
            )}
            <div className="flex-1">
              <h3 className={`text-lg font-bold mb-2 ${deletionSuccess ? 'text-green-900' : 'text-yellow-900'}`}>
                {deletionSuccess ? '✅ Deletion Completed Successfully' : '⚠️ Deletion Completed with Warnings'}
              </h3>
              <p className={deletionSuccess ? 'text-green-800' : 'text-yellow-800'}>
                {deletionSuccess 
                  ? 'All resources have been removed. You can now deploy fresh infrastructure if needed.'
                  : 'Some resources may require manual cleanup. Check the logs above for details.'}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex justify-between">
        {!deletionComplete ? (
          <>
            <button
              onClick={handleCancel}
              disabled={deleting}
              className="px-6 py-3 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={handleStartDeletion}
              disabled={!confirmDelete || deleting}
              className={`px-6 py-3 rounded-lg font-semibold ${
                !confirmDelete || deleting
                  ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                  : 'bg-red-600 text-white hover:bg-red-700'
              }`}
            >
              {deleting ? (
                <span className="flex items-center">
                  <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  Deleting...
                </span>
              ) : (
                '🗑️ Delete All Resources'
              )}
            </button>
          </>
        ) : sessionExpired ? (
          <div className="flex w-full gap-4">
            <button onClick={handleCancel} className="flex-1 px-6 py-3 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50">
              Cancel
            </button>
            <button onClick={handleReauthenticate} className="flex-1 px-6 py-3 bg-orange-600 text-white rounded-lg hover:bg-orange-700 font-semibold">
              Re-authenticate & Retry
            </button>
          </div>
        ) : (
          <button
            onClick={handleFinish}
            className="w-full px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-semibold"
          >
            Return to Capabilities
          </button>
        )}
      </div>
    </div>
  );
};

export default DeletionExecution;

/**
 * Discovery Execution Component
 * 
 * Runs after AWS authentication in discovery mode.
 * Auto-creates a landing zone from the authenticated account,
 * runs CloudFormation + EKS discovery, and shows results with detailed logs.
 */
import React, { useState, useEffect, useRef } from 'react';
import { useWizard } from '../context/WizardContext';
import { WizardStep } from '../types/wizard';
import { discoveryApi, LandingZone, DiscoveryStatus, DiscoveredCapability, DiscoveryLogEntry } from '../services/api';

type DiscoveryPhase = 'creating-landing-zone' | 'discovering' | 'completed' | 'failed';

const DiscoveryExecution: React.FC = () => {
  const { state, setStep, setDiscoveryMode } = useWizard();
  const [phase, setPhase] = useState<DiscoveryPhase>('creating-landing-zone');
  const [landingZone, setLandingZone] = useState<LandingZone | null>(null);
  const [discoveryStatus, setDiscoveryStatus] = useState<DiscoveryStatus | null>(null);
  const [capabilities, setCapabilities] = useState<DiscoveredCapability[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const logsEndRef = useRef<HTMLDivElement>(null);

  const accountId = state.awsConfig?.account_id || '';
  const region = state.awsConfig?.region || 'ap-southeast-1';
  const sessionId = state.awsConfig?.aws_session_id || '';

  // Auto-scroll logs
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  // Step 1: Create or find landing zone, then start discovery
  useEffect(() => {
    const initDiscovery = async () => {
      try {
        setLogs(prev => [...prev, formatLog('INFO', `Initializing discovery for account ${accountId} in ${region}...`)]);

        const existingZones = await discoveryApi.listLandingZones('aws');
        let zone = existingZones.find(z => z.account_id === accountId);

        if (!zone) {
          setLogs(prev => [...prev, formatLog('INFO', `Creating landing zone for account ${accountId}...`)]);
          zone = await discoveryApi.createLandingZone({
            name: `AWS-${accountId}`,
            provider: 'aws',
            account_id: accountId,
            default_region: region,
          });
          setLogs(prev => [...prev, formatLog('INFO', `Landing zone created: ${zone!.name}`)]);
        } else {
          setLogs(prev => [...prev, formatLog('INFO', `Using existing landing zone: ${zone!.name}`)]);
        }

        setLandingZone(zone);
        setPhase('discovering');

        setLogs(prev => [...prev, formatLog('INFO', 'Starting capability discovery...')]);
        const status = await discoveryApi.startDiscovery(
          zone.landing_zone_id,
          sessionId,
          [region]
        );
        setDiscoveryStatus(status);
        setIsPolling(true);
      } catch (err: any) {
        const msg = err.response?.data?.detail || err.message || 'Failed to start discovery';
        setError(msg);
        setLogs(prev => [...prev, formatLog('ERROR', `Discovery failed: ${msg}`)]);
        setPhase('failed');
      }
    };

    initDiscovery();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Step 2: Poll for discovery status + logs
  useEffect(() => {
    let pollInterval: ReturnType<typeof setInterval> | null = null;

    if (isPolling && discoveryStatus?.job_id) {
      pollInterval = setInterval(async () => {
        try {
          const status = await discoveryApi.getDiscoveryStatus(discoveryStatus.job_id);
          setDiscoveryStatus(status);

          // Fetch logs
          try {
            const logEntries = await discoveryApi.getDiscoveryLogs(discoveryStatus.job_id);
            const formatted = logEntries.map(entry => formatLogEntry(entry));
            setLogs(prev => {
              // Keep initial client-side logs, replace server logs
              const clientLogs = prev.filter(l => !l.startsWith('[') || l.includes('Initializing') || l.includes('Creating landing zone') || l.includes('Using existing') || l.includes('Starting capability'));
              // Deduplicate: only add server logs
              const initialCount = clientLogs.length;
              return [...clientLogs.slice(0, Math.min(initialCount, 4)), ...formatted];
            });
          } catch {
            // Logs endpoint may not be available yet
          }

          if (status.status === 'completed') {
            setIsPolling(false);
            if (landingZone) {
              const caps = await discoveryApi.listDiscoveredCapabilities(landingZone.landing_zone_id);
              setCapabilities(caps);
            }
            setPhase('completed');
          } else if (status.status === 'failed') {
            setIsPolling(false);
            setError(status.errors.join(', ') || 'Discovery failed');
            setPhase('failed');
          }
        } catch (err) {
          console.error('Error polling discovery status:', err);
        }
      }, 2000);
    }

    return () => {
      if (pollInterval) clearInterval(pollInterval);
    };
  }, [isPolling, discoveryStatus?.job_id, landingZone]);

  const formatLog = (_level: string, message: string): string => {
    const ts = new Date().toLocaleTimeString();
    return `[${ts}] ${message}`;
  };

  const formatLogEntry = (entry: DiscoveryLogEntry): string => {
    const ts = new Date(entry.timestamp).toLocaleTimeString();
    const prefix = entry.level === 'ERROR' ? '✗ ' : entry.level === 'WARNING' ? '⚠ ' : '';
    return `[${ts}] ${prefix}${entry.message}`;
  };

  const handleDone = () => {
    setDiscoveryMode(false);
    setStep(WizardStep.CAPABILITY_SELECTION);
  };

  const handleRetry = async () => {
    if (!landingZone) return;
    setError(null);
    setLogs([formatLog('INFO', 'Retrying discovery...')]);
    setPhase('discovering');
    try {
      const status = await discoveryApi.startDiscovery(
        landingZone.landing_zone_id,
        sessionId,
        [region]
      );
      setDiscoveryStatus(status);
      setIsPolling(true);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to retry discovery');
      setPhase('failed');
    }
  };

  const handleCopyLogs = () => {
    navigator.clipboard.writeText(logs.join('\n'));
  };

  const handleDownloadLogs = () => {
    const blob = new Blob([logs.join('\n')], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `discovery-${accountId}-${new Date().toISOString().slice(0, 10)}.log`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const getStatusColor = (status: string): string => {
    switch (status) {
      case 'healthy': return 'text-green-600 bg-green-100';
      case 'partial': return 'text-amber-600 bg-amber-100';
      case 'failed': return 'text-red-600 bg-red-100';
      case 'in_progress': return 'text-blue-600 bg-blue-100';
      default: return 'text-gray-600 bg-gray-100';
    }
  };

  const getLogColor = (log: string): string => {
    if (log.includes('✗') || log.includes('ERROR') || log.includes('failed') || log.includes('Failed')) return 'text-red-400';
    if (log.includes('⚠') || log.includes('WARNING') || log.includes('skipped') || log.includes('Skipping')) return 'text-yellow-400';
    if (log.includes('[OK]') || log.includes('✓') || log.includes('complete') || log.includes('Complete') || log.includes('Found')) return 'text-green-400';
    if (log.includes('[LAUNCH]') || log.includes('[CFN]') || log.includes('[EKS]') || log.includes('[SYNC]') || log.includes('━━━')) return 'text-blue-400';
    return 'text-gray-300';
  };

  return (
    <div className="max-w-5xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">Capability Discovery</h1>
        <p className="text-gray-600">
          Scanning CloudFormation stacks and EKS clusters in account {accountId} ({region})
        </p>
      </div>

      {/* Progress + Stats */}
      <div className="bg-white rounded-lg shadow-md p-6 mb-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center">
            {(phase === 'creating-landing-zone' || phase === 'discovering') && (
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600 mr-3"></div>
            )}
            {phase === 'completed' && (
              <svg className="w-6 h-6 text-green-600 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            )}
            {phase === 'failed' && (
              <svg className="w-6 h-6 text-red-600 mr-3" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
              </svg>
            )}
            <h2 className="text-lg font-semibold text-gray-900">
              {phase === 'creating-landing-zone' && 'Setting up...'}
              {phase === 'discovering' && 'Discovery in Progress'}
              {phase === 'completed' && 'Discovery Complete'}
              {phase === 'failed' && 'Discovery Failed'}
            </h2>
          </div>
          {discoveryStatus && (
            <div className="flex gap-4 text-sm">
              <span className="text-gray-600">Stacks: <span className="font-semibold">{discoveryStatus.stacks_scanned}</span></span>
              <span className="text-gray-600">Capabilities: <span className="font-semibold text-green-600">{discoveryStatus.capabilities_found}</span></span>
            </div>
          )}
        </div>

        {discoveryStatus?.progress_message && (phase === 'creating-landing-zone' || phase === 'discovering') && (
          <p className="text-sm text-gray-500">
            <span className="inline-block animate-pulse mr-1">●</span>
            {discoveryStatus.progress_message}
          </p>
        )}

        {error && (
          <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
            {error}
          </div>
        )}
      </div>

      {/* Discovery Logs Console */}
      <div className="bg-white rounded-lg shadow-md p-6 mb-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium text-gray-700">Discovery Logs</h3>
          <div className="flex gap-2">
            <button
              onClick={handleCopyLogs}
              disabled={logs.length === 0}
              className="px-3 py-1 text-xs font-medium text-gray-700 bg-white border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50 flex items-center gap-1"
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
              className="px-3 py-1 text-xs font-medium text-white bg-blue-600 rounded hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1"
              title="Download logs"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Download
            </button>
          </div>
        </div>
        <div className="bg-gray-900 rounded-lg p-4 h-80 overflow-y-auto font-mono text-sm">
          {logs.length === 0 ? (
            <div className="text-gray-500 italic">Waiting for logs...</div>
          ) : (
            logs.map((log, index) => (
              <div key={index} className={`mb-0.5 ${getLogColor(log)}`}>
                {log}
              </div>
            ))
          )}
          <div ref={logsEndRef} />
        </div>
      </div>

      {/* Discovered Capabilities List */}
      {phase === 'completed' && capabilities.length > 0 && (
        <div className="bg-white rounded-lg shadow-md p-6 mb-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">
            Discovered Capabilities ({capabilities.length})
          </h3>
          <div className="space-y-3">
            {capabilities.map((cap, idx) => (
              <div
                key={`${cap.capability_name}-${cap.environment}-${idx}`}
                className="p-4 border border-gray-200 rounded-lg hover:border-gray-300 transition-colors"
              >
                <div className="flex items-start justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-gray-900">{cap.capability_name}</span>
                      <span className={`px-2 py-0.5 text-xs font-medium rounded ${getStatusColor(cap.status)}`}>
                        {cap.status.replace(/_/g, ' ')}
                      </span>
                    </div>
                    <div className="text-sm text-gray-500 mt-1">
                      Environment: <span className="font-medium">{cap.environment.toUpperCase()}</span> •
                      Region: {cap.primary_region} •
                      Stacks: {cap.stacks_count}
                    </div>
                    {cap.version && (
                      <div className="text-xs text-gray-400 mt-1">Version: {cap.version}</div>
                    )}
                  </div>
                  <div className="text-right text-xs text-gray-400">
                    <div>Account: {cap.account_id}</div>
                  </div>
                </div>
                {(cap.frontend_url || cap.backend_url) && (
                  <div className="mt-3 pt-3 border-t border-gray-100 flex gap-4 text-xs">
                    {cap.frontend_url && (
                      <a href={cap.frontend_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:text-blue-700">
                        Frontend URL →
                      </a>
                    )}
                    {cap.backend_url && (
                      <a href={cap.backend_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:text-blue-700">
                        Backend URL →
                      </a>
                    )}
                  </div>
                )}
                {cap.missing_stacks.length > 0 && (
                  <div className="mt-3 p-2 bg-amber-50 border border-amber-200 rounded text-xs text-amber-700">
                    <span className="font-medium">Missing stacks:</span> {cap.missing_stacks.join(', ')}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {phase === 'completed' && capabilities.length === 0 && (
        <div className="bg-white rounded-lg shadow-md p-6 mb-6">
          <div className="text-center py-8 bg-gray-50 rounded-lg border-2 border-dashed border-gray-200">
            <svg className="w-12 h-12 text-gray-400 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <p className="text-gray-500 font-medium">No capabilities found</p>
            <p className="text-sm text-gray-400 mt-1">
              No CloudFormation stacks or EKS clusters matching the naming convention were found
            </p>
          </div>
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex justify-between">
        <button
          onClick={() => {
            setDiscoveryMode(false);
            setStep(WizardStep.AWS_CONFIGURATION);
          }}
          className="px-6 py-3 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50"
        >
          Back
        </button>
        <div className="flex gap-3">
          {phase === 'failed' && (
            <button onClick={handleRetry} className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium">
              Retry Discovery
            </button>
          )}
          {(phase === 'completed' || phase === 'failed') && (
            <button
              onClick={handleDone}
              className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium"
            >
              Done — Return to Capabilities
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default DiscoveryExecution;

/**
 * Discovery Panel Component
 * 
 * Displays discovery progress and results for a landing zone.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { discoveryApi, LandingZone, DiscoveryStatus, DiscoveredCapability } from '../services/api';

interface DiscoveryPanelProps {
  landingZone: LandingZone;
  awsSessionId?: string;
  onDiscoveryComplete?: (capabilities: DiscoveredCapability[]) => void;
}

const DiscoveryPanel: React.FC<DiscoveryPanelProps> = ({
  landingZone,
  awsSessionId,
  onDiscoveryComplete,
}) => {
  const [discoveryStatus, setDiscoveryStatus] = useState<DiscoveryStatus | null>(null);
  const [capabilities, setCapabilities] = useState<DiscoveredCapability[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPolling, setIsPolling] = useState(false);

  // Load discovered capabilities for this landing zone
  const loadCapabilities = useCallback(async () => {
    try {
      const caps = await discoveryApi.listDiscoveredCapabilities(landingZone.landing_zone_id);
      setCapabilities(caps);
      onDiscoveryComplete?.(caps);
    } catch (err: any) {
      console.error('Error loading capabilities:', err);
    }
  }, [landingZone.landing_zone_id, onDiscoveryComplete]);

  // Poll for discovery status
  useEffect(() => {
    let pollInterval: NodeJS.Timeout | null = null;

    if (isPolling && discoveryStatus?.job_id) {
      pollInterval = setInterval(async () => {
        try {
          const status = await discoveryApi.getDiscoveryStatus(discoveryStatus.job_id);
          setDiscoveryStatus(status);

          if (status.status === 'completed' || status.status === 'failed') {
            setIsPolling(false);
            if (status.status === 'completed') {
              await loadCapabilities();
            }
          }
        } catch (err) {
          console.error('Error polling discovery status:', err);
        }
      }, 2000);
    }

    return () => {
      if (pollInterval) clearInterval(pollInterval);
    };
  }, [isPolling, discoveryStatus?.job_id, loadCapabilities]);

  // Load capabilities on mount
  useEffect(() => {
    loadCapabilities();
  }, [loadCapabilities]);

  const startDiscovery = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const status = await discoveryApi.startDiscovery(
        landingZone.landing_zone_id,
        awsSessionId
      );
      
      setDiscoveryStatus(status);
      setIsPolling(true);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to start discovery');
    } finally {
      setLoading(false);
    }
  };

  const refreshCapabilities = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const status = await discoveryApi.refreshCapabilities(
        landingZone.landing_zone_id,
        awsSessionId
      );
      
      setDiscoveryStatus(status);
      setIsPolling(true);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to refresh capabilities');
    } finally {
      setLoading(false);
    }
  };

  const getStatusColor = (status: string): string => {
    switch (status) {
      case 'healthy': return 'text-green-600 bg-green-100';
      case 'partial': return 'text-amber-600 bg-amber-100';
      case 'failed': return 'text-red-600 bg-red-100';
      case 'in_progress': return 'text-blue-600 bg-blue-100';
      case 'not_found_in_aws': return 'text-gray-600 bg-gray-100';
      default: return 'text-gray-600 bg-gray-100';
    }
  };

  const isDiscovering = discoveryStatus?.status === 'pending' || discoveryStatus?.status === 'running';

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-900">
          Discovered Capabilities
        </h3>
        <div className="flex gap-2">
          <button
            onClick={refreshCapabilities}
            disabled={loading || isDiscovering}
            className="flex items-center px-3 py-1.5 text-sm bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 disabled:opacity-50"
          >
            <svg className={`w-4 h-4 mr-1 ${isDiscovering ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Refresh
          </button>
          {capabilities.length === 0 && (
            <button
              onClick={startDiscovery}
              disabled={loading || isDiscovering}
              className="flex items-center px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              Discover
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          {error}
        </div>
      )}

      {/* Discovery Progress */}
      {isDiscovering && discoveryStatus && (
        <div className="mb-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
          <div className="flex items-center mb-2">
            <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600 mr-3"></div>
            <span className="font-medium text-blue-800">Discovery in Progress</span>
          </div>
          <p className="text-sm text-blue-700 ml-8">{discoveryStatus.progress_message}</p>
          <div className="mt-2 ml-8 text-xs text-blue-600">
            Stacks scanned: {discoveryStatus.stacks_scanned} • 
            Capabilities found: {discoveryStatus.capabilities_found}
          </div>
        </div>
      )}

      {/* Discovery Complete */}
      {discoveryStatus?.status === 'completed' && (
        <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg">
          <div className="flex items-center text-green-700">
            <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            <span className="font-medium">Discovery Complete</span>
          </div>
          <p className="text-sm text-green-600 ml-7">
            Found {discoveryStatus.capabilities_found} capabilities across {discoveryStatus.stacks_scanned} stacks
          </p>
        </div>
      )}

      {/* Discovery Failed */}
      {discoveryStatus?.status === 'failed' && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
          <div className="flex items-center text-red-700">
            <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
            <span className="font-medium">Discovery Failed</span>
          </div>
          {discoveryStatus.errors.length > 0 && (
            <ul className="text-sm text-red-600 ml-7 mt-1">
              {discoveryStatus.errors.map((err, idx) => (
                <li key={idx}>{err}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Capabilities List */}
      {capabilities.length === 0 && !isDiscovering ? (
        <div className="text-center py-8 bg-gray-50 rounded-lg border-2 border-dashed border-gray-200">
          <svg className="w-12 h-12 text-gray-400 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <p className="text-gray-500 font-medium">No capabilities discovered</p>
          <p className="text-sm text-gray-400 mt-1">
            Click "Discover" to scan CloudFormation stacks in this account
          </p>
        </div>
      ) : (
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
                    <span className="px-2 py-0.5 text-xs font-medium bg-purple-100 text-purple-700 rounded">
                      Discovered
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
                  <div>Discovered: {new Date(cap.discovered_at).toLocaleDateString()}</div>
                </div>
              </div>
              
              {/* URLs */}
              {(cap.frontend_url || cap.backend_url) && (
                <div className="mt-3 pt-3 border-t border-gray-100 flex gap-4 text-xs">
                  {cap.frontend_url && (
                    <a
                      href={cap.frontend_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:text-blue-700"
                    >
                      Frontend URL →
                    </a>
                  )}
                  {cap.backend_url && (
                    <a
                      href={cap.backend_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:text-blue-700"
                    >
                      Backend URL →
                    </a>
                  )}
                </div>
              )}
              
              {/* Missing Stacks Warning */}
              {cap.missing_stacks.length > 0 && (
                <div className="mt-3 p-2 bg-amber-50 border border-amber-200 rounded text-xs text-amber-700">
                  <span className="font-medium">Missing stacks:</span> {cap.missing_stacks.join(', ')}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default DiscoveryPanel;

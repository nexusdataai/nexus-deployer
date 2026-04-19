/**
 * Installation History Component
 * Displays list of deployment installations with details and logs
 */
import React, { useState, useEffect } from 'react';
import {
  installationApi,
  InstallationSummary,
  InstallationDetail,
} from '../services/api';

interface InstallationHistoryProps {
  onClose?: () => void;
}

const InstallationHistory: React.FC<InstallationHistoryProps> = ({ onClose }) => {
  const [installations, setInstallations] = useState<InstallationSummary[]>([]);
  const [selectedInstallation, setSelectedInstallation] = useState<InstallationDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState({
    capability_name: '',
    environment: '',
    status: '',
  });

  useEffect(() => {
    loadInstallations();
  }, []);

  const loadInstallations = async () => {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string> = {};
      if (filters.capability_name) params.capability_name = filters.capability_name;
      if (filters.environment) params.environment = filters.environment;
      if (filters.status) params.status = filters.status;

      const response = await installationApi.list(params);
      setInstallations(response.installations);
    } catch (err: any) {
      setError(err.message || 'Failed to load installations');
    } finally {
      setLoading(false);
    }
  };

  const loadInstallationDetails = async (installationId: string) => {
    try {
      const detail = await installationApi.getById(installationId);
      setSelectedInstallation(detail);
    } catch (err: any) {
      setError(err.message || 'Failed to load installation details');
    }
  };

  const handleDelete = async (installationId: string) => {
    if (!confirm('Are you sure you want to delete this installation record?')) return;
    try {
      await installationApi.delete(installationId);
      setInstallations(installations.filter((i) => i.installation_id !== installationId));
      if (selectedInstallation?.installation_id === installationId) {
        setSelectedInstallation(null);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to delete installation');
    }
  };

  const formatDuration = (seconds?: number) => {
    if (!seconds) return '-';
    if (seconds < 60) return `${seconds}s`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs}s`;
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString();
  };

  const getStatusBadge = (status: string) => {
    const colors: Record<string, string> = {
      pending: 'bg-yellow-100 text-yellow-800',
      running: 'bg-blue-100 text-blue-800',
      completed: 'bg-green-100 text-green-800',
      failed: 'bg-red-100 text-red-800',
      cancelled: 'bg-gray-100 text-gray-800',
      deleted: 'bg-red-100 text-red-800',
    };
    return (
      <span className={`px-2 py-1 rounded-full text-xs font-medium ${colors[status] || 'bg-gray-100'}`}>
        {status}
      </span>
    );
  };

  const getOperationBadge = (operation: string, status: string) => {
    let color = 'bg-gray-100 text-gray-800';
    if (status === 'completed') {
      if (operation === 'create') {
        color = 'bg-green-100 text-green-800';
      } else if (operation === 'delete') {
        color = 'bg-red-100 text-red-800';
      } else {
        color = 'bg-blue-100 text-blue-800';
      }
    } else if (status === 'failed') {
      color = 'bg-red-100 text-red-800';
    } else if (status === 'started') {
      color = 'bg-yellow-100 text-yellow-800';
    }
    return (
      <span className={`px-2 py-1 rounded text-xs font-medium ${color}`}>
        {operation}
      </span>
    );
  };

  return (
    <div className="bg-white rounded-lg shadow-lg max-w-6xl mx-auto">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
        <h2 className="text-xl font-semibold text-gray-900">Installation History</h2>
        {onClose && (
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>

      {/* Filters */}
      <div className="px-6 py-4 bg-gray-50 border-b border-gray-200">
        <div className="flex gap-4 items-end">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Capability</label>
            <input
              type="text"
              value={filters.capability_name}
              onChange={(e) => setFilters({ ...filters, capability_name: e.target.value })}
              placeholder="Filter by capability"
              className="px-3 py-2 border border-gray-300 rounded-md text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Environment</label>
            <select
              value={filters.environment}
              onChange={(e) => setFilters({ ...filters, environment: e.target.value })}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm"
            >
              <option value="">All</option>
              <option value="dev">Dev</option>
              <option value="stage">Stage</option>
              <option value="prod">Prod</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Status</label>
            <select
              value={filters.status}
              onChange={(e) => setFilters({ ...filters, status: e.target.value })}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm"
            >
              <option value="">All</option>
              <option value="pending">Pending</option>
              <option value="running">Running</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
              <option value="cancelled">Cancelled</option>
              <option value="deleted">Deleted</option>
            </select>
          </div>
          <button
            onClick={loadInstallations}
            className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm hover:bg-blue-700"
          >
            Apply Filters
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex" style={{ minHeight: '500px' }}>
        {/* Installation List */}
        <div className="w-1/2 border-r border-gray-200 overflow-y-auto" style={{ maxHeight: '600px' }}>
          {loading ? (
            <div className="p-8 text-center text-gray-500">Loading...</div>
          ) : error ? (
            <div className="p-8 text-center text-red-500">{error}</div>
          ) : installations.length === 0 ? (
            <div className="p-8 text-center text-gray-500">No installations found</div>
          ) : (
            <div className="divide-y divide-gray-200">
              {installations.map((inst) => (
                <div
                  key={inst.installation_id}
                  onClick={() => loadInstallationDetails(inst.installation_id)}
                  className={`p-4 cursor-pointer hover:bg-gray-50 ${
                    selectedInstallation?.installation_id === inst.installation_id ? 'bg-blue-50' : ''
                  }`}
                >
                  <div className="flex justify-between items-start mb-2">
                    <div>
                      <span className="font-medium text-gray-900">{inst.capability_name}</span>
                      <span className="text-gray-500 text-sm ml-2">v{inst.capability_version}</span>
                    </div>
                    {getStatusBadge(inst.status)}
                  </div>
                  <div className="text-sm text-gray-600 space-y-1">
                    <div className="flex gap-4">
                      <span>Env: {inst.environment}</span>
                      <span>Region: {inst.region}</span>
                    </div>
                    <div className="flex gap-4">
                      <span>Started: {formatDate(inst.started_at)}</span>
                      <span>Duration: {formatDuration(inst.duration_seconds)}</span>
                    </div>
                    {inst.stacks_summary && (
                      <div className="flex gap-2 mt-1">
                        {inst.stacks_summary.created > 0 && (
                          <span className="text-green-600">✓ {inst.stacks_summary.created} created</span>
                        )}
                        {inst.stacks_summary.updated > 0 && (
                          <span className="text-blue-600">↻ {inst.stacks_summary.updated} updated</span>
                        )}
                        {inst.stacks_summary.failed > 0 && (
                          <span className="text-red-600">✗ {inst.stacks_summary.failed} failed</span>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Installation Details */}
        <div className="w-1/2 overflow-y-auto" style={{ maxHeight: '600px' }}>
          {selectedInstallation ? (
            <div className="p-4">
              <div className="flex justify-between items-start mb-4">
                <h3 className="text-lg font-semibold text-gray-900">Installation Details</h3>
                <button
                  onClick={() => handleDelete(selectedInstallation.installation_id)}
                  className="text-red-600 hover:text-red-800 text-sm"
                >
                  Delete
                </button>
              </div>

              {/* Basic Info */}
              <div className="bg-gray-50 rounded-lg p-4 mb-4">
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div><span className="text-gray-500">ID:</span> <span className="font-mono text-xs">{selectedInstallation.installation_id}</span></div>
                  <div><span className="text-gray-500">Strategy:</span> {selectedInstallation.strategy}</div>
                  <div><span className="text-gray-500">Account:</span> {selectedInstallation.account_id}</div>
                  <div><span className="text-gray-500">Frontend:</span> {selectedInstallation.deploy_frontend ? 'Yes' : 'No'}</div>
                  <div><span className="text-gray-500">Backend:</span> {selectedInstallation.deploy_backend ? 'Yes' : 'No'}</div>
                </div>
              </div>

              {/* URLs */}
              {(selectedInstallation.frontend_url || selectedInstallation.backend_url) && (
                <div className="bg-green-50 rounded-lg p-4 mb-4">
                  <h4 className="font-medium text-green-800 mb-2">Deployment URLs</h4>
                  {selectedInstallation.frontend_url && (
                    <div className="text-sm">
                      <span className="text-gray-600">Frontend:</span>{' '}
                      <a href={selectedInstallation.frontend_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
                        {selectedInstallation.frontend_url}
                      </a>
                    </div>
                  )}
                  {selectedInstallation.backend_url && (
                    <div className="text-sm">
                      <span className="text-gray-600">Backend:</span>{' '}
                      <a href={selectedInstallation.backend_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
                        {selectedInstallation.backend_url}
                      </a>
                    </div>
                  )}
                </div>
              )}

              {/* Error */}
              {selectedInstallation.error && (
                <div className="bg-red-50 rounded-lg p-4 mb-4">
                  <h4 className="font-medium text-red-800 mb-2">Error</h4>
                  <p className="text-sm text-red-700">{selectedInstallation.error}</p>
                </div>
              )}

              {/* Stack Operations */}
              <div>
                <h4 className="font-medium text-gray-900 mb-2">Stack Operations ({selectedInstallation.logs.length})</h4>
                <div className="space-y-2">
                  {selectedInstallation.logs.map((log) => (
                    <div key={log.log_id} className="border border-gray-200 rounded p-3 text-sm">
                      <div className="flex justify-between items-start mb-1">
                        <span className="font-medium">{log.stack_name}</span>
                        {getOperationBadge(log.operation, log.status)}
                      </div>
                      <div className="text-gray-600 text-xs space-y-1">
                        <div>Type: {log.stack_type} | Region: {log.region}</div>
                        <div>Duration: {formatDuration(log.duration_seconds)}</div>
                        {log.error_message && (
                          <div className="text-red-600 mt-1">{log.error_message}</div>
                        )}
                        {log.stack_outputs && Object.keys(log.stack_outputs).length > 0 && (
                          <details className="mt-2">
                            <summary className="cursor-pointer text-blue-600">Outputs ({Object.keys(log.stack_outputs).length})</summary>
                            <div className="mt-1 bg-gray-100 p-2 rounded font-mono text-xs">
                              {Object.entries(log.stack_outputs).map(([key, value]) => (
                                <div key={key}>{key}: {value}</div>
                              ))}
                            </div>
                          </details>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Deployment Log */}
              {selectedInstallation.installation_log && (
                <div className="mt-4">
                  <div className="flex justify-between items-center mb-2">
                    <h4 className="font-medium text-gray-900">Deployment Log</h4>
                    <button
                      onClick={() => {
                        const blob = new Blob([selectedInstallation.installation_log || ''], { type: 'text/plain' });
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = `deployment-log-${selectedInstallation.capability_name}-${selectedInstallation.environment}-${selectedInstallation.started_at.slice(0, 10)}.txt`;
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                        URL.revokeObjectURL(url);
                      }}
                      className="flex items-center gap-1 px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                      </svg>
                      Download Log
                    </button>
                  </div>
                  <div className="bg-gray-900 text-gray-100 rounded-lg p-4 font-mono text-xs overflow-x-auto max-h-64 overflow-y-auto">
                    <pre className="whitespace-pre-wrap">{selectedInstallation.installation_log}</pre>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="p-8 text-center text-gray-500">
              Select an installation to view details
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default InstallationHistory;

/**
 * EKSClusterSelector Component
 * Displays available EKS clusters and allows selection for deployment
 */
import React, { useState, useEffect, useCallback } from 'react';
import { useWizard } from '../context/WizardContext';
import { WizardStep } from '../types/wizard';
import {
  EKSCluster,
  EKSConfig,
  DEFAULT_EKS_CONFIG,
  generateDefaultNamespace,
  isValidNamespace,
  OperatorStatus,
} from '../types/eks';
import { eksApi } from '../services/api';

interface ClusterCardProps {
  cluster: EKSCluster;
  isSelected: boolean;
  onSelect: () => void;
}

const getStatusColor = (status: string): string => {
  switch (status) {
    case 'ACTIVE':
      return 'text-green-600 bg-green-100';
    case 'CREATING':
    case 'UPDATING':
      return 'text-yellow-600 bg-yellow-100';
    case 'DELETING':
    case 'FAILED':
      return 'text-red-600 bg-red-100';
    default:
      return 'text-gray-600 bg-gray-100';
  }
};

const getOperatorStatusDisplay = (status?: OperatorStatus): { text: string; color: string } => {
  switch (status) {
    case 'installed':
      return { text: 'Operator Installed', color: 'text-green-600 bg-green-100' };
    case 'installing':
      return { text: 'Installing...', color: 'text-yellow-600 bg-yellow-100' };
    case 'failed':
      return { text: 'Install Failed', color: 'text-red-600 bg-red-100' };
    case 'not_installed':
      return { text: 'Not Installed', color: 'text-gray-600 bg-gray-100' };
    default:
      return { text: 'Unknown', color: 'text-gray-500 bg-gray-100' };
  }
};

const ClusterCard: React.FC<ClusterCardProps> = ({ cluster, isSelected, onSelect }) => {
  const isSelectable = cluster.status === 'ACTIVE';
  const operatorDisplay = getOperatorStatusDisplay(cluster.operatorStatus);

  return (
    <div
      onClick={() => isSelectable && onSelect()}
      className={`
        relative p-4 rounded-lg border-2 transition-all duration-200
        ${!isSelectable
          ? 'opacity-60 cursor-not-allowed bg-gray-50 border-gray-200'
          : 'cursor-pointer hover:shadow-md'
        }
        ${isSelected && isSelectable
          ? 'border-blue-500 bg-blue-50 shadow-md ring-2 ring-blue-200'
          : isSelectable ? 'border-gray-200 bg-white hover:border-blue-300' : ''
        }
      `}
      role="button"
      tabIndex={isSelectable ? 0 : -1}
      aria-selected={isSelected}
      aria-disabled={!isSelectable}
    >
      <div className="flex items-start justify-between mb-3">
        <div>
          <h4 className="font-semibold text-gray-900 text-lg">{cluster.name}</h4>
          <p className="text-sm text-gray-500">v{cluster.version}</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className={`px-2 py-1 text-xs font-medium rounded ${getStatusColor(cluster.status)}`}>
            {cluster.status}
          </span>
          <span className={`px-2 py-1 text-xs font-medium rounded ${operatorDisplay.color}`}>
            {operatorDisplay.text}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 text-sm">
        <div>
          <span className="text-gray-500">Nodes:</span>
          <span className="ml-1 font-medium">{cluster.nodeCount ?? 'N/A'}</span>
        </div>
        <div>
          <span className="text-gray-500">Platform:</span>
          <span className="ml-1 font-medium">{cluster.platformVersion}</span>
        </div>
      </div>

      {!isSelectable && (
        <p className="mt-2 text-xs text-red-600">
          Cluster must be ACTIVE to select
        </p>
      )}

      {isSelected && isSelectable && (
        <div className="absolute top-2 right-2">
          <svg className="w-6 h-6 text-blue-500" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
          </svg>
        </div>
      )}
    </div>
  );
};


const EKSClusterSelector: React.FC = () => {
  const { state, setEKSConfig, setStep } = useWizard();
  
  const [clusters, setClusters] = useState<EKSCluster[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const [selectedCluster, setSelectedCluster] = useState<EKSCluster | null>(null);
  const [namespace, setNamespace] = useState('');
  const [createNamespace, setCreateNamespace] = useState(true);
  const [namespaceError, setNamespaceError] = useState<string | null>(null);

  // Generate default namespace when capability/environment changes
  useEffect(() => {
    if (state.selectedCapability && state.selectedEnvironment && !namespace) {
      const defaultNs = generateDefaultNamespace(
        state.selectedCapability.name,
        state.selectedEnvironment
      );
      setNamespace(defaultNs);
    }
  }, [state.selectedCapability, state.selectedEnvironment, namespace]);

  // Fetch clusters on mount
  const fetchClusters = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Pass AWS session ID and region for authenticated requests
      const awsSessionId = state.awsConfig?.aws_session_id;
      const region = state.awsRegion || undefined;
      
      console.log('Fetching EKS clusters with session:', awsSessionId, 'region:', region);
      const response = await eksApi.listClusters(awsSessionId, region);
      setClusters(response.clusters);
      console.log('Found clusters:', response.clusters.length);
    } catch (err) {
      console.error('Failed to fetch EKS clusters:', err);
      setError(err instanceof Error ? err.message : 'Failed to fetch EKS clusters');
    } finally {
      setLoading(false);
    }
  }, [state.awsConfig?.aws_session_id, state.awsRegion]);

  useEffect(() => {
    fetchClusters();
  }, [fetchClusters]);

  // Validate namespace
  useEffect(() => {
    if (namespace && !isValidNamespace(namespace)) {
      setNamespaceError('Namespace must be lowercase, alphanumeric with hyphens, max 63 characters');
    } else {
      setNamespaceError(null);
    }
  }, [namespace]);

  const handleClusterSelect = (cluster: EKSCluster) => {
    setSelectedCluster(cluster);
  };

  const isValid = selectedCluster && namespace && !namespaceError;

  const handleContinue = () => {
    if (isValid && selectedCluster) {
      const eksConfig: EKSConfig = {
        ...DEFAULT_EKS_CONFIG,
        clusterName: selectedCluster.name,
        clusterArn: selectedCluster.arn,
        clusterEndpoint: selectedCluster.endpoint,
        namespace,
        createNamespace,
        operatorInstalled: selectedCluster.operatorStatus === 'installed',
        operatorVersion: selectedCluster.operatorVersion,
      } as EKSConfig;
      
      setEKSConfig(eksConfig);
      // Go to permission verification (next step in the Pure EKS flow)
      setStep(WizardStep.PERMISSION_VERIFICATION);
    }
  };

  const handleBack = () => {
    // Go back to AWS configuration (previous step in the Pure EKS flow)
    setStep(WizardStep.AWS_CONFIGURATION);
  };

  return (
    <div className="max-w-4xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">Select EKS Cluster</h1>
        <p className="text-gray-600">
          Choose an existing EKS cluster for deploying your capability. 
          The Totogi Operator will be installed if not already present.
        </p>
      </div>

      {/* Cluster List */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 mb-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-gray-900">Available Clusters</h2>
          <button
            onClick={fetchClusters}
            disabled={loading}
            className="px-3 py-1 text-sm text-blue-600 hover:text-blue-700 disabled:opacity-50"
          >
            {loading ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>

        {loading && (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
            <span className="ml-3 text-gray-600">Loading clusters...</span>
          </div>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
            <p className="font-medium">Error loading clusters</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {!loading && !error && clusters.length === 0 && (
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-yellow-700">
            <p className="font-medium">No EKS clusters found</p>
            <p className="text-sm">
              Create an EKS cluster in your AWS account before proceeding with Pure EKS deployment.
            </p>
          </div>
        )}

        {!loading && !error && clusters.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {clusters.map((cluster) => (
              <ClusterCard
                key={cluster.arn}
                cluster={cluster}
                isSelected={selectedCluster?.arn === cluster.arn}
                onSelect={() => handleClusterSelect(cluster)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Namespace Configuration */}
      {selectedCluster && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 mb-6">
          <h2 className="text-xl font-semibold text-gray-900 mb-4">Namespace Configuration</h2>
          
          <div className="space-y-4">
            <div>
              <label htmlFor="namespace" className="block text-sm font-medium text-gray-700 mb-1">
                Target Namespace
              </label>
              <input
                type="text"
                id="namespace"
                value={namespace}
                onChange={(e) => setNamespace(e.target.value.toLowerCase())}
                className={`w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 ${
                  namespaceError ? 'border-red-300' : 'border-gray-300'
                }`}
                placeholder="e.g., call-processing-prod"
              />
              {namespaceError && (
                <p className="mt-1 text-sm text-red-600">{namespaceError}</p>
              )}
              <p className="mt-1 text-xs text-gray-500">
                Default: {'{capability-name}'}-{'{environment}'}
              </p>
            </div>

            <div className="flex items-center">
              <input
                type="checkbox"
                id="createNamespace"
                checked={createNamespace}
                onChange={(e) => setCreateNamespace(e.target.checked)}
                className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
              />
              <label htmlFor="createNamespace" className="ml-2 text-sm text-gray-700">
                Create namespace if it doesn't exist
              </label>
            </div>
          </div>
        </div>
      )}

      {/* Operator Status Info */}
      {selectedCluster && selectedCluster.operatorStatus !== 'installed' && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
          <div className="flex items-start">
            <svg className="w-5 h-5 text-blue-600 mt-0.5 mr-2" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
            </svg>
            <div>
              <p className="font-medium text-blue-800">Totogi Operator Required</p>
              <p className="text-sm text-blue-700">
                The Totogi Operator will be automatically installed to this cluster during deployment.
                This enables declarative capability management via Kubernetes Custom Resources.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Navigation Buttons */}
      <div className="flex justify-between">
        <button
          onClick={handleBack}
          className="px-6 py-3 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 font-medium"
        >
          Back
        </button>
        <button
          onClick={handleContinue}
          disabled={!isValid}
          className={`px-6 py-3 rounded-lg font-medium ${
            isValid
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

export default EKSClusterSelector;

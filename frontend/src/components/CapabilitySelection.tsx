/**
 * Capability Selection Component
 * Displays installed and available capabilities in separate sections
 * Enhanced with AWS capability discovery support
 * 
 * Requirements: 8.1, 9.2, 9.3, 11.1, 11.2, 11.3
 */
import React, { useEffect, useState, useCallback } from 'react';
import { useWizard } from '../context/WizardContext';
import { WizardStep } from '../types/wizard';
import { Capability } from '../types/capability';
import { capabilityApi, deploymentApi, discoveryApi, LandingZone, DiscoveredCapability } from '../services/api';
import EnvironmentSelectorModal, { DeploymentState } from './EnvironmentSelectorModal';

// Installed Capability Card Component
interface InstalledCardProps {
  capability: Capability;
  deployments: DeploymentState[];
  onUpdate: () => void;
  onDelete: () => void;
  isDiscovered?: boolean;
  landingZoneName?: string;
  discoveredAt?: string;
  accountId?: string;
}

const InstalledCapabilityCard: React.FC<InstalledCardProps> = ({
  capability,
  deployments,
  onUpdate,
  onDelete,
  isDiscovered = false,
  landingZoneName,
  discoveredAt,
  accountId,
}) => {
  const formatDate = (dateString: string): string => {
    try {
      const date = new Date(dateString);
      return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return dateString;
    }
  };

  return (
    <div className="bg-white rounded-lg shadow-md border-l-4 border-green-500 p-5">
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-lg font-semibold text-gray-900">{capability.name}</h3>
            {/* Requirement 9.2, 9.3: Show "Discovered" badge for discovered capabilities */}
            {isDiscovered && (
              <span className="inline-block px-2 py-0.5 text-xs font-semibold bg-purple-100 text-purple-700 rounded-full">
                Discovered
              </span>
            )}
          </div>
          <span className="inline-block px-2 py-1 text-xs font-medium bg-green-100 text-green-800 rounded mt-1">
            {capability.category}
          </span>
          {/* Requirement 11.2: Indicate which landing zone each capability belongs to */}
          {/* Requirement 11.5: Show account identifier for capabilities with same name in different accounts */}
          {(landingZoneName || accountId) && (
            <div className="text-xs text-gray-500 mt-1 space-y-0.5">
              {landingZoneName && (
                <span className="inline-flex items-center mr-2">
                  <svg className="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z" />
                  </svg>
                  {landingZoneName}
                </span>
              )}
              {accountId && (
                <span className="inline-flex items-center text-gray-400">
                  <svg className="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V8a2 2 0 00-2-2h-5m-4 0V5a2 2 0 114 0v1m-4 0a2 2 0 104 0m-5 8a2 2 0 100-4 2 2 0 000 4zm0 0c1.306 0 2.417.835 2.83 2M9 14a3.001 3.001 0 00-2.83 2M15 11h3m-3 4h2" />
                  </svg>
                  Account: {accountId}
                </span>
              )}
            </div>
          )}
        </div>
        <span className="text-xs text-gray-500">v{capability.version}</span>
      </div>

      <p className="text-sm text-gray-600 mb-4">{capability.description}</p>

      {/* Requirement 9.2, 9.3: Show "Discovered: {timestamp}" in capability details */}
      {isDiscovered && discoveredAt && (
        <div className="text-xs text-purple-600 mb-3 flex items-center">
          <svg className="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          Discovered: {formatDate(discoveredAt)}
        </div>
      )}

      {/* Deployment Details */}
      <div className="bg-green-50 border border-green-200 rounded-lg p-3 mb-4">
        <h4 className="text-xs font-semibold text-green-800 mb-2">Active Deployments:</h4>
        <div className="space-y-2">
          {deployments.map((dep, idx) => (
            <div key={idx} className="flex items-center justify-between text-xs">
              <div className="flex items-center">
                <span className="w-2 h-2 bg-green-500 rounded-full mr-2"></span>
                <span className="font-medium text-green-700">
                  {dep.environment.toUpperCase()}
                </span>
                <span className="text-green-600 ml-2">({dep.region})</span>
              </div>
              <span className="text-green-600">{formatDate(dep.last_deployment)}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Action Buttons */}
      <div className="flex gap-2">
        <button
          onClick={onUpdate}
          className="flex-1 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 font-medium text-sm flex items-center justify-center"
        >
          <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          Update
        </button>
        <button
          onClick={onDelete}
          className="px-4 py-2 border-2 border-red-500 text-red-600 rounded-lg hover:bg-red-50 font-medium text-sm flex items-center justify-center"
        >
          <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
          </svg>
          Delete
        </button>
      </div>
    </div>
  );
};

// Available Capability Card Component
interface AvailableCardProps {
  capability: Capability;
  onInstall: () => void;
}

const AvailableCapabilityCard: React.FC<AvailableCardProps> = ({
  capability,
  onInstall,
}) => {
  const isComingSoon = capability.status === 'coming_soon';
  
  return (
    <div className={`bg-white rounded-lg shadow-md border-l-4 p-5 ${
      isComingSoon ? 'border-gray-400 opacity-75' : 'border-blue-500'
    }`}>
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-lg font-semibold text-gray-900">{capability.name}</h3>
            {isComingSoon && (
              <span className="inline-block px-2 py-0.5 text-xs font-semibold bg-amber-100 text-amber-700 rounded-full">
                Coming Soon
              </span>
            )}
          </div>
          <span className={`inline-block px-2 py-1 text-xs font-medium rounded mt-1 ${
            isComingSoon ? 'bg-gray-100 text-gray-600' : 'bg-blue-100 text-blue-800'
          }`}>
            {capability.category}
          </span>
        </div>
        <span className="text-xs text-gray-500">v{capability.version}</span>
      </div>

      <p className="text-sm text-gray-600 mb-4">{capability.description}</p>

      {/* Capability Info */}
      <div className="flex items-center text-xs text-gray-500 mb-4">
        <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        ~{capability.estimated_deployment_time} min deployment
      </div>

      {/* Install Button or Coming Soon */}
      {isComingSoon ? (
        <button
          disabled
          className="w-full px-4 py-2 bg-gray-300 text-gray-500 rounded-lg font-medium text-sm flex items-center justify-center cursor-not-allowed"
        >
          <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          Coming Soon
        </button>
      ) : (
        <button
          onClick={onInstall}
          className="w-full px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium text-sm flex items-center justify-center"
        >
          <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
          </svg>
          Install
        </button>
      )}
    </div>
  );
};


// Main CapabilitySelection Component
const CapabilitySelection: React.FC = () => {
  const { setCapability, setStep, setEnvironment, setAwsRegion, setDeleteMode, setDiscoveryMode } = useWizard();
  const [capabilities, setCapabilities] = useState<Capability[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deploymentStates, setDeploymentStates] = useState<DeploymentState[]>([]);
  const [loadingStates, setLoadingStates] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  
  // Discovery state - Requirements 11.1, 11.2, 11.3
  const [landingZones, setLandingZones] = useState<LandingZone[]>([]);
  const [discoveredCapabilities, setDiscoveredCapabilities] = useState<DiscoveredCapability[]>([]);
  const [landingZoneFilter, setLandingZoneFilter] = useState<string>('all');
  const [refreshingDiscovery, setRefreshingDiscovery] = useState(false);
  
  // Environment selector modal state
  const [selectorModalOpen, setSelectorModalOpen] = useState(false);
  const [pendingOperation, setPendingOperation] = useState<{
    capability: Capability;
    deployments: DeploymentState[];
    operationType: 'update' | 'delete';
  } | null>(null);

  // Load landing zones on mount
  useEffect(() => {
    loadLandingZones();
  }, []);

  // Refresh data on mount and when refreshKey changes
  useEffect(() => {
    loadCapabilities();
    loadDeploymentStates();
    loadDiscoveredCapabilities();
  }, [refreshKey]);

  // Also refresh when component becomes visible (e.g., returning from deletion)
  useEffect(() => {
    // This will trigger a refresh every time the component mounts
    loadDeploymentStates();
  }, []);

  const loadLandingZones = async () => {
    try {
      const zones = await discoveryApi.listLandingZones('aws');
      setLandingZones(zones);
    } catch (err) {
      console.error('Error loading landing zones:', err);
    }
  };

  const loadDiscoveredCapabilities = useCallback(async () => {
    try {
      const caps = await discoveryApi.listDiscoveredCapabilities();
      setDiscoveredCapabilities(caps);
    } catch (err) {
      console.error('Error loading discovered capabilities:', err);
    }
  }, []);

  const handleRefresh = async () => {
    // Requirement 8.1: Display a "Refresh" button when viewing discovered capabilities
    // Use discovery refresh for discovered capabilities
    if (discoveredCapabilities.length > 0 && landingZoneFilter !== 'all') {
      // Refresh discovered capabilities for the selected landing zone
      setRefreshingDiscovery(true);
      try {
        await discoveryApi.refreshCapabilities(landingZoneFilter);
        // Wait a bit for the refresh to complete, then reload
        setTimeout(() => {
          loadDiscoveredCapabilities();
          setRefreshingDiscovery(false);
        }, 2000);
      } catch (err) {
        console.error('Error refreshing discovered capabilities:', err);
        setRefreshingDiscovery(false);
      }
    }
    setRefreshKey(prev => prev + 1);
  };

  const loadCapabilities = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await capabilityApi.getAll();
      setCapabilities(data);
    } catch (err) {
      setError('Failed to load capabilities. Please check if the backend is running.');
      console.error('Error loading capabilities:', err);
    } finally {
      setLoading(false);
    }
  };

  const loadDeploymentStates = async () => {
    try {
      setLoadingStates(true);
      const response = await deploymentApi.getDeploymentStates();
      setDeploymentStates(response.deployments || []);
    } catch (err) {
      console.error('Error loading deployment states:', err);
    } finally {
      setLoadingStates(false);
    }
  };

  // Get deployment states for a specific capability
  const getCapabilityDeployments = (capabilityName: string): DeploymentState[] => {
    return deploymentStates.filter(
      state => state.capability_name.toLowerCase() === capabilityName.toLowerCase()
    );
  };

  // Get discovered capability info for a deployment
  const getDiscoveredInfo = (capabilityName: string, environment: string): DiscoveredCapability | undefined => {
    return discoveredCapabilities.find(
      dc => dc.capability_name.toLowerCase() === capabilityName.toLowerCase() &&
            dc.environment.toLowerCase() === environment.toLowerCase()
    );
  };

  // Get landing zone name by ID
  const getLandingZoneName = (landingZoneId: string): string | undefined => {
    const zone = landingZones.find(z => z.landing_zone_id === landingZoneId);
    return zone?.name || zone?.account_id;
  };

  // Check if a deployment is discovered (strategy === 'DISCOVERED')
  const isDeploymentDiscovered = (deployment: DeploymentState): boolean => {
    return deployment.strategy === 'DISCOVERED';
  };

  // Categorize capabilities into installed and available
  // Installed: capabilities with at least one deployment
  // Available: ALL capabilities (regardless of deployment status) - allows installing to new environments
  // Requirement 11.3: Allow filtering capabilities by landing zone
  // Requirement 11.5: Display capabilities with same name in different accounts as separate entries
  const categorizeCapabilities = () => {
    const installed: { 
      capability: Capability; 
      deployments: DeploymentState[];
      isDiscovered: boolean;
      landingZoneName?: string;
      discoveredAt?: string;
      accountId?: string;
    }[] = [];

    // Track unique keys to handle Requirement 11.5: same capability name in different accounts
    const seenKeys = new Set<string>();

    capabilities.forEach(capability => {
      let deployments = getCapabilityDeployments(capability.name);
      
      // Apply landing zone filter if set
      if (landingZoneFilter !== 'all') {
        deployments = deployments.filter(dep => {
          const discoveredInfo = getDiscoveredInfo(capability.name, dep.environment);
          return discoveredInfo?.landing_zone_id === landingZoneFilter;
        });
      }
      
      if (deployments.length > 0) {
        // Check if any deployment is discovered
        const hasDiscoveredDeployment = deployments.some(isDeploymentDiscovered);
        const firstDiscoveredInfo = deployments
          .map(dep => getDiscoveredInfo(capability.name, dep.environment))
          .find(info => info !== undefined);
        
        // Create unique key including account_id for Requirement 11.5
        const accountId = firstDiscoveredInfo?.account_id;
        const uniqueKey = `${capability.name.toLowerCase()}-${accountId || 'local'}`;
        
        if (!seenKeys.has(uniqueKey)) {
          seenKeys.add(uniqueKey);
          installed.push({ 
            capability, 
            deployments,
            isDiscovered: hasDiscoveredDeployment,
            landingZoneName: firstDiscoveredInfo ? getLandingZoneName(firstDiscoveredInfo.landing_zone_id) : undefined,
            discoveredAt: firstDiscoveredInfo?.discovered_at,
            accountId: accountId,
          });
        }
      }
    });

    // Also include discovered capabilities that don't match any known capability
    // This handles capabilities discovered from AWS that aren't in the local catalog
    // Requirement 11.5: Handle same capability name in different accounts as separate entries
    discoveredCapabilities.forEach(dc => {
      // Apply landing zone filter
      if (landingZoneFilter !== 'all' && dc.landing_zone_id !== landingZoneFilter) {
        return;
      }
      
      const matchingCapability = capabilities.find(
        c => c.name.toLowerCase() === dc.capability_name.toLowerCase()
      );
      
      if (!matchingCapability) {
        // Create a synthetic capability for discovered-only items
        // Include account_id in the ID to make it unique per account (Requirement 11.5)
        const syntheticCapability: Capability = {
          id: `discovered-${dc.capability_name}-${dc.environment}-${dc.account_id}`,
          name: dc.capability_name,
          version: dc.version || 'unknown',
          description: `Discovered capability from AWS account ${dc.account_id}`,
          category: 'Discovered',
          status: 'available',
          estimated_deployment_time: 0,
          supported_clouds: ['aws'],
          supported_environments: [dc.environment],
          requirements: { frontend: true, backend: true, database: false, authentication: false },
          artifacts: {},
          required_iam_permissions: [],
          prerequisites: [],
        };
        
        const syntheticDeployment: DeploymentState = {
          capability_name: dc.capability_name,
          environment: dc.environment,
          region: dc.primary_region,
          status: dc.status,
          last_deployment: dc.discovered_at,
          strategy: 'DISCOVERED',
          stacks: [], // Discovered capabilities don't have detailed stack info in this view
        };
        
        // Requirement 11.5: Check if we already added this specific capability+account combination
        // Use capability name + account_id as the unique key to allow same name in different accounts
        const uniqueKey = `${dc.capability_name.toLowerCase()}-${dc.account_id}`;
        
        if (!seenKeys.has(uniqueKey)) {
          seenKeys.add(uniqueKey);
          installed.push({
            capability: syntheticCapability,
            deployments: [syntheticDeployment],
            isDiscovered: true,
            landingZoneName: getLandingZoneName(dc.landing_zone_id),
            discoveredAt: dc.discovered_at,
            accountId: dc.account_id,
          });
        }
      }
    });

    // Available section shows ALL capabilities - users can install to any environment
    const available: Capability[] = [...capabilities];

    return { installed, available };
  };

  // Action handlers
  const handleInstall = (capability: Capability) => {
    setCapability(capability);
    setDeleteMode(false);  // Ensure delete mode is off for install
    setStep(WizardStep.ARCHITECTURE_SELECTION);
  };

  // Proceed with operation after environment selection
  const proceedWithOperation = (
    capability: Capability,
    deployment: DeploymentState,
    operationType: 'update' | 'delete'
  ) => {
    setCapability(capability);
    setEnvironment(deployment.environment);
    setAwsRegion(deployment.region);
    setDeleteMode(operationType === 'delete');
    setStep(WizardStep.AWS_CONFIGURATION);
  };

  // Handle environment selection from modal
  const handleEnvironmentSelect = (deployment: DeploymentState) => {
    if (pendingOperation) {
      proceedWithOperation(pendingOperation.capability, deployment, pendingOperation.operationType);
      setSelectorModalOpen(false);
      setPendingOperation(null);
    }
  };

  // Close modal without action
  const handleModalClose = () => {
    setSelectorModalOpen(false);
    setPendingOperation(null);
  };

  // Update: shows modal if multiple deployments, otherwise proceeds directly
  const handleUpdate = (capability: Capability, deployments: DeploymentState[]) => {
    if (deployments.length > 1) {
      setPendingOperation({ capability, deployments, operationType: 'update' });
      setSelectorModalOpen(true);
    } else if (deployments.length === 1) {
      proceedWithOperation(capability, deployments[0], 'update');
    }
  };

  // Delete: shows modal if multiple deployments, otherwise proceeds directly
  const handleDelete = (capability: Capability, deployments: DeploymentState[]) => {
    if (deployments.length > 1) {
      setPendingOperation({ capability, deployments, operationType: 'delete' });
      setSelectorModalOpen(true);
    } else if (deployments.length === 1) {
      proceedWithOperation(capability, deployments[0], 'delete');
    }
  };

  const { installed, available } = categorizeCapabilities();

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600">Loading capabilities...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-2xl mx-auto">
        <div className="bg-red-50 border border-red-200 rounded-lg p-6">
          <h3 className="text-red-800 font-semibold mb-2">Error Loading Capabilities</h3>
          <p className="text-red-600 mb-4">{error}</p>
          <button
            onClick={loadCapabilities}
            className="px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 mb-2">Capabilities</h1>
          <p className="text-gray-600">Manage your installed capabilities or install new ones</p>
        </div>
        <div className="flex items-center gap-3">
          {/* Discover from AWS Button - Requirement 11.1 */}
          <button
            onClick={() => {
              setDiscoveryMode(true);
              setDeleteMode(false);
              setStep(WizardStep.AWS_CONFIGURATION);
            }}
            className="flex items-center px-4 py-2 text-sm bg-purple-600 text-white rounded-lg hover:bg-purple-700"
          >
            <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            Discover from AWS
          </button>
          {/* Requirement 8.1: Display a "Refresh" button */}
          <button
            onClick={handleRefresh}
            disabled={loading || loadingStates || refreshingDiscovery}
            className="flex items-center px-4 py-2 text-sm bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 disabled:opacity-50"
          >
            <svg className={`w-4 h-4 mr-2 ${(loadingStates || refreshingDiscovery) ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            {refreshingDiscovery ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* Landing Zone Filter - Requirement 11.3: Allow filtering capabilities by landing zone */}
      {landingZones.length > 0 && (
        <div className="mb-6 flex items-center gap-4">
          <label className="text-sm font-medium text-gray-700">Filter by Landing Zone:</label>
          <select
            value={landingZoneFilter}
            onChange={(e) => setLandingZoneFilter(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="all">All Landing Zones</option>
            {landingZones.map(zone => (
              <option key={zone.landing_zone_id} value={zone.landing_zone_id}>
                {zone.name} ({zone.account_id})
              </option>
            ))}
          </select>
          {landingZoneFilter !== 'all' && (
            <button
              onClick={() => setLandingZoneFilter('all')}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Clear filter
            </button>
          )}
        </div>
      )}

      {loadingStates && (
        <div className="mb-4 text-sm text-gray-500 flex items-center">
          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600 mr-2"></div>
          Loading deployment states...
        </div>
      )}

      {/* Installed Capabilities Section - Boxed */}
      <div className="mb-8 bg-white border-2 border-green-200 rounded-xl shadow-sm">
        <div className="p-6">
          <div className="flex items-center mb-6">
            <div className="w-3 h-3 bg-green-500 rounded-full mr-2"></div>
            <h2 className="text-xl font-semibold text-gray-900">Installed Capabilities</h2>
            <span className="ml-2 px-2 py-1 text-xs font-medium bg-green-100 text-green-800 rounded-full">
              {installed.length}
            </span>
          </div>

          {installed.length === 0 ? (
            <div className="bg-green-50 border-2 border-dashed border-green-300 rounded-lg p-8 text-center">
              <svg className="w-12 h-12 text-green-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
              </svg>
              <p className="text-green-700 font-medium">No capabilities installed yet</p>
              <p className="text-sm text-green-600 mt-1">Install a capability from the available list below or discover from AWS</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {installed.map(({ capability, deployments, isDiscovered, landingZoneName, discoveredAt, accountId }) => (
                <InstalledCapabilityCard
                  key={`${capability.id}-${accountId || 'local'}`}
                  capability={capability}
                  deployments={deployments}
                  onUpdate={() => handleUpdate(capability, deployments)}
                  onDelete={() => handleDelete(capability, deployments)}
                  isDiscovered={isDiscovered}
                  landingZoneName={landingZoneName}
                  discoveredAt={discoveredAt}
                  accountId={accountId}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Available Capabilities Section - Boxed */}
      <div className="mb-8 bg-white border-2 border-blue-200 rounded-xl shadow-sm">
        <div className="p-6">
          <div className="flex items-center mb-6">
            <div className="w-3 h-3 bg-blue-500 rounded-full mr-2"></div>
            <h2 className="text-xl font-semibold text-gray-900">Available Capabilities</h2>
            <span className="ml-2 px-2 py-1 text-xs font-medium bg-blue-100 text-blue-800 rounded-full">
              {available.length}
            </span>
          </div>

          {available.length === 0 ? (
            <div className="bg-blue-50 border-2 border-dashed border-blue-300 rounded-lg p-8 text-center">
              <svg className="w-12 h-12 text-blue-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <p className="text-blue-700 font-medium">No capabilities available</p>
              <p className="text-sm text-blue-600 mt-1">Check back later for new capabilities</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {available.map(capability => (
                <AvailableCapabilityCard
                  key={capability.id}
                  capability={capability}
                  onInstall={() => handleInstall(capability)}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Back Button */}
      <div className="flex justify-start">
        <button
          onClick={() => setStep(WizardStep.WELCOME)}
          className="px-6 py-3 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50"
        >
          Back
        </button>
      </div>

      {/* Environment Selector Modal */}
      <EnvironmentSelectorModal
        isOpen={selectorModalOpen}
        onClose={handleModalClose}
        onSelect={handleEnvironmentSelect}
        capability={pendingOperation?.capability || null}
        deployments={pendingOperation?.deployments || []}
        operationType={pendingOperation?.operationType || 'update'}
      />


    </div>
  );
};

export default CapabilitySelection;

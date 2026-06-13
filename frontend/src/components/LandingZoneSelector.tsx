/**
 * Landing Zone Selector Component
 * 
 * Allows users to select cloud provider and manage landing zones
 * for capability discovery.
 */
import React, { useState, useEffect } from 'react';
import { discoveryApi, LandingZone, CreateLandingZoneRequest } from '../services/api';

interface LandingZoneSelectorProps {
  onSelect: (landingZone: LandingZone | null) => void;
  selectedLandingZone: LandingZone | null;
  awsSessionId?: string;
}

type CloudProvider = 'aws' | 'azure' | 'gcp';

const CLOUD_PROVIDERS: { id: CloudProvider; name: string; icon: string; supported: boolean }[] = [
  { id: 'aws', name: 'Amazon Web Services', icon: '☁️', supported: true },
  { id: 'azure', name: 'Microsoft Azure', icon: '🔷', supported: false },
  { id: 'gcp', name: 'Google Cloud Platform', icon: '🌐', supported: false },
];

const LandingZoneSelector: React.FC<LandingZoneSelectorProps> = ({
  onSelect,
  selectedLandingZone,
  awsSessionId,
}) => {
  const [selectedProvider, setSelectedProvider] = useState<CloudProvider>('aws');
  const [landingZones, setLandingZones] = useState<LandingZone[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  
  // Add form state
  const [newZoneName, setNewZoneName] = useState('');
  const [newZoneAccountId, setNewZoneAccountId] = useState('');
  const [newZoneRegion, setNewZoneRegion] = useState('ap-southeast-1');
  const [newZoneAlias, setNewZoneAlias] = useState('');
  const [addingZone, setAddingZone] = useState(false);

  useEffect(() => {
    loadLandingZones();
  }, [selectedProvider]);

  const loadLandingZones = async () => {
    try {
      setLoading(true);
      setError(null);
      const zones = await discoveryApi.listLandingZones(selectedProvider);
      setLandingZones(zones);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load landing zones');
      console.error('Error loading landing zones:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleAddLandingZone = async () => {
    if (!newZoneName || !newZoneAccountId) {
      setError('Name and Account ID are required');
      return;
    }

    try {
      setAddingZone(true);
      setError(null);
      
      const request: CreateLandingZoneRequest = {
        name: newZoneName,
        provider: selectedProvider,
        account_id: newZoneAccountId,
        default_region: newZoneRegion,
        account_alias: newZoneAlias || undefined,
      };
      
      const newZone = await discoveryApi.createLandingZone(request);
      setLandingZones(prev => [...prev, newZone]);
      onSelect(newZone);
      
      // Reset form
      setNewZoneName('');
      setNewZoneAccountId('');
      setNewZoneRegion('ap-southeast-1');
      setNewZoneAlias('');
      setShowAddForm(false);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create landing zone');
    } finally {
      setAddingZone(false);
    }
  };

  const handleDeleteLandingZone = async (zoneId: string) => {
    if (!confirm('Are you sure you want to delete this landing zone?')) return;
    
    try {
      await discoveryApi.deleteLandingZone(zoneId);
      setLandingZones(prev => prev.filter(z => z.landing_zone_id !== zoneId));
      if (selectedLandingZone?.landing_zone_id === zoneId) {
        onSelect(null);
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to delete landing zone');
    }
  };

  const formatDate = (dateString?: string): string => {
    if (!dateString) return 'Never';
    try {
      return new Date(dateString).toLocaleString();
    } catch {
      return dateString;
    }
  };

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4">
      <h3 className="text-lg font-semibold text-gray-900 mb-4">Landing Zones</h3>
      
      {/* Cloud Provider Selection */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Cloud Provider
        </label>
        <div className="flex gap-2">
          {CLOUD_PROVIDERS.map(provider => (
            <button
              key={provider.id}
              onClick={() => provider.supported && setSelectedProvider(provider.id)}
              disabled={!provider.supported}
              className={`flex items-center px-4 py-2 rounded-lg border-2 transition-colors ${
                selectedProvider === provider.id
                  ? 'border-blue-500 bg-blue-50 text-blue-700'
                  : provider.supported
                  ? 'border-gray-200 hover:border-gray-300 text-gray-700'
                  : 'border-gray-100 bg-gray-50 text-gray-400 cursor-not-allowed'
              }`}
            >
              <span className="mr-2">{provider.icon}</span>
              <span className="text-sm font-medium">{provider.name}</span>
              {!provider.supported && (
                <span className="ml-2 text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded">
                  Coming Soon
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          {error}
        </div>
      )}

      {/* Landing Zones List */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-2">
          <label className="block text-sm font-medium text-gray-700">
            {selectedProvider.toUpperCase()} Landing Zones
          </label>
          <button
            onClick={() => setShowAddForm(true)}
            className="text-sm text-blue-600 hover:text-blue-700 font-medium"
          >
            + Add Landing Zone
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600"></div>
            <span className="ml-2 text-gray-600">Loading...</span>
          </div>
        ) : landingZones.length === 0 ? (
          <div className="text-center py-8 bg-gray-50 rounded-lg border-2 border-dashed border-gray-200">
            <p className="text-gray-500">No landing zones configured</p>
            <p className="text-sm text-gray-400 mt-1">Add a landing zone to discover capabilities</p>
          </div>
        ) : (
          <div className="space-y-2">
            {landingZones.map(zone => (
              <div
                key={zone.landing_zone_id}
                onClick={() => onSelect(zone)}
                className={`p-3 rounded-lg border-2 cursor-pointer transition-colors ${
                  selectedLandingZone?.landing_zone_id === zone.landing_zone_id
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-gray-200 hover:border-gray-300'
                }`}
              >
                <div className="flex items-start justify-between">
                  <div>
                    <div className="font-medium text-gray-900">{zone.name}</div>
                    <div className="text-sm text-gray-500">
                      Account: {zone.account_id}
                      {zone.account_alias && ` (${zone.account_alias})`}
                    </div>
                    <div className="text-xs text-gray-400 mt-1">
                      Region: {zone.default_region} • 
                      Last Discovery: {formatDate(zone.last_discovery_at)} •
                      Capabilities: {zone.capabilities_count}
                    </div>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteLandingZone(zone.landing_zone_id);
                    }}
                    className="text-gray-400 hover:text-red-500 p-1"
                    title="Delete landing zone"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
                {zone.discovery_status === 'running' && (
                  <div className="mt-2 flex items-center text-xs text-blue-600">
                    <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-blue-600 mr-2"></div>
                    Discovery in progress...
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Add Landing Zone Form */}
      {showAddForm && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-md">
            <h4 className="text-lg font-semibold mb-4">Add Landing Zone</h4>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Name *
                </label>
                <input
                  type="text"
                  value={newZoneName}
                  onChange={(e) => setNewZoneName(e.target.value)}
                  placeholder="e.g., Production Account"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  AWS Account ID *
                </label>
                <input
                  type="text"
                  value={newZoneAccountId}
                  onChange={(e) => setNewZoneAccountId(e.target.value)}
                  placeholder="e.g., 123456789012"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Default Region
                </label>
                <select
                  value={newZoneRegion}
                  onChange={(e) => setNewZoneRegion(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                >
                  <option value="ap-southeast-1">ap-southeast-1 (Singapore)</option>
                  <option value="us-east-1">us-east-1 (N. Virginia)</option>
                  <option value="us-west-2">us-west-2 (Oregon)</option>
                  <option value="eu-west-1">eu-west-1 (Ireland)</option>
                  <option value="eu-central-1">eu-central-1 (Frankfurt)</option>
                </select>
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Account Alias (optional)
                </label>
                <input
                  type="text"
                  value={newZoneAlias}
                  onChange={(e) => setNewZoneAlias(e.target.value)}
                  placeholder="e.g., nexus-prod"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
              </div>
            </div>
            
            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => setShowAddForm(false)}
                className="px-4 py-2 text-gray-700 border border-gray-300 rounded-lg hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleAddLandingZone}
                disabled={addingZone || !newZoneName || !newZoneAccountId}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {addingZone ? 'Adding...' : 'Add Landing Zone'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default LandingZoneSelector;

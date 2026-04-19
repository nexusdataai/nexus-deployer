/**
 * UnifiedEnvironmentConfig Component
 * Main component that combines environment selection and infrastructure configuration
 * Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
 */
import React, { useState, useEffect, useCallback } from 'react';
import { useWizard } from '../context/WizardContext';
import { WizardStep } from '../types/wizard';
import { configApi } from '../services/api';
import { EnvironmentConfig } from '../types/config';
import { FrontendService, BackendService } from '../types/architecture';
import { EKSConfig, DEFAULT_EKS_CONFIG, generateDefaultNamespace } from '../types/eks';
import EnvironmentSelector, { ENVIRONMENTS } from './unified-config/EnvironmentSelector';
import { EnvironmentType } from './unified-config/EnvironmentBox';
import ConfigurationPanel, { ConfigTab } from './unified-config/ConfigurationPanel';
import EKSConfigurationPanel, { EKSConfigTab } from './unified-config/EKSConfigurationPanel';

// Fallback defaults if API fails
const FALLBACK_BASE_DOMAIN = 'totogicore.com';
const FALLBACK_HOSTED_ZONE_ID = 'Z084501638STQ2EKKSIA';

// Minimal fallback preset structure (used only if API fails)
const createFallbackPreset = (env: EnvironmentType): Partial<EnvironmentConfig> => ({
  infrastructure: {
    domain: { 
      base: FALLBACK_BASE_DOMAIN, 
      frontend_subdomain: env === 'prod' ? 'call' : `call-${env}`, 
      backend_subdomain: env === 'prod' ? 'call-api' : `call-api-${env}`, 
      hosted_zone_id: FALLBACK_HOSTED_ZONE_ID 
    },
    frontend: {
      cloudfront: { enabled: true, price_class: 'PriceClass_100', waf_enabled: false, cache_ttl: 86400, enable_logging: false, enable_ipv6: true, rate_limit: 2000 },
    },
    backend: {
      vpc: { create_new: true, enable_nat_gateway: false, enable_flow_logs: false },
      ecs: { container_port: 8000, task_cpu: 256, task_memory: 512, desired_count: 1, health_check_path: '/health' },
      autoscaling: { enabled: false, min_capacity: 1, max_capacity: 3, target_cpu: 70, target_memory: 80 },
      storage: { dynamodb_billing_mode: 'PAY_PER_REQUEST', enable_backup: false, enable_point_in_time_recovery: false, ecr_image_scan_on_push: true, ecr_image_retention_days: 7 },
      certificate: { create_in_foundation: true },
      alb: { enable_access_logs: false, deregistration_delay: 30, health_check_interval: 30, health_check_timeout: 5, healthy_threshold: 2, unhealthy_threshold: 3 },
    },
    monitoring: { cloudwatch: { log_retention_days: 7, container_insights: false } },
    tags: { common: { Environment: env, Project: '', CostCenter: '' } },
  },
});

const UnifiedEnvironmentConfig: React.FC = () => {
  const { state, setStep, setEnvironment, setInfrastructureConfig, setEKSConfig, setAwsRegion } = useWizard();
  
  // Determine if Pure EKS architecture is selected
  const isPureEKS = state.architectureConfig?.frontendService === FrontendService.EKS && 
                    state.architectureConfig?.backendService === BackendService.EKS;

  // Component state - Requirement 1.4: Production selected by default
  const [selectedEnvironment, setSelectedEnvironment] = useState<EnvironmentType>(
    (state.selectedEnvironment as EnvironmentType) || 'prod'
  );
  const [config, setConfig] = useState<EnvironmentConfig | null>(null);
  const [_originalConfig, setOriginalConfig] = useState<EnvironmentConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasChanges, setHasChanges] = useState(false);
  const [selectedRegion, setSelectedRegion] = useState<string>(state.awsRegion || 'ap-southeast-1');
  const [activeTab, setActiveTab] = useState<ConfigTab>('domain');
  const [eksActiveTab, setEksActiveTab] = useState<EKSConfigTab>('namespace');
  
  // EKS-specific configuration state
  const [eksConfig, setEksConfigLocal] = useState<Partial<EKSConfig>>(() => {
    // Initialize with existing state or defaults
    const defaultNamespace = state.selectedCapability 
      ? generateDefaultNamespace(state.selectedCapability.name, state.selectedEnvironment || 'prod')
      : '';
    return {
      ...DEFAULT_EKS_CONFIG,
      ...state.eksConfig,
      namespace: state.eksConfig?.namespace || defaultNamespace,
    };
  });
  
  // Environment presets loaded from API
  const [environmentPresets, setEnvironmentPresets] = useState<Record<string, any>>({});
  const [presetsLoaded, setPresetsLoaded] = useState(false);

  // Load environment presets from API on mount
  useEffect(() => {
    const loadPresets = async () => {
      try {
        const response = await configApi.getPresets();
        if (response.success && response.data?.presets) {
          setEnvironmentPresets(response.data.presets);
          console.log('Loaded environment presets from API');
        }
      } catch (err) {
        console.warn('Failed to load presets from API, using fallbacks:', err);
      } finally {
        setPresetsLoaded(true);
      }
    };
    loadPresets();
  }, []);

  // Helper to get preset for current environment
  const getPresetForEnvironment = useCallback((env: EnvironmentType): Partial<EnvironmentConfig> => {
    if (environmentPresets[env]) {
      return environmentPresets[env] as Partial<EnvironmentConfig>;
    }
    // Fallback if API presets not available
    return createFallbackPreset(env);
  }, [environmentPresets]);


  // Load configuration when environment changes - Requirement 3.1
  const loadConfiguration = useCallback(async () => {
    // Wait for presets to load first
    if (!presetsLoaded) {
      return;
    }

    if (!state.selectedCapability) {
      // Use preset if no capability selected
      const preset = getPresetForEnvironment(selectedEnvironment);
      setConfig(preset as EnvironmentConfig);
      setOriginalConfig(preset as EnvironmentConfig);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await configApi.getConfig(
        state.selectedCapability.name,
        selectedEnvironment
      );

      if (response.success && response.config) {
        setConfig(response.config);
        setOriginalConfig(response.config);
      } else {
        // Fall back to preset if no saved config
        const preset = getPresetForEnvironment(selectedEnvironment);
        setConfig(preset as EnvironmentConfig);
        setOriginalConfig(preset as EnvironmentConfig);
      }
    } catch (err: any) {
      // Fall back to preset on error
      const preset = getPresetForEnvironment(selectedEnvironment);
      setConfig(preset as EnvironmentConfig);
      setOriginalConfig(preset as EnvironmentConfig);
      console.warn('Failed to load config, using preset:', err);
    } finally {
      setLoading(false);
    }
  }, [state.selectedCapability, selectedEnvironment, presetsLoaded, getPresetForEnvironment]);

  useEffect(() => {
    if (presetsLoaded) {
      loadConfiguration();
    }
  }, [loadConfiguration, presetsLoaded]);

  // Handle environment change - Requirement 3.4: Preserve active tab
  const handleEnvironmentChange = (env: EnvironmentType) => {
    setSelectedEnvironment(env);
    setHasChanges(false);
    // activeTab is preserved automatically since we don't reset it
    
    // Update EKS namespace when environment changes
    if (isPureEKS && state.selectedCapability) {
      const newNamespace = generateDefaultNamespace(state.selectedCapability.name, env);
      setEksConfigLocal(prev => ({ ...prev, namespace: newNamespace }));
    }
  };

  // Handle config field change - Requirement 4.3: Track changes
  const handleConfigChange = (path: string[], value: any) => {
    if (!config) return;

    const newConfig = JSON.parse(JSON.stringify(config));
    let current: any = newConfig;

    for (let i = 0; i < path.length - 1; i++) {
      current = current[path[i]];
    }

    current[path[path.length - 1]] = value;
    setConfig(newConfig);
    setHasChanges(true);
  };

  // Handle EKS config field change
  const handleEKSConfigChange = (path: string[], value: any) => {
    const newConfig = JSON.parse(JSON.stringify(eksConfig));
    let current: any = newConfig;

    for (let i = 0; i < path.length - 1; i++) {
      if (!current[path[i]]) {
        current[path[i]] = {};
      }
      current = current[path[i]];
    }

    current[path[path.length - 1]] = value;
    setEksConfigLocal(newConfig);
    setHasChanges(true);
  };

  // Handle save - Requirement 4.6
  const handleSave = async () => {
    if (!config || !state.selectedCapability) {
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const response = await configApi.saveConfig(
        state.selectedCapability.name,
        selectedEnvironment,
        config
      );

      if (response.success) {
        setHasChanges(false);
        setOriginalConfig(config);
        alert('Configuration saved successfully!');
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to save configuration');
    } finally {
      setSaving(false);
    }
  };

  // Handle reset - Requirement 4.5
  const handleReset = async () => {
    if (!window.confirm('Reset to default configuration? This will discard your changes.')) {
      return;
    }

    if (isPureEKS) {
      // Reset EKS config to defaults
      const defaultNamespace = state.selectedCapability 
        ? generateDefaultNamespace(state.selectedCapability.name, selectedEnvironment)
        : '';
      setEksConfigLocal({
        ...DEFAULT_EKS_CONFIG,
        namespace: defaultNamespace,
      });
    } else {
      // Reset infrastructure config to preset
      const preset = getPresetForEnvironment(selectedEnvironment);
      setConfig(preset as EnvironmentConfig);
    }
    setHasChanges(false);
  };

  // Handle navigation - Requirement 1.5, 7.3, 7.4
  const handleNext = () => {
    if (!selectedRegion) {
      setError('Please select an AWS region');
      return;
    }

    // Store environment and config in wizard context
    setEnvironment(selectedEnvironment);
    setAwsRegion(selectedRegion);
    
    if (isPureEKS) {
      // Store EKS config for Pure EKS architecture
      setEKSConfig(eksConfig as EKSConfig);
    } else if (config) {
      // Store infrastructure config for ECS/CloudFront architecture
      setInfrastructureConfig(config);
    }
    
    setStep(WizardStep.AWS_CONFIGURATION);
  };

  const handleBack = () => {
    setStep(WizardStep.ARCHITECTURE_SELECTION);
  };


  // Loading state - Requirement 3.2
  if (loading) {
    return (
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-center h-96">
          <div className="text-center">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
            <p className="text-gray-600">Loading configuration...</p>
          </div>
        </div>
      </div>
    );
  }

  // Error state with no config - Requirement 3.3
  if (!config) {
    return (
      <div className="max-w-6xl mx-auto">
        <div className="bg-red-50 border border-red-200 rounded-lg p-6">
          <p className="text-red-800 mb-4">Failed to load configuration</p>
          <button
            onClick={loadConfiguration}
            className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto">
      {/* Header - Requirement 1.1, 1.2 */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">
          Environment & Infrastructure Configuration
        </h1>
        <p className="text-gray-600">
          Select your deployment environment and configure {isPureEKS ? 'Kubernetes' : 'infrastructure'} settings for{' '}
          {state.selectedCapability?.name || 'your capability'}
        </p>
        {isPureEKS && (
          <div className="mt-2 inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-purple-100 text-purple-800">
            <svg className="w-4 h-4 mr-1" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
            </svg>
            Pure EKS Architecture
          </div>
        )}
      </div>

      {/* Error message */}
      {error && (
        <div className="mb-6 bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-red-800">{error}</p>
        </div>
      )}

      {/* Unsaved changes warning - Requirement 4.4 */}
      {hasChanges && (
        <div className="mb-6 bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <p className="text-yellow-800">
            You have unsaved changes. Click "Save Configuration" to persist them.
          </p>
        </div>
      )}

      {/* Environment Selector - Requirement 1.1, 2.1-2.6 */}
      <EnvironmentSelector
        selectedEnvironment={selectedEnvironment}
        onEnvironmentChange={handleEnvironmentChange}
        disabled={loading || saving}
      />

      {/* AWS Region Selection - Requirement 1.3 */}
      <div className="bg-white rounded-lg shadow-md p-6 mb-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">AWS Region</h3>
        <p className="text-sm text-gray-600 mb-4">
          Select the AWS region where you want to deploy this capability.
        </p>
        <div className="max-w-md">
          <label htmlFor="region" className="block text-sm font-medium text-gray-700 mb-2">
            Deployment Region *
          </label>
          <select
            id="region"
            value={selectedRegion}
            onChange={(e) => setSelectedRegion(e.target.value)}
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            required
          >
            <option value="">Select a region...</option>
            <optgroup label="Asia Pacific">
              <option value="ap-south-1">Asia Pacific (Mumbai) - ap-south-1</option>
              <option value="ap-northeast-1">Asia Pacific (Tokyo) - ap-northeast-1</option>
              <option value="ap-northeast-2">Asia Pacific (Seoul) - ap-northeast-2</option>
              <option value="ap-northeast-3">Asia Pacific (Osaka) - ap-northeast-3</option>
              <option value="ap-southeast-1">Asia Pacific (Singapore) - ap-southeast-1</option>
              <option value="ap-southeast-2">Asia Pacific (Sydney) - ap-southeast-2</option>
            </optgroup>
            <optgroup label="Europe">
              <option value="eu-central-1">Europe (Frankfurt) - eu-central-1</option>
              <option value="eu-west-1">Europe (Ireland) - eu-west-1</option>
              <option value="eu-west-2">Europe (London) - eu-west-2</option>
              <option value="eu-west-3">Europe (Paris) - eu-west-3</option>
              <option value="eu-north-1">Europe (Stockholm) - eu-north-1</option>
            </optgroup>
            <optgroup label="North America">
              <option value="us-east-1">US East (N. Virginia) - us-east-1</option>
              <option value="us-east-2">US East (Ohio) - us-east-2</option>
              <option value="us-west-1">US West (N. California) - us-west-1</option>
              <option value="us-west-2">US West (Oregon) - us-west-2</option>
              <option value="ca-central-1">Canada (Central) - ca-central-1</option>
            </optgroup>
            <optgroup label="South America">
              <option value="sa-east-1">South America (São Paulo) - sa-east-1</option>
            </optgroup>
          </select>
          {selectedRegion && (
            <p className="mt-2 text-sm text-green-600">✓ Selected: {selectedRegion}</p>
          )}
        </div>
      </div>

      {/* Configuration Panel - Requirement 1.2, 4.1, 4.2 */}
      {/* Show architecture-specific configuration panel */}
      {isPureEKS ? (
        <EKSConfigurationPanel
          config={eksConfig}
          onConfigChange={handleEKSConfigChange}
          activeTab={eksActiveTab}
          onTabChange={setEksActiveTab}
        />
      ) : (
        <ConfigurationPanel
          config={config}
          onConfigChange={handleConfigChange}
          activeTab={activeTab}
          onTabChange={setActiveTab}
        />
      )}

      {/* Cost Summary */}
      <div className="mt-6 bg-white rounded-lg shadow-md p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-2">Estimated Monthly Cost</h3>
        {isPureEKS ? (
          <>
            <p className="text-2xl font-bold text-blue-600">
              {selectedEnvironment === 'prod' ? '$150 - $500+' : selectedEnvironment === 'stage' ? '$100 - $300' : '$75 - $150'}
            </p>
            <p className="text-sm text-gray-500 mt-1">
              EKS control plane ($0.10/hr) + Node costs + Load Balancer for {ENVIRONMENTS[selectedEnvironment].name} environment
            </p>
            <div className="mt-3 text-xs text-gray-400">
              <p>• EKS Control Plane: ~$73/month</p>
              <p>• Node costs depend on instance types and count</p>
              <p>• ALB: ~$16/month + data processing</p>
            </div>
          </>
        ) : (
          <>
            <p className="text-2xl font-bold text-blue-600">
              {ENVIRONMENTS[selectedEnvironment].estimatedCost}
            </p>
            <p className="text-sm text-gray-500 mt-1">
              Based on typical usage for {ENVIRONMENTS[selectedEnvironment].name} environment
            </p>
          </>
        )}
      </div>

      {/* Action Buttons - Requirement 1.5 */}
      <div className="mt-6 flex justify-between items-center">
        <button
          onClick={handleBack}
          className="px-6 py-3 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 font-medium"
        >
          Back
        </button>

        <div className="flex gap-3">
          <button
            onClick={handleReset}
            className="px-6 py-3 border border-red-300 text-red-700 rounded-lg hover:bg-red-50 font-medium"
            disabled={saving}
          >
            Reset to Defaults
          </button>

          {state.selectedCapability && (
            <button
              onClick={handleSave}
              className="px-6 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 font-medium disabled:opacity-50"
              disabled={!hasChanges || saving}
            >
              {saving ? 'Saving...' : 'Save Configuration'}
            </button>
          )}

          <button
            onClick={handleNext}
            className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium"
          >
            Continue
          </button>
        </div>
      </div>
    </div>
  );
};

export default UnifiedEnvironmentConfig;

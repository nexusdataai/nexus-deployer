/**
 * EKSConfigurationPanel Component
 * Tabbed panel for EKS-specific infrastructure configuration
 * Used when Pure EKS architecture is selected
 */
import React from 'react';
import { EKSConfig, DEFAULT_EKS_CONFIG } from '../../types/eks';

export type EKSConfigTab = 'namespace' | 'replicas' | 'resources' | 'autoscaling' | 'ingress';

interface EKSConfigurationPanelProps {
  config: Partial<EKSConfig>;
  onConfigChange: (path: string[], value: any) => void;
  activeTab: EKSConfigTab;
  onTabChange: (tab: EKSConfigTab) => void;
}

const TAB_LABELS: Record<EKSConfigTab, string> = {
  namespace: 'Namespace',
  replicas: 'Replicas',
  resources: 'Resources',
  autoscaling: 'Auto Scaling',
  ingress: 'Ingress & TLS',
};

const EKSConfigurationPanel: React.FC<EKSConfigurationPanelProps> = ({
  config,
  onConfigChange,
  activeTab,
  onTabChange,
}) => {
  const tabs: EKSConfigTab[] = ['namespace', 'replicas', 'resources', 'autoscaling', 'ingress'];
  const inputBaseClass = 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent';

  // Merge with defaults for safe access
  const mergedConfig = { ...DEFAULT_EKS_CONFIG, ...config };

  return (
    <div className="bg-white rounded-lg shadow-md" data-testid="eks-configuration-panel">
      {/* Tab Navigation */}
      <div className="border-b border-gray-200">
        <nav className="flex -mb-px" role="tablist">
          {tabs.map((tab) => (
            <button
              key={tab}
              onClick={() => onTabChange(tab)}
              role="tab"
              aria-selected={activeTab === tab}
              className={`px-6 py-4 text-sm font-medium border-b-2 ${
                activeTab === tab
                  ? 'border-blue-600 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              {TAB_LABELS[tab]}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab Content */}
      <div className="p-6">
        {activeTab === 'namespace' && (
          <NamespaceTab config={mergedConfig} onConfigChange={onConfigChange} inputClass={inputBaseClass} />
        )}
        {activeTab === 'replicas' && (
          <ReplicasTab config={mergedConfig} onConfigChange={onConfigChange} inputClass={inputBaseClass} />
        )}
        {activeTab === 'resources' && (
          <ResourcesTab config={mergedConfig} onConfigChange={onConfigChange} inputClass={inputBaseClass} />
        )}
        {activeTab === 'autoscaling' && (
          <AutoscalingTab config={mergedConfig} onConfigChange={onConfigChange} inputClass={inputBaseClass} />
        )}
        {activeTab === 'ingress' && (
          <IngressTab config={mergedConfig} onConfigChange={onConfigChange} inputClass={inputBaseClass} />
        )}
      </div>
    </div>
  );
};

interface TabProps {
  config: Partial<EKSConfig>;
  onConfigChange: (path: string[], value: any) => void;
  inputClass: string;
}


const NamespaceTab: React.FC<TabProps> = ({ config, onConfigChange, inputClass }) => {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Kubernetes Namespace</h3>
        <p className="text-sm text-gray-600 mb-4">
          Configure the namespace where your application will be deployed. Namespaces provide isolation between deployments.
        </p>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Namespace Name</label>
            <input
              type="text"
              value={config.namespace || ''}
              onChange={(e) => onConfigChange(['namespace'], e.target.value)}
              className={inputClass}
              placeholder="e.g., my-app-prod"
            />
            <p className="mt-1 text-xs text-gray-500">
              Must be lowercase, alphanumeric with hyphens, max 63 characters
            </p>
          </div>
          <div className="flex items-center pt-6">
            <input
              type="checkbox"
              checked={config.createNamespace ?? true}
              onChange={(e) => onConfigChange(['createNamespace'], e.target.checked)}
              className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
            />
            <label className="ml-2 text-sm font-medium text-gray-700">
              Create namespace if it doesn't exist
            </label>
          </div>
        </div>
      </div>

      <div>
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Deletion Policy</h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Resource Deletion Policy</label>
            <select
              value={config.deletionPolicy || 'Delete'}
              onChange={(e) => onConfigChange(['deletionPolicy'], e.target.value)}
              className={inputClass}
            >
              <option value="Delete">Delete - Remove resources when CR is deleted</option>
              <option value="Retain">Retain - Keep resources when CR is deleted</option>
            </select>
          </div>
        </div>
        <div className="mt-4 p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
          <p className="text-sm text-yellow-800">
            <strong>Note:</strong> "Retain" policy keeps AWS resources (S3, DynamoDB, etc.) even after uninstalling the capability.
            Use this for production environments to prevent accidental data loss.
          </p>
        </div>
      </div>
    </div>
  );
};

const ReplicasTab: React.FC<TabProps> = ({ config, onConfigChange, inputClass }) => {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Pod Replicas</h3>
        <p className="text-sm text-gray-600 mb-4">
          Configure the number of pod replicas for frontend and backend services. More replicas provide higher availability.
        </p>
        <div className="grid grid-cols-2 gap-6">
          <div className="p-4 border border-gray-200 rounded-lg">
            <h4 className="font-medium text-gray-900 mb-3">Frontend Replicas</h4>
            <input
              type="number"
              min="1"
              max="20"
              value={config.frontendReplicas ?? 2}
              onChange={(e) => onConfigChange(['frontendReplicas'], parseInt(e.target.value))}
              className={inputClass}
            />
            <p className="mt-1 text-xs text-gray-500">Recommended: 2+ for production</p>
          </div>
          <div className="p-4 border border-gray-200 rounded-lg">
            <h4 className="font-medium text-gray-900 mb-3">Backend Replicas</h4>
            <input
              type="number"
              min="1"
              max="20"
              value={config.backendReplicas ?? 2}
              onChange={(e) => onConfigChange(['backendReplicas'], parseInt(e.target.value))}
              className={inputClass}
            />
            <p className="mt-1 text-xs text-gray-500">Recommended: 2+ for production</p>
          </div>
        </div>
      </div>

      <div>
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Pod Disruption Budget</h3>
        <div className="grid grid-cols-2 gap-4">
          <div className="flex items-center col-span-2">
            <input
              type="checkbox"
              checked={config.pdb?.enabled ?? true}
              onChange={(e) => onConfigChange(['pdb', 'enabled'], e.target.checked)}
              className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
            />
            <label className="ml-2 text-sm font-medium text-gray-700">
              Enable Pod Disruption Budget (PDB)
            </label>
          </div>
          {config.pdb?.enabled && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Minimum Available Pods</label>
              <input
                type="number"
                min="0"
                value={config.pdb?.minAvailable ?? 1}
                onChange={(e) => onConfigChange(['pdb', 'minAvailable'], parseInt(e.target.value))}
                className={inputClass}
              />
              <p className="mt-1 text-xs text-gray-500">
                Ensures at least this many pods remain available during disruptions
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};


const ResourcesTab: React.FC<TabProps> = ({ config, onConfigChange, inputClass }) => {
  const cpuOptions = [
    { value: '100m', label: '100m (0.1 CPU)' },
    { value: '250m', label: '250m (0.25 CPU)' },
    { value: '500m', label: '500m (0.5 CPU)' },
    { value: '1000m', label: '1000m (1 CPU)' },
    { value: '2000m', label: '2000m (2 CPU)' },
  ];

  const memoryOptions = [
    { value: '128Mi', label: '128 MiB' },
    { value: '256Mi', label: '256 MiB' },
    { value: '512Mi', label: '512 MiB' },
    { value: '1Gi', label: '1 GiB' },
    { value: '2Gi', label: '2 GiB' },
    { value: '4Gi', label: '4 GiB' },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Frontend Resources</h3>
        <div className="grid grid-cols-2 gap-4">
          <div className="p-4 border border-gray-200 rounded-lg">
            <h4 className="font-medium text-gray-700 mb-3">Requests (Guaranteed)</h4>
            <div className="space-y-3">
              <div>
                <label className="block text-sm text-gray-600 mb-1">CPU</label>
                <select
                  value={config.frontendResources?.requests?.cpu || '100m'}
                  onChange={(e) => onConfigChange(['frontendResources', 'requests', 'cpu'], e.target.value)}
                  className={inputClass}
                >
                  {cpuOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm text-gray-600 mb-1">Memory</label>
                <select
                  value={config.frontendResources?.requests?.memory || '128Mi'}
                  onChange={(e) => onConfigChange(['frontendResources', 'requests', 'memory'], e.target.value)}
                  className={inputClass}
                >
                  {memoryOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>
            </div>
          </div>
          <div className="p-4 border border-gray-200 rounded-lg">
            <h4 className="font-medium text-gray-700 mb-3">Limits (Maximum)</h4>
            <div className="space-y-3">
              <div>
                <label className="block text-sm text-gray-600 mb-1">CPU</label>
                <select
                  value={config.frontendResources?.limits?.cpu || '500m'}
                  onChange={(e) => onConfigChange(['frontendResources', 'limits', 'cpu'], e.target.value)}
                  className={inputClass}
                >
                  {cpuOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm text-gray-600 mb-1">Memory</label>
                <select
                  value={config.frontendResources?.limits?.memory || '512Mi'}
                  onChange={(e) => onConfigChange(['frontendResources', 'limits', 'memory'], e.target.value)}
                  className={inputClass}
                >
                  {memoryOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div>
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Backend Resources</h3>
        <div className="grid grid-cols-2 gap-4">
          <div className="p-4 border border-gray-200 rounded-lg">
            <h4 className="font-medium text-gray-700 mb-3">Requests (Guaranteed)</h4>
            <div className="space-y-3">
              <div>
                <label className="block text-sm text-gray-600 mb-1">CPU</label>
                <select
                  value={config.backendResources?.requests?.cpu || '250m'}
                  onChange={(e) => onConfigChange(['backendResources', 'requests', 'cpu'], e.target.value)}
                  className={inputClass}
                >
                  {cpuOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm text-gray-600 mb-1">Memory</label>
                <select
                  value={config.backendResources?.requests?.memory || '512Mi'}
                  onChange={(e) => onConfigChange(['backendResources', 'requests', 'memory'], e.target.value)}
                  className={inputClass}
                >
                  {memoryOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>
            </div>
          </div>
          <div className="p-4 border border-gray-200 rounded-lg">
            <h4 className="font-medium text-gray-700 mb-3">Limits (Maximum)</h4>
            <div className="space-y-3">
              <div>
                <label className="block text-sm text-gray-600 mb-1">CPU</label>
                <select
                  value={config.backendResources?.limits?.cpu || '500m'}
                  onChange={(e) => onConfigChange(['backendResources', 'limits', 'cpu'], e.target.value)}
                  className={inputClass}
                >
                  {cpuOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm text-gray-600 mb-1">Memory</label>
                <select
                  value={config.backendResources?.limits?.memory || '1Gi'}
                  onChange={(e) => onConfigChange(['backendResources', 'limits', 'memory'], e.target.value)}
                  className={inputClass}
                >
                  {memoryOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
        <p className="text-sm text-blue-800">
          <strong>Tip:</strong> Requests are guaranteed resources. Limits are the maximum allowed.
          Set requests based on typical usage and limits for peak loads.
        </p>
      </div>
    </div>
  );
};


const AutoscalingTab: React.FC<TabProps> = ({ config, onConfigChange, inputClass }) => {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Horizontal Pod Autoscaler (HPA)</h3>
        <p className="text-sm text-gray-600 mb-4">
          Automatically scale pods based on CPU utilization. HPA adjusts replica count within the specified range.
        </p>
        <div className="grid grid-cols-2 gap-4">
          <div className="flex items-center col-span-2">
            <input
              type="checkbox"
              checked={config.hpa?.enabled ?? false}
              onChange={(e) => onConfigChange(['hpa', 'enabled'], e.target.checked)}
              className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
            />
            <label className="ml-2 text-sm font-medium text-gray-700">
              Enable Horizontal Pod Autoscaler
            </label>
          </div>
          
          {config.hpa?.enabled && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Minimum Replicas</label>
                <input
                  type="number"
                  min="1"
                  max="50"
                  value={config.hpa?.minReplicas ?? 2}
                  onChange={(e) => onConfigChange(['hpa', 'minReplicas'], parseInt(e.target.value))}
                  className={inputClass}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Maximum Replicas</label>
                <input
                  type="number"
                  min="1"
                  max="100"
                  value={config.hpa?.maxReplicas ?? 10}
                  onChange={(e) => onConfigChange(['hpa', 'maxReplicas'], parseInt(e.target.value))}
                  className={inputClass}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Target CPU Utilization (%)</label>
                <input
                  type="number"
                  min="10"
                  max="100"
                  value={config.hpa?.targetCPUUtilization ?? 70}
                  onChange={(e) => onConfigChange(['hpa', 'targetCPUUtilization'], parseInt(e.target.value))}
                  className={inputClass}
                />
                <p className="mt-1 text-xs text-gray-500">
                  Scale up when average CPU exceeds this threshold
                </p>
              </div>
            </>
          )}
        </div>
      </div>

      {config.hpa?.enabled && (
        <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
          <p className="text-sm text-blue-800">
            <strong>Note:</strong> When HPA is enabled, the replica counts in the Replicas tab become the initial values.
            HPA will automatically adjust replicas between min and max based on load.
          </p>
        </div>
      )}
    </div>
  );
};

const IngressTab: React.FC<TabProps> = ({ config, onConfigChange, inputClass }) => {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Ingress Configuration</h3>
        <p className="text-sm text-gray-600 mb-4">
          Configure how external traffic reaches your application. AWS Load Balancer Controller creates ALB/NLB resources.
        </p>
        <div className="grid grid-cols-2 gap-4">
          <div className="flex items-center col-span-2">
            <input
              type="checkbox"
              checked={config.ingress?.enabled ?? true}
              onChange={(e) => onConfigChange(['ingress', 'enabled'], e.target.checked)}
              className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
            />
            <label className="ml-2 text-sm font-medium text-gray-700">
              Enable Ingress (AWS Load Balancer)
            </label>
          </div>
          
          {config.ingress?.enabled && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Ingress Class</label>
                <select
                  value={config.ingress?.className || 'alb'}
                  onChange={(e) => onConfigChange(['ingress', 'className'], e.target.value)}
                  className={inputClass}
                >
                  <option value="alb">ALB (Application Load Balancer)</option>
                  <option value="nlb">NLB (Network Load Balancer)</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Custom Domain (Optional)</label>
                <input
                  type="text"
                  value={config.ingress?.customDomain || ''}
                  onChange={(e) => onConfigChange(['ingress', 'customDomain'], e.target.value)}
                  className={inputClass}
                  placeholder="e.g., app.example.com"
                />
              </div>
            </>
          )}
        </div>
      </div>

      {config.ingress?.enabled && (
        <div>
          <h3 className="text-lg font-semibold text-gray-900 mb-4">TLS Configuration</h3>
          <div className="grid grid-cols-2 gap-4">
            <div className="flex items-center col-span-2">
              <input
                type="checkbox"
                checked={config.ingress?.tls?.enabled ?? false}
                onChange={(e) => onConfigChange(['ingress', 'tls', 'enabled'], e.target.checked)}
                className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
              />
              <label className="ml-2 text-sm font-medium text-gray-700">
                Enable TLS/HTTPS
              </label>
            </div>
            
            {config.ingress?.tls?.enabled && (
              <>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">ACM Certificate ARN</label>
                  <input
                    type="text"
                    value={config.ingress?.tls?.certificateArn || ''}
                    onChange={(e) => onConfigChange(['ingress', 'tls', 'certificateArn'], e.target.value)}
                    className={inputClass}
                    placeholder="arn:aws:acm:region:account:certificate/id"
                  />
                  <p className="mt-1 text-xs text-gray-500">
                    AWS Certificate Manager certificate for HTTPS
                  </p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">TLS Secret Name (Optional)</label>
                  <input
                    type="text"
                    value={config.ingress?.tls?.secretName || ''}
                    onChange={(e) => onConfigChange(['ingress', 'tls', 'secretName'], e.target.value)}
                    className={inputClass}
                    placeholder="e.g., tls-secret"
                  />
                  <p className="mt-1 text-xs text-gray-500">
                    Kubernetes secret containing TLS cert (alternative to ACM)
                  </p>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
        <p className="text-sm text-yellow-800">
          <strong>Prerequisite:</strong> AWS Load Balancer Controller must be installed in your EKS cluster.
          The operator will verify this during deployment.
        </p>
      </div>
    </div>
  );
};

export default EKSConfigurationPanel;

/**
 * ConfigurationPanel Component
 * Tabbed panel for infrastructure configuration with field permissions
 */
import React from 'react';
import { EnvironmentConfig } from '../../types/config';
import { isFieldReadOnly, getFieldClassName } from './fieldPermissions';

export type ConfigTab = 'domain' | 'compute' | 'network' | 'monitoring' | 'tags';

interface ConfigurationPanelProps {
  config: EnvironmentConfig;
  onConfigChange: (path: string[], value: any) => void;
  activeTab: ConfigTab;
  onTabChange: (tab: ConfigTab) => void;
}

const TAB_LABELS: Record<ConfigTab, string> = {
  domain: 'Domain & CDN',
  compute: 'Compute & Scaling',
  network: 'Network & Storage',
  monitoring: 'Monitoring',
  tags: 'Tags',
};

const ConfigurationPanel: React.FC<ConfigurationPanelProps> = ({
  config,
  onConfigChange,
  activeTab,
  onTabChange,
}) => {
  const tabs: ConfigTab[] = ['domain', 'compute', 'network', 'monitoring', 'tags'];

  const inputBaseClass = 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent';

  const renderInput = (
    fieldPath: string,
    value: any,
    type: 'text' | 'number' | 'select' | 'checkbox' = 'text',
    options?: { value: string | number; label: string }[]
  ) => {
    const isReadOnly = isFieldReadOnly(fieldPath);
    const className = getFieldClassName(fieldPath, inputBaseClass);

    if (type === 'checkbox') {
      return (
        <input
          type="checkbox"
          checked={value}
          onChange={(e) => onConfigChange(fieldPath.split('.'), e.target.checked)}
          disabled={isReadOnly}
          className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded disabled:opacity-50"
          data-field={fieldPath}
        />
      );
    }

    if (type === 'select' && options) {
      return (
        <select
          value={value}
          onChange={(e) => {
            const newValue = typeof value === 'number' ? parseInt(e.target.value) : e.target.value;
            onConfigChange(fieldPath.split('.'), newValue);
          }}
          disabled={isReadOnly}
          className={className}
          data-field={fieldPath}
        >
          {options.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      );
    }

    return (
      <input
        type={type}
        value={value}
        onChange={(e) => {
          const newValue = type === 'number' ? parseInt(e.target.value) : e.target.value;
          onConfigChange(fieldPath.split('.'), newValue);
        }}
        disabled={isReadOnly}
        className={className}
        data-field={fieldPath}
      />
    );
  };

  return (
    <div className="bg-white rounded-lg shadow-md" data-testid="configuration-panel">
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
        {activeTab === 'domain' && (
          <DomainCDNTab config={config} renderInput={renderInput} />
        )}
        {activeTab === 'compute' && (
          <ComputeScalingTab config={config} renderInput={renderInput} />
        )}
        {activeTab === 'network' && (
          <NetworkStorageTab config={config} renderInput={renderInput} />
        )}
        {activeTab === 'monitoring' && (
          <MonitoringTab config={config} renderInput={renderInput} />
        )}
        {activeTab === 'tags' && (
          <TagsTab config={config} onConfigChange={onConfigChange} />
        )}
      </div>
    </div>
  );
};


interface TabProps {
  config: EnvironmentConfig;
  renderInput: (
    fieldPath: string,
    value: any,
    type?: 'text' | 'number' | 'select' | 'checkbox',
    options?: { value: string | number; label: string }[]
  ) => React.ReactNode;
}

const DomainCDNTab: React.FC<TabProps> = ({ config, renderInput }) => {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Domain Configuration</h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Base Domain</label>
            {renderInput('infrastructure.domain.base', config.infrastructure.domain.base || 'nexus.ai', 'text')}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Hosted Zone ID</label>
            {renderInput('infrastructure.domain.hosted_zone_id', config.infrastructure.domain.hosted_zone_id || 'Z084501638STQ2EKKSIA', 'text')}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Frontend Subdomain</label>
            {renderInput('infrastructure.domain.frontend_subdomain', config.infrastructure.domain.frontend_subdomain, 'text')}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Backend Subdomain</label>
            {renderInput('infrastructure.domain.backend_subdomain', config.infrastructure.domain.backend_subdomain, 'text')}
          </div>
        </div>
      </div>

      <div>
        <h3 className="text-lg font-semibold text-gray-900 mb-4">CloudFront CDN</h3>
        <div className="grid grid-cols-2 gap-4">
          <div className="flex items-center">
            {renderInput('infrastructure.frontend.cloudfront.enabled', config.infrastructure.frontend.cloudfront.enabled, 'checkbox')}
            <label className="ml-2 text-sm font-medium text-gray-700">Enable CloudFront CDN</label>
          </div>
          <div className="flex items-center">
            {renderInput('infrastructure.frontend.cloudfront.waf_enabled', config.infrastructure.frontend.cloudfront.waf_enabled, 'checkbox')}
            <label className="ml-2 text-sm font-medium text-gray-700">Enable WAF Protection</label>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Price Class</label>
            {renderInput('infrastructure.frontend.cloudfront.price_class', config.infrastructure.frontend.cloudfront.price_class, 'select', [
              { value: 'PriceClass_100', label: 'Price Class 100 (US, Europe)' },
              { value: 'PriceClass_200', label: 'Price Class 200 (Most regions)' },
              { value: 'PriceClass_All', label: 'Price Class All (All regions)' },
            ])}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Cache TTL (seconds)</label>
            {renderInput('infrastructure.frontend.cloudfront.cache_ttl', config.infrastructure.frontend.cloudfront.cache_ttl, 'number')}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Rate Limit (requests per 5 min)</label>
            {renderInput('infrastructure.frontend.cloudfront.rate_limit', config.infrastructure.frontend.cloudfront.rate_limit, 'number')}
          </div>
          <div className="flex items-center">
            {renderInput('infrastructure.frontend.cloudfront.enable_logging', config.infrastructure.frontend.cloudfront.enable_logging, 'checkbox')}
            <label className="ml-2 text-sm font-medium text-gray-700">Enable Logging</label>
          </div>
          <div className="flex items-center">
            {renderInput('infrastructure.frontend.cloudfront.enable_ipv6', config.infrastructure.frontend.cloudfront.enable_ipv6, 'checkbox')}
            <label className="ml-2 text-sm font-medium text-gray-700">Enable IPv6</label>
          </div>
        </div>
      </div>
    </div>
  );
};

const ComputeScalingTab: React.FC<TabProps> = ({ config, renderInput }) => {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-gray-900 mb-4">ECS Configuration</h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Container Port</label>
            {renderInput('infrastructure.backend.ecs.container_port', config.infrastructure.backend.ecs.container_port, 'number')}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Health Check Path</label>
            {renderInput('infrastructure.backend.ecs.health_check_path', config.infrastructure.backend.ecs.health_check_path, 'text')}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Task CPU (units)</label>
            {renderInput('infrastructure.backend.ecs.task_cpu', config.infrastructure.backend.ecs.task_cpu, 'select', [
              { value: 256, label: '256 (0.25 vCPU)' },
              { value: 512, label: '512 (0.5 vCPU)' },
              { value: 1024, label: '1024 (1 vCPU)' },
              { value: 2048, label: '2048 (2 vCPU)' },
              { value: 4096, label: '4096 (4 vCPU)' },
            ])}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Task Memory (MiB)</label>
            {renderInput('infrastructure.backend.ecs.task_memory', config.infrastructure.backend.ecs.task_memory, 'select', [
              { value: 512, label: '512 MiB' },
              { value: 1024, label: '1024 MiB (1 GB)' },
              { value: 2048, label: '2048 MiB (2 GB)' },
              { value: 4096, label: '4096 MiB (4 GB)' },
              { value: 8192, label: '8192 MiB (8 GB)' },
            ])}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Desired Task Count</label>
            {renderInput('infrastructure.backend.ecs.desired_count', config.infrastructure.backend.ecs.desired_count, 'number')}
          </div>
        </div>
      </div>

      <div>
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Auto Scaling</h3>
        <div className="grid grid-cols-2 gap-4">
          <div className="flex items-center col-span-2">
            {renderInput('infrastructure.backend.autoscaling.enabled', config.infrastructure.backend.autoscaling.enabled, 'checkbox')}
            <label className="ml-2 text-sm font-medium text-gray-700">Enable Auto Scaling</label>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Min Capacity</label>
            {renderInput('infrastructure.backend.autoscaling.min_capacity', config.infrastructure.backend.autoscaling.min_capacity, 'number')}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Max Capacity</label>
            {renderInput('infrastructure.backend.autoscaling.max_capacity', config.infrastructure.backend.autoscaling.max_capacity, 'number')}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Target CPU (%)</label>
            {renderInput('infrastructure.backend.autoscaling.target_cpu', config.infrastructure.backend.autoscaling.target_cpu, 'number')}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Target Memory (%)</label>
            {renderInput('infrastructure.backend.autoscaling.target_memory', config.infrastructure.backend.autoscaling.target_memory, 'number')}
          </div>
        </div>
      </div>
    </div>
  );
};

const NetworkStorageTab: React.FC<TabProps> = ({ config, renderInput }) => {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-gray-900 mb-4">VPC Configuration</h3>
        <div className="grid grid-cols-2 gap-4">
          <div className="flex items-center col-span-2">
            {renderInput('infrastructure.backend.vpc.create_new', config.infrastructure.backend.vpc.create_new, 'checkbox')}
            <label className="ml-2 text-sm font-medium text-gray-500">Create New VPC</label>
          </div>
          {config.infrastructure.backend.vpc.create_new ? (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-500 mb-2">VPC CIDR</label>
                {renderInput('infrastructure.backend.vpc.vpc_cidr', config.infrastructure.backend.vpc.vpc_cidr || '', 'text')}
              </div>
              <div className="flex items-center">
                {renderInput('infrastructure.backend.vpc.enable_nat_gateway', config.infrastructure.backend.vpc.enable_nat_gateway, 'checkbox')}
                <label className="ml-2 text-sm font-medium text-gray-500">Enable NAT Gateway</label>
              </div>
              <div className="flex items-center">
                {renderInput('infrastructure.backend.vpc.enable_flow_logs', config.infrastructure.backend.vpc.enable_flow_logs, 'checkbox')}
                <label className="ml-2 text-sm font-medium text-gray-500">Enable VPC Flow Logs</label>
              </div>
            </>
          ) : (
            <>
              <div className="col-span-2 p-3 bg-blue-50 border border-blue-200 rounded-lg">
                <p className="text-sm text-blue-700">Using existing VPC. Provide the VPC ID and subnet IDs below.</p>
              </div>
              <div className="col-span-2">
                <label className="block text-sm font-medium text-gray-500 mb-2">Existing VPC ID</label>
                {renderInput('infrastructure.backend.vpc.vpc_id', config.infrastructure.backend.vpc.vpc_id || '', 'text')}
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-500 mb-2">Public Subnet 1</label>
                {renderInput('infrastructure.backend.vpc.public_subnet_1', config.infrastructure.backend.vpc.public_subnet_1 || '', 'text')}
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-500 mb-2">Public Subnet 2</label>
                {renderInput('infrastructure.backend.vpc.public_subnet_2', config.infrastructure.backend.vpc.public_subnet_2 || '', 'text')}
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-500 mb-2">Private Subnet 1</label>
                {renderInput('infrastructure.backend.vpc.private_subnet_1', config.infrastructure.backend.vpc.private_subnet_1 || '', 'text')}
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-500 mb-2">Private Subnet 2</label>
                {renderInput('infrastructure.backend.vpc.private_subnet_2', config.infrastructure.backend.vpc.private_subnet_2 || '', 'text')}
              </div>
            </>
          )}
        </div>
      </div>

      <div>
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Storage Configuration</h3>
        <div className="mb-2 p-3 bg-gray-50 border border-gray-200 rounded-lg">
          <p className="text-sm text-gray-600">Storage settings are determined by the environment preset and cannot be modified.</p>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">DynamoDB Billing Mode</label>
            {renderInput('infrastructure.backend.storage.dynamodb_billing_mode', config.infrastructure.backend.storage.dynamodb_billing_mode, 'select', [
              { value: 'PAY_PER_REQUEST', label: 'Pay Per Request' },
              { value: 'PROVISIONED', label: 'Provisioned' },
            ])}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">ECR Image Retention (days)</label>
            {renderInput('infrastructure.backend.storage.ecr_image_retention_days', config.infrastructure.backend.storage.ecr_image_retention_days, 'number')}
          </div>
          <div className="flex items-center">
            {renderInput('infrastructure.backend.storage.enable_backup', config.infrastructure.backend.storage.enable_backup, 'checkbox')}
            <label className="ml-2 text-sm font-medium text-gray-500">Enable Automated Backups</label>
          </div>
          <div className="flex items-center">
            {renderInput('infrastructure.backend.storage.enable_point_in_time_recovery', config.infrastructure.backend.storage.enable_point_in_time_recovery, 'checkbox')}
            <label className="ml-2 text-sm font-medium text-gray-500">Enable Point-in-Time Recovery</label>
          </div>
          <div className="flex items-center">
            {renderInput('infrastructure.backend.storage.ecr_image_scan_on_push', config.infrastructure.backend.storage.ecr_image_scan_on_push, 'checkbox')}
            <label className="ml-2 text-sm font-medium text-gray-500">Scan ECR Images on Push</label>
          </div>
        </div>
      </div>

      <div>
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Load Balancer</h3>
        <div className="mb-2 p-3 bg-gray-50 border border-gray-200 rounded-lg">
          <p className="text-sm text-gray-600">ALB settings are determined by the environment preset and cannot be modified.</p>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">Health Check Interval (seconds)</label>
            {renderInput('infrastructure.backend.alb.health_check_interval', config.infrastructure.backend.alb.health_check_interval, 'number')}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">Health Check Timeout (seconds)</label>
            {renderInput('infrastructure.backend.alb.health_check_timeout', config.infrastructure.backend.alb.health_check_timeout, 'number')}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">Healthy Threshold</label>
            {renderInput('infrastructure.backend.alb.healthy_threshold', config.infrastructure.backend.alb.healthy_threshold, 'number')}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">Unhealthy Threshold</label>
            {renderInput('infrastructure.backend.alb.unhealthy_threshold', config.infrastructure.backend.alb.unhealthy_threshold, 'number')}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">Deregistration Delay (seconds)</label>
            {renderInput('infrastructure.backend.alb.deregistration_delay', config.infrastructure.backend.alb.deregistration_delay, 'number')}
          </div>
          <div className="flex items-center">
            {renderInput('infrastructure.backend.alb.enable_access_logs', config.infrastructure.backend.alb.enable_access_logs, 'checkbox')}
            <label className="ml-2 text-sm font-medium text-gray-500">Enable ALB Access Logs</label>
          </div>
        </div>
      </div>
    </div>
  );
};

const MonitoringTab: React.FC<TabProps> = ({ config, renderInput }) => {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-gray-900 mb-4">CloudWatch Monitoring</h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Log Retention (days)</label>
            {renderInput('infrastructure.monitoring.cloudwatch.log_retention_days', config.infrastructure.monitoring.cloudwatch.log_retention_days, 'select', [
              { value: 1, label: '1 day' },
              { value: 3, label: '3 days' },
              { value: 7, label: '7 days' },
              { value: 14, label: '14 days' },
              { value: 30, label: '30 days' },
              { value: 60, label: '60 days' },
              { value: 90, label: '90 days' },
              { value: 180, label: '180 days' },
              { value: 365, label: '365 days' },
            ])}
          </div>
          <div className="flex items-center">
            {renderInput('infrastructure.monitoring.cloudwatch.container_insights', config.infrastructure.monitoring.cloudwatch.container_insights, 'checkbox')}
            <label className="ml-2 text-sm font-medium text-gray-700">Enable Container Insights</label>
          </div>
        </div>
        <div className="mt-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
          <p className="text-sm text-blue-800">
            <strong>Note:</strong> Container Insights provides detailed metrics for ECS tasks but incurs additional CloudWatch costs.
          </p>
        </div>
      </div>
    </div>
  );
};

interface TagsTabProps {
  config: EnvironmentConfig;
  onConfigChange: (path: string[], value: any) => void;
}

const TagsTab: React.FC<TagsTabProps> = ({ config, onConfigChange }) => {
  const handleAddTag = () => {
    const newKey = prompt('Enter tag key:');
    if (newKey && newKey.trim()) {
      const newTags = { ...config.infrastructure.tags.common };
      newTags[newKey.trim()] = '';
      onConfigChange(['infrastructure', 'tags', 'common'], newTags);
    }
  };

  const handleRemoveTag = (key: string) => {
    const newTags = { ...config.infrastructure.tags.common };
    delete newTags[key];
    onConfigChange(['infrastructure', 'tags', 'common'], newTags);
  };

  const handleTagValueChange = (key: string, value: string) => {
    const newTags = { ...config.infrastructure.tags.common };
    newTags[key] = value;
    onConfigChange(['infrastructure', 'tags', 'common'], newTags);
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-gray-900 mb-4">AWS Resource Tags</h3>
        <p className="text-sm text-gray-600 mb-4">
          Tags are applied to all AWS resources created during deployment. Use tags for cost tracking, organization, and resource management.
        </p>

        <div className="space-y-4">
          {Object.entries(config.infrastructure.tags.common).map(([key, value]) => (
            <div key={key} className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  {key}
                </label>
                <input
                  type="text"
                  value={value}
                  onChange={(e) => handleTagValueChange(key, e.target.value)}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder={`Enter ${key}`}
                  data-field={`infrastructure.tags.common.${key}`}
                />
              </div>
              <div className="flex items-end">
                <button
                  onClick={() => handleRemoveTag(key)}
                  className="px-4 py-2 text-sm text-red-600 hover:text-red-700 hover:bg-red-50 rounded-lg"
                >
                  Remove
                </button>
              </div>
            </div>
          ))}

          <div className="pt-4 border-t border-gray-200">
            <button
              onClick={handleAddTag}
              className="px-4 py-2 text-sm text-blue-600 hover:text-blue-700 hover:bg-blue-50 rounded-lg font-medium"
            >
              + Add Custom Tag
            </button>
          </div>
        </div>

        <div className="mt-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
          <p className="text-sm text-blue-800">
            <strong>Best Practices:</strong>
          </p>
          <ul className="mt-2 text-sm text-blue-800 list-disc list-inside space-y-1">
            <li>Use consistent tag keys across all resources</li>
            <li>Include Project, Environment, and CostCenter for cost tracking</li>
            <li>Add Team and Application tags for ownership identification</li>
            <li>Keep tag values concise and meaningful</li>
          </ul>
        </div>
      </div>
    </div>
  );
};

export default ConfigurationPanel;

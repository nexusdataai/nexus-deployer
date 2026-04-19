/**
 * EnvironmentSelector Component
 * Displays all environment options as selectable boxes in a horizontal row
 */
import React from 'react';
import EnvironmentBox, { EnvironmentType, EnvironmentInfo } from './EnvironmentBox';

// Environment configurations
export const ENVIRONMENTS: Record<EnvironmentType, EnvironmentInfo> = {
  dev: {
    id: 'dev',
    name: 'Development',
    description: 'Lower resources, cost-optimized for development and testing',
    features: [
      'No NAT Gateway',
      'Minimal auto-scaling',
      'Single AZ deployment',
      'Reduced instance sizes',
    ],
    estimatedCost: '$40-80/month',
    badge: 'dev',
  },
  test: {
    id: 'test',
    name: 'Test',
    description: 'Similar to dev, isolated environment for testing',
    features: [
      'Isolated from dev',
      'Minimal auto-scaling',
      'Single AZ deployment',
      'Test data isolation',
    ],
    estimatedCost: '$40-80/month',
    badge: 'test',
  },
  stage: {
    id: 'stage',
    name: 'Staging',
    description: 'Production-like environment for final testing',
    features: [
      'Full features enabled',
      'Moderate auto-scaling',
      'Multi-AZ deployment',
      'Production-like configuration',
    ],
    estimatedCost: '$150-300/month',
    badge: 'stage',
  },
  prod: {
    id: 'prod',
    name: 'Production',
    description: 'Full HA, auto-scaling, and backups for production workloads',
    features: [
      'High availability',
      'Full auto-scaling',
      'Multi-AZ deployment',
      'Enhanced monitoring',
      'Automated backups',
    ],
    estimatedCost: '$250-500/month',
    badge: 'prod',
  },
};

// Order of environments to display
const ENVIRONMENT_ORDER: EnvironmentType[] = ['dev', 'test', 'stage', 'prod'];

interface EnvironmentSelectorProps {
  selectedEnvironment: EnvironmentType;
  onEnvironmentChange: (env: EnvironmentType) => void;
  disabled?: boolean;
}

const EnvironmentSelector: React.FC<EnvironmentSelectorProps> = ({
  selectedEnvironment,
  onEnvironmentChange,
  disabled = false,
}) => {
  return (
    <div className="bg-white rounded-lg shadow-md p-6 mb-6">
      <h3 className="text-lg font-semibold text-gray-900 mb-2">Deployment Environment</h3>
      <p className="text-sm text-gray-600 mb-4">
        Select the target environment for your deployment. Each environment has different resource configurations and costs.
      </p>
      
      <div 
        data-testid="environment-selector"
        className="flex flex-wrap gap-4"
      >
        {ENVIRONMENT_ORDER.map((envId) => (
          <EnvironmentBox
            key={envId}
            environment={ENVIRONMENTS[envId]}
            isSelected={selectedEnvironment === envId}
            onClick={() => onEnvironmentChange(envId)}
            disabled={disabled}
          />
        ))}
      </div>

      {/* Cost info box */}
      <div className="mt-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
        <div className="flex items-start">
          <svg
            className="w-5 h-5 text-blue-600 mr-2 mt-0.5 flex-shrink-0"
            fill="currentColor"
            viewBox="0 0 20 20"
          >
            <path
              fillRule="evenodd"
              d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
              clipRule="evenodd"
            />
          </svg>
          <p className="text-sm text-blue-800">
            Cost estimates are based on typical usage patterns. Actual costs may vary based on usage, data transfer, and other factors.
          </p>
        </div>
      </div>
    </div>
  );
};

export default EnvironmentSelector;
export type { EnvironmentType, EnvironmentInfo };

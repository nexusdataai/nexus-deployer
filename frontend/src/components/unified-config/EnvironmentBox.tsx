/**
 * EnvironmentBox Component
 * Displays a single environment option as a selectable compact box
 */
import React, { useState } from 'react';

export type EnvironmentType = 'dev' | 'test' | 'stage' | 'prod';

export interface EnvironmentInfo {
  id: EnvironmentType;
  name: string;
  description: string;
  features: string[];
  estimatedCost: string;
  badge: string;
}

interface EnvironmentBoxProps {
  environment: EnvironmentInfo;
  isSelected: boolean;
  onClick: () => void;
  disabled?: boolean;
}

const EnvironmentBox: React.FC<EnvironmentBoxProps> = ({
  environment,
  isSelected,
  onClick,
  disabled = false,
}) => {
  const [showTooltip, setShowTooltip] = useState(false);

  return (
    <div className="relative">
      <div
        data-env={environment.id}
        data-testid={`env-box-${environment.id}`}
        onClick={disabled ? undefined : onClick}
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
        className={`
          relative p-4 rounded-lg border-2 transition-all cursor-pointer min-w-[140px]
          ${isSelected 
            ? 'ring-2 ring-blue-600 border-blue-600 bg-blue-50 shadow-md' 
            : 'border-gray-200 bg-white hover:border-gray-300 hover:shadow-sm'
          }
          ${disabled ? 'opacity-50 cursor-not-allowed' : ''}
        `}
      >
        {/* Selection indicator */}
        {isSelected && (
          <div className="absolute top-2 right-2">
            <svg className="w-5 h-5 text-blue-600" fill="currentColor" viewBox="0 0 20 20">
              <path
                fillRule="evenodd"
                d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                clipRule="evenodd"
              />
            </svg>
          </div>
        )}

        {/* Environment name */}
        <h3 
          data-testid={`env-name-${environment.id}`}
          className={`text-base font-semibold mb-1 ${isSelected ? 'text-blue-900' : 'text-gray-900'}`}
        >
          {environment.name}
        </h3>

        {/* Badge */}
        <span 
          data-testid={`env-badge-${environment.id}`}
          className={`
            inline-block px-2 py-0.5 text-xs font-medium rounded mb-2
            ${isSelected ? 'bg-blue-200 text-blue-800' : 'bg-gray-100 text-gray-600'}
          `}
        >
          {environment.badge}
        </span>

        {/* Cost estimate */}
        <div 
          data-testid={`env-cost-${environment.id}`}
          className={`text-sm font-medium ${isSelected ? 'text-blue-700' : 'text-gray-700'}`}
        >
          {environment.estimatedCost}
        </div>
      </div>

      {/* Tooltip with features */}
      {showTooltip && (
        <div 
          data-testid={`env-tooltip-${environment.id}`}
          className="absolute z-10 top-full left-0 mt-2 w-64 p-3 bg-gray-900 text-white text-sm rounded-lg shadow-lg"
        >
          <p className="font-medium mb-2">{environment.description}</p>
          <ul className="space-y-1">
            {environment.features.map((feature, index) => (
              <li key={index} className="flex items-start">
                <svg className="w-4 h-4 text-green-400 mr-2 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                  <path
                    fillRule="evenodd"
                    d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                    clipRule="evenodd"
                  />
                </svg>
                {feature}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

export default EnvironmentBox;

/**
 * ServiceOptionCard Component
 * Displays a selectable AWS service option with icon, description, and cost tier
 */
import React from 'react';
import { ServiceOptionMeta } from '../types/architecture';
import { getServiceIcon } from '../utils/awsIcons';

interface ServiceOptionCardProps {
  option: ServiceOptionMeta;
  isSelected: boolean;
  onSelect: () => void;
  disabled?: boolean;
}

const getCostTierDisplay = (tier: string): string => {
  switch (tier) {
    case 'low': return '$';
    case 'medium': return '$$';
    case 'high': return '$$$';
    default: return '$';
  }
};

const ServiceOptionCard: React.FC<ServiceOptionCardProps> = ({
  option,
  isSelected,
  onSelect,
  disabled = false,
}) => {
  const isDisabled = option.availability === 'coming_soon' || disabled;
  const IconComponent = getServiceIcon(option.icon);

  const handleClick = () => {
    if (!isDisabled) {
      onSelect();
    }
  };

  return (
    <div
      onClick={handleClick}
      className={`
        relative p-4 rounded-lg border-2 transition-all duration-200
        ${isDisabled 
          ? 'opacity-60 cursor-not-allowed bg-gray-50 border-gray-200' 
          : 'cursor-pointer hover:shadow-md'
        }
        ${isSelected && !isDisabled
          ? 'border-blue-500 bg-blue-50 shadow-md ring-2 ring-blue-200'
          : !isDisabled ? 'border-gray-200 bg-white hover:border-blue-300' : ''
        }
      `}
      role="button"
      tabIndex={isDisabled ? -1 : 0}
      aria-selected={isSelected}
      aria-disabled={isDisabled}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          handleClick();
        }
      }}
    >
      {/* Coming Soon Badge */}
      {isDisabled && (
        <span className="absolute top-2 right-2 px-2 py-1 text-xs font-medium bg-gray-200 text-gray-600 rounded">
          Coming Soon
        </span>
      )}

      {/* Icon and Name */}
      <div className="flex items-center mb-3">
        <IconComponent className="w-10 h-10 mr-3" />
        <div>
          <h4 className="font-semibold text-gray-900">{option.name}</h4>
          <span className={`text-sm font-medium ${
            option.costTier === 'low' ? 'text-green-600' :
            option.costTier === 'medium' ? 'text-yellow-600' :
            'text-red-600'
          }`}>
            {getCostTierDisplay(option.costTier)}
          </span>
        </div>
      </div>

      {/* Description */}
      <p className="text-sm text-gray-600 mb-3">{option.description}</p>

      {/* Features */}
      <div className="flex flex-wrap gap-1">
        {option.features.slice(0, 3).map((feature, idx) => (
          <span
            key={idx}
            className="px-2 py-0.5 text-xs bg-gray-100 text-gray-600 rounded"
          >
            {feature}
          </span>
        ))}
        {option.features.length > 3 && (
          <span className="px-2 py-0.5 text-xs bg-gray-100 text-gray-500 rounded">
            +{option.features.length - 3} more
          </span>
        )}
      </div>

      {/* Selection Indicator */}
      {isSelected && !isDisabled && (
        <div className="absolute top-2 right-2">
          <svg className="w-6 h-6 text-blue-500" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
          </svg>
        </div>
      )}
    </div>
  );
};

export default ServiceOptionCard;

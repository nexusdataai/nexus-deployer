/**
 * IAM Permission Panel Component
 * Displays categorized IAM permissions required for deployment
 */
import React, { useState } from 'react';
import { PERMISSION_CATEGORIES, PermissionCategory, ServicePermission } from '../data/permission-data';
import { generateFullDeploymentPolicy, downloadPolicy } from '../utils/policy-generator';

interface IAMPermissionPanelProps {
  expanded?: boolean;
  onToggle?: () => void;
}

const IAMPermissionPanel: React.FC<IAMPermissionPanelProps> = ({
  expanded: controlledExpanded,
  onToggle
}) => {
  const [internalExpanded, setInternalExpanded] = useState(false);
  const [expandedCategory, setExpandedCategory] = useState<string | null>(null);
  const [expandedService, setExpandedService] = useState<string | null>(null);

  // Support both controlled and uncontrolled modes
  const isExpanded = controlledExpanded !== undefined ? controlledExpanded : internalExpanded;
  
  const handleToggle = () => {
    if (onToggle) {
      onToggle();
    } else {
      setInternalExpanded(!internalExpanded);
    }
  };

  const handleDownloadPolicy = () => {
    const policy = generateFullDeploymentPolicy();
    downloadPolicy(policy, 'deployment-role-policy.json');
  };

  const toggleCategory = (categoryName: string) => {
    setExpandedCategory(expandedCategory === categoryName ? null : categoryName);
    setExpandedService(null);
  };

  const toggleService = (serviceName: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpandedService(expandedService === serviceName ? null : serviceName);
  };

  const getTotalPermissionCount = () => {
    let count = 0;
    for (const category of PERMISSION_CATEGORIES) {
      for (const service of category.services) {
        count += service.allActions.length;
      }
    }
    return count;
  };

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      {/* Header - Always visible */}
      <button
        onClick={handleToggle}
        className="w-full px-4 py-3 bg-gray-50 hover:bg-gray-100 flex items-center justify-between transition-colors"
        aria-expanded={isExpanded}
      >
        <div className="flex items-center">
          <svg
            className={`w-5 h-5 text-gray-500 mr-2 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
            fill="currentColor"
            viewBox="0 0 20 20"
          >
            <path
              fillRule="evenodd"
              d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z"
              clipRule="evenodd"
            />
          </svg>
          <span className="font-medium text-gray-900">Required IAM Permissions</span>
          <span className="ml-2 text-sm text-gray-500">
            ({getTotalPermissionCount()} actions across {PERMISSION_CATEGORIES.length} categories)
          </span>
        </div>
        <div className="flex items-center">
          <span className="text-xs text-blue-600 mr-2">
            {isExpanded ? 'Click to collapse' : 'Click to expand'}
          </span>
        </div>
      </button>

      {/* Expanded Content */}
      {isExpanded && (
        <div className="p-4 border-t border-gray-200">
          {/* Download Button */}
          <div className="mb-4 flex justify-between items-center">
            <p className="text-sm text-gray-600">
              The deployment role needs the following permissions to create and manage AWS resources.
            </p>
            <button
              onClick={handleDownloadPolicy}
              className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 flex items-center"
            >
              <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Download Full Policy
            </button>
          </div>

          {/* Permission Categories */}
          <div className="space-y-2">
            {PERMISSION_CATEGORIES.map((category) => (
              <CategorySection
                key={category.name}
                category={category}
                isExpanded={expandedCategory === category.name}
                expandedService={expandedService}
                onToggle={() => toggleCategory(category.name)}
                onServiceToggle={toggleService}
              />
            ))}
          </div>

          {/* Info Box */}
          <div className="mt-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
            <div className="flex items-start">
              <svg className="w-5 h-5 text-blue-600 mr-2 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
              </svg>
              <div className="text-sm text-blue-800">
                <p className="font-medium">Principle of Least Privilege</p>
                <p className="mt-1">
                  The downloaded policy includes all permissions needed for deployment. You can further 
                  restrict resource ARNs based on your naming conventions and security requirements.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

interface CategorySectionProps {
  category: PermissionCategory;
  isExpanded: boolean;
  expandedService: string | null;
  onToggle: () => void;
  onServiceToggle: (serviceName: string, e: React.MouseEvent) => void;
}

const CategorySection: React.FC<CategorySectionProps> = ({
  category,
  isExpanded,
  expandedService,
  onToggle,
  onServiceToggle
}) => {
  const totalActions = category.services.reduce((sum, s) => sum + s.allActions.length, 0);

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full px-4 py-3 bg-white hover:bg-gray-50 flex items-center justify-between"
        aria-expanded={isExpanded}
      >
        <div className="flex items-center">
          <svg
            className={`w-4 h-4 text-gray-400 mr-2 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
            fill="currentColor"
            viewBox="0 0 20 20"
          >
            <path
              fillRule="evenodd"
              d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z"
              clipRule="evenodd"
            />
          </svg>
          <span className="font-medium text-gray-800">{category.name}</span>
        </div>
        <div className="flex items-center text-sm text-gray-500">
          <span>{category.services.length} services</span>
          <span className="mx-2">•</span>
          <span>{totalActions} actions</span>
        </div>
      </button>

      {isExpanded && (
        <div className="border-t border-gray-200 bg-gray-50 p-3">
          <p className="text-sm text-gray-600 mb-3">{category.description}</p>
          <div className="space-y-2">
            {category.services.map((service) => (
              <ServiceItem
                key={service.service}
                service={service}
                isExpanded={expandedService === service.service}
                onToggle={(e) => onServiceToggle(service.service, e)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

interface ServiceItemProps {
  service: ServicePermission;
  isExpanded: boolean;
  onToggle: (e: React.MouseEvent) => void;
}

const ServiceItem: React.FC<ServiceItemProps> = ({ service, isExpanded, onToggle }) => {
  return (
    <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full px-3 py-2 flex items-center justify-between hover:bg-gray-50"
        aria-expanded={isExpanded}
      >
        <div className="flex items-center">
          <svg
            className={`w-3 h-3 text-gray-400 mr-2 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
            fill="currentColor"
            viewBox="0 0 20 20"
          >
            <path
              fillRule="evenodd"
              d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z"
              clipRule="evenodd"
            />
          </svg>
          <span className="font-medium text-gray-700 text-sm">{service.service}</span>
        </div>
        <span className="text-xs text-gray-500">{service.allActions.length} actions</span>
      </button>

      {isExpanded && (
        <div className="border-t border-gray-200 p-3 bg-gray-50">
          <p className="text-xs text-gray-600 mb-2">{service.purpose}</p>
          
          {/* Key Actions */}
          <div className="mb-2">
            <p className="text-xs font-medium text-gray-700 mb-1">Key Actions:</p>
            <div className="flex flex-wrap gap-1">
              {service.keyActions.map((action) => (
                <span
                  key={action}
                  className="px-2 py-0.5 bg-blue-100 text-blue-800 text-xs rounded"
                >
                  {action}
                </span>
              ))}
            </div>
          </div>

          {/* All Actions */}
          <div>
            <p className="text-xs font-medium text-gray-700 mb-1">All Actions:</p>
            <div className="max-h-32 overflow-y-auto">
              <ul className="text-xs text-gray-600 space-y-0.5">
                {service.allActions.map((action) => (
                  <li key={action} className="font-mono">{action}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default IAMPermissionPanel;

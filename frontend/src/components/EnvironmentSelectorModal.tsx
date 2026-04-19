/**
 * Environment Selector Modal Component
 * Allows users to select which specific deployment environment to update or delete
 * when a capability has multiple active deployments.
 */
import React, { useEffect, useCallback, useState } from 'react';
import { Capability } from '../types/capability';

export interface DeploymentState {
  capability_name: string;
  environment: string;
  region: string;
  last_deployment: string;
  status?: string;
  strategy?: string;  // 'DEPLOYED' or 'DISCOVERED'
  // Requirement 11.2: Indicate which landing zone each capability belongs to
  landing_zone_id?: string;
  account_id?: string;
  stacks: Array<{
    stack_name: string;
    stack_type: string;
    region: string;
  }>;
  metadata?: {
    frontend_url?: string;
    backend_url?: string;
  };
}

export interface EnvironmentSelectorModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (deployment: DeploymentState) => void;
  capability: Capability | null;
  deployments: DeploymentState[];
  operationType: 'update' | 'delete';
}

/**
 * Sorts deployments with PROD first, then alphabetically by environment name
 */
export const sortDeployments = (deployments: DeploymentState[]): DeploymentState[] => {
  return [...deployments].sort((a, b) => {
    const aIsProd = a.environment.toLowerCase() === 'prod';
    const bIsProd = b.environment.toLowerCase() === 'prod';
    
    if (aIsProd && !bIsProd) return -1;
    if (!aIsProd && bIsProd) return 1;
    return a.environment.localeCompare(b.environment);
  });
};

/**
 * Checks if an environment is a production environment
 */
export const isProductionEnvironment = (environment: string): boolean => {
  return environment.toLowerCase() === 'prod' || environment.toLowerCase() === 'production';
};


/**
 * Formats a date string for display
 */
const formatDate = (dateString: string): string => {
  try {
    const date = new Date(dateString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { 
      hour: '2-digit', 
      minute: '2-digit' 
    });
  } catch {
    return dateString;
  }
};

/**
 * Production Delete Confirmation Dialog
 */
interface ConfirmationDialogProps {
  isOpen: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  environment: string;
  region: string;
}

const ProductionDeleteConfirmation: React.FC<ConfirmationDialogProps> = ({
  isOpen,
  onConfirm,
  onCancel,
  environment,
  region,
}) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={onCancel} />
      <div className="relative bg-white rounded-xl shadow-2xl max-w-md w-full mx-4 p-6 border-2 border-red-500">
        <div className="flex items-center mb-4">
          <div className="w-12 h-12 bg-red-100 rounded-full flex items-center justify-center mr-4">
            <svg className="w-6 h-6 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <div>
            <h3 className="text-lg font-bold text-red-800">Delete Production Environment</h3>
            <p className="text-sm text-red-600">This action cannot be undone</p>
          </div>
        </div>
        
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
          <p className="text-sm text-red-800">
            You are about to delete the <span className="font-bold">{environment.toUpperCase()}</span> environment 
            in <span className="font-bold">{region}</span>. This will permanently remove all associated 
            CloudFormation stacks and resources.
          </p>
        </div>

        <div className="flex gap-3">
          <button
            onClick={onCancel}
            className="flex-1 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 font-medium"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 font-medium"
          >
            Delete Production
          </button>
        </div>
      </div>
    </div>
  );
};


/**
 * Environment Selector Modal Component
 */
const EnvironmentSelectorModal: React.FC<EnvironmentSelectorModalProps> = ({
  isOpen,
  onClose,
  onSelect,
  capability,
  deployments,
  operationType,
}) => {
  const [showProdConfirmation, setShowProdConfirmation] = useState(false);
  const [selectedDeployment, setSelectedDeployment] = useState<DeploymentState | null>(null);

  // Handle Escape key to close modal
  const handleKeyDown = useCallback((event: KeyboardEvent) => {
    if (event.key === 'Escape') {
      if (showProdConfirmation) {
        setShowProdConfirmation(false);
        setSelectedDeployment(null);
      } else {
        onClose();
      }
    }
  }, [onClose, showProdConfirmation]);

  useEffect(() => {
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
      return () => document.removeEventListener('keydown', handleKeyDown);
    }
  }, [isOpen, handleKeyDown]);

  // Reset state when modal closes
  useEffect(() => {
    if (!isOpen) {
      setShowProdConfirmation(false);
      setSelectedDeployment(null);
    }
  }, [isOpen]);

  if (!isOpen || !capability) return null;

  const sortedDeployments = sortDeployments(deployments);
  const isDelete = operationType === 'delete';

  const handleEnvironmentSelect = (deployment: DeploymentState) => {
    // For delete operations on production, show confirmation
    if (isDelete && isProductionEnvironment(deployment.environment)) {
      setSelectedDeployment(deployment);
      setShowProdConfirmation(true);
    } else {
      onSelect(deployment);
    }
  };

  const handleProdDeleteConfirm = () => {
    if (selectedDeployment) {
      onSelect(selectedDeployment);
    }
  };

  const handleProdDeleteCancel = () => {
    setShowProdConfirmation(false);
    setSelectedDeployment(null);
  };

  // Click outside to close (on overlay)
  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  return (
    <>
      <div 
        className="fixed inset-0 z-50 flex items-center justify-center"
        onClick={handleOverlayClick}
      >
        {/* Overlay */}
        <div className="absolute inset-0 bg-black/50" />
        
        {/* Modal */}
        <div className={`relative bg-white rounded-xl shadow-2xl max-w-lg w-full mx-4 border-2 ${
          isDelete ? 'border-red-300' : 'border-green-300'
        }`}>
          {/* Header */}
          <div className={`px-6 py-4 border-b ${
            isDelete ? 'bg-red-50 border-red-200' : 'bg-green-50 border-green-200'
          } rounded-t-xl`}>
            <div className="flex items-center justify-between">
              <div>
                <h2 className={`text-xl font-bold ${
                  isDelete ? 'text-red-800' : 'text-green-800'
                }`}>
                  {isDelete ? 'Delete' : 'Update'} Environment
                </h2>
                <p className={`text-sm ${
                  isDelete ? 'text-red-600' : 'text-green-600'
                }`}>
                  {capability.name}
                </p>
              </div>
              <button
                onClick={onClose}
                className={`p-2 rounded-lg hover:bg-opacity-20 ${
                  isDelete ? 'hover:bg-red-200 text-red-600' : 'hover:bg-green-200 text-green-600'
                }`}
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>

          {/* Body */}
          <div className="p-6">
            <p className="text-sm text-gray-600 mb-4">
              Select which environment you want to {isDelete ? 'delete' : 'update'}:
            </p>

            {/* Environment Cards */}
            <div className="space-y-3">
              {sortedDeployments.map((deployment, idx) => {
                const isProd = isProductionEnvironment(deployment.environment);
                
                return (
                  <button
                    key={idx}
                    onClick={() => handleEnvironmentSelect(deployment)}
                    className={`w-full text-left p-4 rounded-lg border-2 transition-all hover:shadow-md ${
                      isProd 
                        ? 'border-red-300 hover:border-red-500 hover:bg-red-50' 
                        : 'border-blue-300 hover:border-blue-500 hover:bg-blue-50'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center">
                        <span className={`w-3 h-3 rounded-full mr-3 ${
                          isProd ? 'bg-red-500' : 'bg-blue-500'
                        }`}></span>
                        <div>
                          <div className="flex items-center gap-2">
                            <span className={`font-bold ${
                              isProd ? 'text-red-700' : 'text-blue-700'
                            }`}>
                              {deployment.environment.toUpperCase()}
                            </span>
                            {isProd && isDelete && (
                              <span className="px-2 py-0.5 text-xs font-semibold bg-red-100 text-red-700 rounded-full">
                                ⚠️ Production
                              </span>
                            )}
                          </div>
                          <span className="text-sm text-gray-500">
                            {deployment.region}
                          </span>
                        </div>
                      </div>
                      <div className="text-right">
                        <span className="text-xs text-gray-500">
                          Last deployed
                        </span>
                        <p className="text-sm text-gray-700">
                          {formatDate(deployment.last_deployment)}
                        </p>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Footer */}
          <div className="px-6 py-4 border-t border-gray-200 bg-gray-50 rounded-b-xl">
            <button
              onClick={onClose}
              className="w-full px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-100 font-medium"
            >
              Cancel
            </button>
          </div>
        </div>
      </div>

      {/* Production Delete Confirmation */}
      <ProductionDeleteConfirmation
        isOpen={showProdConfirmation}
        onConfirm={handleProdDeleteConfirm}
        onCancel={handleProdDeleteCancel}
        environment={selectedDeployment?.environment || ''}
        region={selectedDeployment?.region || ''}
      />
    </>
  );
};

export default EnvironmentSelectorModal;

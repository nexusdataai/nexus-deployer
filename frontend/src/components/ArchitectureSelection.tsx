/**
 * ArchitectureSelection Component
 * Displays a visual architecture diagram with selectable frontend and backend services
 */
import React, { useState, useEffect } from 'react';
import { useWizard } from '../context/WizardContext';
import { WizardStep } from '../types/wizard';
import {
  FrontendService,
  BackendService,
  ArchitectureConfig,
  FRONTEND_SERVICE_OPTIONS,
  BACKEND_SERVICE_OPTIONS,
  DEFAULT_ARCHITECTURE_CONFIG,
} from '../types/architecture';
import ServiceOptionCard from './ServiceOptionCard';

/**
 * Check if Pure EKS architecture is selected (both frontend and backend on EKS)
 */
export const isPureEKSArchitecture = (config: ArchitectureConfig | null): boolean => {
  return config?.frontendService === FrontendService.EKS && config?.backendService === BackendService.EKS;
};

const ArchitectureSelection: React.FC = () => {
  const { state, setArchitectureConfig, setStep } = useWizard();

  // Initialize local state from context or defaults
  const [frontendService, setFrontendService] = useState<FrontendService>(
    state.architectureConfig?.frontendService ?? DEFAULT_ARCHITECTURE_CONFIG.frontendService
  );
  const [backendService, setBackendService] = useState<BackendService>(
    state.architectureConfig?.backendService ?? DEFAULT_ARCHITECTURE_CONFIG.backendService
  );

  // Auto-couple EKS backend when Pure EKS frontend is selected
  const handleFrontendSelect = (service: FrontendService) => {
    setFrontendService(service);
    // When Pure EKS frontend is selected, automatically select EKS backend
    if (service === FrontendService.EKS) {
      setBackendService(BackendService.EKS);
    }
  };

  // Prevent changing backend when Pure EKS frontend is selected
  const handleBackendSelect = (service: BackendService) => {
    // If Pure EKS frontend is selected, backend must remain EKS
    if (frontendService === FrontendService.EKS) {
      return; // Ignore backend selection changes
    }
    setBackendService(service);
  };

  // Sync local state to context when selections change
  useEffect(() => {
    const config: ArchitectureConfig = { frontendService, backendService };
    setArchitectureConfig(config);
  }, [frontendService, backendService, setArchitectureConfig]);

  // Validation: both services must be valid
  const isValid = frontendService && backendService;

  // Check if Pure EKS is selected for UI hints
  const isPureEKS = frontendService === FrontendService.EKS;

  const handleContinue = () => {
    if (isValid) {
      // For all architectures (including Pure EKS), go to environment config first
      // The wizard flow will handle EKS cluster selection after AWS authentication
      setStep(WizardStep.UNIFIED_ENVIRONMENT_CONFIG);
    }
  };

  const handleBack = () => {
    setStep(WizardStep.CAPABILITY_SELECTION);
  };

  return (
    <div className="max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">Architecture Selection</h1>
        <p className="text-gray-600">
          Choose the AWS services for deploying your frontend and backend components.
          Select from available options below.
        </p>
      </div>

      {/* Architecture Diagram */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 mb-8">
        {/* Visual Architecture Flow */}
        <div className="flex flex-col lg:flex-row items-center justify-center gap-4 mb-8">
          {/* Users */}
          <div className="flex flex-col items-center">
            <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center">
              <svg className="w-8 h-8 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197m13.5-9a2.5 2.5 0 11-5 0 2.5 2.5 0 015 0z" />
              </svg>
            </div>
            <span className="text-sm text-gray-600 mt-2">Users</span>
          </div>

          {/* Arrow */}
          <div className="hidden lg:block">
            <svg className="w-12 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
            </svg>
          </div>
          <div className="lg:hidden">
            <svg className="w-6 h-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-7 7m0 0l-7-7m7 7V3" />
            </svg>
          </div>

          {/* EKS Cluster Container (shown when Pure EKS is selected) */}
          {isPureEKS ? (
            <div className="relative border-2 border-dashed border-green-400 rounded-xl p-4 bg-green-50">
              <div className="absolute -top-3 left-4 bg-green-50 px-2 text-sm font-medium text-green-700">
                EKS Cluster
              </div>
              <div className="flex flex-col lg:flex-row items-center gap-4">
                {/* Frontend Box */}
                <div className="w-48 p-4 bg-purple-50 border-2 border-purple-200 rounded-lg text-center">
                  <div className="text-sm font-medium text-purple-700 mb-1">Frontend</div>
                  <div className="text-xs text-purple-600">
                    {FRONTEND_SERVICE_OPTIONS[frontendService].name}
                  </div>
                </div>

                {/* Arrow */}
                <div className="hidden lg:block">
                  <svg className="w-8 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
                  </svg>
                </div>
                <div className="lg:hidden">
                  <svg className="w-6 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-7 7m0 0l-7-7m7 7V3" />
                  </svg>
                </div>

                {/* Backend Box */}
                <div className="w-48 p-4 bg-orange-50 border-2 border-orange-200 rounded-lg text-center">
                  <div className="text-sm font-medium text-orange-700 mb-1">Backend</div>
                  <div className="text-xs text-orange-600">
                    {BACKEND_SERVICE_OPTIONS[backendService].name}
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <>
              {/* Frontend Box */}
              <div className="w-48 p-4 bg-purple-50 border-2 border-purple-200 rounded-lg text-center">
                <div className="text-sm font-medium text-purple-700 mb-1">Frontend</div>
                <div className="text-xs text-purple-600">
                  {FRONTEND_SERVICE_OPTIONS[frontendService].name}
                </div>
              </div>

              {/* Arrow */}
              <div className="hidden lg:block">
                <svg className="w-12 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
                </svg>
              </div>
              <div className="lg:hidden">
                <svg className="w-6 h-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-7 7m0 0l-7-7m7 7V3" />
                </svg>
              </div>

              {/* Backend Box */}
              <div className="w-48 p-4 bg-orange-50 border-2 border-orange-200 rounded-lg text-center">
                <div className="text-sm font-medium text-orange-700 mb-1">Backend</div>
                <div className="text-xs text-orange-600">
                  {BACKEND_SERVICE_OPTIONS[backendService].name}
                </div>
              </div>
            </>
          )}

          {/* Arrow */}
          <div className="hidden lg:block">
            <svg className="w-12 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
            </svg>
          </div>
          <div className="lg:hidden">
            <svg className="w-6 h-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-7 7m0 0l-7-7m7 7V3" />
            </svg>
          </div>

          {/* Database */}
          <div className="flex flex-col items-center">
            <div className="w-16 h-16 bg-blue-100 rounded-lg flex items-center justify-center">
              <svg className="w-8 h-8 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
              </svg>
            </div>
            <span className="text-sm text-gray-600 mt-2">Data</span>
          </div>
        </div>
      </div>

      {/* Service Selection Sections */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-8">
        {/* Frontend Layer */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <div className="flex items-center mb-4">
            <div className="w-3 h-3 bg-purple-500 rounded-full mr-2"></div>
            <h2 className="text-xl font-semibold text-gray-900">Frontend Layer</h2>
          </div>
          <p className="text-sm text-gray-600 mb-4">
            Select how your frontend application will be hosted and delivered to users.
          </p>
          <div className="space-y-4">
            {Object.entries(FRONTEND_SERVICE_OPTIONS).map(([key, option]) => (
              <ServiceOptionCard
                key={key}
                option={option}
                isSelected={frontendService === key}
                onSelect={() => handleFrontendSelect(key as FrontendService)}
              />
            ))}
          </div>
        </div>

        {/* Backend Layer */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <div className="flex items-center mb-4">
            <div className="w-3 h-3 bg-orange-500 rounded-full mr-2"></div>
            <h2 className="text-xl font-semibold text-gray-900">Backend Layer</h2>
            {isPureEKS && (
              <span className="ml-2 text-xs bg-green-100 text-green-700 px-2 py-1 rounded-full">
                Locked to EKS
              </span>
            )}
          </div>
          <p className="text-sm text-gray-600 mb-4">
            Select the compute platform for running your backend services and APIs.
            {isPureEKS && (
              <span className="block mt-1 text-green-600 text-xs">
                Pure EKS architecture requires both frontend and backend on EKS.
              </span>
            )}
          </p>
          <div className="space-y-4">
            {Object.entries(BACKEND_SERVICE_OPTIONS).map(([key, option]) => (
              <ServiceOptionCard
                key={key}
                option={option}
                isSelected={backendService === key}
                onSelect={() => handleBackendSelect(key as BackendService)}
                disabled={isPureEKS && key !== BackendService.EKS}
              />
            ))}
          </div>
        </div>
      </div>

      {/* Navigation Buttons */}
      <div className="flex justify-between">
        <button
          onClick={handleBack}
          className="px-6 py-3 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 font-medium"
        >
          Back
        </button>
        <button
          onClick={handleContinue}
          disabled={!isValid}
          className={`px-6 py-3 rounded-lg font-medium ${
            isValid
              ? 'bg-blue-600 text-white hover:bg-blue-700'
              : 'bg-gray-300 text-gray-500 cursor-not-allowed'
          }`}
        >
          Continue
        </button>
      </div>
    </div>
  );
};

export default ArchitectureSelection;

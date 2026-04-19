/**
 * Wizard Shell Component - Main container for the deployment wizard
 * 
 * Feature: update-workflow-cognito-preservation, user-menu, pure-eks-deployment
 * Requirements: 1.1, 3.1, 5.1
 */
import React, { useCallback } from 'react';
import { useWizard } from '../context/WizardContext';
import { WizardStep, UpdateOptions, DriftDetectionResult } from '../types/wizard';
import WelcomeScreen from './WelcomeScreen';
import CapabilitySelection from './CapabilitySelection';
import ArchitectureSelection from './ArchitectureSelection';
import EKSClusterSelector from './EKSClusterSelector';
import UnifiedEnvironmentConfig from './UnifiedEnvironmentConfig';
import AWSConfigurationEnhanced from './AWSConfigurationEnhanced';
import PermissionVerification from './PermissionVerification';
import { StrategySelection } from './StrategySelection';
import DeploymentExecution from './DeploymentExecution';
import DeletionExecution from './DeletionExecution';
import DiscoveryExecution from './DiscoveryExecution';
import PostVerification from './PostVerification';
import Results from './Results';
import AppHeader from './AppHeader';
import { deploymentApi } from '../services/api';
import { FrontendService, BackendService } from '../types/architecture';

const WizardShell: React.FC = () => {
  const { state, setSelectedStrategy, setUpdateOptions, setStep } = useWizard();

  // Handle drift detection for Cognito
  const handleDetectDrift = useCallback(async (): Promise<DriftDetectionResult | null> => {
    if (!state.awsConfig || !state.selectedCapability || !state.selectedEnvironment) {
      return null;
    }

    try {
      const response = await deploymentApi.detectCognitoDrift({
        capability_name: state.selectedCapability.name,
        environment: state.selectedEnvironment,
        region: state.awsConfig.region,
        aws_session_id: state.awsConfig.aws_session_id,
      });
      return response;
    } catch (error) {
      console.error('Drift detection failed:', error);
      return {
        has_drift: false,
        drift_items: [],
        detection_timestamp: new Date().toISOString(),
        error_message: 'Failed to detect drift. You can proceed with the update.',
        categories_checked: [],
      };
    }
  }, [state.awsConfig, state.selectedCapability, state.selectedEnvironment]);

  const renderStep = () => {
    switch (state.currentStep) {
      case WizardStep.WELCOME:
        return <WelcomeScreen />;
      case WizardStep.CAPABILITY_SELECTION:
        return <CapabilitySelection />;
      case WizardStep.ARCHITECTURE_SELECTION:
        return <ArchitectureSelection />;
      case WizardStep.EKS_CLUSTER_SELECTION:
        return <EKSClusterSelector />;
      case WizardStep.UNIFIED_ENVIRONMENT_CONFIG:
        return <UnifiedEnvironmentConfig />;
      case WizardStep.AWS_CONFIGURATION:
        return <AWSConfigurationEnhanced />;
      case WizardStep.PERMISSION_VERIFICATION:
        return <PermissionVerification />;
      case WizardStep.STRATEGY_SELECTION:
        // Guard: Only render if detection result exists
        if (!state.detectionResult) {
          console.error('❌ STRATEGY_SELECTION step reached without detection result');
          setStep(WizardStep.PERMISSION_VERIFICATION);
          return <div className="p-8">Loading...</div>;
        }
        return <StrategySelection 
          detectionResult={state.detectionResult}
          onStrategySelected={(strategy, updateOptions?: UpdateOptions) => {
            setSelectedStrategy(strategy);
            if (updateOptions) {
              setUpdateOptions(updateOptions);
            }
            setStep(WizardStep.DEPLOYMENT_EXECUTION);
          }}
          onCancel={() => {
            setStep(WizardStep.PERMISSION_VERIFICATION);
          }}
          onDetectDrift={handleDetectDrift}
        />;
      case WizardStep.DEPLOYMENT_EXECUTION:
        return <DeploymentExecution />;
      case WizardStep.DELETION_EXECUTION:
        return <DeletionExecution />;
      case WizardStep.DISCOVERY_EXECUTION:
        return <DiscoveryExecution />;
      case WizardStep.POST_VERIFICATION:
        return <PostVerification />;
      case WizardStep.RESULTS:
        return <Results />;
      default:
        return <div className="p-8">Unknown Step</div>;
    }
  };

  const getStepNumber = () => {
    // Determine if Pure EKS architecture is selected
    const isPureEKS = state.architectureConfig?.frontendService === FrontendService.EKS && 
                      state.architectureConfig?.backendService === BackendService.EKS;

    // For Pure EKS: AWS auth comes BEFORE EKS cluster selection (need credentials to query clusters)
    const steps = isPureEKS ? [
      WizardStep.WELCOME,
      WizardStep.CAPABILITY_SELECTION,
      WizardStep.ARCHITECTURE_SELECTION,
      WizardStep.UNIFIED_ENVIRONMENT_CONFIG,
      WizardStep.AWS_CONFIGURATION,
      WizardStep.EKS_CLUSTER_SELECTION,  // After AWS auth so we can query clusters
      WizardStep.PERMISSION_VERIFICATION,
      WizardStep.STRATEGY_SELECTION,
      WizardStep.DEPLOYMENT_EXECUTION,
      WizardStep.DELETION_EXECUTION,
      WizardStep.POST_VERIFICATION,
      WizardStep.RESULTS,
    ] : [
      WizardStep.WELCOME,
      WizardStep.CAPABILITY_SELECTION,
      WizardStep.ARCHITECTURE_SELECTION,
      WizardStep.UNIFIED_ENVIRONMENT_CONFIG,
      WizardStep.AWS_CONFIGURATION,
      WizardStep.PERMISSION_VERIFICATION,
      WizardStep.STRATEGY_SELECTION,
      WizardStep.DEPLOYMENT_EXECUTION,
      WizardStep.DELETION_EXECUTION,
      WizardStep.POST_VERIFICATION,
      WizardStep.RESULTS,
    ];
    return steps.indexOf(state.currentStep) + 1;
  };

  const getTotalSteps = () => {
    // Determine if Pure EKS architecture is selected
    const isPureEKS = state.architectureConfig?.frontendService === FrontendService.EKS && 
                      state.architectureConfig?.backendService === BackendService.EKS;
    return isPureEKS ? 12 : 11;
  };

  // Show progress bar only after welcome screen
  const showProgress = state.currentStep !== WizardStep.WELCOME;

  return (
    <div className="min-h-screen bg-gray-50">
      {/* App Header with User Menu */}
      <AppHeader
        title="Totogi Customer Toolkit"
        showProgress={showProgress}
        currentStep={showProgress ? getStepNumber() : undefined}
        totalSteps={showProgress ? getTotalSteps() : undefined}
        capabilityName={state.selectedCapability?.name}
      />

      {/* Main Content */}
      <div className="max-w-7xl mx-auto px-4 py-8">{renderStep()}</div>
    </div>
  );
};

export default WizardShell;

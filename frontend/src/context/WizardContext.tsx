/**
 * Wizard Context for managing wizard state
 */
import React, { createContext, useContext, useState, ReactNode } from 'react';
import {
  WizardState,
  WizardStep,
  WizardContextType,
  DeploymentStatus,
  LogEntry,
  VerificationResult,
  StackDetectionResult,
  DeploymentStrategy,
  UpdateOptions,
} from '../types/wizard';
import { Capability } from '../types/capability';
import { AWSConfiguration, PermissionStatus } from '../types/aws';
import { EnvironmentConfig } from '../types/config';
import { ArchitectureConfig, FrontendService, BackendService } from '../types/architecture';
import { EKSConfig } from '../types/eks';

const initialDeploymentStatus: DeploymentStatus = {
  id: null,
  status: 'pending',
  progress: 0,
  currentStage: '',
};

const initialState: WizardState = {
  currentStep: WizardStep.WELCOME,
  selectedCapability: null,
  selectedEnvironment: null,
  awsRegion: null,
  awsConfig: null,
  architectureConfig: null,
  eksConfig: null,
  infrastructureConfig: null,
  permissionStatus: null,
  detectionResult: null,
  selectedStrategy: null,
  updateOptions: null,
  deploymentStatus: initialDeploymentStatus,
  logs: [],
  verificationResults: null,
  deleteMode: false,
  discoveryMode: false,
};

const WizardContext = createContext<WizardContextType | undefined>(undefined);

export const WizardProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [state, setState] = useState<WizardState>(initialState);

  const setStep = (step: WizardStep) => {
    setState((prev) => ({ ...prev, currentStep: step }));
  };

  const setCapability = (capability: Capability) => {
    setState((prev) => ({ ...prev, selectedCapability: capability }));
  };

  const setEnvironment = (environment: string) => {
    setState((prev) => ({ ...prev, selectedEnvironment: environment }));
  };

  const setAwsRegion = (region: string) => {
    setState((prev) => ({ ...prev, awsRegion: region }));
  };

  const setAWSConfig = (config: AWSConfiguration) => {
    setState((prev) => ({ ...prev, awsConfig: config }));
  };

  const setArchitectureConfig = (config: ArchitectureConfig) => {
    setState((prev) => ({ ...prev, architectureConfig: config }));
  };

  const setEKSConfig = (config: EKSConfig) => {
    setState((prev) => ({ ...prev, eksConfig: config }));
  };

  const setInfrastructureConfig = (config: EnvironmentConfig) => {
    setState((prev) => ({ ...prev, infrastructureConfig: config }));
  };

  const setPermissionStatus = (status: PermissionStatus) => {
    setState((prev) => ({ ...prev, permissionStatus: status }));
  };

  const setDetectionResult = (result: StackDetectionResult) => {
    setState((prev) => ({ ...prev, detectionResult: result }));
  };

  const setSelectedStrategy = (strategy: DeploymentStrategy) => {
    setState((prev) => ({ ...prev, selectedStrategy: strategy }));
  };

  const setUpdateOptions = (options: UpdateOptions) => {
    setState((prev) => ({ ...prev, updateOptions: options }));
  };

  const setDeploymentStatus = (status: DeploymentStatus) => {
    setState((prev) => ({ ...prev, deploymentStatus: status }));
  };

  const addLog = (log: LogEntry) => {
    setState((prev) => ({ ...prev, logs: [...prev.logs, log] }));
  };

  const setVerificationResults = (results: VerificationResult) => {
    setState((prev) => ({ ...prev, verificationResults: results }));
  };

  const setDeleteMode = (deleteMode: boolean) => {
    setState((prev) => ({ ...prev, deleteMode }));
  };

  const setDiscoveryMode = (discoveryMode: boolean) => {
    setState((prev) => ({ ...prev, discoveryMode }));
  };

  const resetWizard = () => {
    setState(initialState);
  };

  const goToNextStep = () => {
    // Determine if Pure EKS architecture is selected
    const isPureEKS = state.architectureConfig?.frontendService === FrontendService.EKS && 
                      state.architectureConfig?.backendService === BackendService.EKS;

    // Delete mode has a simplified flow - skip architecture and EKS selection
    // The deployment type is already known from the existing deployment
    let stepOrder: WizardStep[];
    
    if (state.deleteMode) {
      // Simplified delete flow - no architecture or EKS selection needed
      stepOrder = [
        WizardStep.WELCOME,
        WizardStep.CAPABILITY_SELECTION,
        WizardStep.AWS_CONFIGURATION,
        WizardStep.PERMISSION_VERIFICATION,
        WizardStep.DELETION_EXECUTION,
        WizardStep.RESULTS,
      ];
    } else if (state.discoveryMode) {
      // Discovery flow - AWS auth then discovery execution
      stepOrder = [
        WizardStep.CAPABILITY_SELECTION,
        WizardStep.AWS_CONFIGURATION,
        WizardStep.DISCOVERY_EXECUTION,
      ];
    } else if (isPureEKS) {
      // For Pure EKS: AWS auth comes BEFORE EKS cluster selection (need credentials to query clusters)
      stepOrder = [
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
      ];
    } else {
      // CloudFormation flow
      stepOrder = [
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
    }

    const currentIndex = stepOrder.indexOf(state.currentStep);
    if (currentIndex < stepOrder.length - 1) {
      setStep(stepOrder[currentIndex + 1]);
    }
  };

  const goToPreviousStep = () => {
    // Determine if Pure EKS architecture is selected
    const isPureEKS = state.architectureConfig?.frontendService === FrontendService.EKS && 
                      state.architectureConfig?.backendService === BackendService.EKS;

    // Delete mode has a simplified flow
    let stepOrder: WizardStep[];
    
    if (state.deleteMode) {
      // Simplified delete flow
      stepOrder = [
        WizardStep.WELCOME,
        WizardStep.CAPABILITY_SELECTION,
        WizardStep.AWS_CONFIGURATION,
        WizardStep.PERMISSION_VERIFICATION,
        WizardStep.DELETION_EXECUTION,
        WizardStep.RESULTS,
      ];
    } else if (state.discoveryMode) {
      // Discovery flow
      stepOrder = [
        WizardStep.CAPABILITY_SELECTION,
        WizardStep.AWS_CONFIGURATION,
        WizardStep.DISCOVERY_EXECUTION,
      ];
    } else if (isPureEKS) {
      // For Pure EKS: AWS auth comes BEFORE EKS cluster selection
      stepOrder = [
        WizardStep.WELCOME,
        WizardStep.CAPABILITY_SELECTION,
        WizardStep.ARCHITECTURE_SELECTION,
        WizardStep.UNIFIED_ENVIRONMENT_CONFIG,
        WizardStep.AWS_CONFIGURATION,
        WizardStep.EKS_CLUSTER_SELECTION,  // After AWS auth
        WizardStep.PERMISSION_VERIFICATION,
        WizardStep.STRATEGY_SELECTION,
        WizardStep.DEPLOYMENT_EXECUTION,
        WizardStep.DELETION_EXECUTION,
        WizardStep.POST_VERIFICATION,
        WizardStep.RESULTS,
      ];
    } else {
      // CloudFormation flow
      stepOrder = [
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
    }

    const currentIndex = stepOrder.indexOf(state.currentStep);
    if (currentIndex > 0) {
      setStep(stepOrder[currentIndex - 1]);
    }
  };

  const value: WizardContextType = {
    state,
    setStep,
    setCapability,
    setEnvironment,
    setAwsRegion,
    setAWSConfig,
    setArchitectureConfig,
    setEKSConfig,
    setInfrastructureConfig,
    setPermissionStatus,
    setDetectionResult,
    setSelectedStrategy,
    setUpdateOptions,
    setDeploymentStatus,
    addLog,
    setVerificationResults,
    setDeleteMode,
    setDiscoveryMode,
    resetWizard,
    goToNextStep,
    goToPreviousStep,
  };

  return <WizardContext.Provider value={value}>{children}</WizardContext.Provider>;
};

export const useWizard = (): WizardContextType => {
  const context = useContext(WizardContext);
  if (!context) {
    throw new Error('useWizard must be used within a WizardProvider');
  }
  return context;
};

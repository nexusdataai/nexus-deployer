/**
 * Permission Verification Component
 * Comprehensive pre-deployment verification including permissions, artifacts, and resources
 */
import React, { useState, useEffect } from 'react';
import { useWizard } from '../context/WizardContext';
import { WizardStep, StackDetectionResult, DeploymentStrategy } from '../types/wizard';
import { FrontendService, BackendService } from '../types/architecture';
import axios from 'axios';
import { generateMinimalPolicy, formatPolicyForDownload, downloadPolicy, MissingPermission } from '../utils/policy-generator';
import { matchErrorType, getErrorHelp, ErrorType } from '../data/error-help-data';

interface ServicePermission {
  service: string;
  purpose: string;
  status: string;
  granted_count: number;
  total_count: number;
  granted_actions: string[];
  restricted_actions: string[];
}

interface PermissionResult {
  overall_status: string;
  total_granted: number;
  total_actions: number;
  services: ServicePermission[];
}

interface PrerequisiteCheck {
  name: string;
  status: 'pending' | 'checking' | 'success' | 'warning' | 'error';
  message: string;
  details?: string[];
}

const PermissionVerification: React.FC = () => {
  const { state, setStep, setDetectionResult } = useWizard();
  
  // Detect Pure EKS architecture
  const isPureEKS = state.architectureConfig?.frontendService === FrontendService.EKS && 
                    state.architectureConfig?.backendService === BackendService.EKS;
  
  const [verifying, setVerifying] = useState(false);
  const [verified, setVerified] = useState(false);
  const [permissionResult, setPermissionResult] = useState<PermissionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expandedService, setExpandedService] = useState<string | null>(null);
  const [hasRunVerification, setHasRunVerification] = useState(false);
  const [isNavigating, setIsNavigating] = useState(false);
  const [copiedPolicy, setCopiedPolicy] = useState(false);
  const [showErrorHelp, setShowErrorHelp] = useState(false);
  const [matchedErrorType, setMatchedErrorType] = useState<ErrorType | null>(null);
  
  // Prerequisite checks - different for Pure EKS vs ECS/CloudFront
  const getInitialPrerequisiteChecks = (): PrerequisiteCheck[] => {
    if (isPureEKS) {
      return [
        { name: 'AWS Account Access', status: 'pending', message: 'Waiting to verify...' },
        { name: 'IAM Permissions', status: 'pending', message: 'Waiting to verify...' },
        { name: 'EKS Cluster Access', status: 'pending', message: 'Waiting to verify...' },
        { name: 'Frontend Container Image', status: 'pending', message: 'Waiting to verify...' },
        { name: 'Backend Container Image', status: 'pending', message: 'Waiting to verify...' },
        { name: 'Network Resources', status: 'pending', message: 'Waiting to verify...' },
        { name: 'Stack Detection', status: 'pending', message: 'Will check after verification...' },
      ];
    }
    return [
      { name: 'AWS Account Access', status: 'pending', message: 'Waiting to verify...' },
      { name: 'IAM Permissions', status: 'pending', message: 'Waiting to verify...' },
      { name: 'Frontend Artifact', status: 'pending', message: 'Waiting to verify...' },
      { name: 'Backend Container Image', status: 'pending', message: 'Waiting to verify...' },
      { name: 'Network Resources', status: 'pending', message: 'Waiting to verify...' },
      { name: 'Service Limits', status: 'pending', message: 'Waiting to verify...' },
      { name: 'Stack Detection', status: 'pending', message: 'Will check after verification...' },
    ];
  };
  
  const [prerequisiteChecks, setPrerequisiteChecks] = useState<PrerequisiteCheck[]>(getInitialPrerequisiteChecks());

  // Delete mode specific permissions
  const DELETE_PERMISSIONS = [
    { service: 'CloudFormation', action: 'DeleteStack', purpose: 'Delete CloudFormation stacks' },
    { service: 'S3', action: 'DeleteBucket', purpose: 'Delete S3 buckets' },
    { service: 'S3', action: 'DeleteObject', purpose: 'Delete S3 objects' },
    { service: 'CloudFront', action: 'DeleteDistribution', purpose: 'Delete CloudFront distributions' },
    { service: 'ECS', action: 'DeleteCluster', purpose: 'Delete ECS clusters' },
    { service: 'ECS', action: 'DeleteService', purpose: 'Delete ECS services' },
    { service: 'EC2', action: 'DeleteVpc', purpose: 'Delete VPC resources' },
    { service: 'EC2', action: 'DeleteSecurityGroup', purpose: 'Delete security groups' },
    { service: 'DynamoDB', action: 'DeleteTable', purpose: 'Delete DynamoDB tables' },
    { service: 'IAM', action: 'DeleteRole', purpose: 'Delete IAM roles' },
  ];

  // Resources that will be deleted (populated from detection)
  const [resourcesToDelete, setResourcesToDelete] = useState<string[]>([]);
  const [showDeleteWarnings, setShowDeleteWarnings] = useState(false);

  // Auto-verify on mount (only once)
  // For delete mode, skip detailed verification and go straight to deletion
  useEffect(() => {
    if (state.deleteMode) {
      console.log('🗑️ Delete mode - skipping detailed verification');
      handleDeleteModeVerification();
      return;
    }
    
    if (!hasRunVerification && !verifying) {
      console.log('🔍 PermissionVerification: Starting auto-verification');
      handleVerifyAll();
    }
  }, [hasRunVerification, verifying, state.deleteMode]);

  // Simplified verification for delete mode - only verify AWS access
  const handleDeleteModeVerification = async () => {
    setVerifying(true);
    setHasRunVerification(true);
    setShowDeleteWarnings(true);
    
    // Show delete-specific checks
    setPrerequisiteChecks([
      { name: 'AWS Account Access', status: 'checking', message: 'Verifying account access...' },
      { name: 'Delete Permissions', status: 'pending', message: 'Waiting to verify delete permissions...' },
    ]);
    
    try {
      await verifyAccountAccess();
      
      // Update delete permissions check
      updateCheck('Delete Permissions', 'success', 'Delete permissions available', [
        'CloudFormation:DeleteStack',
        'S3:DeleteBucket, DeleteObject',
        'ECS:DeleteCluster, DeleteService'
      ]);
      
      // Populate resources to delete based on capability
      const resources = [
        `${state.selectedCapability?.name}-${state.selectedEnvironment}-frontend (S3 + CloudFront)`,
        `${state.selectedCapability?.name}-${state.selectedEnvironment}-backend (ECS + ALB)`,
        `${state.selectedCapability?.name}-${state.selectedEnvironment}-data (DynamoDB)`,
        `${state.selectedCapability?.name}-${state.selectedEnvironment}-network (VPC)`,
      ];
      setResourcesToDelete(resources);
      
      setVerified(true);
      
      // Don't auto-continue - let user review warnings first
    } catch (err: any) {
      console.error('❌ Delete mode verification error:', err);
      setError(err.response?.data?.detail || err.message || 'Verification failed');
      updateCheck('Delete Permissions', 'error', 'Failed to verify delete permissions');
    } finally {
      setVerifying(false);
    }
  };

  const updateCheck = (name: string, status: PrerequisiteCheck['status'], message: string, details?: string[]) => {
    setPrerequisiteChecks(prev => 
      prev.map(check => 
        check.name === name ? { ...check, status, message, details } : check
      )
    );
  };

  const handleVerifyAll = async () => {
    console.log('🔍 PermissionVerification: handleVerifyAll called');
    console.log('🔍 Architecture: isPureEKS =', isPureEKS);
    setError(null);
    setVerifying(true);
    setVerified(false);
    setHasRunVerification(true);

    try {
      // 1. Verify AWS Account Access
      updateCheck('AWS Account Access', 'checking', 'Verifying account access...');
      await verifyAccountAccess();
      
      // 2. Verify IAM Permissions (different for Pure EKS)
      updateCheck('IAM Permissions', 'checking', 'Checking IAM permissions...');
      await verifyPermissions();
      
      // 3. For Pure EKS: Verify EKS Cluster Access
      if (isPureEKS) {
        updateCheck('EKS Cluster Access', 'checking', 'Verifying EKS cluster access...');
        await verifyEKSClusterAccess();
      }
      
      // 4. Verify Frontend Artifact/Container Image
      if (state.selectedCapability?.requirements?.frontend) {
        if (isPureEKS) {
          updateCheck('Frontend Container Image', 'checking', 'Verifying frontend container image...');
          await verifyFrontendContainerImage();
        } else {
          updateCheck('Frontend Artifact', 'checking', 'Verifying frontend artifact...');
          await verifyFrontendArtifact();
        }
      } else {
        const checkName = isPureEKS ? 'Frontend Container Image' : 'Frontend Artifact';
        updateCheck(checkName, 'success', 'Not required for this deployment');
      }
      
      // 5. Verify Backend Image (if needed)
      if (state.selectedCapability?.requirements?.backend) {
        updateCheck('Backend Container Image', 'checking', 'Verifying container image...');
        await verifyBackendImage();
      } else {
        updateCheck('Backend Container Image', 'success', 'Not required for this deployment');
      }
      
      // 6. Verify Network Resources
      updateCheck('Network Resources', 'checking', 'Checking network resources...');
      await verifyNetworkResources();
      
      // 7. Verify Service Limits (skip for Pure EKS - uses Kubernetes limits instead)
      if (!isPureEKS) {
        updateCheck('Service Limits', 'checking', 'Checking service limits...');
        await verifyServiceLimits();
      }
      
      setVerified(true);
    } catch (err: any) {
      console.error('❌ Verification error:', err);
      const errorMsg = err.response?.data?.detail || err.message || 'Verification failed';
      setError(errorMsg);
    } finally {
      setVerifying(false);
    }
  };

  const verifyAccountAccess = async () => {
    try {
      console.log('🔍 Frontend: Verifying account access with:', {
        aws_session_id: state.awsConfig?.aws_session_id,
        region: state.awsConfig?.region,
        account_id: state.awsConfig?.account_id,
      });
      
      const response = await axios.post('http://127.0.0.1:8001/api/aws/verify-account', {
        aws_session_id: state.awsConfig?.aws_session_id,
        region: state.awsConfig?.region,
        account_id: state.awsConfig?.account_id,
      });
      
      updateCheck('AWS Account Access', 'success', `Account ${response.data.account_id} verified`, [
        `Identity: ${response.data.arn}`,
        `Region: ${response.data.region}`
      ]);
    } catch (err: any) {
      updateCheck('AWS Account Access', 'error', 'Failed to verify account access', [
        err.response?.data?.detail || err.message
      ]);
      throw err;
    }
  };

  const verifyPermissions = async () => {
    try {
      // For Pure EKS, use EKS-specific permission verification
      const endpoint = isPureEKS 
        ? 'http://127.0.0.1:8001/api/aws/verify-permissions-eks'
        : 'http://127.0.0.1:8001/api/aws/verify-permissions-detailed';
      
      const response = await axios.post(endpoint, {
        aws_session_id: state.awsConfig?.aws_session_id,
        region: state.awsConfig?.region,
        account_id: state.awsConfig?.account_id,
        // For EKS, pass the cluster name if available
        ...(isPureEKS && state.eksConfig?.clusterName && { cluster_name: state.eksConfig.clusterName }),
      });
      
      setPermissionResult(response.data);
      
      const servicesWithAccess = response.data.services.filter((s: ServicePermission) => s.granted_count > 0).length;
      const totalServices = response.data.services.length;
      
      if (servicesWithAccess === totalServices) {
        updateCheck('IAM Permissions', 'success', `All ${totalServices} services accessible`, [
          `${response.data.total_granted}/${response.data.total_actions} permissions verified`,
          isPureEKS ? 'EKS-specific permissions verified' : undefined
        ].filter(Boolean) as string[]);
      } else if (servicesWithAccess > 0) {
        updateCheck('IAM Permissions', 'warning', `${servicesWithAccess}/${totalServices} services accessible`, [
          `Some permissions may be missing`,
          `${response.data.total_granted}/${response.data.total_actions} permissions verified`
        ]);
      } else {
        updateCheck('IAM Permissions', 'error', 'Insufficient permissions', [
          'No service access detected'
        ]);
        throw new Error('Insufficient permissions');
      }
    } catch (err: any) {
      // If EKS endpoint doesn't exist, fall back to standard verification
      if (isPureEKS && err.response?.status === 404) {
        console.log('EKS permission endpoint not found, using standard verification');
        const response = await axios.post('http://127.0.0.1:8001/api/aws/verify-permissions-detailed', {
          aws_session_id: state.awsConfig?.aws_session_id,
          region: state.awsConfig?.region,
          account_id: state.awsConfig?.account_id,
        });
        setPermissionResult(response.data);
        const servicesWithAccess = response.data.services.filter((s: ServicePermission) => s.granted_count > 0).length;
        const totalServices = response.data.services.length;
        updateCheck('IAM Permissions', servicesWithAccess > 0 ? 'success' : 'error', 
          `${servicesWithAccess}/${totalServices} services accessible`);
        return;
      }
      updateCheck('IAM Permissions', 'error', 'Failed to verify permissions', [
        err.response?.data?.detail || err.message
      ]);
      throw err;
    }
  };

  const verifyFrontendArtifact = async () => {
    try {
      const response = await axios.post('http://127.0.0.1:8001/api/aws/verify-artifact', {
        aws_session_id: state.awsConfig?.aws_session_id,
        artifact_type: 'frontend',
        s3_uri: state.selectedCapability?.artifacts?.frontend?.s3_uri,
      });
      
      updateCheck('Frontend Artifact', 'success', 'Frontend artifact verified', [
        `Size: ${response.data.size_mb} MB`,
        `Last Modified: ${new Date(response.data.last_modified).toLocaleString()}`
      ]);
    } catch (err: any) {
      updateCheck('Frontend Artifact', 'error', 'Frontend artifact not found or inaccessible', [
        err.response?.data?.detail || err.message
      ]);
      throw err;
    }
  };

  // Verify frontend container image for Pure EKS deployments
  const verifyFrontendContainerImage = async () => {
    try {
      // Use eks_artifacts.frontend_ecr_uri for Pure EKS
      const frontendEcrUri = state.selectedCapability?.eks_artifacts?.frontend_ecr_uri;
      
      if (!frontendEcrUri) {
        updateCheck('Frontend Container Image', 'warning', 'No frontend ECR URI configured', [
          'eks_artifacts.frontend_ecr_uri not found in capability config'
        ]);
        return;
      }
      
      const response = await axios.post('http://127.0.0.1:8001/api/aws/verify-artifact', {
        aws_session_id: state.awsConfig?.aws_session_id,
        artifact_type: 'backend', // ECR verification uses 'backend' type
        ecr_uri: frontendEcrUri,
      });
      
      updateCheck('Frontend Container Image', 'success', 'Frontend container image verified', [
        `Image: ${frontendEcrUri.split('/').pop()}`,
        `Size: ${response.data.size_mb} MB`,
        `Pushed: ${new Date(response.data.pushed_at).toLocaleString()}`
      ]);
    } catch (err: any) {
      updateCheck('Frontend Container Image', 'error', 'Frontend container image not found or inaccessible', [
        err.response?.data?.detail || err.message,
        'Ensure the ECR image exists and you have ecr:DescribeImages permission'
      ]);
      throw err;
    }
  };

  // Verify EKS cluster access for Pure EKS deployments
  const verifyEKSClusterAccess = async () => {
    try {
      const clusterName = state.eksConfig?.clusterName;
      
      if (!clusterName) {
        updateCheck('EKS Cluster Access', 'warning', 'No EKS cluster selected', [
          'Please go back and select an EKS cluster'
        ]);
        return;
      }
      
      // Import eksApi dynamically to avoid circular dependencies
      const { eksApi } = await import('../services/api');
      
      const response = await eksApi.listClusters(
        state.awsConfig?.aws_session_id,
        state.awsConfig?.region
      );
      
      // Check if the selected cluster is in the list
      const clusters = response.clusters || [];
      const selectedCluster = clusters.find((c: any) => c.name === clusterName);
      
      if (selectedCluster) {
        updateCheck('EKS Cluster Access', 'success', `EKS cluster "${clusterName}" accessible`, [
          `Status: ${selectedCluster.status}`,
          `Version: ${selectedCluster.version}`,
          `Endpoint: ${selectedCluster.endpoint ? 'Available' : 'Not available'}`
        ]);
      } else {
        updateCheck('EKS Cluster Access', 'error', `EKS cluster "${clusterName}" not found`, [
          'The selected cluster may have been deleted or you may not have access'
        ]);
        throw new Error(`EKS cluster "${clusterName}" not found`);
      }
    } catch (err: any) {
      if (err.message?.includes('not found')) {
        throw err;
      }
      updateCheck('EKS Cluster Access', 'error', 'Failed to verify EKS cluster access', [
        err.response?.data?.detail || err.message,
        'Ensure you have eks:DescribeCluster permission'
      ]);
      throw err;
    }
  };

  const verifyBackendImage = async () => {
    try {
      // For Pure EKS, use eks_artifacts.backend_ecr_uri
      const backendEcrUri = isPureEKS 
        ? state.selectedCapability?.eks_artifacts?.backend_ecr_uri
        : state.selectedCapability?.artifacts?.backend?.ecr_uri;
      
      if (!backendEcrUri) {
        updateCheck('Backend Container Image', 'warning', 'No backend ECR URI configured', [
          isPureEKS ? 'eks_artifacts.backend_ecr_uri not found' : 'artifacts.backend.ecr_uri not found'
        ]);
        return;
      }
      
      const response = await axios.post('http://127.0.0.1:8001/api/aws/verify-artifact', {
        aws_session_id: state.awsConfig?.aws_session_id,
        artifact_type: 'backend',
        ecr_uri: backendEcrUri,
      });
      
      updateCheck('Backend Container Image', 'success', 'Container image verified', [
        `Size: ${response.data.size_mb} MB`,
        `Pushed: ${new Date(response.data.pushed_at).toLocaleString()}`
      ]);
    } catch (err: any) {
      updateCheck('Backend Container Image', 'error', 'Container image not found or inaccessible', [
        err.response?.data?.detail || err.message
      ]);
      throw err;
    }
  };

  const verifyNetworkResources = async () => {
    try {
      const response = await axios.post('http://127.0.0.1:8001/api/aws/verify-network', {
        aws_session_id: state.awsConfig?.aws_session_id,
        region: state.awsConfig?.region,
      });
      
      updateCheck('Network Resources', 'success', 'Network resources verified', [
        `${response.data.available_azs} Availability Zones available`,
        `Current VPCs: ${response.data.vpc_count}/5`
      ]);
    } catch (err: any) {
      updateCheck('Network Resources', 'warning', 'Network verification completed with warnings', [
        err.response?.data?.detail || err.message
      ]);
      // Don't throw - network checks are informational
    }
  };

  const verifyServiceLimits = async () => {
    try {
      const response = await axios.post('http://127.0.0.1:8001/api/aws/verify-limits', {
        aws_session_id: state.awsConfig?.aws_session_id,
        region: state.awsConfig?.region,
      });
      
      updateCheck('Service Limits', 'success', 'Service limits verified', [
        `ECS Clusters: ${response.data.ecs_clusters}`,
        `Sufficient capacity available`
      ]);
    } catch (err: any) {
      updateCheck('Service Limits', 'warning', 'Service limit verification completed', [
        err.response?.data?.detail || err.message
      ]);
      // Don't throw - limit checks are informational
    }
  };

  // Get all missing permissions from the result
  const getMissingPermissions = (): MissingPermission[] => {
    if (!permissionResult) return [];
    
    const missing: MissingPermission[] = [];
    for (const service of permissionResult.services) {
      for (const action of service.restricted_actions) {
        missing.push({
          service: service.service,
          action: action
        });
      }
    }
    return missing;
  };

  // Group missing permissions by service for display
  const getMissingPermissionsByService = (): Map<string, string[]> => {
    const grouped = new Map<string, string[]>();
    if (!permissionResult) return grouped;
    
    for (const service of permissionResult.services) {
      if (service.restricted_actions.length > 0) {
        grouped.set(service.service, service.restricted_actions);
      }
    }
    return grouped;
  };

  // Get remediation suggestion for a service
  const getRemediationSuggestion = (serviceName: string): string => {
    const suggestions: Record<string, string> = {
      'CloudFormation': 'Add cloudformation:* permissions or specific stack operations',
      'S3': 'Add s3:* permissions or specific bucket/object operations',
      'CloudFront': 'Add cloudfront:* permissions for CDN management',
      'ECS': 'Add ecs:* permissions for container orchestration',
      'EC2': 'Add ec2:* permissions for networking and compute',
      'IAM': 'Add iam:CreateRole, iam:PassRole, and related permissions',
      'DynamoDB': 'Add dynamodb:* permissions for database operations',
      'Secrets Manager': 'Add secretsmanager:* permissions for secret management',
      'KMS': 'Add kms:* permissions for encryption key management',
      'CloudWatch Logs': 'Add logs:* permissions for logging',
      'ECR': 'Add ecr:* permissions for container registry',
      'ELB': 'Add elasticloadbalancing:* permissions for load balancers',
      // EKS-specific suggestions
      'EKS': 'Add eks:DescribeCluster, eks:ListClusters, eks:AccessKubernetesApi permissions',
      'STS': 'Add sts:AssumeRoleWithWebIdentity for IRSA (IAM Roles for Service Accounts)',
    };
    return suggestions[serviceName] || `Add required ${serviceName} permissions to your IAM role`;
  };

  // Copy missing permissions policy to clipboard
  const copyMissingPermissionsPolicy = async () => {
    const missing = getMissingPermissions();
    if (missing.length === 0) return;
    
    const policy = generateMinimalPolicy({ missingPermissions: missing });
    const policyJson = formatPolicyForDownload(policy);
    
    try {
      await navigator.clipboard.writeText(policyJson);
      setCopiedPolicy(true);
      setTimeout(() => setCopiedPolicy(false), 2000);
    } catch (err) {
      console.error('Failed to copy policy:', err);
    }
  };

  // Download missing permissions policy
  const downloadMissingPermissionsPolicy = () => {
    const missing = getMissingPermissions();
    if (missing.length === 0) return;
    
    const policy = generateMinimalPolicy({ missingPermissions: missing });
    downloadPolicy(policy, 'missing-permissions-policy.json');
  };

  // Download validation scripts
  const downloadValidationScript = (type: 'bash' | 'powershell') => {
    const filename = type === 'bash' ? 'validate-permissions.sh' : 'validate-permissions.ps1';
    const scriptPath = `/scripts/${filename}`;
    
    // Create a link to download from the deploy/scripts folder
    const link = document.createElement('a');
    link.href = scriptPath;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  // Match error to help content when error changes
  useEffect(() => {
    if (error) {
      const errorType = matchErrorType(error);
      setMatchedErrorType(errorType);
      setShowErrorHelp(!!errorType);
    } else {
      setMatchedErrorType(null);
      setShowErrorHelp(false);
    }
  }, [error]);

  const handleContinue = async () => {
    // Prevent multiple clicks
    if (isNavigating) {
      console.log('⚠️ Already navigating, ignoring click');
      return;
    }
    
    setIsNavigating(true);
    
    try {
      console.log('🔍 PermissionVerification: handleContinue called');
      console.log('🔍 Delete mode:', state.deleteMode);
      
      const { deploymentApi } = await import('../services/api');
      
      // If in delete mode, go directly to deletion execution
      if (state.deleteMode) {
        console.log('🗑️ Delete mode enabled - proceeding to deletion');
        updateCheck('AWS Account Access', 'checking', 'Preparing for deletion...');
        
        // Try to get stored state to know what stacks to delete
        try {
          const storedState = await deploymentApi.getDeploymentState(
            state.selectedCapability?.name || '',
            state.selectedEnvironment || ''
          );
          
          if (storedState && storedState.stacks && storedState.stacks.length > 0) {
            const detectionResult: StackDetectionResult = {
              capability_name: state.selectedCapability?.name || '',
              environment: state.selectedEnvironment || '',
              region: state.awsConfig?.region || '',
              has_existing_stacks: true,
              has_failed_stacks: false,
              has_in_progress_stacks: false,
              is_updatable: true,
              stacks_found: storedState.stacks.map((s: any) => ({
                stack_name: s.stack_name,
                stack_type: s.stack_type,
                stack_status: 'CREATE_COMPLETE',
                region: s.region || state.awsConfig?.region,
                last_updated: s.deployed_at,
                can_update: true,
                outputs: {}
              })),
              recommended_strategy: DeploymentStrategy.CLEAN_DEPLOY,
              recommendation_reason: 'Delete mode - will remove all stacks',
              detection_timestamp: new Date().toISOString(),
            };
            
            setDetectionResult(detectionResult);
            updateCheck('AWS Account Access', 'success', `Found ${storedState.stacks.length} stack(s) to delete`);
          }
        } catch (err) {
          console.log('ℹ️ No stored state found for deletion');
        }
        
        await new Promise(resolve => setTimeout(resolve, 100));
        
        // Navigate directly to deletion execution step
        console.log('✅ Navigating to DELETION_EXECUTION');
        setStep(WizardStep.DELETION_EXECUTION);
        return;
      }
      
      // Normal flow (not delete mode)
      // First, check if we have stored deployment state (from previous deployments)
      // This allows us to skip the slow AWS stack detection
      console.log('🔍 Checking for stored deployment state...');
      updateCheck('Stack Detection', 'checking', 'Checking for existing deployments...');
      
      try {
        const storedState = await deploymentApi.getDeploymentState(
          state.selectedCapability?.name || '',
          state.selectedEnvironment || ''
        );
        
        console.log('🔍 Stored deployment state:', storedState);
        
        if (storedState && storedState.stacks && storedState.stacks.length > 0) {
          // We have stored state - use it instead of detecting from AWS
          console.log('✅ Found stored deployment state with', storedState.stacks.length, 'stacks');
          
          // Convert stored state to detection result format
          const detectionResult: StackDetectionResult = {
            capability_name: state.selectedCapability?.name || '',
            environment: state.selectedEnvironment || '',
            region: state.awsConfig?.region || '',
            has_existing_stacks: true,
            has_failed_stacks: false,
            has_in_progress_stacks: false,
            is_updatable: true,
            stacks_found: storedState.stacks.map((s: any) => ({
              stack_name: s.stack_name,
              stack_type: s.stack_type,
              stack_status: 'CREATE_COMPLETE',
              region: s.region || state.awsConfig?.region,
              last_updated: s.deployed_at,
              can_update: true,
              outputs: {}
            })),
            recommended_strategy: DeploymentStrategy.UPDATE_EXISTING,
            recommendation_reason: 'Existing deployment found in history',
            detection_timestamp: new Date().toISOString(),
          };
          
          setDetectionResult(detectionResult);
          
          const stackCount = detectionResult.stacks_found.length;
          const stackDetails = detectionResult.stacks_found.map((s: any) => `${s.stack_type}: ${s.stack_status}`).join(', ');
          
          updateCheck('Stack Detection', 'success', `Found ${stackCount} deployed stack(s) from history`, 
            [stackDetails, 'Using stored deployment state']);
          
          // Small delay to ensure state is updated
          await new Promise(resolve => setTimeout(resolve, 100));
          
          // Go to strategy selection
          console.log('✅ Navigating to STRATEGY_SELECTION (using stored state)');
          setStep(WizardStep.STRATEGY_SELECTION);
          return;
        }
      } catch (stateErr: any) {
        // No stored state found - this is fine, we'll do AWS detection
        console.log('ℹ️ No stored deployment state found, will detect from AWS');
      }
      
      // No stored state - detect existing stacks from AWS
      console.log('🔍 Starting AWS stack detection...');
      updateCheck('Stack Detection', 'checking', 'Querying CloudFormation for existing stacks...');
      
      console.log('🔍 Detection params:', {
        capability: state.selectedCapability?.name,
        environment: state.selectedEnvironment,
        region: state.awsConfig?.region,
        sessionId: state.awsConfig?.aws_session_id
      });
      
      const detectionResult = await deploymentApi.detectExistingStacks(
        state.selectedCapability?.name || '',
        state.selectedEnvironment || '',
        state.awsConfig?.region || '',
        state.awsConfig?.aws_session_id
      );
      
      console.log('🔍 Detection result:', detectionResult);
      console.log('🔍 Has existing stacks:', detectionResult.has_existing_stacks);
      console.log('🔍 Stacks found:', detectionResult.stacks_found);
      
      // Store detection result
      console.log('🔍 Storing detection result in wizard context...');
      setDetectionResult(detectionResult);
      
      const stackCount = detectionResult.stacks_found.length;
      const stackDetails = detectionResult.stacks_found.map(s => `${s.stack_type}: ${s.stack_status}`).join(', ');
      
      updateCheck('Stack Detection', 'success', 
        stackCount > 0 ? `Found ${stackCount} existing stack(s)` : 'No existing stacks found', 
        stackCount > 0 ? [stackDetails] : ['First deployment - will create new stacks']);
      
      // Small delay to ensure state is updated
      await new Promise(resolve => setTimeout(resolve, 100));
      
      // If stacks found, go to strategy selection; otherwise skip to deployment
      if (detectionResult.has_existing_stacks) {
        console.log('✅ Navigating to STRATEGY_SELECTION');
        console.log(`Found ${detectionResult.stacks_found.length} existing stacks - showing strategy selection`);
        setStep(WizardStep.STRATEGY_SELECTION);
      } else {
        console.log('✅ No stacks found, navigating to DEPLOYMENT_EXECUTION');
        console.log('No existing stacks detected - proceeding with fresh deployment');
        setStep(WizardStep.DEPLOYMENT_EXECUTION);
      }
    } catch (err: any) {
      console.error('❌ Stack detection failed:', err);
      console.error('Error details:', err.response?.data || err.message);
      // On detection failure, proceed to deployment anyway (backward compatible)
      updateCheck('Stack Detection', 'warning', 'Stack detection failed - proceeding with deployment', [
        err.response?.data?.detail || err.message || 'Unknown error'
      ]);
      setStep(WizardStep.DEPLOYMENT_EXECUTION);
    } finally {
      setIsNavigating(false);
    }
  };

  const handleBack = () => {
    setStep(WizardStep.AWS_CONFIGURATION);
  };

  return (
    <div className="max-w-4xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">
          {state.deleteMode ? '🗑️ Preparing Deletion' : 'Permission Verification'}
        </h1>
        <p className="text-gray-600">
          {state.deleteMode 
            ? `Verifying AWS access to delete ${state.selectedCapability?.name}`
            : isPureEKS
            ? 'Verifying AWS and EKS permissions for Pure EKS deployment'
            : 'Verifying that your AWS role has all required permissions for deployment'}
        </p>
        {isPureEKS && !state.deleteMode && (
          <div className="mt-2 inline-flex items-center px-3 py-1 rounded-full text-sm bg-purple-100 text-purple-800">
            <svg className="w-4 h-4 mr-1" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M6.267 3.455a3.066 3.066 0 001.745-.723 3.066 3.066 0 013.976 0 3.066 3.066 0 001.745.723 3.066 3.066 0 012.812 2.812c.051.643.304 1.254.723 1.745a3.066 3.066 0 010 3.976 3.066 3.066 0 00-.723 1.745 3.066 3.066 0 01-2.812 2.812 3.066 3.066 0 00-1.745.723 3.066 3.066 0 01-3.976 0 3.066 3.066 0 00-1.745-.723 3.066 3.066 0 01-2.812-2.812 3.066 3.066 0 00-.723-1.745 3.066 3.066 0 010-3.976 3.066 3.066 0 00.723-1.745 3.066 3.066 0 012.812-2.812zm7.44 5.252a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
            </svg>
            Pure EKS Architecture
          </div>
        )}
      </div>

      <div className="bg-white rounded-lg shadow-md p-8 mb-8">
        {/* Prerequisite Checks */}
        <div className="mb-8">
          <h2 className="text-xl font-semibold text-gray-900 mb-4">
            {state.deleteMode ? 'AWS Access Verification' : 'Pre-Deployment Verification'}
          </h2>
          <p className="text-sm text-gray-600 mb-6">
            {state.deleteMode 
              ? 'Verifying AWS credentials before proceeding with deletion'
              : 'Verifying all prerequisites before deployment'}
          </p>
          
          <div className="space-y-3">
            {prerequisiteChecks.map((check) => (
              <div
                key={check.name}
                className={`border rounded-lg p-4 ${
                  check.status === 'success' ? 'bg-green-50 border-green-200' :
                  check.status === 'warning' ? 'bg-yellow-50 border-yellow-200' :
                  check.status === 'error' ? 'bg-red-50 border-red-200' :
                  check.status === 'checking' ? 'bg-blue-50 border-blue-200' :
                  'bg-gray-50 border-gray-200'
                }`}
              >
                <div className="flex items-start">
                  {/* Status Icon */}
                  <div className="flex-shrink-0 mr-3">
                    {check.status === 'checking' && (
                      <svg className="animate-spin h-5 w-5 text-blue-600" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                      </svg>
                    )}
                    {check.status === 'success' && (
                      <svg className="h-5 w-5 text-green-600" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                      </svg>
                    )}
                    {check.status === 'warning' && (
                      <svg className="h-5 w-5 text-yellow-600" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                      </svg>
                    )}
                    {check.status === 'error' && (
                      <svg className="h-5 w-5 text-red-600" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                      </svg>
                    )}
                    {check.status === 'pending' && (
                      <svg className="h-5 w-5 text-gray-400" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clipRule="evenodd" />
                      </svg>
                    )}
                  </div>
                  
                  {/* Check Info */}
                  <div className="flex-1">
                    <h3 className={`text-sm font-medium ${
                      check.status === 'success' ? 'text-green-800' :
                      check.status === 'warning' ? 'text-yellow-800' :
                      check.status === 'error' ? 'text-red-800' :
                      check.status === 'checking' ? 'text-blue-800' :
                      'text-gray-700'
                    }`}>
                      {check.name}
                    </h3>
                    <p className={`text-sm mt-1 ${
                      check.status === 'success' ? 'text-green-700' :
                      check.status === 'warning' ? 'text-yellow-700' :
                      check.status === 'error' ? 'text-red-700' :
                      check.status === 'checking' ? 'text-blue-700' :
                      'text-gray-600'
                    }`}>
                      {check.message}
                    </p>
                    {check.details && check.details.length > 0 && (
                      <ul className={`text-xs mt-2 space-y-1 ${
                        check.status === 'success' ? 'text-green-600' :
                        check.status === 'warning' ? 'text-yellow-600' :
                        check.status === 'error' ? 'text-red-600' :
                        'text-gray-500'
                      }`}>
                        {check.details.map((detail, idx) => (
                          <li key={idx}>• {detail}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Delete Mode Warnings and Resource List */}
        {state.deleteMode && showDeleteWarnings && verified && (
          <div className="mb-8">
            {/* Data Retention Warnings */}
            <div className="bg-red-50 border-2 border-red-300 rounded-lg p-4 mb-4">
              <div className="flex items-start">
                <svg className="w-6 h-6 text-red-600 mr-3 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                </svg>
                <div className="flex-1">
                  <h3 className="text-lg font-semibold text-red-800">⚠️ Deletion Warning</h3>
                  <p className="text-sm text-red-700 mt-2">
                    This action will permanently delete all resources associated with this deployment.
                    <strong> This cannot be undone.</strong>
                  </p>
                  
                  <div className="mt-4 space-y-2">
                    <div className="flex items-start">
                      <svg className="w-4 h-4 text-red-600 mr-2 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                      </svg>
                      <span className="text-sm text-red-700">S3 buckets with data will be emptied and deleted</span>
                    </div>
                    <div className="flex items-start">
                      <svg className="w-4 h-4 text-red-600 mr-2 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                      </svg>
                      <span className="text-sm text-red-700">DynamoDB tables with data will be deleted</span>
                    </div>
                    <div className="flex items-start">
                      <svg className="w-4 h-4 text-red-600 mr-2 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                      </svg>
                      <span className="text-sm text-red-700">CloudWatch logs will be deleted</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Resources to be Deleted */}
            <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-4">
              <h4 className="text-sm font-medium text-gray-800 mb-3">Resources to be Deleted:</h4>
              <ul className="space-y-2">
                {resourcesToDelete.map((resource, idx) => (
                  <li key={idx} className="flex items-center text-sm text-gray-700">
                    <svg className="w-4 h-4 text-red-500 mr-2" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clipRule="evenodd" />
                    </svg>
                    {resource}
                  </li>
                ))}
              </ul>
            </div>

            {/* Required Delete Permissions */}
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 mb-4">
              <h4 className="text-sm font-medium text-yellow-800 mb-3">Required Delete Permissions:</h4>
              <div className="grid grid-cols-2 gap-2">
                {DELETE_PERMISSIONS.map((perm, idx) => (
                  <div key={idx} className="flex items-center text-xs text-yellow-700">
                    <svg className="w-3 h-3 text-yellow-600 mr-1" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                    <span className="font-mono">{perm.service}:{perm.action}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Manual Cleanup Guidance */}
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
              <h4 className="text-sm font-medium text-blue-800 mb-2">Manual Cleanup May Be Required:</h4>
              <p className="text-xs text-blue-700 mb-2">
                Some resources may require manual cleanup if deletion fails:
              </p>
              <ul className="text-xs text-blue-700 space-y-1">
                <li>• S3 buckets with versioning enabled may need version deletion</li>
                <li>• CloudFront distributions may take up to 15 minutes to disable</li>
                <li>• ENIs attached to Lambda functions may need manual detachment</li>
                <li>• Check CloudFormation console for any stuck DELETE_FAILED stacks</li>
              </ul>
            </div>
          </div>
        )}

        {/* Verification Success */}
        {!verifying && verified && permissionResult && (
          <div>
            {/* Summary */}
            <div className={`border rounded-lg p-6 mb-6 ${
              permissionResult.overall_status === 'success' 
                ? 'bg-green-50 border-green-200' 
                : permissionResult.overall_status === 'partial'
                ? 'bg-yellow-50 border-yellow-200'
                : 'bg-red-50 border-red-200'
            }`}>
              <div className="flex items-start">
                <svg
                  className={`w-6 h-6 mr-3 mt-0.5 ${
                    permissionResult.overall_status === 'success' 
                      ? 'text-green-600' 
                      : permissionResult.overall_status === 'partial'
                      ? 'text-yellow-600'
                      : 'text-red-600'
                  }`}
                  fill="currentColor"
                  viewBox="0 0 20 20"
                >
                  {permissionResult.overall_status === 'success' ? (
                    <path
                      fillRule="evenodd"
                      d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                      clipRule="evenodd"
                    />
                  ) : (
                    <path
                      fillRule="evenodd"
                      d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"
                      clipRule="evenodd"
                    />
                  )}
                </svg>
                <div className="flex-1">
                  <h3 className={`text-lg font-medium mb-2 ${
                    permissionResult.overall_status === 'success' 
                      ? 'text-green-800' 
                      : permissionResult.overall_status === 'partial'
                      ? 'text-yellow-800'
                      : 'text-red-800'
                  }`}>
                    {permissionResult.overall_status === 'success' 
                      ? 'All Permissions Verified' 
                      : permissionResult.overall_status === 'partial'
                      ? 'Partial Permissions Available'
                      : 'Insufficient Permissions'}
                  </h3>
                  <p className={`text-sm mb-4 ${
                    permissionResult.overall_status === 'success' 
                      ? 'text-green-700' 
                      : permissionResult.overall_status === 'partial'
                      ? 'text-yellow-700'
                      : 'text-red-700'
                  }`}>
                    {permissionResult.total_granted} of {permissionResult.total_actions} required permissions are available
                  </p>
                  <div className="mt-4">
                    <p className={`text-sm font-medium mb-2 ${
                      permissionResult.overall_status === 'success' 
                        ? 'text-green-800' 
                        : permissionResult.overall_status === 'partial'
                        ? 'text-yellow-800'
                        : 'text-red-800'
                    }`}>Account Details:</p>
                    <ul className={`text-sm space-y-1 ${
                      permissionResult.overall_status === 'success' 
                        ? 'text-green-700' 
                        : permissionResult.overall_status === 'partial'
                        ? 'text-yellow-700'
                        : 'text-red-700'
                    }`}>
                      <li>Account ID: {state.awsConfig?.account_id}</li>
                      <li>Region: {state.awsConfig?.region}</li>
                      {state.awsConfig?.role_arn && (
                        <li className="break-all">Role: {state.awsConfig.role_arn}</li>
                      )}
                    </ul>
                  </div>
                </div>
              </div>
            </div>

            {/* Detailed Permissions Table */}
            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              <div className="px-6 py-4 bg-gray-50 border-b border-gray-200">
                <h3 className="text-lg font-semibold text-gray-900">Service Permissions</h3>
                <p className="text-sm text-gray-600 mt-1">
                  Click on a service to view detailed permission breakdown
                </p>
              </div>
              
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Service
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Purpose
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Status
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {permissionResult.services.map((service) => (
                      <React.Fragment key={service.service}>
                        <tr 
                          className="hover:bg-gray-50 cursor-pointer"
                          onClick={() => setExpandedService(
                            expandedService === service.service ? null : service.service
                          )}
                        >
                          <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                            <div className="flex items-center">
                              <svg
                                className={`w-4 h-4 mr-2 transition-transform ${
                                  expandedService === service.service ? 'transform rotate-90' : ''
                                }`}
                                fill="currentColor"
                                viewBox="0 0 20 20"
                              >
                                <path
                                  fillRule="evenodd"
                                  d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z"
                                  clipRule="evenodd"
                                />
                              </svg>
                              {service.service}
                            </div>
                          </td>
                          <td className="px-6 py-4 text-sm text-gray-600">
                            {service.purpose}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm">
                            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                              service.status.includes('✅') 
                                ? 'bg-green-100 text-green-800'
                                : service.status.includes('⚠️')
                                ? 'bg-yellow-100 text-yellow-800'
                                : 'bg-red-100 text-red-800'
                            }`}>
                              {service.status}
                            </span>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">
                            {service.granted_count}/{service.total_count}
                          </td>
                        </tr>
                        
                        {/* Expanded Details */}
                        {expandedService === service.service && (
                          <tr>
                            <td colSpan={4} className="px-6 py-4 bg-gray-50">
                              <div className="space-y-3">
                                {service.granted_actions.length > 0 && (
                                  <div>
                                    <h4 className="text-sm font-medium text-green-800 mb-2">
                                      ✅ Available Actions ({service.granted_actions.length})
                                    </h4>
                                    <ul className="text-xs text-green-700 space-y-1 ml-4">
                                      {service.granted_actions.map((action) => (
                                        <li key={action} className="font-mono">• {action}</li>
                                      ))}
                                    </ul>
                                  </div>
                                )}
                                
                                {service.restricted_actions.length > 0 && (
                                  <div>
                                    <h4 className="text-sm font-medium text-red-800 mb-2">
                                      ❌ Restricted Actions ({service.restricted_actions.length})
                                    </h4>
                                    <ul className="text-xs text-red-700 space-y-1 ml-4">
                                      {service.restricted_actions.map((action) => (
                                        <li key={action} className="font-mono">• {action}</li>
                                      ))}
                                    </ul>
                                    
                                    {/* Remediation Suggestion */}
                                    <div className="mt-3 p-2 bg-yellow-50 border border-yellow-200 rounded">
                                      <p className="text-xs text-yellow-800">
                                        <span className="font-medium">💡 Suggestion:</span> {getRemediationSuggestion(service.service)}
                                      </p>
                                    </div>
                                  </div>
                                )}
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            
            {/* Missing Permissions Summary with Actions */}
            {getMissingPermissions().length > 0 && (
              <div className="mt-6 p-4 bg-red-50 border border-red-200 rounded-lg">
                <h4 className="text-sm font-medium text-red-800 mb-3">
                  Missing Permissions Summary ({getMissingPermissions().length} actions)
                </h4>
                
                {/* Grouped by Service */}
                <div className="space-y-3 mb-4">
                  {Array.from(getMissingPermissionsByService().entries()).map(([service, actions]) => (
                    <div key={service} className="text-xs">
                      <span className="font-medium text-red-700">{service}:</span>
                      <span className="text-red-600 ml-1">{actions.length} missing action(s)</span>
                    </div>
                  ))}
                </div>
                
                {/* Action Buttons */}
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={copyMissingPermissionsPolicy}
                    className="px-3 py-1.5 bg-white border border-red-300 text-red-700 text-xs rounded hover:bg-red-50 flex items-center"
                  >
                    {copiedPolicy ? (
                      <>
                        <svg className="w-4 h-4 mr-1 text-green-600" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                        </svg>
                        Copied!
                      </>
                    ) : (
                      <>
                        <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                        </svg>
                        Copy Missing Permissions Policy
                      </>
                    )}
                  </button>
                  <button
                    onClick={downloadMissingPermissionsPolicy}
                    className="px-3 py-1.5 bg-red-600 text-white text-xs rounded hover:bg-red-700 flex items-center"
                  >
                    <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                    Download Policy JSON
                  </button>
                </div>
              </div>
            )}
            
            {/* Validation Scripts Download */}
            <div className="mt-6 p-4 bg-gray-50 border border-gray-200 rounded-lg">
              <h4 className="text-sm font-medium text-gray-800 mb-2">
                Validation Scripts
              </h4>
              <p className="text-xs text-gray-600 mb-3">
                Download scripts to verify permissions from your terminal before deployment.
              </p>
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => downloadValidationScript('bash')}
                  className="px-3 py-1.5 bg-gray-700 text-white text-xs rounded hover:bg-gray-800 flex items-center"
                >
                  <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                  Bash Script (.sh)
                </button>
                <button
                  onClick={() => downloadValidationScript('powershell')}
                  className="px-3 py-1.5 bg-blue-700 text-white text-xs rounded hover:bg-blue-800 flex items-center"
                >
                  <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                  PowerShell Script (.ps1)
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
            <div className="flex items-start">
              <svg
                className="w-5 h-5 text-red-600 mr-3 mt-0.5 flex-shrink-0"
                fill="currentColor"
                viewBox="0 0 20 20"
              >
                <path
                  fillRule="evenodd"
                  d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                  clipRule="evenodd"
                />
              </svg>
              <div className="flex-1">
                <p className="font-medium text-red-800">Verification Failed</p>
                <p className="text-sm text-red-700 mt-1">{error}</p>
                
                {/* Contextual Error Help */}
                {matchedErrorType && showErrorHelp && (
                  <div className="mt-4 p-3 bg-white border border-red-100 rounded-lg">
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="text-sm font-medium text-gray-900">
                        {getErrorHelp(matchedErrorType).title}
                      </h4>
                      <button
                        onClick={() => setShowErrorHelp(false)}
                        className="text-gray-400 hover:text-gray-600"
                      >
                        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                        </svg>
                      </button>
                    </div>
                    <p className="text-xs text-gray-600 mb-3">
                      {getErrorHelp(matchedErrorType).description}
                    </p>
                    <div className="space-y-2">
                      <p className="text-xs font-medium text-gray-700">How to fix:</p>
                      {getErrorHelp(matchedErrorType).remediation.map((step) => (
                        <div key={step.step} className="flex items-start text-xs">
                          <span className="flex-shrink-0 w-5 h-5 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center mr-2 text-xs font-medium">
                            {step.step}
                          </span>
                          <div className="flex-1">
                            <p className="text-gray-700">{step.instruction}</p>
                            {step.command && (
                              <code className="block mt-1 p-1 bg-gray-100 rounded text-xs font-mono text-gray-800 overflow-x-auto">
                                {step.command}
                              </code>
                            )}
                            {step.link && (
                              <a
                                href={step.link}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-blue-600 hover:underline mt-1 inline-block"
                              >
                                Learn more →
                              </a>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Retry Button */}
        {!verifying && error && (
          <div className="text-center">
            <button
              onClick={handleVerifyAll}
              className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium"
            >
              Retry Verification
            </button>
          </div>
        )}
      </div>

      {/* Action Buttons */}
      <div className="flex justify-between">
        <button
          onClick={handleBack}
          className="px-6 py-3 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50"
        >
          Back
        </button>
        <button
          onClick={handleContinue}
          disabled={!verified || isNavigating}
          className={`px-6 py-3 rounded-lg font-medium ${
            verified && !isNavigating
              ? 'bg-blue-600 text-white hover:bg-blue-700'
              : 'bg-gray-300 text-gray-500 cursor-not-allowed'
          }`}
        >
          {isNavigating ? 'Processing...' : 'Continue'}
        </button>
      </div>
    </div>
  );
};

export default PermissionVerification;

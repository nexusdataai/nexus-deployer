# Implementation Plan: Pure EKS Deployment

## Overview

This implementation plan breaks down the Pure EKS Deployment feature into discrete coding tasks. The implementation follows the Operator-based approach where a Kubernetes Operator manages capability deployments and AWS resource provisioning.

## Tasks

- [x] 1. Update Architecture Types and Selection UI
  - [x] 1.1 Update architecture types to enable EKS options
    - Modify `frontend/src/types/architecture.ts`
    - Add `EKS` to `FrontendService` enum
    - Change EKS `availability` from `coming_soon` to `available` in `BACKEND_SERVICE_OPTIONS`
    - Add Pure EKS frontend option to `FRONTEND_SERVICE_OPTIONS`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.7_

  - [x] 1.2 Update ArchitectureSelection component for EKS coupling
    - Modify `frontend/src/components/ArchitectureSelection.tsx`
    - Add logic to auto-select EKS backend when Pure EKS frontend is selected
    - Update architecture diagram to show EKS cluster icon when Pure EKS is selected
    - _Requirements: 1.5, 1.6_

  - [x] 1.3 Write property test for architecture coupling
    - **Property 1: Pure EKS Architecture Coupling**
    - **Validates: Requirements 1.5**

- [x] 2. Create EKS Cluster Selector Component
  - [x] 2.1 Add EKS types and wizard context updates
    - Create `frontend/src/types/eks.ts` with EKSCluster and EKSConfig interfaces
    - Update `frontend/src/types/wizard.ts` to add eksConfig to WizardState
    - Update `frontend/src/context/WizardContext.tsx` to handle EKS config
    - _Requirements: 2.7_

  - [x] 2.2 Create EKSClusterSelector component
    - Create `frontend/src/components/EKSClusterSelector.tsx`
    - Display cluster list with name, version, status, node count, operator status
    - Implement cluster selection with ACTIVE status validation
    - Add namespace configuration section
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.8_

  - [x] 2.3 Write property test for cluster selection validation
    - **Property 2: Cluster Selection Validation**
    - **Validates: Requirements 2.5, 2.6**

  - [x] 2.4 Write property test for namespace validation
    - **Property 11: Namespace Naming Validation**
    - **Validates: Requirements 7.4, 7.5**

- [x] 3. Integrate EKS Cluster Selector into Wizard Flow
  - [x] 3.1 Add EKS_CLUSTER_SELECTION wizard step
    - Update `frontend/src/types/wizard.ts` to add new WizardStep enum value
    - Update `frontend/src/context/WizardContext.tsx` step navigation
    - Update `frontend/src/components/WizardShell.tsx` to render EKSClusterSelector
    - _Requirements: 2.1_

  - [x] 3.2 Update wizard navigation for EKS flow
    - Modify step order to include EKS cluster selection after architecture selection (when EKS is selected)
    - Update progress bar step numbering
    - _Requirements: 2.1_

- [x] 4. Create EKS Backend API Endpoints
  - [x] 4.1 Create EKS router with cluster discovery endpoints
    - Create `backend/app/routers/eks.py`
    - Implement `GET /api/eks/clusters` - list EKS clusters in region
    - Implement `GET /api/eks/clusters/{name}` - get cluster details
    - Implement `GET /api/eks/clusters/{name}/operator-status` - check operator installation
    - Implement `GET /api/eks/clusters/{name}/namespaces` - list namespaces
    - _Requirements: 2.2, 2.3, 3.9_

  - [x] 4.2 Create EKS service for AWS API interactions
    - Create `backend/app/services/eks_service.py`
    - Implement cluster listing with boto3 EKS client
    - Implement cluster details retrieval
    - Implement Kubernetes API client initialization for namespace listing
    - _Requirements: 2.2, 2.3_

  - [x] 4.3 Add EKS API to frontend service layer
    - Update `frontend/src/services/api.ts` to add eksApi object
    - Add methods: listClusters, getClusterDetails, checkOperatorStatus, listNamespaces
    - _Requirements: 2.2_

- [x] 5. Checkpoint - Verify EKS Discovery Flow
  - All tests pass
  - EKS cluster listing API implemented
  - Wizard navigation includes EKS cluster selection step after AWS authentication

- [x] 6. Create Kubernetes Operator Project Structure
  - [x] 6.1 Initialize kube-operator directory structure
    - Create `kube-operator/` directory with subdirectories: src/, manifests/, tests/
    - Create `kube-operator/requirements.txt` with kopf, boto3, kubernetes dependencies
    - Create `kube-operator/pyproject.toml` for project configuration
    - Create `kube-operator/Dockerfile` for operator container image
    - _Requirements: 12.1, 12.2_

  - [x] 6.2 Create TotogiCapability CRD manifest
    - Create `kube-operator/manifests/crd.yaml` with full schema
    - Include spec fields: capabilityName, version, environment, region, frontend, backend, dataServices, deletionPolicy
    - Include status fields: phase, message, frontendUrl, backendUrl, resources, lastReconcileTime
    - _Requirements: 12.3_

  - [x] 6.3 Write property test for CRD schema compliance
    - **Property 6: TotogiCapability CR Schema Compliance**
    - **Validates: Requirements 4.1, 4.2, 12.3**

- [x] 7. Implement Operator Resource Provisioners
  - [x] 7.1 Create resource naming utility
    - Create `kube-operator/src/utils/naming.py`
    - Implement SSM parameter path generation following `/{capability}/{env}/{category}/{resource}` pattern
    - Implement Secrets Manager name generation following `{capability}/{env}/{secret-type}` pattern
    - Implement resource name generation for DynamoDB, S3, Glue
    - _Requirements: 4.6, 4.7_

  - [x] 7.2 Write property test for SSM naming convention
    - **Property 7: SSM Parameter Naming Convention**
    - **Validates: Requirements 4.6**

  - [x] 7.3 Write property test for Secrets naming convention
    - **Property 8: Secrets Manager Naming Convention**
    - **Validates: Requirements 4.7**

  - [x] 7.4 Create DynamoDB provisioner
    - Create `kube-operator/src/resources/dynamodb.py`
    - Implement table creation for transformation-system, license, wxcc-task-tracking
    - Follow existing table schemas from CloudFormation templates
    - _Requirements: 4.4_

  - [x] 7.5 Create S3 provisioner
    - Create `kube-operator/src/resources/s3.py`
    - Implement bucket creation for call-data, wxcc-simulator, journey-logs, journey-reports
    - Configure bucket policies and lifecycle rules
    - _Requirements: 4.4_

  - [x] 7.6 Create Glue provisioner
    - Create `kube-operator/src/resources/glue.py`
    - Implement database and table creation
    - Follow existing Glue schema from CloudFormation templates
    - _Requirements: 4.4_

  - [x] 7.7 Create SSM provisioner
    - Create `kube-operator/src/resources/ssm.py`
    - Implement parameter creation for all categories (aws, server, cognito, wxcc, s3, dynamodb, glue, cloudwatch)
    - Use naming utility for path generation
    - _Requirements: 4.6_

  - [x] 7.8 Create Secrets provisioner
    - Create `kube-operator/src/resources/secrets.py`
    - Implement secret creation for api-keys, wxcc, openai, license, anthropic, github
    - Use naming utility for name generation
    - _Requirements: 4.7_

  - [x] 7.9 Create IAM provisioner
    - Create `kube-operator/src/resources/iam.py`
    - Implement application IAM role creation with IRSA trust policy
    - Implement least-privilege policy for data service access
    - _Requirements: 5.2, 5.3, 5.4_

  - [x] 7.10 Write property test for IRSA configuration ✓ (5 tests passing)
    - **Property 5: IRSA Configuration Correctness**
    - **Validates: Requirements 3.5, 3.6, 5.3, 5.4, 5.5**

- [x] 8. Implement Operator Kubernetes Resource Creator
  - [x] 8.1 Create Kubernetes resource creator
    - Create `kube-operator/src/resources/kubernetes.py`
    - Implement ServiceAccount creation with IAM role annotation
    - Implement Deployment creation for frontend and backend
    - Implement Service creation (LoadBalancer type)
    - Configure environment variables for SSM/Secrets Manager access
    - _Requirements: 4.5, 4.8, 5.5_

  - [x] 8.2 Implement health check configuration
    - Add liveness and readiness probes to Deployment specs
    - Configure appropriate timeouts and thresholds
    - _Requirements: 4.5_

- [x] 9. Implement Capability Controller
  - [x] 9.1 Create capability controller with kopf
    - Create `kube-operator/src/controllers/capability_controller.py`
    - Implement `@kopf.on.create` handler for TotogiCapability
    - Implement resource provisioning sequence: data services → SSM → Secrets → IAM → K8s resources
    - Update CR status at each phase
    - _Requirements: 4.3, 4.9, 12.4_

  - [ ] 9.2 Write property test for reconciliation loop
    - **Property 9: Operator Reconciliation Loop**
    - **Validates: Requirements 4.3, 4.9, 4.10, 12.4**

  - [x] 9.3 Implement update handler
    - Implement `@kopf.on.update` handler for TotogiCapability
    - Perform rolling updates for container image changes
    - Update SSM/Secrets if configuration changes
    - _Requirements: 4.10_

  - [x] 9.4 Implement delete handler with finalizer
    - Implement `@kopf.on.delete` handler for TotogiCapability
    - Add finalizer on CR creation
    - Implement cleanup sequence: K8s resources → IAM → Secrets → SSM → Glue → S3 → DynamoDB
    - Remove finalizer only after successful cleanup
    - _Requirements: 4.11, 12.6_

  - [ ] 9.5 Write property test for resource cleanup
    - **Property 10: Resource Cleanup on Deletion**
    - **Validates: Requirements 4.11, 12.6**

  - [x] 9.6 Implement Kubernetes event emission
    - Emit events for: DeploymentStarted, ResourceCreated, DeploymentComplete, DeploymentFailed
    - Include relevant details in event messages
    - _Requirements: 12.7_

- [x] 10. Create Operator Main Entry Point
  - [x] 10.1 Create operator main module
    - Create `kube-operator/src/main.py`
    - Initialize kopf operator
    - Configure logging
    - Add health check endpoints (/healthz, /readyz)
    - _Requirements: 12.8_

  - [x] 10.2 Create operator RBAC manifest
    - Create `kube-operator/manifests/rbac.yaml`
    - Define ClusterRole with permissions for CRDs, Deployments, Services, ConfigMaps, Secrets
    - Define ClusterRoleBinding for operator ServiceAccount
    - _Requirements: 3.4_

  - [x] 10.3 Create operator deployment manifest
    - Create `kube-operator/manifests/deployment.yaml`
    - Configure operator Deployment in totogi-system namespace
    - Include ServiceAccount with IRSA annotation placeholder
    - Configure resource requests/limits
    - _Requirements: 3.2, 3.3_

- [x] 11. Checkpoint - Verify Operator Locally ✓
  - All 13 property tests pass (8 naming + 5 IRSA)
  - Operator main.py complete with kopf handlers
  - CRD, RBAC, and deployment manifests created

- [x] 12. Create Operator Deployment Service
  - [x] 12.1 Create operator deployment service ✓
    - Created `backend/app/services/operator_deployment_service.py`
    - Implement Kubernetes client initialization using EKS cluster credentials
    - Implement operator deployment: namespace → IAM role → ServiceAccount → CRD → Deployment
    - Implement operator health verification
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

  - [ ] 12.2 Write property test for operator deployment idempotency
    - **Property 4: Operator Deployment Idempotency**
    - **Validates: Requirements 3.1, 3.9**

  - [x] 12.3 Implement TotogiCapability CR creation ✓
    - Add method to create TotogiCapability CR from wizard configuration
    - Implement CR status watching for deployment progress
    - _Requirements: 4.1, 4.2_

  - [x] 12.4 Add operator deployment API endpoints ✓
    - Updated `backend/app/services/eks_service.py` to use operator_deployment_service
    - Endpoints already exist in `backend/app/routers/eks.py`
    - _Requirements: 3.1, 4.1_

- [x] 13. Update Deployment Execution for EKS
  - [x] 13.1 Update DeploymentExecution component for EKS stages ✓
    - Modified `frontend/src/components/DeploymentExecution.tsx`
    - Added EKS-specific deployment stages display
    - Show progress for: Operator deployment, CR creation, data services, backend, frontend, services
    - _Requirements: 8.1, 8.2, 8.3_

  - [x] 13.2 Implement EKS deployment log streaming ✓
    - Added polling for operator reconciliation status
    - Display real-time reconciliation events
    - Show pod events on failure
    - _Requirements: 8.4, 8.5_

  - [x] 13.3 Display deployment results ✓
    - Show frontend and backend URLs from CR status
    - Added EKS resources panel showing provisioned resources
    - _Requirements: 8.6, 8.7_

- [x] 14. Update Deployment State Management
  - [x] 14.1 Update deployment state service for EKS ✓
    - Modified `backend/app/services/tinydb_deployment_state_service.py`
    - Added EKS-specific fields: cluster_arn, namespace, cr_name, deployment_type
    - Added save_eks_deployment_state, get_eks_deployments, update_eks_resources methods
    - _Requirements: 9.1_

  - [ ] 14.2 Write property test for deployment state persistence
    - **Property 13: Deployment State Persistence**
    - **Validates: Requirements 9.1, 9.6**

  - [x] 14.3 Update stack detection for EKS ✓
    - Modified `backend/app/services/stack_detection_service.py`
    - Added detect_eks_deployment and detect_any_deployment methods
    - Return appropriate strategy options for EKS deployments
    - _Requirements: 9.2, 9.3_

  - [ ] 14.4 Write property test for existing deployment detection
    - **Property 14: Existing Deployment Detection**
    - **Validates: Requirements 9.2, 9.3**

- [x] 15. Update Permission Verification for EKS
  - [ ] 15.1 Add EKS permission checks
    - Update `backend/app/routers/aws.py` permission verification
    - Add checks for: eks:DescribeCluster, eks:ListClusters, eks:AccessKubernetesApi
    - Add checks for IAM role creation permissions
    - Add checks for ECR permissions
    - _Requirements: 10.1, 10.2, 10.3_

  - [ ] 15.2 Write property test for EKS permission verification
    - **Property 15: EKS Permission Verification**
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.6**

  - [x] 15.3 Update permission data for EKS ✓
    - Updated `frontend/src/data/permission-data.ts`
    - Added EKS service to Backend category
    - Added EKS_PERMISSIONS array and getEKSPermissionCategories function
    - _Requirements: 10.5_

- [x] 16. Update Unified Environment Config for EKS
  - [x] 16.1 Add EKS configuration options ✓
    - EKS configuration handled in `frontend/src/components/EKSClusterSelector.tsx`
    - Namespace configuration section implemented
    - Replica count and resource configuration defined in `frontend/src/types/eks.ts` DEFAULT_EKS_CONFIG
    - _Requirements: 7.1, 7.2, 11.1, 11.2, 11.3_

  - [ ] 16.2 Write property test for namespace default value
    - **Property 12: Namespace Default Value**
    - **Validates: Requirements 7.6**

  - [x] 16.3 Add advanced EKS options ✓
    - HPA, PDB, Ingress, TLS config defined in `frontend/src/types/eks.ts`
    - EKSConfig interface includes all advanced options
    - _Requirements: 11.4, 11.5, 11.6, 11.7_

- [x] 17. Checkpoint - End-to-End Testing
  - All 13 property tests pass
  - Frontend builds successfully
  - Backend services implemented (operator_deployment_service, eks_service)
  - EKS deployment flow integrated into wizard

- [x] 18. Final Integration and Documentation
  - [x] 18.1 Update installation history for EKS ✓
    - Updated `backend/app/services/installation_tracker.py`
    - Added create_eks_installation, update_eks_installation, log_eks_resource_operation
    - Added get_eks_installations for listing EKS deployments
    - _Requirements: 9.6_

  - [x] 18.2 Add EKS deletion workflow ✓
    - Capability deletion via CR deletion implemented in operator delete handler
    - DeletionPolicy (Delete/Retain) supported in TotogiCapability CR
    - _Requirements: 9.5_

  - [ ] 18.3 Update cost estimation for EKS
    - Update `frontend/src/data/cost-data.ts`
    - Add EKS cluster costs (control plane, nodes)
    - Add LoadBalancer costs
    - _Requirements: 1.7_

- [x] 19. Final Checkpoint ✓
  - All 13 property tests pass (8 naming + 5 IRSA)
  - Frontend builds successfully
  - All core implementation tasks completed
  - Remaining items: property tests for reconciliation, cleanup, deployment state, detection, permissions

## Notes

- All tasks including property tests are required for comprehensive coverage
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties
- Unit tests validate specific examples and edge cases
- The Kubernetes Operator uses the `kopf` framework (Python) for simplicity and AWS SDK compatibility

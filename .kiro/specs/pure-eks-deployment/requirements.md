<!-- (renamed totogi-* -> nexus-* on 2026-06-13; original wording was design-snapshot) -->
# Requirements Document

## Introduction

This feature extends the Nexus AI Customer Toolkit to support Pure AWS EKS (Elastic Kubernetes Service) based deployment architecture using a Kubernetes Operator pattern. In this deployment model, a custom Kubernetes Operator is deployed to the EKS cluster, which then manages the provisioning of both application components (frontend/backend containers) and AWS data services (DynamoDB, S3, Glue Database).

The Operator-based approach provides:
- Kubernetes-native resource management via Custom Resource Definitions (CRDs)
- Declarative infrastructure provisioning through the Operator
- Self-healing and reconciliation capabilities
- Consistent deployment patterns across environments

The feature encompasses:
1. UI changes to enable EKS selection in the Architecture Selection wizard step
2. A new EKS Cluster Discovery screen to discover and select existing EKS clusters
3. Deployment of the Nexus AI Kubernetes Operator to the selected cluster
4. Operator-managed provisioning of data services and application deployment
5. Integration with existing wizard flow for progress tracking and state management

The Kubernetes Operator code will be developed in `C:\mycode\nexus\nexus-deployer\kube-operator`.

## Glossary

- **EKS_Cluster**: An Amazon Elastic Kubernetes Service cluster that provides managed Kubernetes control plane
- **Kubernetes_Operator**: A custom controller that extends Kubernetes to manage application-specific resources and AWS services
- **Nexus_Operator**: The custom Kubernetes Operator that provisions data services and deploys application components
- **Custom_Resource_Definition (CRD)**: A Kubernetes extension that defines custom resource types managed by the Operator
- **NexusCapability_CR**: A Custom Resource representing a Nexus AI capability deployment, including frontend, backend, and data services
- **EKS_Cluster_Selector**: The UI component that allows users to discover and select available EKS clusters in their AWS account
- **Operator_Deployment_Service**: The backend service responsible for deploying the Nexus AI Operator to EKS clusters
- **Container_Image**: A Docker container image stored in ECR (Elastic Container Registry) containing the frontend, backend, or operator application
- **IRSA**: IAM Roles for Service Accounts - AWS mechanism to grant Kubernetes pods (including the Operator) access to AWS services
- **Kubernetes_Namespace**: A logical partition within an EKS cluster to isolate deployed resources
- **Reconciliation_Loop**: The Operator's continuous process of comparing desired state (CR spec) with actual state and making corrections
- **Architecture_Config**: The wizard state object storing selected deployment architecture (frontend/backend service choices)
- **Data_Services**: AWS managed services (DynamoDB, S3, Glue Database) that store application data, provisioned by the Operator
- **Service_Account**: A Kubernetes identity used by the Operator to authenticate with AWS services via IRSA
- **SSM_Parameter_Store**: AWS Systems Manager Parameter Store used to store configuration values for the application
- **Secrets_Manager**: AWS Secrets Manager used to store sensitive configuration (credentials, API keys) for the application

## Requirements

### Requirement 1: EKS Architecture Selection in Wizard

**User Story:** As a deployment operator, I want to select EKS as my deployment target for both frontend and backend, so that I can deploy my application using Kubernetes orchestration with the Nexus AI Operator.

#### Acceptance Criteria

1. WHEN the user views the Backend_Layer options in Architecture_Selector, THE Architecture_Selector SHALL display EKS (Kubernetes) as an available and selectable Service_Option (not disabled/coming soon)
2. WHEN the user selects EKS for the Backend_Layer, THE Architecture_Selector SHALL visually highlight the EKS option and update the architecture diagram to show EKS
3. WHEN EKS is selected for Backend_Layer, THE Architecture_Selector SHALL display EKS-specific characteristics including: "Kubernetes native", "Operator managed", "Self-healing", "Declarative config"
4. THE Architecture_Selector SHALL display a new "Pure EKS" frontend option that deploys the frontend container to EKS instead of S3/CloudFront
5. WHEN the user selects "Pure EKS" for Frontend_Layer, THE Architecture_Selector SHALL enable EKS selection for Backend_Layer automatically (Pure EKS requires both layers on EKS)
6. WHEN "Pure EKS" architecture is selected, THE Architecture_Selector SHALL update the visual diagram to show both Frontend and Backend boxes connected to a single EKS cluster icon with an Operator icon
7. THE Architecture_Selector SHALL display cost tier indicator "$$" for EKS options to indicate higher infrastructure costs compared to serverless options

### Requirement 2: EKS Cluster Discovery and Selection

**User Story:** As a deployment operator, I want to see available EKS clusters in my AWS account and select one for deployment, so that I can deploy to my existing Kubernetes infrastructure.

#### Acceptance Criteria

1. WHEN the user selects EKS architecture and proceeds to the next step, THE Wizard SHALL display an EKS_Cluster_Selector screen
2. WHEN the EKS_Cluster_Selector screen loads, THE EKS_Cluster_Selector SHALL query the AWS account for available EKS clusters in the selected region
3. WHEN EKS clusters are found, THE EKS_Cluster_Selector SHALL display a list showing: cluster name, Kubernetes version, cluster status, node count, and whether Nexus_Operator is already installed
4. WHEN no EKS clusters are found in the region, THE EKS_Cluster_Selector SHALL display a message indicating no clusters are available and provide guidance on creating one
5. WHEN the user selects an EKS cluster, THE EKS_Cluster_Selector SHALL validate that the cluster is in "ACTIVE" status before allowing selection
6. IF the selected cluster is not in "ACTIVE" status, THEN THE EKS_Cluster_Selector SHALL display a warning and prevent selection
7. WHEN a valid cluster is selected, THE Wizard_Context SHALL store the selected cluster ARN, name, endpoint, and OIDC provider URL for use in deployment
8. THE EKS_Cluster_Selector SHALL display cluster health indicators showing node group status and any cluster issues

### Requirement 3: Nexus AI Operator Deployment

**User Story:** As a deployment operator, I want the Nexus AI Kubernetes Operator to be deployed to my EKS cluster, so that it can manage capability deployments and AWS resource provisioning.

#### Acceptance Criteria

1. WHEN an EKS cluster is selected and does not have Nexus_Operator installed, THE Operator_Deployment_Service SHALL deploy the Nexus_Operator to the cluster
2. THE Operator_Deployment_Service SHALL create a dedicated namespace "nexus-system" for the Operator deployment
3. THE Operator_Deployment_Service SHALL deploy the Operator container image from ECR to the nexus-system namespace
4. THE Operator_Deployment_Service SHALL create Custom Resource Definitions (CRDs) for NexusCapability resources
5. THE Operator_Deployment_Service SHALL create an IAM role for the Operator with permissions to provision DynamoDB, S3, Glue, and ECR resources
6. THE Operator_Deployment_Service SHALL configure IRSA for the Operator's ServiceAccount to assume the IAM role
7. WHEN the Operator is deployed, THE Operator_Deployment_Service SHALL verify the Operator pod is running and healthy before proceeding
8. IF the Operator deployment fails, THEN THE Operator_Deployment_Service SHALL display detailed error messages and rollback any partial deployment
9. WHEN the cluster already has Nexus_Operator installed, THE Operator_Deployment_Service SHALL verify the Operator version and offer upgrade if a newer version is available

### Requirement 4: Operator-Based Capability Deployment

**User Story:** As a deployment operator, I want to deploy capabilities through the Kubernetes Operator using Custom Resources, so that deployments are managed declaratively with self-healing capabilities.

#### Acceptance Criteria

1. WHEN deploying a capability to EKS, THE Operator_Deployment_Service SHALL create a NexusCapability Custom Resource in the target namespace
2. THE NexusCapability CR spec SHALL include: capability name, version, environment, frontend configuration, backend configuration, and data services configuration
3. WHEN the NexusCapability CR is created, THE Nexus_Operator SHALL reconcile the desired state by provisioning all required resources
4. THE Nexus_Operator SHALL provision data services (DynamoDB tables, S3 buckets, Glue databases) as specified in the NexusCapability CR
5. THE Nexus_Operator SHALL deploy frontend and backend containers as Kubernetes Deployments with appropriate Services
6. THE Nexus_Operator SHALL provision SSM parameters following the existing naming convention: `/{capability-name}/{environment}/{category}/{resource}` with categories including: aws, server, cognito, wxcc, s3, dynamodb, glue, cloudwatch
7. THE Nexus_Operator SHALL provision Secrets Manager secrets following the existing naming convention: `{capability-name}/{environment}/{secret-type}` for secrets including: api-keys, wxcc, openai, license, anthropic, github
8. THE Nexus_Operator SHALL configure container environment variables to enable the backend service to read from SSM Parameter Store and Secrets Manager at runtime (using existing config loading patterns)
9. THE Nexus_Operator SHALL update the NexusCapability CR status with deployment progress, resource ARNs, and endpoint URLs
10. WHEN the NexusCapability CR is modified, THE Nexus_Operator SHALL reconcile changes and perform rolling updates
11. WHEN the NexusCapability CR is deleted, THE Nexus_Operator SHALL clean up all managed resources (Kubernetes resources, SSM parameters, Secrets Manager secrets, and optionally AWS data services)

### Requirement 5: Operator IAM and IRSA Configuration

**User Story:** As a deployment operator, I want the Operator and deployed applications to securely access AWS services, so that data services can be provisioned and configuration can be managed without embedding credentials.

#### Acceptance Criteria

1. THE Nexus_Operator SHALL use IRSA to obtain AWS credentials for provisioning data services and managing configuration
2. THE Operator's IAM role SHALL have permissions to: create/delete DynamoDB tables, create/delete S3 buckets, create/delete Glue databases/tables, manage ECR repositories, create/manage SSM parameters, create/manage Secrets Manager secrets, create IAM roles for application workloads
3. WHEN deploying application workloads, THE Nexus_Operator SHALL create a dedicated IAM role for each capability deployment
4. THE application IAM role SHALL have least-privilege permissions to: access only the data services created for that capability, read SSM parameters for the capability/environment, read Secrets Manager secrets for the capability/environment
5. THE Nexus_Operator SHALL create a Kubernetes ServiceAccount for each capability deployment annotated with the application IAM role ARN
6. THE Nexus_Operator SHALL verify the EKS cluster has an OIDC provider configured before attempting IRSA setup
7. IF the EKS cluster does not have an OIDC provider, THEN THE Operator_Deployment_Service SHALL display an error with instructions to enable OIDC

### Requirement 6: Container Image Management

**User Story:** As a deployment operator, I want the system to manage container images for the Operator and application deployments, so that all components are properly containerized and available.

#### Acceptance Criteria

1. THE Operator_Deployment_Service SHALL verify that the Nexus_Operator container image exists in ECR before deployment
2. WHEN deploying a capability, THE Nexus_Operator SHALL verify that frontend and backend container images exist in ECR
3. IF container images do not exist in ECR, THEN THE Nexus_Operator SHALL report an error in the NexusCapability CR status
4. THE Nexus_Operator SHALL tag container images with the capability version and environment (e.g., "call-processing:1.0.0-prod")
5. THE Nexus_Operator SHALL support multi-architecture images (amd64, arm64) for EKS node compatibility
6. THE NexusCapability CR spec SHALL allow specifying custom image repositories and tags for frontend and backend

### Requirement 7: Namespace Configuration

**User Story:** As a deployment operator, I want to specify the Kubernetes namespace for my capability deployment, so that I can organize and isolate my application within the cluster.

#### Acceptance Criteria

1. WHEN configuring EKS deployment, THE Unified_Environment_Config screen SHALL display a namespace configuration section
2. THE Unified_Environment_Config screen SHALL provide an option to use an existing namespace or create a new one
3. WHEN "create new namespace" is selected, THE Nexus_Operator SHALL create the namespace before deploying resources
4. THE namespace name SHALL follow Kubernetes naming rules (lowercase, alphanumeric, hyphens allowed, max 63 characters)
5. IF an invalid namespace name is entered, THEN THE Unified_Environment_Config screen SHALL display a validation error
6. THE namespace name SHALL default to "{capability-name}-{environment}" format
7. THE Nexus_Operator SHALL apply standard labels to the namespace for identification and management

### Requirement 8: EKS Deployment Progress and Logging

**User Story:** As a deployment operator, I want to see real-time progress of my EKS deployment, so that I can monitor the deployment status and troubleshoot issues.

#### Acceptance Criteria

1. WHEN EKS deployment starts, THE Deployment_Execution screen SHALL display EKS-specific deployment stages
2. THE Deployment_Execution screen SHALL show progress for: "Deploying Nexus AI Operator", "Creating NexusCapability CR", "Provisioning data services", "Deploying backend pods", "Deploying frontend pods", "Configuring services", "Verifying health"
3. WHEN a deployment stage completes, THE Deployment_Execution screen SHALL update the progress indicator and display success/failure status
4. THE Deployment_Execution screen SHALL display real-time logs from the Nexus_Operator including reconciliation events
5. IF a Kubernetes resource fails to deploy, THEN THE Deployment_Execution screen SHALL display the Kubernetes error message and pod events from the Operator
6. WHEN deployment completes successfully, THE Deployment_Execution screen SHALL display the frontend URL and backend API endpoint from the NexusCapability CR status
7. THE Deployment_Execution screen SHALL provide a "View in AWS Console" link to the EKS cluster workloads page

### Requirement 9: EKS Deployment State Management

**User Story:** As a deployment operator, I want the system to track my EKS deployments, so that I can manage updates and deletions of my Kubernetes-based applications.

#### Acceptance Criteria

1. WHEN an EKS deployment completes, THE Deployment_State_Service SHALL store the deployment record including: cluster ARN, namespace, NexusCapability CR name, and data service ARNs
2. WHEN detecting existing deployments, THE Stack_Detection_Service SHALL check for existing NexusCapability CRs in the specified namespace
3. IF existing EKS deployment is detected, THEN THE Strategy_Selection screen SHALL offer "Update Existing" or "Clean Deploy" options
4. WHEN updating an existing EKS deployment, THE Nexus_Operator SHALL perform rolling updates by modifying the NexusCapability CR
5. WHEN deleting an EKS deployment, THE Nexus_Operator SHALL remove all Kubernetes resources and optionally delete AWS data services based on deletion policy
6. THE Installation_History SHALL record EKS deployments with Operator-specific metadata (CR status, reconciliation count, resource inventory)

### Requirement 10: EKS Prerequisites Verification

**User Story:** As a deployment operator, I want the system to verify EKS prerequisites before deployment, so that I can ensure my cluster is properly configured.

#### Acceptance Criteria

1. WHEN EKS architecture is selected, THE Permission_Verification step SHALL check for EKS-specific IAM permissions (eks:DescribeCluster, eks:ListClusters, eks:AccessKubernetesApi)
2. THE Permission_Verification step SHALL verify the user has permissions to create IAM roles for IRSA (Operator and application roles)
3. THE Permission_Verification step SHALL verify the user has permissions to create/manage ECR repositories
4. WHEN an EKS cluster is selected, THE EKS_Cluster_Selector SHALL verify cluster prerequisites: OIDC provider enabled, sufficient node capacity, kubectl API access
5. IF prerequisites are not met, THEN THE Wizard SHALL display specific remediation steps for each missing prerequisite
6. THE Permission_Verification step SHALL verify the user can create CRDs and deploy to the nexus-system namespace

### Requirement 11: EKS-Specific Configuration Options

**User Story:** As a deployment operator, I want to configure EKS-specific deployment options, so that I can customize how my application runs in Kubernetes.

#### Acceptance Criteria

1. WHEN EKS architecture is selected, THE Unified_Environment_Config screen SHALL display EKS-specific configuration options
2. THE Unified_Environment_Config screen SHALL allow configuration of replica count for frontend and backend deployments
3. THE Unified_Environment_Config screen SHALL allow configuration of resource requests/limits (CPU, memory) for containers
4. THE Unified_Environment_Config screen SHALL allow selection of Kubernetes ingress class if multiple ingress controllers are available
5. THE Unified_Environment_Config screen SHALL allow configuration of pod disruption budgets for high availability
6. THE Unified_Environment_Config screen SHALL allow enabling/disabling of Horizontal Pod Autoscaler with min/max replica settings
7. WHEN custom domain is configured, THE Unified_Environment_Config screen SHALL allow configuration of TLS certificate (ACM or cluster cert-manager)

### Requirement 12: Kubernetes Operator Implementation

**User Story:** As a platform developer, I want a well-structured Kubernetes Operator codebase, so that the Operator can be maintained and extended.

#### Acceptance Criteria

1. THE Nexus_Operator code SHALL be located in the `kube-operator` directory within the nexus-deployer repository
2. THE Nexus_Operator SHALL be implemented using a standard Kubernetes Operator framework (Operator SDK, Kubebuilder, or kopf for Python)
3. THE Nexus_Operator SHALL define a NexusCapability CRD with spec fields for: capability metadata, frontend config, backend config, data services config, and deployment options
4. THE Nexus_Operator SHALL implement a reconciliation loop that provisions AWS resources using AWS SDK
5. THE Nexus_Operator SHALL update the NexusCapability CR status with: deployment phase, resource ARNs, endpoint URLs, and error messages
6. THE Nexus_Operator SHALL implement finalizers to handle resource cleanup when CRs are deleted
7. THE Nexus_Operator SHALL emit Kubernetes events for significant state changes (deployment started, resource created, error occurred)
8. THE Nexus_Operator SHALL include health check endpoints for liveness and readiness probes
9. THE Nexus_Operator container image SHALL be built and published to ECR as part of the release process


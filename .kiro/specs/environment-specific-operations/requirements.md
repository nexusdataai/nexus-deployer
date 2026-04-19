# Requirements Document

## Introduction

This feature addresses the need for environment-specific update and delete operations in the Capability Selection screen. Currently, when a capability has multiple deployments (e.g., PROD and DEV), the Update and Delete buttons automatically target the first deployment without allowing users to select which specific environment they want to operate on. This creates a risk of unintended operations on the wrong environment.

## Glossary

- **Capability_Selection_Screen**: The main UI component that displays installed and available capabilities
- **Installed_Capability_Card**: A UI card component showing a deployed capability with its active deployments
- **Environment_Selector**: A UI component that allows users to choose a specific deployment environment
- **Deployment_State**: The stored state of a capability deployment including environment, region, and timestamp
- **Operation_Type**: Either "update" or "delete" action to be performed on a deployment

## Requirements

### Requirement 1: Environment Selection for Update Operations

**User Story:** As a deployment administrator, I want to select which specific environment to update when a capability has multiple deployments, so that I can safely update only the intended environment without affecting others.

#### Acceptance Criteria

1. WHEN a user clicks the Update button on an installed capability with multiple deployments, THE Environment_Selector SHALL display a modal or dropdown showing all available deployment environments
2. WHEN the Environment_Selector displays deployment options, THE System SHALL show the environment name (e.g., PROD, DEV), region, and last deployment timestamp for each option
3. WHEN a user selects a specific environment from the Environment_Selector, THE System SHALL proceed to the AWS Configuration step with that environment and region pre-populated
4. WHEN a user clicks Update on a capability with only one deployment, THE System SHALL skip the environment selection and proceed directly with that deployment's environment and region
5. WHEN the Environment_Selector is displayed, THE System SHALL visually distinguish between production and non-production environments

### Requirement 2: Environment Selection for Delete Operations

**User Story:** As a deployment administrator, I want to select which specific environment to delete when a capability has multiple deployments, so that I can safely remove only the intended environment without accidentally deleting others.

#### Acceptance Criteria

1. WHEN a user clicks the Delete button on an installed capability with multiple deployments, THE Environment_Selector SHALL display a modal showing all available deployment environments with clear delete warnings
2. WHEN displaying delete options, THE System SHALL show a warning indicator for production environments to prevent accidental deletion
3. WHEN a user selects a specific environment for deletion, THE System SHALL proceed to the AWS Configuration step with delete mode enabled and the selected environment pre-populated
4. WHEN a user clicks Delete on a capability with only one deployment, THE System SHALL skip the environment selection and proceed directly with that deployment's environment and region
5. IF a user attempts to delete a production environment, THEN THE System SHALL require explicit confirmation before proceeding

### Requirement 3: Environment Selector UI Component

**User Story:** As a user, I want a clear and intuitive interface for selecting deployment environments, so that I can quickly identify and choose the correct environment for my operation.

#### Acceptance Criteria

1. THE Environment_Selector SHALL display as a modal dialog centered on the screen
2. WHEN the modal is displayed, THE System SHALL show the capability name and operation type (Update/Delete) in the header
3. THE Environment_Selector SHALL display each deployment option as a selectable card with environment name, region, and deployment date
4. WHEN a user clicks outside the modal or presses Escape, THE System SHALL close the modal without performing any action
5. THE Environment_Selector SHALL include a Cancel button to dismiss the modal
6. WHEN displaying environments, THE System SHALL sort production environments first, followed by other environments alphabetically

### Requirement 4: Visual Feedback and Safety

**User Story:** As a deployment administrator, I want clear visual feedback about which environment I'm operating on, so that I can avoid mistakes when managing multiple deployments.

#### Acceptance Criteria

1. WHEN an environment is selected in the Environment_Selector, THE System SHALL highlight the selected option with a distinct visual style
2. THE Environment_Selector SHALL use color coding to differentiate environment types (e.g., red border for PROD, blue for DEV)
3. WHEN the Delete operation is selected, THE Environment_Selector SHALL display the modal with a warning color scheme (e.g., red accents)
4. WHEN the Update operation is selected, THE Environment_Selector SHALL display the modal with a neutral or positive color scheme (e.g., green accents)

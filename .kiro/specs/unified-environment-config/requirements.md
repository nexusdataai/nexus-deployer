# Requirements Document

## Introduction

This feature combines the Environment Selection (Step 3) and Infrastructure Configuration (Step 4) wizard screens into a single unified screen. The new screen displays environment options (Prod/Stage/Test/Dev) as selectable boxes at the top, with Production selected by default. Below the environment selector, configuration tabs (Domain & CDN, Compute & Scaling, Network & Storage, Monitoring, Tags) display environment-specific values that dynamically update based on the selected environment. Users can override certain configuration values directly in the UI.

## Glossary

- **Unified_Config_Screen**: The combined wizard step that merges environment selection and infrastructure configuration into a single view
- **Environment_Selector**: A horizontal container displaying environment options (Dev, Test, Stage, Prod) as clickable boxes
- **Environment_Box**: An individual selectable box representing one deployment environment with its name, badge, and selection state
- **Configuration_Panel**: The tabbed section below the environment selector showing infrastructure settings
- **Overridable_Field**: A configuration field that users can modify from its default/preset value
- **Read_Only_Field**: A configuration field that displays a value but cannot be modified by the user
- **Environment_Preset**: The default configuration values associated with each environment type

## Requirements

### Requirement 1: Unified Screen Layout

**User Story:** As a deployment operator, I want to see environment selection and infrastructure configuration on a single screen, so that I can quickly select an environment and review/modify its settings without navigating between steps.

#### Acceptance Criteria

1. THE Unified_Config_Screen SHALL display the Environment_Selector at the top of the screen
2. THE Unified_Config_Screen SHALL display the Configuration_Panel below the Environment_Selector
3. THE Unified_Config_Screen SHALL display the AWS Region selector between the Environment_Selector and Configuration_Panel
4. WHEN the screen loads, THE Unified_Config_Screen SHALL select the Production environment by default
5. THE Unified_Config_Screen SHALL maintain the existing wizard navigation (Back/Continue buttons)

### Requirement 2: Environment Selector Display

**User Story:** As a deployment operator, I want to see all available environments as compact selectable boxes, so that I can quickly switch between environments and compare their configurations.

#### Acceptance Criteria

1. THE Environment_Selector SHALL display four Environment_Box components in a horizontal row: Dev, Test, Stage, Prod
2. WHEN an Environment_Box is selected, THE Environment_Selector SHALL visually highlight the selected box with a distinct border and background
3. THE Environment_Box SHALL display the environment name (e.g., "Development", "Production")
4. THE Environment_Box SHALL display a short identifier badge (e.g., "dev", "prod")
5. THE Environment_Box SHALL display the estimated monthly cost range
6. WHEN the user hovers over an Environment_Box, THE Environment_Selector SHALL display a tooltip with environment features

### Requirement 3: Dynamic Configuration Loading

**User Story:** As a deployment operator, I want the configuration panel to automatically update when I select a different environment, so that I can see the appropriate settings for each environment.

#### Acceptance Criteria

1. WHEN the user selects a different environment, THE Configuration_Panel SHALL load and display the configuration values for that environment
2. WHILE loading configuration data, THE Configuration_Panel SHALL display a loading indicator
3. IF the configuration fails to load, THEN THE Configuration_Panel SHALL display an error message with retry option
4. WHEN switching environments, THE Configuration_Panel SHALL preserve the currently active tab selection
5. THE Configuration_Panel SHALL display environment-specific preset values as the initial configuration

### Requirement 4: Configuration Override Capability

**User Story:** As a deployment operator, I want to override certain configuration values for my specific deployment needs, so that I can customize the infrastructure while using environment presets as a baseline.

#### Acceptance Criteria

1. THE Configuration_Panel SHALL mark Overridable_Field inputs as editable with standard input styling
2. THE Configuration_Panel SHALL mark Read_Only_Field inputs as disabled with muted styling
3. WHEN the user modifies an Overridable_Field, THE Configuration_Panel SHALL track the change as unsaved
4. WHEN the user has unsaved changes, THE Configuration_Panel SHALL display a warning indicator
5. THE Configuration_Panel SHALL provide a "Reset to Defaults" button to restore environment preset values
6. WHEN the user clicks "Save Configuration", THE Configuration_Panel SHALL persist the overridden values

### Requirement 5: Overridable Configuration Fields

**User Story:** As a deployment operator, I want to customize specific infrastructure settings while keeping others locked to environment presets, so that I can balance flexibility with standardization.

#### Acceptance Criteria

1. THE Configuration_Panel SHALL allow override of Domain Configuration fields (base domain, hosted zone ID, subdomains)
2. THE Configuration_Panel SHALL allow override of CloudFront CDN settings (enabled, WAF, price class, cache TTL, rate limit)
3. THE Configuration_Panel SHALL allow override of ECS task sizing (CPU, memory, desired count)
4. THE Configuration_Panel SHALL allow override of Auto Scaling settings (enabled, min/max capacity, target CPU/memory)
5. THE Configuration_Panel SHALL allow override of Monitoring settings (log retention, container insights)
6. THE Configuration_Panel SHALL allow override of custom Tags
7. THE Configuration_Panel SHALL display VPC and Storage settings as Read_Only_Field based on environment preset

### Requirement 6: Environment Cost Visibility

**User Story:** As a deployment operator, I want to see estimated costs for each environment, so that I can make informed decisions about which environment to deploy to.

#### Acceptance Criteria

1. THE Environment_Box SHALL display the estimated monthly cost range prominently
2. WHEN the user selects an environment, THE Configuration_Panel SHALL display a cost summary section
3. THE cost summary SHALL update dynamically based on configuration overrides where applicable

### Requirement 7: Wizard Step Consolidation

**User Story:** As a system administrator, I want the wizard to skip the separate environment selection step, so that the deployment flow is more streamlined.

#### Acceptance Criteria

1. WHEN navigating from Capability Selection, THE Wizard SHALL proceed directly to the Unified_Config_Screen
2. THE Unified_Config_Screen SHALL be labeled as a single step in the wizard progress indicator
3. WHEN the user clicks Continue, THE Wizard SHALL proceed to the AWS Configuration step (or next appropriate step)
4. WHEN the user clicks Back, THE Wizard SHALL return to the Capability Selection step

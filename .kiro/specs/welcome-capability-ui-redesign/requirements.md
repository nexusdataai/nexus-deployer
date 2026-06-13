<!-- (renamed totogi-* -> nexus-* on 2026-06-13; original wording was design-snapshot) -->
# Requirements Document

## Introduction

This feature redesigns the Welcome Screen and Capability Selection screens in the Nexus AI Capability Installer. The Welcome Screen will be simplified to show a clean graphic/hero section instead of verbose text instructions. The Capability Selection screen will be reorganized to show Installed Capabilities and Available Capabilities in separate sections with appropriate actions (Update/Delete for installed, Install for available).

## Glossary

- **Welcome_Screen**: The first screen users see when opening the application
- **Capability_Selection_Screen**: The second screen where users choose which capability to work with
- **Installed_Capability**: A capability that has been deployed to at least one environment
- **Available_Capability**: A capability that exists in the catalog but has not been deployed
- **Deployment_State**: Record of a capability deployment including environment, region, and timestamp
- **Telco_Business_Capability**: Modular business functionality specific to telecommunications industry that can be deployed to customer infrastructure
- **Deployment_Platform**: Target infrastructure where capabilities can be deployed (AWS, Azure, GCP, Kubernetes, On-Premise)
- **Platform_Support_Indicator**: Visual checkmark showing whether a deployment platform is currently supported

## Requirements

### Requirement 1

**User Story:** As a user, I want to see a clean, visually appealing welcome screen, so that I can quickly understand the application purpose and start using it.

#### Acceptance Criteria

1. WHEN a user opens the application THEN the Welcome_Screen SHALL display a prominent hero graphic/illustration representing Telco Business Capability deployment
2. WHEN the Welcome_Screen loads THEN the system SHALL display the application title "Nexus AI Capability Installer" prominently
3. WHEN the Welcome_Screen loads THEN the system SHALL display a single "Get Started" button to proceed
4. WHEN the Welcome_Screen loads THEN the system SHALL NOT display the detailed workflow steps or feature lists
5. WHEN the Welcome_Screen loads THEN the system SHALL display the tagline "Deploy Business Capability in your Environment"

### Requirement 6

**User Story:** As a user, I want to see which deployment platforms are supported, so that I can understand where I can deploy capabilities and what platforms are coming soon.

#### Acceptance Criteria

1. WHEN the Welcome_Screen loads THEN the system SHALL display deployment platform icons for AWS, Azure, GCP, Kubernetes, and On-Premise
2. WHEN displaying the AWS platform icon THEN the system SHALL show a checkmark/tick indicator to signify current support
3. WHEN displaying Azure, GCP, Kubernetes, and On-Premise platform icons THEN the system SHALL NOT show a checkmark indicator to signify future support
4. WHEN displaying platform icons THEN the system SHALL arrange the icons in a horizontal row below the hero graphic
5. WHEN a user hovers over a platform icon THEN the system SHALL display a tooltip indicating "Supported" for AWS and "Coming Soon" for other platforms

### Requirement 2

**User Story:** As a user, I want to see my installed capabilities separately from available ones, so that I can easily manage existing deployments or install new capabilities.

#### Acceptance Criteria

1. WHEN the Capability_Selection_Screen loads THEN the system SHALL display two distinct sections: "Installed Capabilities" and "Available Capabilities"
2. WHEN a capability has at least one deployment THEN the system SHALL display that capability in the "Installed Capabilities" section
3. WHEN the "Installed Capabilities" section is empty THEN the system SHALL display a message indicating no capabilities are installed
4. WHEN the Capability_Selection_Screen loads THEN the system SHALL display ALL capabilities in the "Available Capabilities" section regardless of deployment status
5. WHEN a capability is displayed in "Available Capabilities" THEN the system SHALL allow installation to any environment including environments where the capability is not yet deployed

### Requirement 3

**User Story:** As a user, I want appropriate action buttons for installed capabilities, so that I can update or delete existing deployments.

#### Acceptance Criteria

1. WHEN viewing an Installed_Capability THEN the system SHALL display "Update" and "Delete" action buttons
2. WHEN a user clicks "Update" on an Installed_Capability THEN the system SHALL proceed directly to the AWS credentials configuration screen with the capability pre-selected
3. WHEN a user clicks "Delete" on an Installed_Capability THEN the system SHALL proceed directly to the delete/cleanup screen with the capability pre-selected
4. WHEN viewing an Installed_Capability THEN the system SHALL display the deployment details including environment, region, and last deployment date

### Requirement 4

**User Story:** As a user, I want to install new capabilities easily, so that I can deploy new business capabilities to my AWS environment.

#### Acceptance Criteria

1. WHEN viewing an Available_Capability THEN the system SHALL display only an "Install" action button
2. WHEN a user clicks "Install" on an Available_Capability THEN the system SHALL proceed to the environment selection step with the capability pre-selected
3. WHEN viewing an Available_Capability THEN the system SHALL display capability details including name, description, version, and estimated deployment time

### Requirement 5

**User Story:** As a user, I want visual distinction between installed and available capabilities, so that I can quickly identify the status of each capability.

#### Acceptance Criteria

1. WHEN displaying the "Installed Capabilities" section THEN the system SHALL use a distinct visual style with a green accent color
2. WHEN displaying the "Available Capabilities" section THEN the system SHALL use a distinct visual style with a blue accent color
3. WHEN a capability card is displayed THEN the system SHALL show the capability icon or category badge

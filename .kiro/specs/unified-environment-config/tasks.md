# Implementation Plan: Unified Environment Configuration

## Overview

This implementation combines the Environment Selection and Infrastructure Configuration wizard steps into a single unified screen. The approach is incremental: first update types and context, then create the new component, then integrate with the wizard flow.

## Tasks

- [x] 1. Update wizard types and context
  - [x] 1.1 Update WizardStep enum in types/wizard.ts
    - Remove `ENVIRONMENT_SELECTION` step
    - Rename `INFRASTRUCTURE_CONFIG` to `UNIFIED_ENVIRONMENT_CONFIG`
    - _Requirements: 7.1, 7.2_

  - [x] 1.2 Update WizardContext step navigation
    - Update `stepOrder` array in goToNextStep and goToPreviousStep
    - Ensure navigation flows correctly from CAPABILITY_SELECTION to UNIFIED_ENVIRONMENT_CONFIG to AWS_CONFIGURATION
    - _Requirements: 7.3, 7.4_

- [x] 2. Create EnvironmentSelector component
  - [x] 2.1 Create EnvironmentBox sub-component
    - Create `src/components/unified-config/EnvironmentBox.tsx`
    - Implement compact box design with name, badge, cost display
    - Add selection styling (ring-2, ring-blue-600 for selected)
    - Add hover tooltip for features
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x] 2.2 Write property test for EnvironmentBox display
    - **Property 1: Environment Box Display Completeness**
    - **Validates: Requirements 2.3, 2.4, 2.5**

  - [x] 2.3 Create EnvironmentSelector component
    - Create `src/components/unified-config/EnvironmentSelector.tsx`
    - Render 4 EnvironmentBox components in horizontal row
    - Handle selection state and callbacks
    - _Requirements: 2.1, 2.2_

  - [x] 2.4 Write property test for selection visual feedback
    - **Property 2: Environment Selection Visual Feedback**
    - **Validates: Requirements 2.2**

- [x] 3. Create field permissions system
  - [x] 3.1 Define field permissions configuration
    - Create `src/components/unified-config/fieldPermissions.ts`
    - Define OVERRIDABLE_FIELDS and READ_ONLY_FIELDS arrays
    - Create helper function to check field editability
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

  - [x] 3.2 Write property test for field editability
    - **Property 5: Field Editability Consistency**
    - **Validates: Requirements 4.1, 4.2, 5.1-5.7**

- [x] 4. Create ConfigurationPanel component
  - [x] 4.1 Create ConfigurationPanel wrapper component
    - Create `src/components/unified-config/ConfigurationPanel.tsx`
    - Implement tab navigation (domain, compute, network, monitoring, tags)
    - Use field permissions to enable/disable inputs
    - _Requirements: 4.1, 4.2_

  - [x] 4.2 Implement DomainCDNTab content
    - Extract domain/CDN form fields from existing InfrastructureConfiguration
    - Apply field permissions for editability
    - _Requirements: 5.1, 5.2_

  - [x] 4.3 Implement ComputeScalingTab content
    - Extract ECS and autoscaling form fields
    - Apply field permissions for editability
    - _Requirements: 5.3, 5.4_

  - [x] 4.4 Implement NetworkStorageTab content
    - Extract VPC and storage form fields
    - Mark VPC and storage fields as read-only
    - _Requirements: 5.7_

  - [x] 4.5 Implement MonitoringTab content
    - Extract monitoring form fields
    - Apply field permissions for editability
    - _Requirements: 5.5_

  - [x] 4.6 Implement TagsTab content
    - Extract tags form fields
    - Apply field permissions for editability
    - _Requirements: 5.6_

- [x] 5. Create UnifiedEnvironmentConfig main component
  - [x] 5.1 Create main component structure
    - Create `src/components/UnifiedEnvironmentConfig.tsx`
    - Implement component state (selectedEnvironment, config, loading, etc.)
    - Set Production as default selected environment
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 5.2 Implement configuration loading logic
    - Load config when environment changes
    - Show loading indicator during load
    - Handle load errors with retry option
    - _Requirements: 3.1, 3.2, 3.3_

  - [ ]* 5.3 Write property test for environment configuration loading
    - **Property 3: Environment Configuration Loading**
    - **Validates: Requirements 3.1, 3.5**

  - [x] 5.4 Implement change tracking
    - Track modifications to overridable fields
    - Display unsaved changes warning
    - Implement Reset to Defaults functionality
    - _Requirements: 4.3, 4.4, 4.5_

  - [ ]* 5.5 Write property test for change tracking
    - **Property 6: Change Tracking Accuracy**
    - **Validates: Requirements 4.3**

  - [x] 5.6 Implement tab preservation on environment switch
    - Preserve activeTab state when switching environments
    - _Requirements: 3.4_

  - [ ]* 5.7 Write property test for tab preservation
    - **Property 4: Tab Preservation on Environment Switch**
    - **Validates: Requirements 3.4**

  - [x] 5.8 Implement save configuration functionality
    - Call configApi.saveConfig on save
    - Handle save errors
    - Clear hasChanges on successful save
    - _Requirements: 4.6_

  - [x] 5.9 Implement navigation buttons
    - Back button navigates to CAPABILITY_SELECTION
    - Continue button navigates to AWS_CONFIGURATION
    - Store environment and config in wizard context before navigation
    - _Requirements: 1.5, 7.3, 7.4_

- [x] 6. Integrate with WizardShell
  - [x] 6.1 Update WizardShell component
    - Import UnifiedEnvironmentConfig
    - Update switch case to render UnifiedEnvironmentConfig for UNIFIED_ENVIRONMENT_CONFIG step
    - Remove case for ENVIRONMENT_SELECTION
    - _Requirements: 7.1, 7.2_

  - [x] 6.2 Update wizard progress indicator
    - Update step labels to reflect combined step
    - Adjust step count (10 steps instead of 11)
    - _Requirements: 7.2_

- [x] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Cleanup and finalization
  - [x] 8.1 Remove deprecated EnvironmentSelection component
    - Delete `src/components/EnvironmentSelection.tsx`
    - Remove any imports referencing the old component
    - _Requirements: 7.1_

  - [x] 8.2 Update InfrastructureConfiguration component (optional)
    - Either delete or mark as deprecated
    - The new UnifiedEnvironmentConfig replaces its functionality
    - _Requirements: 7.1_

  - [x] 8.3 Write integration tests for wizard flow
    - Test navigation from Capability Selection to Unified Config
    - Test navigation from Unified Config to AWS Configuration
    - Test Back navigation
    - _Requirements: 7.1, 7.3, 7.4_

- [x] 9. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- All tasks including property tests are required for comprehensive validation
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties
- Unit tests validate specific examples and edge cases
- The existing configApi is reused for loading/saving configurations
- Environment presets are defined in the new component, not fetched from backend

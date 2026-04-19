# Implementation Plan: AWS Architecture Selection

## Overview

This implementation plan creates the AWS Architecture Selection feature for the starhub-deployer wizard. The feature allows users to visually select deployment targets (S3/CloudFront for frontend, ECS for backend) through a graphical architecture diagram interface.

## Tasks

- [x] 1. Create architecture types and constants
  - [x] 1.1 Create `types/architecture.ts` with FrontendService, BackendService enums and ArchitectureConfig interface
    - Define FrontendService enum (S3_CLOUDFRONT, AMPLIFY)
    - Define BackendService enum (ECS, EKS, EC2)
    - Define ServiceAvailability, CostTier types
    - Define ServiceOptionMeta interface
    - Define ArchitectureConfig interface
    - Create FRONTEND_SERVICE_OPTIONS and BACKEND_SERVICE_OPTIONS constants with metadata
    - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 6.5_

- [x] 2. Update wizard state management
  - [x] 2.1 Update `types/wizard.ts` to add ARCHITECTURE_SELECTION step and architectureConfig to WizardState
    - Add ARCHITECTURE_SELECTION to WizardStep enum (after CAPABILITY_SELECTION)
    - Add architectureConfig: ArchitectureConfig | null to WizardState interface
    - Add setArchitectureConfig method to WizardContextType interface
    - _Requirements: 4.1, 5.1_
  - [x] 2.2 Update `context/WizardContext.tsx` to implement architectureConfig state management
    - Add architectureConfig to initialState (null)
    - Implement setArchitectureConfig function
    - Update stepOrder arrays in goToNextStep and goToPreviousStep
    - Export setArchitectureConfig in context value
    - _Requirements: 4.1, 4.2, 4.4_
  - [ ]* 2.3 Write property test for state restoration round-trip
    - **Property 3: State Restoration Round-Trip**
    - **Validates: Requirements 4.2**

- [x] 3. Create AWS service icons
  - [x] 3.1 Create `utils/awsIcons.tsx` with SVG icon components
    - Create CloudFrontIcon component
    - Create AmplifyIcon component
    - Create ECSIcon component
    - Create EKSIcon component
    - Create EC2Icon component
    - Use consistent sizing and className props
    - _Requirements: 6.1_

- [x] 4. Create ServiceOptionCard component
  - [x] 4.1 Create `components/ServiceOptionCard.tsx`
    - Accept ServiceOptionMeta, isSelected, and onSelect props
    - Render service icon, name, description
    - Render cost tier indicator ($, $$, $$$)
    - Render "Coming Soon" badge for disabled options
    - Apply selection highlight styling when selected
    - Disable click handler for coming_soon availability
    - Apply reduced opacity for disabled options
    - _Requirements: 2.4, 2.5, 3.5, 3.6, 6.1, 6.2, 6.3, 6.4, 6.5_
  - [ ]* 4.2 Write property test for disabled service non-selectability
    - **Property 5: Disabled Service Non-Selectability**
    - **Validates: Requirements 2.3, 3.3, 3.4**

- [x] 5. Create ArchitectureSelection component
  - [x] 5.1 Create `components/ArchitectureSelection.tsx` with architecture diagram and layer selectors
    - Import useWizard hook and architecture types
    - Initialize local state with defaults (S3_CLOUDFRONT, ECS) or from context
    - Render header with title and description
    - Render architecture diagram with Frontend and Backend layers
    - Render connection arrows between layers
    - Render Frontend layer with ServiceOptionCard for each frontend option
    - Render Backend layer with ServiceOptionCard for each backend option
    - Handle selection changes and update context
    - Implement validation (both layers must have valid selections)
    - Render Back and Continue buttons
    - Disable Continue when validation fails
    - Navigate to previous/next step on button clicks
    - Apply responsive layout (horizontal on desktop, stacked on mobile)
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 3.7, 5.2, 5.3, 5.5, 7.1, 7.2_
  - [ ]* 5.2 Write property test for default selection invariant
    - **Property 1: Default Selection Invariant**
    - **Validates: Requirements 2.6, 3.7**
  - [ ]* 5.3 Write property test for selection state consistency
    - **Property 2: Selection State Consistency**
    - **Validates: Requirements 4.1**
  - [ ]* 5.4 Write property test for validation gate
    - **Property 4: Validation Gate Property**
    - **Validates: Requirements 5.2, 5.5**

- [x] 6. Integrate into wizard flow
  - [x] 6.1 Update `components/WizardShell.tsx` to include ArchitectureSelection step
    - Import ArchitectureSelection component
    - Add case for WizardStep.ARCHITECTURE_SELECTION in renderStep switch
    - Update getStepNumber and getTotalSteps to account for new step
    - _Requirements: 5.1, 5.4_
  - [x] 6.2 Update `components/CapabilitySelection.tsx` to navigate to architecture selection
    - Update handleInstall to navigate to ARCHITECTURE_SELECTION instead of UNIFIED_ENVIRONMENT_CONFIG
    - _Requirements: 5.1_

- [x] 7. Checkpoint - Ensure all tests pass
  - All new files pass TypeScript diagnostics. Pre-existing errors in unrelated files (PermissionVerification.test.ts, policy-generator.ts) are not related to this feature.

- [x] 8. Unit tests for components
  - [x]* 8.1 Write unit tests for ArchitectureSelection component
    - Test initial render with default selections
    - Test service option rendering
    - Test selection changes
    - Test navigation buttons
    - Test responsive layout classes
    - _Requirements: 1.1, 2.1, 3.1, 5.2, 5.3_
  - [x]* 8.2 Write unit tests for ServiceOptionCard component
    - Test rendering with different service options
    - Test selected state styling
    - Test disabled state styling
    - Test click handler behavior
    - _Requirements: 6.1, 6.2, 6.4_

- [x] 9. Final checkpoint - Ensure all tests pass
  - All 47 tests pass (20 ServiceOptionCard tests + 27 ArchitectureSelection tests)

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties
- Unit tests validate specific examples and edge cases
- The implementation uses TypeScript, React, and Tailwind CSS consistent with existing codebase

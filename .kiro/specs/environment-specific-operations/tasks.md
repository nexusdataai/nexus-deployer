# Implementation Plan: Environment-Specific Operations

## Overview

This plan implements an environment selector modal that allows users to choose which specific deployment to update or delete when a capability has multiple active deployments.

## Tasks

- [x] 1. Create EnvironmentSelectorModal component
  - [x] 1.1 Create the modal component file with TypeScript interfaces
    - Create `EnvironmentSelectorModal.tsx` in `frontend/src/components/`
    - Define `EnvironmentSelectorModalProps` interface
    - Implement modal overlay with click-outside-to-close
    - Implement Escape key handler to close modal
    - _Requirements: 3.1, 3.4, 3.5_

  - [x] 1.2 Implement modal header with capability name and operation type
    - Display capability name prominently
    - Show "Update" or "Delete" based on operationType prop
    - Apply operation-specific styling (green for update, red for delete)
    - _Requirements: 3.2, 4.3, 4.4_

  - [x] 1.3 Implement deployment sorting utility
    - Create `sortDeployments` function
    - Sort PROD environments first
    - Sort remaining environments alphabetically
    - _Requirements: 3.6_

  - [x] 1.4 Write property test for environment sorting
    - **Property 9: Environment Sorting Order**
    - **Validates: Requirements 3.6**

- [x] 2. Implement environment cards in modal
  - [x] 2.1 Create selectable deployment cards
    - Display environment name, region, and formatted timestamp
    - Add hover/focus highlighting for interactivity
    - Implement click handler to select environment
    - _Requirements: 1.2, 3.3, 4.1_

  - [x] 2.2 Add environment-type visual distinction
    - Apply red border/accent for PROD environments
    - Apply blue border/accent for DEV/other environments
    - Add warning icon for PROD in delete mode
    - _Requirements: 1.5, 2.2, 4.2_

  - [x] 2.3 Write property test for deployment card content
    - **Property 2: Deployment Option Content Completeness**
    - **Validates: Requirements 1.2, 3.3**

  - [x] 2.4 Write property test for environment visual distinction
    - **Property 5: Environment Type Visual Distinction**
    - **Validates: Requirements 1.5, 4.2**

- [x] 3. Implement production delete confirmation
  - [x] 3.1 Create confirmation dialog for PROD deletion
    - Show warning message about production environment
    - Require explicit "Delete Production" button click
    - Allow cancel to return to environment selector
    - _Requirements: 2.5_

  - [x] 3.2 Write property test for production delete confirmation
    - **Property 6: Production Delete Confirmation**
    - **Validates: Requirements 2.2, 2.5**

- [x] 4. Integrate modal into CapabilitySelection component
  - [x] 4.1 Add modal state management
    - Add `selectorModalOpen` state
    - Add `pendingOperation` state for capability, deployments, and operation type
    - _Requirements: 1.1, 2.1_

  - [x] 4.2 Modify handleUpdate function
    - Check if deployments.length > 1
    - If multiple: open modal with update operation
    - If single: proceed directly with that deployment
    - _Requirements: 1.1, 1.3, 1.4_

  - [x] 4.3 Modify handleDelete function
    - Check if deployments.length > 1
    - If multiple: open modal with delete operation
    - If single: proceed directly with that deployment
    - _Requirements: 2.1, 2.3, 2.4_

  - [x] 4.4 Implement proceedWithOperation function
    - Set capability in wizard context
    - Set environment and region from selected deployment
    - Set deleteMode based on operation type
    - Navigate to AWS_CONFIGURATION step
    - _Requirements: 1.3, 2.3_

  - [x] 4.5 Write property test for modal display logic
    - **Property 1: Modal Display for Multi-Deployment Capabilities**
    - **Validates: Requirements 1.1, 2.1**

  - [x] 4.6 Write property test for single deployment bypass
    - **Property 4: Single Deployment Skips Modal**
    - **Validates: Requirements 1.4, 2.4**

  - [x] 4.7 Write property test for wizard state after selection
    - **Property 3: Environment Selection Sets Correct Wizard State**
    - **Validates: Requirements 1.3, 2.3**

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Add modal to component render
  - [x] 6.1 Render EnvironmentSelectorModal in CapabilitySelection
    - Add modal component at end of JSX
    - Pass required props (isOpen, onClose, onSelect, capability, deployments, operationType)
    - Handle onSelect to call proceedWithOperation
    - Handle onClose to reset modal state
    - _Requirements: 1.1, 2.1, 3.4_

  - [x] 6.2 Write property test for modal dismissal
    - **Property 8: Modal Dismissal Behavior**
    - **Validates: Requirements 3.4, 3.5**

- [x] 7. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- All tasks are required for comprehensive implementation
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties
- Unit tests validate specific examples and edge cases

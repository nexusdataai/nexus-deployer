# Implementation Plan

- [x] 1. Redesign WelcomeScreen component

  - [x] 1.1 Create hero SVG graphic for capability installer
    - Design a clean, modern SVG illustration representing cloud deployment/installation
    - Use blue/green color scheme consistent with the application
    - _Requirements: 1.1_

  - [x] 1.2 Simplify WelcomeScreen layout
    - Remove workflow steps grid
    - Remove key features section
    - Add hero graphic at top
    - Keep title "Totogi Capability Installer" and brief subtitle
    - Change button text to "Get Started"
    - _Requirements: 1.2, 1.3, 1.4_

- [x] 2. Update CapabilitySelection component for new behavior


  - [x] 2.1 Update capability categorization logic


    - Installed section: capabilities with at least one deployment
    - Available section: ALL capabilities (regardless of deployment status)
    - _Requirements: 2.2, 2.4, 2.5_


  - [x] 2.2 Update action handlers for new navigation

    - Install: Set capability in context → navigate to Environment Selection
    - Update: Set capability in context → navigate directly to AWS Credentials Screen
    - Delete: Set capability in context → navigate directly to Delete/Cleanup Screen
    - _Requirements: 3.2, 3.3, 4.2_


  - [x] 2.3 Remove DeleteConfirmationModal component

    - Delete button now navigates directly to cleanup screen
    - Remove modal state and related code
    - _Requirements: 3.3_


  - [x] 2.4 Write unit tests for capability categorization

    - Test ALL capabilities appear in Available section
    - Test only deployed capabilities appear in Installed section
    - Test action buttons render correctly for each section
    - _Requirements: 2.2, 2.4_


  - [x] 2.5 Write unit tests for navigation flows

    - Test Update navigates to AWS credentials screen
    - Test Delete navigates to cleanup screen
    - Test Install navigates to environment selection
    - _Requirements: 3.2, 3.3, 4.2_


- [x] 3. Checkpoint - Verify all tests pass


  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Add platform support indicators to WelcomeScreen


  - [x] 4.1 Update hero graphic to represent Telco Business Capability


    - Modify SVG to better represent Telco Business Capability deployment
    - Show capability flowing down to cloud/infrastructure
    - _Requirements: 1.1_



  - [x] 4.2 Update tagline text

    - Change subtitle to "Deploy Business Capability in your Environment"
    - _Requirements: 1.5_


  - [x] 4.3 Create platform icons SVG components

    - Create AWS icon SVG
    - Create Azure icon SVG
    - Create GCP icon SVG
    - Create Kubernetes icon SVG
    - Create On-Premise/Server icon SVG
    - _Requirements: 6.1_


  - [x] 4.4 Create PlatformIcon component with support indicator

    - Create reusable PlatformIcon component
    - Add green checkmark overlay for supported platforms
    - Add grayscale/muted style for unsupported platforms
    - Add Tooltip component for hover state
    - _Requirements: 6.2, 6.3, 6.5_




  - [x] 4.5 Add platform icons row to WelcomeScreen

    - Create DEPLOYMENT_PLATFORMS configuration array
    - Render platform icons in horizontal row below hero graphic
    - AWS shows checkmark (isSupported: true)
    - Azure, GCP, K8s, On-Premise show no checkmark (isSupported: false)
    - _Requirements: 6.1, 6.2, 6.3, 6.4_



  - [x] 4.6 Write unit tests for platform icons


    - Test all 5 platform icons render
    - Test AWS icon has checkmark indicator
    - Test non-AWS icons do NOT have checkmark
    - Test tooltips show correct text ("Supported" vs "Coming Soon")
    - **Property 8: Unsupported platforms have no checkmark**
    - **Property 9: Platform tooltip matches support status**

    - **Validates: Requirements 6.2, 6.3, 6.5**

- [ ] 5. Final Checkpoint - Verify all tests pass


  - Ensure all tests pass, ask the user if questions arise.


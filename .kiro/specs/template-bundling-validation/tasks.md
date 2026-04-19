# Implementation Plan: Template Bundling Validation

## Overview

This implementation plan addresses the template bundling issue causing deployment failures. The tasks are ordered to first fix the immediate build configuration issue, then add runtime path resolution, and finally add validation components.

## Tasks

- [x] 1. Update Electron build configuration to bundle templates
  - [x] 1.1 Add templates to extraResources in electron/package.json
    - Add entry for `../deploy/templates` to `templates` with YAML filter
    - _Requirements: 1.1, 1.2, 1.3_

- [x] 2. Create Resource Resolver utility
  - [x] 2.1 Create app/utils/resource_resolver.py module
    - Implement `get_templates_dir()` with environment detection
    - Handle Electron packaged mode (check for ELECTRON_RESOURCES_PATH or process.resourcesPath)
    - Handle PyInstaller mode (sys._MEIPASS)
    - Handle development mode (relative paths)
    - _Requirements: 2.1, 2.2, 2.3_
  - [x] 2.2 Write property test for path resolution
    - **Property 2: Path Resolution Returns Correct Absolute Paths**
    - **Validates: Requirements 2.1, 2.2, 2.3**

- [x] 3. Update CloudFormation service to use Resource Resolver
  - [x] 3.1 Refactor cloudformation_service.py to use ResourceResolver
    - Replace `_get_templates_dir()` with call to ResourceResolver
    - Add Electron resource path detection
    - _Requirements: 2.1, 2.2, 2.3_
  - [x] 3.2 Update pre_deployment_validator.py to use ResourceResolver
    - Replace duplicate `_get_templates_dir()` implementation
    - _Requirements: 2.1, 2.2, 2.3_

- [x] 4. Checkpoint - Verify template path resolution
  - Ensure templates are found in both dev and packaged modes
  - Ask the user if questions arise

- [x] 5. Create Template Validator service
  - [x] 5.1 Create app/services/template_validator.py
    - Implement `validate_templates()` for pre-deployment checks
    - Implement `validate_template_integrity()` for YAML and CFN validation
    - Return all missing templates in single error message
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2_
  - [x] 5.2 Write property test for template validation
    - **Property 3: Template Validation Checks All Required Templates**
    - **Validates: Requirements 3.1, 3.2, 3.4**
  - [x] 5.3 Write property test for missing template error aggregation
    - **Property 4: Missing Template Errors Include All Missing Files**
    - **Validates: Requirements 3.3, 3.5**
  - [x] 5.4 Write property test for template integrity validation
    - **Property 5: Template Integrity Validation Checks YAML and CloudFormation Structure**
    - **Validates: Requirements 4.1, 4.2**

- [x] 6. Integrate Template Validator into deployment flow
  - [x] 6.1 Add template validation to deployment_orchestrator.py
    - Call Template Validator before starting deployment
    - Return early with descriptive error if validation fails
    - _Requirements: 3.1, 3.4_

- [x] 7. Checkpoint - Verify pre-deployment validation
  - Test deployment with missing template to verify error handling
  - Ask the user if questions arise

- [x] 8. Create Template Manifest Generator
  - [x] 8.1 Create scripts/generate_template_manifest.py
    - Generate template-manifest.json with path, filename, size for each template
    - Include SHA256 hash for integrity verification
    - _Requirements: 5.1, 5.2_
  - [x] 8.2 Write property test for manifest content
    - **Property 6: Manifest Contains Required Fields for All Templates**
    - **Validates: Requirements 5.1, 5.2**

- [x] 9. Add manifest validation on startup
  - [x] 9.1 Add manifest validation to Template Validator
    - Compare available templates against manifest on startup
    - Warn if templates are missing compared to manifest
    - _Requirements: 5.3, 5.4_
  - [x] 9.2 Write property test for manifest validation
    - **Property 7: Manifest Validation Detects Missing Templates**
    - **Validates: Requirements 5.3, 5.4**

- [x] 10. Update build scripts to generate manifest
  - [x] 10.1 Update backend build process to run manifest generator
    - Add manifest generation step before PyInstaller
    - Include manifest in bundled resources
    - _Requirements: 5.1_

- [x] 11. Final checkpoint - End-to-end verification
  - Build installer and verify templates are bundled
  - Test deployment with bundled templates
  - Verify manifest validation on startup
  - Ask the user if questions arise

## Notes

- All tasks including property-based tests are required
- The critical fix is Task 1 (updating electron/package.json) - this alone will resolve the immediate deployment failure
- Tasks 2-3 improve robustness of path resolution across environments
- Tasks 5-9 add validation to catch issues early with helpful error messages
- Each task references specific requirements for traceability

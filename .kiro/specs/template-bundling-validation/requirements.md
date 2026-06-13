<!-- (renamed totogi-* -> nexus-* on 2026-06-13; original wording was design-snapshot) -->
# Requirements Document

## Introduction

This specification addresses the critical issue where CloudFormation templates are not properly bundled with the Nexus AI Installer, causing deployment failures. The deployer expects templates at runtime in a specific location (`deploy/templates/`), but these templates are not included in the installer's `extraResources` configuration, resulting in "Template not found" errors during capability deployment.

## Glossary

- **Installer**: The Electron-based Nexus AI Installer application that packages the deployment wizard
- **Template_Bundle**: The collection of CloudFormation YAML templates required for capability deployment
- **Template_Validator**: A component that verifies template presence and integrity before deployment
- **Resource_Resolver**: A component that determines the correct path to bundled resources at runtime
- **Deployment_Engine**: The backend component that orchestrates CloudFormation stack deployments

## Requirements

### Requirement 1: Template Bundling in Installer

**User Story:** As a deployment operator, I want all CloudFormation templates to be included in the installer package, so that deployments work without requiring external template files.

#### Acceptance Criteria

1. WHEN the Installer is built, THE Installer SHALL include all files from `deploy/templates/` directory in the packaged application
2. WHEN the Installer is built, THE Installer SHALL preserve the directory structure of templates (backend/, frontend/ subdirectories)
3. WHEN the Installer is built, THE Installer SHALL include all `.yaml` template files without modification
4. IF a template file is missing from the source directory during build, THEN THE Installer build process SHALL fail with a descriptive error

### Requirement 2: Runtime Template Path Resolution

**User Story:** As a deployment operator, I want the deployer to automatically find templates in the correct location, so that deployments work regardless of installation directory.

#### Acceptance Criteria

1. WHEN running in packaged Electron mode, THE Resource_Resolver SHALL locate templates in the `resources/templates/` directory relative to the application
2. WHEN running in development mode, THE Resource_Resolver SHALL locate templates in the `deploy/templates/` directory relative to the project root
3. WHEN the Deployment_Engine requests a template path, THE Resource_Resolver SHALL return the absolute path to the template file
4. IF a requested template does not exist at the resolved path, THEN THE Resource_Resolver SHALL return a descriptive error indicating the expected location

### Requirement 3: Pre-Deployment Template Validation

**User Story:** As a deployment operator, I want the system to validate template availability before starting deployment, so that I receive early feedback about missing templates.

#### Acceptance Criteria

1. WHEN a deployment is initiated, THE Template_Validator SHALL verify all required templates exist before proceeding
2. WHEN validating templates, THE Template_Validator SHALL check for the presence of all template files referenced by the selected capability
3. IF any required template is missing, THEN THE Template_Validator SHALL report all missing templates in a single error message
4. WHEN all templates are present, THE Template_Validator SHALL allow the deployment to proceed
5. WHEN a template validation fails, THE Template_Validator SHALL display the expected template path and suggest remediation steps

### Requirement 4: Template Integrity Verification

**User Story:** As a deployment operator, I want the system to verify template integrity, so that I can be confident templates haven't been corrupted during packaging.

#### Acceptance Criteria

1. WHEN validating templates, THE Template_Validator SHALL verify each template file is valid YAML
2. WHEN validating templates, THE Template_Validator SHALL verify each template contains required CloudFormation sections (AWSTemplateFormatVersion or Resources)
3. IF a template fails integrity validation, THEN THE Template_Validator SHALL report the specific validation error
4. WHEN template integrity validation passes, THE Template_Validator SHALL log successful validation for audit purposes

### Requirement 5: Template Manifest Generation

**User Story:** As a build engineer, I want a manifest of all bundled templates generated during build, so that I can verify the correct templates are included.

#### Acceptance Criteria

1. WHEN the Installer is built, THE build process SHALL generate a `template-manifest.json` file listing all bundled templates
2. THE template manifest SHALL include the relative path, filename, and file size for each template
3. WHEN the application starts, THE Template_Validator SHALL compare available templates against the manifest
4. IF the manifest check fails, THEN THE Template_Validator SHALL warn the user about potentially incomplete installation

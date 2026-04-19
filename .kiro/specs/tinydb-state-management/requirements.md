# Requirements Document

## Introduction

This document specifies the requirements for migrating the starhub-deployer application from file-based JSON state management to TinyDB for managing installation state and capabilities catalogue. The current system uses individual JSON files for deployment state tracking and a single JSON file for the capabilities catalogue. TinyDB will provide a more robust, queryable, and maintainable solution while maintaining the simplicity of a file-based database suitable for desktop and PWA deployment scenarios.

## Glossary

- **TinyDB**: A lightweight, document-oriented database written in pure Python with no external dependencies
- **Deployment State**: Information about deployed CloudFormation stacks for each capability and environment combination
- **Capabilities Catalogue**: The master list of available capabilities that can be deployed
- **State Service**: The backend service responsible for managing deployment state persistence
- **Capability Service**: The backend service responsible for managing the capabilities catalogue
- **Document**: A JSON-like record stored in TinyDB
- **Table**: A collection of documents in TinyDB (analogous to a database table)
- **Query**: A TinyDB operation to search and filter documents
- **Installation Instance**: A single deployment of the starhub-deployer application managing one or more capability deployments

## Requirements

### Requirement 1

**User Story:** As a system administrator, I want deployment state to be stored in a reliable database, so that I can query and manage deployment information efficiently.

#### Acceptance Criteria

1. WHEN the system initializes THEN TinyDB SHALL create or open a database file at `backend/data/state.db`
2. WHEN a capability is deployed THEN the system SHALL store deployment state in the TinyDB deployments table
3. WHEN deployment state is queried THEN the system SHALL retrieve records from TinyDB using structured queries
4. WHEN deployment state is updated THEN the system SHALL modify existing TinyDB documents atomically
5. WHEN a capability is cleaned up THEN the system SHALL remove corresponding deployment state records from TinyDB

### Requirement 2

**User Story:** As a developer, I want the capabilities catalogue to be stored in TinyDB, so that I can query, filter, and manage capabilities programmatically.

#### Acceptance Criteria

1. WHEN the system initializes THEN TinyDB SHALL create or open a capabilities table in the database
2. WHEN the application starts THEN the system SHALL load capabilities from `backend/capabilities/capabilities.json` into TinyDB if the table is empty
3. WHEN capabilities are queried by category THEN the system SHALL return filtered results using TinyDB queries
4. WHEN capabilities are queried by cloud provider THEN the system SHALL return filtered results using TinyDB queries
5. WHEN a capability is updated THEN the system SHALL modify the corresponding TinyDB document

### Requirement 3

**User Story:** As a system architect, I want backward compatibility with existing state files, so that existing deployments are not disrupted during migration.

#### Acceptance Criteria

1. WHEN the system detects existing JSON state files in `deploy/state/` THEN the system SHALL migrate them to TinyDB automatically
2. WHEN migration occurs THEN the system SHALL preserve all existing deployment state data
3. WHEN migration completes successfully THEN the system SHALL archive original JSON files to `deploy/state/archive/`
4. IF migration fails THEN the system SHALL log errors and continue using JSON files as fallback
5. WHEN the system operates in fallback mode THEN the system SHALL function with existing JSON-based state service

### Requirement 4

**User Story:** As a developer, I want a clean service interface for state management, so that the rest of the application is decoupled from the storage implementation.

#### Acceptance Criteria

1. WHEN the deployment state service is instantiated THEN the system SHALL initialize TinyDB connection with proper error handling
2. WHEN state operations are performed THEN the system SHALL use consistent method signatures matching the existing service interface
3. WHEN database operations fail THEN the system SHALL raise appropriate exceptions with descriptive error messages
4. WHEN the service is used THEN the system SHALL provide methods for CRUD operations on deployment state
5. WHEN concurrent access occurs THEN TinyDB SHALL handle thread-safe operations automatically

### Requirement 5

**User Story:** As a system administrator, I want to query deployment history, so that I can audit and track capability deployments over time.

#### Acceptance Criteria

1. WHEN querying deployments by capability name THEN the system SHALL return all matching deployment records
2. WHEN querying deployments by environment THEN the system SHALL return all matching deployment records
3. WHEN querying deployments by date range THEN the system SHALL return deployments within the specified time period
4. WHEN querying deployments by region THEN the system SHALL return all deployments in the specified AWS region
5. WHEN listing all deployments THEN the system SHALL return a summary of all tracked deployments with pagination support

### Requirement 6

**User Story:** As a developer, I want to query capabilities with complex filters, so that I can provide rich search and filtering functionality in the UI.

#### Acceptance Criteria

1. WHEN searching capabilities by name THEN the system SHALL return capabilities matching the search term using case-insensitive partial matching
2. WHEN filtering by multiple criteria THEN the system SHALL combine filters using logical AND operations
3. WHEN sorting capabilities THEN the system SHALL return results ordered by the specified field
4. WHEN querying capability versions THEN the system SHALL support version comparison operations
5. WHEN checking capability requirements THEN the system SHALL query nested document fields efficiently

### Requirement 7

**User Story:** As a system operator, I want deployment state to include stack-level details, so that I can track individual CloudFormation stacks within a deployment.

#### Acceptance Criteria

1. WHEN storing deployment state THEN the system SHALL persist the list of deployed stacks as nested documents
2. WHEN querying a specific stack THEN the system SHALL retrieve stack details from the deployment record
3. WHEN updating a stack status THEN the system SHALL modify the nested stack document within the deployment record
4. WHEN a stack is deleted THEN the system SHALL remove the stack entry from the deployment record
5. WHEN listing stacks for a deployment THEN the system SHALL return all stack documents with their current status

### Requirement 8

**User Story:** As a developer, I want comprehensive error handling for database operations, so that the application remains stable when database issues occur.

#### Acceptance Criteria

1. WHEN the database file is corrupted THEN the system SHALL detect the corruption and log an error with recovery instructions
2. WHEN disk space is insufficient THEN the system SHALL catch write errors and notify the user
3. WHEN the database file is locked THEN the system SHALL retry operations with exponential backoff
4. WHEN a query fails THEN the system SHALL log the error with query details and return an empty result or raise an exception
5. WHEN database initialization fails THEN the system SHALL provide clear error messages indicating the root cause

### Requirement 9

**User Story:** As a system administrator, I want database backup and restore capabilities, so that I can protect deployment state data.

#### Acceptance Criteria

1. WHEN a backup is requested THEN the system SHALL create a timestamped copy of the TinyDB database file
2. WHEN storing backups THEN the system SHALL save backup files to `backend/data/backups/` directory
3. WHEN restoring from backup THEN the system SHALL replace the current database with the specified backup file
4. WHEN automatic backup is enabled THEN the system SHALL create backups before major operations
5. WHEN backup retention is configured THEN the system SHALL remove backups older than the specified retention period

### Requirement 10

**User Story:** As a developer, I want database schema versioning, so that future schema changes can be managed systematically.

#### Acceptance Criteria

1. WHEN the database is created THEN the system SHALL store a schema version document in a metadata table
2. WHEN the application starts THEN the system SHALL verify the database schema version matches the expected version
3. WHEN a schema mismatch is detected THEN the system SHALL run migration scripts to update the schema
4. WHEN migration scripts execute THEN the system SHALL update the schema version after successful migration
5. WHEN migration fails THEN the system SHALL restore the database from automatic backup and log the failure

### Requirement 11

**User Story:** As a developer, I want indexed queries for common access patterns, so that database operations remain performant as data grows.

#### Acceptance Criteria

1. WHEN querying by capability name and environment THEN the system SHALL use indexed fields for optimal performance
2. WHEN querying by timestamp ranges THEN the system SHALL use indexed date fields
3. WHEN the database grows beyond 1000 records THEN query performance SHALL remain under 100ms for indexed queries
4. WHEN creating indexes THEN the system SHALL define indexes on frequently queried fields during initialization
5. WHEN analyzing query performance THEN the system SHALL provide logging for slow queries exceeding 500ms

### Requirement 12

**User Story:** As a system architect, I want the TinyDB implementation to support the existing API contracts, so that frontend and other backend services require no changes.

#### Acceptance Criteria

1. WHEN the deployment service API is called THEN the system SHALL return responses in the same format as the JSON-based implementation
2. WHEN the capabilities API is called THEN the system SHALL return capability objects matching the existing schema
3. WHEN error conditions occur THEN the system SHALL raise the same exception types as the existing implementation
4. WHEN the service is instantiated THEN the system SHALL accept the same initialization parameters as the existing service
5. WHEN integration tests run THEN the system SHALL pass all existing test cases without modification

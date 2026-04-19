# Implementation Tasks

## Task 1: Create Data Models

- [x] 1.1 Create discovery models module
  - Create `backend/app/services/discovery/__init__.py`
  - Create `backend/app/services/discovery/models.py`
  - Implement `CloudProvider` enum (aws, azure, gcp)
  - Implement `LandingZone` dataclass with to_dict method
  - Implement `DiscoveredStack` dataclass
  - Implement `CapabilityStatus` enum (healthy, failed, in_progress, partial, not_found)
  - Implement `DiscoveredCapability` dataclass with to_dict method
  - Implement `DiscoveryJobStatus` enum
  - Implement `DiscoveryJob` dataclass
  - _Requirements: 3.1, 4.3, 5.1, 9.1_

## Task 2: Implement Landing Zone Manager

- [x] 2.1 Create LandingZoneManager class
  - Create `backend/app/services/discovery/landing_zone_manager.py`
  - Initialize with TinyDBStateManager
  - Create `landing_zones` table in TinyDB
  - Implement `create_landing_zone()` method
  - Handle duplicate account detection and update
  - Implement `get_landing_zone()` method
  - Implement `list_landing_zones()` with optional provider filter
  - Implement `delete_landing_zone()` method
  - Implement `update_discovery_status()` method
  - _Requirements: 3.2, 3.3, 3.4, 3.5, 3.6_

## Task 3: Implement Discovery Service

- [x] 3.1 Create DiscoveryService class
  - Create `backend/app/services/discovery/discovery_service.py`
  - Initialize with region and optional credentials
  - Implement lazy-loaded CloudFormation client
  - Define KNOWN_STACK_TYPES constant from CloudFormationDeploymentService.STACK_ORDER
  - Define VALID_ENVIRONMENTS constant
  - _Requirements: 4.1, 4.4_

- [x] 3.2 Implement stack name parsing
  - Implement `parse_stack_name()` method
  - Parse `{capability}-{environment}-{stack-type}` pattern
  - Handle all valid stack types (backend-*, frontend-*)
  - Handle all valid environments (dev, test, stage, prod)
  - Return None for non-matching stack names
  - _Requirements: 4.3, 4.4, 4.6, 6.1, 6.5_

- [x] 3.3 Implement CloudFormation scanning
  - Implement `discover_capabilities()` method
  - Use CloudFormation ListStacks paginator
  - Filter by relevant stack statuses (exclude DELETE_COMPLETE)
  - Parse each stack name and collect matching stacks
  - Implement `_get_stack_details()` for full stack info
  - Extract stack outputs and tags
  - Support progress callback for UI updates
  - _Requirements: 4.1, 4.2, 5.6, 5.7_

- [x] 3.4 Implement capability grouping
  - Implement `_group_stacks_into_capabilities()` method
  - Group stacks by (capability_name, environment)
  - Build DiscoveredStack objects for each stack
  - Extract frontend_url and backend_url from outputs
  - Extract version from stack tags if available
  - _Requirements: 4.5, 6.2, 6.3, 6.4_

- [x] 3.5 Implement status determination
  - Implement `_determine_capability_status()` method
  - Check for FAILED/ROLLBACK states first
  - Check for IN_PROGRESS states
  - Determine expected stacks based on frontend/backend presence
  - Calculate missing stacks for PARTIAL status
  - Return HEALTHY if all expected stacks present and complete
  - _Requirements: 5.2, 5.3, 5.4, 5.5, 10.1, 10.2, 10.5_

## Task 4: Implement Discovery Sync Service

- [x] 4.1 Create DiscoverySyncService class
  - Create `backend/app/services/discovery/discovery_sync_service.py`
  - Initialize with InstallationTracker
  - Implement `sync_discovered_capabilities()` method
  - Get existing installations for landing zone
  - Compare discovered vs existing capabilities
  - _Requirements: 7.1, 7.3_

- [x] 4.2 Implement installation record creation
  - Implement `_create_installation()` method
  - Map CapabilityStatus to installation status
  - Set strategy to "DISCOVERED"
  - Populate all required fields from DiscoveredCapability
  - Include stacks_summary with counts
  - _Requirements: 7.5, 7.6_

- [x] 4.3 Implement installation record update
  - Implement `_update_installation()` method
  - Update status, URLs, version, discovered_at
  - Update stacks_summary
  - Use capability_name + environment + account_id as unique key
  - _Requirements: 7.2, 7.3_

- [x] 4.4 Implement not-found marking
  - Implement `_mark_not_found()` method
  - Mark installations that exist in TinyDB but not in AWS
  - Set status to "not_found_in_aws"
  - Preserve the record for reference
  - _Requirements: 7.4_

## Task 5: Implement Discovery API Router

- [x] 5.1 Create discovery router
  - Create `backend/app/routers/discovery.py`
  - Define request/response Pydantic models
  - Create in-memory discovery jobs storage
  - Register router in main.py
  - _Requirements: 1.1, 2.1_

- [x] 5.2 Implement landing zone endpoints
  - POST /api/discovery/landing-zones - Create landing zone
  - GET /api/discovery/landing-zones - List landing zones
  - DELETE /api/discovery/landing-zones/{id} - Delete landing zone
  - Validate provider (only AWS supported)
  - Return appropriate error for Azure/GCP
  - _Requirements: 1.2, 1.3, 1.4, 3.2, 3.3, 3.4_

- [x] 5.3 Implement discovery endpoints
  - POST /api/discovery/discover - Start discovery
  - GET /api/discovery/discover/{job_id}/status - Get status
  - POST /api/discovery/refresh/{landing_zone_id} - Refresh
  - Validate landing zone exists
  - Get AWS credentials from session manager
  - Handle credential expiration
  - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6, 8.1, 8.2, 8.3, 8.4, 8.5_

- [x] 5.4 Implement background discovery task
  - Create `_run_discovery()` background function
  - Update job status throughout process
  - Scan multiple regions if specified
  - Call DiscoveryService for each region
  - Call DiscoverySyncService to sync results
  - Update landing zone status on completion
  - Handle and log errors
  - _Requirements: 4.7, 8.6, 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

## Task 6: Implement Frontend Components

- [x] 6.1 Create LandingZoneSelector component
  - Create `frontend/src/components/LandingZoneSelector.tsx`
  - Display cloud provider selection (AWS, Azure, GCP)
  - Show "Coming Soon" for Azure and GCP
  - List existing landing zones for selected provider
  - Show landing zone details (account, region, last discovery)
  - Add "Add Landing Zone" button
  - Handle landing zone selection
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 3.3_

- [x] 6.2 Create DiscoveryPanel component
  - Create `frontend/src/components/DiscoveryPanel.tsx`
  - Start discovery on mount
  - Poll for discovery status
  - Display progress message and spinner
  - Show stacks scanned and capabilities found
  - Display errors if any
  - Handle completion and failure states
  - _Requirements: 4.7, 8.3, 8.4_

- [x] 6.3 Add discovery API to frontend
  - Add `discoveryApi` object to `frontend/src/services/api.ts`
  - Implement createLandingZone()
  - Implement listLandingZones()
  - Implement deleteLandingZone()
  - Implement startDiscovery()
  - Implement getDiscoveryStatus()
  - Implement refreshCapabilities()
  - _Requirements: All frontend API calls_

- [x] 6.4 Enhance CapabilitySelection component
  - Add "Discover from AWS" button/option
  - Add landing zone filter dropdown
  - Show landing zone indicator on discovered capabilities
  - Show "Discovered" badge for discovered capabilities
  - Update refresh to use discovery refresh for discovered capabilities
  - _Requirements: 8.1, 9.2, 9.3, 11.1, 11.2, 11.3_

## Task 7: Implement Multi-Account Support

- [x] 7.1 Add landing zone context to capabilities
  - Add landing_zone_id field to installation records
  - Update deployment states API to include landing zone info
  - Filter capabilities by landing zone in UI
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

- [x] 7.2 Implement unified view
  - Allow discovery across multiple landing zones
  - Aggregate capabilities from all landing zones
  - Show account identifier for each capability
  - Handle same capability name in different accounts
  - _Requirements: 11.1, 11.5_

## Task 8: Testing

- [x] 8.1 Unit tests for stack name parsing
  - Test valid stack names are parsed correctly
  - Test all stack types are recognized
  - Test all environments are recognized
  - Test invalid stack names return None
  - Test edge cases (hyphens in capability name)
  - _Requirements: 4.3, 4.4, 4.6_

- [x] 8.2 Unit tests for status determination
  - Test FAILED status takes priority
  - Test IN_PROGRESS status detection
  - Test PARTIAL status with missing stacks
  - Test HEALTHY status when all stacks complete
  - _Requirements: 5.2, 5.3, 5.4, 5.5_

- [x] 8.3 Unit tests for TinyDB sync
  - Test new capabilities are created
  - Test existing capabilities are updated
  - Test missing capabilities are marked not found
  - Test sync is idempotent
  - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [x] 8.4 Integration tests for discovery flow
  - Test end-to-end discovery with mocked AWS
  - Test landing zone CRUD operations
  - Test discovery job status updates
  - Test error handling
  - _Requirements: 12.1, 12.2, 12.3, 12.4_

## Task 9: Documentation

- [x] 9.1 Update API documentation
  - Document new discovery endpoints
  - Document request/response models
  - Add examples for common operations
  - _Requirements: All API endpoints_

- [x] 9.2 Update user documentation
  - Add discovery feature guide
  - Document landing zone setup
  - Document multi-account workflow
  - Add troubleshooting section
  - _Requirements: All user-facing features_

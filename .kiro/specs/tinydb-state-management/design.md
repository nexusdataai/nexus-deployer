# Design Document

## Overview

This design document describes the migration from file-based JSON state management to TinyDB for the starhub-deployer application. TinyDB is a lightweight, pure-Python document database that requires no external dependencies, making it ideal for desktop and PWA deployment scenarios. The design maintains backward compatibility with existing JSON state files while providing enhanced querying capabilities, better data integrity, and a foundation for future enhancements.

### Key Design Goals

1. **Minimal Dependencies**: TinyDB is pure Python with no external dependencies
2. **Backward Compatibility**: Seamless migration from existing JSON files
3. **API Stability**: Maintain existing service interfaces to avoid breaking changes
4. **Performance**: Indexed queries for common access patterns
5. **Reliability**: Comprehensive error handling and backup capabilities
6. **Simplicity**: File-based database suitable for single-instance deployments

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI Backend                          │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────────┐         ┌──────────────────┐         │
│  │  Deployment      │         │  Capability      │         │
│  │  Router          │         │  Router          │         │
│  └────────┬─────────┘         └────────┬─────────┘         │
│           │                             │                    │
│           ▼                             ▼                    │
│  ┌──────────────────┐         ┌──────────────────┐         │
│  │  Deployment      │         │  Capability      │         │
│  │  Service         │         │  Service         │         │
│  └────────┬─────────┘         └────────┬─────────┘         │
│           │                             │                    │
│           └──────────┬──────────────────┘                    │
│                      ▼                                        │
│           ┌──────────────────────┐                          │
│           │  TinyDB State        │                          │
│           │  Manager             │                          │
│           └──────────┬───────────┘                          │
│                      │                                        │
└──────────────────────┼────────────────────────────────────┘
                       │
                       ▼
            ┌──────────────────────┐
            │  TinyDB Database     │
            │  backend/data/       │
            │  state.db            │
            └──────────────────────┘
```

### Database Structure

The TinyDB database will contain the following tables:

1. **deployments** - Deployment state records
2. **capabilities** - Capabilities catalogue
3. **metadata** - Schema version and system metadata
4. **audit_log** - Optional audit trail for state changes

### Migration Strategy

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Startup                       │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
         ┌────────────────────────┐
         │ Check if TinyDB exists │
         └────────┬───────────────┘
                  │
         ┌────────┴────────┐
         │                 │
         ▼                 ▼
    [Exists]          [Not Exists]
         │                 │
         │                 ▼
         │      ┌──────────────────────┐
         │      │ Create new database  │
         │      │ Initialize schema    │
         │      └──────────┬───────────┘
         │                 │
         │                 ▼
         │      ┌──────────────────────┐
         │      │ Check for JSON files │
         │      │ in deploy/state/     │
         │      └──────────┬───────────┘
         │                 │
         │        ┌────────┴────────┐
         │        │                 │
         │        ▼                 ▼
         │   [Files Found]    [No Files]
         │        │                 │
         │        ▼                 │
         │   ┌─────────────┐       │
         │   │ Migrate to  │       │
         │   │ TinyDB      │       │
         │   └──────┬──────┘       │
         │          │               │
         │          ▼               │
         │   ┌─────────────┐       │
         │   │ Archive     │       │
         │   │ JSON files  │       │
         │   └──────┬──────┘       │
         │          │               │
         └──────────┴───────────────┘
                    │
                    ▼
         ┌──────────────────────┐
         │ Load capabilities    │
         │ from JSON if needed  │
         └──────────┬───────────┘
                    │
                    ▼
         ┌──────────────────────┐
         │ System Ready         │
         └──────────────────────┘
```

## Components and Interfaces

### 1. TinyDB State Manager

Core component responsible for all database operations.

```python
class TinyDBStateManager:
    """
    Manages TinyDB database connections and operations
    """
    
    def __init__(self, db_path: str = "backend/data/state.db"):
        """Initialize TinyDB connection"""
        
    def get_table(self, table_name: str) -> Table:
        """Get or create a table"""
        
    def close(self):
        """Close database connection"""
        
    def backup(self, backup_name: Optional[str] = None) -> str:
        """Create database backup"""
        
    def restore(self, backup_path: str) -> bool:
        """Restore from backup"""
        
    def get_schema_version(self) -> str:
        """Get current schema version"""
        
    def migrate_schema(self, target_version: str) -> bool:
        """Migrate schema to target version"""
```

### 2. Deployment State Service (TinyDB Implementation)

Replaces the existing `DeploymentStateService` with TinyDB backend.

```python
class DeploymentStateService:
    """
    Service for managing deployment state using TinyDB
    """
    
    def __init__(self, db_manager: Optional[TinyDBStateManager] = None):
        """Initialize with TinyDB manager"""
        
    def save_deployment_state(
        self,
        capability_name: str,
        environment: str,
        region: str,
        stacks: List[Dict[str, Any]],
        deployment_metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Save deployment state to TinyDB"""
        
    def load_deployment_state(
        self,
        capability_name: str,
        environment: str
    ) -> Optional[Dict[str, Any]]:
        """Load deployment state from TinyDB"""
        
    def delete_deployment_state(
        self,
        capability_name: str,
        environment: str
    ) -> bool:
        """Delete deployment state from TinyDB"""
        
    def list_deployments(
        self,
        capability_name: Optional[str] = None,
        environment: Optional[str] = None,
        region: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """List deployments with optional filters"""
        
    def update_stack_in_state(
        self,
        capability_name: str,
        environment: str,
        stack_name: str,
        stack_updates: Dict[str, Any]
    ) -> bool:
        """Update specific stack information"""
        
    def get_deployment_history(
        self,
        capability_name: str,
        environment: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get deployment history for a capability/environment"""
```

### 3. Capability Service

New service for managing the capabilities catalogue.

```python
class CapabilityService:
    """
    Service for managing capabilities catalogue using TinyDB
    """
    
    def __init__(self, db_manager: Optional[TinyDBStateManager] = None):
        """Initialize with TinyDB manager"""
        
    def load_capabilities_from_json(self, json_path: str) -> bool:
        """Load capabilities from JSON file into TinyDB"""
        
    def get_all_capabilities(self) -> List[Dict[str, Any]]:
        """Get all capabilities"""
        
    def get_capability_by_id(self, capability_id: str) -> Optional[Dict[str, Any]]:
        """Get capability by ID"""
        
    def search_capabilities(
        self,
        search_term: str,
        category: Optional[str] = None,
        cloud_provider: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search capabilities with filters"""
        
    def get_capabilities_by_category(self, category: str) -> List[Dict[str, Any]]:
        """Get capabilities filtered by category"""
        
    def update_capability(
        self,
        capability_id: str,
        updates: Dict[str, Any]
    ) -> bool:
        """Update capability information"""
        
    def add_capability(self, capability: Dict[str, Any]) -> bool:
        """Add new capability to catalogue"""
```

### 4. Migration Service

Handles migration from JSON files to TinyDB.

```python
class MigrationService:
    """
    Handles migration from JSON-based state to TinyDB
    """
    
    def __init__(
        self,
        db_manager: TinyDBStateManager,
        state_dir: str = "deploy/state"
    ):
        """Initialize migration service"""
        
    def migrate_deployment_states(self) -> Dict[str, Any]:
        """
        Migrate all JSON state files to TinyDB
        Returns migration statistics
        """
        
    def archive_json_files(self) -> bool:
        """Archive migrated JSON files"""
        
    def verify_migration(self) -> bool:
        """Verify migration completed successfully"""
```

## Data Models

### Deployment State Document

```python
{
    "doc_id": 1,  # Auto-generated by TinyDB
    "capability_name": "Call Processing",
    "capability_id": "call-processing",
    "environment": "prod",
    "region": "us-east-1",
    "stacks": [
        {
            "stack_name": "call-processing-prod-frontend-global",
            "stack_type": "frontend-global",
            "stack_id": "arn:aws:cloudformation:...",
            "region": "us-east-1",
            "status": "CREATE_COMPLETE",
            "deployed_at": "2025-12-14T10:30:00.000000",
            "last_updated": "2025-12-14T10:30:00.000000",
            "outputs": {
                "CloudFrontDistributionId": "E1234567890ABC",
                "S3BucketName": "call-processing-prod-frontend"
            }
        },
        {
            "stack_name": "call-processing-prod-backend-service",
            "stack_type": "backend-service",
            "stack_id": "arn:aws:cloudformation:...",
            "region": "us-east-1",
            "status": "CREATE_COMPLETE",
            "deployed_at": "2025-12-14T10:35:00.000000",
            "last_updated": "2025-12-14T10:35:00.000000",
            "outputs": {
                "ServiceUrl": "https://api.example.com",
                "LoadBalancerDNS": "call-processing-prod-lb-123456.us-east-1.elb.amazonaws.com"
            }
        }
    ],
    "deployment_config": {
        "frontend_strategy": "cloudfront-s3",
        "backend_strategy": "ecs-fargate",
        "domain_name": "app.example.com"
    },
    "metadata": {
        "frontend_deployed": true,
        "backend_deployed": true,
        "frontend_url": "https://app.example.com",
        "backend_url": "https://api.example.com",
        "deployment_duration_seconds": 1200,
        "deployed_by": "admin@example.com"
    },
    "created_at": "2025-12-14T10:30:00.000000",
    "last_deployment": "2025-12-14T10:35:00.000000",
    "version": "1.2.0"
}
```

### Capability Document

```python
{
    "doc_id": 1,  # Auto-generated by TinyDB
    "id": "call-processing",
    "name": "Call Processing",
    "version": "1.2.0",
    "description": "AI-powered voice call routing and processing system",
    "icon": "phone-call.svg",
    "category": "Voice Services",
    "supported_clouds": ["aws"],
    "supported_environments": ["dev", "test", "stage", "prod"],
    "requirements": {
        "frontend": true,
        "backend": true,
        "database": true,
        "authentication": true
    },
    "artifacts": {
        "frontend": {
            "s3_uri": "s3://starhub-ui-delivery-ps/starhub-ui-1.0.0.zip",
            "size_mb": 15
        },
        "backend": {
            "ecr_uri": "764119721991.dkr.ecr.us-east-1.amazonaws.com/ai-job-engine:latest",
            "size_mb": 250
        }
    },
    "aws_options": {
        "frontend": ["cloudfront-s3"],
        "backend": ["ecs-fargate"]
    },
    "estimated_deployment_time": 20,
    "documentation_url": "https://docs.totogi.com/call-processing",
    "required_iam_permissions": [...],
    "prerequisites": [...],
    "created_at": "2025-12-01T00:00:00.000000",
    "updated_at": "2025-12-14T00:00:00.000000"
}
```

### Metadata Document

```python
{
    "doc_id": 1,
    "key": "schema_version",
    "value": "1.0.0",
    "updated_at": "2025-12-14T10:00:00.000000"
}
```

### Audit Log Document (Optional)

```python
{
    "doc_id": 1,
    "timestamp": "2025-12-14T10:30:00.000000",
    "operation": "save_deployment_state",
    "table": "deployments",
    "document_id": 5,
    "capability_name": "Call Processing",
    "environment": "prod",
    "user": "admin@example.com",
    "changes": {
        "stacks": "added 2 stacks",
        "status": "CREATE_COMPLETE"
    }
}
```


## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Deployment state round-trip consistency
*For any* valid deployment state data (capability name, environment, region, stacks, metadata), storing it to TinyDB and then loading it back should return data equivalent to the original input.
**Validates: Requirements 1.2, 1.3**

### Property 2: Deployment state deletion completeness
*For any* deployment state stored in TinyDB, after calling delete_deployment_state, querying for that deployment should return None.
**Validates: Requirements 1.5**

### Property 3: Capability filtering correctness
*For any* set of capabilities stored in TinyDB and any filter criteria (category, cloud provider, search term), all returned capabilities should match the filter criteria and no matching capabilities should be excluded.
**Validates: Requirements 2.3, 2.4, 6.1, 6.2**

### Property 4: Capability update persistence
*For any* capability in TinyDB and any valid update data, after updating the capability, querying it should return the updated values.
**Validates: Requirements 2.5**

### Property 5: JSON migration data preservation
*For any* valid JSON state file in deploy/state/, after migration to TinyDB, the data retrieved from TinyDB should be equivalent to the original JSON content.
**Validates: Requirements 3.1, 3.2**

### Property 6: Migration file archival
*For any* JSON state files successfully migrated, all original files should be moved to deploy/state/archive/ and no longer exist in deploy/state/.
**Validates: Requirements 3.3**

### Property 7: Database operation error handling
*For any* database operation that fails (due to corruption, lock, or other errors), the system should either raise an appropriate exception or return an error indicator without crashing.
**Validates: Requirements 4.3, 8.4**

### Property 8: Deployment query filtering
*For any* set of deployments in TinyDB and any query filter (capability name, environment, region, date range), all returned deployments should match all specified filter criteria.
**Validates: Requirements 5.1, 5.2, 5.3, 5.4**

### Property 9: Deployment pagination consistency
*For any* set of deployments in TinyDB, retrieving all pages with a given page size should return the same total set of deployments as retrieving without pagination, with no duplicates or omissions.
**Validates: Requirements 5.5**

### Property 10: Capability sorting correctness
*For any* set of capabilities and any sortable field, the returned results should be ordered according to the specified field in ascending or descending order.
**Validates: Requirements 6.3**

### Property 11: Version comparison correctness
*For any* two capability version strings, the version comparison operation should correctly determine their relative ordering according to semantic versioning rules.
**Validates: Requirements 6.4**

### Property 12: Nested field query correctness
*For any* capability with nested requirement fields, querying by nested field values should return all capabilities where the nested field matches the query.
**Validates: Requirements 6.5**

### Property 13: Stack storage and retrieval
*For any* deployment with a list of stacks, storing the deployment and then retrieving it should return all stack documents with their complete data.
**Validates: Requirements 7.1, 7.2, 7.5**

### Property 14: Stack update atomicity
*For any* deployment with stacks, updating a specific stack's data should modify only that stack and leave other stacks unchanged.
**Validates: Requirements 1.4, 7.3**

### Property 15: Stack deletion from deployment
*For any* deployment with multiple stacks, deleting a specific stack should remove only that stack from the deployment record and leave other stacks intact.
**Validates: Requirements 7.4**

### Property 16: Backup and restore round-trip
*For any* database state, creating a backup, modifying the database, and then restoring from backup should return the database to its original state.
**Validates: Requirements 9.1, 9.2, 9.3**

### Property 17: Automatic backup creation
*For any* major operation (deployment, cleanup) when automatic backup is enabled, a backup file should exist after the operation completes.
**Validates: Requirements 9.4**

### Property 18: Backup retention enforcement
*For any* configured retention period, after running backup cleanup, no backup files older than the retention period should exist.
**Validates: Requirements 9.5**

### Property 19: Schema migration version update
*For any* successful schema migration, the schema version in the metadata table should be updated to the target version.
**Validates: Requirements 10.4**

### Property 20: API response format compatibility
*For any* deployment state service API call, the response format from the TinyDB implementation should match the response format from the JSON-based implementation for equivalent inputs.
**Validates: Requirements 12.1, 12.2**

### Property 21: Exception type compatibility
*For any* error condition that raises an exception, the TinyDB implementation should raise the same exception type as the JSON-based implementation.
**Validates: Requirements 12.3**

## Error Handling

### Database Initialization Errors

1. **Missing Directory**: If `backend/data/` doesn't exist, create it automatically
2. **Permission Errors**: Log clear error message with path and required permissions
3. **Corrupted Database**: Detect corruption on open, log error, attempt to restore from latest backup
4. **Schema Version Mismatch**: Run migration scripts automatically or fail with clear upgrade instructions

### Operation Errors

1. **Write Failures**: Catch IOError/OSError, log with details, raise custom DatabaseWriteError
2. **Query Failures**: Catch TinyDB exceptions, log query details, return empty results or raise
3. **Lock Timeouts**: Retry with exponential backoff (100ms, 200ms, 400ms, 800ms, 1600ms)
4. **Validation Errors**: Validate input before database operations, raise ValueError with details

### Migration Errors

1. **JSON Parse Errors**: Log file path and error, skip file, continue with others
2. **Data Validation Errors**: Log validation failures, skip invalid records, report in migration summary
3. **Partial Migration**: Track migration progress, support resume from last successful file
4. **Rollback on Failure**: If migration fails critically, restore from pre-migration backup

### Backup/Restore Errors

1. **Backup Creation Failure**: Log error, continue operation (backup is optional)
2. **Restore Validation**: Verify backup file integrity before restore
3. **Restore Failure**: Log error, keep current database intact, provide recovery instructions

## Testing Strategy

### Unit Testing

The implementation will include comprehensive unit tests using pytest:

1. **TinyDB State Manager Tests**
   - Database initialization and connection
   - Table creation and access
   - Backup and restore operations
   - Schema version management
   - Error handling for various failure scenarios

2. **Deployment State Service Tests**
   - CRUD operations on deployment state
   - Query filtering and pagination
   - Stack-level operations
   - Migration from JSON files
   - Error handling and edge cases

3. **Capability Service Tests**
   - Loading capabilities from JSON
   - Querying and filtering capabilities
   - Search functionality
   - Update operations
   - Nested field queries

4. **Migration Service Tests**
   - JSON file discovery and parsing
   - Data transformation and validation
   - Archival of migrated files
   - Error handling and partial migration
   - Migration verification

### Property-Based Testing

Property-based testing will be implemented using **Hypothesis** (Python's leading property-based testing library). Each property-based test will run a minimum of 100 iterations with randomly generated data.

**Property-based test requirements:**
- Each test must be tagged with a comment referencing the design document property
- Tag format: `# Feature: tinydb-state-management, Property {number}: {property_text}`
- Each correctness property must be implemented by a single property-based test
- Tests should use Hypothesis strategies to generate valid random data

**Example property-based test structure:**

```python
from hypothesis import given, strategies as st
import hypothesis

# Feature: tinydb-state-management, Property 1: Deployment state round-trip consistency
@given(
    capability_name=st.text(min_size=1, max_size=50),
    environment=st.sampled_from(['dev', 'test', 'stage', 'prod']),
    region=st.sampled_from(['us-east-1', 'us-west-2', 'eu-west-1']),
    stacks=st.lists(st.dictionaries(...), min_size=1, max_size=10)
)
@hypothesis.settings(max_examples=100)
def test_deployment_state_round_trip(capability_name, environment, region, stacks):
    """Property 1: Round-trip consistency for deployment state"""
    # Store deployment state
    service.save_deployment_state(capability_name, environment, region, stacks)
    
    # Load it back
    loaded = service.load_deployment_state(capability_name, environment)
    
    # Verify equivalence
    assert loaded['capability_name'] == capability_name
    assert loaded['environment'] == environment
    assert loaded['region'] == region
    assert len(loaded['stacks']) == len(stacks)
```

### Integration Testing

1. **End-to-End Deployment Flow**
   - Deploy capability → verify state in TinyDB → query state → cleanup → verify deletion

2. **Migration Integration**
   - Create JSON files → run migration → verify TinyDB data → verify archival

3. **API Compatibility**
   - Run existing integration tests against new TinyDB implementation
   - Verify all tests pass without modification

4. **Concurrent Access**
   - Simulate multiple concurrent operations
   - Verify data integrity and no corruption

### Performance Testing

1. **Query Performance**
   - Measure query times with 100, 1000, 10000 records
   - Verify indexed queries remain under 100ms

2. **Write Performance**
   - Measure write times for various data sizes
   - Verify acceptable performance for typical deployments

3. **Migration Performance**
   - Measure migration time for various numbers of JSON files
   - Verify migration completes in reasonable time

## Implementation Notes

### TinyDB Configuration

```python
from tinydb import TinyDB, Query
from tinydb.storages import JSONStorage
from tinydb.middlewares import CachingMiddleware

# Use caching middleware for better performance
db = TinyDB(
    'backend/data/state.db',
    storage=CachingMiddleware(JSONStorage),
    indent=2,
    ensure_ascii=False
)
```

### Indexing Strategy

While TinyDB doesn't have built-in indexes, we can optimize queries by:

1. Using compound keys for common queries (e.g., `{capability_id}-{environment}`)
2. Caching frequently accessed data in memory
3. Using TinyDB's query cache effectively

### Thread Safety

TinyDB is thread-safe by default when using the default JSONStorage. For additional safety:

1. Use context managers for database operations
2. Implement retry logic for lock contention
3. Consider using TinyDB's `CachingMiddleware` for better concurrency

### Backward Compatibility

To maintain backward compatibility:

1. Keep the same service interface (method signatures)
2. Return the same data structures
3. Raise the same exception types
4. Support gradual migration (JSON fallback if TinyDB fails)

### Migration Strategy

1. **Phase 1**: Implement TinyDB services alongside existing JSON services
2. **Phase 2**: Add migration logic to convert JSON to TinyDB on startup
3. **Phase 3**: Switch to TinyDB as primary storage
4. **Phase 4**: Keep JSON fallback for one release cycle
5. **Phase 5**: Remove JSON-based implementation

### Database Location

- **Development**: `backend/data/state.db`
- **Production**: Configurable via environment variable `STATE_DB_PATH`
- **Backups**: `backend/data/backups/state-{timestamp}.db`
- **Archive**: `deploy/state/archive/` for migrated JSON files

### Dependencies

Add to `backend/requirements.txt`:

```
tinydb==4.8.0
```

TinyDB has no external dependencies, making it ideal for desktop and PWA deployments.

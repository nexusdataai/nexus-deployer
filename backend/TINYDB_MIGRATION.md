# TinyDB State Management Migration Guide

## Overview

The starhub-deployer application has been migrated from file-based JSON state management to TinyDB for improved reliability, queryability, and maintainability.

## What Changed

### Before (JSON Files)
- Deployment state stored in individual JSON files: `deploy/state/{capability}-{environment}.json`
- Capabilities loaded from `backend/capabilities/capabilities.json`
- Manual file management and parsing

### After (TinyDB)
- All state stored in a single database: `backend/data/state.db`
- Automatic migration from existing JSON files
- Enhanced querying capabilities with filters and pagination
- Built-in backup and restore functionality
- Schema versioning for future upgrades

## Automatic Migration

The migration happens automatically on application startup:

1. **First Startup**: TinyDB database is created at `backend/data/state.db`
2. **Capability Loading**: If capabilities table is empty, loads from `backend/capabilities/capabilities.json`
3. **State Migration**: If JSON files exist in `deploy/state/`, they are automatically migrated
4. **Archival**: Successfully migrated JSON files are moved to `deploy/state/archive/`

## Database Structure

### Tables

- **deployments**: Deployment state records
- **capabilities**: Capabilities catalogue
- **metadata**: Schema version and system metadata

### Deployment Record Schema

```json
{
  "capability_name": "Call Processing",
  "capability_id": "call-processing",
  "environment": "prod",
  "region": "us-east-1",
  "stacks": [...],
  "metadata": {...},
  "created_at": "2025-12-14T10:30:00.000000",
  "last_deployment": "2025-12-14T10:35:00.000000"
}
```

## Database Management

### CLI Utilities

A command-line tool is provided for database management:

```bash
# Create a backup
python backend/app/cli/db_manager.py backup

# Create a named backup
python backend/app/cli/db_manager.py backup --name my-backup.db

# List available backups
python backend/app/cli/db_manager.py list-backups

# Restore from backup
python backend/app/cli/db_manager.py restore path/to/backup.db

# Verify database integrity
python backend/app/cli/db_manager.py verify

# Export data to JSON
python backend/app/cli/db_manager.py export --output-dir ./export

# Clean up old backups (default: 30 days retention)
python backend/app/cli/db_manager.py cleanup --retention-days 30
```

### Backup Strategy

- **Automatic Backups**: Created before major operations (migrations, schema updates)
- **Manual Backups**: Use CLI tool or API
- **Location**: `backend/data/backups/`
- **Retention**: Configurable (default: 30 days)

## API Compatibility

The migration maintains full API compatibility:

- All existing endpoints work unchanged
- Response formats remain the same
- Error handling is consistent
- No frontend changes required

## Troubleshooting

### Database Corruption

If the database becomes corrupted:

1. Check logs for error messages
2. Restore from latest backup:
   ```bash
   python backend/app/cli/db_manager.py list-backups
   python backend/app/cli/db_manager.py restore path/to/backup.db
   ```

### Migration Issues

If migration fails:

1. Original JSON files are preserved in `deploy/state/`
2. Check logs for specific errors
3. Fix data issues in JSON files
4. Restart application to retry migration

### Fallback to JSON

If TinyDB initialization fails, the application logs an error but continues running. You can manually fix the issue and restart.

## Performance

- **Query Performance**: Optimized for common access patterns
- **Pagination**: Supported for large result sets
- **Caching**: Built-in caching middleware for better performance
- **Thread Safety**: Automatic thread-safe operations

## Schema Versioning

Current schema version: **1.0.0**

Schema migrations are handled automatically:
1. Application checks schema version on startup
2. If mismatch detected, runs migration scripts
3. Automatic backup created before migration
4. Schema version updated after successful migration

## Development

### Testing

```bash
# Test imports
python backend/test_imports.py

# Run with TinyDB
python backend/app/main.py
```

### Using TinyDB Services

```python
from app.services.tinydb_deployment_state_service import tinydb_deployment_state_service
from app.services.tinydb_capability_service import tinydb_capability_service

# Save deployment state
tinydb_deployment_state_service.save_deployment_state(
    capability_name="My Capability",
    environment="dev",
    region="us-east-1",
    stacks=[...]
)

# Query deployments
deployments = tinydb_deployment_state_service.list_deployments(
    environment="prod",
    region="us-east-1"
)

# Get capabilities
capabilities = tinydb_capability_service.get_all_capabilities()
```

## Benefits

1. **Reliability**: Single database file, atomic operations
2. **Queryability**: Filter by capability, environment, region, date range
3. **Maintainability**: Centralized state management
4. **Backup/Restore**: Built-in functionality
5. **Schema Versioning**: Future-proof for upgrades
6. **Performance**: Optimized queries with caching
7. **No External Dependencies**: Pure Python, no database server required

## Support

For issues or questions:
1. Check application logs
2. Verify database with CLI tool
3. Review this documentation
4. Check the design document: `.kiro/specs/tinydb-state-management/design.md`

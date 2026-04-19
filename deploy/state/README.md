# Deployment State Directory

This directory stores the state of deployed capabilities to enable faster stack detection and management.

## Purpose

When a capability is deployed, the system saves information about all deployed CloudFormation stacks to a JSON file in this directory. This allows:

1. **Faster Detection**: Instead of querying all possible stack names, we can quickly check what was actually deployed
2. **Accurate Tracking**: Know exactly which stacks exist for each capability/environment combination
3. **Efficient Updates**: Quickly determine if an update or clean deployment is needed

## File Format

Files are named: `{capability-name}-{environment}.json`

Example: `call-processing-prod.json`

### File Structure

```json
{
  "capability_name": "Call Processing",
  "environment": "prod",
  "region": "us-east-1",
  "last_deployment": "2025-12-12T17:45:00.000000",
  "stacks": [
    {
      "stack_name": "call-processing-prod-frontend-global",
      "stack_type": "frontend-global",
      "region": "us-east-1",
      "deployed_at": "2025-12-12T17:45:00.000000"
    },
    {
      "stack_name": "call-processing-prod-backend-service",
      "stack_type": "backend-service",
      "region": "us-east-1",
      "deployed_at": "2025-12-12T17:45:00.000000"
    }
  ],
  "metadata": {
    "frontend_deployed": true,
    "backend_deployed": true,
    "frontend_url": "https://app.example.com",
    "backend_url": "https://api.example.com"
  }
}
```

## Lifecycle

- **Created**: After successful deployment
- **Updated**: When stacks are updated or redeployed
- **Deleted**: When capability is cleaned up (all stacks deleted)
- **Verified**: On each detection, stacks are verified to still exist in CloudFormation

## Benefits

1. **Performance**: No need to query CloudFormation for all possible stack combinations
2. **Reliability**: Know exactly what was deployed, not just what might exist
3. **History**: Track when deployments occurred
4. **Metadata**: Store additional deployment information (URLs, configuration, etc.)

## Notes

- State files are local to this installation
- If state files are lost, the system falls back to full CloudFormation scanning
- State files are automatically cleaned up when stacks are deleted
- Files are human-readable JSON for easy inspection and debugging

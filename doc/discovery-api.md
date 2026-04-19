# Discovery API Documentation

The Discovery API enables capability discovery from AWS CloudFormation stacks. It provides endpoints for managing landing zones (AWS account configurations) and discovering deployed capabilities by scanning CloudFormation stacks.

## Base URL

```
/api/discovery
```

## Table of Contents

- [Overview](#overview)
- [Authentication](#authentication)
- [Landing Zone Endpoints](#landing-zone-endpoints)
  - [Create Landing Zone](#create-landing-zone)
  - [List Landing Zones](#list-landing-zones)
  - [Get Landing Zone](#get-landing-zone)
  - [Delete Landing Zone](#delete-landing-zone)
- [Discovery Endpoints](#discovery-endpoints)
  - [Start Discovery](#start-discovery)
  - [Get Discovery Status](#get-discovery-status)
  - [Refresh Capabilities](#refresh-capabilities)
  - [List Discovered Capabilities](#list-discovered-capabilities)
- [Data Models](#data-models)
- [Error Responses](#error-responses)
- [Examples](#examples)

---

## Overview

The Discovery API solves the problem of fragmented capability visibility when multiple users deploy capabilities using separate local TinyDB instances. It scans CloudFormation stacks in AWS accounts, identifies capabilities based on the stack naming convention `{capability-name}-{environment}-{stack-type}`, and synchronizes the results with the local database.

### Key Features

- **Landing Zone Management**: Configure and manage multiple AWS accounts for discovery
- **CloudFormation Scanning**: Automatically discover capabilities from stack names
- **Status Tracking**: Monitor discovery job progress in real-time
- **Database Synchronization**: Sync discovered capabilities to local TinyDB

---

## Authentication

Discovery operations require valid AWS credentials. The API supports:

1. **AWS Session ID**: Pass an existing AWS session ID obtained through ADFS/SAML authentication
2. **Default Credentials**: If no session ID is provided, the system uses default AWS credentials

---

## Landing Zone Endpoints

### Create Landing Zone

Creates or updates a landing zone configuration. If a landing zone with the same provider and account_id exists, it will be updated instead of creating a duplicate.

**Endpoint:** `POST /api/discovery/landing-zones`

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | User-friendly name for the landing zone |
| `provider` | string | Yes | Cloud provider: `aws`, `azure`, `gcp` |
| `account_id` | string | Yes | AWS account identifier (12-digit account ID) |
| `default_region` | string | No | Default region for discovery (default: `ap-southeast-1`) |
| `account_alias` | string | No | Optional account alias |

**Response:** `LandingZoneResponse`

**Status Codes:**
- `200 OK` - Landing zone created/updated successfully
- `400 Bad Request` - Invalid provider (only AWS is currently supported)
- `500 Internal Server Error` - Failed to create landing zone

**Example Request:**

```bash
curl -X POST "http://localhost:8000/api/discovery/landing-zones" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Production Account",
    "provider": "aws",
    "account_id": "123456789012",
    "default_region": "ap-southeast-1",
    "account_alias": "prod-account"
  }'
```

**Example Response:**

```json
{
  "landing_zone_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "name": "Production Account",
  "provider": "aws",
  "account_id": "123456789012",
  "account_alias": "prod-account",
  "default_region": "ap-southeast-1",
  "created_at": "2024-01-15T10:30:00",
  "last_discovery_at": null,
  "discovery_status": "idle",
  "capabilities_count": 0
}
```

---

### List Landing Zones

Lists all configured landing zones, optionally filtered by cloud provider.

**Endpoint:** `GET /api/discovery/landing-zones`

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `provider` | string | No | Filter by cloud provider: `aws`, `azure`, `gcp` |

**Response:** `List[LandingZoneResponse]`

**Status Codes:**
- `200 OK` - Success

**Example Request:**

```bash
# List all landing zones
curl -X GET "http://localhost:8000/api/discovery/landing-zones"

# List only AWS landing zones
curl -X GET "http://localhost:8000/api/discovery/landing-zones?provider=aws"
```

**Example Response:**

```json
[
  {
    "landing_zone_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "name": "Production Account",
    "provider": "aws",
    "account_id": "123456789012",
    "account_alias": "prod-account",
    "default_region": "ap-southeast-1",
    "created_at": "2024-01-15T10:30:00",
    "last_discovery_at": "2024-01-15T11:00:00",
    "discovery_status": "completed",
    "capabilities_count": 5
  },
  {
    "landing_zone_id": "b2c3d4e5-f6a7-8901-bcde-f23456789012",
    "name": "Development Account",
    "provider": "aws",
    "account_id": "987654321098",
    "account_alias": "dev-account",
    "default_region": "us-east-1",
    "created_at": "2024-01-14T09:00:00",
    "last_discovery_at": null,
    "discovery_status": "idle",
    "capabilities_count": 0
  }
]
```

---

### Get Landing Zone

Retrieves a specific landing zone by its ID.

**Endpoint:** `GET /api/discovery/landing-zones/{landing_zone_id}`

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `landing_zone_id` | string | Yes | UUID of the landing zone |

**Response:** `LandingZoneResponse`

**Status Codes:**
- `200 OK` - Success
- `404 Not Found` - Landing zone not found

**Example Request:**

```bash
curl -X GET "http://localhost:8000/api/discovery/landing-zones/a1b2c3d4-e5f6-7890-abcd-ef1234567890"
```

---

### Delete Landing Zone

Deletes a landing zone configuration. Note: This does not delete discovered capability records.

**Endpoint:** `DELETE /api/discovery/landing-zones/{landing_zone_id}`

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `landing_zone_id` | string | Yes | UUID of the landing zone |

**Response:**

```json
{
  "message": "Landing zone deleted",
  "landing_zone_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**Status Codes:**
- `200 OK` - Landing zone deleted successfully
- `404 Not Found` - Landing zone not found

**Example Request:**

```bash
curl -X DELETE "http://localhost:8000/api/discovery/landing-zones/a1b2c3d4-e5f6-7890-abcd-ef1234567890"
```

---

## Discovery Endpoints

### Start Discovery

Starts capability discovery for a landing zone. This scans CloudFormation stacks in the AWS account and identifies capabilities based on the stack naming convention.

**Endpoint:** `POST /api/discovery/discover`

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `landing_zone_id` | string | Yes | UUID of the landing zone to discover capabilities in |
| `aws_session_id` | string | No | AWS session ID for credentials (from ADFS/SAML auth) |
| `regions` | array | No | List of AWS regions to scan (defaults to landing zone's default region) |

**Response:** `DiscoveryStatusResponse`

**Status Codes:**
- `200 OK` - Discovery job started
- `401 Unauthorized` - AWS session expired or not found
- `404 Not Found` - Landing zone not found

**Example Request:**

```bash
# Start discovery with default region
curl -X POST "http://localhost:8000/api/discovery/discover" \
  -H "Content-Type: application/json" \
  -d '{
    "landing_zone_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
  }'

# Start discovery with specific regions and AWS session
curl -X POST "http://localhost:8000/api/discovery/discover" \
  -H "Content-Type: application/json" \
  -d '{
    "landing_zone_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "aws_session_id": "session-xyz-123",
    "regions": ["ap-southeast-1", "us-east-1"]
  }'
```

**Example Response:**

```json
{
  "job_id": "abc12345",
  "landing_zone_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "pending",
  "started_at": "2024-01-15T11:00:00",
  "completed_at": null,
  "stacks_scanned": 0,
  "capabilities_found": 0,
  "errors": [],
  "progress_message": "Initializing discovery..."
}
```

---

### Get Discovery Status

Gets the current status of a discovery job.

**Endpoint:** `GET /api/discovery/discover/{job_id}/status`

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `job_id` | string | Yes | Discovery job ID (returned from start discovery) |

**Response:** `DiscoveryStatusResponse`

**Status Codes:**
- `200 OK` - Success
- `404 Not Found` - Discovery job not found

**Example Request:**

```bash
curl -X GET "http://localhost:8000/api/discovery/discover/abc12345/status"
```

**Example Response (In Progress):**

```json
{
  "job_id": "abc12345",
  "landing_zone_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "running",
  "started_at": "2024-01-15T11:00:00",
  "completed_at": null,
  "stacks_scanned": 15,
  "capabilities_found": 3,
  "errors": [],
  "progress_message": "Scanning region ap-southeast-1..."
}
```

**Example Response (Completed):**

```json
{
  "job_id": "abc12345",
  "landing_zone_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "completed",
  "started_at": "2024-01-15T11:00:00",
  "completed_at": "2024-01-15T11:02:30",
  "stacks_scanned": 45,
  "capabilities_found": 5,
  "errors": [],
  "progress_message": "Discovery complete: 5 capabilities found across 1 region(s)"
}
```

---

### Refresh Capabilities

Refreshes capabilities for a landing zone by re-running discovery. This is a convenience endpoint that starts a new discovery job.

**Endpoint:** `POST /api/discovery/refresh/{landing_zone_id}`

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `landing_zone_id` | string | Yes | UUID of the landing zone |

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `aws_session_id` | string | No | AWS session ID for credentials |

**Response:** `DiscoveryStatusResponse`

**Status Codes:**
- `200 OK` - Refresh job started
- `401 Unauthorized` - AWS session expired or not found
- `404 Not Found` - Landing zone not found

**Example Request:**

```bash
curl -X POST "http://localhost:8000/api/discovery/refresh/a1b2c3d4-e5f6-7890-abcd-ef1234567890"

# With AWS session
curl -X POST "http://localhost:8000/api/discovery/refresh/a1b2c3d4-e5f6-7890-abcd-ef1234567890?aws_session_id=session-xyz-123"
```

---

### List Discovered Capabilities

Lists all discovered capabilities, optionally filtered by landing zone or account ID.

**Endpoint:** `GET /api/discovery/capabilities`

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `landing_zone_id` | string | No | Filter by landing zone UUID |
| `account_id` | string | No | Filter by AWS account ID |

**Response:** `List[DiscoveredCapabilityResponse]`

**Status Codes:**
- `200 OK` - Success

**Example Request:**

```bash
# List all discovered capabilities
curl -X GET "http://localhost:8000/api/discovery/capabilities"

# Filter by landing zone
curl -X GET "http://localhost:8000/api/discovery/capabilities?landing_zone_id=a1b2c3d4-e5f6-7890-abcd-ef1234567890"

# Filter by account ID
curl -X GET "http://localhost:8000/api/discovery/capabilities?account_id=123456789012"
```

**Example Response:**

```json
[
  {
    "capability_name": "Call-Processing",
    "environment": "prod",
    "account_id": "123456789012",
    "primary_region": "ap-southeast-1",
    "status": "healthy",
    "stacks_count": 7,
    "missing_stacks": [],
    "discovered_at": "2024-01-15T11:02:30",
    "version": "1.2.0",
    "frontend_url": "https://d1234567890.cloudfront.net",
    "backend_url": "https://api.example.com",
    "landing_zone_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
  },
  {
    "capability_name": "Call-Processing",
    "environment": "dev",
    "account_id": "123456789012",
    "primary_region": "ap-southeast-1",
    "status": "partial",
    "stacks_count": 4,
    "missing_stacks": ["backend-domain", "frontend-regional"],
    "discovered_at": "2024-01-15T11:02:30",
    "version": null,
    "frontend_url": null,
    "backend_url": null,
    "landing_zone_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
  }
]
```

---

## Data Models

### LandingZoneResponse

| Field | Type | Description |
|-------|------|-------------|
| `landing_zone_id` | string | Unique identifier (UUID) |
| `name` | string | User-friendly name |
| `provider` | string | Cloud provider (`aws`, `azure`, `gcp`) |
| `account_id` | string | AWS account ID |
| `account_alias` | string | Optional account alias |
| `default_region` | string | Default AWS region for discovery |
| `created_at` | string | ISO 8601 timestamp of creation |
| `last_discovery_at` | string | ISO 8601 timestamp of last discovery (null if never) |
| `discovery_status` | string | Current status: `idle`, `running`, `completed`, `failed` |
| `capabilities_count` | integer | Number of discovered capabilities |

### DiscoveryStatusResponse

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | string | Unique job identifier |
| `landing_zone_id` | string | Associated landing zone UUID |
| `status` | string | Job status: `pending`, `running`, `completed`, `failed` |
| `started_at` | string | ISO 8601 timestamp when job started |
| `completed_at` | string | ISO 8601 timestamp when job completed (null if in progress) |
| `stacks_scanned` | integer | Number of CloudFormation stacks scanned |
| `capabilities_found` | integer | Number of capabilities discovered |
| `errors` | array | List of error messages encountered |
| `progress_message` | string | Human-readable progress message |

### DiscoveredCapabilityResponse

| Field | Type | Description |
|-------|------|-------------|
| `capability_name` | string | Name of the capability |
| `environment` | string | Deployment environment: `dev`, `test`, `stage`, `prod` |
| `account_id` | string | AWS account ID where capability is deployed |
| `primary_region` | string | Primary AWS region |
| `status` | string | Capability status (see below) |
| `stacks_count` | integer | Number of CloudFormation stacks |
| `missing_stacks` | array | List of expected but missing stack types |
| `discovered_at` | string | ISO 8601 timestamp of discovery |
| `version` | string | Capability version (from stack tags, may be null) |
| `frontend_url` | string | Frontend URL (from stack outputs, may be null) |
| `backend_url` | string | Backend URL (from stack outputs, may be null) |
| `landing_zone_id` | string | Associated landing zone UUID |

### Capability Status Values

| Status | Description |
|--------|-------------|
| `healthy` | All expected stacks are in `CREATE_COMPLETE` or `UPDATE_COMPLETE` state |
| `failed` | One or more stacks are in `FAILED` or `ROLLBACK` state |
| `in_progress` | One or more stacks are in an `IN_PROGRESS` state |
| `partial` | Some expected stacks are missing |
| `not_found` | Capability exists in database but not found in AWS |

### Stack Types

The discovery service recognizes the following CloudFormation stack types:

**Backend Stacks:**
- `backend-foundation`
- `backend-iam-roles`
- `backend-regional-cert`
- `backend-storage`
- `backend-network`
- `backend-service`
- `backend-domain`

**Frontend Stacks:**
- `frontend-global`
- `frontend-cognito`
- `frontend-regional`

---

## Error Responses

All error responses follow this format:

```json
{
  "detail": "Error message describing what went wrong"
}
```

### Common Error Codes

| Status Code | Description |
|-------------|-------------|
| `400 Bad Request` | Invalid request parameters (e.g., unsupported provider) |
| `401 Unauthorized` | AWS session expired or credentials invalid |
| `404 Not Found` | Resource not found (landing zone, job, etc.) |
| `500 Internal Server Error` | Server-side error |

### Provider Not Supported Error

```json
{
  "detail": "Provider 'azure' is not yet supported. Only AWS is currently available."
}
```

### AWS Session Expired Error

```json
{
  "detail": "AWS session expired or not found. Please re-authenticate."
}
```

---

## Examples

### Complete Discovery Workflow

This example demonstrates a complete workflow for discovering capabilities in an AWS account.

#### Step 1: Create a Landing Zone

```bash
curl -X POST "http://localhost:8000/api/discovery/landing-zones" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Production Account",
    "provider": "aws",
    "account_id": "123456789012",
    "default_region": "ap-southeast-1"
  }'
```

Response:
```json
{
  "landing_zone_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "name": "Production Account",
  "provider": "aws",
  "account_id": "123456789012",
  "account_alias": null,
  "default_region": "ap-southeast-1",
  "created_at": "2024-01-15T10:30:00",
  "last_discovery_at": null,
  "discovery_status": "idle",
  "capabilities_count": 0
}
```

#### Step 2: Start Discovery

```bash
curl -X POST "http://localhost:8000/api/discovery/discover" \
  -H "Content-Type: application/json" \
  -d '{
    "landing_zone_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
  }'
```

Response:
```json
{
  "job_id": "abc12345",
  "landing_zone_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "pending",
  "started_at": "2024-01-15T11:00:00",
  "completed_at": null,
  "stacks_scanned": 0,
  "capabilities_found": 0,
  "errors": [],
  "progress_message": "Initializing discovery..."
}
```

#### Step 3: Poll for Status

```bash
curl -X GET "http://localhost:8000/api/discovery/discover/abc12345/status"
```

Response (when completed):
```json
{
  "job_id": "abc12345",
  "landing_zone_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "completed",
  "started_at": "2024-01-15T11:00:00",
  "completed_at": "2024-01-15T11:02:30",
  "stacks_scanned": 45,
  "capabilities_found": 5,
  "errors": [],
  "progress_message": "Discovery complete: 5 capabilities found across 1 region(s)"
}
```

#### Step 4: List Discovered Capabilities

```bash
curl -X GET "http://localhost:8000/api/discovery/capabilities?landing_zone_id=a1b2c3d4-e5f6-7890-abcd-ef1234567890"
```

Response:
```json
[
  {
    "capability_name": "Call-Processing",
    "environment": "prod",
    "account_id": "123456789012",
    "primary_region": "ap-southeast-1",
    "status": "healthy",
    "stacks_count": 7,
    "missing_stacks": [],
    "discovered_at": "2024-01-15T11:02:30",
    "version": "1.2.0",
    "frontend_url": "https://d1234567890.cloudfront.net",
    "backend_url": "https://api.example.com",
    "landing_zone_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
  }
]
```

### Multi-Region Discovery

Discover capabilities across multiple AWS regions:

```bash
curl -X POST "http://localhost:8000/api/discovery/discover" \
  -H "Content-Type: application/json" \
  -d '{
    "landing_zone_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "regions": ["ap-southeast-1", "us-east-1", "eu-west-1"]
  }'
```

### Refresh Capabilities

Re-run discovery to get the latest state:

```bash
curl -X POST "http://localhost:8000/api/discovery/refresh/a1b2c3d4-e5f6-7890-abcd-ef1234567890"
```

---

## Stack Naming Convention

The discovery service identifies capabilities by parsing CloudFormation stack names that follow this convention:

```
{capability-name}-{environment}-{stack-type}
```

**Examples:**
- `Call-Processing-prod-backend-service`
- `Call-Processing-prod-frontend-regional`
- `Analytics-Dashboard-dev-backend-foundation`

**Components:**
- **capability-name**: The name of the capability (can contain hyphens)
- **environment**: One of `dev`, `test`, `stage`, `prod`
- **stack-type**: One of the recognized stack types (see [Stack Types](#stack-types))

Stacks that don't match this naming convention are ignored during discovery.

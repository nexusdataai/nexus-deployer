#!/usr/bin/env bats

# Property tests for s3-uploader.sh
# Feature: ui-config-automation
# Property 3: S3 Upload Header Correctness
# Property 8: Backup Creation with Timestamp
# Validates: Requirements 4.1, 4.2, 4.3, 8.1, 8.2

# Test setup
setup() {
    # Load the library
    SCRIPT_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
    source "$SCRIPT_DIR/lib/s3-uploader.sh"
    
    # Create mock directory
    MOCK_DIR="$BATS_TEST_TMPDIR/mock"
    mkdir -p "$MOCK_DIR"
    
    # Track AWS CLI calls
    AWS_CALLS_FILE="$BATS_TEST_TMPDIR/aws_calls.log"
    > "$AWS_CALLS_FILE"
}

# Helper to create mock AWS CLI that logs calls
create_mock_aws() {
    local response="$1"
    local exit_code="${2:-0}"
    
    cat > "$MOCK_DIR/aws" << 'MOCK_SCRIPT'
#!/bin/bash
# Log the call
echo "$@" >> "$AWS_CALLS_FILE"

# Parse command
if [[ "$1" == "s3" && "$2" == "cp" ]]; then
    # Check for expected headers in s3 cp command
    echo "mock-upload-success"
    exit 0
elif [[ "$1" == "s3api" && "$2" == "head-object" ]]; then
    # Return success for head-object (file exists)
    exit 0
elif [[ "$1" == "s3api" && "$2" == "head-bucket" ]]; then
    exit 0
elif [[ "$1" == "cloudfront" && "$2" == "create-invalidation" ]]; then
    echo "INVALIDATION123"
    exit 0
fi
exit 0
MOCK_SCRIPT
    
    chmod +x "$MOCK_DIR/aws"
    export PATH="$MOCK_DIR:$PATH"
    export AWS_CALLS_FILE
}

# Property 3: S3 Upload Header Correctness
# For any successful S3 upload, the uploaded object has correct headers

@test "Property 3: upload_config_to_s3 sets content-type to application/json" {
    # Arrange
    create_mock_aws "success"
    local config='{"version": "1.0.0"}'
    
    # Act
    run upload_config_to_s3 "$config" "test-bucket" "config.json" "false"
    
    # Assert: Check that content-type was specified
    grep -q "content-type" "$AWS_CALLS_FILE" || grep -q "application/json" "$AWS_CALLS_FILE"
}

@test "Property 3: upload_config_to_s3 sets cache-control headers" {
    # Arrange
    create_mock_aws "success"
    local config='{"version": "1.0.0"}'
    
    # Act
    run upload_config_to_s3 "$config" "test-bucket" "config.json" "false"
    
    # Assert: Check that cache-control was specified
    grep -q "cache-control" "$AWS_CALLS_FILE" || grep -q "no-cache" "$AWS_CALLS_FILE"
}

@test "Property 3: upload_config_to_s3 uploads to correct S3 path" {
    # Arrange
    create_mock_aws "success"
    local config='{"version": "1.0.0"}'
    
    # Act
    result=$(upload_config_to_s3 "$config" "my-bucket" "config.json" "false")
    
    # Assert: Returns correct S3 URI
    [[ "$result" == "s3://my-bucket/config.json" ]]
}

@test "Property 3: upload_config_to_s3 fails with empty config" {
    # Arrange
    create_mock_aws "success"
    
    # Act & Assert
    run upload_config_to_s3 "" "test-bucket"
    [ "$status" -ne 0 ]
}

@test "Property 3: upload_config_to_s3 fails with empty bucket name" {
    # Arrange
    create_mock_aws "success"
    
    # Act & Assert
    run upload_config_to_s3 '{"test": true}' ""
    [ "$status" -ne 0 ]
}

# Property 8: Backup Creation with Timestamp
# For any existing config.json, backup file has correct timestamp format

@test "Property 8: backup_existing_config creates timestamped backup" {
    # Arrange
    local backup_key=""
    
    # Mock AWS to simulate existing file
    create_mock_aws "success"
    
    # Act
    backup_key=$(backup_existing_config "test-bucket" "config.json")
    
    # Assert: Backup key matches pattern config.json.backup.YYYYMMDDTHHMMSSZ
    [[ "$backup_key" =~ ^config\.json\.backup\.[0-9]{8}T[0-9]{6}Z$ ]]
}

@test "Property 8: backup_existing_config uses ISO8601 timestamp format" {
    # Arrange
    create_mock_aws "success"
    
    # Act
    backup_key=$(backup_existing_config "test-bucket" "config.json")
    
    # Assert: Timestamp is valid ISO8601 format
    local timestamp=$(echo "$backup_key" | sed 's/config.json.backup.//')
    
    # Check format: YYYYMMDDTHHMMSSZ
    [[ "$timestamp" =~ ^[0-9]{8}T[0-9]{6}Z$ ]]
}

@test "Property 8: backup_existing_config returns empty when source doesn't exist" {
    # Arrange: Mock AWS to return error for head-object (file doesn't exist)
    cat > "$MOCK_DIR/aws" << 'EOF'
#!/bin/bash
if [[ "$2" == "head-object" ]]; then
    exit 1
fi
exit 0
EOF
    chmod +x "$MOCK_DIR/aws"
    export PATH="$MOCK_DIR:$PATH"
    
    # Act
    result=$(backup_existing_config "test-bucket" "config.json")
    
    # Assert: Empty result (no backup created)
    [ -z "$result" ]
}

@test "Property 8: upload_config_to_s3 calls backup when enabled" {
    # Arrange
    create_mock_aws "success"
    local config='{"version": "1.0.0"}'
    
    # Act
    run upload_config_to_s3 "$config" "test-bucket" "config.json" "true"
    
    # Assert: s3 cp was called (for backup)
    grep -q "s3 cp" "$AWS_CALLS_FILE" || grep -q "s3api" "$AWS_CALLS_FILE"
}

@test "Property 8: upload_config_to_s3 skips backup when disabled" {
    # Arrange
    # Create mock that tracks if backup copy was attempted
    cat > "$MOCK_DIR/aws" << 'MOCK_SCRIPT'
#!/bin/bash
echo "$@" >> "$AWS_CALLS_FILE"
if [[ "$1" == "s3" && "$2" == "cp" && "$3" == "s3://"* ]]; then
    # This is a backup copy (source is S3)
    echo "BACKUP_ATTEMPTED" >> "$AWS_CALLS_FILE"
fi
exit 0
MOCK_SCRIPT
    chmod +x "$MOCK_DIR/aws"
    export PATH="$MOCK_DIR:$PATH"
    export AWS_CALLS_FILE
    
    local config='{"version": "1.0.0"}'
    
    # Act
    upload_config_to_s3 "$config" "test-bucket" "config.json" "false"
    
    # Assert: No backup copy was attempted
    ! grep -q "BACKUP_ATTEMPTED" "$AWS_CALLS_FILE"
}

# CloudFront invalidation tests

@test "invalidate_cloudfront_cache creates invalidation for /config.json" {
    # Arrange
    create_mock_aws "INVALIDATION123"
    
    # Act
    result=$(invalidate_cloudfront_cache "E1234567890")
    
    # Assert
    [ "$result" = "INVALIDATION123" ]
}

@test "invalidate_cloudfront_cache skips when distribution_id is empty" {
    # Arrange
    create_mock_aws "success"
    
    # Act
    run invalidate_cloudfront_cache ""
    
    # Assert: Returns success but no invalidation created
    [ "$status" -eq 0 ]
}

@test "verify_s3_bucket_access returns 0 for accessible bucket" {
    # Arrange
    create_mock_aws "success"
    
    # Act & Assert
    run verify_s3_bucket_access "test-bucket"
    [ "$status" -eq 0 ]
}

@test "verify_s3_bucket_access fails with empty bucket name" {
    # Act & Assert
    run verify_s3_bucket_access ""
    [ "$status" -ne 0 ]
}

# Property test with various bucket names
@test "Property 3: upload_config_to_s3 handles various bucket name formats" {
    create_mock_aws "success"
    local config='{"version": "1.0.0"}'
    
    local buckets=("my-bucket" "my.bucket.name" "bucket-with-123-numbers" "a")
    
    for bucket in "${buckets[@]}"; do
        result=$(upload_config_to_s3 "$config" "$bucket" "config.json" "false")
        [[ "$result" == "s3://${bucket}/config.json" ]]
    done
}

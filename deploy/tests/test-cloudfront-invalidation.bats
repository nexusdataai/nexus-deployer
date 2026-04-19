#!/usr/bin/env bats

# Property tests for CloudFront invalidation
# Feature: ui-config-automation
# Property 6: CloudFront Invalidation Path Correctness
# Validates: Requirements 6.1, 6.2

# Test setup
setup() {
    SCRIPT_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
    source "$SCRIPT_DIR/lib/s3-uploader.sh"
    
    # Create mock directory
    MOCK_DIR="$BATS_TEST_TMPDIR/mock"
    mkdir -p "$MOCK_DIR"
    
    # Track AWS CLI calls
    AWS_CALLS_FILE="$BATS_TEST_TMPDIR/aws_calls.log"
    > "$AWS_CALLS_FILE"
}

# Create mock AWS CLI that captures invalidation calls
create_mock_aws() {
    cat > "$MOCK_DIR/aws" << 'MOCK_SCRIPT'
#!/bin/bash
# Log the full command
echo "$@" >> "$AWS_CALLS_FILE"

if [[ "$1" == "cloudfront" && "$2" == "create-invalidation" ]]; then
    # Extract and log the paths argument
    for i in "${!@}"; do
        if [[ "${!i}" == "--paths" ]]; then
            next=$((i + 1))
            echo "INVALIDATION_PATH: ${!next}" >> "$AWS_CALLS_FILE"
        fi
    done
    echo "INVALIDATION_ID_123"
    exit 0
fi
exit 0
MOCK_SCRIPT
    
    chmod +x "$MOCK_DIR/aws"
    export PATH="$MOCK_DIR:$PATH"
    export AWS_CALLS_FILE
}

# Property 6: CloudFront Invalidation Path Correctness
# For any successful config.json upload with valid distribution ID,
# the invalidation request targets exactly /config.json

@test "Property 6: invalidate_cloudfront_cache targets /config.json path" {
    # Arrange
    create_mock_aws
    
    # Act
    invalidate_cloudfront_cache "E1234567890" "/config.json"
    
    # Assert: The invalidation was called with /config.json path
    grep -q "INVALIDATION_PATH: /config.json" "$AWS_CALLS_FILE"
}

@test "Property 6: invalidate_cloudfront_cache uses correct distribution ID" {
    # Arrange
    create_mock_aws
    local distribution_id="EDISTRIBUTION123"
    
    # Act
    invalidate_cloudfront_cache "$distribution_id" "/config.json"
    
    # Assert: The distribution ID was passed correctly
    grep -q "$distribution_id" "$AWS_CALLS_FILE"
}

@test "Property 6: invalidate_cloudfront_cache returns invalidation ID" {
    # Arrange
    create_mock_aws
    
    # Act
    result=$(invalidate_cloudfront_cache "E1234567890" "/config.json")
    
    # Assert: Returns the invalidation ID
    [[ "$result" == "INVALIDATION_ID_123" ]]
}

@test "Property 6: invalidate_cloudfront_cache skips when distribution ID is empty" {
    # Arrange
    create_mock_aws
    > "$AWS_CALLS_FILE"
    
    # Act
    result=$(invalidate_cloudfront_cache "" "/config.json" 2>&1) || true
    
    # Assert: No AWS CLI call was made
    [[ ! -s "$AWS_CALLS_FILE" ]] || ! grep -q "cloudfront" "$AWS_CALLS_FILE"
}

@test "Property 6: invalidate_cloudfront_cache handles None distribution ID" {
    # Arrange
    create_mock_aws
    > "$AWS_CALLS_FILE"
    
    # Act
    result=$(invalidate_cloudfront_cache "None" "/config.json" 2>&1) || true
    
    # Assert: No AWS CLI call was made for "None" value
    [[ ! -s "$AWS_CALLS_FILE" ]] || ! grep -q "cloudfront" "$AWS_CALLS_FILE"
}

# Property-based test: For any valid distribution ID format, path is always /config.json
@test "Property 6: multiple distribution IDs all invalidate /config.json" {
    # Arrange
    create_mock_aws
    
    # Test with various valid distribution ID formats
    local dist_ids=("E1234567890ABC" "EDISTRIBUTION1" "E9876543210XYZ")
    
    for dist_id in "${dist_ids[@]}"; do
        > "$AWS_CALLS_FILE"
        
        # Act
        invalidate_cloudfront_cache "$dist_id" "/config.json"
        
        # Assert: Each call targets /config.json
        grep -q "INVALIDATION_PATH: /config.json" "$AWS_CALLS_FILE"
    done
}

@test "Property 6: invalidation uses cloudfront create-invalidation command" {
    # Arrange
    create_mock_aws
    
    # Act
    invalidate_cloudfront_cache "E1234567890" "/config.json"
    
    # Assert: Uses correct AWS CLI command
    grep -q "cloudfront create-invalidation" "$AWS_CALLS_FILE"
}
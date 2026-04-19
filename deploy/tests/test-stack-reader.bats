#!/usr/bin/env bats

# Property tests for stack-reader.sh
# Feature: ui-config-automation, Property 1: Stack Output Extraction Completeness
# Validates: Requirements 1.1, 1.2, 2.1, 2.2

# Test setup
setup() {
    # Load the library
    SCRIPT_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
    source "$SCRIPT_DIR/lib/stack-reader.sh"
    
    # Create mock AWS CLI responses directory
    MOCK_DIR="$BATS_TEST_TMPDIR/mock"
    mkdir -p "$MOCK_DIR"
}

# Helper to create mock AWS CLI
create_mock_aws() {
    local response="$1"
    local exit_code="${2:-0}"
    
    cat > "$MOCK_DIR/aws" << EOF
#!/bin/bash
if [ "$exit_code" -ne 0 ]; then
    echo "$response" >&2
    exit $exit_code
fi
echo '$response'
EOF
    chmod +x "$MOCK_DIR/aws"
    export PATH="$MOCK_DIR:$PATH"
}

# Property 1: Stack Output Extraction Completeness
# For any valid CloudFormation stack with expected outputs, all required values are extracted

@test "Property 1: get_api_config extracts API URL from ApiEndpoint output" {
    # Arrange: Mock stack with ApiEndpoint output
    create_mock_aws '["CREATE_COMPLETE", [{"OutputKey": "ApiEndpoint", "OutputValue": "https://api.example.com"}]]'
    
    # Act
    result=$(get_api_config "test-stack" "us-east-1")
    
    # Assert
    [ "$result" = "https://api.example.com" ]
}

@test "Property 1: get_api_config adds https prefix if missing" {
    # Arrange: Mock stack with URL without protocol
    create_mock_aws 'api.example.com'
    
    # Override get_stack_output to return URL without protocol
    get_stack_output() {
        echo "api.example.com"
    }
    
    # Act
    result=$(get_api_config "test-stack" "us-east-1")
    
    # Assert
    [[ "$result" == "https://api.example.com" ]]
}

@test "Property 1: get_cognito_config extracts all required Cognito values" {
    # Arrange: Mock get_stack_output to return valid values
    get_stack_output() {
        local stack_name="$1"
        local region="$2"
        local key="$3"
        
        case "$key" in
            "UserPoolId") echo "us-east-1_ABC123" ;;
            "UserPoolClientId") echo "client123456" ;;
            "UserPoolDomain") echo "auth.example.com" ;;
            *) return 3 ;;
        esac
    }
    
    # Act
    result=$(get_cognito_config "test-cognito-stack" "us-east-1")
    
    # Assert: All required fields are present
    echo "$result" | grep -q "user_pool_id=us-east-1_ABC123"
    echo "$result" | grep -q "client_id=client123456"
    echo "$result" | grep -q "cognito_domain=auth.example.com"
    echo "$result" | grep -q "region=us-east-1"
}

@test "Property 1: get_frontend_config extracts S3 bucket and domain" {
    # Arrange: Mock get_stack_output to return valid values
    get_stack_output() {
        local stack_name="$1"
        local region="$2"
        local key="$3"
        
        case "$key" in
            "S3BucketName") echo "my-frontend-bucket" ;;
            "FrontendDomainName") echo "app.example.com" ;;
            "CloudFrontDistributionId") echo "E1234567890" ;;
            *) return 3 ;;
        esac
    }
    
    # Act
    result=$(get_frontend_config "test-frontend-stack" "us-east-1")
    
    # Assert: All required fields are present
    echo "$result" | grep -q "s3_bucket=my-frontend-bucket"
    echo "$result" | grep -q "frontend_domain=app.example.com"
    echo "$result" | grep -q "cloudfront_distribution_id=E1234567890"
}

@test "Property 1: get_cognito_config fails when UserPoolId is missing" {
    # Arrange: Mock get_stack_output to return empty for UserPoolId
    get_stack_output() {
        local key="$3"
        case "$key" in
            "UserPoolId") return 3 ;;
            "UserPoolClientId") echo "client123456" ;;
            "UserPoolDomain") echo "auth.example.com" ;;
            *) return 3 ;;
        esac
    }
    
    # Act & Assert
    run get_cognito_config "test-cognito-stack" "us-east-1"
    [ "$status" -eq 3 ]
    [[ "$output" == *"UserPoolId"* ]]
}

@test "Property 1: check_stack_status returns 0 for CREATE_COMPLETE" {
    # Arrange
    create_mock_aws 'CREATE_COMPLETE'
    
    # Act & Assert
    run check_stack_status "test-stack" "us-east-1"
    [ "$status" -eq 0 ]
}

@test "Property 1: check_stack_status returns error for IN_PROGRESS state" {
    # Arrange
    create_mock_aws 'CREATE_IN_PROGRESS'
    
    # Act & Assert
    run check_stack_status "test-stack" "us-east-1"
    [ "$status" -ne 0 ]
}

# Property test with random inputs
@test "Property 1: Stack output extraction handles various region formats" {
    # Test with different region formats
    local regions=("us-east-1" "ap-southeast-1" "eu-west-2" "sa-east-1")
    
    for region in "${regions[@]}"; do
        get_stack_output() {
            local r="$2"
            case "$3" in
                "UserPoolId") echo "${r}_ABC123" ;;
                "UserPoolClientId") echo "client_${r}" ;;
                "UserPoolDomain") echo "auth.${r}.example.com" ;;
                *) return 3 ;;
            esac
        }
        
        result=$(get_cognito_config "test-stack" "$region")
        echo "$result" | grep -q "region=$region"
    done
}

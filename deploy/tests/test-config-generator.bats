#!/usr/bin/env bats

# Property tests for config-generator.sh
# Feature: ui-config-automation
# Property 2: Config Generation Schema Validity
# Property 4: Stack Name Derivation Consistency
# Validates: Requirements 3.1, 3.2, 3.3, 5.3

# Test setup
setup() {
    # Load the library
    SCRIPT_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
    source "$SCRIPT_DIR/lib/config-generator.sh"
}

# Property 2: Config Generation Schema Validity
# For any valid set of extracted stack outputs, the generated config.json:
# - Is syntactically valid JSON
# - Contains all required fields
# - Has correctly formatted redirect URIs

@test "Property 2: build_config_json produces valid JSON" {
    # Arrange
    local api_url="https://api.example.com"
    local user_pool_id="us-east-1_ABC123"
    local client_id="client123456"
    local cognito_domain="auth.example.com"
    local region="us-east-1"
    local frontend_domain="https://app.example.com"
    
    # Act
    result=$(build_config_json "$api_url" "$user_pool_id" "$client_id" "$cognito_domain" "$region" "$frontend_domain")
    
    # Assert: JSON is valid
    echo "$result" | jq . >/dev/null 2>&1
    [ $? -eq 0 ]
}

@test "Property 2: build_config_json contains all required fields" {
    # Arrange
    local api_url="https://api.example.com"
    local user_pool_id="us-east-1_ABC123"
    local client_id="client123456"
    local cognito_domain="auth.example.com"
    local region="us-east-1"
    local frontend_domain="https://app.example.com"
    
    # Act
    result=$(build_config_json "$api_url" "$user_pool_id" "$client_id" "$cognito_domain" "$region" "$frontend_domain")
    
    # Assert: All required fields are present
    [ "$(echo "$result" | jq -r '.api.baseUrl')" = "$api_url" ]
    [ "$(echo "$result" | jq -r '.cognito.userPoolId')" = "$user_pool_id" ]
    [ "$(echo "$result" | jq -r '.cognito.clientId')" = "$client_id" ]
    [ "$(echo "$result" | jq -r '.cognito.domain')" = "$cognito_domain" ]
    [ "$(echo "$result" | jq -r '.cognito.region')" = "$region" ]
}

@test "Property 2: build_config_json generates correct redirect URIs" {
    # Arrange
    local frontend_domain="https://app.example.com"
    
    # Act
    result=$(build_config_json "https://api.example.com" "pool123" "client123" "auth.example.com" "us-east-1" "$frontend_domain")
    
    # Assert: Redirect URIs are correctly formatted
    [ "$(echo "$result" | jq -r '.cognito.redirectSignIn')" = "https://app.example.com/auth/callback" ]
    [ "$(echo "$result" | jq -r '.cognito.redirectSignOut')" = "https://app.example.com" ]
}

@test "Property 2: build_redirect_uris adds https prefix if missing" {
    # Arrange
    local domain="app.example.com"
    
    # Act
    result=$(build_redirect_uris "$domain")
    
    # Assert
    echo "$result" | grep -q "redirect_sign_in=https://app.example.com/auth/callback"
    echo "$result" | grep -q "redirect_sign_out=https://app.example.com"
}

@test "Property 2: build_redirect_uris removes trailing slash" {
    # Arrange
    local domain="https://app.example.com/"
    
    # Act
    result=$(build_redirect_uris "$domain")
    
    # Assert: No double slashes
    echo "$result" | grep -q "redirect_sign_in=https://app.example.com/auth/callback"
    ! echo "$result" | grep -q "https://app.example.com//auth/callback"
}

@test "Property 2: validate_config_json accepts valid JSON" {
    # Arrange
    local valid_json='{"version": "1.0.0", "api": {"baseUrl": "https://api.example.com"}}'
    
    # Act & Assert
    run validate_config_json "$valid_json"
    [ "$status" -eq 0 ]
}

@test "Property 2: validate_config_json rejects invalid JSON" {
    # Arrange
    local invalid_json='{"version": "1.0.0", "api": {"baseUrl": }'
    
    # Act & Assert
    run validate_config_json "$invalid_json"
    [ "$status" -ne 0 ]
}

@test "Property 2: validate_config_schema checks all required fields" {
    # Arrange: Complete valid config
    local valid_config=$(build_config_json "https://api.example.com" "pool123" "client123" "auth.example.com" "us-east-1" "https://app.example.com")
    
    # Act & Assert
    run validate_config_schema "$valid_config"
    [ "$status" -eq 0 ]
}

@test "Property 2: validate_config_schema fails when cognito.userPoolId is missing" {
    # Arrange: Config missing userPoolId
    local incomplete_config='{"api": {"baseUrl": "https://api.example.com"}, "cognito": {"clientId": "123", "domain": "auth.example.com", "region": "us-east-1", "redirectSignIn": "https://app.example.com/auth/callback", "redirectSignOut": "https://app.example.com"}}'
    
    # Act & Assert
    run validate_config_schema "$incomplete_config"
    [ "$status" -ne 0 ]
    [[ "$output" == *"userPoolId"* ]]
}

# Property 4: Stack Name Derivation Consistency
# For any capability name and environment, derived stack names follow the pattern

@test "Property 4: derive_stack_names follows naming convention" {
    # Arrange
    local capability="my-app"
    local environment="prod"
    
    # Act
    result=$(derive_stack_names "$capability" "$environment")
    
    # Assert: All stack names follow pattern {capability}-{environment}-{type}
    echo "$result" | grep -q "api_stack=my-app-prod-backend-service"
    echo "$result" | grep -q "cognito_stack=my-app-prod-frontend-cognito"
    echo "$result" | grep -q "frontend_stack=my-app-prod-frontend-global"
}

@test "Property 4: derive_stack_names works with different environments" {
    # Test with multiple environments
    local environments=("dev" "stage" "prod")
    local capability="test-app"
    
    for env in "${environments[@]}"; do
        result=$(derive_stack_names "$capability" "$env")
        
        # Assert: Pattern is consistent
        echo "$result" | grep -q "api_stack=test-app-${env}-backend-service"
        echo "$result" | grep -q "cognito_stack=test-app-${env}-frontend-cognito"
        echo "$result" | grep -q "frontend_stack=test-app-${env}-frontend-global"
    done
}

@test "Property 4: derive_stack_names handles hyphenated capability names" {
    # Arrange
    local capability="my-complex-app-name"
    local environment="dev"
    
    # Act
    result=$(derive_stack_names "$capability" "$environment")
    
    # Assert
    echo "$result" | grep -q "api_stack=my-complex-app-name-dev-backend-service"
}

@test "Property 4: derive_stack_names fails with empty capability name" {
    # Act & Assert
    run derive_stack_names "" "prod"
    [ "$status" -ne 0 ]
}

@test "Property 4: derive_stack_names fails with empty environment" {
    # Act & Assert
    run derive_stack_names "my-app" ""
    [ "$status" -ne 0 ]
}

# Property test with random-like inputs
@test "Property 2: build_config_json handles various API URL formats" {
    local urls=("https://api.example.com" "https://api.example.com/v1" "https://api-gateway.execute-api.us-east-1.amazonaws.com/prod")
    
    for url in "${urls[@]}"; do
        result=$(build_config_json "$url" "pool123" "client123" "auth.example.com" "us-east-1" "https://app.example.com")
        
        # Assert: URL is preserved exactly
        [ "$(echo "$result" | jq -r '.api.baseUrl')" = "$url" ]
        
        # Assert: JSON is still valid
        echo "$result" | jq . >/dev/null 2>&1
        [ $? -eq 0 ]
    done
}

@test "Property 2: build_config_json uses default values when optional params not provided" {
    # Act
    result=$(build_config_json "https://api.example.com" "pool123" "client123" "auth.example.com" "us-east-1" "https://app.example.com")
    
    # Assert: Default values are used
    [ "$(echo "$result" | jq -r '.api.timeout')" = "30000" ]
    [ "$(echo "$result" | jq -r '.dataSource')" = "api" ]
    [ "$(echo "$result" | jq -r '.enableFallback')" = "true" ]
    [ "$(echo "$result" | jq -r '.version')" = "1.0.0" ]
}

@test "Property 2: build_config_json accepts custom optional values" {
    # Act
    result=$(build_config_json "https://api.example.com" "pool123" "client123" "auth.example.com" "us-east-1" "https://app.example.com" "60000" "mock" "false" "2.0.0" "my-api-key")
    
    # Assert: Custom values are used
    [ "$(echo "$result" | jq -r '.api.timeout')" = "60000" ]
    [ "$(echo "$result" | jq -r '.dataSource')" = "mock" ]
    [ "$(echo "$result" | jq -r '.enableFallback')" = "false" ]
    [ "$(echo "$result" | jq -r '.version')" = "2.0.0" ]
    [ "$(echo "$result" | jq -r '.gateway.apiKey')" = "my-api-key" ]
}

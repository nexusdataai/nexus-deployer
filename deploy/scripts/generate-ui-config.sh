#!/bin/bash

# UI Config Generator Script
# Generates and uploads config.json for the UI application
# Part of UI Config Automation feature

set -e  # Exit on error
set -o pipefail  # Pipe failures propagate

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="$(dirname "$SCRIPT_DIR")/lib"

# Load libraries
source "${LIB_DIR}/stack-reader.sh"
source "${LIB_DIR}/config-generator.sh"
source "${LIB_DIR}/s3-uploader.sh"

# Load colors if available
source "${LIB_DIR}/colors.sh" 2>/dev/null || true

# Exit codes
EXIT_SUCCESS=0
EXIT_GENERAL_ERROR=1
EXIT_STACK_NOT_FOUND=2
EXIT_MISSING_OUTPUT=3
EXIT_S3_ERROR=4
EXIT_INVALID_CONFIG=5

# Default values
CAPABILITY_NAME=""
ENVIRONMENT=""
REGION=""
API_STACK_NAME=""
COGNITO_STACK_NAME=""
FRONTEND_STACK_NAME=""
FRONTEND_REGIONAL_STACK_NAME=""
S3_BUCKET=""
CONFIG_FILE=""
DRY_RUN="false"
NO_BACKUP="false"
SKIP_INVALIDATION="false"
API_TIMEOUT="30000"
ENABLE_FALLBACK="true"
DATA_SOURCE="api"
GATEWAY_API_KEY=""
VERBOSE="false"

# Colors for output (fallback)
if [ -z "$RED" ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m'
fi

# Logging functions
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_dry_run() {
    echo -e "${YELLOW}[DRY-RUN]${NC} $1"
}

# Usage function
usage() {
    cat << EOF
Usage: $(basename "$0") [OPTIONS]

Generates and uploads config.json for the UI application from CloudFormation stack outputs.

OPTIONS:
  -c, --config FILE           YAML configuration file
  -n, --capability-name NAME  Capability name (used to derive stack names)
  -e, --environment ENV       Environment (dev|stage|prod)
  -r, --region REGION         AWS region
  --api-stack NAME            API/backend service stack name (overrides derived name)
  --cognito-stack NAME        Cognito stack name (overrides derived name)
  --frontend-stack NAME       Frontend global stack name (overrides derived name)
  --s3-bucket NAME            S3 bucket for config.json (overrides stack output)
  --api-timeout MS            API timeout in milliseconds (default: 30000)
  --data-source TYPE          Data source type (default: api)
  --enable-fallback BOOL      Enable fallback mode (default: true)
  --gateway-api-key KEY       Gateway API key (optional)
  --dry-run                   Generate config but don't upload
  --no-backup                 Don't backup existing config.json
  --skip-invalidation         Skip CloudFront cache invalidation
  --verbose                   Verbose output
  -h, --help                  Display this help message

EXAMPLES:
  # Using capability name and environment (derives stack names)
  $(basename "$0") -n my-app -e prod -r us-east-1

  # Using explicit stack names
  $(basename "$0") -r us-east-1 \\
    --api-stack my-app-prod-backend-service \\
    --cognito-stack my-app-prod-frontend-cognito \\
    --frontend-stack my-app-prod-frontend-global

  # Using configuration file
  $(basename "$0") -c config/ui-config.yaml

  # Dry run mode
  $(basename "$0") -n my-app -e prod -r us-east-1 --dry-run

EOF
}

# Parse command line arguments
parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -c|--config)
                CONFIG_FILE="$2"
                shift 2
                ;;
            -n|--capability-name)
                CAPABILITY_NAME="$2"
                shift 2
                ;;
            -e|--environment)
                ENVIRONMENT="$2"
                shift 2
                ;;
            -r|--region)
                REGION="$2"
                shift 2
                ;;
            --api-stack)
                API_STACK_NAME="$2"
                shift 2
                ;;
            --cognito-stack)
                COGNITO_STACK_NAME="$2"
                shift 2
                ;;
            --frontend-stack)
                FRONTEND_STACK_NAME="$2"
                shift 2
                ;;
            --frontend-regional-stack)
                FRONTEND_REGIONAL_STACK_NAME="$2"
                shift 2
                ;;
            --s3-bucket)
                S3_BUCKET="$2"
                shift 2
                ;;
            --api-timeout)
                API_TIMEOUT="$2"
                shift 2
                ;;
            --data-source)
                DATA_SOURCE="$2"
                shift 2
                ;;
            --enable-fallback)
                ENABLE_FALLBACK="$2"
                shift 2
                ;;
            --gateway-api-key)
                GATEWAY_API_KEY="$2"
                shift 2
                ;;
            --dry-run)
                DRY_RUN="true"
                shift
                ;;
            --no-backup)
                NO_BACKUP="true"
                shift
                ;;
            --skip-invalidation)
                SKIP_INVALIDATION="true"
                shift
                ;;
            --verbose)
                VERBOSE="true"
                set -x
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                usage
                exit $EXIT_INVALID_CONFIG
                ;;
        esac
    done
}


# Load configuration from YAML file if provided
load_configuration() {
    if [ -n "$CONFIG_FILE" ]; then
        if [ ! -f "$CONFIG_FILE" ]; then
            print_error "Configuration file not found: $CONFIG_FILE"
            exit $EXIT_INVALID_CONFIG
        fi
        
        print_status "Loading configuration from: $CONFIG_FILE"
        
        # Load YAML config and export variables
        eval "$(load_yaml_config "$CONFIG_FILE")"
        
        print_success "Configuration loaded"
    fi
}

# Derive stack names if not explicitly provided
derive_stack_names_if_needed() {
    if [ -n "$CAPABILITY_NAME" ] && [ -n "$ENVIRONMENT" ]; then
        local derived
        derived=$(derive_stack_names "$CAPABILITY_NAME" "$ENVIRONMENT")
        
        # Only use derived names if not explicitly provided
        if [ -z "$API_STACK_NAME" ]; then
            API_STACK_NAME=$(echo "$derived" | grep "api_stack=" | cut -d'=' -f2)
        fi
        if [ -z "$COGNITO_STACK_NAME" ]; then
            COGNITO_STACK_NAME=$(echo "$derived" | grep "cognito_stack=" | cut -d'=' -f2)
        fi
        if [ -z "$FRONTEND_STACK_NAME" ]; then
            FRONTEND_STACK_NAME=$(echo "$derived" | grep "frontend_stack=" | cut -d'=' -f2)
        fi
        if [ -z "$FRONTEND_REGIONAL_STACK_NAME" ]; then
            FRONTEND_REGIONAL_STACK_NAME=$(echo "$derived" | grep "frontend_regional_stack=" | cut -d'=' -f2)
        fi
    fi
}

# Validate required parameters
validate_parameters() {
    local errors=()
    
    if [ -z "$REGION" ]; then
        errors+=("region")
    fi
    
    # Need either explicit stack names or capability+environment to derive them
    if [ -z "$API_STACK_NAME" ] && ([ -z "$CAPABILITY_NAME" ] || [ -z "$ENVIRONMENT" ]); then
        errors+=("api-stack or (capability-name + environment)")
    fi
    
    if [ -z "$COGNITO_STACK_NAME" ] && ([ -z "$CAPABILITY_NAME" ] || [ -z "$ENVIRONMENT" ]); then
        errors+=("cognito-stack or (capability-name + environment)")
    fi
    
    if [ -z "$FRONTEND_STACK_NAME" ] && ([ -z "$CAPABILITY_NAME" ] || [ -z "$ENVIRONMENT" ]); then
        errors+=("frontend-stack or (capability-name + environment)")
    fi
    
    if [ ${#errors[@]} -gt 0 ]; then
        print_error "Missing required parameters: ${errors[*]}"
        usage
        exit $EXIT_INVALID_CONFIG
    fi
}

# Main workflow
main() {
    if [ "$DRY_RUN" = "true" ]; then
        print_dry_run "Running in dry-run mode - no changes will be made"
    fi
    
    print_status "=== UI Config Generator ==="
    
    # Step 1: Derive stack names if needed
    derive_stack_names_if_needed
    
    print_status "Stack names:"
    print_status "  API Stack: $API_STACK_NAME"
    print_status "  Cognito Stack: $COGNITO_STACK_NAME"
    print_status "  Frontend Stack: $FRONTEND_STACK_NAME"
    if [ -n "$FRONTEND_REGIONAL_STACK_NAME" ]; then
        print_status "  Frontend Regional Stack: $FRONTEND_REGIONAL_STACK_NAME"
    fi
    
    # Step 2: Validate stack accessibility (in dry-run mode too)
    print_status "Validating stack accessibility..."
    
    if ! check_stack_status "$API_STACK_NAME" "$REGION"; then
        print_error "API stack not accessible"
        exit $EXIT_STACK_NOT_FOUND
    fi
    
    if ! check_stack_status "$COGNITO_STACK_NAME" "$REGION"; then
        print_error "Cognito stack not accessible"
        exit $EXIT_STACK_NOT_FOUND
    fi
    
    # Frontend global stack is usually in us-east-1
    local frontend_region="us-east-1"
    if ! check_stack_status "$FRONTEND_STACK_NAME" "$frontend_region"; then
        # Try the specified region as fallback
        frontend_region="$REGION"
        if ! check_stack_status "$FRONTEND_STACK_NAME" "$frontend_region"; then
            print_error "Frontend stack not accessible"
            exit $EXIT_STACK_NOT_FOUND
        fi
    fi
    
    print_success "All stacks accessible"
    
    # Step 3: Extract configuration from stacks
    print_status "Extracting configuration from stacks..."
    
    # Get API URL
    local api_url
    api_url=$(get_api_config "$API_STACK_NAME" "$REGION")
    if [ -z "$api_url" ]; then
        print_error "Failed to get API URL from stack"
        exit $EXIT_MISSING_OUTPUT
    fi
    print_status "  API URL: $api_url"
    
    # Get Cognito config
    local cognito_config
    cognito_config=$(get_cognito_config "$COGNITO_STACK_NAME" "$REGION")
    if [ -z "$cognito_config" ]; then
        print_error "Failed to get Cognito config from stack"
        exit $EXIT_MISSING_OUTPUT
    fi
    
    local user_pool_id=$(echo "$cognito_config" | grep "user_pool_id=" | cut -d'=' -f2)
    local client_id=$(echo "$cognito_config" | grep "client_id=" | cut -d'=' -f2)
    local cognito_domain=$(echo "$cognito_config" | grep "cognito_domain=" | cut -d'=' -f2)
    
    print_status "  User Pool ID: $user_pool_id"
    print_status "  Client ID: $client_id"
    print_status "  Cognito Domain: $cognito_domain"
    
    # Get frontend config - pass regional stack info for S3 bucket and CloudFront
    local frontend_config
    frontend_config=$(get_frontend_config "$FRONTEND_STACK_NAME" "$frontend_region" "$FRONTEND_REGIONAL_STACK_NAME" "$REGION")
    if [ -z "$frontend_config" ]; then
        print_error "Failed to get frontend config from stack"
        exit $EXIT_MISSING_OUTPUT
    fi
    
    local frontend_domain=$(echo "$frontend_config" | grep "frontend_domain=" | cut -d'=' -f2)
    local cloudfront_distribution_id=$(echo "$frontend_config" | grep "cloudfront_distribution_id=" | cut -d'=' -f2)
    
    # Get S3 bucket from stack if not explicitly provided
    if [ -z "$S3_BUCKET" ]; then
        S3_BUCKET=$(echo "$frontend_config" | grep "s3_bucket=" | cut -d'=' -f2)
    fi
    
    print_status "  Frontend Domain: $frontend_domain"
    print_status "  S3 Bucket: $S3_BUCKET"
    if [ -n "$cloudfront_distribution_id" ]; then
        print_status "  CloudFront Distribution: $cloudfront_distribution_id"
    fi
    
    # Step 4: Generate config.json
    print_status "Generating config.json..."
    
    local config_json
    config_json=$(build_config_json \
        "$api_url" \
        "$user_pool_id" \
        "$client_id" \
        "$cognito_domain" \
        "$REGION" \
        "$frontend_domain" \
        "$API_TIMEOUT" \
        "$DATA_SOURCE" \
        "$ENABLE_FALLBACK" \
        "1.0.0" \
        "$GATEWAY_API_KEY")
    
    # Validate generated JSON
    if ! validate_config_json "$config_json"; then
        print_error "Generated config.json is invalid"
        exit $EXIT_INVALID_CONFIG
    fi
    
    if ! validate_config_schema "$config_json"; then
        print_error "Generated config.json is missing required fields"
        exit $EXIT_INVALID_CONFIG
    fi
    
    print_success "Config.json generated successfully"
    
    # Step 5: Display or upload config
    if [ "$DRY_RUN" = "true" ]; then
        print_dry_run "Generated config.json:"
        echo "$config_json" | jq . 2>/dev/null || echo "$config_json"
        
        # Verify S3 bucket access in dry-run mode
        print_dry_run "Verifying S3 bucket access..."
        if verify_s3_bucket_access "$S3_BUCKET"; then
            print_dry_run "S3 bucket '$S3_BUCKET' is accessible"
        else
            print_warning "S3 bucket '$S3_BUCKET' may not be accessible"
        fi
        
        print_dry_run "Would upload to: s3://${S3_BUCKET}/config.json"
        if [ -n "$cloudfront_distribution_id" ] && [ "$SKIP_INVALIDATION" != "true" ]; then
            print_dry_run "Would invalidate CloudFront distribution: $cloudfront_distribution_id"
        fi
        
        print_success "Dry run complete - no changes made"
    else
        # Upload to S3
        local backup_enabled="true"
        if [ "$NO_BACKUP" = "true" ]; then
            backup_enabled="false"
        fi
        
        local s3_uri
        s3_uri=$(upload_config_to_s3 "$config_json" "$S3_BUCKET" "config.json" "$backup_enabled")
        
        if [ -z "$s3_uri" ]; then
            print_error "Failed to upload config.json to S3"
            exit $EXIT_S3_ERROR
        fi
        
        print_success "Uploaded config.json to: $s3_uri"
        
        # Invalidate CloudFront cache
        if [ -n "$cloudfront_distribution_id" ] && [ "$SKIP_INVALIDATION" != "true" ]; then
            local invalidation_id
            invalidation_id=$(invalidate_cloudfront_cache "$cloudfront_distribution_id" "/config.json")
            
            if [ -n "$invalidation_id" ]; then
                print_success "Created CloudFront invalidation: $invalidation_id"
            fi
        fi
        
        print_success "UI config generation complete!"
    fi
}

# Entry point
parse_arguments "$@"
load_configuration
validate_parameters
main

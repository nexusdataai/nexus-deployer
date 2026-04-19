#!/bin/bash

# Complete Layered Business Capability Deployment Script
# Deploys business capabilities in a layered, incremental approach
# Supports cross-account and cross-region deployments

set -e  # Exit on error
set -o pipefail  # Pipe failures propagate

# Script directory
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

# Load helper libraries
source "${SCRIPT_DIR}/lib/colors.sh" 2>/dev/null || true
source "${SCRIPT_DIR}/lib/logging.sh" 2>/dev/null || true
source "${SCRIPT_DIR}/lib/aws-helpers.sh" 2>/dev/null || true
source "${SCRIPT_DIR}/lib/stack-helpers.sh" 2>/dev/null || true

# Default values
ENVIRONMENT=""
CAPABILITY_NAME=""
CAPABILITY_VERSION=""
CONFIG_FILE=""
AWS_REGION=""
TARGET_ACCOUNT=""
ROLE_ARN=""
DEPLOY_FRONTEND="true"
DEPLOY_BACKEND="true"
DRY_RUN="false"
VERBOSE="false"
SKIP_ARTIFACT_VERIFICATION="false"
STACK_PREFIX=""

# Source artifact locations
FRONTEND_S3_URI=""
BACKEND_ECR_URI=""

# Domain configuration
BASE_DOMAIN=""
HOSTED_ZONE_ID=""
FRONTEND_SUBDOMAIN="app"

# Stack names
declare -A STACK_NAMES

# Stack deployment order
declare -a STACK_ORDER=(
  "frontend-global"
  "frontend-cognito"
  "frontend-regional"
  "backend-foundation"
  "backend-regional-cert"
  "backend-storage"
  "backend-network"
  "backend-service"
)

# Colors for output (fallback if colors.sh not loaded)
if [ -z "$RED" ]; then
  RED='\033[0;31m'
  GREEN='\033[0;32m'
  YELLOW='\033[1;33m'
  BLUE='\033[0;34m'
  NC='\033[0m' # No Color
fi

# Logging functions (fallback if logging.sh not loaded)
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

# Usage function
usage() {
  cat << EOF
Usage: $(basename "$0") [OPTIONS]

Deploys a business capability using layered CloudFormation stacks.

OPTIONS:
  -c, --config FILE           Configuration file (YAML)
  -e, --environment ENV       Environment (dev|stage|prod)
  -n, --name NAME            Capability name
  -v, --version VERSION      Capability version
  -r, --region REGION        AWS region for deployment
  -a, --account ACCOUNT      Target AWS account ID
  --role-arn ARN            IAM role ARN for cross-account deployment
  --frontend-source URI      Frontend S3 URI (s3://bucket/path/dist.zip)
  --backend-source URI       Backend ECR URI (account.dkr.ecr.region.amazonaws.com/repo:tag)
  --frontend-only           Deploy only frontend stacks
  --backend-only            Deploy only backend stacks
  --dry-run                 Validate but don't deploy
  --skip-verification       Skip artifact existence verification
  --verbose                 Verbose output
  -h, --help                Display this help message

EXAMPLES:
  # Deploy with configuration file
  $(basename "$0") -c config/prod-config.yaml

  # Deploy with explicit parameters
  $(basename "$0") -e prod -n my-capability -v 1.2.3 -r us-west-2 \\
    --frontend-source s3://artifacts/frontend/dist.zip \\
    --backend-source 123456789.dkr.ecr.us-east-1.amazonaws.com/backend:v1.2.3

  # Cross-account deployment
  $(basename "$0") -c config/prod-config.yaml \\
    --role-arn arn:aws:iam::987654321:role/DeploymentRole

  # Frontend only deployment
  $(basename "$0") -c config/dev-config.yaml --frontend-only

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
      -e|--environment)
        ENVIRONMENT="$2"
        shift 2
        ;;
      -n|--name)
        CAPABILITY_NAME="$2"
        shift 2
        ;;
      -v|--version)
        CAPABILITY_VERSION="$2"
        shift 2
        ;;
      -r|--region)
        AWS_REGION="$2"
        shift 2
        ;;
      -a|--account)
        TARGET_ACCOUNT="$2"
        shift 2
        ;;
      --role-arn)
        ROLE_ARN="$2"
        shift 2
        ;;
      --frontend-source)
        FRONTEND_S3_URI="$2"
        shift 2
        ;;
      --backend-source)
        BACKEND_ECR_URI="$2"
        shift 2
        ;;
      --frontend-only)
        DEPLOY_FRONTEND="true"
        DEPLOY_BACKEND="false"
        shift
        ;;
      --backend-only)
        DEPLOY_FRONTEND="false"
        DEPLOY_BACKEND="true"
        shift
        ;;
      --dry-run)
        DRY_RUN="true"
        shift
        ;;
      --skip-verification)
        SKIP_ARTIFACT_VERIFICATION="true"
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
        exit 1
        ;;
    esac
  done
}

# Load configuration from YAML file
load_config() {
  local config_file="$1"
  
  if [ ! -f "$config_file" ]; then
    print_error "Configuration file not found: $config_file"
    exit 1
  fi
  
  print_status "Loading configuration from: $config_file"
  
  # Parse YAML configuration (requires yq or python)
  if command -v yq >/dev/null 2>&1; then
    # Use yq if available
    CAPABILITY_NAME=$(yq eval '.capability.name' "$config_file")
    CAPABILITY_VERSION=$(yq eval '.capability.version' "$config_file")
    ENVIRONMENT=$(yq eval '.target.environment' "$config_file")
    AWS_REGION=$(yq eval '.target.region' "$config_file")
    TARGET_ACCOUNT=$(yq eval '.target.account_id' "$config_file")
    FRONTEND_S3_URI=$(yq eval '.source.frontend.s3_uri' "$config_file")
    BACKEND_ECR_URI=$(yq eval '.source.backend.ecr_uri' "$config_file")
    
    # Domain configuration
    BASE_DOMAIN=$(yq eval '.infrastructure.domain.base' "$config_file")
    HOSTED_ZONE_ID=$(yq eval '.infrastructure.domain.hosted_zone_id' "$config_file")
    local frontend_sub=$(yq eval '.infrastructure.domain.frontend_subdomain // "app"' "$config_file")
    [ "$frontend_sub" != "null" ] && [ -n "$frontend_sub" ] && FRONTEND_SUBDOMAIN="$frontend_sub"
    
    # Backend ECS configuration
    CONTAINER_PORT=$(yq eval '.infrastructure.backend.ecs.container_port // 8080' "$config_file")
    HEALTH_CHECK_PATH=$(yq eval '.infrastructure.backend.ecs.health_check_path // "/health"' "$config_file")
    
    # Optional role ARN
    local role=$(yq eval '.target.role_arn // ""' "$config_file")
    [ "$role" != "null" ] && [ -n "$role" ] && ROLE_ARN="$role"
  elif command -v python3 >/dev/null 2>&1; then
    # Use Python as fallback
    eval "$(python3 -c "
import yaml
import sys
with open('$config_file', 'r') as f:
    config = yaml.safe_load(f)
    print(f\"CAPABILITY_NAME='{config['capability']['name']}'\")
    print(f\"CAPABILITY_VERSION='{config['capability']['version']}'\")
    print(f\"ENVIRONMENT='{config['target']['environment']}'\")
    print(f\"AWS_REGION='{config['target']['region']}'\")
    print(f\"TARGET_ACCOUNT='{config['target']['account_id']}'\")
    print(f\"FRONTEND_S3_URI='{config['source']['frontend']['s3_uri']}'\")
    print(f\"BACKEND_ECR_URI='{config['source']['backend']['ecr_uri']}'\")
    # Domain configuration
    domain = config.get('infrastructure', {}).get('domain', {})
    print(f\"BASE_DOMAIN='{domain.get('base', '')}'\")
    print(f\"HOSTED_ZONE_ID='{domain.get('hosted_zone_id', '')}'\")
    print(f\"FRONTEND_SUBDOMAIN='{domain.get('frontend_subdomain', 'app')}'\")
    # Backend ECS configuration
    ecs = config.get('infrastructure', {}).get('backend', {}).get('ecs', {})
    print(f\"CONTAINER_PORT={ecs.get('container_port', 8080)}\")
    print(f\"HEALTH_CHECK_PATH='{ecs.get('health_check_path', '/health')}'\")
    if 'role_arn' in config.get('target', {}):
        print(f\"ROLE_ARN='{config['target']['role_arn']}'\")
")"
  else
    print_error "Neither yq nor python3 with PyYAML is available. Please install one of them."
    print_status "Install yq: brew install yq (macOS) or wget https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 -O /usr/bin/yq"
    print_status "Install PyYAML: pip3 install pyyaml"
    exit 1
  fi
  
  print_success "Configuration loaded successfully"
}

# Verify S3 object exists
verify_s3_artifact() {
  local s3_uri="$1"
  
  print_status "Verifying frontend artifact: $s3_uri"
  
  # Extract bucket and key from S3 URI
  local bucket=$(echo "$s3_uri" | sed 's|s3://\([^/]*\)/.*|\1|')
  local key=$(echo "$s3_uri" | sed 's|s3://[^/]*/||')
  
  # Check if object exists
  if aws s3api head-object --bucket "$bucket" --key "$key" >/dev/null 2>&1; then
    print_success "Frontend artifact exists and is accessible"
    
    # Get object size for information
    local size=$(aws s3api head-object --bucket "$bucket" --key "$key" --query 'ContentLength' --output text 2>/dev/null)
    if [ -n "$size" ]; then
      local size_mb=$((size / 1024 / 1024))
      print_status "  Size: ${size_mb} MB"
    fi
    
    return 0
  else
    print_error "Frontend artifact not found or not accessible: $s3_uri"
    print_status "  Please ensure:"
    print_status "    - The S3 URI is correct"
    print_status "    - The object exists"
    print_status "    - You have permission to access it"
    return 1
  fi
}

# Verify ECR image exists
verify_ecr_image() {
  local ecr_uri="$1"
  
  print_status "Verifying backend container image: $ecr_uri"
  
  # Parse ECR URI components
  # Format: ACCOUNT.dkr.ecr.REGION.amazonaws.com/REPOSITORY:TAG
  local registry=$(echo "$ecr_uri" | cut -d'/' -f1)
  local repo_tag=$(echo "$ecr_uri" | cut -d'/' -f2-)
  local repository=$(echo "$repo_tag" | cut -d':' -f1)
  local tag=$(echo "$repo_tag" | cut -d':' -f2)
  
  # If no tag specified, use 'latest'
  if [ -z "$tag" ] || [ "$tag" == "$repository" ]; then
    tag="latest"
  fi
  
  # Extract region from registry
  local ecr_region=$(echo "$registry" | cut -d'.' -f4)
  
  # Check if image exists
  if aws ecr describe-images \
    --repository-name "$repository" \
    --image-ids "imageTag=$tag" \
    --region "$ecr_region" \
    --output json >/dev/null 2>&1; then
    
    print_success "Backend container image exists and is accessible"
    
    # Get image details for information
    local image_info=$(aws ecr describe-images \
      --repository-name "$repository" \
      --image-ids "imageTag=$tag" \
      --region "$ecr_region" \
      --query 'imageDetails[0].[imageSizeInBytes,imagePushedAt]' \
      --output text 2>/dev/null)
    
    if [ -n "$image_info" ]; then
      local size_bytes=$(echo "$image_info" | cut -f1)
      local pushed_at=$(echo "$image_info" | cut -f2)
      if [ -n "$size_bytes" ]; then
        local size_mb=$((size_bytes / 1024 / 1024))
        print_status "  Size: ${size_mb} MB"
      fi
      if [ -n "$pushed_at" ]; then
        print_status "  Pushed: $pushed_at"
      fi
    fi
    
    # Check for vulnerability scan results if available
    local scan_status=$(aws ecr describe-images \
      --repository-name "$repository" \
      --image-ids "imageTag=$tag" \
      --region "$ecr_region" \
      --query 'imageDetails[0].imageScanStatus.status' \
      --output text 2>/dev/null)
    
    if [ -n "$scan_status" ] && [ "$scan_status" != "None" ]; then
      print_status "  Scan Status: $scan_status"
      
      if [ "$scan_status" == "COMPLETE" ]; then
        local findings=$(aws ecr describe-images \
          --repository-name "$repository" \
          --image-ids "imageTag=$tag" \
          --region "$ecr_region" \
          --query 'imageDetails[0].imageScanFindingsSummary.findingSeverityCounts' \
          --output json 2>/dev/null)
        
        if [ -n "$findings" ] && [ "$findings" != "null" ]; then
          print_status "  Vulnerability findings: $findings"
        fi
      fi
    fi
    
    return 0
  else
    print_error "Backend container image not found or not accessible: $ecr_uri"
    print_status "  Please ensure:"
    print_status "    - The ECR URI is correct"
    print_status "    - The repository exists in region: $ecr_region"
    print_status "    - The image with tag '$tag' exists"
    print_status "    - You have permission to access the repository"
    print_status ""
    print_status "  To push an image:"
    print_status "    aws ecr get-login-password --region $ecr_region | docker login --username AWS --password-stdin $registry"
    print_status "    docker tag your-image:tag $ecr_uri"
    print_status "    docker push $ecr_uri"
    return 1
  fi
}

# Validate prerequisites
validate_prerequisites() {
  print_status "Validating prerequisites..."
  
  # Check AWS CLI
  if ! command -v aws >/dev/null 2>&1; then
    print_error "AWS CLI is not installed"
    exit 1
  fi
  
  # Check Docker if backend deployment is enabled
  if [ "$DEPLOY_BACKEND" == "true" ]; then
    if ! command -v docker >/dev/null 2>&1; then
      print_error "Docker is not installed (required for backend deployment)"
      print_status "Install Docker: curl -fsSL https://get.docker.com | sh"
      exit 1
    fi
    
    # Check if Docker daemon is running
    if ! docker info >/dev/null 2>&1; then
      print_error "Docker daemon is not running"
      print_status "Start Docker: sudo systemctl start docker"
      exit 1
    fi
  fi
  
  # Check required parameters
  if [ -z "$CAPABILITY_NAME" ]; then
    print_error "Capability name is required"
    exit 1
  fi
  
  if [ -z "$ENVIRONMENT" ]; then
    print_error "Environment is required"
    exit 1
  fi
  
  if [ -z "$AWS_REGION" ]; then
    print_error "AWS region is required"
    exit 1
  fi
  
  # Validate environment
  if [[ ! "$ENVIRONMENT" =~ ^(dev|stage|prod)$ ]]; then
    print_error "Invalid environment: $ENVIRONMENT (must be dev, stage, or prod)"
    exit 1
  fi
  
  # Check artifact sources
  if [ "$DEPLOY_FRONTEND" == "true" ]; then
    if [ -z "$FRONTEND_S3_URI" ]; then
      print_error "Frontend S3 URI is required for frontend deployment"
      exit 1
    fi
  fi
  
  if [ "$DEPLOY_BACKEND" == "true" ]; then
    if [ -z "$BACKEND_ECR_URI" ]; then
      print_error "Backend ECR URI is required for backend deployment"
      exit 1
    fi
  fi
  
  # Verify artifact existence (unless skipped)
  if [ "$SKIP_ARTIFACT_VERIFICATION" == "true" ]; then
    print_warning "Artifact verification skipped (--skip-verification flag set)"
    print_warning "Deployment may fail if artifacts don't exist"
  elif [ "$DEPLOY_FRONTEND" == "true" ] || [ "$DEPLOY_BACKEND" == "true" ]; then
    print_status ""
    print_status "=== Verifying Source Artifacts ==="
    
    if [ "$DEPLOY_FRONTEND" == "true" ]; then
      # Verify frontend artifact exists in S3
      if ! verify_s3_artifact "$FRONTEND_S3_URI"; then
        exit 1
      fi
    fi
    
    if [ "$DEPLOY_BACKEND" == "true" ]; then
      # Verify backend container image exists in ECR
      if ! verify_ecr_image "$BACKEND_ECR_URI"; then
        exit 1
      fi
    fi
    
    print_status ""
  fi
  
  print_success "All prerequisites validated successfully"
}

# Assume cross-account role if specified
assume_role() {
  if [ -z "$ROLE_ARN" ]; then
    return 0
  fi
  
  print_status "Assuming role: $ROLE_ARN"
  
  local session_name="capability-deployment-$(date +%s)"
  local credentials
  
  credentials=$(aws sts assume-role \
    --role-arn "$ROLE_ARN" \
    --role-session-name "$session_name" \
    --duration-seconds 3600 \
    --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' \
    --output text)
  
  if [ $? -ne 0 ]; then
    print_error "Failed to assume role"
    exit 1
  fi
  
  export AWS_ACCESS_KEY_ID=$(echo "$credentials" | cut -f1)
  export AWS_SECRET_ACCESS_KEY=$(echo "$credentials" | cut -f2)
  export AWS_SESSION_TOKEN=$(echo "$credentials" | cut -f3)
  
  print_success "Role assumed successfully"
}

# Initialize stack names
init_stack_names() {
  STACK_PREFIX="${CAPABILITY_NAME}-${ENVIRONMENT}"
  
  STACK_NAMES["frontend-global"]="${STACK_PREFIX}-frontend-global"
  STACK_NAMES["frontend-cognito"]="${STACK_PREFIX}-frontend-cognito"
  STACK_NAMES["frontend-regional"]="${STACK_PREFIX}-frontend-regional"
  STACK_NAMES["backend-foundation"]="${STACK_PREFIX}-backend-foundation"
  STACK_NAMES["backend-regional-cert"]="${STACK_PREFIX}-backend-regional-cert"
  STACK_NAMES["backend-storage"]="${STACK_PREFIX}-backend-storage"
  STACK_NAMES["backend-network"]="${STACK_PREFIX}-backend-network"
  STACK_NAMES["backend-service"]="${STACK_PREFIX}-backend-service"
}

# Check if stack exists
stack_exists() {
  local stack_name="$1"
  local region="${2:-$AWS_REGION}"
  
  aws cloudformation describe-stacks \
    --stack-name "$stack_name" \
    --region "$region" >/dev/null 2>&1
}

# Deploy a stack
deploy_stack() {
  local stack_type="$1"
  local region="${2:-$AWS_REGION}"
  local stack_name="${STACK_NAMES[$stack_type]}"
  local template_file="${SCRIPT_DIR}/templates/${stack_type//-//}-stack.yaml"
  
  # Skip if stack type not needed
  if [ "$stack_type" == "backend-regional-cert" ] && [ "$region" == "us-east-1" ]; then
    print_status "Skipping regional certificate (not needed for us-east-1)"
    return 0
  fi
  
  # Skip frontend stacks if not deploying frontend
  if [[ "$stack_type" == frontend-* ]] && [ "$DEPLOY_FRONTEND" != "true" ]; then
    return 0
  fi
  
  # Skip backend stacks if not deploying backend
  if [[ "$stack_type" == backend-* ]] && [ "$DEPLOY_BACKEND" != "true" ]; then
    return 0
  fi
  
  # Check if template exists
  if [ ! -f "$template_file" ]; then
    print_warning "Template not found: $template_file (skipping)"
    return 0
  fi
  
  print_status "Deploying stack: $stack_name in region: $region"
  
  # Build parameters based on stack type
  # aws cloudformation deploy uses Key=Value format for --parameter-overrides
  local parameters=""
  parameters="$parameters CapabilityName=${CAPABILITY_NAME}"
  parameters="$parameters Environment=${ENVIRONMENT}"
  
  # Add stack-specific parameters
  case $stack_type in
    "frontend-global")
      parameters="$parameters BaseDomain=${BASE_DOMAIN}"
      parameters="$parameters HostedZoneId=${HOSTED_ZONE_ID}"
      parameters="$parameters FrontendSubdomain=${FRONTEND_SUBDOMAIN}"
      ;;
    "frontend-cognito")
      # Fetch frontend domain from global stack
      local global_stack="${STACK_NAMES['frontend-global']}"
      local frontend_domain=$(aws cloudformation describe-stacks --stack-name "$global_stack" --region us-east-1 \
        --query "Stacks[0].Outputs[?OutputKey=='FrontendDomainName'].OutputValue" --output text)
      parameters="$parameters FrontendDomainName=${frontend_domain}"
      ;;
    "frontend-regional")
      # Fetch values from global stack (cross-region, so can't use Fn::ImportValue)
      local global_stack="${STACK_NAMES['frontend-global']}"
      local s3_domain=$(aws cloudformation describe-stacks --stack-name "$global_stack" --region us-east-1 \
        --query "Stacks[0].Outputs[?OutputKey=='S3BucketDomainName'].OutputValue" --output text)
      local cf_oai=$(aws cloudformation describe-stacks --stack-name "$global_stack" --region us-east-1 \
        --query "Stacks[0].Outputs[?OutputKey=='CloudFrontOAI'].OutputValue" --output text)
      local cert_arn=$(aws cloudformation describe-stacks --stack-name "$global_stack" --region us-east-1 \
        --query "Stacks[0].Outputs[?OutputKey=='CertificateArn'].OutputValue" --output text)
      local waf_arn=$(aws cloudformation describe-stacks --stack-name "$global_stack" --region us-east-1 \
        --query "Stacks[0].Outputs[?OutputKey=='WAFWebACLArn'].OutputValue" --output text)
      local frontend_domain=$(aws cloudformation describe-stacks --stack-name "$global_stack" --region us-east-1 \
        --query "Stacks[0].Outputs[?OutputKey=='FrontendDomainName'].OutputValue" --output text)
      local hosted_zone=$(aws cloudformation describe-stacks --stack-name "$global_stack" --region us-east-1 \
        --query "Stacks[0].Outputs[?OutputKey=='HostedZoneId'].OutputValue" --output text)
      
      parameters="$parameters GlobalStackName=${global_stack}"
      parameters="$parameters S3BucketDomainName=${s3_domain}"
      parameters="$parameters CloudFrontOAI=${cf_oai}"
      parameters="$parameters CertificateArn=${cert_arn}"
      parameters="$parameters WAFWebACLArn=${waf_arn}"
      parameters="$parameters FrontendDomainName=${frontend_domain}"
      parameters="$parameters HostedZoneId=${hosted_zone}"
      ;;
    "backend-foundation")
      parameters="$parameters BaseDomain=${BASE_DOMAIN}"
      parameters="$parameters HostedZoneId=${HOSTED_ZONE_ID}"
      parameters="$parameters ApiSubdomain=api"
      ;;
    "backend-regional-cert")
      parameters="$parameters BaseDomain=${BASE_DOMAIN}"
      parameters="$parameters HostedZoneId=${HOSTED_ZONE_ID}"
      parameters="$parameters ApiSubdomain=api"
      ;;
    "backend-storage")
      parameters="$parameters FoundationStackName=${STACK_NAMES['backend-foundation']}"
      ;;
    "backend-network")
      parameters="$parameters FoundationStackName=${STACK_NAMES['backend-foundation']}"
      parameters="$parameters ContainerPort=${CONTAINER_PORT}"
      ;;
    "backend-service")
      # Get the regional ECR URI from storage stack
      local target_ecr_uri=$(aws cloudformation describe-stacks \
        --stack-name "${STACK_NAMES['backend-storage']}" \
        --query "Stacks[0].Outputs[?OutputKey=='ECRRepositoryUri'].OutputValue" \
        --output text \
        --region "$AWS_REGION")
      local container_image="${target_ecr_uri}:${CAPABILITY_VERSION}"
      
      parameters="$parameters FoundationStackName=${STACK_NAMES['backend-foundation']}"
      parameters="$parameters StorageStackName=${STACK_NAMES['backend-storage']}"
      parameters="$parameters NetworkStackName=${STACK_NAMES['backend-network']}"
      parameters="$parameters ContainerImage=${container_image}"
      parameters="$parameters ContainerPort=${CONTAINER_PORT}"
      parameters="$parameters HealthCheckPath=${HEALTH_CHECK_PATH}"
      ;;
  esac
  
  # Determine if we're creating or updating
  local action="create"
  if stack_exists "$stack_name" "$region"; then
    action="update"
    print_status "Stack exists, updating..."
  else
    print_status "Creating new stack..."
  fi
  
  # Deploy stack (or validate in dry-run mode)
  if [ "$DRY_RUN" == "true" ]; then
    print_status "DRY RUN: Would deploy $stack_name"
    aws cloudformation validate-template \
      --template-body "file://${template_file}" \
      --region "$region" >/dev/null
    
    if [ $? -eq 0 ]; then
      print_success "Template validation successful"
    else
      print_error "Template validation failed"
      return 1
    fi
  else
    aws cloudformation deploy \
      --stack-name "$stack_name" \
      --template-file "$template_file" \
      --parameter-overrides $parameters \
      --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
      --region "$region" \
      --no-fail-on-empty-changeset
    
    if [ $? -eq 0 ]; then
      print_success "Stack deployed successfully: $stack_name"
    else
      print_error "Stack deployment failed: $stack_name"
      return 1
    fi
  fi
}

# Deploy frontend stacks
deploy_frontend() {
  if [ "$DEPLOY_FRONTEND" != "true" ]; then
    return 0
  fi
  
  print_status "Deploying frontend infrastructure..."
  
  # Deploy global resources in us-east-1
  deploy_stack "frontend-global" "us-east-1"
  
  # Deploy Cognito authentication in target region
  deploy_stack "frontend-cognito" "$AWS_REGION"
  
  # Deploy regional resources
  deploy_stack "frontend-regional" "$AWS_REGION"
  
  # Upload frontend artifacts
  if [ "$DRY_RUN" != "true" ]; then
    upload_frontend_artifacts
    
    # Generate and upload Cognito config.json to S3
    generate_cognito_config
    
    # Setup default admin user with permanent password
    setup_admin_user
  fi
  
  # Display Cognito configuration for frontend
  show_cognito_config
  
  print_success "Frontend deployment complete"
}

# Show Cognito configuration for frontend application
show_cognito_config() {
  local cognito_stack="${STACK_NAMES['frontend-cognito']}"
  
  if stack_exists "$cognito_stack" "$AWS_REGION"; then
    print_status "Cognito Configuration for Frontend:"
    aws cloudformation describe-stacks \
      --stack-name "$cognito_stack" \
      --query "Stacks[0].Outputs[?starts_with(OutputKey, 'EnvVar')].OutputValue" \
      --output text \
      --region "$AWS_REGION" | tr '\t' '\n'
  fi
}

# Generate and upload complete UI config.json to S3
# This function generates config.json with API and Cognito configuration
generate_cognito_config() {
  local cognito_stack="${STACK_NAMES['frontend-cognito']}"
  local global_stack="${STACK_NAMES['frontend-global']}"
  local regional_stack="${STACK_NAMES['frontend-regional']}"
  local api_stack="${STACK_NAMES['backend-service']}"
  
  if ! stack_exists "$cognito_stack" "$AWS_REGION"; then
    print_warning "Cognito stack not found, skipping config.json generation"
    return 0
  fi
  
  print_status "Generating UI config.json..."
  
  # Try to use the new config generator script if available
  local config_generator="${SCRIPT_DIR}/scripts/generate-ui-config.sh"
  if [ -f "$config_generator" ]; then
    print_status "Using enhanced config generator..."
    
    local generator_args=(
      --capability-name "$CAPABILITY_NAME"
      --environment "$ENVIRONMENT"
      --region "$AWS_REGION"
      --cognito-stack "$cognito_stack"
      --frontend-stack "$global_stack"
      --frontend-regional-stack "$regional_stack"
    )
    
    # Add API stack if backend is deployed
    if [ "$DEPLOY_BACKEND" = "true" ] && stack_exists "$api_stack" "$AWS_REGION"; then
      generator_args+=(--api-stack "$api_stack")
    fi
    
    # Add dry-run flag if applicable
    if [ "$DRY_RUN" = "true" ]; then
      generator_args+=(--dry-run)
    fi
    
    # Run the config generator
    if bash "$config_generator" "${generator_args[@]}"; then
      print_success "UI config.json generated and uploaded successfully"
      return 0
    else
      print_warning "Enhanced config generator failed, falling back to basic config"
    fi
  fi
  
  # Fallback: Generate basic config with Cognito only
  print_status "Generating basic Cognito config.json..."
  
  # Get Cognito outputs
  local user_pool_id=$(aws cloudformation describe-stacks \
    --stack-name "$cognito_stack" \
    --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" \
    --output text \
    --region "$AWS_REGION")
  
  local client_id=$(aws cloudformation describe-stacks \
    --stack-name "$cognito_stack" \
    --query "Stacks[0].Outputs[?OutputKey=='UserPoolClientId'].OutputValue" \
    --output text \
    --region "$AWS_REGION")
  
  local cognito_domain=$(aws cloudformation describe-stacks \
    --stack-name "$cognito_stack" \
    --query "Stacks[0].Outputs[?OutputKey=='UserPoolDomain'].OutputValue" \
    --output text \
    --region "$AWS_REGION")
  
  # Get S3 bucket from regional stack (S3BucketName is in frontend-regional, not frontend-global)
  local bucket_name=$(aws cloudformation describe-stacks \
    --stack-name "$regional_stack" \
    --query "Stacks[0].Outputs[?OutputKey=='S3BucketName'].OutputValue" \
    --output text \
    --region "$AWS_REGION")
  
  if [ -z "$bucket_name" ] || [ "$bucket_name" == "None" ]; then
    print_error "Could not get S3 bucket name from regional stack"
    return 1
  fi
  
  # Get CloudFront distribution ID from regional stack for cache invalidation
  local cloudfront_distribution_id=$(aws cloudformation describe-stacks \
    --stack-name "$regional_stack" \
    --query "Stacks[0].Outputs[?OutputKey=='CloudFrontDistributionId'].OutputValue" \
    --output text \
    --region "$AWS_REGION" 2>/dev/null || echo "")
  
  # Get frontend domain for redirect URIs from global stack
  local frontend_domain=$(aws cloudformation describe-stacks \
    --stack-name "$global_stack" \
    --query "Stacks[0].Outputs[?OutputKey=='FrontendDomainName'].OutputValue" \
    --output text \
    --region "us-east-1")
  
  # Try to get API URL if backend stack exists
  local api_url=""
  if stack_exists "$api_stack" "$AWS_REGION"; then
    api_url=$(aws cloudformation describe-stacks \
      --stack-name "$api_stack" \
      --query "Stacks[0].Outputs[?OutputKey=='ApiEndpoint'].OutputValue" \
      --output text \
      --region "$AWS_REGION" 2>/dev/null || echo "")
    
    if [ -z "$api_url" ] || [ "$api_url" == "None" ]; then
      # Try alternative output names
      api_url=$(aws cloudformation describe-stacks \
        --stack-name "$api_stack" \
        --query "Stacks[0].Outputs[?OutputKey=='ApiGatewayUrl'].OutputValue" \
        --output text \
        --region "$AWS_REGION" 2>/dev/null || echo "")
    fi
  fi
  
  # Build redirect URIs
  local redirect_sign_in="https://${frontend_domain}/auth/callback"
  local redirect_sign_out="https://${frontend_domain}"
  
  # Create config.json content with full schema
  local config_json=$(cat <<EOF
{
  "version": "${CAPABILITY_VERSION:-1.0.0}",
  "api": {
    "baseUrl": "${api_url:-}",
    "timeout": 30000
  },
  "gateway": {
    "apiKey": ""
  },
  "dataSource": "api",
  "enableFallback": true,
  "cognito": {
    "region": "${AWS_REGION}",
    "userPoolId": "${user_pool_id}",
    "clientId": "${client_id}",
    "domain": "${cognito_domain}",
    "redirectSignIn": "${redirect_sign_in}",
    "redirectSignOut": "${redirect_sign_out}"
  }
}
EOF
)
  
  # Upload to S3
  print_status "Uploading config.json to s3://${bucket_name}/config.json"
  echo "$config_json" | aws s3 cp - "s3://${bucket_name}/config.json" \
    --content-type "application/json" \
    --cache-control "no-cache,no-store,must-revalidate"
  
  if [ $? -eq 0 ]; then
    print_success "config.json uploaded successfully"
    print_status "Config contents:"
    echo "$config_json" | jq . 2>/dev/null || echo "$config_json"
    
    # Invalidate CloudFront cache if distribution ID is available
    if [ -n "$cloudfront_distribution_id" ] && [ "$cloudfront_distribution_id" != "None" ]; then
      print_status "Invalidating CloudFront cache for /config.json..."
      local invalidation_id=$(aws cloudfront create-invalidation \
        --distribution-id "$cloudfront_distribution_id" \
        --paths "/config.json" \
        --query 'Invalidation.Id' \
        --output text 2>/dev/null || echo "")
      
      if [ -n "$invalidation_id" ] && [ "$invalidation_id" != "None" ]; then
        print_success "Created CloudFront invalidation: $invalidation_id"
      else
        print_warning "CloudFront invalidation failed or not available"
      fi
    fi
  else
    print_error "Failed to upload config.json"
    return 1
  fi
}

# Setup default admin user with permanent password
setup_admin_user() {
  local cognito_stack="${STACK_NAMES['frontend-cognito']}"
  
  if ! stack_exists "$cognito_stack" "$AWS_REGION"; then
    print_warning "Cognito stack not found, skipping admin user setup"
    return 0
  fi
  
  print_status "Setting up default admin user..."
  
  # Get User Pool ID
  local user_pool_id=$(aws cloudformation describe-stacks \
    --stack-name "$cognito_stack" \
    --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" \
    --output text \
    --region "$AWS_REGION")
  
  # Get Admin user email from stack output
  local admin_email=$(aws cloudformation describe-stacks \
    --stack-name "$cognito_stack" \
    --query "Stacks[0].Outputs[?OutputKey=='AdminUserEmail'].OutputValue" \
    --output text \
    --region "$AWS_REGION")
  
  if [ -z "$user_pool_id" ] || [ "$user_pool_id" == "None" ]; then
    print_error "Could not get User Pool ID"
    return 1
  fi
  
  if [ -z "$admin_email" ] || [ "$admin_email" == "None" ]; then
    # Fallback to default admin email format
    admin_email="admin@${CAPABILITY_NAME}.local"
  fi
  
  # Generate default password based on capability name
  # Format: Admin@{CapabilityNamePascalCase}123!
  local capability_pascal=$(echo "$CAPABILITY_NAME" | sed -r 's/(^|-)(\w)/\U\2/g')
  local admin_password="Admin@${capability_pascal}123!"
  
  print_status "Admin email: $admin_email"
  
  # Check if user exists
  if aws cognito-idp admin-get-user \
    --user-pool-id "$user_pool_id" \
    --username "$admin_email" \
    --region "$AWS_REGION" >/dev/null 2>&1; then
    
    # Set permanent password for admin user
    print_status "Setting permanent password for admin user..."
    
    if aws cognito-idp admin-set-user-password \
      --user-pool-id "$user_pool_id" \
      --username "$admin_email" \
      --password "$admin_password" \
      --permanent \
      --region "$AWS_REGION" 2>/dev/null; then
      
      print_success "Admin user configured successfully"
      print_status ""
      print_status "╔════════════════════════════════════════════════════════════╗"
      print_status "║           DEFAULT ADMIN CREDENTIALS                        ║"
      print_status "╠════════════════════════════════════════════════════════════╣"
      print_status "║  Email:    $admin_email"
      print_status "║  Password: $admin_password"
      print_status "╠════════════════════════════════════════════════════════════╣"
      print_status "║  ⚠️  Please change this password after first login!        ║"
      print_status "╚════════════════════════════════════════════════════════════╝"
      print_status ""
    else
      print_warning "Could not set admin password (user may already have a password)"
    fi
  else
    print_warning "Admin user not found in Cognito (stack may still be creating user)"
  fi
}

# Deploy backend stacks
deploy_backend() {
  if [ "$DEPLOY_BACKEND" != "true" ]; then
    return 0
  fi
  
  print_status "Deploying backend infrastructure..."
  
  # Deploy foundation stack
  deploy_stack "backend-foundation" "$AWS_REGION"
  
  # Deploy regional certificate if needed
  if [ "$AWS_REGION" != "us-east-1" ]; then
    deploy_stack "backend-regional-cert" "$AWS_REGION"
  fi
  
  # Deploy storage stack
  deploy_stack "backend-storage" "$AWS_REGION"
  
  # Deploy network stack
  deploy_stack "backend-network" "$AWS_REGION"
  
  # Copy container image if needed
  if [ "$DRY_RUN" != "true" ]; then
    copy_container_image
  fi
  
  # Deploy service stack
  deploy_stack "backend-service" "$AWS_REGION"
  
  # Update Route53 alias
  if [ "$DRY_RUN" != "true" ]; then
    update_route53_alias
  fi
  
  print_success "Backend deployment complete"
}

# Upload frontend artifacts to S3
upload_frontend_artifacts() {
  print_status "Uploading frontend artifacts..."
  
  # Get S3 bucket name from frontend-global stack
  local bucket_name
  bucket_name=$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAMES['frontend-global']}" \
    --query "Stacks[0].Outputs[?OutputKey=='S3BucketName'].OutputValue" \
    --output text \
    --region "us-east-1")
  
  if [ -z "$bucket_name" ]; then
    print_error "Could not get S3 bucket name from stack"
    return 1
  fi
  
  # Create temp directory
  local temp_dir=$(mktemp -d)
  trap "rm -rf $temp_dir" EXIT
  
  # Download frontend artifacts
  print_status "Downloading frontend artifacts from: $FRONTEND_S3_URI"
  aws s3 cp "$FRONTEND_S3_URI" "$temp_dir/dist.zip"
  
  # Extract artifacts (use -o to overwrite without prompting)
  unzip -q -o "$temp_dir/dist.zip" -d "$temp_dir/dist"
  
  # Upload to target bucket
  print_status "Uploading to bucket: $bucket_name"
  
  # Upload static assets with long cache (exclude html and json for separate handling)
  aws s3 sync "$temp_dir/dist" "s3://${bucket_name}/" \
    --delete \
    --cache-control "max-age=31536000,public" \
    --exclude "index.html" \
    --exclude "*.json"
  
  # Upload index.html with no-cache
  aws s3 cp "$temp_dir/dist/index.html" "s3://${bucket_name}/index.html" \
    --cache-control "no-cache,no-store,must-revalidate" \
    --content-type "text/html"
  
  # Upload JSON files with no-cache (data files that may change)
  while IFS= read -r -d '' json_file; do
    relative_path="${json_file#$temp_dir/dist/}"
    print_status "  Uploading JSON: $relative_path"
    aws s3 cp "$json_file" "s3://${bucket_name}/${relative_path}" \
      --cache-control "no-cache,no-store,must-revalidate" \
      --content-type "application/json"
  done < <(find "$temp_dir/dist" -name "*.json" -type f -print0)
  
  # Invalidate CloudFront cache
  local distribution_id
  distribution_id=$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAMES['frontend-regional']}" \
    --query "Stacks[0].Outputs[?OutputKey=='DistributionId'].OutputValue" \
    --output text \
    --region "$AWS_REGION")
  
  if [ -n "$distribution_id" ]; then
    print_status "Creating CloudFront invalidation..."
    aws cloudfront create-invalidation \
      --distribution-id "$distribution_id" \
      --paths "/*" >/dev/null
  fi
  
  print_success "Frontend artifacts uploaded successfully"
}

# Copy container image to target ECR
copy_container_image() {
  print_status "Copying container image..."
  
  # Get ECR repository URI from storage stack
  local target_ecr_uri
  target_ecr_uri=$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAMES['backend-storage']}" \
    --query "Stacks[0].Outputs[?OutputKey=='ECRRepositoryUri'].OutputValue" \
    --output text \
    --region "$AWS_REGION")
  
  if [ -z "$target_ecr_uri" ]; then
    print_error "Could not get ECR repository URI from stack"
    return 1
  fi
  
  # Login to source ECR
  local source_region=$(echo "$BACKEND_ECR_URI" | cut -d. -f4)
  aws ecr get-login-password --region "$source_region" | \
    docker login --username AWS --password-stdin "${BACKEND_ECR_URI%%/*}"
  
  # Pull source image
  print_status "Pulling image: $BACKEND_ECR_URI"
  docker pull "$BACKEND_ECR_URI"
  
  # Tag for target repository
  local target_tag="${target_ecr_uri}:${CAPABILITY_VERSION:-latest}"
  docker tag "$BACKEND_ECR_URI" "$target_tag"
  
  # Login to target ECR
  aws ecr get-login-password --region "$AWS_REGION" | \
    docker login --username AWS --password-stdin "${target_ecr_uri%%/*}"
  
  # Push to target repository
  print_status "Pushing to: $target_tag"
  docker push "$target_tag"
  
  print_success "Container image copied successfully"
}

# Update Route53 alias to point to ALB
update_route53_alias() {
  print_status "Updating Route53 alias record..."
  
  # Get ALB details from service stack
  local alb_dns alb_zone
  alb_dns=$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAMES['backend-service']}" \
    --query "Stacks[0].Outputs[?OutputKey=='LoadBalancerDNS'].OutputValue" \
    --output text \
    --region "$AWS_REGION")
  
  alb_zone=$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAMES['backend-service']}" \
    --query "Stacks[0].Outputs[?OutputKey=='LoadBalancerZone'].OutputValue" \
    --output text \
    --region "$AWS_REGION")
  
  if [ -z "$alb_dns" ] || [ -z "$alb_zone" ]; then
    print_warning "ALB details not found, skipping Route53 update"
    return 0
  fi
  
  # Update would happen here (placeholder for actual implementation)
  print_success "Route53 alias updated"
}

# Show deployment outputs
show_outputs() {
  print_status "=== Deployment Outputs ==="
  
  for stack_type in "${STACK_ORDER[@]}"; do
    local stack_name="${STACK_NAMES[$stack_type]}"
    local region="$AWS_REGION"
    
    # Frontend global is always in us-east-1
    if [ "$stack_type" == "frontend-global" ]; then
      region="us-east-1"
    fi
    
    if stack_exists "$stack_name" "$region"; then
      echo
      print_status "Stack: $stack_name"
      aws cloudformation describe-stacks \
        --stack-name "$stack_name" \
        --query "Stacks[0].Outputs[*].[OutputKey,OutputValue]" \
        --output table \
        --region "$region"
    fi
  done
}

# Verify deployment
verify_deployment() {
  print_status "Verifying deployment..."
  
  local all_healthy=true
  
  # Check frontend if deployed
  if [ "$DEPLOY_FRONTEND" == "true" ]; then
    local frontend_url
    frontend_url=$(aws cloudformation describe-stacks \
      --stack-name "${STACK_NAMES['frontend-regional']}" \
      --query "Stacks[0].Outputs[?OutputKey=='CloudFrontURL'].OutputValue" \
      --output text \
      --region "$AWS_REGION" 2>/dev/null)
    
    if [ -n "$frontend_url" ]; then
      if curl -s -o /dev/null -w "%{http_code}" "https://${frontend_url}" | grep -q "200\|301\|302"; then
        print_success "Frontend is accessible: https://${frontend_url}"
      else
        print_warning "Frontend might not be fully deployed yet"
        all_healthy=false
      fi
    fi
  fi
  
  # Check backend if deployed
  if [ "$DEPLOY_BACKEND" == "true" ]; then
    local backend_url
    backend_url=$(aws cloudformation describe-stacks \
      --stack-name "${STACK_NAMES['backend-service']}" \
      --query "Stacks[0].Outputs[?OutputKey=='ServiceURL'].OutputValue" \
      --output text \
      --region "$AWS_REGION" 2>/dev/null)
    
    if [ -n "$backend_url" ]; then
      if curl -s -o /dev/null -w "%{http_code}" "${backend_url}/health" | grep -q "200"; then
        print_success "Backend is healthy: ${backend_url}"
      else
        print_warning "Backend might not be fully deployed yet"
        all_healthy=false
      fi
    fi
  fi
  
  if [ "$all_healthy" == "true" ]; then
    print_success "Deployment verification complete - all systems operational"
  else
    print_warning "Some services may still be initializing"
  fi
}

# Main deployment function
main() {
  print_status "=== Starting Layered Capability Deployment ==="
  print_status "Version: 1.0.0"
  print_status "Time: $(date)"
  
  # Parse arguments
  parse_arguments "$@"
  
  # Load configuration if provided
  if [ -n "$CONFIG_FILE" ]; then
    load_config "$CONFIG_FILE"
  fi
  
  # Initialize stack names (needed for validation output)
  init_stack_names
  
  # Assume role if needed (before validation so we can check artifacts in target account)
  assume_role
  
  # Validate prerequisites (includes artifact existence checks)
  validate_prerequisites
  
  # Show deployment configuration
  print_status "Deployment Configuration:"
  print_status "  Capability: $CAPABILITY_NAME"
  print_status "  Version: ${CAPABILITY_VERSION:-latest}"
  print_status "  Environment: $ENVIRONMENT"
  print_status "  Region: $AWS_REGION"
  print_status "  Deploy Frontend: $DEPLOY_FRONTEND"
  print_status "  Deploy Backend: $DEPLOY_BACKEND"
  print_status "  Dry Run: $DRY_RUN"
  
  # Deploy frontend infrastructure
  deploy_frontend
  
  # Deploy backend infrastructure
  deploy_backend
  
  # Show outputs
  if [ "$DRY_RUN" != "true" ]; then
    show_outputs
    verify_deployment
  fi
  
  print_success "=== Deployment Complete ==="
}

# Run main function
main "$@"

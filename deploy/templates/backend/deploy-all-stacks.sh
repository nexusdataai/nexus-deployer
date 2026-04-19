#!/bin/bash

# Backend Stack Deployment Script
# This script deploys all backend CloudFormation stacks in the correct order

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
CAPABILITY_NAME="${CAPABILITY_NAME:-my-capability}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
BASE_DOMAIN="${BASE_DOMAIN:-example.com}"
API_SUBDOMAIN="${API_SUBDOMAIN:-api-${ENVIRONMENT}}"
HOSTED_ZONE_ID="${HOSTED_ZONE_ID:-Z1234567890ABC}"
VPC_CIDR="${VPC_CIDR:-10.0.0.0/16}"
CONTAINER_IMAGE="${CONTAINER_IMAGE:-}"

# Stack names
FOUNDATION_STACK="${CAPABILITY_NAME}-foundation-${ENVIRONMENT}"
IAM_ROLES_STACK="${CAPABILITY_NAME}-iam-roles-${ENVIRONMENT}"
NETWORK_STACK="${CAPABILITY_NAME}-network-${ENVIRONMENT}"
STORAGE_STACK="${CAPABILITY_NAME}-storage-${ENVIRONMENT}"
WXCC_STACK="${CAPABILITY_NAME}-wxcc-${ENVIRONMENT}"
REGIONAL_CERT_STACK="${CAPABILITY_NAME}-regional-cert-${ENVIRONMENT}"
SERVICE_STACK="${CAPABILITY_NAME}-service-${ENVIRONMENT}"
DOMAIN_STACK="${CAPABILITY_NAME}-domain-${ENVIRONMENT}"

# Deployment flags
DEPLOY_FOUNDATION="${DEPLOY_FOUNDATION:-true}"
DEPLOY_IAM_ROLES="${DEPLOY_IAM_ROLES:-true}"
DEPLOY_NETWORK="${DEPLOY_NETWORK:-true}"
DEPLOY_STORAGE="${DEPLOY_STORAGE:-true}"
DEPLOY_WXCC="${DEPLOY_WXCC:-true}"
DEPLOY_REGIONAL_CERT="${DEPLOY_REGIONAL_CERT:-false}"
DEPLOY_SERVICE="${DEPLOY_SERVICE:-true}"
DEPLOY_DOMAIN="${DEPLOY_DOMAIN:-true}"

# WXCC Configuration (optional)
WEBEX_BASE_URL="${WEBEX_BASE_URL:-https://api.wxcc-us1.cisco.com/v1}"
WEBEX_REDIRECT_URI="${WEBEX_REDIRECT_URI:-https://trilogy.com}"

# Function to print colored messages
print_info() {
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

# Function to wait for stack completion
wait_for_stack() {
    local stack_name=$1
    local operation=$2
    
    print_info "Waiting for stack ${stack_name} to complete ${operation}..."
    
    aws cloudformation wait stack-${operation}-complete \
        --stack-name "${stack_name}" \
        --region "${AWS_REGION}" 2>/dev/null
    
    if [ $? -eq 0 ]; then
        print_success "Stack ${stack_name} ${operation} completed successfully"
        return 0
    else
        print_error "Stack ${stack_name} ${operation} failed or timed out"
        return 1
    fi
}

# Function to check if stack exists
stack_exists() {
    local stack_name=$1
    aws cloudformation describe-stacks \
        --stack-name "${stack_name}" \
        --region "${AWS_REGION}" \
        >/dev/null 2>&1
    return $?
}

# Function to deploy or update stack
deploy_stack() {
    local stack_name=$1
    local template_file=$2
    shift 2
    local parameters=("$@")
    
    print_info "Deploying stack: ${stack_name}"
    
    if stack_exists "${stack_name}"; then
        print_warning "Stack ${stack_name} already exists. Updating..."
        operation="update"
        
        aws cloudformation update-stack \
            --stack-name "${stack_name}" \
            --template-body "file://${template_file}" \
            --parameters "${parameters[@]}" \
            --capabilities CAPABILITY_NAMED_IAM \
            --region "${AWS_REGION}" 2>&1 | tee /tmp/cfn-output.txt
        
        if grep -q "No updates are to be performed" /tmp/cfn-output.txt; then
            print_info "No updates needed for stack ${stack_name}"
            return 0
        fi
    else
        print_info "Creating new stack: ${stack_name}"
        operation="create"
        
        aws cloudformation create-stack \
            --stack-name "${stack_name}" \
            --template-body "file://${template_file}" \
            --parameters "${parameters[@]}" \
            --capabilities CAPABILITY_NAMED_IAM \
            --region "${AWS_REGION}"
    fi
    
    wait_for_stack "${stack_name}" "${operation}"
}

# Validate required parameters
validate_parameters() {
    print_info "Validating parameters..."
    
    if [ -z "${CAPABILITY_NAME}" ]; then
        print_error "CAPABILITY_NAME is required"
        exit 1
    fi
    
    if [ -z "${ENVIRONMENT}" ]; then
        print_error "ENVIRONMENT is required"
        exit 1
    fi
    
    if [ "${DEPLOY_SERVICE}" = "true" ] && [ -z "${CONTAINER_IMAGE}" ]; then
        print_error "CONTAINER_IMAGE is required when deploying service stack"
        exit 1
    fi
    
    print_success "Parameter validation passed"
}

# Main deployment function
main() {
    print_info "Starting backend stack deployment"
    print_info "Capability: ${CAPABILITY_NAME}"
    print_info "Environment: ${ENVIRONMENT}"
    print_info "Region: ${AWS_REGION}"
    echo ""
    
    validate_parameters
    
    # 1. Deploy Foundation Stack
    if [ "${DEPLOY_FOUNDATION}" = "true" ]; then
        print_info "Step 1/8: Deploying Foundation Stack"
        deploy_stack "${FOUNDATION_STACK}" "foundation-stack.yaml" \
            "ParameterKey=CapabilityName,ParameterValue=${CAPABILITY_NAME}" \
            "ParameterKey=Environment,ParameterValue=${ENVIRONMENT}" \
            "ParameterKey=LogRetentionDays,ParameterValue=7"
        echo ""
    else
        print_warning "Skipping Foundation Stack deployment"
    fi
    
    # 2. Deploy IAM Roles Stack
    if [ "${DEPLOY_IAM_ROLES}" = "true" ]; then
        print_info "Step 2/8: Deploying IAM Roles Stack"
        deploy_stack "${IAM_ROLES_STACK}" "iam-roles-stack.yaml" \
            "ParameterKey=CapabilityName,ParameterValue=${CAPABILITY_NAME}" \
            "ParameterKey=Environment,ParameterValue=${ENVIRONMENT}"
        echo ""
    else
        print_warning "Skipping IAM Roles Stack deployment"
    fi
    
    # 3. Deploy Network Stack
    if [ "${DEPLOY_NETWORK}" = "true" ]; then
        print_info "Step 3/8: Deploying Network Stack"
        deploy_stack "${NETWORK_STACK}" "network-stack.yaml" \
            "ParameterKey=CapabilityName,ParameterValue=${CAPABILITY_NAME}" \
            "ParameterKey=Environment,ParameterValue=${ENVIRONMENT}" \
            "ParameterKey=VpcCIDR,ParameterValue=${VPC_CIDR}"
        echo ""
    else
        print_warning "Skipping Network Stack deployment"
    fi
    
    # 4. Deploy Storage Stack
    if [ "${DEPLOY_STORAGE}" = "true" ]; then
        print_info "Step 4/8: Deploying Storage Stack"
        deploy_stack "${STORAGE_STACK}" "storage-stack.yaml" \
            "ParameterKey=CapabilityName,ParameterValue=${CAPABILITY_NAME}" \
            "ParameterKey=Environment,ParameterValue=${ENVIRONMENT}" \
            "ParameterKey=FoundationStackName,ParameterValue=${FOUNDATION_STACK}"
        echo ""
    else
        print_warning "Skipping Storage Stack deployment"
    fi
    
    # 5. Deploy WXCC Stack (Webex Contact Center Resources)
    if [ "${DEPLOY_WXCC}" = "true" ]; then
        print_info "Step 5/8: Deploying WXCC Stack (Webex Contact Center)"
        deploy_stack "${WXCC_STACK}" "wxcc-stack.yaml" \
            "ParameterKey=CapabilityName,ParameterValue=${CAPABILITY_NAME}" \
            "ParameterKey=Environment,ParameterValue=${ENVIRONMENT}" \
            "ParameterKey=StorageStackName,ParameterValue=${STORAGE_STACK}" \
            "ParameterKey=WebexBaseUrl,ParameterValue=${WEBEX_BASE_URL}" \
            "ParameterKey=WebexRedirectUri,ParameterValue=${WEBEX_REDIRECT_URI}"
        echo ""
    else
        print_warning "Skipping WXCC Stack deployment"
    fi
    
    # 6. Deploy Regional Certificate Stack (Optional)
    if [ "${DEPLOY_REGIONAL_CERT}" = "true" ]; then
        print_info "Step 6/8: Deploying Regional Certificate Stack"
        deploy_stack "${REGIONAL_CERT_STACK}" "regional-cert-stack.yaml" \
            "ParameterKey=CapabilityName,ParameterValue=${CAPABILITY_NAME}" \
            "ParameterKey=Environment,ParameterValue=${ENVIRONMENT}" \
            "ParameterKey=BaseDomain,ParameterValue=${BASE_DOMAIN}" \
            "ParameterKey=ApiSubdomain,ParameterValue=${API_SUBDOMAIN}" \
            "ParameterKey=HostedZoneId,ParameterValue=${HOSTED_ZONE_ID}"
        echo ""
    else
        print_warning "Skipping Regional Certificate Stack deployment"
    fi
    
    # 7. Deploy Service Stack
    if [ "${DEPLOY_SERVICE}" = "true" ]; then
        print_info "Step 7/8: Deploying Service Stack"
        deploy_stack "${SERVICE_STACK}" "service-stack.yaml" \
            "ParameterKey=CapabilityName,ParameterValue=${CAPABILITY_NAME}" \
            "ParameterKey=Environment,ParameterValue=${ENVIRONMENT}" \
            "ParameterKey=FoundationStackName,ParameterValue=${FOUNDATION_STACK}" \
            "ParameterKey=IAMRolesStackName,ParameterValue=${IAM_ROLES_STACK}" \
            "ParameterKey=NetworkStackName,ParameterValue=${NETWORK_STACK}" \
            "ParameterKey=StorageStackName,ParameterValue=${STORAGE_STACK}" \
            "ParameterKey=DomainStackName,ParameterValue=${DOMAIN_STACK}" \
            "ParameterKey=ContainerImage,ParameterValue=${CONTAINER_IMAGE}" \
            "ParameterKey=CreateRoute53Record,ParameterValue=false"
        echo ""
    else
        print_warning "Skipping Service Stack deployment"
    fi
    
    # 8. Deploy Domain Stack
    if [ "${DEPLOY_DOMAIN}" = "true" ]; then
        print_info "Step 8/8: Deploying Domain Stack"
        deploy_stack "${DOMAIN_STACK}" "domain-stack.yaml" \
            "ParameterKey=CapabilityName,ParameterValue=${CAPABILITY_NAME}" \
            "ParameterKey=Environment,ParameterValue=${ENVIRONMENT}" \
            "ParameterKey=BaseDomain,ParameterValue=${BASE_DOMAIN}" \
            "ParameterKey=ApiSubdomain,ParameterValue=${API_SUBDOMAIN}" \
            "ParameterKey=HostedZoneId,ParameterValue=${HOSTED_ZONE_ID}" \
            "ParameterKey=ServiceStackName,ParameterValue=${SERVICE_STACK}" \
            "ParameterKey=CreateCertificate,ParameterValue=true" \
            "ParameterKey=CreateRoute53Record,ParameterValue=true"
        echo ""
    else
        print_warning "Skipping Domain Stack deployment"
    fi
    
    print_success "All stacks deployed successfully!"
    print_info "API URL: https://${API_SUBDOMAIN}.${BASE_DOMAIN}"
}

# Print usage
usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Deploy backend CloudFormation stacks in the correct order.

Required Environment Variables:
  CAPABILITY_NAME       Name of the capability (e.g., my-capability)
  ENVIRONMENT          Environment name (dev, stage, prod)
  CONTAINER_IMAGE      Full ECR image URI (required for service stack)

Optional Environment Variables:
  AWS_REGION           AWS region (default: us-east-1)
  BASE_DOMAIN          Base domain name (default: example.com)
  API_SUBDOMAIN        API subdomain (default: api-{environment})
  HOSTED_ZONE_ID       Route53 hosted zone ID (default: Z1234567890ABC)
  VPC_CIDR             VPC CIDR block (default: 10.0.0.0/16)

Deployment Flags (set to 'false' to skip):
  DEPLOY_FOUNDATION    Deploy foundation stack (default: true)
  DEPLOY_IAM_ROLES     Deploy IAM roles stack (default: true)
  DEPLOY_NETWORK       Deploy network stack (default: true)
  DEPLOY_STORAGE       Deploy storage stack (default: true)
  DEPLOY_WXCC          Deploy WXCC stack (default: true)
  DEPLOY_REGIONAL_CERT Deploy regional cert stack (default: false)
  DEPLOY_SERVICE       Deploy service stack (default: true)
  DEPLOY_DOMAIN        Deploy domain stack (default: true)

WXCC Configuration (optional):
  WEBEX_BASE_URL       Webex API base URL (default: https://api.wxcc-us1.cisco.com/v1)
  WEBEX_REDIRECT_URI   OAuth redirect URI (default: https://trilogy.com)

Examples:
  # Deploy all stacks (NOTE: ECR region should match AWS_REGION for ECS)
  CAPABILITY_NAME=my-app ENVIRONMENT=dev CONTAINER_IMAGE=123.dkr.ecr.ap-southeast-1.amazonaws.com/my-app:latest ./deploy-all-stacks.sh

  # Deploy only service and domain stacks
  CAPABILITY_NAME=my-app ENVIRONMENT=dev CONTAINER_IMAGE=123.dkr.ecr.ap-southeast-1.amazonaws.com/my-app:latest \\
    DEPLOY_FOUNDATION=false DEPLOY_IAM_ROLES=false DEPLOY_NETWORK=false DEPLOY_STORAGE=false \\
    ./deploy-all-stacks.sh

  # Deploy with custom domain
  CAPABILITY_NAME=my-app ENVIRONMENT=prod CONTAINER_IMAGE=123.dkr.ecr.ap-southeast-1.amazonaws.com/my-app:v1.0.0 \\
    BASE_DOMAIN=mycompany.com API_SUBDOMAIN=api HOSTED_ZONE_ID=Z9876543210XYZ \\
    ./deploy-all-stacks.sh

EOF
}

# Check for help flag
if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    usage
    exit 0
fi

# Run main deployment
main

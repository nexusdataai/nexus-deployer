#!/bin/bash

# Backend Stack Cleanup Script
# This script deletes all backend CloudFormation stacks in the correct reverse order

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

# Stack names
FOUNDATION_STACK="${CAPABILITY_NAME}-foundation-${ENVIRONMENT}"
IAM_ROLES_STACK="${CAPABILITY_NAME}-iam-roles-${ENVIRONMENT}"
NETWORK_STACK="${CAPABILITY_NAME}-network-${ENVIRONMENT}"
STORAGE_STACK="${CAPABILITY_NAME}-storage-${ENVIRONMENT}"
WXCC_STACK="${CAPABILITY_NAME}-wxcc-${ENVIRONMENT}"
REGIONAL_CERT_STACK="${CAPABILITY_NAME}-regional-cert-${ENVIRONMENT}"
SERVICE_STACK="${CAPABILITY_NAME}-service-${ENVIRONMENT}"
DOMAIN_STACK="${CAPABILITY_NAME}-domain-${ENVIRONMENT}"

# Cleanup flags
DELETE_FOUNDATION="${DELETE_FOUNDATION:-true}"
DELETE_IAM_ROLES="${DELETE_IAM_ROLES:-true}"
DELETE_NETWORK="${DELETE_NETWORK:-true}"
DELETE_STORAGE="${DELETE_STORAGE:-true}"
DELETE_WXCC="${DELETE_WXCC:-true}"
DELETE_REGIONAL_CERT="${DELETE_REGIONAL_CERT:-true}"
DELETE_SERVICE="${DELETE_SERVICE:-true}"
DELETE_DOMAIN="${DELETE_DOMAIN:-true}"

# Confirmation flag
SKIP_CONFIRMATION="${SKIP_CONFIRMATION:-false}"

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

# Function to wait for stack deletion
wait_for_deletion() {
    local stack_name=$1
    
    print_info "Waiting for stack ${stack_name} to be deleted..."
    
    aws cloudformation wait stack-delete-complete \
        --stack-name "${stack_name}" \
        --region "${AWS_REGION}" 2>/dev/null
    
    if [ $? -eq 0 ]; then
        print_success "Stack ${stack_name} deleted successfully"
        return 0
    else
        print_error "Stack ${stack_name} deletion failed or timed out"
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

# Function to delete stack
delete_stack() {
    local stack_name=$1
    
    if ! stack_exists "${stack_name}"; then
        print_warning "Stack ${stack_name} does not exist. Skipping..."
        return 0
    fi
    
    print_info "Deleting stack: ${stack_name}"
    
    aws cloudformation delete-stack \
        --stack-name "${stack_name}" \
        --region "${AWS_REGION}"
    
    wait_for_deletion "${stack_name}"
}

# Function to list stack resources
list_stack_resources() {
    local stack_name=$1
    
    if stack_exists "${stack_name}"; then
        print_info "Resources in ${stack_name}:"
        aws cloudformation list-stack-resources \
            --stack-name "${stack_name}" \
            --region "${AWS_REGION}" \
            --query 'StackResourceSummaries[*].[ResourceType,LogicalResourceId,PhysicalResourceId]' \
            --output table
    fi
}

# Function to check for retained resources
check_retained_resources() {
    print_warning "The following resources have DeletionPolicy: Retain and will NOT be deleted:"
    echo "  - S3 Buckets (data and backups)"
    echo "  - DynamoDB Tables (state)"
    echo "  - CloudWatch Log Groups"
    echo ""
    print_warning "You must manually delete these resources if needed."
}

# Confirmation prompt
confirm_deletion() {
    if [ "${SKIP_CONFIRMATION}" = "true" ]; then
        return 0
    fi
    
    echo ""
    print_warning "You are about to delete the following stacks:"
    [ "${DELETE_DOMAIN}" = "true" ] && echo "  - ${DOMAIN_STACK}"
    [ "${DELETE_SERVICE}" = "true" ] && echo "  - ${SERVICE_STACK}"
    [ "${DELETE_REGIONAL_CERT}" = "true" ] && echo "  - ${REGIONAL_CERT_STACK}"
    [ "${DELETE_WXCC}" = "true" ] && echo "  - ${WXCC_STACK}"
    [ "${DELETE_STORAGE}" = "true" ] && echo "  - ${STORAGE_STACK}"
    [ "${DELETE_NETWORK}" = "true" ] && echo "  - ${NETWORK_STACK}"
    [ "${DELETE_IAM_ROLES}" = "true" ] && echo "  - ${IAM_ROLES_STACK}"
    [ "${DELETE_FOUNDATION}" = "true" ] && echo "  - ${FOUNDATION_STACK}"
    echo ""
    print_warning "Capability: ${CAPABILITY_NAME}"
    print_warning "Environment: ${ENVIRONMENT}"
    print_warning "Region: ${AWS_REGION}"
    echo ""
    check_retained_resources
    echo ""
    
    read -p "Are you sure you want to proceed? (yes/no): " confirmation
    
    if [ "${confirmation}" != "yes" ]; then
        print_info "Deletion cancelled by user"
        exit 0
    fi
}

# Main cleanup function
main() {
    print_info "Starting backend stack cleanup"
    print_info "Capability: ${CAPABILITY_NAME}"
    print_info "Environment: ${ENVIRONMENT}"
    print_info "Region: ${AWS_REGION}"
    echo ""
    
    confirm_deletion
    
    # 1. Delete Domain Stack
    if [ "${DELETE_DOMAIN}" = "true" ]; then
        print_info "Step 1/8: Deleting Domain Stack"
        delete_stack "${DOMAIN_STACK}"
        echo ""
    else
        print_warning "Skipping Domain Stack deletion"
    fi
    
    # 2. Delete Service Stack
    if [ "${DELETE_SERVICE}" = "true" ]; then
        print_info "Step 2/8: Deleting Service Stack"
        delete_stack "${SERVICE_STACK}"
        echo ""
    else
        print_warning "Skipping Service Stack deletion"
    fi
    
    # 3. Delete Regional Certificate Stack (Optional)
    if [ "${DELETE_REGIONAL_CERT}" = "true" ]; then
        print_info "Step 3/8: Deleting Regional Certificate Stack"
        delete_stack "${REGIONAL_CERT_STACK}"
        echo ""
    else
        print_warning "Skipping Regional Certificate Stack deletion"
    fi
    
    # 4. Delete WXCC Stack (Webex Contact Center)
    if [ "${DELETE_WXCC}" = "true" ]; then
        print_info "Step 4/8: Deleting WXCC Stack (Webex Contact Center)"
        print_warning "Note: SSM parameters and Secrets will be deleted"
        delete_stack "${WXCC_STACK}"
        echo ""
    else
        print_warning "Skipping WXCC Stack deletion"
    fi
    
    # 5. Delete Storage Stack
    if [ "${DELETE_STORAGE}" = "true" ]; then
        print_info "Step 5/8: Deleting Storage Stack"
        print_warning "Note: S3 buckets and DynamoDB tables with Retain policy will not be deleted"
        delete_stack "${STORAGE_STACK}"
        echo ""
    else
        print_warning "Skipping Storage Stack deletion"
    fi
    
    # 6. Delete Network Stack
    if [ "${DELETE_NETWORK}" = "true" ]; then
        print_info "Step 6/8: Deleting Network Stack"
        delete_stack "${NETWORK_STACK}"
        echo ""
    else
        print_warning "Skipping Network Stack deletion"
    fi
    
    # 7. Delete IAM Roles Stack
    if [ "${DELETE_IAM_ROLES}" = "true" ]; then
        print_info "Step 7/8: Deleting IAM Roles Stack"
        delete_stack "${IAM_ROLES_STACK}"
        echo ""
    else
        print_warning "Skipping IAM Roles Stack deletion"
    fi
    
    # 8. Delete Foundation Stack
    if [ "${DELETE_FOUNDATION}" = "true" ]; then
        print_info "Step 8/8: Deleting Foundation Stack"
        print_warning "Note: CloudWatch Log Groups with Retain policy will not be deleted"
        delete_stack "${FOUNDATION_STACK}"
        echo ""
    else
        print_warning "Skipping Foundation Stack deletion"
    fi
    
    print_success "All stacks deleted successfully!"
    echo ""
    check_retained_resources
    echo ""
    print_info "To manually delete retained resources:"
    echo "  # Delete S3 buckets"
    echo "  aws s3 rb s3://${CAPABILITY_NAME}-${ENVIRONMENT}-data --force"
    echo "  aws s3 rb s3://${CAPABILITY_NAME}-${ENVIRONMENT}-backups --force"
    echo ""
    echo "  # Delete DynamoDB tables"
    echo "  aws dynamodb delete-table --table-name ${CAPABILITY_NAME}-${ENVIRONMENT}-state"
    echo "  aws dynamodb delete-table --table-name ${CAPABILITY_NAME}-${ENVIRONMENT}-sessions"
    echo "  aws dynamodb delete-table --table-name ${CAPABILITY_NAME}-${ENVIRONMENT}-wxcc-task-tracking"
    echo ""
    echo "  # Delete CloudWatch Log Groups"
    echo "  aws logs delete-log-group --log-group-name /ecs/${CAPABILITY_NAME}-${ENVIRONMENT}"
    echo "  aws logs delete-log-group --log-group-name /aws/application/${CAPABILITY_NAME}-${ENVIRONMENT}"
    echo ""
    echo "  # Delete WXCC Secrets (if not deleted by stack)"
    echo "  aws secretsmanager delete-secret --secret-id ${CAPABILITY_NAME}-${ENVIRONMENT}-webex-credentials --force-delete-without-recovery"
    echo "  aws secretsmanager delete-secret --secret-id ${CAPABILITY_NAME}-${ENVIRONMENT}-webex-tokens --force-delete-without-recovery"
    echo ""
    echo "  # Delete Glue resources (if not deleted by stack)"
    echo "  aws glue delete-table --database-name ${CAPABILITY_NAME}_${ENVIRONMENT}_wxcc_calls_db --name calls"
    echo "  aws glue delete-database --name ${CAPABILITY_NAME}_${ENVIRONMENT}_wxcc_calls_db"
}

# Print usage
usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Delete backend CloudFormation stacks in the correct reverse order.

Required Environment Variables:
  CAPABILITY_NAME       Name of the capability (e.g., my-capability)
  ENVIRONMENT          Environment name (dev, stage, prod)

Optional Environment Variables:
  AWS_REGION           AWS region (default: us-east-1)
  SKIP_CONFIRMATION    Skip confirmation prompt (default: false)

Deletion Flags (set to 'false' to skip):
  DELETE_FOUNDATION    Delete foundation stack (default: true)
  DELETE_IAM_ROLES     Delete IAM roles stack (default: true)
  DELETE_NETWORK       Delete network stack (default: true)
  DELETE_STORAGE       Delete storage stack (default: true)
  DELETE_WXCC          Delete WXCC stack (default: true)
  DELETE_REGIONAL_CERT Delete regional cert stack (default: true)
  DELETE_SERVICE       Delete service stack (default: true)
  DELETE_DOMAIN        Delete domain stack (default: true)

Examples:
  # Delete all stacks with confirmation
  CAPABILITY_NAME=my-app ENVIRONMENT=dev ./cleanup-all-stacks.sh

  # Delete all stacks without confirmation (dangerous!)
  CAPABILITY_NAME=my-app ENVIRONMENT=dev SKIP_CONFIRMATION=true ./cleanup-all-stacks.sh

  # Delete only service and domain stacks
  CAPABILITY_NAME=my-app ENVIRONMENT=dev \\
    DELETE_FOUNDATION=false DELETE_IAM_ROLES=false DELETE_NETWORK=false DELETE_STORAGE=false \\
    ./cleanup-all-stacks.sh

  # List resources before deletion
  CAPABILITY_NAME=my-app ENVIRONMENT=dev ./cleanup-all-stacks.sh --list

EOF
}

# Check for help flag
if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    usage
    exit 0
fi

# Check for list flag
if [ "$1" = "--list" ] || [ "$1" = "-l" ]; then
    print_info "Listing resources in all stacks..."
    echo ""
    list_stack_resources "${DOMAIN_STACK}"
    echo ""
    list_stack_resources "${SERVICE_STACK}"
    echo ""
    list_stack_resources "${REGIONAL_CERT_STACK}"
    echo ""
    list_stack_resources "${WXCC_STACK}"
    echo ""
    list_stack_resources "${STORAGE_STACK}"
    echo ""
    list_stack_resources "${NETWORK_STACK}"
    echo ""
    list_stack_resources "${IAM_ROLES_STACK}"
    echo ""
    list_stack_resources "${FOUNDATION_STACK}"
    exit 0
fi

# Run main cleanup
main

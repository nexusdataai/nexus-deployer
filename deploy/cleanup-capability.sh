#!/bin/bash

# Cleanup Script for Business Capability Deployment
# Removes all CloudFormation stacks and retained resources created by deploy-capability-layered.sh

set -e
set -o pipefail

# Script directory
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

# Default values
CONFIG_FILE=""
CAPABILITY_NAME=""
ENVIRONMENT=""
AWS_REGION=""
DRY_RUN="false"
FORCE="false"
VERBOSE="false"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_status() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

usage() {
  cat << EOF
Usage: $(basename "$0") [OPTIONS]

Cleans up all resources (both frontend and backend) created by the capability deployment script.

Deletes:
  - Frontend: CloudFront, S3, Cognito, WAF, CloudWatch Logs
  - Backend: ECS, ALB, VPC, Security Groups, RDS/DynamoDB, S3, CloudWatch Logs

OPTIONS:
  -c, --config FILE       Configuration file (YAML) - same as used for deployment
  -e, --environment ENV   Environment (dev|stage|prod)
  -n, --name NAME         Capability name
  -r, --region REGION     AWS region
  --dry-run               Show what would be deleted without actually deleting
  --force                 Skip confirmation prompts
  --verbose               Verbose output
  -h, --help              Display this help message

EXAMPLES:
  # Cleanup using config file
  $(basename "$0") -c config/prod-config.yaml

  # Cleanup with explicit parameters
  $(basename "$0") -n call-processing -e prod -r ap-southeast-1

  # Dry run to see what would be deleted
  $(basename "$0") -c config/prod-config.yaml --dry-run

EOF
}

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
      -r|--region)
        AWS_REGION="$2"
        shift 2
        ;;
      --dry-run)
        DRY_RUN="true"
        shift
        ;;
      --force)
        FORCE="true"
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

load_config() {
  local config_file="$1"
  
  if [ ! -f "$config_file" ]; then
    print_error "Configuration file not found: $config_file"
    exit 1
  fi
  
  print_status "Loading configuration from: $config_file"
  
  if command -v yq >/dev/null 2>&1; then
    CAPABILITY_NAME=$(yq eval '.capability.name' "$config_file")
    ENVIRONMENT=$(yq eval '.target.environment' "$config_file")
    AWS_REGION=$(yq eval '.target.region' "$config_file")
  elif command -v python3 >/dev/null 2>&1; then
    eval "$(python3 -c "
import yaml
with open('$config_file', 'r') as f:
    config = yaml.safe_load(f)
    print(f\"CAPABILITY_NAME='{config['capability']['name']}'\")
    print(f\"ENVIRONMENT='{config['target']['environment']}'\")
    print(f\"AWS_REGION='{config['target']['region']}'\")
")"
  else
    print_error "Neither yq nor python3 with PyYAML is available"
    exit 1
  fi
  
  print_success "Configuration loaded"
}

validate_inputs() {
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
}

stack_exists() {
  local stack_name="$1"
  local region="$2"
  aws cloudformation describe-stacks --stack-name "$stack_name" --region "$region" >/dev/null 2>&1
}

delete_stack() {
  local stack_name="$1"
  local region="$2"
  
  if ! stack_exists "$stack_name" "$region"; then
    print_warning "Stack does not exist: $stack_name (region: $region)"
    return 0
  fi
  
  print_status "Deleting stack: $stack_name (region: $region)"
  
  if [ "$DRY_RUN" == "true" ]; then
    print_status "DRY RUN: Would delete stack $stack_name"
    return 0
  fi
  
  aws cloudformation delete-stack --stack-name "$stack_name" --region "$region"
  
  print_status "Waiting for stack deletion to complete..."
  if aws cloudformation wait stack-delete-complete --stack-name "$stack_name" --region "$region" 2>/dev/null; then
    print_success "Stack deleted: $stack_name"
  else
    print_error "Stack deletion failed or timed out: $stack_name"
    return 1
  fi
}

empty_and_delete_bucket() {
  local bucket_name="$1"
  
  # Check if bucket exists
  if ! aws s3api head-bucket --bucket "$bucket_name" 2>/dev/null; then
    print_warning "S3 bucket does not exist: $bucket_name"
    return 0
  fi
  
  print_status "Emptying S3 bucket: $bucket_name"
  
  if [ "$DRY_RUN" == "true" ]; then
    local count=$(aws s3 ls "s3://${bucket_name}" --recursive --summarize 2>/dev/null | grep "Total Objects" | awk '{print $3}')
    print_status "DRY RUN: Would delete ${count:-0} objects from $bucket_name"
    return 0
  fi
  
  # Delete all objects (including versions)
  aws s3 rm "s3://${bucket_name}" --recursive 2>/dev/null || true
  
  # Delete all object versions (for versioned buckets)
  local versions=$(aws s3api list-object-versions --bucket "$bucket_name" --query 'Versions[].{Key:Key,VersionId:VersionId}' --output json 2>/dev/null)
  if [ -n "$versions" ] && [ "$versions" != "null" ] && [ "$versions" != "[]" ]; then
    echo "$versions" | python3 -c "
import sys, json
versions = json.load(sys.stdin)
if versions:
    for v in versions:
        print(f\"{v['Key']} {v['VersionId']}\")
" 2>/dev/null | while read -r key version; do
      aws s3api delete-object --bucket "$bucket_name" --key "$key" --version-id "$version" 2>/dev/null || true
    done
  fi
  
  # Delete all delete markers
  local markers=$(aws s3api list-object-versions --bucket "$bucket_name" --query 'DeleteMarkers[].{Key:Key,VersionId:VersionId}' --output json 2>/dev/null)
  if [ -n "$markers" ] && [ "$markers" != "null" ] && [ "$markers" != "[]" ]; then
    echo "$markers" | python3 -c "
import sys, json
markers = json.load(sys.stdin)
if markers:
    for m in markers:
        print(f\"{m['Key']} {m['VersionId']}\")
" 2>/dev/null | while read -r key version; do
      aws s3api delete-object --bucket "$bucket_name" --key "$key" --version-id "$version" 2>/dev/null || true
    done
  fi
  
  # Delete the bucket
  print_status "Deleting S3 bucket: $bucket_name"
  if aws s3 rb "s3://${bucket_name}" --force 2>/dev/null; then
    print_success "S3 bucket deleted: $bucket_name"
  else
    print_warning "Could not delete bucket $bucket_name (may already be empty or deleted)"
  fi
}

delete_cloudfront_distribution() {
  local distribution_id="$1"
  
  if [ -z "$distribution_id" ]; then
    return 0
  fi
  
  print_status "Checking CloudFront distribution: $distribution_id"
  
  # Get distribution config
  local etag=$(aws cloudfront get-distribution --id "$distribution_id" --query 'ETag' --output text 2>/dev/null)
  local enabled=$(aws cloudfront get-distribution --id "$distribution_id" --query 'Distribution.DistributionConfig.Enabled' --output text 2>/dev/null)
  
  if [ -z "$etag" ]; then
    print_warning "CloudFront distribution not found: $distribution_id"
    return 0
  fi
  
  if [ "$DRY_RUN" == "true" ]; then
    print_status "DRY RUN: Would disable and delete CloudFront distribution $distribution_id"
    return 0
  fi
  
  # Disable if enabled
  if [ "$enabled" == "true" ]; then
    print_status "Disabling CloudFront distribution..."
    local config=$(aws cloudfront get-distribution-config --id "$distribution_id" --output json)
    local new_config=$(echo "$config" | python3 -c "
import sys, json
data = json.load(sys.stdin)
data['DistributionConfig']['Enabled'] = False
print(json.dumps(data['DistributionConfig']))
")
    aws cloudfront update-distribution --id "$distribution_id" --if-match "$etag" --distribution-config "$new_config" >/dev/null
    
    print_status "Waiting for distribution to be disabled (this may take several minutes)..."
    aws cloudfront wait distribution-deployed --id "$distribution_id"
    
    # Get new etag after update
    etag=$(aws cloudfront get-distribution --id "$distribution_id" --query 'ETag' --output text)
  fi
  
  # Delete distribution
  print_status "Deleting CloudFront distribution..."
  aws cloudfront delete-distribution --id "$distribution_id" --if-match "$etag"
  print_success "CloudFront distribution deleted: $distribution_id"
}

disable_alb_deletion_protection() {
  local stack_name="$1"
  local region="$2"
  
  print_status "Checking for ALB in stack: $stack_name"
  
  # Get ALB ARN from stack resources
  local alb_arn=$(aws cloudformation describe-stack-resources \
    --stack-name "$stack_name" \
    --region "$region" \
    --query 'StackResources[?ResourceType==`AWS::ElasticLoadBalancingV2::LoadBalancer`].PhysicalResourceId' \
    --output text 2>/dev/null)
  
  if [ -z "$alb_arn" ] || [ "$alb_arn" == "None" ]; then
    print_status "No ALB found in stack"
    return 0
  fi
  
  if [ "$DRY_RUN" == "true" ]; then
    print_status "DRY RUN: Would disable deletion protection on ALB: $alb_arn"
    return 0
  fi
  
  print_status "Disabling deletion protection on ALB: $alb_arn"
  aws elbv2 modify-load-balancer-attributes \
    --load-balancer-arn "$alb_arn" \
    --attributes Key=deletion_protection.enabled,Value=false \
    --region "$region" >/dev/null 2>&1
  
  print_success "Disabled deletion protection on ALB"
}
  
empty_ecr_repository() {
  local repository_name="$1"
  local region="$2"
  
  if [ -z "$repository_name" ]; then
    return 0
  fi
  
  print_status "Checking ECR repository: $repository_name"
  
  # Check if repository exists
  if ! aws ecr describe-repositories --repository-names "$repository_name" --region "$region" >/dev/null 2>&1; then
    print_status "ECR repository not found: $repository_name"
    return 0
  fi
  
  if [ "$DRY_RUN" == "true" ]; then
    local image_count=$(aws ecr list-images --repository-name "$repository_name" --region "$region" --query 'length(imageIds)' --output text 2>/dev/null || echo "0")
    print_status "DRY RUN: Would delete $image_count images from ECR repository $repository_name"
    return 0
  fi
  
  print_status "Deleting all images from ECR repository: $repository_name"
  
  # Get all image IDs
  local image_ids=$(aws ecr list-images --repository-name "$repository_name" --region "$region" --query 'imageIds[*]' --output json 2>/dev/null)
  
  if [ -n "$image_ids" ] && [ "$image_ids" != "[]" ] && [ "$image_ids" != "null" ]; then
    # Delete all images
    if aws ecr batch-delete-image --repository-name "$repository_name" --region "$region" --image-ids "$image_ids" >/dev/null 2>&1; then
      print_success "Deleted images from ECR repository: $repository_name"
    else
      print_warning "Could not delete some images from ECR repository"
    fi
  else
    print_status "No images found in ECR repository"
  fi
}

cleanup_route53_records() {
  local hosted_zone_id="$1"
  local domain_name="$2"
  
  if [ -z "$hosted_zone_id" ] || [ -z "$domain_name" ]; then
    return 0
  fi
  
  print_status "Checking Route53 records for: $domain_name"
  
  # List records matching the domain
  local records=$(aws route53 list-resource-record-sets \
    --hosted-zone-id "$hosted_zone_id" \
    --query "ResourceRecordSets[?Name=='${domain_name}.']" \
    --output json 2>/dev/null)
  
  if [ -z "$records" ] || [ "$records" == "[]" ]; then
    print_status "No Route53 records found for $domain_name"
    return 0
  fi
  
  if [ "$DRY_RUN" == "true" ]; then
    print_status "DRY RUN: Would delete Route53 records for $domain_name"
    return 0
  fi
  
  # Route53 records are usually deleted with the CloudFormation stack
  # This is a safety cleanup for any orphaned records
  print_status "Route53 records will be cleaned up with stack deletion"
}

main() {
  print_status "=== Capability Cleanup Script ==="
  print_status "Time: $(date)"
  
  parse_arguments "$@"
  
  # Load config if provided
  if [ -n "$CONFIG_FILE" ]; then
    load_config "$CONFIG_FILE"
  fi
  
  validate_inputs
  
  # Stack names
  local stack_prefix="${CAPABILITY_NAME}-${ENVIRONMENT}"
  
  # Frontend stacks
  local global_stack="${stack_prefix}-frontend-global"
  local cognito_stack="${stack_prefix}-frontend-cognito"
  local regional_stack="${stack_prefix}-frontend-regional"
  
  # Backend stacks
  local backend_service="${stack_prefix}-backend-service"
  local backend_network="${stack_prefix}-backend-network"
  local backend_storage="${stack_prefix}-backend-storage"
  local backend_foundation="${stack_prefix}-backend-foundation"
  local backend_regional_cert="${stack_prefix}-backend-regional-cert"
  
  # S3 bucket names (these have DeletionPolicy: Retain)
  local frontend_bucket="${CAPABILITY_NAME}-${ENVIRONMENT}-frontend"
  local logs_bucket="${CAPABILITY_NAME}-${ENVIRONMENT}-cloudfront-logs"
  local data_bucket="${CAPABILITY_NAME}-${ENVIRONMENT}-data"
  local backup_bucket="${CAPABILITY_NAME}-${ENVIRONMENT}-backups"
  local alb_logs_bucket="${CAPABILITY_NAME}-${ENVIRONMENT}-alb-logs"
  
  print_status ""
  print_status "Cleanup Configuration:"
  print_status "  Capability: $CAPABILITY_NAME"
  print_status "  Environment: $ENVIRONMENT"
  print_status "  Region: $AWS_REGION"
  print_status "  Dry Run: $DRY_RUN"
  print_status ""
  print_status "Resources to be deleted:"
  print_status ""
  print_status "Frontend Stacks:"
  print_status "  - Stack: $regional_stack (region: $AWS_REGION)"
  print_status "  - Stack: $cognito_stack (region: $AWS_REGION)"
  print_status "  - Stack: $global_stack (region: us-east-1)"
  print_status "  - S3 Bucket: $frontend_bucket"
  print_status "  - S3 Bucket: $logs_bucket (if exists)"
  print_status ""
  print_status "Backend Stacks:"
  print_status "  - Stack: $backend_service (region: $AWS_REGION)"
  print_status "  - Stack: $backend_network (region: $AWS_REGION)"
  print_status "  - Stack: $backend_storage (region: $AWS_REGION)"
  print_status "  - Stack: $backend_foundation (region: $AWS_REGION)"
  print_status "  - Stack: $backend_regional_cert (region: $AWS_REGION, if exists)"
  print_status "  - S3 Bucket: $data_bucket"
  print_status "  - S3 Bucket: $backup_bucket"
  print_status "  - S3 Bucket: $alb_logs_bucket (if exists)"
  print_status ""
  
  # Confirmation prompt
  if [ "$FORCE" != "true" ] && [ "$DRY_RUN" != "true" ]; then
    read -p "Are you sure you want to delete all these resources? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
      print_status "Cleanup cancelled"
      exit 0
    fi
  fi
  
  # FRONTEND CLEANUP
  print_status ""
  print_status "=== FRONTEND CLEANUP ==="
  
  # Step 1: Delete regional stack first (depends on global stack exports)
  print_status ""
  print_status "=== Step 1: Deleting Frontend Regional Stack ==="
  delete_stack "$regional_stack" "$AWS_REGION"
  
  # Step 2: Delete Cognito stack (depends on global stack for domain name)
  print_status ""
  print_status "=== Step 2: Deleting Frontend Cognito Stack ==="
  delete_stack "$cognito_stack" "$AWS_REGION"
  
  # Step 3: Delete global stack
  print_status ""
  print_status "=== Step 3: Deleting Frontend Global Stack ==="
  delete_stack "$global_stack" "us-east-1"
  
  # Step 4: Clean up retained frontend S3 buckets
  print_status ""
  print_status "=== Step 4: Cleaning Up Frontend S3 Buckets ==="
  empty_and_delete_bucket "$frontend_bucket"
  empty_and_delete_bucket "$logs_bucket"
  
  # Step 5: Clean up frontend CloudWatch log groups
  print_status ""
  print_status "=== Step 5: Cleaning Up Frontend CloudWatch Log Groups ==="
  local waf_log_group="aws-waf-logs-${CAPABILITY_NAME}-${ENVIRONMENT}-frontend"
  if [ "$DRY_RUN" == "true" ]; then
    print_status "DRY RUN: Would delete log group $waf_log_group"
  else
    if aws logs delete-log-group --log-group-name "$waf_log_group" --region us-east-1 2>/dev/null; then
      print_success "Deleted log group: $waf_log_group"
    else
      print_status "Log group not found or already deleted: $waf_log_group"
    fi
  fi
  
  # BACKEND CLEANUP
  print_status ""
  print_status "=== BACKEND CLEANUP ==="
  
  # Step 6: Disable ALB deletion protection and delete backend service stack
  print_status ""
  print_status "=== Step 6: Deleting Backend Service Stack ==="
  disable_alb_deletion_protection "$backend_service" "$AWS_REGION"
  delete_stack "$backend_service" "$AWS_REGION"
  
  # Step 7: Delete backend network stack
  print_status ""
  print_status "=== Step 7: Deleting Backend Network Stack ==="
  delete_stack "$backend_network" "$AWS_REGION"
  
  # Step 8: Empty ECR repository before deleting storage stack
  print_status ""
  print_status "=== Step 8: Emptying ECR Repository ==="
  local ecr_repo="${CAPABILITY_NAME}-${ENVIRONMENT}"
  empty_ecr_repository "$ecr_repo" "$AWS_REGION"
  
  # Step 9: Delete backend storage stack
  print_status ""
  print_status "=== Step 9: Deleting Backend Storage Stack ==="
  delete_stack "$backend_storage" "$AWS_REGION"
  
  # Step 10: Delete backend foundation stack
  print_status ""
  print_status "=== Step 10: Deleting Backend Foundation Stack ==="
  delete_stack "$backend_foundation" "$AWS_REGION"
  
  # Step 11: Delete backend regional cert stack (if exists, us-east-1 regions skip this)
  if [ "$AWS_REGION" != "us-east-1" ]; then
    print_status ""
    print_status "=== Step 11: Deleting Backend Regional Certificate Stack ==="
    delete_stack "$backend_regional_cert" "$AWS_REGION"
  fi
  
  # Step 12: Clean up DynamoDB tables
  print_status ""
  print_status "=== Step 12: Cleaning Up DynamoDB Tables ==="
  local state_table="${CAPABILITY_NAME}-${ENVIRONMENT}-state"
  local sessions_table="${CAPABILITY_NAME}-${ENVIRONMENT}-sessions"
  
  for table in "$state_table" "$sessions_table"; do
    if [ "$DRY_RUN" == "true" ]; then
      print_status "DRY RUN: Would delete DynamoDB table $table"
    else
      if aws dynamodb describe-table --table-name "$table" --region "$AWS_REGION" >/dev/null 2>&1; then
        print_status "Deleting DynamoDB table: $table"
        if aws dynamodb delete-table --table-name "$table" --region "$AWS_REGION" >/dev/null 2>&1; then
          print_success "Deleted DynamoDB table: $table"
        else
          print_warning "Could not delete table: $table"
        fi
      else
        print_status "DynamoDB table not found or already deleted: $table"
      fi
    fi
  done
  
  # Step 13: Clean up retained backend S3 buckets
  print_status ""
  print_status "=== Step 13: Cleaning Up Backend S3 Buckets ==="
  empty_and_delete_bucket "$data_bucket"
  empty_and_delete_bucket "$backup_bucket"
  empty_and_delete_bucket "$alb_logs_bucket"
  
  # Step 14: Clean up backend CloudWatch log groups
  print_status ""
  print_status "=== Step 14: Cleaning Up Backend CloudWatch Log Groups ==="
  local ecs_log_group="/ecs/${CAPABILITY_NAME}-${ENVIRONMENT}"
  local app_log_group="/aws/application/${CAPABILITY_NAME}-${ENVIRONMENT}"
  
  if [ "$DRY_RUN" == "true" ]; then
    print_status "DRY RUN: Would delete log groups: $ecs_log_group, $app_log_group"
  else
    if aws logs delete-log-group --log-group-name "$ecs_log_group" --region "$AWS_REGION" 2>/dev/null; then
      print_success "Deleted log group: $ecs_log_group"
    else
      print_status "Log group not found or already deleted: $ecs_log_group"
    fi
    
    if aws logs delete-log-group --log-group-name "$app_log_group" --region "$AWS_REGION" 2>/dev/null; then
      print_success "Deleted log group: $app_log_group"
    else
      print_status "Log group not found or already deleted: $app_log_group"
    fi
  fi
  
  print_status ""
  if [ "$DRY_RUN" == "true" ]; then
    print_success "=== Dry Run Complete ==="
    print_status "No resources were actually deleted. Remove --dry-run to perform actual cleanup."
  else
    print_success "=== Cleanup Complete ==="
  fi
}

main "$@"


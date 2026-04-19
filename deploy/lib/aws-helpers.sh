#!/bin/bash

# AWS Helper Functions
# Provides utility functions for AWS operations

# Source logging if not already loaded
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
source "${SCRIPT_DIR}/logging.sh" 2>/dev/null || true

# Check if AWS CLI is installed
check_aws_cli() {
  if ! command -v aws >/dev/null 2>&1; then
    print_error "AWS CLI is not installed"
    print_status "Install with: pip install awscli"
    return 1
  fi
  
  # Check AWS CLI version
  local aws_version=$(aws --version 2>&1 | cut -d' ' -f1 | cut -d'/' -f2)
  print_debug "AWS CLI version: $aws_version"
  
  return 0
}

# Check AWS credentials
check_aws_credentials() {
  if ! aws sts get-caller-identity >/dev/null 2>&1; then
    print_error "AWS credentials are not configured or expired"
    print_status "Configure with: aws configure"
    return 1
  fi
  
  return 0
}

# Get current AWS account ID
get_account_id() {
  aws sts get-caller-identity --query 'Account' --output text
}

# Get current AWS region
get_current_region() {
  aws configure get region || echo "us-east-1"
}

# Assume IAM role
assume_role() {
  local role_arn="$1"
  local session_name="${2:-deployment-session-$(date +%s)}"
  local duration="${3:-3600}"
  
  print_debug "Assuming role: $role_arn"
  
  local credentials
  credentials=$(aws sts assume-role \
    --role-arn "$role_arn" \
    --role-session-name "$session_name" \
    --duration-seconds "$duration" \
    --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' \
    --output text 2>/dev/null)
  
  if [ $? -ne 0 ]; then
    print_error "Failed to assume role: $role_arn"
    return 1
  fi
  
  export AWS_ACCESS_KEY_ID=$(echo "$credentials" | cut -f1)
  export AWS_SECRET_ACCESS_KEY=$(echo "$credentials" | cut -f2)
  export AWS_SESSION_TOKEN=$(echo "$credentials" | cut -f3)
  
  print_success "Role assumed successfully"
  return 0
}

# Clear assumed role credentials
clear_assumed_role() {
  unset AWS_ACCESS_KEY_ID
  unset AWS_SECRET_ACCESS_KEY
  unset AWS_SESSION_TOKEN
  print_status "Cleared assumed role credentials"
}

# Check if S3 bucket exists
s3_bucket_exists() {
  local bucket_name="$1"
  
  aws s3api head-bucket --bucket "$bucket_name" 2>/dev/null
  return $?
}

# Create S3 bucket with proper settings
create_s3_bucket() {
  local bucket_name="$1"
  local region="${2:-us-east-1}"
  
  if s3_bucket_exists "$bucket_name"; then
    print_status "S3 bucket already exists: $bucket_name"
    return 0
  fi
  
  print_status "Creating S3 bucket: $bucket_name"
  
  # Create bucket (location constraint not needed for us-east-1)
  if [ "$region" == "us-east-1" ]; then
    aws s3api create-bucket \
      --bucket "$bucket_name" \
      --region "$region"
  else
    aws s3api create-bucket \
      --bucket "$bucket_name" \
      --region "$region" \
      --create-bucket-configuration LocationConstraint="$region"
  fi
  
  if [ $? -ne 0 ]; then
    print_error "Failed to create S3 bucket"
    return 1
  fi
  
  # Enable versioning
  aws s3api put-bucket-versioning \
    --bucket "$bucket_name" \
    --versioning-configuration Status=Enabled
  
  # Enable encryption
  aws s3api put-bucket-encryption \
    --bucket "$bucket_name" \
    --server-side-encryption-configuration '{
      "Rules": [{
        "ApplyServerSideEncryptionByDefault": {
          "SSEAlgorithm": "AES256"
        }
      }]
    }'
  
  print_success "S3 bucket created successfully"
  return 0
}

# Upload file to S3
upload_to_s3() {
  local local_path="$1"
  local s3_uri="$2"
  local extra_args="${3:-}"
  
  print_status "Uploading to S3: $s3_uri"
  
  if [ -d "$local_path" ]; then
    aws s3 sync "$local_path" "$s3_uri" $extra_args
  else
    aws s3 cp "$local_path" "$s3_uri" $extra_args
  fi
  
  if [ $? -eq 0 ]; then
    print_success "Upload successful"
    return 0
  else
    print_error "Upload failed"
    return 1
  fi
}

# Download from S3
download_from_s3() {
  local s3_uri="$1"
  local local_path="$2"
  local extra_args="${3:-}"
  
  print_status "Downloading from S3: $s3_uri"
  
  aws s3 cp "$s3_uri" "$local_path" $extra_args
  
  if [ $? -eq 0 ]; then
    print_success "Download successful"
    return 0
  else
    print_error "Download failed"
    return 1
  fi
}

# Check if ECR repository exists
ecr_repository_exists() {
  local repo_name="$1"
  local region="${2:-us-east-1}"
  
  aws ecr describe-repositories \
    --repository-names "$repo_name" \
    --region "$region" >/dev/null 2>&1
  
  return $?
}

# Create ECR repository
create_ecr_repository() {
  local repo_name="$1"
  local region="${2:-us-east-1}"
  
  if ecr_repository_exists "$repo_name" "$region"; then
    print_status "ECR repository already exists: $repo_name"
    return 0
  fi
  
  print_status "Creating ECR repository: $repo_name"
  
  aws ecr create-repository \
    --repository-name "$repo_name" \
    --region "$region" \
    --image-scanning-configuration scanOnPush=true \
    --encryption-configuration encryptionType=AES256
  
  if [ $? -eq 0 ]; then
    print_success "ECR repository created successfully"
    return 0
  else
    print_error "Failed to create ECR repository"
    return 1
  fi
}

# Login to ECR
ecr_login() {
  local region="${1:-us-east-1}"
  local account_id="${2:-$(get_account_id)}"
  
  print_status "Logging in to ECR"
  
  aws ecr get-login-password --region "$region" | \
    docker login --username AWS --password-stdin "${account_id}.dkr.ecr.${region}.amazonaws.com"
  
  if [ $? -eq 0 ]; then
    print_success "ECR login successful"
    return 0
  else
    print_error "ECR login failed"
    return 1
  fi
}

# Tag and push Docker image to ECR
push_to_ecr() {
  local local_image="$1"
  local ecr_uri="$2"
  
  print_status "Tagging image for ECR"
  docker tag "$local_image" "$ecr_uri"
  
  print_status "Pushing image to ECR: $ecr_uri"
  docker push "$ecr_uri"
  
  if [ $? -eq 0 ]; then
    print_success "Image pushed successfully"
    return 0
  else
    print_error "Failed to push image"
    return 1
  fi
}

# Check if Route53 hosted zone exists
hosted_zone_exists() {
  local domain_name="$1"
  
  aws route53 list-hosted-zones-by-name \
    --query "HostedZones[?Name=='${domain_name}.'].Id" \
    --output text | grep -q .
  
  return $?
}

# Get Route53 hosted zone ID
get_hosted_zone_id() {
  local domain_name="$1"
  
  aws route53 list-hosted-zones-by-name \
    --query "HostedZones[?Name=='${domain_name}.'].Id" \
    --output text | cut -d'/' -f3
}

# Create or update Route53 record
upsert_route53_record() {
  local hosted_zone_id="$1"
  local record_name="$2"
  local record_type="$3"
  local record_value="$4"
  local ttl="${5:-300}"
  
  print_status "Updating Route53 record: $record_name"
  
  local change_batch=$(cat <<EOF
{
  "Changes": [{
    "Action": "UPSERT",
    "ResourceRecordSet": {
      "Name": "$record_name",
      "Type": "$record_type",
      "TTL": $ttl,
      "ResourceRecords": [{
        "Value": "$record_value"
      }]
    }
  }]
}
EOF
)
  
  aws route53 change-resource-record-sets \
    --hosted-zone-id "$hosted_zone_id" \
    --change-batch "$change_batch"
  
  if [ $? -eq 0 ]; then
    print_success "Route53 record updated"
    return 0
  else
    print_error "Failed to update Route53 record"
    return 1
  fi
}

# Create Route53 alias record
create_route53_alias() {
  local hosted_zone_id="$1"
  local record_name="$2"
  local alias_target="$3"
  local alias_zone_id="$4"
  
  print_status "Creating Route53 alias: $record_name -> $alias_target"
  
  local change_batch=$(cat <<EOF
{
  "Changes": [{
    "Action": "UPSERT",
    "ResourceRecordSet": {
      "Name": "$record_name",
      "Type": "A",
      "AliasTarget": {
        "HostedZoneId": "$alias_zone_id",
        "DNSName": "$alias_target",
        "EvaluateTargetHealth": true
      }
    }
  }]
}
EOF
)
  
  aws route53 change-resource-record-sets \
    --hosted-zone-id "$hosted_zone_id" \
    --change-batch "$change_batch"
  
  if [ $? -eq 0 ]; then
    print_success "Route53 alias created"
    return 0
  else
    print_error "Failed to create Route53 alias"
    return 1
  fi
}

# Invalidate CloudFront distribution
invalidate_cloudfront() {
  local distribution_id="$1"
  local paths="${2:-/*}"
  
  print_status "Creating CloudFront invalidation"
  
  aws cloudfront create-invalidation \
    --distribution-id "$distribution_id" \
    --paths "$paths" \
    --query 'Invalidation.Id' \
    --output text
  
  if [ $? -eq 0 ]; then
    print_success "CloudFront invalidation created"
    return 0
  else
    print_error "Failed to create invalidation"
    return 1
  fi
}

# Check if Lambda function exists
lambda_exists() {
  local function_name="$1"
  local region="${2:-us-east-1}"
  
  aws lambda get-function \
    --function-name "$function_name" \
    --region "$region" >/dev/null 2>&1
  
  return $?
}

# Get VPC details
get_vpc_details() {
  local vpc_id="$1"
  
  aws ec2 describe-vpcs \
    --vpc-ids "$vpc_id" \
    --query 'Vpcs[0]' \
    --output json
}

# Get subnet details
get_subnet_details() {
  local subnet_ids="$1"
  
  aws ec2 describe-subnets \
    --subnet-ids $subnet_ids \
    --query 'Subnets[]' \
    --output json
}

# Check ECS service status
check_ecs_service_status() {
  local cluster_name="$1"
  local service_name="$2"
  local region="${3:-us-east-1}"
  
  aws ecs describe-services \
    --cluster "$cluster_name" \
    --services "$service_name" \
    --region "$region" \
    --query 'services[0].status' \
    --output text
}

# Wait for ECS service to be stable
wait_for_ecs_service() {
  local cluster_name="$1"
  local service_name="$2"
  local region="${3:-us-east-1}"
  local max_wait="${4:-600}"  # 10 minutes default
  
  print_status "Waiting for ECS service to stabilize..."
  
  aws ecs wait services-stable \
    --cluster "$cluster_name" \
    --services "$service_name" \
    --region "$region" \
    --waiter-config MaxAttempts=$((max_wait/30))
  
  if [ $? -eq 0 ]; then
    print_success "ECS service is stable"
    return 0
  else
    print_error "ECS service failed to stabilize"
    return 1
  fi
}

# Export functions
export -f check_aws_cli check_aws_credentials get_account_id get_current_region
export -f assume_role clear_assumed_role
export -f s3_bucket_exists create_s3_bucket upload_to_s3 download_from_s3
export -f ecr_repository_exists create_ecr_repository ecr_login push_to_ecr
export -f hosted_zone_exists get_hosted_zone_id upsert_route53_record create_route53_alias
export -f invalidate_cloudfront lambda_exists
export -f get_vpc_details get_subnet_details
export -f check_ecs_service_status wait_for_ecs_service

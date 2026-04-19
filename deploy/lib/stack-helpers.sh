#!/bin/bash

# CloudFormation Stack Helper Functions
# Provides utility functions for CloudFormation operations

# Source logging if not already loaded
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
source "${SCRIPT_DIR}/logging.sh" 2>/dev/null || true

# Check if CloudFormation stack exists
stack_exists() {
  local stack_name="$1"
  local region="${2:-us-east-1}"
  
  aws cloudformation describe-stacks \
    --stack-name "$stack_name" \
    --region "$region" >/dev/null 2>&1
  
  return $?
}

# Get stack status
get_stack_status() {
  local stack_name="$1"
  local region="${2:-us-east-1}"
  
  aws cloudformation describe-stacks \
    --stack-name "$stack_name" \
    --region "$region" \
    --query 'Stacks[0].StackStatus' \
    --output text 2>/dev/null
}

# Check if stack is in a stable state
is_stack_stable() {
  local stack_name="$1"
  local region="${2:-us-east-1}"
  
  local status=$(get_stack_status "$stack_name" "$region")
  
  case "$status" in
    CREATE_COMPLETE|UPDATE_COMPLETE|UPDATE_ROLLBACK_COMPLETE)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

# Wait for stack operation to complete
wait_for_stack() {
  local stack_name="$1"
  local operation="$2"  # create, update, delete
  local region="${3:-us-east-1}"
  local max_wait="${4:-1800}"  # 30 minutes default
  
  print_status "Waiting for stack $operation to complete: $stack_name"
  
  local wait_condition=""
  case "$operation" in
    create)
      wait_condition="stack-create-complete"
      ;;
    update)
      wait_condition="stack-update-complete"
      ;;
    delete)
      wait_condition="stack-delete-complete"
      ;;
    *)
      print_error "Unknown operation: $operation"
      return 1
      ;;
  esac
  
  aws cloudformation wait "$wait_condition" \
    --stack-name "$stack_name" \
    --region "$region"
  
  if [ $? -eq 0 ]; then
    print_success "Stack $operation completed successfully"
    return 0
  else
    print_error "Stack $operation failed or timed out"
    return 1
  fi
}

# Create CloudFormation stack
create_stack() {
  local stack_name="$1"
  local template="$2"
  local parameters="$3"
  local region="${4:-us-east-1}"
  local capabilities="${5:-CAPABILITY_IAM CAPABILITY_NAMED_IAM}"
  
  print_status "Creating stack: $stack_name"
  
  local cmd="aws cloudformation create-stack"
  cmd="$cmd --stack-name $stack_name"
  cmd="$cmd --region $region"
  
  # Handle template (file or URL)
  if [[ "$template" == http* ]]; then
    cmd="$cmd --template-url $template"
  else
    cmd="$cmd --template-body file://$template"
  fi
  
  # Add parameters if provided
  if [ -n "$parameters" ]; then
    cmd="$cmd --parameters $parameters"
  fi
  
  # Add capabilities
  if [ -n "$capabilities" ]; then
    cmd="$cmd --capabilities $capabilities"
  fi
  
  # Execute command
  local stack_id
  stack_id=$(eval "$cmd --query 'StackId' --output text")
  
  if [ $? -eq 0 ]; then
    print_success "Stack creation initiated: $stack_id"
    return 0
  else
    print_error "Failed to create stack"
    return 1
  fi
}

# Update CloudFormation stack
update_stack() {
  local stack_name="$1"
  local template="$2"
  local parameters="$3"
  local region="${4:-us-east-1}"
  local capabilities="${5:-CAPABILITY_IAM CAPABILITY_NAMED_IAM}"
  
  print_status "Updating stack: $stack_name"
  
  local cmd="aws cloudformation update-stack"
  cmd="$cmd --stack-name $stack_name"
  cmd="$cmd --region $region"
  
  # Handle template (file or URL)
  if [[ "$template" == http* ]]; then
    cmd="$cmd --template-url $template"
  else
    cmd="$cmd --template-body file://$template"
  fi
  
  # Add parameters if provided
  if [ -n "$parameters" ]; then
    cmd="$cmd --parameters $parameters"
  fi
  
  # Add capabilities
  if [ -n "$capabilities" ]; then
    cmd="$cmd --capabilities $capabilities"
  fi
  
  # Execute command
  local stack_id
  stack_id=$(eval "$cmd --query 'StackId' --output text" 2>&1)
  
  if [ $? -eq 0 ]; then
    print_success "Stack update initiated"
    return 0
  elif echo "$stack_id" | grep -q "No updates are to be performed"; then
    print_status "No updates required for stack"
    return 0
  else
    print_error "Failed to update stack"
    return 1
  fi
}

# Deploy CloudFormation stack (create or update)
deploy_stack() {
  local stack_name="$1"
  local template="$2"
  local parameters="$3"
  local region="${4:-us-east-1}"
  local capabilities="${5:-CAPABILITY_IAM CAPABILITY_NAMED_IAM}"
  
  # Use AWS CLI deploy command for idempotent operations
  print_status "Deploying stack: $stack_name"
  
  local cmd="aws cloudformation deploy"
  cmd="$cmd --stack-name $stack_name"
  cmd="$cmd --template-file $template"
  cmd="$cmd --region $region"
  cmd="$cmd --no-fail-on-empty-changeset"
  
  # Add parameters if provided
  if [ -n "$parameters" ]; then
    cmd="$cmd --parameter-overrides $parameters"
  fi
  
  # Add capabilities
  if [ -n "$capabilities" ]; then
    cmd="$cmd --capabilities $capabilities"
  fi
  
  # Execute command
  eval "$cmd"
  
  if [ $? -eq 0 ]; then
    print_success "Stack deployed successfully"
    return 0
  else
    print_error "Stack deployment failed"
    return 1
  fi
}

# Delete CloudFormation stack
delete_stack() {
  local stack_name="$1"
  local region="${2:-us-east-1}"
  
  print_status "Deleting stack: $stack_name"
  
  aws cloudformation delete-stack \
    --stack-name "$stack_name" \
    --region "$region"
  
  if [ $? -eq 0 ]; then
    print_success "Stack deletion initiated"
    return 0
  else
    print_error "Failed to delete stack"
    return 1
  fi
}

# Get stack output value
get_stack_output() {
  local stack_name="$1"
  local output_key="$2"
  local region="${3:-us-east-1}"
  
  aws cloudformation describe-stacks \
    --stack-name "$stack_name" \
    --region "$region" \
    --query "Stacks[0].Outputs[?OutputKey=='$output_key'].OutputValue" \
    --output text 2>/dev/null
}

# Get all stack outputs
get_all_stack_outputs() {
  local stack_name="$1"
  local region="${2:-us-east-1}"
  
  aws cloudformation describe-stacks \
    --stack-name "$stack_name" \
    --region "$region" \
    --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
    --output table
}

# Get stack export value
get_stack_export() {
  local export_name="$1"
  local region="${2:-us-east-1}"
  
  aws cloudformation list-exports \
    --region "$region" \
    --query "Exports[?Name=='$export_name'].Value" \
    --output text 2>/dev/null
}

# Validate CloudFormation template
validate_template() {
  local template="$1"
  local region="${2:-us-east-1}"
  
  print_status "Validating template: $template"
  
  local cmd="aws cloudformation validate-template"
  cmd="$cmd --region $region"
  
  # Handle template (file or URL)
  if [[ "$template" == http* ]]; then
    cmd="$cmd --template-url $template"
  else
    cmd="$cmd --template-body file://$template"
  fi
  
  eval "$cmd" >/dev/null
  
  if [ $? -eq 0 ]; then
    print_success "Template is valid"
    return 0
  else
    print_error "Template validation failed"
    return 1
  fi
}

# Create change set
create_change_set() {
  local stack_name="$1"
  local change_set_name="$2"
  local template="$3"
  local parameters="$4"
  local region="${5:-us-east-1}"
  local capabilities="${6:-CAPABILITY_IAM CAPABILITY_NAMED_IAM}"
  
  print_status "Creating change set: $change_set_name"
  
  local cmd="aws cloudformation create-change-set"
  cmd="$cmd --stack-name $stack_name"
  cmd="$cmd --change-set-name $change_set_name"
  cmd="$cmd --region $region"
  
  # Determine change set type
  if stack_exists "$stack_name" "$region"; then
    cmd="$cmd --change-set-type UPDATE"
  else
    cmd="$cmd --change-set-type CREATE"
  fi
  
  # Handle template (file or URL)
  if [[ "$template" == http* ]]; then
    cmd="$cmd --template-url $template"
  else
    cmd="$cmd --template-body file://$template"
  fi
  
  # Add parameters if provided
  if [ -n "$parameters" ]; then
    cmd="$cmd --parameters $parameters"
  fi
  
  # Add capabilities
  if [ -n "$capabilities" ]; then
    cmd="$cmd --capabilities $capabilities"
  fi
  
  # Execute command
  local change_set_id
  change_set_id=$(eval "$cmd --query 'Id' --output text")
  
  if [ $? -eq 0 ]; then
    print_success "Change set created: $change_set_id"
    return 0
  else
    print_error "Failed to create change set"
    return 1
  fi
}

# Execute change set
execute_change_set() {
  local change_set_name="$1"
  local stack_name="$2"
  local region="${3:-us-east-1}"
  
  print_status "Executing change set: $change_set_name"
  
  aws cloudformation execute-change-set \
    --change-set-name "$change_set_name" \
    --stack-name "$stack_name" \
    --region "$region"
  
  if [ $? -eq 0 ]; then
    print_success "Change set execution initiated"
    return 0
  else
    print_error "Failed to execute change set"
    return 1
  fi
}

# Get stack events
get_stack_events() {
  local stack_name="$1"
  local region="${2:-us-east-1}"
  local limit="${3:-10}"
  
  aws cloudformation describe-stack-events \
    --stack-name "$stack_name" \
    --region "$region" \
    --max-items "$limit" \
    --query 'StackEvents[*].[Timestamp,ResourceStatus,ResourceType,LogicalResourceId,ResourceStatusReason]' \
    --output table
}

# Get stack resources
get_stack_resources() {
  local stack_name="$1"
  local region="${2:-us-east-1}"
  
  aws cloudformation list-stack-resources \
    --stack-name "$stack_name" \
    --region "$region" \
    --query 'StackResourceSummaries[*].[LogicalResourceId,ResourceType,PhysicalResourceId,ResourceStatus]' \
    --output table
}

# Cancel stack update
cancel_stack_update() {
  local stack_name="$1"
  local region="${2:-us-east-1}"
  
  print_warning "Canceling stack update: $stack_name"
  
  aws cloudformation cancel-update-stack \
    --stack-name "$stack_name" \
    --region "$region"
  
  if [ $? -eq 0 ]; then
    print_success "Stack update canceled"
    return 0
  else
    print_error "Failed to cancel stack update"
    return 1
  fi
}

# Rollback stack
rollback_stack() {
  local stack_name="$1"
  local region="${2:-us-east-1}"
  
  print_warning "Rolling back stack: $stack_name"
  
  aws cloudformation continue-update-rollback \
    --stack-name "$stack_name" \
    --region "$region"
  
  if [ $? -eq 0 ]; then
    print_success "Stack rollback initiated"
    wait_for_stack "$stack_name" "rollback" "$region"
    return $?
  else
    print_error "Failed to rollback stack"
    return 1
  fi
}

# Export functions
export -f stack_exists get_stack_status is_stack_stable wait_for_stack
export -f create_stack update_stack deploy_stack delete_stack
export -f get_stack_output get_all_stack_outputs get_stack_export
export -f validate_template create_change_set execute_change_set
export -f get_stack_events get_stack_resources
export -f cancel_stack_update rollback_stack

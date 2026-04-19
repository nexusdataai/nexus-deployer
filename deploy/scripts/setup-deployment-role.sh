#!/bin/bash

# Setup script for creating cross-account deployment role
# This script helps create the necessary IAM role in the target AWS account

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
STACK_NAME="BusinessCapabilityDeploymentRole"
ROLE_NAME="BusinessCapabilityDeploymentRole"
AWS_REGION="us-east-1"
MAX_SESSION_DURATION=3600
REQUIRE_EXTERNAL_ID="true"
ENVIRONMENT_RESTRICTION="*"
CAPABILITY_RESTRICTION="*"

# Usage function
usage() {
  cat << EOF
Usage: $(basename "$0") [OPTIONS]

Setup cross-account deployment role for business capability deployment.

OPTIONS:
  -s, --source-account ID      Source AWS account ID (required)
  -t, --target-account ID      Target AWS account ID (optional, uses current)
  -r, --role-name NAME        Name for the deployment role
  -e, --external-id ID        External ID for secure access
  -d, --duration SECONDS      Max session duration (default: 3600)
  --environment ENV           Restrict to environment (dev/stage/prod/*)
  --capability-prefix PREFIX  Restrict to capability name prefix
  --region REGION            AWS region (default: us-east-1)
  --stack-name NAME          CloudFormation stack name
  --no-external-id           Don't require external ID
  -h, --help                 Display this help message

EXAMPLES:
  # Basic setup
  $(basename "$0") -s 123456789012 -e my-external-id

  # With restrictions
  $(basename "$0") -s 123456789012 -e my-external-id \\
    --environment prod \\
    --capability-prefix my-app

  # Custom role name and duration
  $(basename "$0") -s 123456789012 -e my-external-id \\
    --role-name MyDeploymentRole \\
    --duration 7200

EOF
}

# Parse arguments
parse_arguments() {
  while [[ $# -gt 0 ]]; do
    case $1 in
      -s|--source-account)
        SOURCE_ACCOUNT="$2"
        shift 2
        ;;
      -t|--target-account)
        TARGET_ACCOUNT="$2"
        shift 2
        ;;
      -r|--role-name)
        ROLE_NAME="$2"
        shift 2
        ;;
      -e|--external-id)
        EXTERNAL_ID="$2"
        shift 2
        ;;
      -d|--duration)
        MAX_SESSION_DURATION="$2"
        shift 2
        ;;
      --environment)
        ENVIRONMENT_RESTRICTION="$2"
        shift 2
        ;;
      --capability-prefix)
        CAPABILITY_RESTRICTION="$2"
        shift 2
        ;;
      --region)
        AWS_REGION="$2"
        shift 2
        ;;
      --stack-name)
        STACK_NAME="$2"
        shift 2
        ;;
      --no-external-id)
        REQUIRE_EXTERNAL_ID="false"
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        echo -e "${RED}Unknown option: $1${NC}"
        usage
        exit 1
        ;;
    esac
  done
}

# Validate prerequisites
validate_prerequisites() {
  echo -e "${BLUE}Validating prerequisites...${NC}"
  
  # Check AWS CLI
  if ! command -v aws >/dev/null 2>&1; then
    echo -e "${RED}AWS CLI is not installed${NC}"
    exit 1
  fi
  
  # Check AWS credentials
  if ! aws sts get-caller-identity >/dev/null 2>&1; then
    echo -e "${RED}AWS credentials are not configured${NC}"
    exit 1
  fi
  
  # Get current account if target not specified
  if [ -z "$TARGET_ACCOUNT" ]; then
    TARGET_ACCOUNT=$(aws sts get-caller-identity --query 'Account' --output text)
    echo -e "${BLUE}Using current account as target: $TARGET_ACCOUNT${NC}"
  fi
  
  # Validate source account
  if [ -z "$SOURCE_ACCOUNT" ]; then
    echo -e "${RED}Source account ID is required${NC}"
    usage
    exit 1
  fi
  
  # Validate source account format
  if [[ ! "$SOURCE_ACCOUNT" =~ ^[0-9]{12}$ ]]; then
    echo -e "${RED}Invalid source account ID: $SOURCE_ACCOUNT${NC}"
    exit 1
  fi
  
  # Validate external ID requirement
  if [ "$REQUIRE_EXTERNAL_ID" == "true" ] && [ -z "$EXTERNAL_ID" ]; then
    echo -e "${YELLOW}Generating random external ID for security...${NC}"
    EXTERNAL_ID=$(openssl rand -hex 32)
    echo -e "${GREEN}Generated External ID: $EXTERNAL_ID${NC}"
    echo -e "${YELLOW}⚠️  Save this External ID - you'll need it to assume the role${NC}"
  fi
  
  echo -e "${GREEN}Prerequisites validated${NC}"
}

# Check if role already exists
check_existing_role() {
  echo -e "${BLUE}Checking for existing role...${NC}"
  
  if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    echo -e "${YELLOW}Role '$ROLE_NAME' already exists${NC}"
    read -p "Do you want to update the existing role? (y/N): " -r
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
      echo -e "${YELLOW}Exiting without changes${NC}"
      exit 0
    fi
    STACK_EXISTS=true
  else
    STACK_EXISTS=false
  fi
}

# Create or update CloudFormation stack
deploy_stack() {
  echo -e "${BLUE}Deploying CloudFormation stack...${NC}"
  
  # Build parameters
  PARAMETERS="ParameterKey=RoleName,ParameterValue=$ROLE_NAME"
  PARAMETERS="$PARAMETERS ParameterKey=TrustedAccountId,ParameterValue=$SOURCE_ACCOUNT"
  PARAMETERS="$PARAMETERS ParameterKey=MaxSessionDuration,ParameterValue=$MAX_SESSION_DURATION"
  PARAMETERS="$PARAMETERS ParameterKey=RequireExternalId,ParameterValue=$REQUIRE_EXTERNAL_ID"
  
  if [ "$REQUIRE_EXTERNAL_ID" == "true" ]; then
    PARAMETERS="$PARAMETERS ParameterKey=ExternalId,ParameterValue=$EXTERNAL_ID"
  fi
  
  if [ "$ENVIRONMENT_RESTRICTION" != "*" ]; then
    PARAMETERS="$PARAMETERS ParameterKey=EnvironmentRestriction,ParameterValue=$ENVIRONMENT_RESTRICTION"
  fi
  
  if [ "$CAPABILITY_RESTRICTION" != "*" ]; then
    PARAMETERS="$PARAMETERS ParameterKey=CapabilityNameRestriction,ParameterValue=$CAPABILITY_RESTRICTION"
  fi
  
  # Create or update stack
  if [ "$STACK_EXISTS" == true ]; then
    echo -e "${BLUE}Updating existing stack...${NC}"
    aws cloudformation update-stack \
      --stack-name "$STACK_NAME" \
      --template-body file://../iam/deployment-role-stack.yaml \
      --parameters $PARAMETERS \
      --capabilities CAPABILITY_NAMED_IAM \
      --region "$AWS_REGION" 2>/dev/null || {
        if [ $? -eq 255 ]; then
          echo -e "${YELLOW}No updates needed for the stack${NC}"
        else
          echo -e "${RED}Failed to update stack${NC}"
          exit 1
        fi
      }
  else
    echo -e "${BLUE}Creating new stack...${NC}"
    aws cloudformation create-stack \
      --stack-name "$STACK_NAME" \
      --template-body file://../iam/deployment-role-stack.yaml \
      --parameters $PARAMETERS \
      --capabilities CAPABILITY_NAMED_IAM \
      --region "$AWS_REGION"
  fi
  
  # Wait for stack to complete
  echo -e "${BLUE}Waiting for stack operation to complete...${NC}"
  
  if [ "$STACK_EXISTS" == true ]; then
    aws cloudformation wait stack-update-complete \
      --stack-name "$STACK_NAME" \
      --region "$AWS_REGION" 2>/dev/null || true
  else
    aws cloudformation wait stack-create-complete \
      --stack-name "$STACK_NAME" \
      --region "$AWS_REGION"
  fi
  
  # Get stack status
  STATUS=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query 'Stacks[0].StackStatus' \
    --output text \
    --region "$AWS_REGION")
  
  if [[ "$STATUS" == *"COMPLETE"* ]]; then
    echo -e "${GREEN}Stack deployment successful!${NC}"
  else
    echo -e "${RED}Stack deployment failed with status: $STATUS${NC}"
    exit 1
  fi
}

# Get stack outputs
get_outputs() {
  echo -e "${BLUE}Retrieving deployment information...${NC}"
  
  # Get role ARN
  ROLE_ARN=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query 'Stacks[0].Outputs[?OutputKey==`RoleArn`].OutputValue' \
    --output text \
    --region "$AWS_REGION")
  
  echo ""
  echo -e "${GREEN}=== Deployment Role Created Successfully ===${NC}"
  echo ""
  echo -e "${BLUE}Role Details:${NC}"
  echo "  Role Name: $ROLE_NAME"
  echo "  Role ARN: $ROLE_ARN"
  echo "  Target Account: $TARGET_ACCOUNT"
  echo "  Source Account: $SOURCE_ACCOUNT"
  
  if [ "$REQUIRE_EXTERNAL_ID" == "true" ]; then
    echo "  External ID: $EXTERNAL_ID"
  fi
  
  if [ "$ENVIRONMENT_RESTRICTION" != "*" ]; then
    echo "  Environment Restriction: $ENVIRONMENT_RESTRICTION"
  fi
  
  if [ "$CAPABILITY_RESTRICTION" != "*" ]; then
    echo "  Capability Restriction: $CAPABILITY_RESTRICTION"
  fi
  
  echo ""
  echo -e "${BLUE}To use this role in deployments:${NC}"
  echo ""
  echo "1. Add to your deployment configuration:"
  echo "   role_arn: $ROLE_ARN"
  
  if [ "$REQUIRE_EXTERNAL_ID" == "true" ]; then
    echo ""
    echo "2. Set the external ID as an environment variable:"
    echo "   export AWS_EXTERNAL_ID=\"$EXTERNAL_ID\""
  fi
  
  echo ""
  echo "3. Run the deployment:"
  echo "   ./deploy-capability-layered.sh \\"
  echo "     -c config/your-config.yaml \\"
  echo "     --role-arn $ROLE_ARN"
  
  echo ""
  echo -e "${BLUE}To test the role assumption:${NC}"
  echo ""
  
  if [ "$REQUIRE_EXTERNAL_ID" == "true" ]; then
    echo "aws sts assume-role \\"
    echo "  --role-arn $ROLE_ARN \\"
    echo "  --role-session-name test-session \\"
    echo "  --external-id $EXTERNAL_ID"
  else
    echo "aws sts assume-role \\"
    echo "  --role-arn $ROLE_ARN \\"
    echo "  --role-session-name test-session"
  fi
  
  echo ""
  echo -e "${YELLOW}⚠️  Important: Save the External ID securely - you cannot retrieve it later!${NC}"
}

# Create configuration file
create_config_file() {
  CONFIG_FILE="deployment-role-${TARGET_ACCOUNT}.conf"
  
  cat > "$CONFIG_FILE" << EOF
# Deployment Role Configuration
# Created: $(date)
# Target Account: $TARGET_ACCOUNT
# Source Account: $SOURCE_ACCOUNT

ROLE_ARN="$ROLE_ARN"
ROLE_NAME="$ROLE_NAME"
TARGET_ACCOUNT="$TARGET_ACCOUNT"
SOURCE_ACCOUNT="$SOURCE_ACCOUNT"
EOF

  if [ "$REQUIRE_EXTERNAL_ID" == "true" ]; then
    echo "EXTERNAL_ID=\"$EXTERNAL_ID\"" >> "$CONFIG_FILE"
  fi
  
  echo "" >> "$CONFIG_FILE"
  echo "# Restrictions" >> "$CONFIG_FILE"
  echo "ENVIRONMENT_RESTRICTION=\"$ENVIRONMENT_RESTRICTION\"" >> "$CONFIG_FILE"
  echo "CAPABILITY_RESTRICTION=\"$CAPABILITY_RESTRICTION\"" >> "$CONFIG_FILE"
  
  echo ""
  echo -e "${GREEN}Configuration saved to: $CONFIG_FILE${NC}"
}

# Main function
main() {
  echo -e "${BLUE}=== Business Capability Deployment Role Setup ===${NC}"
  echo ""
  
  # Parse arguments
  parse_arguments "$@"
  
  # Validate prerequisites
  validate_prerequisites
  
  # Check for existing role
  check_existing_role
  
  # Deploy stack
  deploy_stack
  
  # Get outputs
  get_outputs
  
  # Create config file
  create_config_file
  
  echo ""
  echo -e "${GREEN}=== Setup Complete ===${NC}"
}

# Run main function
main "$@"

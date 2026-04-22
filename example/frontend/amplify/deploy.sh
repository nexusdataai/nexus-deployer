#!/bin/bash

# AWS Amplify UI Stack Deployment Script
# This script combines the CloudFormation template parts and deploys the stack

set -e

# Configuration
STACK_NAME="amplify-ui-production"
REGION="us-east-1"
TEMPLATE_FILE="complete-amplify-stack.yaml"
PARAMETERS_FILE="parameters.json"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}AWS Amplify UI Stack Deployment${NC}"
echo "=================================="

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo -e "${RED}Error: AWS CLI is not installed${NC}"
    exit 1
fi

# Check if AWS credentials are configured
if ! aws sts get-caller-identity &> /dev/null; then
    echo -e "${RED}Error: AWS credentials not configured${NC}"
    exit 1
fi

echo -e "${YELLOW}Step 1: Combining CloudFormation template parts...${NC}"
cat amplify-ui-stack.yaml amplify-ui-stack-part2.yaml amplify-ui-stack-part3.yaml > $TEMPLATE_FILE
echo -e "${GREEN}✓ Template combined successfully${NC}"

# Check if parameters file exists
if [ ! -f "$PARAMETERS_FILE" ]; then
    echo -e "${YELLOW}Creating sample parameters file...${NC}"
    cat > $PARAMETERS_FILE << EOF
[
  {
    "ParameterKey": "DomainName",
    "ParameterValue": "myapp.example.com"
  },
  {
    "ParameterKey": "GitHubRepository",
    "ParameterValue": "https://github.com/username/my-frontend-app"
  },
  {
    "ParameterKey": "GitHubBranch",
    "ParameterValue": "main"
  },
  {
    "ParameterKey": "GitHubToken",
    "ParameterValue": "your-github-token-here"
  },
  {
    "ParameterKey": "Environment",
    "ParameterValue": "prod"
  }
]
EOF
    echo -e "${YELLOW}Please edit $PARAMETERS_FILE with your actual values before proceeding${NC}"
    echo -e "${RED}Exiting...${NC}"
    exit 1
fi

echo -e "${YELLOW}Step 2: Validating CloudFormation template...${NC}"
aws cloudformation validate-template \
    --template-body file://$TEMPLATE_FILE \
    --region $REGION > /dev/null

echo -e "${GREEN}✓ Template validation successful${NC}"

echo -e "${YELLOW}Step 3: Deploying CloudFormation stack...${NC}"
aws cloudformation create-stack \
    --stack-name $STACK_NAME \
    --template-body file://$TEMPLATE_FILE \
    --parameters file://$PARAMETERS_FILE \
    --capabilities CAPABILITY_IAM \
    --region $REGION \
    --tags Key=Project,Value=AmplifyUIStack Key=ManagedBy,Value=CloudFormation

echo -e "${GREEN}✓ Stack deployment initiated${NC}"

echo -e "${YELLOW}Step 4: Monitoring deployment progress...${NC}"
echo "This may take 10-15 minutes..."

# Wait for stack creation to complete
aws cloudformation wait stack-create-complete \
    --stack-name $STACK_NAME \
    --region $REGION

# Check final status
STACK_STATUS=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].StackStatus' \
    --output text)

if [ "$STACK_STATUS" = "CREATE_COMPLETE" ]; then
    echo -e "${GREEN}✓ Stack deployment completed successfully!${NC}"
    
    echo -e "\n${GREEN}Deployment Outputs:${NC}"
    aws cloudformation describe-stacks \
        --stack-name $STACK_NAME \
        --region $REGION \
        --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
        --output table
    
    echo -e "\n${GREEN}Next Steps:${NC}"
    echo "1. Configure your domain registrar to use the Route 53 name servers"
    echo "2. Wait for DNS propagation (up to 48 hours)"
    echo "3. Verify SSL certificate validation in ACM console"
    echo "4. Test your application at the provided URLs"
    echo "5. Monitor the CloudWatch dashboard for performance metrics"
    
else
    echo -e "${RED}✗ Stack deployment failed with status: $STACK_STATUS${NC}"
    
    echo -e "\n${YELLOW}Stack Events (last 10):${NC}"
    aws cloudformation describe-stack-events \
        --stack-name $STACK_NAME \
        --region $REGION \
        --query 'StackEvents[0:9].[Timestamp,ResourceStatus,ResourceType,LogicalResourceId,ResourceStatusReason]' \
        --output table
    
    exit 1
fi

echo -e "\n${GREEN}Deployment completed successfully!${NC}"

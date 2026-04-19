#!/bin/bash
# IAM Permission Validation Script for Totogi Deployment
# This script checks if the current AWS credentials have all required permissions

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Counters
PASSED=0
FAILED=0
WARNINGS=0

echo "=============================================="
echo "  Totogi Deployment Permission Validator"
echo "=============================================="
echo ""

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo -e "${RED}ERROR: AWS CLI is not installed${NC}"
    echo "Please install AWS CLI: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
    exit 1
fi

# Get current identity
echo "Checking AWS credentials..."
IDENTITY=$(aws sts get-caller-identity 2>&1) || {
    echo -e "${RED}ERROR: Failed to get AWS identity. Check your credentials.${NC}"
    exit 1
}

ACCOUNT_ID=$(echo $IDENTITY | jq -r '.Account')
ARN=$(echo $IDENTITY | jq -r '.Arn')
echo -e "${GREEN}✓ Authenticated as: $ARN${NC}"
echo -e "${GREEN}✓ Account ID: $ACCOUNT_ID${NC}"
echo ""

# Function to check a permission
check_permission() {
    local service=$1
    local action=$2
    local resource=$3
    local description=$4
    
    # Use IAM policy simulator
    RESULT=$(aws iam simulate-principal-policy \
        --policy-source-arn "$ARN" \
        --action-names "$action" \
        --resource-arns "$resource" \
        2>&1) || RESULT="ERROR"
    
    if echo "$RESULT" | grep -q '"EvalDecision": "allowed"'; then
        echo -e "${GREEN}✓ $service:$action${NC}"
        ((PASSED++))
        return 0
    else
        echo -e "${RED}✗ $service:$action - $description${NC}"
        ((FAILED++))
        return 1
    fi
}

# Function to check service access (simplified check)
check_service() {
    local service=$1
    local test_action=$2
    local description=$3
    
    case $service in
        "cloudformation")
            aws cloudformation list-stacks --max-items 1 &>/dev/null && {
                echo -e "${GREEN}✓ CloudFormation - $description${NC}"
                ((PASSED++))
            } || {
                echo -e "${RED}✗ CloudFormation - $description${NC}"
                ((FAILED++))
            }
            ;;
        "s3")
            aws s3 ls --max-items 1 &>/dev/null && {
                echo -e "${GREEN}✓ S3 - $description${NC}"
                ((PASSED++))
            } || {
                echo -e "${RED}✗ S3 - $description${NC}"
                ((FAILED++))
            }
            ;;
        "ecs")
            aws ecs list-clusters --max-results 1 &>/dev/null && {
                echo -e "${GREEN}✓ ECS - $description${NC}"
                ((PASSED++))
            } || {
                echo -e "${RED}✗ ECS - $description${NC}"
                ((FAILED++))
            }
            ;;
        "ecr")
            aws ecr describe-repositories --max-results 1 &>/dev/null && {
                echo -e "${GREEN}✓ ECR - $description${NC}"
                ((PASSED++))
            } || {
                echo -e "${RED}✗ ECR - $description${NC}"
                ((FAILED++))
            }
            ;;
        "ec2")
            aws ec2 describe-vpcs --max-results 1 &>/dev/null && {
                echo -e "${GREEN}✓ EC2/VPC - $description${NC}"
                ((PASSED++))
            } || {
                echo -e "${RED}✗ EC2/VPC - $description${NC}"
                ((FAILED++))
            }
            ;;
        "iam")
            aws iam list-roles --max-items 1 &>/dev/null && {
                echo -e "${GREEN}✓ IAM - $description${NC}"
                ((PASSED++))
            } || {
                echo -e "${RED}✗ IAM - $description${NC}"
                ((FAILED++))
            }
            ;;
        "dynamodb")
            aws dynamodb list-tables --max-items 1 &>/dev/null && {
                echo -e "${GREEN}✓ DynamoDB - $description${NC}"
                ((PASSED++))
            } || {
                echo -e "${RED}✗ DynamoDB - $description${NC}"
                ((FAILED++))
            }
            ;;
        "secretsmanager")
            aws secretsmanager list-secrets --max-results 1 &>/dev/null && {
                echo -e "${GREEN}✓ Secrets Manager - $description${NC}"
                ((PASSED++))
            } || {
                echo -e "${RED}✗ Secrets Manager - $description${NC}"
                ((FAILED++))
            }
            ;;
        "logs")
            aws logs describe-log-groups --limit 1 &>/dev/null && {
                echo -e "${GREEN}✓ CloudWatch Logs - $description${NC}"
                ((PASSED++))
            } || {
                echo -e "${RED}✗ CloudWatch Logs - $description${NC}"
                ((FAILED++))
            }
            ;;
        "cloudfront")
            aws cloudfront list-distributions --max-items 1 &>/dev/null && {
                echo -e "${GREEN}✓ CloudFront - $description${NC}"
                ((PASSED++))
            } || {
                echo -e "${RED}✗ CloudFront - $description${NC}"
                ((FAILED++))
            }
            ;;
        "elb")
            aws elbv2 describe-load-balancers --page-size 1 &>/dev/null && {
                echo -e "${GREEN}✓ Elastic Load Balancing - $description${NC}"
                ((PASSED++))
            } || {
                echo -e "${RED}✗ Elastic Load Balancing - $description${NC}"
                ((FAILED++))
            }
            ;;
        "route53")
            aws route53 list-hosted-zones --max-items 1 &>/dev/null && {
                echo -e "${GREEN}✓ Route53 - $description${NC}"
                ((PASSED++))
            } || {
                echo -e "${YELLOW}⚠ Route53 - $description (may not be required)${NC}"
                ((WARNINGS++))
            }
            ;;
        "acm")
            aws acm list-certificates --max-items 1 &>/dev/null && {
                echo -e "${GREEN}✓ ACM - $description${NC}"
                ((PASSED++))
            } || {
                echo -e "${YELLOW}⚠ ACM - $description (may not be required)${NC}"
                ((WARNINGS++))
            }
            ;;
        "wafv2")
            aws wafv2 list-web-acls --scope CLOUDFRONT --region us-east-1 &>/dev/null && {
                echo -e "${GREEN}✓ WAF - $description${NC}"
                ((PASSED++))
            } || {
                echo -e "${YELLOW}⚠ WAF - $description (may not be required)${NC}"
                ((WARNINGS++))
            }
            ;;
        "kms")
            aws kms list-keys --max-items 1 &>/dev/null && {
                echo -e "${GREEN}✓ KMS - $description${NC}"
                ((PASSED++))
            } || {
                echo -e "${RED}✗ KMS - $description${NC}"
                ((FAILED++))
            }
            ;;
        *)
            echo -e "${YELLOW}⚠ Unknown service: $service${NC}"
            ((WARNINGS++))
            ;;
    esac
}

echo "Checking service permissions..."
echo "----------------------------------------------"

# Core Infrastructure
echo ""
echo "Core Infrastructure:"
check_service "cloudformation" "" "Stack management"
check_service "iam" "" "Role management"

# Frontend Services
echo ""
echo "Frontend Services:"
check_service "s3" "" "Bucket operations"
check_service "cloudfront" "" "CDN distribution"
check_service "route53" "" "DNS management"
check_service "acm" "" "Certificate management"
check_service "wafv2" "" "Web application firewall"

# Backend Services
echo ""
echo "Backend Services:"
check_service "ecs" "" "Container orchestration"
check_service "ecr" "" "Container registry"
check_service "ec2" "" "VPC and networking"
check_service "elb" "" "Load balancing"

# Data Services
echo ""
echo "Data Services:"
check_service "dynamodb" "" "Database tables"
check_service "secretsmanager" "" "Secrets storage"
check_service "kms" "" "Encryption keys"

# Monitoring
echo ""
echo "Monitoring Services:"
check_service "logs" "" "Application logging"

echo ""
echo "=============================================="
echo "  Summary"
echo "=============================================="
echo -e "${GREEN}Passed: $PASSED${NC}"
echo -e "${RED}Failed: $FAILED${NC}"
echo -e "${YELLOW}Warnings: $WARNINGS${NC}"
echo ""

if [ $FAILED -gt 0 ]; then
    echo -e "${RED}Some permissions are missing. Please update your IAM policy.${NC}"
    echo "Download the required policy from the Totogi installer wizard."
    exit 1
else
    echo -e "${GREEN}All required permissions are available!${NC}"
    exit 0
fi

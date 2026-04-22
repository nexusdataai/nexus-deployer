#!/bin/bash
#
# Build and Push Nexus Operator Image to ECR
#
# Usage:
#   ./build-and-push.sh [tag] [region] [profile]
#
# Examples:
#   ./build-and-push.sh                           # Build and push 'latest' to default region
#   ./build-and-push.sh v1.0.0                    # Build and push 'v1.0.0' tag
#   ./build-and-push.sh latest us-east-1     # Specify region
#   ./build-and-push.sh latest us-east-1 external-access  # Specify AWS profile
#

set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
IMAGE_NAME="nexus-operator"
TAG="${1:-latest}"
REGION="${2:-${AWS_REGION:-us-east-1}}"
AWS_PROFILE="${3:-${AWS_PROFILE:-}}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Set AWS profile if provided
if [ -n "$AWS_PROFILE" ]; then
    export AWS_PROFILE
fi

echo ""
echo -e "${BLUE}=============================================="
echo "  Building Nexus Operator Image"
echo -e "==============================================${NC}"
echo ""
echo "Image:       ${IMAGE_NAME}"
echo "Tag:         ${TAG}"
echo "Region:      ${REGION}"
echo "Profile:     ${AWS_PROFILE:-default}"
echo ""

# Step 1: Get AWS account ID
echo -e "${BLUE}[1/6] Getting AWS account ID...${NC}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --region "${REGION}")

if [ -z "$ACCOUNT_ID" ]; then
    echo -e "${RED}✗ Failed to get AWS account ID${NC}"
    echo "  Make sure AWS credentials are configured"
    exit 1
fi

ECR_REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
FULL_IMAGE_NAME="${ECR_REGISTRY}/${IMAGE_NAME}:${TAG}"

echo -e "${GREEN}✓ Account ID: ${ACCOUNT_ID}${NC}"
echo "  Registry: ${ECR_REGISTRY}"
echo ""

# Step 2: Create ECR repository if it doesn't exist
echo -e "${BLUE}[2/6] Ensuring ECR repository exists...${NC}"
REPO_EXISTS=false
if aws ecr describe-repositories --repository-names "${IMAGE_NAME}" --region "${REGION}" >/dev/null 2>&1; then
    echo -e "${GREEN}✓ ECR repository '${IMAGE_NAME}' already exists${NC}"
    REPO_EXISTS=true
else
    echo "  Creating ECR repository..."
    aws ecr create-repository \
        --repository-name "${IMAGE_NAME}" \
        --region "${REGION}" \
        --image-scanning-configuration scanOnPush=true \
        --tags Key=managed-by,Value=starhub-deployer Key=component,Value=nexus-operator \
        >/dev/null
    
    echo -e "${GREEN}✓ ECR repository '${IMAGE_NAME}' created${NC}"
fi

# Set repository policy to allow EKS nodes to pull (in case of restrictive account policies)
echo "  Configuring repository permissions for EKS nodes..."
aws ecr set-repository-policy \
    --repository-name "${IMAGE_NAME}" \
    --region "${REGION}" \
    --policy-text '{
      "Version": "2012-10-17",
      "Statement": [
        {
          "Sid": "AllowEKSNodePull",
          "Effect": "Allow",
          "Principal": {
            "Service": "eks.amazonaws.com"
          },
          "Action": [
            "ecr:BatchGetImage",
            "ecr:GetDownloadUrlForLayer"
          ]
        },
        {
          "Sid": "AllowAccountPull",
          "Effect": "Allow",
          "Principal": {
            "AWS": "arn:aws:iam::'"${ACCOUNT_ID}"':root"
          },
          "Action": [
            "ecr:BatchGetImage",
            "ecr:GetDownloadUrlForLayer",
            "ecr:BatchCheckLayerAvailability"
          ]
        }
      ]
    }' >/dev/null 2>&1 || echo "  (Policy update skipped - using default permissions)"

echo ""

# Step 3: Login to ECR
echo -e "${BLUE}[3/6] Logging in to ECR...${NC}"
aws ecr get-login-password --region "${REGION}" | \
    docker login --username AWS --password-stdin "${ECR_REGISTRY}" >/dev/null 2>&1

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Logged in to ECR${NC}"
else
    echo -e "${RED}✗ Failed to login to ECR${NC}"
    exit 1
fi
echo ""

# Step 4: Build Docker image
echo -e "${BLUE}[4/6] Building Docker image...${NC}"
cd "${SCRIPT_DIR}"

docker build --no-cache \
    -t "${IMAGE_NAME}:${TAG}" \
    -t "${IMAGE_NAME}:latest" \
    --build-arg BUILD_DATE="$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
    --build-arg VERSION="${TAG}" \
    .

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Docker image built successfully${NC}"
else
    echo -e "${RED}✗ Docker build failed${NC}"
    exit 1
fi
echo ""

# Step 5: Tag image for ECR
echo -e "${BLUE}[5/6] Tagging image for ECR...${NC}"
docker tag "${IMAGE_NAME}:${TAG}" "${FULL_IMAGE_NAME}"

# Also tag as latest in ECR if this is a version tag
if [ "${TAG}" != "latest" ]; then
    docker tag "${IMAGE_NAME}:${TAG}" "${ECR_REGISTRY}/${IMAGE_NAME}:latest"
    echo -e "${GREEN}✓ Tagged as both ${TAG} and latest${NC}"
else
    echo -e "${GREEN}✓ Tagged as ${TAG}${NC}"
fi
echo ""

# Step 6: Push to ECR
echo -e "${BLUE}[6/6] Pushing image to ECR...${NC}"
docker push "${FULL_IMAGE_NAME}"

# Push latest tag if this is a version tag
if [ "${TAG}" != "latest" ]; then
    docker push "${ECR_REGISTRY}/${IMAGE_NAME}:latest"
fi

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Image pushed successfully${NC}"
else
    echo -e "${RED}✗ Failed to push image${NC}"
    exit 1
fi
echo ""

# Summary
echo -e "${GREEN}=============================================="
echo "  ✓ Build and Push Complete!"
echo -e "==============================================${NC}"
echo ""
echo "Image URL:"
echo "  ${FULL_IMAGE_NAME}"
echo ""
echo "To deploy the operator with this image:"
echo "  export OPERATOR_IMAGE=${FULL_IMAGE_NAME}"
echo "  ./operator-nexus.sh deploy"
echo ""
echo "Or set in operator_deployment_service.py:"
echo "  OPERATOR_IMAGE = \"${FULL_IMAGE_NAME}\""
echo ""

#!/bin/bash
#
# Build Operator Image and Deploy to EKS Cluster
#
# This script combines building the operator image and deploying it to the cluster.
# It ensures the latest code is always deployed.
#
# Usage:
#   ./build-and-deploy.sh [tag] [cluster] [region] [profile]
#
# Examples:
#   ./build-and-deploy.sh                                    # Build latest, deploy to starhub-test
#   ./build-and-deploy.sh v1.0.0                            # Build v1.0.0, deploy to starhub-test
#   ./build-and-deploy.sh latest starhub-test ap-southeast-1 external-access  # Full options
#

set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
TAG="${1:-latest}"
CLUSTER="${2:-starhub-test}"
REGION="${3:-${AWS_REGION:-ap-southeast-1}}"
AWS_PROFILE="${4:-${AWS_PROFILE:-external-access}}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo -e "${BLUE}================================================"
echo "  Build and Deploy Totogi Operator"
echo -e "================================================${NC}"
echo ""
echo "Tag:         ${TAG}"
echo "Cluster:     ${CLUSTER}"
echo "Region:      ${REGION}"
echo "Profile:     ${AWS_PROFILE}"
echo ""

# Set AWS profile
export AWS_PROFILE="${AWS_PROFILE}"

# Step 1: Build and push operator image
echo -e "${BLUE}Step 1: Building and pushing operator image...${NC}"
echo ""
"${SCRIPT_DIR}/build-and-push.sh" "${TAG}" "${REGION}" "${AWS_PROFILE}"

if [ $? -ne 0 ]; then
    echo -e "${RED}✗ Build failed${NC}"
    exit 1
fi

# Get account ID for image URL
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --region "${REGION}")
IMAGE_URL="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/totogi-operator:${TAG}"

echo ""
echo -e "${BLUE}Step 2: Deploying operator to cluster...${NC}"
echo ""

# Export image URL for deployment script
export OPERATOR_IMAGE="${IMAGE_URL}"

# Deploy using the operator management script
"${SCRIPT_DIR}/operator-starhub-test.sh" deploy --force

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}================================================"
    echo "  ✓ Build and Deploy Complete!"
    echo -e "================================================${NC}"
    echo ""
    echo "Operator image: ${IMAGE_URL}"
    echo "Cluster:        ${CLUSTER}"
    echo ""
    echo "Check operator status:"
    echo "  ./operator-starhub-test.sh status"
    echo ""
    echo "View operator logs:"
    echo "  kubectl -n nexus-system logs -f deployment/totogi-operator"
    echo ""
else
    echo ""
    echo -e "${RED}✗ Deployment failed${NC}"
    echo ""
    exit 1
fi

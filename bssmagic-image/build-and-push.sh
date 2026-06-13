#!/bin/bash
# =============================================================================
# Build and push BSS Magic K8s runtime image to ECR
# =============================================================================
# All required source files are included in this directory.
# No external repository references are needed.
#
# This script is for INTERNAL CloudSense use (rebuilding the image).
# The client should NOT run this — they use the pre-built tar via e2e-deploy.sh.
#
# Prerequisites:
#   - Docker installed and running
#   - AWS CLI configured with ECR push permissions
#   - Access to CloudSense base image ECR (008731404932.dkr.ecr.us-east-1.amazonaws.com)
#
# Usage:
#   ./build-and-push.sh <ECR_REGISTRY> [TAG]
#
# Example:
#   ./build-and-push.sh 123456789012.dkr.ecr.us-east-1.amazonaws.com latest
# =============================================================================

set -e

ECR_REGISTRY="${1:?Usage: $0 <ECR_REGISTRY> [TAG]}"
TAG="${2:-latest}"
IMAGE_NAME="bssmagic-nexus-k8s"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Building BSS Magic K8s Image ==="
echo "ECR Registry: ${ECR_REGISTRY}"
echo "Image: ${IMAGE_NAME}:${TAG}"
echo ""

# --- Build ---
echo "Building Docker image..."
docker build -t "${IMAGE_NAME}:${TAG}" "${SCRIPT_DIR}"

# --- Tag and push ---
FULL_IMAGE="${ECR_REGISTRY}/${IMAGE_NAME}:${TAG}"
echo "Tagging as: ${FULL_IMAGE}"
docker tag "${IMAGE_NAME}:${TAG}" "${FULL_IMAGE}"

echo "Logging in to ECR..."
aws ecr get-login-password --region "$(echo $ECR_REGISTRY | sed 's/.*\.ecr\.\(.*\)\.amazonaws.*/\1/')" \
    | docker login --username AWS --password-stdin "${ECR_REGISTRY}"

# Create ECR repo if it doesn't exist
REPO_NAME="${IMAGE_NAME}"
aws ecr describe-repositories --repository-names "${REPO_NAME}" 2>/dev/null || \
    aws ecr create-repository --repository-name "${REPO_NAME}" --image-scanning-configuration scanOnPush=true

echo "Pushing to ECR..."
docker push "${FULL_IMAGE}"

echo ""
echo "=== Done ==="
echo "Image: ${FULL_IMAGE}"
echo ""
echo "Use this image in your TotogiCapability manifest:"
echo "  bssmagic:"
echo "    enabled: true"
echo "    image: \"${FULL_IMAGE}\""

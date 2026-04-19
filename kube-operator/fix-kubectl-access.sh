#!/bin/bash
#
# Fix kubectl Access to EKS Cluster
#
# This script updates kubeconfig and verifies kubectl access
#

set -e

CLUSTER_NAME="${1:-starhub-test}"
REGION="${2:-us-east-1}"
AWS_PROFILE="${3:-external-access}"

echo ""
echo "=============================================="
echo "  Fixing kubectl Access"
echo "=============================================="
echo ""
echo "Cluster: ${CLUSTER_NAME}"
echo "Region:  ${REGION}"
echo "Profile: ${AWS_PROFILE}"
echo ""

# Update kubeconfig
echo "Updating kubeconfig..."
aws eks update-kubeconfig \
    --name "${CLUSTER_NAME}" \
    --region "${REGION}" \
    --profile "${AWS_PROFILE}"

echo ""
echo "Testing kubectl access..."

# Test kubectl
if kubectl get namespaces >/dev/null 2>&1; then
    echo "✓ kubectl access working!"
    echo ""
    kubectl get namespaces
    echo ""
    echo "You can now use kubectl commands."
    echo ""
else
    echo "✗ kubectl access still not working"
    echo ""
    echo "This means you don't have EKS Access Entry or aws-auth entry yet."
    echo ""
    echo "Solution: Deploy the operator, which will automatically grant you access:"
    echo "  ./operator-starhub-test.sh deploy"
    echo ""
    echo "Or manually create EKS Access Entry:"
    echo "  aws eks create-access-entry \\"
    echo "    --cluster-name ${CLUSTER_NAME} \\"
    echo "    --principal-arn \$(aws sts get-caller-identity --query 'Arn' --output text | sed 's/:assumed-role\//:role\//;s/\/[^/]*$//' | sed 's/sts/iam/') \\"
    echo "    --type STANDARD \\"
    echo "    --region ${REGION} \\"
    echo "    --profile ${AWS_PROFILE}"
    echo ""
    echo "  aws eks associate-access-policy \\"
    echo "    --cluster-name ${CLUSTER_NAME} \\"
    echo "    --principal-arn \$(aws sts get-caller-identity --query 'Arn' --output text | sed 's/:assumed-role\//:role\//;s/\/[^/]*$//' | sed 's/sts/iam//')  \\"
    echo "    --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy \\"
    echo "    --access-scope type=cluster \\"
    echo "    --region ${REGION} \\"
    echo "    --profile ${AWS_PROFILE}"
    echo ""
    exit 1
fi

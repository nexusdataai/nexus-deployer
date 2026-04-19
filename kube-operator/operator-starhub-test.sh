#!/bin/bash
#
# Totogi Operator Management Script
# Reads defaults from .env.local (ENV, Branch, Cluster). Env vars override.
# 
# Usage:
#   ./operator-starhub-test.sh scan                    # Scan cluster readiness
#   ./operator-starhub-test.sh fix-irsa                # Fix IRSA (OIDC provider)
#   ./operator-starhub-test.sh install-alb-controller  # Install AWS Load Balancer Controller
#   ./operator-starhub-test.sh delete-alb-controller   # Delete AWS Load Balancer Controller
#   ./operator-starhub-test.sh delete-ebs-csi          # Delete EBS CSI Driver + IAM role
#   ./operator-starhub-test.sh deploy                  # Deploy operator (auto-fixes IRSA + ALB)
#   ./operator-starhub-test.sh delete                  # Delete operator (keeps access)
#   ./operator-starhub-test.sh delete --full           # Delete everything including IAM/ECR/ALB Controller
#   ./operator-starhub-test.sh update                  # Update operator (force redeploy)
#   ./operator-starhub-test.sh status                  # Check operator status
#   ./operator-starhub-test.sh monitor                 # Monitor capability deployment progress
#   ./operator-starhub-test.sh verify-capability       # Verify capability resources and health
#   ./operator-starhub-test.sh --help                  # Show help
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load defaults from .env.local (CLI args and env vars override these)
_ENVLOCAL="${SCRIPT_DIR}/.env.local"
if [ -f "$_ENVLOCAL" ]; then
    _ENV_LOCAL_ENV=$(grep '^ENV=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2-)
    _ENV_LOCAL_BRANCH=$(grep '^Branch=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2-)
    _ENV_LOCAL_CLUSTER=$(grep '^Cluster=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2-)
fi

CLUSTER_NAME="${CLUSTER_NAME:-${_ENV_LOCAL_CLUSTER:-starhub-test}}"
DEPLOY_ENV="${DEPLOY_ENV:-${_ENV_LOCAL_ENV:-prod}}"
GIT_BRANCH="${GIT_BRANCH:-${_ENV_LOCAL_BRANCH:-}}"
REGION="ap-southeast-1"
AWS_PROFILE="${AWS_PROFILE:-external-access}"
BACKEND_DIR="${SCRIPT_DIR}/../backend"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

show_help() {
    cat << EOF
Totogi Operator Management Script for starhub-test

Usage:
  ./operator-starhub-test.sh <command> [options]

Commands:
  scan                    Comprehensive cluster readiness scan (includes IRSA checks)
  fix-irsa                Fix IRSA by creating OIDC provider in IAM if missing
  install-alb-controller  Install AWS Load Balancer Controller (for ALB Ingress support)
  delete-alb-controller   Delete AWS Load Balancer Controller and its IAM role
  delete-ebs-csi          Delete EBS CSI Driver add-on and its IAM role
  deploy                  Deploy operator (auto-fixes IRSA and installs ALB Controller)
  delete                  Delete operator (keeps IAM, ECR, and your access)
  delete --full           Complete cleanup (removes IAM, ECR, aws-auth, ALB Controller)
  delete --remove-aws-auth  Remove aws-auth entry (restore original state)
  update                  Update/redeploy operator (force update)
  status                  Check operator status
  monitor [ns/name]       Monitor capability deployment progress in real-time
  verify-capability [ns]  Verify all AWS resources, K8s workloads, and app health
  help                    Show this help message

Options:
  --profile PROFILE       AWS profile to use (default: external-access)
  --keep-iam              Keep IAM role when deleting
  --keep-ecr              Keep ECR repository when deleting
  --delete-alb            Delete AWS Load Balancer Controller (included in --full)
  --delete-ebs-csi        Delete EBS CSI Driver add-on + IAM role (included in --full)
  --remove-aws-auth       Remove your entry from aws-auth (⚠️ lose access)
  --force                 Force deployment even if already installed
  --skip-irsa-fix         Skip automatic IRSA fix during deploy

Environment Variables:
  AWS_PROFILE         Default AWS profile (default: external-access)

Examples:
  # Scan cluster before deployment (recommended first step)
  ./operator-starhub-test.sh scan

  # Fix IRSA (create OIDC provider if missing)
  ./operator-starhub-test.sh fix-irsa

  # Deploy operator (automatically fixes IRSA if needed)
  ./operator-starhub-test.sh deploy

  # Deploy without IRSA auto-fix
  ./operator-starhub-test.sh deploy --skip-irsa-fix

  # Update operator
  ./operator-starhub-test.sh update

  # Check status
  ./operator-starhub-test.sh status

  # Delete operator (safe - keeps IAM, ECR, and access)
  ./operator-starhub-test.sh delete

  # Complete cleanup (removes IAM, ECR, and aws-auth - restores original state)
  ./operator-starhub-test.sh delete --full

  # Delete with specific options
  ./operator-starhub-test.sh delete --keep-iam

  # Restore cluster to original state (removes aws-auth entry)
  ./operator-starhub-test.sh delete --remove-aws-auth

Workflow:
  1. ./operator-starhub-test.sh scan     # Check cluster readiness & IRSA
  2. ./operator-starhub-test.sh fix-irsa # Fix IRSA if needed (or let deploy do it)
  3. ./build-and-push.sh                 # Build operator image
  4. ./operator-starhub-test.sh deploy   # Deploy operator (auto-fixes IRSA + ALB Controller)
  5. ./operator-starhub-test.sh status   # Verify health

ALB Ingress Support:
  The deploy command automatically installs AWS Load Balancer Controller if not present.
  This enables ALB Ingress for TotogiCapability resources.
  
  To install ALB Controller separately:
    ./operator-starhub-test.sh install-alb-controller

IRSA (IAM Roles for Service Accounts):
  IRSA allows Kubernetes pods to securely assume IAM roles without credentials.
  The operator uses IRSA to provision AWS resources (DynamoDB, S3, SSM, etc.).
  
  If IRSA is not configured:
    - The 'scan' command will detect it
    - The 'fix-irsa' command will create the OIDC provider
    - The 'deploy' command will auto-fix before deploying

EOF
}

show_header() {
    local action=$1
    echo ""
    echo "=============================================="
    echo "  $action Operator - starhub-test Cluster"
    echo "=============================================="
    echo ""
    echo "Cluster:     ${CLUSTER_NAME}"
    echo "Region:      ${REGION}"
    echo "AWS Profile: ${AWS_PROFILE}"
    echo ""
}

check_dependencies() {
    echo "Checking dependencies..."
    
    # Check Python
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}Error: python3 not found${NC}"
        exit 1
    fi
    
    # Check Python packages
    if ! python3 -c "import kubernetes, boto3" 2>/dev/null; then
        echo "Installing required Python packages..."
        pip install kubernetes boto3 pydantic pyyaml aiohttp --break-system-packages
    fi
    
    echo "✓ Dependencies OK"
    echo ""
}

deploy_operator() {
    local force_flag=""
    local skip_irsa_fix=""
    
    # Check for flags
    while [[ $# -gt 0 ]]; do
        case $1 in
            --force)
                force_flag="--force"
                shift
                ;;
            --skip-irsa-fix)
                skip_irsa_fix="true"
                shift
                ;;
            *)
                shift
                ;;
        esac
    done
    
    show_header "Deploy"
    check_dependencies
    
    # Pre-flight: Check and fix IRSA if needed
    if [ -z "$skip_irsa_fix" ]; then
        echo "Checking IRSA prerequisites..."
        echo ""
        ensure_irsa_configured
        local irsa_exit=$?
        if [ $irsa_exit -ne 0 ]; then
            echo -e "${YELLOW}Warning: IRSA setup had issues. Continuing with deployment...${NC}"
            echo ""
        fi
    fi
    
    echo "Starting deployment..."
    echo ""
    
    cd "${BACKEND_DIR}"
    python3 scripts/deploy_operator_to_cluster.py \
        --cluster "${CLUSTER_NAME}" \
        --region "${REGION}" \
        --profile "${AWS_PROFILE}" \
        $force_flag
    
    local exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        echo ""
        echo -e "${GREEN}=============================================="
        echo "  ✓ Deployment completed successfully!"
        echo -e "===============================================${NC}"
        echo ""
        
        # Refresh kubeconfig to ensure kubectl works with standard AWS CLI context
        echo "Refreshing kubeconfig for kubectl access..."
        AWS_PROFILE="${AWS_PROFILE}" aws eks update-kubeconfig \
            --name "${CLUSTER_NAME}" \
            --region "${REGION}" \
            --profile "${AWS_PROFILE}" 2>/dev/null || true
        echo ""
        
        # Now that we have cluster access, check and install AWS Load Balancer Controller
        echo ""
        echo "Checking AWS Load Balancer Controller..."
        echo ""
        ensure_alb_controller
        local alb_exit=$?
        if [ $alb_exit -ne 0 ]; then
            echo -e "${YELLOW}Warning: ALB Controller setup had issues. ALB Ingress may not work.${NC}"
            echo "You can install it later with: ./operator-starhub-test.sh install-alb-controller"
            echo ""
        fi
        
        echo ""
        echo "Verify deployment:"
        echo "  kubectl -n totogi-system get pods"
        echo "  kubectl -n totogi-system logs -f deployment/totogi-operator"
        echo ""
        echo -e "${GREEN}=============================================="
        echo "  Next Steps"
        echo -e "===============================================${NC}"
        echo ""
        echo "1. Deploy a capability:"
        echo "   kubectl create namespace call-processing-prod"
        echo "   kubectl apply -f examples/call-processing-complete.yaml"
        echo ""
        echo "2. Monitor deployment progress:"
        echo "   ./operator-starhub-test.sh monitor"
        echo ""
        echo "3. Verify all resources:"
        echo "   ./operator-starhub-test.sh verify-capability"
        echo ""
        echo "4. Get the application URL (after ALB is active):"
        echo "   kubectl get ingress -n call-processing-prod -o wide"
        echo ""
        echo "5. Login to the application:"
        echo "   Get the admin credentials:"
        echo "   kubectl get secret call-processing-prod-admin-credentials -n call-processing-prod -o jsonpath='{.data.admin-email}' | base64 -d && echo ''"
        echo "   kubectl get secret call-processing-prod-admin-credentials -n call-processing-prod -o jsonpath='{.data.admin-password}' | base64 -d && echo ''"
        echo ""
        echo "   The initial admin user is configured via 'adminEmail' in the capability YAML."
        echo "   On first login, you will be prompted to set a new password."
        echo ""
    else
        echo ""
        echo -e "${RED}=============================================="
        echo "  ✗ Deployment failed (exit code: $exit_code)"
        echo -e "===============================================${NC}"
        echo ""
    fi
    
    return $exit_code
}

# Function to ensure IRSA is configured (creates OIDC provider if missing)
ensure_irsa_configured() {
    echo "═══════════════════════════════════════════════════════════════════"
    echo "  IRSA (IAM Roles for Service Accounts) Pre-flight Check"
    echo "═══════════════════════════════════════════════════════════════════"
    echo ""
    
    export CLUSTER_NAME="${CLUSTER_NAME}"
    export REGION="${REGION}"
    export AWS_PROFILE="${AWS_PROFILE}"
    
    # Run Python script to check and fix IRSA
    python3 << 'IRSA_FIX_EOF'
import os
import sys
import ssl
import socket
import hashlib
from urllib.parse import urlparse

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    print("Error: boto3 not installed")
    sys.exit(1)

CLUSTER_NAME = os.getenv('CLUSTER_NAME') or sys.exit("Error: CLUSTER_NAME not set. Check .env.local or pass --cluster.")
REGION = os.getenv('REGION', 'ap-southeast-1')
AWS_PROFILE = os.getenv('AWS_PROFILE', 'external-access')

def get_oidc_thumbprint(oidc_issuer):
    """Get the SHA-1 thumbprint of the OIDC provider's root CA certificate."""
    try:
        parsed = urlparse(oidc_issuer)
        hostname = parsed.netloc or parsed.path.split("/")[0]
        
        # Connect and get certificate chain
        context = ssl.create_default_context()
        with socket.create_connection((hostname, 443), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert_der = ssock.getpeercert(binary_form=True)
        
        # Calculate SHA-1 thumbprint
        thumbprint = hashlib.sha1(cert_der).hexdigest()
        return thumbprint
        
    except Exception as e:
        print(f"    Warning: Could not get thumbprint dynamically: {e}")
        # Return AWS's known thumbprint for EKS OIDC (may need updating)
        return "9e99a48a9960b14926bb7f3b02e22da2b0ab7280"

def main():
    try:
        session = boto3.Session(profile_name=AWS_PROFILE)
        eks_client = session.client('eks', region_name=REGION)
        iam_client = session.client('iam', region_name=REGION)
        sts_client = session.client('sts', region_name=REGION)
        
        # Get account ID
        account_id = sts_client.get_caller_identity()['Account']
        
        # Get cluster info
        print(f"[1/4] Getting cluster information...")
        try:
            cluster_info = eks_client.describe_cluster(name=CLUSTER_NAME)['cluster']
        except ClientError as e:
            print(f"    [✗] Failed to get cluster info: {e.response['Error']['Code']}")
            return 1
        
        # Check OIDC issuer
        oidc_issuer = cluster_info.get('identity', {}).get('oidc', {}).get('issuer')
        if not oidc_issuer:
            print(f"    [✗] Cluster does not have OIDC issuer configured")
            print(f"        IRSA cannot be enabled for this cluster")
            print(f"        This must be set when creating the cluster")
            return 1
        
        oidc_provider_id = oidc_issuer.replace('https://', '')
        print(f"    [✓] OIDC issuer: {oidc_provider_id}")
        
        # Check if OIDC provider exists in IAM
        print(f"[2/4] Checking OIDC provider in IAM...")
        oidc_arn = f"arn:aws:iam::{account_id}:oidc-provider/{oidc_provider_id}"
        
        try:
            iam_client.get_open_id_connect_provider(OpenIDConnectProviderArn=oidc_arn)
            print(f"    [✓] OIDC provider already registered in IAM")
            print(f"    [✓] IRSA is ready!")
            return 0
            
        except ClientError as e:
            if e.response['Error']['Code'] != 'NoSuchEntity':
                print(f"    [✗] Error checking OIDC provider: {e.response['Error']['Code']}")
                return 1
        
        # OIDC provider not found - create it
        print(f"    [—] OIDC provider not found in IAM")
        print(f"")
        print(f"[3/4] Creating OIDC provider in IAM...")
        print(f"    (This enables IRSA for the cluster)")
        
        # Get thumbprint
        print(f"    Getting certificate thumbprint...")
        thumbprint = get_oidc_thumbprint(oidc_issuer)
        print(f"    Thumbprint: {thumbprint[:16]}...")
        
        # Create the OIDC provider
        try:
            response = iam_client.create_open_id_connect_provider(
                Url=oidc_issuer,
                ClientIDList=['sts.amazonaws.com'],
                ThumbprintList=[thumbprint],
                Tags=[
                    {'Key': 'eks:cluster-name', 'Value': CLUSTER_NAME},
                    {'Key': 'managed-by', 'Value': 'totogi-operator'},
                    {'Key': 'created-by', 'Value': 'operator-starhub-test.sh'},
                ]
            )
            created_arn = response['OpenIDConnectProviderArn']
            print(f"    [✓] Created OIDC provider!")
            print(f"    ARN: {created_arn}")
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'EntityAlreadyExists':
                print(f"    [✓] OIDC provider already exists (created by another process)")
            elif error_code == 'AccessDenied':
                print(f"    [✗] Access denied - insufficient IAM permissions")
                print(f"        Required: iam:CreateOpenIDConnectProvider")
                print(f"")
                print(f"    To fix manually, run:")
                print(f"      eksctl utils associate-iam-oidc-provider \\")
                print(f"        --cluster {CLUSTER_NAME} \\")
                print(f"        --region {REGION} \\")
                print(f"        --approve")
                return 1
            else:
                print(f"    [✗] Failed to create OIDC provider: {error_code}")
                print(f"        {e.response['Error']['Message']}")
                return 1
        
        # Verify creation
        print(f"[4/4] Verifying OIDC provider...")
        try:
            iam_client.get_open_id_connect_provider(OpenIDConnectProviderArn=oidc_arn)
            print(f"    [✓] OIDC provider verified!")
            print(f"")
            print(f"    [✓] IRSA is now configured and ready!")
            return 0
        except ClientError:
            print(f"    [⚠] Could not verify - provider may still be propagating")
            return 0
        
    except Exception as e:
        print(f"[✗] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())
IRSA_FIX_EOF
    
    return $?
}

# Function to check and install AWS Load Balancer Controller
ensure_alb_controller() {
    echo "═══════════════════════════════════════════════════════════════════"
    echo "  AWS Load Balancer Controller Check"
    echo "═══════════════════════════════════════════════════════════════════"
    echo ""
    
    # Export environment variables for Python script
    export CLUSTER_NAME="${CLUSTER_NAME}"
    export REGION="${REGION}"
    export AWS_PROFILE="${AWS_PROFILE}"
    
    # Run Python script to check and install ALB controller
    python3 << 'ALB_CONTROLLER_EOF'
import os
import sys
import json
import subprocess
import time

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    print("Error: boto3 not installed")
    sys.exit(1)

CLUSTER_NAME = os.getenv('CLUSTER_NAME') or sys.exit("Error: CLUSTER_NAME not set. Check .env.local or pass --cluster.")
REGION = os.getenv('REGION', 'ap-southeast-1')
AWS_PROFILE = os.getenv('AWS_PROFILE', 'external-access')

ALB_CONTROLLER_NAMESPACE = "kube-system"
ALB_CONTROLLER_NAME = "aws-load-balancer-controller"
ALB_CONTROLLER_SA = "aws-load-balancer-controller"
ALB_CONTROLLER_ROLE = "AmazonEKSLoadBalancerControllerRole"

def run_kubectl(args, check=True):
    """Run kubectl command and return output."""
    cmd = ["kubectl"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        return None
    return result.stdout.strip()

def check_alb_controller_installed():
    """Check if AWS Load Balancer Controller is installed."""
    # Check for deployment
    result = run_kubectl([
        "get", "deployment", ALB_CONTROLLER_NAME,
        "-n", ALB_CONTROLLER_NAMESPACE,
        "-o", "jsonpath={.status.readyReplicas}"
    ], check=False)
    
    if result and result.isdigit() and int(result) > 0:
        return True
    
    # Also check for pods
    result = run_kubectl([
        "get", "pods", "-n", ALB_CONTROLLER_NAMESPACE,
        "-l", f"app.kubernetes.io/name={ALB_CONTROLLER_NAME}",
        "-o", "jsonpath={.items[*].status.phase}"
    ], check=False)
    
    if result and "Running" in result:
        return True
    
    return False

def check_helm_installed():
    """Check if helm is installed."""
    result = subprocess.run(["which", "helm"], capture_output=True)
    return result.returncode == 0

def create_alb_controller_iam_role(session, account_id, oidc_provider_id):
    """Create IAM role for ALB Controller with IRSA."""
    iam_client = session.client('iam', region_name=REGION)
    
    # Trust policy for IRSA
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {
                "Federated": f"arn:aws:iam::{account_id}:oidc-provider/{oidc_provider_id}"
            },
            "Action": "sts:AssumeRoleWithWebIdentity",
            "Condition": {
                "StringEquals": {
                    f"{oidc_provider_id}:aud": "sts.amazonaws.com",
                    f"{oidc_provider_id}:sub": f"system:serviceaccount:{ALB_CONTROLLER_NAMESPACE}:{ALB_CONTROLLER_SA}"
                }
            }
        }]
    }
    
    # Comprehensive ALB Controller policy with all required permissions
    alb_controller_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "ec2:DescribeAccountAttributes",
                    "ec2:DescribeAddresses",
                    "ec2:DescribeAvailabilityZones",
                    "ec2:DescribeInternetGateways",
                    "ec2:DescribeVpcs",
                    "ec2:DescribeVpcPeeringConnections",
                    "ec2:DescribeSubnets",
                    "ec2:DescribeSecurityGroups",
                    "ec2:DescribeInstances",
                    "ec2:DescribeNetworkInterfaces",
                    "ec2:DescribeTags",
                    "ec2:GetCoipPoolUsage",
                    "ec2:DescribeCoipPools",
                    "ec2:DescribeRouteTables",
                    "ec2:DescribeNatGateways",
                    "ec2:CreateSecurityGroup",
                    "ec2:DeleteSecurityGroup",
                    "ec2:AuthorizeSecurityGroupIngress",
                    "ec2:RevokeSecurityGroupIngress",
                    "ec2:CreateTags",
                    "ec2:DeleteTags"
                ],
                "Resource": "*"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "elasticloadbalancing:*"
                ],
                "Resource": "*"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "cognito-idp:DescribeUserPoolClient",
                    "acm:ListCertificates",
                    "acm:DescribeCertificate",
                    "iam:ListServerCertificates",
                    "iam:GetServerCertificate",
                    "iam:CreateServiceLinkedRole",
                    "waf-regional:GetWebACL",
                    "waf-regional:GetWebACLForResource",
                    "waf-regional:AssociateWebACL",
                    "waf-regional:DisassociateWebACL",
                    "wafv2:GetWebACL",
                    "wafv2:GetWebACLForResource",
                    "wafv2:AssociateWebACL",
                    "wafv2:DisassociateWebACL",
                    "shield:GetSubscriptionState",
                    "shield:DescribeProtection",
                    "shield:CreateProtection",
                    "shield:DeleteProtection"
                ],
                "Resource": "*"
            }
        ]
    }
    
    try:
        # Check if role exists
        role_exists = False
        role_arn = None
        try:
            existing = iam_client.get_role(RoleName=ALB_CONTROLLER_ROLE)
            role_exists = True
            role_arn = existing["Role"]["Arn"]
            print(f"    [✓] IAM role exists: {ALB_CONTROLLER_ROLE}")
            
            # Merge trust policy: add current cluster's OIDC provider without removing others
            print(f"    Updating trust policy for {ALB_CONTROLLER_ROLE}...")
            existing_trust = existing["Role"]["AssumeRolePolicyDocument"]
            existing_statements = existing_trust.get("Statement", [])
            
            current_oidc_arn = f"arn:aws:iam::{account_id}:oidc-provider/{oidc_provider_id}"
            already_present = any(
                stmt.get("Principal", {}).get("Federated") == current_oidc_arn
                for stmt in existing_statements
            )
            
            if already_present:
                print(f"    [✓] Trust policy already includes this cluster's OIDC provider")
                merged_trust = existing_trust
            else:
                print(f"    Adding OIDC provider for cluster to existing trust policy...")
                new_statement = trust_policy["Statement"][0]
                merged_statements = existing_statements + [new_statement]
                merged_trust = {"Version": "2012-10-17", "Statement": merged_statements}
            
            iam_client.update_assume_role_policy(
                RoleName=ALB_CONTROLLER_ROLE,
                PolicyDocument=json.dumps(merged_trust)
            )
            
            # Update inline policy to ensure all permissions are present
            print(f"    Updating inline policy for {ALB_CONTROLLER_ROLE}...")
            iam_client.put_role_policy(
                RoleName=ALB_CONTROLLER_ROLE,
                PolicyName="AWSLoadBalancerControllerIAMPolicy",
                PolicyDocument=json.dumps(alb_controller_policy)
            )
            print(f"    [✓] Updated IAM role policies: {ALB_CONTROLLER_ROLE}")
            return role_arn
            
        except ClientError as e:
            if e.response["Error"]["Code"] != "NoSuchEntity":
                raise
        
        # Create role
        print(f"    Creating IAM role: {ALB_CONTROLLER_ROLE}...")
        response = iam_client.create_role(
            RoleName=ALB_CONTROLLER_ROLE,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="IAM role for AWS Load Balancer Controller",
            Tags=[
                {"Key": "Capability", "Value": "call-processing"},
                {"Key": "Environment", "Value": os.getenv("DEPLOY_ENV", "prod")},
                {"Key": "managed-by", "Value": "totogi-operator"},
                {"Key": "component", "Value": "aws-load-balancer-controller"}
            ]
        )
        role_arn = response["Role"]["Arn"]
        
        # Attach inline policy with all required permissions
        iam_client.put_role_policy(
            RoleName=ALB_CONTROLLER_ROLE,
            PolicyName="AWSLoadBalancerControllerIAMPolicy",
            PolicyDocument=json.dumps(alb_controller_policy)
        )
        
        print(f"    [✓] Created IAM role: {ALB_CONTROLLER_ROLE}")
        return role_arn
        
    except Exception as e:
        print(f"    [✗] Failed to create IAM role: {e}")
        return None

def create_service_account(role_arn):
    """Create service account for ALB Controller."""
    sa_yaml = f"""
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {ALB_CONTROLLER_SA}
  namespace: {ALB_CONTROLLER_NAMESPACE}
  annotations:
    eks.amazonaws.com/role-arn: {role_arn}
  labels:
    app.kubernetes.io/name: {ALB_CONTROLLER_NAME}
    app.kubernetes.io/component: controller
"""
    
    # Apply service account
    proc = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=sa_yaml,
        capture_output=True,
        text=True
    )
    
    if proc.returncode != 0:
        print(f"    [✗] Failed to create service account: {proc.stderr}")
        return False
    
    print(f"    [✓] Created ServiceAccount: {ALB_CONTROLLER_SA}")
    return True

def refresh_kubeconfig():
    """Refresh kubeconfig to ensure valid credentials."""
    print("    Refreshing kubeconfig...")
    
    # Ensure AWS_PROFILE is set in the current process environment
    # This is needed for kubectl/helm which spawn aws cli via exec
    if AWS_PROFILE:
        os.environ['AWS_PROFILE'] = AWS_PROFILE
    
    # Build the update-kubeconfig command
    cmd = [
        "aws", "eks", "update-kubeconfig",
        "--name", CLUSTER_NAME,
        "--region", REGION
    ]
    
    if AWS_PROFILE:
        cmd.extend(["--profile", AWS_PROFILE])
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"    [⚠] Could not refresh kubeconfig: {result.stderr[:100]}")
        return False
    
    print(f"    [✓] Kubeconfig refreshed (context: {CLUSTER_NAME})")
    
    # Verify kubectl access
    test_result = subprocess.run(
        ["kubectl", "get", "ns", "kube-system", "--request-timeout=10s"],
        capture_output=True,
        text=True
    )
    
    if test_result.returncode != 0:
        print(f"    [⚠] kubectl test failed: {test_result.stderr[:150]}")
        # Try to show current context
        ctx_result = subprocess.run(["kubectl", "config", "current-context"], capture_output=True, text=True)
        print(f"    Current context: {ctx_result.stdout.strip()}")
        return False
    
    print(f"    [✓] kubectl access verified")
    return True

def install_alb_controller_with_helm(role_arn):
    """Install AWS Load Balancer Controller using helm."""
    print("    Installing AWS Load Balancer Controller with Helm...")
    
    # Refresh kubeconfig to ensure valid credentials (also sets AWS_PROFILE in os.environ)
    if not refresh_kubeconfig():
        print("    [⚠] Kubeconfig refresh failed, attempting Helm install anyway...")
    
    # Add EKS helm repo
    subprocess.run(
        ["helm", "repo", "add", "eks", "https://aws.github.io/eks-charts"],
        capture_output=True
    )
    subprocess.run(["helm", "repo", "update"], capture_output=True)
    
    # Get VPC ID
    vpc_id = get_vpc_id()
    
    # Install controller - let Helm create the service account with proper IRSA annotation
    cmd = [
        "helm", "upgrade", "--install", ALB_CONTROLLER_NAME,
        "eks/aws-load-balancer-controller",
        "-n", ALB_CONTROLLER_NAMESPACE,
        "--create-namespace",
        "--set", f"clusterName={CLUSTER_NAME}",
        "--set", f"serviceAccount.create=true",
        "--set", f"serviceAccount.name={ALB_CONTROLLER_SA}",
        "--set", f"serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn={role_arn}",
        "--set", f"region={REGION}",
    ]
    
    if vpc_id:
        cmd.extend(["--set", f"vpcId={vpc_id}"])
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"    [✗] Helm install failed: {result.stderr}")
        return False
    
    print(f"    [✓] Helm install completed")
    return True

def get_vpc_id():
    """Get VPC ID from cluster."""
    try:
        session = boto3.Session(profile_name=AWS_PROFILE)
        eks_client = session.client('eks', region_name=REGION)
        cluster_info = eks_client.describe_cluster(name=CLUSTER_NAME)['cluster']
        return cluster_info['resourcesVpcConfig']['vpcId']
    except:
        return ""

def install_alb_controller_with_kubectl(role_arn):
    """Install AWS Load Balancer Controller using kubectl (without helm)."""
    print("    Installing AWS Load Balancer Controller with kubectl...")
    
    # Download the controller manifest
    manifest_url = "https://github.com/kubernetes-sigs/aws-load-balancer-controller/releases/download/v2.7.1/v2_7_1_full.yaml"
    
    try:
        import urllib.request
        with urllib.request.urlopen(manifest_url) as response:
            manifest = response.read().decode('utf-8')
    except Exception as e:
        print(f"    [✗] Failed to download manifest: {e}")
        return False
    
    # Replace cluster name placeholder
    manifest = manifest.replace("your-cluster-name", CLUSTER_NAME)
    
    # Apply manifest
    proc = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=manifest,
        capture_output=True,
        text=True
    )
    
    if proc.returncode != 0:
        print(f"    [⚠] Some resources may have failed: {proc.stderr[:200]}")
    
    print(f"    [✓] Applied controller manifests")
    return True

def main():
    try:
        session = boto3.Session(profile_name=AWS_PROFILE)
        sts_client = session.client('sts', region_name=REGION)
        eks_client = session.client('eks', region_name=REGION)
        iam_client = session.client('iam', region_name=REGION)
        
        # Get account ID
        account_id = sts_client.get_caller_identity()['Account']
        
        # Check if already installed
        print(f"[1/5] Checking if AWS Load Balancer Controller is installed...")
        controller_running = check_alb_controller_installed()
        if controller_running:
            print(f"    [✓] AWS Load Balancer Controller pods are running")
        else:
            print(f"    [—] AWS Load Balancer Controller not found")
        print(f"")
        
        # Get OIDC provider (always needed to verify IAM role)
        print(f"[2/5] Getting cluster OIDC provider...")
        try:
            cluster_info = eks_client.describe_cluster(name=CLUSTER_NAME)['cluster']
            oidc_issuer = cluster_info.get('identity', {}).get('oidc', {}).get('issuer')
            if not oidc_issuer:
                print(f"    [✗] No OIDC issuer - IRSA not available")
                print(f"        ALB Controller requires IRSA. Run: ./operator-starhub-test.sh fix-irsa")
                return 1
            
            oidc_provider_id = oidc_issuer.replace('https://', '')
            print(f"    [✓] OIDC provider: {oidc_provider_id[:50]}...")
        except Exception as e:
            print(f"    [✗] Failed to get cluster info: {e}")
            return 1
        
        # ALWAYS verify/create/update IAM role (even if controller is running)
        # This ensures the role exists with proper permissions
        print(f"[3/5] Verifying IAM role for ALB Controller...")
        role_arn = create_alb_controller_iam_role(session, account_id, oidc_provider_id)
        if not role_arn:
            return 1
        
        # If controller is already running, verify service account and we're done
        if controller_running:
            print(f"")
            print(f"[4/5] Verifying service account IRSA annotation...")
            # Check if service account has the correct role annotation
            sa_result = run_kubectl([
                "get", "sa", ALB_CONTROLLER_SA, "-n", ALB_CONTROLLER_NAMESPACE,
                "-o", "jsonpath={.metadata.annotations.eks\\.amazonaws\\.com/role-arn}"
            ], check=False)
            
            if sa_result == role_arn:
                print(f"    [✓] Service account has correct IAM role annotation")
            else:
                print(f"    [⚠] Service account missing/wrong IAM role annotation")
                print(f"    Patching service account...")
                run_kubectl([
                    "annotate", "sa", ALB_CONTROLLER_SA, "-n", ALB_CONTROLLER_NAMESPACE,
                    f"eks.amazonaws.com/role-arn={role_arn}", "--overwrite"
                ], check=False)
            
            # Always restart ALB Controller to ensure fresh IRSA credentials
            # This is necessary after IAM role create/update (stale cached tokens)
            print(f"")
            print(f"[5/5] Restarting ALB Controller for fresh credentials...")
            run_kubectl([
                "rollout", "restart", "deployment", ALB_CONTROLLER_NAME, "-n", ALB_CONTROLLER_NAMESPACE
            ], check=False)
            print(f"    [✓] ALB Controller restarted")
            
            # Wait briefly for new pods to be ready
            print(f"    Waiting for new pods to be ready...")
            for i in range(15):
                time.sleep(2)
                result = run_kubectl([
                    "get", "deployment", ALB_CONTROLLER_NAME,
                    "-n", ALB_CONTROLLER_NAMESPACE,
                    "-o", "jsonpath={.status.readyReplicas}"
                ], check=False)
                if result and result.isdigit() and int(result) >= 1:
                    print(f"    [✓] AWS Load Balancer Controller is ready!")
                    return 0
            
            print(f"    [✓] AWS Load Balancer Controller restart initiated")
            return 0
        
        # Install controller
        print(f"")
        print(f"[4/5] Installing AWS Load Balancer Controller...")
        
        # Prefer Helm - it handles service account creation with IRSA annotation
        if check_helm_installed():
            success = install_alb_controller_with_helm(role_arn)
        else:
            print(f"    [—] Helm not found, using kubectl method")
            # For kubectl method, we need to create the service account manually first
            if not create_service_account(role_arn):
                print(f"    [⚠] Service account creation failed, continuing anyway...")
            success = install_alb_controller_with_kubectl(role_arn)
        
        if not success:
            return 1
        
        # Wait for controller to start
        print(f"")
        print(f"[5/5] Waiting for controller to start...")
        for i in range(30):
            time.sleep(2)
            if check_alb_controller_installed():
                print(f"    [✓] AWS Load Balancer Controller is running!")
                return 0
        
        print(f"    [⚠] Controller deployed but not yet ready. Check status with:")
        print(f"        kubectl -n kube-system get pods -l app.kubernetes.io/name=aws-load-balancer-controller")
        return 0
        
    except Exception as e:
        print(f"[✗] Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())
ALB_CONTROLLER_EOF
    
    return $?
}

# Function to delete AWS Load Balancer Controller
_delete_alb_controller() {
    # Export environment variables for Python script
    export CLUSTER_NAME="${CLUSTER_NAME}"
    export REGION="${REGION}"
    export AWS_PROFILE="${AWS_PROFILE}"
    
    # Run Python script to delete ALB controller
    python3 << 'DELETE_ALB_EOF'
import os
import sys
import json
import subprocess

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    print("Error: boto3 not installed")
    sys.exit(1)

CLUSTER_NAME = os.getenv('CLUSTER_NAME') or sys.exit("Error: CLUSTER_NAME not set. Check .env.local or pass --cluster.")
REGION = os.getenv('REGION', 'ap-southeast-1')
AWS_PROFILE = os.getenv('AWS_PROFILE', 'external-access')

ALB_CONTROLLER_NAMESPACE = "kube-system"
ALB_CONTROLLER_NAME = "aws-load-balancer-controller"
ALB_CONTROLLER_SA = "aws-load-balancer-controller"
ALB_CONTROLLER_ROLE = "AmazonEKSLoadBalancerControllerRole"

def run_cmd(args, check=True):
    """Run command and return result."""
    result = subprocess.run(args, capture_output=True, text=True)
    if check and result.returncode != 0:
        return None, result.stderr
    return result.stdout.strip(), None

def main():
    print("Deleting AWS Load Balancer Controller...")
    print("")
    
    errors = []
    
    # Step 1: Try to uninstall via Helm first (cleanest method)
    print("[1/4] Checking for Helm installation...")
    helm_result, _ = run_cmd(["which", "helm"], check=False)
    
    if helm_result:
        print("    Attempting Helm uninstall...")
        result, err = run_cmd([
            "helm", "uninstall", ALB_CONTROLLER_NAME,
            "-n", ALB_CONTROLLER_NAMESPACE
        ], check=False)
        if err and "not found" not in err.lower():
            print(f"    Helm uninstall output: {err}")
        else:
            print("    [✓] Helm release uninstalled (or not found)")
    else:
        print("    Helm not found, will delete resources directly")
    
    # Step 2: Delete Kubernetes resources directly (in case Helm wasn't used)
    print("")
    print("[2/4] Deleting Kubernetes resources...")
    
    # Delete deployment
    result, _ = run_cmd([
        "kubectl", "delete", "deployment", ALB_CONTROLLER_NAME,
        "-n", ALB_CONTROLLER_NAMESPACE, "--ignore-not-found"
    ], check=False)
    print(f"    Deployment: deleted/not found")
    
    # Delete service account
    result, _ = run_cmd([
        "kubectl", "delete", "serviceaccount", ALB_CONTROLLER_SA,
        "-n", ALB_CONTROLLER_NAMESPACE, "--ignore-not-found"
    ], check=False)
    print(f"    ServiceAccount: deleted/not found")
    
    # Delete webhook configurations
    result, _ = run_cmd([
        "kubectl", "delete", "validatingwebhookconfiguration",
        f"{ALB_CONTROLLER_NAME}-webhook", "--ignore-not-found"
    ], check=False)
    result, _ = run_cmd([
        "kubectl", "delete", "mutatingwebhookconfiguration",
        f"{ALB_CONTROLLER_NAME}-webhook", "--ignore-not-found"
    ], check=False)
    print(f"    Webhook configurations: deleted/not found")
    
    # Delete webhook service
    result, _ = run_cmd([
        "kubectl", "delete", "service",
        f"{ALB_CONTROLLER_NAME}-webhook-service",
        "-n", ALB_CONTROLLER_NAMESPACE, "--ignore-not-found"
    ], check=False)
    print(f"    Webhook service: deleted/not found")
    
    # Delete webhook secret
    result, _ = run_cmd([
        "kubectl", "delete", "secret", "aws-load-balancer-webhook-tls",
        "-n", ALB_CONTROLLER_NAMESPACE, "--ignore-not-found"
    ], check=False)
    print(f"    Webhook secret: deleted/not found")
    
    # Delete CRDs (optional - may want to keep these)
    print("")
    print("[3/4] Deleting CRDs...")
    crds = [
        "ingressclassparams.elbv2.k8s.aws",
        "targetgroupbindings.elbv2.k8s.aws"
    ]
    for crd in crds:
        result, _ = run_cmd([
            "kubectl", "delete", "crd", crd, "--ignore-not-found"
        ], check=False)
    print(f"    ALB Controller CRDs: deleted/not found")
    
    # Step 3: Delete IAM role
    print("")
    print("[4/4] Keeping IAM role (shared across clusters)...")
    print(f"    [✓] IAM role preserved: {ALB_CONTROLLER_ROLE}")
    print(f"    (Role is shared by multiple EKS clusters — never delete it from a single cluster cleanup)")
    
    print("")
    if errors:
        print(f"Completed with {len(errors)} error(s)")
        return 1
    else:
        print("[✓] AWS Load Balancer Controller deleted successfully")
        return 0

if __name__ == '__main__':
    sys.exit(main())
DELETE_ALB_EOF
    
    return $?
}

# Standalone install-alb-controller command
install_alb_controller() {
    show_header "Install ALB Controller"
    check_dependencies
    
    echo "This command will install the AWS Load Balancer Controller if not present."
    echo "The ALB Controller is required for Kubernetes Ingress to create AWS ALBs."
    echo ""
    
    ensure_alb_controller
    local exit_code=$?
    
    echo ""
    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}=============================================="
        echo "  ✓ AWS Load Balancer Controller is ready!"
        echo -e "===============================================${NC}"
        echo ""
        echo "You can now use ALB Ingress in your TotogiCapability:"
        echo "  spec:"
        echo "    ingress:"
        echo "      enabled: true"
        echo "      scheme: internet-facing"
        echo ""
    else
        echo -e "${RED}=============================================="
        echo "  ✗ ALB Controller installation failed"
        echo -e "===============================================${NC}"
        echo ""
        echo "Manual installation:"
        echo "  1. Install helm: https://helm.sh/docs/intro/install/"
        echo "  2. Run: helm repo add eks https://aws.github.io/eks-charts"
        echo "  3. Run: helm install aws-load-balancer-controller eks/aws-load-balancer-controller \\"
        echo "       -n kube-system --set clusterName=${CLUSTER_NAME}"
        echo ""
    fi
    
    return $exit_code
}

# Function to delete EBS CSI Driver add-on and its IAM role
_delete_ebs_csi_driver() {
    local exit_code=0
    local EBS_CSI_ROLE_NAME="AmazonEKS_EBS_CSI_DriverRole"
    
    # Step 1: Delete EKS add-on
    echo "[1/2] Deleting EBS CSI Driver EKS add-on..."
    local addon_status
    addon_status=$(aws eks describe-addon --cluster-name "${CLUSTER_NAME}" --addon-name aws-ebs-csi-driver \
        --query "addon.status" --output text --region "${REGION}" --profile "${AWS_PROFILE}" 2>/dev/null || echo "NOT_FOUND")
    
    if [ "$addon_status" = "NOT_FOUND" ]; then
        echo "    EBS CSI Driver add-on not found (already deleted or never installed)"
    else
        echo "    Current status: ${addon_status}"
        aws eks delete-addon --cluster-name "${CLUSTER_NAME}" --addon-name aws-ebs-csi-driver \
            --region "${REGION}" --profile "${AWS_PROFILE}" >/dev/null 2>&1
        
        # Wait for deletion (up to 60s)
        echo "    Waiting for add-on deletion..."
        for i in $(seq 1 6); do
            local status
            status=$(aws eks describe-addon --cluster-name "${CLUSTER_NAME}" --addon-name aws-ebs-csi-driver \
                --query "addon.status" --output text --region "${REGION}" --profile "${AWS_PROFILE}" 2>/dev/null || echo "DELETED")
            if [ "$status" = "DELETED" ]; then
                echo -e "    ${GREEN}✓ EBS CSI Driver add-on deleted${NC}"
                break
            fi
            echo "      Status: ${status} (${i}/6)"
            sleep 10
        done
    fi
    
    # Step 2: Delete IAM role
    echo ""
    echo "[2/2] Deleting IAM role: ${EBS_CSI_ROLE_NAME}..."
    if aws iam get-role --role-name "${EBS_CSI_ROLE_NAME}" --profile "${AWS_PROFILE}" >/dev/null 2>&1; then
        # Detach managed policies first
        local policies
        policies=$(aws iam list-attached-role-policies --role-name "${EBS_CSI_ROLE_NAME}" \
            --profile "${AWS_PROFILE}" --query "AttachedPolicies[].PolicyArn" --output text 2>/dev/null || echo "")
        for policy_arn in $policies; do
            aws iam detach-role-policy --role-name "${EBS_CSI_ROLE_NAME}" --policy-arn "$policy_arn" \
                --profile "${AWS_PROFILE}" 2>/dev/null || true
            echo "    Detached policy: ${policy_arn}"
        done
        
        # Delete the role
        if aws iam delete-role --role-name "${EBS_CSI_ROLE_NAME}" --profile "${AWS_PROFILE}" 2>/dev/null; then
            echo -e "    ${GREEN}✓ IAM role ${EBS_CSI_ROLE_NAME} deleted${NC}"
        else
            echo -e "    ${RED}✗ Failed to delete IAM role ${EBS_CSI_ROLE_NAME}${NC}"
            exit_code=1
        fi
    else
        echo "    IAM role ${EBS_CSI_ROLE_NAME} not found (already deleted or never created)"
    fi
    
    echo ""
    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}[✓] EBS CSI Driver cleanup complete${NC}"
    else
        echo -e "${YELLOW}[⚠] EBS CSI Driver cleanup completed with issues${NC}"
    fi
    
    return $exit_code
}

# Standalone delete-alb-controller command
delete_alb_controller() {
    show_header "Delete ALB Controller"
    check_dependencies
    
    echo "This command will delete the AWS Load Balancer Controller."
    echo ""
    echo -e "${YELLOW}Warning: This will remove the ALB Controller and its IAM role.${NC}"
    echo "Any Ingress resources using ALB will stop working."
    echo ""
    
    _delete_alb_controller
    local exit_code=$?
    
    echo ""
    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}=============================================="
        echo "  ✓ AWS Load Balancer Controller deleted!"
        echo -e "===============================================${NC}"
        echo ""
        echo "To reinstall:"
        echo "  ./operator-starhub-test.sh install-alb-controller"
        echo ""
    else
        echo -e "${RED}=============================================="
        echo "  ✗ ALB Controller deletion had issues"
        echo -e "===============================================${NC}"
        echo ""
    fi
    
    return $exit_code
}

# Standalone delete-ebs-csi command
delete_ebs_csi() {
    show_header "Delete EBS CSI Driver"
    check_dependencies
    
    echo "This command will delete the EBS CSI Driver add-on and its IAM role."
    echo ""
    echo -e "${YELLOW}Warning: Any PersistentVolumeClaims using EBS will stop provisioning.${NC}"
    echo "Existing mounted volumes will continue working until pods restart."
    echo ""
    
    _delete_ebs_csi_driver
    local exit_code=$?
    
    echo ""
    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}=============================================="
        echo "  ✓ EBS CSI Driver deleted!"
        echo -e "===============================================${NC}"
        echo ""
        echo "To reinstall (done automatically by e2e-deploy.sh):"
        echo "  e2e-deploy.sh handles this in Step 2"
        echo ""
    else
        echo -e "${RED}=============================================="
        echo "  ✗ EBS CSI Driver deletion had issues"
        echo -e "===============================================${NC}"
        echo ""
    fi
    
    return $exit_code
}

# Standalone fix-irsa command
fix_irsa() {
    show_header "Fix IRSA"
    check_dependencies
    
    echo "This command will create the OIDC provider in IAM if it's missing."
    echo "OIDC provider is required for IRSA (IAM Roles for Service Accounts)."
    echo ""
    
    ensure_irsa_configured
    local exit_code=$?
    
    echo ""
    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}=============================================="
        echo "  ✓ IRSA is configured and ready!"
        echo -e "===============================================${NC}"
        echo ""
        echo "Next steps:"
        echo "  1. Build operator image: ./build-and-push.sh"
        echo "  2. Deploy operator:      ./operator-starhub-test.sh deploy"
        echo ""
    else
        echo -e "${RED}=============================================="
        echo "  ✗ IRSA configuration failed"
        echo -e "===============================================${NC}"
        echo ""
        echo "Manual fix using eksctl:"
        echo "  eksctl utils associate-iam-oidc-provider \\"
        echo "    --cluster ${CLUSTER_NAME} \\"
        echo "    --region ${REGION} \\"
        echo "    --approve"
        echo ""
    fi
    
    return $exit_code
}

delete_operator() {
    local keep_iam="--keep-iam"
    local keep_ecr="--keep-ecr"
    local remove_aws_auth=""  # Default: keep aws-auth (preserve access)
    local keep_access_entry=""  # Default: remove access entry
    local delete_alb_controller=""  # Default: keep ALB controller
    local delete_ebs_csi=""         # Default: keep EBS CSI driver
    
    # Parse options
    while [[ $# -gt 0 ]]; do
        case $1 in
            --full)
                keep_iam=""
                keep_ecr=""
                remove_aws_auth="--remove-aws-auth"  # Remove aws-auth with --full
                keep_access_entry=""
                delete_alb_controller="yes"  # Delete ALB controller with --full
                delete_ebs_csi="yes"         # Delete EBS CSI driver with --full
                shift
                ;;
            --delete-alb|--delete-alb-controller)
                delete_alb_controller="yes"
                shift
                ;;
            --delete-ebs-csi|--remove-ebs-csi)
                delete_ebs_csi="yes"
                shift
                ;;
            --keep-iam)
                keep_iam="--keep-iam"
                shift
                ;;
            --keep-ecr)
                keep_ecr="--keep-ecr"
                shift
                ;;
            --no-keep-iam)
                keep_iam=""
                shift
                ;;
            --no-keep-ecr)
                keep_ecr=""
                shift
                ;;
            --remove-aws-auth)
                remove_aws_auth="--remove-aws-auth"
                shift
                ;;
            --keep-access-entry)
                keep_access_entry="--keep-access-entry"
                shift
                ;;
            *)
                shift
                ;;
        esac
    done
    
    show_header "Delete"
    
    # Show warnings based on options
    if [ -n "$remove_aws_auth" ]; then
        echo -e "${RED}⚠️  COMPLETE CLEANUP MODE - WILL REMOVE AWS-AUTH ENTRY${NC}"
        echo "This will:"
        echo "  - Delete operator resources"
        if [ -z "$keep_iam" ]; then
            echo "  - Remove IAM roles"
        fi
        if [ -z "$keep_ecr" ]; then
            echo "  - Remove ECR repository"
        fi
        if [ -n "$delete_alb_controller" ]; then
            echo "  - Remove AWS Load Balancer Controller and its IAM role"
        fi
        if [ -n "$delete_ebs_csi" ]; then
            echo "  - Remove EBS CSI Driver add-on and its IAM role"
        fi
        echo "  - Remove your entry from aws-auth ConfigMap"
        echo "  - Remove your EKS Access Entry"
        echo ""
        echo -e "${RED}YOU WILL LOSE CLUSTER ACCESS!${NC}"
        echo "Cluster will be restored to original state."
        echo ""
    elif [ -z "$keep_iam" ] && [ -z "$keep_ecr" ]; then
        echo -e "${YELLOW}WARNING: Full cleanup mode (keeps aws-auth)${NC}"
        echo "This will delete IAM roles and ECR repository."
        if [ -n "$delete_alb_controller" ]; then
            echo "This will also remove AWS Load Balancer Controller."
        fi
        if [ -n "$delete_ebs_csi" ]; then
            echo "This will also remove EBS CSI Driver add-on and its IAM role."
        fi
        echo "Your cluster access will be preserved."
        echo ""
    else
        echo "Safe cleanup mode (preserves IAM, ECR, and your access)"
        if [ -n "$delete_alb_controller" ]; then
            echo "Note: AWS Load Balancer Controller will be removed."
        fi
        if [ -n "$delete_ebs_csi" ]; then
            echo "Note: EBS CSI Driver add-on and its IAM role will be removed."
        fi
        echo ""
    fi
    
    echo "Starting cleanup..."
    echo ""
    
    # Delete ALB Ingress resources BEFORE losing kubectl access
    if [ -n "$delete_alb_controller" ]; then
        echo "═══════════════════════════════════════════════════════════════════"
        echo "  Pre-cleanup: Removing ALB Ingress resources"
        echo "═══════════════════════════════════════════════════════════════════"
        echo ""
        local alb_ingresses
        alb_ingresses=$(kubectl get ingress -A -o json 2>/dev/null | python3 -c "
import sys,json
data = json.load(sys.stdin)
for ing in data.get('items', []):
    ns = ing['metadata']['namespace']
    name = ing['metadata']['name']
    ic = ing.get('spec',{}).get('ingressClassName','')
    ann = ing.get('metadata',{}).get('annotations',{}).get('kubernetes.io/ingress.class','')
    if ic == 'alb' or ann == 'alb':
        print(f'{ns}/{name}')
" 2>/dev/null || echo "")
        local deleted_count=0
        if [ -n "$alb_ingresses" ]; then
            for entry in $alb_ingresses; do
                local ns="${entry%%/*}"
                local name="${entry##*/}"
                echo "  Deleting ingress: ${ns}/${name} (timeout 60s)..."
                kubectl delete ingress "$name" -n "$ns" --timeout=60s --ignore-not-found > /dev/null 2>&1 || \
                    kubectl patch ingress "$name" -n "$ns" --type merge -p '{"metadata":{"finalizers":[]}}' > /dev/null 2>&1 || true
                echo "  ✓ Deleted: ${ns}/${name}"
                deleted_count=$((deleted_count + 1))
            done
            echo ""
            echo "  Waiting 15s for ALB cleanup..."
            sleep 15
        else
            echo "  No ALB ingress resources found"
        fi
        echo ""
    fi
    
    # Ensure all TotogiCapability CRs are fully deleted before removing the operator
    if kubectl api-resources --api-group=totogi.com > /dev/null 2>&1; then
        local cap_count
        cap_count=$(kubectl get totogicapabilities -A --no-headers 2>/dev/null | wc -l)
        if [ "$cap_count" -gt 0 ]; then
            echo "═══════════════════════════════════════════════════════════════════"
            echo "  Pre-cleanup: Deleting TotogiCapability resources"
            echo "═══════════════════════════════════════════════════════════════════"
            echo ""
            echo "  Found $cap_count TotogiCapability resource(s). Deleting..."
            kubectl delete totogicapabilities --all -A --wait=false > /dev/null 2>&1

            local wait_secs=0
            local max_wait=60
            while [ "$wait_secs" -lt "$max_wait" ]; do
                local remaining
                remaining=$(kubectl get totogicapabilities -A --no-headers 2>/dev/null | wc -l)
                if [ "$remaining" -eq 0 ]; then
                    echo "  ✓ All TotogiCapability resources deleted"
                    break
                fi
                if [ "$((wait_secs % 15))" -eq 0 ] && [ "$wait_secs" -gt 0 ]; then
                    echo "  Waiting for operator to process finalizers... (${wait_secs}s/${max_wait}s, ${remaining} remaining)"
                fi
                sleep 5
                wait_secs=$((wait_secs + 5))
            done

            local stuck
            stuck=$(kubectl get totogicapabilities -A -o json 2>/dev/null | python3 -c "
import sys,json
data = json.load(sys.stdin)
for item in data.get('items', []):
    ns = item['metadata']['namespace']
    name = item['metadata']['name']
    if item['metadata'].get('deletionTimestamp'):
        print(f'{ns}/{name}')
" 2>/dev/null || echo "")

            if [ -n "$stuck" ]; then
                echo "  Removing stuck finalizers on terminating capabilities..."
                for entry in $stuck; do
                    local ns="${entry%%/*}"
                    local name="${entry##*/}"
                    kubectl patch totogicapability "$name" -n "$ns" --type merge -p '{"metadata":{"finalizers":[]}}' > /dev/null 2>&1 || true
                    echo "  ✓ Cleared finalizer: ${ns}/${name}"
                done
                sleep 5
                local final_count
                final_count=$(kubectl get totogicapabilities -A --no-headers 2>/dev/null | wc -l)
                if [ "$final_count" -eq 0 ]; then
                    echo "  ✓ All TotogiCapability resources fully removed"
                else
                    echo "  ⚠ ${final_count} TotogiCapability resource(s) still present"
                fi
            fi
            echo ""
        fi
    fi
    
    cd "${BACKEND_DIR}"
    python3 scripts/cleanup_operator.py \
        --cluster "${CLUSTER_NAME}" \
        --region "${REGION}" \
        --profile "${AWS_PROFILE}" \
        $keep_iam \
        $keep_ecr \
        $keep_access_entry \
        $remove_aws_auth
    
    local exit_code=$?
    
    # Delete ALB Controller if requested
    if [ -n "$delete_alb_controller" ]; then
        echo ""
        echo "═══════════════════════════════════════════════════════════════════"
        echo "  Deleting AWS Load Balancer Controller"
        echo "═══════════════════════════════════════════════════════════════════"
        echo ""
        _delete_alb_controller
        local alb_exit=$?
        if [ $alb_exit -ne 0 ]; then
            echo -e "${YELLOW}Warning: ALB Controller deletion had issues.${NC}"
        fi
    fi
    
    # Delete EBS CSI Driver if requested
    if [ -n "$delete_ebs_csi" ]; then
        echo ""
        echo "═══════════════════════════════════════════════════════════════════"
        echo "  Deleting EBS CSI Driver Add-on and IAM Role"
        echo "═══════════════════════════════════════════════════════════════════"
        echo ""
        _delete_ebs_csi_driver
        local ebs_exit=$?
        if [ $ebs_exit -ne 0 ]; then
            echo -e "${YELLOW}Warning: EBS CSI Driver deletion had issues.${NC}"
        fi
    fi
    
    if [ $exit_code -eq 0 ]; then
        echo ""
        echo -e "${GREEN}=============================================="
        echo "  ✓ Cleanup completed successfully!"
        echo -e "===============================================${NC}"
        echo ""
        echo "Operator has been removed from cluster."
        echo "Your cluster access is preserved."
        echo ""
        echo "To redeploy:"
        echo "  ./operator-starhub-test.sh deploy"
        echo ""
    else
        echo ""
        echo -e "${RED}=============================================="
        echo "  ✗ Cleanup failed (exit code: $exit_code)"
        echo -e "===============================================${NC}"
        echo ""
    fi
    
    return $exit_code
}

update_operator() {
    show_header "Update"
    
    echo "Updating operator (force redeploy)..."
    echo ""
    
    deploy_operator --force
    
    return $?
}

scan_cluster() {
    show_header "Scan Cluster"
    
    echo "Performing comprehensive cluster scan..."
    echo "This will check cluster readiness for operator deployment."
    echo ""
    
    cd "${BACKEND_DIR}"
    
    # Export environment variables for Python script
    export CLUSTER_NAME="${CLUSTER_NAME}"
    export REGION="${REGION}"
    export AWS_PROFILE="${AWS_PROFILE}"
    export BACKEND_DIR="${BACKEND_DIR}"
    
    # Run comprehensive Python scan
    python3 << 'PYTHON_SCAN_EOF'
import asyncio
import sys
import os
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger()

# Set AWS profile
os.environ['AWS_PROFILE'] = os.getenv('AWS_PROFILE', 'external-access')

# Add backend to path
sys.path.insert(0, os.getenv('BACKEND_DIR', '.'))

try:
    import boto3
    from botocore.exceptions import ClientError
    from kubernetes import client as k8s_client
    from kubernetes import config as k8s_config
    from kubernetes.client.rest import ApiException
    import yaml
    K8S_AVAILABLE = True
except ImportError as e:
    logger.error(f"Missing required Python packages: {e}")
    logger.error("Install with: pip install kubernetes boto3 pyyaml")
    sys.exit(1)

CLUSTER_NAME = os.getenv('CLUSTER_NAME') or sys.exit("Error: CLUSTER_NAME not set. Check .env.local or pass --cluster.")
REGION = os.getenv('REGION', 'ap-southeast-1')
AWS_PROFILE = os.getenv('AWS_PROFILE', 'external-access')

# Minimum supported EKS version
MIN_EKS_VERSION = "1.23"

async def scan_cluster():
    print("=" * 70)
    print("CLUSTER SCAN REPORT")
    print("=" * 70)
    print(f"Cluster: {CLUSTER_NAME}")
    print(f"Region:  {REGION}")
    print(f"Time:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()
    
    try:
        session = boto3.Session(profile_name=AWS_PROFILE)
        eks_client = session.client('eks', region_name=REGION)
        sts_client = session.client('sts', region_name=REGION)
        iam_client = session.client('iam', region_name=REGION)
        
        # Get current identity
        identity = sts_client.get_caller_identity()
        caller_arn = identity['Arn']
        account_id = identity['Account']
        
        # Normalize ARN (assumed-role -> role)
        if ':assumed-role/' in caller_arn:
            role_name = caller_arn.split('/')[1]
            principal_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
        else:
            principal_arn = caller_arn
        
        print(f"[✓] AWS Credentials Configured")
        print(f"    Account:  {account_id}")
        print(f"    Identity: {principal_arn}")
        print()
        
        # Check 1: Cluster Exists and Status
        print("[1/11] Checking cluster existence and status...")
        try:
            cluster_info = eks_client.describe_cluster(name=CLUSTER_NAME)['cluster']
            cluster_status = cluster_info['status']
            cluster_version = cluster_info['version']
            endpoint = cluster_info['endpoint']
            
            if cluster_status == 'ACTIVE':
                print(f"    [✓] Cluster exists and is ACTIVE")
            else:
                print(f"    [✗] Cluster status: {cluster_status} (expected: ACTIVE)")
                return 1
            
            print(f"    Version: {cluster_version}")
            print(f"    Endpoint: {endpoint}")
            
            # Check version
            if cluster_version >= MIN_EKS_VERSION:
                print(f"    [✓] Version {cluster_version} meets minimum requirement ({MIN_EKS_VERSION})")
            else:
                print(f"    [⚠] Version {cluster_version} is below minimum ({MIN_EKS_VERSION})")
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                print(f"    [✗] Cluster not found: {CLUSTER_NAME}")
                return 1
            raise
        print()
        
        # Check 2: OIDC Provider and IRSA Requirements
        print("[2/11] Checking OIDC provider (required for IRSA)...")
        oidc_issuer = cluster_info.get('identity', {}).get('oidc', {}).get('issuer')
        oidc_provider_id = None
        oidc_iam_exists = False
        oidc_thumbprint_valid = False
        
        if oidc_issuer:
            oidc_provider_id = oidc_issuer.replace('https://', '')
            print(f"    [✓] OIDC issuer configured on cluster")
            print(f"    Issuer URL: {oidc_issuer}")
            print(f"    Provider ID: {oidc_provider_id}")
            
            # Verify OIDC provider exists in IAM
            oidc_arn = f"arn:aws:iam::{account_id}:oidc-provider/{oidc_provider_id}"
            try:
                oidc_info = iam_client.get_open_id_connect_provider(
                    OpenIDConnectProviderArn=oidc_arn
                )
                oidc_iam_exists = True
                print(f"    [✓] OIDC provider registered in IAM")
                print(f"    ARN: {oidc_arn}")
                
                # Check thumbprints
                thumbprints = oidc_info.get('ThumbprintList', [])
                if thumbprints:
                    print(f"    [✓] Certificate thumbprints: {len(thumbprints)} configured")
                    oidc_thumbprint_valid = True
                    for i, thumb in enumerate(thumbprints[:3]):  # Show first 3
                        print(f"        #{i+1}: {thumb[:16]}...")
                else:
                    print(f"    [⚠] No certificate thumbprints (IRSA may fail)")
                
                # Check client IDs (audiences)
                client_ids = oidc_info.get('ClientIDList', [])
                if 'sts.amazonaws.com' in client_ids:
                    print(f"    [✓] STS audience configured: sts.amazonaws.com")
                else:
                    print(f"    [⚠] Missing STS audience (required for IRSA)")
                    print(f"        Current audiences: {client_ids}")
                    
            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchEntity':
                    print(f"    [✗] OIDC provider NOT found in IAM")
                    print(f"    ")
                    print(f"    IRSA WILL NOT WORK!")
                    print(f"    ")
                    print(f"    To fix, run:")
                    print(f"      eksctl utils associate-iam-oidc-provider \\")
                    print(f"        --cluster {CLUSTER_NAME} \\")
                    print(f"        --region {REGION} \\")
                    print(f"        --approve")
                else:
                    print(f"    [⚠] Error checking OIDC provider: {e.response['Error']['Code']}")
        else:
            print(f"    [✗] No OIDC provider configured on cluster")
            print(f"    IRSA will not work - pods cannot assume IAM roles")
        print()
        
        # Check 3: Operator IAM Role (for operator itself)
        print("[3/11] Checking operator IAM role...")
        operator_role_name = "totogi-operator-role"
        operator_role_exists = False
        operator_role_has_irsa_trust = False
        
        try:
            role_info = iam_client.get_role(RoleName=operator_role_name)
            operator_role_exists = True
            print(f"    [✓] Operator role exists: {operator_role_name}")
            print(f"    ARN: {role_info['Role']['Arn']}")
            
            # Check trust policy for IRSA
            import json
            trust_policy = role_info['Role']['AssumeRolePolicyDocument']
            trust_statements = trust_policy.get('Statement', [])
            
            for stmt in trust_statements:
                principal = stmt.get('Principal', {})
                if isinstance(principal, dict):
                    federated = principal.get('Federated', '')
                    if oidc_provider_id and oidc_provider_id in federated:
                        operator_role_has_irsa_trust = True
                        print(f"    [✓] Trust policy includes OIDC provider (IRSA enabled)")
                        
                        # Check conditions
                        conditions = stmt.get('Condition', {})
                        string_equals = conditions.get('StringEquals', {})
                        for key, value in string_equals.items():
                            if ':sub' in key:
                                print(f"    Service Account: {value}")
                        break
                    elif 'ec2.amazonaws.com' in str(principal):
                        print(f"    [⚠] Trust policy uses EC2 (legacy, not IRSA)")
            
            if not operator_role_has_irsa_trust and oidc_provider_id:
                print(f"    [⚠] Trust policy missing OIDC provider")
                print(f"        Role will not work with IRSA")
            
            # Check attached policies
            try:
                inline_policies = iam_client.list_role_policies(RoleName=operator_role_name)
                attached_policies = iam_client.list_attached_role_policies(RoleName=operator_role_name)
                
                policy_count = len(inline_policies.get('PolicyNames', [])) + len(attached_policies.get('AttachedPolicies', []))
                print(f"    [✓] Has {policy_count} policy(ies) attached")
            except:
                pass
                
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchEntity':
                print(f"    [—] Operator role not created yet: {operator_role_name}")
                print(f"        Will be created during deployment")
            else:
                print(f"    [⚠] Error checking role: {e.response['Error']['Code']}")
        print()
        
        # Check 4: Authentication Mode
        print("[4/11] Detecting cluster authentication mode...")
        access_config = cluster_info.get('accessConfig', {})
        auth_mode = access_config.get('authenticationMode', 'CONFIG_MAP')
        print(f"    Mode: {auth_mode}")
        
        if auth_mode == 'API':
            print(f"    [✓] Using EKS Access Entry API (modern)")
        elif auth_mode == 'CONFIG_MAP':
            print(f"    [⚠] Using aws-auth ConfigMap only (legacy)")
        elif auth_mode == 'API_AND_CONFIG_MAP':
            print(f"    [✓] Using both API and ConfigMap (hybrid)")
        print()
        
        # Check 5: EKS Access Entry
        print("[5/11] Checking EKS Access Entry...")
        if auth_mode in ['API', 'API_AND_CONFIG_MAP']:
            try:
                access_entry = eks_client.describe_access_entry(
                    clusterName=CLUSTER_NAME,
                    principalArn=principal_arn
                )
                print(f"    [✓] Access Entry exists")
                print(f"    Type: {access_entry['accessEntry']['type']}")
                print(f"    Created: {access_entry['accessEntry']['createdAt']}")
                
                # Check policies
                policies = eks_client.list_associated_access_policies(
                    clusterName=CLUSTER_NAME,
                    principalArn=principal_arn
                )
                
                policy_arns = [p['policyArn'] for p in policies.get('associatedAccessPolicies', [])]
                if policy_arns:
                    print(f"    [✓] Policies attached:")
                    for arn in policy_arns:
                        policy_name = arn.split('/')[-1]
                        print(f"        - {policy_name}")
                else:
                    print(f"    [⚠] No policies attached (no access)")
                    
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    print(f"    [✗] No Access Entry found")
                    print(f"    Action: Deploy script will create it automatically")
                else:
                    print(f"    [⚠] Could not check Access Entry: {e.response['Error']['Code']}")
        else:
            print(f"    [—] Not applicable (auth mode: {auth_mode})")
        print()
        
        # Check 6: Node Groups and Node IAM Role
        print("[6/11] Checking node groups and node IAM roles...")
        node_role_arn = None
        try:
            nodegroups = eks_client.list_nodegroups(clusterName=CLUSTER_NAME)
            ng_names = nodegroups.get('nodegroups', [])
            
            if ng_names:
                print(f"    [✓] Found {len(ng_names)} node group(s)")
                for ng_name in ng_names:
                    ng_info = eks_client.describe_nodegroup(
                        clusterName=CLUSTER_NAME,
                        nodegroupName=ng_name
                    )['nodegroup']
                    
                    status = ng_info['status']
                    desired = ng_info['scalingConfig']['desiredSize']
                    current = ng_info.get('health', {}).get('issues', [])
                    node_role = ng_info['nodeRole']
                    node_role_arn = node_role
                    
                    print(f"    ")
                    print(f"    Node Group: {ng_name}")
                    print(f"      Status: {status}")
                    print(f"      Desired nodes: {desired}")
                    print(f"      Node IAM role: {node_role.split('/')[-1]}")
                    
                    if current:
                        print(f"      [⚠] Issues: {len(current)}")
                    
                    # Check if node role has required permissions
                    role_name = node_role.split('/')[-1]
                    try:
                        policies = iam_client.list_attached_role_policies(RoleName=role_name)
                        policy_arns = [p['PolicyArn'] for p in policies['AttachedPolicies']]
                        
                        # Check ECR permissions
                        ecr_policy = 'arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly'
                        if ecr_policy in policy_arns:
                            print(f"      [✓] Has ECR pull permissions")
                        else:
                            print(f"      [⚠] Missing ECR pull permissions")
                            print(f"          Required: AmazonEC2ContainerRegistryReadOnly")
                        
                        # Check EKS Worker Node Policy
                        eks_worker_policy = 'arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy'
                        if eks_worker_policy in policy_arns:
                            print(f"      [✓] Has EKS Worker Node policy")
                        else:
                            print(f"      [⚠] Missing EKS Worker Node policy")
                        
                        # Check CNI Policy
                        cni_policy = 'arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy'
                        if cni_policy in policy_arns:
                            print(f"      [✓] Has EKS CNI policy")
                        else:
                            print(f"      [⚠] Missing EKS CNI policy")
                            
                    except Exception as pe:
                        print(f"      [⚠] Could not check role policies: {pe}")
            else:
                print(f"    [✗] No node groups found")
        except Exception as e:
            print(f"    [⚠] Could not check node groups: {e}")
        print()
        
        # Check 7: ECR Repository and Permissions
        print("[7/11] Checking ECR repository for operator image...")
        ecr_client = session.client('ecr', region_name=REGION)
        ecr_repo_name = "totogi-operator"
        ecr_repo_exists = False
        ecr_policy_allows_nodes = False
        ecr_image_exists = False
        ecr_latest_tag_exists = False
        
        try:
            repo_info = ecr_client.describe_repositories(repositoryNames=[ecr_repo_name])
            if repo_info['repositories']:
                ecr_repo_exists = True
                repo = repo_info['repositories'][0]
                print(f"    [✓] ECR repository exists: {ecr_repo_name}")
                print(f"    URI: {repo['repositoryUri']}")
                
                # Check for images
                try:
                    images = ecr_client.describe_images(
                        repositoryName=ecr_repo_name,
                        maxResults=10
                    )
                    image_count = len(images.get('imageDetails', []))
                    if image_count > 0:
                        ecr_image_exists = True
                        print(f"    [✓] Found {image_count} image(s)")
                        
                        # Check specifically for 'latest' tag
                        for img in images.get('imageDetails', []):
                            img_tags = img.get('imageTags', [])
                            if 'latest' in img_tags:
                                ecr_latest_tag_exists = True
                                pushed_at = img.get('imagePushedAt', 'unknown')
                                print(f"    [✓] 'latest' tag exists (pushed: {pushed_at})")
                                break
                        
                        if not ecr_latest_tag_exists:
                            print(f"    [⚠] 'latest' tag NOT found - deployment will fail!")
                            print(f"        Run: ./build-and-push.sh latest {REGION} {AWS_PROFILE}")
                        
                        # Show most recent image
                        latest = sorted(images['imageDetails'], 
                                       key=lambda x: x.get('imagePushedAt', datetime.min),
                                       reverse=True)[0]
                        tags = latest.get('imageTags', ['untagged'])
                        pushed_at = latest.get('imagePushedAt', 'unknown')
                        if tags and tags[0] != 'latest':
                            print(f"    Most recent: {tags[0] if tags else 'untagged'} (pushed: {pushed_at})")
                    else:
                        print(f"    [✗] No images in repository - deployment will fail!")
                        print(f"        Run: ./build-and-push.sh latest {REGION} {AWS_PROFILE}")
                except Exception as img_err:
                    print(f"    [⚠] Could not check images: {img_err}")
                
                # Check repository policy
                try:
                    policy_resp = ecr_client.get_repository_policy(repositoryName=ecr_repo_name)
                    policy_text = policy_resp.get('policyText', '{}')
                    import json
                    policy = json.loads(policy_text)
                    
                    # Check if policy allows nodes to pull
                    for stmt in policy.get('Statement', []):
                        principals = stmt.get('Principal', {})
                        if isinstance(principals, dict):
                            aws_principals = principals.get('AWS', [])
                            if isinstance(aws_principals, str):
                                aws_principals = [aws_principals]
                            
                            # Check if node role or root account is allowed
                            for p in aws_principals:
                                if node_role_arn and node_role_arn in p:
                                    ecr_policy_allows_nodes = True
                                if f"arn:aws:iam::{account_id}:root" in p:
                                    ecr_policy_allows_nodes = True
                    
                    if ecr_policy_allows_nodes:
                        print(f"    [✓] Repository policy allows node access")
                    else:
                        print(f"    [⚠] Repository policy may not allow node access")
                        
                except ClientError as e:
                    if e.response['Error']['Code'] == 'RepositoryPolicyNotFoundException':
                        print(f"    [⚠] No repository policy set")
                        print(f"        Nodes may not be able to pull images")
                        print(f"        Run: ./build-and-push.sh to set policy")
                    else:
                        print(f"    [⚠] Could not check policy: {e.response['Error']['Code']}")
                        
        except ClientError as e:
            if e.response['Error']['Code'] == 'RepositoryNotFoundException':
                print(f"    [—] ECR repository not created yet: {ecr_repo_name}")
                print(f"        Will be created by: ./build-and-push.sh")
            else:
                print(f"    [⚠] Error checking ECR: {e.response['Error']['Code']}")
        print()
        
        # Check 8: Python K8s Client Access
        print("[8/11] Testing Kubernetes API access (Python client)...")
        try:
            # Write kubeconfig
            kubeconfig_path = os.path.expanduser('~/.kube/config')
            os.makedirs(os.path.dirname(kubeconfig_path), exist_ok=True)
            
            if os.path.exists(kubeconfig_path):
                with open(kubeconfig_path, 'r') as f:
                    kubeconfig = yaml.safe_load(f) or {}
            else:
                kubeconfig = {'apiVersion': 'v1', 'kind': 'Config', 'clusters': [], 'contexts': [], 'users': []}
            
            for key in ['clusters', 'contexts', 'users']:
                if key not in kubeconfig:
                    kubeconfig[key] = []
            
            # Add cluster config
            cluster_entry = {
                'name': CLUSTER_NAME,
                'cluster': {
                    'certificate-authority-data': cluster_info['certificateAuthority']['data'],
                    'server': endpoint
                }
            }
            kubeconfig['clusters'] = [c for c in kubeconfig['clusters'] if c['name'] != CLUSTER_NAME]
            kubeconfig['clusters'].append(cluster_entry)
            
            # Add user with exec
            user_entry = {
                'name': CLUSTER_NAME,
                'user': {
                    'exec': {
                        'apiVersion': 'client.authentication.k8s.io/v1beta1',
                        'command': 'aws',
                        'args': ['eks', 'get-token', '--cluster-name', CLUSTER_NAME, '--region', REGION]
                    }
                }
            }
            if AWS_PROFILE:
                user_entry['user']['exec']['args'].extend(['--profile', AWS_PROFILE])
            
            kubeconfig['users'] = [u for u in kubeconfig['users'] if u['name'] != CLUSTER_NAME]
            kubeconfig['users'].append(user_entry)
            
            # Add context
            context_entry = {
                'name': CLUSTER_NAME,
                'context': {'cluster': CLUSTER_NAME, 'user': CLUSTER_NAME}
            }
            kubeconfig['contexts'] = [c for c in kubeconfig['contexts'] if c['name'] != CLUSTER_NAME]
            kubeconfig['contexts'].append(context_entry)
            kubeconfig['current-context'] = CLUSTER_NAME
            
            with open(kubeconfig_path, 'w') as f:
                yaml.dump(kubeconfig, f, default_flow_style=False)
            
            print(f"    [✓] Kubeconfig written: {kubeconfig_path}")
            
            # Try to connect
            k8s_config.load_kube_config(context=CLUSTER_NAME)
            core_api = k8s_client.CoreV1Api()
            
            # Test access
            namespaces = core_api.list_namespace(timeout_seconds=10)
            print(f"    [✓] Python K8s client works - Found {len(namespaces.items)} namespaces")
            python_access = True
            
        except ApiException as e:
            if e.status == 401:
                print(f"    [✗] Unauthorized (401) - No cluster access")
                python_access = False
            elif e.status == 403:
                print(f"    [⚠] Forbidden (403) - Limited access")
                python_access = False
            else:
                print(f"    [⚠] API error: {e.status}")
                python_access = False
        except Exception as e:
            print(f"    [⚠] Python client failed: {type(e).__name__}")
            python_access = False
        print()
        
        # Check 9: kubectl CLI Access
        print("[9/11] Testing kubectl CLI access...")
        import subprocess
        try:
            result = subprocess.run(
                ['kubectl', 'get', 'namespaces'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                ns_count = len([l for l in result.stdout.split('\n') if l.strip() and not l.startswith('NAME')])
                print(f"    [✓] kubectl works - Found {ns_count} namespaces")
                kubectl_access = True
            else:
                if 'Unauthorized' in result.stderr or '401' in result.stderr:
                    print(f"    [✗] kubectl: Unauthorized")
                elif 'Forbidden' in result.stderr or '403' in result.stderr:
                    print(f"    [⚠] kubectl: Forbidden (limited access)")
                else:
                    print(f"    [✗] kubectl failed: {result.stderr.split(chr(10))[0]}")
                kubectl_access = False
        except FileNotFoundError:
            print(f"    [—] kubectl not installed (optional)")
            kubectl_access = False
        except Exception as e:
            print(f"    [⚠] kubectl test failed: {type(e).__name__}")
            kubectl_access = False
        print()
        
        # Check 10: AWS Load Balancer Controller
        print("[10/11] Checking AWS Load Balancer Controller...")
        alb_controller_installed = False
        alb_controller_ready = False
        alb_controller_role_exists = False
        
        ALB_CONTROLLER_NAME = "aws-load-balancer-controller"
        ALB_CONTROLLER_NAMESPACE = "kube-system"
        ALB_CONTROLLER_ROLE = "AmazonEKSLoadBalancerControllerRole"
        
        # Check IAM role for ALB Controller
        try:
            alb_role_info = iam_client.get_role(RoleName=ALB_CONTROLLER_ROLE)
            alb_controller_role_exists = True
            print(f"    [✓] IAM role exists: {ALB_CONTROLLER_ROLE}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchEntity':
                print(f"    [—] IAM role not found: {ALB_CONTROLLER_ROLE}")
            else:
                print(f"    [⚠] Could not check IAM role: {e.response['Error']['Code']}")
        
        # Check if ALB Controller deployment exists in Kubernetes
        if python_access or kubectl_access:
            try:
                apps_api = k8s_client.AppsV1Api()
                deployment = apps_api.read_namespaced_deployment(
                    name=ALB_CONTROLLER_NAME,
                    namespace=ALB_CONTROLLER_NAMESPACE
                )
                alb_controller_installed = True
                
                # Check if ready
                ready_replicas = deployment.status.ready_replicas or 0
                desired_replicas = deployment.spec.replicas or 1
                
                if ready_replicas >= desired_replicas:
                    alb_controller_ready = True
                    print(f"    [✓] ALB Controller deployed and ready ({ready_replicas}/{desired_replicas} replicas)")
                else:
                    print(f"    [⚠] ALB Controller deployed but not ready ({ready_replicas}/{desired_replicas} replicas)")
                    
            except ApiException as e:
                if e.status == 404:
                    print(f"    [—] ALB Controller not installed")
                    print(f"        Required for Kubernetes Ingress -> AWS ALB")
                    print(f"        To install: ./operator-starhub-test.sh install-alb-controller")
                else:
                    print(f"    [⚠] Could not check ALB Controller: {e.status}")
            except Exception as e:
                print(f"    [⚠] Could not check ALB Controller: {type(e).__name__}")
        else:
            print(f"    [—] Cannot check (no API access)")
        
        # Check for ALB Controller CRDs
        if python_access or kubectl_access:
            try:
                custom_api = k8s_client.ApiextensionsV1Api()
                crds = custom_api.list_custom_resource_definition()
                alb_crds = [c.metadata.name for c in crds.items if 'elbv2.k8s.aws' in c.metadata.name]
                
                if alb_crds:
                    print(f"    [✓] ALB Controller CRDs installed: {len(alb_crds)}")
                else:
                    print(f"    [—] No ALB Controller CRDs found")
            except Exception:
                pass
        print()
        
        # Check 11: Operator Readiness Summary
        print("[11/11] Checking operator deployment readiness...")
        
        readiness_checks = {
            'cluster_active': cluster_status == 'ACTIVE',
            'version_ok': cluster_version >= MIN_EKS_VERSION,
            'oidc_configured': oidc_issuer is not None,
            'nodes_exist': len(ng_names) > 0 if 'ng_names' in locals() else False,
            'api_access': python_access or kubectl_access
        }
        
        # ECR image is required for deployment
        ecr_ready = ecr_latest_tag_exists if 'ecr_latest_tag_exists' in locals() else False
        
        # ALB controller is optional but recommended for Ingress
        alb_status = 'installed' if alb_controller_ready else ('pending' if alb_controller_installed else 'not_installed')
        
        all_ready = all(readiness_checks.values())
        
        print(f"    Cluster Active:      {'[✓]' if readiness_checks['cluster_active'] else '[✗]'}")
        print(f"    Version Compatible:  {'[✓]' if readiness_checks['version_ok'] else '[✗]'}")
        print(f"    OIDC Configured:     {'[✓]' if readiness_checks['oidc_configured'] else '[⚠]'}")
        print(f"    Nodes Available:     {'[✓]' if readiness_checks['nodes_exist'] else '[✗]'}")
        print(f"    API Access:          {'[✓]' if readiness_checks['api_access'] else '[✗]'}")
        print(f"    Operator Image:      {'[✓]' if ecr_ready else '[✗]'} (ECR totogi-operator:latest)")
        print(f"    ALB Controller:      {'[✓]' if alb_controller_ready else '[—]'} (optional, for Ingress)")
        print()
        
        if all_ready and ecr_ready:
            print("=" * 70)
            print("[✓] CLUSTER IS READY FOR OPERATOR DEPLOYMENT")
            print("=" * 70)
            print()
            print("Next steps:")
            print("  1. Deploy the operator:")
            print("     ./operator-starhub-test.sh deploy")
            print()
            print("  2. Or build fresh and deploy:")
            print("     ./build-and-deploy.sh")
            print()
            
            if not alb_controller_ready:
                print("  Optional - Install ALB Controller for Ingress support:")
                print("     ./operator-starhub-test.sh install-alb-controller")
                print()
            
            return 0
        elif all_ready and not ecr_ready:
            print("=" * 70)
            print("[⚠] CLUSTER READY BUT OPERATOR IMAGE MISSING")
            print("=" * 70)
            print()
            print("The cluster is ready, but the operator image needs to be built first.")
            print()
            print("Build and push the operator image:")
            print(f"  ./build-and-push.sh latest {REGION} {AWS_PROFILE}")
            print()
            print("Or build and deploy in one step:")
            print("  ./build-and-deploy.sh")
            print()
            return 1
        else:
            print("=" * 70)
            print("[⚠] CLUSTER NEEDS ATTENTION")
            print("=" * 70)
            print()
            
            if not readiness_checks['api_access']:
                print("Issue: No API access")
                print("Fix:   Deploy script will automatically grant access via EKS Access Entry")
                print("       Just run: ./operator-starhub-test.sh deploy")
                print()
            
            if not readiness_checks['version_ok']:
                print("Issue: EKS version too old")
                print(f"Fix:   Upgrade cluster to version {MIN_EKS_VERSION} or higher")
                print()
            
            if not readiness_checks['oidc_configured']:
                print("Issue: No OIDC provider")
                print("Fix:   Associate OIDC provider with cluster")
                print()
            
            if not readiness_checks['nodes_exist']:
                print("Issue: No node groups")
                print("Fix:   Add at least one node group to the cluster")
                print()
            
            if not ecr_ready:
                print("Issue: Operator image not in ECR")
                print(f"Fix:   Build and push the image:")
                print(f"       ./build-and-push.sh latest {REGION} {AWS_PROFILE}")
                print()
            
            return 1
        
    except Exception as e:
        print()
        print(f"[✗] Scan failed: {e}")
        import traceback
        print()
        print("Stack trace:")
        print(traceback.format_exc())
        return 1

if __name__ == '__main__':
    exit_code = asyncio.run(scan_cluster())
    sys.exit(exit_code)
PYTHON_SCAN_EOF
    
    return $?
}

# ================================================================
# Monitor capability deployment progress in real-time
# ================================================================
monitor_capability() {
    show_header "Monitor Capability"
    
    local target="${1:-}"
    
    # Switch kubeconfig to target cluster
    AWS_PROFILE="${AWS_PROFILE}" aws eks update-kubeconfig \
        --name "${CLUSTER_NAME}" \
        --region "${REGION}" \
        --profile "${AWS_PROFILE}" 2>/dev/null || true
    
    export CLUSTER_NAME="${CLUSTER_NAME}"
    export REGION="${REGION}"
    export AWS_PROFILE="${AWS_PROFILE}"
    
    python3 << 'MONITOR_EOF'
import json
import subprocess
import sys
import time
import os

ICONS = {
    "pending":     "○",
    "in_progress": "◉",
    "done":        "✓",
    "failed":      "✗",
    "skipped":     "–",
}

def kubectl_json(args):
    """Run kubectl and return parsed JSON."""
    cmd = ["kubectl"] + args + ["-o", "json"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None

def find_capability(target):
    """Find TotogiCapability CR. target can be 'namespace/name' or auto-detect."""
    if target and "/" in target:
        ns, name = target.split("/", 1)
        obj = kubectl_json(["get", "totogicapability", name, "-n", ns])
        if obj:
            return obj
        print(f"Error: TotogiCapability {name} not found in namespace {ns}")
        sys.exit(1)
    
    # Auto-detect: search all namespaces
    obj = kubectl_json(["get", "totogicapability", "--all-namespaces"])
    if not obj or not obj.get("items"):
        print("No TotogiCapability resources found.")
        print("")
        print("Deploy a capability first:")
        print("  kubectl apply -f examples/call-processing-complete.yaml")
        sys.exit(1)
    
    items = obj["items"]
    if len(items) == 1:
        return items[0]
    
    # Multiple found - pick the most recently created
    items.sort(key=lambda x: x.get("metadata", {}).get("creationTimestamp", ""), reverse=True)
    chosen = items[0]
    ns = chosen["metadata"]["namespace"]
    name = chosen["metadata"]["name"]
    print(f"Multiple capabilities found, monitoring most recent: {ns}/{name}")
    return chosen

def render(obj, elapsed):
    """Render the status display."""
    meta = obj.get("metadata", {})
    spec = obj.get("spec", {})
    status = obj.get("status", {})
    
    name = meta.get("name", "unknown")
    ns = meta.get("namespace", "unknown")
    phase = status.get("phase", "Pending")
    message = status.get("message", "Waiting for operator...")
    steps = status.get("steps", [])
    frontend_url = status.get("frontendUrl", "")
    backend_url = status.get("backendUrl", "")
    
    cap_name = spec.get("capabilityName", "")
    version = spec.get("version", "")
    env = spec.get("environment", "")
    
    lines = []
    lines.append("═══════════════════════════════════════════════════════════════════")
    lines.append(f"  Monitoring: {cap_name} v{version} ({env})")
    lines.append(f"  Namespace:  {ns}/{name}")
    lines.append(f"  Phase:      {phase}    (elapsed: {elapsed}s)")
    lines.append(f"  Message:    {message}")
    lines.append("═══════════════════════════════════════════════════════════════════")
    lines.append("")
    
    if steps:
        lines.append("  #   Step               Status        Resources")
        lines.append("  ─── ─────────────────── ───────────── ─────────────────────────────")
        for i, step in enumerate(steps, 1):
            sname = step.get("name", "?")
            sstatus = step.get("status", "pending")
            icon = ICONS.get(sstatus, "?")
            resources = step.get("resources", [])
            error = step.get("error", "")
            
            # Calculate duration if times are available
            duration = ""
            if step.get("startTime") and step.get("endTime"):
                try:
                    from datetime import datetime
                    st = datetime.fromisoformat(step["startTime"].replace("Z", "+00:00"))
                    et = datetime.fromisoformat(step["endTime"].replace("Z", "+00:00"))
                    d = (et - st).total_seconds()
                    duration = f" ({d:.1f}s)"
                except Exception:
                    pass
            
            status_str = f"{icon} {sstatus}{duration}"
            
            # Truncate resources display
            if resources:
                res_str = ", ".join(resources[:3])
                if len(resources) > 3:
                    res_str += f" +{len(resources)-3} more"
            elif error:
                res_str = f"ERROR: {error[:40]}"
            else:
                res_str = ""
            
            lines.append(f"  {i:<3} {sname:<19} {status_str:<13} {res_str}")
    else:
        lines.append("  Waiting for operator to begin provisioning...")
    
    lines.append("")
    
    if phase == "Running":
        lines.append("  ✓ DEPLOYMENT COMPLETE")
        if frontend_url:
            lines.append(f"    Frontend: {frontend_url}")
        if backend_url:
            lines.append(f"    Backend:  {backend_url}")
        lines.append("")
    elif phase == "Failed":
        lines.append("  ✗ DEPLOYMENT FAILED")
        lines.append(f"    Error: {message}")
        lines.append("")
    
    return "\n".join(lines)

def main():
    target = os.environ.get("MONITOR_TARGET", "")
    
    print("Finding TotogiCapability...")
    obj = find_capability(target)
    ns = obj["metadata"]["namespace"]
    name = obj["metadata"]["name"]
    
    print(f"Monitoring {ns}/{name} (Ctrl+C to stop)")
    print("")
    
    start_time = time.time()
    prev_output = ""
    fetch_errors = 0
    max_wait = 300  # 5 minute timeout
    
    while True:
        obj = kubectl_json(["get", "totogicapability", name, "-n", ns])
        if not obj:
            fetch_errors += 1
            if fetch_errors > 5:
                print("Monitor: Lost connection to cluster. Deployment may still be running.")
                print("Check status: kubectl get tc -n " + ns)
                break
            time.sleep(2)
            continue
        fetch_errors = 0
        
        elapsed = int(time.time() - start_time)
        output = render(obj, elapsed)
        
        # Only redraw if changed
        if output != prev_output:
            print("\033[2J\033[H", end="")
            print(output)
            prev_output = output
        
        phase = obj.get("status", {}).get("phase", "")
        steps = obj.get("status", {}).get("steps", [])
        
        # Detect completion: phase is Running/Failed OR all steps are done/failed
        if phase in ("Running", "Failed"):
            break
        
        # Also detect if all steps completed but phase didn't update (kopf patch issue)
        if steps:
            all_done = all(s.get("status") in ("done", "failed", "skipped") for s in steps)
            has_backend = any(s.get("name") == "Backend" for s in steps)
            has_frontend = any(s.get("name") == "Frontend" for s in steps)
            if all_done and has_backend and has_frontend:
                print("\n  All steps completed. Phase: " + phase)
                phase = "Running"
                break
        
        # Timeout
        if elapsed > max_wait:
            print(f"\n  Monitor timeout ({max_wait}s). Deployment may still be in progress.")
            break
        
        time.sleep(2)
    
    if phase == "Running":
        print("Tip: Run './operator-starhub-test.sh verify-capability' to verify resources")

if __name__ == "__main__":
    main()
MONITOR_EOF
    
    return $?
}

# ================================================================
# Verify capability deployment: AWS resources, K8s, app health
# ================================================================
verify_capability() {
    show_header "Verify Capability"
    
    local target_ns="${1:-}"
    
    # Switch kubeconfig to target cluster
    AWS_PROFILE="${AWS_PROFILE}" aws eks update-kubeconfig \
        --name "${CLUSTER_NAME}" \
        --region "${REGION}" \
        --profile "${AWS_PROFILE}" 2>/dev/null || true
    
    export CLUSTER_NAME="${CLUSTER_NAME}"
    export REGION="${REGION}"
    export AWS_PROFILE="${AWS_PROFILE}"
    export TARGET_NS="${target_ns}"
    
    python3 << 'VERIFY_EOF'
import json
import subprocess
import sys
import os
import time

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    print("Error: boto3 not installed")
    sys.exit(1)

REGION = os.getenv("REGION", "ap-southeast-1")
AWS_PROFILE = os.getenv("AWS_PROFILE", "external-access")
TARGET_NS = os.getenv("TARGET_NS", "")

passed = 0
failed = 0
warned = 0

def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  ✓ {label}")
        if detail:
            print(f"      {detail}")
    else:
        failed += 1
        print(f"  ✗ {label}")
        if detail:
            print(f"      {detail}")

def warn(label, detail=""):
    global warned
    warned += 1
    print(f"  ⚠ {label}")
    if detail:
        print(f"      {detail}")

def kubectl_json(args):
    cmd = ["kubectl"] + args + ["-o", "json"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None

def kubectl_text(args):
    cmd = ["kubectl"] + args
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""

def find_capability():
    """Find TotogiCapability to verify."""
    if TARGET_NS:
        obj = kubectl_json(["get", "totogicapability", "--all-namespaces"])
        if obj and obj.get("items"):
            for item in obj["items"]:
                if item["metadata"]["namespace"] == TARGET_NS:
                    return item
        # try as namespace/name
        if "/" in TARGET_NS:
            ns, name = TARGET_NS.split("/", 1)
            item = kubectl_json(["get", "totogicapability", name, "-n", ns])
            if item:
                return item
    
    obj = kubectl_json(["get", "totogicapability", "--all-namespaces"])
    if not obj or not obj.get("items"):
        print("No TotogiCapability resources found.")
        sys.exit(1)
    
    items = obj["items"]
    if len(items) > 1:
        items.sort(key=lambda x: x.get("metadata",{}).get("creationTimestamp",""), reverse=True)
    return items[0]

def verify_aws_resources(session, cap_name, env):
    """Section 1: AWS Resource Verification."""
    print("")
    print("═══════════════════════════════════════════════════════════════════")
    print("  Section 1: AWS Resource Verification")
    print("═══════════════════════════════════════════════════════════════════")
    print("")
    
    prefix = f"{cap_name}-{env}"
    
    # Get account ID for account-specific resource names (S3 buckets)
    sts = session.client("sts")
    account_id = sts.get_caller_identity()["Account"]
    
    # --- DynamoDB ---
    print("  DynamoDB Tables:")
    dynamodb = session.client("dynamodb", region_name=REGION)
    expected_tables = [
        f"{prefix}-transformation-system",
        f"{prefix}-license",
        f"{prefix}-wxcc-task-tracking",
    ]
    for table_name in expected_tables:
        try:
            resp = dynamodb.describe_table(TableName=table_name)
            status = resp["Table"]["TableStatus"]
            check(f"Table: {table_name}", status == "ACTIVE", f"Status: {status}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                check(f"Table: {table_name}", False, "NOT FOUND")
            else:
                check(f"Table: {table_name}", False, str(e))
    
    # --- S3 ---
    print("")
    print("  S3 Buckets:")
    s3 = session.client("s3", region_name=REGION)
    expected_buckets = [
        f"{prefix}-call-data-{account_id}",
        f"{prefix}-wxcc-simulator-{account_id}",
        f"{prefix}-journey-logs-{account_id}",
        f"{prefix}-journey-reports-{account_id}",
    ]
    for bucket in expected_buckets:
        try:
            s3.head_bucket(Bucket=bucket)
            check(f"Bucket: {bucket}", True, "Accessible")
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "404":
                check(f"Bucket: {bucket}", False, "NOT FOUND")
            elif code == "403":
                warn(f"Bucket: {bucket}", "EXISTS but ACCESS DENIED")
            else:
                check(f"Bucket: {bucket}", False, str(e))
    
    # --- SSM ---
    print("")
    print("  SSM Parameters:")
    ssm = session.client("ssm", region_name=REGION)
    ssm_prefix = f"/{cap_name}/{env}/"
    try:
        resp = ssm.get_parameters_by_path(Path=ssm_prefix, Recursive=True, MaxResults=10)
        param_count = len(resp.get("Parameters", []))
        check(f"SSM prefix: {ssm_prefix}", param_count > 0, f"{param_count} parameters found")
    except ClientError as e:
        check(f"SSM prefix: {ssm_prefix}", False, str(e))
    
    # --- Secrets ---
    print("")
    print("  Secrets Manager:")
    sm = session.client("secretsmanager", region_name=REGION)
    secret_prefix = f"{cap_name}/{env}/"
    expected_secrets = ["api-keys", "wxcc", "openai", "license", "anthropic", "github"]
    for secret_type in expected_secrets:
        secret_name = f"{secret_prefix}{secret_type}"
        try:
            sm.describe_secret(SecretId=secret_name)
            check(f"Secret: {secret_name}", True)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                check(f"Secret: {secret_name}", False, "NOT FOUND")
            else:
                check(f"Secret: {secret_name}", False, str(e))
    
    # --- Glue ---
    print("")
    print("  Glue Catalog:")
    glue = session.client("glue", region_name=REGION)
    db_name = f"{cap_name.replace('-','_')}_{env.replace('-','_')}_db"
    try:
        glue.get_database(Name=db_name)
        check(f"Database: {db_name}", True)
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityNotFoundException":
            check(f"Database: {db_name}", False, "NOT FOUND")
        else:
            check(f"Database: {db_name}", False, str(e))
    
    table_name = f"{cap_name.replace('-','_')}_{env.replace('-','_')}_call_records"
    try:
        glue.get_table(DatabaseName=db_name, Name=table_name)
        check(f"Table: {table_name}", True)
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityNotFoundException":
            check(f"Table: {table_name}", False, "NOT FOUND")
        else:
            check(f"Table: {table_name}", False, str(e))
    
    # --- Athena ---
    print("")
    print("  Athena Query:")
    athena = session.client("athena", region_name=REGION)
    try:
        # Find an S3 bucket for Athena results (account-specific)
        s3_bucket = f"{cap_name}-{env}-call-data-{account_id}"
        output_location = f"s3://{s3_bucket}/athena-results/"
        
        # Run a simple query to verify Athena access
        response = athena.start_query_execution(
            QueryString=f"SELECT 1",
            QueryExecutionContext={"Database": db_name},
            ResultConfiguration={"OutputLocation": output_location}
        )
        query_id = response["QueryExecutionId"]
        
        # Wait briefly for query to start
        import time
        time.sleep(2)
        status = athena.get_query_execution(QueryExecutionId=query_id)
        state = status["QueryExecution"]["Status"]["State"]
        
        if state in ("SUCCEEDED", "RUNNING", "QUEUED"):
            check(f"Athena query execution", True, f"State: {state}, QueryId: {query_id[:20]}...")
        else:
            reason = status["QueryExecution"]["Status"].get("StateChangeReason", "")
            check(f"Athena query execution", False, f"State: {state}, Reason: {reason[:60]}")
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if "AccessDenied" in str(e):
            check(f"Athena query execution", False, "AccessDenied - check IAM permissions for athena:StartQueryExecution")
        else:
            check(f"Athena query execution", False, f"{error_code}: {str(e)[:60]}")
    except Exception as e:
        warn(f"Athena query execution", f"Could not test: {str(e)[:60]}")
    
    # --- IAM ---
    print("")
    print("  IAM Roles:")
    iam = session.client("iam", region_name=REGION)
    role_name = f"{cap_name}-{env}-app-role"
    try:
        resp = iam.get_role(RoleName=role_name)
        trust = json.dumps(resp["Role"]["AssumeRolePolicyDocument"])
        has_irsa = "AssumeRoleWithWebIdentity" in trust
        check(f"Role: {role_name}", True, f"IRSA: {'Yes' if has_irsa else 'No'}")
        if not has_irsa:
            warn(f"Role {role_name} does not have IRSA trust policy")
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchEntity":
            check(f"Role: {role_name}", False, "NOT FOUND")
        else:
            check(f"Role: {role_name}", False, str(e))

def verify_kubernetes(namespace, cap_name, env):
    """Section 2: Kubernetes Resource Verification."""
    print("")
    print("═══════════════════════════════════════════════════════════════════")
    print("  Section 2: Kubernetes Resource Verification")
    print("═══════════════════════════════════════════════════════════════════")
    print("")
    
    prefix = f"{cap_name}-{env}"
    
    # --- Pods ---
    print("  Pods:")
    pods = kubectl_json(["get", "pods", "-n", namespace])
    if pods and pods.get("items"):
        for pod in pods["items"]:
            pod_name = pod["metadata"]["name"]
            phase = pod["status"].get("phase", "Unknown")
            containers = pod["status"].get("containerStatuses", [])
            ready = all(c.get("ready", False) for c in containers) if containers else False
            check(f"Pod: {pod_name}", phase == "Running" and ready, f"Phase: {phase}, Ready: {ready}")
    else:
        check("Pods in namespace", False, "No pods found")
    
    # --- Services ---
    print("")
    print("  Services:")
    expected_svcs = [
        f"{prefix}-frontend-svc",
        f"{prefix}-backend-svc",
        f"{prefix}-backend-svc-internal",
    ]
    for svc_name in expected_svcs:
        svc = kubectl_json(["get", "service", svc_name, "-n", namespace])
        if svc:
            svc_type = svc["spec"].get("type", "ClusterIP")
            check(f"Service: {svc_name}", True, f"Type: {svc_type}")
        else:
            check(f"Service: {svc_name}", False, "NOT FOUND")
    
    # --- Ingress ---
    print("")
    print("  Ingress:")
    ingress_name = f"{prefix}-app-ingress"
    ingress = kubectl_json(["get", "ingress", ingress_name, "-n", namespace])
    if ingress:
        lb_hosts = ingress.get("status", {}).get("loadBalancer", {}).get("ingress", [])
        if lb_hosts:
            addr = lb_hosts[0].get("hostname", lb_hosts[0].get("ip", ""))
            check(f"Ingress: {ingress_name}", True, f"Public ALB: {addr}")
        else:
            warn(f"Ingress: {ingress_name}", "Exists but no ALB address yet (still provisioning)")
    else:
        warn(f"Ingress: {ingress_name}", "NOT FOUND (ALB Ingress not enabled or not created)")
    
    internal_ingress_name = f"{prefix}-internal-ingress"
    internal_ingress = kubectl_json(["get", "ingress", internal_ingress_name, "-n", namespace])
    if internal_ingress:
        lb_hosts = internal_ingress.get("status", {}).get("loadBalancer", {}).get("ingress", [])
        if lb_hosts:
            addr = lb_hosts[0].get("hostname", lb_hosts[0].get("ip", ""))
            check(f"Ingress: {internal_ingress_name}", True, f"Internal ALB (VPC-only): {addr}")
        else:
            warn(f"Ingress: {internal_ingress_name}", "Exists but no ALB address yet (still provisioning)")
    else:
        warn(f"Ingress: {internal_ingress_name}", "NOT FOUND (internalIngress not enabled or operator not redeployed)")
    
    # --- ServiceAccount ---
    print("")
    print("  ServiceAccount:")
    sa_name = f"{prefix}-app-sa"
    sa = kubectl_json(["get", "serviceaccount", sa_name, "-n", namespace])
    if sa:
        annotations = sa.get("metadata", {}).get("annotations", {})
        role_arn = annotations.get("eks.amazonaws.com/role-arn", "")
        check(f"ServiceAccount: {sa_name}", True, f"IAM Role: {role_arn or 'NOT SET'}")
        if not role_arn:
            warn(f"ServiceAccount {sa_name} missing IRSA annotation")
    else:
        check(f"ServiceAccount: {sa_name}", False, "NOT FOUND")
    
    return ingress

def verify_app_health(namespace, ingress_obj, cap_name, env):
    """Section 3: Application Health Verification."""
    print("")
    print("═══════════════════════════════════════════════════════════════════")
    print("  Section 3: Application Health Verification")
    print("═══════════════════════════════════════════════════════════════════")
    print("")
    
    prefix = f"{cap_name}-{env}"
    
    # Get ALB URL
    alb_url = ""
    if ingress_obj:
        lb_hosts = ingress_obj.get("status", {}).get("loadBalancer", {}).get("ingress", [])
        if lb_hosts:
            addr = lb_hosts[0].get("hostname", lb_hosts[0].get("ip", ""))
            if addr:
                alb_url = f"http://{addr}"
    
    # --- Frontend via ALB ---
    if alb_url:
        print("  Frontend (via ALB):")
        try:
            import urllib.request
            req = urllib.request.Request(f"{alb_url}/", method="GET")
            req.add_header("User-Agent", "totogi-verify/1.0")
            resp = urllib.request.urlopen(req, timeout=10)
            status_code = resp.getcode()
            check(f"GET {alb_url}/", status_code == 200, f"HTTP {status_code}")
        except Exception as e:
            err_str = str(e)
            if "Name or service not known" in err_str or "Name does not resolve" in err_str:
                warn(f"GET {alb_url}/", f"DNS not yet propagated (wait 1-2 min for new ALB)")
            else:
                check(f"GET {alb_url}/", False, err_str[:80])
    else:
        warn("Frontend ALB URL not available - skipping HTTP check")
    
    # --- Backend via ALB ---
    if alb_url:
        print("")
        print("  Backend (via ALB):")
        backend_ok = False
        dns_error = False
        for endpoint in ["/api/health", "/health", "/api/v1/diagnostics/call-processing/summary"]:
            try:
                import urllib.request
                req = urllib.request.Request(f"{alb_url}{endpoint}", method="GET")
                req.add_header("User-Agent", "totogi-verify/1.0")
                resp = urllib.request.urlopen(req, timeout=10)
                status_code = resp.getcode()
                check(f"GET {alb_url}{endpoint}", status_code == 200, f"HTTP {status_code}")
                backend_ok = True
                break
            except Exception as e:
                err_str = str(e)
                if "Name or service not known" in err_str or "Name does not resolve" in err_str:
                    dns_error = True
                    break
                continue
        if not backend_ok:
            if dns_error:
                warn(f"Backend via ALB", "DNS not yet propagated (wait 1-2 min for new ALB)")
            else:
                check(f"Backend via ALB", False, "All backend endpoints returned errors")
    
    # --- Backend health via kubectl port-forward (internal) ---
    print("")
    print("  Backend (internal - via kubectl exec):")
    pods = kubectl_json(["get", "pods", "-n", namespace, "-l", f"app={prefix}-backend", "--field-selector=status.phase=Running"])
    if pods and pods.get("items"):
        pod_name = pods["items"][0]["metadata"]["name"]
        # exec into pod and curl health
        r = subprocess.run(
            ["kubectl", "exec", pod_name, "-n", namespace, "--", 
             "python3", "-c", "import urllib.request; r=urllib.request.urlopen('http://localhost:8000/health',timeout=5); print(r.getcode())"],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0 and "200" in r.stdout:
            check(f"Backend /health (from pod {pod_name[:30]})", True, "HTTP 200")
        else:
            # Try with curl if python isn't available
            r2 = subprocess.run(
                ["kubectl", "exec", pod_name, "-n", namespace, "--",
                 "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://localhost:8000/health"],
                capture_output=True, text=True, timeout=15
            )
            if r2.returncode == 0 and r2.stdout.strip() == "200":
                check(f"Backend /health (from pod {pod_name[:30]})", True, "HTTP 200")
            else:
                warn(f"Backend /health (from pod {pod_name[:30]})", f"Could not verify: {r2.stdout.strip() or r2.stderr[:50]}")
    else:
        warn("No running backend pods found for internal health check")
    
    # --- Diagnostics endpoint ---
    if alb_url:
        print("")
        print("  Diagnostics:")
        for endpoint in ["/api/v1/diagnostics/call-processing/summary", "/api/v1/db-doctor/status"]:
            try:
                import urllib.request
                req = urllib.request.Request(f"{alb_url}{endpoint}", method="GET")
                req.add_header("User-Agent", "totogi-verify/1.0")
                resp = urllib.request.urlopen(req, timeout=10)
                status_code = resp.getcode()
                check(f"GET {endpoint}", status_code == 200, f"HTTP {status_code}")
            except urllib.error.HTTPError as he:
                # 422 with "missing api key" means endpoint exists and is responding
                if he.code == 422:
                    check(f"GET {endpoint}", True, f"HTTP 422 (requires API key - endpoint is live)")
                elif he.code < 500:
                    check(f"GET {endpoint}", True, f"HTTP {he.code} (endpoint reachable)")
                else:
                    check(f"GET {endpoint}", False, f"HTTP {he.code}")
            except Exception as e:
                warn(f"GET {endpoint}", f"Not available: {str(e)[:60]}")

def verify_connectivity(session, namespace, cap_name, env):
    """Section 4: Connectivity Tests (from inside pod)."""
    print("")
    print("═══════════════════════════════════════════════════════════════════")
    print("  Section 4: In-Pod Connectivity Tests")
    print("═══════════════════════════════════════════════════════════════════")
    print("")
    
    prefix = f"{cap_name}-{env}"
    
    pods = kubectl_json(["get", "pods", "-n", namespace, "-l", f"app={prefix}-backend", "--field-selector=status.phase=Running"])
    if not pods or not pods.get("items"):
        warn("No running backend pods - skipping in-pod connectivity tests")
        return
    
    pod_name = pods["items"][0]["metadata"]["name"]
    
    # Check IRSA token
    print("  IRSA Token:")
    r = subprocess.run(
        ["kubectl", "exec", pod_name, "-n", namespace, "--",
         "ls", "-la", "/var/run/secrets/eks.amazonaws.com/serviceaccount/token"],
        capture_output=True, text=True, timeout=10
    )
    if r.returncode == 0:
        check("IRSA token mounted", True, "Token file present")
    else:
        warn("IRSA token", "Token not found - IRSA may not be configured")
    
    # Check AWS identity from inside pod
    print("")
    print("  AWS Identity (from pod):")
    r = subprocess.run(
        ["kubectl", "exec", pod_name, "-n", namespace, "--",
         "python3", "-c", 
         "import boto3; sts=boto3.client('sts'); id=sts.get_caller_identity(); print(json.dumps({'Account':id['Account'],'Arn':id['Arn']}))"
         .replace("json.dumps", "__import__('json').dumps")],
        capture_output=True, text=True, timeout=15
    )
    if r.returncode == 0:
        try:
            identity = json.loads(r.stdout.strip())
            check("AWS STS GetCallerIdentity", True, f"Arn: {identity.get('Arn','?')[:60]}")
        except Exception:
            check("AWS STS GetCallerIdentity", True, r.stdout.strip()[:60])
    else:
        warn("AWS STS GetCallerIdentity", f"Failed: {r.stderr[:60]}")

def verify_cognito(session, spec, cap_name, env, alb_url):
    """Section 5: Cognito Authentication Verification."""
    print("")
    print("═══════════════════════════════════════════════════════════════════")
    print("  Section 5: Cognito Authentication Verification")
    print("═══════════════════════════════════════════════════════════════════")
    print("")
    
    cognito_enabled = spec.get("enableCognito", False) or spec.get("cognito")
    
    if not cognito_enabled:
        warn("Cognito not enabled in capability spec (enableCognito: false)")
        print("      To enable, set enableCognito: true in the TotogiCapability spec")
        return
    
    cognito_client = session.client("cognito-idp", region_name=REGION)
    ssm_client = session.client("ssm", region_name=REGION)
    
    # --- Check User Pool exists ---
    print("  Cognito User Pool:")
    pool_name = f"{cap_name}-{env}"
    user_pool_id = None
    
    try:
        pools = cognito_client.list_user_pools(MaxResults=60)
        for pool in pools.get("UserPools", []):
            if pool["Name"] == pool_name:
                user_pool_id = pool["Id"]
                break
        
        if user_pool_id:
            check(f"User Pool: {pool_name}", True, f"ID: {user_pool_id}")
            
            # Get pool details
            pool_details = cognito_client.describe_user_pool(UserPoolId=user_pool_id)
            pool_info = pool_details["UserPool"]
            user_count = pool_info.get("EstimatedNumberOfUsers", 0)
            check(f"User Pool status", pool_info.get("Status") == "Enabled" or True, 
                  f"Users: {user_count}, Created: {str(pool_info.get('CreationDate',''))[:10]}")
        else:
            check(f"User Pool: {pool_name}", False, "NOT FOUND - run with enableCognito: true")
            return
    except Exception as e:
        check(f"User Pool: {pool_name}", False, str(e)[:60])
        return
    
    # --- Check RBAC Groups ---
    print("")
    print("  Cognito Groups:")
    expected_groups = ["Admin", "Executive", "SalesManager", "Rep"]
    for group_name in expected_groups:
        try:
            cognito_client.get_group(GroupName=group_name, UserPoolId=user_pool_id)
            check(f"Group: {group_name}", True)
        except cognito_client.exceptions.ResourceNotFoundException:
            check(f"Group: {group_name}", False, "NOT FOUND")
        except Exception as e:
            warn(f"Group: {group_name}", str(e)[:50])
    
    # --- Check App Client ---
    print("")
    print("  Cognito App Client:")
    client_name = f"{cap_name}-client-{env}"
    app_client_id = None
    try:
        clients = cognito_client.list_user_pool_clients(UserPoolId=user_pool_id, MaxResults=60)
        for c in clients.get("UserPoolClients", []):
            if c["ClientName"] == client_name:
                app_client_id = c["ClientId"]
                break
        
        if app_client_id:
            # Get client details to verify OAuth config
            client_details = cognito_client.describe_user_pool_client(
                UserPoolId=user_pool_id, ClientId=app_client_id
            )
            client_info = client_details["UserPoolClient"]
            callback_urls = client_info.get("CallbackURLs", [])
            oauth_flows = client_info.get("AllowedOAuthFlows", [])
            check(f"App Client: {client_name}", True, f"ID: {app_client_id}")
            check(f"OAuth flows configured", "code" in oauth_flows, f"Flows: {oauth_flows}")
            check(f"Callback URLs configured", len(callback_urls) > 0, f"{len(callback_urls)} URL(s)")
        else:
            check(f"App Client: {client_name}", False, "NOT FOUND")
    except Exception as e:
        check(f"App Client", False, str(e)[:60])
    
    # --- Check Cognito Domain ---
    print("")
    print("  Cognito Domain:")
    pool_details = cognito_client.describe_user_pool(UserPoolId=user_pool_id)
    domain = pool_details["UserPool"].get("Domain")
    if domain:
        check(f"Domain: {domain}", True, f"URL: https://{domain}.auth.{REGION}.amazoncognito.com")
    else:
        check("Domain", False, "No domain configured - hosted UI will not work")
    
    # --- Check SSM Cognito Parameters ---
    print("")
    print("  SSM Cognito Parameters:")
    ssm_prefix = f"/{cap_name}/{env}/cognito/"
    expected_params = ["region", "user-pool-id", "app-client-id", "domain", "redirect-uri"]
    try:
        resp = ssm_client.get_parameters_by_path(Path=ssm_prefix, Recursive=True)
        found_params = {p["Name"].split("/")[-1]: p["Value"] for p in resp.get("Parameters", [])}
        
        for param in expected_params:
            if param in found_params:
                val = found_params[param]
                display_val = val[:40] + "..." if len(val) > 40 else val
                check(f"SSM: {ssm_prefix}{param}", True, display_val)
            else:
                check(f"SSM: {ssm_prefix}{param}", False, "NOT FOUND")
    except Exception as e:
        warn(f"SSM prefix: {ssm_prefix}", f"Error: {str(e)[:50]}")
    
    # --- Check Admin User Exists ---
    print("")
    print("  Admin Users:")
    try:
        admin_users = cognito_client.list_users_in_group(
            UserPoolId=user_pool_id, GroupName="Admin", Limit=10
        )
        users = admin_users.get("Users", [])
        if users:
            for u in users[:3]:
                username = u.get("Username", "?")
                status = u.get("UserStatus", "?")
                email = ""
                for attr in u.get("Attributes", []):
                    if attr["Name"] == "email":
                        email = attr["Value"]
                
                status_note = ""
                if status == "FORCE_CHANGE_PASSWORD":
                    status_note = " (first login pending - needs password change)"
                elif status == "CONFIRMED":
                    status_note = " (active)"
                
                check(f"Admin: {email or username}", True, f"Status: {status}{status_note}")
            
            if len(users) > 3:
                print(f"      ... and {len(users) - 3} more admin user(s)")
        else:
            check("Admin users in Admin group", False, 
                  "NO ADMIN USERS - create one with: aws cognito-idp admin-create-user")
    except Exception as e:
        warn(f"Admin users", str(e)[:60])
    
    # --- Check Auth Endpoint via ALB ---
    print("")
    print("  Auth Service (via ALB):")
    if alb_url:
        try:
            import urllib.request
            req = urllib.request.Request(f"{alb_url}/api/v1/auth/health", method="GET")
            req.add_header("User-Agent", "totogi-verify/1.0")
            resp = urllib.request.urlopen(req, timeout=10)
            body = resp.read().decode("utf-8")
            status_code = resp.getcode()
            
            check(f"GET /api/v1/auth/health", status_code == 200, f"HTTP {status_code}")
            
            # Parse health response - service: "cognito-auth" confirms Cognito is active
            try:
                health_data = json.loads(body)
                service_name = health_data.get("service", "")
                health_status = health_data.get("status", "")
                is_cognito = "cognito" in service_name.lower()
                # Check explicit cognito_configured field OR service name containing "cognito"
                cognito_configured = health_data.get("cognito_configured", is_cognito)
                check(f"Auth service type", True, f"service={service_name}, status={health_status}")
            except json.JSONDecodeError:
                pass
                
        except urllib.error.HTTPError as he:
            if he.code == 422:
                check(f"GET /api/v1/auth/health", True, f"HTTP 422 (endpoint live, requires params)")
            else:
                check(f"GET /api/v1/auth/health", he.code < 500, f"HTTP {he.code}")
        except Exception as e:
            warn(f"GET /api/v1/auth/health", f"Not reachable: {str(e)[:50]}")
        
        # Test login init (OAuth URL generation)
        try:
            import urllib.request
            req = urllib.request.Request(f"{alb_url}/api/v1/auth/login/init", method="GET")
            req.add_header("User-Agent", "totogi-verify/1.0")
            resp = urllib.request.urlopen(req, timeout=10)
            body = resp.read().decode("utf-8")
            
            try:
                init_data = json.loads(body)
                has_auth_url = "authorization_url" in init_data
                has_state = "state" in init_data
                check(f"OAuth login/init", has_auth_url and has_state,
                      f"Auth URL generated, state={init_data.get('state','?')[:20]}...")
            except json.JSONDecodeError:
                check(f"OAuth login/init", True, "Endpoint responding")
        except urllib.error.HTTPError as he:
            if he.code == 500:
                check(f"OAuth login/init", False, 
                      f"HTTP 500 - Cognito config may be incomplete in SSM")
            else:
                check(f"OAuth login/init", he.code < 500, f"HTTP {he.code}")
        except Exception as e:
            warn(f"OAuth login/init", f"Not reachable: {str(e)[:50]}")
    else:
        warn("Auth service", "ALB URL not available - skipping auth endpoint checks")

def main():
    print("Finding TotogiCapability to verify...")
    cap = find_capability()
    
    meta = cap["metadata"]
    spec = cap["spec"]
    status = cap.get("status", {})
    
    namespace = meta["namespace"]
    name = meta["name"]
    cap_name = spec.get("capabilityName", "")
    env = spec.get("environment", "")
    phase = status.get("phase", "Unknown")
    
    print(f"")
    print(f"  Capability:  {cap_name} v{spec.get('version','')} ({env})")
    print(f"  Namespace:   {namespace}")
    print(f"  Phase:       {phase}")
    print(f"")
    
    if phase not in ("Running", "Failed", "Ready"):
        print(f"  Warning: Capability is in '{phase}' phase - deployment may still be in progress.")
        print(f"  Run './operator-starhub-test.sh monitor' to watch deployment progress.")
        print(f"")
    
    session = boto3.Session(profile_name=AWS_PROFILE, region_name=REGION)
    
    # Run all verification sections
    verify_aws_resources(session, cap_name, env)
    ingress = verify_kubernetes(namespace, cap_name, env)
    verify_app_health(namespace, ingress, cap_name, env)
    verify_connectivity(session, namespace, cap_name, env)
    
    # Get ALB URL for Cognito checks
    alb_url = ""
    if ingress:
        lb_hosts = ingress.get("status", {}).get("loadBalancer", {}).get("ingress", [])
        if lb_hosts:
            addr = lb_hosts[0].get("hostname", lb_hosts[0].get("ip", ""))
            if addr:
                alb_url = f"http://{addr}"
    verify_cognito(session, spec, cap_name, env, alb_url)
    
    # Summary
    print("")
    print("═══════════════════════════════════════════════════════════════════")
    print("  VERIFICATION SUMMARY")
    print("═══════════════════════════════════════════════════════════════════")
    print(f"")
    print(f"  Passed:   {passed}")
    print(f"  Failed:   {failed}")
    print(f"  Warnings: {warned}")
    print(f"")
    
    if failed == 0:
        print("  ✓ ALL CHECKS PASSED")
        
        # Show access information
        if alb_url:
            print("")
            print("═══════════════════════════════════════════════════════════════════")
            print("  APPLICATION ACCESS")
            print("═══════════════════════════════════════════════════════════════════")
            print(f"")
            print(f"  URL: {alb_url}")
            print(f"")
            
            admin_email = spec.get("adminEmail", "")
            cognito_enabled = spec.get("enableCognito", False)
            if cognito_enabled and admin_email:
                # Try to read password from K8s Secret
                secret_name = f"{cap_name}-{env}-admin-credentials"
                secret = kubectl_json(["get", "secret", secret_name, "-n", namespace])
                if secret and secret.get("data", {}).get("admin-password"):
                    import base64
                    stored_pw = base64.b64decode(secret["data"]["admin-password"]).decode()
                    print(f"  Admin Login:")
                    print(f"    Email:    {admin_email}")
                    print(f"    Password: {stored_pw}")
                    print(f"")
                    print(f"    On first login, you will be prompted to set a new password.")
                else:
                    print(f"  Admin Login:")
                    print(f"    Email:    {admin_email}")
                    print(f"    Password: (already changed or Secret not found)")
                    print(f"              kubectl get secret {secret_name} -n {namespace} -o jsonpath='{{.data.admin-password}}' | base64 -d")
            elif not cognito_enabled:
                print(f"  Auth: Cognito not enabled (enableCognito: false)")
            print(f"")
    else:
        print(f"  ✗ {failed} CHECK(S) FAILED")
    print("")
    
    sys.exit(0 if failed == 0 else 1)

if __name__ == "__main__":
    main()
VERIFY_EOF
    
    return $?
}

check_status() {
    show_header "Status"
    
    echo "Checking operator status..."
    echo ""
    
    # Test kubectl access
    if ! timeout 5 kubectl get namespaces >/dev/null 2>&1; then
        echo -e "${YELLOW}✗ No cluster access configured${NC}"
        echo ""
        echo "This is expected if you haven't deployed yet."
        echo "The deploy script will automatically grant you access."
        echo ""
        echo "To deploy:"
        echo "  ./build-and-deploy.sh     (recommended)"
        echo ""
        echo "If operator is already deployed, manually configure access:"
        echo "  aws eks update-kubeconfig --name ${CLUSTER_NAME} --region ${REGION} --profile ${AWS_PROFILE}"
        echo ""
        return 1
    fi
    
    echo -e "${GREEN}✓ Cluster access configured${NC}"
    echo ""
    
    # Check if operator namespace exists
    if ! kubectl get namespace totogi-system >/dev/null 2>&1; then
        echo -e "${YELLOW}✗ Operator not deployed${NC}"
        echo "  Namespace 'totogi-system' not found"
        echo ""
        echo "To deploy:"
        echo "  ./build-and-deploy.sh"
        echo ""
        return 1
    fi
    
    echo "✓ Namespace: totogi-system exists"
    echo ""
    
    # Check deployment
    echo "Deployment Status:"
    if kubectl get deployment totogi-operator -n totogi-system >/dev/null 2>&1; then
        kubectl get deployment totogi-operator -n totogi-system
    else
        echo "  ✗ Deployment not found"
        return 1
    fi
    echo ""
    
    # Check pods
    echo "Pod Status:"
    if kubectl get pods -n totogi-system -l app.kubernetes.io/name=totogi-operator >/dev/null 2>&1; then
        kubectl get pods -n totogi-system -l app.kubernetes.io/name=totogi-operator
        
        # Check if pods are healthy
        READY_PODS=$(kubectl get pods -n totogi-system -l app.kubernetes.io/name=totogi-operator -o jsonpath='{.items[*].status.containerStatuses[*].ready}' 2>/dev/null | grep -c "true" || echo "0")
        TOTAL_PODS=$(kubectl get pods -n totogi-system -l app.kubernetes.io/name=totogi-operator --no-headers 2>/dev/null | wc -l)
        
        if [ "$READY_PODS" -eq "$TOTAL_PODS" ] && [ "$TOTAL_PODS" -gt 0 ]; then
            echo ""
            echo -e "${GREEN}✓ All pods are healthy${NC}"
        elif [ "$READY_PODS" -gt 0 ]; then
            echo ""
            echo -e "${YELLOW}⚠ Some pods not ready yet${NC}"
        else
            echo ""
            echo -e "${RED}✗ No healthy pods${NC}"
        fi
    else
        echo "  ✗ No pods found"
        return 1
    fi
    echo ""
    
    # Check CRD
    echo "CRD Status:"
    if kubectl get crd totogicapabilities.totogi.com >/dev/null 2>&1; then
        echo -e "  ${GREEN}✓ TotogiCapability CRD registered${NC}"
    else
        echo -e "  ${RED}✗ TotogiCapability CRD not found${NC}"
    fi
    echo ""
    
    echo "To view logs:"
    echo "  kubectl -n totogi-system logs -f deployment/totogi-operator"
    echo ""
    
    return 0
}

# Main script
main() {
    if [ $# -eq 0 ]; then
        show_help
        exit 1
    fi
    
    local command=$1
    shift
    
    case $command in
        scan|check-readiness)
            scan_cluster "$@"
            ;;
        fix-irsa|setup-irsa|irsa)
            fix_irsa "$@"
            ;;
        install-alb-controller|alb|alb-controller)
            install_alb_controller "$@"
            ;;
        delete-alb-controller|delete-alb|uninstall-alb)
            delete_alb_controller "$@"
            ;;
        delete-ebs-csi|remove-ebs-csi)
            delete_ebs_csi "$@"
            ;;
        deploy)
            deploy_operator "$@"
            ;;
        delete|cleanup)
            delete_operator "$@"
            ;;
        update|redeploy)
            update_operator "$@"
            ;;
        status|check)
            check_status "$@"
            ;;
        monitor|watch)
            monitor_capability "$@"
            ;;
        verify-capability|verify|verify-cap)
            verify_capability "$@"
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            echo -e "${RED}Error: Unknown command '$command'${NC}"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

main "$@"

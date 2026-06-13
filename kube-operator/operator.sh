#!/bin/bash
#
# Totogi Operator Management Script for starhub-test cluster
# 
# Usage:
#   ./operator.sh scan                    # Scan cluster readiness
#   ./operator.sh fix-irsa                # Fix IRSA (OIDC provider)
#   ./operator.sh install-alb-controller  # Install AWS Load Balancer Controller
#   ./operator.sh delete-alb-controller   # Delete AWS Load Balancer Controller
#   ./operator.sh delete-ebs-csi          # Delete EBS CSI Driver + IAM role
#   ./operator.sh deploy                  # Deploy operator (auto-fixes IRSA + ALB)
#   ./operator.sh delete                  # Delete operator (keeps access)
#   ./operator.sh delete --full           # Delete everything including IAM/ECR/ALB Controller
#   ./operator.sh update                  # Update operator (force redeploy)
#   ./operator.sh status                  # Check operator status
#   ./operator.sh monitor                 # Monitor capability deployment progress
#   ./operator.sh verify-capability       # Verify via operator IRSA Job (default)
#   ./operator.sh verify-capability --local  # Verify using local AWS profile + kubectl
#   ./operator.sh --help                  # Show help
#

set -e

# Windows compatibility: Python scripts use Unicode (✓/✗/box-drawing) that
# fail under cp1252. Force UTF-8 for all Python subprocesses.
export PYTHONIOENCODING=utf-8

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${SCRIPT_DIR}/../backend"

# Load defaults from .env.local (CLI args and env vars override these)
# Tolerates spaces around '=' (e.g. "ENV = prod" and "ENV=prod")
_ENVLOCAL="${SCRIPT_DIR}/.env.local"
if [ -f "$_ENVLOCAL" ]; then
    _ENV_LOCAL_ENV=$(grep '^ENV\s*=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- | tr -d ' ')
    _ENV_LOCAL_BRANCH=$(grep '^Branch\s*=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- | tr -d ' ')
    _ENV_LOCAL_CLUSTER=$(grep '^Cluster\s*=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- | tr -d ' ')
fi

CLUSTER_NAME="${CLUSTER_NAME:-${_ENV_LOCAL_CLUSTER:-starhub-test}}"
DEPLOY_ENV="${DEPLOY_ENV:-${_ENV_LOCAL_ENV:-prod}}"
GIT_BRANCH="${GIT_BRANCH:-${_ENV_LOCAL_BRANCH:-}}"
REGION="${REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-external-access}"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

show_help() {
    cat << EOF
Totogi Operator Management Script for starhub-test

Usage:
  ./operator.sh <command> [options]

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
  verify-capability [--local] [ns]  Verify deployment (default: Job as operator SA / IRSA; --local: this host)
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
  ./operator.sh scan

  # Fix IRSA (create OIDC provider if missing)
  ./operator.sh fix-irsa

  # Deploy operator (automatically fixes IRSA if needed)
  ./operator.sh deploy

  # Deploy without IRSA auto-fix
  ./operator.sh deploy --skip-irsa-fix

  # Update operator
  ./operator.sh update

  # Check status
  ./operator.sh status

  # Delete operator (safe - keeps IAM, ECR, and access)
  ./operator.sh delete

  # Complete cleanup (removes IAM, ECR, and aws-auth - restores original state)
  ./operator.sh delete --full

  # Delete with specific options
  ./operator.sh delete --keep-iam

  # Restore cluster to original state (removes aws-auth entry)
  ./operator.sh delete --remove-aws-auth

Workflow:
  1. ./operator.sh scan     # Check cluster readiness & IRSA
  2. ./operator.sh fix-irsa # Fix IRSA if needed (or let deploy do it)
  3. ./build-and-push.sh                 # Build operator image
  4. ./operator.sh deploy   # Deploy operator (auto-fixes IRSA + ALB Controller)
  5. ./operator.sh status   # Verify health

ALB Ingress Support:
  The deploy command automatically installs AWS Load Balancer Controller if not present.
  This enables ALB Ingress for TotogiCapability resources.
  
  To install ALB Controller separately:
    ./operator.sh install-alb-controller

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

# Wait for check-app / check-operator Job. Polls every 1s (max ~3 min).
# Returns 0 when the Job has finished (succeeded or failed pod count) OR when
# pod logs already show IRSA/trust failure — Job.status.failed can lag behind
# the container exit, so we sniff logs to surface AssumeRole errors immediately.
_wait_perm_check_job() {
    local ns=$1
    local job_name=$2
    local _i _suc _fail _logs
    for _i in $(seq 1 180); do
        _suc=$(kubectl get job "$job_name" -n "$ns" -o jsonpath='{.status.succeeded}' 2>/dev/null || echo "")
        _fail=$(kubectl get job "$job_name" -n "$ns" -o jsonpath='{.status.failed}' 2>/dev/null || echo "")
        _suc=${_suc:-0}
        _fail=${_fail:-0}
        if [ "$_suc" -ge 1 ] || [ "$_fail" -ge 1 ]; then
            return 0
        fi
        _logs=$(kubectl logs "job/$job_name" -n "$ns" 2>/dev/null || true)
        if echo "$_logs" | grep -qE 'AssumeRoleWithWebIdentity|Not authorized to perform sts:AssumeRoleWithWebIdentity|\[ERROR\] Cannot get identity'; then
            return 0
        fi
        sleep 1
    done
    return 1
}

check_dependencies() {
    echo "Checking dependencies..."
    
    # Check Python
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}Error: python3 not found${NC}"
        exit 1
    fi
    
    # Ensure pip installs to the same python3 that will run scripts
    if ! python3 -c "import kubernetes, boto3" 2>/dev/null; then
        echo "Installing required Python packages..."
        python3 -m pip install kubernetes boto3 pydantic pyyaml aiohttp --break-system-packages
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
    
    # IRSA is admin-managed (OIDC provider pre-created) -- skip IAM checks
    echo "Skipping IRSA check (admin-managed OIDC provider)..."
    echo ""
    
    echo "Starting deployment..."
    echo ""
    
    cd "${BACKEND_DIR}"
    python3 scripts/deploy_operator_to_cluster.py \
        --cluster "${CLUSTER_NAME}" \
        --region "${REGION}" \
        --profile "${AWS_PROFILE}" \
        --skip-iam \
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
        
        # ALB Controller is admin-managed -- just verify it's running via kubectl
        echo ""
        echo "Checking AWS Load Balancer Controller..."
        if kubectl get deployment aws-load-balancer-controller -n kube-system > /dev/null 2>&1; then
            READY=$(kubectl get deployment aws-load-balancer-controller -n kube-system -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
            echo -e "${GREEN}  ✓ ALB Controller is running (${READY} replica(s))${NC}"
        else
            echo -e "${YELLOW}  ! ALB Controller not found — admin must install it separately${NC}"
            echo "    ALB Ingress will not work until it's installed."
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
        echo "   kubectl create namespace nexus-ai-prod"
        echo "   kubectl apply -f examples/nexus-ai-complete.yaml"
        echo ""
        echo "2. Monitor deployment progress:"
        echo "   ./operator.sh monitor"
        echo ""
        echo "3. Verify all resources:"
        echo "   ./operator.sh verify-capability"
        echo ""
        echo "4. Get the application URL (after ALB is active):"
        echo "   kubectl get ingress -n nexus-ai-prod -o wide"
        echo ""
        echo "5. Login to the application:"
        echo "   Get the admin credentials:"
        echo "   kubectl get secret nexus-ai-prod-admin-credentials -n nexus-ai-prod -o jsonpath='{.data.admin-email}' | base64 -d && echo ''"
        echo "   kubectl get secret nexus-ai-prod-admin-credentials -n nexus-ai-prod -o jsonpath='{.data.admin-password}' | base64 -d && echo ''"
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

CLUSTER_NAME = os.getenv('CLUSTER_NAME', 'starhub-test')
REGION = os.getenv('REGION', 'us-east-1')
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
                    {'Key': 'created-by', 'Value': 'operator.sh'},
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

CLUSTER_NAME = os.getenv('CLUSTER_NAME', 'starhub-test')
REGION = os.getenv('REGION', 'us-east-1')
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
    
    role_arn = f"arn:aws:iam::{account_id}:role/{ALB_CONTROLLER_ROLE}"

    try:
        existing = iam_client.get_role(RoleName=ALB_CONTROLLER_ROLE)
        role_arn = existing["Role"]["Arn"]
        print(f"    [✓] IAM role exists: {ALB_CONTROLLER_ROLE}")

        # Merge trust policy: add current cluster's OIDC provider without removing others
        try:
            existing_trust = existing["Role"]["AssumeRolePolicyDocument"]
            existing_statements = existing_trust.get("Statement", [])
            current_oidc_arn = f"arn:aws:iam::{account_id}:oidc-provider/{oidc_provider_id}"
            already_present = any(
                stmt.get("Principal", {}).get("Federated") == current_oidc_arn
                for stmt in existing_statements
            )
            if already_present:
                print(f"    [✓] Trust policy already includes this cluster's OIDC provider")
            else:
                print(f"    Adding OIDC provider for cluster to existing trust policy...")
                merged_statements = existing_statements + [trust_policy["Statement"][0]]
                merged_trust = {"Version": "2012-10-17", "Statement": merged_statements}
                iam_client.update_assume_role_policy(
                    RoleName=ALB_CONTROLLER_ROLE,
                    PolicyDocument=json.dumps(merged_trust)
                )

            iam_client.put_role_policy(
                RoleName=ALB_CONTROLLER_ROLE,
                PolicyName="AWSLoadBalancerControllerIAMPolicy",
                PolicyDocument=json.dumps(alb_controller_policy)
            )
            print(f"    [✓] Updated IAM role policies: {ALB_CONTROLLER_ROLE}")
        except Exception as update_err:
            print(f"    [!] Could not update role policies (may need admin): {update_err}")

        return role_arn

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "NoSuchEntity":
            # Role does not exist -- try to create it
            try:
                print(f"    Creating IAM role: {ALB_CONTROLLER_ROLE}...")
                response = iam_client.create_role(
                    RoleName=ALB_CONTROLLER_ROLE,
                    AssumeRolePolicyDocument=json.dumps(trust_policy),
                    Description="IAM role for AWS Load Balancer Controller",
                    Tags=[
                        {"Key": "Capability", "Value": "nexus-ai"},
                        {"Key": "Environment", "Value": os.getenv("DEPLOY_ENV", "prod")},
                        {"Key": "managed-by", "Value": "totogi-operator"},
                        {"Key": "component", "Value": "aws-load-balancer-controller"}
                    ]
                )
                role_arn = response["Role"]["Arn"]
                iam_client.put_role_policy(
                    RoleName=ALB_CONTROLLER_ROLE,
                    PolicyName="AWSLoadBalancerControllerIAMPolicy",
                    PolicyDocument=json.dumps(alb_controller_policy)
                )
                print(f"    [✓] Created IAM role: {ALB_CONTROLLER_ROLE}")
                return role_arn
            except Exception as create_err:
                print(f"    [✗] Failed to create IAM role: {create_err}")
                return None
        else:
            # AccessDenied or connection error -- IAM unreachable, assume role was pre-created
            print(f"    [!] IAM API not accessible ({error_code}). Assuming role was pre-created by admin.")
            print(f"    [✓] Using pre-created role: {role_arn}")
            return role_arn

    except Exception as e:
        # Connection errors (no IAM endpoint) -- assume role was pre-created
        print(f"    [!] IAM API unreachable ({type(e).__name__}). Assuming role was pre-created by admin.")
        print(f"    [✓] Using pre-created role: {role_arn}")
        return role_arn

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
            # Verify the service account has an IRSA annotation
            sa_result = run_kubectl([
                "get", "sa", ALB_CONTROLLER_SA, "-n", ALB_CONTROLLER_NAMESPACE,
                "-o", "jsonpath={.metadata.annotations.eks\\.amazonaws\\.com/role-arn}"
            ], check=False)
            if sa_result:
                print(f"    [✓] Service account has IAM role annotation: {sa_result.split('/')[-1]}")
            else:
                print(f"    [!] Service account missing IAM role annotation")
            print(f"    [✓] ALB Controller is fully operational — skipping IAM and install steps")
            return 0
        else:
            print(f"    [—] AWS Load Balancer Controller not found")
        print(f"")
        
        # Get OIDC provider (needed for IAM role setup)
        print(f"[2/5] Getting cluster OIDC provider...")
        try:
            cluster_info = eks_client.describe_cluster(name=CLUSTER_NAME)['cluster']
            oidc_issuer = cluster_info.get('identity', {}).get('oidc', {}).get('issuer')
            if not oidc_issuer:
                print(f"    [✗] No OIDC issuer - IRSA not available")
                print(f"        ALB Controller requires IRSA. Run: ./operator.sh fix-irsa")
                return 1
            
            oidc_provider_id = oidc_issuer.replace('https://', '')
            print(f"    [✓] OIDC provider: {oidc_provider_id[:50]}...")
        except Exception as e:
            print(f"    [✗] Failed to get cluster info: {e}")
            return 1
        
        # Verify/create IAM role (only reached if controller is NOT running)
        print(f"[3/5] Verifying IAM role for ALB Controller...")
        role_arn = create_alb_controller_iam_role(session, account_id, oidc_provider_id)
        if not role_arn:
            return 1
        
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

CLUSTER_NAME = os.getenv('CLUSTER_NAME', 'starhub-test')
REGION = os.getenv('REGION', 'us-east-1')
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
    print("[4/4] Deleting IAM role...")
    
    try:
        session = boto3.Session(profile_name=AWS_PROFILE)
        iam_client = session.client('iam', region_name=REGION)
        
        # Check if role exists
        try:
            iam_client.get_role(RoleName=ALB_CONTROLLER_ROLE)
            
            # Detach managed policies
            try:
                paginator = iam_client.get_paginator('list_attached_role_policies')
                for page in paginator.paginate(RoleName=ALB_CONTROLLER_ROLE):
                    for policy in page['AttachedPolicies']:
                        print(f"    Detaching policy: {policy['PolicyName']}")
                        iam_client.detach_role_policy(
                            RoleName=ALB_CONTROLLER_ROLE,
                            PolicyArn=policy['PolicyArn']
                        )
            except ClientError as e:
                print(f"    Warning: Could not list/detach policies: {e}")
            
            # Delete inline policies
            try:
                inline_policies = iam_client.list_role_policies(RoleName=ALB_CONTROLLER_ROLE)
                for policy_name in inline_policies.get('PolicyNames', []):
                    print(f"    Deleting inline policy: {policy_name}")
                    iam_client.delete_role_policy(
                        RoleName=ALB_CONTROLLER_ROLE,
                        PolicyName=policy_name
                    )
            except ClientError as e:
                print(f"    Warning: Could not list/delete inline policies: {e}")
            
            # Delete the role
            iam_client.delete_role(RoleName=ALB_CONTROLLER_ROLE)
            print(f"    [✓] IAM role deleted: {ALB_CONTROLLER_ROLE}")
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchEntity':
                print(f"    IAM role not found (already deleted): {ALB_CONTROLLER_ROLE}")
            else:
                print(f"    Error checking IAM role: {e}")
                errors.append(str(e))
                
    except Exception as e:
        print(f"    Error with AWS session: {e}")
        errors.append(str(e))
    
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
        echo "  ./operator.sh install-alb-controller"
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
        echo "To reinstall the EBS CSI Driver:"
        echo "  ./setup-iam-policies.sh    # creates IAM role + EKS add-on"
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
        echo "  2. Deploy operator:      ./operator.sh deploy"
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
    local remove_aws_auth=""               # Never remove aws-auth (preserve access)
    local keep_access_entry="--keep-access-entry"  # Always keep access entry
    local delete_alb_controller=""         # Never delete ALB controller (admin-managed)
    local delete_ebs_csi=""                # Never delete EBS CSI (admin-managed)
    
    # Parse options
    while [[ $# -gt 0 ]]; do
        case $1 in
            --full)
                keep_iam="--keep-iam"                  # Always keep (admin-managed)
                keep_ecr=""                             # OK to clean ECR
                remove_aws_auth=""                      # NEVER remove aws-auth
                keep_access_entry="--keep-access-entry" # NEVER remove access entry
                delete_alb_controller=""                # NEVER delete ALB controller
                delete_ebs_csi=""                       # NEVER delete EBS CSI
                shift
                ;;
            --delete-alb|--delete-alb-controller)
                echo -e "${YELLOW}Warning: --delete-alb is disabled (ALB controller is admin-managed)${NC}"
                shift
                ;;
            --delete-ebs-csi|--remove-ebs-csi)
                echo -e "${YELLOW}Warning: --delete-ebs-csi is disabled (EBS CSI is admin-managed)${NC}"
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
                echo -e "${YELLOW}Warning: --no-keep-iam is disabled (IAM roles are admin-managed)${NC}"
                shift
                ;;
            --no-keep-ecr)
                keep_ecr=""
                shift
                ;;
            --remove-aws-auth)
                echo -e "${YELLOW}Warning: --remove-aws-auth is disabled (preserving cluster access)${NC}"
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
        echo "  ./operator.sh deploy"
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

CLUSTER_NAME = os.getenv('CLUSTER_NAME', 'starhub-test')
REGION = os.getenv('REGION', 'us-east-1')
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
                    print(f"        To install: ./operator.sh install-alb-controller")
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
            print("     ./operator.sh deploy")
            print()
            print("  2. Or build fresh and deploy:")
            print("     ./build-and-deploy.sh")
            print()
            
            if not alb_controller_ready:
                print("  Optional - Install ALB Controller for Ingress support:")
                print("     ./operator.sh install-alb-controller")
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
                print("       Just run: ./operator.sh deploy")
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
        print("  kubectl apply -f examples/nexus-ai-complete.yaml")
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
        print("Tip: Run './operator.sh verify-capability' to verify resources")

if __name__ == "__main__":
    main()
MONITOR_EOF
    
    return $?
}

# ================================================================
# Verify capability deployment: AWS resources, K8s, app health
# Default: runs verify-capability.py in a Job using the operator image + SA (IRSA).
# Use --local to run boto3/kubectl on this machine with AWS_PROFILE instead.
# ================================================================
verify_capability() {
    show_header "Verify Capability"
    
    local target_ns=""
    local run_local=""
    while [[ $# -gt 0 ]]; do
        case $1 in
            --local) run_local=1; shift ;;
            *) target_ns="$1"; shift; break ;;
        esac
    done
    
    # Switch kubeconfig to target cluster (admin/user identity to create Job + read logs)
    AWS_PROFILE="${AWS_PROFILE}" aws eks update-kubeconfig \
        --name "${CLUSTER_NAME}" \
        --region "${REGION}" \
        --profile "${AWS_PROFILE}" 2>/dev/null || true
    
    export CLUSTER_NAME="${CLUSTER_NAME}"
    export REGION="${REGION}"
    export AWS_PROFILE="${AWS_PROFILE}"
    export TARGET_NS="${target_ns}"
    
    if [ -n "$run_local" ]; then
        echo "  Mode: local (boto3 profile ${AWS_PROFILE}, kubectl from this host)"
        echo ""
        if ! python3 "${SCRIPT_DIR}/verify-capability.py"; then
            return 1
        fi
        return 0
    fi
    
    local OP_NS="totogi-system"
    local JOB_NAME="verify-capability-run"
    local CM_NAME="verify-capability-script"
    local VERIFY_PY="${SCRIPT_DIR}/verify-capability.py"
    
    if [ ! -f "$VERIFY_PY" ]; then
        echo -e "${RED}  Missing ${VERIFY_PY}${NC}"
        return 1
    fi
    
    if ! kubectl get deployment totogi-operator -n "${OP_NS}" >/dev/null 2>&1; then
        echo -e "${RED}  Operator deployment not found in ${OP_NS}. Deploy operator first.${NC}"
        return 1
    fi
    
    local OP_SA
    OP_SA=$(kubectl get deployment totogi-operator -n "${OP_NS}" -o jsonpath='{.spec.template.spec.serviceAccountName}' 2>/dev/null || echo "totogi-operator")
    local OP_IMAGE
    OP_IMAGE=$(kubectl get deployment totogi-operator -n "${OP_NS}" -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null)
    if [ -z "$OP_IMAGE" ]; then
        echo -e "${RED}  Could not read operator container image.${NC}"
        return 1
    fi
    
    echo "  Mode: in-cluster Job (operator SA ${OP_SA} → IRSA for AWS API)"
    echo "  Image: ${OP_IMAGE}"
    [ -n "$target_ns" ] && echo "  Target namespace filter: ${target_ns}"
    echo ""
    
    kubectl delete job "${JOB_NAME}" -n "${OP_NS}" --ignore-not-found >/dev/null 2>&1
    kubectl delete configmap "${CM_NAME}" -n "${OP_NS}" --ignore-not-found >/dev/null 2>&1
    
    echo "  Uploading verify script ConfigMap..."
    kubectl create configmap "${CM_NAME}" \
        --from-file=verify-capability.py="${VERIFY_PY}" \
        -n "${OP_NS}" >/dev/null
    echo ""
    
    echo "  Starting verify Job..."
    kubectl apply -f - <<VERIFYJOB_EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${JOB_NAME}
  namespace: ${OP_NS}
spec:
  ttlSecondsAfterFinished: 600
  backoffLimit: 0
  template:
    spec:
      serviceAccountName: ${OP_SA}
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
      containers:
        - name: verify
          image: ${OP_IMAGE}
          imagePullPolicy: IfNotPresent
          command: ["python3", "-u", "/scripts/verify-capability.py"]
          env:
            - name: VERIFY_USE_IRSA
              value: "1"
            - name: REGION
              value: "${REGION}"
            - name: TARGET_NS
              value: "${target_ns}"
            - name: AWS_REGION
              value: "${REGION}"
            - name: AWS_DEFAULT_REGION
              value: "${REGION}"
            - name: EKS_CLUSTER_NAME
              value: "${CLUSTER_NAME}"
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop:
                - ALL
          volumeMounts:
            - name: script
              mountPath: /scripts
              readOnly: true
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: script
          configMap:
            name: ${CM_NAME}
            defaultMode: 0555
        - name: tmp
          emptyDir: {}
      restartPolicy: Never
VERIFYJOB_EOF
    echo ""
    
    echo "  Live progress: logs stream below until the verify pod exits (max ~10 min)."
    echo "  Second terminal (same follow): kubectl logs -f job/${JOB_NAME} -n ${OP_NS}"
    echo "  Pod status:            kubectl get pods -n ${OP_NS} -l job-name=${JOB_NAME} -w"
    echo ""
    echo "  Waiting for verify pod to be created / scheduled..."
    local _wpod
    for _wpod in $(seq 1 90); do
        if kubectl get pods -n "${OP_NS}" -l "job-name=${JOB_NAME}" --no-headers 2>/dev/null | grep -q .; then
            break
        fi
        sleep 1
    done
    echo "  Streaming verify Job logs:"
    echo "═══════════════════════════════════════════════════════════════════"
    
    local JOB_DONE=true
    local STREAM_EC=0
    set +e
    timeout 600 kubectl logs -f "job/${JOB_NAME}" -n "${OP_NS}" 2>&1
    STREAM_EC=$?
    set -e
    echo "═══════════════════════════════════════════════════════════════════"
    echo ""
    if [ "$STREAM_EC" -eq 124 ]; then
        JOB_DONE=false
        echo -e "${YELLOW}  Log stream stopped: 600s timeout (Job may still be running).${NC}"
        echo ""
    fi
    
    local LOG_OUT
    LOG_OUT=$(kubectl logs "job/${JOB_NAME}" -n "${OP_NS}" 2>/dev/null || true)
    if [ "$JOB_DONE" != true ] && [ -z "$LOG_OUT" ]; then
        echo -e "${YELLOW}  No logs captured yet. Try: kubectl describe job ${JOB_NAME} -n ${OP_NS}${NC}"
        echo ""
    fi
    
    local FAILED
    FAILED=$(kubectl get job "${JOB_NAME}" -n "${OP_NS}" -o jsonpath='{.status.failed}' 2>/dev/null || echo "")
    FAILED=${FAILED:-0}
    local SUCCEEDED
    SUCCEEDED=$(kubectl get job "${JOB_NAME}" -n "${OP_NS}" -o jsonpath='{.status.succeeded}' 2>/dev/null || echo "")
    SUCCEEDED=${SUCCEEDED:-0}

    # Early log-sniff can return before apiserver sets Job.status.{succeeded,failed}; sync briefly.
    if [ "${SUCCEEDED:-0}" -lt 1 ] && [ "${FAILED:-0}" -lt 1 ] && echo "$LOG_OUT" | grep -Fq "VERIFICATION SUMMARY"; then
        local _j
        for _j in $(seq 1 25); do
            sleep 1
            SUCCEEDED=$(kubectl get job "${JOB_NAME}" -n "${OP_NS}" -o jsonpath='{.status.succeeded}' 2>/dev/null || echo "")
            FAILED=$(kubectl get job "${JOB_NAME}" -n "${OP_NS}" -o jsonpath='{.status.failed}' 2>/dev/null || echo "")
            SUCCEEDED=${SUCCEEDED:-0}
            FAILED=${FAILED:-0}
            if [ "${SUCCEEDED}" -ge 1 ] || [ "${FAILED}" -ge 1 ]; then
                break
            fi
        done
    fi

    local VERIFY_FAIL_IN_LOG=false
    if echo "$LOG_OUT" | grep -Fq "CHECK(S) FAILED"; then
        VERIFY_FAIL_IN_LOG=true
    fi
    if echo "$LOG_OUT" | grep -q '^Traceback \(most recent call last\)'; then
        VERIFY_FAIL_IN_LOG=true
    fi
    local VERIFY_OK_IN_LOG=false
    if echo "$LOG_OUT" | grep -Fq "VERIFICATION SUMMARY" && echo "$LOG_OUT" | grep -Fq "ALL CHECKS PASSED"; then
        VERIFY_OK_IN_LOG=true
    fi
    
    echo ""
    echo "  Cleaning up Job + ConfigMap..."
    kubectl delete job "${JOB_NAME}" -n "${OP_NS}" --ignore-not-found >/dev/null 2>&1
    kubectl delete configmap "${CM_NAME}" -n "${OP_NS}" --ignore-not-found >/dev/null 2>&1
    echo -e "${GREEN}  ✓ Cleanup done${NC}"
    echo ""
    
    if [ "$JOB_DONE" != true ]; then
        echo -e "${RED}  Verify timed out (Job still running or not finished within ~10 min).${NC}"
        return 1
    fi
    if [ "${FAILED:-0}" -ge 1 ] || [ "$VERIFY_FAIL_IN_LOG" = true ]; then
        echo -e "${RED}  Verification failed (see log above).${NC}"
        return 1
    fi
    if [ "${SUCCEEDED:-0}" -ge 1 ] || [ "$VERIFY_OK_IN_LOG" = true ]; then
        return 0
    fi
    echo -e "${RED}  Job finished but success could not be confirmed (no summary in logs — see above).${NC}"
    return 1
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
        setup-endpoints|endpoints)
            show_header "Setup VPC Endpoints"

            echo "Applying TotogiNetworkConfig CRD..."
            kubectl apply -f "${SCRIPT_DIR}/manifests/network-config-crd.yaml" 2>/dev/null
            echo ""

            # Ensure operator ServiceAccount has RBAC for the new CRD
            echo "Ensuring operator RBAC for TotogiNetworkConfig..."
            SA_NAME=$(kubectl get deployment totogi-operator -n totogi-system -o jsonpath='{.spec.template.spec.serviceAccountName}' 2>/dev/null || echo "totogi-operator-sa")
            kubectl apply -f - <<RBAC_EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: totogi-operator-network-config
rules:
  - apiGroups: ["totogi.com"]
    resources: ["totoginetworkconfigs", "totoginetworkconfigs/status"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: totogi-operator-network-config
subjects:
  - kind: ServiceAccount
    name: ${SA_NAME}
    namespace: totogi-system
roleRef:
  kind: ClusterRole
  name: totogi-operator-network-config
  apiGroup: rbac.authorization.k8s.io
RBAC_EOF
            echo -e "${GREEN}  ✓ RBAC configured for ${SA_NAME}${NC}"
            echo ""

            echo "Applying VPC endpoint configuration for cluster ${CLUSTER_NAME}..."
            sed "s|__CLUSTER_NAME__|${CLUSTER_NAME}|g; s|__REGION__|${REGION}|g" \
                "${SCRIPT_DIR}/examples/network-config.yaml" | kubectl apply -f -
            echo ""

            # Restart operator to pick up the new CRD if it was watching before RBAC was ready
            echo "Restarting operator to pick up new CRD..."
            kubectl rollout restart deployment totogi-operator -n totogi-system 2>/dev/null || true
            sleep 10
            echo ""

            echo "Waiting for operator to provision endpoints..."
            echo ""
            for i in $(seq 1 30); do
                PHASE=$(kubectl get tnc vpc-endpoints -o jsonpath='{.status.phase}' 2>/dev/null || echo "Pending")
                HEALTHY=$(kubectl get tnc vpc-endpoints -o jsonpath='{.status.healthyEndpoints}' 2>/dev/null || echo "0")
                TOTAL=$(kubectl get tnc vpc-endpoints -o jsonpath='{.status.totalEndpoints}' 2>/dev/null || echo "0")
                if [ "$PHASE" = "Ready" ]; then
                    echo -e "${GREEN}  ✓ VPC Endpoints ready! (${HEALTHY}/${TOTAL} healthy)${NC}"
                    echo ""
                    kubectl get tnc vpc-endpoints 2>/dev/null
                    echo ""
                    echo "  Endpoint details:"
                    kubectl get tnc vpc-endpoints -o jsonpath='{range .status.endpoints[*]}  [{.type}] {.service}: {.state} ({.endpointId}){"\n"}{end}' 2>/dev/null
                    echo ""
                    exit 0
                elif [ "$PHASE" = "Error" ]; then
                    MSG=$(kubectl get tnc vpc-endpoints -o jsonpath='{.status.message}' 2>/dev/null || echo "")
                    echo -e "${YELLOW}  ! Phase: Error — ${MSG}${NC}"
                    echo ""
                    kubectl get tnc vpc-endpoints -o jsonpath='{range .status.endpoints[*]}  [{.type}] {.service}: {.state}{"\n"}{end}' 2>/dev/null
                    echo ""
                    exit 1
                fi
                echo "  Phase: ${PHASE} (${HEALTHY}/${TOTAL})... (${i}/30)"
                sleep 10
            done
            echo -e "${YELLOW}Timeout waiting for endpoints. Check: kubectl logs -n totogi-system deployment/totogi-operator${NC}"
            ;;
        check-endpoints|endpoints-status)
            echo ""
            echo "═══════════════════════════════════════════════════════════════════"
            echo "  VPC Endpoint Status"
            echo "═══════════════════════════════════════════════════════════════════"
            echo ""
            if kubectl get tnc vpc-endpoints > /dev/null 2>&1; then
                kubectl get tnc vpc-endpoints 2>/dev/null
                echo ""
                echo "  Endpoint details:"
                echo ""
                kubectl get tnc vpc-endpoints -o jsonpath='{range .status.endpoints[*]}  [{.type}] {.service}: {.state} ({.endpointId}){"\n"}{end}' 2>/dev/null
                echo ""
                MSG=$(kubectl get tnc vpc-endpoints -o jsonpath='{.status.message}' 2>/dev/null || echo "")
                CHECKED=$(kubectl get tnc vpc-endpoints -o jsonpath='{.status.lastChecked}' 2>/dev/null || echo "")
                if [ -n "$MSG" ]; then echo "  Message: ${MSG}"; fi
                if [ -n "$CHECKED" ]; then echo "  Last checked: ${CHECKED}"; fi
            else
                echo "  No TotogiNetworkConfig found."
                echo ""
                echo "  To set up VPC endpoints, run:"
                echo "    ./operator.sh setup-endpoints"
            fi
            echo ""
            ;;
        delete-endpoints|remove-endpoints)
            show_header "Delete VPC Endpoints Configuration"

            if ! kubectl get tnc vpc-endpoints > /dev/null 2>&1; then
                echo "  No TotogiNetworkConfig 'vpc-endpoints' found — nothing to delete."
                echo ""
                exit 0
            fi

            echo "  This will delete the TotogiNetworkConfig CR."
            echo "  The actual VPC endpoints in AWS will NOT be deleted (they remain for other workloads)."
            echo ""
            read -rp "  Proceed? [y/N] " confirm
            if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
                echo "  Aborted."
                exit 0
            fi
            echo ""

            echo "  Deleting TotogiNetworkConfig 'vpc-endpoints'..."
            kubectl delete tnc vpc-endpoints --timeout=30s 2>/dev/null || \
                kubectl patch tnc vpc-endpoints --type merge -p '{"metadata":{"finalizers":[]}}' 2>/dev/null
            echo -e "${GREEN}  ✓ TotogiNetworkConfig deleted${NC}"
            echo ""

            echo "  Cleaning up RBAC..."
            kubectl delete clusterrolebinding totogi-operator-network-config 2>/dev/null || true
            kubectl delete clusterrole totogi-operator-network-config 2>/dev/null || true
            echo -e "${GREEN}  ✓ RBAC cleaned up${NC}"
            echo ""

            echo "  Cleaning up CRD..."
            kubectl delete crd totoginetworkconfigs.totogi.com 2>/dev/null || true
            echo -e "${GREEN}  ✓ CRD removed${NC}"
            echo ""

            echo "  Note: VPC endpoints still exist in AWS. To remove them:"
            echo "    aws ec2 delete-vpc-endpoints --vpc-endpoint-ids <vpce-id1> <vpce-id2> ..."
            echo ""
            ;;
        check-app-permissions|check-app)
            show_header "Check App Permissions & VPC Endpoints"

            CAP="nexus-ai"
            local APP_NS="${CAP}-${DEPLOY_ENV}"
            local APP_SA="${CAP}-${DEPLOY_ENV}-app-sa"
            local APP_ROLE="${CAP}-${DEPLOY_ENV}-app-role"
            local JOB_NAME="check-app-permissions"
            local CM_NAME="app-perm-check"
            local CREATED_NS=false
            local CREATED_SA=false

            # Resolve ECR registry and account
            local APP_ACCOUNT
            APP_ACCOUNT=$(aws sts get-caller-identity --profile "${AWS_PROFILE}" --query Account --output text 2>/dev/null)
            local APP_ECR="${APP_ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
            local ROLE_ARN="arn:aws:iam::${APP_ACCOUNT}:role/${APP_ROLE}"

            echo "  Namespace:      ${APP_NS}"
            echo "  ServiceAccount: ${APP_SA}"
            echo "  IAM Role:       ${APP_ROLE}"
            echo "  Image:          ${APP_ECR}/ai-job-engine:latest"
            echo ""

            # Create namespace if it doesn't exist
            if ! kubectl get ns "${APP_NS}" > /dev/null 2>&1; then
                echo "  Creating namespace ${APP_NS}..."
                kubectl create namespace "${APP_NS}" > /dev/null 2>&1
                CREATED_NS=true
                echo -e "${GREEN}  ✓ Namespace created (will be cleaned up after check)${NC}"
            else
                echo "  ✓ Namespace ${APP_NS} exists"
            fi

            # Create ServiceAccount with IRSA if it doesn't exist
            if ! kubectl get sa "${APP_SA}" -n "${APP_NS}" > /dev/null 2>&1; then
                echo "  Creating ServiceAccount ${APP_SA} with IRSA annotation..."
                kubectl apply -f - <<SA_EOF > /dev/null 2>&1
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ${APP_SA}
  namespace: ${APP_NS}
  annotations:
    eks.amazonaws.com/role-arn: ${ROLE_ARN}
  labels:
    app.kubernetes.io/managed-by: permission-checker
SA_EOF
                CREATED_SA=true
                echo -e "${GREEN}  ✓ ServiceAccount created with role ${APP_ROLE} (will be cleaned up after check)${NC}"
            else
                echo "  ✓ ServiceAccount ${APP_SA} exists"
                # Show current IRSA role
                local EXISTING_ROLE
                EXISTING_ROLE=$(kubectl get sa "${APP_SA}" -n "${APP_NS}" -o jsonpath='{.metadata.annotations.eks\.amazonaws\.com/role-arn}' 2>/dev/null || echo "none")
                echo "    IRSA role: ${EXISTING_ROLE}"
            fi
            echo ""

            # Clean up any previous run
            kubectl delete job "${JOB_NAME}" -n "${APP_NS}" --ignore-not-found > /dev/null 2>&1
            kubectl delete configmap "${CM_NAME}" -n "${APP_NS}" --ignore-not-found > /dev/null 2>&1

            # Create ConfigMap with the check script
            echo "  Creating check script ConfigMap..."
            kubectl create configmap "${CM_NAME}" \
                --from-file=check.py="${SCRIPT_DIR}/check-app-permissions.py" \
                -n "${APP_NS}" > /dev/null 2>&1
            echo ""

            # Launch Job
            echo "  Launching permission check Job (using ${APP_SA} → ${APP_ROLE})..."
            kubectl apply -f - <<APPJOB_EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${JOB_NAME}
  namespace: ${APP_NS}
spec:
  ttlSecondsAfterFinished: 300
  backoffLimit: 0
  template:
    spec:
      serviceAccountName: ${APP_SA}
      containers:
        - name: checker
          image: ${APP_ECR}/ai-job-engine:latest
          command: ["python3", "/scripts/check.py"]
          env:
            - name: CAPABILITY
              value: "${CAP}"
            - name: ENV
              value: "${DEPLOY_ENV}"
            - name: REGION
              value: "${REGION}"
            - name: PERM_CHECK_SSL_VERIFY
              value: "${PERM_CHECK_SSL_VERIFY:-1}"
          volumeMounts:
            - name: script
              mountPath: /scripts
      volumes:
        - name: script
          configMap:
            name: ${CM_NAME}
      restartPolicy: Never
APPJOB_EOF
            echo ""

            echo "  Waiting for check to finish (1s poll, IRSA errors detected from logs immediately, max ~3 min)..."
            echo ""
            local JOB_DONE=false
            if _wait_perm_check_job "${APP_NS}" "${JOB_NAME}"; then
                JOB_DONE=true
            fi

            echo ""
            local LOG_OUT
            LOG_OUT=$(kubectl logs "job/${JOB_NAME}" -n "${APP_NS}" 2>/dev/null || true)
            if [ "$JOB_DONE" = true ]; then
                echo "$LOG_OUT"
            else
                echo -e "${YELLOW}  Job still running after timeout. Fetching available logs:${NC}"
                echo ""
                echo "$LOG_OUT"
                [ -n "$LOG_OUT" ] || echo "  (no logs available)"
            fi

            local FAILED IRSA_FAIL
            FAILED=$(kubectl get job "${JOB_NAME}" -n "${APP_NS}" -o jsonpath='{.status.failed}' 2>/dev/null || echo "")
            FAILED=${FAILED:-0}
            IRSA_FAIL=false
            if echo "$LOG_OUT" | grep -qE 'AssumeRoleWithWebIdentity|Not authorized to perform sts:AssumeRoleWithWebIdentity|\[ERROR\] Cannot get identity'; then
                IRSA_FAIL=true
            fi

            # Cleanup
            echo ""
            echo "  Cleaning up..."
            kubectl delete job "${JOB_NAME}" -n "${APP_NS}" --ignore-not-found > /dev/null 2>&1
            kubectl delete configmap "${CM_NAME}" -n "${APP_NS}" --ignore-not-found > /dev/null 2>&1

            if [ "$CREATED_SA" = true ]; then
                kubectl delete sa "${APP_SA}" -n "${APP_NS}" --ignore-not-found > /dev/null 2>&1
                echo "  ✓ Temporary ServiceAccount deleted"
            fi
            if [ "$CREATED_NS" = true ]; then
                kubectl delete ns "${APP_NS}" --timeout=30s > /dev/null 2>&1 || true
                echo "  ✓ Temporary namespace deleted"
            fi

            echo -e "${GREEN}  ✓ Cleanup done${NC}"
            echo ""
            if [ "$JOB_DONE" != true ] || [ "$FAILED" -ge 1 ] || [ "$IRSA_FAIL" = true ]; then
                echo -e "${RED}  App permission check failed (IRSA/trust, IAM denials, or timeout). Fix trust/policy and re-run.${NC}"
                exit 1
            fi
            ;;
        check-operator-permissions|check-operator)
            show_header "Check Operator Permissions & VPC Endpoints"

            local OP_NS="totogi-system"
            local JOB_NAME="check-operator-permissions"
            local CM_NAME="operator-perm-check"

            # Resolve ECR registry
            local OP_ACCOUNT
            OP_ACCOUNT=$(aws sts get-caller-identity --profile "${AWS_PROFILE}" --query Account --output text 2>/dev/null)
            local OP_ECR="${OP_ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

            # Get operator SA name from deployment
            local OP_SA
            OP_SA=$(kubectl get deployment totogi-operator -n "${OP_NS}" -o jsonpath='{.spec.template.spec.serviceAccountName}' 2>/dev/null || echo "totogi-operator-sa")
            local OP_ROLE
            OP_ROLE=$(kubectl get sa "${OP_SA}" -n "${OP_NS}" -o jsonpath='{.metadata.annotations.eks\.amazonaws\.com/role-arn}' 2>/dev/null || echo "unknown")

            echo "  Namespace:      ${OP_NS}"
            echo "  ServiceAccount: ${OP_SA}"
            echo "  IAM Role:       ${OP_ROLE##*/}"
            echo "  Image:          ${OP_ECR}/ai-job-engine:latest"
            echo ""

            if ! kubectl get sa "${OP_SA}" -n "${OP_NS}" > /dev/null 2>&1; then
                echo -e "${RED}  Operator ServiceAccount ${OP_SA} not found. Deploy operator first.${NC}"
                exit 1
            fi

            # Clean up any previous run
            kubectl delete job "${JOB_NAME}" -n "${OP_NS}" --ignore-not-found > /dev/null 2>&1
            kubectl delete configmap "${CM_NAME}" -n "${OP_NS}" --ignore-not-found > /dev/null 2>&1

            # Create ConfigMap with the check script
            echo "  Creating check script ConfigMap..."
            kubectl create configmap "${CM_NAME}" \
                --from-file=check.py="${SCRIPT_DIR}/check-operator-permissions.py" \
                -n "${OP_NS}" > /dev/null 2>&1
            echo ""

            # Launch Job using the operator's ServiceAccount
            echo "  Launching permission check Job (using ${OP_SA})..."
            kubectl apply -f - <<OPJOB_EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${JOB_NAME}
  namespace: ${OP_NS}
spec:
  ttlSecondsAfterFinished: 300
  backoffLimit: 0
  template:
    spec:
      serviceAccountName: ${OP_SA}
      containers:
        - name: checker
          image: ${OP_ECR}/ai-job-engine:latest
          command: ["python3", "/scripts/check.py"]
          env:
            - name: PERM_CHECK_SSL_VERIFY
              value: "${PERM_CHECK_SSL_VERIFY:-1}"
          volumeMounts:
            - name: script
              mountPath: /scripts
      volumes:
        - name: script
          configMap:
            name: ${CM_NAME}
      restartPolicy: Never
OPJOB_EOF
            echo ""

            echo "  Waiting for check to finish (1s poll, IRSA errors from logs immediately, max ~3 min)..."
            echo ""
            local JOB_DONE=false
            if _wait_perm_check_job "${OP_NS}" "${JOB_NAME}"; then
                JOB_DONE=true
            fi

            echo ""
            local LOG_OUT
            LOG_OUT=$(kubectl logs "job/${JOB_NAME}" -n "${OP_NS}" 2>/dev/null || true)
            if [ "$JOB_DONE" = true ]; then
                echo "$LOG_OUT"
            else
                echo -e "${YELLOW}  Job still running after timeout. Fetching available logs:${NC}"
                echo ""
                echo "$LOG_OUT"
                [ -n "$LOG_OUT" ] || echo "  (no logs available)"
            fi

            local FAILED IRSA_FAIL
            FAILED=$(kubectl get job "${JOB_NAME}" -n "${OP_NS}" -o jsonpath='{.status.failed}' 2>/dev/null || echo "")
            FAILED=${FAILED:-0}
            IRSA_FAIL=false
            if echo "$LOG_OUT" | grep -qE 'AssumeRoleWithWebIdentity|Not authorized to perform sts:AssumeRoleWithWebIdentity|\[ERROR\] Cannot get identity'; then
                IRSA_FAIL=true
            fi

            # Cleanup
            echo ""
            echo "  Cleaning up..."
            kubectl delete job "${JOB_NAME}" -n "${OP_NS}" --ignore-not-found > /dev/null 2>&1
            kubectl delete configmap "${CM_NAME}" -n "${OP_NS}" --ignore-not-found > /dev/null 2>&1
            echo -e "${GREEN}  ✓ Cleanup done${NC}"
            echo ""
            if [ "$JOB_DONE" != true ] || [ "$FAILED" -ge 1 ] || [ "$IRSA_FAIL" = true ]; then
                echo -e "${RED}  Operator permission check failed (IRSA/trust, IAM denials, or timeout). Fix trust/policy and re-run.${NC}"
                exit 1
            fi
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

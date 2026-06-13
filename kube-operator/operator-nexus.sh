#!/bin/bash
#
# Nexus Operator Management Script
# Reads defaults from .env.local (ENV, Branch, Cluster). Env vars override.
# 
# Usage:
#   ./operator-nexus.sh scan                    # Scan cluster readiness
#   ./operator-nexus.sh fix-irsa                # Fix IRSA (OIDC provider)
#   ./operator-nexus.sh install-alb-controller  # Install AWS Load Balancer Controller
#   ./operator-nexus.sh delete-alb-controller   # Delete AWS Load Balancer Controller
#   ./operator-nexus.sh delete-ebs-csi          # Delete EBS CSI Driver + IAM role
#   ./operator-nexus.sh deploy                  # Deploy operator (auto-fixes IRSA + ALB)
#   ./operator-nexus.sh delete                  # Delete operator (keeps access)
#   ./operator-nexus.sh delete --full           # Delete everything including IAM/ECR/ALB Controller
#   ./operator-nexus.sh update                  # Update operator (force redeploy)
#   ./operator-nexus.sh status                  # Check operator status
#   ./operator-nexus.sh monitor                 # Monitor capability deployment progress
#   ./operator-nexus.sh verify-capability       # Verify via operator IRSA Job (default)
#   ./operator-nexus.sh verify-capability --local  # Verify using local AWS profile + kubectl
#   ./operator-nexus.sh --help                  # Show help
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

CLUSTER_NAME="${CLUSTER_NAME:-${_ENV_LOCAL_CLUSTER:-nexus-dev}}"
DEPLOY_ENV="${DEPLOY_ENV:-${_ENV_LOCAL_ENV:-dev}}"
CAPABILITY="${CAPABILITY:-nexus-ai}"
GIT_BRANCH="${GIT_BRANCH:-${_ENV_LOCAL_BRANCH:-}}"
REGION="${REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-ptr-tech}"
BACKEND_DIR="${SCRIPT_DIR}/../backend"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

show_help() {
    cat << EOF
Nexus Operator Lifecycle Script

Usage:
  ./operator-nexus.sh <command> [options]

Commands:
  deploy                  Deploy operator to the cluster
  delete                  Delete operator from the cluster
  delete --full           Complete cleanup (removes ECR, aws-auth)
  update                  Update/redeploy operator (force update)
  status                  Check operator status
  monitor [ns/name]       Monitor capability deployment progress
  verify-capability [ns]  Verify capability resources
  check-operator          Run operator IRSA permission check
  setup-endpoints         Apply VPC endpoint CRD
  help                    Show this help

Options:
  --profile PROFILE       AWS profile (default: ptr-tech)
  --keep-ecr              Keep ECR repository when deleting
  --remove-aws-auth       Remove aws-auth entry
  --force                 Force deployment even if already installed
  --skip-irsa-fix         Skip IRSA check during deploy

Prerequisites (managed by separate scripts):
  Cluster setup:    deploy/eks/create-hardened-eks-cluster.sh
  Cluster checks:   ./cluster-access.sh check
  Cluster fix:      ./cluster-access.sh fix
  Cluster delete:   deploy/eks/delete-eks-cluster.sh

Workflow:
  1. ./cluster-access.sh check          # Verify cluster readiness
  2. ./build-and-push.sh                # Build operator image
  3. ./operator-nexus.sh deploy         # Deploy operator
  4. ./operator-nexus.sh status         # Verify health
  5. ./deploy-capability.sh             # Deploy capability

Examples:
  ./operator-nexus.sh deploy
  ./operator-nexus.sh status
  ./operator-nexus.sh update
  ./operator-nexus.sh delete
  ./operator-nexus.sh monitor

EOF
}

show_header() {
    local action=$1
    echo ""
    echo "=============================================="
    echo "  $action Operator - nexus-dev Cluster"
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
        echo "  kubectl -n nexus-system get pods"
        echo "  kubectl -n nexus-system logs -f deployment/nexus-operator"
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
        echo "   ./operator-nexus.sh monitor"
        echo ""
        echo "3. Verify all resources:"
        echo "   ./operator-nexus.sh verify-capability"
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
    
    # Ensure all NexusCapability CRs are fully deleted before removing the operator
    if kubectl api-resources --api-group=nexus.ai > /dev/null 2>&1; then
        local cap_count
        cap_count=$(kubectl get nexuscapabilities -A --no-headers 2>/dev/null | wc -l)
        if [ "$cap_count" -gt 0 ]; then
            echo "═══════════════════════════════════════════════════════════════════"
            echo "  Pre-cleanup: Deleting NexusCapability resources"
            echo "═══════════════════════════════════════════════════════════════════"
            echo ""
            echo "  Found $cap_count NexusCapability resource(s). Deleting..."
            kubectl delete nexuscapabilities --all -A --wait=false > /dev/null 2>&1

            local wait_secs=0
            local max_wait=60
            while [ "$wait_secs" -lt "$max_wait" ]; do
                local remaining
                remaining=$(kubectl get nexuscapabilities -A --no-headers 2>/dev/null | wc -l)
                if [ "$remaining" -eq 0 ]; then
                    echo "  ✓ All NexusCapability resources deleted"
                    break
                fi
                if [ "$((wait_secs % 15))" -eq 0 ] && [ "$wait_secs" -gt 0 ]; then
                    echo "  Waiting for operator to process finalizers... (${wait_secs}s/${max_wait}s, ${remaining} remaining)"
                fi
                sleep 5
                wait_secs=$((wait_secs + 5))
            done

            local stuck
            stuck=$(kubectl get nexuscapabilities -A -o json 2>/dev/null | python3 -c "
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
                    kubectl patch nexuscapability "$name" -n "$ns" --type merge -p '{"metadata":{"finalizers":[]}}' > /dev/null 2>&1 || true
                    echo "  ✓ Cleared finalizer: ${ns}/${name}"
                done
                sleep 5
                local final_count
                final_count=$(kubectl get nexuscapabilities -A --no-headers 2>/dev/null | wc -l)
                if [ "$final_count" -eq 0 ]; then
                    echo "  ✓ All NexusCapability resources fully removed"
                else
                    echo "  ⚠ ${final_count} NexusCapability resource(s) still present"
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
        echo "  ./operator-nexus.sh deploy"
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
    """Find NexusCapability CR. target can be 'namespace/name' or auto-detect."""
    if target and "/" in target:
        ns, name = target.split("/", 1)
        obj = kubectl_json(["get", "nexuscapability", name, "-n", ns])
        if obj:
            return obj
        print(f"Error: NexusCapability {name} not found in namespace {ns}")
        sys.exit(1)
    
    # Auto-detect: search all namespaces
    obj = kubectl_json(["get", "nexuscapability", "--all-namespaces"])
    if not obj or not obj.get("items"):
        print("No NexusCapability resources found.")
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
    
    print("Finding NexusCapability...")
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
        obj = kubectl_json(["get", "nexuscapability", name, "-n", ns])
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
        print("Tip: Run './operator-nexus.sh verify-capability' to verify resources")

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
    
    local OP_NS="nexus-system"
    local JOB_NAME="verify-capability-run"
    local CM_NAME="verify-capability-script"
    local VERIFY_PY="${SCRIPT_DIR}/verify-capability.py"
    
    if [ ! -f "$VERIFY_PY" ]; then
        echo -e "${RED}  Missing ${VERIFY_PY}${NC}"
        return 1
    fi
    
    if ! kubectl get deployment nexus-operator -n "${OP_NS}" >/dev/null 2>&1; then
        echo -e "${RED}  Operator deployment not found in ${OP_NS}. Deploy operator first.${NC}"
        return 1
    fi
    
    local OP_SA
    OP_SA=$(kubectl get deployment nexus-operator -n "${OP_NS}" -o jsonpath='{.spec.template.spec.serviceAccountName}' 2>/dev/null || echo "nexus-operator")
    local OP_IMAGE
    OP_IMAGE=$(kubectl get deployment nexus-operator -n "${OP_NS}" -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null)
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
    if ! kubectl get namespace nexus-system >/dev/null 2>&1; then
        echo -e "${YELLOW}✗ Operator not deployed${NC}"
        echo "  Namespace 'nexus-system' not found"
        echo ""
        echo "To deploy:"
        echo "  ./build-and-deploy.sh"
        echo ""
        return 1
    fi
    
    echo "✓ Namespace: nexus-system exists"
    echo ""
    
    # Check deployment
    echo "Deployment Status:"
    if kubectl get deployment nexus-operator -n nexus-system >/dev/null 2>&1; then
        kubectl get deployment nexus-operator -n nexus-system
    else
        echo "  ✗ Deployment not found"
        return 1
    fi
    echo ""
    
    # Check pods
    echo "Pod Status:"
    if kubectl get pods -n nexus-system -l app.kubernetes.io/name=nexus-operator >/dev/null 2>&1; then
        kubectl get pods -n nexus-system -l app.kubernetes.io/name=nexus-operator
        
        # Check if pods are healthy
        READY_PODS=$(kubectl get pods -n nexus-system -l app.kubernetes.io/name=nexus-operator -o jsonpath='{.items[*].status.containerStatuses[*].ready}' 2>/dev/null | grep -c "true" || echo "0")
        TOTAL_PODS=$(kubectl get pods -n nexus-system -l app.kubernetes.io/name=nexus-operator --no-headers 2>/dev/null | wc -l)
        
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
    if kubectl get crd nexuscapabilities.nexus.ai >/dev/null 2>&1; then
        echo -e "  ${GREEN}✓ NexusCapability CRD registered${NC}"
    else
        echo -e "  ${RED}✗ NexusCapability CRD not found${NC}"
    fi
    echo ""
    
    echo "To view logs:"
    echo "  kubectl -n nexus-system logs -f deployment/nexus-operator"
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
            echo "Use ./cluster-access.sh check for cluster readiness checks."
            exit 0
            ;;
        fix-irsa|setup-irsa|irsa)
            echo "OIDC/IRSA is managed by create-hardened-eks-cluster.sh."
            echo "To verify: ./cluster-access.sh check"
            exit 0
            ;;
        install-alb-controller|alb|alb-controller)
            echo "ALB Controller is installed by create-hardened-eks-cluster.sh."
            echo "To verify: ./cluster-access.sh check"
            exit 0
            ;;
        delete-alb-controller|delete-alb|uninstall-alb|delete-ebs-csi|remove-ebs-csi)
            echo "Use deploy/eks/delete-eks-cluster.sh for infrastructure cleanup."
            exit 0
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

            echo "Applying NexusNetworkConfig CRD..."
            kubectl apply -f "${SCRIPT_DIR}/manifests/network-config-crd.yaml" 2>/dev/null
            echo ""

            # Ensure operator ServiceAccount has RBAC for the new CRD
            echo "Ensuring operator RBAC for NexusNetworkConfig..."
            SA_NAME=$(kubectl get deployment nexus-operator -n nexus-system -o jsonpath='{.spec.template.spec.serviceAccountName}' 2>/dev/null || echo "nexus-operator-sa")
            kubectl apply -f - <<RBAC_EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: nexus-operator-network-config
rules:
  - apiGroups: ["nexus.ai"]
    resources: ["nexusnetworkconfigs", "nexusnetworkconfigs/status"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: nexus-operator-network-config
subjects:
  - kind: ServiceAccount
    name: ${SA_NAME}
    namespace: nexus-system
roleRef:
  kind: ClusterRole
  name: nexus-operator-network-config
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
            kubectl rollout restart deployment nexus-operator -n nexus-system 2>/dev/null || true
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
            echo -e "${YELLOW}Timeout waiting for endpoints. Check: kubectl logs -n nexus-system deployment/nexus-operator${NC}"
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
                echo "  No NexusNetworkConfig found."
                echo ""
                echo "  To set up VPC endpoints, run:"
                echo "    ./operator-nexus.sh setup-endpoints"
            fi
            echo ""
            ;;
        delete-endpoints|remove-endpoints)
            show_header "Delete VPC Endpoints Configuration"

            if ! kubectl get tnc vpc-endpoints > /dev/null 2>&1; then
                echo "  No NexusNetworkConfig 'vpc-endpoints' found — nothing to delete."
                echo ""
                exit 0
            fi

            echo "  This will delete the NexusNetworkConfig CR."
            echo "  The actual VPC endpoints in AWS will NOT be deleted (they remain for other workloads)."
            echo ""
            read -rp "  Proceed? [y/N] " confirm
            if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
                echo "  Aborted."
                exit 0
            fi
            echo ""

            echo "  Deleting NexusNetworkConfig 'vpc-endpoints'..."
            kubectl delete tnc vpc-endpoints --timeout=30s 2>/dev/null || \
                kubectl patch tnc vpc-endpoints --type merge -p '{"metadata":{"finalizers":[]}}' 2>/dev/null
            echo -e "${GREEN}  ✓ NexusNetworkConfig deleted${NC}"
            echo ""

            echo "  Cleaning up RBAC..."
            kubectl delete clusterrolebinding nexus-operator-network-config 2>/dev/null || true
            kubectl delete clusterrole nexus-operator-network-config 2>/dev/null || true
            echo -e "${GREEN}  ✓ RBAC cleaned up${NC}"
            echo ""

            echo "  Cleaning up CRD..."
            kubectl delete crd nexusnetworkconfigs.nexus.ai 2>/dev/null || true
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

            local OP_NS="nexus-system"
            local JOB_NAME="check-operator-permissions"
            local CM_NAME="operator-perm-check"

            # Resolve ECR registry
            local OP_ACCOUNT
            OP_ACCOUNT=$(aws sts get-caller-identity --profile "${AWS_PROFILE}" --query Account --output text 2>/dev/null)
            local OP_ECR="${OP_ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

            # Get operator SA name from deployment
            local OP_SA
            OP_SA=$(kubectl get deployment nexus-operator -n "${OP_NS}" -o jsonpath='{.spec.template.spec.serviceAccountName}' 2>/dev/null || echo "nexus-operator-sa")
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

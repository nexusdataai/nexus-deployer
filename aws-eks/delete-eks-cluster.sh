#!/bin/bash
#
# EKS Cluster Deletion Script
#
# Deletes an EKS cluster and EVERY resource that create-hardened-eks-cluster.sh
# provisions, by default. To keep something around, opt out per category:
#   --keep-vpc      preserves VPC, NAT, ELBs, EBS volumes, VPC endpoints
#   --keep-roles    preserves IAM roles + LB Controller IAM policy
#
# Resources removed by default (no flags needed):
#   - Helm releases (LB controller)
#   - EKS addons (EBS CSI)
#   - Node groups
#   - EKS cluster
#   - OIDC provider for the cluster
#   - CloudWatch log group /aws/eks/<cluster>/cluster
#   - IRSA roles (operator, app, EBS CSI, LB controller)        [opt out: --keep-roles]
#   - AmazonEKSAutoClusterRole, EKS_Node_Role                   [opt out: --keep-roles]
#   - AWSLoadBalancerControllerIAMPolicy                        [opt out: --keep-roles]
#   - NAT ASGs + launch templates + NAT EC2 instances           [opt out: --keep-vpc]
#   - ELBs tagged elbv2.k8s.aws/cluster=<name>                  [opt out: --keep-vpc]
#   - EBS volumes tagged kubernetes.io/cluster/<name>=owned     [opt out: --keep-vpc]
#   - VPC endpoints                                             [opt out: --keep-vpc]
#   - VPC (subnets, route tables, IGW, ENIs, security groups)   [opt out: --keep-vpc]
#
# Usage:
#   ./delete-eks-cluster.sh --name nexus-dev                       # full teardown (interactive confirm)
#   ./delete-eks-cluster.sh --name nexus-dev --auto-approve        # full teardown, no prompt
#   ./delete-eks-cluster.sh --name nexus-dev --keep-vpc            # delete cluster only, keep VPC
#   ./delete-eks-cluster.sh --name nexus-dev --keep-roles          # delete cluster + VPC, keep IAM roles
#   ./delete-eks-cluster.sh --name nexus-dev --keep-vpc --keep-roles  # delete cluster ONLY
#

set -e

CLUSTER_NAME="${CLUSTER_NAME:-nexus-dev}"
REGION="${REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-ptr-tech}"
CAPABILITY="${CAPABILITY:-nexus}"
APP_ENV="${APP_ENV:-dev}"
AUTO_APPROVE="${AUTO_APPROVE:-no}"
# Default behavior: full teardown. Every resource the create script
# provisioned (VPC, NAT, ELBs, EBS volumes, IAM roles, log groups) is
# removed unless you opt out via --keep-vpc / --keep-roles. This is the
# safe-by-default for "delete this cluster end-to-end" but very
# destructive — the confirmation prompt below enumerates what will go.
DELETE_VPC="${DELETE_VPC:-true}"
DELETE_ROLES="${DELETE_ROLES:-true}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --name)         CLUSTER_NAME="$2"; shift 2 ;;
        --region)       REGION="$2"; shift 2 ;;
        --profile)      AWS_PROFILE="$2"; shift 2 ;;
        --capability)   CAPABILITY="$2"; shift 2 ;;
        --env)          APP_ENV="$2"; shift 2 ;;
        --vpc-id)       VPC_ID="$2"; shift 2 ;;
        # Opt-out flags. The legacy --delete-* names are kept as no-ops
        # so existing CI / scripts that pass them explicitly don't break.
        --keep-vpc)     DELETE_VPC=false; shift ;;
        --keep-roles)   DELETE_ROLES=false; shift ;;
        --delete-vpc)   DELETE_VPC=true; shift ;;
        --delete-roles) DELETE_ROLES=true; shift ;;
        --auto-approve) AUTO_APPROVE=yes; shift ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Deletes an EKS cluster and ALL resources created by"
            echo "create-hardened-eks-cluster.sh by default."
            echo ""
            echo "Options:"
            echo "  --name NAME           Cluster name (default: nexus-dev)"
            echo "  --region REGION       AWS region (default: us-east-1)"
            echo "  --profile PROFILE     AWS CLI profile (default: ptr-tech)"
            echo "  --capability NAME     Capability name for app role cleanup (default: nexus)"
            echo "  --env ENV             Environment for app role cleanup (default: dev)"
            echo "  --vpc-id VPC_ID       VPC ID to delete (auto-detected from cluster if running)"
            echo "  --keep-vpc            DO NOT delete VPC, NAT ASGs, ELBs, EBS volumes, endpoints"
            echo "  --keep-roles          DO NOT delete IAM roles (cluster, node, IRSA, LBC policy)"
            echo "  --auto-approve        Skip confirmation prompt"
            echo "  --help                Show this help"
            echo ""
            echo "Backward-compatible flags (default behavior is now 'delete all'):"
            echo "  --delete-vpc          (no-op; same as default)"
            echo "  --delete-roles        (no-op; same as default)"
            exit 0
            ;;
        *) echo "Unknown option: $1 (use --help for usage)"; exit 1 ;;
    esac
done

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

AWS_ACCOUNT_ID=$(aws sts get-caller-identity --profile "$AWS_PROFILE" --query 'Account' --output text 2>/dev/null || true)
if [ -z "$AWS_ACCOUNT_ID" ]; then
    echo "❌ Failed to get credentials from profile '$AWS_PROFILE'"
    exit 1
fi

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║              EKS Cluster Deletion Script                      ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "Cluster:      $CLUSTER_NAME"
echo "Region:       $REGION"
echo "Account:      $AWS_ACCOUNT_ID"
echo "Profile:      $AWS_PROFILE"
echo "Delete VPC:   $DELETE_VPC"
echo "Delete Roles: $DELETE_ROLES"
echo ""

if ! aws eks describe-cluster --name "$CLUSTER_NAME" --region "$REGION" --profile "$AWS_PROFILE" &>/dev/null; then
    echo -e "${YELLOW}Cluster '$CLUSTER_NAME' does not exist. Skipping cluster deletion.${NC}"
    CLUSTER_EXISTS=false
else
    CLUSTER_EXISTS=true
fi

if [ "$AUTO_APPROVE" != "yes" ]; then
    echo -e "${RED}WARNING: This will PERMANENTLY DELETE the following:${NC}"
    echo "  • EKS cluster:       $CLUSTER_NAME (in $REGION)"
    echo "  • All node groups, Helm releases (LB Controller), EKS addons (EBS CSI)"
    echo "  • OIDC provider for the cluster"
    echo "  • CloudWatch log group: /aws/eks/$CLUSTER_NAME/cluster"
    if [ "$DELETE_VPC" == "true" ]; then
        echo "  • VPC + subnets + route tables + IGW + security groups (auto-created)"
        echo "  • VPC endpoints, NAT ASGs / launch templates / NAT EC2 instances"
        echo "  • Cluster-tagged ELBs (ALBs/NLBs)"
        echo "  • Cluster-tagged EBS volumes (data loss possible)"
    else
        echo "  • VPC: PRESERVED (--keep-vpc)"
    fi
    if [ "$DELETE_ROLES" == "true" ]; then
        echo "  • IAM roles: operator, app, EBS CSI, LB controller, AmazonEKSAutoClusterRole, EKS_Node_Role"
        echo "  • IAM policy: AWSLoadBalancerControllerIAMPolicy"
    else
        echo "  • IAM roles: PRESERVED (--keep-roles)"
    fi
    echo ""
    read -p "Type the cluster name '${CLUSTER_NAME}' to confirm: " CONFIRM
    if [ "$CONFIRM" != "$CLUSTER_NAME" ]; then
        echo "Aborted."
        exit 1
    fi
fi

# Discover VPC and OIDC from cluster (if still running)
if [ -z "$VPC_ID" ] && [ "$CLUSTER_EXISTS" == "true" ]; then
    VPC_ID=$(aws eks describe-cluster --name "$CLUSTER_NAME" --region "$REGION" --profile "$AWS_PROFILE" \
        --query 'cluster.resourcesVpcConfig.vpcId' --output text 2>/dev/null || true)
fi
if [ "$CLUSTER_EXISTS" == "true" ]; then
    OIDC_ISSUER=$(aws eks describe-cluster --name "$CLUSTER_NAME" --region "$REGION" --profile "$AWS_PROFILE" \
        --query 'cluster.identity.oidc.issuer' --output text 2>/dev/null || true)
    OIDC_PROVIDER=$(echo "$OIDC_ISSUER" | sed 's|https://||')
fi

# If VPC not found from cluster (already deleted), try by name tag
if [ -z "$VPC_ID" ] || [ "$VPC_ID" == "None" ]; then
    VPC_ID=$(aws ec2 describe-vpcs --filters "Name=tag:Name,Values=${CLUSTER_NAME}-vpc" \
        --region "$REGION" --profile "$AWS_PROFILE" \
        --query 'Vpcs[0].VpcId' --output text 2>/dev/null || true)
    [ "$VPC_ID" == "None" ] && VPC_ID=""
    if [ -n "$VPC_ID" ]; then
        echo "Discovered VPC by name tag: $VPC_ID"
    fi
fi

#=============================================================================
# Step 1: Remove Helm releases
#=============================================================================

if [ "$CLUSTER_EXISTS" == "true" ]; then
    echo "=== Step 1: Removing Helm releases ==="
    aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$REGION" --profile "$AWS_PROFILE" 2>/dev/null || true

    if command -v helm &>/dev/null; then
        if helm status aws-load-balancer-controller -n kube-system &>/dev/null; then
            helm uninstall aws-load-balancer-controller -n kube-system --wait 2>/dev/null || true
            echo -e "${GREEN}✓ AWS Load Balancer Controller removed${NC}"
        else
            echo "   LB controller not installed, skipping"
        fi
    else
        echo "   helm not found, skipping Helm cleanup"
    fi
fi

#=============================================================================
# Step 2: Remove EKS addons
#=============================================================================

if [ "$CLUSTER_EXISTS" == "true" ]; then
    echo ""
    echo "=== Step 2: Removing EKS addons ==="
    if aws eks describe-addon --cluster-name "$CLUSTER_NAME" --addon-name aws-ebs-csi-driver \
        --region "$REGION" --profile "$AWS_PROFILE" &>/dev/null; then
        aws eks delete-addon --cluster-name "$CLUSTER_NAME" --addon-name aws-ebs-csi-driver \
            --region "$REGION" --profile "$AWS_PROFILE" > /dev/null 2>&1
        echo -e "${GREEN}✓ EBS CSI Driver addon removed${NC}"
    else
        echo "   EBS CSI addon not found, skipping"
    fi
fi

#=============================================================================
# Step 3: Delete node groups
#=============================================================================

if [ "$CLUSTER_EXISTS" == "true" ]; then
    echo ""
    echo "=== Step 3: Deleting node groups ==="
    NODEGROUPS=$(aws eks list-nodegroups --cluster-name "$CLUSTER_NAME" --region "$REGION" --profile "$AWS_PROFILE" \
        --query 'nodegroups[]' --output text 2>/dev/null)

    if [ -n "$NODEGROUPS" ]; then
        for ng in $NODEGROUPS; do
            echo "   Deleting: $ng"
            aws eks delete-nodegroup --cluster-name "$CLUSTER_NAME" --nodegroup-name "$ng" \
                --region "$REGION" --profile "$AWS_PROFILE" &>/dev/null || true
        done
        echo "   Waiting for node groups to delete..."
        while true; do
            REMAINING=$(aws eks list-nodegroups --cluster-name "$CLUSTER_NAME" --region "$REGION" --profile "$AWS_PROFILE" \
                --query 'nodegroups[]' --output text 2>/dev/null)
            [ -z "$REMAINING" ] && break
            echo -n "."
            sleep 10
        done
        echo ""
        echo -e "${GREEN}✓ All node groups deleted${NC}"
    else
        echo "   No node groups found"
    fi
fi

#=============================================================================
# Step 4: Delete EKS cluster
#=============================================================================

if [ "$CLUSTER_EXISTS" == "true" ]; then
    echo ""
    echo "=== Step 4: Deleting EKS cluster ==="
    aws eks delete-cluster --name "$CLUSTER_NAME" --region "$REGION" --profile "$AWS_PROFILE" > /dev/null 2>&1
    echo "   Waiting for cluster deletion (5-10 minutes)..."
    COUNT=0
    while aws eks describe-cluster --name "$CLUSTER_NAME" --region "$REGION" --profile "$AWS_PROFILE" &>/dev/null; do
        COUNT=$((COUNT + 1))
        [ $((COUNT % 6)) -eq 0 ] && echo "   Still deleting... ($((COUNT / 6)) minutes)"
        sleep 10
    done
    echo -e "${GREEN}✓ Cluster deleted${NC}"
fi

#=============================================================================
# Step 5: Delete OIDC provider
#=============================================================================

echo ""
echo "=== Step 5: Deleting OIDC provider ==="
if [ -n "$OIDC_PROVIDER" ] && [ "$OIDC_PROVIDER" != "None" ]; then
    OIDC_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/${OIDC_PROVIDER}"
    if aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_ARN" \
        --profile "$AWS_PROFILE" &>/dev/null; then
        aws iam delete-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_ARN" \
            --profile "$AWS_PROFILE"
        echo -e "${GREEN}✓ OIDC provider deleted${NC}"
    else
        echo "   OIDC provider not found in IAM"
    fi
else
    echo "   No OIDC provider to delete (cluster info not available)"
fi

#=============================================================================
# Step 6: Delete IRSA roles
#=============================================================================

if [ "$DELETE_ROLES" == "true" ]; then
    echo ""
    echo "=== Step 6: Deleting IAM roles ==="

    delete_role() {
        local role_name="$1"
        if ! aws iam get-role --role-name "$role_name" --profile "$AWS_PROFILE" &>/dev/null; then
            echo "   $role_name: not found"
            return 0
        fi

        for policy_arn in $(aws iam list-attached-role-policies --role-name "$role_name" \
            --profile "$AWS_PROFILE" --query 'AttachedPolicies[].PolicyArn' --output text 2>/dev/null); do
            aws iam detach-role-policy --role-name "$role_name" --policy-arn "$policy_arn" \
                --profile "$AWS_PROFILE" 2>/dev/null || true
        done

        for policy_name in $(aws iam list-role-policies --role-name "$role_name" \
            --profile "$AWS_PROFILE" --query 'PolicyNames[]' --output text 2>/dev/null); do
            aws iam delete-role-policy --role-name "$role_name" --policy-name "$policy_name" \
                --profile "$AWS_PROFILE" 2>/dev/null || true
        done

        aws iam delete-role --role-name "$role_name" --profile "$AWS_PROFILE" 2>/dev/null || true
        echo -e "   ${GREEN}✓ $role_name deleted${NC}"
    }

    OPERATOR_ROLE_NAME="${CAPABILITY}-${APP_ENV}-operator-role"
    APP_ROLE_NAME="${CAPABILITY}-${APP_ENV}-app-role"
    delete_role "$OPERATOR_ROLE_NAME"
    delete_role "$APP_ROLE_NAME"
    delete_role "AmazonEKS_EBS_CSI_DriverRole"
    delete_role "aws-load-balancer-controller-role"

    LBC_POLICY_ARN=$(aws iam list-policies --query "Policies[?PolicyName=='AWSLoadBalancerControllerIAMPolicy'].Arn" \
        --profile "$AWS_PROFILE" --output text 2>/dev/null)
    if [ -n "$LBC_POLICY_ARN" ] && [ "$LBC_POLICY_ARN" != "None" ]; then
        aws iam delete-policy --policy-arn "$LBC_POLICY_ARN" --profile "$AWS_PROFILE" 2>/dev/null || true
        echo -e "   ${GREEN}✓ AWSLoadBalancerControllerIAMPolicy deleted${NC}"
    fi

    delete_role "AmazonEKSAutoClusterRole"
    delete_role "EKS_Node_Role"
else
    echo ""
    echo "=== Step 6: Skipping IAM role deletion (--keep-roles) ==="
fi

#=============================================================================
# Step 6b: Delete NAT instance ASGs / launch templates (hybrid profiles)
#=============================================================================
#
# Created by create-hardened-eks-cluster.sh for moderate/lowest-cost network
# profiles. Idempotent — silently skip resources that don't exist (cluster
# was created on a profile that didn't use NAT instances).

if [ "$DELETE_VPC" == "true" ] && [ -n "$VPC_ID" ] && [ "$VPC_ID" != "None" ]; then
    echo ""
    echo "=== Step 6b: Deleting NAT instance ASGs / launch templates ==="

    for suffix in az1 az2 single; do
        asg_name="${CLUSTER_NAME}-nat-${suffix}"
        if aws autoscaling describe-auto-scaling-groups \
            --auto-scaling-group-names "$asg_name" \
            --region "$REGION" --profile "$AWS_PROFILE" \
            --query 'AutoScalingGroups[0].AutoScalingGroupName' --output text 2>/dev/null | grep -q "$asg_name"; then
            aws autoscaling update-auto-scaling-group \
                --auto-scaling-group-name "$asg_name" \
                --min-size 0 --max-size 0 --desired-capacity 0 \
                --region "$REGION" --profile "$AWS_PROFILE" >/dev/null 2>&1 || true
            aws autoscaling delete-auto-scaling-group \
                --auto-scaling-group-name "$asg_name" --force-delete \
                --region "$REGION" --profile "$AWS_PROFILE" >/dev/null 2>&1 || true
            echo -e "   ${GREEN}✓ ASG $asg_name deleted${NC}"
        fi

        lt_name="${CLUSTER_NAME}-nat-lt-${suffix}"
        if aws ec2 describe-launch-templates --launch-template-names "$lt_name" \
            --region "$REGION" --profile "$AWS_PROFILE" >/dev/null 2>&1; then
            aws ec2 delete-launch-template --launch-template-name "$lt_name" \
                --region "$REGION" --profile "$AWS_PROFILE" >/dev/null 2>&1 || true
            echo -e "   ${GREEN}✓ Launch template $lt_name deleted${NC}"
        fi
    done

    # Also terminate any straggler NAT instances tagged by us, in case the
    # ASG was already deleted but instances lingered.
    NAT_INSTANCES=$(aws ec2 describe-instances \
        --filters "Name=tag:nexus:nat-instance,Values=true" "Name=vpc-id,Values=$VPC_ID" \
                  "Name=instance-state-name,Values=pending,running,stopping,stopped" \
        --region "$REGION" --profile "$AWS_PROFILE" \
        --query 'Reservations[].Instances[].InstanceId' --output text 2>/dev/null)
    if [ -n "$NAT_INSTANCES" ]; then
        aws ec2 terminate-instances --instance-ids $NAT_INSTANCES \
            --region "$REGION" --profile "$AWS_PROFILE" >/dev/null 2>&1 || true
        echo -e "   ${GREEN}✓ Terminated NAT instances: $NAT_INSTANCES${NC}"
    fi

    # NAT security group cleanup happens in Step 8's generic SG sweep.
fi

#=============================================================================
# Step 6c: Delete ELBs tagged for this cluster
#=============================================================================
#
# AWS Load Balancer Controller provisions ALBs / NLBs for Ingress and
# Service:LoadBalancer resources. Those ELBs are AWS resources that
# outlive both the cluster and the Helm release. Their ENIs sit in the
# VPC subnets, so they MUST be deleted before VPC teardown — Step 8's
# ENI sweep cannot detach ELB-owned ENIs. We filter strictly by the
# LB Controller's standard cluster tag so other clusters' ELBs are
# never touched.

if [ "$DELETE_VPC" == "true" ]; then
    echo ""
    echo "=== Step 6c: Deleting ELBs tagged for cluster $CLUSTER_NAME ==="
    LB_ARNS=$(aws elbv2 describe-load-balancers --region "$REGION" --profile "$AWS_PROFILE" \
        --query 'LoadBalancers[].LoadBalancerArn' --output text 2>/dev/null)
    LB_DELETED=0
    for arn in $LB_ARNS; do
        OWNED=$(aws elbv2 describe-tags --resource-arns "$arn" \
            --region "$REGION" --profile "$AWS_PROFILE" \
            --query "TagDescriptions[0].Tags[?Key=='elbv2.k8s.aws/cluster' && Value=='$CLUSTER_NAME'].Value" \
            --output text 2>/dev/null)
        if [ -n "$OWNED" ] && [ "$OWNED" != "None" ]; then
            aws elbv2 delete-load-balancer --load-balancer-arn "$arn" \
                --region "$REGION" --profile "$AWS_PROFILE" 2>/dev/null || true
            echo "   ✓ Deleted ELB $arn"
            LB_DELETED=$((LB_DELETED + 1))
        fi
    done
    if [ "$LB_DELETED" -gt 0 ]; then
        echo "   Waiting 30 s for ELB ENIs to be released..."
        sleep 30
    else
        echo "   No cluster-tagged ELBs found"
    fi
fi

#=============================================================================
# Step 6d: Delete EBS volumes tagged for this cluster
#=============================================================================
#
# EBS CSI driver creates volumes for PersistentVolumeClaims and tags
# them with kubernetes.io/cluster/<cluster>=owned. After cluster delete
# they linger as orphan volumes and accrue cost. Cluster-name tag filter
# scopes the delete to this cluster only.

if [ "$DELETE_VPC" == "true" ]; then
    echo ""
    echo "=== Step 6d: Deleting EBS volumes tagged for cluster $CLUSTER_NAME ==="
    VOL_IDS=$(aws ec2 describe-volumes --region "$REGION" --profile "$AWS_PROFILE" \
        --filters "Name=tag:kubernetes.io/cluster/$CLUSTER_NAME,Values=owned" \
                  "Name=status,Values=available,in-use" \
        --query 'Volumes[].VolumeId' --output text 2>/dev/null)
    if [ -n "$VOL_IDS" ]; then
        for vol in $VOL_IDS; do
            aws ec2 delete-volume --volume-id "$vol" \
                --region "$REGION" --profile "$AWS_PROFILE" 2>/dev/null || true
            echo "   ✓ Deleted volume $vol"
        done
    else
        echo "   No cluster-tagged volumes found"
    fi
fi

#=============================================================================
# Step 7: Delete VPC endpoints
#=============================================================================

if [ "$DELETE_VPC" == "true" ] && [ -n "$VPC_ID" ] && [ "$VPC_ID" != "None" ]; then
    echo ""
    echo "=== Step 7: Deleting VPC endpoints ==="
    ENDPOINT_IDS=$(aws ec2 describe-vpc-endpoints \
        --filters "Name=vpc-id,Values=$VPC_ID" \
        --region "$REGION" --profile "$AWS_PROFILE" \
        --query 'VpcEndpoints[].VpcEndpointId' --output text 2>/dev/null)

    if [ -n "$ENDPOINT_IDS" ]; then
        for ep in $ENDPOINT_IDS; do
            aws ec2 delete-vpc-endpoints --vpc-endpoint-ids "$ep" \
                --region "$REGION" --profile "$AWS_PROFILE" > /dev/null 2>&1 || true
        done
        ENDPOINT_COUNT=$(echo "$ENDPOINT_IDS" | wc -w)
        echo -e "${GREEN}✓ $ENDPOINT_COUNT VPC endpoints deleted${NC}"
    else
        echo "   No VPC endpoints found"
    fi
else
    echo ""
    echo "=== Step 7: Skipping VPC endpoint deletion (--keep-vpc) ==="
fi

#=============================================================================
# Step 8: Delete VPC and networking
#=============================================================================

if [ "$DELETE_VPC" == "true" ] && [ -n "$VPC_ID" ] && [ "$VPC_ID" != "None" ]; then
    echo ""
    echo "=== Step 8: Deleting VPC ($VPC_ID) ==="

    echo "   Cleaning up ENIs..."
    for attempt in 1 2 3; do
        ENIS=$(aws ec2 describe-network-interfaces \
            --filters "Name=vpc-id,Values=$VPC_ID" \
            --region "$REGION" --profile "$AWS_PROFILE" \
            --query 'NetworkInterfaces[].NetworkInterfaceId' --output text 2>/dev/null)
        [ -z "$ENIS" ] && break
        for eni in $ENIS; do
            ATTACH_ID=$(aws ec2 describe-network-interfaces --network-interface-ids "$eni" \
                --region "$REGION" --profile "$AWS_PROFILE" \
                --query 'NetworkInterfaces[0].Attachment.AttachmentId' --output text 2>/dev/null)
            if [ -n "$ATTACH_ID" ] && [ "$ATTACH_ID" != "None" ]; then
                aws ec2 detach-network-interface --attachment-id "$ATTACH_ID" --force \
                    --region "$REGION" --profile "$AWS_PROFILE" 2>/dev/null || true
            fi
            sleep 2
            aws ec2 delete-network-interface --network-interface-id "$eni" \
                --region "$REGION" --profile "$AWS_PROFILE" 2>/dev/null || true
        done
        [ "$attempt" -lt 3 ] && echo "   Waiting 10s for ENI cleanup (attempt $attempt/3)..." && sleep 10
    done
    echo "   ENIs cleaned up"

    for sg in $(aws ec2 describe-security-groups \
        --filters "Name=vpc-id,Values=$VPC_ID" \
        --region "$REGION" --profile "$AWS_PROFILE" \
        --query 'SecurityGroups[?GroupName!=`default`].GroupId' --output text 2>/dev/null); do
        aws ec2 delete-security-group --group-id "$sg" \
            --region "$REGION" --profile "$AWS_PROFILE" 2>/dev/null || true
    done
    echo "   Security groups cleaned up"

    for sub in $(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" \
        --region "$REGION" --profile "$AWS_PROFILE" \
        --query 'Subnets[].SubnetId' --output text 2>/dev/null); do
        aws ec2 delete-subnet --subnet-id "$sub" \
            --region "$REGION" --profile "$AWS_PROFILE" 2>/dev/null || true
    done
    echo "   Subnets deleted"

    for rt in $(aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$VPC_ID" \
        --region "$REGION" --profile "$AWS_PROFILE" \
        --query 'RouteTables[].RouteTableId' --output text 2>/dev/null); do
        MAIN_COUNT=$(aws ec2 describe-route-tables --route-table-ids "$rt" \
            --region "$REGION" --profile "$AWS_PROFILE" \
            --query 'length(RouteTables[0].Associations[?Main==`true`])' --output text 2>/dev/null || echo "0")
        if [ "$MAIN_COUNT" != "0" ]; then
            continue
        fi
        for assoc in $(aws ec2 describe-route-tables --route-table-ids "$rt" \
            --region "$REGION" --profile "$AWS_PROFILE" \
            --query 'RouteTables[0].Associations[].RouteTableAssociationId' --output text 2>/dev/null); do
            aws ec2 disassociate-route-table --association-id "$assoc" \
                --region "$REGION" --profile "$AWS_PROFILE" 2>/dev/null || true
        done
        aws ec2 delete-route-table --route-table-id "$rt" \
            --region "$REGION" --profile "$AWS_PROFILE" 2>/dev/null || true
    done
    echo "   Route tables deleted"

    for igw in $(aws ec2 describe-internet-gateways \
        --filters "Name=attachment.vpc-id,Values=$VPC_ID" \
        --region "$REGION" --profile "$AWS_PROFILE" \
        --query 'InternetGateways[].InternetGatewayId' --output text 2>/dev/null); do
        aws ec2 detach-internet-gateway --internet-gateway-id "$igw" --vpc-id "$VPC_ID" \
            --region "$REGION" --profile "$AWS_PROFILE" 2>/dev/null || true
        aws ec2 delete-internet-gateway --internet-gateway-id "$igw" \
            --region "$REGION" --profile "$AWS_PROFILE" 2>/dev/null || true
    done
    echo "   Internet gateway deleted"

    if aws ec2 delete-vpc --vpc-id "$VPC_ID" --region "$REGION" --profile "$AWS_PROFILE" 2>&1; then
        echo -e "${GREEN}✓ VPC $VPC_ID deleted${NC}"
    else
        echo -e "${RED}✗ VPC $VPC_ID could not be deleted. Check for remaining dependencies:${NC}"
        echo "    aws ec2 describe-network-interfaces --filters Name=vpc-id,Values=$VPC_ID --region $REGION --profile $AWS_PROFILE"
    fi
else
    if [ "$DELETE_VPC" != "true" ]; then
        echo ""
        echo "=== Step 8: Skipping VPC deletion (--keep-vpc) ==="
    fi
fi

#=============================================================================
# Step 9: Delete CloudWatch log group
#=============================================================================
#
# create-hardened-eks-cluster.sh enables control-plane logging via
#   --logging '{"clusterLogging":[{"types":["api","audit","authenticator",
#                                           "controllerManager","scheduler"],
#                                  "enabled":true}]}'
# AWS provisions /aws/eks/<cluster>/cluster on first log emission but does
# NOT delete it when the cluster goes away. The orphan log group keeps
# accruing storage cost. Cluster-scoped name, so safe to always sweep.

echo ""
echo "=== Step 9: Deleting CloudWatch log group ==="
LOG_GROUP="/aws/eks/${CLUSTER_NAME}/cluster"
if aws logs describe-log-groups --log-group-name-prefix "$LOG_GROUP" \
    --region "$REGION" --profile "$AWS_PROFILE" \
    --query "logGroups[?logGroupName=='$LOG_GROUP'].logGroupName" --output text 2>/dev/null \
    | grep -q "$LOG_GROUP"; then
    if aws logs delete-log-group --log-group-name "$LOG_GROUP" \
        --region "$REGION" --profile "$AWS_PROFILE" 2>/dev/null; then
        echo -e "${GREEN}✓ Log group $LOG_GROUP deleted${NC}"
    else
        echo -e "${YELLOW}⚠ Could not delete log group $LOG_GROUP (insufficient perms?)${NC}"
    fi
else
    echo "   No log group $LOG_GROUP found"
fi

#=============================================================================
# Done
#=============================================================================

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║              ✅ CLUSTER DELETION COMPLETE                      ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "Deleted:"
echo "  Cluster:        $CLUSTER_NAME"
[ "$CLUSTER_EXISTS" == "true" ] && echo "  OIDC Provider:  deleted"
[ "$DELETE_ROLES" == "true" ] && echo "  IAM Roles:      deleted (operator, app, EBS CSI, LB controller, cluster, node)"
[ "$DELETE_VPC" == "true" ] && [ -n "$VPC_ID" ] && echo "  VPC:            $VPC_ID (endpoints, subnets, IGW, SGs)"
[ "$DELETE_VPC" == "true" ] && echo "  ELBs:           cluster-tagged ALBs/NLBs deleted"
[ "$DELETE_VPC" == "true" ] && echo "  EBS Volumes:    cluster-tagged volumes deleted"
[ "$DELETE_VPC" == "true" ] && echo "  NAT:            ASGs + launch templates + EC2 instances deleted"
echo "  CW Log Group:   /aws/eks/$CLUSTER_NAME/cluster"
echo ""
if [ "$DELETE_ROLES" != "true" ] || [ "$DELETE_VPC" != "true" ]; then
    echo "Resources PRESERVED (you opted out via --keep-* flags):"
    [ "$DELETE_ROLES" != "true" ] && echo "  --keep-roles    IAM roles kept: operator, app, EBS CSI, LB controller, cluster, node + LBC policy"
    [ "$DELETE_VPC" != "true" ] && echo "  --keep-vpc      VPC kept: subnets, endpoints, security groups, NAT, ELBs, EBS volumes"
    echo ""
fi
echo "✅ Done"
echo ""

#!/bin/bash
#
# migrate-network-profile.sh — incremental network-profile migration helper.
#
# Migrates an existing, live EKS cluster between AWS access modes without
# losing pod state or causing downtime. Companion to create-hardened-eks-cluster.sh:
#   - The create script builds a brand-new cluster on a chosen profile.
#   - This script flips an EXISTING cluster between profiles in place.
#
# Forward path (provision):
#   higher-cost / public-nodes  →  lowest-cost  (provision 1 NAT instance)
#   higher-cost / lowest-cost   →  moderate     (provision NAT per AZ)
#
# Reverse path (teardown):
#   lowest-cost / moderate      →  higher-cost  (tear down NAT instance(s))
#
# What this script DOES:
#   1. Detects the current network-profile from the VPC tag nexus:network-profile.
#   2. Idempotently provisions NAT instance ASGs / launch templates / SG as needed.
#   3. Adds a 0.0.0.0/0 → NAT-ENI default route to the private route table(s).
#   4. Restamps the VPC tag to the target profile.
#   5. Prints the kubectl commands to patch NexusNetworkConfig and trigger reconcile.
#
# What this script does NOT do:
#   - Touch the cluster, node groups, IAM, or addons.
#   - Create or delete VPC interface endpoints. Interface endpoints can be
#     deleted as a separate manual step AFTER the new mode is verified — see
#     deploy/eks/README.md "Switching profiles on a running cluster".
#   - Patch NexusNetworkConfig automatically (printed instead, for safety).
#
# Usage:
#   ./migrate-network-profile.sh --name nexus-dev --target-profile lowest-cost
#   ./migrate-network-profile.sh --name nexus-dev --target-profile higher-cost  # rollback
#   AUTO_APPROVE=yes ./migrate-network-profile.sh --name nexus-dev --target-profile lowest-cost
#

set -e

# ── Defaults ────────────────────────────────────────────────────────────
CLUSTER_NAME="${CLUSTER_NAME:-nexus-dev}"
REGION="${REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-ptr-tech}"
TARGET_PROFILE="${TARGET_PROFILE:-}"
NAT_INSTANCE_TYPE="${NAT_INSTANCE_TYPE:-t4g.nano}"
NAT_AMI_OWNER="${NAT_AMI_OWNER:-568608671756}"        # fck-nat publisher
NAT_AMI_NAME_FILTER="${NAT_AMI_NAME_FILTER:-fck-nat-al2023-hvm-*}"
# Auto-detect AMI architecture from the instance type family suffix.
# Graviton-based families end with "g" (optionally followed by extra letters)
# right before the dot (e.g. t4g.nano, c6gn.large, m7gd.xlarge). Everything
# else is x86_64. Override with NAT_AMI_ARCH=... for unusual cases.
if [ -z "$NAT_AMI_ARCH" ]; then
    if [[ "$NAT_INSTANCE_TYPE" =~ g[a-z]*\. ]]; then
        NAT_AMI_ARCH="arm64"
    else
        NAT_AMI_ARCH="x86_64"
    fi
fi
AUTO_APPROVE="${AUTO_APPROVE:-no}"
DRY_RUN="${DRY_RUN:-no}"

# ── Args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case $1 in
        --name)              CLUSTER_NAME="$2"; shift 2 ;;
        --region)            REGION="$2"; shift 2 ;;
        --profile)           AWS_PROFILE="$2"; shift 2 ;;
        --target-profile)    TARGET_PROFILE="$2"; shift 2 ;;
        --nat-instance-type) NAT_INSTANCE_TYPE="$2"; shift 2 ;;
        --auto-approve)      AUTO_APPROVE=yes; shift ;;
        --dry-run)           DRY_RUN=yes; shift ;;
        --help|-h)
            cat <<EOF
Usage: $0 --name CLUSTER --target-profile PROFILE [options]

Required:
  --name NAME                    EKS cluster name (default: nexus-dev)
  --target-profile PROFILE       One of: higher-cost, moderate, lowest-cost, public-nodes

Optional:
  --region REGION                AWS region (default: us-east-1)
  --profile AWS_PROFILE          AWS CLI profile (default: ptr-tech)
  --nat-instance-type TYPE       NAT EC2 instance type (default: t4g.nano)
  --auto-approve                 Skip the confirmation prompt
  --dry-run                      Show planned actions without executing
  --help                         Show this help

Examples:
  $0 --name nexus-dev --target-profile lowest-cost
  $0 --name nexus-dev --target-profile higher-cost          # rollback
  AUTO_APPROVE=yes $0 --name nexus-dev --target-profile moderate
EOF
            exit 0
            ;;
        *) echo "Unknown option: $1 (use --help)"; exit 1 ;;
    esac
done

if [ -z "$TARGET_PROFILE" ]; then
    echo "❌ --target-profile is required (one of: higher-cost, moderate, lowest-cost, public-nodes)"
    exit 1
fi

case "$TARGET_PROFILE" in
    higher-cost|moderate|lowest-cost|public-nodes) ;;
    *)
        echo "❌ Invalid --target-profile '$TARGET_PROFILE'."
        echo "   Expected one of: higher-cost, moderate, lowest-cost, public-nodes"
        exit 1
        ;;
esac

GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
RED=$'\033[0;31m'
BLUE=$'\033[0;34m'
NC=$'\033[0m'

# ── Prereqs ─────────────────────────────────────────────────────────────
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --profile "$AWS_PROFILE" \
    --query 'Account' --output text 2>/dev/null || true)
if [ -z "$AWS_ACCOUNT_ID" ]; then
    echo "❌ Failed to get credentials from profile '$AWS_PROFILE'. Run aws-login first."
    exit 1
fi

if ! aws eks describe-cluster --name "$CLUSTER_NAME" --region "$REGION" --profile "$AWS_PROFILE" \
    >/dev/null 2>&1; then
    echo "❌ EKS cluster '$CLUSTER_NAME' not found in region $REGION (profile $AWS_PROFILE)."
    echo "   This script is for in-place migration of an existing cluster."
    echo "   For fresh deployments use ./create-hardened-eks-cluster.sh."
    exit 1
fi

# ── Discover current state ──────────────────────────────────────────────
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║          Network Profile Migration                             ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "Cluster:        $CLUSTER_NAME"
echo "Region:         $REGION"
echo "AWS account:    $AWS_ACCOUNT_ID"
echo "Target profile: $TARGET_PROFILE"
echo ""

VPC_ID=$(aws eks describe-cluster --name "$CLUSTER_NAME" --region "$REGION" --profile "$AWS_PROFILE" \
    --query 'cluster.resourcesVpcConfig.vpcId' --output text)
VPC_CIDR=$(aws ec2 describe-vpcs --vpc-ids "$VPC_ID" --region "$REGION" --profile "$AWS_PROFILE" \
    --query 'Vpcs[0].CidrBlock' --output text)
CURRENT_PROFILE=$(aws ec2 describe-vpcs --vpc-ids "$VPC_ID" --region "$REGION" --profile "$AWS_PROFILE" \
    --query 'Vpcs[0].Tags[?Key==`nexus:network-profile`]|[0].Value' --output text 2>/dev/null)
[ "$CURRENT_PROFILE" == "None" ] && CURRENT_PROFILE=""
echo "VPC:            $VPC_ID ($VPC_CIDR)"
echo "Current tag:    ${CURRENT_PROFILE:-<unset — assuming higher-cost>}"

# Existing NAT instances (managed by us — tagged nexus:nat-instance=true)
EXISTING_NAT_COUNT=$(aws ec2 describe-instances --region "$REGION" --profile "$AWS_PROFILE" \
    --filters "Name=vpc-id,Values=$VPC_ID" \
              "Name=tag:nexus:nat-instance,Values=true" \
              "Name=instance-state-name,Values=pending,running" \
    --query 'length(Reservations[].Instances[])' --output text 2>/dev/null || echo "0")

# Existing interface endpoints (signal that we're on higher-cost today)
INTERFACE_EP_COUNT=$(aws ec2 describe-vpc-endpoints --region "$REGION" --profile "$AWS_PROFILE" \
    --filters "Name=vpc-id,Values=$VPC_ID" "Name=vpc-endpoint-type,Values=Interface" \
    --query 'length(VpcEndpoints[])' --output text 2>/dev/null || echo "0")

echo "Existing NATs:  $EXISTING_NAT_COUNT"
echo "Interface eps:  $INTERFACE_EP_COUNT"
echo ""

# ── Determine direction ─────────────────────────────────────────────────
EFFECTIVE_CURRENT="${CURRENT_PROFILE:-higher-cost}"

if [ "$EFFECTIVE_CURRENT" == "$TARGET_PROFILE" ]; then
    echo "Current profile already matches target. Will only re-stamp the VPC tag."
    echo "Re-run the kubectl steps at the end of this script if the operator CR is stale."
fi

NEEDED_NATS=0
case "$TARGET_PROFILE" in
    higher-cost|public-nodes) NEEDED_NATS=0 ;;
    lowest-cost)              NEEDED_NATS=1 ;;
    moderate)                 NEEDED_NATS=2 ;;
esac

# ── Print plan ──────────────────────────────────────────────────────────
echo "── Plan ────────────────────────────────────────────────────────────"
echo "  Direction:  ${EFFECTIVE_CURRENT} → ${TARGET_PROFILE}"
echo "  NAT target: $NEEDED_NATS instance(s)"
if [ "$NEEDED_NATS" -gt "$EXISTING_NAT_COUNT" ]; then
    echo "  Action:     PROVISION $((NEEDED_NATS - EXISTING_NAT_COUNT)) new NAT instance(s)"
elif [ "$NEEDED_NATS" -lt "$EXISTING_NAT_COUNT" ]; then
    echo "  Action:     TEAR DOWN $((EXISTING_NAT_COUNT - NEEDED_NATS)) NAT instance(s) + route(s)"
else
    echo "  Action:     No NAT changes needed (re-stamp VPC tag only)"
fi
echo ""
if [ "$TARGET_PROFILE" == "public-nodes" ] && [ "$EFFECTIVE_CURRENT" != "public-nodes" ]; then
    echo -e "${YELLOW}⚠  public-nodes requires worker subnets with MapPublicIpOnLaunch=true.${NC}"
    echo -e "${YELLOW}   Live conversion is not safe on a private-subnet cluster — rebuild${NC}"
    echo -e "${YELLOW}   instead via ./create-hardened-eks-cluster.sh --network-profile public-nodes.${NC}"
    exit 1
fi
echo "Interface VPC endpoints are NOT touched by this script. To realize cost"
echo "savings on hybrid profiles, delete them MANUALLY after Phase D verification"
echo "(see deploy/eks/README.md)."
echo ""

if [ "$DRY_RUN" == "yes" ]; then
    echo "${BLUE}DRY-RUN: stopping before any AWS changes.${NC}"
    exit 0
fi

if [ "$AUTO_APPROVE" != "yes" ]; then
    read -p "Proceed with migration? (yes/no): " CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        echo "Aborted."
        exit 1
    fi
fi
echo ""

# ════════════════════════════════════════════════════════════════════════
# Provisioning helpers (kept in sync with create-hardened-eks-cluster.sh)
# ════════════════════════════════════════════════════════════════════════

ensure_nat_sg() {
    local sg_name="${CLUSTER_NAME}-nat-sg"
    NAT_SG=$(aws ec2 describe-security-groups \
        --filters "Name=group-name,Values=$sg_name" "Name=vpc-id,Values=$VPC_ID" \
        --region "$REGION" --profile "$AWS_PROFILE" \
        --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)
    if [ -z "$NAT_SG" ] || [ "$NAT_SG" == "None" ]; then
        NAT_SG=$(aws ec2 create-security-group \
            --group-name "$sg_name" \
            --description "NAT instance traffic (fck-nat) - managed by deploy/eks scripts" \
            --vpc-id "$VPC_ID" \
            --region "$REGION" --profile "$AWS_PROFILE" \
            --query 'GroupId' --output text)
        aws ec2 create-tags --resources "$NAT_SG" \
            --tags "Key=Name,Value=$sg_name" "Key=nexus:network-profile,Value=$TARGET_PROFILE" \
            --region "$REGION" --profile "$AWS_PROFILE" >/dev/null 2>&1 || true
        aws ec2 authorize-security-group-ingress --group-id "$NAT_SG" \
            --protocol -1 --cidr "$VPC_CIDR" \
            --region "$REGION" --profile "$AWS_PROFILE" >/dev/null 2>&1 || true
        echo "  NAT SG: $NAT_SG (ingress all from $VPC_CIDR)"
    else
        echo "  NAT SG: $NAT_SG (existing, reused)"
    fi
}

lookup_nat_ami() {
    NAT_AMI=$(aws ec2 describe-images \
        --owners "$NAT_AMI_OWNER" \
        --filters "Name=name,Values=$NAT_AMI_NAME_FILTER" "Name=architecture,Values=$NAT_AMI_ARCH" \
        --region "$REGION" --profile "$AWS_PROFILE" \
        --query 'Images|sort_by(@,&CreationDate)|[-1].ImageId' --output text 2>/dev/null)
    if [ -z "$NAT_AMI" ] || [ "$NAT_AMI" == "None" ]; then
        echo -e "${RED}❌ fck-nat AMI not found in $REGION (owner=$NAT_AMI_OWNER, filter=$NAT_AMI_NAME_FILTER, arch=$NAT_AMI_ARCH).${NC}"
        echo "   See https://fck-nat.dev/ for region availability."
        exit 1
    fi
    echo "  fck-nat AMI: $NAT_AMI ($NAT_AMI_ARCH, for $NAT_INSTANCE_TYPE)"
}

create_nat_asg() {
    # Usage: create_nat_asg <public_subnet_id> <priv_rt_id> <suffix>
    local pub_subnet="$1"
    local priv_rt="$2"
    local suffix="$3"

    local asg_name="${CLUSTER_NAME}-nat-${suffix}"
    local lt_name="${CLUSTER_NAME}-nat-lt-${suffix}"

    # Launch template (idempotent)
    if aws ec2 describe-launch-templates --launch-template-names "$lt_name" \
        --region "$REGION" --profile "$AWS_PROFILE" >/dev/null 2>&1; then
        echo "  Launch template $lt_name (existing, reused)"
    else
        local lt_data
        lt_data=$(cat <<EOF
{"ImageId":"$NAT_AMI","InstanceType":"$NAT_INSTANCE_TYPE","SecurityGroupIds":["$NAT_SG"],"TagSpecifications":[{"ResourceType":"instance","Tags":[{"Key":"Name","Value":"${CLUSTER_NAME}-nat-${suffix}"},{"Key":"nexus:nat-instance","Value":"true"},{"Key":"nexus:network-profile","Value":"$TARGET_PROFILE"}]}]}
EOF
)
        aws ec2 create-launch-template \
            --launch-template-name "$lt_name" \
            --launch-template-data "$lt_data" \
            --region "$REGION" --profile "$AWS_PROFILE" >/dev/null
        echo "  Launch template: $lt_name"
    fi

    # ASG (idempotent)
    if aws autoscaling describe-auto-scaling-groups \
        --auto-scaling-group-names "$asg_name" \
        --region "$REGION" --profile "$AWS_PROFILE" \
        --query 'AutoScalingGroups[0].AutoScalingGroupName' --output text 2>/dev/null | grep -q "$asg_name"; then
        echo "  ASG $asg_name (existing, reused)"
    else
        aws autoscaling create-auto-scaling-group \
            --auto-scaling-group-name "$asg_name" \
            --launch-template "LaunchTemplateName=$lt_name,Version=\$Latest" \
            --min-size 1 --max-size 1 --desired-capacity 1 \
            --vpc-zone-identifier "$pub_subnet" \
            --tags "Key=Name,Value=$asg_name,PropagateAtLaunch=false" \
                   "Key=nexus:nat-instance,Value=true,PropagateAtLaunch=false" \
                   "Key=nexus:network-profile,Value=$TARGET_PROFILE,PropagateAtLaunch=false" \
            --region "$REGION" --profile "$AWS_PROFILE" >/dev/null
        echo "  ASG: $asg_name (min=max=1, in $pub_subnet)"
    fi

    # Wait for instance and ENI. Bail out early if the ASG reports a Failed
    # scaling activity (quota exceeded, capacity unavailable, etc.) — the
    # original 5-min polling loop would otherwise hang silently.
    echo -n "  Waiting for NAT instance to come up"
    local nat_instance="" nat_eni="" state=""
    for attempt in $(seq 1 60); do
        nat_instance=$(aws ec2 describe-instances \
            --filters "Name=tag:aws:autoscaling:groupName,Values=$asg_name" \
                      "Name=instance-state-name,Values=pending,running" \
            --region "$REGION" --profile "$AWS_PROFILE" \
            --query 'Reservations[0].Instances[0].InstanceId' --output text 2>/dev/null || true)
        if [ -n "$nat_instance" ] && [ "$nat_instance" != "None" ]; then
            state=$(aws ec2 describe-instances --instance-ids "$nat_instance" \
                --region "$REGION" --profile "$AWS_PROFILE" \
                --query 'Reservations[0].Instances[0].State.Name' --output text 2>/dev/null || true)
            if [ "$state" == "running" ]; then
                nat_eni=$(aws ec2 describe-instances --instance-ids "$nat_instance" \
                    --region "$REGION" --profile "$AWS_PROFILE" \
                    --query 'Reservations[0].Instances[0].NetworkInterfaces[0].NetworkInterfaceId' --output text 2>/dev/null)
                break
            fi
        fi
        # Every ~30s, check the ASG's last scaling activity. A "Failed" status
        # with a Status Reason is almost always permanent (quota, AMI perms,
        # subnet capacity, security group invalid). Surface it instead of
        # waiting out the full timeout.
        if [ $((attempt % 6)) -eq 0 ]; then
            local last_act
            last_act=$(aws autoscaling describe-scaling-activities \
                --auto-scaling-group-name "$asg_name" \
                --region "$REGION" --profile "$AWS_PROFILE" \
                --max-items 1 \
                --query 'Activities[0].{Code:StatusCode,Reason:StatusMessage}' \
                --output json 2>/dev/null || echo "{}")
            if echo "$last_act" | grep -q '"Code": "Failed"'; then
                echo ""
                local reason
                reason=$(echo "$last_act" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("Reason","unknown"))' 2>/dev/null || echo "unknown")
                echo -e "${RED}  ❌ ASG $asg_name cannot launch instances. Reason:${NC}"
                echo "     $reason"
                echo ""
                echo "  Common causes:"
                echo "    - EC2 vCPU quota exhausted: aws service-quotas get-service-quota --service-code ec2 --quota-code L-1216C47A --region $REGION --profile $AWS_PROFILE"
                echo "    - Subnet has no free IPs"
                echo "    - Launch template references a missing AMI / SG"
                echo ""
                echo "  Roll back what was created so far:"
                echo "    ./migrate-network-profile.sh --name $CLUSTER_NAME --target-profile higher-cost --auto-approve"
                exit 1
            fi
        fi
        echo -n "."; sleep 5
    done
    echo ""
    if [ -z "$nat_eni" ] || [ "$nat_eni" == "None" ]; then
        echo -e "${RED}  ❌ NAT instance for $asg_name not running after 5 min.${NC}"
        exit 1
    fi

    aws ec2 modify-instance-attribute --instance-id "$nat_instance" \
        --no-source-dest-check \
        --region "$REGION" --profile "$AWS_PROFILE" >/dev/null 2>&1 || true
    aws ec2 create-tags --resources "$nat_eni" \
        --tags "Key=nexus:nat-instance,Value=true" "Key=nexus:network-profile,Value=$TARGET_PROFILE" \
        --region "$REGION" --profile "$AWS_PROFILE" >/dev/null 2>&1 || true

    # Default route — replace if it points elsewhere, add if missing.
    aws ec2 delete-route --route-table-id "$priv_rt" --destination-cidr-block 0.0.0.0/0 \
        --region "$REGION" --profile "$AWS_PROFILE" >/dev/null 2>&1 || true
    aws ec2 create-route --route-table-id "$priv_rt" --destination-cidr-block 0.0.0.0/0 \
        --network-interface-id "$nat_eni" \
        --region "$REGION" --profile "$AWS_PROFILE" >/dev/null
    echo -e "  ${GREEN}✓ Route 0.0.0.0/0 → $nat_eni on $priv_rt${NC}"
}

teardown_nat_asgs() {
    echo "── Tearing down existing NAT instances ──"
    for suffix in az1 az2 single; do
        local asg_name="${CLUSTER_NAME}-nat-${suffix}"
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
            echo -e "  ${GREEN}✓ ASG $asg_name deleted${NC}"
        fi
        local lt_name="${CLUSTER_NAME}-nat-lt-${suffix}"
        if aws ec2 describe-launch-templates --launch-template-names "$lt_name" \
            --region "$REGION" --profile "$AWS_PROFILE" >/dev/null 2>&1; then
            aws ec2 delete-launch-template --launch-template-name "$lt_name" \
                --region "$REGION" --profile "$AWS_PROFILE" >/dev/null 2>&1 || true
            echo -e "  ${GREEN}✓ Launch template $lt_name deleted${NC}"
        fi
    done

    # Terminate any straggler NAT instances tagged by us.
    local stragglers
    stragglers=$(aws ec2 describe-instances \
        --filters "Name=tag:nexus:nat-instance,Values=true" "Name=vpc-id,Values=$VPC_ID" \
                  "Name=instance-state-name,Values=pending,running,stopping,stopped" \
        --region "$REGION" --profile "$AWS_PROFILE" \
        --query 'Reservations[].Instances[].InstanceId' --output text 2>/dev/null || true)
    if [ -n "$stragglers" ]; then
        aws ec2 terminate-instances --instance-ids $stragglers \
            --region "$REGION" --profile "$AWS_PROFILE" >/dev/null 2>&1 || true
        echo -e "  ${GREEN}✓ Terminated straggler NAT instances: $stragglers${NC}"
    fi

    # Remove any 0.0.0.0/0 routes from private RTs that point at NAT ENIs we
    # just deleted. Without this, the RT keeps a black-hole route and traffic
    # silently fails until manually fixed.
    local rts
    rts=$(aws ec2 describe-route-tables \
        --filters "Name=vpc-id,Values=$VPC_ID" \
                  "Name=tag:Name,Values=${CLUSTER_NAME}-private-rt*" \
        --region "$REGION" --profile "$AWS_PROFILE" \
        --query 'RouteTables[].RouteTableId' --output text 2>/dev/null)
    for rt in $rts; do
        if aws ec2 describe-route-tables --route-table-ids "$rt" \
            --region "$REGION" --profile "$AWS_PROFILE" \
            --query 'RouteTables[0].Routes[?DestinationCidrBlock==`0.0.0.0/0`]|[0].NetworkInterfaceId' \
            --output text 2>/dev/null | grep -q '^eni-'; then
            aws ec2 delete-route --route-table-id "$rt" \
                --destination-cidr-block 0.0.0.0/0 \
                --region "$REGION" --profile "$AWS_PROFILE" >/dev/null 2>&1 || true
            echo -e "  ${GREEN}✓ Removed 0.0.0.0/0 (NAT) route from $rt${NC}"
        fi
    done
}

# ════════════════════════════════════════════════════════════════════════
# Execute
# ════════════════════════════════════════════════════════════════════════

if [ "$NEEDED_NATS" -gt 0 ]; then
    echo "── Provisioning NAT instance(s) ──"
    ensure_nat_sg
    lookup_nat_ami

    # Resolve public subnets (NAT instances must live in a public subnet).
    PUB_SUBS_RESOLVED=$(aws ec2 describe-subnets --region "$REGION" --profile "$AWS_PROFILE" \
        --filters "Name=vpc-id,Values=$VPC_ID" "Name=map-public-ip-on-launch,Values=true" \
        --query 'Subnets[].SubnetId' --output text 2>/dev/null)
    PUB_SUB1=$(echo "$PUB_SUBS_RESOLVED" | awk '{print $1}')
    PUB_SUB2=$(echo "$PUB_SUBS_RESOLVED" | awk '{print $2}')
    if [ -z "$PUB_SUB1" ]; then
        echo -e "${RED}❌ No public subnets found in $VPC_ID. Cannot place a NAT instance.${NC}"
        echo "   This script expects the cluster was created by create-hardened-eks-cluster.sh."
        exit 1
    fi
    [ -z "$PUB_SUB2" ] && PUB_SUB2="$PUB_SUB1"

    # Resolve private RTs by Name tag (handles both single-RT clusters and
    # per-AZ-RT clusters from --network-profile moderate).
    PRIV_RT_AZ1=$(aws ec2 describe-route-tables --region "$REGION" --profile "$AWS_PROFILE" \
        --filters "Name=vpc-id,Values=$VPC_ID" \
                  "Name=tag:Name,Values=${CLUSTER_NAME}-private-rt-*" \
        --query 'RouteTables[0].RouteTableId' --output text 2>/dev/null)
    PRIV_RT_AZ2=$(aws ec2 describe-route-tables --region "$REGION" --profile "$AWS_PROFILE" \
        --filters "Name=vpc-id,Values=$VPC_ID" \
                  "Name=tag:Name,Values=${CLUSTER_NAME}-private-rt-*" \
        --query 'RouteTables[1].RouteTableId' --output text 2>/dev/null)
    SHARED_PRIV_RT=$(aws ec2 describe-route-tables --region "$REGION" --profile "$AWS_PROFILE" \
        --filters "Name=vpc-id,Values=$VPC_ID" \
                  "Name=tag:Name,Values=${CLUSTER_NAME}-private-rt" \
        --query 'RouteTables[0].RouteTableId' --output text 2>/dev/null)
    if [ -z "$PRIV_RT_AZ1" ] || [ "$PRIV_RT_AZ1" == "None" ]; then
        PRIV_RT_AZ1="$SHARED_PRIV_RT"
    fi
    if [ -z "$PRIV_RT_AZ2" ] || [ "$PRIV_RT_AZ2" == "None" ]; then
        PRIV_RT_AZ2="$SHARED_PRIV_RT"
    fi
    if [ -z "$PRIV_RT_AZ1" ] || [ "$PRIV_RT_AZ1" == "None" ]; then
        echo -e "${RED}❌ Could not resolve any private route table named ${CLUSTER_NAME}-private-rt*.${NC}"
        exit 1
    fi
    echo "  Private RTs: AZ1=$PRIV_RT_AZ1, AZ2=$PRIV_RT_AZ2"

    if [ "$TARGET_PROFILE" == "moderate" ] && [ "$PRIV_RT_AZ1" == "$PRIV_RT_AZ2" ]; then
        echo -e "${YELLOW}⚠  Cluster has a single shared private route table.${NC}"
        echo -e "${YELLOW}   Per-AZ NAT locality is not possible without splitting it.${NC}"
        echo -e "${YELLOW}   Both NAT instances will be created but only the second one will${NC}"
        echo -e "${YELLOW}   own the default route. For true per-AZ HA, rebuild the cluster${NC}"
        echo -e "${YELLOW}   via ./create-hardened-eks-cluster.sh --network-profile moderate.${NC}"
        echo ""
    fi

    if [ "$TARGET_PROFILE" == "moderate" ]; then
        create_nat_asg "$PUB_SUB1" "$PRIV_RT_AZ1" "az1"
        create_nat_asg "$PUB_SUB2" "$PRIV_RT_AZ2" "az2"
    else
        create_nat_asg "$PUB_SUB1" "$PRIV_RT_AZ1" "single"
    fi
fi

if [ "$NEEDED_NATS" -lt "$EXISTING_NAT_COUNT" ]; then
    teardown_nat_asgs
fi

# Restamp the VPC tag last — operator polls every 5 min and uses this to
# detect drift against spec.awsAccessMode.
aws ec2 create-tags --resources "$VPC_ID" \
    --tags "Key=nexus:network-profile,Value=$TARGET_PROFILE" \
    --region "$REGION" --profile "$AWS_PROFILE" >/dev/null
echo ""
echo -e "${GREEN}✓ VPC $VPC_ID re-tagged: nexus:network-profile=$TARGET_PROFILE${NC}"
echo ""

# ── Next-step instructions (printed, not executed) ──────────────────────
cat <<EOF
╔════════════════════════════════════════════════════════════════╗
║   ${GREEN}✓ Infrastructure migration complete${NC}                            ║
╚════════════════════════════════════════════════════════════════╝

Phase A is done. Next steps (run from a shell with kubectl context = $CLUSTER_NAME):

${BLUE}# 1. Smoke-test the NAT path before flipping the operator${NC}
kubectl run nat-probe --rm -it --image=amazonlinux:2023 --restart=Never -- bash -lc \\
    "curl -sS https://sts.${REGION}.amazonaws.com -o /dev/null -w 'STS: HTTP %{http_code}\\n' && \\
     curl -sS https://checkip.amazonaws.com -w 'Source IP: %{remote_ip}\\n'"

${BLUE}# 2. Flip the operator-watched CR${NC}
kubectl patch nexusnetworkconfig vpc-endpoints --type=merge \\
    -p '{"spec":{"awsAccessMode":"$TARGET_PROFILE"}}'

${BLUE}# 3. Force a capability reconcile so deploy_backend re-applies with new env vars${NC}
kubectl annotate nexuscapability nexus-ai-dev reconcile=\$(date +%s) --overwrite

${BLUE}# 4. Wait for the rolling restart${NC}
kubectl rollout status deploy/nexus-ai-dev-backend

${BLUE}# 5. Verify the projected env var matches${NC}
kubectl port-forward svc/nexus-ai-dev-backend 8000:8000 &
curl -s http://localhost:8000/api/v1/health/aws | jq .
kill %1

${BLUE}# 6. (Optional) Realize cost savings by deleting unused interface endpoints${NC}
# See deploy/eks/README.md "Network profiles & cost tiers" for the staged deletion.

EOF

if [ "$TARGET_PROFILE" == "higher-cost" ]; then
    cat <<EOF
${YELLOW}NOTE${NC}: To return to full PrivateLink you'll also need to re-create the
interface VPC endpoints. The fastest path is:

  ./create-hardened-eks-cluster.sh --vpc-id $VPC_ID --network-profile higher-cost \\
      --skip-addons --auto-approve

That command's VPC-endpoint creation loop is idempotent and will re-create any
missing endpoints without touching the cluster — but it WILL prompt to delete
the cluster if AUTO_APPROVE=yes is unset. Confirm carefully.

EOF
fi

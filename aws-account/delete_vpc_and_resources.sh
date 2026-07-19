#!/bin/bash
set -e

# =========================================================
# VPC FULL CLEANUP + DELETE SCRIPT
# Run this in AWS CloudShell (or anywhere with AWS CLI + creds)
# =========================================================
# USAGE:
#   chmod +x delete_vpc_and_resources.sh
#   ./delete_vpc_and_resources.sh vpc-027288988b1ac3149
#
# This will delete, in order:
#   1. NAT Gateways
#   2. Elastic IPs (released, not just disassociated)
#   3. VPC Endpoints
#   4. Load Balancers (ELB/ALB/NLB) in the VPC
#   5. RDS instances/subnet groups in the VPC (if any)
#   6. EC2 instances
#   7. Network Interfaces (ENIs) left dangling
#   8. Internet Gateway (detach + delete)
#   9. Non-default Security Groups
#  10. Subnets
#  11. Non-main Route Tables
#  12. Non-default Network ACLs
#  13. VPC Peering Connections
#  14. The VPC itself
#
# NOTE: This is DESTRUCTIVE. Double-check the VPC ID before running.
# =========================================================

VPC_ID=$1
REGION=${2:-$(aws configure get region)}

if [ -z "$VPC_ID" ]; then
  echo "Usage: $0 <vpc-id> [region]"
  exit 1
fi

echo "=================================================="
echo " Target VPC : $VPC_ID"
echo " Region     : $REGION"
echo "=================================================="
read -p "Type the VPC ID again to confirm deletion: " CONFIRM
if [ "$CONFIRM" != "$VPC_ID" ]; then
  echo "Confirmation failed. Aborting."
  exit 1
fi

AWS="aws --region $REGION"

echo ">>> [1/14] Deleting NAT Gateways..."
NAT_IDS=$($AWS ec2 describe-nat-gateways \
  --filter "Name=vpc-id,Values=$VPC_ID" "Name=state,Values=available,pending" \
  --query 'NatGateways[].NatGatewayId' --output text)
for NAT in $NAT_IDS; do
  echo "  Deleting NAT Gateway $NAT"
  $AWS ec2 delete-nat-gateway --nat-gateway-id $NAT
done
if [ -n "$NAT_IDS" ]; then
  echo "  Waiting for NAT Gateways to delete (this can take a few minutes)..."
  for NAT in $NAT_IDS; do
    while true; do
      STATE=$($AWS ec2 describe-nat-gateways --nat-gateway-ids $NAT \
        --query 'NatGateways[0].State' --output text 2>/dev/null || echo "deleted")
      if [ "$STATE" == "deleted" ]; then break; fi
      sleep 10
    done
  done
fi

echo ">>> [2/14] Releasing Elastic IPs in this VPC..."
EIP_ALLOC_IDS=$($AWS ec2 describe-addresses \
  --query "Addresses[?NetworkInterfaceId!=null] | [?contains(NetworkInterfaceId, '')].AllocationId" \
  --output text)
# Safer: match EIPs whose associated ENI belongs to this VPC
for ALLOC in $($AWS ec2 describe-addresses --query 'Addresses[].AllocationId' --output text); do
  ENI=$($AWS ec2 describe-addresses --allocation-ids $ALLOC --query 'Addresses[0].NetworkInterfaceId' --output text)
  if [ "$ENI" != "None" ] && [ -n "$ENI" ]; then
    ENI_VPC=$($AWS ec2 describe-network-interfaces --network-interface-ids $ENI \
      --query 'NetworkInterfaces[0].VpcId' --output text 2>/dev/null || echo "")
    if [ "$ENI_VPC" == "$VPC_ID" ]; then
      echo "  Releasing EIP allocation $ALLOC"
      $AWS ec2 release-address --allocation-id $ALLOC || true
    fi
  fi
done

echo ">>> [3/14] Deleting VPC Endpoints..."
EP_IDS=$($AWS ec2 describe-vpc-endpoints \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'VpcEndpoints[].VpcEndpointId' --output text)
if [ -n "$EP_IDS" ]; then
  $AWS ec2 delete-vpc-endpoints --vpc-endpoint-ids $EP_IDS
fi

echo ">>> [4/14] Deleting Load Balancers (ELBv2: ALB/NLB)..."
LB_ARNS=$($AWS elbv2 describe-load-balancers \
  --query "LoadBalancers[?VpcId=='$VPC_ID'].LoadBalancerArn" --output text)
for LB in $LB_ARNS; do
  echo "  Deleting Load Balancer $LB"
  $AWS elbv2 delete-load-balancer --load-balancer-arn $LB
done

echo ">>> [4b/14] Deleting Classic ELBs..."
CLB_NAMES=$($AWS elb describe-load-balancers \
  --query "LoadBalancerDescriptions[?VPCId=='$VPC_ID'].LoadBalancerName" --output text)
for CLB in $CLB_NAMES; do
  echo "  Deleting Classic ELB $CLB"
  $AWS elb delete-load-balancer --load-balancer-name $CLB
done

echo ">>> [5/14] Checking for RDS instances in this VPC (manual review recommended)..."
$AWS rds describe-db-instances \
  --query "DBInstances[?DBSubnetGroup.VpcId=='$VPC_ID'].DBInstanceIdentifier" --output text | \
  tr '\t' '\n' | while read -r DBID; do
    if [ -n "$DBID" ]; then
      echo "  !! Found RDS instance: $DBID -- NOT auto-deleting (has final snapshot implications)."
      echo "     Delete manually: aws rds delete-db-instance --db-instance-identifier $DBID --skip-final-snapshot"
    fi
  done

echo ">>> [6/14] Terminating EC2 instances..."
INSTANCE_IDS=$($AWS ec2 describe-instances \
  --filters "Name=vpc-id,Values=$VPC_ID" "Name=instance-state-name,Values=running,stopped,stopping,pending" \
  --query 'Reservations[].Instances[].InstanceId' --output text)
if [ -n "$INSTANCE_IDS" ]; then
  $AWS ec2 terminate-instances --instance-ids $INSTANCE_IDS
  echo "  Waiting for instances to terminate..."
  $AWS ec2 wait instance-terminated --instance-ids $INSTANCE_IDS
fi

echo ">>> [7/14] Deleting leftover Network Interfaces..."
ENI_IDS=$($AWS ec2 describe-network-interfaces \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'NetworkInterfaces[].NetworkInterfaceId' --output text)
for ENI in $ENI_IDS; do
  echo "  Deleting ENI $ENI"
  $AWS ec2 delete-network-interface --network-interface-id $ENI || true
done

echo ">>> [8/14] Detaching and deleting Internet Gateway..."
IGW_ID=$($AWS ec2 describe-internet-gateways \
  --filters "Name=attachment.vpc-id,Values=$VPC_ID" \
  --query 'InternetGateways[0].InternetGatewayId' --output text)
if [ "$IGW_ID" != "None" ] && [ -n "$IGW_ID" ]; then
  echo "  Detaching IGW $IGW_ID"
  $AWS ec2 detach-internet-gateway --internet-gateway-id $IGW_ID --vpc-id $VPC_ID
  echo "  Deleting IGW $IGW_ID"
  $AWS ec2 delete-internet-gateway --internet-gateway-id $IGW_ID
fi

echo ">>> [9/14] Deleting non-default Security Groups..."
SG_IDS=$($AWS ec2 describe-security-groups \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query "SecurityGroups[?GroupName!='default'].GroupId" --output text)
for SG in $SG_IDS; do
  echo "  Deleting Security Group $SG"
  $AWS ec2 delete-security-group --group-id $SG || echo "    (still referenced, skipping for now)"
done

echo ">>> [10/14] Deleting Subnets..."
SUBNET_IDS=$($AWS ec2 describe-subnets \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'Subnets[].SubnetId' --output text)
for SUBNET in $SUBNET_IDS; do
  echo "  Deleting Subnet $SUBNET"
  $AWS ec2 delete-subnet --subnet-id $SUBNET
done

echo ">>> [11/14] Deleting non-main Route Tables..."
RTB_IDS=$($AWS ec2 describe-route-tables \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query "RouteTables[?Associations[?Main!=\`true\`] || Associations==\`[]\`].RouteTableId" --output text)
for RTB in $RTB_IDS; do
  echo "  Deleting Route Table $RTB"
  $AWS ec2 delete-route-table --route-table-id $RTB || echo "    (skip - might be main table)"
done

echo ">>> [12/14] Deleting non-default Network ACLs..."
NACL_IDS=$($AWS ec2 describe-network-acls \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query "NetworkAcls[?IsDefault==\`false\`].NetworkAclId" --output text)
for NACL in $NACL_IDS; do
  echo "  Deleting NACL $NACL"
  $AWS ec2 delete-network-acl --network-acl-id $NACL
done

echo ">>> [13/14] Deleting VPC Peering Connections..."
PCX_IDS=$($AWS ec2 describe-vpc-peering-connections \
  --filters "Name=requester-vpc-info.vpc-id,Values=$VPC_ID" \
  --query 'VpcPeeringConnections[].VpcPeeringConnectionId' --output text)
for PCX in $PCX_IDS; do
  echo "  Deleting Peering Connection $PCX"
  $AWS ec2 delete-vpc-peering-connection --vpc-peering-connection-id $PCX
done

echo ">>> [14/14] Deleting the VPC itself..."
$AWS ec2 delete-vpc --vpc-id $VPC_ID

echo "=================================================="
echo " DONE. VPC $VPC_ID and its resources are deleted."
echo "=================================================="
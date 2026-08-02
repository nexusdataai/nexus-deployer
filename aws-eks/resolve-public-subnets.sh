#!/bin/bash
#
# Network discovery helpers for existing / shared VPCs.
# Expects: VPC_ID, REGION, AWS_PROFILE, AWS_ACCOUNT_ID (for ownership checks)
# Optional inputs: PUB_SUB1, PUB_SUB2, PUBLIC_SUBNETS, PRIVATE_SUBNETS, SUBNETS
# Sets: PUB_SUB1, PUB_SUB2 (via resolve_public_subnets)

_pick_subnets_across_azs() {
    local candidates="$1"
    local preferred_azs="$2"
    local picked=()
    local azs=()
    local sid az

    for sid in $candidates; do
        [ -z "$sid" ] && continue
        az=$(aws ec2 describe-subnets --subnet-ids "$sid" \
            --region "$REGION" --profile "$AWS_PROFILE" \
            --query 'Subnets[0].AvailabilityZone' --output text 2>/dev/null)
        [ -z "$az" ] || [ "$az" == "None" ] && continue
        if [ -n "$preferred_azs" ] && ! echo " $preferred_azs " | grep -q " $az "; then
            continue
        fi
        local az_known=false
        for a in "${azs[@]}"; do [ "$a" == "$az" ] && az_known=true; done
        if [ ${#azs[@]} -ge 2 ] && [ "$az_known" == "false" ]; then
            continue
        fi
        if [ "$az_known" == "false" ]; then
            azs+=("$az")
        fi
        picked+=("$sid")
    done

    if [ ${#picked[@]} -eq 0 ] && [ -n "$preferred_azs" ]; then
        _pick_subnets_across_azs "$candidates" ""
        return
    fi

    PUB_SUB1="${picked[0]:-}"
    PUB_SUB2="${picked[1]:-$PUB_SUB1}"
}

_target_azs_from_subnets() {
    local subnet_list="$1"
    local azs=""
    local sid az

    subnet_list=${subnet_list//,/ }
    for sid in $subnet_list; do
        [ -z "$sid" ] && continue
        az=$(aws ec2 describe-subnets --subnet-ids "$sid" \
            --region "$REGION" --profile "$AWS_PROFILE" \
            --query 'Subnets[0].AvailabilityZone' --output text 2>/dev/null)
        [ -n "$az" ] && [ "$az" != "None" ] && azs="$azs $az"
    done
    echo "$azs" | tr ' ' '\n' | sort -u | tr '\n' ' '
}

_filter_existing_subnets() {
    local candidates="$1"
    local existing=""
    local sid

    for sid in $candidates; do
        [ -z "$sid" ] && continue
        if aws ec2 describe-subnets --subnet-ids "$sid" \
            --region "$REGION" --profile "$AWS_PROFILE" \
            --query 'Subnets[0].SubnetId' --output text 2>/dev/null | grep -q '^subnet-'; then
            existing="$existing $sid"
        fi
    done
    echo "$existing"
}

route_table_for_subnet() {
    local subnet_id="$1"
    aws ec2 describe-route-tables \
        --filters "Name=association.subnet-id,Values=$subnet_id" \
        --region "$REGION" --profile "$AWS_PROFILE" \
        --query 'RouteTables[0].RouteTableId' --output text 2>/dev/null
}

route_table_owner() {
    local rt_id="$1"
    aws ec2 describe-route-tables --route-table-ids "$rt_id" \
        --region "$REGION" --profile "$AWS_PROFILE" \
        --query 'RouteTables[0].OwnerId' --output text 2>/dev/null
}

resolve_private_subnets() {
    local candidates=""

    if [ -n "$PRIVATE_SUBNETS" ]; then
        echo "$PRIVATE_SUBNETS"
        return 0
    fi

    candidates=$(aws ec2 describe-subnets \
        --filters "Name=vpc-id,Values=$VPC_ID" \
        --region "$REGION" --profile "$AWS_PROFILE" \
        --output json 2>/dev/null \
        | jq -r '
            def is_public:
                .MapPublicIpOnLaunch == true
                or ((.Tags // []) | any(.Key == "Name" and (.Value | test("public"; "i"))));
            .Subnets[]
            | select(
                ((.Tags // []) | any(.Key == "Name" and (.Value | test("private"; "i"))))
                or (.MapPublicIpOnLaunch == false and (is_public | not))
              )
            | .SubnetId
          ' | sort -u | tr '\n' ' ')

    if [ -z "$candidates" ]; then
        return 1
    fi

    echo "$candidates" | tr ' ' '\n' | sort -u | paste -sd, -
    return 0
}

validate_eks_subnets() {
    local subnet_list="$1"
    local azs az_count

    if [ -z "$subnet_list" ]; then
        echo "❌ No subnets resolved for EKS. Pass --subnets or --private-subnets."
        return 1
    fi

    azs=$(_target_azs_from_subnets "$subnet_list")
    az_count=$(echo "$azs" | wc -w)
    if [ "$az_count" -lt 2 ]; then
        echo "❌ EKS requires subnets in at least 2 AZs; found ${az_count}: ${azs:-none}"
        echo "   Subnets: $subnet_list"
        echo "   This VPC exposes only one AZ to your account."
        echo "   Pass --subnets spanning 2+ AZs, or omit --vpc-id to create a dedicated VPC."
        return 1
    fi
    return 0
}

resolve_public_subnets() {
    if [ -n "$PUB_SUB1" ]; then
        [ -z "$PUB_SUB2" ] && PUB_SUB2="$PUB_SUB1"
        return 0
    fi

    if [ -n "$PUBLIC_SUBNETS" ]; then
        PUB_SUB1=$(echo "$PUBLIC_SUBNETS" | cut -d',' -f1 | tr -d ' ')
        PUB_SUB2=$(echo "$PUBLIC_SUBNETS" | cut -d',' -f2 | tr -d ' ')
        [ -z "$PUB_SUB2" ] && PUB_SUB2="$PUB_SUB1"
        if [ -n "$PUB_SUB1" ]; then
            echo "   Public subnets (from --public-subnets): $PUB_SUB1, $PUB_SUB2"
            return 0
        fi
    fi

    local candidates="" source="" preferred_azs=""
    preferred_azs=$(_target_azs_from_subnets "${PRIVATE_SUBNETS:-$SUBNETS}")

    candidates=$(aws ec2 describe-subnets \
        --filters "Name=vpc-id,Values=$VPC_ID" "Name=map-public-ip-on-launch,Values=true" \
        --region "$REGION" --profile "$AWS_PROFILE" \
        --query 'Subnets | sort_by(@, &AvailabilityZone)[].SubnetId' --output text 2>/dev/null)
    if [ -n "$candidates" ] && [ "$candidates" != "None" ]; then
        source="map-public-ip-on-launch"
    else
        candidates=$(aws ec2 describe-subnets \
            --filters "Name=vpc-id,Values=$VPC_ID" \
            --region "$REGION" --profile "$AWS_PROFILE" \
            --output json 2>/dev/null \
            | jq -r '.Subnets[] | select((.Tags // []) | any(.Key == "Name" and (.Value | test("public"; "i")))) | .SubnetId' \
            | sort -u | tr '\n' ' ')
        if [ -n "$candidates" ]; then
            source="Name tag"
        else
            candidates=$(aws ec2 describe-route-tables \
                --filters "Name=vpc-id,Values=$VPC_ID" \
                --region "$REGION" --profile "$AWS_PROFILE" \
                --output json 2>/dev/null \
                | jq -r '
                    .RouteTables[]
                    | select(any(.Routes[]?; .DestinationCidrBlock == "0.0.0.0/0" and ((.GatewayId // "") | startswith("igw-"))))
                    | .Associations[]? | select(.SubnetId != null) | .SubnetId
                  ' | sort -u | tr '\n' ' ')
            candidates=$(_filter_existing_subnets "$candidates")
            [ -n "$candidates" ] && source="IGW route table"
        fi
    fi

    if [ -z "$candidates" ]; then
        return 1
    fi

    _pick_subnets_across_azs "$candidates" "$preferred_azs"
    if [ -z "$PUB_SUB1" ]; then
        return 1
    fi
    echo "   Public subnets (via $source): $PUB_SUB1${PUB_SUB2:+, $PUB_SUB2}"
    return 0
}

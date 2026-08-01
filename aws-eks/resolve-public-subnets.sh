#!/bin/bash
#
# Discover public subnets in an existing VPC for NAT instance placement.
# Expects: VPC_ID, REGION, AWS_PROFILE
# Optional inputs: PUB_SUB1, PUB_SUB2, PUBLIC_SUBNETS, SUBNETS, PRIVATE_SUBNETS
# Sets: PUB_SUB1, PUB_SUB2

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

    # If AZ filtering left us with nothing, retry without the filter.
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

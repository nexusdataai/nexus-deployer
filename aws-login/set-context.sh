#!/bin/bash
#
# Unified AWS + EKS context selector.
#
# Picks a numbered environment (AWS account + cluster) from environments.conf,
# logs into AWS, writes kubeconfig locally, and exports context for kubectl/AWS CLI.
#
# Usage:
#   ./set-context.sh                  # interactive menu
#   ./set-context.sh 2                # select index 2
#   ./set-context.sh --list           # list environments
#   ./set-context.sh --status         # show active context
#   ./set-context.sh --export 2       # print export commands (for eval)
#   source ./set-context.sh 2         # select AND export in current shell
#
# After running (exec mode):
#   source .active-env
#
# kube-operator scripts auto-load .active-env via lib/init-kube-env.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORIGINAL_DIR="$(pwd)"
trap 'cd "$ORIGINAL_DIR"' EXIT

# shellcheck source=lib/kube-env.sh
. "${SCRIPT_DIR}/lib/kube-env.sh"

CONFIG_FILE="${ENVIRONMENTS_CONF:-${SCRIPT_DIR}/environments.conf}"
CONFIG_EXAMPLE="${SCRIPT_DIR}/environments.conf.example"
CACHE_FILE="${SCRIPT_DIR}/.last-env-index"
EXPORT_MODE=0
LIST_MODE=0
STATUS_MODE=0
ENV_INDEX=""
SOURCE_MODE=0

if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
    SOURCE_MODE=1
fi

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS] [INDEX]

Select AWS account + EKS cluster from environments.conf, login, set local kubeconfig.

Options:
  --list              List configured environments
  --status            Show active environment / KUBECONFIG
  --export [INDEX]    Print export statements (use: eval "\$(./set-context.sh --export 2)")
  --config FILE       Alternate environments.conf path
  --reset             Clear .last-env-index cache before prompting
  --help              Show this help

Environment variables:
  ENVIRONMENTS_CONF   Path to environments registry (default: ./environments.conf)

Registry format (environments.conf):
  index|label|aws_profile|role_index|role_arn|region|cluster|namespace|context_alias

Examples:
  ./set-context.sh                    # menu
  ./set-context.sh 2                  # Starhub BSSMagic Prod (example row)
  source ./set-context.sh 2           # select + export in current shell
  source .active-env                  # restore last selection in a new terminal
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --list)      LIST_MODE=1; shift ;;
        --status)    STATUS_MODE=1; shift ;;
        --export)    EXPORT_MODE=1; shift ;;
        --config)    CONFIG_FILE="$2"; shift 2 ;;
        --reset)
            rm -f "$CACHE_FILE"
            echo "Cleared .last-env-index"
            shift
            ;;
        --help|-h)   usage; exit 0 ;;
        -*)          echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
        *)
            if [[ "$1" =~ ^[0-9]+$ ]]; then
                ENV_INDEX="$1"
            else
                echo "Invalid index: $1" >&2
                exit 1
            fi
            shift
            ;;
    esac
done

nexus_kube_env_init "$SCRIPT_DIR"

if [[ "$STATUS_MODE" -eq 1 ]]; then
    nexus_kube_env_status
    if command -v aws >/dev/null 2>&1 && [[ -n "${AWS_PROFILE:-}" ]]; then
        echo "AWS account:    $(aws sts get-caller-identity --profile "$AWS_PROFILE" --query Account --output text 2>/dev/null || echo '?')"
    fi
    exit 0
fi

if [[ ! -f "$CONFIG_FILE" ]]; then
    if [[ "$LIST_MODE" -eq 1 && -f "$CONFIG_EXAMPLE" ]]; then
        CONFIG_FILE="$CONFIG_EXAMPLE"
    elif [[ -f "$CONFIG_EXAMPLE" ]]; then
        echo "No $CONFIG_FILE found."
        echo "Copy the example and edit cluster names:"
        echo "  cp environments.conf.example environments.conf"
        exit 1
    else
        echo "Missing environments config: $CONFIG_FILE" >&2
        exit 1
    fi
fi

# Parse registry into parallel arrays
declare -a REG_IDX=() REG_LABEL=() REG_PROFILE=() REG_ROLE_IDX=()
declare -a REG_ROLE_ARN=() REG_REGION=() REG_CLUSTER=() REG_NAMESPACE=() REG_CTX=()

while IFS='|' read -r idx label profile role_idx role_arn region cluster namespace ctx_alias; do
    [[ "$idx" =~ ^#.*$ || -z "${idx// /}" ]] && continue
    REG_IDX+=("$idx")
    REG_LABEL+=("$label")
    REG_PROFILE+=("$profile")
    REG_ROLE_IDX+=("$role_idx")
    REG_ROLE_ARN+=("$role_arn")
    REG_REGION+=("$region")
    REG_CLUSTER+=("$cluster")
    REG_NAMESPACE+=("$namespace")
    REG_CTX+=("$ctx_alias")
done < "$CONFIG_FILE"

if [[ ${#REG_IDX[@]} -eq 0 ]]; then
    echo "No environments defined in $CONFIG_FILE" >&2
    exit 1
fi

if [[ "$LIST_MODE" -eq 1 ]]; then
    echo "Configured environments ($CONFIG_FILE):"
    for i in "${!REG_IDX[@]}"; do
        printf "  %s) %s\n     profile=%s role_index=%s region=%s cluster=%s ns=%s ctx=%s\n" \
            "${REG_IDX[$i]}" "${REG_LABEL[$i]}" "${REG_PROFILE[$i]}" "${REG_ROLE_IDX[$i]}" \
            "${REG_REGION[$i]}" "${REG_CLUSTER[$i]}" "${REG_NAMESPACE[$i]}" "${REG_CTX[$i]}"
    done
    exit 0
fi

# Resolve selection
SELECTED_POS=""
if [[ -n "$ENV_INDEX" ]]; then
    for i in "${!REG_IDX[@]}"; do
        if [[ "${REG_IDX[$i]}" == "$ENV_INDEX" ]]; then
            SELECTED_POS="$i"
            break
        fi
    done
    if [[ -z "$SELECTED_POS" ]]; then
        echo "Index $ENV_INDEX not found in $CONFIG_FILE" >&2
        exit 1
    fi
else
    DEFAULT_IDX="${REG_IDX[0]}"
    if [[ -f "$CACHE_FILE" ]]; then
        DEFAULT_IDX="$(tr -d '[:space:]' < "$CACHE_FILE")"
    fi
    echo "Select environment:"
    for i in "${!REG_IDX[@]}"; do
        marker="  "
        [[ "${REG_IDX[$i]}" == "$DEFAULT_IDX" ]] && marker="* "
        printf "  %s%s) %s — %s @ %s (ns: %s)\n" \
            "$marker" "${REG_IDX[$i]}" "${REG_LABEL[$i]}" "${REG_CLUSTER[$i]}" \
            "${REG_REGION[$i]}" "${REG_NAMESPACE[$i]}"
    done
    echo ""
    read -r -p "Choice [${DEFAULT_IDX}]: " CHOICE
    CHOICE="${CHOICE:-$DEFAULT_IDX}"
    for i in "${!REG_IDX[@]}"; do
        if [[ "${REG_IDX[$i]}" == "$CHOICE" ]]; then
            SELECTED_POS="$i"
            break
        fi
    done
    if [[ -z "$SELECTED_POS" ]]; then
        echo "Invalid choice: $CHOICE" >&2
        exit 1
    fi
fi

SEL_LABEL="${REG_LABEL[$SELECTED_POS]}"
SEL_PROFILE="${REG_PROFILE[$SELECTED_POS]}"
SEL_ROLE_IDX="${REG_ROLE_IDX[$SELECTED_POS]}"
SEL_ROLE_ARN="${REG_ROLE_ARN[$SELECTED_POS]}"
SEL_REGION="${REG_REGION[$SELECTED_POS]}"
SEL_CLUSTER="${REG_CLUSTER[$SELECTED_POS]}"
SEL_NAMESPACE="${REG_NAMESPACE[$SELECTED_POS]}"
SEL_CTX="${REG_CTX[$SELECTED_POS]}"
SEL_INDEX="${REG_IDX[$SELECTED_POS]}"

if [[ "$SEL_CLUSTER" == CHANGE_ME* ]]; then
    echo "Environment [$SEL_INDEX] still has placeholder cluster name — edit $CONFIG_FILE" >&2
    exit 1
fi

echo ""
echo "Selected: [$SEL_INDEX] $SEL_LABEL"
echo "  AWS profile:  $SEL_PROFILE"
echo "  Region:       $SEL_REGION"
echo "  Cluster:      $SEL_CLUSTER"
echo "  Namespace:    $SEL_NAMESPACE"
echo "  Context:      $SEL_CTX"
echo "  KUBECONFIG:   ${SCRIPT_DIR}/.kube/config"
echo ""

# Load ADFS credentials from .env.local
if [[ -f "${SCRIPT_DIR}/.env.local" ]]; then
    set -o allexport
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/.env.local"
    set +o allexport
fi

# AWS login
LOGIN_ARGS=(--profile "$SEL_PROFILE" --region "$SEL_REGION")
if [[ -n "$SEL_ROLE_ARN" ]]; then
    LOGIN_ARGS+=(--role-arn "$SEL_ROLE_ARN")
else
    LOGIN_ARGS+=(--default-role "$SEL_ROLE_IDX")
fi

echo "Logging into AWS..."
if ! "${SCRIPT_DIR}/aws-login.sh" "${LOGIN_ARGS[@]}"; then
    echo "AWS login failed" >&2
    exit 1
fi

export AWS_PROFILE="$SEL_PROFILE"
export AWS_REGION="$SEL_REGION"

# EKS kubeconfig (project-local)
echo ""
echo "Updating kubeconfig..."
nexus_kube_env_init "$SCRIPT_DIR"
if ! nexus_eks_update_kubeconfig "$SEL_CLUSTER" "$SEL_REGION" "$SEL_PROFILE" "$SEL_CTX"; then
    echo "aws eks update-kubeconfig failed" >&2
    exit 1
fi

nexus_kubectl_use_context "$SEL_CTX" "$SEL_NAMESPACE"

# Persist
nexus_write_active_env "$SCRIPT_DIR" "$SEL_INDEX" "$SEL_LABEL" "$SEL_PROFILE" \
    "$SEL_REGION" "$SEL_CLUSTER" "$SEL_NAMESPACE" "$SEL_CTX"
echo "$SEL_INDEX" > "$CACHE_FILE"

# Export for current shell if sourced
export AWS_PROFILE AWS_REGION KUBECONFIG
export NEXUS_ENV_INDEX="$SEL_INDEX"
export NEXUS_ENV_LABEL="$SEL_LABEL"
export NEXUS_EKS_CLUSTER="$SEL_CLUSTER"
export NEXUS_K8S_NAMESPACE="$SEL_NAMESPACE"
export NEXUS_K8S_CONTEXT="$SEL_CTX"
export CLUSTER_NAME="$SEL_CLUSTER"
export REGION="$SEL_REGION"

if [[ "$EXPORT_MODE" -eq 1 ]]; then
    cat "${SCRIPT_DIR}/.active-env"
    exit 0
fi

# Smoke checks
echo ""
echo "Smoke checks..."
if aws sts get-caller-identity --profile "$AWS_PROFILE" >/dev/null 2>&1; then
    ACCT=$(aws sts get-caller-identity --profile "$AWS_PROFILE" --query Account --output text)
    echo "  AWS account:       $ACCT"
else
    echo "  AWS account:       FAILED"
fi
echo "  current-context:   $(kubectl config current-context --kubeconfig="$KUBECONFIG")"
if kubectl get ns "$SEL_NAMESPACE" --kubeconfig="$KUBECONFIG" >/dev/null 2>&1; then
    echo "  namespace:         $SEL_NAMESPACE (reachable)"
else
    echo "  namespace:         $SEL_NAMESPACE (not reachable — check RBAC or create ns)"
fi

echo ""
echo "Context ready: [$SEL_INDEX] $SEL_LABEL"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ "$SOURCE_MODE" -eq 0 ]]; then
    echo "Export in this shell:"
    echo "  source ${SCRIPT_DIR}/.active-env"
    echo ""
    echo "kube-operator scripts pick this up automatically via lib/init-kube-env.sh"
fi
echo ""
echo "Next:"
echo "  kubectl get pods"
echo "  cd ../kube-operator && ./app-rollout.sh --env dev all"
echo ""

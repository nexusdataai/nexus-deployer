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
  Legacy (ADFS, 9 fields):
    index|label|aws_profile|role_index|role_arn|region|cluster|namespace|context_alias
  With auth type (10 fields):
    index|label|auth_type|aws_profile|role_index|role_arn|region|cluster|namespace|context_alias

  auth_type: adfs (default) | keys | local
    adfs  — federated login via aws-login.sh + ADFS (.env.local)
    keys  — long-term IAM access keys via aws-iam-login.sh (.env.iam.local)
            role_index and role_arn are ignored for keys entries
    local — localhost K3s cluster (no AWS login; refreshes project kubeconfig)
            aws_profile/role fields ignored; see ../local-k3s/create-local-k3s-cluster.sh

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
declare -a REG_IDX=() REG_LABEL=() REG_AUTH=() REG_PROFILE=() REG_ROLE_IDX=()
declare -a REG_ROLE_ARN=() REG_REGION=() REG_CLUSTER=() REG_NAMESPACE=() REG_CTX=()

_normalize_auth_type() {
    case "$1" in
        keys|key|iam)  echo "keys" ;;
        local|k3s)     echo "local" ;;
        adfs|"")       echo "adfs" ;;
        *)
            echo "Unknown auth_type '$1' (expected adfs, keys, or local)" >&2
            return 1
            ;;
    esac
}

_load_local_k3s_cluster_info() {
    local info_file="${SCRIPT_DIR}/../local-k3s/.cluster-info"
    if [[ ! -f "$info_file" ]]; then
        return 0
    fi
    # shellcheck disable=SC1090
    source "$info_file"
    if [[ -n "${CLUSTER_NAME:-}" ]]; then
        SEL_CLUSTER="$CLUSTER_NAME"
    fi
    if [[ -n "${CONTEXT:-}" ]]; then
        SEL_CTX="$CONTEXT"
    elif [[ -n "${CLUSTER_NAME:-}" ]]; then
        SEL_CTX="$CLUSTER_NAME"
    fi
}

while IFS='|' read -r f0 f1 f2 f3 f4 f5 f6 f7 f8 f9; do
    [[ "$f0" =~ ^#.*$ || -z "${f0// /}" ]] && continue

    # 10-field when field 3 is an auth type keyword; otherwise legacy 9-field (ADFS).
    if [[ "$f2" =~ ^(adfs|keys|key|iam|local|k3s)$ ]]; then
        idx="$f0"
        label="$f1"
        auth_type="$(_normalize_auth_type "$f2")" || exit 1
        profile="$f3"
        role_idx="$f4"
        role_arn="$f5"
        region="$f6"
        cluster="$f7"
        namespace="$f8"
        ctx_alias="$f9"
    else
        idx="$f0"
        label="$f1"
        auth_type="adfs"
        profile="$f2"
        role_idx="$f3"
        role_arn="$f4"
        region="$f5"
        cluster="$f6"
        namespace="$f7"
        ctx_alias="$f8"
    fi

    REG_IDX+=("$idx")
    REG_LABEL+=("$label")
    REG_AUTH+=("$auth_type")
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
        printf "  %s) %s\n     auth=%s profile=%s role_index=%s region=%s cluster=%s ns=%s ctx=%s\n" \
            "${REG_IDX[$i]}" "${REG_LABEL[$i]}" "${REG_AUTH[$i]}" "${REG_PROFILE[$i]}" \
            "${REG_ROLE_IDX[$i]}" "${REG_REGION[$i]}" "${REG_CLUSTER[$i]}" \
            "${REG_NAMESPACE[$i]}" "${REG_CTX[$i]}"
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
        if [[ "${REG_AUTH[$i]}" == "local" ]]; then
            printf "       (local K3s — no AWS login)\n"
        fi
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
SEL_AUTH="${REG_AUTH[$SELECTED_POS]}"
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

if [[ "$SEL_AUTH" == "local" ]]; then
    _load_local_k3s_cluster_info
fi

echo ""
echo "Selected: [$SEL_INDEX] $SEL_LABEL"
echo "  Auth type:    $SEL_AUTH"
if [[ "$SEL_AUTH" != "local" ]]; then
    echo "  AWS profile:  $SEL_PROFILE"
fi
echo "  Region:       $SEL_REGION"
echo "  Cluster:      $SEL_CLUSTER"
echo "  Namespace:    $SEL_NAMESPACE"
echo "  Context:      $SEL_CTX"
echo "  KUBECONFIG:   ${SCRIPT_DIR}/.kube/config"
echo ""

nexus_kube_env_init "$SCRIPT_DIR"

if [[ "$SEL_AUTH" == "local" ]]; then
    echo "Connecting to local K3s cluster..."
    if ! nexus_local_k3s_refresh_kubeconfig "$SEL_CLUSTER" "$SEL_CTX"; then
        exit 1
    fi
    nexus_kubectl_use_context "$SEL_CTX" "$SEL_NAMESPACE"

    nexus_write_active_env "$SCRIPT_DIR" "$SEL_INDEX" "$SEL_LABEL" "$SEL_PROFILE" \
        "$SEL_REGION" "$SEL_CLUSTER" "$SEL_NAMESPACE" "$SEL_CTX" "$SEL_AUTH"
    echo "$SEL_INDEX" > "$CACHE_FILE"

    export AWS_PROFILE="$SEL_PROFILE"
    export AWS_REGION="$SEL_REGION"
    export KUBECONFIG
    export NEXUS_ENV_INDEX="$SEL_INDEX"
    export NEXUS_ENV_LABEL="$SEL_LABEL"
    export NEXUS_AWS_AUTH_TYPE="$SEL_AUTH"
    export NEXUS_EKS_CLUSTER="$SEL_CLUSTER"
    export NEXUS_K8S_NAMESPACE="$SEL_NAMESPACE"
    export NEXUS_K8S_CONTEXT="$SEL_CTX"
    export NEXUS_LOCAL_K3S=1
    export CLUSTER_NAME="$SEL_CLUSTER"
    export REGION="$SEL_REGION"
    export AWS_ACCESS_KEY_ID=minioadmin
    export AWS_SECRET_ACCESS_KEY=minioadmin
    export AWS_DEFAULT_REGION="$SEL_REGION"

    if [[ "$EXPORT_MODE" -eq 1 ]]; then
        cat "${SCRIPT_DIR}/.active-env"
        exit 0
    fi

    echo ""
    echo "Smoke checks..."
    if kubectl cluster-info --kubeconfig="$KUBECONFIG" >/dev/null 2>&1; then
        echo "  cluster-info:      OK"
    else
        echo "  cluster-info:      FAILED"
    fi
    echo "  current-context:   $(kubectl config current-context --kubeconfig="$KUBECONFIG")"
    if kubectl get ns "$SEL_NAMESPACE" --kubeconfig="$KUBECONFIG" >/dev/null 2>&1; then
        echo "  namespace:         $SEL_NAMESPACE (reachable)"
    else
        echo "  namespace:         $SEL_NAMESPACE (not reachable — deploy local stack or create ns)"
    fi

    echo ""
    echo "Context ready: [$SEL_INDEX] $SEL_LABEL (local K3s)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if [[ "$SOURCE_MODE" -eq 0 ]]; then
        echo "Export in this shell:"
        echo "  source ${SCRIPT_DIR}/.active-env"
        echo ""
        echo "kube-operator scripts pick this up automatically via lib/init-kube-env.sh"
    fi
    echo ""
    echo "Next:"
    echo "  kubectl get pods -n ${SEL_NAMESPACE}"
    echo "  cd ../local-k3s && ./deploy-local-aws-stack.sh --kube-context ${SEL_CTX}"
    echo ""
    exit 0
fi

# Ensure profile-based auth is not overridden by stale env credentials.
nexus_aws_clear_env_credentials

# AWS login — branch on auth type
case "$SEL_AUTH" in
    keys)
        echo "Configuring AWS from IAM access keys (.env.iam.local)..."
        if ! "${SCRIPT_DIR}/aws-iam-login.sh" --profile "$SEL_PROFILE"; then
            echo "AWS IAM key login failed" >&2
            echo "  Populate ${SCRIPT_DIR}/.env.iam.local with IAM_ACCOUNT_* entries" >&2
            echo "  whose IAM_ACCOUNT_*_PROFILE matches: $SEL_PROFILE" >&2
            exit 1
        fi
        ;;
    adfs)
        # Load ADFS credentials from .env.local
        if [[ -f "${SCRIPT_DIR}/.env.local" ]]; then
            set -o allexport
            # shellcheck disable=SC1091
            source "${SCRIPT_DIR}/.env.local"
            set +o allexport
        fi

        LOGIN_ARGS=(--profile "$SEL_PROFILE" --region "$SEL_REGION")
        if [[ -n "$SEL_ROLE_ARN" ]]; then
            LOGIN_ARGS+=(--role-arn "$SEL_ROLE_ARN")
        else
            LOGIN_ARGS+=(--default-role "$SEL_ROLE_IDX")
        fi

        echo "Logging into AWS via ADFS..."
        if ! "${SCRIPT_DIR}/aws-login.sh" "${LOGIN_ARGS[@]}"; then
            echo "AWS ADFS login failed" >&2
            exit 1
        fi
        ;;
    *)
        echo "Unsupported auth_type: $SEL_AUTH" >&2
        exit 1
        ;;
esac

export AWS_PROFILE="$SEL_PROFILE"
export AWS_REGION="$SEL_REGION"

# EKS kubeconfig (project-local)
echo ""
echo "Updating kubeconfig..."
nexus_kube_env_init "$SCRIPT_DIR"
nexus_aws_clear_env_credentials
export AWS_PROFILE="$SEL_PROFILE"
if ! nexus_eks_update_kubeconfig "$SEL_CLUSTER" "$SEL_REGION" "$SEL_PROFILE" "$SEL_CTX"; then
    echo "aws eks update-kubeconfig failed" >&2
    exit 1
fi

nexus_kubectl_use_context "$SEL_CTX" "$SEL_NAMESPACE"

# Persist
nexus_write_active_env "$SCRIPT_DIR" "$SEL_INDEX" "$SEL_LABEL" "$SEL_PROFILE" \
    "$SEL_REGION" "$SEL_CLUSTER" "$SEL_NAMESPACE" "$SEL_CTX" "$SEL_AUTH"
echo "$SEL_INDEX" > "$CACHE_FILE"

# Export for current shell if sourced
export AWS_PROFILE AWS_REGION KUBECONFIG
export NEXUS_ENV_INDEX="$SEL_INDEX"
export NEXUS_ENV_LABEL="$SEL_LABEL"
export NEXUS_AWS_AUTH_TYPE="$SEL_AUTH"
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
nexus_aws_clear_env_credentials
export AWS_PROFILE="$SEL_PROFILE"
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

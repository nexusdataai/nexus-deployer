#!/bin/bash

# AWS EKS Context Selector
# After a successful AWS login (via aws-login.sh or aws-sso-login.sh), this
# script lists EKS clusters in the active profile + region, lets you pick
# one, switches kubectl context, and pins a Kubernetes namespace.
#
# Default namespace pattern: nexus-ai-${ENVIRONMENT:-dev}
# Override with --namespace, NAMESPACE=, or --pick-namespace.

# ── Directory dance (matches aws-login.sh) ──────────────────────────────
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ORIGINAL_DIR="$(pwd)"

cd "$SCRIPT_DIR"

# Restore working directory on every exit path.
trap 'cd "$ORIGINAL_DIR"' EXIT

# ── Defaults ────────────────────────────────────────────────────────────
# Configuration is read from --profile / --region CLI flags or AWS_PROFILE /
# AWS_REGION shell env vars only. No .env.* files are sourced — log in first
# with aws-sso-login.sh / aws-login.sh (which export the right profile) or
# pass --profile / --region explicitly.
: "${AWS_PROFILE:=default}"
: "${AWS_REGION:=us-east-1}"

CACHE_FILE="$SCRIPT_DIR/.last-eks"

# Flags / overrides
PICK_NAMESPACE_FLAG=false
NO_NAMESPACE_FLAG=false
RESET_CACHE=false
NAMESPACE_EXPLICIT=false   # tracks whether --namespace or NAMESPACE= was set

# If NAMESPACE env was provided by the shell, respect it.
if [ -n "${NAMESPACE:-}" ]; then
    NAMESPACE_EXPLICIT=true
fi

# ── Argument parsing ────────────────────────────────────────────────────
while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --profile)        AWS_PROFILE="$2"; shift ;;
        --region)         AWS_REGION="$2"; shift ;;
        --cluster)        EKS_CLUSTER_NAME="$2"; shift ;;
        --namespace)      NAMESPACE="$2"; NAMESPACE_EXPLICIT=true; shift ;;
        --pick-namespace) PICK_NAMESPACE_FLAG=true ;;
        --no-namespace)   NO_NAMESPACE_FLAG=true ;;
        --reset)          RESET_CACHE=true ;;
        --help|-h)
            cat <<EOF
Usage: $0 [OPTIONS]

After AWS login, list EKS clusters, pick one, switch kubectl context, pin a namespace.

Options:
  --profile NAME       AWS CLI profile to use (default: \$AWS_PROFILE or 'default')
  --region REGION      AWS region to query (default: \$AWS_REGION or 'us-east-1')
  --cluster NAME       Non-interactive cluster pick (falls back to menu if not found)
  --namespace NS       Pin this namespace onto the kubectl context
  --pick-namespace     Show an interactive namespace menu after the cluster picker
  --no-namespace       Skip namespace pinning entirely
  --reset              Clear the .last-eks cache before resolving
  --help               Show this help

Environment variables (also recognized):
  AWS_PROFILE                     AWS CLI profile (overridden by --profile)
  AWS_REGION                      AWS region (overridden by --region)
  EKS_CLUSTER_NAME                Same as --cluster
  NAMESPACE                       Same as --namespace
  ENVIRONMENT                     Used to derive the default namespace: nexus-ai-\${ENVIRONMENT:-dev}

Precedence (highest-wins):
  1. CLI flags (--profile / --region / --cluster / --namespace)
  2. Shell env (\$AWS_PROFILE / \$AWS_REGION / ...; e.g. exported by aws-sso-login.sh)
  3. Hardcoded defaults (AWS_PROFILE=default, AWS_REGION=us-east-1)

  No .env.* files are auto-loaded. Run aws-sso-login.sh or aws-login.sh first
  to set AWS_PROFILE in your shell, or pass --profile explicitly.

Examples:
  ./aws-eks-context.sh                                  # interactive menu, default namespace pattern
  ./aws-eks-context.sh --cluster nexus-dev              # non-interactive cluster pick
  EKS_CLUSTER_NAME=nexus-dev ./aws-eks-context.sh       # same, via env
  ./aws-eks-context.sh --no-namespace --cluster nexus-dev   # cluster only, no namespace pin
  NAMESPACE=nexus-ai-engine-dev ./aws-eks-context.sh    # nexus-ai-engine namespace
  ./aws-eks-context.sh --pick-namespace                 # menu of namespaces after cluster
  ./aws-eks-context.sh --reset                          # clear cache and re-prompt
EOF
            exit 0
            ;;
        *)
            echo "❌ Unknown parameter: $1"
            echo "   Run '$0 --help' for usage."
            exit 1
            ;;
    esac
    shift
done

# ── Reset cache if requested ────────────────────────────────────────────
if [ "$RESET_CACHE" = "true" ] && [ -f "$CACHE_FILE" ]; then
    rm -f "$CACHE_FILE"
    echo "🔄 Cleared .last-eks cache"
fi

# ── Prereq checks ───────────────────────────────────────────────────────
if ! command -v aws &> /dev/null; then
    echo "❌ aws CLI not found on PATH."
    echo "   Install: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
    exit 1
fi

if ! command -v kubectl &> /dev/null; then
    echo "❌ kubectl not found on PATH."
    echo "   Install: https://kubernetes.io/docs/tasks/tools/"
    exit 1
fi

echo "🔍 Verifying AWS credentials for profile: $AWS_PROFILE"
if ! aws sts get-caller-identity --profile "$AWS_PROFILE" &> /dev/null; then
    echo "❌ AWS credentials are missing or expired for profile '$AWS_PROFILE'."
    echo ""
    echo "   Log in first:"
    echo "     ./aws-login.sh                # ADFS login"
    echo "     ./aws-sso-login.sh            # SSO login"
    echo ""
    echo "   Then re-run: $0 ${*}"
    exit 1
fi

# Capture caller identity for the summary block
CALLER_JSON=$(aws sts get-caller-identity --profile "$AWS_PROFILE" --output json 2>/dev/null || true)
CALLER_ACCOUNT=$(printf '%s' "$CALLER_JSON" | sed -n 's/.*"Account": *"\([^"]*\)".*/\1/p')
CALLER_ARN=$(printf '%s' "$CALLER_JSON" | sed -n 's/.*"Arn": *"\([^"]*\)".*/\1/p')

echo "   Account: ${CALLER_ACCOUNT:-?}"
echo "   Identity: ${CALLER_ARN:-?}"
echo "   Region:  $AWS_REGION"
echo ""

# ── List clusters ───────────────────────────────────────────────────────
echo "🔍 Listing EKS clusters in $AWS_REGION ..."
CLUSTERS_RAW=$(aws eks list-clusters \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" \
    --query 'clusters[]' \
    --output text 2>&1)
LIST_EXIT=$?

if [ $LIST_EXIT -ne 0 ]; then
    echo "❌ aws eks list-clusters failed:"
    echo "   $CLUSTERS_RAW"
    exit 1
fi

# AWS returns tab-separated names on one line for --output text on a flat array
mapfile -t CLUSTERS < <(printf '%s\n' "$CLUSTERS_RAW" | tr '\t' '\n' | sed '/^$/d')

if [ ${#CLUSTERS[@]} -eq 0 ]; then
    echo "ℹ️  No EKS clusters found in region '$AWS_REGION' for profile '$AWS_PROFILE'."
    echo "   Try a different region with --region <name>, or verify the profile permissions."
    exit 0
fi

echo "   Found ${#CLUSTERS[@]} cluster(s)."
echo ""

# ── Resolve cluster choice ──────────────────────────────────────────────
SELECTED=""

# 1. Explicit --cluster / EKS_CLUSTER_NAME (validated against the list)
if [ -n "${EKS_CLUSTER_NAME:-}" ]; then
    if printf '%s\n' "${CLUSTERS[@]}" | grep -qx -- "$EKS_CLUSTER_NAME"; then
        SELECTED="$EKS_CLUSTER_NAME"
        echo "🎯 Using cluster from --cluster/EKS_CLUSTER_NAME: $SELECTED"
    else
        echo "⚠️  Requested cluster '$EKS_CLUSTER_NAME' not found in $AWS_REGION."
        echo "   Falling back to interactive menu."
    fi
fi

# 2. Cached previous selection becomes the menu default
DEFAULT_INDEX=1
if [ -z "$SELECTED" ] && [ -f "$CACHE_FILE" ]; then
    LAST=$(head -n 1 "$CACHE_FILE" 2>/dev/null | tr -d '[:space:]')
    if [ -n "$LAST" ]; then
        IDX=$(printf '%s\n' "${CLUSTERS[@]}" | grep -nxF -- "$LAST" | head -1 | cut -d: -f1)
        if [ -n "$IDX" ]; then
            DEFAULT_INDEX="$IDX"
        fi
    fi
fi

# 3. Interactive menu
if [ -z "$SELECTED" ]; then
    echo "📋 Available clusters:"
    for i in "${!CLUSTERS[@]}"; do
        idx=$((i + 1))
        marker="  "
        if [ "$idx" = "$DEFAULT_INDEX" ]; then
            marker="* "
        fi
        printf "  %s%2d) %s\n" "$marker" "$idx" "${CLUSTERS[$i]}"
    done
    echo ""
    read -r -p "Select cluster [${DEFAULT_INDEX}]: " CHOICE
    CHOICE="${CHOICE:-$DEFAULT_INDEX}"

    if ! [[ "$CHOICE" =~ ^[0-9]+$ ]] || [ "$CHOICE" -lt 1 ] || [ "$CHOICE" -gt "${#CLUSTERS[@]}" ]; then
        echo "❌ Invalid selection: $CHOICE"
        exit 1
    fi
    SELECTED="${CLUSTERS[$((CHOICE - 1))]}"
fi

echo ""
echo "🎯 Selected cluster: $SELECTED"

# ── update-kubeconfig ───────────────────────────────────────────────────
echo "🔧 Running aws eks update-kubeconfig ..."
if ! aws eks update-kubeconfig \
        --name "$SELECTED" \
        --region "$AWS_REGION" \
        --profile "$AWS_PROFILE" \
        --alias "$SELECTED" >/dev/null 2>&1; then
    echo "❌ aws eks update-kubeconfig failed for cluster '$SELECTED'."
    echo "   Re-run with --reset, or verify your IAM permissions on this cluster."
    exit 1
fi
echo "   kubectl context set to: $SELECTED"

# Switch to the new context (update-kubeconfig sets it as current, but be explicit)
kubectl config use-context "$SELECTED" >/dev/null 2>&1 || true

# ── Resolve namespace ───────────────────────────────────────────────────
NAMESPACE_PINNED=false
RESOLVED_NAMESPACE=""
NAMESPACE_REASON=""

if [ "$NO_NAMESPACE_FLAG" = "true" ]; then
    NAMESPACE_REASON="--no-namespace; namespace not pinned"
elif [ "$PICK_NAMESPACE_FLAG" = "true" ]; then
    echo ""
    echo "🔍 Listing namespaces in $SELECTED ..."
    mapfile -t NAMESPACES < <(kubectl get ns -o name 2>/dev/null | sed 's|^namespace/||')
    if [ ${#NAMESPACES[@]} -eq 0 ]; then
        echo "⚠️  Could not list namespaces (RBAC?). Skipping namespace pin."
        NAMESPACE_REASON="namespaces not listable; skipped"
    else
        # Default index: prefer NAMESPACE if it exists in the list, else 1
        NS_DEFAULT_IDX=1
        if [ -n "${NAMESPACE:-}" ]; then
            IDX=$(printf '%s\n' "${NAMESPACES[@]}" | grep -nxF -- "$NAMESPACE" | head -1 | cut -d: -f1)
            [ -n "$IDX" ] && NS_DEFAULT_IDX="$IDX"
        fi
        echo "📋 Available namespaces:"
        for i in "${!NAMESPACES[@]}"; do
            idx=$((i + 1))
            marker="  "
            [ "$idx" = "$NS_DEFAULT_IDX" ] && marker="* "
            printf "  %s%3d) %s\n" "$marker" "$idx" "${NAMESPACES[$i]}"
        done
        echo ""
        read -r -p "Select namespace [${NS_DEFAULT_IDX}]: " NS_CHOICE
        NS_CHOICE="${NS_CHOICE:-$NS_DEFAULT_IDX}"
        if ! [[ "$NS_CHOICE" =~ ^[0-9]+$ ]] || [ "$NS_CHOICE" -lt 1 ] || [ "$NS_CHOICE" -gt "${#NAMESPACES[@]}" ]; then
            echo "❌ Invalid namespace selection: $NS_CHOICE"
            exit 1
        fi
        RESOLVED_NAMESPACE="${NAMESPACES[$((NS_CHOICE - 1))]}"
    fi
elif [ -n "${NAMESPACE:-}" ]; then
    RESOLVED_NAMESPACE="$NAMESPACE"
else
    RESOLVED_NAMESPACE="nexus-ai-${ENVIRONMENT:-dev}"
fi

# ── Verify namespace exists and pin it ──────────────────────────────────
if [ -n "$RESOLVED_NAMESPACE" ]; then
    if kubectl get ns "$RESOLVED_NAMESPACE" >/dev/null 2>&1; then
        if kubectl config set-context --current --namespace="$RESOLVED_NAMESPACE" >/dev/null 2>&1; then
            NAMESPACE_PINNED=true
        else
            NAMESPACE_REASON="kubectl config set-context failed; not pinned"
        fi
    else
        if [ "$NAMESPACE_EXPLICIT" = "true" ] && [ "$PICK_NAMESPACE_FLAG" != "true" ]; then
            # User explicitly asked for this namespace and it does not exist — offer to create.
            echo ""
            echo "⚠️  Namespace '$RESOLVED_NAMESPACE' does not exist in $SELECTED."
            read -r -p "    (s)kip pinning [default] or (c)reate the namespace now? [s/c] " NS_ACTION
            NS_ACTION="${NS_ACTION:-s}"
            if [[ "$NS_ACTION" =~ ^[Cc] ]]; then
                if kubectl create namespace "$RESOLVED_NAMESPACE" >/dev/null 2>&1; then
                    echo "   Created namespace: $RESOLVED_NAMESPACE"
                    if kubectl config set-context --current --namespace="$RESOLVED_NAMESPACE" >/dev/null 2>&1; then
                        NAMESPACE_PINNED=true
                    fi
                else
                    NAMESPACE_REASON="kubectl create namespace failed; not pinned"
                fi
            else
                NAMESPACE_REASON="namespace '$RESOLVED_NAMESPACE' does not exist; skipped"
            fi
        else
            # Default-pattern namespace doesn't exist → silently skip with a hint.
            NAMESPACE_REASON="default namespace '$RESOLVED_NAMESPACE' does not exist; skipped"
        fi
    fi
fi

# ── Smoke checks (informational) ────────────────────────────────────────
echo ""
echo "🔍 Smoke checks ..."
CURRENT_CTX=$(kubectl config current-context 2>/dev/null || echo "?")
echo "   current-context: $CURRENT_CTX"

if [ "$NAMESPACE_PINNED" = "true" ]; then
    if kubectl get ns "$RESOLVED_NAMESPACE" >/dev/null 2>&1; then
        echo "   namespace '$RESOLVED_NAMESPACE': reachable"
    else
        echo "   namespace '$RESOLVED_NAMESPACE': NOT reachable"
    fi
    CAN_I=$(kubectl auth can-i get pods -n "$RESOLVED_NAMESPACE" 2>/dev/null || echo "no")
    echo "   auth can-i get pods -n $RESOLVED_NAMESPACE: $CAN_I"
fi

# ── Save cache ──────────────────────────────────────────────────────────
echo "$SELECTED" > "$CACHE_FILE"

# ── Cluster metadata for the summary ────────────────────────────────────
DESCRIBE_JSON=$(aws eks describe-cluster \
    --name "$SELECTED" \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" \
    --output json 2>/dev/null || true)
CLUSTER_ARN=$(printf '%s' "$DESCRIBE_JSON" | sed -n 's/.*"arn": *"\([^"]*\)".*/\1/p' | head -1)
CLUSTER_ENDPOINT=$(printf '%s' "$DESCRIBE_JSON" | sed -n 's/.*"endpoint": *"\([^"]*\)".*/\1/p' | head -1)

# ── Summary ─────────────────────────────────────────────────────────────
echo ""
echo "🎯 EKS context ready"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
printf "   Cluster:    %s\n" "$SELECTED"
printf "   Region:     %s\n" "$AWS_REGION"
printf "   Profile:    %s\n" "$AWS_PROFILE"
printf "   Account:    %s\n" "${CALLER_ACCOUNT:-?}"
printf "   Context:    %s\n" "$CURRENT_CTX"
if [ "$NAMESPACE_PINNED" = "true" ]; then
    printf "   Namespace:  %s   (pinned)\n" "$RESOLVED_NAMESPACE"
elif [ -n "$NAMESPACE_REASON" ]; then
    printf "   Namespace:  %s\n" "$NAMESPACE_REASON"
fi
if [ -n "$CLUSTER_ENDPOINT" ]; then
    printf "   Endpoint:   %s\n" "$CLUSTER_ENDPOINT"
fi
if [ -n "$CLUSTER_ARN" ]; then
    printf "   ARN:        %s\n" "$CLUSTER_ARN"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Next:"
echo "   kubectl get pods"
if [ "$NAMESPACE_PINNED" = "true" ]; then
    echo "   kubectl get pods -n $RESOLVED_NAMESPACE   # (already pinned, -n optional)"
fi
echo ""
echo "✅ Done!"

#!/bin/bash
#
# deploy-app-changes.sh — Fast dev deploy path for Nexus product repos
#
# First-time deploy: operator + examples/*-complete.yaml descriptor
# Dev iteration:     this script (build → ECR push → app-rollout)
#
# Products:
#   nexus-ai      nexus-backend + nexus-ui (default)
#   ai-engine     nexus-ai-engine API + UI
#   sre           nexus-sre backend + UI (+ --postgres for postgres image)
#   ontology      nexus-ontology API + UI
#   simulator     nexus-simulator API + UI
#
# Usage:
#   ./deploy-app-changes.sh ai-engine --env dev
#   ./deploy-app-changes.sh --product sre --backend --env dev
#   ./deploy-app-changes.sh ontology --ui --dry-run
#   ./deploy-app-changes.sh                          # nexus-ai, auto-detect
#
# Options:
#   PRODUCT             Positional product name (or --product NAME)
#   --product NAME      nexus-ai | ai-engine | sre | ontology | simulator
#   --env ENV           dev | stage | prod
#   --cluster NAME      EKS cluster (default: .env.local Cluster= or nexus-{env})
#   --namespace NS      Override target Kubernetes namespace
#   --backend|--api     Force backend/API/server component
#   --frontend|--ui     Force frontend/UI component
#   --postgres          Force SRE postgres image (sre product only)
#   --all|--both        Force all default components for the product
#   --bump TYPE         patch | minor | major (default: patch)
#   -m, --message MSG   Git commit message
#   --commit            Commit before build (default: on)
#   --no-commit         Skip git commits
#   --push              Push commits after --commit
#   --no-cache          docker build --no-cache
#   --skip-build        Rollout only (tags from images/*/versions.env)
#   --skip-rollout      Build + push only
#   --sequential        Disable parallel build/rollout
#   --conservative-rollout  Skip maxSurge strategy patch
#   --dry-run           Show plan only
#   --help              Show help

set -euo pipefail

if docker buildx version >/dev/null 2>&1; then
    export DOCKER_BUILDKIT=1
fi

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

dac_log_step() { printf "\n${CYAN}── %s ──${NC}\n" "$1"; }
dac_log_ok()   { printf "${GREEN}✓${NC} %s\n" "$1"; }
dac_log_warn() { printf "${YELLOW}!${NC} %s\n" "$1"; }
dac_log_fail() { printf "${RED}✗${NC} %s\n" "$1"; }
dac_log_info() { printf "  %s\n" "$1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/init-kube-env.sh
. "${SCRIPT_DIR}/lib/init-kube-env.sh"
# shellcheck source=lib/deploy-app-changes-common.sh
. "${SCRIPT_DIR}/lib/deploy-app-changes-common.sh"
# shellcheck source=lib/deploy-app-changes-products.sh
. "${SCRIPT_DIR}/lib/deploy-app-changes-products.sh"

DEPLOYER_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
NEXUS_ROOT="$(cd "$DEPLOYER_ROOT/.." && pwd)"
REGION="${REGION:-us-east-1}"

_env_local="${SCRIPT_DIR}/.env.local"
[ -f "$_env_local" ] && . "$_env_local"

PRODUCT="${PRODUCT:-nexus-ai}"
DEPLOY_ENV="${DEPLOY_ENV:-${ENV:-dev}}"
CLUSTER_NAME="${CLUSTER_NAME:-${Cluster:-}}"
NAMESPACE_OVERRIDE=""
BUMP_TYPE="patch"
COMMIT=true
DO_PUSH=false
NO_CACHE=false
SKIP_BUILD=false
SKIP_ROLLOUT=false
PARALLEL=true
FAST_ROLLOUT=true
DRY_RUN=false
COMMIT_MSG=""
FORCE_BACKEND=false
FORCE_FRONTEND=false
FORCE_API=false
FORCE_UI=false
FORCE_POSTGRES=false
FORCE_ALL=false

show_help() {
    sed -n '2,44p' "$0"
    echo ""
    echo "Products: $(dac_list_products)"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --product)         PRODUCT="$2"; shift 2 ;;
        --env)             DEPLOY_ENV="$2"; shift 2 ;;
        --cluster)         CLUSTER_NAME="$2"; shift 2 ;;
        --namespace|-n)    NAMESPACE_OVERRIDE="$2"; shift 2 ;;
        --backend)         FORCE_BACKEND=true; shift ;;
        --frontend)        FORCE_FRONTEND=true; shift ;;
        --api)             FORCE_API=true; shift ;;
        --ui)              FORCE_UI=true; shift ;;
        --postgres)        FORCE_POSTGRES=true; shift ;;
        --all|--both)      FORCE_ALL=true; shift ;;
        --bump)            BUMP_TYPE="$2"; shift 2 ;;
        -m|--message)      COMMIT_MSG="$2"; shift 2 ;;
        --commit)          COMMIT=true; shift ;;
        --no-commit)       COMMIT=false; shift ;;
        --push)            DO_PUSH=true; shift ;;
        --no-cache)        NO_CACHE=true; shift ;;
        --skip-build)      SKIP_BUILD=true; shift ;;
        --skip-rollout)    SKIP_ROLLOUT=true; shift ;;
        --sequential)      PARALLEL=false; shift ;;
        --conservative-rollout) FAST_ROLLOUT=false; shift ;;
        --dry-run)         DRY_RUN=true; shift ;;
        --help|-h)         show_help; exit 0 ;;
        nexus-ai|ai-engine|nexus-ai-engine|sre|nexus-sre|ontology|nexus-ontology|simulator|nexus-simulator|training|nexus-training|fde-training)
            PRODUCT="$1"; shift ;;
        *)
            dac_log_fail "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

case "$DEPLOY_ENV" in
    prod)  CLUSTER_NAME="${CLUSTER_NAME:-nexus-prod}" ;;
    dev)   CLUSTER_NAME="${CLUSTER_NAME:-nexus-dev}" ;;
    local) CLUSTER_NAME="${CLUSTER_NAME:-local-cluster}" ;;
    *)     CLUSTER_NAME="${CLUSTER_NAME:-nexus-${DEPLOY_ENV}}" ;;
esac

dac_load_product "$PRODUCT" || exit 1
dac_validate_product_repos || exit 1

if [ "$DRY_RUN" = false ]; then
    if [ "${CLUSTER_NAME}" = "local-cluster" ]; then
        if ! kubectl config use-context "${CLUSTER_NAME}" --kubeconfig "${KUBECONFIG}" >/dev/null 2>&1; then
            nexus_local_k3s_refresh_kubeconfig "${CLUSTER_NAME}" "${CLUSTER_NAME}" >/dev/null 2>&1 \
                || dac_log_warn "Context ${CLUSTER_NAME} not in kubeconfig — run local-k3s/create-local-k3s-cluster.sh"
            kubectl config use-context "${CLUSTER_NAME}" --kubeconfig "${KUBECONFIG}" >/dev/null 2>&1 \
                || { dac_log_fail "Failed to configure kubectl for local K3s ('${CLUSTER_NAME}')"; exit 1; }
        fi
    else
        nexus_eks_update_kubeconfig "${CLUSTER_NAME}" "${REGION}" "${AWS_PROFILE:-}" >/dev/null 2>&1 \
            || aws eks update-kubeconfig --name "${CLUSTER_NAME}" --region "${REGION}" \
                --profile "${AWS_PROFILE:-}" --kubeconfig "${KUBECONFIG}" >/dev/null 2>&1 \
            || { dac_log_fail "Failed to configure kubectl for cluster '${CLUSTER_NAME}'"; exit 1; }
    fi
    kubectl get nodes >/dev/null 2>&1 \
        || { dac_log_fail "kubectl cannot connect to cluster '${CLUSTER_NAME}'"; exit 1; }
fi

if [ "$DRY_RUN" = false ]; then
    dac_prepare_ecr_aws_env
fi

LOCAL_K3S_IMAGES=false
ACCOUNT_ID="$(nexus_aws_account_id)"
if [ -z "$ACCOUNT_ID" ]; then
    if { [ "${CLUSTER_NAME}" = "local-cluster" ] || [ "${DEPLOY_ENV}" = "local" ]; }; then
        LOCAL_K3S_IMAGES=true
        [ "$DRY_RUN" = false ] \
            && dac_log_warn "No AWS credentials for ECR — building locally and importing into K3s"
        ACCOUNT_ID="local"
    elif [ "$DRY_RUN" = false ]; then
        dac_log_fail "AWS credentials not available for ECR (run: aws sts get-caller-identity, or use --env local on K3s)"
        exit 1
    fi
fi
export LOCAL_K3S_IMAGES
[ -z "$ACCOUNT_ID" ] && ACCOUNT_ID="<account>"

# local-cluster only runs ai-engine-local workloads (not ai-engine-dev).
if [ "$LOCAL_K3S_IMAGES" = true ] && [ "$PRODUCT" = "ai-engine" ] && [ "$DEPLOY_ENV" != "local" ]; then
    dac_log_warn "local-cluster uses ai-engine-local — remapping --env ${DEPLOY_ENV} → local"
    DEPLOY_ENV=local
    dac_load_product "$PRODUCT" || exit 1
fi

if [ "$LOCAL_K3S_IMAGES" = true ] && [ "$PRODUCT" = "ontology" ] && [ "$DEPLOY_ENV" != "local" ]; then
    dac_log_warn "local-cluster uses ontology-local — remapping --env ${DEPLOY_ENV} → local"
    DEPLOY_ENV=local
    dac_load_product "$PRODUCT" || exit 1
fi

if [ "$LOCAL_K3S_IMAGES" = true ] && [ "$PRODUCT" = "simulator" ] && [ "$DEPLOY_ENV" != "local" ]; then
    dac_log_warn "local-cluster uses simulator-local — remapping --env ${DEPLOY_ENV} → local"
    DEPLOY_ENV=local
    dac_load_product "$PRODUCT" || exit 1
fi

if [ "$LOCAL_K3S_IMAGES" = true ] && [ "$PRODUCT" = "training" ] && [ "$DEPLOY_ENV" != "local" ]; then
    dac_log_warn "local-cluster uses training-local — remapping --env ${DEPLOY_ENV} → local"
    DEPLOY_ENV=local
    dac_load_product "$PRODUCT" || exit 1
fi

if [ "$LOCAL_K3S_IMAGES" = true ]; then
    ECR_REGISTRY="local-k3s"
else
    ECR_REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
fi

BUILD_FLAGS=""
[ "$NO_CACHE" = true ] && BUILD_FLAGS="--no-cache"

# ── Detect components to deploy ──────────────────────────────────
declare -A DEPLOY_COMP=()
declare -A COMP_SPEC=()

for spec in "${DAC_COMPONENTS[@]}"; do
    id=$(dac_comp_field "$spec" 1)
    COMP_SPEC[$id]="$spec"
done

if [ "$FORCE_ALL" = true ]; then
    for id in $(dac_default_deploy_components); do
        DEPLOY_COMP[$id]=true
    done
else
    for spec in "${DAC_COMPONENTS[@]}"; do
        id=$(dac_comp_field "$spec" 1)
        # Skip postgres unless explicitly forced (SRE dev default)
        [ "$id" = postgres ] && ! dac_component_force_requested postgres && continue
        if dac_component_force_requested "$id"; then
            DEPLOY_COMP[$id]=true
        elif ! dac_component_force_requested "$id" \
            && [ "$FORCE_BACKEND" = false ] && [ "$FORCE_FRONTEND" = false ] \
            && [ "$FORCE_API" = false ] && [ "$FORCE_UI" = false ] \
            && [ "$FORCE_POSTGRES" = false ]; then
            dir=$(dac_comp_field "$spec" 2)
            k8s_name=$(dac_comp_field "$spec" 8)
            kind=$(dac_comp_field "$spec" 9)
            dac_component_needs_deploy "$id" "$dir" "$k8s_name" "$kind" false && DEPLOY_COMP[$id]=true
        fi
    done
fi

if [ "${#DEPLOY_COMP[@]}" -eq 0 ]; then
    dac_log_ok "Nothing to deploy — working trees match cluster (use --all or component flags to force)"
    exit 0
fi

# ── Plan ─────────────────────────────────────────────────────────
printf "\n${BOLD}Deploy App Changes${NC}\n"
dac_log_info "Product:      ${PRODUCT} (${DAC_PRODUCT_LABEL})"
dac_log_info "Environment:  ${DEPLOY_ENV}"
dac_log_info "Namespace:    ${DAC_NAMESPACE}"
dac_log_info "Cluster:      ${CLUSTER_NAME}"
dac_log_info "ECR:          ${ECR_REGISTRY}$([ "$LOCAL_K3S_IMAGES" = true ] && echo ' (local import, no push)')"
dac_log_info "Descriptor:   ${DAC_DESCRIPTOR}"
dac_log_info "Components:   ${!DEPLOY_COMP[*]}"
dac_log_info "Bump:         ${BUMP_TYPE}"
dac_log_info "Commit:       ${COMMIT}$([ "$DO_PUSH" = true ] && echo ' + push')"
[ "$DRY_RUN" = true ] && dac_log_warn "DRY RUN — no changes will be made"

declare -A COMP_TAG=()
declare -A COMP_VER=()
declare -A COMP_SHA=()
DAC_VERSION_ENTRIES=()

# ── Phase 1: version bump + commit ───────────────────────────────
if [ "$SKIP_BUILD" = true ] && [ -f "${DAC_IMAGES_DIR}/versions.env" ]; then
    dac_log_step "Phase 1: Using tags from ${DAC_IMAGES_DIR}/versions.env"
    for id in "${!DEPLOY_COMP[@]}"; do
        spec="${COMP_SPEC[$id]}"
        tag_key=$(dac_comp_field "$spec" 11)
        ver_key=$(dac_comp_field "$spec" 12)
        tag=$(dac_load_tags_from_versions_env "$tag_key")
        ver=$(dac_load_tags_from_versions_env "$ver_key")
        [ -z "$ver" ] && ver="${tag%%-*}"
        COMP_TAG[$id]="$tag"
        COMP_VER[$id]="$ver"
        COMP_SHA[$id]="${tag##*-}"
        dac_log_info "${id} tag: ${tag}"
    done
else
    dac_log_step "Phase 1: Version bump + git"
    for id in "${!DEPLOY_COMP[@]}"; do
        spec="${COMP_SPEC[$id]}"
        dir=$(dac_comp_field "$spec" 2)
        ver_file=$(dac_comp_field "$spec" 3)
        cur_ver="$(dac_read_version "$dir" "$ver_file" 2>/dev/null || echo "0.1.0")"
        new_ver="$(dac_bump_semver "$cur_ver" "$BUMP_TYPE")"
        COMP_VER[$id]="$new_ver"
        dac_log_info "${id} VERSION: ${cur_ver} → ${new_ver}"
        dac_bump_version_file "$dir" "$ver_file" "$new_ver"
        dac_git_commit_repo "$dir" "$id" "$new_ver" "$COMMIT_MSG"
        sha="$(dac_repo_git_sha "$dir")"
        COMP_SHA[$id]="$sha"
        COMP_TAG[$id]="${new_ver}-${sha}"
        dac_log_info "${id} tag: ${COMP_TAG[$id]}"
    done
fi

# ── Phase 2: build + push ────────────────────────────────────────
if [ "$SKIP_BUILD" = false ]; then
    if [ "$LOCAL_K3S_IMAGES" = true ]; then
        dac_log_step "Phase 2: Build + import into K3s"
    else
        dac_log_step "Phase 2: Build + push to ECR"
        dac_ecr_login "$ACCOUNT_ID"
    fi
    _build_jobs=()
    for id in "${!DEPLOY_COMP[@]}"; do
        spec="${COMP_SPEC[$id]}"
        local_image=$(dac_comp_field "$spec" 4)
        ecr_repo=$(dac_comp_field "$spec" 5)
        dir=$(dac_comp_field "$spec" 2)
        pre_build=$(dac_comp_field "$spec" 10)
        dockerfile=$(dac_comp_dockerfile "$spec")
        tag="${COMP_TAG[$id]}"
        sha="${COMP_SHA[$id]:-}"
        _build_jobs+=("${id}|dac_build_and_push '${local_image}' '${ecr_repo}' '${tag}' '${sha}' '${BUILD_FLAGS}' '${dir}' '${pre_build}' '${dockerfile}'")
    done
    dac_run_parallel_jobs "build+push" "${_build_jobs[@]}" || exit 1

    for spec in "${DAC_COMPONENTS[@]}"; do
        id=$(dac_comp_field "$spec" 1)
        tag_key=$(dac_comp_field "$spec" 11)
        ver_key=$(dac_comp_field "$spec" 12)
        dir=$(dac_comp_field "$spec" 2)
        k8s_name=$(dac_comp_field "$spec" 8)
        kind=$(dac_comp_field "$spec" 9)
        if [ "${DEPLOY_COMP[$id]+set}" = set ]; then
            tag="${COMP_TAG[$id]}"
            ver="${COMP_VER[$id]}"
        else
            tag=$(dac_resolve_persisted_tag "$tag_key" "$dir" "0.0.0" "$k8s_name" "$kind")
            ver="${tag%%-*}"
        fi
        DAC_VERSION_ENTRIES+=("${tag_key}=${tag}")
        DAC_VERSION_ENTRIES+=("${ver_key}=${ver}")
    done
    dac_write_versions_env
    [ "$DRY_RUN" = false ] && dac_log_ok "Updated ${DAC_IMAGES_DIR}/versions.env"
else
    dac_log_step "Phase 2: Skipped (--skip-build)"
fi

# ── Phase 3: rollout ─────────────────────────────────────────────
if [ "$SKIP_ROLLOUT" = false ]; then
    if [ "$LOCAL_K3S_IMAGES" = true ] && [ "$PRODUCT" = "ai-engine" ]; then
        dac_ensure_local_ai_engine_workloads "${COMP_TAG[api]:-}" "${COMP_TAG[ui]:-}" || exit 1
    fi
    if [ "$LOCAL_K3S_IMAGES" = true ] && [ "$PRODUCT" = "ontology" ]; then
        dac_ensure_local_ontology_workloads "${COMP_TAG[api]:-}" "${COMP_TAG[ui]:-}" || exit 1
    fi
    if [ "$LOCAL_K3S_IMAGES" = true ] && [ "$PRODUCT" = "simulator" ]; then
        dac_ensure_local_simulator_workloads "${COMP_TAG[api]:-}" "${COMP_TAG[ui]:-}" || exit 1
    fi
    if [ "$LOCAL_K3S_IMAGES" = true ] && [ "$PRODUCT" = "training" ]; then
        dac_ensure_local_training_workloads "${COMP_TAG[api]:-}" "${COMP_TAG[ui]:-}" || exit 1
    fi
    dac_log_step "Phase 3: Kubernetes rollout (no diagnostics)"
    _rollout_jobs=()
    for id in "${!DEPLOY_COMP[@]}"; do
        spec="${COMP_SPEC[$id]}"
        rollout_comp=$(dac_comp_field "$spec" 6)
        version_flag=$(dac_comp_field "$spec" 7)
        k8s_name=$(dac_comp_field "$spec" 8)
        kind=$(dac_comp_field "$spec" 9)
        local_image=$(dac_comp_field "$spec" 4)
        tag="${COMP_TAG[$id]}"
        _rollout_jobs+=("${id}|dac_rollout_component '${rollout_comp}' '${version_flag}' '${tag}' '${k8s_name}' '${kind}' '${local_image}'")
    done
    dac_run_parallel_jobs "rollout" "${_rollout_jobs[@]}" || exit 1
else
    dac_log_step "Phase 3: Skipped (--skip-rollout)"
fi

printf "\n${GREEN}${BOLD}✓ Deploy complete (${PRODUCT})${NC}\n"
for id in "${!DEPLOY_COMP[@]}"; do
    dac_log_info "${id}: ${COMP_TAG[$id]}"
done
echo ""

#!/bin/bash
# Product definitions for deploy-app-changes.sh (sourced, not executed directly).
#
# Component spec fields (pipe-separated):
#   1 id            logical id + force-flag alias (backend|frontend|api|ui|postgres|server)
#   2 dir           build context directory
#   3 version_file  VERSION filename relative to dir
#   4 local_image   local docker tag (without :latest)
#   5 ecr_repo      ECR repository name
#   6 rollout_comp  app-rollout.sh component name
#   7 version_flag  app-rollout version flag (--backend-version, etc.)
#   8 k8s_name      deployment/statefulset name
#   9 k8s_kind      deployment | statefulset
#  10 pre_build      empty | docs
#  11 tag_env_key    versions.env key for image tag
#  12 version_env_key versions.env key for semver
#  13 dockerfile     Dockerfile path relative to dir (default: Dockerfile)

dac_normalize_product() {
    case "$1" in
        nexus-ai|ai|nexus-ai-platform) echo "nexus-ai" ;;
        ai-engine|nexus-ai-engine)     echo "ai-engine" ;;
        sre|nexus-sre)                 echo "sre" ;;
        ontology|nexus-ontology)       echo "ontology" ;;
        simulator|nexus-simulator)       echo "simulator" ;;
        *)                             echo "$1" ;;
    esac
}

dac_list_products() {
    echo "nexus-ai ai-engine sre ontology simulator"
}

dac_load_product() {
    local product="$1"
    PRODUCT="$(dac_normalize_product "$product")"

    case "$PRODUCT" in
        nexus-ai)
            DAC_PRODUCT_LABEL="Nexus AI (backend + UI)"
            DAC_IMAGES_DIR="${SCRIPT_DIR}/images/nexus"
            DAC_DESCRIPTOR="${SCRIPT_DIR}/examples/nexus-ai-complete.yaml"
            DAC_ROLLOUT_ARGS=(--capability nexus-ai)
            case "$DEPLOY_ENV" in
                prod)  DAC_NAMESPACE="nexus-ai-prod" ;;
                *)     DAC_NAMESPACE="nexus-ai-${DEPLOY_ENV}" ;;
            esac
            DAC_COMPONENTS=(
                "backend|${NEXUS_ROOT}/nexus-backend|VERSION|ai-job-engine|ai-job-engine|backend|--backend-version|${DAC_NAMESPACE}-backend|deployment||BACKEND_TAG|BACKEND_VERSION"
                "frontend|${NEXUS_ROOT}/nexus-ui|VERSION|nexus-ui|nexus-ui|frontend|--frontend-version|${DAC_NAMESPACE}-frontend|deployment|docs|FRONTEND_TAG|FRONTEND_VERSION"
            )
            ;;
        ai-engine)
            DAC_PRODUCT_LABEL="Nexus AI Engine (API + UI)"
            DAC_IMAGES_DIR="${SCRIPT_DIR}/images/nexus-ai-engine"
            DAC_DESCRIPTOR="${SCRIPT_DIR}/examples/nexus-ai-engine-complete.yaml"
            DAC_ROLLOUT_ARGS=(--capability ai-engine)
            case "$DEPLOY_ENV" in
                prod)  DAC_NAMESPACE="ai-engine" ;;
                *)     DAC_NAMESPACE="ai-engine-${DEPLOY_ENV}" ;;
            esac
            local _ae="${AI_ENGINE_DIR:-${NEXUS_ROOT}/nexus-ai-engine}"
            DAC_COMPONENTS=(
                "api|${_ae}|backend/VERSION|nexus-ai-engine-api|nexus-ai-engine-api|ai-engine-api|--ai-engine-api-version|ai-engine-${DEPLOY_ENV}-backend|deployment||AI_ENGINE_API_TAG|AI_ENGINE_API_VERSION|backend/Dockerfile"
                "worker|${_ae}|backend/VERSION|nexus-ai-engine-api|nexus-ai-engine-api|ai-engine-worker|--ai-engine-worker-version|ai-engine-${DEPLOY_ENV}-job-worker|deployment||AI_ENGINE_WORKER_TAG|AI_ENGINE_API_VERSION|backend/Dockerfile"
                "ui|${_ae}/frontend|VERSION|nexus-ai-engine-ui|nexus-ai-engine-ui|ai-engine-ui|--ai-engine-ui-version|ai-engine-${DEPLOY_ENV}-frontend|deployment||AI_ENGINE_UI_TAG|AI_ENGINE_UI_VERSION"
            )
            ;;
        sre)
            DAC_PRODUCT_LABEL="Nexus SRE (backend + UI + postgres)"
            DAC_IMAGES_DIR="${SCRIPT_DIR}/images/nexus-sre"
            DAC_DESCRIPTOR="${SCRIPT_DIR}/examples/nexus-sre-complete.yaml"
            DAC_ROLLOUT_ARGS=(--namespace nexus-sre)
            DAC_NAMESPACE="nexus-sre"
            local _sbe="${SRE_BACKEND_DIR:-${NEXUS_ROOT}/nexus-sre/backend}"
            local _sfe="${SRE_FRONTEND_DIR:-${NEXUS_ROOT}/nexus-sre/frontend}"
            local _spg="${SRE_POSTGRES_DIR:-${NEXUS_ROOT}/nexus-sre/postgres-image}"
            DAC_COMPONENTS=(
                "backend|${_sbe}|VERSION|nexus-sre-backend|nexus-sre-backend|sre-backend|--sre-backend-version|nexus-sre-backend|deployment||SRE_BACKEND_TAG|SRE_BACKEND_VERSION"
                "frontend|${_sfe}|VERSION|nexus-sre-ui|nexus-sre-ui|sre-ui|--sre-ui-version|nexus-sre-ui|deployment||SRE_UI_TAG|SRE_UI_VERSION"
                "postgres|${_spg}|VERSION|nexus-sre-postgres|nexus-sre-postgres|sre-postgres|--sre-postgres-version|nexus-sre-postgres|statefulset||SRE_POSTGRES_TAG|SRE_POSTGRES_VERSION"
            )
            ;;
        ontology)
            DAC_PRODUCT_LABEL="Nexus Ontology (API + UI)"
            DAC_IMAGES_DIR="${SCRIPT_DIR}/images/nexus-ontology"
            DAC_DESCRIPTOR="${SCRIPT_DIR}/examples/nexus-ontology-complete.yaml"
            DAC_ROLLOUT_ARGS=(--capability ontology)
            case "$DEPLOY_ENV" in
                prod)  DAC_NAMESPACE="ontology-prod" ;;
                *)     DAC_NAMESPACE="ontology-${DEPLOY_ENV}" ;;
            esac
            local _od="${ONTOLOGY_DIR:-${NEXUS_ROOT}/nexus-ontology}"
            DAC_COMPONENTS=(
                "api|${_od}/backend|VERSION|nexus-ontology-api|nexus-ontology-api|ontology-api|--ontology-api-version|ontology-${DEPLOY_ENV}-backend|deployment||ONTOLOGY_API_TAG|ONTOLOGY_API_VERSION"
                "ui|${_od}/frontend|VERSION|nexus-ontology-ui|nexus-ontology-ui|ontology-ui|--ontology-ui-version|ontology-${DEPLOY_ENV}-frontend|deployment||ONTOLOGY_UI_TAG|ONTOLOGY_UI_VERSION"
            )
            ;;
        simulator)
            DAC_PRODUCT_LABEL="Nexus Simulator (reference server)"
            DAC_IMAGES_DIR="${SCRIPT_DIR}/images/nexus-simulator"
            DAC_DESCRIPTOR="${SCRIPT_DIR}/examples/nexus-simulator-complete.yaml"
            DAC_ROLLOUT_ARGS=(--namespace nexus-simulator --capability simulator)
            DAC_NAMESPACE="nexus-simulator"
            local _sim="${SIMULATOR_DIR:-${NEXUS_ROOT}/nexus-simulator}"
            DAC_COMPONENTS=(
                "server|${_sim}|VERSION|nexus-simulator|nexus-simulator|simulator|--simulator-version|nexus-simulator|deployment||SIMULATOR_TAG|SIMULATOR_VERSION"
            )
            ;;
        *)
            dac_log_fail "Unknown product: ${product}"
            dac_log_info "Available: $(dac_list_products)"
            return 1
            ;;
    esac

    # Override namespace when explicitly set via --namespace
    [ -n "${NAMESPACE_OVERRIDE:-}" ] && DAC_NAMESPACE="$NAMESPACE_OVERRIDE"
    return 0
}

# Map generic force flags to component ids for the current product.
dac_component_force_requested() {
    local comp_id="$1"
    [ "$FORCE_ALL" = true ] && return 0
    case "$comp_id" in
        backend|api|server)
            [ "$FORCE_BACKEND" = true ] || [ "$FORCE_API" = true ] && return 0
            ;;
        frontend|ui)
            [ "$FORCE_FRONTEND" = true ] || [ "$FORCE_UI" = true ] && return 0
            ;;
        postgres)
            [ "$FORCE_POSTGRES" = true ] && return 0
            ;;
    esac
    return 1
}

dac_default_deploy_components() {
    # SRE postgres is opt-in during dev (--postgres); other products deploy all changed parts.
    case "$PRODUCT" in
        sre)
            echo "backend frontend"
            ;;
        *)
            for spec in "${DAC_COMPONENTS[@]}"; do
                dac_comp_field "$spec" 1
            done
            ;;
    esac
}

dac_validate_product_repos() {
    local spec id dir dockerfile ver_file
    for spec in "${DAC_COMPONENTS[@]}"; do
        id=$(dac_comp_field "$spec" 1)
        dir=$(dac_comp_field "$spec" 2)
        dockerfile=$(dac_comp_dockerfile "$spec")
        if [ ! -d "$dir" ] || [ ! -f "${dir}/${dockerfile}" ]; then
            dac_log_fail "${id}: Dockerfile not found at ${dir}/${dockerfile}"
            return 1
        fi
        ver_file=$(dac_comp_field "$spec" 3)
        if [ ! -f "${dir}/${ver_file}" ]; then
            dac_log_warn "${id}: ${dir}/${ver_file} missing — will create on bump"
        fi
    done
}

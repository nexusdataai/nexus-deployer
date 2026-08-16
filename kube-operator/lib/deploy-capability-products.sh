#!/bin/bash
# Product definitions for deploy-capability.sh (sourced, not executed directly).
#
# Deploy modes:
#   cr-full  — NexusCapability with BSS Magic, Cognito, SSM fixes (nexus-ai)
#   cr-lite  — Backend+frontend via operator; data plane from CR dataServices (ontology, ai-engine, …)
#   cr-single — NexusCapability backend only (simulator)

dcap_normalize_product() {
    case "$1" in
        nexus-ai|ai)              echo "nexus-ai" ;;
        ontology|nexus-ontology) echo "ontology" ;;
        ai-engine|nexus-ai-engine) echo "ai-engine" ;;
        sre|nexus-sre)            echo "sre" ;;
        simulator|nexus-simulator) echo "simulator" ;;
        local-ontology|local_ontology) echo "local-ontology" ;;
        local-nexus-ai|local_nexus_ai|local-ai) echo "local-nexus-ai" ;;
        *)                        echo "$1" ;;
    esac
}

dcap_list_products() {
    echo "nexus-ai ontology ai-engine sre simulator local-ontology local-nexus-ai"
}

dcap_load_product() {
    local product="$1"
    PRODUCT="$(dcap_normalize_product "$product")"

    case "$PRODUCT" in
        nexus-ai)
            DCP_LABEL="Nexus AI (operator CR — full stack)"
            DCP_MODE="cr-full"
            DCP_CAPABILITY_NAME="nexus-ai"
            DCP_NAMESPACE="${DCP_CAPABILITY_NAME}-${DEPLOY_ENV}"
            DCP_CAPABILITY_FILE="${SCRIPT_DIR}/examples/nexus-ai-complete.yaml"
            DCP_ECR_MODE="callsense"
            DCP_ECR_SCRIPT=(create-ecr-images.sh)
            DCP_ECR_ARGS=()
            DCP_SKIP_CREDS_DEFAULT=false
            DCP_SKIP_SSM_FIX_DEFAULT=false
            DCP_WAIT_ALB=true
            ;;
        ontology)
            DCP_LABEL="Nexus Ontology (operator CR — API + UI + data plane)"
            DCP_MODE="cr-lite"
            DCP_CAPABILITY_NAME="ontology"
            DCP_NAMESPACE="ontology-${DEPLOY_ENV}"
            DCP_CAPABILITY_FILE="${SCRIPT_DIR}/examples/nexus-ontology-complete.yaml"
            DCP_ECR_MODE="script"
            DCP_ECR_SCRIPT=(create-ecr-images.sh)
            DCP_ECR_ARGS=(--only-ontology-images)
            DCP_PRE_BUILD_UI=true
            DCP_SKIP_CREDS_DEFAULT=true
            DCP_SKIP_SSM_FIX_DEFAULT=true
            DCP_WAIT_ALB=true
            ;;
        ai-engine)
            DCP_LABEL="Nexus AI Engine (operator CR — API + UI)"
            DCP_MODE="cr-lite"
            DCP_CAPABILITY_NAME="ai-engine"
            case "$DEPLOY_ENV" in
                prod) DCP_NAMESPACE="ai-engine" ;;
                *)    DCP_NAMESPACE="ai-engine-${DEPLOY_ENV}" ;;
            esac
            DCP_CAPABILITY_FILE="${SCRIPT_DIR}/examples/nexus-ai-engine-complete.yaml"
            DCP_ECR_MODE="script"
            DCP_ECR_SCRIPT=(create-ecr-images.sh)
            DCP_ECR_ARGS=(--only-ai-engine-images)
            DCP_SKIP_CREDS_DEFAULT=true
            DCP_SKIP_SSM_FIX_DEFAULT=true
            DCP_WAIT_ALB=true
            ;;
        sre)
            DCP_LABEL="Nexus SRE (operator CR — backend + UI; postgres via app-rollout)"
            DCP_MODE="cr-lite"
            DCP_CAPABILITY_NAME="nexus-sre"
            DCP_NAMESPACE="nexus-sre"
            DCP_CAPABILITY_FILE="${SCRIPT_DIR}/examples/nexus-sre-complete.yaml"
            DCP_ECR_MODE="script"
            DCP_ECR_SCRIPT=(create-ecr-images.sh)
            DCP_ECR_ARGS=(--only-sre-images)
            DCP_SKIP_CREDS_DEFAULT=true
            DCP_SKIP_SSM_FIX_DEFAULT=true
            DCP_WAIT_ALB=false
            ;;
        simulator)
            DCP_LABEL="Nexus Simulator (operator CR — API server only)"
            DCP_MODE="cr-single"
            DCP_CAPABILITY_NAME="simulator"
            DCP_NAMESPACE="nexus-simulator"
            DCP_CAPABILITY_FILE="${SCRIPT_DIR}/examples/nexus-simulator-complete.yaml"
            DCP_ECR_MODE="script"
            DCP_ECR_SCRIPT=(create-ecr-images.sh)
            DCP_ECR_ARGS=(--only-simulator-images)
            DCP_SKIP_CREDS_DEFAULT=true
            DCP_SKIP_SSM_FIX_DEFAULT=true
            DCP_WAIT_ALB=false
            ;;
        local-ontology)
            DCP_LABEL="Nexus Ontology (local K3s — nexus-local AWS stack)"
            DCP_MODE="cr-lite"
            DCP_CAPABILITY_NAME="ontology"
            DCP_NAMESPACE="ontology-${DEPLOY_ENV}"
            DCP_CAPABILITY_FILE="${SCRIPT_DIR}/examples/nexus-ontology-local.yaml"
            DCP_ECR_MODE="script"
            DCP_ECR_SCRIPT=(create-ecr-images.sh)
            DCP_ECR_ARGS=(--only-ontology-images)
            DCP_PRE_BUILD_UI=true
            DCP_SKIP_CREDS_DEFAULT=true
            DCP_SKIP_SSM_FIX_DEFAULT=true
            DCP_SKIP_IAM_DEFAULT=true
            DCP_WAIT_ALB=false
            CLUSTER_NAME="${CLUSTER_NAME:-local-cluster}"
            ;;
        local-nexus-ai)
            DCP_LABEL="Nexus AI (local K3s — nexus-local AWS stack)"
            DCP_MODE="cr-lite"
            DCP_CAPABILITY_NAME="nexus-ai"
            DCP_NAMESPACE="nexus-ai-${DEPLOY_ENV}"
            DCP_CAPABILITY_FILE="${SCRIPT_DIR}/examples/nexus-ai-local.yaml"
            DCP_ECR_MODE="callsense"
            DCP_ECR_SCRIPT=(create-ecr-images.sh)
            DCP_ECR_ARGS=()
            DCP_SKIP_CREDS_DEFAULT=true
            DCP_SKIP_SSM_FIX_DEFAULT=true
            DCP_SKIP_IAM_DEFAULT=true
            DCP_WAIT_ALB=false
            CLUSTER_NAME="${CLUSTER_NAME:-local-cluster}"
            ;;
        *)
            dcap_log_fail "Unknown product: ${product}"
            dcap_log_info "Available: $(dcap_list_products)"
            return 1
            ;;
    esac

    [ -n "${NAMESPACE_OVERRIDE:-}" ] && DCP_NAMESPACE="$NAMESPACE_OVERRIDE"
    CAPABILITY_NAME="$DCP_CAPABILITY_NAME"
    NAMESPACE="$DCP_NAMESPACE"
    CAPABILITY_FILE="$DCP_CAPABILITY_FILE"
    return 0
}

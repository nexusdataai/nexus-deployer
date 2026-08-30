#!/bin/bash
#
# deploy-local-aws-stack.sh — Deploy shared nexus-local dev stack (Helm).
#
# Installs common infrastructure for all Nexus capabilities in one namespace:
#   MinIO, MiniStack, Scylla (DynamoDB), Trino, Redis, Mimir, Postgres (pgvector/AGE)
#
# Usage:
#   ./deploy-local-aws-stack.sh
#   ./deploy-local-aws-stack.sh --kube-context local-cluster
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KUBE_OP="$(cd "${SCRIPT_DIR}/../kube-operator" && pwd)"
CHART_DIR="${KUBE_OP}/charts/nexus-local-aws-stack"
INIT_SCRIPT="${KUBE_OP}/scripts/local_init_aws.py"
SRE_POSTGRES_DIR="$(cd "${SCRIPT_DIR}/../../nexus-sre/postgres-image" && pwd)"
AGE_PG_IMAGE="${AGE_PG_IMAGE:-nexus-sre-postgres:latest}"
NAMESPACE="nexus-local"
KUBE_CONTEXT=""
VALUES_FILE="${CHART_DIR}/values-k3s.yaml"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --kube-context) KUBE_CONTEXT="$2"; shift 2 ;;
        --namespace) NAMESPACE="$2"; shift 2 ;;
        --values) VALUES_FILE="$2"; shift 2 ;;
        --help|-h)
            cat <<'EOF'
Usage: deploy-local-aws-stack.sh [options]

Deploy the shared nexus-local stack (Helm chart nexus-local-aws-stack).

Options:
  --kube-context NAME   kubectl context (e.g. local-cluster)
  --namespace NS        Target namespace (default: nexus-local)
  --values FILE         Helm values file (default: kube-operator/charts/.../values-k3s.yaml)

Shared services (when enabled in values.yaml):
  minio-svc, ministack-svc, scylla-svc, trino-svc, redis-svc,
  mimir-svc, pgvector-svc (Postgres + pgvector + Apache AGE)

Postgres always uses ${AGE_PG_IMAGE} (built/imported into K3s if needed).

Capability CRs should set redis/mimir/postgres.enabled: false and use localEmulation.
See local-k3s/docs/K3S-LOCAL-STACK.md
EOF
            exit 0
            ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

KUBECTL=(kubectl)
if [ -n "${KUBE_CONTEXT}" ]; then
    KUBECTL+=(--context "${KUBE_CONTEXT}")
fi

if ! command -v helm >/dev/null 2>&1; then
    echo "helm is required; install from https://helm.sh" >&2
    exit 1
fi

mkdir -p "${CHART_DIR}/files"
cp "${INIT_SCRIPT}" "${CHART_DIR}/files/local_init_aws.py"

ensure_age_postgres_image() {
    if ! command -v docker >/dev/null 2>&1; then
        echo "docker is required to build/import ${AGE_PG_IMAGE}" >&2
        exit 1
    fi
    if ! docker image inspect "${AGE_PG_IMAGE}" >/dev/null 2>&1; then
        echo "Building Apache AGE Postgres image ${AGE_PG_IMAGE} (pgvector + AGE; first build takes several minutes) ..."
        docker build -t "${AGE_PG_IMAGE}" "${SRE_POSTGRES_DIR}"
    else
        echo "Using existing image ${AGE_PG_IMAGE}"
    fi
    if command -v k3s >/dev/null 2>&1; then
        echo "Importing ${AGE_PG_IMAGE} into K3s containerd ..."
        if [ "$(id -u)" -eq 0 ]; then
            docker save "${AGE_PG_IMAGE}" | k3s ctr -n k8s.io images import -
        else
            docker save "${AGE_PG_IMAGE}" | sudo k3s ctr -n k8s.io images import -
        fi
    else
        echo "k3s CLI not found — assuming the runtime can see Docker images" >&2
    fi
}

ensure_age_postgres_image

# Completed Jobs are immutable — remove before upgrade so Helm can recreate them.
"${KUBECTL[@]}" delete job nexus-local-init postgres-init-extensions -n "${NAMESPACE}" --ignore-not-found 2>/dev/null || true

echo "Installing Helm chart nexus-local-aws-stack (Postgres=${AGE_PG_IMAGE}) ..."
helm upgrade --install nexus-local-aws "${CHART_DIR}" \
    -n "${NAMESPACE}" --create-namespace \
    -f "${VALUES_FILE}" \
    --set postgres.image="${AGE_PG_IMAGE}" \
    --set postgres.imagePullPolicy=IfNotPresent \
    ${KUBE_CONTEXT:+--kube-context "$KUBE_CONTEXT"}

echo "Waiting for core pods ..."
for label in app=minio app=scylla app=ministack app=redis; do
    "${KUBECTL[@]}" wait --for=condition=ready pod -l "${label}" -n "${NAMESPACE}" --timeout=600s 2>/dev/null || true
done

MIMIR_ENABLED=$(helm get values nexus-local-aws -n "${NAMESPACE}" ${KUBE_CONTEXT:+--kube-context "$KUBE_CONTEXT"} -o json 2>/dev/null \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print('true' if d.get('mimir',{}).get('enabled', True) else 'false')" 2>/dev/null || echo "true")
POSTGRES_ENABLED=$(helm get values nexus-local-aws -n "${NAMESPACE}" ${KUBE_CONTEXT:+--kube-context "$KUBE_CONTEXT"} -o json 2>/dev/null \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print('true' if d.get('postgres',{}).get('enabled', True) else 'false')" 2>/dev/null || echo "true")

if [ "${MIMIR_ENABLED}" = "true" ]; then
    echo "Waiting for shared Mimir ..."
    "${KUBECTL[@]}" wait --for=condition=ready pod -l app=mimir -n "${NAMESPACE}" --timeout=600s 2>/dev/null || true
fi

if [ "${POSTGRES_ENABLED}" = "true" ]; then
    echo "Waiting for shared Postgres (pgvector + Apache AGE) ..."
    "${KUBECTL[@]}" wait --for=condition=ready pod -l app=pgvector -n "${NAMESPACE}" --timeout=600s
fi

echo "Waiting for AWS resource init Job ..."
"${KUBECTL[@]}" wait --for=condition=complete job/nexus-local-init -n "${NAMESPACE}" --timeout=600s || {
    echo "Init job logs:"
    "${KUBECTL[@]}" logs -n "${NAMESPACE}" job/nexus-local-init --tail=100 || true
    exit 1
}

if [ "${POSTGRES_ENABLED}" = "true" ]; then
    echo "Waiting for Postgres extension init Job (vector + Apache AGE) ..."
    "${KUBECTL[@]}" wait --for=condition=complete job/postgres-init-extensions -n "${NAMESPACE}" --timeout=600s || {
        echo "Postgres init job logs:"
        "${KUBECTL[@]}" logs -n "${NAMESPACE}" job/postgres-init-extensions --tail=80 || true
        exit 1
    }
    echo "Confirming Apache AGE extension ..."
    AGE_OK="$("${KUBECTL[@]}" exec -n "${NAMESPACE}" pgvector-0 -- \
        env PGPASSWORD=nexus psql -U nexus -d ontology_cp -tAc \
        "SELECT extname FROM pg_extension WHERE extname = 'age';" 2>/dev/null | tr -d '[:space:]')"
    if [ "${AGE_OK}" != "age" ]; then
        echo "Apache AGE is not enabled on pgvector-0 (got '${AGE_OK}')" >&2
        exit 1
    fi
    echo "Apache AGE is enabled"
fi

echo ""
echo "nexus-local shared stack deployed in namespace ${NAMESPACE}"
echo "  Verify: ${SCRIPT_DIR}/tests/verify-local-stack.sh ${KUBE_CONTEXT:+--kube-context $KUBE_CONTEXT}"
echo "  Docs:   ${SCRIPT_DIR}/docs/K3S-LOCAL-STACK.md"

#!/bin/bash
# Deploy Nexus capabilities to local K3s (build + import + rollout).
set -euo pipefail
export KUBECONFIG="${KUBECONFIG:-/opt/mycode/nexus/nexus-deployer/aws-login/.kube/config}"
export CLUSTER_NAME=local-cluster
KO="/opt/mycode/nexus/nexus-deployer/kube-operator"
COMMON=(--env local --cluster local-cluster --all --no-commit)

for product in ontology ai-engine simulator; do
  echo "========== Deploying ${product} =========="
  (cd "$KO" && ./deploy-app-changes.sh "$product" "${COMMON[@]}")
done

echo "========== Building SRE images =========="
(cd "$KO" && ./deploy-app-changes.sh sre --env local --cluster local-cluster --backend --frontend --no-commit)

BE_TAG=$(grep SRE_BACKEND_TAG "$KO/images/nexus-sre/versions.env" | cut -d= -f2)
UI_TAG=$(grep SRE_UI_TAG "$KO/images/nexus-sre/versions.env" | cut -d= -f2)

echo "========== Helm install nexus-sre (${BE_TAG} / ${UI_TAG}) =========="
helm upgrade --install nexus-sre /opt/mycode/nexus/nexus-sre/helm/nexus-sre \
  -n nexus-sre --create-namespace \
  -f /opt/mycode/nexus/nexus-deployer/local-k3s/nexus-sre-values-local.yaml \
  --kube-context local-cluster \
  --set "image.backend.tag=${BE_TAG}" \
  --set "image.ui.tag=${UI_TAG}" \
  --set "image.backend.repository=nexus-sre-backend" \
  --set "image.ui.repository=nexus-sre-ui"

kubectl --context local-cluster -n nexus-sre rollout status deployment/nexus-sre-backend --timeout=600s || true
kubectl --context local-cluster -n nexus-sre rollout status deployment/nexus-sre-ui --timeout=600s || true

echo "========== Done =========="

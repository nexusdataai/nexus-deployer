#!/bin/bash
#
# Setup Fluent Bit for CloudWatch Log Shipping
#
# Ships all pod stdout/stderr from the EKS cluster to CloudWatch Logs.
# Reuses the existing app IAM role (no new IAM role needed) by deploying
# Fluent Bit in the capability namespace where the app role trust allows
# any service account (system:serviceaccount:nexus-ai-{env}:*).
#
# Usage:
#   ./setup-fluentbit.sh setup       # Install Fluent Bit DaemonSet
#   ./setup-fluentbit.sh verify      # Check Fluent Bit status
#   ./setup-fluentbit.sh teardown    # Remove Fluent Bit
#
# Reads: .env.local (ENV, Cluster)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SCRIPT_DIR}/lib/init-kube-env.sh"

_ENVLOCAL="${SCRIPT_DIR}/.env.local"
if [ -f "$_ENVLOCAL" ]; then
    _ENV=$(grep '^ENV[[:space:]]*=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true)
    _CLUSTER=$(grep '^Cluster[[:space:]]*=' "$_ENVLOCAL" 2>/dev/null | cut -d= -f2- | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true)
fi

DEPLOY_ENV="${DEPLOY_ENV:-${_ENV:-prod}}"
CLUSTER_NAME="${CLUSTER_NAME:-${_CLUSTER:-nexus-test}}"
AWS_PROFILE="${AWS_PROFILE:-external-access}"
REGION="${REGION:-us-east-1}"
NAMESPACE="nexus-ai-${DEPLOY_ENV}"
SA_NAME="fluent-bit"
APP_ROLE_NAME="nexus-ai-${DEPLOY_ENV}-app-role"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --profile "${AWS_PROFILE}" 2>/dev/null || echo "")
if [ -z "$ACCOUNT_ID" ]; then
    echo "Failed to get AWS account ID. Check credentials."
    exit 1
fi

LOG_GROUP="/nexus/nexus-ai/${DEPLOY_ENV}"

show_help() {
    echo "Usage: $0 {setup|verify|teardown}"
    echo ""
    echo "Commands:"
    echo "  setup      Install Fluent Bit DaemonSet for CloudWatch log shipping"
    echo "  verify     Check Fluent Bit pod status and log delivery"
    echo "  teardown   Remove Fluent Bit from the cluster"
}

do_setup() {
    echo "================================================"
    echo "  Setting up Fluent Bit -> CloudWatch"
    echo "================================================"
    echo ""
    echo "Environment: ${DEPLOY_ENV}"
    echo "Cluster:     ${CLUSTER_NAME}"
    echo "Log Group:   ${LOG_GROUP}"
    echo "Region:      ${REGION}"
    echo ""

    nexus_eks_update_kubeconfig "${CLUSTER_NAME}" "${REGION}" "${AWS_PROFILE}" 2>/dev/null

    echo "Creating Fluent Bit ConfigMap..."
    kubectl apply -f - <<CFGEOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: fluent-bit-config
  namespace: ${NAMESPACE}
data:
  fluent-bit.conf: |
    [SERVICE]
        Flush         5
        Log_Level     info
        Daemon        off
        Parsers_File  parsers.conf

    [INPUT]
        Name              tail
        Tag               kube.*
        Path              /var/log/containers/*_nexus-ai-${DEPLOY_ENV}_*.log
        Parser            docker
        DB                /var/fluent-bit/state/flb_container.db
        Mem_Buf_Limit     50MB
        Skip_Long_Lines   On
        Refresh_Interval  10

    [INPUT]
        Name              tail
        Tag               operator.*
        Path              /var/log/containers/*_nexus-system_*.log
        Parser            docker
        DB                /var/fluent-bit/state/flb_operator.db
        Mem_Buf_Limit     10MB
        Skip_Long_Lines   On
        Refresh_Interval  10

    [FILTER]
        Name                kubernetes
        Match               kube.*
        Kube_URL            https://kubernetes.default.svc:443
        Kube_CA_File        /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
        Kube_Token_File     /var/run/secrets/kubernetes.io/serviceaccount/token
        Kube_Tag_Prefix     kube.var.log.containers.
        Merge_Log           On
        Keep_Log            Off
        K8S-Logging.Parser  On
        K8S-Logging.Exclude Off

    [FILTER]
        Name                kubernetes
        Match               operator.*
        Kube_URL            https://kubernetes.default.svc:443
        Kube_CA_File        /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
        Kube_Token_File     /var/run/secrets/kubernetes.io/serviceaccount/token
        Merge_Log           On
        Keep_Log            Off

    [OUTPUT]
        Name                cloudwatch_logs
        Match               kube.*
        region              ${REGION}
        log_group_name      ${LOG_GROUP}
        log_stream_prefix   app/
        auto_create_group   true
        log_retention_days  30

    [OUTPUT]
        Name                cloudwatch_logs
        Match               operator.*
        region              ${REGION}
        log_group_name      ${LOG_GROUP}/operator
        log_stream_prefix   operator/
        auto_create_group   true
        log_retention_days  30

  parsers.conf: |
    [PARSER]
        Name        docker
        Format      json
        Time_Key    time
        Time_Format %Y-%m-%dT%H:%M:%S.%LZ
        Time_Keep   On

    [PARSER]
        Name        syslog
        Format      regex
        Regex       ^\<(?<pri>[0-9]+)\>(?<time>[^ ]* {1,2}[^ ]* [^ ]*) (?<host>[^ ]*) (?<ident>[a-zA-Z0-9_\/\.\-]*)(?:\[(?<pid>[0-9]+)\])?(?:[^\:]*\:)? *(?<message>.*)$
        Time_Key    time
        Time_Format %b %d %H:%M:%S
CFGEOF

    echo "Creating ServiceAccount with IRSA annotation (reuses app role)..."
    kubectl apply -f - <<SAEOF
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ${SA_NAME}
  namespace: ${NAMESPACE}
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::${ACCOUNT_ID}:role/${APP_ROLE_NAME}
SAEOF

    echo "Creating ClusterRole and Binding..."
    kubectl apply -f - <<RBACEOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: fluent-bit-read
rules:
  - apiGroups: [""]
    resources: ["namespaces", "pods"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: fluent-bit-read
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: fluent-bit-read
subjects:
  - kind: ServiceAccount
    name: ${SA_NAME}
    namespace: ${NAMESPACE}
RBACEOF

    echo "Deploying Fluent Bit DaemonSet..."
    kubectl apply -f - <<DSEOF
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: fluent-bit
  namespace: ${NAMESPACE}
  labels:
    app: fluent-bit
spec:
  selector:
    matchLabels:
      app: fluent-bit
  template:
    metadata:
      labels:
        app: fluent-bit
    spec:
      serviceAccountName: ${SA_NAME}
      tolerations:
        - key: node-role.kubernetes.io/master
          operator: Exists
          effect: NoSchedule
      containers:
        - name: fluent-bit
          image: amazon/aws-for-fluent-bit:latest
          resources:
            limits:
              cpu: 200m
              memory: 256Mi
            requests:
              cpu: 50m
              memory: 64Mi
          volumeMounts:
            - name: varlog
              mountPath: /var/log
              readOnly: true
            - name: varlibdockercontainers
              mountPath: /var/lib/docker/containers
              readOnly: true
            - name: config
              mountPath: /fluent-bit/etc/
            - name: state
              mountPath: /var/fluent-bit/state
      volumes:
        - name: varlog
          hostPath:
            path: /var/log
        - name: varlibdockercontainers
          hostPath:
            path: /var/lib/docker/containers
        - name: config
          configMap:
            name: fluent-bit-config
        - name: state
          hostPath:
            path: /var/fluent-bit/state
            type: DirectoryOrCreate
DSEOF

    echo ""
    echo "Waiting for Fluent Bit pods..."
    kubectl rollout status daemonset/fluent-bit -n "${NAMESPACE}" --timeout=120s || echo "Still starting..."

    echo ""
    kubectl get pods -n "${NAMESPACE}" -l app=fluent-bit
    echo ""
    echo "================================================"
    echo "  Fluent Bit setup complete"
    echo "================================================"
    echo ""
    echo "Log group: ${LOG_GROUP}"
    echo "Streams:   app/<pod-name>, operator/<pod-name>"
    echo ""
    echo "View logs:"
    echo "  aws logs tail ${LOG_GROUP} --follow --region ${REGION}"
    echo ""
    echo "IAM: Reusing existing app role '${APP_ROLE_NAME}' (no new role needed)"
}

do_verify() {
    echo "Fluent Bit Status:"
    echo ""
    kubectl get daemonset fluent-bit -n "${NAMESPACE}" 2>/dev/null || { echo "Fluent Bit not installed."; exit 1; }
    echo ""
    kubectl get pods -n "${NAMESPACE}" -l app=fluent-bit
    echo ""

    echo "Recent Fluent Bit logs:"
    POD=$(kubectl get pods -n "${NAMESPACE}" -l app=fluent-bit -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    if [ -n "$POD" ]; then
        kubectl logs "$POD" -n "${NAMESPACE}" --tail=20
    fi
    echo ""

    echo "CloudWatch Log Groups:"
    aws logs describe-log-groups --log-group-name-prefix "${LOG_GROUP}" \
        --region "${REGION}" --profile "${AWS_PROFILE}" \
        --query 'logGroups[].{Name:logGroupName,Retention:retentionInDays,Size:storedBytes}' \
        --output table 2>/dev/null || echo "Could not query CloudWatch (check credentials)"
}

do_teardown() {
    echo "Removing Fluent Bit..."
    kubectl delete daemonset fluent-bit -n "${NAMESPACE}" 2>/dev/null || true
    kubectl delete configmap fluent-bit-config -n "${NAMESPACE}" 2>/dev/null || true
    kubectl delete clusterrolebinding fluent-bit-read 2>/dev/null || true
    kubectl delete clusterrole fluent-bit-read 2>/dev/null || true
    kubectl delete serviceaccount "${SA_NAME}" -n "${NAMESPACE}" 2>/dev/null || true
    echo "Fluent Bit removed. Namespace '${NAMESPACE}' preserved."
}

case "${1:-}" in
    setup)    do_setup ;;
    verify)   do_verify ;;
    teardown) do_teardown ;;
    -h|--help|help) show_help ;;
    *) show_help; exit 1 ;;
esac

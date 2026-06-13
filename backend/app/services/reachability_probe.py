"""
In-cluster reachability probe (pipeline step 7).

Spawns a one-shot Pod in the capability namespace using the per-capability
ServiceAccount (so IRSA reflects what the real workload sees), runs the
embedded DNS+TLS probe from kube-operator/inspect-capability.sh:1462-1540,
captures the JSON output via `read_namespaced_pod_log`, and cleans up.

The Pod runs `python:3.12-slim` with the probe script passed via `args`,
so we don't need ConfigMaps or vendored scripts. Total runtime ~10-30 s
(dominated by per-service TLS handshakes).
"""
import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from app.models.eks_pipeline import (
    PipelineCheck,
    ReachabilityProbeRow,
    ReachabilityReport,
)

logger = logging.getLogger(__name__)


# Embedded probe script. Mirrors inspect-capability.sh:1480-1540.
# Output is one JSON object per line on stdout for easy parsing.
PROBE_SCRIPT = r"""
import json
import socket
import ssl
import ipaddress
import os
import sys

REGION = os.environ.get('AWS_REGION') or os.environ.get('AWS_DEFAULT_REGION') or 'us-east-1'

SERVICES = {
    'sts':            f'sts.{REGION}.amazonaws.com',
    'ssm':            f'ssm.{REGION}.amazonaws.com',
    'secretsmanager': f'secretsmanager.{REGION}.amazonaws.com',
    'dynamodb':       f'dynamodb.{REGION}.amazonaws.com',
    's3':             f's3.{REGION}.amazonaws.com',
    'glue':           f'glue.{REGION}.amazonaws.com',
    'athena':         f'athena.{REGION}.amazonaws.com',
    'cognito-idp':    f'cognito-idp.{REGION}.amazonaws.com',
    'logs':           f'logs.{REGION}.amazonaws.com',
    'ecr':            f'api.ecr.{REGION}.amazonaws.com',
    'eks':            f'eks.{REGION}.amazonaws.com',
    'events':         f'events.{REGION}.amazonaws.com',
    'ec2':            f'ec2.{REGION}.amazonaws.com',
}


def detect_cert_owner(sans, svc_name):
    for san in sans:
        if f'.{svc_name}.' in san or san.startswith(f'{svc_name}.') or f'.{svc_name}.{REGION}.vpce.' in san:
            return svc_name
        for s in SERVICES:
            if f'.{s}.' in san or san.startswith(f'{s}.'):
                return s
    return 'unknown'


for svc, host in SERVICES.items():
    row = {'service': svc, 'host': host, 'ip': None, 'route': 'UNKNOWN', 'tls_status': '', 'detail': ''}
    try:
        results = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
        ips = sorted(set(r[4][0] for r in results))
        is_private = all(ipaddress.ip_address(ip).is_private for ip in ips)
        row['ip'] = ips[0]
        row['route'] = 'VPCE' if is_private else 'PUBLIC'
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with socket.create_connection((ips[0], 443), timeout=5) as sock:
                with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                    cert = ssock.getpeercert()
                    sans = [e[1] for e in (cert or {}).get('subjectAltName', []) if e[0] == 'DNS']
                    row['tls_status'] = 'OK'
                    if is_private and sans:
                        owner = detect_cert_owner(sans, svc)
                        if owner != svc and owner != 'unknown':
                            row['detail'] = f'CROSS:{owner}'
        except Exception as e:
            row['tls_status'] = 'TLS_FAIL'
            row['detail'] = str(e)[:120]
    except Exception as e:
        row['route'] = 'DNS_FAIL'
        row['detail'] = str(e)[:120]
    print(json.dumps(row), flush=True)

# Optional IAM smoke probe: does sts:GetCallerIdentity work?
try:
    import boto3
    sts = boto3.client('sts', region_name=REGION)
    ident = sts.get_caller_identity()
    print(json.dumps({
        '__iam__': True,
        'arn': ident.get('Arn'),
        'account': ident.get('Account'),
        'region': REGION,
    }), flush=True)
except Exception as e:
    print(json.dumps({'__iam__': True, 'error': str(e)[:200]}), flush=True)
"""


class ReachabilityProbe:
    """Spawn a probe Pod, capture results, clean up."""

    PROBE_IMAGE = "python:3.12-slim"
    PROBE_TIMEOUT_SECONDS = 90

    def __init__(self, core_v1, region: str):
        self.core_v1 = core_v1
        self.region = region

    def _service_account_name(self, capability_name: str, environment: str) -> str:
        # Mirrors operator's ResourceNaming.kubernetes_service_account('app').
        # Kept private to avoid pulling the operator package in.
        return f"{capability_name}-{environment}-app-sa"

    def _pod_name(self, capability_name: str, environment: str) -> str:
        # Use a timestamped suffix so retries don't collide.
        return f"nexus-reachability-probe-{capability_name}-{environment}-{int(time.time())}"

    def build_pod_spec(
        self,
        pod_name: str,
        namespace: str,
        service_account: str,
    ) -> Dict[str, Any]:
        """Inline Pod manifest. Avoids external manifest dependency."""
        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": pod_name,
                "namespace": namespace,
                "labels": {
                    "app.kubernetes.io/managed-by": "nexus-deployer",
                    "nexus.ai/diagnostic": "reachability-probe",
                },
            },
            "spec": {
                "restartPolicy": "Never",
                "serviceAccountName": service_account,
                "containers": [{
                    "name": "probe",
                    "image": self.PROBE_IMAGE,
                    "command": ["/bin/sh", "-lc"],
                    "args": [
                        # Install boto3 quietly, then run the probe.
                        "pip install --quiet --no-cache-dir boto3==1.34.131 botocore==1.34.131 "
                        ">/dev/null 2>&1 || true; "
                        "python -c \"" + PROBE_SCRIPT.replace('"', '\\"').replace("$", "\\$") + "\""
                    ],
                    "env": [
                        {"name": "AWS_REGION", "value": self.region},
                        {"name": "AWS_DEFAULT_REGION", "value": self.region},
                    ],
                    "resources": {
                        "requests": {"cpu": "100m", "memory": "128Mi"},
                        "limits": {"cpu": "500m", "memory": "512Mi"},
                    },
                }],
            },
        }

    async def run(
        self,
        namespace: str,
        capability_name: str,
        environment: str,
    ) -> ReachabilityReport:
        from kubernetes.client.rest import ApiException

        sa_name = self._service_account_name(capability_name, environment)
        pod_name = self._pod_name(capability_name, environment)
        pod_spec = self.build_pod_spec(pod_name, namespace, sa_name)

        cluster_name = ""  # surfaced in the report by the orchestrator
        rows: List[ReachabilityProbeRow] = []
        iam_results: Dict[str, Any] = {}

        try:
            self.core_v1.create_namespaced_pod(namespace=namespace, body=pod_spec)
        except ApiException as e:
            return ReachabilityReport(
                cluster_name=cluster_name,
                namespace=namespace,
                pod_name=pod_name,
                overall="fail",
                rows=[],
                iam_results={"error": f"create_namespaced_pod failed: {e}"},
            )

        try:
            await self._wait_for_pod_terminal(namespace, pod_name)
            log_text = self.core_v1.read_namespaced_pod_log(
                name=pod_name, namespace=namespace
            )
        except Exception as e:
            iam_results["error"] = f"Pod did not produce logs in time: {e}"
            log_text = ""
        finally:
            # Best-effort cleanup; ignore 404s if the pod was already collected.
            try:
                self.core_v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
            except Exception as ce:
                logger.debug(f"probe cleanup ignored: {ce}")

        # Parse one-JSON-per-line output.
        for line in (log_text or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("__iam__"):
                iam_results = {k: v for k, v in obj.items() if k != "__iam__"}
                continue
            rows.append(ReachabilityProbeRow(
                service=obj.get("service", ""),
                host=obj.get("host", ""),
                ip=obj.get("ip"),
                route=obj.get("route", "UNKNOWN"),  # type: ignore[arg-type]
                tls_status=obj.get("tls_status", ""),
                detail=obj.get("detail", ""),
            ))

        if not rows:
            return ReachabilityReport(
                cluster_name=cluster_name,
                namespace=namespace,
                pod_name=pod_name,
                overall="fail",
                rows=[],
                iam_results=iam_results or {"error": "no probe output captured"},
            )

        # Verdict: fail if any DNS_FAIL; warn if any TLS_FAIL or PUBLIC route
        # for a service that should be VPC-private; pass otherwise.
        has_dns_fail = any(r.route == "DNS_FAIL" for r in rows)
        has_tls_fail = any(r.tls_status == "TLS_FAIL" for r in rows)
        all_vpce = all(r.route == "VPCE" for r in rows if r.route != "DNS_FAIL")
        if has_dns_fail:
            overall = "fail"
        elif has_tls_fail or not all_vpce:
            overall = "warn"
        else:
            overall = "pass"

        return ReachabilityReport(
            cluster_name=cluster_name,
            namespace=namespace,
            pod_name=pod_name,
            overall=overall,  # type: ignore[arg-type]
            rows=rows,
            iam_results=iam_results,
        )

    async def _wait_for_pod_terminal(self, namespace: str, pod_name: str):
        elapsed = 0
        poll = 2
        while elapsed < self.PROBE_TIMEOUT_SECONDS:
            await asyncio.sleep(poll)
            elapsed += poll
            try:
                pod = self.core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            except Exception as e:
                logger.debug(f"probe pod read failed: {e}")
                continue
            phase = (pod.status.phase if pod.status else "") or ""
            if phase in ("Succeeded", "Failed"):
                return
        raise TimeoutError(f"Probe pod {pod_name} did not terminate in {self.PROBE_TIMEOUT_SECONDS}s")

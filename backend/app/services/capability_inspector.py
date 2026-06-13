"""
Full capability inspection (pipeline step 10).

Ports the 17 sections of kube-operator/inspect-capability.sh into Python
methods that return `InspectionSection` rows. Each section is independent
and runs in parallel where it is safe to do so. Failures in one section
never block the others; partial reports are still useful.

Sections:
  1. Kubernetes resources
  2. Service versions
  3. DynamoDB tables
  4. S3 buckets
  5. Glue catalog
  6. Athena workgroup
  7. Athena deep diagnostics
  8. WXCC connectivity (in-cluster exec)
  9. Licensing AWS IoT endpoints (in-cluster exec)
  10. Call Processing pipeline (in-cluster exec)
  11. App permissions + VPC endpoints (in-cluster exec)
  12. Call DB Doctor (in-cluster exec)
  13. SSM Parameters
  14. Secrets Manager
  15. IAM Roles
  16. Cognito
  17. ALB Load Balancers
"""
import asyncio
import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.models.eks_pipeline import (
    CapabilityInspectionReport,
    InspectionSection,
)

logger = logging.getLogger(__name__)


# ---------- helpers --------------------------------------------------------

def _swallow(fn: Callable[[], Any], default: Any = None) -> Any:
    try:
        return fn()
    except Exception as e:
        logger.debug(f"swallowed: {e}")
        return default


def _section_status(rows: List[Dict[str, Any]], failure_keys: Tuple[str, ...] = ("error",)) -> str:
    """Heuristic: any row with `error` set => fail; if zero rows => warn; else pass."""
    if not rows:
        return "warn"
    for r in rows:
        if any(r.get(k) for k in failure_keys):
            return "fail"
    return "pass"


# ---------- main service ---------------------------------------------------

class CapabilityInspector:
    """One-shot full inspection of a deployed NexusCapability.

    Constructed per-call by the orchestrator; holds AWS clients tied to
    the wizard's session. All methods are synchronous boto3/k8s calls
    wrapped in `loop.run_in_executor` by the orchestrator so the FastAPI
    thread does not block.
    """

    def __init__(
        self,
        core_v1,
        apps_v1,
        custom,
        eks_client,
        iam_client,
        sts_client,
        boto3_session,
        region: str,
        cluster_name: str,
        namespace: str,
        capability_name: str,
        environment: str,
        cr_name: str,
        account_id: Optional[str] = None,
    ):
        self.core_v1 = core_v1
        self.apps_v1 = apps_v1
        self.custom = custom
        self.eks = eks_client
        self.iam = iam_client
        self.sts = sts_client
        self.boto = boto3_session
        self.region = region
        self.cluster_name = cluster_name
        self.namespace = namespace
        self.capability_name = capability_name
        self.environment = environment
        self.cr_name = cr_name
        self.account_id = account_id or _swallow(
            lambda: sts_client.get_caller_identity()["Account"], default=""
        )
        self._naming = ResourceNamingShim(capability_name, environment, self.account_id or "")

    # =================================================================
    #                        SECTIONS 1-2: K8S
    # =================================================================
    def section_kubernetes_resources(self) -> InspectionSection:
        rows: List[Dict[str, Any]] = []
        ns = self.namespace

        try:
            for d in self.apps_v1.list_namespaced_deployment(ns).items:
                rows.append({
                    "kind": "Deployment", "name": d.metadata.name,
                    "ready": (d.status.ready_replicas or 0) if d.status else 0,
                    "desired": (d.spec.replicas or 1) if d.spec else 1,
                })
        except Exception as e:
            rows.append({"kind": "Deployment", "error": str(e)})

        try:
            for s in self.apps_v1.list_namespaced_stateful_set(ns).items:
                rows.append({
                    "kind": "StatefulSet", "name": s.metadata.name,
                    "ready": (s.status.ready_replicas or 0) if s.status else 0,
                    "desired": (s.spec.replicas or 1) if s.spec else 1,
                })
        except Exception:
            pass

        try:
            for p in self.core_v1.list_namespaced_pod(ns).items:
                phase = p.status.phase if p.status else ""
                restarts = sum(
                    (cs.restart_count or 0)
                    for cs in (p.status.container_statuses or [])
                    if p.status and p.status.container_statuses
                )
                waiting = ""
                for cs in (p.status.container_statuses or []) if p.status else []:
                    if cs.state and cs.state.waiting:
                        waiting = cs.state.waiting.reason or ""
                        break
                rows.append({
                    "kind": "Pod", "name": p.metadata.name,
                    "phase": phase, "restarts": restarts,
                    "waiting_reason": waiting,
                })
        except Exception as e:
            rows.append({"kind": "Pod", "error": str(e)})

        try:
            for s in self.core_v1.list_namespaced_service(ns).items:
                rows.append({
                    "kind": "Service", "name": s.metadata.name,
                    "type": s.spec.type if s.spec else "",
                    "cluster_ip": s.spec.cluster_ip if s.spec else "",
                })
        except Exception:
            pass

        try:
            from kubernetes import client as k8s_client
            net_v1 = k8s_client.NetworkingV1Api(self.core_v1.api_client)
            for ing in net_v1.list_namespaced_ingress(ns).items:
                hosts: List[str] = []
                if ing.status and ing.status.load_balancer and ing.status.load_balancer.ingress:
                    for entry in ing.status.load_balancer.ingress:
                        if entry.hostname:
                            hosts.append(entry.hostname)
                rows.append({
                    "kind": "Ingress", "name": ing.metadata.name,
                    "class": ing.spec.ingress_class_name if ing.spec else "",
                    "hostnames": hosts,
                })
        except Exception:
            pass

        return InspectionSection(
            name="k8s_resources",
            label="Kubernetes Resources",
            status=_section_status(rows),
            summary=f"{len(rows)} workload + service + ingress objects in {ns}",
            rows=rows,
        )

    def section_service_versions(self) -> InspectionSection:
        rows: List[Dict[str, Any]] = []
        try:
            for d in self.apps_v1.list_namespaced_deployment(self.namespace).items:
                if not d.spec or not d.spec.template or not d.spec.template.spec:
                    continue
                for c in d.spec.template.spec.containers or []:
                    rows.append({
                        "deployment": d.metadata.name,
                        "container": c.name,
                        "image": c.image or "",
                    })
        except Exception as e:
            rows.append({"error": str(e)})
        return InspectionSection(
            name="service_versions",
            label="Service Versions",
            status=_section_status(rows),
            summary=f"{len(rows)} container image(s)",
            rows=rows,
        )

    # =================================================================
    #                  SECTIONS 3-7: AWS DATA SERVICES
    # =================================================================
    def section_dynamodb(self) -> InspectionSection:
        rows: List[Dict[str, Any]] = []
        ddb = _swallow(lambda: self.boto.client("dynamodb", region_name=self.region))
        if ddb is None:
            return InspectionSection(
                name="dynamodb", label="DynamoDB Tables",
                status="fail", summary="boto3 dynamodb client failed", rows=[],
            )
        prefix = f"{self.capability_name}-{self.environment}"
        try:
            paginator = ddb.get_paginator("list_tables")
            for page in paginator.paginate():
                for tbl in page.get("TableNames", []):
                    if not tbl.startswith(prefix):
                        continue
                    desc = _swallow(lambda t=tbl: ddb.describe_table(TableName=t)["Table"])
                    rows.append({
                        "name": tbl,
                        "status": (desc or {}).get("TableStatus") if desc else "Unknown",
                        "items": (desc or {}).get("ItemCount", 0) if desc else 0,
                    })
        except Exception as e:
            rows.append({"error": f"list_tables failed: {e}"})
        return InspectionSection(
            name="dynamodb", label="DynamoDB Tables",
            status=_section_status(rows),
            summary=f"{sum(1 for r in rows if 'name' in r)} tables for {prefix}",
            rows=rows,
        )

    def section_s3(self) -> InspectionSection:
        rows: List[Dict[str, Any]] = []
        s3 = _swallow(lambda: self.boto.client("s3", region_name=self.region))
        if s3 is None:
            return InspectionSection(
                name="s3", label="S3 Buckets",
                status="fail", summary="boto3 s3 client failed", rows=[],
            )
        prefix = f"{self.capability_name}-{self.environment}-"
        try:
            for b in s3.list_buckets().get("Buckets", []):
                name = b.get("Name", "")
                if not name.startswith(prefix):
                    continue
                tagging = _swallow(lambda n=name: s3.get_bucket_tagging(Bucket=n).get("TagSet", []), default=[])
                rows.append({
                    "name": name,
                    "created": str(b.get("CreationDate", "")),
                    "tags": {t["Key"]: t["Value"] for t in (tagging or [])},
                })
        except Exception as e:
            rows.append({"error": f"list_buckets failed: {e}"})
        return InspectionSection(
            name="s3", label="S3 Buckets",
            status=_section_status(rows),
            summary=f"{sum(1 for r in rows if 'name' in r)} buckets for {prefix}*",
            rows=rows,
        )

    def section_glue(self) -> InspectionSection:
        rows: List[Dict[str, Any]] = []
        glue = _swallow(lambda: self.boto.client("glue", region_name=self.region))
        if glue is None:
            return InspectionSection(
                name="glue", label="Glue Catalog",
                status="fail", summary="boto3 glue client failed", rows=[],
            )
        db_name = (
            f"{self.capability_name}_{self.environment}_db"
            .replace("-", "_")
        )
        try:
            db = glue.get_database(Name=db_name)["Database"]
            rows.append({
                "name": db_name, "exists": True,
                "location": db.get("LocationUri", ""),
                "description": db.get("Description", ""),
            })
            tables = _swallow(
                lambda: glue.get_tables(DatabaseName=db_name).get("TableList", []),
                default=[],
            ) or []
            for t in tables:
                rows.append({
                    "name": t.get("Name"), "kind": "table",
                    "type": t.get("TableType"),
                    "input_format": (t.get("StorageDescriptor") or {}).get("InputFormat", ""),
                })
        except Exception as e:
            rows.append({"name": db_name, "exists": False, "error": str(e)})
        return InspectionSection(
            name="glue", label="Glue Catalog",
            status=_section_status(rows),
            summary=f"Database {db_name}",
            rows=rows,
        )

    def section_athena_workgroup(self) -> InspectionSection:
        rows: List[Dict[str, Any]] = []
        athena = _swallow(lambda: self.boto.client("athena", region_name=self.region))
        if athena is None:
            return InspectionSection(
                name="athena_wg", label="Athena Workgroup",
                status="fail", summary="boto3 athena client failed", rows=[],
            )
        try:
            wg = athena.get_work_group(WorkGroup="primary")["WorkGroup"]
            cfg = (wg.get("Configuration") or {}).get("ResultConfiguration") or {}
            rows.append({
                "name": wg.get("Name"),
                "state": wg.get("State"),
                "result_location": cfg.get("OutputLocation", ""),
                "engine_version": (
                    (wg.get("Configuration") or {}).get("EngineVersion") or {}
                ).get("EffectiveEngineVersion", ""),
            })
        except Exception as e:
            rows.append({"error": str(e)})
        return InspectionSection(
            name="athena_wg", label="Athena Workgroup",
            status=_section_status(rows),
            summary="primary workgroup",
            rows=rows,
        )

    def section_athena_deep(self) -> InspectionSection:
        """End-to-end smoke: SHOW DATABASES against the capability's DB."""
        rows: List[Dict[str, Any]] = []
        athena = _swallow(lambda: self.boto.client("athena", region_name=self.region))
        if athena is None:
            return InspectionSection(
                name="athena_deep", label="Athena Deep Diagnostics",
                status="fail", summary="boto3 athena client failed", rows=[],
            )
        db_name = f"{self.capability_name}_{self.environment}_db".replace("-", "_")
        try:
            start = athena.start_query_execution(
                QueryString=f"SHOW TABLES IN `{db_name}`",
                QueryExecutionContext={"Database": db_name},
                WorkGroup="primary",
            )
            qid = start["QueryExecutionId"]
            # Poll up to ~20 s for completion
            import time
            state = "RUNNING"
            for _ in range(20):
                time.sleep(1)
                qe = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]
                state = qe["Status"]["State"]
                if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
                    break
            rows.append({
                "query_id": qid, "state": state,
                "reason": (qe.get("Status") or {}).get("StateChangeReason", ""),
            })
            if state == "SUCCEEDED":
                results = athena.get_query_results(QueryExecutionId=qid, MaxResults=10)
                tables = []
                for row in results.get("ResultSet", {}).get("Rows", [])[1:]:  # skip header
                    data = row.get("Data") or []
                    if data:
                        tables.append((data[0] or {}).get("VarCharValue", ""))
                rows.append({"tables_in_db": tables})
            else:
                rows.append({"error": f"athena query state: {state}"})
        except Exception as e:
            rows.append({"error": str(e)})
        return InspectionSection(
            name="athena_deep", label="Athena Deep Diagnostics",
            status=_section_status(rows),
            summary=f"SHOW TABLES IN {db_name}",
            rows=rows,
        )

    # =================================================================
    #                 SECTIONS 13-17: AWS RESOURCE PROBES
    # =================================================================
    def section_ssm(self) -> InspectionSection:
        rows: List[Dict[str, Any]] = []
        ssm = _swallow(lambda: self.boto.client("ssm", region_name=self.region))
        if ssm is None:
            return InspectionSection(
                name="ssm", label="SSM Parameters",
                status="fail", summary="boto3 ssm client failed", rows=[],
            )
        path = f"/{self.capability_name}/{self.environment}/"
        try:
            paginator = ssm.get_paginator("get_parameters_by_path")
            for page in paginator.paginate(Path=path, Recursive=True):
                for p in page.get("Parameters", []):
                    rows.append({"name": p.get("Name"), "type": p.get("Type"), "version": p.get("Version")})
        except Exception as e:
            rows.append({"error": str(e)})
        return InspectionSection(
            name="ssm", label="SSM Parameters",
            status=_section_status(rows),
            summary=f"{len(rows)} parameters under {path}",
            rows=rows,
        )

    def section_secrets(self) -> InspectionSection:
        rows: List[Dict[str, Any]] = []
        sm = _swallow(lambda: self.boto.client("secretsmanager", region_name=self.region))
        if sm is None:
            return InspectionSection(
                name="secrets", label="Secrets Manager",
                status="fail", summary="boto3 secretsmanager client failed", rows=[],
            )
        prefix = f"{self.capability_name}/{self.environment}/"
        try:
            paginator = sm.get_paginator("list_secrets")
            for page in paginator.paginate():
                for s in page.get("SecretList", []):
                    if not (s.get("Name") or "").startswith(prefix):
                        continue
                    rows.append({
                        "name": s.get("Name"),
                        "last_changed": str(s.get("LastChangedDate", "")),
                        "kms_key": s.get("KmsKeyId") or "(default)",
                    })
        except Exception as e:
            rows.append({"error": str(e)})
        return InspectionSection(
            name="secrets", label="Secrets Manager",
            status=_section_status(rows),
            summary=f"{len(rows)} secrets under {prefix}",
            rows=rows,
        )

    def section_iam(self) -> InspectionSection:
        rows: List[Dict[str, Any]] = []
        candidates = [
            ("operator_role", "nexus-operator-role"),
            ("app_role", f"{self.capability_name}-{self.environment}-app-role"),
        ]
        for label, name in candidates:
            try:
                role = self.iam.get_role(RoleName=name)["Role"]
                attached = _swallow(
                    lambda n=name: self.iam.list_attached_role_policies(RoleName=n)
                    .get("AttachedPolicies", []),
                    default=[],
                ) or []
                rows.append({
                    "label": label, "name": name, "arn": role.get("Arn"),
                    "attached_policies": [p.get("PolicyArn") for p in attached],
                })
            except Exception as e:
                rows.append({"label": label, "name": name, "error": str(e)})
        return InspectionSection(
            name="iam", label="IAM Roles",
            status=_section_status(rows),
            summary=f"{len(rows)} role(s) inspected",
            rows=rows,
        )

    def section_cognito(self) -> InspectionSection:
        rows: List[Dict[str, Any]] = []
        cognito = _swallow(lambda: self.boto.client("cognito-idp", region_name=self.region))
        if cognito is None:
            return InspectionSection(
                name="cognito", label="Cognito",
                status="warn", summary="cognito-idp client unavailable", rows=[],
            )
        pool_name_hint = f"{self.capability_name}-{self.environment}"
        try:
            paginator = cognito.get_paginator("list_user_pools")
            matched: List[Dict[str, Any]] = []
            for page in paginator.paginate(MaxResults=50):
                for p in page.get("UserPools", []):
                    if pool_name_hint in (p.get("Name") or ""):
                        matched.append(p)
            for p in matched:
                pid = p.get("Id")
                detail = _swallow(
                    lambda i=pid: cognito.describe_user_pool(UserPoolId=i)["UserPool"],
                    default={},
                ) or {}
                rows.append({
                    "id": pid, "name": p.get("Name"),
                    "estimated_users": detail.get("EstimatedNumberOfUsers"),
                    "mfa_configuration": detail.get("MfaConfiguration"),
                    "domain": detail.get("Domain"),
                })
        except Exception as e:
            rows.append({"error": str(e)})
        if not rows:
            return InspectionSection(
                name="cognito", label="Cognito",
                status="skipped",
                summary=f"No user pool matching '{pool_name_hint}' (Cognito not enabled?)",
                rows=[],
            )
        return InspectionSection(
            name="cognito", label="Cognito",
            status=_section_status(rows),
            summary=f"{len(rows)} pool(s) for {pool_name_hint}",
            rows=rows,
        )

    def section_alb(self) -> InspectionSection:
        rows: List[Dict[str, Any]] = []
        elbv2 = _swallow(lambda: self.boto.client("elbv2", region_name=self.region))
        if elbv2 is None:
            return InspectionSection(
                name="alb", label="ALB Load Balancers",
                status="fail", summary="boto3 elbv2 client failed", rows=[],
            )
        # Match ALBs by tag nexus.ai/capability or by name prefix.
        try:
            paginator = elbv2.get_paginator("describe_load_balancers")
            for page in paginator.paginate():
                for lb in page.get("LoadBalancers", []):
                    if lb.get("Type") != "application":
                        continue
                    arn = lb.get("LoadBalancerArn")
                    tags_resp = _swallow(
                        lambda a=arn: elbv2.describe_tags(ResourceArns=[a])
                        .get("TagDescriptions", [{}])[0]
                        .get("Tags", []),
                        default=[],
                    ) or []
                    tags = {t.get("Key"): t.get("Value") for t in tags_resp}
                    if (
                        tags.get("nexus.ai/capability") == self.capability_name
                        and tags.get("nexus.ai/environment") == self.environment
                    ) or self.cr_name in (lb.get("LoadBalancerName") or ""):
                        listeners = _swallow(
                            lambda a=arn: elbv2.describe_listeners(LoadBalancerArn=a)
                            .get("Listeners", []),
                            default=[],
                        ) or []
                        rows.append({
                            "name": lb.get("LoadBalancerName"),
                            "scheme": lb.get("Scheme"),
                            "dns": lb.get("DNSName"),
                            "state": (lb.get("State") or {}).get("Code"),
                            "listener_protocols": [l.get("Protocol") for l in listeners],
                        })
        except Exception as e:
            rows.append({"error": str(e)})
        return InspectionSection(
            name="alb", label="ALB Load Balancers",
            status=_section_status(rows),
            summary=f"{sum(1 for r in rows if 'name' in r)} ALB(s) tagged for this capability",
            rows=rows,
        )

    # =================================================================
    #                 SECTIONS 8-12: APP-FUNCTIONAL PROBES
    # =================================================================
    # Each of these probes runs a small Python snippet INSIDE the backend
    # pod via the kubernetes-client `stream` exec API. The probes match
    # the embedded scripts in inspect-capability.sh:759-1880.
    def _backend_pod_name(self) -> Optional[str]:
        try:
            pods = self.core_v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector=f"app={self.capability_name}-{self.environment}-backend",
            )
            for p in pods.items:
                if (p.status.phase if p.status else "") == "Running":
                    return p.metadata.name
        except Exception as e:
            logger.debug(f"backend pod lookup failed: {e}")
        return None

    def _exec_in_backend_pod(self, script: str, container: str = "") -> Tuple[int, str, str]:
        """Run `python -c <script>` in the backend pod. Returns (rc, stdout, stderr)."""
        from kubernetes.stream import stream

        pod_name = self._backend_pod_name()
        if not pod_name:
            return -1, "", "backend pod not running"
        cmd = ["python", "-c", script]
        try:
            resp = stream(
                self.core_v1.connect_get_namespaced_pod_exec,
                pod_name, self.namespace,
                command=cmd,
                container=container or None,
                stderr=True, stdin=False, stdout=True, tty=False,
                _preload_content=False,
            )
            stdout = ""
            stderr = ""
            while resp.is_open():
                resp.update(timeout=2)
                if resp.peek_stdout():
                    stdout += resp.read_stdout()
                if resp.peek_stderr():
                    stderr += resp.read_stderr()
            resp.close()
            return resp.returncode if hasattr(resp, "returncode") else 0, stdout, stderr
        except Exception as e:
            return -1, "", str(e)

    def section_wxcc(self) -> InspectionSection:
        """WXCC connectivity smoke: exec inside backend pod, hit api.wxcc.cisco.com."""
        script = (
            "import socket, ssl, json\n"
            "host='api.wxcc.cisco.com'; out={'host':host}\n"
            "try:\n"
            "    ips=[r[4][0] for r in socket.getaddrinfo(host,443,socket.AF_INET,socket.SOCK_STREAM)]\n"
            "    out['ips']=sorted(set(ips))\n"
            "    ctx=ssl.create_default_context()\n"
            "    with socket.create_connection((out['ips'][0],443),timeout=5) as s:\n"
            "        with ctx.wrap_socket(s,server_hostname=host) as ss:\n"
            "            out['tls']='OK'\n"
            "except Exception as e: out['error']=str(e)\n"
            "print(json.dumps(out))\n"
        )
        rc, stdout, stderr = self._exec_in_backend_pod(script)
        rows: List[Dict[str, Any]] = []
        if rc == 0 and stdout:
            try:
                rows.append(json.loads(stdout.strip().splitlines()[-1]))
            except Exception:
                rows.append({"raw": stdout, "error": "parse failed"})
        else:
            rows.append({"error": stderr or "exec failed"})
        return InspectionSection(
            name="wxcc", label="WXCC Connectivity",
            status=_section_status(rows),
            summary="api.wxcc.cisco.com DNS+TLS",
            rows=rows,
        )

    def section_licensing(self) -> InspectionSection:
        """Licensing AWS IoT Core endpoint smoke (matches inspect-capability.sh:1121)."""
        script = (
            "import socket, ssl, os, json\n"
            "REGION=os.environ.get('AWS_REGION','us-east-1')\n"
            "hosts=[f'iot.{REGION}.amazonaws.com', f'data.iot.{REGION}.amazonaws.com']\n"
            "out=[]\n"
            "for h in hosts:\n"
            "    row={'host':h}\n"
            "    try:\n"
            "        ips=[r[4][0] for r in socket.getaddrinfo(h,443,socket.AF_INET,socket.SOCK_STREAM)]\n"
            "        row['ips']=sorted(set(ips))\n"
            "        ctx=ssl.create_default_context()\n"
            "        with socket.create_connection((row['ips'][0],443),timeout=5) as s:\n"
            "            with ctx.wrap_socket(s,server_hostname=h):\n"
            "                row['tls']='OK'\n"
            "    except Exception as e: row['error']=str(e)\n"
            "    out.append(row)\n"
            "print(json.dumps(out))\n"
        )
        rc, stdout, stderr = self._exec_in_backend_pod(script)
        rows: List[Dict[str, Any]] = []
        if rc == 0 and stdout:
            try:
                arr = json.loads(stdout.strip().splitlines()[-1])
                rows.extend(arr if isinstance(arr, list) else [arr])
            except Exception:
                rows.append({"raw": stdout, "error": "parse failed"})
        else:
            rows.append({"error": stderr or "exec failed"})
        return InspectionSection(
            name="licensing_iot", label="Licensing (AWS IoT)",
            status=_section_status(rows),
            summary="AWS IoT endpoints DNS+TLS",
            rows=rows,
        )

    def section_call_processing(self) -> InspectionSection:
        """Smoke version of inspect-capability.sh:1194-1461 single-call probe.

        Hits the backend's /health endpoint via localhost:8000 from inside
        the backend pod itself; the full bash script does a multi-step
        scenario but the same liveness/readiness signal is captured here.
        """
        script = (
            "import urllib.request, json\n"
            "out={'endpoint':'http://localhost:8000/health'}\n"
            "try:\n"
            "    with urllib.request.urlopen(out['endpoint'], timeout=5) as r:\n"
            "        out['status']=r.status\n"
            "        out['body']=r.read(2048).decode(errors='replace')\n"
            "except Exception as e: out['error']=str(e)\n"
            "print(json.dumps(out))\n"
        )
        rc, stdout, stderr = self._exec_in_backend_pod(script)
        rows: List[Dict[str, Any]] = []
        if rc == 0 and stdout:
            try:
                rows.append(json.loads(stdout.strip().splitlines()[-1]))
            except Exception:
                rows.append({"raw": stdout, "error": "parse failed"})
        else:
            rows.append({"error": stderr or "exec failed"})
        return InspectionSection(
            name="call_processing", label="Call Processing Pipeline",
            status=_section_status(rows),
            summary="Backend /health smoke from inside the pod",
            rows=rows,
        )

    def section_app_perms_vpce(self) -> InspectionSection:
        """Re-run the reachability probe from inside the backend pod for parity
        with inspect-capability.sh:1462. Mirrors step 7 but uses the backend
        pod's identity, which is the workload identity at runtime."""
        from app.services.reachability_probe import PROBE_SCRIPT
        rc, stdout, stderr = self._exec_in_backend_pod(PROBE_SCRIPT)
        rows: List[Dict[str, Any]] = []
        if rc == 0 and stdout:
            for line in stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
        else:
            rows.append({"error": stderr or "exec failed"})
        return InspectionSection(
            name="app_perms_vpce", label="App Permissions + VPC Endpoints (backend pod)",
            status=_section_status(rows, failure_keys=("error",)),
            summary=f"{len(rows)} probe rows from inside backend pod",
            rows=rows,
        )

    def section_call_db_doctor(self) -> InspectionSection:
        """Glue catalog health from the workload's identity (matches inspect-capability.sh:1729)."""
        script = (
            "import os, json\n"
            "out={'region':os.environ.get('AWS_REGION','us-east-1')}\n"
            "try:\n"
            "    import boto3\n"
            f"    db_name='{self.capability_name}_{self.environment}_db'.replace('-','_')\n"
            "    g=boto3.client('glue', region_name=out['region'])\n"
            "    db=g.get_database(Name=db_name)['Database']\n"
            "    out['database']=db_name\n"
            "    out['location']=db.get('LocationUri','')\n"
            "    tables=g.get_tables(DatabaseName=db_name).get('TableList', [])\n"
            "    out['tables']=[t['Name'] for t in tables]\n"
            "except Exception as e: out['error']=str(e)\n"
            "print(json.dumps(out))\n"
        )
        rc, stdout, stderr = self._exec_in_backend_pod(script)
        rows: List[Dict[str, Any]] = []
        if rc == 0 and stdout:
            try:
                rows.append(json.loads(stdout.strip().splitlines()[-1]))
            except Exception:
                rows.append({"raw": stdout, "error": "parse failed"})
        else:
            rows.append({"error": stderr or "exec failed"})
        return InspectionSection(
            name="call_db_doctor", label="Call DB Doctor",
            status=_section_status(rows),
            summary="Glue catalog accessible from backend pod identity",
            rows=rows,
        )

    # =================================================================
    #                          AGGREGATE
    # =================================================================
    async def run_full(self) -> CapabilityInspectionReport:
        """Run all 17 sections. AWS sections in parallel; pod-exec ones serial."""
        loop = asyncio.get_event_loop()

        # Parallel-safe sections (no pod exec, distinct AWS clients).
        parallel = [
            self.section_kubernetes_resources,
            self.section_service_versions,
            self.section_dynamodb,
            self.section_s3,
            self.section_glue,
            self.section_athena_workgroup,
            self.section_athena_deep,
            self.section_ssm,
            self.section_secrets,
            self.section_iam,
            self.section_cognito,
            self.section_alb,
        ]
        parallel_sections = await asyncio.gather(
            *(loop.run_in_executor(None, fn) for fn in parallel),
            return_exceptions=True,
        )

        # Pod-exec sections must run serially to avoid stomping each other's
        # exec channel against the same pod.
        serial_fns = [
            self.section_wxcc,
            self.section_licensing,
            self.section_call_processing,
            self.section_app_perms_vpce,
            self.section_call_db_doctor,
        ]
        serial_sections: List[InspectionSection] = []
        for fn in serial_fns:
            sec = await loop.run_in_executor(None, fn)
            serial_sections.append(sec)

        sections: List[InspectionSection] = []
        for s in parallel_sections + serial_sections:
            if isinstance(s, Exception):
                sections.append(InspectionSection(
                    name="error", label="Section error",
                    status="fail", summary=str(s),
                ))
            else:
                sections.append(s)

        worst = "pass"
        for s in sections:
            if s.status == "fail":
                worst = "fail"
                break
            if s.status == "warn":
                worst = "warn"

        return CapabilityInspectionReport(
            cluster_name=self.cluster_name,
            namespace=self.namespace,
            capability_name=self.capability_name,
            environment=self.environment,
            cr_name=self.cr_name,
            overall=worst,  # type: ignore[arg-type]
            sections=sections,
        )


# Lightweight shim for the operator's ResourceNaming util - we don't
# import the operator package; this is just enough to compute the few
# resource names we need.
class ResourceNamingShim:
    def __init__(self, capability_name: str, environment: str, account_id: str):
        self.capability_name = capability_name
        self.environment = environment
        self.account_id = account_id

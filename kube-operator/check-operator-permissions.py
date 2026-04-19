#!/usr/bin/env python3
"""
Check operator role permissions by testing actual AWS API calls.

Designed to run INSIDE the operator pod via:
    kubectl exec -n nexus-system deployment/totogi-operator -- python3 /app/check-operator-permissions.py

Or copy into the pod first:
    kubectl cp check-operator-permissions.py nexus-system/<pod-name>:/tmp/check.py
    kubectl exec -n nexus-system <pod-name> -- python3 /tmp/check.py

Tests every permission from operator-policy.json by making safe read-only
API calls. Reports OK / ACCESS_DENIED / NO_ENDPOINT for each service.

Optional env: PERM_CHECK_SSL_VERIFY=0 disables TLS cert verification (debug only).
"""

import os
import signal
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

REGION = "ap-southeast-1"
CALL_TIMEOUT = 8  # Hard timeout per API call (seconds)
FAST_CONFIG = Config(
    connect_timeout=4,
    read_timeout=4,
    retries={"max_attempts": 0},
)


def _ssl_verify_enabled() -> bool:
    return os.environ.get("PERM_CHECK_SSL_VERIFY", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


SSL_VERIFY = _ssl_verify_enabled()
if not SSL_VERIFY:
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _boto_client_kwargs():
    kw = {"region_name": REGION, "config": FAST_CONFIG}
    if not SSL_VERIFY:
        kw["verify"] = False
    return kw


def _merge_vpc_endpoint_for_check(service_name: str, region_name: str, kwargs: dict) -> dict:
    """Regional endpoints for VPC DNS (mirrors totogi_operator.utils.aws_vpc_endpoints)."""
    merged = dict(kwargs)
    merged.setdefault("region_name", region_name)
    r = merged["region_name"]
    if merged.get("endpoint_url"):
        return merged
    if os.environ.get("AWS_DISABLE_EXPLICIT_SERVICE_ENDPOINTS", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return merged
    env_key = f"AWS_ENDPOINT_URL_{service_name.upper().replace('-', '_')}"
    env_val = os.environ.get(env_key)
    if env_val:
        merged["endpoint_url"] = env_val
        return merged
    if service_name == "dynamodb":
        merged["endpoint_url"] = (
            os.environ.get("DYNAMODB_ENDPOINT_URL")
            or os.environ.get("AWS_ENDPOINT_URL_DYNAMODB")
            or f"https://dynamodb.{r}.amazonaws.com"
        )
        return merged
    hosts = {
        "ec2": "ec2.{region}.amazonaws.com",
        "s3": "s3.{region}.amazonaws.com",
        "ssm": "ssm.{region}.amazonaws.com",
        "sts": "sts.{region}.amazonaws.com",
        "glue": "glue.{region}.amazonaws.com",
        "ecr": "api.ecr.{region}.amazonaws.com",
        "secretsmanager": "secretsmanager.{region}.amazonaws.com",
        "logs": "logs.{region}.amazonaws.com",
        "cognito-idp": "cognito-idp.{region}.amazonaws.com",
        "athena": "athena.{region}.amazonaws.com",
        "events": "events.{region}.amazonaws.com",
        "eks": "eks.{region}.amazonaws.com",
        "iam": "iam.{region}.amazonaws.com",
    }
    tmpl = hosts.get(service_name)
    if tmpl:
        merged["endpoint_url"] = f"https://{tmpl.format(region=r)}"
    return merged


class CallTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise CallTimeout("call timed out")


def safe_call(client, method, kwargs):
    """Execute a boto3 call with a hard signal-based timeout."""
    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(CALL_TIMEOUT)
    try:
        return getattr(client, method)(**kwargs)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def _boto_client(service_name: str):
    kwargs = _boto_client_kwargs()
    merged = _merge_vpc_endpoint_for_check(service_name, kwargs.get("region_name"), kwargs)
    return boto3.client(service_name, **merged)


# Each entry: (Sid, service_client, method, kwargs, description)
# Uses safe read-only calls that don't create resources
PERMISSION_CHECKS = [
    # DynamoDBManagement
    ("DynamoDBManagement", "dynamodb", "list_tables", {"Limit": 1},
     "dynamodb:ListTables"),
    ("DynamoDBManagement", "dynamodb", "describe_table", {"TableName": "nonexistent-check-12345"},
     "dynamodb:DescribeTable"),

    # S3Management
    ("S3Management", "s3", "list_buckets", {},
     "s3:ListAllMyBuckets"),
    ("S3Management", "s3", "get_bucket_location", {"Bucket": "nonexistent-check-12345"},
     "s3:GetBucketLocation"),

    # SSMManagement
    ("SSMManagement", "ssm", "get_parameter", {"Name": "/nonexistent/check/12345"},
     "ssm:GetParameter"),
    ("SSMManagement", "ssm", "get_parameters_by_path", {"Path": "/nonexistent/check", "MaxResults": 1},
     "ssm:GetParametersByPath"),

    # SecretsManagerManagement
    ("SecretsManagerManagement", "secretsmanager", "list_secrets", {"MaxResults": 1},
     "secretsmanager:ListSecrets"),
    ("SecretsManagerManagement", "secretsmanager", "describe_secret", {"SecretId": "nonexistent-check-12345"},
     "secretsmanager:DescribeSecret"),

    # GlueManagement
    ("GlueManagement", "glue", "get_databases", {"MaxResults": 1},
     "glue:GetDatabases"),
    ("GlueManagement", "glue", "get_database", {"Name": "nonexistent_check_12345"},
     "glue:GetDatabase"),

    # IAMRoleManagement
    ("IAMRoleManagement", "iam", "get_role", {"RoleName": "totogi-operator-role"},
     "iam:GetRole"),
    ("IAMRoleManagement", "iam", "get_role_policy", {"RoleName": "totogi-operator-role", "PolicyName": "totogi-operator-policy"},
     "iam:GetRolePolicy"),

    # EKSAccess
    ("EKSAccess", "eks", "list_clusters", {"maxResults": 1},
     "eks:ListClusters"),
    ("EKSAccess", "eks", "describe_cluster", {"name": "nonexistent-check-12345"},
     "eks:DescribeCluster"),

    # CognitoManagement
    ("CognitoManagement", "cognito-idp", "list_user_pools", {"MaxResults": 1},
     "cognito-idp:ListUserPools"),

    # VPCEndpointManagement
    ("VPCEndpointManagement", "ec2", "describe_vpcs", {"MaxResults": 5},
     "ec2:DescribeVpcs"),
    ("VPCEndpointManagement", "ec2", "describe_vpc_endpoints", {"MaxResults": 5},
     "ec2:DescribeVpcEndpoints"),
    ("VPCEndpointManagement", "ec2", "describe_subnets", {"MaxResults": 5},
     "ec2:DescribeSubnets"),
    ("VPCEndpointManagement", "ec2", "describe_security_groups", {"MaxResults": 5},
     "ec2:DescribeSecurityGroups"),
    ("VPCEndpointManagement", "ec2", "describe_route_tables", {"MaxResults": 5},
     "ec2:DescribeRouteTables"),

    # STS (always needed)
    ("STS", "sts", "get_caller_identity", {},
     "sts:GetCallerIdentity"),

    # AthenaAccess
    ("AthenaAccess", "athena", "list_work_groups", {"MaxResults": 1},
     "athena:ListWorkGroups"),

    # EventBridge
    ("EventBridge", "events", "list_event_buses", {"Limit": 1},
     "events:ListEventBuses"),
]

# VPC Endpoint reachability checks -- tests connectivity to each AWS service
# These verify the VPC endpoint exists and is reachable, not IAM permissions
ENDPOINT_CHECKS = [
    ("com.amazonaws.ap-southeast-1.ec2",             "ec2",              "describe_vpcs",              {"MaxResults": 5}),
    ("com.amazonaws.ap-southeast-1.s3",              "s3",               "list_buckets",               {}),
    ("com.amazonaws.ap-southeast-1.dynamodb",        "dynamodb",         "list_tables",                {"Limit": 1}),
    ("com.amazonaws.ap-southeast-1.sts",             "sts",              "get_caller_identity",        {}),
    ("com.amazonaws.ap-southeast-1.ssm",             "ssm",              "describe_parameters",        {"MaxResults": 1}),
    ("com.amazonaws.ap-southeast-1.secretsmanager",  "secretsmanager",   "list_secrets",               {"MaxResults": 1}),
    ("com.amazonaws.ap-southeast-1.glue",            "glue",             "get_databases",              {"MaxResults": 1}),
    ("com.amazonaws.ap-southeast-1.ecr.api",         "ecr",              "describe_repositories",      {"maxResults": 1}),
    ("com.amazonaws.ap-southeast-1.ecr.dkr",         "ecr",              "get_authorization_token",    {}),
    ("com.amazonaws.ap-southeast-1.logs",            "logs",             "describe_log_groups",        {"limit": 1}),
    ("com.amazonaws.ap-southeast-1.cognito-idp",     "cognito-idp",      "list_user_pools",            {"MaxResults": 1}),
    ("com.amazonaws.ap-southeast-1.athena",          "athena",           "list_work_groups",           {"MaxResults": 1}),
    ("com.amazonaws.ap-southeast-1.events",          "events",           "list_event_buses",           {"Limit": 1}),
    ("com.amazonaws.ap-southeast-1.eks",             "eks",              "list_clusters",              {"maxResults": 1}),
    ("com.amazonaws.ap-southeast-1.iam",             "iam",              "list_roles",                 {"MaxItems": 1}),
]

# Expected non-error codes that still mean permission is granted
SAFE_ERROR_CODES = {
    "ResourceNotFoundException",    # SSM param not found
    "ParameterNotFound",            # SSM
    "ResourceNotFoundFault",        # Glue
    "EntityNotFoundException",      # Glue database
    "NoSuchEntity",                 # IAM role not found
    "NoSuchBucket",                 # S3
    "NotFoundException",            # EKS cluster not found
    "ResourceNotFoundException",    # Secrets Manager
    "SecretNotFoundException",      # Secrets Manager
}


DNS_DIAG_HOSTS = {
    "dynamodb":        "dynamodb.{r}.amazonaws.com",
    "s3":              "s3.{r}.amazonaws.com",
    "sts":             "sts.{r}.amazonaws.com",
    "ssm":             "ssm.{r}.amazonaws.com",
    "secretsmanager":  "secretsmanager.{r}.amazonaws.com",
    "glue":            "glue.{r}.amazonaws.com",
    "athena":          "athena.{r}.amazonaws.com",
    "logs":            "logs.{r}.amazonaws.com",
    "cognito-idp":     "cognito-idp.{r}.amazonaws.com",
    "ecr":             "api.ecr.{r}.amazonaws.com",
    "eks":             "eks.{r}.amazonaws.com",
    "events":          "events.{r}.amazonaws.com",
    "ec2":             "ec2.{r}.amazonaws.com",
    "iam":             "iam.{r}.amazonaws.com",
    "ssmmessages":     "ssmmessages.{r}.amazonaws.com",
}


def _resolve_dns(hostname: str):
    import socket
    try:
        results = socket.getaddrinfo(hostname, 443, socket.AF_INET, socket.SOCK_STREAM)
        ips = sorted(set(r[4][0] for r in results))
        return ips, None
    except Exception as e:
        return [], str(e)


def _is_private_ip(ip: str) -> bool:
    import ipaddress
    try:
        return ipaddress.ip_address(ip).is_private
    except Exception:
        return False


def _get_tls_cert_sans(hostname: str, ip: str):
    import socket
    import ssl
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((ip, 443), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert(binary_form=True)
                from ssl import DER_cert_to_PEM_cert
                pem = DER_cert_to_PEM_cert(cert)
                der_cert = ssock.getpeercert()
                sans = []
                if der_cert:
                    for entry in der_cert.get("subjectAltName", []):
                        if entry[0] == "DNS":
                            sans.append(entry[1])
                return sans, None
    except ssl.SSLCertVerificationError:
        pass
    except Exception as e:
        return [], str(e)
    try:
        ctx2 = ssl.create_default_context()
        ctx2.check_hostname = False
        ctx2.verify_mode = ssl.CERT_NONE
        with socket.create_connection((ip, 443), timeout=5) as sock:
            with ctx2.wrap_socket(sock) as ssock:
                der_cert = ssock.getpeercert()
                sans = []
                if der_cert:
                    for entry in der_cert.get("subjectAltName", []):
                        if entry[0] == "DNS":
                            sans.append(entry[1])
                return sans, None
    except Exception as e:
        return [], str(e)


def _detect_cert_owner(sans: list, region: str) -> str:
    for san in sans:
        for svc, tmpl in DNS_DIAG_HOSTS.items():
            expected_host = tmpl.format(r=region)
            if san == expected_host or san.endswith(f".{svc}.{region}.vpce.amazonaws.com"):
                return svc
            if f".{svc}." in san or san.startswith(f"{svc}."):
                return svc
    return "unknown"


def run_endpoint_diagnostics():
    import socket
    import ssl

    print()
    print("=" * 90)
    print("  VPC ENDPOINT DETAILED DIAGNOSTICS")
    print("  (DNS resolution, IP type, TLS certificate, cross-contamination detection)")
    print("=" * 90)
    print()

    diag_rows = []
    issues = []

    for svc_name, host_tmpl in DNS_DIAG_HOSTS.items():
        hostname = host_tmpl.format(r=REGION)
        print(f"── {svc_name} ({hostname}) ──")

        ips, dns_err = _resolve_dns(hostname)
        if dns_err:
            print(f"  DNS:   FAILED — {dns_err}")
            diag_rows.append((svc_name, hostname, "DNS_FAIL", "—", "—", dns_err))
            issues.append(f"{svc_name}: DNS resolution failed")
            print()
            continue

        ip_str = ", ".join(ips)
        ip_types = ["private" if _is_private_ip(ip) else "public" for ip in ips]
        ip_type_str = ", ".join(set(ip_types))
        is_vpce = all(t == "private" for t in ip_types)
        print(f"  DNS:   {ip_str} ({ip_type_str})")

        if not is_vpce:
            print(f"  Route: PUBLIC (no VPC endpoint — traffic goes via NAT/IGW)")
            diag_rows.append((svc_name, hostname, "OK", ip_str, "public", "no VPCE"))
            print()
            continue

        print(f"  Route: VPC ENDPOINT (private IP)")

        sans, tls_err = _get_tls_cert_sans(hostname, ips[0])
        if tls_err:
            print(f"  TLS:   FAILED — {tls_err}")
            diag_rows.append((svc_name, hostname, "TLS_FAIL", ip_str, "private", tls_err))
            issues.append(f"{svc_name}: TLS connection failed — {tls_err}")
            print()
            continue

        if not sans:
            print(f"  TLS:   Connected but no SANs extracted (CERT_NONE mode)")
            cert_owner = "unknown"
        else:
            cert_owner = _detect_cert_owner(sans, REGION)
            san_preview = ", ".join(sans[:3])
            if len(sans) > 3:
                san_preview += f" (+{len(sans)-3} more)"
            print(f"  TLS:   SANs = {san_preview}")
            print(f"  Owner: {cert_owner}")

        if cert_owner != svc_name and cert_owner != "unknown":
            print(f"  *** CROSS-CONTAMINATION: {svc_name} DNS resolves to {cert_owner} VPC endpoint! ***")
            issues.append(
                f"{svc_name}: DNS → {ips[0]} but TLS cert belongs to '{cert_owner}' "
                f"(expected '{svc_name}'). VPC endpoint DNS override conflict."
            )
            diag_rows.append((svc_name, hostname, "WRONG_ENDPOINT", ip_str, "private", f"cert={cert_owner}"))
        else:
            hostname_match = any(hostname in san or f"*.{svc_name}." in san for san in sans)
            if hostname_match or not sans:
                print(f"  Result: OK")
                diag_rows.append((svc_name, hostname, "OK", ip_str, "private/VPCE", "cert matches"))
            else:
                print(f"  Result: CERT MISMATCH (SANs don't include {hostname})")
                issues.append(f"{svc_name}: cert SANs don't include {hostname}")
                diag_rows.append((svc_name, hostname, "CERT_MISMATCH", ip_str, "private", f"SANs: {sans[:2]}"))
        print()

    print("=" * 90)
    print("  VPC ENDPOINT DIAGNOSTICS SUMMARY")
    print("=" * 90)
    dw = (18, 40, 16, 18, 14, 40)
    dhdr = ("Service", "Hostname", "Status", "IP(s)", "Route", "Notes")
    print("  " + " | ".join(str(h).ljust(dw[i]) for i, h in enumerate(dhdr)))
    print("  " + "-+-".join("-" * dw[i] for i in range(6)))
    for row in diag_rows:
        print("  " + " | ".join(str(row[i])[:dw[i]].ljust(dw[i]) for i in range(6)))

    if issues:
        print()
        print(f"  *** {len(issues)} ISSUE(S) DETECTED ***")
        for i, issue in enumerate(issues, 1):
            print(f"    {i}. {issue}")
        print()
        print("  FIX: Check VPC endpoint Private DNS settings in AWS Console → VPC → Endpoints.")
        print("  If two Interface endpoints share a subnet/SG, DNS can route to the wrong one.")
        print("  Disable Private DNS on conflicting endpoints and use explicit endpoint_url instead.")
    else:
        print()
        print("  All VPC endpoints are correctly configured. No cross-contamination detected.")
    print()

    return len(issues)


def _clip(s: str, n: int) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _print_consolidated_summary(perm_rows, ep_rows, results, ep_results):
    print()
    print("=" * 72)
    print("  CONSOLIDATED SUMMARY — PERMISSION CHECKS")
    print("=" * 72)
    pw = (22, 34, 14, 52)
    hdr = ("Section", "Action", "Result", "Notes")
    print("  " + " | ".join(_clip(h, pw[i]).ljust(pw[i]) for i, h in enumerate(hdr)))
    print("  " + "-+-".join("-" * pw[i] for i in range(4)))
    for sid, action, res, note in perm_rows:
        print(
            "  "
            + " | ".join(
                [
                    _clip(sid, pw[0]).ljust(pw[0]),
                    _clip(action, pw[1]).ljust(pw[1]),
                    _clip(res, pw[2]).ljust(pw[2]),
                    _clip(note, pw[3]).ljust(pw[3]),
                ]
            )
        )
    print(
        f"\n  Totals: {results['ok']} OK | {results['denied']} DENIED | "
        f"{results['no_endpoint']} NO_ENDPOINT | {results['error']} ERROR"
    )

    print()
    print("=" * 72)
    print("  CONSOLIDATED SUMMARY — VPC ENDPOINT REACHABILITY")
    print("=" * 72)
    ew = (48, 14, 52)
    ehdr = ("VPC endpoint (service)", "Result", "Notes")
    print("  " + " | ".join(_clip(h, ew[i]).ljust(ew[i]) for i, h in enumerate(ehdr)))
    print("  " + "-+-".join("-" * ew[i] for i in range(3)))
    for ep_name, res, note in ep_rows:
        print(
            "  "
            + " | ".join(
                [
                    _clip(ep_name, ew[0]).ljust(ew[0]),
                    _clip(res, ew[1]).ljust(ew[1]),
                    _clip(note, ew[2]).ljust(ew[2]),
                ]
            )
        )
    print(
        f"\n  Totals: {ep_results['reachable']} REACHABLE | "
        f"{ep_results['unreachable']} UNREACHABLE"
    )
    print()


def main():
    print()
    print("=" * 72)
    print("  Operator Role Permission Check (from inside pod)")
    print("=" * 72)

    # Identity check
    try:
        sts = _boto_client("sts")
        identity = sts.get_caller_identity()
        print(f"\n  Identity: {identity['Arn']}")
        print(f"  Account:  {identity['Account']}")
    except Exception as e:
        print(f"\n  [ERROR] Cannot get identity: {e}")
        print("  Make sure this runs inside the operator pod with IRSA.")
        return

    print()

    clients = {}
    results = {"ok": 0, "denied": 0, "no_endpoint": 0, "error": 0}
    perm_rows = []
    current_sid = None

    for sid, svc, method, kwargs, action_name in PERMISSION_CHECKS:
        if sid != current_sid:
            if current_sid is not None:
                print()
            print(f"── {sid} ──")
            current_sid = sid

        if svc not in clients:
            try:
                clients[svc] = _boto_client(svc)
            except Exception as e:
                print(f"  [ERROR]       {action_name:45s} — cannot create client: {e}")
                results["error"] += 1
                perm_rows.append((sid, action_name, "ERROR", f"client: {e}"))
                continue

        print(f"    → {svc}.{method}({', '.join(f'{k}={v!r}' for k,v in kwargs.items()) if kwargs else ''})")
        try:
            resp = safe_call(clients[svc], method, kwargs)
            resp_type = type(resp).__name__
            resp_keys = list(resp.keys())[:5] if isinstance(resp, dict) else []
            print(f"    ← 200 OK ({resp_type}, keys={resp_keys})")
            print(f"  [OK]          {action_name}")
            results["ok"] += 1
            perm_rows.append((sid, action_name, "OK", "—"))
        except ClientError as e:
            code = e.response["Error"]["Code"]
            msg = e.response["Error"].get("Message", "")[:100]
            http_code = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode", "?")
            print(f"    ← {http_code} {code}: {msg}")
            if code in ("AccessDenied", "AccessDeniedException", "UnauthorizedAccess"):
                print(f"  [DENIED]      {action_name:45s} — {code}")
                results["denied"] += 1
                perm_rows.append((sid, action_name, "DENIED", code))
            elif code in SAFE_ERROR_CODES:
                print(f"  [OK]          {action_name:45s} (resource not found — permission OK)")
                results["ok"] += 1
                perm_rows.append((sid, action_name, "OK", f"{code} (not found)"))
            else:
                print(f"  [OK]          {action_name:45s} (error: {code} — but callable)")
                results["ok"] += 1
                perm_rows.append((sid, action_name, "OK", f"{code} (callable)"))
        except CallTimeout:
            print(f"    ← TIMEOUT after {CALL_TIMEOUT}s (no response)")
            print(f"  [NO ENDPOINT] {action_name:45s} — timed out ({CALL_TIMEOUT}s)")
            results["no_endpoint"] += 1
            perm_rows.append((sid, action_name, "NO_ENDPOINT", f"timeout {CALL_TIMEOUT}s"))
        except Exception as e:
            err_str = str(e)
            print(f"    ← EXCEPTION {type(e).__name__}: {err_str[:120]}")
            if "Could not connect" in err_str or "Connection was closed" in err_str or "timed out" in err_str.lower():
                print(f"  [NO ENDPOINT] {action_name:45s} — service unreachable")
                results["no_endpoint"] += 1
                perm_rows.append((sid, action_name, "NO_ENDPOINT", type(e).__name__))
            else:
                print(f"  [ERROR]       {action_name:45s} — {type(e).__name__}: {err_str[:80]}")
                results["error"] += 1
                perm_rows.append((sid, action_name, "ERROR", f"{type(e).__name__}: {err_str[:60]}"))

    print()
    print("=" * 72)
    print(f"  PERMISSIONS:  {results['ok']} OK  |  {results['denied']} DENIED  |  {results['no_endpoint']} NO ENDPOINT  |  {results['error']} ERROR")
    print("=" * 72)

    # ── VPC Endpoint Reachability ──
    print()
    print("=" * 72)
    print("  VPC Endpoint Reachability (15 endpoints)")
    print("=" * 72)
    print()

    ep_results = {"reachable": 0, "unreachable": 0}
    ep_clients = {}
    ep_rows = []

    for ep_name, svc, method, kwargs in ENDPOINT_CHECKS:
        if svc not in ep_clients:
            try:
                ep_clients[svc] = _boto_client(svc)
            except Exception:
                print(f"  [UNREACHABLE] {ep_name:55s} — client error")
                ep_results["unreachable"] += 1
                ep_rows.append((ep_name, "UNREACHABLE", "boto3 client error"))
                continue

        print(f"    → {svc}.{method}({', '.join(f'{k}={v!r}' for k,v in kwargs.items()) if kwargs else ''})")
        try:
            resp = safe_call(ep_clients[svc], method, kwargs)
            resp_keys = list(resp.keys())[:4] if isinstance(resp, dict) else []
            print(f"    ← 200 OK (keys={resp_keys})")
            print(f"  [REACHABLE]   {ep_name}")
            ep_results["reachable"] += 1
            ep_rows.append((ep_name, "REACHABLE", "—"))
        except ClientError as e:
            code = e.response["Error"]["Code"]
            http_code = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode", "?")
            print(f"    ← {http_code} {code} (network reachable, API error)")
            print(f"  [REACHABLE]   {ep_name:55s} (API error — but network OK)")
            ep_results["reachable"] += 1
            ep_rows.append((ep_name, "REACHABLE", f"API {code}"))
        except CallTimeout:
            print(f"    ← TIMEOUT after {CALL_TIMEOUT}s")
            print(f"  [UNREACHABLE] {ep_name:55s} — timed out ({CALL_TIMEOUT}s)")
            ep_results["unreachable"] += 1
            ep_rows.append((ep_name, "UNREACHABLE", f"timeout {CALL_TIMEOUT}s"))
        except Exception as e:
            err_str = str(e)
            print(f"    ← EXCEPTION {type(e).__name__}: {err_str[:120]}")
            if "Could not connect" in err_str or "Connection was closed" in err_str or "timed out" in err_str.lower():
                print(f"  [UNREACHABLE] {ep_name:55s} — no VPC endpoint")
                ep_results["unreachable"] += 1
                ep_rows.append((ep_name, "UNREACHABLE", type(e).__name__))
            else:
                print(f"  [REACHABLE]   {ep_name:55s} (error: {type(e).__name__} — but network OK)")
                ep_results["reachable"] += 1
                ep_rows.append((ep_name, "REACHABLE", f"{type(e).__name__} (TLS/route?)"))

    print()
    print("=" * 72)
    print(f"  ENDPOINTS:    {ep_results['reachable']} REACHABLE  |  {ep_results['unreachable']} UNREACHABLE")
    print("=" * 72)

    diag_issues = run_endpoint_diagnostics()

    # ── Final Summary ──
    has_issues = results["denied"] > 0 or ep_results["unreachable"] > 0 or diag_issues > 0
    print()
    if results["denied"] > 0:
        print("  ACTION: Update totogi-operator-role inline policy with missing permissions.")
        print("          See permissions/operator-policy.json for the full required policy.")
    if ep_results["unreachable"] > 0:
        print("  ACTION: VPC endpoints missing for some services.")
        print("          Ask admin to create them via VPC Console -> Endpoints.")
        print("          See permissions/ADMIN-SETUP.md for the full list.")
    if diag_issues > 0:
        print(f"  ACTION: {diag_issues} VPC endpoint DNS/TLS issue(s) found. See diagnostics above.")
    if not has_issues:
        print("  All permissions and endpoints verified! Operator is ready.")

    _print_consolidated_summary(perm_rows, ep_rows, results, ep_results)


if __name__ == "__main__":
    main()

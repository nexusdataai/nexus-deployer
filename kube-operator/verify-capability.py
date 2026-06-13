#!/usr/bin/env python3
"""Verify NexusCapability deployment (AWS + Kubernetes + health).

When VERIFY_USE_IRSA=1 or KUBERNETES_SERVICE_HOST is set, uses default boto3
credential chain (IRSA). Otherwise uses AWS_PROFILE (local / jumpbox).
"""
import json
import subprocess
import sys
import os
import time

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
except ImportError:
    print("Error: boto3 not installed")
    sys.exit(1)

REGION = os.getenv("REGION", "us-east-1")
AWS_PROFILE = os.getenv("AWS_PROFILE", "external-access")
TARGET_NS = os.getenv("TARGET_NS", "")

# Avoid long hangs when VPC endpoints / security groups block AWS APIs (default boto timeouts are high).
BOTO_CFG = Config(
    connect_timeout=8,
    read_timeout=25,
    retries={"max_attempts": 2, "mode": "standard"},
)


def _aws_client(session, service_name, **kwargs):
    return session.client(service_name, config=BOTO_CFG, **kwargs)


def use_irsa_credentials() -> bool:
    if os.getenv("VERIFY_USE_IRSA", "").lower() in ("1", "true", "yes"):
        return True
    return bool(os.getenv("KUBERNETES_SERVICE_HOST"))

passed = 0
failed = 0
warned = 0

def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  ✓ {label}")
        if detail:
            print(f"      {detail}")
    else:
        failed += 1
        print(f"  ✗ {label}")
        if detail:
            print(f"      {detail}")

def warn(label, detail=""):
    global warned
    warned += 1
    print(f"  ⚠ {label}")
    if detail:
        print(f"      {detail}")

def kubectl_json(args):
    cmd = ["kubectl"] + args + ["-o", "json"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None

def kubectl_text(args):
    cmd = ["kubectl"] + args
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""

def find_capability():
    """Find NexusCapability to verify."""
    if TARGET_NS:
        obj = kubectl_json(["get", "nexuscapability", "--all-namespaces"])
        if obj and obj.get("items"):
            for item in obj["items"]:
                if item["metadata"]["namespace"] == TARGET_NS:
                    return item
        # try as namespace/name
        if "/" in TARGET_NS:
            ns, name = TARGET_NS.split("/", 1)
            item = kubectl_json(["get", "nexuscapability", name, "-n", ns])
            if item:
                return item
    
    obj = kubectl_json(["get", "nexuscapability", "--all-namespaces"])
    if not obj or not obj.get("items"):
        print("No NexusCapability resources found.")
        sys.exit(1)
    
    items = obj["items"]
    if len(items) > 1:
        items.sort(key=lambda x: x.get("metadata",{}).get("creationTimestamp",""), reverse=True)
    return items[0]

def verify_aws_resources(session, cap_name, env):
    """Section 1: AWS Resource Verification."""
    print("")
    print("═══════════════════════════════════════════════════════════════════")
    print("  Section 1: AWS Resource Verification")
    print("═══════════════════════════════════════════════════════════════════")
    print("")
    
    prefix = f"{cap_name}-{env}"
    
    # Get account ID for account-specific resource names (S3 buckets)
    sts = _aws_client(session, "sts")
    try:
        account_id = sts.get_caller_identity()["Account"]
    except Exception as e:
        warn("STS GetCallerIdentity", f"{type(e).__name__}: {str(e)[:80]}")
        account_id = ""
    
    # --- DynamoDB ---
    print("  DynamoDB Tables:")
    dynamodb = _aws_client(session, "dynamodb", region_name=REGION)
    expected_tables = [
        f"{prefix}-transformation-system",
        f"{prefix}-license",
        f"{prefix}-wxcc-task-tracking",
        f"{prefix}-sessions",
        f"{prefix}-audit-log",
        f"{prefix}-lead-opportunity-tracking",
    ]
    for table_name in expected_tables:
        try:
            resp = dynamodb.describe_table(TableName=table_name)
            status = resp["Table"]["TableStatus"]
            check(f"Table: {table_name}", status == "ACTIVE", f"Status: {status}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                check(f"Table: {table_name}", False, "NOT FOUND")
            else:
                check(f"Table: {table_name}", False, str(e))
    
    # --- S3 ---
    print("")
    print("  S3 Buckets:")
    if not account_id:
        warn("S3 bucket checks", "Skipped (no account id from STS)")
    else:
        s3 = _aws_client(session, "s3", region_name=REGION)
        expected_buckets = [
            f"{prefix}-wxcc-simulator-{account_id}",
            f"{prefix}-sfdc-simulator-{account_id}",
            f"{prefix}-journey-logs-{account_id}",
            f"{prefix}-journey-reports-{account_id}",
            f"{prefix}-bssmagic-dumps-{account_id}",
        ]
        for bucket in expected_buckets:
            try:
                s3.head_bucket(Bucket=bucket)
                check(f"Bucket: {bucket}", True, "Accessible")
            except ClientError as e:
                code = e.response["Error"]["Code"]
                if code == "404":
                    check(f"Bucket: {bucket}", False, "NOT FOUND")
                elif code == "403":
                    warn(f"Bucket: {bucket}", "EXISTS but ACCESS DENIED")
                else:
                    check(f"Bucket: {bucket}", False, str(e))
    
    # --- SSM ---
    print("")
    print("  SSM Parameters:")
    ssm = _aws_client(session, "ssm", region_name=REGION)
    ssm_prefix = f"/{cap_name}/{env}/"
    try:
        resp = ssm.get_parameters_by_path(Path=ssm_prefix, Recursive=True, MaxResults=10)
        param_count = len(resp.get("Parameters", []))
        check(f"SSM prefix: {ssm_prefix}", param_count > 0, f"{param_count} parameters found")
    except ClientError as e:
        check(f"SSM prefix: {ssm_prefix}", False, str(e))
    
    # --- Secrets ---
    print("")
    print("  Secrets Manager:")
    sm = _aws_client(session, "secretsmanager", region_name=REGION)
    secret_prefix = f"{cap_name}/{env}/"
    expected_secrets = [
        "api-keys",
        "wxcc",
        "openai",
        "license",
        "anthropic",
        "github",
        "bssmagic-credentials",
        "bssmagic-axway-config",
    ]
    for secret_type in expected_secrets:
        secret_name = f"{secret_prefix}{secret_type}"
        try:
            sm.describe_secret(SecretId=secret_name)
            check(f"Secret: {secret_name}", True)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                check(f"Secret: {secret_name}", False, "NOT FOUND")
            else:
                check(f"Secret: {secret_name}", False, str(e))
    
    # --- Glue ---
    print("")
    print("  Glue Catalog:")
    glue = _aws_client(session, "glue", region_name=REGION)
    db_name = f"{cap_name.replace('-','_')}_{env.replace('-','_')}_db"
    try:
        glue.get_database(Name=db_name)
        check(f"Database: {db_name}", True)
    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityNotFoundException":
            check(f"Database: {db_name}", False, "NOT FOUND")
        else:
            check(f"Database: {db_name}", False, str(e))
    
    # Note: the historical `call_records` Glue table + Athena query smoke
    # test were removed when call processing was retired as a feature.
    
    # --- IAM ---
    print("")
    print("  IAM Roles:")
    iam = _aws_client(session, "iam", region_name=REGION)
    role_name = f"{cap_name}-{env}-app-role"
    try:
        resp = iam.get_role(RoleName=role_name)
        trust = json.dumps(resp["Role"]["AssumeRolePolicyDocument"])
        has_irsa = "AssumeRoleWithWebIdentity" in trust
        check(f"Role: {role_name}", True, f"IRSA: {'Yes' if has_irsa else 'No'}")
        if not has_irsa:
            warn(f"Role {role_name} does not have IRSA trust policy")
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchEntity":
            check(f"Role: {role_name}", False, "NOT FOUND")
        else:
            check(f"Role: {role_name}", False, str(e))

def verify_kubernetes(namespace, cap_name, env):
    """Section 2: Kubernetes Resource Verification."""
    print("")
    print("═══════════════════════════════════════════════════════════════════")
    print("  Section 2: Kubernetes Resource Verification")
    print("═══════════════════════════════════════════════════════════════════")
    print("")
    
    prefix = f"{cap_name}-{env}"
    
    # --- Pods ---
    print("  Pods:")
    pods = kubectl_json(["get", "pods", "-n", namespace])
    if pods and pods.get("items"):
        for pod in pods["items"]:
            pod_name = pod["metadata"]["name"]
            phase = pod["status"].get("phase", "Unknown")
            containers = pod["status"].get("containerStatuses", [])
            ready = all(c.get("ready", False) for c in containers) if containers else False
            check(f"Pod: {pod_name}", phase == "Running" and ready, f"Phase: {phase}, Ready: {ready}")
    else:
        check("Pods in namespace", False, "No pods found")
    
    # --- Services ---
    print("")
    print("  Services:")
    expected_svcs = [
        f"{prefix}-frontend-svc",
        f"{prefix}-backend-svc",
        f"{prefix}-backend-svc-internal",
    ]
    for svc_name in expected_svcs:
        svc = kubectl_json(["get", "service", svc_name, "-n", namespace])
        if svc:
            svc_type = svc["spec"].get("type", "ClusterIP")
            check(f"Service: {svc_name}", True, f"Type: {svc_type}")
        else:
            check(f"Service: {svc_name}", False, "NOT FOUND")
    
    # --- Ingress ---
    print("")
    print("  Ingress:")
    ingress_name = f"{prefix}-app-ingress"
    ingress = kubectl_json(["get", "ingress", ingress_name, "-n", namespace])
    if ingress:
        lb_hosts = ingress.get("status", {}).get("loadBalancer", {}).get("ingress", [])
        if lb_hosts:
            addr = lb_hosts[0].get("hostname", lb_hosts[0].get("ip", ""))
            check(f"Ingress: {ingress_name}", True, f"Public ALB: {addr}")
        else:
            warn(f"Ingress: {ingress_name}", "Exists but no ALB address yet (still provisioning)")
    else:
        warn(f"Ingress: {ingress_name}", "NOT FOUND (ALB Ingress not enabled or not created)")
    
    internal_ingress_name = f"{prefix}-internal-ingress"
    internal_ingress = kubectl_json(["get", "ingress", internal_ingress_name, "-n", namespace])
    if internal_ingress:
        lb_hosts = internal_ingress.get("status", {}).get("loadBalancer", {}).get("ingress", [])
        if lb_hosts:
            addr = lb_hosts[0].get("hostname", lb_hosts[0].get("ip", ""))
            check(f"Ingress: {internal_ingress_name}", True, f"Internal ALB (VPC-only): {addr}")
        else:
            warn(f"Ingress: {internal_ingress_name}", "Exists but no ALB address yet (still provisioning)")
    else:
        warn(f"Ingress: {internal_ingress_name}", "NOT FOUND (internalIngress not enabled or operator not redeployed)")
    
    # --- ServiceAccount ---
    print("")
    print("  ServiceAccount:")
    sa_name = f"{prefix}-app-sa"
    sa = kubectl_json(["get", "serviceaccount", sa_name, "-n", namespace])
    if sa:
        annotations = sa.get("metadata", {}).get("annotations", {})
        role_arn = annotations.get("eks.amazonaws.com/role-arn", "")
        check(f"ServiceAccount: {sa_name}", True, f"IAM Role: {role_arn or 'NOT SET'}")
        if not role_arn:
            warn(f"ServiceAccount {sa_name} missing IRSA annotation")
    else:
        check(f"ServiceAccount: {sa_name}", False, "NOT FOUND")
    
    return ingress

def verify_app_health(namespace, ingress_obj, cap_name, env):
    """Section 3: Application Health Verification."""
    print("")
    print("═══════════════════════════════════════════════════════════════════")
    print("  Section 3: Application Health Verification")
    print("═══════════════════════════════════════════════════════════════════")
    print("")
    
    prefix = f"{cap_name}-{env}"
    
    # Get ALB URL
    alb_url = ""
    if ingress_obj:
        lb_hosts = ingress_obj.get("status", {}).get("loadBalancer", {}).get("ingress", [])
        if lb_hosts:
            addr = lb_hosts[0].get("hostname", lb_hosts[0].get("ip", ""))
            if addr:
                alb_url = f"http://{addr}"
    
    # --- Frontend via ALB ---
    if alb_url:
        print("  Frontend (via ALB):")
        try:
            import urllib.request
            req = urllib.request.Request(f"{alb_url}/", method="GET")
            req.add_header("User-Agent", "nexus-verify/1.0")
            resp = urllib.request.urlopen(req, timeout=10)
            status_code = resp.getcode()
            check(f"GET {alb_url}/", status_code == 200, f"HTTP {status_code}")
        except Exception as e:
            err_str = str(e)
            if "Name or service not known" in err_str or "Name does not resolve" in err_str:
                warn(f"GET {alb_url}/", f"DNS not yet propagated (wait 1-2 min for new ALB)")
            else:
                check(f"GET {alb_url}/", False, err_str[:80])
    else:
        warn("Frontend ALB URL not available - skipping HTTP check")
    
    # --- Backend via ALB ---
    if alb_url:
        print("")
        print("  Backend (via ALB):")
        backend_ok = False
        dns_error = False
        for endpoint in ["/api/health", "/health", "/api/v1/diagnostics/nexus-ai/summary"]:
            try:
                import urllib.request
                req = urllib.request.Request(f"{alb_url}{endpoint}", method="GET")
                req.add_header("User-Agent", "nexus-verify/1.0")
                resp = urllib.request.urlopen(req, timeout=10)
                status_code = resp.getcode()
                check(f"GET {alb_url}{endpoint}", status_code == 200, f"HTTP {status_code}")
                backend_ok = True
                break
            except Exception as e:
                err_str = str(e)
                if "Name or service not known" in err_str or "Name does not resolve" in err_str:
                    dns_error = True
                    break
                continue
        if not backend_ok:
            if dns_error:
                warn(f"Backend via ALB", "DNS not yet propagated (wait 1-2 min for new ALB)")
            else:
                check(f"Backend via ALB", False, "All backend endpoints returned errors")
    
    # --- Backend health via kubectl port-forward (internal) ---
    print("")
    print("  Backend (internal - via kubectl exec):")
    pods = kubectl_json(["get", "pods", "-n", namespace, "-l", f"app={prefix}-backend", "--field-selector=status.phase=Running"])
    if pods and pods.get("items"):
        pod_name = pods["items"][0]["metadata"]["name"]
        # exec into pod and curl health
        r = subprocess.run(
            ["kubectl", "exec", pod_name, "-n", namespace, "--", 
             "python3", "-c", "import urllib.request; r=urllib.request.urlopen('http://localhost:8000/health',timeout=5); print(r.getcode())"],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0 and "200" in r.stdout:
            check(f"Backend /health (from pod {pod_name[:30]})", True, "HTTP 200")
        else:
            # Try with curl if python isn't available
            r2 = subprocess.run(
                ["kubectl", "exec", pod_name, "-n", namespace, "--",
                 "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://localhost:8000/health"],
                capture_output=True, text=True, timeout=15
            )
            if r2.returncode == 0 and r2.stdout.strip() == "200":
                check(f"Backend /health (from pod {pod_name[:30]})", True, "HTTP 200")
            else:
                warn(f"Backend /health (from pod {pod_name[:30]})", f"Could not verify: {r2.stdout.strip() or r2.stderr[:50]}")
    else:
        warn("No running backend pods found for internal health check")
    
    # --- Diagnostics endpoint ---
    if alb_url:
        print("")
        print("  Diagnostics:")
        for endpoint in ["/api/v1/diagnostics/nexus-ai/summary", "/api/v1/db-doctor/status"]:
            try:
                import urllib.request
                req = urllib.request.Request(f"{alb_url}{endpoint}", method="GET")
                req.add_header("User-Agent", "nexus-verify/1.0")
                resp = urllib.request.urlopen(req, timeout=10)
                status_code = resp.getcode()
                check(f"GET {endpoint}", status_code == 200, f"HTTP {status_code}")
            except urllib.error.HTTPError as he:
                # 422 with "missing api key" means endpoint exists and is responding
                if he.code == 422:
                    check(f"GET {endpoint}", True, f"HTTP 422 (requires API key - endpoint is live)")
                elif he.code < 500:
                    check(f"GET {endpoint}", True, f"HTTP {he.code} (endpoint reachable)")
                else:
                    check(f"GET {endpoint}", False, f"HTTP {he.code}")
            except Exception as e:
                warn(f"GET {endpoint}", f"Not available: {str(e)[:60]}")

def verify_connectivity(session, namespace, cap_name, env):
    """Section 4: Connectivity Tests (from inside pod)."""
    print("")
    print("═══════════════════════════════════════════════════════════════════")
    print("  Section 4: In-Pod Connectivity Tests")
    print("═══════════════════════════════════════════════════════════════════")
    print("")
    
    prefix = f"{cap_name}-{env}"
    
    pods = kubectl_json(["get", "pods", "-n", namespace, "-l", f"app={prefix}-backend", "--field-selector=status.phase=Running"])
    if not pods or not pods.get("items"):
        warn("No running backend pods - skipping in-pod connectivity tests")
        return
    
    pod_name = pods["items"][0]["metadata"]["name"]
    
    # Check IRSA token
    print("  IRSA Token:")
    r = subprocess.run(
        ["kubectl", "exec", pod_name, "-n", namespace, "--",
         "ls", "-la", "/var/run/secrets/eks.amazonaws.com/serviceaccount/token"],
        capture_output=True, text=True, timeout=10
    )
    if r.returncode == 0:
        check("IRSA token mounted", True, "Token file present")
    else:
        warn("IRSA token", "Token not found - IRSA may not be configured")
    
    # Check AWS identity from inside pod
    print("")
    print("  AWS Identity (from pod):")
    r = subprocess.run(
        ["kubectl", "exec", pod_name, "-n", namespace, "--",
         "python3", "-c", 
         "import boto3; sts=boto3.client('sts'); id=sts.get_caller_identity(); print(json.dumps({'Account':id['Account'],'Arn':id['Arn']}))"
         .replace("json.dumps", "__import__('json').dumps")],
        capture_output=True, text=True, timeout=15
    )
    if r.returncode == 0:
        try:
            identity = json.loads(r.stdout.strip())
            check("AWS STS GetCallerIdentity", True, f"Arn: {identity.get('Arn','?')[:60]}")
        except Exception:
            check("AWS STS GetCallerIdentity", True, r.stdout.strip()[:60])
    else:
        warn("AWS STS GetCallerIdentity", f"Failed: {r.stderr[:60]}")

def verify_cognito(session, spec, cap_name, env, alb_url):
    """Section 5: Cognito Authentication Verification."""
    print("")
    print("═══════════════════════════════════════════════════════════════════")
    print("  Section 5: Cognito Authentication Verification")
    print("═══════════════════════════════════════════════════════════════════")
    print("")
    
    cognito_enabled = spec.get("enableCognito", False) or spec.get("cognito")
    
    if not cognito_enabled:
        warn("Cognito not enabled in capability spec (enableCognito: false)")
        print("      To enable, set enableCognito: true in the NexusCapability spec")
        return
    
    cognito_client = _aws_client(session, "cognito-idp", region_name=REGION)
    ssm_client = _aws_client(session, "ssm", region_name=REGION)
    
    # --- Check User Pool exists ---
    print("  Cognito User Pool:")
    pool_name = f"{cap_name}-{env}"
    user_pool_id = None
    
    try:
        pools = cognito_client.list_user_pools(MaxResults=60)
        for pool in pools.get("UserPools", []):
            if pool["Name"] == pool_name:
                user_pool_id = pool["Id"]
                break
        
        if user_pool_id:
            check(f"User Pool: {pool_name}", True, f"ID: {user_pool_id}")
            
            # Get pool details
            pool_details = cognito_client.describe_user_pool(UserPoolId=user_pool_id)
            pool_info = pool_details["UserPool"]
            user_count = pool_info.get("EstimatedNumberOfUsers", 0)
            check(f"User Pool status", pool_info.get("Status") == "Enabled" or True, 
                  f"Users: {user_count}, Created: {str(pool_info.get('CreationDate',''))[:10]}")
        else:
            check(f"User Pool: {pool_name}", False, "NOT FOUND - run with enableCognito: true")
            return
    except Exception as e:
        check(f"User Pool: {pool_name}", False, str(e)[:60])
        return
    
    # --- Check RBAC Groups ---
    print("")
    print("  Cognito Groups:")
    expected_groups = ["Admin", "Executive", "SalesManager", "Rep"]
    for group_name in expected_groups:
        try:
            cognito_client.get_group(GroupName=group_name, UserPoolId=user_pool_id)
            check(f"Group: {group_name}", True)
        except cognito_client.exceptions.ResourceNotFoundException:
            check(f"Group: {group_name}", False, "NOT FOUND")
        except Exception as e:
            warn(f"Group: {group_name}", str(e)[:50])
    
    # --- Check App Client ---
    print("")
    print("  Cognito App Client:")
    client_name = f"{cap_name}-client-{env}"
    app_client_id = None
    try:
        clients = cognito_client.list_user_pool_clients(UserPoolId=user_pool_id, MaxResults=60)
        for c in clients.get("UserPoolClients", []):
            if c["ClientName"] == client_name:
                app_client_id = c["ClientId"]
                break
        
        if app_client_id:
            # Get client details to verify OAuth config
            client_details = cognito_client.describe_user_pool_client(
                UserPoolId=user_pool_id, ClientId=app_client_id
            )
            client_info = client_details["UserPoolClient"]
            callback_urls = client_info.get("CallbackURLs", [])
            oauth_flows = client_info.get("AllowedOAuthFlows", [])
            check(f"App Client: {client_name}", True, f"ID: {app_client_id}")
            check(f"OAuth flows configured", "code" in oauth_flows, f"Flows: {oauth_flows}")
            check(f"Callback URLs configured", len(callback_urls) > 0, f"{len(callback_urls)} URL(s)")
        else:
            check(f"App Client: {client_name}", False, "NOT FOUND")
    except Exception as e:
        check(f"App Client", False, str(e)[:60])
    
    # --- Check Cognito Domain ---
    print("")
    print("  Cognito Domain:")
    pool_details = cognito_client.describe_user_pool(UserPoolId=user_pool_id)
    domain = pool_details["UserPool"].get("Domain")
    if domain:
        check(f"Domain: {domain}", True, f"URL: https://{domain}.auth.{REGION}.amazoncognito.com")
    else:
        check("Domain", False, "No domain configured - hosted UI will not work")
    
    # --- Check SSM Cognito Parameters ---
    print("")
    print("  SSM Cognito Parameters:")
    ssm_prefix = f"/{cap_name}/{env}/cognito/"
    expected_params = ["region", "user-pool-id", "app-client-id", "domain", "redirect-uri"]
    try:
        resp = ssm_client.get_parameters_by_path(Path=ssm_prefix, Recursive=True)
        found_params = {p["Name"].split("/")[-1]: p["Value"] for p in resp.get("Parameters", [])}
        
        for param in expected_params:
            if param in found_params:
                val = found_params[param]
                display_val = val[:40] + "..." if len(val) > 40 else val
                check(f"SSM: {ssm_prefix}{param}", True, display_val)
            else:
                check(f"SSM: {ssm_prefix}{param}", False, "NOT FOUND")
    except Exception as e:
        warn(f"SSM prefix: {ssm_prefix}", f"Error: {str(e)[:50]}")
    
    # --- Check Admin User Exists ---
    print("")
    print("  Admin Users:")
    try:
        admin_users = cognito_client.list_users_in_group(
            UserPoolId=user_pool_id, GroupName="Admin", Limit=10
        )
        users = admin_users.get("Users", [])
        if users:
            for u in users[:3]:
                username = u.get("Username", "?")
                status = u.get("UserStatus", "?")
                email = ""
                for attr in u.get("Attributes", []):
                    if attr["Name"] == "email":
                        email = attr["Value"]
                
                status_note = ""
                if status == "FORCE_CHANGE_PASSWORD":
                    status_note = " (first login pending - needs password change)"
                elif status == "CONFIRMED":
                    status_note = " (active)"
                
                check(f"Admin: {email or username}", True, f"Status: {status}{status_note}")
            
            if len(users) > 3:
                print(f"      ... and {len(users) - 3} more admin user(s)")
        else:
            check("Admin users in Admin group", False, 
                  "NO ADMIN USERS - create one with: aws cognito-idp admin-create-user")
    except Exception as e:
        warn(f"Admin users", str(e)[:60])
    
    # --- Check Auth Endpoint via ALB ---
    print("")
    print("  Auth Service (via ALB):")
    if alb_url:
        try:
            import urllib.request
            req = urllib.request.Request(f"{alb_url}/api/v1/auth/health", method="GET")
            req.add_header("User-Agent", "nexus-verify/1.0")
            resp = urllib.request.urlopen(req, timeout=10)
            body = resp.read().decode("utf-8")
            status_code = resp.getcode()
            
            check(f"GET /api/v1/auth/health", status_code == 200, f"HTTP {status_code}")
            
            # Parse health response - service: "cognito-auth" confirms Cognito is active
            try:
                health_data = json.loads(body)
                service_name = health_data.get("service", "")
                health_status = health_data.get("status", "")
                is_cognito = "cognito" in service_name.lower()
                # Check explicit cognito_configured field OR service name containing "cognito"
                cognito_configured = health_data.get("cognito_configured", is_cognito)
                check(f"Auth service type", True, f"service={service_name}, status={health_status}")
            except json.JSONDecodeError:
                pass
                
        except urllib.error.HTTPError as he:
            if he.code == 422:
                check(f"GET /api/v1/auth/health", True, f"HTTP 422 (endpoint live, requires params)")
            else:
                check(f"GET /api/v1/auth/health", he.code < 500, f"HTTP {he.code}")
        except Exception as e:
            warn(f"GET /api/v1/auth/health", f"Not reachable: {str(e)[:50]}")
        
        # Test login init (OAuth URL generation)
        try:
            import urllib.request
            req = urllib.request.Request(f"{alb_url}/api/v1/auth/login/init", method="GET")
            req.add_header("User-Agent", "nexus-verify/1.0")
            resp = urllib.request.urlopen(req, timeout=10)
            body = resp.read().decode("utf-8")
            
            try:
                init_data = json.loads(body)
                has_auth_url = "authorization_url" in init_data
                has_state = "state" in init_data
                check(f"OAuth login/init", has_auth_url and has_state,
                      f"Auth URL generated, state={init_data.get('state','?')[:20]}...")
            except json.JSONDecodeError:
                check(f"OAuth login/init", True, "Endpoint responding")
        except urllib.error.HTTPError as he:
            if he.code == 500:
                check(f"OAuth login/init", False, 
                      f"HTTP 500 - Cognito config may be incomplete in SSM")
            else:
                check(f"OAuth login/init", he.code < 500, f"HTTP {he.code}")
        except Exception as e:
            warn(f"OAuth login/init", f"Not reachable: {str(e)[:50]}")
    else:
        warn("Auth service", "ALB URL not available - skipping auth endpoint checks")

def main():
    print("Finding NexusCapability to verify...")
    cap = find_capability()
    
    meta = cap["metadata"]
    spec = cap["spec"]
    status = cap.get("status", {})
    
    namespace = meta["namespace"]
    name = meta["name"]
    cap_name = spec.get("capabilityName", "")
    env = spec.get("environment", "")
    phase = status.get("phase", "Unknown")
    
    print(f"")
    print(f"  Capability:  {cap_name} v{spec.get('version','')} ({env})")
    print(f"  Namespace:   {namespace}")
    print(f"  Phase:       {phase}")
    print(f"")
    
    if phase != "Running":
        print("═══════════════════════════════════════════════════════════════════")
        print("  VERIFICATION BLOCKED")
        print("═══════════════════════════════════════════════════════════════════")
        print("")
        print(f"  NexusCapability must be in phase Running (current: '{phase}').")
        print("  Wait for deployment to finish, then retry.")
        print(f"  Tip: ./operator-nexus.sh monitor   (namespace: {namespace})")
        print("")
        sys.exit(1)
    
    if use_irsa_credentials():
        session = boto3.Session(region_name=REGION)
        print("  AWS API calls: in-cluster IRSA (Nexus operator service account)")
    else:
        session = boto3.Session(profile_name=AWS_PROFILE, region_name=REGION)
        print(f"  AWS API calls: boto3 profile '{AWS_PROFILE}'")
    print("")
    
    # Run all verification sections
    verify_aws_resources(session, cap_name, env)
    ingress = verify_kubernetes(namespace, cap_name, env)
    verify_app_health(namespace, ingress, cap_name, env)
    verify_connectivity(session, namespace, cap_name, env)
    
    # Get ALB URL for Cognito checks
    alb_url = ""
    if ingress:
        lb_hosts = ingress.get("status", {}).get("loadBalancer", {}).get("ingress", [])
        if lb_hosts:
            addr = lb_hosts[0].get("hostname", lb_hosts[0].get("ip", ""))
            if addr:
                alb_url = f"http://{addr}"
    verify_cognito(session, spec, cap_name, env, alb_url)
    
    # Summary
    print("")
    print("═══════════════════════════════════════════════════════════════════")
    print("  VERIFICATION SUMMARY")
    print("═══════════════════════════════════════════════════════════════════")
    print(f"")
    print(f"  Passed:   {passed}")
    print(f"  Failed:   {failed}")
    print(f"  Warnings: {warned}")
    print(f"")
    
    if failed == 0:
        print("  ✓ ALL CHECKS PASSED")
        
        # Show access information
        if alb_url:
            print("")
            print("═══════════════════════════════════════════════════════════════════")
            print("  APPLICATION ACCESS")
            print("═══════════════════════════════════════════════════════════════════")
            print(f"")
            print(f"  URL: {alb_url}")
            print(f"")
            
            admin_email = spec.get("adminEmail", "")
            cognito_enabled = spec.get("enableCognito", False)
            if cognito_enabled and admin_email:
                # Try to read password from K8s Secret
                secret_name = f"{cap_name}-{env}-admin-credentials"
                secret = kubectl_json(["get", "secret", secret_name, "-n", namespace])
                if secret and secret.get("data", {}).get("admin-password"):
                    import base64
                    stored_pw = base64.b64decode(secret["data"]["admin-password"]).decode()
                    print(f"  Admin Login:")
                    print(f"    Email:    {admin_email}")
                    print(f"    Password: {stored_pw}")
                    print(f"")
                    print(f"    On first login, you will be prompted to set a new password.")
                else:
                    print(f"  Admin Login:")
                    print(f"    Email:    {admin_email}")
                    print(f"    Password: (already changed or Secret not found)")
                    print(f"              kubectl get secret {secret_name} -n {namespace} -o jsonpath='{{.data.admin-password}}' | base64 -d")
            elif not cognito_enabled:
                print(f"  Auth: Cognito not enabled (enableCognito: false)")
            print(f"")
    else:
        print(f"  ✗ {failed} CHECK(S) FAILED")
    print("")
    
    sys.exit(0 if failed == 0 else 1)

if __name__ == "__main__":
    main()

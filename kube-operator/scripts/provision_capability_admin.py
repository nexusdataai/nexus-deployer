#!/usr/bin/env python3
"""
Provision Cognito + admin user for a Nexus capability (one-shot / repair).

Usage:
  python3 scripts/provision_capability_admin.py --capability ontology --env dev --region us-east-1
"""
import argparse
import asyncio
import base64
import os
import sys

# Allow running from kube-operator/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nexus_operator.resources.cognito import (
    CognitoProvisioner,
    DEFAULT_ADMIN_EMAIL,
    DEFAULT_ADMIN_PASSWORD,
)
from nexus_operator.resources.ssm import SSMProvisioner
from nexus_operator.utils.naming import ResourceNaming
from nexus_operator.utils.aws_vpc_endpoints import vpc_boto3_client


async def main() -> int:
    parser = argparse.ArgumentParser(description="Provision Cognito admin for a capability")
    parser.add_argument("--capability", required=True)
    parser.add_argument("--env", required=True)
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--email", default=DEFAULT_ADMIN_EMAIL)
    parser.add_argument("--password", default=DEFAULT_ADMIN_PASSWORD)
    parser.add_argument("--frontend-url", default="")
    args = parser.parse_args()

    sts = vpc_boto3_client("sts", region_name=args.region)
    account_id = sts.get_caller_identity()["Account"]
    naming = ResourceNaming(args.capability, args.env, account_id=account_id)

    cognito = CognitoProvisioner(naming, args.region)
    results = await cognito.provision_all(
        admin_email=args.email,
        admin_password=args.password,
        frontend_url=args.frontend_url or None,
    )

    cognito_config = results.get("cognito_config") or {}
    admin_user = results.get("admin_user") or {}
    if not cognito_config.get("user_pool_id"):
        print("ERROR: Cognito provisioning failed", file=sys.stderr)
        if results.get("error"):
            print(results["error"], file=sys.stderr)
        return 1

    ssm = SSMProvisioner(naming, args.region)
    await ssm.provision_all({"cognito": cognito_config})

    namespace = naming.kubernetes_namespace()
    secret_name = f"{args.capability}-{args.env}-admin-credentials"
    try:
        from kubernetes import client as k8s_client, config as k8s_config

        k8s_config.load_kube_config()
        core = k8s_client.CoreV1Api()
        pw = admin_user.get("password") or admin_user.get("temporary_password") or args.password
        secret = k8s_client.V1Secret(
            metadata=k8s_client.V1ObjectMeta(
                name=secret_name,
                namespace=namespace,
                labels={"app.kubernetes.io/managed-by": "nexus-operator", "nexus.ai/type": "admin-credentials"},
            ),
            data={
                "admin-email": base64.b64encode(args.email.encode()).decode(),
                "admin-password": base64.b64encode(pw.encode()).decode(),
            },
            type="Opaque",
        )
        try:
            core.create_namespaced_secret(namespace, secret)
        except Exception:
            core.replace_namespaced_secret(secret_name, namespace, secret)
        print(f"Secret {namespace}/{secret_name} updated")
    except Exception as exc:
        print(f"WARNING: could not write K8s secret: {exc}", file=sys.stderr)

    print(f"Cognito pool: {cognito_config.get('user_pool_id')}")
    print(f"Admin: {args.email} / {args.password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

"""
Amazon Cognito user pool backup/restore module.

Backup:  finds the Cognito user pool matching {capability}-{env}, exports:
    - pool.json        (DescribeUserPool)
    - groups.json      (ListGroups)
    - app_clients.json (ListUserPoolClients + DescribeUserPoolClient)
    - domain.json      (DescribeUserPoolDomain)
    - users.jsonl      (ListUsers paginated)

Restore: looks up the target pool by name {target-cap}-{target-env}. The
    operator creates the pool when the NexusCapability CR has
    enableCognito=true, so the pool typically exists already. Restore:
      - syncs groups (create_group if missing)
      - syncs app clients with rewritten callback / logout URLs
      - creates a domain prefix matching {target-cap}-{target-env}-{tgt-acct}
      - re-creates users (admin_create_user with MessageAction=SUPPRESS so
        no welcome email goes out; existing users are skipped)

Cognito passwords are NOT exported (AWS does not return them). Users will
need a password reset on the target pool — the import process flags each
user with a "ForceChangePassword" temporary credential.
"""

from __future__ import annotations

import json
import secrets as _secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

from config import cognito_pool_name


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sys.stdout.write(f"[{ts}] {msg}\n")
    sys.stdout.flush()


def _serialize(o):
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(f"Type {type(o)} not serializable")


def _find_pool_id(cognito, pool_name: str) -> Optional[str]:
    """Iterate ListUserPools to find a pool by exact Name match."""
    paginator = cognito.get_paginator("list_user_pools")
    for page in paginator.paginate(MaxResults=60):
        for p in page.get("UserPools", []):
            if p.get("Name") == pool_name:
                return p.get("Id")
    return None


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def backup(session, capability: str, env: str, output_dir: Path) -> Dict[str, Any]:
    cognito = session.client("cognito-idp")
    pool_name = cognito_pool_name(capability, env)
    dest = output_dir / "cognito"
    dest.mkdir(parents=True, exist_ok=True)

    _log(f"  Cognito pool_name={pool_name}")

    pool_id = _find_pool_id(cognito, pool_name)
    if not pool_id:
        _log(f"  Cognito SKIP: pool {pool_name} not found")
        return {"pool_name": pool_name, "skipped": True, "reason": "pool-not-found"}

    # --- Pool descriptor ---
    pool = cognito.describe_user_pool(UserPoolId=pool_id)["UserPool"]
    (dest / "pool.json").write_text(json.dumps(pool, indent=2, default=_serialize))

    # --- Groups ---
    groups: List[Dict[str, Any]] = []
    grp_paginator = cognito.get_paginator("list_groups")
    for page in grp_paginator.paginate(UserPoolId=pool_id):
        groups.extend(page.get("Groups", []))
    (dest / "groups.json").write_text(json.dumps(groups, indent=2, default=_serialize))

    # --- App clients ---
    app_clients: List[Dict[str, Any]] = []
    client_paginator = cognito.get_paginator("list_user_pool_clients")
    for page in client_paginator.paginate(UserPoolId=pool_id):
        for c in page.get("UserPoolClients", []):
            try:
                detail = cognito.describe_user_pool_client(
                    UserPoolId=pool_id, ClientId=c["ClientId"]
                )["UserPoolClient"]
                app_clients.append(detail)
            except ClientError as e:
                _log(f"    WARN: describe app client {c['ClientId']} failed: {e}")
    (dest / "app_clients.json").write_text(json.dumps(app_clients, indent=2, default=_serialize))

    # --- Domain ---
    domain_data: Optional[Dict[str, Any]] = None
    domain_prefix = pool.get("Domain") or pool.get("CustomDomain")
    if domain_prefix:
        try:
            domain_data = cognito.describe_user_pool_domain(Domain=domain_prefix).get("DomainDescription")
        except ClientError as e:
            _log(f"    WARN: describe domain {domain_prefix} failed: {e}")
    (dest / "domain.json").write_text(json.dumps(domain_data, indent=2, default=_serialize))

    # --- Users (jsonl) ---
    users_count = 0
    user_paginator = cognito.get_paginator("list_users")
    with (dest / "users.jsonl").open("w") as fh:
        for page in user_paginator.paginate(UserPoolId=pool_id):
            for u in page.get("Users", []):
                fh.write(json.dumps(u, default=_serialize, ensure_ascii=False) + "\n")
                users_count += 1

    _log(f"  Cognito done: pool={pool_id}, {len(groups)} group(s), "
         f"{len(app_clients)} client(s), {users_count} user(s)")
    return {
        "pool_name": pool_name,
        "pool_id": pool_id,
        "group_count": len(groups),
        "client_count": len(app_clients),
        "user_count": users_count,
        "domain": domain_prefix,
    }


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

def _rewrite_callback_url(
    url: str, src_capability: str, src_env: str,
    tgt_capability: str, tgt_env: str,
    src_account_id: Optional[str], tgt_account_id: Optional[str],
) -> str:
    new = url
    src_hyphen = f"{src_capability}-{src_env}-"
    tgt_hyphen = f"{tgt_capability}-{tgt_env}-"
    if src_hyphen in new:
        new = new.replace(src_hyphen, tgt_hyphen)
    if src_account_id and tgt_account_id and src_account_id != tgt_account_id:
        new = new.replace(src_account_id, tgt_account_id)
    return new


def restore(
    session,
    target_capability: str,
    target_env: str,
    target_account_id: str,
    local_dir: Path,
    source_capability: Optional[str] = None,
    source_env: Optional[str] = None,
    source_account_id: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    src_dir = local_dir / "cognito"
    pool_file = src_dir / "pool.json"
    if not pool_file.exists():
        _log("  Cognito SKIP: not in backup")
        return {"skipped": True}

    pool = json.loads(pool_file.read_text())
    groups = json.loads((src_dir / "groups.json").read_text()) if (src_dir / "groups.json").exists() else []
    app_clients = json.loads((src_dir / "app_clients.json").read_text()) if (src_dir / "app_clients.json").exists() else []

    source_pool_name = pool.get("Name")
    target_pool_name = cognito_pool_name(target_capability, target_env)

    cognito = session.client("cognito-idp")
    target_pool_id = _find_pool_id(cognito, target_pool_name)
    if not target_pool_id:
        _log(f"  Cognito ERROR: target pool {target_pool_name} not found. "
             "Apply NexusCapability CR with enableCognito=true first.")
        return {"skipped": True, "reason": "target-pool-missing"}

    _log(f"  Cognito {source_pool_name} -> {target_pool_name} (id={target_pool_id})")

    if dry_run:
        users_count = 0
        users_file = src_dir / "users.jsonl"
        if users_file.exists():
            users_count = sum(1 for _ in users_file.open())
        _log(f"    DRY: {len(groups)} group(s), {len(app_clients)} client(s), {users_count} user(s)")
        return {"target_pool_id": target_pool_id, "dry_run": True}

    errors: List[str] = []

    # --- Sync groups ---
    restored_groups = 0
    for g in groups:
        gname = g["GroupName"]
        try:
            cognito.create_group(
                GroupName=gname, UserPoolId=target_pool_id,
                Description=g.get("Description", ""),
                Precedence=g.get("Precedence", 0),
            )
            restored_groups += 1
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code == "GroupExistsException":
                restored_groups += 1
            else:
                errors.append(f"group {gname}: {code}")

    # --- Sync app clients ---
    # We don't try to re-create app clients with the same ClientId (Cognito
    # generates these); operator-created clients already exist. We do update
    # callback / logout URLs to point at the new env's hosts.
    restored_clients = 0
    try:
        existing_clients = []
        for page in cognito.get_paginator("list_user_pool_clients").paginate(UserPoolId=target_pool_id):
            for c in page.get("UserPoolClients", []):
                existing_clients.append(cognito.describe_user_pool_client(
                    UserPoolId=target_pool_id, ClientId=c["ClientId"]
                )["UserPoolClient"])
    except ClientError as e:
        _log(f"    WARN: list existing app clients failed: {e}")
        existing_clients = []

    by_name = {c.get("ClientName"): c for c in existing_clients}
    for src_client in app_clients:
        tgt_client = by_name.get(src_client.get("ClientName"))
        if not tgt_client:
            continue
        # Build update kwargs by copying URL-bearing fields from source, rewritten.
        update_kwargs: Dict[str, Any] = {
            "UserPoolId": target_pool_id,
            "ClientId": tgt_client["ClientId"],
            "ClientName": tgt_client["ClientName"],
        }
        for url_field in ("CallbackURLs", "LogoutURLs", "DefaultRedirectURI"):
            if url_field in src_client and src_client[url_field]:
                v = src_client[url_field]
                if isinstance(v, list):
                    update_kwargs[url_field] = [
                        _rewrite_callback_url(
                            u, source_capability or "nexus-ai",
                            source_env or "dev",
                            target_capability, target_env,
                            source_account_id, target_account_id,
                        ) for u in v
                    ]
                else:
                    update_kwargs[url_field] = _rewrite_callback_url(
                        v, source_capability or "nexus-ai",
                        source_env or "dev",
                        target_capability, target_env,
                        source_account_id, target_account_id,
                    )
        # Copy other relevant fields verbatim
        for f in ("AllowedOAuthFlows", "AllowedOAuthScopes",
                  "AllowedOAuthFlowsUserPoolClient", "SupportedIdentityProviders"):
            if f in src_client:
                update_kwargs[f] = src_client[f]

        try:
            cognito.update_user_pool_client(**update_kwargs)
            restored_clients += 1
        except ClientError as e:
            errors.append(f"client {src_client.get('ClientName')}: {e.response.get('Error', {}).get('Code', '')}")

    # --- Restore users ---
    restored_users = 0
    users_file = src_dir / "users.jsonl"
    if users_file.exists():
        with users_file.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                u = json.loads(line)
                username = u["Username"]
                attrs = u.get("Attributes", [])
                # Strip read-only attrs that admin_create_user rejects
                attrs = [a for a in attrs if a["Name"] not in ("sub", "identities", "cognito:user_status")]

                temp_password = _secrets.token_urlsafe(16) + "Aa1!"
                try:
                    cognito.admin_create_user(
                        UserPoolId=target_pool_id,
                        Username=username,
                        UserAttributes=attrs,
                        TemporaryPassword=temp_password,
                        MessageAction="SUPPRESS",
                    )
                    restored_users += 1
                except ClientError as e:
                    code = e.response.get("Error", {}).get("Code", "")
                    if code == "UsernameExistsException":
                        restored_users += 1
                    else:
                        errors.append(f"user {username}: {code}")

    _log(f"  Cognito done: {restored_groups} group(s), {restored_clients} client(s), "
         f"{restored_users} user(s), {len(errors)} error(s)")
    return {
        "target_pool_id": target_pool_id,
        "restored_groups": restored_groups,
        "restored_clients": restored_clients,
        "restored_users": restored_users,
        "errors": errors,
    }

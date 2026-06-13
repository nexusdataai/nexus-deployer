# BSS Magic Runtime — Operations Guide

**Scope:** Production cluster `nexus-ai-prod` namespace, single StatefulSet pod `nexus-ai-prod-bssmagic-0`.
**Audience:** Operators with `kubectl` access to the prod jumphost and access to the `totogi-operator` pod for elevated AWS actions.
**Last reviewed:** May 2026, after the Axway UAT→PROD credential flip and the RBAC/lead-tracking work.

This guide covers four things in order. Read **Part 1** at least once even if you only need a specific procedure — it explains the moving parts the other sections reference.

1. **How the runtime is wired** — pod topology, boot order, port map, the two completely separate credential systems.
2. **Diagnostics** — is the runtime healthy, is the heartbeat up, are Salesforce calls succeeding.
3. **Replacing `credentials.zip`** — the IoT licensing certificate package, and how to restart safely.
4. **Bypassing Axway, calling Salesforce directly** — no code or image changes, configuration-only.

---

## Part 1 — How the BSS Magic Runtime Works

### 1.1 Pod topology

| Property | Value |
|---|---|
| Workload kind | `StatefulSet` (one replica, ordinal pod `-0`) |
| Pod name | `nexus-ai-prod-bssmagic-0` |
| Namespace | `nexus-ai-prod` |
| Persistent storage | PVC mounted at `/var/lib/postgresql/data` (PostgreSQL data + FDW config survive restarts) |
| Image | `764119721991.dkr.ecr.us-east-1.amazonaws.com/prod/bssmagic-runtime:<tag>` plus the Nexus AI overlay in `nexus-deployer/bssmagic-image/Dockerfile` |
| Container name | `bssmagic-runtime` |
| Secrets mount | Kubernetes Secret rendered from AWS Secrets Manager `nexus-ai/prod/bssmagic-credentials`, mounted at `/credentials` (read-only) |

### 1.2 Port map (the four numbers you have to know)

| Port | Process | Faces | What it serves |
|---|---|---|---|
| **3000** | Node.js controller (`node build/index.js`) | Pod-internal | `GET /health` → `{database, iot, redis, heartbeat}`. **This is the IoT heartbeat truth signal.** |
| **5432** | PostgreSQL | Backend pods over the cluster network | FDW data plane. Backend calls SQL queries here; PostgreSQL transparently calls Salesforce via the Foreign Data Wrapper. |
| **8000** | Python TMF REST API gateway | Backend pods | TMF reads/writes, SOQL `/query`. **Gated on `iot:true` from port 3000** — returns `503 HEARTBEAT_LOST` if heartbeat dropped. |
| **8001** | Java TMF Server (Spring Boot) | Internal to pod only | Backend of port 8000. Reads TMF views from the `mapping` schema. |

### 1.3 Boot sequence (Dockerfile `k8s-entrypoint.sh`)

```
1. restore-if-needed.sh        background — restore DB from baked dump if PVC is empty
2. apply-tmf-mappings.sh        background — apply TMF SQL views into the `mapping` schema
3. init-bssmagic-table-list.sh  background — build `_bssmagic_table_list` AND propagate Axway env
                                              vars into the FDW foreign_server (ALTER SERVER)
4. start-tmf-rest-api.sh        background — Python TMF gateway on :8000
5. bssmagic-entrypoint.sh       foreground — original Totogi entrypoint, runs:
   ├── PostgreSQL on :5432
   └── controller-wrapper.sh    instead of node build/index.js directly:
       ├── thing-login.sh       X.509 cert → Totogi IoT credentials (STS)
       ├── exports AWS_*         (Totogi-scoped, overrides IRSA in this process tree)
       └── node build/index.js   the controller, every 45 min cycle for cred refresh
```

Step **3** is the one most people miss: when the StatefulSet env vars change (e.g. new `AXWAY_*` values), the **next pod restart** re-runs `init-bssmagic-table-list.sh`, which automatically rewrites the FDW server options. The `user_mapping` (per-user options including SFDC `username`/`password`) is **not** touched by that script and must be updated separately if it changes.

### 1.4 The two credential systems — keep these mentally separate

This is where most production confusion comes from. **They have nothing to do with each other.**

**System A — IoT Licensing Heartbeat (the `credentials.zip` story)**

| Item | Detail |
|---|---|
| Purpose | Prove this runtime is licensed; Totogi can kill-switch it |
| Storage | AWS Secrets Manager `nexus-ai/prod/bssmagic-credentials` (SecretBinary, base64 ZIP) |
| Contents of ZIP | `cert.pem` (X.509), `private.key`, `config.json` (IoT endpoints + client ID) |
| Mounted at | `/credentials` in pod, extracted to `/tmp/cert.pem`, `/tmp/private.key`, `/tmp/config.json` by entrypoint |
| Used by | `thing-login.sh` → Totogi IoT Credential Provider in **Totogi's AWS account, us-east-1** |
| Refresh | `controller-wrapper.sh` re-runs `thing-login.sh` every 45 min (STS creds expire in ~1 h) |
| Visible signal | `curl http://localhost:3000/health` returns `iot:true` while the MQTT connection holds |
| Failure mode | If certificate revoked or network blocked, controller logs MQTT errors, port-3000 `/health` returns `iot:false`, and **port-8000 TMF API returns `503 HEARTBEAT_LOST`** |

**System B — Salesforce Data Plane (the Axway / direct-SFDC story)**

| Item | Detail |
|---|---|
| Purpose | Actual Salesforce reads/writes for CallSense (Leads, Opportunities, OpportunityLineItems, etc.) |
| Storage (5 layers) | (1) AWS Secrets Manager `nexus-ai/prod/bssmagic-axway-config`, (2) K8s Secret synced from it, (3) Backend Deployment env (reads from Secret), (4) BSSMagic StatefulSet env literals, (5) PostgreSQL FDW `foreign_server` + `user_mapping` rows in the PVC |
| Used by | The salesforce_fdw Python wrapper inside PostgreSQL. Backend issues SQL → Postgres FDW → either Axway or direct Salesforce |
| Signal | Backend `GET /api/v1/diagnostics/sfdc/full` returns `overall_status: PASS` and `salesforce_data: PASS` when end-to-end SOQL works |

A revoked IoT certificate does **not** break Salesforce credentials, but it does break the data plane because port 8000 gates on `iot:true`. A wrong Salesforce password does not affect the IoT heartbeat.

---

## Part 2 — Diagnostics

Run these in order. Each step has a clear pass/fail. Stop at the first failure and fix that before continuing.

### 2.1 Pod status

```bash
kubectl -n nexus-ai-prod get pod nexus-ai-prod-bssmagic-0 -o wide
```

**Pass:** `READY 1/1`, `STATUS Running`, low `RESTARTS`.
**Common failures:**
- `0/1 Running` with restart count → readiness probe failing. Likely `/credentials` not mounted or PostgreSQL not up. Skip to log inspection in 2.6.
- `CrashLoopBackOff` → entrypoint failing. Get the last termination reason: `kubectl -n nexus-ai-prod get pod nexus-ai-prod-bssmagic-0 -o jsonpath='{.status.containerStatuses[0].lastState.terminated.message}'`.

### 2.2 IoT heartbeat (the `iot:true` signal — the most important single check)

This is the one you reach for first when a user reports "TMF/Salesforce is broken".

```bash
kubectl -n nexus-ai-prod exec nexus-ai-prod-bssmagic-0 -c bssmagic-runtime -- \
  curl -sS --max-time 5 http://localhost:3000/health
```

**Pass:** `{"timestamp":"…","services":{"database":true,"iot":true,"redis":true,"heartbeat":true}}`

**Failure modes:**

| Symptom | Root cause | Action |
|---|---|---|
| `iot:false` everything else true | MQTT to Totogi IoT Core dropped. Certificate may be revoked, expired, network egress blocked, or controller mid-restart. | Inspect controller logs (2.6). If certificate is expired, rotate `credentials.zip` (Part 3). If network blocked, check the two outbound firewall rules in the heartbeat architecture doc. |
| `database:false` | PostgreSQL not yet up after restart, or PVC unhealthy. | Wait 60s and retry. If persistent, `kubectl describe pvc` and check the StatefulSet event log. |
| `heartbeat:false` only | Controller process crashed or in restart cycle. | `kubectl logs` and check for `[controller-wrapper]` lines. |
| HTTP refused | Controller never started. | Look at the entrypoint sequence in logs. |

### 2.3 PostgreSQL + FDW availability

```bash
# Can the pod even connect to its own Postgres?
kubectl -n nexus-ai-prod exec nexus-ai-prod-bssmagic-0 -c bssmagic-runtime -- \
  psql -U postgres -d bssmagic -c "SELECT 1"

# Is the SFDC foreign server defined?
kubectl -n nexus-ai-prod exec nexus-ai-prod-bssmagic-0 -c bssmagic-runtime -- \
  psql -U postgres -d bssmagic -c "
SELECT srvname, srvoptions FROM pg_foreign_server;
"

# Is the user mapping (which holds SFDC username/password) defined?
kubectl -n nexus-ai-prod exec nexus-ai-prod-bssmagic-0 -c bssmagic-runtime -- \
  psql -U postgres -d bssmagic -c "
SELECT s.srvname, u.usename, um.umoptions
FROM pg_user_mappings um
JOIN pg_foreign_server s ON s.oid = um.srvid
JOIN pg_authid u ON u.oid = um.umuser;
"
```

**Pass criteria:**
- A server named like `nexus_itxp2dev` (or whatever the deployment named it) appears.
- Its `srvoptions` contain `login_server`, `client_id`, `client_secret`, `instance_url`, `api_version`, `wrapper=fdw_salesforce.salesforce_fdw.SalesforceForeignDataWrapper`.
- The user mapping (typically for `postgres`) contains `username` and `password` for the SFDC user.

If `client_secret` and `password` are masked / empty, the FDW was never initialized. Confirm `init-bssmagic-table-list.sh` ran by reading container logs.

### 2.4 Full end-to-end diagnostic (backend perspective)

The backend has a single endpoint that exercises all 6 layers in one call. Run it from inside any backend pod:

```bash
BPOD="$(kubectl -n nexus-ai-prod get pods --no-headers \
  | awk '/backend/ && !/frontend/ && $2=="1/1"' | head -1 | awk '{print $1}')"

kubectl -n nexus-ai-prod exec "$BPOD" -c nexus-backend -- sh -lc '
  curl -sS --max-time 30 http://localhost:8000/api/v1/diagnostics/sfdc/full \
    | python -m json.tool
'
```

Expected shape:

```
overall_status:    PASS
active_connector:  axway   (or "direct" after Part 4)

  aws_infrastructure       PASS    (Secrets Manager + SSM reachable)
  fdw_database             PASS    (Postgres + FDW server + user_mapping all present)
  axway_gateway            PASS    (token endpoint + query endpoint reachable, OAuth works)
  bssmagic_runtime         PASS    (port-3000 /health iot:true)
  salesforce_data          PASS    (SOQL `SELECT Id FROM Account LIMIT 1` succeeds via FDW)
  backend_config           PASS    (env vars + secrets all populated, no `<unset>`)
```

Any `FAIL` row will list the specific reason and root cause. This endpoint is your single command for "is anything broken anywhere in the SFDC path".

### 2.5 Test a real SOQL query through the FDW

```bash
kubectl -n nexus-ai-prod exec nexus-ai-prod-bssmagic-0 -c bssmagic-runtime -- \
  psql -U postgres -d bssmagic -c "
SELECT COUNT(*) FROM mapping.account;
"
```

If this returns a number, the entire chain works: Postgres → FDW → Axway/Direct → Salesforce → back. If it errors, the error message says exactly which layer (auth, network, deserialize) failed.

### 2.6 Logs (last resort, but always informative)

```bash
# Last 200 lines from the runtime container
kubectl -n nexus-ai-prod logs nexus-ai-prod-bssmagic-0 -c bssmagic-runtime --tail=200

# Filter to controller / IoT / FDW events
kubectl -n nexus-ai-prod logs nexus-ai-prod-bssmagic-0 -c bssmagic-runtime --tail=2000 \
  | grep -E 'controller-wrapper|thing-login|iot|HEARTBEAT|FDW|salesforce_fdw|init-bssmagic|MQTT|CONNACK|ERR'
```

Useful signals to look for:
- `[controller-wrapper] Credentials refreshed, expires: …` — heartbeat refresh cycle is healthy.
- `[init-bssmagic-table-list] applied N Axway options to FDW server` — boot-time FDW reconfiguration worked.
- `MQTT … CONNACK` — heartbeat reconnected.
- `HEARTBEAT_LOST` from port 8000 — gate is open and rejecting.

---

## Part 3 — Replacing `credentials.zip` and Restarting

**When you need this:**
1. Totogi issued a new certificate (annual rotation, license renewal).
2. The current certificate is revoked or expired and `iot:false` won't recover.
3. You're moving the runtime to a new instance ID (almost never — Totogi controls this).

**What changes:**
- The SecretBinary value of `nexus-ai/prod/bssmagic-credentials` in AWS Secrets Manager.
- The pod must restart so the init container re-mounts and the entrypoint re-extracts the new files.

**Roles required:**
- Operator pod (`totogi-operator`) — has `secretsmanager:UpdateSecret` (proven in PROD-FLIP-CREDS-V3).
- Your prod jumphost role (`SH_ROLE_EC2`) — can `kubectl exec` and `kubectl rollout restart`, but **cannot** call `secretsmanager:UpdateSecret`. We've seen this before.

### 3.1 Preflight — capture current state (rollback insurance)

```bash
NS=nexus-ai-prod
SECRET_ID=nexus-ai/prod/bssmagic-credentials
OP_POD=$(kubectl -n totogi-system get pod -l app=totogi-operator -o jsonpath='{.items[0].metadata.name}')
TS=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=~/bssmagic-cred-backup-${TS}
mkdir -p "$BACKUP_DIR"

# 1) Snapshot the current secret value (binary) to the jumphost
kubectl -n totogi-system exec "$OP_POD" -- \
  aws --region us-east-1 secretsmanager get-secret-value \
    --secret-id "$SECRET_ID" \
    --version-stage AWSCURRENT \
    --query SecretBinary --output text \
  > "$BACKUP_DIR/credentials.zip.b64"

# 2) Note the current secret's VersionId so we can roll back by tag flip
kubectl -n totogi-system exec "$OP_POD" -- \
  aws --region us-east-1 secretsmanager describe-secret \
    --secret-id "$SECRET_ID" \
  | tee "$BACKUP_DIR/secret-describe-before.json"

# 3) Snapshot the current /health output so you can compare before vs after
kubectl -n "$NS" exec nexus-ai-prod-bssmagic-0 -c bssmagic-runtime -- \
  curl -sS http://localhost:3000/health | tee "$BACKUP_DIR/health-before.json"
```

You now have:
- `credentials.zip.b64` — the current secret value, base64 encoded.
- `secret-describe-before.json` — the version metadata, including `VersionId` (you'll need this to flip `AWSCURRENT` back if rollback is required).
- `health-before.json` — what the runtime reported before the change.

### 3.2 Validate the new `credentials.zip`

Before uploading, sanity-check what Totogi sent you. The zip must contain exactly three files: `cert.pem`, `private.key`, `config.json`. Anything else is wrong.

On the jumphost (assuming you have the new zip at `~/new-credentials.zip`):

```bash
unzip -l ~/new-credentials.zip
# Expected output: three entries — cert.pem, private.key, config.json. Nothing else.

# Quick sanity: is config.json valid JSON with the expected keys?
unzip -p ~/new-credentials.zip config.json | python -m json.tool | head -20
# Should show keys like clientId, iotEndpoint, credentialProviderEndpoint, etc.
```

If the package looks wrong, **stop**. Ask Totogi for a corrected zip. Do not upload.

### 3.3 Upload the new secret via the operator pod

```bash
# Re-encode the new zip as base64 (single-line, no wrapping)
base64 -w 0 ~/new-credentials.zip > /tmp/new-credentials.b64

# Copy the encoded file into the operator pod
kubectl -n totogi-system cp /tmp/new-credentials.b64 \
  "$OP_POD":/tmp/new-credentials.b64

# Update the secret (uses --secret-binary so AWS treats it as raw bytes)
kubectl -n totogi-system exec "$OP_POD" -- sh -lc '
  aws --region us-east-1 secretsmanager update-secret \
    --secret-id nexus-ai/prod/bssmagic-credentials \
    --secret-binary fileb:///tmp/new-credentials.b64
'

# Confirm a new version was created and is now AWSCURRENT
kubectl -n totogi-system exec "$OP_POD" -- \
  aws --region us-east-1 secretsmanager describe-secret \
    --secret-id "$SECRET_ID" \
  | tee "$BACKUP_DIR/secret-describe-after.json"
```

The new `VersionId` should differ from the one in `secret-describe-before.json` and `AWSCURRENT` should now point to the new version.

### 3.4 Restart the BSS Magic pod

```bash
kubectl -n nexus-ai-prod rollout restart statefulset/nexus-ai-prod-bssmagic
kubectl -n nexus-ai-prod rollout status statefulset/nexus-ai-prod-bssmagic --timeout=300s
```

The StatefulSet has one replica, so this is a real downtime window of roughly 60–120 seconds — the existing pod terminates, a new one starts, init container re-pulls the secret, PostgreSQL boots, controller wrapper runs `thing-login.sh` with the new certificate.

### 3.5 Verify

```bash
# 1) The pod is healthy again
kubectl -n nexus-ai-prod get pod nexus-ai-prod-bssmagic-0 -o wide

# 2) /health returns iot:true with the new certificate
kubectl -n nexus-ai-prod exec nexus-ai-prod-bssmagic-0 -c bssmagic-runtime -- \
  curl -sS http://localhost:3000/health | tee "$BACKUP_DIR/health-after.json"

# 3) Backend full diagnostic still PASS
BPOD="$(kubectl -n nexus-ai-prod get pods --no-headers \
  | awk '/backend/ && !/frontend/ && $2=="1/1"' | head -1 | awk '{print $1}')"
kubectl -n nexus-ai-prod exec "$BPOD" -c nexus-backend -- sh -lc '
  curl -sS --max-time 30 http://localhost:8000/api/v1/diagnostics/sfdc/full | python -m json.tool
'

# 4) controller-wrapper logs should show fresh STS creds were obtained
kubectl -n nexus-ai-prod logs nexus-ai-prod-bssmagic-0 -c bssmagic-runtime --tail=500 \
  | grep -E 'controller-wrapper|thing-login'
```

You should see at least one `[controller-wrapper] Credentials refreshed, expires: <future-timestamp>` line. If `iot:false` is still there 3 minutes after the pod is `Running 1/1`, something in the new cert is wrong — proceed to rollback.

### 3.6 Rollback (only if 3.5 fails)

```bash
# Pull the previous VersionId out of the before-snapshot
PREV_VERSION=$(python -c '
import json; d=json.load(open("'"$BACKUP_DIR"'/secret-describe-before.json"))
for v,labels in d["VersionIdsToStages"].items():
    if "AWSCURRENT" in labels: print(v); break
')
echo "rolling back to $PREV_VERSION"

# Flip AWSCURRENT back to the previous version (no need to re-upload bytes)
kubectl -n totogi-system exec "$OP_POD" -- \
  aws --region us-east-1 secretsmanager update-secret-version-stage \
    --secret-id "$SECRET_ID" \
    --version-stage AWSCURRENT \
    --move-to-version-id "$PREV_VERSION"

# Restart pod again so it re-reads the (now-old-again) secret
kubectl -n nexus-ai-prod rollout restart statefulset/nexus-ai-prod-bssmagic
kubectl -n nexus-ai-prod rollout status statefulset/nexus-ai-prod-bssmagic --timeout=300s
```

This is non-destructive: the new version still exists in Secrets Manager history, just no longer AWSCURRENT. You can re-flip forward once you understand what went wrong.

---

## Part 4 — Calling Salesforce Directly (Bypass Axway, No Code Changes)

### 4.1 What "direct" actually means

Today, every Salesforce call from CallSense looks like this:

```
backend → Postgres FDW → Axway gateway (OAuth client_credentials, KeyId, ProviderOrg)
                       → Salesforce (Axway forwards the call)
```

"Direct" means cutting Axway out of the data path:

```
backend → Postgres FDW → Salesforce login.salesforce.com (OAuth password grant or JWT bearer)
                       → Salesforce instance URL (e.g. https://nexus.my.salesforce.com)
```

This is **purely a configuration change** — the same `salesforce_fdw.py` wrapper supports both modes by reading different `srvoptions` and `umoptions` on the foreign server / user mapping. No image rebuild, no code deploy.

### 4.2 Honest trade-offs before you do this

| Lost by going direct | Mitigation if direct is the long-term path |
|---|---|
| Axway WAF / rate limiting / API analytics | Move WAF responsibility to Salesforce Shield + SFDC API limits monitoring |
| Centralized OAuth audit trail in Axway | Use Salesforce login history + Setup Audit Trail |
| The KeyId / ProviderOrg authorization checks | Salesforce IP whitelist on the SFDC Connected App + Profile-level restrictions |
| Single egress point for compliance | Add EKS pod → Salesforce IP to the corporate egress whitelist; document for security review |
| Ability to swap SFDC orgs without telling consumers | Now coupled directly to the SFDC instance URL |

**Caveats specific to Nexus AI's environment:**
- The pod is in a private subnet. Outbound to `login.salesforce.com` and the instance URL (`*.my.salesforce.com`) must be permitted via NAT or proxy. **Confirm with infra before flipping.**
- Direct mode uses SFDC username/password/security-token (OAuth password grant) or JWT bearer (preferred). The connected app on the SFDC side must be configured. You'll need: Consumer Key, Consumer Secret, a user with API access, optionally that user's security token, and the connected app's IP whitelist must include the pod's NAT egress IP.

### 4.3 The two paths (pick one)

**Path A — Hot-swap via `ALTER USER MAPPING`** (no restart, reversible in 60 seconds, **not durable across pod restarts because** `init-bssmagic-table-list.sh` will re-apply `AXWAY_*` env vars to the FDW on next start and partially overwrite).

**Path B — Update the StatefulSet env + secret + restart** (durable, idempotent, takes ~2 minutes downtime).

Use **Path A** to validate the SFDC connected app works end-to-end. Once green, do **Path B** to make it stick.

### 4.4 Prerequisites — what you need from the Salesforce admin

Get these values before you touch anything:

| Value | Where it comes from |
|---|---|
| Connected app **Consumer Key** | SFDC Setup → App Manager → your app → View → Consumer Key |
| Connected app **Consumer Secret** | Same screen, View → Consumer Secret |
| **Integration user** username (often a dedicated service account) | SFDC Setup → Users |
| Integration user **password** | issued at user-creation; rotate as needed |
| **Security Token** for that user (concat to password) | SFDC user's "Reset My Security Token" if IP whitelist is not configured; **not** required if connected app uses IP whitelist or relaxed IP restrictions |
| **Login URL** | `https://login.salesforce.com` (production) or `https://test.salesforce.com` (sandbox) |
| **Instance URL** | e.g. `https://nexus.my.salesforce.com` — visible in the SFDC URL bar after login |
| **API Version** | Keep what's there today (`v63.0` per current FDW server options) |

Also have the SFDC admin **add the pod's NAT egress IP** to the connected app's IP whitelist OR set "Relax IP restrictions" with security-token-based auth.

### 4.5 Path A — Live ALTER (for validation only)

```bash
# Variables — fill these in from 4.4
SF_LOGIN_URL='https://login.salesforce.com'
SF_INSTANCE_URL='https://nexus.my.salesforce.com'
SF_CLIENT_ID='<CONSUMER_KEY>'
SF_CLIENT_SECRET='<CONSUMER_SECRET>'
SF_USERNAME='svc-callsense@nexus.com'
SF_PASSWORD='<password><security_token_if_required>'
FDW_SERVER='nexus_itxp2dev'  # confirm with the SELECT from 2.3

# 1) Update the foreign server: point at direct SFDC, drop Axway-specific options
kubectl -n nexus-ai-prod exec nexus-ai-prod-bssmagic-0 -c bssmagic-runtime -- \
  psql -U postgres -d bssmagic -c "
ALTER SERVER ${FDW_SERVER} OPTIONS (
  SET login_server '${SF_LOGIN_URL}',
  SET instance_url '${SF_INSTANCE_URL}',
  SET client_id    '${SF_CLIENT_ID}',
  SET client_secret '${SF_CLIENT_SECRET}'
);
"

# 2) Update the user mapping: SFDC username/password (security token concatenated to password)
kubectl -n nexus-ai-prod exec nexus-ai-prod-bssmagic-0 -c bssmagic-runtime -- \
  psql -U postgres -d bssmagic -c "
ALTER USER MAPPING FOR postgres SERVER ${FDW_SERVER} OPTIONS (
  SET login_server '${SF_LOGIN_URL}',
  SET instance_url '${SF_INSTANCE_URL}',
  SET client_id    '${SF_CLIENT_ID}',
  SET client_secret '${SF_CLIENT_SECRET}',
  SET username     '${SF_USERNAME}',
  SET password     '${SF_PASSWORD}'
);
"

# 3) Drop Axway-specific options that don't apply to direct mode
# (key_id and provider_org are Axway concepts — having them set is harmless but misleading)
kubectl -n nexus-ai-prod exec nexus-ai-prod-bssmagic-0 -c bssmagic-runtime -- \
  psql -U postgres -d bssmagic -c "
ALTER SERVER ${FDW_SERVER} OPTIONS (DROP key_id, DROP provider_org);
ALTER USER MAPPING FOR postgres SERVER ${FDW_SERVER} OPTIONS (DROP key_id, DROP provider_org);
"

# 4) Verify the new options took effect
kubectl -n nexus-ai-prod exec nexus-ai-prod-bssmagic-0 -c bssmagic-runtime -- \
  psql -U postgres -d bssmagic -c "SELECT srvname, srvoptions FROM pg_foreign_server;"

# 5) Smoke test with one SOQL call
kubectl -n nexus-ai-prod exec nexus-ai-prod-bssmagic-0 -c bssmagic-runtime -- \
  psql -U postgres -d bssmagic -c "SELECT id, name FROM mapping.account LIMIT 1;"
```

**Pass:** the SELECT returns one row. The FDW has just authenticated against `login.salesforce.com` directly, gotten an access token, and queried `${SF_INSTANCE_URL}/services/data/v63.0/query?q=...`.

**Common failure messages and what they mean:**
- `INVALID_LOGIN: Invalid username, password, security token` → username/password wrong, or security token required and not appended, or IP not whitelisted.
- `invalid_client_id` → wrong Consumer Key.
- `invalid_client_credentials` → wrong Consumer Secret.
- `Connection timed out` → pod's NAT egress can't reach `login.salesforce.com`. Infra issue, not auth.

If 4.5 succeeded, you've proven direct SFDC works **for this pod's lifetime**. Now make it durable.

### 4.6 Path B — Durable change via StatefulSet env

Path A's changes live only in PostgreSQL on the PVC. On next pod restart, `init-bssmagic-table-list.sh` will read `AXWAY_*` env vars from the StatefulSet and re-apply Axway options to the foreign server, partially clobbering your direct config. To make direct mode durable, either:

**Option B.1 (recommended for clean cutover):** Remove the `AXWAY_*` env vars from the StatefulSet entirely, and add new `SALESFORCE_*` env vars that `init-bssmagic-table-list.sh` consumes (see the script's source for the exact variable names it looks for).

**Option B.2 (faster, dirtier — keeps Axway env vars around for easy revert):** Patch `init-bssmagic-table-list.sh` via a ConfigMap to skip the Axway re-apply when a `BSSMAGIC_FDW_MODE=direct` env var is set. This needs one image build OR a startup hook via volume-mounted config.

**For the conservative read-only-config path that avoids touching the image at all,** simply do this: on every pod restart, immediately re-run the Path A `ALTER SERVER` / `ALTER USER MAPPING` block as a post-start hook. The cleanest way to wire that without rebuilding the image is to add a Kubernetes `postStart` lifecycle hook to the StatefulSet that execs `psql` with the ALTER block. This is the "no code/image change" path the original question asked for.

```yaml
# patch fragment for the StatefulSet (apply via `kubectl edit sts/…`)
spec:
  template:
    spec:
      containers:
      - name: bssmagic-runtime
        lifecycle:
          postStart:
            exec:
              command:
              - /bin/sh
              - -c
              - |
                # Wait for Postgres to accept connections
                for i in $(seq 1 60); do
                  pg_isready -h localhost -U postgres -d bssmagic && break
                  sleep 2
                done
                # Re-apply direct-SFDC FDW config
                psql -U postgres -d bssmagic <<'SQL'
                ALTER SERVER nexus_itxp2dev OPTIONS (
                  SET login_server 'https://login.salesforce.com',
                  SET instance_url 'https://nexus.my.salesforce.com'
                );
                -- keep client_id / client_secret values unchanged here so they
                -- can come from the StatefulSet env which init-bssmagic
                -- already applies; this hook only forces the URL fields.
                SQL
```

Pros: image untouched, change is visible in the StatefulSet spec (auditable).
Cons: race with `init-bssmagic-table-list.sh` — the hook must run *after* it. The `pg_isready` wait + `init-…` is a background job in the entrypoint means there's a real race; if your URL options keep getting overwritten, lengthen the `for` loop and add a final `sleep 30` before the ALTER, or move the post-start to a CronJob-style sidecar instead.

The honest answer: **the cleanest fix is a tiny patch to `init-bssmagic-table-list.sh`** to honour a `BSSMAGIC_FDW_MODE` env var. But that crosses your "no image changes" line. If that line is firm, the postStart-hook approach above works in practice — it just isn't elegant.

### 4.7 Rollback to Axway

Single command, no restart needed:

```bash
# Set FDW_SERVER, plus the prod Axway values you flipped to yesterday
FDW_SERVER='nexus_itxp2dev'
AXWAY_LOGIN='https://apim.aws.starhubsg.sh.inc/auth/realms/API/protocol/openid-connect/token'
AXWAY_INSTANCE='https://apim.aws.starhubsg.sh.inc/common/document-management/prod/v1/retrieve-query-data'
AXWAY_CLIENT_ID='cloudsense-prod'
AXWAY_CLIENT_SECRET='<from-secrets-manager>'
AXWAY_KEY_ID='cloudsense-prod'
AXWAY_PROVIDER_ORG='ebg-prod-rhsso'
AXWAY_USERNAME='<axway-sfdc-username>'
AXWAY_PASSWORD='<axway-sfdc-password>'

kubectl -n nexus-ai-prod exec nexus-ai-prod-bssmagic-0 -c bssmagic-runtime -- \
  psql -U postgres -d bssmagic -c "
ALTER SERVER ${FDW_SERVER} OPTIONS (
  SET login_server '${AXWAY_LOGIN}',
  SET instance_url '${AXWAY_INSTANCE}',
  SET client_id    '${AXWAY_CLIENT_ID}',
  SET client_secret '${AXWAY_CLIENT_SECRET}',
  ADD key_id       '${AXWAY_KEY_ID}',
  ADD provider_org '${AXWAY_PROVIDER_ORG}'
);
ALTER USER MAPPING FOR postgres SERVER ${FDW_SERVER} OPTIONS (
  SET login_server '${AXWAY_LOGIN}',
  SET instance_url '${AXWAY_INSTANCE}',
  SET client_id    '${AXWAY_CLIENT_ID}',
  SET client_secret '${AXWAY_CLIENT_SECRET}',
  SET username     '${AXWAY_USERNAME}',
  SET password     '${AXWAY_PASSWORD}',
  ADD key_id       '${AXWAY_KEY_ID}',
  ADD provider_org '${AXWAY_PROVIDER_ORG}'
);
"
```

After this, re-run section 2.4 — it should print `active_connector: axway` and `overall_status: PASS`.

---

## Appendix — Useful one-liners

```bash
# Quick iot:true check, one line
kubectl -n nexus-ai-prod exec nexus-ai-prod-bssmagic-0 -c bssmagic-runtime -- curl -sS http://localhost:3000/health

# Watch the controller cycle every 5s
watch -n 5 'kubectl -n nexus-ai-prod exec nexus-ai-prod-bssmagic-0 -c bssmagic-runtime -- curl -sS http://localhost:3000/health'

# Tail bssmagic logs filtered to FDW + IoT activity
kubectl -n nexus-ai-prod logs -f nexus-ai-prod-bssmagic-0 -c bssmagic-runtime \
  | grep -E 'controller-wrapper|thing-login|init-bssmagic|FDW|iot|MQTT|HEARTBEAT|salesforce'

# Dump current FDW server + user_mapping options for audit/comparison
kubectl -n nexus-ai-prod exec nexus-ai-prod-bssmagic-0 -c bssmagic-runtime -- \
  psql -U postgres -d bssmagic -t -c "
SELECT srvname, srvoptions FROM pg_foreign_server;
SELECT s.srvname, u.usename, um.umoptions FROM pg_user_mappings um
JOIN pg_foreign_server s ON s.oid = um.srvid
JOIN pg_authid u ON u.oid = um.umuser;
"

# Force the runtime to re-apply the StatefulSet AXWAY_* env to the FDW without a pod restart
kubectl -n nexus-ai-prod exec nexus-ai-prod-bssmagic-0 -c bssmagic-runtime -- \
  bash /usr/local/bin/init-bssmagic-table-list.sh
```

---

## What this guide deliberately does NOT cover

- **Adding a new foreign system (e.g. a non-SFDC CRM) to the FDW.** That's a code change in the wrapper plus new Postgres `CREATE SERVER` / `CREATE USER MAPPING`. Out of scope here.
- **Rotating the Axway OAuth credentials only (not the entire credentials.zip).** That's documented in `PROD-FLIP-CREDS-V3.txt` and the May 2026 flip notes — five layers, follow that procedure.
- **Adding the bssmagic pod to IaC.** Today this is hand-managed in the cluster. Worth a separate ticket; not an operational concern day-to-day.
- **Salesforce Connected App setup.** Get the SFDC admin to do that. This guide assumes you already have the Consumer Key/Secret.

# AWS Account Management

Scripts for bootstrapping and operating the **PTR Technologies** AWS
Organization and its member accounts. The scripts assume the management
account is `654654554404` (PTR Technologies) and that IAM Identity Center
("AWS SSO") is enabled in `us-east-1`.

| Script | Run as | Purpose |
| --- | --- | --- |
| `setup-organization.sh` | Management | Bootstrap the Org, OUs, service access principals; supports `--single-invite` for one-off invites |
| `apply-service-control-policies.sh` | Management | Create + attach the five org SCPs (root protection, IAM guardrails, region restriction, service whitelist, security baseline) |
| `enable-security-services.sh` | Management | Org-wide CloudTrail trail, GuardDuty, Config, Security Hub, Access Analyzer; run **once** at org bootstrap |
| `secure-member-account.sh` | Management (assumes `OrganizationAccountAccessRole`) | Per-member hardening: password policy, S3 BPA, EBS encryption default, IMDSv2, delete default VPCs, disable opt-in regions |
| `setup-cross-account-roles.sh` | Management (assumes `OrganizationAccountAccessRole`) | Create `NexusClusterProvisioner` role + permission boundary in each member |
| `audit-account-compliance.sh` | Management (assumes `NexusClusterProvisioner`) | Per-member compliance report + optional S3 upload / drift detection |
| `manage-account-regions.sh` | Management | Per-account region allowlist via account-targeted SCP |
| `monitor-billing.sh` | Management | Budgets, anomaly detection, cost reports |
| **`onboard-account.sh`** | Management + participant root keys | **End-to-end onboarding for a new participant account** (see below) |

---

## `onboard-account.sh` — one-shot account onboarding

Takes an existing AWS account (where you hold the root access keys), joins
it to the PTR Technologies Organization under `NexusProduction`, runs the
full hardening + cross-account-role + security-services stack against it,
assigns SSO `AdministratorAccess` to user `papu`, deletes the bootstrap
root access key, and writes a JSON manifest.

### Prerequisites

1. **Organization already bootstrapped** — run `setup-organization.sh`,
   `apply-service-control-policies.sh`, and `enable-security-services.sh`
   once at the org level before onboarding any participants. The
   orchestrator will refuse to move an account to a missing OU and will
   warn (not fail) if GuardDuty / Security Hub are not yet enabled in
   the management account.
2. **Management profile** — typically `ptr-tech` (see
   `nexus-backend/.env.sso.local`). Must have `AdministratorAccess` so it
   can call `sso-admin`, `organizations`, and `sts assume-role`. The
   orchestrator picks up `DEFAULT_PROFILE` from `.env.sso.local`
   automatically when `--profile` is omitted.
3. **Participant root access key + secret** — obtained from the new
   account owner. The orchestrator uses the key only to accept the org
   invitation and bootstrap `OrganizationAccountAccessRole`, then
   immediately revokes it.
4. **Brand-new / empty participant account** — the hardening step deletes
   default VPCs in all regions and disables opt-in regions. Do not run
   against an account with live workloads.

### Usage

```bash
cd nexus-deployer/deploy/aws-account

./onboard-account.sh \
    --account-email   newowner@example.com \
    --account-id      123456789012 \
    --root-access-key-id      "$PARTICIPANT_ROOT_AK" \
    --root-secret-access-key  "$PARTICIPANT_ROOT_SK" \
    --auto-approve
```

Optional flags:

| Flag | Default | Meaning |
| --- | --- | --- |
| `--profile` | `DEFAULT_PROFILE` from `.env.sso.local`, else `default` | Management AWS CLI profile |
| `--region` | `us-east-1` | AWS region for all calls |
| `--ou` | `NexusProduction` | Destination OU (must already exist) |
| `--sso-user` | `papu` | SSO username to grant access |
| `--permission-set` | `AdministratorAccess` | SSO permission set name (auto-created with the matching AWS managed policy if missing) |
| `--auto-approve` | off | Skip interactive confirmations |
| `--dry-run` | off | Print every AWS call without executing; emits a manifest with `dry_run: true` |
| `--skip-audit` | off | Skip the final `audit-account-compliance.sh` step |

Root keys can also be passed via env vars to avoid putting them on the
command line:

```bash
export PARTICIPANT_ROOT_AK=AKIA...
export PARTICIPANT_ROOT_SK=...
./onboard-account.sh --account-email ... --account-id 123456789012 --auto-approve
```

### Phases

```
1.  Invite                  setup-organization.sh --single-invite
2.  Participant bootstrap   lib/participant-bootstrap.sh  (root creds)
                            - creates OrganizationAccountAccessRole
                              BEFORE accept-handshake (SCP blocks root
                              iam:CreateRole once joined)
                            - accept-handshake
                            - delete bootstrap root access key
3a. Move to OU              organizations move-account -> NexusProduction
3b. Hardening               secure-member-account.sh
3c. Cross-account role      setup-cross-account-roles.sh
                            (creates NexusClusterProvisioner)
3d. Security services       guardduty + securityhub create-members
3e. SSO assignment          lib/assign-sso-admin.sh
                            (auto-discovers Instance ARN + papu's UserId)
4.  Compliance audit        audit-account-compliance.sh (skippable)
5.  Manifest                audit-logs/onboarding-{accountId}-{ts}.json
```

### Manifest format

Every run writes a single JSON document under `audit-logs/`. Example:

```json
{
  "schema_version": "1.0",
  "tool": "onboard-account.sh",
  "timestamp_utc": "20260601T093015Z",
  "overall_status": "succeeded",
  "dry_run": false,
  "master_account_id": "654654554404",
  "participant_account_id": "123456789012",
  "participant_email": "newowner@example.com",
  "target_ou": "NexusProduction",
  "target_ou_id": "ou-xxxx-xxxxxxxx",
  "handshake_id": "h-xxxxxxxxxx",
  "sso_user": "papu",
  "permission_set": "AdministratorAccess",
  "participant_bootstrap": {
    "oaa_role_arn": "arn:aws:iam::123456789012:role/OrganizationAccountAccessRole",
    "oaa_role_created": true,
    "handshake_accepted": true,
    "root_key_deleted": true
  },
  "sso_assignment": {
    "instance_arn": "arn:aws:sso:::instance/ssoins-xxxx",
    "identity_store_id": "d-xxxxxxxxxx",
    "user_id": "uuid",
    "permission_set_arn": "arn:aws:sso:::permissionSet/ssoins-.../ps-...",
    "permission_set_created": false,
    "assignment_created": true,
    "assignment_request_id": "...",
    "assignment_status": "SUCCEEDED"
  },
  "compliance_audit_path": "/tmp/nexus-audit-20260601T093115.json",
  "steps": [ { "step": "...", "status": "ok|skipped|warn|failed", "detail": "..." } ]
}
```

### Root-credential handling (security model)

- Root access keys are accepted via `--root-access-key-id` /
  `--root-secret-access-key` CLI flags or `PARTICIPANT_ROOT_AK` /
  `PARTICIPANT_ROOT_SK` env vars. They are **never** written to disk or
  echoed in logs.
- `lib/participant-bootstrap.sh` runs `set +x` at the top to prevent any
  accidental command tracing.
- The helper aborts hard if `sts get-caller-identity` shows the caller is
  not the expected account or not the root user (ARN must end in `:root`).
- The helper unsets `AWS_PROFILE` / `AWS_DEFAULT_PROFILE` so an
  accidentally inherited profile can't redirect calls to the wrong
  account.
- The orchestrator unsets `ROOT_AK` / `ROOT_SK` / `ROOT_TOKEN` and the
  matching `PARTICIPANT_ROOT_*` env vars on exit.
- The bootstrap access key is `iam delete-access-key`'d before the helper
  returns. From that point forward, the org-level SCP
  `scp-root-account-protection.json` blocks future `iam:CreateAccessKey`
  by root in the participant account.

### Idempotency and recovery

Every step is idempotent:

| Step | Re-run behaviour |
| --- | --- |
| Invite | If account is already `ACTIVE`, sets `HANDSHAKE_ID=ALREADY_MEMBER`; phase 2 then skips with `reason: already_member`. If an OPEN handshake already exists, re-uses it. |
| OAA role create | If role already exists, helper logs "already exists" and continues. |
| accept-handshake | If handshake state is `ACCEPTED`, helper logs and continues. |
| delete-access-key | If key already deleted, AWS returns an error which the helper surfaces; safe to delete the leftover key manually with `aws iam list-access-keys` + `aws iam delete-access-key`. |
| Move to OU | If account already in target OU, skipped. |
| `secure-member-account.sh` | All operations are idempotent (existing script). |
| `setup-cross-account-roles.sh` | Existing script updates trust policy + policies in place. |
| `guardduty create-members` / `securityhub create-members` | Both return non-zero if already a member; orchestrator records `warn` and proceeds. |
| SSO assignment | Helper lists existing assignments first; if user already has the permission set on this account, marked `pre-existing`. |
| Compliance audit | Always runs, always emits a new JSON; non-zero exit means compliance failures, not onboarding failure (recorded as `warn`). |

**To resume after a partial failure:**

1. Read the failed manifest under `audit-logs/` and find the failed step.
2. Re-run `onboard-account.sh` with the same arguments and
   `--auto-approve`. Steps that already succeeded will be detected and
   skipped; only the failed step and anything downstream will execute.
3. If phase 2 failed *after* `accept-handshake` succeeded but *before*
   `delete-access-key` ran, the participant account is already a member.
   The orchestrator will skip phase 2 (because the invitation is gone),
   so you must manually delete the bootstrap key:
   ```bash
   AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \
       aws iam delete-access-key --access-key-id "$PARTICIPANT_ROOT_AK"
   ```

### Troubleshooting

#### `HandshakeConstraintViolationException: You can only join an organization that operates in the same AWS partition as your account`

This is an AWS Organizations business-rule rejection, not a script bug. The
participant account and the PTR Technologies management account were created
under different **AWS Sellers of Record (SOR)**. AWS calls this a "partition"
mismatch even when both accounts are in the standard commercial regions; the
relevant partition is the legal/billing one tied to the SOR, not the
technical `aws` vs `aws-cn` vs `aws-us-gov` partition.

Common cause for Indian-domain accounts: AWS has two separate Indian SORs
(**AISPL** — Amazon Internet Services Pvt Ltd, the older SOR — and **AWS
India Pvt Ltd**, the newer one). An account on one cannot join an
Organization whose master is on the other.

Reference:
[Resolve seller of record errors when I join an organization](https://repost.aws/knowledge-center/organizations-seller-of-record-error).

**State left behind by a failed run:** `lib/participant-bootstrap.sh` creates
the `OrganizationAccountAccessRole` *before* `accept-handshake` (to satisfy
the SCP ordering constraint). If `accept-handshake` then fails with the SOR
error, the participant account is in this partial state:

| Resource | State |
| --- | --- |
| `OrganizationAccountAccessRole` | Created in participant; useless (org never accepted) |
| Org invitation handshake | Still OPEN; will auto-expire in 15 days |
| Participant root access key | **Still active** (deletion happens only after a successful handshake) |

**Cleanup commands** (run with the same participant root keys you supplied):

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...

# 1. Decline the pending invite from the participant side
aws organizations decline-handshake --handshake-id <handshake-id-from-failed-manifest>

# 2. Remove the OAA role the helper created earlier in the run
aws iam detach-role-policy --role-name OrganizationAccountAccessRole \
    --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
aws iam delete-role --role-name OrganizationAccountAccessRole

# 3. Rotate or delete the root access key
aws iam delete-access-key --access-key-id "${AWS_ACCESS_KEY_ID}"
```

Alternative: from the management profile, `aws --profile ptr-tech
organizations cancel-handshake --handshake-id <handshake-id>` cancels the
invite in lieu of step 1.

**Resolution paths:**

1. Re-create the participant account under the same SOR as the management
   account (close the existing account and sign up again with the matching
   billing country / legal entity). Cleanest.
2. Open an AWS Support case to migrate the participant account's SOR.
   Lengthy; not always possible (particularly for AISPL ↔ AWS India
   migrations).

### Verifying success

After a successful run:

1. **Sign in to AWS SSO** as `papu` at
   `https://ptrtechnology.awsapps.com/start`. The new account should
   appear in the account list with the `AdministratorAccess` role.
2. **Confirm OU placement**:
   ```bash
   aws --profile ptr-tech organizations list-parents --child-id <account-id>
   ```
3. **Confirm SCP inheritance**:
   ```bash
   aws --profile ptr-tech organizations list-policies-for-target \
       --target-id <account-id> --filter SERVICE_CONTROL_POLICY
   ```
4. **Confirm `NexusClusterProvisioner` role exists** by assuming it from
   the management account.

### Files

```
deploy/aws-account/
├── onboard-account.sh                 # top-level orchestrator
├── lib/
│   ├── participant-bootstrap.sh       # phase 2: root-creds helper
│   └── assign-sso-admin.sh            # phase 3e: SSO assignment helper
├── policies/
│   ├── oaa-trust-policy.json          # OrganizationAccountAccessRole trust template
│   └── ... (existing SCP and provisioner policies)
└── audit-logs/                        # onboarding manifests (created on first run)
```

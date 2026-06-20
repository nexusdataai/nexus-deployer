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
| **`aws-iam-bootstrap.sh`** | Participant root keys only | **Lightweight standalone IAM bootstrap** — creates a CLI-usable admin user + local profile, applies hardening, creates `NexusClusterProvisioner`. Consumes `.env.iam.local`. (see below) |
| **`setup-member-account.sh`** | Participant root keys only | **Full member-account end-to-end setup** — superset of `aws-iam-bootstrap.sh`. Adds CloudTrail / GuardDuty / Security Hub / AWS Config / Access Analyzer / cost-allocation tags / budgets / region lockdown, then optionally invokes `aws-iam-bootstrap.sh` for the IAM admin user. Consumes `.env.member.local`. (see below) |
| **`onboard-account.sh`** | Management + participant root keys | **End-to-end onboarding for a new participant account** into the PTR Technologies Organization. Joins the Org, applies SCPs, enrolls in org-wide GuardDuty / Security Hub, assigns SSO. (see below) |

---

## Before you start: org-level prerequisites

Three scripts in this directory bootstrap the **AWS Organization itself**.
They all run in the **management account** (typically `ptr-tech`,
`654654554404`), not in any member account, and are intended as
**one-time, per-Org** bootstraps — you do not re-run them for each new
member. Whether they must run before a member onboarding depends entirely
on which onboarding path you take:

| Org-level script | Required before `onboard-account.sh` (SSO path)? | Required before `aws-iam-bootstrap.sh` (IAM/standalone path)? |
| --- | --- | --- |
| `setup-organization.sh` | **Yes — strictly required.** Creates the Org root and the `NexusProduction` OU. Without it, `onboard-account.sh` refuses to move the new account to a missing OU and aborts at phase 3a. | **No.** The new account is standalone and never joins any Org. |
| `apply-service-control-policies.sh` | Recommended. Creates and attaches the five Org SCPs (root protection, IAM guardrails, region restriction, service whitelist, security baseline). If you skip it the new account joins SCP-free; the SCPs can be applied later without re-onboarding. | **No.** SCPs are an Org-only concept and never apply to a standalone account. |
| `enable-security-services.sh` | Recommended. Bootstraps org-wide CloudTrail, GuardDuty, Config, Security Hub, Access Analyzer. Without it `onboard-account.sh` phase 3d (`guardduty create-members` / `securityhub create-members`) logs `WARN` and skips that enrollment. | **No.** The standalone child is not enrolled in any org-wide service. The in-account hardening that `secure-member-account.sh` applies during `aws-iam-bootstrap.sh` is independent of these. |

> **For an Org-member onboarding (SSO path / `onboard-account.sh`):**
> Run the three scripts above once in the management account before
> onboarding the first participant. All three are idempotent, so it's safe
> to re-run any of them later if you skipped one and want to catch up.
>
> **For a standalone onboarding (IAM path / `aws-iam-bootstrap.sh`):**
> Skip this entire section. The bootstrap is fully self-contained against
> the target account using its root access keys — no Org, no management
> profile, no prior setup of any kind in this directory is required. The
> hardening + `NexusClusterProvisioner` steps inside the bootstrap are
> applied **in-place** against the new account, not via any org-level
> mechanism.

Order of operations once everything is in place:

```text
(once, in management account)
  setup-organization.sh
  apply-service-control-policies.sh
  enable-security-services.sh

(per child account, pick ONE)
  ─ Org-member path ──────────────────────────────
    onboard-account.sh
       └─ secure-member-account.sh            (cross-account assume-role)
       └─ setup-cross-account-roles.sh        (cross-account assume-role)
       └─ guardduty/securityhub create-members
       └─ lib/assign-sso-admin.sh

  ─ Standalone path ──────────────────────────────
    aws-iam-bootstrap.sh
       └─ secure-member-account.sh --no-assume
       └─ setup-cross-account-roles.sh --no-assume
```

---

## Which script do I run?

Both `aws-iam-bootstrap.sh` and `onboard-account.sh` take participant root keys,
**apply the same hardening baseline and create the same `NexusClusterProvisioner`
role**, then revoke the bootstrap root keys. The only deliberate difference is
Org membership and how callers authenticate:

| You want to … | Use |
|---|---|
| Join the account to the PTR Technologies Organization and let humans sign in via SSO (account inherits SCPs, gets enrolled in GuardDuty / Security Hub, sits under `NexusProduction` OU) | `onboard-account.sh` |
| Leave the account standalone (no Org, no SCPs, no SSO) but still get the same in-account hardening, the same `NexusClusterProvisioner` role, and a local CLI profile so you can run `aws --profile <name> …` against it | `aws-iam-bootstrap.sh` |
| Both, in sequence (rare) | Run `aws-iam-bootstrap.sh` first to get a usable profile, then `onboard-account.sh` — note the SCPs applied during onboarding will lock down what the bootstrap-created user can do |

**Identical in both paths** (no drift between standalone and Org-member children):

| Action | Both | Notes |
|---|---|---|
| `secure-member-account.sh` baseline (password policy, S3 BPA, EBS encryption, IMDSv2 default, default-VPC delete, region opt-outs) | ✓ | `onboard-account.sh` invokes via cross-account assume-role; `aws-iam-bootstrap.sh` invokes the same script with `--no-assume --profile <new-admin>` |
| `setup-cross-account-roles.sh` (creates `NexusClusterProvisioner` + permission boundary, gated by `--external-id`) | ✓ | Trust principal differs: in Org mode it trusts `arn:aws:iam::<mgmt>:root`; in standalone mode it trusts `arn:aws:iam::<local>:root` |

**Differs by design:**

| Action | `onboard-account.sh` | `aws-iam-bootstrap.sh` |
|---|---|---|
| Accept Org invitation + create `OrganizationAccountAccessRole` | ✓ | — |
| Move account to `NexusProduction` OU; inherit org-level SCPs | ✓ | — |
| `guardduty create-members` / `securityhub create-members` (as org-wide service member) | ✓ | — |
| SSO assignment (`AdministratorAccess` for `papu`) | ✓ | — |
| Local IAM admin user + access key + `~/.aws/credentials` profile | — | ✓ |
| Audit-logs manifest JSON | ✓ | — |

Operationally: `aws-iam-bootstrap.sh` needs **only** the participant root keys
(no management profile, no Org); `onboard-account.sh` needs the management
profile **as well as** the participant root keys.

> **A third option, `setup-member-account.sh`,** is the recommended path
> when you want a fully-onboarded standalone child account (everything
> `aws-iam-bootstrap.sh` does, **plus** CloudTrail / GuardDuty /
> Security Hub / AWS Config / Access Analyzer / cost-allocation tags /
> budgets / region lockdown — all from the member-account side, no
> management account involved). It internally calls `aws-iam-bootstrap.sh`
> for IAM-admin-user creation. See the dedicated `setup-member-account.sh`
> section further down. **`setup-member-account.sh` is the script that
> reads `.env.member.local`.**

---

## Configuration files (`.env.iam.local` and `.env.member.local`)

Two `.env.*.local` files live in this directory. They are **not**
interchangeable and they are **not** read together — each is consumed
by exactly one script:

| File | Read by | Not read by | Format |
| --- | --- | --- | --- |
| `.env.iam.local` | `aws-iam-bootstrap.sh` | `setup-member-account.sh`, `onboard-account.sh`, all others | Bash-sourceable `KEY=value` (UPPER_SNAKE_CASE only — file is `source`d) |
| `.env.member.local` | `setup-member-account.sh` | `aws-iam-bootstrap.sh`, `onboard-account.sh`, all others | `KEY=value`, parsed line-by-line. Accepts **both** `UPPER_SNAKE_CASE` **and** `lowercase-with-hyphens` (the latter is normalised at parse time, so `management-account-id` ≡ `MANAGEMENT_ACCOUNT_ID`) |

> **Common misconception (worth stating once):** `aws-iam-bootstrap.sh`
> does **not** read `.env.member.local`. Even when
> `setup-member-account.sh` calls `aws-iam-bootstrap.sh` internally
> during its Phase 1 (i.e. when `create-iam-admin-user` is set), it
> passes everything as **CLI flags** built from `.env.member.local`.
> The inner `aws-iam-bootstrap.sh` invocation does not load
> `.env.iam.local` either — its flags already cover every input it
> needs, and `setup-member-account.sh` exports `ROOT_AK` / `ROOT_SK`
> into the subshell so the bootstrap doesn't re-read them from disk.
>
> In short:
> - Run `aws-iam-bootstrap.sh` directly → reads `.env.iam.local`.
> - Run `setup-member-account.sh` (or call `aws-iam-bootstrap.sh` from
>   `setup-member-account.sh`) → reads `.env.member.local` only.
> - You may keep both files populated on disk; they will not interfere.

Both files must be `chmod 600` (each consumer script warns at startup
if the permissions are looser). Both are already covered by the
repo-wide `.env.*.local` gitignore rule, so they cannot be committed.

### What goes in `.env.iam.local`

Required for `aws-iam-bootstrap.sh`: only the root credentials. Every
other line is optional — each key maps 1:1 to a CLI flag and overrides
the default if set. The file is bash-`source`d, so identifiers must be
valid bash variable names (`UPPER_SNAKE_CASE`, no hyphens, no spaces
around `=`).

```bash
# ── Required ──────────────────────────────────────────────────────────
# Root credentials of the target standalone account. Either pair works;
# AWS_* names are SCRUBBED from the shell environment immediately after
# sourcing so they cannot leak into any aws-cli call that bypasses the
# script's internal aws_as_root helper.
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
# AWS_SESSION_TOKEN=...                   # only if you have an STS session
# ROOT_AK=AKIA... / ROOT_SK=... / ROOT_TOKEN=...   # internal aliases, also accepted

# ── Optional defaults (each = one CLI flag) ──────────────────────────
ACCOUNT_ID=040740747817                   # --account-id
PROFILE_NAME=promode-official             # --profile-name
IAM_USER_NAME=papu                        # --iam-user-name
REGION=us-east-1                          # --region
EXTERNAL_ID=nexus-provision-2026          # --external-id  (NexusClusterProvisioner trust)
# IMPORTANT: 12-digit account ID whose root will be trusted by
# NexusClusterProvisioner. Set this to your management account ID so
# the role is assumable from elsewhere via assume-role-to-profile.sh /
# similar. Leave EMPTY only for a truly isolated account (the role
# will then trust only the local account and can only be assumed from
# inside it).
MANAGEMENT_ACCOUNT_ID=654654554404        # --management-account-id
SKIP_HARDENING=no                         # --skip-hardening
SKIP_PROVISIONER_ROLE=no                  # --skip-provisioner-role
KEEP_ROOT_KEY=no                          # --keep-root-key (skip phase 9)
AUTO_APPROVE=yes                          # --auto-approve
DRY_RUN=no                                # --dry-run
```

Precedence (highest wins): CLI flag > parent-shell env var > `.env.iam.local`.

> **Centrally-managed standalone accounts: set `MANAGEMENT_ACCOUNT_ID`.**
> Without it, `aws-iam-bootstrap.sh` builds `NexusClusterProvisioner`
> with trust = local account, so the role can only be assumed from
> inside the new account itself. `assume-role-to-profile.sh` from your
> management account will return `AccessDenied`. If you intend to drive
> the new child centrally (the usual case), set this key.
>
> The simpler way to manage centrally is to use
> `setup-member-account.sh` instead — its `management-account-id` is
> required, so this footgun cannot fire.

### What goes in `.env.member.local`

Drives `setup-member-account.sh`. Two extra keys vs. `.env.iam.local`:
`management-account-id` (the trust principal embedded in the
`NexusClusterProvisioner` role) and budget settings. The custom parser
also tolerates `lowercase-with-hyphens` keys, which is why this file
typically reads like a CLI-flag list rather than bash assignments.

```bash
# ── Required: identity of the member account being set up ────────────
account-id=040740747817                   # --account-id (member account)
management-account-id=654654554404        # --management-account-id (trust principal)

# ── Required: root credentials of the member account ─────────────────
ROOT_AK=AKIA...
ROOT_SK=...
# ROOT_TOKEN=...                          # only if STS session
# AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY are also accepted (aliased
# at parse time to ROOT_AK / ROOT_SK)

# ── Required: which AWS region this account is allowed to use ────────
allowed-region=us-east-1                  # --allowed-region. Default-VPCs in EVERY
                                          # other region are deleted; every opt-in
                                          # region except this one is disabled.

# ── External-ID gating on NexusClusterProvisioner trust ──────────────
# Leave EMPTY to skip the sts:ExternalId condition (recommended when
# the assuming identity is an SSO/IAM user in the management account
# with AdministratorAccess; trust is then scoped by Principal alone).
# Set a non-empty value only if your assume-role caller (e.g.
# aws-login/assume-role-to-profile.sh) passes --external-id <value>.
external-id=nexus-provision-2026

# ── Phase 1: optionally create an IAM admin user + CLI profile ───────
# When set, setup-member-account.sh invokes aws-iam-bootstrap.sh with
# --iam-user-name=<this> --profile-name=<this> --keep-root-key, so the
# inner bootstrap creates the user but leaves root-key revocation to
# setup-member-account.sh's own Phase 6. Leave empty to use only the
# role-based access path (assume NexusClusterProvisioner from the
# management account).
create-iam-admin-user=papu

# ── Phase 4: budget visibility ───────────────────────────────────────
# Both must be set to enable the monthly Budget + CloudWatch billing
# alarm. Leave budget-email empty to skip both.
budget-email=ops@example.com              # --budget-email
monthly-budget-usd=100                    # --monthly-budget-usd

# ── Behaviour flags ──────────────────────────────────────────────────
keep-root-key=no                          # --keep-root-key (skip phase 6)
skip-region-lockdown=no                   # --skip-region-lockdown (skip phase 3)
auto-approve=yes                          # --auto-approve
dry-run=no                                # --dry-run
```

Precedence (highest wins): CLI flag > parent-shell env var > `.env.member.local`.

### End-to-end: onboarding a member account using both scripts

The intended workflow is to run `setup-member-account.sh` and let it
drive `aws-iam-bootstrap.sh` for the IAM-admin-user step:

```bash
cd nexus-deployer/aws-account

# 1. Edit .env.member.local with the member's account-id, root keys,
#    your management-account-id, and the region you want to keep.
#    Setting `create-iam-admin-user=<name>` is what triggers the
#    bootstrap call in Phase 1.
$EDITOR .env.member.local
chmod 600 .env.member.local

# 2. Run the full member-account setup. Reads .env.member.local.
./setup-member-account.sh --dry-run        # preview every AWS call first
./setup-member-account.sh                  # real run; ~3-5 min
```

Internally `setup-member-account.sh`'s Phase 1 invokes
`aws-iam-bootstrap.sh` with explicit flags (no env-file sourcing):

```text
ROOT_AK=$ROOT_AK ROOT_SK=$ROOT_SK \
    bash aws-iam-bootstrap.sh \
        --account-id            ${account-id}                    \
        --profile-name          ${create-iam-admin-user}         \
        --iam-user-name         ${create-iam-admin-user}         \
        --region                ${allowed-region}                \
        --keep-root-key                                          \
        --auto-approve
```

So in practice `.env.iam.local` is only consulted when you run
`aws-iam-bootstrap.sh` **directly** (which you only need to do when
you want just the IAM-admin-user + CLI-profile slice without the full
member-account setup — e.g. building a sandboxed dev profile against
an already-onboarded account).

---

## `onboard-account.sh` — one-shot account onboarding

Takes an existing AWS account (where you hold the root access keys), joins
it to the PTR Technologies Organization under `NexusProduction`, runs the
full hardening + cross-account-role + security-services stack against it,
assigns SSO `AdministratorAccess` to user `papu`, deletes the bootstrap
root access key, and writes a JSON manifest.

### Prerequisites

1. **Organization already bootstrapped.** See
   [Before you start: org-level prerequisites](#before-you-start-org-level-prerequisites)
   above — at minimum, `setup-organization.sh` must have run once in the
   management account, otherwise this orchestrator aborts at phase 3a
   (move-to-OU). The SCP and security-service scripts are recommended
   but not strictly blocking.
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

---

## `aws-iam-bootstrap.sh` — standalone-account IAM bootstrap

Takes an existing AWS account (where you hold the root access keys) **that is
not joining any AWS Organization** and produces a fully-hardened standalone
child account with a usable AWS CLI profile. Used for customer-owned
accounts, isolated demo accounts, or any environment where Identity Center
/ SSO is not in play.

### What it does

Phases run in order; the bootstrap root key is held in env-var-only memory
throughout and revoked at the end:

1. Create an IAM admin user (`papu` by default) with `AdministratorAccess`
   and a programmatic access key.
2. Write a local AWS CLI profile (`--profile-name`) under `~/.aws/credentials`
   + `~/.aws/config` pointing at the new key.
3. **Apply the same hardening as `secure-member-account.sh`** — invokes
   the sibling script with `--no-assume --profile <new-admin>` so the
   baseline runs against the local account directly, no cross-account
   role assumption needed. Covers password policy, S3 Block Public Access,
   EBS default encryption, IMDSv2-as-default, default-VPC deletion in
   every region, opt-in region disable.
4. **Create the same `NexusClusterProvisioner` role + permission boundary**
   as `setup-cross-account-roles.sh` — invoked with `--no-assume --profile
   <new-admin> --external-id <secret>`. Trust principal in standalone mode
   is `arn:aws:iam::<local-account>:root`, meaning any IAM identity in
   the new child account with `sts:AssumeRole` permission **and** the
   correct external-id can assume the role.
5. Revoke the bootstrap root access key.

Compared to `onboard-account.sh` this script deliberately **does not**:

- invite the account to any Organization;
- create `OrganizationAccountAccessRole`;
- enroll the account in org-managed GuardDuty / Security Hub / Config;
- write an audit-logs manifest.

It is otherwise hardened identically; phases 3 + 4 call the same sibling
scripts so future security updates apply uniformly to both onboarding
paths.

### Prerequisites

**No org-level setup is required.** Unlike `onboard-account.sh`, this
script never touches AWS Organizations — you do **not** need
`setup-organization.sh` / `apply-service-control-policies.sh` /
`enable-security-services.sh` to have run anywhere first. See
[Before you start: org-level prerequisites](#before-you-start-org-level-prerequisites)
for the full comparison.

What you do need:

1. **Participant root access key + secret** — supplied via flags, env vars,
   or `.env.iam.local`. The script aborts hard if the keys don't resolve to
   the expected `--account-id` or if the caller ARN does not end in `:root`.
2. **A free local profile name** — `--profile-name` cannot already exist;
   if it does, the script backs up `~/.aws/credentials` to a timestamped
   `.bak` before overwriting.
3. **A free IAM user name** in the target account — `--iam-user-name`
   (default `papu`) must not already exist; the script refuses to proceed
   otherwise.
4. **A target account you are willing to harden in-place** — phase 7
   deletes default VPCs in every region and opts out of unused opt-in
   regions. Do not run against an account with live workloads in a
   default VPC, or pass `--skip-hardening`.

### Usage

```bash
cd nexus-deployer/aws-account

./aws-iam-bootstrap.sh \
    --account-id              040740747817 \
    --root-access-key-id      "$ROOT_AK" \
    --root-secret-access-key  "$ROOT_SK" \
    --profile-name            promode-official \
    --auto-approve
```

Optional flags:

| Flag | Default | Meaning |
| --- | --- | --- |
| `--iam-user-name` | `papu` | Name of the IAM admin user to create |
| `--region` | `us-east-1` | Default region written into the local profile |
| `--external-id` | `nexus-provision-<YYYY>` | `sts:ExternalId` enforced on the `NexusClusterProvisioner` trust policy. Set the same value in your assume-role caller |
| `--management-account-id` | unset | **Highly recommended.** 12-digit account ID whose root will be trusted by the new `NexusClusterProvisioner` role. When unset, the role trusts the **local account only**, so it can be assumed only from inside the new account and `assume-role-to-profile.sh` from any other account returns `AccessDenied`. Set this to your management account ID (e.g. `654654554404` for the PTR Technologies org) to make the role centrally usable |
| `--skip-hardening` | off | Skip phase 3 (`secure-member-account.sh`). Account will **not** match the standard child baseline; use only for an account you cannot harden right now (e.g. it has live workloads that would break on default-VPC deletion) |
| `--skip-provisioner-role` | off | Skip phase 4 (`setup-cross-account-roles.sh`). The new account will lack `NexusClusterProvisioner` and cannot be driven by the cluster-provisioner tooling until you re-run with this flag off |
| `--keep-root-key` | off | Do **not** revoke the bootstrap root access key at the end (use sparingly) |
| `--auto-approve` | off | Skip the interactive confirmation prompt; also passed through to the sibling hardening / provisioner scripts so they don't double-prompt |
| `--dry-run` | off | Print every AWS call without executing |
| `--root-session-token` / env `ROOT_TOKEN` | unset | Optional STS session token if you have one |

> **Note on `--external-id`.** The `NexusClusterProvisioner` trust policy
> enforces this string as a `sts:ExternalId` condition. If you forget it,
> the next time you try to assume the role you will get an
> `AccessDenied`. The default (`nexus-provision-<YYYY>`) matches what
> `setup-cross-account-roles.sh` produces in Org mode, so both paths can
> share the same caller tooling.

Root keys can also be passed via env vars to avoid putting them on the
command line:

```bash
ROOT_AK=AKIA... ROOT_SK=... ./aws-iam-bootstrap.sh \
    --account-id 040740747817 \
    --profile-name promode-official \
    --auto-approve
```

### Config file (`.env.iam.local`)

When `.env.iam.local` exists alongside the script it is auto-sourced before
flag parsing, so you can run the script with no arguments at all once the
file is populated. The file supports two key-naming conventions:

```bash
# AWS-standard names (preferred — same names AWS CLI / SDK expect)
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...

# ── or the script-internal names ──
ROOT_AK=AKIA...
ROOT_SK=...

# Plus any of these (each maps 1:1 to a CLI flag)
ACCOUNT_ID=040740747817
PROFILE_NAME=promode-official
IAM_USER_NAME=papu
REGION=us-east-1
EXTERNAL_ID=nexus-provision-2026
SKIP_HARDENING=no
SKIP_PROVISIONER_ROLE=no
KEEP_ROOT_KEY=no
AUTO_APPROVE=yes
DRY_RUN=no
```

**Precedence** (highest wins): CLI flag > parent-shell env var > `.env.iam.local`.

The script warns if `.env.iam.local` permissions are looser than `600` /
`400`. Use a non-default path with `ENV_FILE=/path/to/other.env`.

After sourcing, `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN`
are immediately `unset` from the shell environment so they cannot leak into
any aws-cli call that bypasses the script's internal `aws_as_root` /
`new_aws` helpers.

### Phases

```
1. Verify root identity        sts get-caller-identity (as supplied creds);
                               aborts unless Account == --account-id AND
                               ARN ends in :root
2. Pre-flight                  iam get-user --iam-user-name must FAIL
                               (refuse to step on an existing user)
3. Create IAM admin user       iam create-user + attach AdministratorAccess
4. Create access key           iam create-access-key for the new user
5. Write CLI profile           aws configure set ... --profile <name>
                               (backs up existing same-named profile first)
6. Verify new profile          sts get-caller-identity via the new profile;
                               retries 6× with 5s backoff for IAM
                               eventual-consistency
7. Harden child account        invokes secure-member-account.sh
                               --no-assume --profile <new-admin>:
                                 - IAM password policy
                                 - S3 Block Public Access (account)
                                 - EBS default encryption
                                 - IMDSv2 account default
                                 - delete default VPCs in every region
                                 - opt-out of unused opt-in regions
                               (skipped if --skip-hardening)
8. NexusClusterProvisioner     invokes setup-cross-account-roles.sh
                               --no-assume --profile <new-admin>
                               --external-id <secret>
                               [--trust-account-id <mgmt>]:
                                 - creates NexusClusterProvisioner role
                                 - trust principal:
                                     * arn:...:<mgmt-account>:root when
                                       --management-account-id is set
                                     * arn:...:<this-account>:root when
                                       --management-account-id is NOT set
                                       (role is only assumable from
                                       INSIDE this account in that case)
                                 - sts:ExternalId condition enforced
                                 - NexusClusterProvisionerPolicy attached
                                 - NexusProvisionerBoundary attached
                                   (permission boundary; identical
                                   policy doc as the role policy)
                               (skipped if --skip-provisioner-role)
9. Revoke bootstrap root key   iam delete-access-key on the supplied root AK
                               (skipped if --keep-root-key). Phases 7+8
                               run BEFORE this so a hardening failure
                               leaves root creds intact for recovery.
```

### Security model

- **Root key never touches disk.** Accepted only via flag, env var, or
  `.env.iam.local` (which lives outside git via `*.local` ignore rule and
  must be `chmod 600`).
- **No command tracing.** `set +x` at script start prevents accidental
  echo of secrets even if the caller exports `PS4` / sets `BASH_XTRACEFD`.
- **AWS env vars are scrubbed before any aws-cli call.** After sourcing the
  config file the script `unset`s `AWS_ACCESS_KEY_ID`,
  `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AWS_PROFILE`,
  `AWS_DEFAULT_PROFILE` so any inherited shell context cannot redirect a
  later call to the wrong account.
- **`aws_as_root` injects creds inline per call**, never via long-lived
  exports.
- **Identity is verified before any write.** `verify_root_identity` aborts
  hard if `sts get-caller-identity` returns a different account ID or a
  non-root ARN.
- **Bootstrap key is revoked at the end.** From that point forward the
  account has no programmatic root credentials. The next time you need
  root, sign in via the web console (and please enable MFA there).
- **Secrets are scrubbed on exit.** `unset ROOT_AK ROOT_SK ROOT_TOKEN
  NEW_AK NEW_SK` runs even on normal completion.

### Hang-prevention measures inside `aws_as_root`

The wrapper is hardened against three failure modes observed in real
deployments:

| Failure mode | Mitigation |
| --- | --- |
| aws-cli v2 opens its pager (`less`) and blocks for stdout capture | `AWS_PAGER=""` + `--no-cli-pager` + `< /dev/null` |
| On a non-EC2 host, aws-cli probes `169.254.169.254` IMDS and waits ~30s per attempt | `AWS_EC2_METADATA_DISABLED=true` |
| Hung TCP / DNS leaving the script frozen indefinitely | `--cli-connect-timeout 10 --cli-read-timeout 20` + outer `timeout 45` |

If `sts get-caller-identity` times out at 45s, the script tells you exactly
how to reproduce it by hand and where to look (DNS for
`sts.us-east-1.amazonaws.com`, network egress).

### Idempotency and recovery

| Step | Re-run behaviour |
| --- | --- |
| Verify root identity | Read-only; safe to re-run |
| Pre-flight (user exists?) | **Fails hard if `--iam-user-name` already exists.** Choose a different name or delete the user first |
| Create user / attach policy | Not re-tried in-script; if user exists you won't reach this step (see above) |
| Create access key | Not idempotent — re-running on an existing user that already has an access key will fail at `--iam-user-name` pre-flight; if you removed the pre-flight you would hit AWS's 2-access-key-per-user limit |
| Write CLI profile | Existing profile under the same name is backed up to `~/.aws/credentials.bak.<ts>` before overwrite |
| Verify new profile | Read-only; retries 6× for IAM eventual consistency |
| Harden (phase 7) | `secure-member-account.sh` is idempotent: every action either is a single `put` (overwrite) or guards with a "skip if absent" pattern (e.g. VPC delete is a no-op when none present). Safe to re-run |
| `NexusClusterProvisioner` (phase 8) | `setup-cross-account-roles.sh` detects the existing role and updates trust + policy + boundary in place. Safe to re-run |
| Revoke root key | If the key is already deleted, AWS returns an error which the script downgrades to a `warn` and tells you how to delete the leftover key manually |

**Failure handling.** Phases 7 and 8 each die hard on non-zero exit from
the sibling script. The bootstrap root key is **not** revoked when this
happens, so you can re-run after fixing the underlying issue. If you
genuinely cannot run hardening or the provisioner role in this account
(e.g. you are bootstrapping a customer-owned account where you only have
a 1-hour root-key window), pass `--skip-hardening` and / or
`--skip-provisioner-role` to bypass.

**To resume after a partial failure:** the script does not write a manifest.
Inspect `~/.aws/credentials` (was the new profile written?), then list IAM
users in the target account (`aws iam list-users` with the root creds, or
via the console) to find out where it stopped. Clean up the partial state
and re-run with the same flags.

### Verifying success

```bash
PROFILE=promode-official
ACCT=<account-id>
EXT=nexus-provision-2026   # the value you passed to --external-id

# (1) The new profile resolves to the expected account.
aws --profile "$PROFILE" sts get-caller-identity

# (2) The bootstrap root key is gone.
AWS_ACCESS_KEY_ID="$ROOT_AK" AWS_SECRET_ACCESS_KEY="$ROOT_SK" \
    aws iam list-access-keys --user-name root    # → expect InvalidClientTokenId

# (3) Baseline was applied (skip these if you used --skip-hardening).
aws --profile "$PROFILE" iam get-account-password-policy
aws --profile "$PROFILE" s3control get-public-access-block --account-id "$ACCT"
aws --profile "$PROFILE" ec2  get-ebs-encryption-by-default
aws --profile "$PROFILE" ec2  get-instance-metadata-defaults
# Expect at most one default VPC (us-east-1 may persist if it was the
# only region kept enabled and you ran with workloads in it — the script
# warns rather than failing in that case):
aws --profile "$PROFILE" ec2 describe-vpcs \
    --filters Name=isDefault,Values=true \
    --query 'Vpcs[].{Region:`us-east-1`,Id:VpcId}'

# (4) NexusClusterProvisioner exists (skip if --skip-provisioner-role).
aws --profile "$PROFILE" iam get-role --role-name NexusClusterProvisioner \
    --query 'Role.AssumeRolePolicyDocument'
# Check the trust principal:
#   * with --management-account-id set, expect arn:...:<mgmt>:root
#   * without --management-account-id, expect arn:...:<this-account>:root
#     (in which case the role is NOT assumable from elsewhere — see the
#     "trust footgun" callout in the .env.iam.local section above).
aws --profile "$PROFILE" iam list-attached-role-policies \
    --role-name NexusClusterProvisioner

# (5) End-to-end: can the new profile actually assume the role?
aws --profile "$PROFILE" sts assume-role \
    --role-arn "arn:aws:iam::${ACCT}:role/NexusClusterProvisioner" \
    --external-id "$EXT" \
    --role-session-name verify-bootstrap \
    --query 'Credentials.AccessKeyId' --output text
```

After this you can drive any AWS tool from the new profile, e.g.:

```bash
cd nexus-deployer/deploy/eks
./create-hardened-eks-cluster.sh \
    --profile promode-official \
    --region  us-east-1 \
    ...
```

---

## `setup-member-account.sh` — full member-account setup (standalone)

The most comprehensive standalone-mode tool in this directory. Runs
**entirely from the member account's root keys** (no management account
needed) and produces a member account that is "cluster-ready" — every
in-account control plane covered by `secure-member-account.sh` plus
CloudTrail, GuardDuty, Security Hub, AWS Config, Access Analyzer,
cost-allocation tags, monthly budget + CloudWatch billing alarm,
default-VPC deletion in every region, and the `NexusClusterProvisioner`
role with permission boundary.

Compared to `aws-iam-bootstrap.sh`:

- **Superset** of `aws-iam-bootstrap.sh`'s phases. Anything the bootstrap
  does (IAM admin user, CLI profile, hardening baseline, provisioner
  role, root-key revocation) is either invoked or duplicated here.
- **Adds** the cross-account-aware orchestration that `aws-iam-bootstrap.sh`
  intentionally leaves out: org-equivalent security services running
  **inside the member account itself** (not via Org delegation),
  region lockdown across every commercial region, and budget visibility.
- Trust policy on `NexusClusterProvisioner` points at the value of
  `--management-account-id`, not the bootstrap account, so the resulting
  account is ready to be driven from the PTR Technologies management
  account's `assume-role-to-profile.sh` workflow.

### Usage

```bash
cd nexus-deployer/aws-account

# All defaults from .env.member.local; works with zero CLI args:
./setup-member-account.sh --dry-run
./setup-member-account.sh

# Or with all flags explicit (no .env.member.local needed):
ROOT_AK=AKIA... ROOT_SK=... \
  ./setup-member-account.sh \
      --account-id            040740747817 \
      --management-account-id 654654554404 \
      --allowed-region        us-east-1 \
      --external-id           nexus-provision-2026 \
      --budget-email          ops@example.com \
      --monthly-budget-usd    100 \
      --create-iam-admin-user papu \
      --auto-approve
```

### Phases

```
0. Validate         Root creds + account identity (sts get-caller-identity);
                    aborts unless Account == --account-id AND ARN ends :root
1. Identity         IAM password policy + Access Analyzer (account scope);
                    optionally invokes aws-iam-bootstrap.sh to create the
                    IAM admin user named --create-iam-admin-user (with
                    --keep-root-key so phase 6 still revokes here)
2. Security         S3 BPA + EBS encryption + IMDSv2 default + CloudTrail
                    (own bucket, multi-region, log validation) + GuardDuty
                    (in --allowed-region) + Security Hub (default standards)
                    + AWS Config (recorder + delivery channel + own bucket)
3. Region lockdown  Delete default VPC in every region; disable every
                    opt-in region except --allowed-region (skipped if
                    --skip-region-lockdown)
4. Billing          Activate nexus:* cost-allocation tags; monthly Budget
                    with 80% / 100% / forecast email alerts; CloudWatch
                    EstimatedCharges alarm in us-east-1 (skipped if no
                    --budget-email)
5. Provisioner      NexusClusterProvisioner role + policy + permission
                    boundary. Trust principal = arn:aws:iam::<management-
                    account-id>:root, optionally + sts:ExternalId condition
                    when --external-id is non-empty
6. Revoke root key  iam delete-access-key on the bootstrap root AK
                    (skipped if --keep-root-key)
7. Manifest         Writes audit-logs/setup-member-<accountId>-<ts>.json
                    with every phase's status and detail
```

### Flags

Every flag has a 1:1 mapping into `.env.member.local` — see the file format
documented above. Required flags: `--account-id`, `--management-account-id`,
`--root-access-key-id`, `--root-secret-access-key` (or env-var / config-file
equivalents). Behavioural flags: `--external-id`, `--allowed-region`,
`--budget-email`, `--monthly-budget-usd`, `--create-iam-admin-user`,
`--keep-root-key`, `--skip-region-lockdown`, `--auto-approve`, `--dry-run`.

Full reference: `./setup-member-account.sh --help`.

### When to use `setup-member-account.sh` vs `aws-iam-bootstrap.sh`

| You want… | Run |
| --- | --- |
| A fully-configured standalone member account ready to be driven by `assume-role-to-profile.sh` from the management account (CloudTrail / GuardDuty / SecHub / Config / budgets / region lockdown all in place) | `setup-member-account.sh` |
| Just an IAM admin user + local CLI profile in a standalone account, with the standard hardening baseline (S3 BPA / EBS / IMDSv2 / password policy / default-VPC delete / region opt-outs) and `NexusClusterProvisioner` — but **without** CloudTrail / GuardDuty / SecHub / Config / budgets | `aws-iam-bootstrap.sh` |
| The same as `setup-member-account.sh` but you also want a CLI profile against the new account | Set `create-iam-admin-user=<name>` in `.env.member.local`; phase 1 will invoke `aws-iam-bootstrap.sh` for you |

---

## Files

```
deploy/aws-account/
├── onboard-account.sh                 # org-member orchestrator
│                                      #   reads NO .env file directly;
│                                      #   gets management profile from
│                                      #   nexus-backend/.env.sso.local
├── setup-member-account.sh            # full member-account setup (standalone)
│                                      #   ↳ reads .env.member.local
│                                      #   ↳ optionally invokes
│                                      #     aws-iam-bootstrap.sh in phase 1
├── aws-iam-bootstrap.sh               # standalone-account IAM bootstrap
│                                      #   ↳ reads .env.iam.local
│                                      #   ↳ invokes the two sibling scripts
│                                      #     below with --no-assume to apply
│                                      #     uniform child-account hardening
├── secure-member-account.sh           # baseline hardening
│                                      #   default: cross-account assume-role
│                                      #   --no-assume: in-place via --profile
├── setup-cross-account-roles.sh       # NexusClusterProvisioner + boundary
│                                      #   default: cross-account assume-role
│                                      #   --no-assume: in-place via --profile
├── .env.iam.local                     # (gitignored) defaults for aws-iam-bootstrap.sh only
├── .env.member.local                  # (gitignored) defaults for setup-member-account.sh only
├── lib/
│   ├── participant-bootstrap.sh       # onboard phase 2: root-creds helper
│   └── assign-sso-admin.sh            # onboard phase 3e: SSO assignment helper
├── policies/
│   ├── oaa-trust-policy.json                       # OrganizationAccountAccessRole trust template
│   ├── cross-account-provisioner-role.json         # NexusClusterProvisioner trust template
│   ├── cross-account-provisioner-policy.json       # NexusClusterProvisioner policy doc
│   └── ... (SCP policies)
└── audit-logs/                        # onboarding manifests (created on first run)
```

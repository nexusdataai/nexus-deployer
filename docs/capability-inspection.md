# Capability Inspection (step 10)

The wizard's **Inspect Capability** panel is reachable from the
Post-Verification step. It runs a full-parity port of
`kube-operator/inspect-capability.sh`, returning 17 sections of
diagnostics in a single response.

Endpoint:
`GET /api/eks/pipeline/clusters/{cluster_name}/capability/{cr_name}/inspect`

Backend implementation: [backend/app/services/capability_inspector.py](../backend/app/services/capability_inspector.py).
Frontend renderer: [frontend/src/components/InspectCapability.tsx](../frontend/src/components/InspectCapability.tsx).

## Sections

Sections 1-7 and 13-17 are external-API probes (boto3, kubernetes-client).
Sections 8-12 execute inside the backend pod via `kubernetes-client` exec
streams, so they reflect the workload's view of the world (DNS, IAM
identity, etc.).

| # | Section | Probe |
|---|---|---|
| 1 | `k8s_resources` | Deployments, StatefulSets, Pods, Services, Ingresses in the capability namespace |
| 2 | `service_versions` | Container `image:tag` per Deployment |
| 3 | `dynamodb` | `dynamodb:DescribeTable` for each `<capability>-<env>-*` table |
| 4 | `s3` | `s3:ListBuckets` filtered to `<capability>-<env>-*` |
| 5 | `glue` | `glue:GetDatabase` + `GetTables` for `<capability>_<env>_db` |
| 6 | `athena_wg` | `athena:GetWorkGroup` (`primary`) |
| 7 | `athena_deep` | End-to-end: `SHOW TABLES IN <db>` query, polled to completion |
| 8 | `wxcc` | DNS+TLS smoke from backend pod for `api.wxcc.cisco.com` |
| 9 | `licensing_iot` | DNS+TLS smoke from backend pod for `iot.<region>.amazonaws.com` + `data.iot.<region>.amazonaws.com` |
| 10 | `call_processing` | Backend `/health` endpoint smoke from inside the pod |
| 11 | `app_perms_vpce` | Re-runs the reachability probe inside the backend pod (mirrors step 7 but with workload identity) |
| 12 | `call_db_doctor` | Glue catalog accessible from the workload's IRSA identity |
| 13 | `ssm` | SSM parameters under `/<capability>/<env>/` |
| 14 | `secrets` | Secrets Manager under `<capability>/<env>/` |
| 15 | `iam` | Operator role + per-capability app role: ARN + attached policies |
| 16 | `cognito` | User pools matching `<capability>-<env>` |
| 17 | `alb` | ALBs tagged with `nexus.ai/capability=<capability>` |

## Verdict aggregation

Each section returns `pass` / `warn` / `fail` / `skipped`. The overall
report verdict is the worst of any section. Healthy sections collapse by
default in the UI; failing or warning sections expand so the user sees
problems first.

Sections that throw an exception while running are isolated - the report
still includes the other 16 sections, with the failed one flagged
`status=fail` and the exception message in `summary`.

## When to use

- **Right after deploy**: confirm everything reconciled correctly. The
  Post-Verification step exposes a "Run full inspection" button.
- **Troubleshooting**: surface the exact AWS resource state + pod
  identity + connectivity in one place, without leaving the UI for
  `kubectl` and `aws` CLI.
- **Upgrade verification**: re-run after the operator reconciles a CR
  patch to confirm the data plane is consistent with the new spec.

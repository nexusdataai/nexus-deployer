# Cloudflare Tunnel (local K3s)

Exposes product UIs on **local-cluster** via in-cluster `cloudflared`. TLS and DNS are at Cloudflare; origins are frontend ClusterIP services (nginx proxies `/api` to backends).

## Public hostnames

| Hostname | Origin |
|----------|--------|
| `https://ontology.yourbrain.tech` | `http://ontology-local-frontend-svc.ontology-local.svc.cluster.local:8080` |
| `https://simulator.yourbrain.tech` | `http://simulator-local-frontend-svc.simulator-local.svc.cluster.local:8080` |
| `https://ai-engine.yourbrain.tech` | `http://ai-engine-local-frontend-svc.ai-engine-local.svc.cluster.local:8080` |
| `https://sre.yourbrain.tech` | `http://nexus-sre-ui.nexus-sre.svc.cluster.local:80` (Helm: `local-k3s/nexus-sre-values-local.yaml`) |
| `https://fde-training.yourbrain.tech` | `http://nexus-training-api.training-local.svc.cluster.local:8000` (`nexus-training/deploy/k8s/`) |

Configure these as **Public Hostnames** on your tunnel in Cloudflare Zero Trust (HTTP to origin, no TLS verify needed for internal HTTP).

Prefer **Tunnel → Public Hostname** (plain HTTP origin). If routes show **Published application**, Cloudflare Access may block browsers until you add an allow policy (or remove the app and use hostname-only routing).

### Troubleshooting “site loads but API/UI is blank”

Frontends must forward `X-Forwarded-Proto: https` to backends (use `CF-Connecting-IP` on the origin hop) and rewrite backend redirects with `proxy_redirect http:// https://`. Without that, APIs redirect to `http://…` and the browser blocks mixed content. Redeploy frontends after updating nginx configs, or patch the frontend ConfigMaps and `kubectl rollout restart` the frontend Deployments.

## Deploy

```bash
export KUBECONFIG=/opt/mycode/nexus/nexus-deployer/aws-login/.kube/config
kubectl config use-context local-cluster

kubectl apply -f namespace.yaml

kubectl create secret generic cloudflared-token \
  -n cloudflare \
  --from-literal=TUNNEL_TOKEN='<token-from-zero-trust>' \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f deployment.yaml
kubectl rollout status deployment/cloudflared -n cloudflare
kubectl logs -n cloudflare deploy/cloudflared --tail=30
```

## Ontology simulator link

```bash
kubectl set env deployment/ontology-local-backend -n ontology-local \
  SIMULATOR_UI_URL=https://simulator.yourbrain.tech
```

## Security

- Do not commit tunnel tokens. Use `secret.example.yaml` as documentation only.
- Do not route `nexus-local` infra (MinIO, Redis, Postgres) through the tunnel.
- Use Cloudflare Access on each public hostname for dev/staging.

## Rotate token

Update the secret and restart:

```bash
kubectl delete secret cloudflared-token -n cloudflare
kubectl create secret generic cloudflared-token -n cloudflare --from-literal=TUNNEL_TOKEN='<new-token>'
kubectl rollout restart deployment/cloudflared -n cloudflare
```

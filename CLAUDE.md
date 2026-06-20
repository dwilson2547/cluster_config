# cluster_config

Kubernetes manifests and ArgoCD application definitions for the home cluster.

## How ArgoCD Works Here

ArgoCD watches this repo (and a few external repos) and automatically syncs changes to the cluster. All ArgoCD `Application` resources live in `argocd/` and **must be applied manually** — ArgoCD can't bootstrap itself:

```bash
kubectl apply -f argocd/ai-services.yaml
kubectl apply -f argocd/monitoring.yaml
# etc.
```

Once applied, ArgoCD takes over. All apps are configured with `automated` sync (`prune: true`, `selfHeal: true`), so pushing to `main` in this repo is all that's needed to deploy changes.

## Two Deployment Patterns

### 1. Manifest-based (this repo)

Most services are plain Kubernetes manifests tracked directly in this repo. ArgoCD syncs the directory on every push to `main`.

| Service | Directory | ArgoCD App |
|---|---|---|
| ai-services | `ai-services/` | `argocd/ai-services.yaml` |
| monitoring | `monitoring/` | `argocd/monitoring.yaml` |
| postgres | `postgres/` | `argocd/postgres.yaml` |
| timescaledb | `timescaledb/` | `argocd/timescaledb.yaml` |
| homepage | `homepage/` | `argocd/homepage.yaml` |
| dns | `dns/` | `argocd/dns.yaml` |
| rtk-caster | `rtk-caster/` | `argocd/rtk-caster.yaml` |
| vpn | `vpn/` | `argocd/vpn.yaml` |
| searxng | `searxng/` | `argocd/searxng.yaml` |
| ingress + argocd ingress | `argocd/ingress.yaml` | (applied manually) |
| reloader | — (Helm chart, stakater) | `argocd/reloader.yaml` |
| flink-operator | `flink-operator/` (Helm values) | `argocd/flink-operator.yaml` |

### 2. Self-managed Helm (external repos)

**gyopart** and **scrape-stack** manage their own Helm charts and use a `main`/`dev` branch strategy for prod vs dev environments:

| App | Repo | Branch | Namespace | Values |
|---|---|---|---|---|
| gyopart | `dwilson2547/gyopart` | `main` | `gyopart` | `values.yaml` |
| gyopart-dev | `dwilson2547/gyopart` | `dev` | `gyopart-dev` | `values-dev.yaml` |
| scrape-stack | `dwilson2547/scrape-stack` | `main` | `scrape-stack` | — |
| scrape-stack-dev | `dwilson2547/scrape-stack` | `dev` | `scrape-stack-dev` | — |

For these services, changes are made and committed in their own repos — ArgoCD picks them up automatically. The Helm chart lives at `helm/<service>/` in each repo.

## Secret Management

Secrets are **not** managed by ArgoCD — they must be created in the cluster manually before (or just after) the ArgoCD app is applied. Either order works since ArgoCD will retry on failure.

**Pattern:**
```bash
# 1. Create the namespace (if not using CreateNamespace=true)
kubectl create namespace <namespace>

# 2. Apply the secret
kubectl apply -f <service>/secret.yml

# 3. Apply the ArgoCD app (or push to main if it's already registered)
kubectl apply -f argocd/<service>.yaml
```

Each service directory contains a `secret.yml` (gitignored if it has real values) and/or an `example_secret.yml` / `example-secrets/` template showing the required keys. Fill in real values and apply — never commit real secrets.

The `example-secrets/` directory at the repo root has templates for services whose secrets aren't co-located.

### Required pre-push secret gate

Before **every push**, scan staged changes for secret-like values and stop if any real credential appears.

```bash
git --no-pager diff --cached | grep -nE '(^|[[:space:]])(password|passwd|secret|token|api[_-]?key)[^#\n]*[:=]'
```

If output includes non-placeholder values, do not push. Placeholders must remain placeholders (for example: `replace-me`, `your-password-here`, `CHANGE_ME_*`).

## Adding a New Service

1. Create a directory for the manifests (e.g. `my-service/`)
2. Add a `deployment.yml` (or split into separate files — ArgoCD syncs the whole directory)
3. If secrets are needed, add a `secret.yml` with placeholder values and apply the real version manually
4. Create an `Application` in `argocd/my-service.yaml` pointing at `path: my-service`
5. `kubectl apply -f argocd/my-service.yaml` — ArgoCD handles the rest from here
6. Push to `main` for any subsequent changes

## `kubernetes/` Directory

Contains legacy and one-off manifests that predate the ArgoCD setup (postgres, browserless, grafana, immich, etc.). These are **not** actively synced by ArgoCD — treat them as reference/archive. Some may be partially superseded by the ArgoCD-managed services above.

## Key Ingress Hostnames

| Host | Service |
|---|---|
| `argocd.local` | ArgoCD UI |
| `notes.ai-services.local` | AI Notes |
| `playbooks.ai-services.local` | AI Playbooks |
| `docs.ai-services.local` | AI Tool Docs |
| `home.cluster.local` | Homepage dashboard |

## Notes

- ArgoCD is configured with `server.insecure: true` (in `argocd/ingress.yaml`) so Traefik can proxy plain HTTP — no cert needed on the ArgoCD side.
- postgres `Application` has `ignoreDifferences` on `StatefulSet.spec.volumeClaimTemplates` to prevent ArgoCD from fighting over immutable PVC template fields.
- Reloader (stakater) watches for ConfigMap/Secret changes and triggers rolling restarts on affected Deployments.

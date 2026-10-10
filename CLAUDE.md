# cluster_config

Kubernetes manifests and ArgoCD application definitions for the home cluster.

## How ArgoCD Works Here

Every ArgoCD `Application` lives in `argocd/` in this repo, including those whose Helm chart lives in
another repo (gyopart, scrape-stack, danwiki, ...). The chart belongs to the app; the decision to
deploy it belongs here. Do not put Application manifests in other repos.

`argocd/` is synced by the app-of-apps root `bootstrap/apps.yaml`, the only Application applied by
hand (once, or after editing it):

```bash
kubectl apply -f bootstrap/apps.yaml
```

Adding or editing a file in `argocd/` is just a push. The root has `prune: false`: removing a file
does **not** remove the Application; also run `kubectl delete application <name> -n argocd` (child
apps have no resources-finalizer, so their workloads are orphaned, not deleted).

Once registered, each app syncs its own source. All apps are configured with `automated` sync (`prune: true`, `selfHeal: true`), so pushing to `main` in this repo is all that's needed to deploy changes.

## microk8s addons: never disable ingress, metallb or cert-manager

Traefik (`ingress` namespace) and MetalLB were installed by microk8s addons and are now owned by ArgoCD
(`traefik/`, `metallb/`). cert-manager is Argo-installed; its addon was disabled. `microk8s disable
ingress` / `metallb` would delete the Argo-managed resources and take down every ingress and
LoadBalancer IP. Change them here, through git.

## Public vs internal ingress

Traefik has two LoadBalancers. `traefik` (192.168.0.60, entrypoints `web`/`websecure`) is LAN-only
and is the default: an Ingress that names no entrypoint is internal. `traefik-public`
(192.168.0.65, entrypoints `pubweb`/`pubsecure`) is what the router forwards WAN 80/443 to. To publish
a service, give its Ingress a `*.danwils.com` host, TLS via `cert-manager.io/cluster-issuer:
letsencrypt-prod`, and `traefik.ingress.kubernetes.io/router.entrypoints: pubsecure`. Never point the
router at .60: every internal Ingress would be reachable from the internet by Host header.

DNS for public hosts is automatic: external-dns (`external-dns/`) creates a proxied CNAME
`<name>.danwils.com → danwils.com` for any Ingress labelled `dns.danwils.com/public: "true"` with
annotation `external-dns.kubernetes.io/target: danwils.com` (v0.23 ignores the old
`external-dns.alpha.` prefix; the target then falls back to .60 and is silently excluded), and deletes it with the Ingress. It only
touches records it owns (TXT `_extdns-cname.<name>`); the apex A record is ddclient's.

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
| homepage-public (https://danwils.com) | `homepage-public/` | `argocd/homepage-public.yaml` |
| dns | `dns/` | `argocd/dns.yaml` |
| rtk-caster | `rtk-caster/` | `argocd/rtk-caster.yaml` |
| vpn | `vpn/` | `argocd/vpn.yaml` |
| searxng | `searxng/` | `argocd/searxng.yaml` |
| argocd-server ingress + `server.insecure` | `argocd-server/ingress.yaml` | (applied manually) |
| reloader | — (Helm chart, stakater) | `argocd/reloader.yaml` |
| cert-manager | `cert-manager/` (Helm values + `issuers/`) | `argocd/cert-manager.yaml` |
| traefik (ingress, LB 192.168.0.60) | `traefik/values.yaml` (Helm values) | `argocd/traefik.yaml` |
| external-dns (Cloudflare records) | `external-dns/values.yaml` (Helm values) | `argocd/external-dns.yaml` |
| metallb (LB IP pool) | `metallb/` (upstream manifest + `pool.yaml`) | `argocd/metallb.yaml` |
| flink-operator | `flink-operator/` (Helm values) | `argocd/flink-operator.yaml` |

### 2. Helm charts in external repos

The chart lives in the app's own repo (`helm/<service>/`), with a `main`/`dev` branch strategy for
prod vs dev; the Application lives in `argocd/` here. Chart changes are pushed to the app repo and
picked up automatically.

| App | Repo | Branch | Namespace | Values |
|---|---|---|---|---|
| gyopart-dev | `dwilson2547/gyopart` | `dev` | `gyopart-dev` | `values-dev.yaml` |
| scrape-stack | `dwilson2547/scrape_stack` | `main` | `scrape-stack` | `values.yaml` |
| scrape-stack-dev | `dwilson2547/scrape_stack` | `dev` | `scrapestack-dev` | `values-dev.yaml` |
| danwiki | `dwilson2547/DanWiki` | `main` | `danwiki` | `values.yaml` |
| photo-dump-dev | `dwilson2547/photo_dump` | `dev` | `photo-dump-dev` | `values-dev.yaml` |
| robo-services, build-sim, dxf-converter | own repos | `main` | own | see `argocd/` |

## Secret Management

Secrets are **not** managed by ArgoCD — they must be created in the cluster manually before (or just after) the ArgoCD app is applied. Either order works since ArgoCD will retry on failure.

**Pattern:**
```bash
# 1. Create the namespace (if not using CreateNamespace=true)
kubectl create namespace <namespace>

# 2. Apply the secret
kubectl apply -f <service>/secret.yml

# 3. Push the Application manifest in argocd/ — the root app registers it
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
5. Push to `main` — the root app registers it and ArgoCD handles the rest

## `kubernetes/` Directory

Contains legacy and one-off manifests that predate the ArgoCD setup (postgres, browserless, grafana, immich, etc.). These are **not** actively synced by ArgoCD — treat them as reference/archive. Some may be partially superseded by the ArgoCD-managed services above.

## Key Ingress Hostnames

| Host | Service |
|---|---|
| `argocd.local` | ArgoCD UI |
| `notes.ai-services.local` | AI Notes |
| `playbooks.ai-services.local` | AI Playbooks |
| `docs.ai-services.local` | AI Tool Docs |
| `home.cluster.local` | Homepage dashboard (internal) |
| `danwils.com` | Public landing page (homepage-public, cert-manager TLS) |

## Notes

- ArgoCD is configured with `server.insecure: true` (in `argocd-server/ingress.yaml`) so Traefik can proxy plain HTTP — no cert needed on the ArgoCD side.
- postgres `Application` has `ignoreDifferences` on `StatefulSet.spec.volumeClaimTemplates` to prevent ArgoCD from fighting over immutable PVC template fields.
- Reloader (stakater) watches for ConfigMap/Secret changes and triggers rolling restarts on affected Deployments.

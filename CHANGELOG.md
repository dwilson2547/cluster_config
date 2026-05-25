## 2026-05-25 - Todo Store ingress sync fix

### Fixed

- Corrected the mis-indented backend service ports in `ingress-todo-store` so ArgoCD could create the Todo Store route — see [docs/issues/2026_05_25_todo_store_ingress_port_indentation.md](docs/issues/2026_05_25_todo_store_ingress_port_indentation.md)

---

## 2026-05-25 - Todo Store added to ai-services

### Added

- Added Todo Store API/UI to `ai-services/deployment.yml` with a shared PVC, nginx UI override, and `/api` ingress routing via the existing `ai-services-strip-api-prefix` middleware
- Added `todo.ai-services.local` to the `ai-services.local` DNS zone in `dns/dns.yaml`
- Added Todo Store to the AI Services group in `homepage/homepage.yaml`

---

## 2026-05-24 - Homepage dashboard, gyopart deployment, and cluster.local DNS zone

### Homepage (gethomepage.dev)

Deployed at `home.cluster.local` via `homepage/homepage.yaml`. Full manifest
includes Namespace, ServiceAccount, ClusterRole/Binding (read access to pods,
nodes, namespaces, ingresses, ingressroutes), ConfigMap, Deployment, Service,
and Ingress. All configuration lives in the ConfigMap — edit and push to
update the dashboard without rebuilding any image.

**Groups configured**

| Group | Services |
|-------|----------|
| Gyopart | UI, API docs, Admin |
| Gyopart Dev | UI, API docs, Admin |
| Scrape Stack | Cache Browser, Auth, Webcache/Imgcache/Vidcache/Filecache APIs |
| Scrape Stack Dev | Same, on scrapestack-dev.local |
| AI Services | AI Notes, AI Playbooks |
| Cluster | ArgoCD, Grafana, SearXNG |
| Infrastructure | Router (192.168.0.1), TrueNAS SSD (192.168.0.10), Unraid (192.168.0.15), HPC (192.168.0.50) |

**Bookmarks:** GitHub (gyopart, cluster_config, all repos), Docker Hub, PyPI.

ArgoCD app applied manually: `kubectl apply -f argocd/homepage.yaml`

### cluster.local DNS zone

Added `cluster.local` as the central zone for cluster-wide services not tied
to a specific stack. Wildcard `* IN A 192.168.0.60` means any new subdomain
resolves to Traefik without a further DNS update. Also added a wildcard to
`monitoring.local` for the same reason.

### gyopart ArgoCD applications

Added `argocd/gyopart.yaml` (namespace: `gyopart`, targetRevision: `main`) and
`argocd/gyopart-dev.yaml` (namespace: `gyopart-dev`, targetRevision: `dev`).
Both point at `https://github.com/dwilson2547/gyopart.git` (public repo, HTTPS).
Applied manually — these are not auto-discovered from the folder.

Added DNS zones `gyopart.local` and `gyopart-dev.local` (both wildcard → Traefik).

### ai-services ingress (StripPrefix fix)

Added Traefik `StripPrefix` middleware for the `/api` path on ai-notes and
ai-playbooks ingresses. Without it, the prefix was forwarded to the upstream
FastAPI service and all `/api/*` routes returned 404.

---

## 2026-05-24 - Onboard remaining services to ArgoCD

Added ArgoCD applications for dns, monitoring, and postgres. Also added
searxng and vpn (committed separately earlier in the session).

**Applications added**

| App | Path | Sync |
|-----|------|------|
| searxng | `searxng/` | Automated (prune + selfHeal) |
| vpn | `vpn/` | Automated (prune + selfHeal) |
| dns | `dns/` | Automated (prune + selfHeal) |
| monitoring | `monitoring/` | Automated (prune + selfHeal) |
| postgres | `postgres/` | **Manual** — live data, no automated reconciliation |

**Structure decisions**

- ddclient merged into `dns/` — both services share the `dns` namespace;
  a single app avoids two apps competing over the same Namespace resource
- `monitoring/helm-values/` subdirectory holds Loki and Tempo Helm install
  reference values; ArgoCD does not recurse into subdirectories so these
  are excluded from sync automatically
- Postgres app uses `ignoreDifferences` on `StatefulSet/spec/volumeClaimTemplates`
  to prevent ArgoCD from flagging the immutable field as drift

**Secret handling**

All services follow the public-repo pattern: real secrets are pre-provisioned
manually with `kubectl apply` and are never committed. `example-secrets/<service>/secret.yml`
files serve as templates. `.gitignore` covers `**/secret.yml` (with negation
for `example-secrets/`), `**/example_secret.yml`, `**/.claude/`, `*.log`,
and `**/init-*.sql`.

**searxng migration note**

Original deployment used `search.danwils.com` with TLS via cert-manager and
`storageClassName: nfs-crucial`. Migrated to `search.local` (insecure, ingress
only), `nfs-dataset` storage class to match cluster default. Old resources
were manually deleted before sync due to immutable PVC storageClassName.

---

## 2026-05-22 - ArgoCD installation and ingress

Installed ArgoCD into the cluster and exposed the web UI at `argocd.local`.

**Installation**

```bash
kubectl create namespace argocd
kubectl apply -n argocd --server-side --force-conflicts -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
```

**Configuration**

- Added `cluster/argocd/ingress.yaml`:
  - `argocd-cmd-params-cm` ConfigMap sets `server.insecure: "true"` so argocd-server serves plain HTTP
  - Ingress routes `argocd.local` → `argocd-server:80` via Traefik (`ingressClassName: nginx`)

**DNS**

- Updated `cluster/dns/dns.yaml` to incorporate the previously applied `coredns-patch-add-dev-zones.yaml` (patch file no longer needed)
- Added `argocd.local` zone to CoreDNS pointing apex `A` record at Traefik (`192.168.0.60`)

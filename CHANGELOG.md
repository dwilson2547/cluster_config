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

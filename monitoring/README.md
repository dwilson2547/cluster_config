# Monitoring Stack

Grafana observability stack running in the `monitoring` namespace.

## Layout

| Path | Purpose |
|---|---|
| `argocd/monitoring.yaml` | Parent ArgoCD app for the monitoring stack |
| `monitoring/apps/` | Child ArgoCD `Application` manifests |
| `monitoring/manifests/` | Raw Kubernetes manifests managed by the `monitoring-extras` child app |
| `monitoring/helm-values/` | Helm values files used by the chart-based child apps |

## Child apps

| App | Source | Version | Purpose |
|---|---|---|---|
| `monitoring-prometheus` | `prometheus-community/kube-prometheus-stack` | `82.4.3` | Prometheus, Grafana, Alertmanager, Prometheus Operator |
| `monitoring-loki` | `grafana-community/loki` | `17.1.1` | Log aggregation |
| `monitoring-tempo` | `grafana-community/tempo` | `2.1.2` | Trace storage |
| `monitoring-extras` | `monitoring/manifests/` | repo-managed | OTEL collector, datasources, ingress, `ServiceMonitor`s |

The parent app at `argocd/monitoring.yaml` points to `monitoring/apps`, so ArgoCD manages the child apps and they manage the actual monitoring resources.

## Bootstrap and updates

Normal changes are GitOps-only:

```bash
git push origin main
```

If you change `argocd/monitoring.yaml` itself, apply it manually because ArgoCD does not self-manage its own `Application` definitions:

```bash
kubectl apply -f argocd/monitoring.yaml
```

## Helm values

The child apps use pinned chart versions plus values stored in this repo:

- `monitoring/helm-values/prometheus-values.yaml`
- `monitoring/helm-values/loki-values.yaml`
- `monitoring/helm-values/tempo-values.yaml`

This keeps the chart configuration reviewable in Git instead of relying on `helm upgrade --reuse-values`.

For the current cluster migration, `monitoring/helm-values/prometheus-values.yaml` sets `crds.enabled: false` so ArgoCD does not try to re-patch the already-installed Prometheus Operator CRDs and hit Kubernetes annotation size limits. If you ever need to bootstrap this stack from a blank cluster again, handle those CRDs as a separate one-time bootstrap step first.

## Raw manifests

`monitoring/manifests/` contains the non-chart resources that sit alongside the Helm releases:

- OTEL collector
- Grafana datasource provisioning
- Grafana ingress
- `ServiceMonitor`s, including the OTEL collector scrape and the cross-namespace Iggy scrape

## Access

- Grafana: http://monitoring.local
- Grafana (alternate host): http://grafana.scrapestack.local
- Admin password: `kubectl get secret prometheus-grafana -n monitoring -o jsonpath="{.data.admin-password}" | base64 -d`

## App integration

Apps push telemetry to the OTEL collector in the `monitoring` namespace:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.monitoring.svc.cluster.local:4318
```

The collector fans out:

- Metrics → Prometheus (via the collector's `:8889/metrics` endpoint)
- Traces → Tempo
- Logs → Loki

Prometheus can also scrape services directly through `ServiceMonitor`s, such as the Iggy broker in `pub-sub`.

## Gotchas

- **microk8s TLS**: the self-signed CA lacks the Key Usage extension. Loki's sidecar requires `sidecar.skipTlsVerify: true` in `monitoring/helm-values/loki-values.yaml` to avoid CrashLoopBackOff.
- **Loki WAL on NFS**: if Loki crashes uncleanly, the WAL directory may need manual clearing before it will restart. Location: inside the `loki-0` PVC at `/var/loki/wal`.
- **Loki gateway**: use `http://loki-gateway.monitoring.svc.cluster.local` (not the pod directly) for the Grafana datasource and any direct log pushes.
- **Do not** run `microk8s enable observability` — it requires hostpath storage and will conflict with this setup.

# Monitoring Stack

Grafana observability stack running in the `monitoring` namespace.

## Components

| Component | How installed | Purpose |
|---|---|---|
| kube-prometheus-stack | Helm (`prometheus-community/kube-prometheus-stack`) | Prometheus + Grafana + Alertmanager |
| Loki | Helm (`grafana-community/loki`) | Log aggregation |
| Tempo | Helm (`grafana-community/tempo`) | Distributed tracing |
| OTEL Collector | `kubectl apply` | Receives metrics/traces/logs from apps, fans out to backends |
| Grafana datasources | `kubectl apply` | Auto-provisions Loki + Tempo datasources into Grafana |
| Grafana ingress | `kubectl apply` | Exposes Grafana at `monitoring.local` |
| ServiceMonitor | `kubectl apply` | Tells Prometheus to scrape OTEL collector metrics |

## Fresh install

```bash
# 1. Add Helm repos
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update

# 2. Install kube-prometheus-stack
helm install prometheus prometheus-community/kube-prometheus-stack \
    --namespace monitoring --create-namespace \
    --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.storageClassName=nfs-dataset \
    --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.resources.requests.storage=50Gi \
    --set alertmanager.alertmanagerSpec.storage.volumeClaimTemplate.spec.storageClassName=nfs-dataset \
    --set alertmanager.alertmanagerSpec.storage.volumeClaimTemplate.spec.resources.requests.storage=10Gi \
    --set grafana.persistence.enabled=true \
    --set grafana.persistence.storageClassName=nfs-dataset \
    --set grafana.persistence.size=10Gi

# 3. Install Loki and Tempo
helm install loki grafana-community/loki --namespace monitoring -f loki-values.yaml
helm install tempo grafana-community/tempo --namespace monitoring -f tempo-values.yaml

# 4. Apply manifests
kubectl apply -f grafana-datasources.yaml
kubectl apply -f otel-collector.yaml
kubectl apply -f service-monitor.yaml
kubectl apply -f ingress.yaml
```

## Upgrades

```bash
helm upgrade prometheus prometheus-community/kube-prometheus-stack --namespace monitoring --reuse-values
helm upgrade loki grafana-community/loki --namespace monitoring -f loki-values.yaml
helm upgrade tempo grafana-community/tempo --namespace monitoring -f tempo-values.yaml
```

## Access

- Grafana: http://monitoring.local (also http://grafana.scrapestack.local)
- Admin password: `kubectl get secret prometheus-grafana -n monitoring -o jsonpath="{.data.admin-password}" | base64 -d`

## App integration

Apps push telemetry to the OTEL collector in the `monitoring` namespace:

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.monitoring.svc.cluster.local:4318
```

The collector fans out:
- Metrics → Prometheus (scraped from collector's `:8889/metrics` endpoint)
- Traces → Tempo
- Logs → Loki

## Gotchas

- **microk8s TLS**: The self-signed CA lacks the Key Usage extension. Loki's sidecar requires `sidecar.skipTlsVerify: true` in `loki-values.yaml` to avoid CrashLoopBackOff.
- **Loki WAL on NFS**: If Loki crashes uncleanly, the WAL directory may need manual clearing before it will restart. Location: inside the `loki-0` PVC at `/var/loki/wal`.
- **Loki gateway**: Use `http://loki-gateway.monitoring.svc.cluster.local` (not the pod directly) for the Grafana datasource and any direct log pushes.
- **Do not** run `microk8s enable observability` — it requires hostpath storage and will conflict with this setup.

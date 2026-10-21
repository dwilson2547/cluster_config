# Alerting

Prometheus rules come from kube-prometheus-stack (`monitoring/helm-values/prometheus-values.yaml`) plus the
PrometheusRules in this repo. Alertmanager mails dwilson2547@gmail.com through Gmail SMTP (secret
`alertmanager-smtp`, key `SMTP_PASSWORD`, copied into each namespace that holds an AlertmanagerConfig).

## Routing

| Config | Namespace | Mails |
|---|---|---|
| `cluster-alerts` (`monitoring/manifests/cluster-alerts.yaml`) | monitoring | root route: every `critical`, plus a short list of warnings |
| `postgres-backup-email` (`monitoring/manifests/postgres-backup-alerts.yaml`) | postgres | `PostgresBackup*`, `PostgresRestoreTest*` |
| `secrets-backup-email` (`secrets-backup/alerts.yaml`) | secrets-backup | `SecretsBackup*` |
| `offsite-backup-email` (`offsite-backup/alerts.yaml`) | offsite-backup | `OffsiteBackup*` |

`cluster-alerts` is Alertmanager's root config (`alertmanagerSpec.alertmanagerConfiguration`), so it sees alerts
from every namespace. The namespaced configs only match alerts carrying their own namespace label (the operator
adds that matcher) and are evaluated first, so a backup alert is mailed once.

Warnings mailed by `cluster-alerts`: crashlooping pods, node not ready/unreachable/flapping, volume or node disk
filling, node memory, clock sync, deployment/statefulset replicas or rollouts stuck, failed Jobs, scrape targets
down. To mail another alert, add its name to the regex in the second route. Repeats every 24h while firing; a
resolved notice follows.

scrape-job-manager's own Jobs are left out of `KubeJobFailed`: they fail and retry as normal operation, and
scrape-job-manager mails on its own (`ScrapeJob*` alerts stay unmailed for the same reason; `ScrapeOperatorDown` is
critical and is mailed). A failed Job keeps `KubeJobFailed` firing until the Job is deleted.

## Tower (Unraid)

`monitoring/manifests/tower-monitoring.yaml` scrapes Tower's node_exporter (Unraid plugin, `192.168.0.15:9100`) as
job `tower-node`. That job name keeps it out of the chart's node-exporter rules and dashboards. If the exporter is
unreachable, `TargetDown` fires and is mailed.

| Alert | Fires when | Mailed |
|---|---|---|
| `TowerConnectionCountHigh` | `node_nf_conntrack_entries` > 3000 for 10m (baseline < 100) | yes |
| `TowerCPUSaturated` | CPU > 80% for 30m, outside the parity window | yes |
| `TowerCPUElevated` | CPU > 50% for 3h, outside the parity window | no |
| `TowerBtrfsDeviceErrors` | any btrfs device error counter rises | yes |

These target the 2026-10 Plex compromise: a crypto miner (CPU) and a residential proxy (a flood of connections, with
no unusual bandwidth). Write-up: workspace `docs/machines/2026_10_20_plex_owner_token_transcoder_codec_injection.md`.

**Parity window:** the monthly parity check (starts on the 1st at local midnight, runs about 22h) pins every core.
Both CPU alerts are suppressed from 00:00 UTC on the 1st to 12:00 UTC on the 2nd, because PromQL time is UTC. If the
parity schedule moves, move the `unless` clause in both rules with it.

There is no per-container CPU yet, which would need cAdvisor on Tower, so an alert says something is wrong on Tower
but not which container.

## Turned off

`kubeProxy`, `kubeScheduler`, `kubeControllerManager` and `kubeEtcd` monitoring are disabled: microk8s runs the
first three inside kubelite and uses dqlite instead of etcd, so their `*Down` alerts could never clear.

## Checking

```bash
kubectl -n monitoring port-forward svc/prometheus-kube-prometheus-alertmanager 9093   # UI: what fires, what was sent
kubectl -n monitoring logs alertmanager-prometheus-kube-prometheus-alertmanager-0 -c alertmanager | grep -i notify
```

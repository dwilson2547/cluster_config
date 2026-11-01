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

### Triage (incident-operator)

The `email` receiver of `cluster-alerts` also posts to incident-operator's in-cluster webhook
(`incident-operator-webhook.incident-operator.svc/alertmanager`, `sendResolved`). So every alert mailed by
`cluster-alerts` is also triaged: incident-operator collects read-only evidence, asks a local model through
gpu-scheduler, and mails one suggestion per incident (subject `[triage] …`). Alerts mailed by the namespaced backup
configs are not triaged (they stop before the root route). Details: `infra/incident-operator/README.md`.

scrape-job-manager's own Jobs are left out of `KubeJobFailed`: they fail and retry as normal operation, and
scrape-job-manager mails on its own (`ScrapeJob*` alerts stay unmailed for the same reason; `ScrapeOperatorDown` is
critical and is mailed). A failed Job keeps `KubeJobFailed` firing until the Job is deleted.

## Tower (Unraid)

`monitoring/manifests/tower-monitoring.yaml` scrapes Tower's node_exporter (Unraid plugin, `192.168.0.15:9100`) as
job `tower-node`, and its cAdvisor (`192.168.0.15:8080`) as job `tower-cadvisor`, keeping only CPU, memory and
network families and dropping cAdvisor's `container_label_*` labels. The `tower-node` job name keeps Tower out of
the chart's node-exporter rules and dashboards. If either exporter is unreachable, `TargetDown` fires and is mailed.
cAdvisor is an ordinary Unraid Docker container: it must have autostart on, or it stays down after every Unraid
reboot and `TargetDown{job="tower-cadvisor"}` fires (seen 2026-10-23 after an update reboot; autostart now on).

| Alert | Fires when | Mailed |
|---|---|---|
| `TowerConnectionCountHigh` | `node_nf_conntrack_entries` > 3000 for 10m (baseline < 100) | yes |
| `TowerContainerCPUHigh` | one container uses more than 6 of 12 cores for 30m (names the container) | yes |
| `TowerContainerCPUSustained` | one container's 1h average CPU is above 1 core, held for 2h | yes |
| `TowerCPUSaturated` | CPU > 80% for 30m, outside the parity window | yes |
| `TowerCPUElevated` | CPU > 50% for 3h, outside the parity window | no |
| `TowerBtrfsDeviceErrors` | any btrfs device error counter rises | yes |

These target the 2026-10 Plex compromise: a crypto miner (CPU) and a residential proxy (a flood of connections, with
no unusual bandwidth). Write-up: workspace `docs/machines/2026_10_20_plex_owner_token_transcoder_codec_injection.md`.

**Parity window:** the monthly parity check (starts on the 1st at local midnight, runs about 22h) pins every core.
Both CPU alerts are suppressed from 00:00 UTC on the 1st to 12:00 UTC on the 2nd, because PromQL time is UTC. If the
parity schedule moves, move the `unless` clause in both rules with it.

`TowerContainerCPUSustained` is the one that fits the real incident. The miner ran as short-lived processes using
1–2 cores between them and hopping between cores, far below every other CPU threshold. Container CPU time sums across
cores and includes exited processes, so the churn still shows up as a steady load. Idle containers sit near 0.001
cores. Process-creation rate (`node_forks_total`) was considered and rejected: Unraid itself creates 20–60
processes a second, which hides a miner restarting every few seconds.

`TowerContainerCPUHigh` and `TowerContainerCPUSustained` need no parity window, because the parity check runs in the host, not in a container.

## Mac mini (inference node)

`monitoring/manifests/mac-monitoring.yaml` scrapes the Mac mini's node_exporter (Homebrew, started at login; the Mac
auto-logs in) at `192.168.0.30:9100` as job `mac-node`, instance `mac-mini`. It's gpu-scheduler's first remote
inference node (LM Studio): setup in `ai/gpu-scheduler/docs/remote-worker-mac.md`. The Mac being unreachable is the
chart's `TargetDown` for `mac-node`, already mailed.

A launchd keepalive on the Mac restarts LM Studio's server within a minute and writes text-file metrics on each run:
`lmstudio_server_up` and `lmstudio_keepalive_last_run_timestamp_seconds`.

| Alert | Fires when | Mailed |
|---|---|---|
| `MacLMStudioServerDown` | `lmstudio_server_up == 0` for 10m: the keepalive can't start the server | yes (critical) |
| `MacLMStudioKeepaliveStale` | the keepalive hasn't run for 5m, held 10m: launchd stopped running it, or no one is logged in | yes (critical) |

## Turned off

`kubeProxy`, `kubeScheduler`, `kubeControllerManager` and `kubeEtcd` monitoring are disabled: microk8s runs the
first three inside kubelite and uses dqlite instead of etcd, so their `*Down` alerts could never clear.

## Checking

```bash
kubectl -n monitoring port-forward svc/prometheus-kube-prometheus-alertmanager 9093   # UI: what fires, what was sent
kubectl -n monitoring logs alertmanager-prometheus-kube-prometheus-alertmanager-0 -c alertmanager | grep -i notify
```

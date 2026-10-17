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

## Turned off

`kubeProxy`, `kubeScheduler`, `kubeControllerManager` and `kubeEtcd` monitoring are disabled: microk8s runs the
first three inside kubelite and uses dqlite instead of etcd, so their `*Down` alerts could never clear.

## Checking

```bash
kubectl -n monitoring port-forward svc/prometheus-kube-prometheus-alertmanager 9093   # UI: what fires, what was sent
kubectl -n monitoring logs alertmanager-prometheus-kube-prometheus-alertmanager-0 -c alertmanager | grep -i notify
```

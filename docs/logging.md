# Logging

Loki (`monitoring/helm-values/loki-values.yaml`, single binary, 50 GiB `nfs-dataset` volume) keeps 90 days of
logs; its compactor deletes older chunks. Grafana reads it through the `Loki` data source (uid `loki`).

## What ships logs

| Source | How | What |
|---|---|---|
| Scraper fleet | DaemonSet `otel-agent` (`monitoring/manifests/otel-agent.yaml`) tails `/var/log/pods` on every node, OTLP to Loki | the `scraper` container in `gyopart`, `gyopart-dev`, `motorcycles`, `motorcycles-dev`, `rockauto-dev` |
| AIStor (TrueNAS) | audit webhook to `http://192.168.0.60/aistor-audit` (ingress `aistor-audit`), received by `otel-collector` | S3 requests that failed (status 400 and up); successful ones are dropped in the collector |
| Apps pushing OTLP | the `otel-collector` Deployment (`monitoring/manifests/otel-collector.yaml`) | whatever an app sends; none instrumented yet |

The agent reads only the paths in its `filelog.include` list: browserless sidecars and the rest of the cluster are
not collected. To add a namespace or container, add its path pattern there
(`/var/log/pods/<namespace>_*/<container>/*.log`). Read positions are kept per node in `/var/lib/otel-agent`, so a
restart doesn't send lines twice.

Scraper volume measured 2026-10-17: roughly 10-20 MB/day before compression (⚠ estimate from the pods kept then).

## Labels

Loki indexes these (from the OTel resource attributes, dots become underscores):

| Label | Value |
|---|---|
| `service_name` | the ScrapeJob (`scrape.danwils.com/job` pod label), e.g. `parts-direct-honda` |
| `k8s_namespace_name`, `k8s_pod_name`, `k8s_container_name`, `k8s_job_name` | where the line came from (`k8s_job_name` is one attempt) |

`scrape_run` and `scrape_attempt` ride along as structured metadata: filter with `| scrape_run="20261017023141"`.

```logql
{service_name="parts-direct-honda"}                                   # one job, all runs
{service_name="parts-direct-honda"} | scrape_run="20261017023141"     # one run
{k8s_container_name="scraper", k8s_namespace_name="gyopart"} |= "image failed"
```

The Scrape Jobs dashboard has a logs panel driven by its Namespace/Job variables.

## AIStor audit events

AIStor's audit webhook posts one JSON event per S3 request. The `otel-collector` receives them on
`/aistor-audit` (checking the `Authorization` header against the `otel-collector-aistor-audit` secret), keeps only
events with status 400 and up, and sends them to Loki as `service_name="aistor-audit"`. The full event is the line
body; these ride along as structured metadata: `status`, `api` (e.g. `HeadObject`), `bucket`, `object`,
`remote_host` (the caller; a pod IP for cluster clients), `user_agent`.

```logql
{service_name="aistor-audit"}                                  # all failed requests
sum by (remote_host, api, status) (count_over_time({service_name="aistor-audit"}[1h]))
```

A `HeadObject` 404 is normal: clients check whether an object exists before uploading it (the parts-direct
updaters do this for every new image).

AIStor setting (audit webhook): endpoint `http://192.168.0.60/aistor-audit`, auth token = the secret's `TOKEN`.
The ingress also answers on `otel-webhook.monitoring.local`; the IP form works without the `monitoring.local` zone.

## Permissions

`otel-agent` runs as root with the log directory mounted read-only (pod log files are `root:root 0640`), and its
service account can read pods, namespaces and replicasets cluster-wide (`otel-agent-rbac.yaml`) to label lines.

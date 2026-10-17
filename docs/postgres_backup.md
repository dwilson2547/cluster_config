# Postgres backups: design and runbook

Automated nightly logical backups for the prod postgres instances, shipped 2026-10-15, and a nightly copy of
the object-store buckets (2026-10-16).
Manifests: `postgres/backup.yaml`. Alerting: `monitoring/manifests/postgres-backup-alerts.yaml`.

## What gets backed up

| Instance | Namespace | CronJob | Schedule (ET) |
|---|---|---|---|
| `postgres` (15 DBs, v17) | postgres | `postgres-backup` | 02:30 daily |
| `postgres-pgvector` (v16) | postgres | `postgres-backup-pgvector` | 02:40 daily |

Not backed up: dev instances, timescaledb, and the `private` namespace (per decision
2026-10-15). Restore tests run Sundays 05:00/05:30 ET (`postgres-restore-test*`),
restoring the newest dump of every database into a `_restore_test_` scratch DB.

## Where the backups live

Unraid NFS export `192.168.0.15:/mnt/user/cluster_backup` — a separate box from the live
data (192.168.0.10). Pods run as uid 99 / gid 100 to match the export's squash mapping.

```
/backups/<instance>/<db>/<db>-<YYYYMMDD-HHMMSS>.dump   # pg_dump custom format (-Fc)
/backups/<instance>/globals-<YYYYMMDD-HHMMSS>.sql      # roles/grants (pg_dumpall globals)
/backups/<instance>/.last-success                      # stamp of last clean run
```

File stamps are UTC (containers run UTC); schedules are America/New_York. Retention:
every dump 7 days, Sunday dumps 28 days, everything else pruned by the backup script.
One nightly set is ~2.5GB (parts_interchange dominates: 23GB raw → ~2.4GB compressed).

## Object-store buckets

`postgres/object-backup.yaml`, CronJob `backup-objects`, 03:15 ET daily: rclone copies each `<remote>:<bucket>` in `BUCKETS`
(remote `aistor`) (TrueNAS, `192.168.0.10:30320`) to the same share. AIStor's free tier no longer allows replicating
between two instances, so this copy is the backup.

| Bucket | What |
|---|---|
| `nodewright` | nodewright attachments |
| `photo-dump-prod`, `photo-dump-dev` | photo-dump's photos (moved from the old MinIO on the Unraid box, 2026-10-16) |
| `part-images` | gyopart part images and diagrams: 6,859,975 objects, 134.6 GiB (copied from the old MinIO and checked object-for-object, 2026-10-17) |

All on AIStor. `part-images` keeps millions of objects in flat per-make folders: the job uses rclone ≥ 1.70 with
`--list-cutoff` so those listings sort on disk (`/tmp` emptyDir) instead of in memory. Left out: `dxf-converter`
(conversions) and `race-logger` (robo-services pipeline archive). The backup key is read-only and scoped to the
listed buckets: add a bucket to its AIStor policy as well as to `BUCKETS`.

```
/backups/objects/<bucket>/current/              mirror of the bucket
/backups/objects/<bucket>/replaced/<stamp>/     objects a run overwrote or deleted from current/ (28 days)
/backups/objects/.last-success
```

A run that would delete more than `MAX_DELETE` (500) objects stops before touching `current/` (a wrong key or an
emptied bucket). Credentials: secret `object-backup-s3` (read-only AIStor key; `example-secrets/postgres/`).
The backup alerts below cover it (failed job, no success in 26h, suspended).

Restore a bucket (or one prefix) from any pod or machine with the share:

```bash
rclone copy /backups/objects/<bucket>/current/<prefix> dst:<bucket>/<prefix>    # dst = an S3 remote with write access
# an object deleted or overwritten in the last 28 days: look under replaced/<stamp>/ first
```

## Restoring a database

From any machine with the NAS mounted, or a pod with the `postgres-backup` PVC:

```bash
# 1. Copy the dump somewhere writable if reading from the backup share read-only
#    (dump files are owned by uid 99; restore tools only need read access)

# 2. Restore globals first if the instance is fresh (roles the DB depends on)
psql -h <postgres-host> -U postgres -f globals-<stamp>.sql

# 3. Create the target database, then restore
createdb -h <postgres-host> -U postgres <db>
pg_restore -h <postgres-host> -U postgres -d <db> --exit-on-error <db>-<stamp>.dump
```

Version rule: use a client matching the server's major version — `postgres:17` tools for
the `postgres` instance, `pgvector/pgvector:pg16` tools for pgvector. A v17 `pg_restore`
against a PG16 server fails on `SET transaction_timeout`
(see `docs/issues/2026_10_15_pgvector_restore_transaction_timeout.md`).

The weekly restore-test CronJobs do exactly this automatically and email on failure;
their logs show what a clean restore looks like.

## Alerting

Four alerts (PrometheusRule `postgres-backup-alerts`): job failed, no successful backup in
26h, restore test not succeeded in 8 days, CronJob suspended. All email
dwilson2547@gmail.com via Gmail SMTP (secret `alertmanager-smtp` in namespace postgres,
copied from `scrape-job-manager-smtp`). Alertmanager UI: http://alertmanager.monitoring.local.

## Verifying a backup by hand

```bash
kubectl -n postgres get jobs                          # last runs and status
kubectl -n postgres logs job/<job-name>               # what the run did
# Trigger an immediate run without waiting for the schedule:
kubectl -n postgres create job --from=cronjob/postgres-backup backup-manual-$(date +%s)
```

## Gotchas on record

- `pg_restore` v17 emits `SET transaction_timeout`; a PG16 server rejects it →
  version-matched client images per instance
  (`docs/issues/2026_10_15_pgvector_restore_transaction_timeout.md`)
- The Unraid export squashes to 99:100 → pod securityContext matches, or writes fail
- PromQL `unless` matches the full label set → `unless on(namespace, cronjob)` in the
  staleness alerts (else they fire always)
- The AlertmanagerConfig must live in namespace `postgres`: the operator routes configs
  by their own namespace and the job metrics carry `namespace=postgres`

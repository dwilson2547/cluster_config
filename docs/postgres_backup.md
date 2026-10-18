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

## File volumes

`postgres/volume-backup.yaml`, CronJob `backup-volumes`, 02:50 ET daily. Each app volume's directory on TrueNAS
(`nfs-dataset`, `192.168.0.10:/mnt/ssd_pool/nfs_dataset/<pv name>`) is mounted read-only through a static PV.

| Volume | Kind | Copy |
|---|---|---|
| `web-workflows/web-workflows-db` | SQLite (`web-workflows.db`) | online backup, one file per night |
| `build-sim/build-sim-data` | SQLite (`build_sim.db`) | online backup, one file per night |
| `danwiki/danwiki-uploads` | files (empty on 2026-10-17) | mirror, like the buckets |

```
/backups/volumes/<name>/<db>-<stamp>.db         SQLite copies, integrity-checked, 28 days
/backups/volumes/<name>/current/                file mirror
/backups/volumes/<name>/replaced/<stamp>/       files overwritten or deleted (28 days)
/backups/volumes/.last-success
```

SQLite files are copied with SQLite's backup API, never as plain files: a file copied mid-write can be corrupt.
Restore one: scale the app to 0, copy `<db>-<stamp>.db` over the live file under its original name, scale back up.

The static PVs point at the app PVC's PV name. If an app's PVC is recreated, update the `subdir` in
`postgres/volume-backup.yaml` (the old directory is deleted with the old PVC, so the job fails and alerts until then).
`nfs-dataset` reclaims with `Delete`: deleting an app's PVC deletes its data on TrueNAS, and only this backup
remains.

Not backed up, by choice: scrape-stack caches (rebuildable), monitoring (Prometheus/Loki/Tempo history; dashboards
are provisioned from git), iggy (pipeline data), Redis, searxng.

## Tracks

`postgres/tracks-backup.yaml`, CronJob `postgres-backup-tracks`, 02:45 ET daily: the race-logger registry's
`robo_registry.public.tracks` (OSM-extracted and user-built course geometry) from postgres-dev, the only part of
the race-logger data kept for now (the rest is synthetic; user, 2026-10-17). TimescaleDB, iggy and the
`race-logger` bucket are deliberately not backed up until the system holds real data.

```
/backups/postgres-dev/robo_registry/tracks-<stamp>.dump   pg_dump -Fc -t public.tracks, 28 days
/backups/postgres-dev/robo_registry/tracks-<stamp>.json   the rows as a JSON array, 28 days
```

Restore into an existing registry: `pg_restore -h <host> -U postgres -d robo_registry --data-only
tracks-<stamp>.dump` (empty the table first, or restore into a scratch database and copy the rows you need). The
JSON copy survives schema changes: load it with `json_populate_recordset`. The extractor PoC's GeoJSON
(`robotics/robo-services/track-poly-poc/*.geojson`) is in git.

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
- Tower's nfsd on kernels below 6.12.16 / 6.6.79 / 6.1.129 can deadlock its NFSv4.1 callback
  workqueue after a backchannel fault (typically under `backup-objects` load). Every session
  setup/teardown then hangs and k8s mounts of the share wedge. Fixed by Unraid 7.x with kernel
  6.18.54 (2026-10-18), plus `fs.leases-enable=0` (no delegations) set in `/boot/config/go`
  (`docs/issues/2026_10_18_unraid_nfs_v41_client_wedge.md`)
- The restore test treats an unreadable share or database directory as a failure. Before
  2026-10-18 it skipped them silently and could report a partial test as `completed cleanly`

## When the backup share hangs

Symptoms: backup or restore jobs run into their deadline, pods sit in `ContainerCreating` with
`MountVolume.SetUp failed ... timeout after 110s`, and a worker shows a huge load average from D-state `mount.nfs`.

1. **Don't probe with new mounts from k8s nodes.** A new mount of a wedged server reuses its stuck client
   state and wedges that node too. Look first:
   ```bash
   ps -eo etime,args | grep '[0]\.15-manager'          # on a worker: NFSv4 state manager in D = wedged
   grep -A3 '^device 192.168.0.15' /proc/self/mountstats  # lease_expired > 0, xprt idle growing
   journalctl -k | grep 'nfs: server 192.168.0.15'       # flapping not responding / OK (group adm, no sudo)
   ```
2. **Check Tower** (as root):
   ```bash
   uname -r
   ps -eo pid,stat,etime,comm | awk '$2 ~ /^D/'           # nfsd / nfsd4_callbacks in D = server deadlock
   for p in $(ps -eo pid,stat | awk '$2 ~ /^D/{print $1}'); do echo "== $p $(cat /proc/$p/comm)"; cat /proc/$p/stack; done
   cat /proc/fs/nfsd/clients/*/info                       # per-client status, callback state
   ```
3. **nfsd threads in D → reboot Tower.** `rc.nfsd restart` can't clear threads stuck in D state. On
   2026-10-18 the workers' stuck clients recovered by themselves once Tower went down and came back,
   with no worker reboot needed.
4. **Only if a worker's state manager is still in D after Tower is healthy**, drain and reboot that worker.
   postgres-0 runs on k8s-worker2.
5. Rerun the failed jobs (`kubectl -n postgres create job --from=cronjob/<name> <name>-manual-$(date +%s)`).

Restarting the CSI `nfs` pods only helps with a stale CSI-level mount, not with a wedged kernel NFS client.


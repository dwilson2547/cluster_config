# Offsite backup (MEGA S4)

Two jobs copy to the same MEGA S4 bucket (`cluster-backup`), so a loss of the whole house still leaves a copy:

| Job | What | How | Prefix in the bucket |
|---|---|---|---|
| `offsite-backup` (Sunday 07:00 ET) | the Unraid backup share minus `objects/`: postgres dumps, volume copies, secrets exports (`docs/postgres_backup.md`, `docs/secrets_backup.md`) | restic snapshots | `cluster-backup/` |
| `offsite-objects` (nightly 04:30 ET) | the AIStor buckets, straight from AIStor, no NFS | rclone + crypt | `objects/` |

The buckets skip the share because walking part-images' ~6.9M files there stalls Tower's NFS for every client
(`docs/issues/2026_10_18_unraid_nfs_v41_client_wedge.md`, "Recurrence"). restic snapshots from before 2026-10-23
still contain `objects/`, including part-images, until `forget` ages them out (6 monthly). Syncthing separately
mirrors the share to other sites.

## What runs (restic)

CronJob `offsite-backup` (namespace `offsite-backup`, Sunday 07:00 ET), `restic` 0.17.3:

1. `restic backup /backups` (share mounted read-only). Skips `objects/`.
2. `restic forget --keep-weekly 4 --keep-monthly 6 --prune`.
3. First run of each month: `restic check --read-data-subset 5%` reads part of the stored data back.

restic encrypts with the repository password before upload, packs small files into larger pack files, and
uploads only new data. Snapshots, not a mirror: deleting something from the share
removes it from later snapshots only.

Secret `offsite-backup-restic` holds the repository URL, the password and the S4 key
(`example-secrets/offsite-backup/`). The password also lives in the user's password manager, next to the age key:
without it the repository cannot be read. Alerts (failed run, no success in 8 days, suspended) mail like the
postgres backup alerts.

## Buckets (rclone)

`offsite-backup/objects.yaml`, rclone 1.71.1 with a `crypt` remote over `s4:cluster-backup/objects` (contents and
names encrypted):

```
objects/current/<bucket>/...             mirror of the bucket
objects/replaced/<stamp>/<bucket>/...    what a full sync overwrote or deleted, kept 28 days
```

Nightly: copy objects modified in the last 26h (`--max-age 26h --no-traverse`). Wednesday: full `rclone sync` with
`--max-delete 500`, so a bucket deletion reaches the offsite copy on the next Wednesday. Force a full run with
`FULL_SYNC=1` on a manual Job. Unlike restic this is a mirror plus 28 days of undo, not snapshots. MEGA's object
limit is roughly 20 million (user 2026-10-22). part-images is ~6.9M.

S4 is slow per object: ~1.8s per PUT, and about 40 small uploads/s at most however wide rclone goes (128
transfers; 256 is no faster; measured 2026-10-23). The first full upload of part-images is therefore ~2 days.
Nightly runs carry only a day's new objects. A big backlog goes on a manual Job with `FULL_SYNC=1`,
`TRANSFERS=128` and a longer `activeDeadlineSeconds`. A rerun skips what is already uploaded. S4 doesn't implement
`GetBucketVersioning` (501). rclone logs that as an ERROR on `purge`/`delete` and carries on, so it's noise.

Secret `offsite-objects`: the read-only AIStor key, and the crypt password and salt (`rclone obscure`d). The S4 key
comes from `offsite-backup-restic`. Keep the crypt password and salt off-cluster next to the restic password: on
a machine with kubectl, `rclone reveal $(kubectl -n offsite-backup get secret offsite-objects -o
jsonpath='{.data.CRYPT_PASSWORD}' | base64 -d)` prints the plain value, and the same for `CRYPT_PASSWORD2`.
Alert `OffsiteBackupObjectsStale` fires after 2 days without success (failed runs share `OffsiteBackupJobFailed`).

Restore: configure the `s4` and `s4crypt` remotes as in the CronJob (with the plain password and salt) and copy back, e.g.
`rclone copy s4crypt:current/part-images dst:part-images`. `rclone cryptcheck aistor:<b> s4crypt:current/<b>`
compares the copy with the bucket without downloading it.

## Restore (restic)

From any machine with restic and the four values in the secret exported as environment variables
(`RESTIC_REPOSITORY`, `RESTIC_PASSWORD`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`):

```bash
restic snapshots                                   # pick a snapshot id, or use "latest"
restic ls latest /backups/secrets                  # browse
restic restore latest --target /restore --include /backups/secrets/20261017-050321.json.age
restic restore latest --target /restore --include /backups/<instance>   # one postgres instance's dumps
```

Then follow the restore steps in `docs/postgres_backup.md` or `docs/secrets_backup.md` on the restored files.
Downloads count against MEGA's transfer quota (3 TB per period on this account, user 2026-10-17); a full
part-images restore is ~135 GiB.

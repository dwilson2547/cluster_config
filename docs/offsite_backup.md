# Offsite backup (MEGA S4)

The Unraid backup share (`/mnt/user/cluster_backup`: postgres dumps, bucket copies, secrets exports;
`docs/postgres_backup.md`, `docs/secrets_backup.md`) is copied weekly to MEGA S4 object storage, so a loss of the
whole house still leaves a copy. Syncthing separately mirrors the share to other sites.

## What runs

CronJob `offsite-backup` (namespace `offsite-backup`, Sunday 07:00 ET), `restic` 0.17.3:

1. `restic backup /backups` (share mounted read-only). Skips `objects/*/replaced/` (local undo history).
2. `restic forget --keep-weekly 4 --keep-monthly 6 --prune`.
3. First run of each month: `restic check --read-data-subset 5%` reads part of the stored data back.

restic encrypts with the repository password before upload, packs small files (part-images is ~6.9M objects)
into larger pack files, and uploads only new data. Snapshots, not a mirror: deleting something from the share
removes it from later snapshots only.

Secret `offsite-backup-restic` holds the repository URL, the password and the S4 key
(`example-secrets/offsite-backup/`). The password also lives in the user's password manager, next to the age key:
without it the repository cannot be read. Alerts (failed run, no success in 8 days, suspended) mail like the
postgres backup alerts.

## Restore

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

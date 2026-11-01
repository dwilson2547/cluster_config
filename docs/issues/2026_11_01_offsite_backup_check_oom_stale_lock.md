# The monthly restic check was OOMKilled at 4Gi, and the lock it left made the Job's retry run `restic init` on the existing repository

**Date:** 2026-11-01  
**Component:** `offsite-backup/backup.yaml` (CronJob `offsite-backup`, `restic/restic:0.17.3`, repository on MEGA S4).
Alert `OffsiteBackupJobFailed` for Job `offsite-backup-29892240`.  
**Severity:** Medium. That run's snapshot was saved. But the next weekly run would have failed the same way until
someone cleared the lock, and every first-Sunday check would have been OOMKilled.

> Status: **fixed 2026-11-01** (cluster-config 25d8c4c, 10366ac). A manual run with the fix passed `restic check
> --read-data-subset 5%` ("no errors were found"), peaking at 4.88 GiB.

---

## Observed symptom

The alert's Job had failed twice (`backoffLimit: 1`). The newest pod's log was only:

```
== init repository
Fatal: create key in repository at s3:https://s3.ca-montreal-1.megas4.com/cluster-backup/cluster-backup failed: repository master key and config already initialized
```

## Root cause (verified)

1. **Attempt 1** (`offsite-backup-29892240-swpww`, 12:00Z). The backup succeeded (snapshot `7e53a2c1` saved), and
   forget and prune ran. It was the first Sunday of the month, so the script ran `restic check --read-data-subset
   5%`. That was OOMKilled at the container's 4Gi limit (exit 137, 12:08:11Z). Memory at the last 30 s sample before
   the kill was 3.16 GiB; the next successful check peaked at 4.88 GiB. This was the first check since the CronJob
   was created (2026-10-17), so 4Gi had never been tested against it.
2. The killed check left an **exclusive lock** in the repository (`create exclusive lock for repository` in its log).
3. **Attempt 2** (`-6z7m7`, 12:08:21Z). The script tested whether the repository exists with `restic cat config`,
   output discarded. `cat config` takes a lock, so it failed on attempt 1's exclusive lock. The script read any
   failure as "no repository" and ran `restic init`, which failed with "already initialized". `restic unlock`, which
   would have cleared the lock, came after that test.

Verified with a manual Job before the `--no-lock` fix. It stopped at the same test 2h21m later and, now that the
output was shown, printed:

```
unable to create lock in backend: repository is already locked exclusively by PID 79 on offsite-backup-29892240-swpww
lock was created at 2026-11-01 12:05:01 (2h21m9s ago)
```

A one-off pod running `restic unlock` with the Job's own spec then printed "successfully removed 1 locks". So restic
does treat a killed run's lock as stale; it was only the order of the steps in the script that stopped it being
cleared.

## Fix

- `limits.memory` 4Gi → 8Gi.
- The existence test is `restic cat config --no-lock`. Only exit code 10 ("repository does not exist", checked on
  0.17.3) runs `init`. Any other failure stops the script and shows restic's own error.

## Lessons

- A test hidden behind `>/dev/null 2>&1` turned a lock conflict into a misleading second error. Branch on a specific
  exit code, never on "any failure".
- The first triage (incident-operator #16) saw only the newest pod and blamed the script. incident-operator's Job
  evidence now lists every attempt and includes the first failed one (incident-operator 652d369).

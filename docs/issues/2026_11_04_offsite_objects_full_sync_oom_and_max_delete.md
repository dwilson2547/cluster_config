# The weekly offsite-objects full sync failed twice: rclone's on-disk sort re-read millions of objects, which looked changed, tripped --max-delete and ran out of memory

**Date:** 2026-11-04  
**Component:** `offsite-backup/objects.yaml` (CronJob `offsite-objects`, `rclone/rclone:1.71.1`, AIStor → MEGA S4
crypt). Alert `OffsiteBackupJobFailed` for Jobs `offsite-objects-29886270` (2026-10-28) and `offsite-objects-29896410`
(2026-11-04). Both were the Wednesday full sync (`FULL_SYNC_DOW=3`); the nightly incremental copies kept succeeding.  
**Severity:** Medium. New objects still went offsite every night, but no full sync had completed since the job was
created, so deletions and overwrites in the buckets never reached the offsite copy, and the alert fired every week.

> Status: **fixed 2026-11-04** (cluster-config 26d2a3e, 115e5f0, and the limit commit after them). Verified the same
> day with a manual full sync (`offsite-objects-full-20261104b`, `FULL_SYNC=1`) on the committed CronJob: all four
> buckets plus the `replaced/` prune in 18 minutes, 0 errors, memory peak 3.1 GiB. It re-uploaded two mazda objects
> that the failed 11-04 retry had moved to `replaced/` without re-uploading.

---

## Observed symptom

Each full sync failed on both attempts (`backoffLimit: 1`):

- Attempt 1 OOMKilled (exit 137) within ~3 minutes of starting `part-images`: at 2Gi on 10-28, at 4Gi on 11-04.
  Just before the 11-04 kill, eleven `Switching to on disk sorting as more than 200000 entries in one directory
  detected` notices landed in the same second.
- Attempt 2 on 11-04 ran 16 minutes and stopped with `Failed to sync with 20 errors: last error was: --max-delete
  threshold reached`. Its log was full of `sorter: failed to re-create object ...: HeadObject` and server-side moves
  of existing objects into `replaced/`.

## Previous fix (did not fix it)

491e067 (2026-10-29) raised the limit 2Gi → 4Gi and waited for the next Wednesday. It treated the OOM as a sizing
problem without finding why a sync used that much memory, and did not look at the `--max-delete` failure mode at all.

## Root cause (verified)

`part-images` keeps up to ~971k objects in one flat directory (`gm/images`: 970,874; `ford/images`: 585,476;
`toyota/images`: 518,614, counted from AIStor on 2026-11-04). With `--list-cutoff 200000`, every large directory went
to rclone's on-disk sort. That path stores entries on disk and **re-creates each object with a HEAD** when it reads
them back:

1. **Phantom changes.** AIStor's HEAD returns `Last-Modified` with whole seconds; the S4 copy stores the mtime from
   the listing, with milliseconds. Checked on one object: source via HEAD `2026-10-17T08:58:49.000Z`, S4 metadata
   `mtime 2026-10-17T08:58:49.939Z`. rclone saw them as different, so it moved the S4 object to `replaced/` and
   re-uploaded it. A dry run had 7,443 of these (and 0 real deletions) before it was stopped. Each move counts as a
   delete for `--max-delete`, so 500 trips early.
2. **S4 request storm.** The S4 side does the same: one HEAD per object, millions for `part-images`. During the dry
   run, MEGA reset TLS connections from our IP to `s3.ca-montreal-1.megas4.com` (from the cluster and the
   workstation; other MEGA endpoints answered). It recovered about 4 minutes after the traffic stopped.
3. **Memory.** Each listing is held in memory up to the cutoff, for source and destination, for up to `--checkers 16`
   directories at once, on top of the on-disk sorter.

Lowering the cutoff (tried first in this investigation) makes 1 and 2 worse: more directories go to the on-disk path.

## Fix

- `LIST_CUTOFF=1500000`: above the largest directory, so listings stay in memory and no object is re-read.
- `CHECKERS=4`: bounds how many directory listings are held at once.
- `--modify-window 1s` on both the nightly and full runs: absorbs any sub-second mtime difference.
- `--size-only` on the full sync. With in-memory listings, comparing mtimes still needed one S4 HEAD per object (S3
  listings carry no metadata): a first verification run managed ~120 checks/s with nothing to copy, ~16 hours for
  part-images, and the same per-object load MEGA blocks. The nightly copy already carries changed objects (by
  mtime); the full sync's job is missing objects and deletions, both decidable from listings.
- Memory request 4Gi, limit 8Gi (verification peak 3.1 GiB).

If a directory approaches 1.5M objects, raise `LIST_CUTOFF` and the memory limit together. Don't lower the cutoff.

## Lessons

- A memory bump with "see next week" is not a fix. Measure the run, and find why it uses what it uses.
- A run that dies in a retry with a different error (here `--max-delete`) is evidence, not noise.
- Verify with a real run the same day, not by waiting for the next schedule.

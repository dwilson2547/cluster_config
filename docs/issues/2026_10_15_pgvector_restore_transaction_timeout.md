# pg_restore v17 client fails against PG16 server on `SET transaction_timeout`

**Date:** 2026-10-15  
**Component:** `postgres/backup.yaml` — restore-test script / pgvector backup CronJob image  
**Severity:** High — restore tests for the pgvector instance (webdoc, wiki_db) failed while the dumps themselves were fine; a silent variant would mean untested backups for that instance.

---

## Observed symptom

The first manual run of the `postgres-restore-test` CronJob restored every database of the
`postgres` (v17) instance cleanly, then failed on both databases of the `postgres-pgvector`
instance (PostgreSQL 16) with:

```
pg_restore: error: could not execute query: ERROR:  unrecognized configuration parameter "transaction_timeout"
Command was: SET transaction_timeout = 0;
[postgres-pgvector] webdoc: FAILED restore from webdoc-20261016-022759.dump
```

The dumps had been created moments earlier by the same job's backup run, so this was not a
corrupt-archive problem.

---

## Root cause

### Backup tooling version did not match the server version

The backup CronJob used the `postgres:17` image for all instances, including
`postgres-pgvector`, which runs `pgvector/pgvector:pg16` (PostgreSQL 16). `pg_dump`/`pg_restore`
v17 emits `SET transaction_timeout = 0;` at restore time — `transaction_timeout` is a
PostgreSQL 17 GUC — and a v16 server rejects it as an unrecognized configuration parameter.
PostgreSQL client tools are designed to talk to *older or equal* servers for most operations,
but a v17 `pg_restore` replaying a v17-produced archive against a v16 server is not a
supported combination.

---

## Troubleshooting steps taken

1. **Read the restore-test job logs** — all 15 databases on the v17 instance (including the
   23GB `parts_interchange`) restored with nonzero table counts; only the pgvector instance's
   two databases failed, both with the same `transaction_timeout` error.
2. **Confirmed the dumps were valid** — the error came from a `SET` statement, not from archive
   data; the archive format itself was readable by the v17 `pg_restore` that produced it.
3. **Checked for leftover scratch databases** — the script's `dropdb --if-exists` cleanup ran
   even on failure, so no `_restore_test_*` databases were left behind on either instance.
4. **Verified instance versions** — `postgres` and `private`'s postgres run `postgres:17`;
   `postgres-pgvector` runs `pgvector/pgvector:pg16` (see `postgres/postgres.yaml`).

---

## Fix

### `postgres/backup.yaml` — one version-matched CronJob per instance

The single multi-instance backup/restore CronJobs were split into per-instance CronJobs with
matching client images: `postgres:17` for the v17 instances, `pgvector/pgvector:pg16` for the
pgvector instance. The scripts were made generic (driven by `INSTANCE_DIR`/`PGHOST` env), so
all six CronJobs share the same script text. With v16 tooling against the v16 server, both the
dump and the restore run in the supported same-version path.

---

## Files changed

- `postgres/backup.yaml` — per-instance CronJobs with version-matched images; generic `backup.sh` / `restore-test.sh` scripts

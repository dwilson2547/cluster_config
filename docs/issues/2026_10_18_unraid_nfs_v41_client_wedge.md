# Unraid's nfsd (kernel 6.1.82) deadlocks its NFSv4.1 callback workqueue after a backchannel fault, so session setup/teardown never completes and every k8s mount of the backup share wedges until reboot

**Date:** 2026-10-18  
**Component:** Unraid NFS server (Tower, 192.168.0.15, Unraid 6.12.9, kernel `6.1.82-Unraid`): `nfsd4_callbacks`
workqueue, `nfsd4_shutdown_callback`, `nfsd4_cb_sequence_done`. Linux NFSv4.1 client on k8s workers
(`6.8.0-111-generic`). Consumers: `postgres/backup.yaml`, `postgres/object-backup.yaml`, `secrets-backup/backup.yaml`,
`offsite-backup/backup.yaml`  
**Severity:** High. Backups and restore tests stop silently until the 6h job deadline, the wedge spreads to any node
that touches the share, and it needs reboots to clear. The live data is unaffected because primary storage is on
TrueNAS.

> Status: **root cause identified** (known upstream nfsd bugs, fixed in kernels Tower doesn't run).
> Fix: _TBD_, pending application on Tower and verification.

---

## Observed symptom

Alerts on 2026-10-18 (all times UTC; Tower logs in EDT, UTC−4):

- `PostgresBackupJobFailed` for `backup-objects-29871795`: `DeadlineExceeded` after 6h (`activeDeadlineSeconds: 21600`),
  container killed with exit 137. The previous good run took 4h19m.
- `PostgresBackupStale` for `backup-objects`: no success in more than 26h, from the same failure.
- `PostgresRestoreTestStale`: the CronJob was 2.5 days old and had never succeeded. The first Sunday run restored 8 DBs
  OK, then blocked indefinitely reading the next dump.
- Side effects: two `KubeContainerWaiting` alerts (`postgres-restore-test-pgvector`, `offsite-backup`, both stuck in
  `ContainerCreating` with `MountVolume.SetUp failed ... mount ... timeout after 110s`), and `NodeSystemSaturation`
  on k8s-worker2 (load ~330 with 160–190 tasks in D state, almost all `mount.nfs` retries from kubelet).

From Tower's own point of view the share looked healthy. `/mnt/user/cluster_backup` stayed mounted, and a v4.2
client on another machine kept reading and writing. Only session setup and teardown were blocked (see root cause).

### Timeline (2026-10-18, UTC)

| Time | Event | Source |
|---|---|---|
| 06:30–07:00 | Nightly pg dumps, volume and secrets backups complete normally | job status |
| 07:15:01 | `backup-objects` starts (rclone sync of 4 buckets, incl. `part-images` with millions of objects; `--transfers 4 --checkers 8`) | pod start time |
| 07:18:06 | First `nfs: server 192.168.0.15 not responding, still trying` | worker2 kernel journal |
| 07:18–09:24 | Server flaps under the write load: 147 `not responding` / 148 `OK` messages in 2h | worker2 kernel journal |
| ~07:21 | Tower's `kworker/u24:7+nfsd4_callbacks` is spawned. It's the one later found stuck (elapsed 07:58:15 at 15:19:10) | Tower `ps` |
| 07:30–09:10 | `kcompactd0` hung-task reports (blocked on a locked NFS page during migration), a side effect of the stalls | worker2 kernel journal |
| 09:00 | `postgres-restore-test` starts, restores 8 DBs | job log |
| 09:21:04 | Tower: `receive_cb_reply: Got unrecognized reply: calldir 0x1 ...` ×2. Worker2 logs `server OK` in the same second | Tower syslog (05:21:04 EDT) |
| 09:24:11 | Last NFS message on worker2. Its transport goes idle from this second (`xprt` idle 20465s at 15:05:16) | journal + mountstats |
| 09:30 | `postgres-restore-test-pgvector` can't mount the share | pod events |
| 10:40 | `offsite-backup` can't mount the share | pod events |
| 13:15 | `backup-objects` killed at its 6h deadline | job status |
| ~14:28 | A diagnostic mount from k8s-worker1 wedges worker1 the same way | worker1 ps, Tower client list |
| ~14:40 | `rc.nfsd restart` on Tower. No effect: the stuck nfsd threads survive it (elapsed 218 days afterwards) | Tower `ps` |
| 14:56 | `sysrq-w` blocked-task dump on worker2 | worker2 kernel journal |
| 15:19 | Stack traces of Tower's D-state nfsd threads and kworkers taken | Tower `/proc/<pid>/stack` |

A smaller stall burst happened on **2026-10-17 10:09–10:37**, also during a `backup-objects` run (07:15–11:34), and
recovered without intervention. Both stall episodes on record fall inside `backup-objects` runs.

---

## Root cause

### 1. Trigger: heavy write load stalls Tower, and clients' connections drop and reconnect

`backup-objects` pushes millions of small files through 12 concurrent rclone operations onto
`/mnt/user/cluster_backup`. That's an array share (`shareUseCache="no"`, data on `/mnt/disk4`, behind the `shfs`
FUSE layer, with parity). Tower's 8 nfsd threads can't keep up. Client RPCs exceed `timeo=600` (60s) and the clients
log `not responding`, then reconnect, roughly 150 times in 2h. Every one of those connection losses is a chance to
leave an NFSv4.1 **callback** (server→client RPC over the session backchannel, e.g. `CB_RECALL` for a delegation)
in flight on a dead connection. At 09:21:04 Tower logged `receive_cb_reply: Got unrecognized reply`: a callback
reply arrived for a request the server no longer tracked. The same message preceded the hangs in Debian bug
#1071562 (below).

### 2. Tower's nfsd deadlocks on its callback workqueue (known upstream bugs)

Stacks on Tower at 15:19 EDT (5 tasks in D state):

```
kworker/u24:7+nfsd4_callbacks          # the single-threaded callback workqueue, stuck
  rpc_shutdown_client
  nfsd4_process_cb_update              # tearing down the old callback client, waiting for its in-flight RPC
  nfsd4_run_cb_work

nfsd 26591                             # worker2's DESTROY_SESSION
  __flush_workqueue
  nfsd4_destroy_session
nfsd 26590                             # worker1's CREATE_SESSION
  __flush_workqueue
  nfsd4_create_session
nfsd 26589                             # worker1's EXCHANGE_ID, destroying its old client record
  __flush_workqueue
  nfsd4_shutdown_callback
  __destroy_client
  nfsd4_exchange_id
kworker/u24:3+nfsd4                    # laundromat reaping an expired client
  __flush_workqueue
  nfsd4_shutdown_callback
  __destroy_client
  nfs4_process_client_reaplist
  laundromat_main
```

The callback worker waits forever for a callback RPC that will never finish. Every operation that has to flush the
callback queue (session create/destroy, client destroy, the laundromat) waits behind it. Each one permanently
consumes one of the 8 nfsd threads. Ordinary I/O (`SEQUENCE`/`READ`/`WRITE`) doesn't flush the queue, which is
why an established client on another machine kept working and the share looked fine from Tower's side.

This is the bug class tracked in [Debian #1071562](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=1071562)
("NFSD threads hang when destroying a session or client ID"): same `nfsd4_destroy_session` /
`nfsd4_create_session` / `nfsd4_shutdown_callback → __flush_workqueue` stacks, same `receive_cb_reply` precursor,
on 6.1.x servers, reported mainly with **6.8 clients**, which is what the k8s workers run. Debian closed it as
fixed in 6.1.129 by two upstream fixes:

| Fix | Mechanism | Mainline | Stable backports |
|---|---|---|---|
| `961b4b5e86bf` NFSD: Reset cb_seq_status after NFS4ERR_DELAY | After a client answers `CB_SEQUENCE` with `NFS4ERR_DELAY` and the connection is then lost, the callback is retried forever with a stale status and never completes ([LP #2103564](https://bugs.launchpad.net/bugs/2103564): "nfsd hangs and never recovers after NFS4ERR_DELAY and a connection loss"; "There is no workaround") | 6.9-rc1 | 6.1.129, 6.6.76, 5.15.179 |
| CVE-2025-21795 NFSD: fix hang in nfsd4_shutdown_callback | nfsd sends a callback to a client in **courtesy** state, so `cl_cb_inflight` never drops to 0 and `nfsd4_shutdown_callback` hangs | 6.14-rc3 (`036ac2778f7b`) | 6.1.129, 6.6.79, 6.12.16, 6.13.4 |

Tower runs **6.1.82**, which predates both. Its client table during the incident showed a `courtesy` client for
worker1 next to an `unconfirmed` one, which is the state the second fix addresses. The fix versions are as stated
by the Debian/Launchpad trackers and the CVE announcement; ⚠ unverified against Unraid's kernel patch set.

The Unraid forum thread ["NFS shares stop working beyond 6.12.9"](https://forums.unraid.net/topic/174163-nfs-shares-stop-working-beyond-6129/)
describes the same silent "NFS stops responding, nothing in the logs, reboot fixes it" pattern on Unraid 6.12.11–6.12.13
(kernel 6.1.106, also below 6.1.129) and 7.0 beta 3. No root cause was identified there.

### 3. The client's state manager waits forever on that server (hard mount)

worker2's NFSv4 state manager kthread (`[192.168.0.15-manager]`), full stack via `/proc/<pid>/stack`:

```
rpc_wait_bit_killable
__rpc_execute
rpc_call_sync
nfs4_proc_destroy_session      # waiting on Tower nfsd 26591, which never replies
nfs4_reset_session
nfs4_state_manager
nfs4_run_state_manager
```

The client is resetting its session (after the backchannel fault) and sends `DESTROY_SESSION`. On a `hard` mount it
never gives up. All work on that server queues behind the state manager:

- In-flight I/O: the restore test's `bash` and an `ls` are in `nfs4_proc_getattr → rpc_wait_bit_killable`.
- The CSI node plugin: 87 `nfsplugin` threads are in `newfstatat → nfs_getattr → nfs4_proc_getattr`.
- New mounts: 137 `mount.nfs` are in `nfs4_get_rootfh → nfs41_find_root_sec → _nfs41_proc_secinfo_no_name`. A new mount
  of the same server reuses the existing (wedged) per-server `nfs_client`, so new mounts hang too.

The client's lease expired at about 09:21 (`lease_expired=19443` in `/proc/self/mountstats` at 14:45) and its
transport has been idle since 09:24:11. TrueNAS mounts on the same node with identical options (`hard,nfsvers=4.1`)
were unaffected throughout (`lease_expired=0`). This is a per-server state wedge, not a client config, CNI or node
networking problem.

### 4. Why the usual recoveries don't work

- **`rc.nfsd restart` on Tower**: the stuck nfsd threads are in D state and can't exit, so `rpc.nfsd 8` finds 8
  threads already running and changes nothing. After the restart the same threads were still there, 218 days old.
  Clearing them needs a **Tower reboot**.
- **Restarting the CSI `nfs` pods**: that fixes a stale CSI-level mount, not a wedged kernel `nfs_client`. This is
  why it "sometimes" helped in past incidents (the other failure mode, not this one).
- **More nfsd threads alone**: once the callback queue is stuck, each session setup or teardown takes one more
  thread forever, so more threads only delay starvation. They do help with the trigger (factor 1) by reducing
  load-induced timeouts.

---

## Troubleshooting steps taken

1. **Checked the backup CronJobs and jobs**: all nightly dumps succeeded (06:30–07:00). `backup-objects` failed on
   its deadline. The restore test was `Running` but stuck for 5h, with no `_restore_test_*` session in `pg_stat_activity`.
   This ruled out postgres and pointed at storage.
2. **Described the stuck pods**: `FailedMount ... timeout after 110s` for the Unraid PVs, all on k8s-worker2.
3. **`ls /backups` inside the running restore-test pod**: hung. The share was unreadable from an existing mount.
4. **Probed Tower from the network**: ping OK, TCP 2049 open, `rpcinfo -t ... nfs 3/4` "ready and waiting", web UI
   200 in 20ms. Ruled out a dead host and the network path. NULL RPCs don't need the callback queue, so they still work.
5. **Mounted from k8s-worker1 with a throwaway pod**: `FailedMount`, and it wedged worker1's client too (its
   `EXCHANGE_ID`/`CREATE_SESSION` took two more Tower threads). **Lesson: never probe a degraded Unraid export from a
   k8s node.** Probe from a box you can afford to reboot, with `-o soft,timeo=50`.
6. **Compared `/proc/self/mountstats` for Unraid vs TrueNAS mounts on worker2**: only the Unraid mount has an
   expired lease and an idle transport. Ruled out the client config, the CNI and node networking.
7. **Read Tower syslog and `/proc/fs/nfsd/clients`**: the `receive_cb_reply` error at 05:21:04 EDT, worker2's client
   `confirmed` but not renewed, worker1's `unconfirmed` + `courtesy`, `callback state: UNKNOWN` for every client.
8. **Restarted nfsd on Tower**: no change. The stuck threads survived it.
9. **Read the persistent kernel journal on worker2** (`journalctl -k`, readable via group `adm`; `dmesg` had wrapped):
   the 2h stall window that starts 3 minutes after `backup-objects`, the `kcompactd0` hung tasks, the 10-17
   precursor, and a full `sysrq-w` dump.
10. **Took the state manager's full stack on worker2**: `nfs4_reset_session → nfs4_proc_destroy_session`.
11. **Took stacks of Tower's D-state tasks**: callback worker in `rpc_shutdown_client`, three nfsd threads and the
    laundromat in `__flush_workqueue`. Matching the stacks to worker2's `DESTROY_SESSION` and worker1's
    `EXCHANGE_ID`/`CREATE_SESSION` closed the loop between client and server.
12. **Matched against upstream**: Debian #1071562 and Launchpad #2103564 → fixes `961b4b5e86bf` and CVE-2025-21795,
    both missing from 6.1.82.

---

## Fix

_TBD_, pending application. The plan is below.

### Tower kernel: run a kernel with both fixes (the actual fix)

Upgrade Unraid to a release whose kernel is **≥ 6.12.16** (6.12 line) or **≥ 6.6.79** (6.6 line). From Unraid's
release notes: 7.0.1 ships 6.6.78, **one stable release short** of the shutdown-callback fix, so it isn't enough.
7.1.0–7.1.4 ship 6.12.24, which contains both. After the upgrade, confirm with `uname -r`.

### Tower: disable delegations (defence in depth, applies immediately)

Both bugs need a callback RPC in flight. On NFSv4.1 those are mostly `CB_RECALL`/`CB_RECALL_ANY` for delegations,
and nfsd only grants delegations when kernel file leases are enabled. With `fs.leases-enable=0`, Tower stops handing
them out. This reasoning comes from how nfsd works, ⚠ unverified by test: confirm that no client holds delegations
afterwards. A backup target gains nothing from delegations.

### `postgres/object-backup.yaml`: reduce the trigger load

_TBD_ after the kernel fix lands. Consider lowering `--transfers`/`--checkers` or adding `--tpslimit`, and raising
Tower's nfsd thread count, so the share stops timing out clients during the nightly sync.

### Recovery from a wedge (runbook)

1. Don't probe with new mounts from k8s nodes. Each one wedges that node too.
2. On Tower, check `ps -eo pid,stat,etime,comm | awk '$2 ~ /^D/'`. nfsd threads or an `nfsd4_callbacks` kworker in
   D means this bug. **Reboot Tower.** `rc.nfsd restart` can't clear D-state threads.
3. Then check each worker for `[192.168.0.15-manager]` in D. If it's still stuck after Tower is back, drain and
   reboot that worker.

---

## Files changed

_TBD_

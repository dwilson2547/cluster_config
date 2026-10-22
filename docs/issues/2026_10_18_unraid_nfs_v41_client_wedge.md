# Unraid's nfsd (kernel 6.1.82) deadlocks its NFSv4.1 callback workqueue after a backchannel fault, so session setup/teardown never completes and every k8s mount of the backup share wedges until reboot

**Date:** 2026-10-18  
**Component:** Unraid NFS server (Tower, 192.168.0.15, Unraid 6.12.9, kernel `6.1.82-Unraid`): `nfsd4_callbacks`
workqueue, `nfsd4_shutdown_callback`, `nfsd4_cb_sequence_done`. Linux NFSv4.1 client on k8s workers
(`6.8.0-111-generic`). Consumers: `postgres/backup.yaml`, `postgres/object-backup.yaml`, `secrets-backup/backup.yaml`,
`offsite-backup/backup.yaml`  
**Severity:** High. Backups and restore tests stop silently until the 6h job deadline, the wedge spreads to any node
that touches the share, and it needs reboots to clear. The live data is unaffected because primary storage is on
TrueNAS.

> Status: **fixed 2026-10-18.** Tower was upgraded to Unraid 7.x (kernel `6.18.54-Unraid`, which contains both
> upstream fixes) and delegations were disabled (`fs.leases-enable=0`). Every client recovered without a reboot. The fix is
> considered verified once `backup-objects` runs under full load without a wedge (see "Verification").

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
| ~15:40 | `fs.leases-enable=0` added to `/boot/config/go`; Unraid upgrade started | user |
| 15:43:19 | Tower drops off the network for the reboot. worker1's stuck state manager clears; worker2's exits and restarts against the down server | watcher, worker ps |
| 15:43–16:37 | Tower hangs right after the boot splash, before the OS loads. Fixed with a **motherboard BIOS update**: the new kernel wouldn't boot on the 2024 BIOS | user |
| 16:37 | Tower NFS back. worker2's queued I/O completes (D-state tasks 259 → 0, no worker reboot); the stuck restore test errors out and ends | worker ps, pod logs |
| 16:55 | Exports up, all pending pods mounted, `uname -r` = `6.18.54-Unraid`, `fs.leases-enable = 0` | showmount, Tower |

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
by the Debian/Launchpad trackers and the CVE announcement. Tower now runs mainline-based `6.18.54-Unraid`, newer
than every fix version listed (both fixes are in mainline from 6.9 and 6.14).

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
- **Rebooting Tower** does clear it. Once the server restarts, the clients' stuck calls error out and their state
  managers recover by themselves. On 2026-10-18 neither worker needed a reboot.
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

### Tower kernel: Unraid 7.x on kernel 6.18.54 (the actual fix)

Upgraded from Unraid 6.12.9 (kernel 6.1.82) to a 7.x release on kernel `6.18.54-Unraid`. That contains both
`961b4b5e86bf` (mainline 6.9) and the CVE-2025-21795 fix (mainline 6.14). Unraid 7.0.1 (6.6.78) would **not**
have been enough: it's one stable release short of the shutdown-callback fix (6.6.79).

**Upgrade gotcha:** after the upgrade Tower hung right after the motherboard's boot splash, before the OS loaded
(no network, screen black, the power button cut it off instantly). The new kernel wouldn't boot with the board's 2024
BIOS. **A BIOS update fixed it.** Before a future Unraid major upgrade, update the BIOS first, or keep a monitor and
keyboard handy.

### Tower: delegations disabled (defence in depth)

`sysctl -w fs.leases-enable=0` in `/boot/config/go`, so it applies before nfsd starts on every boot. Both bugs need
a callback RPC in flight, and on NFSv4.1 those are mostly delegation recalls, which nfsd grants only while kernel
leases are enabled. Effect on other services: Samba runs with `kernel oplocks = no` (checked with `testparm`), so
SMB oplocks and SMB2 leases are handled by smbd itself and aren't affected. NFS clients lose delegation caching,
which a backup target doesn't need.

### `postgres/backup.yaml`: restore test fails on unreadable or empty backup directories

When Tower went away mid-run, the stuck `stat` on the next database directory returned `Permission denied`. The old
`[ -d "$dbdir" ] || continue` guard then skipped that directory and every one after it, and the job reported `restore
test completed cleanly`. That would have cleared `PostgresRestoreTestStale` on a partial test. Now an unreadable
instance or database directory, a database directory without dumps, or a run that tests zero databases each count
as a failure, and the success line states how many databases were tested.

### Not changed (deliberately)

- **Client mounts stay `hard,nfsvers=4.1`.** `soft` would turn a server deadlock into lost writes on the backup
  share, and 4.2 uses the same session and callback machinery.
- **nfsd thread count** is still Unraid's default of 8. More threads would only delay starvation in the deadlock. Revisit
  only if `backup-objects` still produces `not responding` flapping on the new kernel.
- **`backup-objects` concurrency** is unchanged until a run on the fixed kernel shows whether the load still stalls Tower.

### Verification

- [x] `uname -r` on Tower = `6.18.54-Unraid`; `fs.leases-enable = 0` after reboot
- [ ] ~~Both workers recovered with no reboot~~ **Wrong for k8s-worker1** (found 2026-10-22, see "Recurrence" below). worker2 recovered; worker1's state manager cleared, but its two `mount.nfs` from the 14:28 diagnostic mount stayed in D
- [x] `postgres-restore-test-pgvector` passed with the new script (2 databases tested)
- [ ] Manual `postgres-restore-test` run passes with the new script
- [ ] `backup-objects` completes on the fixed kernel without `not responding` flapping (`journalctl -k | grep 'nfs: server 192.168.0.15'` on the worker it ran on)
- [ ] No client holds delegations: `grep -c deleg /proc/fs/nfsd/clients/*/states` on Tower

### Recurrence 2026-10-22: k8s-worker1 never recovered

`postgres-backup-29877510` and `postgres-backup-pgvector-29877520` both hit `DeadlineExceeded` after 6h. Both pods
were scheduled on k8s-worker1, and both were the first Unraid-mounting pods on worker1 since 10-18. Every backup pod
between 10-18 and 10-22 ran on worker2 or k8s-main and succeeded (`kube_pod_info`). The same night,
`postgres-backup-tracks` on worker2 used the same PVC and succeeded.

On worker1 the two `mount.nfs` started at 2026-10-18 14:28:11 and 14:30:02 UTC were still in D. From
06:30:00 UTC on 10-22, kubelet added a new `mount.nfs` roughly every 2 minutes (102 in D, load ~104). There was no
`[192.168.0.15-manager]` thread, so the "state manager in D" check in the runbook missed it. The node's
`nfs_client` for Tower stayed wedged from the diagnostic mount on. It was silent because nothing mounted the share
there. Today's dumps were rerun with an anti-affinity to worker1 and completed cleanly on worker2. Tower itself was
not the cause this time.

Fix for worker1: deleting its `csi-nfs-node` pod killed all 102 stuck `mount.nfs`. They wait in a killable
state, so no reboot was needed. A throwaway pod on worker1 then mounted the share and read `.last-success` in
seconds. Runbook step 4 now checks for any D-state NFS task that started before Tower's reboot.

#### The load trigger: a nightly full walk of part-images

worker2 logged `not responding` / `OK` flapping again from 07:18 UTC, 3 minutes into `backup-objects` (~200 messages
07:10–09:30). There has been flapping on every night since 10-17. Tower's node-exporter for the same window:

| Metric (07:20–08:20 UTC) | Value |
|---|---|
| `sdh` (ST8000VN004, array disk) busy | 100% |
| `sdh` reads | 305–346/s, ~4.4 MB/s (~14 KB each), 24–33 ms avg |
| writes on any disk | none above 1/s |
| nfsd RPCs served | 0.06–10/s (vs ~2,000/s once the disk freed up) |
| Tower iowait / dirty memory | ~0 / <1 MB |

The run transferred 0 bytes. `part-images` (6,867,545 objects, 145 GB) is unchanged night to night, so the run was
pure metadata: `rclone sync` stats every object in `current/`, and the old `rclone size` of `current/` walked all
6.9M again. That is random small reads on one 7200 rpm disk through `shfs`. The disk tops out around 330 IOPS, and
every other client's NFS request queues behind the walk past the 60s `timeo`. More nfsd threads (64 per
`node_nfsd_server_threads`) don't help: they deepen the queue on the same spindle. Which `/mnt/diskN` `sdh` is
⚠ unverified (Unraid's md devices report no I/O); this doc's earlier "data on `/mnt/disk4`" fits.

Fix (`postgres/object-backup.yaml`): nightly runs copy only objects modified in the last 26h with
`--no-traverse` (no walk of `current/`). A full `sync` runs Wednesdays with 2 checkers, away from Sunday's restore
tests. The size line is read from the bucket, not the share, and only on the full run.

Verified 2026-10-22 with a manual nightly-mode run (13:31–15:09 UTC; the copy took 13 min, the bucket size listing
the rest, since dropped from nightly runs): 0 `nfs: server 192.168.0.15` messages on either worker, and no Tower
disk above 1% busy (`max_over_time` of `node_disk_io_time_seconds_total` rate).

### Recovery runbook

Kept in `docs/postgres_backup.md` → "When the backup share hangs".

---

## Files changed

- `postgres/backup.yaml` — `restore-test.sh` (unreadable/empty dirs fail the test, tested-count reporting)
- `docs/postgres_backup.md` — gotchas, "When the backup share hangs" runbook
- Tower (not in git): Unraid 6.12.9 → 7.x (kernel 6.18.54), motherboard BIOS update, `fs.leases-enable=0` in `/boot/config/go`

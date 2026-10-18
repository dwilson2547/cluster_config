# Unraid NFS stalls under backup-objects load leave the NFSv4.1 client state manager hung on k8s workers, wedging every mount of the backup share until reboot

**Date:** 2026-10-18  
**Component:** Unraid NFS server (Tower, 192.168.0.15, `/mnt/user/cluster_backup`, kernel `6.1.82-Unraid`) ↔
Linux NFSv4.1 client on k8s workers (`6.8.0-111-generic`); consumers `postgres/backup.yaml`,
`postgres/object-backup.yaml`, `secrets-backup/backup.yaml`, `offsite-backup/backup.yaml`  
**Severity:** High — backups and restore tests stop silently until the 6h deadline, the wedge spreads to any node
that touches the share, and it needs a node reboot to clear. The live data is unaffected because primary storage is
on TrueNAS.

> Status: **investigation in progress.** The client side is fully evidenced. The server side (why Tower's nfsd
> threads blocked) is waiting on Tower stack traces. Sections marked _TBD_ are filled in when that lands.

---

## Observed symptom

Alerts on 2026-10-18 (all times UTC; Tower logs in ET, UTC−4):

- `PostgresBackupJobFailed` for `backup-objects-29871795`: `DeadlineExceeded` after 6h (`activeDeadlineSeconds: 21600`),
  container killed with exit 137. The previous good run took 4h19m.
- `PostgresBackupStale` for `backup-objects`: no success in more than 26h, from the same failure.
- `PostgresRestoreTestStale`: the CronJob was 2.5 days old and had never succeeded. The first Sunday run restored 8 DBs
  OK, then blocked indefinitely reading the next dump.
- Side effects: two `KubeContainerWaiting` alerts (`postgres-restore-test-pgvector`, `offsite-backup`, both stuck in
  `ContainerCreating` with `MountVolume.SetUp failed ... mount ... timeout after 110s`), and `NodeSystemSaturation`
  on k8s-worker2 (load ~330 with 160–190 tasks in D state, almost all `mount.nfs` retries from kubelet).

Signature of the wedge on a client node:

```
$ ps -eo stat,etime,args | grep '[0]\.15-manager'
D   05:44:12 [192.168.0.15-manager]                 # NFSv4 state manager kthread, stuck

$ grep -A3 '^device 192.168.0.15' /proc/self/mountstats
nfsv4: ... sessions, lease_time=90, lease_expired=20562   # lease expired, never renewed
xprt:  tcp 0 0 2 0 20465 ...                             # transport idle 20465s: client sends nothing
```

TrueNAS mounts on the same node, with identical options (`hard,nfsvers=4.1`), stayed healthy throughout:
`lease_expired=0`, one session, no recovery.

### Timeline (2026-10-18, UTC)

| Time | Event | Source |
|---|---|---|
| 06:30–07:00 | Nightly pg dumps, volume and secrets backups complete normally | job status |
| 07:15:01 | `backup-objects` starts (rclone sync, 4 buckets incl. `part-images` with millions of objects; `--transfers 4 --checkers 8`) | pod start time |
| 07:18:06 | First `nfs: server 192.168.0.15 not responding, still trying` | worker2 kernel journal |
| 07:18–09:24 | Server flaps: 147 `not responding` / 148 `OK` messages in 2h | worker2 kernel journal |
| 07:30–09:10 | `kcompactd0` hung-task reports (blocked on a locked NFS page during migration); further reports suppressed | worker2 kernel journal |
| 09:00 | `postgres-restore-test` starts, restores 8 DBs | job log |
| 09:21:04 | Tower: `receive_cb_reply: Got unrecognized reply: calldir 0x1 ...` ×2. Worker2 logs `server OK` in the same second | Tower syslog (05:21:04 ET) |
| 09:24:11 | Last NFS message on worker2. Its transport goes idle from this second (`xprt` idle 20465s at 15:05:16) | journal + mountstats |
| 09:30 | `postgres-restore-test-pgvector` can't mount the share | pod events |
| 10:40 | `offsite-backup` can't mount the share | pod events |
| 13:15 | `backup-objects` killed at its 6h deadline | job status |
| ~14:28 | A diagnostic mount from k8s-worker1 wedges worker1 the same way (its state manager has been stuck ever since) | worker1 ps |
| ~14:40 | `rc.nfsd restart` on Tower. No effect on either client | worker ps / mountstats |
| 14:56 | `sysrq-w` blocked-task dump on worker2 | worker2 kernel journal |

A smaller stall burst happened on **2026-10-17 10:09–10:37**, also during a `backup-objects` run (07:15–11:34), and that
one recovered without intervention. Both stall episodes on record fall inside `backup-objects` runs.

---

## Root cause

### 1. Tower's nfsd stalls under the object-backup write load

The stalls start 3 minutes after `backup-objects` begins and stop being reported only when the client wedges. The
rclone sync of `part-images` (millions of small objects, 12 concurrent operations) produces a sustained metadata and
small-write storm against `/mnt/user/cluster_backup`. `/mnt/user` is Unraid's `shfs` FUSE union layer.

At the time of the dump, Tower had **3 of its 8 `nfsd` threads in D state** plus a
`kworker/u24:7+nfsd4_callbacks` in D (`ps` on Tower). With only 8 threads (`rpc.nfsd ... 8`, the Unraid default),
blocked threads leave too little capacity, and clients see `not responding` whenever the remaining threads are
busy longer than `timeo=600` (60s).

_TBD:_ what the D-state nfsd threads were blocked in (shfs/FUSE, the underlying filesystem, or the NFSv4 callback
path). This decides whether the fix is thread count, bypassing shfs, or delegations.

### 2. A callback (backchannel) reply arrives after Tower gave up on it

NFSv4.1 delegations let the client cache a file. The server recalls them with `CB_RECALL` over the session
backchannel. At 09:21:04 Tower logged `receive_cb_reply: Got unrecognized reply`, meaning the client answered a
callback the server no longer had outstanding. Tower's callback state for both workers' clients shows
`callback state: UNKNOWN`. The `nfsd4_callbacks` worker on Tower was itself blocked in D.

### 3. The client's state manager blocks forever in a synchronous RPC (hard mount)

After 09:24 the client's per-server state manager (`[192.168.0.15-manager]`) sits in:

```
rpc_call_sync+0x53/0xb0 [sunrpc]
nfs4_state_manager+0x405/0xa10 [nfsv4]
nfs4_run_state_manager+0x92/0x180 [nfsv4]
kthread
```

(Partial stack: the journal interleaved the sysrq dump. _TBD:_ full `/proc/<pid>/stack`.)

The RPC it waits on never completes, and on a `hard` mount it is never abandoned. Every other operation on that
server queues behind the state manager:

- In-flight I/O: the restore test's `bash` and an `ls` sit in `nfs4_proc_getattr → rpc_wait_bit_killable`.
- The CSI node plugin: `nfsplugin` threads sit in `newfstatat → nfs_getattr → nfs4_proc_getattr` (87 threads).
- New mounts: `mount.nfs` sits in `nfs4_get_rootfh → nfs41_find_root_sec → _nfs41_proc_secinfo_no_name`, because
  a new mount of the same server reuses the existing (wedged) `nfs_client` (137 tasks in the dump).

The transport has been idle since 09:24:11, so the client is not even retrying on the wire. That's why restarting
nfsd on Tower changed nothing: the server can't unblock a client that isn't talking to it. It's also why
restarting the CSI `nfs` pods only "sometimes" helped in past incidents: that fixes a stale CSI mount, not a
wedged kernel `nfs_client`.

### 4. New clients can't establish a session either

Tower's `/proc/fs/nfsd/clients` showed worker1's client as `unconfirmed` plus a `courtesy` entry with
`callback address: (einval)`. worker1's `EXCHANGE_ID` was accepted but its session was never confirmed, and its
state manager wedged in turn. So during the incident the server side was also unable to bring up a fresh v4.1
session. That's consistent with blocked nfsd threads (factor 1). _TBD:_ confirm with Tower stacks.

---

## Troubleshooting steps taken

1. **Checked the backup CronJobs and jobs**: all nightly dumps succeeded (06:30–07:00). `backup-objects` failed on
   its deadline. The restore test was `Running` but stuck for 5h, with no `_restore_test_*` session in `pg_stat_activity`.
   This ruled out postgres and pointed at storage.
2. **Described the stuck pods**: `FailedMount ... timeout after 110s` for both Unraid PVs, all on k8s-worker2.
3. **`ls /backups` inside the running restore-test pod**: hung. The share was unreadable from an existing mount.
4. **Probed Tower from the network**: ping OK, TCP 2049 open, `rpcinfo -t ... nfs 3/4` "ready and waiting", web UI
   200 in 20ms. Ruled out a dead host and the network path.
5. **Mounted from k8s-worker1 with a throwaway pod**: `FailedMount` as well, and it wedged worker1's client. This
   ruled out a worker2-only problem. **Lesson: don't probe a degraded Unraid export from a k8s node.** Probe from
   a box you can afford to reboot, with `-o soft,timeo=50`.
6. **Compared `/proc/self/mountstats` for Unraid vs TrueNAS mounts on worker2**: only the Unraid mount shows an
   expired lease and an idle transport. This pinned the fault to the Unraid NFSv4 client state, not to the
   client config, CNI or node networking (MicroK8s 1.33's networking has been stable).
7. **Read Tower syslog and `/proc/fs/nfsd/clients`**: the backchannel error at 05:21:04 ET, 3/8 nfsd threads plus
   the callbacks worker in D, worker1's client unconfirmed. The server side was degraded too.
8. **Restarted nfsd on Tower**: no change on either client. Confirmed the client-side wedge is self-sustaining.
9. **Read the persistent kernel journal on worker2** (`journalctl -k`, readable via group `adm`; `dmesg` had wrapped):
   found the 2h stall/flap window that starts 3 minutes after `backup-objects`, the `kcompactd0` hung tasks, the
   10-17 precursor episode, and the full `sysrq-w` dump with the blocked stacks above.

---

## Fix

_TBD_: pending the server-side stacks. The candidate changes are listed below, and each gets measured before it's
adopted:

- **Tower nfsd thread count** (8 → more). Helps if threads are merely saturated, but not if they block indefinitely.
- **Bypass `shfs`** by exporting the backup share's pool path instead of `/mnt/user`. Applies if the nfsd stacks show FUSE.
- **Disable delegations on Tower** (`fs.leases-enable=0`), which removes the callback path in factors 2 and 3.
- **Throttle `backup-objects`** (`--transfers`/`--checkers`, `--tpslimit`), which reduces the trigger load.

Recovery from a wedge (applies regardless): the stuck `nfs_client` can't be released while tasks hold it on a
`hard` mount, so **drain and reboot the affected worker(s).** Restarting nfsd on Tower or restarting the CSI pods
does not clear it.

---

## Files changed

_TBD_

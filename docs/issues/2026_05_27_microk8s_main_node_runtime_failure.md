# microk8s containerd silently breaks on k8s-main, leaving node Ready but unable to start any pods

**Date:** 2026-05-27  
**Component:** k8s-main (`192.168.0.35`) — microk8s snap services: `snap.microk8s.daemon-containerd`, `snap.microk8s.daemon-kubelet`, Calico CNI, NFS CSI driver (`csi-nfs-node-87zr7`)  
**Severity:** Critical — node appears healthy to the control plane but silently drops all new workloads; recurring issue with no automated detection or recovery

---

## Observed symptom

Pods scheduled to k8s-main become permanently stuck in `ContainerCreating` with no events and `PodReadyToStartContainers: False`. The node reports `Ready=True` in `kubectl get nodes` with all conditions normal. The failure is completely silent — no warnings, no error events, no alerts. Worker nodes (k8s-worker1, k8s-worker2) are unaffected.

The stuck-pod fingerprint (confirmed in this session):

```
NAME           READY   STATUS              RESTARTS   AGE
some-pod       0/1     ContainerCreating   0          9m+
```

```
Conditions:
  PodScheduled:           True
  Initialized:            True
  PodReadyToStartContainers: False   ← key indicator
  Ready:                  False

Events: <none>                        ← key indicator (not slow pull — truly broken)
```

Secondary symptom that precedes or co-occurs: pods with NFS volume mounts (nfs-dataset storage class) hang in `Terminating` for 30+ minutes after deletion, with the NFS volume failing to unmount from the node.

---

## Root cause

### containerd loses the ability to create pod sandboxes

The kubelet and containerd are separate processes in microk8s. The kubelet can post healthy heartbeats to the API server (keeping the node `Ready`) while containerd is internally broken. When a pod is scheduled, the kubelet calls containerd to create the pod sandbox — a network namespace plus a pause container. If containerd cannot complete sandbox creation, the kubelet never progresses to the "Pulling image" stage, which is why Events are completely absent.

The `PodReadyToStartContainers: False` condition with zero events is the diagnostic signature of this state. A pod with a slow Docker Hub pull will show `Normal Pulling` events; a pod on a broken containerd shows nothing at all.

Even a trivially simple pod (busybox, no volumes, no secrets) fails to start in this state, which rules out NFS/CSI or secret-mounting as the primary cause — the failure is at the container runtime sandbox layer, before any workload-specific resources are touched.

### Why the node looks healthy

`kubectl describe node k8s-main` reported all conditions green during the failure:

```
NetworkUnavailable   False   (Calico is running)
MemoryPressure       False   (kubelet has sufficient memory)
DiskPressure         False   (kubelet has no disk pressure)
PIDPressure          False   (kubelet has sufficient PID)
Ready                True    (kubelet is posting ready status)
```

These conditions are all reported by the **kubelet**, not by containerd. The kubelet is alive and healthy. containerd is a separate daemon (`snap.microk8s.daemon-containerd`) that the kubelet calls via a Unix socket at `/var/snap/microk8s/common/run/containerd.sock`. A broken containerd does not invalidate any of the kubelet's node conditions.

### Likely internal causes within microk8s (most probable first)

**1. Stale CNI network namespace state from force-deleted pods**

This session's trigger: a ReplicaSet was deleted while pods had active NFS mounts, causing pods to hang in Terminating for 29+ minutes. These pods were then force-deleted (`--force --grace-period=0`). Force-deleting pods with active network namespaces can leave orphaned CNI state — Calico may have IP allocations, route entries, and veth pairs referencing namespaces that no longer exist in the kernel in a clean state. When containerd next attempts to create a new pod sandbox, it calls the Calico CNI binary with a network namespace path, and the CNI binary may deadlock or error trying to reconcile against the stale state.

microk8s bundles the CNI binary at `/var/snap/microk8s/current/opt/cni/bin/calico`. This binary is called synchronously by containerd during sandbox creation. A hung CNI call blocks the containerd goroutine responsible for that sandbox indefinitely.

**2. containerd internal state accumulation**

containerd persists sandbox and container state under `/var/snap/microk8s/common/var/lib/containerd/`. After a series of force-deletes, unexpected terminations, or rapid pod churn, this state can diverge from kernel reality — containerd may believe sandboxes exist that the kernel has already cleaned up, or vice versa. This can cause containerd's sandbox management goroutines to deadlock waiting for state transitions that will never come.

**3. NFS stale kernel mounts cascading to containerd bind mounts**

When an NFS volume hangs unmounting (due to NFS server disconnect or kernel NFS client state), the kernel mount table can accumulate stale entries under `/var/snap/microk8s/common/var/lib/kubelet/pods/`. containerd performs bind mounts when setting up volume mounts for containers. If any of these paths are on or near a stale NFS mount point, the bind mount syscall can block in an uninterruptible kernel wait (`D` state), which in turn blocks the containerd goroutine, eventually exhausting the goroutine pool for sandbox creation.

This mechanism explains why even pods without NFS volumes can fail: if containerd's goroutine pool is exhausted by blocked goroutines waiting on NFS bind mounts, no new work can be processed regardless of whether the new pod needs NFS.

**4. microk8s snap IPC / socket state**

microk8s services communicate via Unix sockets under `/var/snap/microk8s/`. After unexpected service interruptions (e.g., the host kernel having NFS hangs), the containerd API socket may be in a state where it accepts new connections but never completes requests — causing the kubelet to queue work indefinitely without timing out.

---

## Troubleshooting steps taken

1. **Checked pod events** — `kubectl describe pod <stuck>` confirmed `PodReadyToStartContainers: False` with zero events. This distinguishes a broken runtime from a slow image pull (which shows `Normal Pulling`).

2. **Checked node conditions** — `kubectl describe node k8s-main` showed all conditions healthy (Ready=True, no pressure). Ruled out resource exhaustion or kubelet failure.

3. **Confirmed node-specificity** — all stuck pods were on k8s-main; all pods on k8s-worker1 and k8s-worker2 started normally. Ruled out cluster-wide issues (API server, scheduler, etcd).

4. **Deployed busybox test pod pinned to k8s-main** —
   ```bash
   kubectl run busybox-test --image=busybox:latest --restart=Never \
     --overrides='{"spec":{"nodeSelector":{"kubernetes.io/hostname":"k8s-main"}}}' \
     -n default -- sleep 30
   ```
   Pod cycled ContainerCreating → Terminating repeatedly for 9 minutes, never running. This ruled out NFS/CSI/secrets as the cause — busybox has no volumes and no secrets.

5. **Restarted NFS CSI node pod on k8s-main** —
   ```bash
   kubectl delete pod csi-nfs-node-87zr7 -n kube-system
   ```
   No lasting improvement. Ruled out NFS CSI driver as the sole cause.

6. **Restarted Calico node pod on k8s-main** — No lasting improvement. Ruled out the Calico pod as the sole cause (the Calico *pod* is separate from the CNI *binary* and kernel state).

7. **Cordoned k8s-main and force-rescheduled stuck pods** — Worked around the issue for running services by moving them to healthy workers, but did not fix the node.

8. **Drained k8s-main** — `kubectl drain k8s-main --ignore-daemonsets --delete-emptydir-data`. Confirmed no in-flight workloads remaining.

9. **`microk8s stop && microk8s start` on k8s-main** — Full recovery. All microk8s snap services restarted cleanly, containerd state cleared, NFS stale mounts released, node returned to fully functional. Uncordoned and workloads scheduled successfully.

---

## Fix

### Immediate: `microk8s stop && microk8s start` on the affected node

```bash
# SSH to k8s-main (192.168.0.35), then:
microk8s stop
microk8s start

# Back on the management machine, uncordon if needed:
kubectl uncordon k8s-main
```

This works because microk8s stop shuts down all snap-managed services in dependency order (kubelet, then containerd, then CNI), fully releasing all in-memory state, stale goroutines, and socket connections. On restart, containerd initialises from a clean state, re-scans its on-disk state for consistency, and CNI re-registers. Any stale kernel NFS mounts that were blocking containerd bind mounts are also released when containerd stops and its bind-mount subtree is cleaned up by the kernel.

A plain `microk8s restart` may not be sufficient if there are goroutines in uninterruptible kernel wait — a stop followed by a start ensures a clean process boundary.

### Files changed

- `cluster_config/postgres/postgres.yaml` — removed `fsGroup: 999` and `fsGroupChangePolicy: OnRootMismatch` from all four postgres StatefulSets. This is a separate but related fix: `fsGroup` caused kubelet to `chown` NFS volumes on pod start, which fails with NFS `root_squash`. Removing it prevents one class of FailedMount errors that can contribute to NFS state accumulation on nodes. (See secondary fix section below.)

---

## Secondary fix: NFS fsGroup errors on postgres StatefulSets

While resolving the main issue, a separate NFS permissions failure was uncovered that affects postgres StatefulSets when they reschedule to a different node.

**Symptom:** `FailedMount` warning events on postgres pods:
```
MountVolume.SetUp failed for volume "pvc-4de92233...": applyFSGroup failed for vol
192.168.0.10#mnt/ssd_pool/nfs_dataset#pvc-4de92233...##:
open /var/snap/microk8s/.../mount/pgdata: permission denied
```

**Cause:** The pod `securityContext` had `fsGroup: 999`, which instructs kubelet to `chown -R :999` the mounted volume at pod start. On NFS with `root_squash`, the kubelet (running as root) is mapped to `nobody` (UID 65534) by the NFS server and cannot modify the `pgdata` directory (mode `700`, owned by `999:999`). 

`fsGroupChangePolicy: OnRootMismatch` was tried first but also fails — it requires kubelet to `stat` the directory root to check ownership, which also fails with root_squash + mode 700.

**Fix:** Removed `fsGroup` entirely. The postgres container runs as `runAsUser: 999` and already owns its data files. No kubelet-level chown is needed.

```yaml
# Before
securityContext:
  runAsUser: 999
  runAsGroup: 999
  fsGroup: 999

# After
securityContext:
  runAsUser: 999
  runAsGroup: 999
```

**Note for fresh PVCs:** On a brand-new PVC, the NFS volume root may be owned by `root:root`. If the NFS export is not configured to allow UID 999 to create directories, postgres initdb will fail. For existing PVCs this is not an issue. For fresh deployments, ensure the TrueNAS dataset has default permissions that allow UID 999 write access, or pre-create the `pgdata` directory with correct ownership via an initContainer.

---

## Recommended prevention and long-term fixes

### Option 1: Capture containerd diagnostics before next restart (high value)

The next time this occurs, run the following on k8s-main **before** `microk8s stop` to determine the exact cause:

```bash
# Capture containerd service logs (last hour)
sudo journalctl -u snap.microk8s.daemon-containerd --since "1 hour ago" \
  > /tmp/containerd-$(date +%Y%m%d-%H%M%S).log

# List all pod sandboxes containerd knows about
sudo /var/snap/microk8s/current/bin/crictl \
  --runtime-endpoint unix:///var/snap/microk8s/common/run/containerd.sock pods

# List all containers (including stopped/broken ones)
sudo /var/snap/microk8s/current/bin/crictl \
  --runtime-endpoint unix:///var/snap/microk8s/common/run/containerd.sock ps -a

# Check for stuck kernel processes (D state = uninterruptible wait)
ps aux | awk '$8=="D"'

# Check for stale NFS mounts
cat /proc/mounts | grep nfs
findmnt -t nfs,nfs4

# Check containerd socket responsiveness
timeout 5 sudo /var/snap/microk8s/current/bin/crictl \
  --runtime-endpoint unix:///var/snap/microk8s/common/run/containerd.sock info \
  && echo "containerd responsive" || echo "containerd UNRESPONSIVE"
```

The last command is the fastest single-line diagnostic: if `crictl info` times out, containerd is hung and microk8s restart is the correct response.

### Option 2: Early detection — check for the silent ContainerCreating pattern

The no-events ContainerCreating state is distinguishable from a normal slow pull by the absence of any events. A monitoring check on the management machine:

```bash
#!/bin/bash
# Run periodically (e.g. every 5 minutes via cron or systemd timer)
# Detects pods stuck in ContainerCreating on k8s-main with no events for > 5 minutes

STUCK_PODS=$(kubectl get pods -A -o wide --no-headers \
  | grep "ContainerCreating" | grep "k8s-main" \
  | awk '{print $1 "/" $2}')

for pod_ref in $STUCK_PODS; do
  ns=$(echo $pod_ref | cut -d/ -f1)
  pod=$(echo $pod_ref | cut -d/ -f2)
  age=$(kubectl get pod $pod -n $ns --no-headers | awk '{print $5}')
  events=$(kubectl get events -n $ns --field-selector=involvedObject.name=$pod --no-headers 2>/dev/null | wc -l)
  
  # Only alert if > 5m old AND has zero events (not just a slow pull)
  if [[ "$age" == *"m"* ]] && [ "$events" -eq 0 ]; then
    echo "ALERT: $pod in $ns stuck on k8s-main for $age with no events — likely containerd failure"
  fi
done
```

### Option 3: NFS soft mounts to prevent indefinite kernel hangs

The initial trigger in this session was NFS volumes failing to unmount, which likely contributed to containerd's broken state. Configuring NFS mounts as `soft` with a timeout prevents indefinite kernel waits:

In the NFS CSI StorageClass (or the driver's default mount options), add:
```yaml
mountOptions:
  - soft
  - timeo=30      # 3 seconds timeout (in 0.1s units)
  - retrans=3     # retry 3 times before failing
```

`soft` mounts return an error to the calling process if the NFS server is unreachable after `timeo × retrans` attempts, rather than blocking forever in `D` state. This prevents the cascade where a stale NFS mount blocks containerd goroutines.

**Trade-off:** Soft mounts can return I/O errors to applications (including postgres) if the NFS server is temporarily unavailable. For a home lab with a reliable TrueNAS server this is acceptable; in production this requires careful consideration.

### Option 4: Scheduled weekly microk8s restart (lowest effort, prevents accumulation)

If the root cause is state accumulation over time, a scheduled restart during off-hours prevents the issue from ever manifesting:

```bash
# On k8s-main — add to crontab (crontab -e):
0 3 * * 0  microk8s stop && microk8s start
```

This is a blunt instrument but effective if the state corruption is time-dependent. The cluster loses k8s-main as a worker for ~60 seconds during the restart; StatefulSets and any pods with `nodeName: k8s-main` will briefly reschedule.

### Option 5: Move control plane workloads off k8s-main

k8s-main runs both the control plane (API server, etcd, scheduler) and worker workloads. If k8s-main's containerd is broken, control plane components are also at risk (they run as static pods managed by the same containerd). Consider tainting k8s-main to prevent non-system workloads from scheduling there:

```bash
kubectl taint nodes k8s-main node-role.kubernetes.io/control-plane=:NoSchedule
```

This does not prevent the issue but limits blast radius — when k8s-main's containerd fails, only system pods are affected rather than user workloads.

---

## Quick reference: diagnosis flowchart

```
Pod stuck in ContainerCreating > 2 minutes
          │
          ▼
kubectl describe pod → Events section
          │
    ┌─────┴──────┐
  Empty         Has events
    │                │
    ▼                ▼
PodReadyToStart   "Pulling" → slow Docker Hub pull, wait
Containers: False "FailedMount" → NFS/CSI issue
    │             "Failed" → image pull error
    ▼
Which node?
    │
    ├── k8s-worker1/2 → different issue, investigate separately
    │
    └── k8s-main
            │
            ▼
    All pods on k8s-main affected? (test with busybox)
            │
            ├── No → specific pod/namespace issue
            │
            └── Yes → containerd broken on k8s-main
                        │
                        ▼
              SSH to k8s-main:
              microk8s stop && microk8s start
              kubectl uncordon k8s-main
```

---

## Environment context

- **Node:** k8s-main (`192.168.0.35`) — Kubernetes v1.35.0, microk8s
- **Storage:** TrueNAS NFS server at `192.168.0.10`, path `/mnt/ssd_pool/nfs_dataset`
- **NFS CSI driver:** `csi-nfs-controller` + `csi-nfs-node` daemonset in `kube-system`
- **CNI:** Calico (bundled with microk8s)
- **Container runtime:** containerd (bundled with microk8s snap)
- **Cluster topology:** k8s-main (control plane + worker), k8s-worker1, k8s-worker2

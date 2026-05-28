# Pods stuck in ContainerCreating on k8s-main

Pods scheduled to k8s-main sit in `ContainerCreating` indefinitely. No containers ever start. Workers are unaffected.

---

## Step 1 — Confirm the pattern

```bash
kubectl describe pod <stuck-pod> -n <namespace>
```

Look at the **Conditions** and **Events** sections:

| Conditions | Events | Diagnosis |
|---|---|---|
| `PodReadyToStartContainers: False` | Has `Pulling` / `Pulled` events | Normal slow pull — wait |
| `PodReadyToStartContainers: False` | Has `ErrImagePull` / `Failed` events | Image pull failed — see Step 3 |
| `PodReadyToStartContainers: False` | **Zero events** for 3+ minutes | Runtime failure — continue below |
| `PodReadyToStartContainers: False` | Has `FailedMount` events | NFS/CSI issue — see [nfs-volume-mount-failures.md](nfs-volume-mount-failures.md) |

If zero events and age > 3 minutes on k8s-main, continue to Step 2.

---

## Step 2 — Determine which failure mode

SSH to k8s-main (`192.168.0.35`) and run:

```bash
timeout 5 sudo microk8s ctr version && echo "containerd RESPONSIVE" || echo "containerd UNRESPONSIVE"
```

| Result | Failure mode | Go to |
|---|---|---|
| RESPONSIVE | Image pull hanging or bad cached manifest | Step 3 |
| UNRESPONSIVE | containerd deadlocked | Step 4 |

---

## Step 3 — Fix: image pull failure (containerd responsive)

This covers two sub-cases that present identically from kubectl.

### 3a — Bad cached manifest (Docker Hub rate limiting)

**Symptom in containerd log:** `unexpected media type text/html` for the image  
**Cause:** Docker Hub returned an HTML error page when the manifest was fetched; containerd cached it. Every subsequent pull fails immediately with the cached bad entry.

**Fix (SSH to k8s-main):**
```bash
# Remove the bad cached entry — substitute your actual image name
sudo microk8s ctr images rm docker.io/<user>/<image>:<tag>

# Example:
sudo microk8s ctr images rm docker.io/dwilson2547/danwiki-backend:latest
sudo microk8s ctr images rm docker.io/dwilson2547/danwiki-frontend:latest
```

Then trigger a fresh pull from the management machine:
```bash
kubectl rollout restart deployment/<name> -n <namespace>
# or force-delete the pod if it's not managed by a deployment
kubectl delete pod <pod> -n <namespace>
```

### 3b — Hanging pull (Docker Hub connection accepted, data not flowing)

**Symptom in containerd log:** pull started but `bytes read=0` after minutes  
**Cause:** Docker Hub accepted the TCP connection but stalled. The pull blocks indefinitely.

**Fix (management machine):**
```bash
# Force-delete the stuck pod. This triggers StopPodSandbox in containerd,
# which aborts the hanging pull. Kubernetes recreates the pod immediately.
kubectl delete pod <stuck-pod> -n <namespace> --force --grace-period=0
```

If Docker Hub has recovered, the recreated pod pulls and starts normally. If it stalls again, Docker Hub is still degraded — wait and retry.

**Verify Docker Hub is reachable from k8s-main:**
```bash
# SSH to k8s-main
curl -sI https://registry-1.docker.io/v2/ | head -3
# Expected: HTTP/2 401 (auth challenge — means the endpoint is up)
# If timeout/connection refused: Docker Hub is down from this node
```

---

## Step 4 — Fix: containerd unresponsive (full restart required)

Use this path only when `microk8s ctr version` times out. This is the more disruptive fix.

**On k8s-main:**
```bash
# Cordon first so the scheduler stops sending new work here
kubectl cordon k8s-main   # run from management machine

# SSH to k8s-main, then:
microk8s stop
microk8s start
```

**Back on management machine:**
```bash
kubectl uncordon k8s-main
```

**Why `stop && start` and not `restart`:** `microk8s restart` may not fully release goroutines in uninterruptible kernel wait (e.g. stale NFS bind mounts). A stop/start ensures a clean process boundary — containerd re-initialises from scratch, CNI re-registers, and any stale kernel mounts under the snap path are released.

---

## Step 5 — Verify recovery

```bash
# Watch pods on k8s-main resume
kubectl get pods -A -o wide -w | grep k8s-main

# Confirm the node is schedulable and healthy
kubectl get node k8s-main
kubectl describe node k8s-main | grep -A 6 Conditions
```

---

## Quick reference — diagnostic commands

All run from management machine unless noted.

```bash
# Find all stuck ContainerCreating pods on k8s-main
kubectl get pods -A -o wide --no-headers \
  | awk '$4 == "ContainerCreating" && $NF == "k8s-main"'

# Check events for a specific pod (zero events = critical signal)
kubectl describe pod <pod> -n <namespace> | grep -A 20 "Events:"

# SSH to k8s-main: is containerd alive?
timeout 5 sudo microk8s ctr version

# SSH to k8s-main: list images (look for bad/unexpected entries)
sudo microk8s ctr images ls | grep <image-name>

# SSH to k8s-main: see all pods/containers containerd knows about
sudo /var/snap/microk8s/current/bin/crictl \
  --runtime-endpoint unix:///var/snap/microk8s/common/run/containerd.sock pods
sudo /var/snap/microk8s/current/bin/crictl \
  --runtime-endpoint unix:///var/snap/microk8s/common/run/containerd.sock ps -a
```

---

## Background

- **Node:** k8s-main (`192.168.0.35`) — Kubernetes v1.35.0, microk8s snap, control plane + worker
- **Container runtime:** containerd (bundled with microk8s snap)
- **CNI:** Calico (bundled with microk8s snap)
- **Storage:** NFS CSI driver (`csi-nfs-node-*` in kube-system), TrueNAS at `192.168.0.10`

The node shows `Ready=True` in all failure modes because node conditions are reported by the kubelet, which remains healthy even when containerd or image pulls are broken. This is why the symptom is invisible to standard cluster health checks.

See [../docs/issues/2026_05_27_microk8s_main_node_runtime_failure.md](../docs/issues/2026_05_27_microk8s_main_node_runtime_failure.md) for the original incident write-up and syslog analysis.

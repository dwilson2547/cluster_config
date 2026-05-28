# cluster_config + DanWiki — AI-Assisted Engineering Session Showcase
**May 2026 · Claude Code (claude-sonnet-4-6)**

---

## What Is This?

`cluster_config` is a GitOps repository that drives a self-hosted MicroK8s Kubernetes cluster via ArgoCD. It manages core infrastructure (PostgreSQL with pgvector, CoreDNS, Traefik ingress, monitoring), application deployments for several services (gyopart, scrape-stack, DanWiki, robo-services), and cluster-wide DNS zones. `DanWiki` is an AI-powered wiki application — Flask API + React SPA + embedding microservice + RQ worker — being onboarded to the cluster for the first time this session.

This session covered DanWiki's initial Kubernetes deployment (diagnosing and fixing 6 blockers), a recurring microk8s node failure investigation including full syslog analysis that overturned the initial root-cause hypothesis, a Postgres NFS volume fix that was causing data loss risk on node reschedule, and the creation of an operational playbook directory.

---

## What Was Already in Place at Session Start

- MicroK8s cluster: k8s-main (control plane + worker, `192.168.0.35`), k8s-worker1, k8s-worker2
- ArgoCD managing: dns, monitoring, postgres, homepage, ai-services, gyopart, scrape-stack, robo-services, pub-sub
- PostgreSQL StatefulSets: `postgres-pgvector` (prod) and `postgres-pgvector-dev` (dev) in the `postgres` namespace
- NFS CSI driver backed by TrueNAS at `192.168.0.10`; `nfs-dataset` storage class
- CoreDNS (`coredns-local`) serving `.local` zones; Traefik as cluster ingress at `192.168.0.60`
- DanWiki Helm chart committed but not yet successfully running; DNS zone `danwiki.local` added; ArgoCD apps registered

---

## Task 1 — DanWiki Initial Kubernetes Deployment (6 blockers)

**Request:** *"Get DanWiki running on the cluster — it's stuck with pods failing to start."*

**What happened:**

Six distinct blockers were diagnosed and fixed in sequence:

1. **Wrong registry** — Helm chart referenced `ghcr.io/dwilson2547/danwiki-*` images that did not exist; images were on Docker Hub. Fixed `values.yaml` to use `dwilson2547/danwiki-*`.

2. **Wrong storage class** — Uploads PVC and Redis PVC used `nfs-crucial` (a TrueNAS dataset that no longer exists). Changed to `nfs-dataset`.

3. **Nginx API proxy conflict** — The Helm chart included an nginx sidecar proxy to forward `/api` traffic; this conflicted with Traefik's `StripPrefix` middleware handling the same path transformation. The nginx layer was removed and `imagePullPolicy: Always` was set so new images pull immediately.

4. **Missing initial schema migration** — Alembic's migration chain had no `0001_initial_schema` file, so `flask db upgrade` ran on an empty database and produced nothing. Created `0001_initial_schema.py` with all table DDL (users, wikis, pages, page_revisions, attachments, members, page_embeddings, tags, wiki_members) plus HNSW index on the vector column.

5. **fsGroup NFS incompatibility** — PostgreSQL pod failed to start with permission denied on `/var/lib/postgresql/data` after being rescheduled to a different node. Root cause: NFS server has `root_squash` enabled, so the kubelet (running as root) gets mapped to `nobody` (UID 65534) when trying to `chown` the pgdata directory. Removed `fsGroup: 999` from all four Postgres StatefulSets (`postgres-pgvector`, `postgres-pgvector-dev`, and their respective prod/dev variants). PostgreSQL initialises its own data directory permissions at startup without needing kubelet assistance.

6. **Pod sandbox failure on k8s-main** — New DanWiki pods scheduled to k8s-main sat in `ContainerCreating` indefinitely with zero events. This triggered a full node investigation (see Task 2).

**Outcome:** DanWiki fully operational — backend, frontend, embedding service, and worker all running; semantic search functional.

**Files changed:**
- `DanWiki/helm/danwiki/values.yaml` — registry, storage class, pull policy
- `DanWiki/migrations/versions/0001_initial_schema.py` — new: complete schema migration
- `cluster_config/postgres/deployment.yml` — removed `fsGroup` from all 4 StatefulSets
- `DanWiki/docs/issues/2026_05_27_k8s_initial_deployment_blockers.md` — new: full issue write-up

---

## Task 2 — MicroK8s Node Failure Investigation and Syslog Analysis

**Request:** *"Pods on k8s-main are stuck in ContainerCreating forever with no events. Workers are fine. Figure out what's happening."*

**What happened:**

Initial investigation confirmed the classic broken-node pattern: `PodReadyToStartContainers: False`, zero events even for a simple busybox pod pinned to k8s-main. The initial hypothesis was that containerd's pod sandbox creation was broken.

The user dumped the full k8s-main syslog (78,500 lines, May 24–27) to `~/documents/k8s_nfs_death.log` for deep analysis. Analysis proceeded in sections:

**Chronic background noise identified and ruled out:**
- `kine.sock` gRPC reconnection errors: ~240/hour continuously since May 24 — known MicroK8s behavior where kubelet reconnects to the kine-backed API server endpoint; not specific to the failure window
- `csi-nfs-node` liveness probe errors: ~1,140/day — a known MicroK8s bug registering duplicate probes; harmless

**Actual timeline reconstructed from syslog:**
- `04:28 UTC`: Docker Hub returned an HTML error page when containerd fetched the `danwiki-backend:latest` manifest. Containerd cached the HTML page as the manifest (`unexpected media type text/html for sha256:0e024625...`)
- `05:05–06:15 UTC`: Image pull attempts for both danwiki images hung at `bytes read=0` — the TCP connection to Docker Hub was accepted but data never flowed
- `05:51–05:59 UTC`: busybox test pod pull also hung for 8 minutes at 0 bytes before user killed it
- `06:15:01 UTC`: All hanging pulls failed simultaneously with `ErrImagePull: EOF`

**Sandbox success confirmed:** Every `RunPodSandbox` call returned a valid sandbox ID within ~700ms throughout the failure window. The initial hypothesis was wrong — containerd's sandbox creation worked perfectly. The failure was entirely at the image pull layer.

**Why workers were unaffected:** Worker nodes had `danwiki-backend:latest` and `danwiki-frontend:latest` cached from previous runs. They never attempted a Docker Hub pull during the failure window.

**Non-restart fix path developed:** Since containerd was responsive throughout, `microk8s stop && microk8s start` was unnecessary. The minimal fix:
```bash
# Confirm containerd is responsive
timeout 5 sudo microk8s ctr version && echo "OK" || echo "UNRESPONSIVE"
# Remove bad cached manifest
sudo microk8s ctr images rm docker.io/dwilson2547/danwiki-backend:latest
sudo microk8s ctr images rm docker.io/dwilson2547/danwiki-frontend:latest
# Abort any hanging pulls by force-deleting the pod
kubectl delete pod <stuck-pod> -n <namespace> --force --grace-period=0
```

The issue document was substantially revised: the "broken containerd sandbox" hypothesis replaced with the Docker Hub manifest cache poisoning root cause, and the preferred fix changed from microk8s restart to cache clearing.

**Files changed:**
- `cluster_config/docs/issues/2026_05_27_microk8s_main_node_runtime_failure.md` — major update: syslog analysis section, revised timeline, revised root cause, non-restart fix path, chronic noise documentation
- `cluster_config/CHANGELOG.md` — syslog findings appended to microk8s entry

---

## Task 3 — Pods-Stuck-ContainerCreating Playbook

**Request:** *"Add a playbooks folder to cluster_config with a procedural runbook for this issue — when X happens do Y, not a historical write-up."*

**What happened:**

Created `cluster_config/playbooks/` and wrote `pods-stuck-container-creating.md` as a present-tense decision-tree runbook. The document is designed to be read under incident pressure — each step either resolves the issue or routes to the next step.

Structure:
- **Step 1**: Confirm the pattern via `kubectl describe pod` — table maps Conditions+Events combinations to diagnoses (slow pull / image pull fail / runtime failure / NFS/CSI issue)
- **Step 2**: Single fork command (`timeout 5 sudo microk8s ctr version`) to distinguish "image pull hanging" from "containerd unresponsive"
- **Step 3a**: Bad cached manifest fix — `microk8s ctr images rm` + rollout restart
- **Step 3b**: Hanging pull fix — force-delete pod to abort the stalled pull
- **Step 4**: Full restart path — only reached if containerd is confirmed unresponsive
- **Step 5**: Verify recovery
- Quick-reference command block for copy-paste use

The CHANGELOG was updated with a new entry at the top pointing to the new playbooks directory.

**Files changed:**
- `cluster_config/playbooks/pods-stuck-container-creating.md` — new
- `cluster_config/CHANGELOG.md` — new entry for playbooks directory

---

## Summary of Infrastructure Built

| Component | Technology | Notes |
|---|---|---|
| DanWiki backend | Flask + SQLAlchemy + pgvector | Initial schema migration created; `0001_initial_schema.py` |
| DanWiki Helm chart | Helm + Kubernetes | Registry, storage class, pull policy fixed |
| PostgreSQL StatefulSets | PostgreSQL 16 + pgvector | `fsGroup` removed from all 4 StatefulSets to fix NFS root_squash |
| Operational playbooks | Markdown runbooks | `cluster_config/playbooks/` directory established |
| Issue documentation | Markdown | k8s deployment blockers + microk8s node failure write-ups |

---

## Commits in This Session

**cluster_config:**

| Hash | Description |
|---|---|
| `f0b3de5` | Add automatic reloader annotations |
| `327a32a` | docs: add playbook for stuck ContainerCreating pods, update microk8s issue with syslog findings |
| `e01ac12` | docs: document recurring microk8s containerd failure on k8s-main |
| `9d6d03d` | fix: remove fsGroup from postgres StatefulSets to fix NFS root_squash |
| `70fc5d5` | fix: add fsGroupChangePolicy OnRootMismatch to all postgres StatefulSets |

**DanWiki:**

| Hash | Description |
|---|---|
| `7b5b4b0` | docs: add k8s initial deployment blockers issue document |
| `fdd8f4b` | fix: add initial schema migration for core tables |
| `f3c151a` | fix: remove nginx api proxy (handled by Traefik), set pullPolicy Always |
| `f9d601b` | fix: use Docker Hub (dwilson2547) instead of ghcr.io |
| `8001d27` | fix: use nfs-dataset storage class for uploads and redis PVCs |

---

*Document generated 2026-05-28. Repositories: `dwilson2547/cluster_config`, `dwilson2547/DanWiki`.*

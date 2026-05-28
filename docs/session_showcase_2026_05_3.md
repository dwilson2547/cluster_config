# Todo Store — AI-Assisted Engineering Session Showcase
**May 2026 · GitHub Copilot CLI (Claude Sonnet 4.6)**

---

## What Is This?

The Todo Store is a lightweight task-tracking microservice (FastAPI + SQLite + SPA UI) with a
companion CLI and Copilot skill. This session covered the full deployment of Todo Store to the
home Kubernetes cluster via GitOps (ArgoCD), migrating the existing local SQLite backlog into
the live cluster instance and surfacing the service on the `ai-services.local` ingress. The
session also uncovered that the `reloader` ArgoCD application had never been committed to
`cluster_config` and was therefore silently absent from the cluster.

---

## What Was Already in Place at Session Start

- Todo Store service built and running locally via Docker Compose (`todo-store/`)
- `dwilson2547/todo-store-api:latest` and `dwilson2547/todo-store-ui:latest` images published to Docker Hub
- `cluster_config` repo managing the home Kubernetes cluster via ArgoCD
- Existing `ai-services` deployment manifest covering context-store, notes, playbooks, and other
  AI-stack services
- A pending todo item (#5) to deploy Todo Store to k8s, tracked in the local Todo Store instance
- A dirty `cluster_config` local worktree with unreviewed staged/unstaged changes

---

## Task 1 — Deploy Todo Store to Kubernetes

**Request:** *"Can you check the todo-store for the todo to add the todo-store to k8s? I'd like to complete that task now."*

**What happened:**
- Retrieved todo #5 from the local Todo Store via the `todo` CLI and confirmed the task scope
- Consulted `cluster_config/CLAUDE.md` for the ArgoCD-managed deployment conventions for this cluster
- Added a `todo-store` container block to `cluster_config/ai-services/deployment.yml`, wiring up
  the API (`port 8003`) and UI (`port 80`) with appropriate env vars and volume mounts
- Added a `todo.ai-services.local` ingress rule in `dns/dns.yaml`
- Added a Todo Store entry to `homepage/homepage.yaml` so it appears in the cluster dashboard
- Used a clean git clone (not the dirty local worktree) to commit and push all manifests to `main`,
  letting ArgoCD sync the changes to the cluster
- Discovered the initial ingress was broken — a YAML indentation error in `deployment.yml` caused
  the port spec to be invalid, which left ArgoCD stuck in a retry loop; manually applied the
  corrected manifest with `kubectl apply` to unblock it while ArgoCD awaited the push
- Filed an incident write-up at `cluster_config/docs/issues/2026_05_25_todo_store_ingress_port_indentation.md`
- Migrated the existing local backlog from the Docker Compose SQLite instance into the cluster instance
- Set `TODO_STORE_API_URL=http://todo.ai-services.local/api` in the local environment
- Marked todo #5 as done in the now-live cluster store

**Outcome:** Todo Store live at `http://todo.ai-services.local` (UI) and `http://todo.ai-services.local/api` (API), fully managed by ArgoCD.

---

## Task 2 — Audit the Dirty cluster_config Worktree

**Request:** *"Good work, did we push the DNS manually? I see there are still changes staged."*

**What happened:**
- Clarified that DNS was pushed through GitOps (clean clone → commit → ArgoCD sync), not via
  manual `kubectl apply`
- User dumped a diff of the dirty local worktree to `diff.txt` and pulled `main`; agent reviewed
  the diff to identify what, if anything, was at risk of being lost
- Confirmed all tracked changes (`CHANGELOG.md`, `CLAUDE.md`, `ai-services/deployment.yml`,
  `dns/dns.yaml`, `homepage/homepage.yaml`) were already on `main`
- Identified remaining untracked files of note: `argocd/reloader.yaml` (potentially important),
  `docs/issues/2026_05_24_context_store_ingress_404.md`, and legacy `kubernetes/` reference manifests

**Outcome:** Confirmed no in-flight work was lost when the user pulled main; flagged `argocd/reloader.yaml` as the one untracked item warranting attention.

---

## Task 3 — Investigate the Missing Reloader Application

**Request:** *"The stupid reloader was never added to the cluster either, no wonder it never worked."*

**What happened:**
- Confirmed that `argocd/reloader.yaml` was an ArgoCD Application manifest for the Stakater
  Reloader controller (auto-restarts pods on ConfigMap/Secret changes), but it had never been
  committed to `cluster_config`
- Because ArgoCD only manages what is committed to the tracked repo, the reloader was never
  installed in the cluster despite the file existing locally
- Root cause: the manifest was authored locally and never pushed — classic "works on my machine"
  GitOps gap

**Outcome:** Root cause of reloader never working identified; `argocd/reloader.yaml` flagged for a follow-up commit to actually deploy reloader to the cluster.

---

## Task 4 — Establish Global Copilot Behavioral Rules

**Request:** *"Thanks, is there a global Copilot instructions file we can update that you will always listen to?"*

**What happened:**
- Identified `$HOME/.copilot/copilot-instructions.md` as the global instruction file respected
  by the Copilot CLI across all sessions
- Created the file with the following rules at the user's direction:
  - Never assume how something is deployed — always check repo-specific documentation first
  - Consult `cluster_config/CLAUDE.md` before planning or changing anything Kubernetes-related
  - Stop and ask before broad re-investigation when more direction is needed
  - If blocked by a `sudo` prompt, stop and ask the user — do not invent workaround commands
  - Prefer correctness over "it appears to work"
  - Do not use Copilot memories (`store_memory`/`vote_memory`) unless explicitly asked
  - Do not let notes/memory side-workflows interrupt direct requests

**Outcome:** `~/.copilot/copilot-instructions.md` created with persistent behavioral rules applied to all future sessions.

---

## Summary of Infrastructure Built

| Component | Technology | Notes |
|---|---|---|
| Todo Store API | FastAPI + SQLite | Deployed to `ai-services` namespace, port 8003 |
| Todo Store UI | Static SPA (nginx) | Deployed to `ai-services` namespace, port 80 |
| Ingress rule | k8s Ingress + CoreDNS | `todo.ai-services.local` → ui; `/api` → api |
| Homepage entry | Flame/Homer YAML | Todo Store card added to cluster dashboard |
| Incident doc | Markdown | `cluster_config/docs/issues/2026_05_25_todo_store_ingress_port_indentation.md` |
| Global instructions | Copilot CLI config | `~/.copilot/copilot-instructions.md` |

---

*Document generated 2026-05-28. Repository: `dwilson2547/SKILLS`. Session: `3040b240-9896-4dd6-be29-122ac84bea34`.*

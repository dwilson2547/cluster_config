# cluster_config — AI-Assisted Engineering Session Showcase
**May 2026 · GitHub Copilot CLI (GPT-5.4)**

---

## What Is This?

`cluster_config` is the GitOps repository for a home Kubernetes cluster, with ArgoCD managing infrastructure services such as the homepage dashboard and local DNS. This session handled a single maintenance request from start to finish: standardising Stakater Reloader annotations on both Deployments so ConfigMap changes trigger automatic restarts. The work included manifest inspection, corrective edits, commit-and-push to `main`, ArgoCD reconciliation checks, and live-cluster verification.

---

## What Was Already in Place at Session Start

- `homepage/` and `dns/` were already managed from `cluster_config` as ArgoCD-synced manifest applications.
- ArgoCD was configured to reconcile changes pushed to `main`.
- Both services already depended on ConfigMaps, but their reload annotations were not aligned with the requested `reloader.stakater.com/auto: "true"` standard.
- DNS already used a ConfigMap-specific Stakater annotation, while homepage still had an explicit reload annotation that no longer matched the desired pattern.

---

## Task 1 — Enabling Automatic Stakater Reloads for Homepage and DNS

**Request:** *"we need to add the `reloader.stakater.com/auto: \"true\"` annotation to the homepage and dns deployments so they get reloaded when the configmaps are updated. please complete this work then commit and push those changes to main and verify the annotations are present on the cluster after argo syncs"*

**What happened:**
- The agent started by checking `cluster_config/CLAUDE.md` to confirm the repo-specific deployment rules, then inspected the homepage and DNS manifests instead of blindly appending a new annotation.
- That inspection found a subtle cleanup issue: this was not just a missing key on both Deployments. `homepage/homepage.yaml` still carried a stale explicit reloader annotation, and `dns/dns.yaml` used a ConfigMap-targeted reload annotation. The agent replaced both with the requested automatic mode so the two workloads used the same operational model.
- The concrete manifest changes were:
  - `homepage/homepage.yaml` — set `reloader.stakater.com/auto: "true"` on the `homepage` Deployment.
  - `dns/dns.yaml` — set `reloader.stakater.com/auto: "true"` on the `coredns-local` Deployment.
- After editing, the agent committed and pushed the change to `main` as `f0b3de5` with the message `Add automatic reloader annotations`.
- Verification was performed against the live cluster, not just the repo diff. The agent checked both ArgoCD Applications and both Deployments, then waited for reconciliation.
- DNS updated first, but homepage remained healthy on the previous Git revision. Rather than stopping at “push succeeded,” the agent investigated the homepage Application state, forced an ArgoCD refresh, and continued polling until the deployed revision and the live annotation both matched the committed change.

**Outcome:** The `homepage` and `coredns-local` Deployments both ended up live with `reloader.stakater.com/auto: true`, and the `homepage` and `dns` ArgoCD Applications both reached `Synced Healthy` on commit `f0b3de54d5fb5532aea45d7d9bbfb15346056bda`.

---

## Summary of Infrastructure Built

| Component | Technology | Notes |
|---|---|---|
| Homepage dashboard | Kubernetes Deployment | Now automatically reloads when ConfigMap-backed settings change. |
| Local DNS | CoreDNS Deployment | Now uses the same auto-reload annotation strategy as homepage. |
| GitOps delivery | ArgoCD | Change was deployed by pushing to `main` and confirmed post-sync. |
| Config-triggered rollouts | Stakater Reloader | Standardised on `reloader.stakater.com/auto: "true"` for both services. |

## Commits in This Session

| Hash | Description |
|---|---|
| f0b3de5 | Add automatic reloader annotations |

---

*Document generated 2026-05-28. Repository: `dwilson2547/cluster_config`.*

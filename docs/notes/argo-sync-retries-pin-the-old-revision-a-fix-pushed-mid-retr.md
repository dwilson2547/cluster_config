---
title: Argo sync retries pin the old revision; a fix pushed mid-retry is ignored
date: 2026-10-10
tags: argocd,gotcha
---

When an auto-sync operation fails and has syncPolicy.retry, every retry re-syncs the revision the operation started on, not HEAD. Pushing a fix while it retries changes nothing: the app shows OutOfSync and keeps failing on the old commit until retries run out. No argocd CLI here, so end it with: kubectl patch application <app> -n argocd --type merge -p '{"status":{"operationState":{"phase":"Terminating"}}}' (the --subresource=status form returns NotFound). Auto-sync then starts a fresh operation on HEAD. Hit 2026-10-10 on cert-manager when the ClusterIssuers' secret name was fixed during retry #7.

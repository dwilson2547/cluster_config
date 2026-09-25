---
title: Argo shows Synced on the old revision until it polls — hard-refresh after pushing DNS
date: 2026-09-25
tags: argocd,dns,coredns
---

After pushing a dns/dns.yaml change, the dns app reported Synced/Healthy but was still on the previous commit (Argo polls git every ~3 min), so the new zones did not resolve and it looked like Reloader had failed. Check .status.sync.revision against the pushed SHA, and force it with: kubectl -n argocd annotate app <app> argocd.argoproj.io/refresh=hard --overwrite. Reloader then rolls coredns-local within seconds.

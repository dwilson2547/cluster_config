# Notes index

- [Argo shows Synced on the old revision until it polls — hard-refresh after pushing DNS](argo-shows-synced-on-the-old-revision-until-it-polls-hard-re.md) — After pushing a dns/dns.yaml change, the dns app reported Synced/Healthy but was still on the previous commit… `argocd,dns,coredns`
- [Argo sync retries pin the old revision; a fix pushed mid-retry is ignored](argo-sync-retries-pin-the-old-revision-a-fix-pushed-mid-retr.md) — When an auto-sync operation fails and has syncPolicy.retry, every retry re-syncs the revision the operation s… `argocd,gotcha`
- [authentik OIDC: issuer keeps its trailing slash; new client secrets go in before the push](authentik-oidc-issuer-keeps-its-trailing-slash-new-client-se.md) — authentik per-provider issuers are https://auth.danwils.com/application/o/<slug>/ with a trailing slash, and … `authentik,oidc`

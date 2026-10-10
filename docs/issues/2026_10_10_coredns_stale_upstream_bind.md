# 2026-10-10: CoreDNS forwarded half of all lookups to a stale BIND server (192.168.0.30)

## Symptom
ArgoCD SSO through authentik looped back to `/login?return_url=...`. authentik showed the authorization
as successful, and argocd-server logged `Web login successful` (groups claim correct), then on every
request: `Failed to verify session token ... failed to query provider "https://auth.danwils.com/application/o/argocd/"`
with either `lookup auth.danwils.com on 10.152.183.10:53: no such host` or
`dial tcp [2606:4700:...]:443: connect: network is unreachable`.

## Root cause
The cluster CoreDNS (`kube-system/coredns`, microk8s addon) uses `forward . /etc/resolv.conf`. A pod's
`/etc/resolv.conf` is written once, at pod creation. The CoreDNS pod was 136 days old, and its copy still
listed **192.168.0.30**, which is no longer in any node's resolver config (all three nodes now have
`192.168.0.61` + `8.8.8.8`). CoreDNS spreads queries across upstreams, so about half of them went to .30.

192.168.0.30 is a BIND 9.18 (Ubuntu 24.04) server holding an old authoritative `danwils.com` zone
(SOA `danwils.com. admin.danwils.com. 2 ...`, Debian template defaults): `danwils.com` and
`grafana.danwils.com` → 192.168.0.70 (now the `pub-sub/kreceiver` LB IP), and NXDOMAIN for `auth`.
What machine that is and why it still runs: ⚠ unverified.

The "network is unreachable" variant is the same fault: the A lookup got NXDOMAIN from .30 while the
AAAA lookup went to a good upstream, so Go was left with only Cloudflare IPv6 addresses, and the cluster
has no IPv6 route.

The ArgoCD callback succeeded only because its own token exchange happened to resolve through a good
upstream; session verification re-runs OIDC discovery until it succeeds once, so the coin flip kept failing.
Any in-cluster client of `*.danwils.com` (Grafana, DanWiki and photo-dump talking to authentik) was
exposed to the same intermittent failure.

## How it was found
- `dig A auth.danwils.com @10.152.183.10` from a pod: NXDOMAIN with `aa` and the SOA above, while
  `@192.168.0.61` and `@8.8.8.8` answered correctly.
- CoreDNS is distroless; its upstreams were read from its metrics instead:
  `curl http://<coredns-pod-ip>:9153/metrics | grep proxy_conn_cache_misses_total` showed `to="192.168.0.30:53"`.

## Fix
`kubectl -n kube-system rollout restart deploy/coredns` (strategy maxSurge 10% / maxUnavailable 0, so no
DNS gap). The new pod forwards to `192.168.0.61` and `8.8.8.8` only; 30/30 A lookups of
`auth.danwils.com` through cluster DNS succeeded afterwards.

## Follow-ups
- Decommission the BIND server on 192.168.0.30 or delete its `danwils.com` zone, so nothing else on the
  LAN that still points at it gets wrong answers.
- After any change to node resolvers, restart CoreDNS: it does not re-read the node's resolv.conf.

# 2026-10-10: WAN forward to Traefik exposed every internal Ingress

## Symptom
After the router forwarded WAN 80/443 to Traefik (192.168.0.60) for danwils.com, a request to the
public IP with `Host: home.cluster.local` returned the internal homepage (200). Any `.local` Ingress
(argocd, AI services, dxf-converter, ...) was reachable from the internet by Host header; Cloudflare
was not in that path.

## Root cause
Traefik attaches a router that names no entrypoint to **every** entrypoint, and all Ingresses were
served on the same `web`/`websecure` entrypoints and LoadBalancer IP that the router now forwarded to.

## Fix
- Router forward moved to 192.168.0.65 (nothing listening) as soon as it was seen.
- `traefik/values.yaml`: `web`/`websecure` set `asDefault: true`; new entrypoints `pubweb`/`pubsecure`
  exposed only on a second Service `traefik-public` (192.168.0.65). Publishing is opt-in per Ingress via
  `traefik.ingress.kubernetes.io/router.entrypoints: pubsecure`.
- Verified from the public IP: every `.local` host 404, `danwils.com` 200; LAN `.60` unchanged.

## Gotchas hit on the way
- **Traefik rollout wedged Pending** ("didn't have free ports"): the DaemonSet uses hostPorts 80/443 and
  the chart default update strategy is maxSurge 1 / maxUnavailable 0, so the surge pod can never
  schedule. Now maxSurge 0 / maxUnavailable 1. Every Traefik change since install would have hit this.
- **Cloudflare Flexible → redirect loop**: Flexible fetches the origin over HTTP; `pubweb` redirects to
  HTTPS; loop. Cloudflare SSL/TLS mode is now Full (strict) (set under SSL/TLS → Overview, not DNS).
- **homepage `HOMEPAGE_ALLOWED_HOSTS`** must list `danwils.com:443` as well as `danwils.com`: behind
  Traefik the host arrives with the port, and failing validation renders the page without its config.
  Next.js then serves the stale copy for a few requests after the fix (ISR), so re-check before
  concluding a config change didn't apply.

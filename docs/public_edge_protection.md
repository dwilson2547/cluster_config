# Public edge protection

Everything published on `traefik-public` (192.168.0.65, `pubweb`/`pubsecure`) is covered by the
three layers below. Status as of 2026-10-10.

| Layer | Where | Status |
|---|---|---|
| Origin lockdown | Traefik `ingress/public-origin-lockdown`, default on both public entrypoints | verified |
| Per-visitor flood limits | Traefik `ingress/public-inflight`, `ingress/public-ratelimit`, same | verified |
| Per-app limits on expensive routes | the app's chart (dxf-converter: `heavyRateLimit`) | verified (dxf-converter) |
| Cloudflare WAF and rate-limit rules | Cloudflare dashboard (not in git) | planned, see below |
| Ban list from logs (CrowdSec) | — | not started |

All three Traefik middlewares are in `traefik/values.yaml` (`extraObjects`). The entrypoints list
them under `ports.<pubweb|pubsecure>.middlewares`, so every public router gets them without any
annotation.

## Origin lockdown

The router forwards WAN 80/443 to .65 from anyone, and the origin used to answer directly, which
bypassed Cloudflare. `ipAllowList` checks the **TCP peer** (`RemoteAddr`), not
`X-Forwarded-For`. It admits:

- Cloudflare's ranges;
- the LAN (`192.168.0.0/24`), which covers router hairpin and admin access;
- the pod CIDR (`10.1.0.0/16`). DanWiki, photo-dump and dxf-converter reach authentik through .65
  via `hostAliases`, so removing this breaks their sign-in.

Inbound WAN traffic keeps its real source address: no SNAT, which is why `externalTrafficPolicy:
Local` matters. Any other source gets 403.

- Verified on a throwaway route: an allowlist without LAN gave 403 from the LAN and passed
  Cloudflare traffic.
- ⚠ unverified from an outside network. To check, from mobile data, with the home WAN IP:
  `curl -sk -o /dev/null -w '%{http_code}\n' --resolve danwiki.danwils.com:443:<WAN-IP> https://danwiki.danwils.com/`
  should print `403`.

**Cloudflare's ranges appear twice in `traefik/values.yaml`:** in `forwardedHeaders.trustedIPs`
and in the lockdown. YAML can't concatenate lists. Update both from https://www.cloudflare.com/ips/.
A new Cloudflare range missing here means 403s for visitors routed through it.

## Per-visitor limits: keying

Traefik's default source for `rateLimit`/`inFlightReq` is the TCP peer. Here that is a Cloudflare
edge, so every visitor would share a bucket. These limits use `ipStrategy: {depth: 1, ipv6Subnet: 64}`,
the rightmost `X-Forwarded-For` entry, for two reasons:

- Cloudflare appends the real visitor there, so a client-sent value lands further left and is
  ignored.
- Traefik deletes `X-Forwarded-*` from untrusted peers before middlewares run, and it does not
  append the peer itself (checked in v3.6.2 `forwardedheaders` source). LAN and pod traffic
  therefore has no header and shares one `""` bucket.

Verified: with a spoofed `X-Forwarded-For` changing on every request through Cloudflare, the
limit still tripped.

Values are a flood guard, not a quota: 100 req/s average, burst 300, and 100 concurrent per
visitor (IPv6 per /64). Limits are in-memory per Traefik pod. MetalLB L2 sends all of .65 to one
node, so in practice that is one pod; a failover resets the buckets.

Expensive routes get a stricter middleware in the app's own chart. Use the same `depth: 1`
criterion, and put the middleware on a second Ingress for just those paths, without the
cert-manager or external-dns markers; Traefik prefers the longer path rule. The example is
`tools/dxf-converter/helm/dxf-converter/templates/ratelimit.yaml`: upload and convert, 12/min,
burst 10.

## Cloudflare (planned; dashboard, zone danwils.com, Free plan)

The cluster's Cloudflare token (`cloudflare-api-token-danwils`) is DNS-only on purpose; it gets
403 on rulesets and zone settings. These are clicked in the dashboard:

1. **Security → WAF → Rate limiting rules** (Free allows one rule; fixed 10 s period and 10 s
   block; counts per IP). Suggested rule, "sign-in and uploads":
   `(http.host eq "auth.danwils.com" and starts_with(http.request.uri.path, "/api/v3/flows/executor/"))
   or starts_with(http.request.uri.path, "/api/auth/") or http.request.uri.path eq "/api/upload"`,
   with more than 20 requests per 10 s → Block.
   ⚠ Unverified whether Free accepts `http.host` in this expression. If the builder only offers
   URI path, drop the host clause.
2. **Security → WAF → Custom rules** (Free allows five): block common scanner paths that no app
   here serves, e.g.
   `starts_with(http.request.uri.path, "/wp-") or starts_with(http.request.uri.path, "/.env") or starts_with(http.request.uri.path, "/.git") or ends_with(http.request.uri.path, ".php")`
   → Block.
3. **Bot Fight Mode: leave off.** On Free it can't be skipped per host or path, and it challenges
   non-browser clients, such as the ArgoCD CLI against argocd.danwils.com.
4. **SSL/TLS → Edge certificates:** Always Use HTTPS on.

After applying, record what was set here. The dashboard is the only copy.

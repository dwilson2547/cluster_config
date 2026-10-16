---
title: authentik OIDC: issuer keeps its trailing slash; new client secrets go in before the push
date: 2026-10-15
tags: authentik,oidc
domains: web-scrapers
---

authentik per-provider issuers are https://auth.danwils.com/application/o/<slug>/ with a trailing slash, and the ID token iss claim carries it. A hand-rolled OIDC client that trims the configured issuer (to build the .well-known URL) and then validates iss against the trimmed string refuses every sign-in as unverifiable. Validate iss against the discovery document's issuer field verbatim. Separately: each new OIDC app adds an AUTHENTIK_<APP>_CLIENT_SECRET env to authentik/values.yaml via a non-optional secretKeyRef, so the authentik-<app>-oidc Secret must exist before that push or the authentik pods fail to start. A safe check that authentik loaded the right secret: POST the token endpoint with basic auth and a bogus code. invalid_grant means the secret is right, invalid_client means it is wrong. Found wiring scrape-job-manager's UI, 2026-10-15.

Third trap: PyJWT's PyJWKClient fetches the JWKS with urllib's default `Python-urllib/3.x`
User-Agent, and Cloudflare (proxying auth.danwils.com) returns 403 to it. The callback then fails
with "could not be verified" while discovery and the token exchange (httpx) work. Pass
`headers={"User-Agent": "<app>"}` to PyJWKClient. Pods that resolve auth.danwils.com to
192.168.0.65 (traefik-public, as nodewright's does) skip Cloudflare and never see this.

Fourth trap (2026-10-15, gyopart admin): adding the client-secret env makes authentik roll its pods, and an
old worker without the variable can apply the new blueprint first, storing an empty client secret (token
endpoint then answers invalid_client). After the rollout, re-apply from a new worker:
`kubectl -n authentik exec <new worker> -- ak apply_blueprint /blueprints/mounted/cm-authentik-blueprints-danwils/<app>.yaml`,
then re-run the bogus-code probe (invalid_grant = right secret).

Fifth trap (2026-10-16, gyopart admin prod): a callback can arrive twice for one code; the first exchange
succeeds, the duplicate gets invalid_grant ("Code does not exist" in authentik's log) and its error is what
the browser shows. Also, any signed-out GET that starts a sign-in (favicon, images) overwrites the flow
cookie of the one in progress. Pattern: start sign-in only for navigations (Sec-Fetch-Mode: navigate), and on
a failed callback continue if already signed in, else restart once quietly. Write-up:
automotive/gyopart/docs/issues/2026_10_16_admin_signin_duplicate_callback_spent_code.md.

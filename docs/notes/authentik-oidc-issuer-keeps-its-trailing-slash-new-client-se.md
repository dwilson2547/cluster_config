---
title: authentik OIDC: issuer keeps its trailing slash; new client secrets go in before the push
date: 2026-10-15
tags: authentik,oidc
domains: web-scrapers
---

authentik per-provider issuers are https://auth.danwils.com/application/o/<slug>/ with a trailing slash, and the ID token iss claim carries it. A hand-rolled OIDC client that trims the configured issuer (to build the .well-known URL) and then validates iss against the trimmed string refuses every sign-in as unverifiable. Validate iss against the discovery document's issuer field verbatim. Separately: each new OIDC app adds an AUTHENTIK_<APP>_CLIENT_SECRET env to authentik/values.yaml via a non-optional secretKeyRef, so the authentik-<app>-oidc Secret must exist before that push or the authentik pods fail to start. A safe check that authentik loaded the right secret: POST the token endpoint with basic auth and a bogus code. invalid_grant means the secret is right, invalid_client means it is wrong. Found wiring scrape-job-manager's UI, 2026-10-15.

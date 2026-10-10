# ArgoCD access: SSO through authentik, LAN-only admin

How you sign in to ArgoCD, and where every piece of that lives. Verified 2026-10-10 on ArgoCD
v3.4.2 / authentik 2026.8.3.

## Hosts

| Host | Ingress | Reachable from | Sign-in |
|---|---|---|---|
| https://argocd.danwils.com | `argocd-server/ingress-public.yaml` (traefik-public, `pubsecure`, letsencrypt-prod, external-dns) | internet + LAN | authentik SSO only; password login refused (403) |
| http://argocd.local | `argocd-server/ingress.yaml` (LAN, 192.168.0.60) | LAN | authentik SSO **or** local `admin` (break-glass) |

## Where everything lives

ArgoCD itself was installed from the upstream manifest and is **not** managed by an Argo
Application. Everything under `argocd-server/` is applied by hand:

| File | What | Apply |
|---|---|---|
| `argocd-server/ingress.yaml` | LAN ingress + `server.insecure` | `kubectl apply -f` |
| `argocd-server/ingress-public.yaml` | public ingress, `deny-all` Middleware, login-blocking ingress | `kubectl apply -f` |
| `argocd-server/argocd-cm-patch.yaml` | `url`, `additionalUrls`, `admin.enabled`, `oidc.config` | `kubectl -n argocd patch cm argocd-cm --type merge --patch-file` |
| `argocd-server/argocd-rbac-cm-patch.yaml` | group → role mapping | `kubectl -n argocd patch cm argocd-rbac-cm --type merge --patch-file` |

The configmaps are merge-patched rather than applied whole, because the upstream install owns
their default keys. argocd-server reloads most settings live (its log says "oidc config modified.
restarting", followed by harmless "server closed" errors), **but after changing `oidc.config` you must
also run `kubectl -n argocd rollout restart deploy/argocd-server`**. The session manager builds the HTTP
client it uses for OIDC discovery once, at startup (`NewSessionManager` → `OIDCTLSConfig()`, v3.4.2).
If OIDC was not configured then, that client trusts only ArgoCD's own self-signed certificate. The login
callback still succeeds, because it uses a client that is rebuilt on reload, but every session check
fails with `x509: certificate signed by unknown authority` and the UI bounces back to `/login`.

The authentik side is Argo-managed (`argocd/authentik.yaml`):

- `authentik/blueprints/argocd.yaml`: confidential OAuth2 provider + application `argocd`
  (client id `argocd`, redirects `https://argocd.danwils.com/auth/callback` and
  `http://argocd.local/auth/callback`), groups `argocd-admins` / `argocd-viewers`. The application is
  bound to those two groups, so anyone else is refused at authentik.
- `authentik/values.yaml`: `AUTHENTIK_ARGOCD_CLIENT_SECRET` from Secret `authentik-argocd-oidc`.

## Secrets (hand-applied, never committed)

The same random value is stored in two Secrets:

- `authentik-argocd-oidc` (authentik ns): template `example-secrets/authentik/smtp-and-google.yml`
- `argocd-oidc-authentik` (argocd ns): template `example-secrets/argocd/argocd-oidc.yml`. It **must**
  carry `app.kubernetes.io/part-of: argocd`, or ArgoCD ignores the `$argocd-oidc-authentik:client_secret`
  reference in `oidc.config`.

## Roles

`argocd-rbac-cm`: `scopes: [groups]`, `policy.default: ""`.

| authentik group | ArgoCD role |
|---|---|
| `argocd-admins` | `role:admin` |
| `argocd-viewers` | `role:readonly` |

Group membership is set by hand in authentik, not in the blueprint. `dwilson2547` is in
`argocd-admins`. To give someone view-only access, add them to `argocd-viewers`.

## How the admin password is kept off the internet

ArgoCD can only enable or disable `admin` globally; it has no per-host setting. So the block is at the
ingress. On `argocd.danwils.com` the endpoints that accept a username and password go to a separate
Ingress (`argocd-server-public-deny-local-login`) with the Middleware `argocd-deny-all`:

- `/api/v1/session` (Prefix): REST `SessionService.Create`/`Delete`
- `/session.SessionService/Create` (Prefix): gRPC / gRPC-web (CLI)

`deny-all` is an `ipAllowList` of `127.0.0.1/32`, which no client coming through traefik-public can
match, so Traefik answers 403. `/api/v1/session/userinfo` is routed back to ArgoCD by an `Exact` path on
the main public Ingress (the longer rule wins in Traefik), because the UI calls it to check whether it is
signed in.

Endpoints are taken from `server/session/session.proto` at v3.4.2. **After every ArgoCD upgrade,
check that no new password-login endpoint has appeared**, then re-run the checks below.

Verified (2026-10-10): public POST to `/api/v1/session`, `/api/v1/session/`, `/api/v1//session`,
`/api/v1/%73ession`, `/api/v1/./session` and grpc-web `/session.SessionService/Create` all return 403
and never reach ArgoCD. Public `GET /api/v1/session/userinfo` returns 200. A LAN POST to
`http://argocd.local/api/v1/session` reaches ArgoCD (401 for a bad password).

```bash
P=https://argocd.danwils.com
curl -s -o /dev/null -w '%{http_code}\n' -X POST -d '{"username":"admin","password":"x"}' $P/api/v1/session      # 403
curl -s -o /dev/null -w '%{http_code}\n' $P/api/v1/session/userinfo                                             # 200
curl -s -o /dev/null -w '%{http_code}\n' --resolve argocd.local:80:192.168.0.60 \
  -X POST -d '{"username":"admin","password":"x"}' http://argocd.local/api/v1/session                            # 401
```

## Known limits

- **CLI SSO (`argocd login --sso`) is not set up.** It needs a public client with a
  `http://localhost:8085/auth/callback` redirect. Use `argocd login argocd.local` (admin) on the LAN.
- API tokens issued to `admin` would work from the public host too. Don't create any.
- `/api/webhook` is reachable publicly, as with any exposed ArgoCD. No webhook secret is set; it can
  only trigger refreshes.
- Keep ArgoCD current: it runs with cluster-admin, and its unauthenticated surface (login page, API)
  is now on the internet. MFA on accounts in `argocd-admins` matters for the same reason.
## Troubleshooting: login loops back to `/login`

authentik shows the login as authorized and argocd-server logs `Web login successful`, but the session check
fails (`Failed to verify session token ... failed to query provider`). Read the end of that log line:

- `x509: certificate signed by unknown authority`: argocd-server was not restarted after `oidc.config`
  changed (see above).
- `no such host` / IPv6 `network is unreachable`: cluster DNS cannot resolve `auth.danwils.com` over IPv4.
  See `docs/issues/2026_10_10_coredns_stale_upstream_bind.md`.

To reproduce without a browser, send a dummy JWT with authentik's issuer; it forces the same discovery.
A healthy server fails only on the signature (`failed to verify id token signature`):

```bash
b64(){ printf '%s' "$1" | base64 -w0 | tr '+/' '-_' | tr -d '='; }; NOW=$(date +%s)
T="$(b64 '{"alg":"RS256"}').$(b64 "{\"iss\":\"https://auth.danwils.com/application/o/argocd/\",\"aud\":\"argocd\",\"exp\":$((NOW+600))}").c2ln"
curl -s -o /dev/null -H "Cookie: argocd.token=$T" https://argocd.danwils.com/api/v1/session/userinfo
kubectl -n argocd logs deploy/argocd-server --since=30s | grep "verify session"
```

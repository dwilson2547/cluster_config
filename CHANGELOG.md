## 2026-10-11 - nodewright public at nodewright.danwils.com

### Added
- `argocd/nodewright.yaml`: nodewright (chart `helm/nodewright` in `dwilson2547/nodewright`, `main`) into
  namespace `nodewright`. Diagram editor on JSON Canvas; image `dwilson2547/nodewright:0.1.0`. Public on
  pubsecure (letsencrypt-prod, external-dns); everything past health/config/sign-in needs an authentik session.
- `authentik/blueprints/nodewright.yaml` (+ kustomization, `AUTHENTIK_NODEWRIGHT_CLIENT_SECRET` in
  `authentik/values.yaml`): confidential OIDC client `nodewright`, code flow, per-provider issuer, any
  approved user may sign in. Validated with the importer in the worker before pushing.
- `nodewright` role and database on the cluster postgres (namespace `postgres`), owned by `nodewright`,
  `CONNECT` revoked from `PUBLIC`.
- Secrets `nodewright-db`, `nodewright-oidc` (namespace `nodewright`) and `authentik-nodewright-oidc`
  (namespace `authentik`), applied by hand; template in `example-secrets/nodewright/secret.yml`.
- Homepage (Tools) and homepage-public entries.

## 2026-10-10 - scrape-job-manager operator

### Added
- `argocd/scrape-job-manager.yaml`: the scraper operator (chart in `dwilson2547/scrape_job_manager`,
  `main`, `values-prod.yaml`) into namespace `scrape-job-manager`. Installs the cluster-wide CRDs
  `scrapepools` / `scrapers` / `scrapejobs.scrape.danwils.com` and a ClusterRole to create Jobs in any
  namespace. Needs the `repo-scrape-job-manager` repository secret (SSH, same pattern as
  `repo-photo-dump`). No ScrapeJobs yet; the gyopart-dev pilot follows.

## 2026-10-10 - web-tools 1.0.1: OSM tiles blocked

### Fixed
- geojson-editor showed OSM "Access blocked" (403) tiles: the image sent `Referrer-Policy: no-referrer`
  and OSM's tile usage policy rejects requests with no Referer. Now `strict-origin-when-cross-origin`.

## 2026-10-10 - web-tools public at tools.danwils.com

### Added
- `web-tools/` + `argocd/web-tools.yaml`: 13 static browser utilities (source `apps/web-tools` in the
  workspace) in one nginx image `dwilson2547/web-tools:1.0.0`, served at https://tools.danwils.com on
  pubsecure (letsencrypt-prod, external-dns). No auth: the tools are client-side only. No `.local` host,
  because they rely on `navigator.clipboard` / `crypto.subtle`, which need an HTTPS origin.
- Homepage (Tools) and homepage-public (Tools) entries linking to it.

## 2026-10-10 - ArgoCD: restart argocd-server after enabling OIDC

### Fixed
- SSO login looped back to `/login` with `x509: certificate signed by unknown authority`. The session
  manager's OIDC discovery client is built once at startup and trusted only ArgoCD's self-signed
  certificate, because OIDC was not configured then. Restarted argocd-server; `docs/argocd_access.md` and
  `argocd-server/argocd-cm-patch.yaml` now say to restart after any `oidc.config` change, and the doc has
  a troubleshooting section.

## 2026-10-10 - Cluster DNS: CoreDNS restarted to drop stale upstream 192.168.0.30

### Fixed
- `kube-system/coredns` was still forwarding to 192.168.0.30 (from its resolv.conf at pod creation, 136
  days ago), a BIND server with an old `danwils.com` zone that returns NXDOMAIN for `auth.danwils.com`.
  This broke ArgoCD SSO session verification and could intermittently break any in-cluster client of
  `*.danwils.com`. Restarted; see `docs/issues/2026_10_10_coredns_stale_upstream_bind.md`.

## 2026-10-10 - ArgoCD public at argocd.danwils.com, sign-in through authentik

### Added
- `authentik/blueprints/argocd.yaml`: confidential OIDC provider + application `argocd` (client id
  `argocd`, redirects `https://argocd.danwils.com/auth/callback` and `http://argocd.local/auth/callback`),
  groups `argocd-admins` (role:admin) / `argocd-viewers` (role:readonly), application bound to both.
  Client secret from the hand-applied `authentik-argocd-oidc` Secret via `!Env`; ArgoCD reads the same
  value from `argocd-oidc-authentik` (argocd ns, `part-of: argocd` label). Templates in `example-secrets/`.
- `argocd-server/ingress-public.yaml` (applied by hand): `argocd.danwils.com` on pubsecure with
  letsencrypt-prod + external-dns, and a `deny-all` Middleware returning 403 for the password-login
  endpoints (`/api/v1/session`, `/session.SessionService/Create`) on the public host only.
- `argocd-server/argocd-cm-patch.yaml`, `argocd-rbac-cm-patch.yaml` (merge-patched by hand): `url`,
  `additionalUrls`, `oidc.config`, group-to-role mapping.
- `docs/argocd_access.md`: where every piece lives, and how to re-verify the login block after upgrades.
- Public homepage: ArgoCD.

### Changed
- The local `admin` account stays enabled as a LAN-only break-glass login (`argocd.local`).

## 2026-10-10 - Public homepage: GitHub and registry links

### Changed
- `homepage-public`: the single GitHub bookmark is replaced by the internal homepage's link groups:
  GitHub (All Repos, cluster_config) and Registries (Docker Hub, PyPI). gyopart is left out because it
  is not a public service.

## 2026-10-10 - DanWiki public at danwiki.danwils.com, sign-in through authentik

### Added
- `authentik/blueprints/danwiki.yaml`: confidential OIDC provider + application `danwiki` (client id
  `danwiki`, code flow, redirect `https://danwiki.danwils.com/api/auth/oidc/callback`) and groups
  `danwiki-admins` (site admin) / `danwiki-creators` (may create wikis). No policy binding: any approved
  authentik user may sign in; per-wiki roles stay in DanWiki. Client secret from the hand-applied
  `authentik-danwiki-oidc` Secret via `!Env`; the app reads the same value from `danwiki-oidc`
  (danwiki ns). Templates in `example-secrets/`.
- Public homepage: DanWiki.

### Changed
- DanWiki's chart (app repo) now serves only https://danwiki.danwils.com (pubsecure, letsencrypt-prod,
  external-dns) and has no password login. Internal homepage links updated.
- `danwiki-app-secrets` `SECRET_KEY` (hand-applied) was still the template placeholder; rotated, since it
  now signs the OIDC state cookie on a public host.

### Removed
- `dns/dns.yaml`: the `danwiki.local` zone, which no Ingress serves any more.

## 2026-10-10 - Grafana public at grafana.danwils.com, sign-in through authentik

### Added
- `authentik/blueprints/grafana.yaml`: confidential OIDC provider + application `grafana` (client id
  `grafana`, code + refresh grants, redirect `https://grafana.danwils.com/login/generic_oauth`) and
  groups `grafana-admins` / `grafana-editors` / `grafana-viewers`. The application is bound to the three
  groups, so anyone in none of them is refused by authentik. Client secret from the hand-applied
  `authentik-grafana-oidc` Secret via `!Env`; Grafana reads the same value from `grafana-oidc`
  (monitoring ns). Templates in `example-secrets/authentik/` and `example-secrets/monitoring/`.
- Public homepage: Grafana.

### Changed
- `monitoring/helm-values/prometheus-values.yaml`: Grafana `generic_oauth` against authentik, auto
  sign-in, login form disabled, anonymous off, `root_url` https://grafana.danwils.com. Role from groups at
  every sign-in (admins -> GrafanaAdmin, editors -> Editor, viewers -> Viewer), strict. Basic auth left on
  for the API: the datasource sidecar reloads with the chart's admin credentials.
- `monitoring/manifests/ingress.yaml`: Grafana served only at grafana.danwils.com (pubsecure,
  letsencrypt-prod, external-dns). `monitoring.local` and `grafana.scrapestack.local` dropped.
- Internal homepage: Grafana links to grafana.danwils.com.

## 2026-10-10 - photo-dump prod at photo-dump.danwils.com

### Added
- `argocd/photo-dump.yaml`: photo-dump prod from the app repo's `main`, `values-prod.yaml`, namespace
  `photo-dump`. Public (pubsecure, letsencrypt-prod, external-dns). Sign-in only through authentik.
- Prod data starts empty: database + role `photo_dump` on prod `postgres` (role owns the database,
  password from the secret over stdin) and a new private bucket `photo-dump-prod` on the object store
  (192.168.0.15:9768); images reach the browser as presigned links from the API. Hand-applied secrets
  in `photo-dump`: `postgres-photo-dump-creds`, `photo-dump-bucket-creds`, `jwt-photo-dump-creds`,
  `photo-dump-oidc-creds`.
- `authentik/blueprints/photo-dump.yaml`: groups `photo-dump-editors` and `photo-dump-creators` beside
  `photo-dump-admins`; the app sets each user's role from them at every sign-in (Admin / Moderator /
  User, none = Viewer). Prod redirect URI added; dev's kept.
- Public homepage: Photo Dump.

### Changed
- Internal homepage: Photo Dump links to prod; dev entries removed.

### Removed
- `dns/dns.yaml`: the `photo-dump.local` zone, which no Ingress served.

## 2026-10-10 - authentik: photo-dump OIDC application

### Added
- `authentik/blueprints/photo-dump.yaml`: confidential OIDC provider + application `photo-dump`
  (client id `photo-dump`, scopes openid/email/profile, RS256 signed, per-provider issuer
  `https://auth.danwils.com/application/o/photo-dump/`), redirect URI
  `http://photo-dump-dev.local/api/auth/oidc/callback`, and group `photo-dump-admins`. Client secret from
  the hand-applied `authentik-photo-dump-oidc` Secret via `!Env`.

## 2026-10-10 - authentik: Google sign-up with admin approval, mail, real client IPs

### Added
- `authentik/blueprints/` (kustomize ConfigMap, third source of `argocd/authentik.yaml`, mounted via
  `blueprints.configMaps`):
  - `signup.yaml`: Google OAuth source (`/source/oauth/callback/google/`) with "Sign in with Google" on
    the default login page. New Google users go through `danwils-source-enrollment`, which creates them
    **inactive** and ends on a "waiting for approval" page; approve by activating the user. Matching is
    by Google identifier, so no existing account is linked by email.
    Fixed the same day: the pending page was a Deny stage, which aborts the flow before authentik's
    appended PostSourceStage saves the user's Google link, so an approved user could never sign in with
    Google again. It is now an info prompt; the flow completes and the user stays inactive.
  - `notify-new-users.yaml`: every created user notifies the `authentik Admins` group by email and in
    the UI.
- Gmail SMTP (`smtp.gmail.com:587`, TLS). Username, app password and From are in the hand-applied
  `authentik-smtp` Secret (optional; mail is off until it exists). Google client in
  `authentik-google-oauth`. Templates: `example-secrets/authentik/smtp-and-google.yml`.

### Changed
- `AUTHENTIK_LISTEN__TRUSTED_PROXY_CIDRS`: defaults plus Cloudflare's ranges. With only the Traefik
  change, authentik logged the Cloudflare edge IP (104.22.62.62, 172.70.50.41) as the client.

## 2026-10-10 - Real client IPs on the public entrypoints

### Changed
- `traefik/values.yaml`: `traefik-public` (192.168.0.65) uses `externalTrafficPolicy: Local`, and
  `pubweb`/`pubsecure` trust `X-Forwarded-For` from Cloudflare's published ranges only. Before this,
  every public request reached backends with a node IP (192.168.0.35) as its source — measured in
  authentik's request log — so per-IP features (authentik's login reputation) would treat all
  visitors as one. LAN entrypoints unchanged.

## 2026-10-10 - authentik identity provider at auth.danwils.com

### Added
- `authentik/values.yaml`, `argocd/authentik.yaml`: authentik 2026.8.3 (Helm chart), namespace
  `authentik`, public at `auth.danwils.com` (pubsecure, letsencrypt-prod, external-dns). Central
  sign-in for cluster services over OIDC; apps keep their own sessions and permissions.
- Uses the shared `postgres/postgres`: database + role `authentik` created by hand (role password
  from the secret over stdin, role owns the database). No Redis: authentik dropped it in 2025.10.
- `example-secrets/authentik/secret.yml`: `authentik-secrets` (secret key, DB password, bootstrap
  admin). Bootstrap creates `akadmin` on first start so the initial-setup flow is never exposed on
  the public hostname.
- Homepage: Authentik admin link in the Cluster group.

## 2026-10-10 - All ArgoCD Applications centralized; app-of-apps root

### Added
- `bootstrap/apps.yaml`: app-of-apps root `apps` syncing `argocd/` (`selfHeal`, `prune: false`). Adding or
  editing an Application is now a git push; only the root is applied by hand.
- `argocd/scrape-stack.yaml`, `argocd/scrape-stack-dev.yaml`: moved from the scrape_stack repo. All
  Applications now live here; charts stay in their app repos. scrape-stack-dev is unchanged live.
- scrape-stack prod (namespace `scrape-stack`) is deployed for the first time. Empty databases
  `request_auth`, `webcache`, `imgcache`, `filecache`, `vidcache` created on prod `postgres` (services
  create their own tables). Needs the `postgres-credentials` secret in `scrape-stack`. Its user had no
  role on prod postgres (auth failures until created); the role was created from the secret over stdin and
  given ownership of the five databases (PG17: ownership is what grants CREATE on `public`). Verified: all
  10 pods Running, all six `*.scrapestack.local` hosts return 200, gRPC LB on .62.

### Removed
- `argocd/gyopart.yaml`, `argocd/danwiki-dev.yaml`, `argocd/photo-dump.yaml`: never applied, so nothing
  was running; deleted rather than auto-deployed by the root app.

### Changed
- `argocd/ingress.yaml` → `argocd-server/ingress.yaml`. It holds argocd-server's ingress and
  `server.insecure` ConfigMap, not an Application, so it stays out of the root app's path and is still
  applied by hand.

## 2026-10-10 - canvas-viewer published at canvas-viewer.danwils.com

### Added
- `canvas-viewer/deployment.yml`: separate `canvas-viewer-public` Ingress (pubsecure, letsencrypt-prod,
  external-dns label + target `danwils.com`). The `.local` Ingress is unchanged.
- Public homepage: Tools group with Canvas Viewer.

### Fixed
- external-dns v0.23 reads annotations under `external-dns.kubernetes.io/` only (legacy
  `external-dns.alpha.` prefix disabled by default). The alpha target annotation was ignored, the target
  fell back to the Ingress IP .60, and exclude-target-net dropped it, so no record was created and nothing
  was logged. Switched the annotation and the docs (CLAUDE.md, values comment, k8s-argocd skill).

### Changed
- Image 1.0.0 -> 1.1.0: nginx now sends `Content-Security-Policy` (`default-src 'none'`, inline
  script/style only, `connect-src 'self'`, `frame-ancestors 'none'`), `nosniff` and `no-referrer`.
  `connect-src 'self'` stops `?src=` links from loading another origin's content into the viewer.

---

## 2026-10-10 - external-dns for public danwils.com records

### Added
- `argocd/external-dns.yaml` + `external-dns/values.yaml`: external-dns chart 1.23.0 (v0.23.0), Cloudflare
  provider, namespace `external-dns`. Ingress source only, opt-in by label `dns.danwils.com/public=true`,
  domain filter `danwils.com`, records proxied, policy `sync` with TXT registry (owner `home-cluster`,
  prefix `_extdns-%{record_type}.`), private target ranges excluded.
- Token secret `cloudflare-api-token-danwils` in `external-dns`, applied by hand; template in
  `example-secrets/external-dns/secret.yml`.

### Notes
- Replaces the planned agent-run `cf-cname` script: publishing is a git change on the Ingress, and no
  agent holds a Cloudflare token.

---

## 2026-10-10 - Separate public ingress (traefik-public, 192.168.0.65)

### Fixed
- Forwarding WAN 80/443 to Traefik's .60 exposed every internal Ingress to the internet: Traefik
  bound all routers to all entrypoints, so a request to the public IP with `Host: home.cluster.local`
  returned the internal homepage. The router forward was moved to .65 (nothing listening) as soon as
  this was seen.

### Added
- `traefik/values.yaml`: entrypoints `pubweb` (redirects to https) and `pubsecure` (TLS) exposed only on a
  second LoadBalancer Service `traefik-public` pinned to 192.168.0.65. `web`/`websecure` are now
  `asDefault`, so Ingresses that name no entrypoint stay on .60 / LAN only.
- `homepage-public` Ingress opts in with `router.entrypoints: pubsecure`.
- Traefik DaemonSet `updateStrategy` maxSurge 0 / maxUnavailable 1: with hostPorts 80/443 the chart
  default (surge 1) left the first new pod Pending ("didn't have free ports"); any Traefik change would.

---

## 2026-10-10 - Public landing page at danwils.com

### Added
- `homepage-public/` + `argocd/homepage-public.yaml`: a second homepage instance (pinned v2.4.0) at
  `https://danwils.com`, IngressClass `traefik`, TLS from `letsencrypt-prod` (secret `danwils-com-tls`).
- Deliberately bare: no ServiceAccount token, no kubernetes mode, no widgets. Services are added to it
  one at a time as they are made public; the internal homepage (dev instances, .local) stays internal.

### Notes
- Reached via the Cloudflare-proxied `danwils.com` A record (ddclient) → router 80/443 → Traefik 192.168.0.60.

---

## 2026-10-10 - Adopt Traefik and MetalLB into ArgoCD

### Added
- `argocd/traefik.yaml` + `traefik/values.yaml`: Traefik chart 37.4.0 (v3.6.2), release `traefik`,
  namespace `ingress`, values copied unchanged from the microk8s ingress addon's Helm release.
- `argocd/metallb.yaml` + `metallb/`: unmodified upstream `metallb-native` v0.15.2 manifest plus
  `pool.yaml` (IPAddressPool `192.168.0.60-192.168.0.85`, L2Advertisement), via kustomize.
- `Prune=false,Delete=false` on MetalLB CRDs, namespace, pool and L2Advertisement.
- Traefik's IP `192.168.0.60` pinned in `traefik/values.yaml` (`service.annotations`); it had been set by
  a hand-run `kubectl annotate` on 2026-05-10 and existed nowhere in git.

### Notes
- Adopted in place: `kubectl diff` of both renders against the live cluster was empty apart from the
  added Argo annotations, so no pods restarted. First sync manual, then automated.
- Warning added to `CLAUDE.md`: never `microk8s disable ingress|metallb`.

---

## 2026-10-10 - ddclient restarts on secret change

### Changed
- `dns/ddclient.yml`: Reloader annotation for `ddclient-secret`. linuxserver/ddclient reads
  `/defaults/ddclient.conf` only at container start, so a hand-applied secret edit previously sat unused
  (the pod ran 140 days on a config whose token had expired).
- `ddclient-secret` (hand-applied) now updates only `danwils.com`.

---

## 2026-10-10 - cert-manager under ArgoCD

### Added
- `argocd/cert-manager.yaml`: jetstack chart v1.21.2 (values `cert-manager/values.yaml`, CRDs installed
  and kept on delete) plus `cert-manager/issuers/` in one multi-source app, namespace `cert-manager`.
- ClusterIssuers `letsencrypt-staging` and `letsencrypt-prod`: ACME DNS-01 via Cloudflare for
  `danwils.com`. Token secret `cloudflare-api-token-danwils` (key `api-token`; one secret per zone) applied by hand; template in
  `example-secrets/cert-manager/secret.yml`.

### Removed
- The microk8s cert-manager addon and its namespaced `default/letsencrypt` Issuer (HTTP-01) were disabled
  by hand before this; the stale `cert-manager-webhook-ca` secret it left behind was deleted.

### Notes
- Traefik (LB `192.168.0.60`, namespace `ingress`) is the microk8s ingress addon's Helm release
  (chart 37.4.0, Traefik v3.6.2), not managed here. The `public` (default) and `nginx` IngressClasses
  come from that addon.
- `kubernetes/cert manager/` is the legacy, unsynced predecessor; superseded by the above.

---

## 2026-10-10 - Deploy canvas-viewer

### Added
- `canvas-viewer/` (Deployment, Service, Ingress `canvas-viewer.local`) and `argocd/canvas-viewer.yaml`
  (namespace `canvas-viewer`). Image `dwilson2547/canvas-viewer:1.0.0`, built from the workspace's
  `meta/canvas-viewer/Dockerfile` (nginx-unprivileged serving the single `index.html`).
- DNS zone `canvas-viewer.local` → Traefik (192.168.0.60).
- Homepage entry under Tools.

### Notes
- Manifests live here rather than in a project chart: canvas-viewer is a plain folder in the
  workspace repo, not its own repo. Release = rebuild/push a new tag and bump it in `deployment.yml`.

---

## 2026-10-02 - dxf-converter v2: database

### Added
- `dxfconv` role and database on the cluster postgres (namespace `postgres`), owned by `dxfconv`.
- Secret `dxf-converter-db` (namespace `dxf-converter`, key `DATABASE_URL`), applied by hand;
  template added to `example-secrets/dxf-converter/secret.yml`.

### Notes
- Consumed by dxf-converter 2.0.0's chart (`accounts.*` in `helm/dxf-converter/values.yaml`),
  together with `dxf-converter-bucket-credentials`.

---

## 2026-10-02 - dxf-converter v2 bucket credentials template

### Added
- Added `example-secrets/dxf-converter/secret.yml`: template for `dxf-converter-bucket-credentials`
  (namespace `dxf-converter`) with the access/secret key for the `dxf-converter` bucket on AIStor.

### Notes
- AIStor's S3 API is `http://192.168.0.10:30320` (plain HTTP); `:30321` is the web console. Both
  were reachable from a pod in the `dxf-converter` namespace on 2026-10-02.
- Not yet consumed by the chart; dxf-converter v2 (saved scans) will read it.

---

## 2026-09-25 - Deploy dxf-converter and build-sim

### Added
- Added `argocd/dxf-converter.yaml` (chart `helm/dxf-converter` in `dwilson2547/dxf-converter`, namespace `dxf-converter`) and `argocd/build-sim.yaml` (chart `helm/build-sim` in `dwilson2547/drone-build-sim`, namespace `build-sim`).
- Added `dxf-converter.local` and `build-sim.local` zones to `dns/dns.yaml` (apex + wildcard → Traefik at 192.168.0.60).
- Added a `Tools` group to the homepage with both UIs.

### Notes
- Images are public on Docker Hub (`dwilson2547/dxf-converter`, `dwilson2547/build-sim-{backend,frontend}`), `:latest` with `pullPolicy: Always`.
- build-sim keeps its SQLite database on a 1Gi `nfs-dataset` PVC.

---

## 2026-06-20 - Add TimescaleDB service

### Added
- Added `timescaledb/` manifests with a dedicated `timescaledb` namespace, single-replica StatefulSet (`timescale/timescaledb:2.16.1-pg16`), PVC-backed storage on `nfs-dataset`, and internal service on port 5432.
- Added `argocd/timescaledb.yaml` to register TimescaleDB with ArgoCD, including `ignoreDifferences` for StatefulSet `volumeClaimTemplates`.
- Added `example-secrets/timescaledb/secret.yml` template for `timescaledb-credentials`.

### Notes
- TimescaleDB follows the same stateful sync posture as postgres (no automated prune/self-heal in the ArgoCD app spec).

---

## 2026-06-20 - Move kreceiver and mqtt DNS placement to pub-sub

### Changed
- Moved `kreceiver` and `mqtt` DNS records from `db.robo-services.local` to `db.pub-sub.local` in `dns/dns.yaml`.
- Updated `argocd/robo-services.yaml` to disable `receiver` and `mosquitto` in the robo-services Helm release.
- Kept `ntrip` and `registry` records in `db.robo-services.local`.
- Bumped SOA serials for both affected zones.

### Added
- Added `kreceiver` and `mosquitto` manifests directly to `pub-sub/deployment.yml` (ConfigMap, Deployment, and LoadBalancer Services in `pub-sub` namespace).
- Added `example-secrets/pub-sub/kreceiver-secret.yml` as the `pub-sub` namespace template for `kreceiver-secret`.

---

## 2026-06-20 - RTK caster service for base-station corrections

### Added
- Added `rtk-caster/deployment.yml` with a dedicated `rtk-caster` namespace, a lightweight in-cluster NTRIP caster, runtime config map (`BASE1` mountpoint), and a TCP `LoadBalancer` service on `192.168.0.72:2101`.
- Added `rtk2go-relay` deployment in `rtk-caster/deployment.yml` to relay the local `BASE1` stream to RTK2Go as an NTRIP SOURCE client with automatic reconnect.
- Added `argocd/rtk-caster.yaml` so ArgoCD manages the new caster service.
- Added `example-secrets/rtk-caster/secret.yml` template for source/client credentials and RTK2Go relay credentials.
- Added `ntrip.robo-services.local -> 192.168.0.72` to `dns/dns.yaml`.
- Added an "NTRIP Caster" entry under "Robo Services" in `homepage/homepage.yaml`.

### Notes
- The caster expects the base station to push using NTRIP SOURCE auth to mountpoint `BASE1`.
- The RTK2Go relay consumes the local mountpoint and publishes upstream; set `rtk2go_mountpoint` and `rtk2go_source_password` in the secret to activate successful upstream publishing.
- ArgoCD `Application` manifests still require manual apply: `kubectl apply -f argocd/rtk-caster.yaml`.

---

## 2026-05-30 - Registry DNS and homepage entry

### Added
- Added `registry IN A 192.168.0.60` to `db.robo-services.local` zone in `dns/dns.yaml` — routes `registry.robo-services.local` to the Nginx ingress controller
- Added "Robo Services" group to `homepage/homepage.yaml` with a Registry entry pointing at `http://registry.robo-services.local`

---

## 2026-05-27 - playbooks directory and microk8s node runtime failure

### Added
- Created `playbooks/` directory for procedural runbooks; added `playbooks/pods-stuck-container-creating.md` — step-by-step diagnosis and fix for pods stuck in ContainerCreating on k8s-main, covering bad cached manifests, hanging image pulls, and broken containerd

---

## 2026-05-27 - microk8s node runtime failure and postgres NFS fsGroup fix

### Fixed
- Documented recurring microk8s containerd failure on k8s-main (node appears Ready but silently drops all new pods); fix is `microk8s stop && microk8s start` — see [docs/issues/2026_05_27_microk8s_main_node_runtime_failure.md](docs/issues/2026_05_27_microk8s_main_node_runtime_failure.md)
- Added syslog analysis section to microk8s issue doc: root cause for this specific incident was Docker Hub connectivity failures (HTML error responses cached as manifests, then EOF on pulls — 0 bytes read over 12+ min), NOT broken containerd sandbox creation; containerd was creating sandboxes successfully throughout
- Removed `fsGroup: 999` from all four postgres StatefulSets — NFS root_squash prevents kubelet from chowning volumes at pod start, breaking postgres when rescheduled to a new node

---

## 2026-05-25 - Iggy Web UI probe path fix

### Fixed

- Pointed the Iggy Web UI health probes and homepage link at the real `/auth/sign-in` entry route so the pod becomes ready and the ingress can serve traffic again — see [docs/issues/2026_05_25_iggy_web_ui_probe_root_404.md](docs/issues/2026_05_25_iggy_web_ui_probe_root_404.md)

---

## 2026-05-25 - robo-services ArgoCD app and DNS zone

### Added

- Added `argocd/robo-services.yaml` to deploy the external `dwilson2547/robo-services` repo from `helm/robo-services`
- Added `robo-services.local` to `dns/dns.yaml` with an explicit `kreceiver.robo-services.local -> 192.168.0.70` record for the UDP receiver LoadBalancer

### Notes

- `robo-services` follows the same external-repo ArgoCD pattern as `gyopart`: the chart lives in its own repo while `cluster_config` owns the cluster registration and DNS

---

## 2026-05-25 - Pub-sub namespace and Iggy ArgoCD app

### Added

- Added `pub-sub/deployment.yml` with a dedicated `pub-sub` namespace, PVC-backed single-node Iggy deployment, internal Service, and config wiring
- Added `argocd/pub-sub.yaml` so ArgoCD can manage the new pub-sub stack
- Added `example-secrets/pub-sub/secret.yml` as the pre-provisioned template for the Iggy root password

### Notes

- The initial cluster shape keeps Iggy in `cluster_config` as dedicated shared infrastructure under `pub-sub`, while staying small enough to avoid a separate chart for now
- Real `iggy-secret` values are still expected to be created manually before or shortly after the ArgoCD application is applied

---

## 2026-05-25 - Todo Store ingress sync fix

### Fixed

- Corrected the mis-indented backend service ports in `ingress-todo-store` so ArgoCD could create the Todo Store route — see [docs/issues/2026_05_25_todo_store_ingress_port_indentation.md](docs/issues/2026_05_25_todo_store_ingress_port_indentation.md)

---

## 2026-05-25 - Todo Store added to ai-services

### Added

- Added Todo Store API/UI to `ai-services/deployment.yml` with a shared PVC, nginx UI override, and `/api` ingress routing via the existing `ai-services-strip-api-prefix` middleware
- Added `todo.ai-services.local` to the `ai-services.local` DNS zone in `dns/dns.yaml`
- Added Todo Store to the AI Services group in `homepage/homepage.yaml`

---

## 2026-05-24 - Homepage dashboard, gyopart deployment, and cluster.local DNS zone

### Homepage (gethomepage.dev)

Deployed at `home.cluster.local` via `homepage/homepage.yaml`. Full manifest
includes Namespace, ServiceAccount, ClusterRole/Binding (read access to pods,
nodes, namespaces, ingresses, ingressroutes), ConfigMap, Deployment, Service,
and Ingress. All configuration lives in the ConfigMap — edit and push to
update the dashboard without rebuilding any image.

**Groups configured**

| Group | Services |
|-------|----------|
| Gyopart | UI, API docs, Admin |
| Gyopart Dev | UI, API docs, Admin |
| Scrape Stack | Cache Browser, Auth, Webcache/Imgcache/Vidcache/Filecache APIs |
| Scrape Stack Dev | Same, on scrapestack-dev.local |
| AI Services | AI Notes, AI Playbooks |
| Cluster | ArgoCD, Grafana, SearXNG |
| Infrastructure | Router (192.168.0.1), TrueNAS SSD (192.168.0.10), Unraid (192.168.0.15), HPC (192.168.0.50) |

**Bookmarks:** GitHub (gyopart, cluster_config, all repos), Docker Hub, PyPI.

ArgoCD app applied manually: `kubectl apply -f argocd/homepage.yaml`

### cluster.local DNS zone

Added `cluster.local` as the central zone for cluster-wide services not tied
to a specific stack. Wildcard `* IN A 192.168.0.60` means any new subdomain
resolves to Traefik without a further DNS update. Also added a wildcard to
`monitoring.local` for the same reason.

### gyopart ArgoCD applications

Added `argocd/gyopart.yaml` (namespace: `gyopart`, targetRevision: `main`) and
`argocd/gyopart-dev.yaml` (namespace: `gyopart-dev`, targetRevision: `dev`).
Both point at `https://github.com/dwilson2547/gyopart.git` (public repo, HTTPS).
Applied manually — these are not auto-discovered from the folder.

Added DNS zones `gyopart.local` and `gyopart-dev.local` (both wildcard → Traefik).

### ai-services ingress (StripPrefix fix)

Added Traefik `StripPrefix` middleware for the `/api` path on ai-notes and
ai-playbooks ingresses. Without it, the prefix was forwarded to the upstream
FastAPI service and all `/api/*` routes returned 404.

---

## 2026-05-24 - Onboard remaining services to ArgoCD

Added ArgoCD applications for dns, monitoring, and postgres. Also added
searxng and vpn (committed separately earlier in the session).

**Applications added**

| App | Path | Sync |
|-----|------|------|
| searxng | `searxng/` | Automated (prune + selfHeal) |
| vpn | `vpn/` | Automated (prune + selfHeal) |
| dns | `dns/` | Automated (prune + selfHeal) |
| monitoring | `monitoring/` | Automated (prune + selfHeal) |
| postgres | `postgres/` | **Manual** — live data, no automated reconciliation |

**Structure decisions**

- ddclient merged into `dns/` — both services share the `dns` namespace;
  a single app avoids two apps competing over the same Namespace resource
- `monitoring/helm-values/` subdirectory holds Loki and Tempo Helm install
  reference values; ArgoCD does not recurse into subdirectories so these
  are excluded from sync automatically
- Postgres app uses `ignoreDifferences` on `StatefulSet/spec/volumeClaimTemplates`
  to prevent ArgoCD from flagging the immutable field as drift

**Secret handling**

All services follow the public-repo pattern: real secrets are pre-provisioned
manually with `kubectl apply` and are never committed. `example-secrets/<service>/secret.yml`
files serve as templates. `.gitignore` covers `**/secret.yml` (with negation
for `example-secrets/`), `**/example_secret.yml`, `**/.claude/`, `*.log`,
and `**/init-*.sql`.

**searxng migration note**

Original deployment used `search.danwils.com` with TLS via cert-manager and
`storageClassName: nfs-crucial`. Migrated to `search.local` (insecure, ingress
only), `nfs-dataset` storage class to match cluster default. Old resources
were manually deleted before sync due to immutable PVC storageClassName.

---

## 2026-05-22 - ArgoCD installation and ingress

Installed ArgoCD into the cluster and exposed the web UI at `argocd.local`.

**Installation**

```bash
kubectl create namespace argocd
kubectl apply -n argocd --server-side --force-conflicts -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
```

**Configuration**

- Added `cluster/argocd/ingress.yaml`:
  - `argocd-cmd-params-cm` ConfigMap sets `server.insecure: "true"` so argocd-server serves plain HTTP
  - Ingress routes `argocd.local` → `argocd-server:80` via Traefik (`ingressClassName: nginx`)

**DNS**

- Updated `cluster/dns/dns.yaml` to incorporate the previously applied `coredns-patch-add-dev-zones.yaml` (patch file no longer needed)
- Added `argocd.local` zone to CoreDNS pointing apex `A` record at Traefik (`192.168.0.60`)

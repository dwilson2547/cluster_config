# Home Platform Week — AI-Assisted Engineering Session Showcase
**October 2026 (Fri 10-09 → Wed 10-14) · Claude Code (Claude Opus)**

---

## What Is This?

Six days of AI-pair-programmed work across a self-hosted Kubernetes homelab (microk8s, ArgoCD,
Traefik, cert-manager, authentik) and the applications that run on it. Over the week the cluster
gained a public edge at `danwils.com` with single sign-on through authentik (Google sign-in with
admin approval). On top of it ran a rewritten photo app, two new MCP-enabled collaboration apps
built from nothing (nodewright, webdoc), and a Kubernetes operator that schedules a fleet of web
scrapers. The **gyopart** auto-parts platform got a redesigned UI, a VIN resolver, an OEM catalogue
updater across 17 manufacturer sites, and 19 junkyard inventory scrapers live in production. A
6-brand motorcycle parts catalogue fleet followed the same pattern.

**By the numbers (from git, private projects excluded):**

| Metric | Count |
|---|---|
| Commits | ~415 across 13 repositories (incl. 94 superrepo submodule bumps) |
| New apps taken from design doc to production | 3 (scrape-job-manager operator, nodewright, webdoc) |
| Tagged app releases | nodewright 0.1 → 0.22, webdoc 0.1 → 0.6, gyopart 3.0.0 → 3.0.2, dxf-converter 3.0.0/3.0.1, sjm chart 0.6.0 |
| Apps moved behind authentik SSO | photo-dump, DanWiki, Grafana, ArgoCD, dxf-converter, nodewright, webdoc |
| Scrapers live in prod under the operator | 19 junkyard + 1 parts-direct updater (16→17 OEM sites) + 6 motorcycle OEMs |

> This showcase was put together from the git history of each repository and the project docs
> (`RELEASES.md`, issue files, changelogs), not from a single transcript. Each **Goal** says what
> the work was for. It is not a quote of the original request.

---

## What Was Already in Place at Session Start

- microk8s cluster with ArgoCD managing some (not all) workloads; LAN-only `*.local` ingresses
- photo-dump v2 running on the LAN with password login
- gyopart (auto-parts interchange + junkyard inventory) running in dev, with ~24 junkyard scrapers
  written but run by hand or cron, not under any scheduler
- scrape-stack shared services (webcache, imgcache, request-auth rate limiter, browserless)
- `scrape-job-manager` was a Flask stub; nodewright and webdoc did not exist

---

## Task 1 — Public Edge, Certificates and GitOps Consolidation (Fri night → Sat)

**Goal:** Put selected services on the internet at `danwils.com` safely and move every Argo app
under one root.

**What happened:**
- cert-manager brought under ArgoCD with Cloudflare DNS-01 ClusterIssuers (per-zone token secret);
  ddclient restarts on secret change via Reloader
- Traefik and MetalLB (previously microk8s addon installs) adopted into ArgoCD: manual first sync,
  then automated sync. Public and internal entrypoints were split.
- external-dns now creates Cloudflare records only for Ingresses that opt in with a label
- Every ArgoCD `Application` was moved into `cluster-config/argocd/` behind an **app-of-apps root**.
  The `k8s-argocd` skill was updated to match.
- Public landing page (second homepage instance) at `danwils.com`; `canvas-viewer` and a new
  `web-tools` site (static browser utilities moved in from another repo) went public
- Edge protection layers documented in `docs/public_edge_protection.md`
- Debugged an ArgoCD SSO redirect loop down to a stale CoreDNS upstream. That led to a router DHCP
  change and decommissioning the old BIND VM. Written up as an issue doc.

**Outcome:** A GitOps-managed public edge with automatic TLS and DNS, and one ArgoCD root for every
workload.

---

## Task 2 — authentik SSO with Google Sign-In (Sat)

**Goal:** Use one identity provider for every public app, with Google OAuth sign-in and new
sign-ups held for approval.

**What happened:**
- Deployed authentik at `auth.danwils.com` using blueprints. A Google source was added, new Google
  sign-ups land in a pending-approval state, and admins get an email.
- Worked through blueprint gotchas: the notification rule field is `destination_group`, the
  pending-approval page must not abort the flow, and the external user type is set explicitly.
  Traefik was fixed to pass real client IPs. Recorded in `docs/authentik_patterns.md`.
- OIDC clients in one afternoon for **photo-dump, Grafana, DanWiki, ArgoCD** (public UI with
  LAN-only admin login), and **dxf-converter**. nodewright and webdoc were added later in the week.
- dxf-converter 3.0.0 dropped password login for OIDC and went public, then 3.0.1 added
  per-visitor upload/convert limits. DanWiki reaches authentik over the LAN using `hostAliases`.

**Outcome:** Seven apps sign in through one authentik instance with Google OAuth and approval-gated
sign-up.

---

## Task 3 — photo-dump v3: Prod Cut-over and UI Rework (Sat)

**Goal:** Ship the photo-dump rewrite to production behind authentik, then fix what first real use
turned up and rework the layout.

**What happened:**
- OIDC-only sign-in, with roles mapped from authentik groups and signed image links. The prod Argo
  app was deployed, dev was scaled to zero, and the seeded default user was removed.
- Fixed a prod upload crash: piexif returns a non-dict thumbnail entry for some EXIF. Uploads now
  report failures per file and always finish the batch.
- Bug pass: the viewer's Close button now works, zoom follows the pointer in the viewer and editor,
  the colour picker reads the right pixel, tag-only edits save, and timestamps default to insert
  time
- **Five-step layout rework, each step shipped to prod the same hour:**
  1. App bar with a left navigation drawer and a right activity drawer
  2. Uploads start from the app-bar picker, and every app message lands in the activity history
     (toasts were removed)
  3. Selection mode with a floating action bar, bulk delete that also removes bucket objects, and
     drag-and-drop upload
  4. Full-screen photo viewer with an info panel, and the editor as a full page
  5. Dark mode (System/Light/Dark), plus a drawer restyle with chip filters
- Each step went dev → merge → prod image `20261010-HHMM`. That makes 10 prod deploys in one day.

**Outcome:** photo-dump runs in prod at `photo-dump.danwils.com` with SSO and a fully reworked UI.

---

## Task 4 — scrape-job-manager: A Kubernetes Operator for Scrapers (Sat → Mon)

**Goal:** Replace the Flask stub with a real scheduler, so dozens of scrapers run on pooled,
rate-aware schedules with health checks.

**What happened:**
- Design: pool-balanced scheduling, a global run limit, active hours, and no proxy sidecar
- **Phase 1:** `Scraper` and pool CRDs, a pool planner, a reconcile tick, and a Job builder. It was
  verified on `kind`, then deployed with trunk-flow CI (tests and image on PR, publish on main,
  Helm OCI). The base image was pinned to Python 3.12 because the microk8s CA fails 3.13's stricter
  X.509 checks.
- **Phase 2a–c:** result health checks, staleness, retest, dry-run, and Prometheus metrics. Added
  a batched state-change email and a weekly digest, plus Postgres run history, capacity checks and
  missed-run events.
- `SCRAPE_DEADLINE` is injected into every run so long jobs stop gracefully before the Job kill.
  Suspended jobs hold their retries, and run-now replaces a held retry.
- **Phase 3 UI:** a dashboard over CR status and history with recovery buttons, at `sjm.local`
- `Scraper.sidecars` (chart 0.6.0) runs a browser beside the scraper for each run as a native
  sidecar. Prod concurrency was raised 3 → 6 → 10 as the fleet grew.

**Outcome:** A production operator now schedules every scraper in the workspace. It does health
checks, history, alerting and graceful deadlines.

---

## Task 5 — gyopart: Parts-Direct Updater v2 (Sun → Wed)

**Goal:** Keep the OEM parts catalogue current from the manufacturers' parts-direct storefronts
without fragile all-night crawls.

**What happened:**
- Investigated a Mopar load that cached 503 pages and marked 3,492 vehicles done. The cause was the
  site's midnight maintenance window. `CachedParser` now rejects maintenance and challenge pages.
- Redesigned the updater: the DB holds the state (a `scrape_target` work queue with leases), one
  browser session per run, 180-day refresh and 90-day discovery, VPN routing, and one ScrapeJob per
  manufacturer
- parts_interchange got an Alembic baseline and upsert keys (0.3.0), and writes are transactional
  per vehicle
- Hardening: the VPN gate compares exit IPs, Cloudflare blocks are told apart from transient
  challenges, the parser reads the 2026 storefront's React-island props, images download through a
  background queue with request-auth permits, and browserless runs a session per run as a sidecar
  with tab recycling and crash recovery
- Handled aftermarket-only vehicles, script redirects and mid-vehicle deadline stops. **Alfa Romeo**
  was onboarded as a 17th site.
- Live in prod across 16 manufacturer sites from 10-11 (Alfa added 10-13)

**Outcome:** A queue-driven, resumable OEM catalogue updater running nightly in prod.

---

## Task 6 — gyopart: 19 Junkyard Scrapers Live in Prod (Sat → Tue)

**Goal:** Move the junkyard inventory scrapers onto the operator and into production.

**What happened:**
- Pilot of three scrapers in dev (Pic-N-Pull, Parts Galore, Ryan's). Fixes: Pic-N-Pull drops only
  placeholder VINs and keeps real pre-1981 short VINs, and Ryan's upserts additively because its
  feed lists recent arrivals, not the whole yard.
- US Auto Supply went to a daily pool and the rest to a weekly pool. First prod runs: Pic-N-Pull
  12,725 vehicles, US Auto 1,092, Parts Galore 1,063.
- Moved the other 20 scrapers onto `scrape_contract`, then fixed them for 2026 site changes: four
  IIS Pro sites, Pick-N-Pull San Antonio, Fenix location cookie, honest User-Agents, and
  time-boxing Pull-A-Part's detail phase with `SCRAPE_DEADLINE`
- Rolled out in batches over 10-12 and 10-13 until **19 yard scrapers** were in `values-prod.yaml`
- Scraper images are pinned by digest, with a script that re-pins them after a push

**Outcome:** 19 junkyard inventories are scraped on schedule in prod and feed the interchange
search.

---

## Task 7 — gyopart: VIN Resolver and UI 3.0 (Sun → Mon)

**Goal:** Let a user go from "my car" to "this part, in this yard" in one flow.

**What happened:**
- Live VIN resolver: a worker that uses vehicles as its queue, pulls full NHTSA records, and
  matches candidate cars. It handles loose model names, refuses cross-year matches, and requeues
  discrepancies. Deployed dev → prod.
- Interchange search was changed to POST car ids, which removed the 100-id cap. Results now carry
  the match, VIN and arrival date.
- **UI redesign in seven approved workflows**, each with its API: Garage and VIN decode, find a part
  on my vehicle (catalogue tree, diagram and search), confirm the part, interchange chart, find it
  in a yard, part-number lookup from the top bar, and browse a yard
- Released 3.0.0 → 3.0.2 to dev, then promoted 3.0.2 to prod and verified it there

**Outcome:** gyopart 3.0.2 is in prod with the full workflow from car to part to yard.

---

## Task 8 — nodewright: JSON Canvas Editor + MCP, 0.1 → 0.22 in Three Days (Sat → Mon)

**Goal:** A diagram editor that both people and AI agents can edit live, on the JSON Canvas format.

**What happened:**
- Day 1: design, a FastAPI backend with OIDC and revisioned saves, and a React Flow editor with
  tabs, autosave and conflict handling. Phase 2 added the MCP server, access tokens, edit leases and
  live events, then MCP OAuth browser sign-in. Shipped 0.7.0 with node shapes, edge styles,
  templates, cross-tab links, attachments in object storage, edge routing around nodes,
  `render_canvas` through headless Chromium, folders, share links, Alembic and CI.
- Day 2: workspace members, zip export, edge corner radius, node ports, a Lucide icon set with SVG
  upload, an icon creator, schema nodes (Avro, Protobuf, JSON, YAML, SQL), and version history. Also
  **electrical schematic symbols** with wiring routed together, hops at crossings and colour by net.
- Day 3: manual edge waypoints. Organisations and roles were built (0.20–0.21) and then removed
  (0.22) to match webdoc's simpler model.

**Outcome:** nodewright 0.22.0 is live at `nodewright.danwils.com`. The diagrams in this kind of
write-up can now be drawn by an agent through its MCP server.

---

## Task 9 — webdoc: Shared Knowledge Base + MCP, 0.1 → 0.6 (Sun → Mon)

**Goal:** nodewright's sibling for markdown notes and documents, built for agents to read and write.

**What happened:**
- Design (domains, roles, attributed history, trash), then six phases in two days:
  1. Domains, documents, history and the MCP server (0.1.0 live at `webdoc.danwils.com` on the
     pgvector Postgres)
  2. Document types and a proposal queue
  3. Semantic search, literal find and an activity feed
  4. Edit leases, live updates and share links
  5. Public contribution domains with drafts and moderation
  6. Viewers by default, and reports on personal documents. Orgs were dropped.

**Outcome:** webdoc 0.6.0 is live with OAuth MCP and is in daily use by agents.

---

## Task 10 — Motorcycle Parts Catalogue Fleet (Mon → Tue)

**Goal:** Build a reference catalogue of OEM motorcycle parts from six manufacturers.

**What happened:**
- Shared `motorcycle_parts` schema in `motorcycle_common/`. Each OEM was brought onto the operator
  dev-first, verified with a 5-minute timeout, then promoted to prod with an 8-hour timeout.
- **Kawasaki** and **Harley** (ARI PartStream API) needed no browser. **Yamaha** got anonymous API
  token auth and skips years with no parts data. **Aprilia** got reCAPTCHA-gate detection and
  1 request / 15 s pacing. **Suzuki** passes a Cloudflare managed challenge with a stealth browser
  and handles diagram inserts from concurrent runs safely.
- **Ducati** had no PDFs. Parts come from the text layer in Issuu's per-page SVG renders, across
  ~70k pages in 598 catalogues, without OCR.

**Outcome:** All six OEM scrapers are live in prod and write one shared catalogue.

---

## Task 11 — Shared Scraping Infrastructure (throughout)

- **scrape-stack:** browserless pinned to v2 (2.57.0) with a memory limit. webcache got per-bucket
  retention (`max_entries` / `max_total_bytes`) with automatic eviction. Fixed a **prod crash
  loop**: SQLAlchemy 2.1 changed the default psycopg dialect, so it is pinned below 2.1 and every
  Python service dependency across the stack now has an upper bound.
- **nordvpn-proxy:** recovers from dead servers, uses a healthcheck that really detects a down
  tunnel, routes replies to the pod network outside the tunnel, and uses explicit resolvers
- **rockauto:** `rockauto_revival`, a full-catalogue crawler built from recon data (static HTML),
  caching into its own webcache bucket
- **Scuderia:** a feasibility study for a reproducible way to collect the OE catalogue on the
  verified Browserless runtime, and a fleet design

---

## Summary of Infrastructure Built

| Component | Technology | Notes |
|---|---|---|
| Public edge | Traefik, MetalLB, cert-manager (DNS-01), external-dns, Cloudflare | Opt-in public Ingresses; ArgoCD-managed |
| GitOps root | ArgoCD app-of-apps | Every Application in `cluster-config/argocd/` |
| Identity | authentik + Google source | Approval-gated sign-up; 7 OIDC clients |
| photo-dump v3 | FastAPI, React, object storage | Prod with SSO; 5-step UI rework |
| scrape-job-manager | Python operator, CRDs, Postgres, Helm | Pools, health, digest email, UI, sidecars |
| gyopart 3.0 | FastAPI, React, Postgres, NHTSA | VIN resolver, 7-workflow UI, interchange search |
| Parts-direct updater v2 | Playwright over CDP, browserless sidecar | Lease queue; 17 OEM sites |
| Junkyard fleet | 19 scrapers on `scrape_contract` | Daily and weekly pools |
| Motorcycle fleet | 6 OEM scrapers, shared schema | Includes an Issuu SVG text-layer parser |
| nodewright | FastAPI, React Flow, MCP + OAuth, headless Chromium | 22 releases in 3 days |
| webdoc | FastAPI, pgvector, MCP + OAuth | 6 phases in 2 days |

## Commits in This Period

About 415 commits, which is too many to list one per row. Each range below can be reproduced with
`git -C <repo> log --since=2026-10-09`.

| Repository | Commits | First → last |
|---|---:|---|
| `automotive/gyopart` | 105 | `fe475a0` → `585f612` |
| `infra/cluster-config` | 85 | `d45d6c6` → `6b37087` |
| `media/photo-dump` | 53 | `fdfd1cf` → `4234472` |
| `web-scrapers/scrape-job-manager` | 46 | `b90dbf0` → `b8ddb4d` |
| `apps/nodewright` | 46 | `4345dba` → `5c60f7a` |
| `apps/webdoc` | 18 | `7000b99` → `736b888` |
| `web-scrapers/scrape-stack` | 11 | `7f1a037` → `fd79202` |
| `meta/SKILLS` | 4 | `a9dae11` → `1767f7d` |
| `ai/dan-wiki` | 4 | `7d61687` → `6f6734d` |
| `tools/dxf-converter` | 3 | `ddc6033` → `a8a3c95` |
| `automotive/rockauto` | 2 | `6f9525f` → `21970c2` |
| `tools/nordvpn-proxy` | 1 | `5ac51f1` |
| workspace superrepo (incl. motorcycles, web-tools, canvas-viewer) | 131 | `6f73dab` → `54523bd` |

---

*Document generated 2026-10-14. Repositories: `dwilson2547/*` workspace superrepo and submodules.*

# Photo Dump — AI-Assisted Engineering Session Showcase
**May 2026 · GitHub Copilot CLI (Claude Sonnet 4.6)**

---

## What Is This?

`photo_dump` is a personal photo-sharing application built on Flask/CherryPy (Python), Angular, and MinIO-compatible object storage. This session resurrected the project after a period of dormancy: migrating the backend from MySQL + MongoDB to PostgreSQL-only, overhauling authentication from cookie-based JWTs to header-based bearer tokens, packaging the app as a Helm chart for ArgoCD, and iterating through a full live deployment on the home Kubernetes cluster until uploads, authentication, and image rendering were all working end-to-end.

---

## What Was Already in Place at Session Start

- `photo_dump` repo existed but was unmaintained — targeting MySQL for the relational DB and MongoDB for EXIF/metadata storage
- Auth used `flask-jwt-extended` in cookie mode with XSRF protection wired into Angular
- Frontend was Angular with no token service; relied entirely on cookies
- Old release scripts used direct `kubectl apply` rather than Helm/ArgoCD
- A legacy object store (MinIO, `192.168.0.15:9768`) with existing bucket credentials was still reachable
- `cluster_config` had established patterns for Postgres init SQL files, ArgoCD app manifests, DNS zones, and Stakater Reloader

---

## Task 1 — Project Archaeology and Migration Planning

**Request:** *"This is photo dump, it's an old project of mine that I'd like to resurrect and bring back online with a little help from Helm and ArgoCD. We'll need to convert the project over to use Postgres instead of MySQL and I need to get the new bucket set up for it. Also I'd like to review the API/UI and see about changing the auth."*

**What happened:**
- Inspected the `photo_dump` repo and `cluster_config/CLAUDE.md` to understand current state and cluster conventions
- Found the backend used Flask/CherryPy + SQLAlchemy + MySQL + MongoDB + MinIO, with Angular on the frontend using cookie auth
- Asked one clarifying question: keep MongoDB or fold metadata/EXIF into Postgres — user chose Postgres-only
- Created a session migration plan and ingested it into the AI Playbooks server as `photo-dump/resurrection-migration`

**Outcome:** Migration scope was defined and a playbook was established as the source of truth for the work ahead.

---

## Task 2 — Backend and Frontend Migration

**Request:** *Convert the app to PostgreSQL, remove Mongo, and switch auth to header-based bearer tokens.*

**What happened:**
- **Backend:** Switched SQLAlchemy DSN to `psycopg2`; removed MongoDB initialization and runtime code entirely; deleted `mongodb_connector.py`; added `metadata_json` and `exif_json` JSONB columns to the `Image` model; reworked `/auth/login` and `/auth/register` to return bearer tokens; removed cookie refresh/unset behavior
- **Frontend:** Created `TokenService` backed by `localStorage`; updated `AuthInterceptor` to attach `Authorization: Bearer <token>` headers; removed cookie/XSRF wiring from `AppModule`; updated login/register components to persist the token from API responses
- **Deployment:** Added `helm/photo-dump/` chart with API/UI Deployments, Services, Ingress, `values.yaml`, `values-dev.yaml`, and `example-secret.yaml`; added `cluster_config/argocd/photo-dump.yaml` and `photo-dump-dev.yaml`; retired old direct-`kubectl apply` release scripts
- Ran `python -m compileall`, Angular build, and `helm template` to validate before deployment

**Outcome:** Full stack compiles and templates successfully with all MySQL/Mongo references removed.

---

## Task 3 — Root Docker Compose for Local Build and Push

**Request:** *"I'd like a root Docker Compose file to build and push all services from one location."*

**What happened:**
- Added root `docker-compose.yml` with `postgres:16`, `minio/minio`, API build/image service, and UI build/image service
- Updated the UI Dockerfile to a proper multistage build so the image no longer required a pre-built `dist/` directory
- Updated `photo-dump-ui/default.conf` to proxy `/api` to the backend
- Brought the stack up and hit runtime failures:
  - Marshmallow `UserSchema` and `TagSchema` had implicit field-name lookups that broke on startup — rewrote both with explicit field declarations
  - Fixed several old `filter(id == ...)` query expressions that were comparing against column objects instead of values
- Added `.env.example`, root `README.md`, and `.gitignore` to exclude local compose artifacts

**Outcome:** `docker compose up` produced a healthy local stack with UI reachable on `:8080` and API on `:8081`.

---

## Task 4 — Cluster Resource Provisioning

**Request:** *"Review `cluster_config/postgres` and initialize Photo Dump on dev Postgres, publish secrets, and set up ArgoCD for the private repo using SSH."*

**What happened:**
- Reviewed the cluster Postgres init pattern: checked-in SQL files (`init-*.sql`) run manually against `postgres-dev` as superuser; app secrets are created manually in-cluster — never committed
- Found and decoded legacy bucket credentials from `cluster_config/kubernetes/photo-dump/secret.yml`, confirmed the old MinIO endpoint was still live
- Added `cluster_config/postgres/init-photo-dump-dev.sql` using a `psql -v photo_dump_dev_password=...` variable so no password was committed
- Created namespace `photo-dump-dev` and provisioned three secrets manually in-cluster: Postgres creds, bucket creds, JWT secret
- Created DB role `photo_dump_dev` and database `photo_dump` on `postgres-dev`
- Created bucket `photo-dump-dev` on the legacy object store
- Switched ArgoCD app manifests to SSH repo URLs (`git@github.com:dwilson2547/photo_dump.git`) since the repo is private; created ArgoCD repo secret `repo-photo-dump` by cloning the existing `repo-cluster-config` SSH secret pattern

**Outcome:** All cluster-side prerequisites in place: namespace, secrets, DB, bucket, and ArgoCD repo access.

---

## Task 5 — First Deployment and Nginx Upstream Fix

**Request:** *"Push Photo Dump up and publish the dev manifest, unless images have to be built first."*

**What happened:**
- Found Helm dev values still had placeholder image tags — built and pushed dev images via root compose before pushing anything
- Set real dev image tags in `values-dev.yaml`, pushed `photo_dump/dev` branch, pushed `cluster_config/main`, and applied the `photo-dump-dev` ArgoCD Application
- First deploy landed with API healthy, but UI pods crashed in Kubernetes: nginx upstream was hardcoded to `proxy_pass http://api:8080/api` — valid in compose (where the API service is named `api`), invalid in Kubernetes (where it is `photo-dump-api`)
- Fixed `default.conf` to use `${API_HOST}` with nginx template rendering; updated `Dockerfile` to place the template in `/etc/nginx/templates/`; set `API_HOST=api` in compose and `API_HOST=photo-dump-api` in the Helm UI deployment
- Rebuilt/pushed UI image (`dev-20260525-2308`), pushed `photo_dump/dev`, and confirmed ArgoCD reached `Synced / Healthy`

**Outcome:** `photo-dump-dev` was live and healthy in ArgoCD with both API and UI running.

---

## Task 6 — DNS and Reloader Fix

**Request:** *"Add `photo-dump-dev.local` DNS and push it to `cluster_config`."*

**What happened:**
- Updated `cluster_config/dns/dns.yaml`: added a CoreDNS zone block, a `db.photo-dump-dev.local` zone file stanza, and wildcard/apex A records pointing at Traefik (`192.168.0.60`); bumped the serial to `2026052601`
- Committed and pushed `cluster_config/main` (commit `02c6cba`)
- User then reported DNS auto-reload did not work and had to manually kill CoreDNS pods
- Inspected Stakater Reloader: found it was installed with `watchGlobally: false`, meaning it only watched its own `reloader` namespace and ignored the `dns` namespace entirely
- Updated `cluster_config/argocd/reloader.yaml` to `watchGlobally: true`, pushed to `cluster_config/main` (commit `656af21`), manually re-applied the ArgoCD reloader app manifest to pick up the change
- Verified reloader logs now confirmed: *"KUBERNETES_NAMESPACE is unset, will detect changes in all namespaces"*

**Outcome:** `photo-dump-dev.local` DNS was live; Stakater Reloader was fixed to watch all namespaces cluster-wide going forward.

---

## Task 7 — JWT Subject Regression Fix

**Request:** *"I'm seeing `GET /api/auth/check 422` and `GET /api/space-browser/spaces 422` in the browser console."*

**What happened:**
- Reproduced the 422 response live against the dev cluster: login succeeded and returned a token, but every subsequent authenticated or optional-auth request returned `{"msg":"Subject must be a string"}`
- Root cause: `create_access_token(identity={'id': user.id, 'version': user.version})` was passing a dict as the JWT `sub` claim; the deployed `flask-jwt-extended` version rejected anything that wasn't a string
- Fixed: changed to `identity=str(user.id)` with `additional_claims={'version': user.version}`; updated `load_user()` to parse the string identity and read `version` from JWT claims
- Built/pushed new API image, updated `values-dev.yaml`, pushed `photo_dump/dev` — commit `5740e5a`

**Outcome:** Authenticated endpoints returned expected responses; user confirmed the app was working.

---

## Task 8 — EXIF Null-Byte Upload Fix

**Request:** *"Photo uploads are failing with `PUT /api/photos/upload/<id> 500`."*

**What happened:**
- Checked live pod logs: bucket credentials were fine; the error was in PostgreSQL: `psycopg2.errors.UntranslatableCharacter`
- Found that EXIF data from some images contained `\u0000` null bytes, which PostgreSQL JSONB storage rejects
- Added recursive `sanitize_json_value()` to `pd_api/photos.py` that strips null bytes from any string value before EXIF data is assigned to JSONB columns
- Built/pushed new API image, updated `values-dev.yaml`, pushed `photo_dump/dev` — commit `475c258`
- Created issue doc `docs/issues/2026_05_25_exif_null_bytes_break_uploads.md` — commit `d81e179`
- Ingested into playbooks as `photo-dump/issues/exif-null-bytes-break-uploads` and created note `118`

**Outcome:** Upload errors resolved; images were stored successfully.

---

## Task 9 — Image Rendering Fix (Missing Bucket Proxy)

**Request:** *"Uploads work now, but images don't render — the image URL returns 200 with an empty response."*

**What happened:**
- Traced the image URL pattern: the Angular app constructed same-origin URLs like `/<bucket>/<object>` for thumbnails
- In the cluster, these requests hit the UI nginx, which only had a proxy for `/api`; everything else fell through to `index.html` — producing a 200 with HTML content instead of image bytes
- Confirmed the objects were intact and retrievable directly from MinIO, confirming the issue was routing only
- Added a bucket proxy route to `photo-dump-ui/default.conf`, wired `BUCKET_NAME` and `BUCKET_URL` as environment variables into the UI container via Helm and Docker Compose
- Built/pushed new UI image, updated `values-dev.yaml`, pushed `photo_dump/dev` — commit `7b9381f`
- Created issue doc `docs/issues/2026_05_26_missing_bucket_proxy_breaks_image_rendering.md` — commit `f29c116`
- Ingested into playbooks as `photo-dump/issues/missing-bucket-proxy-breaks-image-rendering` and created note `120`; updated migration playbook to include all three post-rollout regressions

**Outcome:** Thumbnails and full images rendered correctly in the UI.

---

## Summary of Infrastructure Built

| Component | Technology | Notes |
|---|---|---|
| API | Flask/CherryPy + SQLAlchemy + Python | Migrated to PostgreSQL; bearer token auth |
| UI | Angular + nginx | Multistage Docker build; templated nginx upstream and bucket proxy |
| Database | PostgreSQL (`postgres-dev`) | New role/DB; init SQL in `cluster_config/postgres/` |
| Object Storage | MinIO (legacy `192.168.0.15:9768`) | Reused existing endpoint; new `photo-dump-dev` bucket |
| Helm Chart | `helm/photo-dump/` | API + UI deployments, services, ingress, secrets |
| ArgoCD Application | `photo-dump-dev.yaml` | SSH repo access via `repo-photo-dump` secret |
| DNS | CoreDNS (`cluster_config/dns/dns.yaml`) | `photo-dump-dev.local` zone pointing at Traefik |
| Cluster Autoreload | Stakater Reloader | Fixed `watchGlobally: false` → `true` |
| Local Dev Stack | Docker Compose | Root compose for build/push/local iteration |

## Commits in This Session

| Hash | Description |
|---|---|
| `02c6cba` | Add photo-dump-dev.local DNS zone |
| `656af21` | Fix Stakater Reloader to watchGlobally |
| `5740e5a` | Fix Photo Dump JWT subject |
| `475c258` | Sanitize Photo Dump EXIF JSON |
| `d81e179` | Document EXIF upload issue |
| `7b9381f` | Proxy Photo Dump bucket paths |
| `f29c116` | Document Photo Dump image proxy issue |

---

*Document generated 2026-05-28. Repository: `dwilson2547/photo_dump` · `dwilson2547/cluster_config`.*

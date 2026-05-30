# robo-services — AI-Assisted Engineering Session Showcase
**May 2026 · GitHub Copilot CLI (Claude Sonnet 4.6)**

---

## What Is This?

robo-services is an open-source MyChron-style racing telemetry data logger built on Kubernetes.
It ingests GPS and IMU data from embedded hardware over UDP, routes messages through an Iggy
message broker, and processes them with Apache Flink. This session designed and delivered two
major features almost entirely autonomously: a Flink-based lap segmentation pipeline that
automatically detects lap boundaries from geofence + bearing analysis, and a FastAPI + React
registry service that acts as the authoritative store for users, devices, versioned device
profiles, and race tracks.

---

## What Was Already in Place at Session Start

- Kubernetes cluster managed via ArgoCD with robo-services as an external Helm repo
- `kreceiver` UDP ingest service publishing GPS and IMU messages to Iggy topics
- Speed derivation Flink job (proof-of-concept) already deployed
- Mosquitto MQTT broker deployed for device communication
- `track-poly-poc/` directory with GeoJSON geopolygons for 7 circuits
- Shared `postgres-dev` instance in the cluster

---

## Task 1 — Lap Segmentation Flink Job: Architecture

**Request:** *"Build a Flink pipeline that subscribes to the GPS feed and handles lap detection — I want something we won't have to rewrite every time I change device specs."*

**What happened:**
- Agent identified that hardcoding sensor field names would break across the three planned hardware tiers (scraps POC with GT-U7/MPU-6050, mid-tier NEO-M9N/BNO085, personal F9P RTK + CAN)
- Designed a **device profile system**: JSON config mapping abstract field names to actual sensor paths, with all thresholds as configurable values
- Designed a three-phase state machine: `UNANCHORED → STAGED → LAPPING`, where the user hits a start button once staged at the line, then the job waits for a detected launch before counting Lap 1
- IMU launch detection made orientation-independent: `|√(ax²+ay²+az²) − baseline| > threshold` rather than relying on any single axis
- Lap completion: 40m geofence around the anchor point with a bearing direction filter (±35°) to reject false positives on circuits that cross near the start/finish

**Outcome:** Full architectural design ratified by user before a line of code was written; `ProfileResolver`, `SensorFieldExtractor`, and `LapCoProcessFunction` designed as the core abstractions.

---

## Task 2 — Lap Segmentation Flink Job: Implementation and Deployment

**Request:** *"Build and push the Docker images and enable in values.yaml, then run the end-to-end test and verify it's working."*

**What happened:**
- Implemented `LapSegmentationJob.java` (~900 lines) as a single-file Flink job with all logic as inner classes — no external deps beyond Flink + Iggy connector + Jackson
- Wrote 22 unit tests covering geofence, bearing, state machine transitions, and profile resolution — all passing
- Built three scenario files for the simulator (`clean.json`, `pit_stop.json`, `cold_start.json`) and implemented `sim/track_sim.py` as a synthetic track session emitter
- Built Helm templates: `lap-job-configmap.yaml`, `lap-job-rbac.yaml`, `lap-job-flinkdeployment.yaml`, added `lapJob` block to `values.yaml`
- Built and pushed `dwilson2547/robo-services-lap-flink:20260530-lap-v1`, ArgoCD synced, `lap-segmentation` FlinkDeployment reached RUNNING/STABLE
- First E2E run: anchor and launch detected correctly; lap completions not firing

**Outcome:** Job deployed and running; two sub-bugs identified for the next debugging round.

---

## Task 3 — Lap Completion Debugging: Three-Bug Chain

**Request:** *"Lap completions aren't firing — let's figure out why."*

**What happened:**

This was a multi-session debugging chain that uncovered three independent bugs in sequence:

**Bug 1 — Simulator using wall-clock timestamps.** The simulator emitted `captured_at` with the current wall time, not simulated time. At 10x playback speed, 30-second laps appeared to be 3 seconds — far below the minimum elapsed threshold. Fixed by adding a `sim_clock` that advances at sensor rate regardless of playback speed.

**Bug 2 — `prevLat/prevLon` update before bearing check.** Lines 469-470 updated the previous position state before the geofence/bearing check on lines 475-477. This meant `bearingDeg(state.prevLat, state.prevLon, lat, lon)` computed bearing from a point to itself → always 0°. Delta from 0° to the expected ~246° was always > 35° tolerance → bearing check permanently failed. Fixed by moving the state update to after the check block.

**Bug 3 — SLF4J format string masking the real problem.** Debug log used `{:.1f}` (Python-style) inside SLF4J which only recognises exact `{}`. This shifted argument positions, making `elapsed` appear as `distToAnchor` and `session` appear as `elapsed`. The log read `elapsed=18.293ms` when it was actually showing the distance value — a complete red herring.

After fixing all three bugs, lap completions still didn't fire. Elapsed was reading ~2ms — definitively wall-clock fallback.

**Outcome:** Three bugs fixed across v2–v4, but root cause still not resolved; pattern pointed to something upstream.

---

## Task 4 — Root Cause: iggy_backend.py b64 Envelope

**Request:** *"Still no completions — why is parseTimestampMs falling back to wall clock on every single message?"*

**What happened:**
- Added diagnostic logging to `parseTimestampMs` in v4: `captured_at missing or wrong type (null)` on every message, every topic
- Traced backwards from Flink through to `kreceiver/iggy_backend.py::_encode_message`
- Discovered the envelope wrapping: every message is published as `{"payload_b64": "<b64 of NormalizedIngressMessage.to_dict()>", "headers": {"x-device-id": ..., "x-captured-at": ...}}`
- Flink receives this outer wrapper and reads field names at the top level — `captured_at`, `device_id`, and `source_session` are all null there. Only lat/lon/speed worked because `extractPayload` had a pre-existing b64 decode path for GPS coordinates — which accidentally masked the issue for months
- Fix: `decodeEnvelope()` — if `device_id` absent at top level, base64-decode `payload_b64` → flat `NormalizedIngressMessage` dict. Headers (`x-session-id`, `x-device-id`, `x-captured-at`) used as fallback
- Built v5, deployed, re-ran simulation — **all 3 laps completed with correct timestamps and session IDs**

**Outcome:** Root cause found and fixed. Lap segmentation pipeline fully operational end-to-end: anchor → launch → 3 complete lap records emitted to `telemetry.derived.laps`. The b64 envelope wrapping is now documented as a critical gotcha for all future Flink jobs in this stack.

---

## Task 5 — Registry Service: FastAPI + React + Postgres

**Request:** *"Build a management system to keep track of users, devices, filters, derivations, configs, and tracks."*

**What happened:**
- Designed a `Device → DeviceProfile (versioned)` data model; profiles stored as JSONB so the schema doesn't need to change when sensor fields are tweaked
- Built a full FastAPI backend: CRUD routers for users, devices (with profile versioning), and tracks; `GET /api/devices/{device_id}/profile` as the Flink-facing active profile endpoint; Alembic migrations; SPA served from `/`
- Built a React 18 SPA: sidebar layout, Users CRUD, Devices CRUD with an inline profile version history panel (JSON editor, set-active button, version history list), Tracks CRUD with GeoJSON file import and Leaflet map view
- Hit react-leaflet 4.x / React 19 peer dep conflict — downgraded to React 18.3.1
- Multi-stage Dockerfile: Node 20 Alpine for Vite build, Python 3.12-slim for runtime; runs `alembic upgrade head` on startup
- Hit `pip install .` failure (pyproject.toml without source tree) — switched to inline deps
- Hit pydantic `EmailStr` → `email-validator` missing → CrashLoopBackOff — added dep, rebuilt as v2
- Created Helm templates: `registry-deployment.yaml`, `registry-service.yaml`, `registry-ingress.yaml`
- Provisioned `robo_registry` database on `postgres-dev` via `kubectl exec` with the init SQL pattern
- Created `registry-credentials` secret, set `registry.enabled: true`, pushed → ArgoCD synced
- Hit SQLAlchemy cascade delete 500 (`cascade="all, delete-orphan"` missing on `Device.profiles`) — fixed, rebuilt as v3
- Enabled ingress at `registry.robo-services.local`, added DNS A record, added "Robo Services" homepage group

**Outcome:** Registry service live at `http://registry.robo-services.local`; all CRUD endpoints verified; Flink lap job wired to registry via `LAP_JOB_REGISTRY_URL` with 5-minute TTL cache and graceful fallback chain.

---

## Task 6 — Flink ProfileResolver: Registry-Backed with TTL Cache

**Request:** *"The registry should become the authority — Flink should query it at runtime."*

**What happened:**
- Rewrote `ProfileResolver` in the lap job to accept `registryUrl` + `cacheTtlMs`
- `HttpClient` and the cache `Map` marked `transient` (not serializable) and rebuilt lazily in `ensureInitialized()` — required for Flink checkpoint restore
- Fallback chain: fresh cache hit → HTTP fetch (5s timeout) → 404 → static profilesJson → stale cache → built-in defaults
- Added `LAP_JOB_REGISTRY_URL` and `LAP_JOB_PROFILE_CACHE_TTL_S` env vars to the configmap
- Built and pushed `20260530-lap-v6`, set `registryUrl` in values.yaml

**Outcome:** Lap job now fetches device profiles from the registry at startup with TTL-based refresh; degrades gracefully if the registry is unreachable.

---

## Summary of Infrastructure Built

| Component | Technology | Notes |
|---|---|---|
| Lap Segmentation Job | Apache Flink 2.0 / Java 17 | 3-phase state machine, geofence + bearing filter, device-profile-driven |
| Device Profile System | JSON config via env var / registry API | Supports field path mapping for 3 hardware tiers |
| Track Simulator | Python | Synthetic GPS+IMU session emitter with simulated clock |
| Registry Service | FastAPI + React 18 + Postgres | Users, devices, versioned profiles, tracks; Alembic migrations |
| Registry UI | React 18 + Leaflet + Vite | GeoJSON import, Leaflet map view, profile JSON editor |
| Registry DNS | CoreDNS | `registry.robo-services.local → 192.168.0.60` |
| ProfileResolver Cache | In-memory TTL cache (Java) | 5-min TTL, transient fields for Flink serialization compatibility |

---

## Commits in This Session

| Hash | Description |
|---|---|
| `cad7f70` | feat: add lap segmentation Flink job and simulator |
| `9ec5304` | feat: enable lap-segmentation job in Helm values |
| `6e72742` | Fix lap bearing bug and simulator timestamps |
| `303c85a` | Add geofence debug logging and bump to lap-v3 |
| `e5c7313` | lap-flink v4: diagnose parseTimestampMs fallback, fix SLF4J format |
| `28f22c1` | fix(lap-job): decode iggy_backend b64 envelope in processElement1/2 (v5) |
| `af52fb3` | docs: add Flink patterns, lap pipeline notes, and b64 envelope issue doc |
| `dd32843` | docs: add README for lap_flink_job |
| `e112b19` | feat: add registry service (FastAPI + React + Postgres) |
| `2cb84d8` | feat: registry-backed ProfileResolver with TTL cache (lap job v6) |
| `65c925f` | feat: enable registry in values.yaml |
| `1f00c90` | fix(registry): add email-validator dep, bump to v2 |
| `c37cb92` | fix(registry): cascade delete profiles on device delete, bump to v3 |
| `d9cbccd` | feat(lap-job): wire registry URL to ProfileResolver |
| `f68e70d` | feat(registry): enable ingress at registry.robo-services.local |
| `2d716ec` | docs: registry service patterns, issue docs, flink transient fields update |
| `5719eec` | feat(robo-services): add registry DNS + homepage entry (cluster_config) |
| `b9c50e5` | chore: update CHANGELOG for registry DNS/homepage (cluster_config) |

---

*Document generated 2026-05-30. Repository: `dwilson2547/robo-services`.*

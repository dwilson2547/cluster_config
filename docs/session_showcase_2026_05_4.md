# Junkyard Inventory Scrapers — AI-Assisted Engineering Session Showcase
**May 2026 · GitHub Copilot Chat (Claude Sonnet 4.6)**

---

## What Is This?

The `junkyard_inventory_scrapers` project builds a library of site-specific scrape strategies
for self-service auto salvage yards — each yard gets a folder with a `readme.md` documenting
how to extract its full inventory programmatically. This session covered the recon and strategy
document for **tearapart.com**, a two-location Utah pick-and-pull yard. The session exercised
Playwright-based live site investigation to reverse-engineer the undocumented WordPress AJAX API
powering the yard's inventory search, confirmed VIN availability, validated the strategy with
live server-side curl tests, and updated the shared notes library with a new WordPress nonce
failure pattern.

---

## What Was Already in Place at Session Start

- `YARDS.md` tracking list of ~24 junkyard sites to investigate, all unchecked
- `notes/` library with recon patterns for four confirmed platforms: WordPress AJAX
  (`wordpress-junkyard-sites.md`), Nuxt SPA API interception (`nuxt-spa-api-interception.md`),
  autorecycler.io SaaS embed (`autorecycler-io-platform.md`), and static HTML table
  (`parts-galore-static-html-table.md`)
- Completed scrapers/strategies for `pull_a_part_scraper`, `pic-n-pull`, `pull-n-save`,
  `u-pull-n-save`, `ryans_pic_a_part`, `us_auto_parts_sterling_heights`, and `parts-galore`
- `YARDS.md` instruction block specifying: check notes first, document VIN absence prominently
  if absent, capture recent-arrivals pages, persist location address and contact info

---

## Task 1 — Investigate tearapart.com and Document Scrape Strategy

**Request:** *"Could we address the next item on the list? The file should have all the
instructions you need, let me know if you have any questions."*

**What happened:**

- Confirmed the first unchecked site: `https://tearapart.com/inventory/`
- Read all four existing notes files in parallel before touching the browser to check for
  known platform patterns
- Opened the inventory page in Playwright and immediately identified it as a WordPress site
  from the `admin-ajax.php` reference in the page source
- Located two custom plugins via `<script src>` analysis:
  - `tap-inventory-search-system` — the primary (newer) plugin, with a `sif_ajax_object`
    JS global containing the AJAX URL and a short-lived nonce (`sif_ajax_nonce`)
  - `gm_inventory_search` — a legacy plugin with no nonce references in its JS
- Read both plugin JS files in full to catalogue all AJAX actions and their required parameters
- Identified five `sif_*` AJAX actions: `sif_get_stores`, `sif_get_locations`, `sif_get_makes`,
  `sif_update_models`, `sif_search_products` (the inventory endpoint)
- Discovered that `sif_form_field_store` is required — there is no "all stores" value; two
  separate calls are needed, one per store
- Called `sif_search_products` in-browser with `make=Any` and `store=SALT LAKE CITY`, receiving
  **824 records** with full VINs in a single un-paginated JSON response; repeated for `OGDEN`
  yielding **803 records**
- Confirmed nonce is required: server-side `curl` without the nonce returns `"test failed!"`
  (HTTP 200, plain text — not a 403); established that the nonce can be extracted from a plain
  `GET /inventory/` with `requests`, no login or cookie needed
- Attempted the legacy `gm_inventory_search` `get_yard_inventory_data` action without a nonce —
  server returned 502 (backend timeout), strategy abandoned
- Retrieved location data from `/location/`:
  - Salt Lake City: 652 S. Redwood Rd, SLC UT 84104 · (801) 886-2345
  - Ogden: 763 W 12th St, Ogden UT 84404 · (801) 564-6960
- Inspected the `/new-arrivals/`, `/just-in-salt-lake-city/`, and `/just-in-ogden/` pages;
  confirmed all are populated by the same `sif` plugin (same nonce required) and render only
  Year/Make/Model/Row/Location — **no VINs** — making them inferior to filtering on
  `yard_in_date` from the primary API
- Documented every record field (`stocknumber`, `vin`, `iyear`, `make`, `model`, `color`,
  `mileage`, `vehicle_row`, `yard_date`, `yard_in_date`, `hol_*` Hollander fields, `reference`,
  `image_url`, yard metadata), including the incremental strategy using `yard_in_date` as a
  watermark and `stocknumber` as the dedup key
- Updated `notes/wordpress-junkyard-sites.md` with two new findings:
  - The `"test failed!"` plain-text nonce-failure signature (HTTP 200, not 403)
  - Custom plugins use non-standard nonce POST field names (e.g. `sif_verify_request`) —
    check the plugin JS for the exact field name, not the WP default `_wpnonce`
- Created `tearapart/readme.md` with full strategy, endpoint reference, record schema,
  Python code sample, and nonce lifecycle notes
- Checked off `tearapart.com` in `YARDS.md`

**Outcome:** Full inventory for both Tear-A-Part locations (SLC + Ogden, ~1,600+ vehicles
combined) is retrievable via two POST requests using a nonce extracted from a single public
page GET. VINs are present on every record. Strategy documented and ready for scraper
implementation.

---

## Summary of Infrastructure Built

| Component | Technology | Notes |
|---|---|---|
| `tearapart/readme.md` | Markdown strategy doc | Covers API, auth, record schema, Python sample, incremental approach |
| `notes/wordpress-junkyard-sites.md` (updated) | Shared recon notes | Added `"test failed!"` nonce failure pattern and custom field name guidance |

---

## Commits in This Session

No commits were made — the session produced documentation files only. The `tearapart/` folder
was created and `YARDS.md` was updated directly in the working tree.

---

*Document generated 2026-05-28. Repository: `junkyard_inventory_scrapers` (local workspace).*

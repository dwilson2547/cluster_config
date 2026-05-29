# Junkyard Inventory Scrapers — AI-Assisted Engineering Session Showcase
**May 2026 · GitHub Copilot Chat (Claude Sonnet 4.6)**

---

## What Is This?

This project is a collection of web scrapers targeting junkyard and auto-salvage inventory sites, accumulating vehicle data (make, model, year, VIN, mileage, stock number) across dozens of independently operated yards. Each scraper strategy is researched using Playwright browser automation to reverse-engineer the site's data transport layer, then documented in a per-site `readme.md`. This session added research and strategy documentation for one new site: **Arizona Auto Parts** (`arizonaautoparts.com`), and extended shared platform notes with a new finding from that investigation.

---

## What Was Already in Place at Session Start

- A `YARDS.md` checklist tracking ~28 target junkyard sites, with ~21 already completed
- Per-site folders with `readme.md` strategy documents (tearapart, speedwayap, chesterfieldauto, sturtevantauto, fenixupull, pyp, ipullupull, centralfloridapickandpay, jacksusedautoparts, las-parts, wegotused, midwayupull, indyupullit, baughmansupullit, budgetupullit, strickerautoparts, utpap, usedautopartsfl, mcdonoughautoparts, picknpullsa — all documented)
- A `notes/` directory of reusable platform notes capturing patterns across sites: URG IIS Pro v2, custom WP SSR themes, ASP.NET MVC, WordPress AJAX, AngularJS inventory plugins, and others
- `arizonaautoparts.com` was the next unchecked item on the list

---

## Task 1 — Research and Document arizonaautoparts.com Scraping Strategy

**Request:** *"Could we address the next item on the list? The file should have all the instructions you need."*

**What happened:**
- Loaded the existing `notes/` files for context on known patterns (URG IIS Pro v2, custom WP SSR, ASP.NET MVC, WordPress AJAX, inventory-7lt plugin, and others) before touching the target site
- Navigated to `https://arizonaautoparts.com/search-inventory/` with Playwright and immediately spotted `/parts/makes/` in the nav — a strong URG IIS Pro v2 fingerprint
- Confirmed the platform via JavaScript evaluation: `iis-pro-v2` plugin present in page source, `urgid = 'AZ03'`, `iisNonce` injected inline, iisincludespro JS at `/wp-content/plugins/iis-pro-v2/js/iisincludespro3.js?ver=4.76`
- Navigated through the full SSR URL hierarchy (`/parts/makes/` → `/parts/CHEVROLET/` → `/parts/CHEVROLET/CAMARO/`) to validate structure and extract a sample vehicle card
- Confirmed VINs are present on every vehicle card (field `<b>Vin :</b>`)
- Navigated to `/latest-arrivals/` — confirmed 60 most recent vehicles with `Arrive Date: YYYY-MM-DD` field (slightly different label from the `Purchase Date` documented in the URG notes for other sites)
- Navigated to `/locations/` — discovered **two yards** under one site: Phoenix (2021 W Buckeye Rd, +1 602-253-5111) and Tucson (6671 E Littletown Rd, +1 520-479-1500)
- Observed stock number format is **alphanumeric** (e.g. `230358A`, `260844B`) rather than the numeric-only format seen on other URG sites; sampled the latest-arrivals suffix distribution: A=31, B=27, U=2 — consistent with a per-location encoding
- Verified no location field appears on vehicle cards — location is only inferrable from stock suffix
- Computed total inventory scope: 46 makes, ~6,521 total vehicles, ~417 GET requests for a full crawl with no row cap or pagination at the model level

**Files created/modified:**
- `arizonaautoparts/readme.md` — full strategy document covering: platform identification, both locations with addresses and phone numbers, VIN availability, the complete SSR URL hierarchy, card HTML structure with field extraction, estimated request count, image CDN pattern (`da8h1v3w8q6n5.cloudfront.net/az03/...`), incremental update approach via `/latest-arrivals/`, and a note on the unconfirmed stock suffix→location mapping
- `notes/urg-iis-pro-v2-platform.md` — updated image CDN section to document that the CDN path is yard-specific (not always `mi34`); added a new **Stock Number Format** section documenting alphanumeric stock IDs and the suffix-to-location pattern discovered on AZ03
- `YARDS.md` — checked off `arizonaautoparts.com`

**Outcome:** Full scraping strategy documented for Arizona Auto Parts (two-location, ~6,500-vehicle URG IIS Pro v2 site); shared platform notes extended with a reusable finding about alphanumeric stock IDs.

---

## Summary of Infrastructure Built

| Component | Technology | Notes |
|---|---|---|
| `arizonaautoparts/readme.md` | Markdown strategy doc | SSR crawl, ~417 requests, no auth, VIN present |
| URG notes update | Markdown | Alphanumeric stock suffix pattern; yard-specific CDN path |

---

## Commits in This Session

No commit hashes captured — work was pushed to `junkyard_inventory_scrapers` via a terminal `git push` visible in session context, but the specific hash was not surfaced during the conversation.

---

*Document generated 2026-05-28. Repository: `junkyard_inventory_scrapers` + `cluster_config`.*

# BATIS — Implementation Progress
_Last updated: 2026-11-10_

Inventory of every tab, endpoint, ETL step and table in BATIS: what works, what needs live data, and what is missing.

## Current status (2026-11-10)

_Rule: update this block, CHANGELOG.md, CLAUDE.md and memory after every change (CLAUDE.md rule 10)._

Open tasks: (4) RT ingestion fixed and verified with one live poll; still to do: keep the ingestor running (uvicorn or `python -m app.workers.run_rt_ingestor`) to accumulate data, then rebuild snapshots/headways/predictions; (5) DONE: spatial `transfer_reliability` with a user-selectable radius (migration 011); (6) DONE: pgvector image + embeddings loaded (Ollama model still needs pulling or OLLAMA_MODEL set); (7) daily backfill cron installed; 5 of 12 months loaded (2026-06 to 2026-10), 7 to go at two per night (about 4 nights); live RT poll bug (routeless BART trip updates) fixed; (8) DONE (docs corrected), still: rotate leaked 511 key.
PROGRESS.md tables rewritten 2026-11-10 from the code (legend, 7 tabs, 62 routes, ETL steps 0 to 17, bug list closed; found `AiAssistant.tsx` orphaned, no tab uses it). Docs sync (2026-11-10): CLAUDE.md said stop_observations held 2026-08 to 2026-10; corrected to 2026-06 to 2026-10 (about 129M rows) per the CHANGELOG batch 1 result. Not re-queried: `psql` is not installed on the host, so verify counts via the dashboard Data tab or `docker exec`.
Done today: Status tab redesigned as activity cards with drill-down and live backfill progress, System Status dashboard (Status tab, `/admin/*`, migration 012), surrogate-key commit, Berkeley removal, synthetic ops data removed and purged. Reliability, Crowding, Demand and Bunching sections now have no data until live RT fills `ops_trip_events`. See `CHANGELOG.md`.

---

## Legend
- ✅ **Complete**: wired end to end (route, service, UI) and not known to be broken
- ⏳ **Needs data**: code works, but the tables it reads are empty until live data accumulates (no synthetic fill, by rule 9)
- ⚠️ **Partial**: works with a known limitation
- 🔲 **Unused**: exists but has no consumer
- ❌ **Missing**: not built

_Audit method (2026-11-10): read from the code (routes in `main.py`, tab and section files, ETL print lines, grep of old bug sites), not from a populated-DB run. Row counts come from CLAUDE.md and the CHANGELOG, not a fresh query._

---

## Frontend (7 tabs in `AppShell.tsx`)

| Tab | File | Reads (endpoints) | Status | Notes |
|-----|------|-------------------|--------|-------|
| Overview | `Overview.tsx` | `/reliability/summary`, `/reliability/trend`, `/routes`, `/safety/stops` | ⏳ | KPIs for reliability need `ops_trip_events`; safety and route list work |
| Operations | `Operations.tsx` | `/bunching/summary`, `/crowding/predictions`, `/reliability/summary`, `/vehicles/live` | ⏳ | Bunching and crowding empty until RT accumulates; live vehicles work while the ingestor runs |
| Network | `Network.tsx` | `/coverage/cells`, `/coverage/deserts`, `/routes`, `/routes/{id}/geo` | ✅ | Route explorer plus coverage layers |
| Equity & Safety | `EquitySafety.tsx` | `/equity/score`, `/safety/stops` | ✅ | Safety is Oakland incidents only |
| Benchmarks & Drift | `BenchmarksDrift.tsx` | `/benchmarks/agency-otp`, `/traffic/events`, `/traffic/work-zones` | ✅ | OTP from `stop_observations`; schedule drift endpoint `/schedule-drift/{agency}/{route}` |
| Planning | `Planning.tsx` + `planning/` | see below | ✅ | Sub-tabs: Coverage, Diagnostics, Transfer reliability and deserts, Fares, Fare burden, Service delivery gap, ADA gap, Scenarios, Regional, Workbench |
| Backend | `Status.tsx` | `/admin/activities`, `/admin/activities/{key}`, `/admin/status` | ✅ | Activity cards, live progress, drill-down tabs |

Shared components: `MapView` (all GeoJSON layers incl. traffic and transit impact), `SectionMap`, `StopDrawer` (calls `/stops/{id}`, holds live departures state), `PlannerPanel` (`/trip-planner`), `BenchmarkPanel`, `AlertsBanner` (`/alerts`), `AgencyCombobox`, `FilterBar`.

| Component | Status | Notes |
|-----------|--------|-------|
| `AiAssistant.tsx` | 🔲 | Not imported anywhere in `frontend/src` (grep), so the RAG chat has no tab. Backend `/ai/*` works. Decide: add a tab or delete |
| Planning sub-tabs | ✅ | ADA gap, fare burden, service delivery gap, transfers have tests and drawers |
| Frontend tests | ✅ | 115 vitest |

---

## Backend API (62 route decorators in `main.py`)

| Group | Endpoints | Status | Notes |
|-------|-----------|--------|-------|
| Admin / status | `/admin/status`, `/admin/activities`, `/admin/activities/{key}`, `/admin/api-calls`, `/admin/job-runs` | ✅ | `X-API-Key` when `BACKEND_API_KEY` set; catalog in `services/activities.py` |
| Meta | `/health`, `/` | ✅ | `/` returns a pointer to the dashboard |
| Agencies | `/agencies`, `/agencies/rollup` | ✅ | |
| Scenarios | `GET/POST /scenarios`, `/scenarios/{id}`, `/scenarios/{id}/impact`, `DELETE` | ✅ | Migration 003 |
| Reliability | `/reliability/summary`, `/route/{id}`, `/predictions`, `/stops/geo`, `/trend` | ⏳ | Needs `ops_trip_events` from live RT. `/route/{id}` and `/predictions` have no UI consumer |
| Benchmarks | `/benchmarks/agency-otp`, `/schedule-drift/{agency}/{route}`, `/observations/status` | ✅ | From `stop_observations` |
| Coverage / equity | `/coverage/cells`, `/coverage/deserts`, `/equity/score` | ✅ | |
| Safety | `/safety/stops`, `/safety/stops/geo` | ✅ | Buffer now geography meters (old degrees bug gone) |
| Demand / crowding | `/demand/forecasts`, `/demand/stops/geo`, `/crowding/predictions`, `/crowding/stops/geo` | ⏳ | Forecast tables truncated 2026-11-10; no real APC data exists |
| Bunching | `/bunching/summary` | ⏳ | Same as above |
| Routes / stops | `/routes`, `/routes/compare`, `/routes/{id}/geo`, `/routes/{id}/headways`, `/stops/{id}`, `/stops/{id}/realtime-departures`, `/stops/{id}/live-departures`, `/stops/{id}/reachability` | ⚠️ | `/routes/compare` now sits before the parameterised routes. Headways need RT. `/reachability` and `/realtime-departures` have no UI consumer. Stop endpoints take `?agency_id=` |
| Live | `/vehicles/live`, `/alerts` | ⚠️ | Work while a 511 key is set |
| Trip planner | `/trip-planner` | ⚠️ | Single-route only |
| Transfers | `/transfers/radii`, `/transfers/reliability`, `/transfers/deserts` | ✅ | Spatial links, radius chosen at read time (migration 011) |
| Fares | `/fares/products`, `/fares/calculate`, `/fares/sample-corridor`, `/equity/fare-burden` | ✅ | |
| Service / ADA gap | `/equity/service-delivery-gap` (+ cell drawer), ADA gap | ✅ | |
| Traffic | `/traffic/events`, `/work-zones`, `/toll-rates`, `/transit-impact` | ✅ | |
| AI | `POST /ai/ask`, `/ai/explain/{route_id}`, `/ai/status` | ⚠️ | Embeddings loaded; Ollama has `llama3.1:8b`; no UI (see AiAssistant) |

---

## ETL (`run_data_jobs.py`, steps 0 to 17; the code labels them "n/20" but nothing prints 18 to 20, so "20 steps" in older docs is a stale label)

| Step | What | Status | Notes |
|------|------|--------|-------|
| 0 | Sync agency catalog from 511 | ✅ | |
| 1 | Load GTFS static (29 of 30 agencies) | ✅ | CR has no 511 feed, reported as skipped |
| 2 | `trip_stop_snapshots` | ⏳ | Empty until RT data exists |
| 3 | `stop_features` | ✅ | 20,260 rows |
| 4 | Headways per service date | ⏳ | Needs RT trip updates |
| 5 | Delay predictions | ⏳ | |
| 6 | Bunching predictions | ⏳ | |
| 7 | Demand forecasts and crowding | ⏳ | |
| 8 | Oakland safety incidents | ⚠️ | Oakland only; Berkeley removed |
| 9 | Stop safety scores | ✅ | 20,260 rows |
| 10 | Coverage cells and deserts | ✅ | 2,350 cells |
| 11 | Census equity columns | ✅ | 1,772 tracts |
| 12 | Transfer reliability and links | ✅ | 35,140 directed pairs up to 400 m |
| 13 | Load last month of `stop_observations` | ✅ | Needs `FIVE11_API_KEY`; 511 budget 60/h |
| 14 | Fare burden | ✅ | |
| 15 | Service delivery gap | ✅ | 688 rows |
| 16 | ADA gap per stop | ✅ | 20,260 rows |
| 17 | Refresh `cell_ada_gap` view | ✅ | |

Other workers: `run_rt_ingestor` (poll every 180 s, ✅ verified live, must be left running), `backfill_stop_observations` (cron 03:00, 2 months a night), `load_stop_observations`.

## Background threads (API startup, all daemon)

| Thread | Status | Notes |
|--------|--------|-------|
| RT ingestor | ✅ | 511 poll, tracked as `rt_ingestor`; accumulates only while uvicorn runs |
| Baseline predictor (30 min) | ⏳ | Needs history in `ops_trip_events` |
| Embed pipeline (30 min) | ✅ | pgvector installed |
| Traffic loop | ✅ | |

---

## Database population (dev DB, port 5434)

| Table | State | Notes |
|-------|-------|-------|
| `gtfs_*` (routes 621, stops 20,260, trips 90k, stop_times 3.17M, shapes) | ✅ | Composite keys (009), stop_pk (010) |
| `stop_observations` | ✅ | About 129M rows, 2026-06 to 2026-10; 7 months to go |
| `rt_vehicle_positions_raw`, `ops_trip_events` | ⏳ Small | One live poll plus whatever ran since; grows while ingestor runs |
| `ops_headways`, `trip_stop_snapshots`, `delay_predictions`, `bunching_predictions`, `demand_forecasts`, `crowding_predictions` | ⏳ Empty | Purged 2026-11-10 (synthetic); refill from live RT |
| `coverage_cells`, `transit_deserts`, census tables | ✅ | |
| `safety_incidents_raw`, `stop_safety_scores` | ✅ | Oakland |
| `fare_*`, `fare_burden`, `service_delivery_gap`, `stop_ada_gap`, `stop_features` | ✅ | |
| `transfer_reliability`, `stop_transfer_links` | ✅ | Slice 2026-10-28..30 in dev DB |
| `ai_embeddings` | ✅ | 621 routes, 2,000 stops, 70 ops summaries |
| `api_call_log`, `job_runs` | ✅ | Migration 012, pruned at startup |
| `traffic_events`, `work_zones`, `toll_rates` | ✅ | Traffic loop |

---

## Old bug list (B1 to B8 from May): all closed

| # | Bug | Now |
|---|-----|-----|
| B1 | `/routes/compare` unreachable | Fixed, route order |
| B2 | Safety `ST_DWithin` in degrees | Fixed, geography meters (`safety_scoring.py`) |
| B3 | `CREATE EXTENSION vector` missing | In `schema.sql` |
| B4 | `sentence-transformers`, `httpx` missing | Fixed in Phase 0 |
| B5 | Equity `WHERE population > 0` | Gone from `equity_loader.py` |
| B6 | StopDrawer scheduled-only | Live departures state and `/live-departures` |
| B7 | f-string embedding in SQL | Fixed in Phase 0 |
| B8 | `verify=False` | None left in `backend/app` (grep) |

## Not built / open product gaps

- AI Assistant tab (component orphaned, see above).
- Real APC passenger counts: demand and crowding stay empty rather than proxy-filled.
- Multi-leg trip planning with transfers.
- UI for `/routes/{id}/reachability`-style isochrones, `/reliability/route/{id}` and `/reliability/predictions`.
- Santa Clara METRO (CR): no 511 GTFS feed.
- Not verified in this audit: API rate limiting and Socrata pagination for Oakland incidents. Check before relying on them.

## History

- 2026-05-11 Phase 0 bug bash. 2026-05-13 composite keys (009). Sprints 4a to 5c: transfers, fares, fare burden, service delivery gap, ADA gap. 2026-11-10: surrogate stop key (010), spatial transfers (011), run log and Backend tab (012), synthetic data purge, pgvector, backfill cron. Details in `CHANGELOG.md` and `docs/superpowers/`.
- Tests: 233 backend, 115 frontend.

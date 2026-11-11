# BATIS — Implementation Progress
_Last updated: 2026-11-10_

Complete inventory of every feature, endpoint, component, and data pipeline in BATIS — what works, what's broken, and what's missing.

> ⚠️ **STALE (checked 2026-11-09):** this file was last written 2026-05-09, before Phase 0 (bug fixes), Sprints 4a–5c (transfers, fares, fare burden, service-delivery gap, ADA gap), and the multi-agency composite-key migration. Many 🔴/⚠️ rows below (e.g. safety `ST_DWithin`, `/routes/compare`) were fixed in Phase 0, and the API now has ~55 route decorators, not 29. Treat statuses as historical; see `CLAUDE.md` and `docs/superpowers/` for current state. A full re-audit needs a populated DB.

## Current status (2026-11-10)

_Rule: update this block, CHANGELOG.md, CLAUDE.md and memory after every change (CLAUDE.md rule 10)._

Open tasks: (4) RT ingestion fixed and verified with one live poll; still to do: keep the ingestor running (uvicorn or `python -m app.workers.run_rt_ingestor`) to accumulate data, then rebuild snapshots/headways/predictions; (5) DONE: spatial `transfer_reliability` with a user-selectable radius (migration 011); (6) DONE: pgvector image + embeddings loaded (Ollama model still needs pulling or OLLAMA_MODEL set); (7) daily backfill cron installed; 5 of 12 months loaded (2026-06 to 2026-10), 7 to go at two per night (about 4 nights); live RT poll bug (routeless BART trip updates) fixed; (8) DONE (docs corrected), still: rotate leaked 511 key.
Docs sync (2026-11-10): CLAUDE.md said stop_observations held 2026-08 to 2026-10; corrected to 2026-06 to 2026-10 (about 129M rows) per the CHANGELOG batch 1 result. Not re-queried: `psql` is not installed on the host, so verify counts via the dashboard Data tab or `docker exec`.
Done today: Status tab redesigned as activity cards with drill-down and live backfill progress, System Status dashboard (Status tab, `/admin/*`, migration 012), surrogate-key commit, Berkeley removal, synthetic ops data removed and purged. Reliability, Crowding, Demand and Bunching sections now have no data until live RT fills `ops_trip_events`. See `CHANGELOG.md`.

---

## Legend
- ✅ **Complete** — works end-to-end in both backend and frontend
- ⚠️ **Partial** — backend works but frontend incomplete (or vice versa), or logic is simplified
- 🔴 **Broken** — code exists but has a bug that prevents it from working correctly
- 🔲 **Stub** — endpoint/component exists but has no real implementation or no consumer
- ❌ **Missing** — not implemented at all

---

## Frontend Sections (11 tabs)

| Section | Map Layer | Sidebar Panel | Status | Notes |
|---------|-----------|---------------|--------|-------|
| Reliability | Delay-colored stop circles + heatmap toggle | KPIs, worst routes list, trend chart | ⚠️ Partial | Works with seeded data; `NULL` delay treated as 0 (inflates OTP); heatmap toggle breaks layer visibility |
| Crowding | Crowding-colored stop circles | KPIs, level bars, routes by crowding | ⚠️ Partial | Crowding derived from event count proxy; thresholds too low for synthetic data |
| Safety | Safety-scored stop circles | KPIs, most-at-risk stops | 🔴 Broken | ST_DWithin uses degrees not meters → all incidents match all stops → all scores are wrong |
| Coverage | Hex grid + transit deserts overlay | KPIs, freq distribution | ⚠️ Partial | Grid works; `equity_score` always NULL (see equity bug) |
| Demand | Stop circles sized by boardings | KPIs, top routes bar chart | ⚠️ Partial | Boardings = event count proxy; CI always NULL |
| Route Explorer | Route shape + stop circles | Searchable route list, headway chart | ✅ Complete | Works well; headway chart needs RT data to populate |
| Bunching | ⚠️ Reuses reliability layer | Stddev-ranked route list | ⚠️ Partial | Map shows delay, not bunching; `/bunching/summary` works; `bunching_predictions` table populated but unused |
| Live Vehicles | Vehicle position dots (30s poll) | Vehicle count, route list | ⚠️ Partial | Needs AC Transit RT API key; polling works |
| Comparison | No map interaction | Multi-route KPI table | 🔴 Broken | `/routes/compare` endpoint unreachable (FastAPI routing conflict) |
| Trip Planner | Click-to-set origin/dest pins | Itinerary list with delay overlay | ⚠️ Partial | Single-route only; no transfers; `minutes` param ignored |
| AI Assistant | No map interaction | Chat UI with citations | ⚠️ Partial | Works if Ollama running + model pulled + sentence-transformers installed; no conversation history |

---

## Backend API Endpoints (29 total)

### Reliability
| Endpoint | Auth | Status | Frontend Consumer | Notes |
|----------|------|--------|-------------------|-------|
| `GET /reliability/summary` | ✓ | ✅ | ReliabilityPanel | NULL delays coerced to 0 |
| `GET /reliability/route/{route_id}` | ✓ | 🔲 | None | No frontend consumer |
| `GET /reliability/predictions` | ✓ | 🔲 | None | Used internally only |
| `GET /reliability/stops/geo` | ✓ | ✅ | MapView | Also used by Bunching section |
| `GET /reliability/trend` | ✓ | ✅ | ReliabilityTrendChart | |

### Coverage
| Endpoint | Auth | Status | Frontend Consumer | Notes |
|----------|------|--------|-------------------|-------|
| `GET /coverage/cells` | ✓ | ⚠️ | MapView + CoveragePanel | equity_score always NULL; bbox parse not validated |
| `GET /coverage/deserts` | ✓ | ✅ | MapView | |

### Safety
| Endpoint | Auth | Status | Frontend Consumer | Notes |
|----------|------|--------|-------------------|-------|
| `GET /safety/stops` | ✓ | 🔴 | SafetyPanel | Scores wrong due to geometry unit bug |
| `GET /safety/stops/geo` | ✓ | 🔴 | MapView | Same bug |

### Demand & Crowding
| Endpoint | Auth | Status | Frontend Consumer | Notes |
|----------|------|--------|-------------------|-------|
| `GET /demand/forecasts` | ✓ | ⚠️ | DemandPanel | time_bucket dimension unused in UI |
| `GET /demand/stops/geo` | ✓ | ⚠️ | MapView | |
| `GET /crowding/predictions` | ✓ | ⚠️ | CrowdingPanel | time_bucket + trip_id fetched but ignored |
| `GET /crowding/stops/geo` | ✓ | ⚠️ | MapView | |

### Routes & Stops
| Endpoint | Auth | Status | Frontend Consumer | Notes |
|----------|------|--------|-------------------|-------|
| `GET /routes` | ✓ | ✅ | RouteExplorerPanel, RouteComparisonPanel | |
| `GET /routes/{route_id}/geo` | ✓ | ✅ | MapView | |
| `GET /routes/{route_id}/headways` | ✓ | ⚠️ | RouteHeadwayChart | Ignores start_date; needs RT data |
| `GET /routes/compare` | ✓ | 🔴 | RouteComparisonPanel | **UNREACHABLE** — routing conflict |
| `GET /stops/{stop_id}` | ✓ | ⚠️ | StopDrawer | Shows scheduled, not RT departures |
| `GET /stops/{stop_id}/realtime-departures` | ✓ | 🔲 | None | Endpoint works; no frontend consumer |
| `GET /stops/{stop_id}/reachability` | ✓ | 🔲 | None | `minutes` param completely ignored |

### Live & Operational
| Endpoint | Auth | Status | Frontend Consumer | Notes |
|----------|------|--------|-------------------|-------|
| `GET /vehicles/live` | None | ⚠️ | MapView + LiveVehiclesPanel | Needs RT API key |
| `GET /alerts` | None | ⚠️ | AlertsBanner | Silently returns [] without AC Transit key |
| `GET /bunching/summary` | ✓ | ✅ | BunchingPanel | |
| `GET /trip-planner` | ✓ | ⚠️ | TripPlannerPanel | Single-route, no transfers |

### AI
| Endpoint | Auth | Status | Frontend Consumer | Notes |
|----------|------|--------|-------------------|-------|
| `POST /ai/ask` | ✓ | ⚠️ | AiAssistant | Needs Ollama + sentence-transformers |
| `GET /ai/explain/{route_id}` | ✓ | 🔲 | None | No frontend trigger |
| `GET /ai/status` | None | ✅ | AiAssistant | |

### Misc
| Endpoint | Auth | Status | Frontend Consumer | Notes |
|----------|------|--------|-------------------|-------|
| `GET /health` | None | ✅ | None | Exposes GTFS URL to anon callers |
| `GET /` | None | ✅ | None | |

---

## Data Pipeline Steps (run_data_jobs.py)

| Step | Function | Status | Output Table(s) | Notes |
|------|----------|--------|-----------------|-------|
| 1 | `load_gtfs_static()` | ⚠️ Slow | gtfs_routes, gtfs_stops, gtfs_trips, gtfs_stop_times, gtfs_shape_geoms | Upserts row-by-row; stop geometry UPDATE is slow loop |
| 2 | `rebuild_trip_stop_snapshots()` | ✅ | trip_stop_snapshots | avg_headway_* always NULL |
| 3 | `rebuild_stop_features()` | ✅ | stop_features | avg_headway_* always NULL; not queried anywhere |
| 4 | `compute_headways()` per day | ⚠️ | ops_headways | Requires trip update RT data (stop_id IS NOT NULL) |
| 5 | `generate_delay_predictions()` | ⚠️ | delay_predictions | NULLs coerced to 0 |
| 6 | `generate_bunching_predictions()` | 🔲 | bunching_predictions | Table populated but no API endpoint reads it |
| 7a | `generate_demand_forecasts()` | ⚠️ | demand_forecasts | Event count proxy for boardings |
| 7b | `generate_crowding_predictions_from_demand()` | ⚠️ | crowding_predictions | Thresholds designed for real APC data |
| 8 | `load_safety_incidents()` | ⚠️ | safety_incidents_raw | Oakland only; 1000-row Socrata limit (no pagination) |
| 9 | `compute_stop_safety_scores()` | 🔴 | stop_safety_scores | **CRITICAL BUG**: ST_DWithin uses degrees, not meters |
| 10 | `build_coverage_cells()` + `build_transit_deserts()` | ✅ | coverage_cells, transit_deserts | |
| 11 | `populate_equity_columns()` | 🔴 | coverage_cells (equity_score) | **CRITICAL BUG**: `WHERE population > 0` never matches |

---

## Background Threads (started at app startup)

| Thread | Interval | Status | Notes |
|--------|----------|--------|-------|
| `gtfs-rt-ingestor` | 30 s | ⚠️ | Polls AC Transit GTFS-RT; needs API key; verify=False |
| `baseline-predictor` | 30 min | ⚠️ | SQL median predictor; needs 28 days of ops history |
| `embed-pipeline` | 30 min | 🔴 | Crashes without sentence_transformers in requirements.txt |

---

## Database Tables — Population Status

| Table | Populated? | How | Notes |
|-------|-----------|-----|-------|
| `gtfs_routes` | ✅ Yes | GTFS static load | Core reference |
| `gtfs_stops` | ✅ Yes | GTFS static load | geom set by separate loop |
| `gtfs_trips` | ✅ Yes | GTFS static load | |
| `gtfs_stop_times` | ✅ Yes | GTFS static load | Largest table |
| `gtfs_shapes` | ✅ Yes | GTFS static load | |
| `gtfs_shape_geoms` | ✅ Yes | GTFS static load | LineStrings |
| `rt_vehicle_positions_raw` | ⚠️ Only with RT key | RT ingestor | 30-day retention |
| `ops_trip_events` | ✅ Yes (seeded) | RT ingestor or seed | stop_id NULL for vehicle-pos rows |
| `ops_headways` | ⚠️ Needs stop-level RT | compute_headways | Empty without trip update feed |
| `coverage_cells` | ✅ Yes | build_coverage_cells | equity_score always NULL |
| `transit_deserts` | ✅ Yes | build_transit_deserts | |
| `safety_incidents_raw` | ⚠️ Partial | Oakland Socrata | 1000-row limit; Oakland only |
| `stop_safety_scores` | 🔴 Wrong values | compute_stop_safety_scores | Geometry unit bug |
| `delay_predictions` | ✅ Yes | generate_delay_predictions + baseline | Two model versions coexist |
| `bunching_predictions` | ✅ Yes | generate_bunching_predictions | No endpoint reads this |
| `demand_forecasts` | ✅ Yes | generate_demand_forecasts | Proxy values, not real boardings |
| `crowding_predictions` | ✅ Yes | generate_crowding_predictions | Derived from demand proxy |
| `trip_stop_snapshots` | ✅ Yes | rebuild_trip_stop_snapshots | No endpoint reads this |
| `stop_features` | ✅ Yes | rebuild_stop_features | avg_headway always NULL; no endpoint |
| `ai_embeddings` | ⚠️ Needs sentence-transformers | run_embed_once | pgvector extension not in schema.sql |

---

## ⚠️ Required: Run Migration Before Sprint 1 Features Work

**File**: `backend/sql/migrations/001_multi_agency.sql`

This migration must be run against any existing database before Sprint 1 features will work. Fresh installs using `schema.sql` already include all changes.

```bash
psql $DATABASE_URL -f backend/sql/migrations/001_multi_agency.sql
```

**What it does:**
- Adds `agency_id text DEFAULT 'AC'` to 8 existing tables (`gtfs_routes`, `gtfs_stops`, `gtfs_trips`, `gtfs_stop_times`, `gtfs_shape_geoms`, `rt_vehicle_positions_raw`, `ops_trip_events`, `ops_headways`)
- Creates 4 agency-id indexes for multi-agency query performance
- Creates 3 new Sprint 1/2/3 tables: `stop_observations`, `traffic_events`, `work_zones`, `toll_rates` (with all indexes)

The migration is idempotent (`IF NOT EXISTS` throughout) and safe to re-run.

---

## Critical Bugs — Must Fix Before Sprint 1

| # | File | Bug | Fix |
|---|------|-----|-----|
| B1 | `main.py` | `/routes/compare` unreachable (routing conflict) | Move before `/routes/{route_id}/geo` |
| B2 | `safety_scoring.py` | `ST_DWithin` uses degrees not meters | Cast geoms to `::geography` |
| B3 | `schema.sql` | `CREATE EXTENSION vector` missing | Add before ai_embeddings DDL |
| B4 | `requirements.txt` | `sentence-transformers` + `httpx` missing | Add both |
| B5 | `equity_loader.py` | `WHERE population > 0` never matches | Remove WHERE or populate column |
| B6 | `StopDrawer.tsx` | Uses scheduled departures, not RT | Call `/realtime-departures` endpoint |
| B7 | `ai_assistant.py` | Embedding vector f-string in SQL | Use parameterised query |
| B8 | All services | `verify=False` on all HTTPS calls | Use `certifi.where()` |

---

## What Is NOT Yet Implemented

- Real-time Stop Monitoring (live ETAs via SIRI)
- Stop Observations archive ingestion
- Toll-transit correlation
- Rate limiting
- CORS from env var
- Pagination on coverage cells endpoint
- Real APC (automatic passenger counting) data

---

## Multi-Agency Foundation Fix — Completed 2026-05-13

The GTFS multi-agency data layer is now data-integrity-correct end-to-end.
Migration 009 (composite primary keys) + Phase 2 loader updates + Phase 3
read-path repair + Phase 4 ETL re-run landed across 14 commits. See
`docs/superpowers/plans/2026-05-13-gtfs-composite-keys.md` for the full plan.

**Data state** (post-Phase-4):

- 24 agencies loaded with full GTFS (routes, trips, stop_times, shapes,
  stop geometry): AC, BA, CC, CT, MA, PE, PG, SA, SB, SC, SF, SM, SO,
  SR, ST, UC, VC, VN, WC, WH, AM, CE, FS, 3D
- 595 routes, 90k trips, 3.3M stop_times, 1.6M shape points
- **0 cross-agency route_id mismatches** (was 57,919 pre-fix)
- Both NOT VALID FKs now fully VALIDATED — referential integrity locked in

**Known follow-up: stop_id collisions block 2 agencies (GG, MV).**
Both share stop_ids with already-loaded agencies (e.g. stop 40427 was
loaded by MA before GG attempted). The single-column PK on gtfs_stops
correctly refuses the second insert. To onboard GG + MV, gtfs_stops PK
must become composite `(agency_id, stop_id)`, which forces
`stop_safety_scores` and `stop_features` to be agency-aware too (their
FKs reference gtfs_stops.stop_id alone). This is documented as a
follow-up sprint in the foundation-fix plan's "Decision points".

**Test counts at sprint close:**

- Backend: 198 passing (was 151 at Sprint 5b close, 163 at Sprint 5c close)
- Frontend: 112 passing (was 105 at Sprint 5b close, 113 at Sprint 5c close)
- The 2 failing `test_service_delivery_gap` tests are pre-existing
  DATABASE_URL config drift, not caused by this work (confirmed by
  running them on commit 41479c5).

**Sprint 5c UX defect closed.** Pre-fix the 4 highest-gap Tenderloin
stops (14483, 18049, 14867, 14480) rendered "Routes: 0" in the ADA-gap
drawer. Post-fix all 5 top stops show their real SFMTA routes (31, 27,
38) with full short names ("31 BALBOA") and trip counts.

---

## Stale items (resolved earlier sprints)

The following bullets in earlier sections of this file are now obsolete
and should be removed in the next docs sweep:

- "511.org integration (any endpoint, any agency)" — IMPLEMENTED, all
  monitored agencies loaded via `/transit/datafeeds?operator_id=...`
- "Multi-agency support (BART, Muni, Caltrain, VTA, etc.)" — IMPLEMENTED
  end-to-end including correct cross-agency JOIN behaviour
- "Cross-agency on-time benchmarking" — `/reliability/summary` returns
  per-(agency, route) rows
- "Transfer reliability scoring" — `compute_transfer_reliability` runs
  in run_data_jobs Step 8
- "Work Zone / traffic event impact on transit" — `/traffic/transit-impact`
  is live and the MapView consumes it
- "Fare calculator (GTFS Fares v2)" — Sprint 4 added the loader and
  `/fares/*` endpoints
- "Accessibility gap analysis" — Sprint 5c shipped, and Phase 3 closed
  the visible defect on top-tier stops
- "Any automated tests (zero backend tests, zero frontend tests)" — 198
  backend + 112 frontend

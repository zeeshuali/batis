# BATIS — Implementation Progress
_Last updated: 2026-05-09_

Complete inventory of every feature, endpoint, component, and data pipeline in BATIS — what works, what's broken, and what's missing.

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

- 511.org integration (any endpoint, any agency)
- Multi-agency support (BART, Muni, Caltrain, VTA, etc.)
- Real-time Stop Monitoring (live ETAs via SIRI)
- Cross-agency on-time benchmarking
- Transfer reliability scoring
- Stop Observations archive ingestion
- Toll-transit correlation
- Work Zone / traffic event impact on transit
- Fare calculator (GTFS Fares v2)
- Accessibility gap analysis
- Any automated tests (zero backend tests, zero frontend tests)
- Rate limiting
- CORS from env var
- Pagination on coverage cells endpoint
- Real APC (automatic passenger counting) data

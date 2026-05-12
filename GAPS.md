# BATIS — Project Gap Analysis
_Generated: 2026-05-09_

This document summarises every gap, bug, incomplete feature, and integration opportunity found in the BATIS codebase after a full review of all backend services, API routes, ML pipeline, database schema, and frontend components.

Gaps are grouped by severity: 🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low / Enhancement.

---

## Table of Contents
1. [511.org Integration (missing entirely)](#1-511org-integration-missing-entirely)
2. [Missing / Broken Dependencies](#2-missing--broken-dependencies)
3. [Security Issues](#3-security-issues)
4. [Incomplete Implementations](#4-incomplete-implementations)
5. [Schema vs. Code Mismatches](#5-schema-vs-code-mismatches)
6. [Missing Error Handling](#6-missing-error-handling)
7. [Hardcoded Values](#7-hardcoded-values)
8. [Performance Issues](#8-performance-issues)
9. [Frontend–Backend Disconnects](#9-frontendbackend-disconnects)
10. [Missing Tests](#10-missing-tests)
11. [Missing Input Validations](#11-missing-input-validations)
12. [Minor / Code Quality](#12-minor--code-quality)

---

## 1. 511.org Integration (missing entirely)

**Status: 🔴 Critical — user has a 511.org token in `.env` but zero integration exists in the codebase.**

511.org is the MTC (Metropolitan Transportation Commission) regional API at `https://api.511.org`. It covers every Bay Area transit agency — BART, Muni, VTA, Caltrain, SamTrans, AC Transit, and ~25 others — under a single API key. BATIS currently speaks directly to AC Transit's own API only. Six specific integration opportunities:

### 1a. Multi-agency GTFS-RT Vehicle Positions
- **URL**: `GET https://api.511.org/transit/VehiclePositions?api_key={key}&agency={id}`
- **Action**: Add `FIVE11_API_KEY` and `FIVE11_BASE_URL` to `config.py`. Refactor `gtfs_rt_ingestor.py`'s `_build_url()` to accept a base-URL override. Add an `agency_id` column to `rt_vehicle_positions_raw` and loop over a configurable list of agency IDs (AC Transit, BART, Muni, etc.).
- **Impact**: Extends the live vehicle map from AC Transit–only to all Bay Area operators.

### 1b. Multi-agency GTFS Static Feeds
- **URL**: `GET https://api.511.org/transit/datafeeds?api_key={key}&operator_id={id}`
- **Action**: `gtfs_static_url` in `config.py` is already configurable; just change the URL. For multi-agency, loop over operator IDs and tag each GTFS row with its `agency_id`.
- **Impact**: Route Explorer and trip planner would show BART, Muni, Caltrain etc. alongside AC Transit.

### 1c. Real-time Departures via Stop Monitoring (SIRI)
- **URL**: `GET https://api.511.org/transit/StopMonitoring?api_key={key}&agency={id}&stopCode={code}&Format=json`
- **Action**: Replace (or supplement) the `get_realtime_departures` function in `analysis.py`, which currently joins `gtfs_stop_times` + `ops_trip_events` to estimate departures. 511.org Stop Monitoring returns live ETAs directly.
- **Impact**: The Stop Drawer would show actual real-time arrival predictions instead of scheduled + delay overlay.

### 1d. Multi-agency Service Alerts
- **URL**: `GET https://api.511.org/transit/ServiceAlerts?api_key={key}&agency={id}`
- **Action**: Refactor `alerts_loader.py` to accept an agency list and aggregate alerts. `AlertsBanner.tsx` already renders an array of alerts — no frontend changes needed.
- **Impact**: Alerts banner would show BART, Muni, and AC Transit alerts simultaneously.

### 1e. Occupancy / Crowding (OccupancyStatus in VehiclePositions)
- **Action**: The `occupancy_status` column already exists in `rt_vehicle_positions_raw` (schema.sql). The 511.org VehiclePositions feed includes `OccupancyStatus` for agencies that publish it. The ingestor already writes this field — the data just isn't flowing in because 511.org isn't the source yet.

### 1f. Regional GTFS for Coverage Analysis
- **Action**: `coverage_builder.py`'s `_BBOX` and `equity_loader.py`'s `_COUNTIES` are both AC Transit–centric. Once 511.org static feeds are loaded, broaden both constants to cover the full 9-county Bay Area.

---

## 2. Missing / Broken Dependencies

### 2a. `sentence_transformers` and `httpx` not in `requirements.txt` 🔴 Critical
`main.py` imports `ml/embed.py` and `app/services/ai_assistant.py` at startup. Both import `sentence_transformers` and `httpx`. Neither is listed in `requirements.txt`.

```
# Current requirements.txt is missing:
sentence-transformers>=2.7
httpx>=0.27
```

**Result**: `pip install -r requirements.txt && uvicorn app.main:app` crashes immediately on a clean install.

**Fix**: Add both to `requirements.txt`.

### 2b. `pandas` listed but usage unclear 🟡 Medium
`pandas==2.2.3` is in `requirements.txt` but not imported in any of the main service files. Audit `gtfs_static_loader.py` and `seed_from_static.py`; if not needed, remove it (heavy dependency).

---

## 3. Security Issues

### 3a. `verify=False` on all outbound HTTP calls 🔴 Critical
Every service that calls an external API (`alerts_loader.py`, `safety_incidents_loader.py`, `equity_loader.py`, `gtfs_rt_ingestor.py`, `gtfs_static_loader.py`) passes `verify=False` to `requests.get()`. This disables SSL certificate verification, making every outbound connection vulnerable to MITM attacks.

Only `gtfs_static_loader.py` has a comment acknowledging this is a WSL dev workaround. The others have no comment at all.

**Fix**: Remove `verify=False` from all production code paths. Use `certifi.where()` if the WSL cert chain is broken:
```python
import certifi
requests.get(url, verify=certifi.where())
```

### 3b. SQL injection risk in AI assistant 🔴 Critical
`ai_assistant.py` lines 33–34 interpolate the embedding vector directly into a SQL f-string:
```python
emb_str = str(embedding.tolist())
query = f"... embedding <=> '{emb_str}'::vector ..."
```
While the vector comes from the local ML model (not user input today), this completely bypasses SQLAlchemy's parameterisation. If the model returns unexpected output, the query breaks — and future code changes could introduce a real injection vector.

**Fix**: Use SQLAlchemy's `cast` or a register vector type:
```python
conn.execute(text("... embedding <=> :emb ::vector ..."), {"emb": str(embedding.tolist())})
```

### 3c. `BACKEND_API_KEY` disabled by default with no warning 🟠 High
`security.py` returns immediately if `BACKEND_API_KEY` is not set. No log warning, no `/health` indication. The API is completely open without the operator knowing.

**Fix**: Log a `WARNING` at startup if the key is absent. Show `"auth_enabled": False` in `/health`.

### 3d. Sensitive data exposed on public endpoints 🟠 High
- `GET /health` returns `gtfs_static_url` (exposes feed URL) to unauthenticated callers.
- `GET /ai/status` returns Ollama model inventory to unauthenticated callers.
- `GET /ai/ask` accepts unbounded `top_k` int without validation — `int("abc")` raises unhandled `ValueError`.

### 3e. Hardcoded default database password 🟠 High
`config.py` line 6:
```python
database_url: str = "postgresql://postgres:password@localhost:5432/bay_area_transit_intel"
```
The default value contains a real password string. Even as a default, this is a security anti-pattern.

**Fix**: Use `postgresql://postgres:@localhost:5432/bay_area_transit_intel` or raise an error if `DATABASE_URL` is unset.

### 3f. CORS origins hardcoded to localhost 🟠 High
`main.py` lines 89–90:
```python
allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"]
```
Any production deployment (Vercel, Netlify, custom domain) will fail CORS without a code change.

**Fix**: Add `CORS_ORIGINS: list[str]` to `config.py` and read it from `.env`.

---

## 4. Incomplete Implementations

### 4a. `/stops/{stop_id}/reachability` ignores `minutes` parameter 🔴 Critical
The endpoint accepts `minutes: int = Query(30, ge=10, le=90)` but the underlying `get_stop_reachability()` function completely ignores it. It returns a convex hull of all stops on all serving routes regardless of travel time.

**Fix**: Implement actual reachability: compute cumulative travel time along routes using `gtfs_stop_times.departure_time` and filter stops reachable within the budget.

### 4b. Bunching map section shows wrong data 🟠 High
The `bunching` frontend section switches to the `reliability` map layer (`/reliability/stops/geo`), not a bunching-specific layer. There is no `/bunching/stops/geo` endpoint and no per-stop bunching visualisation on the map.

**Fix**: Add a `/bunching/stops/geo` endpoint returning per-stop `delay_stddev` from `bunching_predictions`, and add a `bunching-stops` map source/layer in `MapView.tsx`.

### 4c. `get_route_headways` ignores date range 🟡 Medium
The endpoint accepts `start_date`/`end_date` query params but the backend function only uses a single `service_date` (defaulting to `end_date` or today). The frontend `RouteHeadwayChart` sends both dates expecting a range.

**Fix**: Update `get_route_headways()` in `analysis.py` to accept and apply `start_date`/`end_date` with a `BETWEEN` filter.

### 4d. `populate_equity_columns` is always a no-op 🔴 Critical
`equity_loader.py` updates `coverage_cells WHERE population > 0`. However, the `population` column in `coverage_cells` is never written by `build_coverage_cells()` — it remains NULL/0 forever. The entire equity scoring update silently does nothing.

**Fix**: Either populate `population` in `build_coverage_cells()` via a Census join, or change the `WHERE population > 0` filter to `WHERE 1=1` (update all cells) and document that it is a county-average approximation.

### 4e. Ollama model version inconsistency 🟡 Medium
Three places reference different model versions:
- `ai_assistant.py`: `OLLAMA_MODEL = "llama3.1:8b"`
- `ai_assistant.py` `get_status()` hint: `"llama3.2:11b"`
- `AiAssistant.tsx` banner: `ollama pull llama3.1:8b`
- Module docstring in `ai_assistant.py`: `"Llama 3.2 11B"`

**Fix**: Add `OLLAMA_MODEL` to `config.py`, read it from `.env`, and reference the single setting everywhere.

---

## 5. Schema vs. Code Mismatches

### 5a. `coverage_cells.population` never populated 🔴 Critical
(See 4d above.) Schema defines the column; nothing ever writes it.

### 5b. `crowding_predictions` table defined twice 🟠 High
- Defined in `schema.sql` (line 266) with a performance index.
- Also created via `CREATE TABLE IF NOT EXISTS` inside `generate_crowding_predictions_from_demand()` in `models_demand_crowding.py` (line 103) — without the index.

If the model runs before `schema.sql` is applied (fresh DB), the table exists without the index and queries will be slow.

**Fix**: Remove the in-code `CREATE TABLE IF NOT EXISTS` from the service file; rely on `schema.sql` exclusively.

### 5c. `ops_trip_events.delay_seconds` type used inconsistently 🟡 Medium
Schema defines it as `integer`. `models_demand_crowding.py` uses it as a float proxy for boardings, and the baseline predictor uses `PERCENTILE_CONT` returning `double precision`. Semantically the column is delay in seconds but is being reused as a proxy for demand — these are different things.

**Fix**: Add a separate `estimated_boardings integer` column to `ops_trip_events`, or to a derived table; stop reusing `delay_seconds` for demand.

### 5d. `ai_embeddings` dimension mismatch risk 🟡 Medium
Schema hardcodes `vector(384)` for `all-MiniLM-L6-v2`. If `EMBED_MODEL_NAME` is changed to a different-dimension model, inserts silently truncate or fail.

**Fix**: Document the embedding dimension in `config.py` and validate it at startup against the schema column definition.

### 5e. `stop_features` table never read by any API 🟢 Low
`stop_features.avg_headway_peak` / `avg_headway_offpeak` and other ML feature columns are populated by `features_builder.py` but no API endpoint exposes them. They exist only for potential future ML models.

---

## 6. Missing Error Handling

### 6a. `bbox` parsing raises HTTP 500 instead of 400 🟠 High
`/coverage/cells` and `/coverage/deserts` (main.py lines 156 and 173):
```python
bbox_coords = [float(p) for p in bbox.split(",")]
```
A malformed `bbox=bad,bbox` raises an unhandled `ValueError` → HTTP 500 with raw traceback.

**Fix**:
```python
try:
    bbox_coords = [float(p) for p in bbox.split(",")]
    assert len(bbox_coords) == 4
except (ValueError, AssertionError):
    raise HTTPException(status_code=400, detail="bbox must be 'min_lon,min_lat,max_lon,max_lat'")
```

### 6b. `alerts_loader.py` silently swallows all errors 🟠 High
```python
except Exception:
    return []
```
Callers receive empty alerts with no indication of failure. The issue could be a wrong URL, expired token, or network outage — all invisible.

**Fix**: Log the exception at `ERROR` level before returning `[]`.

### 6c. `run_data_jobs.py` pipeline steps 2–7 have no error protection 🟠 High
Steps 1, 8, 10, 11 are wrapped in try/except. Steps 2–7 (snapshots, features, headways, predictions, safety, coverage) are bare function calls. A failure in any of them stops the entire pipeline with an unhandled exception.

**Fix**: Wrap each step in its own try/except with logging, so the pipeline continues to subsequent steps when one fails.

### 6d. Batch insert loses data if mid-batch failure occurs 🟠 High
`safety_incidents_loader.py`: DELETE succeeds, then INSERT fails mid-batch → data is gone with no recovery.

**Fix**: Wrap DELETE + INSERT in a single transaction; if INSERT fails, the DELETE is rolled back.

### 6e. Per-trip DELETE loop in GTFS-RT ingestor 🟡 Medium
`gtfs_rt_ingestor.py` issues one DELETE per active trip per 30-second poll cycle (potentially 200+ DELETEs). See also §8a.

---

## 7. Hardcoded Values That Should Be Configurable

| Value | Location | Should be in |
|-------|----------|-------------|
| `OLLAMA_URL = "http://localhost:11434"` | `ai_assistant.py` | `config.py` → `.env` |
| `OLLAMA_MODEL = "llama3.1:8b"` | `ai_assistant.py` | `config.py` → `.env` |
| `EMBED_MODEL_NAME = "all-MiniLM-L6-v2"` | `ml/embed.py` | `config.py` → `.env` |
| `_BBOX` (AC Transit bounding box + grid step) | `coverage_builder.py` | `config.py` |
| `_COUNTIES = ["06001", "06013"]` | `equity_loader.py` | `config.py` |
| `OAKLAND_CRIME_URL` / `OAKLAND_COLLISION_URL` | `safety_incidents_loader.py` | `config.py` |
| `_PAGE_SIZE = 1000` | `safety_incidents_loader.py` | `config.py` |
| `retain_days = 30` | `gtfs_rt_ingestor.py` | `config.py` |
| `poll_interval_seconds=30` | `main.py` background threads | `config.py` |
| `interval_seconds=1800` (embed/baseline loops) | `main.py` background threads | `config.py` |
| `TOP_K = 6`, `MAX_CONTEXT_CHARS = 4000` | `ai_assistant.py` | `config.py` |
| `_CENSUS_API = ".../2022/acs/acs5"` | `equity_loader.py` | `config.py` (year) |
| CORS origins | `main.py` | `config.py` → `.env` |

---

## 8. Performance Issues

### 8a. Per-trip DELETE loop (N×200 queries per 30s poll) 🟠 High
`gtfs_rt_ingestor.py` `_process_trip_updates()` issues one individual `DELETE FROM ops_trip_events WHERE service_date=... AND trip_id=...` per active trip inside a Python `for` loop. With 200 active trips, that is 200 sequential DELETE statements every 30 seconds.

**Fix**:
```sql
DELETE FROM ops_trip_events
WHERE (service_date, trip_id) = ANY(ARRAY[...])
```

### 8b. No index on `ops_trip_events.stop_id` 🟠 High
Multiple high-traffic queries filter on `stop_id` alone:
- `get_stop_detail` delay history: `WHERE stop_id = :stop_id GROUP BY service_date`
- Safety geo join: `JOIN ops_trip_events e ON e.stop_id = s.stop_id`

The existing indexes cover `(service_date, route_id)` and `(trip_id, stop_sequence)` but not `stop_id`.

**Fix**: `CREATE INDEX ops_trip_events_stop_id_idx ON ops_trip_events(stop_id);`

### 8c. No index on `ops_trip_events.actual_arrival` 🟡 Medium
`get_route_headways` window function orders by `actual_arrival` per stop — no index supports this.

**Fix**: `CREATE INDEX ops_trip_events_actual_arrival_idx ON ops_trip_events(actual_arrival);`

### 8d. No index on `safety_incidents_raw.occurred_at` 🟡 Medium
`get_stop_detail` nearby incidents query orders by `occurred_at DESC` — no index.

**Fix**: `CREATE INDEX safety_incidents_raw_occurred_at_idx ON safety_incidents_raw(occurred_at DESC);`

### 8e. `get_coverage_cells` returns entire grid with no pagination 🟡 Medium
With no `bbox`, `/coverage/cells` returns the entire hex grid (potentially tens of thousands of GeoJSON polygons) in a single HTTP response.

**Fix**: Require `bbox` or add a hard row limit (e.g., `LIMIT 5000`) with a `Link: next` header or cursor.

### 8f. `embed.py` stop builder truncates silently at 2000 rows 🟡 Medium
`_build_stop_texts()` uses `LIMIT 2000` with no pagination. Stop count will grow; embeddings beyond 2000 are never built.

**Fix**: Use cursor-based pagination or remove the LIMIT and batch by 500.

### 8g. `build_coverage_cells` is a single blocking transaction 🟡 Medium
One enormous CTE with multiple LATERAL joins over the full stop list. On a large GTFS feed this can take minutes, blocking other DB writes.

**Fix**: Split into batched inserts or use `CREATE TEMP TABLE` staging.

---

## 9. Frontend–Backend Disconnects

### Endpoints with no frontend UI

| Endpoint | What it returns |
|----------|----------------|
| `GET /reliability/route/{route_id}` | Per-trip/per-stop reliability for a specific route and date |
| `GET /reliability/predictions` | Full delay predictions table |
| `GET /safety/stops` (with `min_score`/`max_score` params) | Safety scores — params exist on API but never sent from UI |
| `GET /stops/{stop_id}/reachability` | Reachability hull — no UI trigger at all |
| `GET /ai/explain/{route_id}` | AI-generated route explanation — no button in frontend |
| `GET /crowding/predictions` | `time_bucket` + `trip_id` columns fetched but ignored |

### Frontend UI with no/wrong backend

| UI feature | Problem |
|-----------|---------|
| Heatmap toggle (MapView) | Adds `reliability-heat` layer outside `SECTION_LAYERS`; can persist visible after switching sections |
| Date range picker for `safety` + `coverage` sections | Both panels ignore `startDate`/`endDate` entirely |
| Route headway chart `start_date` | Backend ignores `start_date`; only `end_date` (as `service_date`) is used |
| Reliability CSV export | Exports only the 10 displayed worst routes, not all routes |
| Demand legend (MapView lines 133–137) | Three legend entries all have the same colour (`#a855f7`); demand uses radius not colour |
| Bunching map section | Shows reliability layer, not bunching — see §4b |

---

## 10. Missing Tests

**Backend**: Zero tests. No `tests/` directory, no pytest config, no fixtures.  
**Frontend**: Zero tests. Playwright is installed (`@playwright/test`) but no config and no test files.  
**Data pipeline**: No tests for `coverage_builder`, `equity_loader`, `safety_incidents_loader`, or any ML service.  
**Schema**: No idempotency test for `schema.sql`.

Suggested priority test additions:
1. FastAPI endpoint smoke tests with a test DB (pytest + `httpx.AsyncClient`)
2. Unit tests for `analysis.py` query functions with mock connections
3. `coverage_builder` unit test verifying grid generation bounds
4. Playwright E2E: load the map, click a stop, verify the Stop Drawer opens

---

## 11. Missing Input Validations

| Endpoint | Missing validation |
|---------|--------------------|
| `GET /reliability/*` | No `start_date <= end_date` check — inverted dates silently return 0 rows |
| `GET /reliability/*` | No maximum date range enforced — a 10-year range causes full table scans |
| `GET /coverage/*` | `bbox` not validated for `min < max` on both axes |
| `GET /reliability/summary` | `route_ids` array size unbounded |
| `POST /ai/ask` | `int(body.get("top_k", 6))` raises unhandled `ValueError` on non-numeric input |
| `GET /stops/{stop_id}/reachability` | `minutes` parameter is validated by FastAPI but completely ignored in implementation |
| `GET /trip-planner` | `lat`/`lng` not validated to be in physically valid ranges |
| Most `/{route_id}` and `/{stop_id}` endpoints | No 404 for nonexistent IDs — return empty array/object instead |

---

## 12. Minor / Code Quality

- **`void ALL_LAYERS;` (MapView.tsx line ~898)**: dead code to suppress an unused variable lint warning — remove or use the variable.
- **Multiple `// eslint-disable-line react-hooks/exhaustive-deps`** in `MapView.tsx`: suppresses missing-dependency warnings rather than fixing the hooks.
- **No ESLint config**: `"lint": "echo \"no lint configured\""` in `package.json`.
- **No Prettier config**: no consistent code formatting enforced.
- **`AlertsBanner.tsx` swallows fetch errors** (`.catch(() => {})`) — no user feedback.
- **`StopDrawer.tsx` swallows errors** (`.catch(() => setDetail(null))`) — user sees generic "Could not load stop details" regardless of error type.
- **`_get_model()` in `ml/embed.py`** has a startup race condition: two threads can both enter `if _model is None` simultaneously and load the model twice. Add a `threading.Lock`.
- **`_PAGE_SIZE = 1000`** in `safety_incidents_loader.py` stops at the first page. Oakland's crime dataset has >100,000 rows; only the first 1,000 are ever loaded. Add a pagination loop.
- **`ACTRANSIT_API_KEY`** named generically — rename to something that signals its scope (e.g., `ACTRANSIT_GTFS_RT_KEY`) so it is not confused with the planned `FIVE11_API_KEY`.

---

## Recommended Priority Order

| Priority | Action |
|----------|--------|
| 🔴 1 | Add `sentence-transformers` and `httpx` to `requirements.txt` — server crashes on clean install |
| 🔴 2 | Remove `verify=False` from all production HTTP calls |
| 🔴 3 | Fix SQL f-string in `ai_assistant.py` — use parameterised query |
| 🔴 4 | Fix `populate_equity_columns` no-op (`WHERE population > 0` always matches nothing) |
| 🟠 5 | Wire up `FIVE11_API_KEY` (user already has token): add to `config.py`, implement 511.org Stop Monitoring for real-time departures |
| 🟠 6 | Wrap pipeline steps 2–7 in `run_data_jobs.py` with individual try/except |
| 🟠 7 | Move CORS origins to `config.py` env var |
| 🟠 8 | Add `CREATE INDEX ops_trip_events_stop_id_idx` to `schema.sql` |
| 🟠 9 | Fix per-trip DELETE loop → batch DELETE in `gtfs_rt_ingestor.py` |
| 🟠 10 | Add 511.org multi-agency GTFS-RT for BART, Muni, VTA (extends map beyond AC Transit) |
| 🟡 11 | Move all hardcoded constants (Ollama URL/model, bbox, counties, page size) to `config.py` |
| 🟡 12 | Fix bunching map section to use bunching-specific endpoint |
| 🟡 13 | Remove in-code `CREATE TABLE` for `crowding_predictions` — rely on `schema.sql` |
| 🟡 14 | Fix `get_route_headways` to respect `start_date` |
| 🟡 15 | Add backend pytest suite with at least smoke tests for all 30 endpoints |
| 🟢 16 | Add Playwright E2E tests for map interactions |
| 🟢 17 | Configure ESLint + Prettier |
| 🟢 18 | Fix demand legend colours in `MapView.tsx` |
| 🟢 19 | Fix `AlertsBanner.tsx` and `StopDrawer.tsx` error handling |
| 🟢 20 | Add `_get_model()` threading lock in `ml/embed.py` |

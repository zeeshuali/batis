# BATIS — Claude Project Memory
_Last updated: 2026-11-10_

This file is Claude's persistent memory for the BATIS project. Read this at the start of every session before touching any code.

---

## What This Project Is

**BATIS** (Bay Area Transit Intelligence System) is a full-stack transit analytics platform for the San Francisco Bay Area. It is NOT a rider-facing app — it is an **operator/analyst dashboard** for transit planners, city staff, and equity researchers.

**Data sources**: 511.org regional API (30+ Bay Area agencies) is integrated; AC Transit direct GTFS-RT is legacy. Also Oakland open data (safety), Census ACS (equity).

The user has a **511.org API token stored in `backend/.env`** as `FIVE11_API_KEY` (or similar). The 511.org integration is **built** (verified 2026-11-09): `app/services/five11_{operators,rt_ingestor,stop_monitoring,stop_observations,traffic}.py`, workers `run_rt_ingestor`, `backfill_stop_observations`, `load_stop_observations`. ETL (`run_data_jobs.py`) is now 20 steps; step 13 loads last month's `stop_observations` if `FIVE11_API_KEY` is set. Built on top (Sprints 4a–5c): transfer reliability, fares v1/v2 + calculator, fare burden, service delivery gap map, ADA gap, transfer deserts, regional planning page. See `docs/superpowers/{specs,plans}/`.

---

## Stack

| Layer | Tech |
|-------|------|
| Backend | Python 3.12, FastAPI + Uvicorn, port 8000 (dev) |
| Database | PostgreSQL + PostGIS (geometry) + pgvector (embeddings) |
| ORM | SQLAlchemy 2.0, raw SQL via `text()` — NO ORM models used |
| ML | sentence-transformers (all-MiniLM-L6-v2), Ollama local (llama3.1:8b) |
| Frontend | React 18 + TypeScript, Vite + SWC, port 5173 (dev) |
| Map | Mapbox GL JS 3.x |
| Charts | Recharts |
| HTTP | Axios (frontend), requests (backend) |

Vite proxy: `/api` → `http://127.0.0.1:8002` (NOTE: backend runs on 8000, not 8002 — this proxy config is wrong and unused unless `VITE_API_BASE_URL=/api` is set in frontend `.env`)

---

## Project Layout

```
batis/
├── backend/
│   ├── .env                    ← DB URL, API keys (NEVER commit)
│   ├── requirements.txt        ← All deps including sentence-transformers, httpx, certifi, pytest
│   ├── app/
│   │   ├── main.py             ← All FastAPI routes (~55 route decorators as of 2026-11-09)
│   │   ├── db.py               ← Engine singleton
│   │   ├── core/
│   │   │   ├── config.py       ← Pydantic Settings (BACKEND_API_KEY missing here)
│   │   │   └── security.py     ← X-API-Key auth (disabled if key not set)
│   │   ├── services/           ← All business logic
│   │   └── workers/
│   │       └── run_data_jobs.py ← 20-step one-shot ETL pipeline
│   ├── ml/
│   │   ├── baseline.py         ← SQL delay predictor (runs every 30 min)
│   │   └── embed.py            ← RAG embedding pipeline (runs every 30 min)
│   └── sql/
│       └── schema.sql          ← Full DB DDL incl. pgvector + immutable generated columns on stop_observations
└── frontend/
    ├── .env                    ← VITE_MAPBOX_TOKEN, VITE_API_BASE_URL
    ├── src/
    │   ├── App.tsx             ← Root component, 11-section tab routing
    │   └── components/
    │       ├── MapView.tsx     ← Mapbox map, all GeoJSON layers
    │       ├── Sidebar.tsx     ← All data panels
    │       ├── AiAssistant.tsx ← RAG chat UI
    │       ├── AlertsBanner.tsx
    │       └── StopDrawer.tsx  ← Stop detail slide-in
    └── vite.config.ts
```

---

## Phase 0 Baseline (completed 2026-05-11)

The six critical bugs previously listed in this section have all been
fixed and locked in with regression tests, plus a seventh discovered
during the baseline run (PG 15 rejected timestamptz subtraction in
stored generated columns on `stop_observations`).

Plan: `docs/superpowers/plans/2026-05-11-batis-phase-0-bug-bash.md`.

To run the test suite:

```bash
docker compose up -d postgres-test
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

Current test count: **207 tests passing** (39 at Phase 0 close).

If a Phase 0 regression appears, the matching test in `backend/tests/`
will catch it before merge — schema lint and import smoke tests cover
the two bugs (pgvector extension, requirements.txt deps) that have no
runtime integration test.

Phase 1 (dashboard shell) is the next plan and will introduce the
frontend test substrate that StopDrawer currently lacks.

---

## Local DB state (updated 2026-11-10, after migration 010 + ETL re-run)

- `docker-compose.yml`: `postgres` (PostGIS 16, host port **5434**, persistent volume `batis_postgres_data`, creds `postgres`/`batis_dev`, `shm_size: 1gb`) and `postgres-test` (PostGIS 15, port **5433**, **tmpfs — wiped on stop**, used only by pytest).
- `backend/.env` `DATABASE_URL` points at the persistent DB on **5434**. Schema + migrations 001–010 are applied.
- Loaded: 621 routes, **20,260 stops** (185 stop_ids are shared by >1 agency), 90k trips, 3.17M stop_times (29 of 30 monitored agencies; **CR = Santa Cruz METRO has no 511 GTFS feed** and is reported as skipped), 1,772 census tracts + ambulatory, 2,629 fare products, 2,350 coverage cells, fare_burden, service_delivery_gap (688), per-stop features/safety/ADA gap (20,260 each).
- `stop_observations`: **52.4M rows, 2026-09 and 2026-10** (about 0.3% have no stop_pk because the stop is missing from the feed; agency EM is unmonitored). The 12-month backfill (`python -m app.workers.backfill_stop_observations 12`, multi-hour, 60 req/hr) has not been run. Don't run two ETLs at once: the month-already-loaded check is not atomic and doubled this table once (fixed by deleting the second batch).
- **VIOLATION to remove (see rule 9, no synthetic data):** `ops_trip_events` (82,416 rows) was seeded from the static schedule with random delays for agency `3D` only, and `rt_vehicle_positions_raw` is empty. Delay/bunching/demand/crowding outputs derived from it are not real. Fix: remove the seed fallback, purge those rows and derived tables, and rebuild from the RT ingestor and `stop_observations`.
- `transfer_reliability` is empty by design until it is reworked to match stops spatially.
- **pgvector is not installed** in the `postgis/postgis:16` image, so `ai_embeddings` does not exist and the AI assistant's RAG is inactive.
- Berkeley crime data fetch returns 403 (skipped); only Oakland incidents feed safety scores.
- Backup taken before migration 010: `~/batis-backups/pre-010-*.dump` (all tables except stop_observations data).
- Rebuild order: `docker compose up -d postgres` → apply `sql/schema.sql` → `python -m app.workers.run_data_jobs`. For a DB created before migration 010 apply `sql/migrations/010_stop_surrogate_key.sql`, then `ALTER TABLE gtfs_stop_times VALIDATE CONSTRAINT gtfs_stop_times_stop_pk_fkey;`.
- Logs: worker entry points and the API call `app.core.redact.install_redaction()` so `api_key=`/`token=` values are scrubbed from stdout/stderr/logging (requests puts the full URL in HTTPError text).

## Data Flow Overview

```
511.org API ───────────────────────────────────────────┐
AC Transit API (GTFS-RT) → gtfs_rt_ingestor.py         │
                         → rt_vehicle_positions_raw     │
                         → ops_trip_events              │
                                                        │
GTFS static (zip)    → gtfs_static_loader.py            │
                     → gtfs_routes, gtfs_stops,         │
                       gtfs_trips, gtfs_stop_times,     │
                       gtfs_shape_geoms                 │
                                                        │
Oakland Open Data    → safety_incidents_loader.py       │
                     → safety_incidents_raw             │
                     → stop_safety_scores               │
                                                        │
Census ACS           → equity_loader.py                 │
                     → coverage_cells.equity_score      │
                                                        ▼
                                            FastAPI (~55 endpoints)
                                                   │
                                            React Frontend
                                            (Mapbox + Recharts)
```

---

## 511.org API Reference (Key Endpoints)

Base URL: `https://api.511.org`
Auth: `?api_key={FIVE11_API_KEY}` query param

| Endpoint | What it returns |
|----------|----------------|
| `/Transit/VehiclePositions?agency=RG` | GTFS-RT vehicle positions for ALL Bay Area agencies |
| `/Transit/TripUpdates?agency=RG` | GTFS-RT trip updates for ALL Bay Area agencies |
| `/transit/servicealerts?agency=RG` | GTFS-RT alerts for ALL Bay Area agencies |
| `/transit/StopMonitoring?agency={id}&monitoringref={stop}` | Live ETAs at a stop (SIRI) |
| `/transit/VehicleMonitoring?agency={id}` | Live vehicle locations (SIRI) |
| `/transit/operators` | List of all 30+ covered agencies with IDs |
| `/transit/lines?operator_id={id}` | Routes for an operator |
| `/transit/stops?operator_id={id}` | Stops for an operator |
| `/transit/datafeeds?operator_id={id}` | Download GTFS zip for any operator |
| `/transit/datafeeds?operator_id=RG&historic=2023-01-so` | Monthly stop_observations archive (actual arrival times) |
| `/traffic/events` | Active + planned road incidents |
| `/traffic/wzdx` | Work zone road closures |
| `/toll/programs` | Bay Bridge + Express Lane toll rates |

Agency codes: `AC`=AC Transit, `BA`=BART, `SF`=Muni/SFMTA, `CT`=Caltrain, `SM`=SamTrans, `GG`=Golden Gate, `WH`=WETA Ferry, `VN`=VTA

Rate limit: 60 req/3600s (1/min). Email for higher limits.

**Unique asset**: `stop_observations.txt` in the historic monthly GTFS download — actual vs. scheduled arrival times at every stop for all agencies, March 2022–present. ~500MB/month compressed.

---

## Environment Variables Required

```bash
# backend/.env
DATABASE_URL=postgresql://postgres:password@localhost:5432/bay_area_transit_intel
ACTRANSIT_API_KEY=...              # AC Transit GTFS-RT token
FIVE11_API_KEY=...                 # 511.org regional API token (USER HAS THIS)
GTFS_STATIC_URL=https://opendata.actransit.org/transitdata/google_transit.zip
GTFS_RT_VEHICLE_POSITIONS_URL=...  # or leave blank to use 511.org
GTFS_RT_TRIP_UPDATES_URL=...       # or leave blank to use 511.org
BACKEND_API_KEY=...                # Optional: X-API-Key for all protected endpoints

# backend/.env additions needed
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
EMBED_MODEL_NAME=all-MiniLM-L6-v2
CORS_ORIGINS=http://localhost:5173

# frontend/.env
VITE_MAPBOX_TOKEN=...
VITE_API_BASE_URL=/api             # Use Vite proxy
VITE_API_KEY=...                   # X-API-Key for frontend requests
```

---

## Coding Conventions

- All backend DB access uses raw SQL via `SQLAlchemy text()` — no ORM, no models
- All geometry uses PostGIS: `geometry(Point, 4326)` for lat/lon points; cast to `::geography` for metric distance operations
- API responses are either plain dicts/lists or GeoJSON FeatureCollections
- Frontend fetches use `axios` with `apiHeaders()` helper for the API key
- All background tasks run as daemon threads (not asyncio tasks)
- The `config.py` Settings class uses `pydantic-settings` — add new env vars there, not via `os.getenv()`
- **Multi-agency JOINs:** every JOIN between `gtfs_routes`, `gtfs_trips`,
  `gtfs_stop_times`, `gtfs_shapes`, `gtfs_shape_geoms` must include
  `agency_id` in the ON clause. PKs are composite `(agency_id, <id>)` as
  of migration 009; joining on `<id>` alone compiles but silently
  cross-bleeds between agencies whenever a route_id/trip_id/shape_id
  label is shared (e.g. SF Muni and Santa Clara VTA both use route_id
  "31").
- **Stops use a surrogate key (migration 010):** `gtfs_stops.stop_pk` is the
  PK; `UNIQUE (agency_id, stop_id)` is the natural key and the loader's
  upsert target. `stop_id` repeats across agencies, so **join on `stop_pk`,
  never on `stop_id` alone**. Every table that references a stop carries
  `stop_pk` (stop_times, ops_trip_events, stop_observations, stop_ada_gap,
  stop_features, stop_safety_scores, delay/crowding/demand predictions,
  trip_stop_snapshots); the text `stop_id` stays for display and 511 API
  calls. Writers resolve it with
  `(SELECT stop_pk FROM gtfs_stops WHERE agency_id = .. AND stop_id = ..)`.
  HTTP stop endpoints accept optional `?agency_id=` to disambiguate.
  `transfer_reliability` still matches the same stop_id label across agencies
  (to be redone spatially). Plan:
  `docs/superpowers/plans/2026-11-10-stop-surrogate-key.md`.
- **Tests must not touch the dev DB:** `tests/conftest.py` pins
  `DATABASE_URL` to the 5433 test DB. Don't put `;` inside `--` comments in
  `schema.sql` (the test loader splits on semicolons).

---

## What Claude Should Always Do In This Project

1. **Check PROGRESS.md first** before suggesting new features — many things are already in progress or broken.
2. **Check BLUEPRINT.md** for the agreed feature roadmap before adding new endpoints or components.
3. **Never use `verify=False`** in any new code — use `certifi.where()` or proper SSL.
4. **Always cast geometry to `::geography`** when computing distances in meters.
5. **Add new env vars to `config.py` Settings class** — not `os.getenv()` inline.
6. **Never add hardcoded values** — all URLs, thresholds, model names go in config.py.
7. **Add `sentence-transformers` and `httpx` to requirements.txt** if touching the AI pipeline.
8. When adding new FastAPI routes, place more specific paths (e.g., `/routes/compare`) BEFORE parameterised ones (e.g., `/routes/{route_id}/geo`).
9. **NEVER use synthetic data. Always use live data.** No seeded, random, mock or placeholder rows in the database, ETL, or UI. If live data is missing from the DB, read the logs of the step that should have filled it (ETL output, loader errors, API responses, `docker logs batis-postgres-1`), find the root cause, fix it, re-run, and verify row counts and sources. An honest empty/"no data" state beats fake numbers. Only `backend/tests/` fixtures in the throwaway test DB may use hand-made rows. (Known violation to remove: `app/services/seed_from_static.py`, called from `app/workers/run_data_jobs.py` when `ops_trip_events` is empty; it fills `ops_trip_events` with random delays for agency 3D.)

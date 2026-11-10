# BATIS Changelog

Newest first. **Rule:** after every change, update this file, PROGRESS.md, CLAUDE.md and memory in the same turn (CLAUDE.md rule 10).

## 2026-11-10

### Process rule
- Added CLAUDE.md rule 10: after every change, update memory, documents and the changelog before reporting done, and commit them with the change.

### Backfill respects the 511 limit and retries at the next run
- Before each month the worker checks the remaining 511 budget from `api_call_log`. Below `stop_obs_backfill_min_budget` (10) it stops without error and prints that the next scheduled run retries, so the live poll keeps its share. A month that fails (for example HTTP 429) stays "missing" and is retried by the next 03:00 run, so history builds gradually. Tests: 230 backend.

### Backfill now loads 2 months per night
- `stop_obs_backfill_months_per_run` default 1 -> 2. The worker commits each month in its own transaction, so a failure in the second month keeps the first, and it stops after a failure or when nothing is left. 9 months remain, so about 5 nights. Tests: 229 backend (+3).

### First backfill month loaded (task 7)
- **2026-08 loaded: 25,768,104 rows, all 30 agencies, 99.6% with stop_pk.** First run took about 38 min, of which roughly 15 min was the closing `UPDATE ... SET stop_pk` that rewrote every row and all 7 indexes.
- Fix: `_load_month_impl` now resolves `stop_pk` while inserting, from an in-memory map of `gtfs_stops`. The closing UPDATE remains only as a cheap fallback for stops missing from the map. Test added (226 backend).
- stop_observations now covers 2026-08, 2026-09 and 2026-10. Nine months remain; cron loads one per night.

### Dashboard discoverability
- The tab is now labelled **Backend** (was Status): http://localhost:5173/#status. The API root (`/` and `/api/` through the Vite proxy) now returns a JSON pointer to the dashboard and the status endpoints. New setting `frontend_url`.

### Reviewed the Status tab in a real browser (Playwright screenshots, dark and light)
- Fixed: the "Open issues" panel was 280 px tall when nearly empty (`.section__panel` min-height), live-query "running for" could be negative (now `clock_timestamp()`), Progress tab hidden for activities with nothing to show (database, scheduler, Ollama, Oakland, Census), null values removed from run detail chips.
- Fixed app-wide: `styles.css` hard-codes a dark body background, so in the light theme the main area stayed dark behind light cards. `.shell` now paints with `--color-bg-0`.
- No browser console errors on the Status tab. The API runs on 8001 for the Vite `/api` proxy.

### Changed: Status tab is now one card per backend activity, with drill-down
- New `app/services/activities.py` (catalog of 14 activities in 4 categories: Ingestion, Processing, External APIs, Infrastructure) and endpoints `GET /admin/activities` (cards) and `GET /admin/activities/{key}` (full breakdown). Each card shows status (ok, warn, error, running, idle), headline, metrics, a progress bar, schedule and next run. Clicking a card opens a panel with tabs: Overview, Progress, Runs, API calls, Data, Live queries (database), Service (Ollama), Errors, Config, Logs.
- Live progress: `job_run(...)` handles now have `.progress(...)` and `report_progress(...)` (writes `job_runs.details` immediately, throttled to every 3 s). The stop_observations loader reports phase, MB downloaded and rows inserted, so the backfill card shows e.g. "2026-08: parsing and inserting (6,500,000 rows), about 25% of a typical month" plus "2 of 12 months loaded". Its Progress tab lists every month in range (loaded, loading, waiting).
- ETL steps are recorded per step (title, duration, notes for failed or skipped steps). New job runs: `traffic_loop`, `transfer_reliability_compute`.
- Scheduler card reads the user's crontab (BATIS lines) and shows the next run. Database card shows size, connections, largest tables and live queries.
- The backfill worker now logs INFO lines to its log file.
- Tests: 225 backend, 115 frontend.

### Added: daily stop_observations backfill (task 7)
- `python -m app.workers.backfill_stop_observations` with no argument is now one small step: it loads the newest missing month, going back at most 12 months (`stop_obs_backfill_months_per_run`=1, `stop_obs_backfill_max_months_back`=12 in `config.py`). With nothing left it exits 0. `... N` keeps the old behaviour (N newest missing months).
- `backfill_step()` in `five11_stop_observations.py`; `load_month()` now takes a transaction-scoped advisory lock (727001), so a concurrent loader fails fast instead of double-loading a month.
- Cron: `scripts/cron_backfill_stop_observations.sh`, installed in the user crontab at 03:00 daily (`flock` on `/tmp/batis_stop_obs.lock`, 6 h timeout, log `backend/logs/backfill_stop_observations.log`). Each month adds about 10 GB to the DB (20 GB for Sep+Oct). 749 GB free.
- Tests: 219 backend (+2).

### Added: System Status dashboard (migration 012)
- Tables `api_call_log` and `job_runs`; helper `app/core/run_log.py` (`tracked_get`, `job_run`, `prune_run_log`). Every outbound `requests.get` in the 511, Oakland, Census and alerts loaders now goes through `tracked_get` (stores host + path, status, latency, error; never the query string, so API keys cannot reach the table).
- Jobs recorded: `rt_ingestor`, `baseline_predictor`, `embed_pipeline`, `stop_observations_load`, `etl_run_data_jobs`.
- Endpoints `GET /admin/status`, `/admin/api-calls`, `/admin/job-runs`. New UI tab **Status**: overall banner, checks, 511 budget meter, jobs (click for run history), API sources, data freshness, recent calls (errors-only and source filters, CSV export), threads and Ollama; auto-refresh every 30 s.
- Settings: `five11_rate_limit_per_hour`, `status_rt_stale_minutes`, `status_job_stale_minutes`, `run_log_retention_days`.
- Checked live: one real RT poll logged 2 calls to 511 (200, 300 ms and 825 ms) and 84,135 rows; the snapshot correctly flagged stale data before the poll and showed "latest position 1 min ago" after. No key material appears in any response.
- Tests: 217 backend (+6), 115 frontend (+3).

### Housekeeping (task 8)
- Docs corrected: `BACKEND_API_KEY` was already in `config.py`; the Vite proxy targets 8001, the docker-compose backend port, not 8002. Ollama now has `llama3.1:8b`.
- Note: the host restarted and the Docker containers had exited. `docker compose up -d postgres postgres-test` brought them back with data intact.

### Added: pgvector (task 6)
- `docker/postgres/Dockerfile`: postgis 16-3.4 plus `postgresql-16-pgvector` (pgdg sources pointed at apt-archive because bullseye is EOL). `docker-compose.yml` now builds it as `batis-postgres:16-postgis3.4-pgvector`. Same major version, so volume `batis_postgres_data` was reused and no data was lost.
- Created extension `vector` and `ai_embeddings` in the dev DB. First `run_embed_once()`: 621 routes, 2,000 stops (the pipeline's cap), 70 ops summaries from real RT data.
- Ollama on this machine has `qwen3.5:4b`, but config uses `llama3.1:8b`. Pull that model or set `OLLAMA_MODEL`.

### Changed: spatial transfer reliability (task 5, migration 011)
- Stops of different agencies are now matched by distance, not by `stop_id` label. New table `stop_transfer_links` holds every cross-agency pair within the largest radius (400 m) with `distance_m` (35,140 directed pairs). `transfer_reliability` is keyed by `(from_stop_pk, to_stop_pk)` and carries `distance_m`, `to_stop_id`.
- The radius is a read-time filter. Settings `transfer_radii_m` (50, 100, 150, 200, 300, 400), `transfer_default_radius_m` (150), `transfer_walk_speed_mps` (1.2). Walk time per pair = max(60 s, distance / speed).
- New `GET /transfers/radii`; `GET /transfers/reliability` takes `radius_m`. The Regional Planning panel has a radius selector.
- Source is `stop_observations` plus `ops_trip_events` (RT skipped for any agency/date already in `stop_observations`). The window ends at the newest data available.
- Dev DB check (2026-10-28..30): 19,151 pairs, ~2.6M observations. Muni Metro to BART station pairs dominate at 150 m, about 88% success and median gap about 6 min.
- Tests: 211 backend, 112 frontend.

### Fixed (live RT ingestion, task 4)
- `rt_vehicle_positions_raw` was empty for three reasons: (1) `workers/run_rt_ingestor.py` imported the deprecated AC-only `gtfs_rt_ingestor`; it now runs `five11_rt_ingestor`. (2) `_process_trip_updates` read `agency_id` before assigning it, so every poll crashed (bug from e489084). (3) the API polled every 30s, 4x the 511 limit of 60 req/hr; the interval is now `five11_rt_poll_seconds` (180) in `config.py`. The ingestor only runs while uvicorn or the worker is running.
- Trip-update schedule lookup and per-trip DELETE are now agency-aware (multi-agency JOIN rule).
- Verified with one live poll: 1,237 vehicle positions and 32,117 trip-update rows, 23 agencies, real delays. Added a regression test (208 tests).

### Removed
- `app/services/seed_from_static.py` and the seeding fallback in `run_data_jobs.py` (rule 9: no synthetic data).
- Berkeley crime fetch from `safety_incidents_loader.py` (out of scope; dataset returned HTTP 403).

### Data
- Truncated synthetic `ops_trip_events` (82,416 rows, agency 3D) and derived tables `trip_stop_snapshots`, `ops_headways`, `delay_predictions`, `bunching_predictions`, `demand_forecasts`, `crowding_predictions`. Backup: `~/batis-backups/pre-synthetic-purge-20261110.dump`.

### Added
- Stop surrogate key (migration 010, `stop_pk`) across services and tests; log redaction (`app/core/redact.py`). Commit `3f1e04c`.

### Tests
- 207 passing.

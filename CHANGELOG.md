# BATIS Changelog

The product's running memory. Newest first. **Rule (CLAUDE.md rule 10 and 11):** at the end of EVERY prompt, once the work is finished, add an entry here, even for read-only work (audits, investigations, answers that found something). Then update PROGRESS.md, CLAUDE.md and memory in the same turn.

## How to write an entry

```
### <short title>
- **Type:** Added | Changed | Fixed | Removed | Data | Docs | Audit | Decision
- **What:** what was done or found (names, counts, commit hashes)
- **Why:** the reason or the user's request
- **Verified:** how it was checked (test counts, live poll, query, or "not verified: ...")
- **Open:** follow-ups, or "none"
```
Type `Audit` is for read-only checks: say what was inspected, what was found, and the verdict. Keep the newest entry at the top of the newest date. Never delete old entries; correct them with a new entry.

## 2026-11-10

### Docs: PROGRESS.md and CHANGELOG.md cleaned up
- **Type:** Docs
- **What:** PROGRESS.md: replaced the run-on "Current status" paragraph with an open-tasks table (adds the 511 budget re-check, the Mapbox token / `backup-pre-scrub` branch, tasks 9 to 11), done list and notes; test counts 233 -> 237; Ollama "needs pulling" note removed (`llama3.1:8b` is installed); added the hidden Agency section (rendered by `AppShell`, reached from Overview drill-down or the URL hash, not in `TABS`). CHANGELOG.md: every 2026-11-10 entry now has a `Type`; bare headings ("Removed", "Data", "Added", "Tests") renamed to say what they cover; dangling "push result below" and the stale "Local main holds 26f6ef6" corrected (push succeeded, `main` == `origin/main`). No entry deleted.
- **Why:** User asked for a cleanup of both files.
- **Verified:** route count 62 (grep), 7 `TABS` plus `agency` in `AppShell`/`useUrlState`, migrations 001 to 012 present, `git status` shows `main` in sync with `origin/main`. Test counts taken from the 2026-11-10 changelog entry (237), not re-run. Docs only.
- **Open:** none. CLAUDE.md was fixed in the same pass (tab count text and 237 backend tests).

### Audit: what is the next task on the list
- **Type:** Audit
- **What:** Read PROGRESS.md "Current status" and the top of CHANGELOG.md. Open items: (1) re-check `five11_budget` (rolling hour, due about 1 h after the 511 budget fix); (2) keep the RT ingestor running so `ops_trip_events` fills, then rebuild snapshots, headways and predictions; (3) the nightly backfill has 7 months left (about 4 nights); (4) rotate the leaked 511 key (user action); (5) decide `AiAssistant.tsx` (add a tab or delete); (6) Ollama model note in PROGRESS is stale, CLAUDE.md says `llama3.1:8b` is present.
- **Why:** User asked "whats the next task on the list?".
- **Verified:** read-only, from docs only. No code, DB or live state checked.
- **Open:** none beyond the list above.

### 511 request budget exceeded (79 of 60 per hour)
- **Type:** Fixed
- **What:** The Backend dashboard check `five11_budget` was red. From `api_call_log`: RT poll 2 req per 180 s (40/h), traffic loop 3 req per 300 s (36/h), and `/alerts` calling 511 on every request with no cache (about 12/h from the banner) added up to about 88/h. Changes: `five11_rt_poll_seconds` 180 -> 300 (24/h); new `five11_traffic_poll_seconds` 900 (12/h) replacing the hardcoded 300 in `main.py`; new `five11_alerts_cache_seconds` 300 with an in-process cache in `alerts_loader.get_service_alerts` (failed fetches are not cached). Planned use is 48 of 60 per hour, leaving 12 for the nightly backfill (which skips below 10). Traffic activity schedule text and stale threshold (45 min) updated.
- **Why:** User said "fix errors". Of the errors listed on the dashboard this was the only live one: the 8 `route_id` failures were already fixed by `3d8b41f` (now rewritten hash, see history), and the 2 "Interrupted" rows are historic restarts.
- **Verified:** 237 backend tests pass (+4 in `tests/test_alerts_cache.py`, including one that checks the planned budget stays at least 10 under the limit). Restarted uvicorn (old PID 37104, new 66276, log `~/batis-uvicorn.log`); `/admin/activities` now reports "Every 300s" (RT) and "Every 900s" (traffic). Not yet verified: the live hourly count dropping below 60. The check uses a rolling hour, so it stays red until the earlier calls age out (about 1 h) and the traffic and RT loops are slower.
- **Open:** re-check `five11_budget` in about an hour. The 2 other dashboard "errors" (interrupted embed pipeline, interrupted backfill restart) are history, not live.

### First push to GitHub, Mapbox token scrubbed from history
- **Type:** Changed
- **What:** Added remote `origin` = `https://github.com/zeeshuali/batis` (public, was empty) and pushed `main`. Before pushing, a scan found the Mapbox public token (`pk.eyJ...`) in captured request URLs in `ui-audit/report.json` (added in the initial commit). Rewrote the local, unpushed history with `git filter-branch` to replace it with `pk.REDACTED`, so **every commit hash changed**; hashes quoted in this changelog, PROGRESS.md and the history section were remapped to the new ones. Local branch `backup-pre-scrub` still holds the old history (not pushed).
- **Why:** User asked to upload the code to that repo; the repo is public. Scan also checked tracked files for `.env`, dumps and keys: none (`.env` files are gitignored, only `.env.example` is tracked), and the 511, AC Transit and Mapbox values from the local `.env` files do not appear in any rewritten commit.
- **Verified:** `git grep pk.eyJ` over the rewritten `main` history: 0 hits. Push succeeded: local `main` equals `origin/main` (checked 2026-11-10).
- **Open:** the token was never pushed, but rotate or URL-restrict it in Mapbox if you want to be safe. Delete `backup-pre-scrub` once satisfied (it contains the token). Still pending: rotate the leaked 511 key.

### Push attempted, no git remote configured
- **Type:** Audit
- **What:** `git push` failed: the repo has no remote (`git remote -v` is empty). Nothing was pushed. Local `main` then held commit `26f6ef6` and the earlier ones (hash since rewritten, see the scrub entry above).
- **Why:** User asked to push the changelog work.
- **Verified:** `git remote -v` printed nothing, push error says to name a remote.
- **Open:** user must supply a remote URL (for example a GitHub repo) so it can be added with `git remote add origin <url>` and pushed.

### Audit: the 9 ingestor errors from the last 24 h
- **Type:** Audit
- **What:** Listed the `rt_ingestor` job runs with status error via `GET /admin/job-runs`. 8 are `NotNullViolation` on `ops_trip_events.route_id` (BART trip updates with no `route_id`, labelled agency AC), at 21:50, 21:53, 21:56, 22:00, 22:03, 22:06, 22:09 and 22:12 UTC, trips `BA:919134610` and `BA:111135410`. The 9th (20:55 UTC) is a job row left `running` when the API process stopped, reaped as "Interrupted".
- **Why:** User asked to see the errors after the ingestor was found already running inside uvicorn on port 8001 (PID 37104), so no second ingestor was started (it would double the 511 request rate).
- **Verified:** Fix commit `97e11d4` is timestamped 22:19 UTC (14:19 PST), 7 minutes after the last failed poll. The most recent run (about 01:30 UTC next day) was ok with 80,539 rows and no error rows after 22:12. So the 8 errors predate the fix and have not recurred. Code path not re-read this turn.
- **Open:** none.

### Docs: changelog turned into the product memory, history backfilled
- **Type:** Docs
- **What:** Added the entry template and the audit type above, a new CLAUDE.md rule 11 (changelog entry at the end of every prompt, including read-only work), and a "History before 2026-11-10" section at the bottom reconstructed from all 176 commits in `git log`.
- **Why:** User asked for a file that records every completed step, audit and feature so nothing is missed.
- **Verified:** Every date and commit in the history section comes from `git log --reverse`. Docs only, tests unchanged (233 backend, 115 frontend).
- **Open:** the 2026-11-09 commits are described in the entries further down under 2026-11-10 (RT ingestion fix, spatial transfers, pgvector, removals), because they were written together on 2026-11-10.

### ETL step count corrected
- **Type:** Docs
- `run_data_jobs.py` prints steps 0 to 17 labelled "n/20"; steps 18 to 20 do not exist. PROGRESS.md and CLAUDE.md now say so. Docs only, tests unchanged.

### PROGRESS.md tables rewritten from the code
- **Type:** Docs
- Replaced the stale May tables (11 old tabs, 29 endpoints, 11 ETL steps, B1 to B8 bugs, 24-agency note) with the current inventory: 7 tabs, 62 routes, 20-step ETL, threads, table population, and a closed-bug table. Legend now has ⏳ "needs data" so empty RT-derived tables are not read as bugs. Verified by grep: no `verify=False`, safety buffer in geography meters, `/routes/compare` ordered, pgvector in schema, CORS from settings. Found `AiAssistant.tsx` imported nowhere (no UI for `/ai/*`). Not verified: API rate limiting, Oakland pagination, and fresh DB row counts (no psql on host). Docs only, tests unchanged (233 backend, 115 frontend).

### Docs sync, PROGRESS.md reaffirmed as always-update
- **Type:** Docs
- User repeated: update PROGRESS.md always. Reworded CLAUDE.md rule header to name PROGRESS.md first. Fixed stale `stop_observations` months in CLAUDE.md (2026-06 to 2026-10, about 129M rows, per the batch 1 entry below) and noted it in PROGRESS.md. Docs only, no code or tests changed (233 backend, 115 frontend).

### Backfill batch 1 result (July + June) and a live-poll bug found during it
- **Type:** Data
- **2026-07: 25,714,079 rows, 2026-06: 25,383,237 rows, both ok, no errors.** July took 58 min (while the API threads were also running), June 29 min. `stop_pk` coverage 99.0 to 99.2% (a few stops are missing from today's GTFS). Only 28 agencies have data in June and July (30 from August). stop_observations now covers 2026-06 to 2026-10, about 129M rows. 7 months remain (about 4 nights).
- **Bug fixed: live RT poll failed intermittently** (8 failed polls from 21:50 UTC). BART trip updates have no `route_id`, so they were labelled agency AC and failed the NOT NULL `ops_trip_events.route_id` insert. That aborted the whole poll transaction and rolled back the vehicle positions too. No bad rows were stored. Fixes: agency now also comes from the `trip_id` prefix (unknown agency is skipped, not defaulted to AC), the route is looked up from `gtfs_trips` when the feed omits it (unresolvable trips skipped and counted as `skipped_no_agency` / `skipped_no_route` in the job details), and each poll stage runs in a SAVEPOINT so one failing stage can no longer discard the others.
- **Stuck "running" jobs fixed:** at API startup, `reap_interrupted_runs` marks leftover `running` rows of the API's own jobs (rt_ingestor, traffic_loop, baseline_predictor, embed_pipeline) as errors ("process stopped"). One orphan from an API restart had been showing as running for 1.5 h.
- Verified with a live poll: 1,972 vehicles, 83,969 trip-update rows, 0 errors, 3 skipped. Tests: 233 backend (+3).

### Process rule
- **Type:** Decision
- Added CLAUDE.md rule 10: after every change, update memory, documents and the changelog before reporting done, and commit them with the change.

### Backfill respects the 511 limit and retries at the next run
- **Type:** Changed
- Before each month the worker checks the remaining 511 budget from `api_call_log`. Below `stop_obs_backfill_min_budget` (10) it stops without error and prints that the next scheduled run retries, so the live poll keeps its share. A month that fails (for example HTTP 429) stays "missing" and is retried by the next 03:00 run, so history builds gradually. Tests: 230 backend.

### Backfill now loads 2 months per night
- **Type:** Changed
- `stop_obs_backfill_months_per_run` default 1 -> 2. The worker commits each month in its own transaction, so a failure in the second month keeps the first, and it stops after a failure or when nothing is left. 9 months remain, so about 5 nights. Tests: 229 backend (+3).

### First backfill month loaded (task 7)
- **Type:** Data
- **2026-08 loaded: 25,768,104 rows, all 30 agencies, 99.6% with stop_pk.** First run took about 38 min, of which roughly 15 min was the closing `UPDATE ... SET stop_pk` that rewrote every row and all 7 indexes.
- Fix: `_load_month_impl` now resolves `stop_pk` while inserting, from an in-memory map of `gtfs_stops`. The closing UPDATE remains only as a cheap fallback for stops missing from the map. Test added (226 backend).
- stop_observations now covers 2026-08, 2026-09 and 2026-10. Nine months remain; cron loads one per night.

### Dashboard discoverability
- **Type:** Changed
- The tab is now labelled **Backend** (was Status): http://localhost:5173/#status. The API root (`/` and `/api/` through the Vite proxy) now returns a JSON pointer to the dashboard and the status endpoints. New setting `frontend_url`.

### Reviewed the Status tab in a real browser (Playwright screenshots, dark and light)
- **Type:** Fixed
- Fixed: the "Open issues" panel was 280 px tall when nearly empty (`.section__panel` min-height), live-query "running for" could be negative (now `clock_timestamp()`), Progress tab hidden for activities with nothing to show (database, scheduler, Ollama, Oakland, Census), null values removed from run detail chips.
- Fixed app-wide: `styles.css` hard-codes a dark body background, so in the light theme the main area stayed dark behind light cards. `.shell` now paints with `--color-bg-0`.
- No browser console errors on the Status tab. The API runs on 8001 for the Vite `/api` proxy.

### Status tab is now one card per backend activity, with drill-down
- **Type:** Changed
- New `app/services/activities.py` (catalog of 14 activities in 4 categories: Ingestion, Processing, External APIs, Infrastructure) and endpoints `GET /admin/activities` (cards) and `GET /admin/activities/{key}` (full breakdown). Each card shows status (ok, warn, error, running, idle), headline, metrics, a progress bar, schedule and next run. Clicking a card opens a panel with tabs: Overview, Progress, Runs, API calls, Data, Live queries (database), Service (Ollama), Errors, Config, Logs.
- Live progress: `job_run(...)` handles now have `.progress(...)` and `report_progress(...)` (writes `job_runs.details` immediately, throttled to every 3 s). The stop_observations loader reports phase, MB downloaded and rows inserted, so the backfill card shows e.g. "2026-08: parsing and inserting (6,500,000 rows), about 25% of a typical month" plus "2 of 12 months loaded". Its Progress tab lists every month in range (loaded, loading, waiting).
- ETL steps are recorded per step (title, duration, notes for failed or skipped steps). New job runs: `traffic_loop`, `transfer_reliability_compute`.
- Scheduler card reads the user's crontab (BATIS lines) and shows the next run. Database card shows size, connections, largest tables and live queries.
- The backfill worker now logs INFO lines to its log file.
- Tests: 225 backend, 115 frontend.

### Daily stop_observations backfill (task 7)
- **Type:** Added
- `python -m app.workers.backfill_stop_observations` with no argument is now one small step: it loads the newest missing month, going back at most 12 months (`stop_obs_backfill_months_per_run`=1, `stop_obs_backfill_max_months_back`=12 in `config.py`). With nothing left it exits 0. `... N` keeps the old behaviour (N newest missing months).
- `backfill_step()` in `five11_stop_observations.py`; `load_month()` now takes a transaction-scoped advisory lock (727001), so a concurrent loader fails fast instead of double-loading a month.
- Cron: `scripts/cron_backfill_stop_observations.sh`, installed in the user crontab at 03:00 daily (`flock` on `/tmp/batis_stop_obs.lock`, 6 h timeout, log `backend/logs/backfill_stop_observations.log`). Each month adds about 10 GB to the DB (20 GB for Sep+Oct). 749 GB free.
- Tests: 219 backend (+2).

### System Status dashboard (migration 012)
- **Type:** Added
- Tables `api_call_log` and `job_runs`; helper `app/core/run_log.py` (`tracked_get`, `job_run`, `prune_run_log`). Every outbound `requests.get` in the 511, Oakland, Census and alerts loaders now goes through `tracked_get` (stores host + path, status, latency, error; never the query string, so API keys cannot reach the table).
- Jobs recorded: `rt_ingestor`, `baseline_predictor`, `embed_pipeline`, `stop_observations_load`, `etl_run_data_jobs`.
- Endpoints `GET /admin/status`, `/admin/api-calls`, `/admin/job-runs`. New UI tab **Status**: overall banner, checks, 511 budget meter, jobs (click for run history), API sources, data freshness, recent calls (errors-only and source filters, CSV export), threads and Ollama; auto-refresh every 30 s.
- Settings: `five11_rate_limit_per_hour`, `status_rt_stale_minutes`, `status_job_stale_minutes`, `run_log_retention_days`.
- Checked live: one real RT poll logged 2 calls to 511 (200, 300 ms and 825 ms) and 84,135 rows; the snapshot correctly flagged stale data before the poll and showed "latest position 1 min ago" after. No key material appears in any response.
- Tests: 217 backend (+6), 115 frontend (+3).

### Housekeeping (task 8)
- **Type:** Docs
- Docs corrected: `BACKEND_API_KEY` was already in `config.py`; the Vite proxy targets 8001, the docker-compose backend port, not 8002. Ollama now has `llama3.1:8b`.
- Note: the host restarted and the Docker containers had exited. `docker compose up -d postgres postgres-test` brought them back with data intact.

### pgvector installed (task 6)
- **Type:** Added
- `docker/postgres/Dockerfile`: postgis 16-3.4 plus `postgresql-16-pgvector` (pgdg sources pointed at apt-archive because bullseye is EOL). `docker-compose.yml` now builds it as `batis-postgres:16-postgis3.4-pgvector`. Same major version, so volume `batis_postgres_data` was reused and no data was lost.
- Created extension `vector` and `ai_embeddings` in the dev DB. First `run_embed_once()`: 621 routes, 2,000 stops (the pipeline's cap), 70 ops summaries from real RT data.
- Ollama on this machine has `qwen3.5:4b`, but config uses `llama3.1:8b`. Pull that model or set `OLLAMA_MODEL`.

### Spatial transfer reliability (task 5, migration 011)
- **Type:** Changed
- Stops of different agencies are now matched by distance, not by `stop_id` label. New table `stop_transfer_links` holds every cross-agency pair within the largest radius (400 m) with `distance_m` (35,140 directed pairs). `transfer_reliability` is keyed by `(from_stop_pk, to_stop_pk)` and carries `distance_m`, `to_stop_id`.
- The radius is a read-time filter. Settings `transfer_radii_m` (50, 100, 150, 200, 300, 400), `transfer_default_radius_m` (150), `transfer_walk_speed_mps` (1.2). Walk time per pair = max(60 s, distance / speed).
- New `GET /transfers/radii`; `GET /transfers/reliability` takes `radius_m`. The Regional Planning panel has a radius selector.
- Source is `stop_observations` plus `ops_trip_events` (RT skipped for any agency/date already in `stop_observations`). The window ends at the newest data available.
- Dev DB check (2026-10-28..30): 19,151 pairs, ~2.6M observations. Muni Metro to BART station pairs dominate at 150 m, about 88% success and median gap about 6 min.
- Tests: 211 backend, 112 frontend.

### Fixed (live RT ingestion, task 4)
- **Type:** Fixed
- `rt_vehicle_positions_raw` was empty for three reasons: (1) `workers/run_rt_ingestor.py` imported the deprecated AC-only `gtfs_rt_ingestor`; it now runs `five11_rt_ingestor`. (2) `_process_trip_updates` read `agency_id` before assigning it, so every poll crashed (bug from d65224f). (3) the API polled every 30s, 4x the 511 limit of 60 req/hr; the interval is now `five11_rt_poll_seconds` (180) in `config.py`. The ingestor only runs while uvicorn or the worker is running.
- Trip-update schedule lookup and per-trip DELETE are now agency-aware (multi-agency JOIN rule).
- Verified with one live poll: 1,237 vehicle positions and 32,117 trip-update rows, 23 agencies, real delays. Added a regression test (208 tests).

### Synthetic seeding and Berkeley fetch removed
- **Type:** Removed
- `app/services/seed_from_static.py` and the seeding fallback in `run_data_jobs.py` (rule 9: no synthetic data).
- Berkeley crime fetch from `safety_incidents_loader.py` (out of scope; dataset returned HTTP 403).

### Synthetic ops data purged
- **Type:** Data
- Truncated synthetic `ops_trip_events` (82,416 rows, agency 3D) and derived tables `trip_stop_snapshots`, `ops_headways`, `delay_predictions`, `bunching_predictions`, `demand_forecasts`, `crowding_predictions`. Backup: `~/batis-backups/pre-synthetic-purge-20261110.dump`.

### Stop surrogate key and log redaction
- **Type:** Added
- Stop surrogate key (migration 010, `stop_pk`) across services and tests; log redaction (`app/core/redact.py`). Commit `f81371e`.

### Test count at start of day
- **Type:** Docs
- 207 backend tests passing at the start of 2026-11-10.

---

## History before 2026-11-10 (reconstructed from `git log`, 2026-11-10)

_Written after the fact from commit subjects, not from per-change notes. The 2026-11-09 work (commits `8a7d7be` to `4ee31aa`) is described in the entries above under 2026-11-10._

### 2026-11-09
- `8a7d7be` Docs: marked the 511.org integration built, recorded local DB state, flagged PROGRESS.md stale.
- `f81371e` Stop surrogate key (migration 010), log redaction, `stop_pk` joins across services.
- `fc23d2c` Removed the Berkeley crime fetch (out of scope).
- `5a77392` Removed synthetic ops seeding, purged synthetic tables, added this CHANGELOG.
- `92292c7` Fixed live 511 RT ingestion (worker import, agency_id bug, poll interval, agency-aware lookups).
- `4c6691c` Spatial transfer reliability with a user-selectable radius (migration 011).
- `4ee31aa` pgvector via a custom postgres image, RAG embeddings enabled.

### 2026-05-13 (multi-agency data and Sprint 5b/5c)
- Sprint 5b: Service Delivery Gap Map finished. Migration 007 (`service_delivery_gap`, `stop_cell`), `backfill_last_n_months`, gap tier function, compute/feature/breakdown services, `tolerance_seconds` config, ETL step 15, `/equity/service-delivery-gap` endpoints (`5098436`), Planning sub-page (`2a04021`), acceptance sweep (`fa7d2a0`). Fix for the 511 edge-schema `stop_observations` (`8b6b56a`, 05-12).
- Sprint 5c: ADA Accessibility Gap Tracker. Spec and plan, migration 008, loaders for Census tracts (TIGERweb), GTFS pathways and ACS B18105 ambulatory data, gap scoring, stop and cell GeoJSON, drill-down, ETL grew by 5 steps, `/accessibility/gaps` endpoints, Planning → ADA Gap page, acceptance sweep, review fixes (`55fc2b5`).
- Foundation fix: GTFS composite primary keys `(agency_id, id)` (migration 009, `c98c82a`), with loader `ON CONFLICT` updates, regression tests, and agency-aware JOINs in analysis, ADA gap, smaller services, AI embeddings and frontend (`0b36998` to `239358c`). Sprint closed `82fd0b2`. ETL re-run after the migration (`25d058d`).

### 2026-05-12 (the big build day)
- **Phase 1 frontend (1b, 1c, 1d):** sections (Operations, Network, Equity & Safety, Benchmarks), shared types and format helpers, fetch errors surfaced, dark/light theme, URL-hash state, CSV export, trip planner moved into Network, MapView reads filter and selection contexts, Sidebar retired. Several field-name and CSS fixes (`50e6366`, `ad9daf0`, `72b63ac`).
- **511.org multi-agency integration** (`e012357`, Blueprint Sprints 1 and 2), AI assistant plus embedding pipeline (`839a2b7`), roadmap/prompts docs (`7432f62`), local `status_server.py` (`3ffcf81`, later superseded by the Backend tab).
- **Agencies catalog, Phase A and B:** agencies SQL and operators ingestor, `/agencies` endpoints, `AgenciesContext`, Agency drill-down section, Overview "By agency" card, searchable agency combobox with grouping.
- **Planning section, Phases 1 to 5b:** Diagnostics, Coverage (equity × access), Regional (MPO), Workbench, Scenarios table, CRUD and builder.
- **GTFS-RT ingestor fix** (`d65224f`): prefix-strip, delay clamp, null guard.
- **Sprint 4a:** transfer reliability matrix, GTFS fares ingestor (v1 and v2), transfer desert map. **Sprint 4b:** fare calculator, corridor sampler, Planning → Fares page, acceptance sweep. **Sprint 5a:** Fare Burden Mapper backend and page, acceptance sweep (check 4 relaxed, `74c5e0e`).

### 2026-05-11 (Phase 0 bug bash and Phase 1a)
- Spec for the BATIS 2.0 redesign (`4bdaa44`) and Phase 0 plan. Backend test infrastructure.
- Phase 0 fixes: `/routes/compare` shadowed by `/routes/{route_id}/geo` (`f115426`), safety buffer in degrees instead of metres (`e2d2736`), schema fixes for pgvector, immutable generated columns and multi-agency (`0d0db84`), missing requirements (`f13e9ef`), `equity_score` populated from Census ACS (`fbc8156`), StopDrawer wired to live departures (`bed21a1`), UTF-8 BOM in the traffic ingestor (`c1ce074`), dual-filter PostGIS pattern for safety scores (`7cc70e0`). Phase 0 marked complete (`b36302c`). docker-compose ports rewired and `postgres-test` added (`ee7b0b4`).
- Phase 1a (dashboard foundation): Vitest and Testing Library, design tokens, AppShell grid, FilterContext, SelectionContext, shared axios helpers, KpiCard/Spinner/EmptyState/DataList/TrendChart/BarChart primitives, FilterBar, section scaffolds, Overview content, 5-tab nav, App.tsx rewired.

### 2026-03-18
- `94f997b` Phase 0: SQL baseline delay predictions and 30-day vehicle position retention.

### 2026-03-17 (project start)
- `a5b7bdd` Initial commit: BATIS dashboard (AC Transit GTFS-RT, GTFS static, safety, equity).
- `2fcd1d7` Trip Planner with a GTFS-RT delay overlay.

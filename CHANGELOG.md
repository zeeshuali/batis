# BATIS Changelog

Newest first. Update this file (and PROGRESS.md and memory) after every change.

## 2026-11-10

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

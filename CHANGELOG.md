# BATIS Changelog

Newest first. Update this file (and PROGRESS.md and memory) after every change.

## 2026-11-10

### Removed
- `app/services/seed_from_static.py` and the seeding fallback in `run_data_jobs.py` (rule 9: no synthetic data).
- Berkeley crime fetch from `safety_incidents_loader.py` (out of scope; dataset returned HTTP 403).

### Data
- Truncated synthetic `ops_trip_events` (82,416 rows, agency 3D) and derived tables `trip_stop_snapshots`, `ops_headways`, `delay_predictions`, `bunching_predictions`, `demand_forecasts`, `crowding_predictions`. Backup: `~/batis-backups/pre-synthetic-purge-20261110.dump`.

### Added
- Stop surrogate key (migration 010, `stop_pk`) across services and tests; log redaction (`app/core/redact.py`). Commit `3f1e04c`.

### Tests
- 207 passing.

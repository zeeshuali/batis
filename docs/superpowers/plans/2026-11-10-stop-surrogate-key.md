# Plan: surrogate key for `gtfs_stops` (migration 010)

_Date: 2026-11-10 · Status: complete (applied to the dev DB and verified)_

## Problem

`gtfs_stops` had `stop_id` as its sole primary key. Agencies assign their own
stop ids and several reuse the same labels, so loading DE, MA and MV (and
probably more agencies later) failed with
`UniqueViolation ... gtfs_stops_pkey`. A composite `(agency_id, stop_id)` PK
would also have fixed the collision but leaves every dependent table keyed on
agency-assigned text.

## Decision

Give `gtfs_stops` a surrogate key and let everything else point at it:

- `gtfs_stops.stop_pk bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY`
- `UNIQUE (agency_id, stop_id)` stays as the natural key (loader upsert target).
- Tables that stored a stop reference gain `stop_pk`: `gtfs_stop_times`,
  `ops_trip_events`, `stop_observations`, `stop_ada_gap`, `stop_features`,
  `stop_safety_scores`, `delay_predictions`, `crowding_predictions`,
  `demand_forecasts`, `trip_stop_snapshots`. The text `stop_id` stays for
  display and 511 API calls.
- One-row-per-stop tables (`stop_features`, `stop_safety_scores`,
  `stop_ada_gap`) move their PK to `stop_pk` with `ON DELETE CASCADE` FKs.
- `stop_cell` and `cell_ada_gap` materialized views are rebuilt on `stop_pk`.
- Not migrated: `transfer_reliability` (it matches the same stop_id label across
  agencies; follow-up task to redo it spatially).

## Stages

| Stage | What | Status |
|---|---|---|
| S1 | `sql/migrations/010_stop_surrogate_key.sql`, `schema.sql`, schema-lint tests; validated on a scratch copy of the dev DB | done |
| S2 | `gtfs_static_loader` resolves `stop_pk` for stop_times; tests for shared stop_ids across agencies | done |
| S3 | Services, `ml/embed.py`, `main.py` joins moved to `stop_pk`; stop endpoints take optional `?agency_id=` | done |
| S4 | Applied to the live DB, reloaded DE/MA/MV/SO/VN/WC, re-ran the ETL, 207 tests, endpoints checked against real data | done |

## Behaviour notes

- HTTP endpoints keyed by `stop_id` (`/stops/{id}`, `/stops/{id}/reachability`,
  `/stops/{id}/live-departures`, `/stops/{id}/realtime-departures`,
  `/accessibility/gaps/stops/{id}/breakdown`) accept `?agency_id=`. Without it
  the lowest `agency_id` wins, deterministically.
- AI embedding content ids for stops are `{agency_id}:{stop_id}` (same shape as
  routes).
- Real-time ingestors resolve `stop_pk` with a scalar subquery on
  `(agency_id, stop_id)`.

## Test hygiene found along the way

- `tests/conftest.py` now pins `DATABASE_URL` to the test DB; before, plain
  `TestClient(app)` tests read the dev DB after `.env` was fixed to point at it.
- A hard-coded FK name in an ADA test differed between fresh installs and
  migrated DBs; the test now looks it up.

## Follow-ups

- Remove synthetic ops data (project rule: never use synthetic data, always live data; diagnose missing data from logs and fix the cause).
- Rework `transfer_reliability` to pair stops of different agencies within
  walking distance (PostGIS) instead of matching equal `stop_id` labels.
- Add pgvector to the DB image so `ai_embeddings` exists.
- CR agency GTFS returns 404 from the 511 datafeeds endpoint.

## S4 outcome (2026-11-10)

- Stops 17,727 → 20,260 once the six previously failing agencies loaded
  (DE, MA, MV, SO, VN, WC — not just the first three seen). 185 stop_ids are
  shared across agencies, e.g. `235` = VN "Linda Vista At Sutherland Dr" and WC
  "Refugio Valley and Country Run"; `/stops/235?agency_id=…`, the ADA breakdown
  and departures return the right stop per agency.
- `stop_observations` had been loaded twice by two concurrent ETL runs
  (53.2M rows = 2 × 26.6M). The second batch (identified by `created_at`) was
  deleted, leaving 26,618,808 for 2026-10; ETL step 13 then added 2026-09.
- Postgres crashed once into recovery during a 53M-row count: Docker's 64 MB
  `/dev/shm` was too small for parallel workers. `shm_size: 1gb` added to
  `docker-compose.yml`.
- Loader hygiene: 404 from the 511 datafeeds endpoint is now "skipped"; API
  keys are redacted from logs (`app/core/redact.py`).

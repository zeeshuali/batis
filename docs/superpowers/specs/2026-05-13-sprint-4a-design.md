# Sprint 4a — Transfer Intelligence + Fares v2 ingest

**Date:** 2026-05-13
**Sprint:** 4a (subset of `BLUEPRINT.md` Sprint 4)
**Status:** design approved; implementation pending

## Scope decision

The blueprint's Sprint 4 bundles four features:

1. Transfer Reliability Matrix
2. Multi-Agency Fare Calculator
3. Transfer Desert Map
4. Multi-Modal Trip Planner

Treating them as one sprint hides their dependencies. **Sprint 4a covers the
three deterministic, data-driven features (1, 2, 3).** The Multi-Modal Trip
Planner (4) — plus a usable fare-calculator UI that sits on top of it — is
deferred to **Sprint 4b** as a separate brainstorm/plan. That deferral lets
us see how the underlying data feels before committing to the router
implementation (own vs. OpenTripPlanner sidecar).

## Source-data decision: ops_trip_events, not stop_observations

`BLUEPRINT.md` says transfer reliability is computed from
`stop_observations`. That table is empty in the dev DB (it expects the
511.org historic monthly archive ingestor, which hasn't been built).

This sprint computes transfer reliability from **`ops_trip_events`** — the
live realtime stream, which the recent ingestor fix (commit `e489084`) made
clean: 93% of RT trip_ids now match the static `gtfs_stop_times`, delays
are clamped to ±2 h, and rows without a verifiable schedule store
`delay_seconds = NULL` rather than garbage.

The `transfer_reliability` table schema is unchanged; only the query that
populates it differs. When the historic archive ingestor eventually lands,
the compute job's input query swaps from `ops_trip_events` to
`stop_observations` with no schema migration.

**Trade-off**: dev DB has 3 days of history vs. months of historic archive.
Initial `n_observations` per (from_agency, to_agency, transfer_stop_id)
tuple will be thin — the UI must surface `n_observations` so users can
tell signal from noise.

---

## Feature 1: Transfer Reliability Matrix

**Persona:** MPO / regional planner (Planning → Regional sub-page).

**Product question:** "If a passenger transfers from AC Transit to BART at
MacArthur, how likely is the connection to succeed?"

### Data model

```sql
CREATE TABLE transfer_reliability (
    id                          bigserial PRIMARY KEY,
    from_agency                 text    NOT NULL,
    to_agency                   text    NOT NULL,
    transfer_stop_id            text    NOT NULL,   -- where the transfer happens
    scheduled_transfer_minutes  numeric,            -- median scheduled gap
    success_rate_pct            numeric,            -- % of pairs where the connection was achievable
    median_gap_seconds          integer,            -- median actual gap
    n_observations              integer,            -- pairs sampled
    computed_at                 timestamptz NOT NULL DEFAULT now(),
    UNIQUE (from_agency, to_agency, transfer_stop_id),
    CHECK (from_agency <> to_agency)
);
CREATE INDEX idx_transfer_reliability_pair
  ON transfer_reliability (from_agency, to_agency);
```

The `CHECK (from_agency <> to_agency)` catches the noise-injection bug
where downtown stations serving multiple lines from the same agency
generate spurious "transfer" pairs.

### Compute job

A new module `app/services/transfer_reliability.py` exposes
`compute_transfer_reliability(conn, days=7)`:

1. **Identify candidate transfer points.** Stops where ≥ 2 distinct agencies
   have entries in `ops_trip_events` within the date window, OR pairs of
   stops within 200 m of each other (PostGIS `ST_DWithin(::geography,
   ::geography, 200)`) belonging to different agencies. v1 uses the
   stricter "same stop_id" rule to avoid the 200m proximity blow-up;
   200m-pairing is a follow-up if results are too sparse.
2. **For each (from_agency, to_agency, transfer_stop_id) tuple**:
   - Pull every `from_agency` arrival at the stop in the window.
   - For each arrival, find the next `to_agency` departure from the same
     stop within ±30 min via `LATERAL` join (bounds the work to O(N) on top
     of the index).
   - Walk-time: 60 s (same stop_id; no 200m-pair variant in v1).
   - **Success** if `(to_departure - from_arrival)::seconds ≥ walk_time` AND
     `≤ 1800` (passenger gives up after 30 min wait).
3. **Aggregate**:
   - `success_rate_pct = 100 * successes / pairs`
   - `median_gap_seconds = percentile_cont(0.5) WITHIN GROUP (ORDER BY gap)`
   - `scheduled_transfer_minutes = same against scheduled_arrival/departure`
   - `n_observations = COUNT(*)`
4. **UPSERT** into `transfer_reliability`. Old rows for the tuple are
   replaced atomically.

Idempotent; cheap to re-run nightly. Initially called from
`run_data_jobs.py` after the GTFS-RT loader settles.

### API

```
GET /transfers/reliability
  ?from_agency=AC
  ?to_agency=BA
  ?min_observations=10
  → [
      {
        "from_agency": "AC",
        "to_agency":   "BA",
        "transfer_stop_id": "59001",
        "transfer_stop_name": "MacArthur BART",
        "scheduled_transfer_minutes": 6,
        "success_rate_pct": 87.3,
        "median_gap_seconds": 412,
        "n_observations": 127
      },
      ...
    ]
```

Filters are AND-ed; omitting from/to returns the matrix flattened to rows.

### UI

A new panel inside **Planning → Regional** (the MPO planner page that
already shows the cross-agency leaderboard).

**Layout**: heat-map grid, rows = `from_agency`, columns = `to_agency`,
cell value = `success_rate_pct` colour-scaled green→red. Cell shows N
(observations) as small subscript so users can see which cells are
trustworthy. Empty cells (no observations) render hatched / muted.

**Click cell** → drill-down panel listing all transfer stops for that
agency pair, ranked by success rate ascending (worst first). Each row
shows scheduled minutes, actual median gap, success %, and n.

A second sibling panel "Top 10 worst transfer points (any pair)" gives a
single-glance investment queue across all agency pairs.

---

## Feature 2: GTFS Fares v2 ingestor

**Persona:** none directly — pure data prerequisite for Feature 3 and
Sprint 4b.

### Why we need it

GTFS Fares v2 is the modern standard for transit fare specification. The
old Fares v1 model (zones, transfer tables) doesn't represent regional
multi-agency systems well. 511.org publishes v2 feeds per agency at
`/transit/datafeeds?operator_id={id}&file=fares`.

### Data model

Four tables (the blueprint specifies two; we add two more so the calculator
in Sprint 4b can route legs correctly):

```sql
CREATE TABLE fare_products (
    agency_id            text NOT NULL,
    fare_product_id      text NOT NULL,
    fare_product_name    text,
    amount               numeric(8,2),
    currency             text NOT NULL DEFAULT 'USD',
    PRIMARY KEY (agency_id, fare_product_id)
);

CREATE TABLE fare_leg_rules (
    agency_id            text NOT NULL,
    leg_group_id         text,
    network_id           text,
    from_area_id         text,
    to_area_id           text,
    fare_product_id      text NOT NULL,
    PRIMARY KEY (agency_id, leg_group_id, network_id, from_area_id, to_area_id, fare_product_id)
);

CREATE TABLE fare_transfer_rules (
    id                   bigserial PRIMARY KEY,
    agency_id            text NOT NULL,
    from_leg_group_id    text,
    to_leg_group_id      text,
    transfer_count       integer,
    duration_limit       integer,         -- seconds
    fare_product_id      text,
    amount               numeric(8,2)
);

CREATE TABLE fare_areas (
    agency_id            text NOT NULL,
    area_id              text NOT NULL,
    area_name            text,
    PRIMARY KEY (agency_id, area_id)
);
```

### Ingestor

A new module `app/services/gtfs_fares_loader.py` exposes
`load_fares_for_agency(conn, agency_id)`:

1. Download zip from 511.org `/transit/datafeeds?operator_id={agency_id}&file=fares`.
2. Read the 4–6 CSVs inside (Fares v2 is partly optional; not every file is
   present in every feed).
3. Validate row shapes; skip with a warning on malformed rows.
4. UPSERT into the four tables.
5. Tag the agency in the agencies catalog with `has_fares_v2: bool` so the
   UI knows which agencies it can compute fares for. (Schema migration adds
   the column to `agencies`.)

Called from `run_data_jobs.py` after the GTFS static loader, so static and
fares stay in sync per agency.

### Risk

Fares v2 is recent; not every Bay Area operator ships clean feeds. AC
Transit and BART are known good; smaller agencies may have partial or no
feed. Mitigation: per-agency `has_fares_v2` flag, opportunistic ingest, UI
degrades gracefully.

### API

No dedicated endpoint in Sprint 4a — the data is only read by Feature 3
(deserts) and (later) Sprint 4b. A debugging endpoint is reasonable:

```
GET /fares/products?agency_id=AC
  → list of fare_products rows for the agency
```

---

## Feature 3: Transfer Desert Map

**Persona:** city / municipal planner (Planning → Coverage sub-page).

**Product question:** "Where in the Bay Area can a resident not transfer
between two specific agencies within a reasonable walk?"

### Computation

Uses the existing `coverage_cells` hex grid (already populated).

For each cell, for each pair of agencies:
- Find the closest stop for `agency_A` within 800 m of the cell centroid.
- Find the closest stop for `agency_B` within 800 m.
- If either is missing, OR the two stops are > 400 m apart from each other
  (max reasonable inter-agency walk), the cell is a **transfer desert for
  that agency pair**.

Output: per-cell, the set of `(agency_A, agency_B)` pairs the cell is a
desert for, plus the cell's `population` and `equity_score` so city
planners can rank by need.

### Storage

No new table — compute on demand. The dataset is small (2,350 cells × ~30
agency pairs) and the cells/stops change infrequently, so a query-time
computation against `coverage_cells` + `gtfs_stops` is fine. If perf becomes
an issue, we materialise into a `coverage_cells.transfer_desert_pairs`
jsonb column later.

### API

```
GET /transfers/deserts
  ?agencies=AC,BA          (require these specific pairs; default = all)
  ?min_population=100
  → GeoJSON FeatureCollection of cells, with:
    {
      cell_id, geometry, population, equity_score,
      desert_pairs: [["AC","BA"], ["AC","CT"]],   // pairs this cell can't transfer between
      worst_distance_m: 1200                       // furthest pair distance
    }
```

### UI

A new toggle on the **Planning → Coverage** map. When on, layers a
hatched-polygon overlay over cells that are deserts for at least one
agency pair the user is filtering on. Tooltip on hover shows which pairs
+ population.

Adds a sibling list panel: "Top 10 transfer-desert cells by population × need"
— ranked queue for city planners to prioritise.

---

## Phasing

```
Week 1 — Feature 1: Transfer Reliability Matrix
  Day 1-2  migration + compute service + tests
  Day 3-4  endpoint + frontend panel
  Day 5    integration testing, polish, smoke

Week 2 — Feature 2: Fares v2 ingestor
  Day 1-2  migration (4 tables) + ingestor module + tests
  Day 3    wire into run_data_jobs.py, agencies catalog flag
  Day 4    debug endpoint, fares from AC + BART verified live
  Day 5    buffer for parser edge cases

Week 3 — Feature 3: Transfer Desert Map
  Day 1-2  endpoint (computed on demand) + tests
  Day 3-4  frontend overlay + ranked list
  Day 5    integration smoke, design doc update for 4b kickoff
```

3 weeks total. Each feature is its own implementation plan, executed
sequentially.

## Open questions deferred to Sprint 4b

- Multi-Modal Trip Planner: own router vs. OpenTripPlanner sidecar.
- Fare Calculator UI: where does it live? (likely a side panel on the new
  planner.)
- Pathways data ingestion (needed for in-station walk-transfer geometry).
- SIRI Stop Monitoring real-time ETAs (per stop, multi-agency).

## Risks

1. **Transfer reliability noise.** 3 days of `ops_trip_events` history will
   produce thin n_observations counts. Surface n_observations in the UI so
   users distrust low-n cells. Long-term fix: historic archive ingest.
2. **Fares v2 feed completeness.** Some Bay Area agencies may not ship v2.
   Per-agency `has_fares_v2` flag mitigates the UX issue but limits the
   transfer-desert computation to agencies that have data.
3. **Compute time.** Transfer reliability's LATERAL join could be slow on
   3.9M rows. Mitigation: index on (agency_id, stop_id, service_date), and
   if needed, prefilter to candidate transfer stops first.
4. **800m / 400m thresholds** in the desert computation are policy not
   physics. Surface as config so they can be tuned without code changes.

## What we are not building this sprint

- Walking direction or Pathways geometry for transfers.
- Live SIRI Stop Monitoring ETAs (per-agency, per-stop).
- Multi-modal trip routing.
- Fare calculation UI / `/fares/calculate` endpoint.
- Backfilling historic `stop_observations` from 511.org.

All four are Sprint 4b or later.

---

## Verification (end of Sprint 4a)

1. `SELECT COUNT(*) FROM transfer_reliability` returns ≥ 5 rows for
   AC↔BART, the most-trafficked Bay Area transfer pair.
2. `GET /transfers/reliability?from_agency=AC&to_agency=BA` returns
   non-empty JSON with success rates between 0 and 100.
3. `SELECT COUNT(*) FROM fare_products` returns ≥ 2 (AC and BART minimum).
4. `GET /transfers/deserts` returns a non-empty FeatureCollection.
5. Planning → Regional renders the transfer matrix heatmap.
6. Planning → Coverage renders the transfer-desert overlay.
7. All existing tests pass (backend ≥ 69 + N new; frontend ≥ 88 + N new).

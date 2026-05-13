# GTFS Composite Primary Keys — Foundation Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the cross-agency GTFS ID collision bug where 47% of `route_id` rows in `gtfs_routes` are misattributed because the existing PK is `(route_id)` instead of `(agency_id, route_id)`. Same flaw exists on `gtfs_stops`, `gtfs_trips`, `gtfs_stop_times`, `gtfs_shapes`, and `gtfs_shape_geoms`. Migrate every multi-agency GTFS table to composite PKs, update the loader's `ON CONFLICT` targets, re-run ETL for all 13 agencies, and patch every read-path query that joins these tables.

**Why this matters:**
- Sprint 5c's ADA-gap drill returns **0 routes** for 4 of the 5 highest-gap stops because `r.agency_id = :aid` filters out the colliding row.
- 163 of 347 `route_id`s in `gtfs_routes` (47%) have an `agency_id` that disagrees with their trips' `agency_id` in `gtfs_trips`.
- 36,765 trips reference a clobbered route row.
- Likely (unverified) silent regressions on `/routes/compare`, `/routes/{route_id}/geo`, bunching, transfer reliability, AI assistant RAG.

**Architecture:**
- One migration (`009_gtfs_composite_keys.sql`) does the FK drop → PK swap → FK re-add ceremony in a single transaction.
- `gtfs_shapes` and `gtfs_shape_geoms` need an `agency_id` column added + backfilled from `gtfs_trips.shape_id`.
- `gtfs_stops` keeps `(stop_id)` as a `UNIQUE` constraint (not PK) so that downstream `stop_safety_scores` / `stop_features` FKs continue to work. Justification: current data has 0 cross-agency stop_id collisions; a future colliding load would error loudly on the unique constraint instead of silently overwriting.
- Loader's `_upsert_dataframe()` call sites change from `["route_id"]` etc. to `["agency_id", "route_id"]` (no API change to the helper itself).
- Read-path patches go in `ada_accessibility_gap.py`, `analysis.py`, `features_builder.py`, `coverage_builder.py`, `headways.py`, `transfer_reliability.py`, `seed_from_static.py`, and the AI assistant's RAG context query.
- ETL must be fully re-run after the migration: dropping the old PK + adding the composite one does not restore the 163 missing routes — only re-ingestion does.

**Tech Stack:** PostgreSQL/PostGIS migrations, SQLAlchemy `text()`, pandas/psycopg2 `execute_values`, pytest. No new dependencies.

---

## Phase 0 — Pre-flight (Task 0)

### Task 0: Snapshot dev DB + record current row counts

**Files:**
- Create: `docs/superpowers/specs/2026-05-13-gtfs-foundation-baseline.md` (artifact only)

- [ ] **Step 1: Capture pre-migration row counts**

```bash
docker exec batis-postgres-1 pg_dump \
  -U postgres -d bay_area_transit_intel \
  --schema-only > /tmp/batis-schema-pre-009.sql
docker exec batis-postgres-1 psql -U postgres -d bay_area_transit_intel -c "
SELECT relname, n_live_tup FROM pg_stat_user_tables
 WHERE relname LIKE 'gtfs_%' OR relname IN ('stop_safety_scores','stop_features','stop_ada_gap')
 ORDER BY relname;
" > /tmp/batis-rowcounts-pre-009.txt
```

Save both to `docs/superpowers/specs/2026-05-13-gtfs-foundation-baseline.md` for diffing after the ETL re-run.

- [ ] **Step 2: Record the canonical "broken" symptom**

```bash
# This MUST currently return 0 routes (the bug):
curl -s -H "X-API-Key: change_me_backend_api_key" \
  "http://localhost:8001/accessibility/gaps/stops/14483/breakdown" \
  | python3 -c "import sys,json; b=json.load(sys.stdin); print('routes:', len(b['routes']), 'tracts:', len(b['tracts']))"
```

Expected output before fix: `routes: 0 tracts: 3`.
Expected output after fix: `routes: ≥1 tracts: 3`.

---

## Phase 1 — Migration (Tasks 1–3)

### Task 1: Write migration 009

**Files:**
- Create: `backend/sql/migrations/009_gtfs_composite_keys.sql`
- Modify: `backend/sql/schema.sql` (update PK declarations to match)

- [ ] **Step 1: Draft the migration**

Create `backend/sql/migrations/009_gtfs_composite_keys.sql`:

```sql
-- 009_gtfs_composite_keys.sql
-- Foundation fix: change GTFS PKs to (agency_id, <id>) composite form so
-- cross-agency ID collisions stop silently overwriting one agency's data.
-- See docs/superpowers/plans/2026-05-13-gtfs-composite-keys.md.

BEGIN;

-- ── 1. Drop FKs that reference the affected PKs ────────────────────────────
ALTER TABLE gtfs_trips        DROP CONSTRAINT IF EXISTS gtfs_trips_route_id_fkey;
ALTER TABLE gtfs_stop_times   DROP CONSTRAINT IF EXISTS gtfs_stop_times_trip_id_fkey;
ALTER TABLE gtfs_stop_times   DROP CONSTRAINT IF EXISTS gtfs_stop_times_stop_id_fkey;
ALTER TABLE stop_safety_scores DROP CONSTRAINT IF EXISTS stop_safety_scores_stop_id_fkey;
ALTER TABLE stop_features      DROP CONSTRAINT IF EXISTS stop_features_stop_id_fkey;

-- ── 2. Backfill agency_id on gtfs_shapes from the trip that references the
--      shape. Shapes are referenced by exactly one agency in practice; if a
--      shape_id appears in multiple agencies' trips, the first wins. ───────
ALTER TABLE gtfs_shapes ADD COLUMN IF NOT EXISTS agency_id text;
UPDATE gtfs_shapes sh
   SET agency_id = src.agency_id
  FROM (
    SELECT DISTINCT ON (shape_id) shape_id, agency_id
      FROM gtfs_trips
     WHERE shape_id IS NOT NULL
     ORDER BY shape_id, agency_id
  ) src
 WHERE sh.shape_id = src.shape_id
   AND sh.agency_id IS NULL;
-- Rows whose shape_id has no matching trip get a synthetic 'UNKNOWN' tag so
-- the NOT NULL constraint below doesn't fail. Re-ingest will overwrite.
UPDATE gtfs_shapes SET agency_id = 'UNKNOWN' WHERE agency_id IS NULL;
ALTER TABLE gtfs_shapes ALTER COLUMN agency_id SET NOT NULL;

-- gtfs_shape_geoms already has agency_id from migration 001; no backfill needed.

-- ── 3. Swap PKs to composite (agency_id, <id>) form ─────────────────────────
-- gtfs_routes
ALTER TABLE gtfs_routes DROP CONSTRAINT gtfs_routes_pkey;
ALTER TABLE gtfs_routes ADD CONSTRAINT gtfs_routes_pkey PRIMARY KEY (agency_id, route_id);

-- gtfs_trips
ALTER TABLE gtfs_trips DROP CONSTRAINT gtfs_trips_pkey;
ALTER TABLE gtfs_trips ADD CONSTRAINT gtfs_trips_pkey PRIMARY KEY (agency_id, trip_id);

-- gtfs_stop_times
ALTER TABLE gtfs_stop_times DROP CONSTRAINT gtfs_stop_times_pkey;
ALTER TABLE gtfs_stop_times ADD CONSTRAINT gtfs_stop_times_pkey
  PRIMARY KEY (agency_id, trip_id, stop_sequence);

-- gtfs_shapes
ALTER TABLE gtfs_shapes DROP CONSTRAINT gtfs_shapes_pkey;
ALTER TABLE gtfs_shapes ADD CONSTRAINT gtfs_shapes_pkey
  PRIMARY KEY (agency_id, shape_id, shape_pt_sequence);

-- gtfs_shape_geoms
ALTER TABLE gtfs_shape_geoms DROP CONSTRAINT gtfs_shape_geoms_pkey;
ALTER TABLE gtfs_shape_geoms ADD CONSTRAINT gtfs_shape_geoms_pkey
  PRIMARY KEY (agency_id, shape_id);

-- gtfs_stops: KEEP single-column PK because stop_safety_scores / stop_features
-- FK to it on stop_id alone, AND the data has 0 cross-agency stop_id
-- collisions today. Add a composite unique index for query-planner
-- assistance and as a future safety net.
CREATE UNIQUE INDEX IF NOT EXISTS gtfs_stops_agency_stop_uniq
  ON gtfs_stops (agency_id, stop_id);

-- ── 4. Re-add FKs with composite references ─────────────────────────────────
ALTER TABLE gtfs_trips
  ADD CONSTRAINT gtfs_trips_route_id_fkey
  FOREIGN KEY (agency_id, route_id) REFERENCES gtfs_routes (agency_id, route_id);

ALTER TABLE gtfs_stop_times
  ADD CONSTRAINT gtfs_stop_times_trip_id_fkey
  FOREIGN KEY (agency_id, trip_id) REFERENCES gtfs_trips (agency_id, trip_id);

-- stop_id FK on gtfs_stop_times references single-column gtfs_stops.stop_id
-- (unchanged PK), so it can be re-added as-is.
ALTER TABLE gtfs_stop_times
  ADD CONSTRAINT gtfs_stop_times_stop_id_fkey
  FOREIGN KEY (stop_id) REFERENCES gtfs_stops (stop_id);

ALTER TABLE stop_safety_scores
  ADD CONSTRAINT stop_safety_scores_stop_id_fkey
  FOREIGN KEY (stop_id) REFERENCES gtfs_stops (stop_id);

ALTER TABLE stop_features
  ADD CONSTRAINT stop_features_stop_id_fkey
  FOREIGN KEY (stop_id) REFERENCES gtfs_stops (stop_id);

COMMIT;
```

**Risks documented inline in the migration body:**
- `gtfs_shapes.agency_id` backfill picks the lowest-`agency_id`-alphabetically winner when one `shape_id` is shared. This is acceptable because the ETL re-run in Phase 4 will OVERWRITE every row with the correct agency tag.
- Migration assumes data already satisfies the new uniqueness: no two rows in `gtfs_routes` currently share `(agency_id, route_id)`. The reverse pre-flight query in Task 0 confirms this.

- [ ] **Step 2: Mirror schema.sql so fresh installs match**

Update every PK line in `backend/sql/schema.sql` that this migration touched. Also add the `agency_id text NOT NULL` column declaration on `gtfs_shapes` and the matching composite PK declarations.

- [ ] **Step 3: Commit**

```
Migration 009: GTFS composite primary keys

Replaces single-column PKs on gtfs_routes / gtfs_trips / gtfs_stop_times /
gtfs_shapes / gtfs_shape_geoms with (agency_id, <id>) composite form.
gtfs_stops keeps the single-column PK (stop_safety_scores and stop_features
FK to it; 0 cross-agency collisions in current data); adds a composite
unique index as a safety net.

Adds NOT NULL agency_id to gtfs_shapes, backfilled from gtfs_trips.

Drop/re-add ceremony for 5 FKs done in a single transaction.
```

---

### Task 2: Schema-lint regression test

**Files:**
- Modify: `backend/tests/test_schema_lint.py`

- [ ] **Step 1: Add assertions for the new composite PKs**

```python
def test_gtfs_pks_are_composite(db_conn):
    """Regression guard for 009: every multi-agency GTFS table must have
    agency_id as the first column of its PK (or as part of a unique constraint
    on gtfs_stops)."""
    expected = {
        "gtfs_routes":      ["agency_id", "route_id"],
        "gtfs_trips":       ["agency_id", "trip_id"],
        "gtfs_stop_times":  ["agency_id", "trip_id", "stop_sequence"],
        "gtfs_shapes":      ["agency_id", "shape_id", "shape_pt_sequence"],
        "gtfs_shape_geoms": ["agency_id", "shape_id"],
    }
    for table, cols in expected.items():
        actual = db_conn.execute(text(f"""
            SELECT a.attname
              FROM pg_constraint c
              JOIN pg_attribute a
                ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
             WHERE c.conrelid = '{table}'::regclass AND c.contype = 'p'
             ORDER BY array_position(c.conkey, a.attnum)
        """)).scalars().all()
        assert actual == cols, f"{table} PK = {actual}, expected {cols}"

    # gtfs_stops keeps single-column PK + composite unique
    assert db_conn.execute(text("""
        SELECT indexdef FROM pg_indexes
         WHERE indexname = 'gtfs_stops_agency_stop_uniq'
    """)).scalar(), "gtfs_stops_agency_stop_uniq index missing"
```

- [ ] **Step 2: Verify it fails before migration, passes after**

Run against a fresh test DB before applying migration 009 → should fail.
Apply migration → should pass.

- [ ] **Step 3: Commit**

---

### Task 3: Apply migration to dev DB

- [ ] **Step 1: Snapshot before applying**

```bash
docker exec batis-postgres-1 pg_dump -U postgres -d bay_area_transit_intel \
  > /tmp/batis-dev-pre-009.dump
```

- [ ] **Step 2: Apply migration**

```bash
docker exec -i batis-postgres-1 psql -U postgres -d bay_area_transit_intel \
  < backend/sql/migrations/009_gtfs_composite_keys.sql
```

Confirm: `BEGIN`/`COMMIT` succeed, all `ALTER TABLE` statements report `ALTER TABLE`.

- [ ] **Step 3: Confirm read paths still respond**

```bash
# These two MUST still work (they don't depend on the broken filter):
curl -s -H "X-API-Key: $KEY" "http://localhost:8001/accessibility/gaps?limit=5" | head -c 200
curl -s -H "X-API-Key: $KEY" "http://localhost:8001/accessibility/gaps/cells?limit=5" | head -c 200
```

The drill endpoint will still return `0 routes` until Phase 3 patches it.

---

## Phase 2 — Loaders (Tasks 4–5)

### Task 4: Update gtfs_static_loader call sites

**Files:**
- Modify: `backend/app/services/gtfs_static_loader.py`

- [ ] **Step 1: Patch the four `_upsert_dataframe` call sites**

At lines 256, 259, 269, 271:

```python
_upsert_dataframe(conn, routes_df[routes_cols], "gtfs_routes",
                  ["agency_id", "route_id"])
_upsert_dataframe(conn, stops_df[stops_core_cols], "gtfs_stops",
                  ["agency_id", "stop_id"])
# Note: gtfs_stops PK is still (stop_id) per the migration, but the upsert
# helper uses ON CONFLICT (conflict_str) → it needs to target the composite
# unique constraint name explicitly. See Step 2.
_upsert_dataframe(conn, trips_subset, "gtfs_trips",
                  ["agency_id", "trip_id"])
_upsert_dataframe(
    conn, stop_times_df[stop_times_cols], "gtfs_stop_times",
    ["agency_id", "trip_id", "stop_sequence"],
)
```

- [ ] **Step 2: Handle gtfs_stops' "unique constraint, not PK" edge case**

`ON CONFLICT (agency_id, stop_id)` requires either a PK or a unique constraint on that column tuple. We created `gtfs_stops_agency_stop_uniq` for exactly this. Postgres matches `ON CONFLICT (cols)` against any unique index that covers those columns — no additional code change needed. Verify by hand once the loader runs.

- [ ] **Step 3: Patch shape upsert + shape_geoms delete to use composite key**

At line 280:

```python
_upsert_dataframe(
    conn, shapes_df[shapes_cols], "gtfs_shapes",
    ["agency_id", "shape_id", "shape_pt_sequence"],
)
```

Make sure `shapes_df` has `agency_id` set — currently the loader's comment at line 138–139 says it doesn't ("shape_geoms gets agency_id set at aggregation time"). Add:

```python
shapes_df["agency_id"] = agency_id
```

Add `agency_id` to `shapes_cols` selection.

At lines 284–286 (the gtfs_shape_geoms DELETE before INSERT):

```python
conn.execute(
    text("DELETE FROM gtfs_shape_geoms WHERE agency_id = :aid AND shape_id = ANY(:ids)"),
    {"aid": agency_id, "ids": loaded_shape_ids},
)
```

Without the agency_id filter we'd delete another agency's shape with the same shape_id.

- [ ] **Step 4: Commit**

```
Loader updates: composite ON CONFLICT for GTFS tables (009)

Updates the 4 _upsert_dataframe call sites in gtfs_static_loader to
target the composite (agency_id, <id>) unique constraints created by
migration 009. Adds agency_id tagging to shapes_df and scopes the
shape_geoms DELETE-before-INSERT by agency to prevent cross-agency
shape clobbering.
```

---

### Task 5: Loader regression test — two agencies, shared route_id

**Files:**
- Create: `backend/tests/test_gtfs_loader_multi_agency.py`

- [ ] **Step 1: Write the regression test**

```python
"""Regression: loader must not clobber Agency A's data when Agency B
loads a feed sharing route_id / stop_id / trip_id values."""

def test_two_agencies_sharing_route_id_keep_both_rows(db_conn):
    db_conn.execute(text("""
      INSERT INTO gtfs_routes (route_id, agency_id, route_short_name,
                               route_long_name, route_type)
      VALUES
        ('31', 'TST_A', 'A31', 'A line 31', 3),
        ('31', 'TST_B', 'B31', 'B line 31', 3)
      ON CONFLICT (agency_id, route_id) DO UPDATE
        SET route_short_name = EXCLUDED.route_short_name
    """))
    rows = db_conn.execute(text(
      "SELECT agency_id, route_short_name FROM gtfs_routes "
      "WHERE route_id = '31' AND agency_id LIKE 'TST_%'"
    )).all()
    assert {(r[0], r[1]) for r in rows} == {("TST_A", "A31"), ("TST_B", "B31")}
    db_conn.execute(text(
      "DELETE FROM gtfs_routes WHERE agency_id LIKE 'TST_%'"
    ))
```

Add parallel tests for `gtfs_stops`, `gtfs_trips`, `gtfs_stop_times`, `gtfs_shapes`, `gtfs_shape_geoms`.

- [ ] **Step 2: Commit**

---

## Phase 3 — Read-path repair (Tasks 6–10)

> Every JOIN of `gtfs_routes` / `gtfs_trips` / `gtfs_shape_geoms` on `route_id` / `trip_id` / `shape_id` alone is currently broken — it can pick the wrong agency's row. Each join needs `agency_id` added to the ON clause OR an explicit `WHERE r.agency_id = X` filter that's sourced from the trip, not the stop.

### Task 6: ada_accessibility_gap.py

**Files:**
- Modify: `backend/app/services/ada_accessibility_gap.py`
- Modify: `backend/tests/test_ada_accessibility_gap.py`

- [ ] **Step 1: Fix `get_stop_ada_gap_breakdown` routes query (line 291)**

```sql
SELECT tr.route_id,
       COALESCE(r.route_short_name, tr.route_id) AS route_short_name,
       COUNT(DISTINCT tr.trip_id)::int AS trips_per_day
  FROM gtfs_stop_times st
  JOIN gtfs_trips      tr ON tr.agency_id = st.agency_id
                         AND tr.trip_id   = st.trip_id
  LEFT JOIN gtfs_routes r  ON r.agency_id = tr.agency_id
                         AND r.route_id   = tr.route_id
 WHERE st.stop_id   = :sid
   AND st.agency_id = :aid
 GROUP BY tr.route_id, r.route_short_name
 ORDER BY trips_per_day DESC
 LIMIT 10
```

Once migration 009 + ETL re-run are done, the LEFT JOIN will always find a match. But keeping it as LEFT JOIN + COALESCE means the endpoint degrades gracefully if a future load partial-fails.

- [ ] **Step 2: Fix `get_stop_ada_gap_features` routes_serving subquery (line 374)**

```sql
COALESCE(
  (SELECT array_agg(DISTINCT COALESCE(r.route_short_name, tr.route_id)
                    ORDER BY COALESCE(r.route_short_name, tr.route_id))
     FROM gtfs_stop_times st
     JOIN gtfs_trips      tr ON tr.agency_id = st.agency_id
                            AND tr.trip_id   = st.trip_id
     LEFT JOIN gtfs_routes r ON r.agency_id = tr.agency_id
                            AND r.route_id  = tr.route_id
    WHERE st.stop_id   = sag.stop_id
      AND st.agency_id = sag.agency_id), ARRAY[]::text[]
) AS routes_serving
```

- [ ] **Step 3: Add a regression test for the top-5 stops**

```python
def test_top_gap_stops_all_return_routes(client, db_conn):
    """After 009 + ETL re-run, every top-5 gap stop must have ≥1 route in
    the drill response. Guards the original Sprint 5c defect."""
    r = client.get("/accessibility/gaps?limit=5")
    stops = [f["properties"]["stop_id"] for f in r.json()["features"]]
    for sid in stops:
        b = client.get(f"/accessibility/gaps/stops/{sid}/breakdown").json()
        assert len(b["routes"]) >= 1, f"stop {sid} returned 0 routes"
```

- [ ] **Step 4: Update sprint-5c-acceptance.py check #9 to require ALL top-5 stops to return ≥1 route, not just any one of them**

- [ ] **Step 5: Commit**

---

### Task 7: analysis.py — 10 join sites

**Files:**
- Modify: `backend/app/services/analysis.py`

- [ ] **Step 1: For each of the 10 grep hits (lines 564, 579, 615, 813, 916, 982, 1084, 1109, 1420), audit whether the agency_id is in scope and add it to the ON clause.**

Pattern to apply:
- `JOIN gtfs_routes r ON r.route_id = t.route_id` → `JOIN gtfs_routes r ON r.agency_id = t.agency_id AND r.route_id = t.route_id`
- For queries that filter `WHERE r.agency_id = :something`, replace with `AND r.agency_id = t.agency_id` in the JOIN (push down the filter).
- For aggregate queries that genuinely need a single agency, add the agency_id filter at the WHERE level and document why.

- [ ] **Step 2: Smoke-test each affected endpoint after editing**

A spreadsheet (in PR description) tracking each line, the endpoint(s) it backs, and a 1-line curl test result.

- [ ] **Step 3: Commit per logical group (don't slam 10 changes into one diff — split into ~3 commits)**

---

### Task 8: Remaining services

**Files:**
- Modify: `backend/app/services/features_builder.py`
- Modify: `backend/app/services/coverage_builder.py`
- Modify: `backend/app/services/headways.py`
- Modify: `backend/app/services/transfer_reliability.py`
- Modify: `backend/app/services/seed_from_static.py`

- [ ] **Step 1: Same pattern — add agency_id to every cross-table JOIN**

- [ ] **Step 2: Smoke test each endpoint they back**

- [ ] **Step 3: Commit**

---

### Task 9: AI assistant RAG context

**Files:**
- Modify: `backend/app/services/ai_assistant.py` (or wherever the route-context lookup happens)

- [ ] **Step 1: Confirm RAG retrieval queries respect agency_id**

The embedding pipeline pulls route names + descriptions to embed. Without agency_id in the lookup, the RAG context for "Route 31" returns whichever agency happened to win. Fix the lookup query.

- [ ] **Step 2: Re-run `ml/embed.py` to regenerate embeddings with corrected text**

```bash
cd backend && python -m ml.embed
```

- [ ] **Step 3: Smoke test the AI assistant with a Muni-specific query**

```bash
curl -s -X POST http://localhost:8001/ai/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $KEY" \
  -d '{"q":"Show me delays for Muni route 31"}' | jq .
```

The response should reference Muni, not Santa Clara.

- [ ] **Step 4: Commit**

---

### Task 10: Frontend audit

**Files:** primarily inspection; small TS-type touch-ups if endpoints change shape.

- [ ] **Step 1: Check whether any frontend code keys data by `route_id` alone**

```bash
grep -rn "route_id" frontend/src/ --include="*.ts*" | head
```

Look especially for `Map<route_id, ...>` patterns or `routes.find(r => r.route_id === id)` — these will mis-dedupe across agencies if both agencies use route_id "31". Fix by keying on `${agency_id}:${route_id}` or by always filtering by current agency in scope.

- [ ] **Step 2: Commit per file**

---

## Phase 4 — ETL re-run + acceptance (Tasks 11–13)

### Task 11: Full ETL re-run

- [ ] **Step 1: Truncate the affected tables (preserves PKs/FKs)**

```sql
BEGIN;
TRUNCATE gtfs_stop_times, gtfs_trips, gtfs_routes,
         gtfs_shape_geoms, gtfs_shapes RESTART IDENTITY CASCADE;
-- gtfs_stops NOT truncated — stop_safety_scores / stop_features FK to it and
-- the cascade would wipe those too. Stops are upserted, so re-running the
-- loader will pick up new rows but won't drop stale ones. Acceptable.
COMMIT;
```

- [ ] **Step 2: Run the loader for all 13 agencies**

```bash
cd backend && python -m app.workers.run_data_jobs --step gtfs_static
# OR if the step name differs, run the script directly:
python -c "from app.services.gtfs_static_loader import load_all_agencies_gtfs; print(load_all_agencies_gtfs())"
```

Expect: `{'AC': 'ok', 'BA': 'ok', 'SF': 'ok', ...}` with all 13 agencies "ok".

- [ ] **Step 3: Confirm 0 misattribution remains**

```sql
SELECT COUNT(*) FROM gtfs_trips tr
  JOIN gtfs_routes r ON r.route_id = tr.route_id
 WHERE tr.agency_id <> r.agency_id;
-- Expected: 0
```

Run the equivalent for stops + shapes.

- [ ] **Step 4: Re-run downstream ETL steps that depend on GTFS**

Recompute `coverage_cells`, `stop_features`, `stop_ada_gap`, `transfer_reliability`, `delay_predictions`, etc. Use:

```bash
python -m app.workers.run_data_jobs
```

- [ ] **Step 5: Commit (data only — no code changes)**

```bash
git commit --allow-empty -m "ETL re-run after 009 (composite GTFS PKs)

Truncated and re-loaded all 13 monitored agencies. Post-load
verification: 0 cross-agency route_id / trip_id / shape_id mismatches.
Recomputed all downstream artifacts (coverage_cells, stop_features,
stop_ada_gap, ...)."
```

---

### Task 12: Re-run Sprint 5c acceptance (must still pass 18/18)

```bash
python3 scripts/sprint-5c-acceptance.py
```

Expected: `18/18 live checks PASS`. AND the test_top_gap_stops_all_return_routes test from Task 6 passes.

If check #9 now reports `stop 14483: ≥1 routes` (instead of `0 routes`), the foundation fix is real.

---

### Task 13: Sprint closeout

- [ ] **Step 1: Update PROGRESS.md**

Move "Multi-Agency Support" from "What Is NOT Yet Implemented" to "Implemented" (or note "data integrity now verified — endpoints regression-tested").

- [ ] **Step 2: Add a CLAUDE.md note**

A short paragraph in CLAUDE.md's "Coding Conventions" section:

> **Multi-agency JOINs:** every JOIN between `gtfs_routes`, `gtfs_trips`, `gtfs_stop_times`, `gtfs_shapes`, `gtfs_shape_geoms` must include `agency_id` in the ON clause. The PKs are composite `(agency_id, <id>)` as of migration 009. Joining on `<id>` alone will compile but silently pick whichever agency's row happened to load last.

- [ ] **Step 3: Final commit + commit log review**

```bash
git log --oneline -n 20
```

Expected: ~10 commits across 4 phases, all starting with "009:" or "Loader:" or "Read path:" etc.

---

## Test count at sprint close

- **Backend**: ~163 (Sprint 5c close) + ~10 new = **≥173 tests**
- **Frontend**: unchanged (no UX changes shipped)

## Commit envelope

| Phase | Commits | Tasks |
|---|---|---|
| Phase 1 — Migration | 3 | 1–3 |
| Phase 2 — Loaders | 2 | 4–5 |
| Phase 3 — Read paths | ~5 (split per file group) | 6–10 |
| Phase 4 — ETL + closeout | 3 | 11–13 |
| **Total** | **~13** | |

---

## Decision points the executor should NOT make alone

1. **`gtfs_stops` PK choice.** This plan keeps single-column PK + adds a composite unique. The alternative is to break the FKs from `stop_safety_scores` / `stop_features` and make those tables agency-aware too. Only revisit if a 14th agency loads a colliding stop_id.
2. **Endpoint behaviour when the colliding row's `route_short_name` is wrong.** This plan uses `LEFT JOIN + COALESCE(r.route_short_name, tr.route_id)` so the route_id renders if the join misses. Some endpoints may prefer to hard-fail instead — flag in PR description.
3. **AI assistant re-embed cost.** If the embedding pipeline takes >30 min, schedule it during off-hours and gate Phase 3's Task 9 on user confirmation.

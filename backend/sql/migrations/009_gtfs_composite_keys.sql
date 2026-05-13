-- 009_gtfs_composite_keys.sql
-- Foundation fix: change GTFS PKs to (agency_id, <id>) composite form so
-- cross-agency ID collisions stop silently overwriting one agency's data.
--
-- Before this migration: gtfs_routes / gtfs_trips / gtfs_stop_times /
-- gtfs_shapes / gtfs_shape_geoms all had single-column PKs. When a second
-- agency's loader hit a colliding ID (e.g. both SF Muni and Santa Clara
-- VTA use route_id '31'), ON CONFLICT DO UPDATE silently overwrote the
-- earlier agency's row. Result: 163 of 347 route_ids in gtfs_routes
-- (47%) had an agency_id disagreeing with the trips referencing them,
-- and 36,765 trips pointed at a clobbered route.
--
-- gtfs_stops keeps its single-column PK because stop_safety_scores and
-- stop_features FK to it, AND the data has 0 cross-agency stop_id
-- collisions today. A new composite unique index serves as a safety net.
--
-- See docs/superpowers/plans/2026-05-13-gtfs-composite-keys.md for the
-- full plan, including Phase 2 (loader updates) and Phase 4 (ETL re-run)
-- that must follow this migration before downstream effects are gone.

BEGIN;

-- ── 1. Drop FKs that reference the affected PKs ─────────────────────────────
-- All five must be dropped before we can swap the PKs they reference.
ALTER TABLE gtfs_trips         DROP CONSTRAINT IF EXISTS gtfs_trips_route_id_fkey;
ALTER TABLE gtfs_stop_times    DROP CONSTRAINT IF EXISTS gtfs_stop_times_trip_id_fkey;
ALTER TABLE gtfs_stop_times    DROP CONSTRAINT IF EXISTS gtfs_stop_times_stop_id_fkey;
ALTER TABLE stop_safety_scores DROP CONSTRAINT IF EXISTS stop_safety_scores_stop_id_fkey;
ALTER TABLE stop_features      DROP CONSTRAINT IF EXISTS stop_features_stop_id_fkey;

-- ── 2. Backfill agency_id on gtfs_shapes ────────────────────────────────────
-- gtfs_shapes has no agency_id column today because the original loader
-- comment claimed shape_ids were globally unique within a feed. That
-- assumption is false across feeds. Add the column and backfill from the
-- trip that references each shape. DISTINCT ON deterministically picks
-- the lowest-agency_id-alphabetically winner when one shape_id is
-- referenced by multiple agencies' trips — acceptable because the Phase 4
-- ETL re-run will overwrite every row with the correct agency.
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

-- 70 shape_ids in this dev DB are orphaned (no trip references them).
-- Tag with 'UNKNOWN' so the NOT NULL constraint below holds. ETL re-run
-- will replace these rows.
UPDATE gtfs_shapes SET agency_id = 'UNKNOWN' WHERE agency_id IS NULL;
ALTER TABLE gtfs_shapes ALTER COLUMN agency_id SET NOT NULL;

-- gtfs_shape_geoms already has agency_id NOT NULL (from migration 001).

-- ── 3. Swap PKs to composite (agency_id, <id>) form ─────────────────────────
ALTER TABLE gtfs_routes DROP CONSTRAINT gtfs_routes_pkey;
ALTER TABLE gtfs_routes
  ADD CONSTRAINT gtfs_routes_pkey PRIMARY KEY (agency_id, route_id);

ALTER TABLE gtfs_trips DROP CONSTRAINT gtfs_trips_pkey;
ALTER TABLE gtfs_trips
  ADD CONSTRAINT gtfs_trips_pkey PRIMARY KEY (agency_id, trip_id);

ALTER TABLE gtfs_stop_times DROP CONSTRAINT gtfs_stop_times_pkey;
ALTER TABLE gtfs_stop_times
  ADD CONSTRAINT gtfs_stop_times_pkey
  PRIMARY KEY (agency_id, trip_id, stop_sequence);

ALTER TABLE gtfs_shapes DROP CONSTRAINT gtfs_shapes_pkey;
ALTER TABLE gtfs_shapes
  ADD CONSTRAINT gtfs_shapes_pkey
  PRIMARY KEY (agency_id, shape_id, shape_pt_sequence);

ALTER TABLE gtfs_shape_geoms DROP CONSTRAINT gtfs_shape_geoms_pkey;
ALTER TABLE gtfs_shape_geoms
  ADD CONSTRAINT gtfs_shape_geoms_pkey
  PRIMARY KEY (agency_id, shape_id);

-- gtfs_stops: keep single-column PK. Add a composite unique index so the
-- loader's ON CONFLICT (agency_id, stop_id) clause has a target and so
-- a future cross-agency collision errors loudly instead of silently
-- overwriting.
CREATE UNIQUE INDEX IF NOT EXISTS gtfs_stops_agency_stop_uniq
  ON gtfs_stops (agency_id, stop_id);

-- ── 4. Re-add FKs with composite references where applicable ────────────────
-- The two FKs that depend on the CORRUPTED data (gtfs_trips → gtfs_routes
-- and gtfs_stop_times → gtfs_trips) are added with NOT VALID. This enforces
-- the FK for NEW rows but skips revalidating the 36,765 trips that
-- currently reference clobbered routes. Phase 4 Task 11 (ETL re-run) will
-- restore the missing rows; Phase 4 Task 11 Step 4 will then run:
--   ALTER TABLE gtfs_trips      VALIDATE CONSTRAINT gtfs_trips_route_id_fkey;
--   ALTER TABLE gtfs_stop_times VALIDATE CONSTRAINT gtfs_stop_times_trip_id_fkey;
-- to retroactively enforce the constraints once the data is clean.
ALTER TABLE gtfs_trips
  ADD CONSTRAINT gtfs_trips_route_id_fkey
  FOREIGN KEY (agency_id, route_id)
  REFERENCES gtfs_routes (agency_id, route_id) NOT VALID;

ALTER TABLE gtfs_stop_times
  ADD CONSTRAINT gtfs_stop_times_trip_id_fkey
  FOREIGN KEY (agency_id, trip_id)
  REFERENCES gtfs_trips (agency_id, trip_id) NOT VALID;

-- stop_id FKs continue to reference single-column gtfs_stops.stop_id and
-- are validated normally — 0 cross-agency stop_id collisions today, so no
-- orphans exist.
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

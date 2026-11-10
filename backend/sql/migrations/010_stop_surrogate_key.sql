-- 010_stop_surrogate_key.sql
-- Give gtfs_stops a surrogate primary key (stop_pk) so any number of agencies
-- can reuse the same agency-assigned stop_id without colliding.
--
-- Before: gtfs_stops PK was stop_id alone. Agencies that reuse a stop_id
-- (DE, MA, MV, ...) failed to load with UniqueViolation on gtfs_stops_pkey, and
-- stop_times / stop_features / stop_safety_scores could only point at one
-- agency's stop for a given label.
--
-- After:
--   * gtfs_stops.stop_pk bigint identity is the PK.
--   * UNIQUE (agency_id, stop_id) stays as the natural key (loader upsert target).
--   * Every table that stored a stop_id gets a stop_pk column, backfilled here.
--     The text stop_id stays on those tables for display / 511 API calls.
--   * FKs now reference gtfs_stops(stop_pk).
--
-- Backfill rule: tables with agency_id join on (agency_id, stop_id); tables
-- without it join on stop_id alone, which is safe today because stop_id was a
-- global PK until this migration (so each label maps to exactly one row).
-- New writers must set stop_pk explicitly (see app/services).
--
-- Do NOT run while run_data_jobs is loading GTFS: it rewrites gtfs_stop_times.

BEGIN;

-- ── 1. Drop objects that depend on the old PK ───────────────────────────────
DROP MATERIALIZED VIEW IF EXISTS cell_ada_gap;
DROP MATERIALIZED VIEW IF EXISTS stop_cell;

ALTER TABLE gtfs_stop_times    DROP CONSTRAINT IF EXISTS gtfs_stop_times_stop_id_fkey;
ALTER TABLE stop_safety_scores DROP CONSTRAINT IF EXISTS stop_safety_scores_stop_id_fkey;
ALTER TABLE stop_features      DROP CONSTRAINT IF EXISTS stop_features_stop_id_fkey;

-- ── 2. Surrogate key on gtfs_stops ──────────────────────────────────────────
ALTER TABLE gtfs_stops ADD COLUMN IF NOT EXISTS stop_pk bigint GENERATED ALWAYS AS IDENTITY;
ALTER TABLE gtfs_stops DROP CONSTRAINT IF EXISTS gtfs_stops_pkey;
ALTER TABLE gtfs_stops ADD CONSTRAINT gtfs_stops_pkey PRIMARY KEY (stop_pk);
-- gtfs_stops_agency_stop_uniq (agency_id, stop_id) already exists from 009.

-- ── 3. stop_pk on every table that references a stop ────────────────────────
-- With agency_id: join on the natural key.
ALTER TABLE gtfs_stop_times ADD COLUMN IF NOT EXISTS stop_pk bigint;
UPDATE gtfs_stop_times t SET stop_pk = s.stop_pk
  FROM gtfs_stops s
 WHERE t.stop_pk IS NULL AND s.agency_id = t.agency_id AND s.stop_id = t.stop_id;

ALTER TABLE ops_trip_events ADD COLUMN IF NOT EXISTS stop_pk bigint;
UPDATE ops_trip_events t SET stop_pk = s.stop_pk
  FROM gtfs_stops s
 WHERE t.stop_pk IS NULL AND s.agency_id = t.agency_id AND s.stop_id = t.stop_id;

ALTER TABLE stop_observations ADD COLUMN IF NOT EXISTS stop_pk bigint;
UPDATE stop_observations t SET stop_pk = s.stop_pk
  FROM gtfs_stops s
 WHERE t.stop_pk IS NULL AND s.agency_id = t.agency_id AND s.stop_id = t.stop_id;

ALTER TABLE stop_ada_gap ADD COLUMN IF NOT EXISTS stop_pk bigint;
UPDATE stop_ada_gap t SET stop_pk = s.stop_pk
  FROM gtfs_stops s
 WHERE t.stop_pk IS NULL AND s.agency_id = t.agency_id AND s.stop_id = t.stop_id;

-- Without agency_id: stop_id was globally unique until now.
-- transfer_reliability is intentionally NOT migrated: it matches the same stop_id
-- label across agencies (shared transfer stops), which is not a per-agency key.
ALTER TABLE stop_features      ADD COLUMN IF NOT EXISTS stop_pk bigint;
ALTER TABLE stop_safety_scores ADD COLUMN IF NOT EXISTS stop_pk bigint;
ALTER TABLE delay_predictions  ADD COLUMN IF NOT EXISTS stop_pk bigint;
ALTER TABLE crowding_predictions ADD COLUMN IF NOT EXISTS stop_pk bigint;
ALTER TABLE demand_forecasts   ADD COLUMN IF NOT EXISTS stop_pk bigint;
ALTER TABLE trip_stop_snapshots ADD COLUMN IF NOT EXISTS stop_pk bigint;

UPDATE stop_features t       SET stop_pk = s.stop_pk FROM gtfs_stops s WHERE t.stop_pk IS NULL AND s.stop_id = t.stop_id;
UPDATE stop_safety_scores t  SET stop_pk = s.stop_pk FROM gtfs_stops s WHERE t.stop_pk IS NULL AND s.stop_id = t.stop_id;
UPDATE delay_predictions t   SET stop_pk = s.stop_pk FROM gtfs_stops s WHERE t.stop_pk IS NULL AND s.stop_id = t.stop_id;
UPDATE crowding_predictions t SET stop_pk = s.stop_pk FROM gtfs_stops s WHERE t.stop_pk IS NULL AND s.stop_id = t.stop_id;
UPDATE demand_forecasts t    SET stop_pk = s.stop_pk FROM gtfs_stops s WHERE t.stop_pk IS NULL AND s.stop_id = t.stop_id;
UPDATE trip_stop_snapshots t SET stop_pk = s.stop_pk FROM gtfs_stops s WHERE t.stop_pk IS NULL AND s.stop_id = t.stop_id;

-- ── 4. Tables keyed one-row-per-stop: PK moves to stop_pk ───────────────────
ALTER TABLE stop_features      ALTER COLUMN stop_pk SET NOT NULL;
ALTER TABLE stop_safety_scores ALTER COLUMN stop_pk SET NOT NULL;
ALTER TABLE stop_features      DROP CONSTRAINT IF EXISTS stop_features_pkey;
ALTER TABLE stop_safety_scores DROP CONSTRAINT IF EXISTS stop_safety_scores_pkey;
ALTER TABLE stop_features      ADD CONSTRAINT stop_features_pkey PRIMARY KEY (stop_pk);
ALTER TABLE stop_safety_scores ADD CONSTRAINT stop_safety_scores_pkey PRIMARY KEY (stop_pk);

-- stop_ada_gap is empty until ETL step 16; set NOT NULL + PK only if no rows.
-- (Populated rows are backfilled above; NOT NULL is enforced after.)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM stop_ada_gap WHERE stop_pk IS NULL) THEN
    ALTER TABLE stop_ada_gap ALTER COLUMN stop_pk SET NOT NULL;
    ALTER TABLE stop_ada_gap DROP CONSTRAINT IF EXISTS stop_ada_gap_pkey;
    ALTER TABLE stop_ada_gap ADD CONSTRAINT stop_ada_gap_pkey PRIMARY KEY (stop_pk);
  ELSE
    RAISE EXCEPTION 'stop_ada_gap has rows without a matching gtfs_stops row';
  END IF;
END $$;

-- ── 5. Foreign keys on stop_pk ──────────────────────────────────────────────
-- gtfs_stop_times: NOT VALID first (3M rows), validated below so the lock is brief.
ALTER TABLE gtfs_stop_times
  ADD CONSTRAINT gtfs_stop_times_stop_pk_fkey
  FOREIGN KEY (stop_pk) REFERENCES gtfs_stops (stop_pk) NOT VALID;
ALTER TABLE stop_safety_scores
  ADD CONSTRAINT stop_safety_scores_stop_pk_fkey
  FOREIGN KEY (stop_pk) REFERENCES gtfs_stops (stop_pk) ON DELETE CASCADE;
ALTER TABLE stop_features
  ADD CONSTRAINT stop_features_stop_pk_fkey
  FOREIGN KEY (stop_pk) REFERENCES gtfs_stops (stop_pk) ON DELETE CASCADE;
ALTER TABLE stop_ada_gap
  ADD CONSTRAINT stop_ada_gap_stop_pk_fkey
  FOREIGN KEY (stop_pk) REFERENCES gtfs_stops (stop_pk) ON DELETE CASCADE;

-- ── 6. Indexes for the new join key ─────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_gtfs_stop_times_stop_pk     ON gtfs_stop_times (stop_pk);
CREATE INDEX IF NOT EXISTS idx_ops_trip_events_stop_pk     ON ops_trip_events (stop_pk);
CREATE INDEX IF NOT EXISTS idx_stop_observations_stop_pk   ON stop_observations (stop_pk);
CREATE INDEX IF NOT EXISTS idx_delay_predictions_stop_pk   ON delay_predictions (stop_pk);
CREATE INDEX IF NOT EXISTS idx_crowding_predictions_stop_pk ON crowding_predictions (stop_pk);
CREATE INDEX IF NOT EXISTS idx_demand_forecasts_stop_pk    ON demand_forecasts (stop_pk);
CREATE INDEX IF NOT EXISTS idx_trip_stop_snapshots_stop_pk ON trip_stop_snapshots (stop_pk);

-- ── 7. Recreate materialized views on stop_pk ───────────────────────────────
CREATE MATERIALIZED VIEW stop_cell AS
  SELECT s.stop_pk, s.agency_id, s.stop_id, c.cell_id
    FROM gtfs_stops s
    JOIN coverage_cells c ON ST_Contains(c.geom, s.geom);
CREATE INDEX ix_stop_cell_cell ON stop_cell (cell_id);
CREATE INDEX ix_stop_cell_stop ON stop_cell (stop_pk);

CREATE MATERIALIZED VIEW cell_ada_gap AS
  SELECT cc.cell_id,
         count(sag.stop_pk)       AS stop_count,
         max(sag.gap_score)       AS max_gap_score,
         avg(sag.gap_score)       AS mean_gap_score,
         (array_agg(sag.gap_tier ORDER BY
            CASE sag.gap_tier
              WHEN 'very_high' THEN 4 WHEN 'high' THEN 3
              WHEN 'moderate'  THEN 2 WHEN 'low'  THEN 1 ELSE 0
            END DESC NULLS LAST))[1] AS worst_tier
    FROM coverage_cells cc
    LEFT JOIN stop_cell sc      ON sc.cell_id = cc.cell_id
    LEFT JOIN stop_ada_gap sag  ON sag.stop_pk = sc.stop_pk
   GROUP BY cc.cell_id;
CREATE INDEX ix_cell_ada_gap_score ON cell_ada_gap (max_gap_score DESC NULLS LAST);

COMMIT;

-- Run after COMMIT (outside the lock-holding transaction):
--   ALTER TABLE gtfs_stop_times VALIDATE CONSTRAINT gtfs_stop_times_stop_pk_fkey;

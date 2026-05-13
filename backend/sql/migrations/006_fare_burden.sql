-- Migration 006: fare burden mapper (BATIS Sprint 5a)
-- Caches the expensive per-cell-per-anchor median-fare compute so the UI
-- can read instantly + reweight anchors at query time.  The endpoint
-- /equity/fare-burden multiplies these by median_household_income on the
-- coverage_cells row to produce burden_pct dynamically.
--
-- Cells unreachable from any anchor on a single-agency network have NULL
-- in every median_fare_to_* column and reachable_anchor_count = 0 — the
-- UI renders them hatched.  Multi-agency leg composition is deferred to
-- Sprint 5b.
--
-- Safe to re-run: all statements IF NOT EXISTS / IF EXISTS guards.

-- Tract-level median household income from ACS B19013, stamped on each
-- cell via the existing per-county aggregation pattern in
-- app/services/equity_loader.py.
ALTER TABLE coverage_cells
    ADD COLUMN IF NOT EXISTS median_household_income integer;

CREATE TABLE IF NOT EXISTS fare_burden (
    cell_id                    text PRIMARY KEY,
    median_fare_to_sf          numeric(8,2),
    median_fare_to_oakland     numeric(8,2),
    median_fare_to_sfo         numeric(8,2),
    reachable_anchor_count     integer NOT NULL DEFAULT 0,
    population                 integer,
    median_household_income    integer,
    computed_at                timestamptz NOT NULL DEFAULT now()
);

-- The choropleth renders best when reachable cells surface first;
-- the index lets the API exclude unreachable cells cheaply.
CREATE INDEX IF NOT EXISTS idx_fare_burden_reachable
    ON fare_burden (reachable_anchor_count)
    WHERE reachable_anchor_count > 0;

-- Sprint 5b — Service Delivery Gap Map
-- See docs/superpowers/specs/2026-05-12-sprint-5b-design.md

CREATE TABLE IF NOT EXISTS service_delivery_gap (
  cell_id            text PRIMARY KEY,
  scheduled_arrivals integer NOT NULL,
  missed_arrivals    integer NOT NULL,
  gap_pct            numeric(6,3) NOT NULL,
  window_start       date NOT NULL,
  window_end         date NOT NULL,
  computed_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_service_delivery_gap_gap_pct
  ON service_delivery_gap (gap_pct DESC);

-- Composite index for the per-route drill-down query.
CREATE INDEX IF NOT EXISTS ix_stop_observations_route_date
  ON stop_observations (route_id, service_date);

-- Helper view: which cell does each stop belong to?
CREATE MATERIALIZED VIEW IF NOT EXISTS stop_cell AS
  SELECT s.stop_id, c.cell_id
  FROM gtfs_stops s
  JOIN coverage_cells c
    ON ST_Contains(c.geom, s.geom);

CREATE INDEX IF NOT EXISTS ix_stop_cell_cell ON stop_cell (cell_id);
CREATE INDEX IF NOT EXISTS ix_stop_cell_stop ON stop_cell (stop_id);

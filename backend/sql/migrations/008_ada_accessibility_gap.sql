-- Sprint 5c — ADA Accessibility Gap Tracker
-- See docs/superpowers/specs/2026-05-13-sprint-5c-design.md

-- Census tract geometry for the 9-county Bay Area (loaded from
-- TIGERweb GeoJSON REST). Required for areal interpolation that maps
-- tract-level ambulatory_pop into per-stop catchment buffers.
CREATE TABLE IF NOT EXISTS census_tracts (
  tract_geoid text PRIMARY KEY,
  county_fips text NOT NULL,
  geom        geometry(MultiPolygon, 4326),
  computed_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_census_tracts_geom
  ON census_tracts USING GIST (geom);

-- GTFS Pathways static data (per-station internal graph)
CREATE TABLE IF NOT EXISTS gtfs_pathways (
  agency_id        text NOT NULL,
  pathway_id       text NOT NULL,
  from_stop_id     text NOT NULL,
  to_stop_id       text NOT NULL,
  pathway_mode     integer,
  is_bidirectional boolean,
  length_m         numeric,
  traversal_time   integer,
  stair_count      integer,
  max_slope        numeric,
  PRIMARY KEY (agency_id, pathway_id)
);
CREATE INDEX IF NOT EXISTS ix_gtfs_pathways_from
  ON gtfs_pathways (agency_id, from_stop_id);
CREATE INDEX IF NOT EXISTS ix_gtfs_pathways_to
  ON gtfs_pathways (agency_id, to_stop_id);

CREATE TABLE IF NOT EXISTS gtfs_levels (
  agency_id   text NOT NULL,
  level_id    text NOT NULL,
  level_index numeric,
  level_name  text,
  PRIMARY KEY (agency_id, level_id)
);

-- Tract-level ambulatory-difficulty population from ACS B18105
CREATE TABLE IF NOT EXISTS census_ambulatory (
  tract_geoid    text PRIMARY KEY,
  ambulatory_pop integer NOT NULL,
  total_pop      integer,
  computed_at    timestamptz DEFAULT now()
);

-- Per-stop ADA gap score (fact table)
CREATE TABLE IF NOT EXISTS stop_ada_gap (
  stop_id              text PRIMARY KEY,
  agency_id            text,
  supply_penalty       numeric(3,2),
  ambulatory_pop_400m  integer,
  gap_score            numeric(10,2),
  gap_tier             text,
  pathways_override    boolean,
  catchment_radius_m   integer,
  computed_at          timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_stop_ada_gap_tier
  ON stop_ada_gap (gap_tier);
CREATE INDEX IF NOT EXISTS ix_stop_ada_gap_score
  ON stop_ada_gap (gap_score DESC);

-- Derived per-cell rollup
CREATE MATERIALIZED VIEW IF NOT EXISTS cell_ada_gap AS
  SELECT cc.cell_id,
         COUNT(sag.stop_id)                                AS stop_count,
         MAX(sag.gap_score)                                AS max_gap_score,
         AVG(sag.gap_score)                                AS mean_gap_score,
         (ARRAY_AGG(sag.gap_tier ORDER BY
            CASE sag.gap_tier
              WHEN 'very_high' THEN 4
              WHEN 'high'      THEN 3
              WHEN 'moderate'  THEN 2
              WHEN 'low'       THEN 1
              ELSE 0
            END DESC NULLS LAST))[1]                       AS worst_tier
    FROM coverage_cells cc
    LEFT JOIN stop_cell    sc  ON sc.cell_id  = cc.cell_id
    LEFT JOIN stop_ada_gap sag ON sag.stop_id = sc.stop_id
   GROUP BY cc.cell_id;
CREATE INDEX IF NOT EXISTS ix_cell_ada_gap_score
  ON cell_ada_gap (max_gap_score DESC NULLS LAST);

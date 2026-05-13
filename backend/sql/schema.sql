-- Supabase / Postgres schema for Bay Area Transit Intelligence
-- Enable PostGIS (must also be enabled in Supabase dashboard or via migration)

CREATE EXTENSION IF NOT EXISTS postgis;

-- === GTFS static tables ===

CREATE TABLE IF NOT EXISTS gtfs_feeds (
  id bigserial PRIMARY KEY,
  feed_url text,
  downloaded_at timestamptz NOT NULL DEFAULT now(),
  feed_start_date date,
  feed_end_date date,
  feed_hash text,
  raw_feed_info jsonb
);

CREATE TABLE IF NOT EXISTS gtfs_routes (
  route_id text PRIMARY KEY,
  agency_id text DEFAULT 'AC',
  route_short_name text,
  route_long_name text,
  route_desc text,
  route_type integer,
  route_url text,
  route_color text,
  route_text_color text
);

CREATE TABLE IF NOT EXISTS gtfs_stops (
  stop_id text PRIMARY KEY,
  agency_id text DEFAULT 'AC',
  stop_code text,
  stop_name text,
  stop_desc text,
  stop_lat double precision,
  stop_lon double precision,
  zone_id text,
  stop_url text,
  location_type integer,
  parent_station text,
  wheelchair_boarding integer,
  -- Geometry representation of stop location
  geom geometry(Point, 4326)
);

CREATE INDEX IF NOT EXISTS idx_gtfs_stops_geom
  ON gtfs_stops
  USING GIST (geom);

CREATE TABLE IF NOT EXISTS gtfs_trips (
  trip_id text PRIMARY KEY,
  agency_id text DEFAULT 'AC',
  route_id text NOT NULL REFERENCES gtfs_routes(route_id),
  service_id text,
  trip_headsign text,
  direction_id integer,
  block_id text,
  shape_id text,
  peak_offpeak text
);

CREATE TABLE IF NOT EXISTS gtfs_stop_times (
  trip_id text NOT NULL REFERENCES gtfs_trips(trip_id),
  agency_id text DEFAULT 'AC',
  arrival_time text,
  departure_time text,
  stop_id text NOT NULL REFERENCES gtfs_stops(stop_id),
  stop_sequence integer,
  pickup_type integer,
  drop_off_type integer,
  timepoint integer,
  PRIMARY KEY (trip_id, stop_sequence)
);

CREATE INDEX IF NOT EXISTS idx_gtfs_stop_times_stop_id
  ON gtfs_stop_times (stop_id);

CREATE TABLE IF NOT EXISTS gtfs_shapes (
  shape_id text,
  shape_pt_lat double precision,
  shape_pt_lon double precision,
  shape_pt_sequence integer,
  shape_dist_traveled double precision,
  PRIMARY KEY (shape_id, shape_pt_sequence)
);

-- Optional pre-aggregated shapes as LineStrings for map rendering
CREATE TABLE IF NOT EXISTS gtfs_shape_geoms (
  shape_id text PRIMARY KEY,
  agency_id text DEFAULT 'AC',
  geom geometry(LineString, 4326)
);

CREATE INDEX IF NOT EXISTS idx_gtfs_shape_geoms_geom
  ON gtfs_shape_geoms
  USING GIST (geom);

-- === Realtime & historical ops ===

CREATE TABLE IF NOT EXISTS rt_vehicle_positions_raw (
  id bigserial PRIMARY KEY,
  agency_id text DEFAULT 'AC',
  vehicle_id text,
  trip_id text,
  route_id text,
  timestamp timestamptz NOT NULL,
  latitude double precision,
  longitude double precision,
  bearing double precision,
  speed double precision,
  occupancy_status text,
  raw_payload jsonb,
  geom geometry(Point, 4326)
);

-- Retention policy: 30 days (managed by _cleanup_old_positions in gtfs_rt_ingestor.py)
CREATE INDEX IF NOT EXISTS idx_rt_vehicle_positions_raw_timestamp
  ON rt_vehicle_positions_raw (timestamp);

CREATE INDEX IF NOT EXISTS idx_rt_vehicle_positions_raw_geom
  ON rt_vehicle_positions_raw
  USING GIST (geom);

CREATE TABLE IF NOT EXISTS ops_trip_events (
  id bigserial PRIMARY KEY,
  agency_id text DEFAULT 'AC',
  service_date date NOT NULL,
  trip_id text NOT NULL,
  route_id text NOT NULL,
  stop_id text,
  stop_sequence integer,
  scheduled_arrival timestamptz,
  actual_arrival timestamptz,
  delay_seconds integer,
  headway_seconds integer,
  occupancy_level text,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ops_trip_events_service_date_route
  ON ops_trip_events (service_date, route_id);

CREATE INDEX IF NOT EXISTS idx_ops_trip_events_trip_stop
  ON ops_trip_events (trip_id, stop_sequence);

-- Partial index for ML baseline and prediction queries
CREATE INDEX IF NOT EXISTS idx_ops_trip_events_delay_date
  ON ops_trip_events (service_date, route_id, delay_seconds)
  WHERE delay_seconds IS NOT NULL;

CREATE TABLE IF NOT EXISTS ops_headways (
  id bigserial PRIMARY KEY,
  agency_id text DEFAULT 'AC',
  service_date date NOT NULL,
  route_id text NOT NULL,
  direction_id integer,
  segment_id text,
  window_start timestamptz NOT NULL,
  window_end timestamptz NOT NULL,
  scheduled_headway_seconds integer,
  actual_headway_seconds integer,
  bunching boolean,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ops_headways_route_window
  ON ops_headways (route_id, window_start);

-- === Analysis-specific tables ===

CREATE TABLE IF NOT EXISTS coverage_cells (
  id bigserial PRIMARY KEY,
  cell_id text,
  geom geometry(Polygon, 4326),
  nearest_stop_id text,
  distance_to_nearest_stop_m double precision,
  stops_within_walk integer,
  effective_frequency_per_hour double precision,
  avg_travel_time_to_cbd_min double precision,
  population integer,
  low_income_population integer,
  no_car_households integer,
  equity_score double precision
);

CREATE INDEX IF NOT EXISTS idx_coverage_cells_geom
  ON coverage_cells
  USING GIST (geom);

CREATE TABLE IF NOT EXISTS transit_deserts (
  id bigserial PRIMARY KEY,
  geom geometry(MultiPolygon, 4326),
  desert_score double precision,
  notes text
);

CREATE INDEX IF NOT EXISTS idx_transit_deserts_geom
  ON transit_deserts
  USING GIST (geom);

CREATE TABLE IF NOT EXISTS safety_incidents_raw (
  id bigserial PRIMARY KEY,
  source text,
  incident_type text,
  occurred_at timestamptz,
  severity integer,
  geom geometry(Point, 4326),
  properties jsonb
);

CREATE INDEX IF NOT EXISTS idx_safety_incidents_geom
  ON safety_incidents_raw
  USING GIST (geom);

CREATE TABLE IF NOT EXISTS stop_safety_scores (
  stop_id text PRIMARY KEY REFERENCES gtfs_stops(stop_id),
  safety_score double precision,
  crime_incidents_nearby integer,
  collisions_nearby integer,
  lighting_score double precision,
  pedestrian_infra_score double precision,
  last_computed_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS delay_predictions (
  id bigserial PRIMARY KEY,
  service_date date NOT NULL,
  route_id text NOT NULL,
  trip_id text,
  stop_id text,
  prediction_timestamp timestamptz NOT NULL,
  predicted_delay_seconds double precision,
  model_version text,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_delay_predictions_route_date
  ON delay_predictions (route_id, service_date);

CREATE TABLE IF NOT EXISTS bunching_predictions (
  id bigserial PRIMARY KEY,
  service_date date NOT NULL,
  route_id text NOT NULL,
  segment_id text,
  window_start timestamptz NOT NULL,
  window_end timestamptz NOT NULL,
  bunching_risk double precision,
  model_version text,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bunching_predictions_route_date
  ON bunching_predictions (route_id, service_date);

CREATE TABLE IF NOT EXISTS demand_forecasts (
  id bigserial PRIMARY KEY,
  route_id text NOT NULL,
  trip_id text,
  stop_id text,
  service_date date NOT NULL,
  time_bucket text NOT NULL,
  forecast_boardings double precision,
  lower_ci double precision,
  upper_ci double precision,
  model_version text,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_demand_forecasts_route_date_bucket
  ON demand_forecasts (route_id, service_date, time_bucket);

CREATE TABLE IF NOT EXISTS crowding_predictions (
  id bigserial PRIMARY KEY,
  route_id text NOT NULL,
  trip_id text,
  stop_id text,
  service_date date NOT NULL,
  time_bucket text NOT NULL,
  crowding_level text,
  model_version text,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_crowding_predictions_route_date
  ON crowding_predictions (route_id, service_date);

-- Feature tables for modeling

CREATE TABLE IF NOT EXISTS trip_stop_snapshots (
  id bigserial PRIMARY KEY,
  service_date date NOT NULL,
  route_id text NOT NULL,
  trip_id text NOT NULL,
  stop_id text,
  stop_sequence integer,
  scheduled_arrival timestamptz,
  actual_arrival timestamptz,
  delay_seconds integer,
  headway_seconds integer,
  time_of_day_bucket text,
  dow integer,
  prev_delay_seconds integer,
  prev_headway_seconds integer,
  features_version text,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_trip_stop_snapshots_route_date
  ON trip_stop_snapshots (route_id, service_date);

CREATE TABLE IF NOT EXISTS stop_features (
  stop_id text PRIMARY KEY REFERENCES gtfs_stops(stop_id),
  distance_to_cbd_m double precision,
  routes_serving integer,
  avg_headway_peak double precision,
  avg_headway_offpeak double precision,
  stop_density_500m double precision,
  features_version text,
  updated_at timestamptz DEFAULT now()
);

-- === AI / RAG tables ===

-- Enable pgvector — must come before the ai_embeddings table DDL
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS ai_embeddings (
  id            bigserial PRIMARY KEY,
  content_type  text NOT NULL,     -- 'route', 'stop', 'alert', 'ops_summary'
  content_id    text NOT NULL,     -- route_id, stop_id, etc.
  content_text  text NOT NULL,     -- human-readable description sent to LLM as context
  embedding     vector(384),       -- all-MiniLM-L6-v2 output dimension
  updated_at    timestamptz DEFAULT now(),
  UNIQUE (content_type, content_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_embeddings_vector
  ON ai_embeddings
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 50);

CREATE INDEX IF NOT EXISTS idx_ai_embeddings_type
  ON ai_embeddings (content_type);

-- === Sprint 1/2/3 tables (multi-agency + traffic/toll) ===

-- Stop Observations — 511.org historical archive (actual vs. scheduled arrivals)
CREATE TABLE IF NOT EXISTS stop_observations (
    id                bigserial PRIMARY KEY,
    service_date      date NOT NULL,
    agency_id         text NOT NULL,
    trip_id           text NOT NULL,
    route_id          text,
    stop_id           text NOT NULL,
    scheduled_arrival timestamptz,
    observed_arrival  timestamptz,
    delay_seconds     integer GENERATED ALWAYS AS (
        CASE
            WHEN observed_arrival IS NOT NULL AND scheduled_arrival IS NOT NULL
            THEN EXTRACT(EPOCH FROM (observed_arrival - scheduled_arrival))::integer
            ELSE NULL
        END
    ) STORED,
    -- Generated columns require IMMUTABLE expressions. The naive form
    -- `observed_arrival <= scheduled_arrival + INTERVAL '5 minutes'` uses
    -- `timestamptz + interval`, which PG 15 marks STABLE because adding
    -- months/days to a timestamptz crosses DST boundaries differently
    -- depending on the session timezone. The fix is to subtract first —
    -- `timestamptz - timestamptz` returns an interval and is IMMUTABLE —
    -- then compare that interval to a constant.
    on_time           boolean GENERATED ALWAYS AS (
        (observed_arrival - scheduled_arrival) <= INTERVAL '5 minutes'
    ) STORED,
    created_at        timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS so_date_agency_idx  ON stop_observations(service_date, agency_id);
CREATE INDEX IF NOT EXISTS so_agency_route_idx ON stop_observations(agency_id, route_id);
CREATE INDEX IF NOT EXISTS so_stop_idx         ON stop_observations(stop_id);
CREATE INDEX IF NOT EXISTS so_trip_idx         ON stop_observations(trip_id);

-- Traffic Events — 511.org /traffic/events API
CREATE TABLE IF NOT EXISTS traffic_events (
    event_id    text PRIMARY KEY,
    event_type  text,
    severity    text,
    geom        geometry(Point, 4326),
    description text,
    road_name   text,
    start_time  timestamptz,
    end_time    timestamptz,
    created_at  timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS traffic_events_geom_idx   ON traffic_events USING gist(geom);
CREATE INDEX IF NOT EXISTS traffic_events_active_idx ON traffic_events(start_time, end_time);

-- Work Zones — 511.org /traffic/wzdx API
CREATE TABLE IF NOT EXISTS work_zones (
    zone_id     text PRIMARY KEY,
    geom        geometry(MultiLineString, 4326),
    road_name   text,
    description text,
    start_time  timestamptz,
    end_time    timestamptz,
    created_at  timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS work_zones_geom_idx ON work_zones USING gist(geom);

-- Toll Rates — 511.org /toll/programs API
CREATE TABLE IF NOT EXISTS toll_rates (
    id            bigserial PRIMARY KEY,
    facility_id   text NOT NULL,
    facility_name text,
    direction     text,
    vehicle_class text DEFAULT 'standard',
    rate_usd      numeric(6,2),
    valid_from    timestamptz,
    valid_to      timestamptz,
    created_at    timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS toll_rates_facility_idx ON toll_rates(facility_id, valid_from);

-- Agency_id indexes on existing tables (for multi-agency query performance)
CREATE INDEX IF NOT EXISTS gtfs_routes_agency_idx     ON gtfs_routes(agency_id);
CREATE INDEX IF NOT EXISTS gtfs_stops_agency_idx      ON gtfs_stops(agency_id);
CREATE INDEX IF NOT EXISTS ops_trip_events_agency_idx ON ops_trip_events(agency_id);
CREATE INDEX IF NOT EXISTS rt_positions_agency_idx    ON rt_vehicle_positions_raw(agency_id);

-- === Agencies catalog (Phase A — single source of truth, mirrors migration 002) ===
-- Sourced from 511.org /transit/operators (or seeded with 8 hand-curated rows
-- when FIVE11_API_KEY is unset).
CREATE TABLE IF NOT EXISTS agencies (
    agency_id       text PRIMARY KEY,
    agency_name     text NOT NULL,
    agency_url      text,
    agency_phone    text,
    agency_timezone text,
    agency_type     text,
    monitored       boolean,
    last_synced_at  timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agencies_monitored ON agencies (monitored);

-- === Planning scenarios (Planning → Scenarios builder) ===

CREATE TABLE IF NOT EXISTS scenarios (
    id             serial PRIMARY KEY,
    name           text NOT NULL,
    description    text,
    stops          jsonb NOT NULL DEFAULT '[]'::jsonb,
    frequency_min  integer NOT NULL DEFAULT 15,
    agency_id      text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_scenarios_created_at ON scenarios (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scenarios_agency_id  ON scenarios (agency_id);

-- === Data health views ===

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_views WHERE viewname = 'vw_ops_events_per_hour'
  ) THEN
    EXECUTE '
      CREATE VIEW vw_ops_events_per_hour AS
      SELECT
        service_date,
        date_trunc(''hour'', actual_arrival) AS hour,
        route_id,
        COUNT(*) AS events_count
      FROM ops_trip_events
      WHERE actual_arrival IS NOT NULL
      GROUP BY service_date, date_trunc(''hour'', actual_arrival), route_id
    ';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_views WHERE viewname = 'vw_rt_positions_per_hour'
  ) THEN
    EXECUTE '
      CREATE VIEW vw_rt_positions_per_hour AS
      SELECT
        date_trunc(''hour'', timestamp) AS hour,
        route_id,
        COUNT(*) AS positions_count
      FROM rt_vehicle_positions_raw
      GROUP BY date_trunc(''hour'', timestamp), route_id
    ';
  END IF;
END
$$;


-- === Transfer Reliability Matrix (Sprint 4a, Feature 1) ===
-- See backend/sql/migrations/004_transfer_reliability.sql for the rationale.
CREATE TABLE IF NOT EXISTS transfer_reliability (
    id                          bigserial PRIMARY KEY,
    from_agency                 text NOT NULL,
    to_agency                   text NOT NULL,
    transfer_stop_id            text NOT NULL,
    scheduled_transfer_minutes  numeric(8,2),
    success_rate_pct            numeric(5,2),
    median_gap_seconds          integer,
    n_observations              integer NOT NULL DEFAULT 0,
    computed_at                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT transfer_reliability_pair_distinct CHECK (from_agency <> to_agency),
    CONSTRAINT transfer_reliability_unique UNIQUE (from_agency, to_agency, transfer_stop_id)
);
CREATE INDEX IF NOT EXISTS idx_transfer_reliability_pair
    ON transfer_reliability (from_agency, to_agency);
CREATE INDEX IF NOT EXISTS idx_transfer_reliability_observed
    ON transfer_reliability (n_observations DESC)
    WHERE n_observations > 0;
CREATE INDEX IF NOT EXISTS idx_ops_trip_events_stop_arrival
    ON ops_trip_events (stop_id, actual_arrival)
    WHERE actual_arrival IS NOT NULL;

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
  agency_id text,
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
  arrival_time text,
  departure_time text,
  stop_id text NOT NULL REFERENCES gtfs_stops(stop_id),
  stop_sequence integer,
  pickup_type integer,
  drop_off_type integer,
  timepoint integer,
  PRIMARY KEY (trip_id, stop_sequence)
);

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
  geom geometry(LineString, 4326)
);

CREATE INDEX IF NOT EXISTS idx_gtfs_shape_geoms_geom
  ON gtfs_shape_geoms
  USING GIST (geom);

-- === Realtime & historical ops ===

CREATE TABLE IF NOT EXISTS rt_vehicle_positions_raw (
  id bigserial PRIMARY KEY,
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

CREATE INDEX IF NOT EXISTS idx_rt_vehicle_positions_raw_timestamp
  ON rt_vehicle_positions_raw (timestamp);

CREATE INDEX IF NOT EXISTS idx_rt_vehicle_positions_raw_geom
  ON rt_vehicle_positions_raw
  USING GIST (geom);

CREATE TABLE IF NOT EXISTS ops_trip_events (
  id bigserial PRIMARY KEY,
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

CREATE TABLE IF NOT EXISTS ops_headways (
  id bigserial PRIMARY KEY,
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


-- Migration 001: Multi-agency support + Sprint 1/2/3 new tables
-- Run once against an existing database before Sprint 1 features will work.
-- schema.sql already incorporates all of these changes for fresh installs.
--
-- Safe to re-run: all statements use IF NOT EXISTS / IF NOT EXISTS guards.

-- =============================================================================
-- Add agency_id to tables that need it
-- =============================================================================

ALTER TABLE gtfs_routes    ADD COLUMN IF NOT EXISTS agency_id text DEFAULT 'AC';
ALTER TABLE gtfs_stops     ADD COLUMN IF NOT EXISTS agency_id text DEFAULT 'AC';
ALTER TABLE gtfs_trips     ADD COLUMN IF NOT EXISTS agency_id text DEFAULT 'AC';
ALTER TABLE gtfs_stop_times ADD COLUMN IF NOT EXISTS agency_id text DEFAULT 'AC';
ALTER TABLE gtfs_shape_geoms ADD COLUMN IF NOT EXISTS agency_id text DEFAULT 'AC';
ALTER TABLE rt_vehicle_positions_raw ADD COLUMN IF NOT EXISTS agency_id text DEFAULT 'AC';
ALTER TABLE ops_trip_events ADD COLUMN IF NOT EXISTS agency_id text DEFAULT 'AC';
ALTER TABLE ops_headways   ADD COLUMN IF NOT EXISTS agency_id text DEFAULT 'AC';

-- =============================================================================
-- Indexes for agency_id filtering (hot path for every multi-agency query)
-- =============================================================================

CREATE INDEX IF NOT EXISTS gtfs_routes_agency_idx     ON gtfs_routes(agency_id);
CREATE INDEX IF NOT EXISTS gtfs_stops_agency_idx      ON gtfs_stops(agency_id);
CREATE INDEX IF NOT EXISTS ops_trip_events_agency_idx ON ops_trip_events(agency_id);
CREATE INDEX IF NOT EXISTS rt_positions_agency_idx    ON rt_vehicle_positions_raw(agency_id);

-- =============================================================================
-- Stop Observations (Sprint 2 — 511.org historical archive)
-- Contains actual vs. scheduled arrival times for every stop on every Bay Area
-- agency, sourced from 511.org's monthly stop_observations.txt archive.
-- =============================================================================

CREATE TABLE IF NOT EXISTS stop_observations (
    id                bigserial PRIMARY KEY,
    service_date      date NOT NULL,
    agency_id         text NOT NULL,
    trip_id           text NOT NULL,
    route_id          text,
    stop_id           text NOT NULL,
    scheduled_arrival timestamptz,
    observed_arrival  timestamptz,
    -- NULL when either timestamp is NULL (no observation recorded)
    delay_seconds     integer GENERATED ALWAYS AS (
        CASE
            WHEN observed_arrival IS NOT NULL AND scheduled_arrival IS NOT NULL
            THEN EXTRACT(EPOCH FROM (observed_arrival - scheduled_arrival))::integer
            ELSE NULL
        END
    ) STORED,
    -- on_time is NULL when observed_arrival is NULL so we can distinguish
    -- "unknown" from "late"
    on_time           boolean GENERATED ALWAYS AS (
        observed_arrival <= scheduled_arrival + INTERVAL '5 minutes'
    ) STORED,
    created_at        timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS so_date_agency_idx  ON stop_observations(service_date, agency_id);
CREATE INDEX IF NOT EXISTS so_agency_route_idx ON stop_observations(agency_id, route_id);
CREATE INDEX IF NOT EXISTS so_stop_idx         ON stop_observations(stop_id);
CREATE INDEX IF NOT EXISTS so_trip_idx         ON stop_observations(trip_id);

-- =============================================================================
-- Traffic Events (Sprint 3 — 511.org /traffic/events API)
-- Active and planned road incidents; refreshed by five11_traffic.py ingestor.
-- =============================================================================

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

-- =============================================================================
-- Work Zones (Sprint 3 — 511.org /traffic/wzdx API)
-- WZDx-format road work zone geometries.
-- =============================================================================

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

-- =============================================================================
-- Toll Rates (Sprint 3 — 511.org /toll/programs API)
-- Bay Bridge + Express Lane dynamic toll rates; refreshed periodically.
-- =============================================================================

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

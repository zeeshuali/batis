-- Migration 005: GTFS Fares v2 ingest schema (BATIS Sprint 4a, Feature 2)
-- Stores fare products, leg rules, transfer rules, and area definitions for
-- every agency that publishes a Fares v2 feed.  The Sprint 4a feature is
-- "ingest only" — no UI in this sprint — but the data unlocks Feature 3
-- (Transfer Desert Map, this sprint) and the Multi-Agency Fare Calculator
-- in Sprint 4b.
--
-- Re-ingest strategy:  the loader DELETEs all rows for an agency before
-- inserting, so we don't need composite UNIQUE constraints that struggle
-- with NULL columns (GTFS Fares v2 has many optional fields).
--
-- Safe to re-run: IF NOT EXISTS / DO blocks throughout.

-- Tag agencies whose fares.zip we've successfully parsed.  UI can use this
-- to skip showing fare-related controls for agencies that don't publish a
-- Fares v2 feed.
ALTER TABLE agencies
    ADD COLUMN IF NOT EXISTS has_fares_v2 boolean NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS fare_products (
    agency_id           text NOT NULL,
    fare_product_id     text NOT NULL,
    fare_product_name   text,
    amount              numeric(8,2),
    currency            text NOT NULL DEFAULT 'USD',
    PRIMARY KEY (agency_id, fare_product_id)
);
CREATE INDEX IF NOT EXISTS idx_fare_products_agency ON fare_products (agency_id);

CREATE TABLE IF NOT EXISTS fare_leg_rules (
    id                  bigserial PRIMARY KEY,
    agency_id           text NOT NULL,
    leg_group_id        text,
    network_id          text,
    from_area_id        text,
    to_area_id          text,
    fare_product_id     text NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fare_leg_rules_agency ON fare_leg_rules (agency_id);
CREATE INDEX IF NOT EXISTS idx_fare_leg_rules_lookup
    ON fare_leg_rules (agency_id, network_id, from_area_id, to_area_id);

CREATE TABLE IF NOT EXISTS fare_transfer_rules (
    id                  bigserial PRIMARY KEY,
    agency_id           text NOT NULL,
    from_leg_group_id   text,
    to_leg_group_id     text,
    transfer_count      integer,
    duration_limit      integer,
    fare_product_id     text,
    amount              numeric(8,2)
);
CREATE INDEX IF NOT EXISTS idx_fare_transfer_rules_agency ON fare_transfer_rules (agency_id);
CREATE INDEX IF NOT EXISTS idx_fare_transfer_rules_from
    ON fare_transfer_rules (agency_id, from_leg_group_id);

CREATE TABLE IF NOT EXISTS fare_areas (
    agency_id           text NOT NULL,
    area_id             text NOT NULL,
    area_name           text,
    PRIMARY KEY (agency_id, area_id)
);
CREATE INDEX IF NOT EXISTS idx_fare_areas_agency ON fare_areas (agency_id);

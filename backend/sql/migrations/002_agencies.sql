-- Migration 002: agencies catalog (BATIS Phase A — agency drill-down)
-- Single source of truth for Bay Area agency metadata, sourced from
-- 511.org /transit/operators.
--
-- Safe to re-run: all statements use IF NOT EXISTS guards.

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

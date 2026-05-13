-- Migration 003: planning scenarios (BATIS Planning → Scenarios builder)
-- Stores hypothetical service additions (a list of new stops + a frequency)
-- so city / agency planners can simulate "what if we added this corridor?"
-- and read the equity / coverage impact back from /scenarios/{id}/impact.
--
-- stops:    jsonb array of {lat, lng, label?} — stops are always edited
--           together, so storing them as one column avoids a child table.
-- agency_id: optional; lets the UI scope a scenario to one operator.
--
-- Safe to re-run: all statements use IF NOT EXISTS guards.

CREATE TABLE IF NOT EXISTS scenarios (
    id             serial PRIMARY KEY,
    name           text NOT NULL,
    description    text,
    stops          jsonb NOT NULL DEFAULT '[]'::jsonb,
    frequency_min  integer NOT NULL DEFAULT 15,
    agency_id      text,                              -- optional; not FK-constrained because catalog can re-sync
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_scenarios_created_at ON scenarios (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scenarios_agency_id  ON scenarios (agency_id);

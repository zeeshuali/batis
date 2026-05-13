-- Migration 004: transfer reliability matrix (BATIS Sprint 4a, Feature 1)
-- One row per (from_agency, to_agency, transfer_stop_id) measuring how often
-- a passenger arriving on `from_agency` at `transfer_stop_id` can connect
-- to the next `to_agency` vehicle at the same stop.
--
-- Populated nightly by app.services.transfer_reliability.compute_transfer_reliability(),
-- which computes from ops_trip_events (clean post-commit e489084).  When the
-- 511.org historic archive is ingested into stop_observations the input
-- query swaps without a schema migration.
--
-- The CHECK guarantees from_agency <> to_agency — same-agency "transfers"
-- (e.g. between two AC Transit lines at MacArthur) are not what this table
-- describes and would be noise in any heatmap.
--
-- Safe to re-run: all statements use IF NOT EXISTS guards.

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

-- Supports the LATERAL-join lookup in compute_transfer_reliability().
-- Without this the outer table scan over 3.9M rows × per-row sorted lookup
-- ran for 6+ minutes against the dev DB and was unusable as a nightly job.
CREATE INDEX IF NOT EXISTS idx_ops_trip_events_stop_arrival
    ON ops_trip_events (stop_id, actual_arrival)
    WHERE actual_arrival IS NOT NULL;

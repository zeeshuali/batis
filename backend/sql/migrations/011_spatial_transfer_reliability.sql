-- 011_spatial_transfer_reliability.sql
-- Rework transfer_reliability to match stops spatially instead of by stop_id label.
--
-- Before: two vehicles counted as a transfer only if they shared the same stop_id
-- text. Agencies name the same physical place differently (a BART station and the
-- AC Transit stop outside it), so the matrix was nearly empty.
--
-- After:
--   * stop_transfer_links holds every cross-agency stop pair within the largest
--     configured radius (settings.transfer_radii_m), with the distance in metres.
--     Both directions are stored. Rebuilt by refresh_stop_transfer_links().
--   * transfer_reliability is keyed by (from_stop_pk, to_stop_pk) and carries
--     distance_m. The radius is a READ-time filter (distance_m <= radius), so the
--     user can pick 50..400 m in the UI without recomputing.
--   * Walk time per pair = max(60 s, distance / walking speed).
--
-- The old table held label-matched rows that are not valid under the new key, so
-- it is emptied here. Recompute with compute_transfer_reliability().

BEGIN;

CREATE INDEX IF NOT EXISTS idx_gtfs_stops_geog
    ON gtfs_stops USING gist ((geom::geography));

CREATE TABLE IF NOT EXISTS stop_transfer_links (
    from_stop_pk  bigint NOT NULL REFERENCES gtfs_stops(stop_pk) ON DELETE CASCADE,
    to_stop_pk    bigint NOT NULL REFERENCES gtfs_stops(stop_pk) ON DELETE CASCADE,
    distance_m    integer NOT NULL,
    PRIMARY KEY (from_stop_pk, to_stop_pk)
);
CREATE INDEX IF NOT EXISTS idx_stop_transfer_links_to ON stop_transfer_links (to_stop_pk);

DELETE FROM transfer_reliability;

ALTER TABLE transfer_reliability DROP CONSTRAINT IF EXISTS transfer_reliability_unique;
ALTER TABLE transfer_reliability ADD COLUMN IF NOT EXISTS from_stop_pk bigint NOT NULL REFERENCES gtfs_stops(stop_pk) ON DELETE CASCADE;
ALTER TABLE transfer_reliability ADD COLUMN IF NOT EXISTS to_stop_pk   bigint NOT NULL REFERENCES gtfs_stops(stop_pk) ON DELETE CASCADE;
ALTER TABLE transfer_reliability ADD COLUMN IF NOT EXISTS to_stop_id   text   NOT NULL;
ALTER TABLE transfer_reliability ADD COLUMN IF NOT EXISTS distance_m   integer NOT NULL;
ALTER TABLE transfer_reliability ADD CONSTRAINT transfer_reliability_unique UNIQUE (from_stop_pk, to_stop_pk);
CREATE INDEX IF NOT EXISTS idx_transfer_reliability_distance ON transfer_reliability (distance_m);

COMMIT;

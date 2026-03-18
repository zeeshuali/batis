from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db import get_engine


def rebuild_trip_stop_snapshots(
    start_date: date,
    end_date: date,
    features_version: str = "v1",
    conn: Optional[Connection] = None,
) -> None:
    """
    Populate trip_stop_snapshots from ops_trip_events for a date range.

    This creates basic operational features per route/trip/stop/time bucket.
    """
    own_conn = False
    if conn is None:
        engine = get_engine()
        conn = engine.connect()
        own_conn = True

    try:
        conn.execute(
            text(
                """
                DELETE FROM trip_stop_snapshots
                WHERE service_date BETWEEN :start_date AND :end_date
                  AND features_version = :features_version;

                INSERT INTO trip_stop_snapshots (
                  service_date,
                  route_id,
                  trip_id,
                  stop_id,
                  stop_sequence,
                  scheduled_arrival,
                  actual_arrival,
                  delay_seconds,
                  headway_seconds,
                  time_of_day_bucket,
                  dow,
                  prev_delay_seconds,
                  prev_headway_seconds,
                  features_version
                )
                SELECT
                  e.service_date,
                  e.route_id,
                  e.trip_id,
                  e.stop_id,
                  e.stop_sequence,
                  e.scheduled_arrival,
                  e.actual_arrival,
                  e.delay_seconds,
                  e.headway_seconds,
                  to_char(e.actual_arrival, 'HH24:00') AS time_of_day_bucket,
                  EXTRACT(DOW FROM e.actual_arrival)::int AS dow,
                  LAG(e.delay_seconds) OVER (
                    PARTITION BY e.route_id
                    ORDER BY e.actual_arrival
                  ) AS prev_delay_seconds,
                  LAG(e.headway_seconds) OVER (
                    PARTITION BY e.route_id
                    ORDER BY e.actual_arrival
                  ) AS prev_headway_seconds,
                  :features_version AS features_version
                FROM ops_trip_events e
                WHERE e.service_date BETWEEN :start_date AND :end_date
                  AND e.actual_arrival IS NOT NULL;
                """
            ),
            {
                "start_date": start_date,
                "end_date": end_date,
                "features_version": features_version,
            },
        )
    finally:
        if own_conn and conn is not None:
            conn.close()


def rebuild_stop_features(
    features_version: str = "v1",
    conn: Optional[Connection] = None,
) -> None:
    """
    Compute basic spatial features for each stop using PostGIS.

    - distance_to_cbd_m: distance to an approximate Oakland CBD point.
    - routes_serving: number of distinct routes serving the stop.
    - stop_density_500m: number of stops within 500m.
    """
    own_conn = False
    if conn is None:
        engine = get_engine()
        conn = engine.connect()
        own_conn = True

    try:
        conn.execute(
            text(
                """
                DELETE FROM stop_features WHERE features_version = :features_version;

                INSERT INTO stop_features (
                  stop_id,
                  distance_to_cbd_m,
                  routes_serving,
                  avg_headway_peak,
                  avg_headway_offpeak,
                  stop_density_500m,
                  features_version
                )
                SELECT
                  s.stop_id,
                  CASE
                    WHEN s.geom IS NOT NULL THEN
                      ST_Distance(
                        s.geom::geography,
                        ST_SetSRID(
                          ST_MakePoint(-122.2711, 37.8044),
                          4326
                        )::geography
                      )
                    ELSE NULL
                  END AS distance_to_cbd_m,
                  COUNT(DISTINCT t.route_id) AS routes_serving,
                  NULL::double precision AS avg_headway_peak,
                  NULL::double precision AS avg_headway_offpeak,
                  (
                    SELECT COUNT(*) - 1
                    FROM gtfs_stops s2
                    WHERE s2.geom IS NOT NULL
                      AND s.geom IS NOT NULL
                      AND ST_DWithin(s.geom, s2.geom, 500)
                  ) AS stop_density_500m,
                  :features_version AS features_version
                FROM gtfs_stops s
                LEFT JOIN gtfs_stop_times st
                  ON st.stop_id = s.stop_id
                LEFT JOIN gtfs_trips t
                  ON t.trip_id = st.trip_id
                GROUP BY s.stop_id, s.geom;
                """
            ),
            {"features_version": features_version},
        )
    finally:
        if own_conn and conn is not None:
            conn.close()


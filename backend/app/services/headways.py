from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db import get_engine


def compute_headways(
    service_date: date,
    conn: Optional[Connection] = None,
) -> None:
    """
    Derive ops_headways for a service date from ops_trip_events.

    For each (route, direction, stop), order actual arrivals chronologically
    and compute the gap to the previous arrival (actual_headway_seconds).
    Scheduled headway is the gap between the corresponding scheduled arrivals.
    A window is flagged as bunching when actual headway falls below 50% of
    the scheduled headway.

    Requires ops_trip_events to contain stop_id, actual_arrival, and
    scheduled_arrival (populated by _process_trip_updates in the RT ingestor).
    """
    own_conn = False
    if conn is None:
        engine = get_engine()
        conn = engine.connect()
        own_conn = True

    try:
        conn.execute(
            text("DELETE FROM ops_headways WHERE service_date = :sd"),
            {"sd": service_date},
        )

        conn.execute(
            text(
                """
                WITH ordered_events AS (
                  SELECT
                    e.service_date,
                    e.route_id,
                    COALESCE(t.direction_id, 0)  AS direction_id,
                    e.stop_id                    AS segment_id,
                    e.actual_arrival,
                    e.scheduled_arrival,
                    LAG(e.actual_arrival)    OVER w AS prev_actual,
                    LAG(e.scheduled_arrival) OVER w AS prev_scheduled
                  FROM ops_trip_events e
                  LEFT JOIN gtfs_trips t ON t.agency_id = e.agency_id
                                        AND t.trip_id   = e.trip_id
                  WHERE e.service_date   = :service_date
                    AND e.stop_id        IS NOT NULL
                    AND e.actual_arrival IS NOT NULL
                  WINDOW w AS (
                    PARTITION BY
                      e.service_date,
                      e.agency_id,
                      e.route_id,
                      COALESCE(t.direction_id, 0),
                      e.stop_id
                    ORDER BY e.actual_arrival
                  )
                )
                INSERT INTO ops_headways (
                  service_date, route_id, direction_id, segment_id,
                  window_start, window_end,
                  scheduled_headway_seconds, actual_headway_seconds, bunching
                )
                SELECT
                  service_date,
                  route_id,
                  direction_id,
                  segment_id,
                  prev_actual    AS window_start,
                  actual_arrival AS window_end,
                  CASE
                    WHEN prev_scheduled IS NOT NULL
                     AND scheduled_arrival IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (scheduled_arrival - prev_scheduled))::integer
                  END AS scheduled_headway_seconds,
                  EXTRACT(EPOCH FROM (actual_arrival - prev_actual))::integer AS actual_headway_seconds,
                  CASE
                    WHEN prev_scheduled IS NOT NULL
                     AND scheduled_arrival IS NOT NULL
                     AND EXTRACT(EPOCH FROM (actual_arrival - prev_actual))
                         < 0.5 * EXTRACT(EPOCH FROM (scheduled_arrival - prev_scheduled))
                    THEN true
                    ELSE false
                  END AS bunching
                FROM ordered_events
                WHERE prev_actual IS NOT NULL
                  -- Ignore implausibly small gaps (<30s) or very large ones (>2h)
                  AND EXTRACT(EPOCH FROM (actual_arrival - prev_actual)) BETWEEN 30 AND 7200
                """
            ),
            {"service_date": service_date},
        )
    finally:
        if own_conn and conn is not None:
            conn.close()

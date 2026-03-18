"""
Seed ops_trip_events from GTFS static scheduled data.

Used when GTFS-RT is unavailable. Generates realistic-looking ops events
by converting scheduled stop_times to timestamped arrivals with small
simulated delays (normal distribution centered on 0).
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from typing import Optional

from dateutil import tz
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db import get_engine

_LA_TZ = tz.gettz("America/Los_Angeles")


def _parse_gtfs_time(service_date: date, time_str: str) -> datetime | None:
    try:
        parts = time_str.strip().split(":")
        h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
        midnight = datetime(service_date.year, service_date.month, service_date.day,
                            0, 0, 0, tzinfo=_LA_TZ)
        return midnight + timedelta(hours=h, minutes=m, seconds=s)
    except Exception:
        return None


def seed_ops_from_static(
    service_date: date,
    max_trips: int = 500,
    conn: Optional[Connection] = None,
) -> int:
    """
    Insert simulated ops_trip_events for `service_date` from GTFS static.

    Uses the first `max_trips` trips (spread across routes). Delays are
    drawn from a normal distribution (mean=60s late, std=120s) capped at ±600s.
    Returns the number of rows inserted.
    """
    own_conn = False
    if conn is None:
        engine = get_engine()
        conn = engine.connect()
        own_conn = True

    try:
        # Delete existing seeded rows for this date
        conn.execute(
            text("DELETE FROM ops_trip_events WHERE service_date = :sd"),
            {"sd": service_date},
        )

        # Fetch a cross-section of trips and their stop times
        rows = conn.execute(
            text(
                """
                SELECT
                    t.trip_id,
                    t.route_id,
                    st.stop_id,
                    st.stop_sequence,
                    st.arrival_time
                FROM gtfs_trips t
                JOIN gtfs_stop_times st ON st.trip_id = t.trip_id
                WHERE t.trip_id IN (
                    SELECT trip_id FROM gtfs_trips
                    ORDER BY trip_id
                    LIMIT :max_trips
                )
                ORDER BY t.trip_id, st.stop_sequence
                """
            ),
            {"max_trips": max_trips},
        ).mappings().all()

        if not rows:
            return 0

        rng = random.Random(service_date.toordinal())  # deterministic per date

        ops_rows = []
        for r in rows:
            scheduled = _parse_gtfs_time(service_date, r["arrival_time"])
            if scheduled is None:
                continue
            delay = int(rng.gauss(60, 120))
            delay = max(-300, min(600, delay))
            actual = scheduled + timedelta(seconds=delay)
            ops_rows.append({
                "service_date": service_date,
                "trip_id": r["trip_id"],
                "route_id": r["route_id"],
                "stop_id": r["stop_id"],
                "stop_sequence": r["stop_sequence"],
                "scheduled_arrival": scheduled,
                "actual_arrival": actual,
                "delay_seconds": delay,
                "headway_seconds": None,
                "occupancy_level": rng.choice(["LOW", "MANY_SEATS_AVAILABLE",
                                               "FEW_SEATS_AVAILABLE", "STANDING_ONLY"]),
            })

        if not ops_rows:
            return 0

        conn.execute(
            text(
                """
                INSERT INTO ops_trip_events (
                  service_date, trip_id, route_id, stop_id, stop_sequence,
                  scheduled_arrival, actual_arrival, delay_seconds,
                  headway_seconds, occupancy_level
                ) VALUES (
                  :service_date, :trip_id, :route_id, :stop_id, :stop_sequence,
                  :scheduled_arrival, :actual_arrival, :delay_seconds,
                  :headway_seconds, :occupancy_level
                )
                """
            ),
            ops_rows,
        )
        return len(ops_rows)
    finally:
        if own_conn and conn is not None:
            conn.close()

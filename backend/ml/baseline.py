"""
Phase 0 SQL Baseline — delay_predictions population.

Uses historical ops_trip_events to compute median delay per
(route_id, day_of_week, hour_of_day) bucket and writes predictions
into delay_predictions for today's remaining hours.

Designed to run every 30 minutes alongside the GTFS-RT ingestor.
No ML dependencies — pure SQL via SQLAlchemy.
"""
from __future__ import annotations

import time
import threading
from datetime import datetime, timezone

from dateutil import tz
from sqlalchemy import text

from app.db import get_engine

MODEL_VERSION = "sql-baseline-v1"
LA_TZ = tz.gettz("America/Los_Angeles")


def run_baseline_once() -> int:
    """
    Compute and upsert delay predictions for today's remaining service hours.

    Returns the number of prediction rows written.
    """
    engine = get_engine()
    now_la = datetime.now(timezone.utc).astimezone(LA_TZ)
    today = now_la.date()
    current_hour = now_la.hour
    today_dow = today.weekday()  # 0=Mon … 6=Sun (Python)
    # Postgres EXTRACT(DOW) uses 0=Sun … 6=Sat; convert
    today_dow_pg = (today_dow + 1) % 7

    with engine.begin() as conn:
        # Delete stale baseline rows for today (will re-insert fresh)
        conn.execute(
            text("""
            DELETE FROM delay_predictions
            WHERE service_date = :today
              AND model_version = :version
            """),
            {"today": today, "version": MODEL_VERSION},
        )

        # Compute median delay per (route_id, day_of_week, hour_of_day)
        # from the last 28 days of ops_trip_events, then project onto
        # today's remaining hours (current hour through end of service).
        result = conn.execute(
            text("""
            WITH history AS (
                SELECT
                    route_id,
                    EXTRACT(DOW  FROM service_date)::int                           AS dow,
                    EXTRACT(HOUR FROM actual_arrival AT TIME ZONE 'America/Los_Angeles')::int AS hour,
                    delay_seconds
                FROM ops_trip_events
                WHERE delay_seconds IS NOT NULL
                  AND service_date >= CURRENT_DATE - INTERVAL '28 days'
                  AND service_date <  CURRENT_DATE
            ),
            stats AS (
                SELECT
                    route_id,
                    dow,
                    hour,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY delay_seconds)::double precision AS median_delay,
                    COUNT(*)                                                                       AS sample_count
                FROM history
                GROUP BY route_id, dow, hour
                HAVING COUNT(*) >= 3
            )
            INSERT INTO delay_predictions (
                service_date,
                route_id,
                predicted_delay_seconds,
                prediction_timestamp,
                model_version
            )
            SELECT
                :today,
                route_id,
                median_delay,
                NOW(),
                :version
            FROM stats
            WHERE dow  = :today_dow
              AND hour >= :current_hour
            RETURNING id
            """),
            {
                "today": today,
                "version": MODEL_VERSION,
                "current_hour": current_hour,
                "today_dow": today_dow_pg,
            },
        )
        rows_written = len(result.fetchall())

    return rows_written


def run_baseline_loop(
    interval_seconds: int = 1800,
    stop_event: "threading.Event | None" = None,
) -> None:
    """
    Long-running loop that refreshes baseline predictions every interval_seconds.
    Default: every 30 minutes.
    """
    _stop = stop_event or threading.Event()
    print("[baseline] Starting SQL baseline prediction loop")
    while not _stop.is_set():
        try:
            from app.core.run_log import job_run
            with job_run("baseline_predictor") as jr:
                n = run_baseline_once()
                jr.set(rows=n)
            print(f"[baseline] Wrote {n} prediction rows at {time.strftime('%H:%M:%S')}")
        except Exception as exc:
            print(f"[baseline] Error: {exc}")
        _stop.wait(interval_seconds)

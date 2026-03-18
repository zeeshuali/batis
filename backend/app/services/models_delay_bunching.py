from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db import get_engine


def generate_delay_predictions(
    start_date: date,
    end_date: date,
    model_version: str = "baseline_delay_v1",
    conn: Optional[Connection] = None,
) -> None:
    """
    Simple baseline delay prediction model.

    For each route and hour-of-day bucket, compute the historical mean delay
    over the requested window, and write that as a prediction into
    delay_predictions.
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
                DELETE FROM delay_predictions
                WHERE service_date BETWEEN :start_date AND :end_date
                  AND model_version = :model_version;

                WITH hourly_stats AS (
                  SELECT
                    service_date,
                    route_id,
                    date_trunc('hour', COALESCE(actual_arrival, scheduled_arrival)) AS hour_bucket,
                    AVG(COALESCE(delay_seconds, 0)) AS avg_delay
                  FROM ops_trip_events
                  WHERE service_date BETWEEN :start_date AND :end_date
                    AND (actual_arrival IS NOT NULL OR scheduled_arrival IS NOT NULL)
                  GROUP BY service_date, route_id, date_trunc('hour', COALESCE(actual_arrival, scheduled_arrival))
                )
                INSERT INTO delay_predictions (
                  service_date,
                  route_id,
                  trip_id,
                  stop_id,
                  prediction_timestamp,
                  predicted_delay_seconds,
                  model_version
                )
                SELECT
                  h.service_date,
                  h.route_id,
                  NULL::text AS trip_id,
                  NULL::text AS stop_id,
                  h.hour_bucket AS prediction_timestamp,
                  h.avg_delay AS predicted_delay_seconds,
                  :model_version AS model_version
                FROM hourly_stats h;
                """
            ),
            {
                "start_date": start_date,
                "end_date": end_date,
                "model_version": model_version,
            },
        )
    finally:
        if own_conn and conn is not None:
            conn.close()


def generate_bunching_predictions(
    start_date: date,
    end_date: date,
    model_version: str = "baseline_bunching_v1",
    conn: Optional[Connection] = None,
) -> None:
    """
    Baseline bunching risk model.

    For each route and headway analysis window, compute the historical fraction
    of windows marked as bunched in ops_headways, and write that as a risk
    score between 0 and 1.
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
                DELETE FROM bunching_predictions
                WHERE service_date BETWEEN :start_date AND :end_date
                  AND model_version = :model_version;

                WITH stats AS (
                  SELECT
                    service_date,
                    route_id,
                    segment_id,
                    window_start,
                    window_end,
                    AVG(CASE WHEN bunching THEN 1.0 ELSE 0.0 END) AS bunching_risk
                  FROM ops_headways
                  WHERE service_date BETWEEN :start_date AND :end_date
                  GROUP BY
                    service_date,
                    route_id,
                    segment_id,
                    window_start,
                    window_end
                )
                INSERT INTO bunching_predictions (
                  service_date,
                  route_id,
                  segment_id,
                  window_start,
                  window_end,
                  bunching_risk,
                  model_version
                )
                SELECT
                  service_date,
                  route_id,
                  segment_id,
                  window_start,
                  window_end,
                  bunching_risk,
                  :model_version AS model_version
                FROM stats;
                """
            ),
            {
                "start_date": start_date,
                "end_date": end_date,
                "model_version": model_version,
            },
        )
    finally:
        if own_conn and conn is not None:
            conn.close()


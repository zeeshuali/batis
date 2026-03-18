from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db import get_engine


def generate_demand_forecasts(
    start_date: date,
    end_date: date,
    model_version: str = "baseline_demand_v1",
    conn: Optional[Connection] = None,
) -> None:
    """
    Baseline demand forecast model.

    Uses historical event counts in ops_trip_events as a proxy for boardings
    per route / stop / time bucket and writes them into demand_forecasts.
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
                DELETE FROM demand_forecasts
                WHERE service_date BETWEEN :start_date AND :end_date
                  AND model_version = :model_version;

                INSERT INTO demand_forecasts (
                  route_id,
                  trip_id,
                  stop_id,
                  service_date,
                  time_bucket,
                  forecast_boardings,
                  lower_ci,
                  upper_ci,
                  model_version
                )
                SELECT
                  e.route_id,
                  NULL::text AS trip_id,
                  e.stop_id,
                  e.service_date,
                  to_char(e.actual_arrival, 'YYYY-MM-DD HH24:00') AS time_bucket,
                  COUNT(*)::double precision AS forecast_boardings,
                  NULL::double precision AS lower_ci,
                  NULL::double precision AS upper_ci,
                  :model_version AS model_version
                FROM ops_trip_events e
                WHERE e.service_date BETWEEN :start_date AND :end_date
                  AND e.actual_arrival IS NOT NULL
                GROUP BY
                  e.route_id,
                  e.stop_id,
                  e.service_date,
                  to_char(e.actual_arrival, 'YYYY-MM-DD HH24:00');
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


def generate_crowding_predictions_from_demand(
    start_date: date,
    end_date: date,
    model_version: str = "baseline_crowding_v1",
    conn: Optional[Connection] = None,
) -> None:
    """
    Derive simple crowding levels from demand_forecasts by thresholding forecast_boardings.

    Writes crowding levels into a separate table for easier consumption.
    """
    from sqlalchemy import text as _text  # local alias to avoid confusion in typing tools

    own_conn = False
    if conn is None:
        engine = get_engine()
        conn = engine.connect()
        own_conn = True

    try:
        conn.execute(
            _text(
                """
                CREATE TABLE IF NOT EXISTS crowding_predictions (
                  id bigserial PRIMARY KEY,
                  route_id text NOT NULL,
                  trip_id text,
                  stop_id text,
                  service_date date NOT NULL,
                  time_bucket text NOT NULL,
                  crowding_level text,
                  model_version text,
                  created_at timestamptz DEFAULT now()
                );
                """
            )
        )

        conn.execute(
            _text(
                """
                DELETE FROM crowding_predictions
                WHERE service_date BETWEEN :start_date AND :end_date
                  AND model_version = :model_version;

                INSERT INTO crowding_predictions (
                  route_id,
                  trip_id,
                  stop_id,
                  service_date,
                  time_bucket,
                  crowding_level,
                  model_version
                )
                SELECT
                  route_id,
                  trip_id,
                  stop_id,
                  service_date,
                  time_bucket,
                  CASE
                    WHEN forecast_boardings IS NULL THEN 'unknown'
                    WHEN forecast_boardings < 10 THEN 'low'
                    WHEN forecast_boardings < 30 THEN 'medium'
                    ELSE 'high'
                  END AS crowding_level,
                  :model_version AS model_version
                FROM demand_forecasts
                WHERE service_date BETWEEN :start_date AND :end_date;
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


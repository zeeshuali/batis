from __future__ import annotations

from datetime import date
from math import sqrt
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db import get_engine


def _ensure_model_evaluations_table(conn: Connection) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS model_evaluations (
              id bigserial PRIMARY KEY,
              model_name text NOT NULL,
              model_version text NOT NULL,
              metric_name text NOT NULL,
              metric_value double precision NOT NULL,
              window_start date NOT NULL,
              window_end date NOT NULL,
              created_at timestamptz DEFAULT now()
            );
            """
        )
    )


def evaluate_delay_model(
    model_version: str,
    start_date: date,
    end_date: date,
    conn: Optional[Connection] = None,
) -> None:
    """
    Compute MAE and RMSE for delay_predictions vs ops_trip_events aggregated
    at route/date/hour level.
    """
    own_conn = False
    if conn is None:
        engine = get_engine()
        conn = engine.connect()
        own_conn = True

    try:
        _ensure_model_evaluations_table(conn)

        rows = conn.execute(
            text(
                """
                WITH actuals AS (
                  SELECT
                    service_date,
                    route_id,
                    date_trunc('hour', COALESCE(actual_arrival, scheduled_arrival)) AS hour_bucket,
                    AVG(COALESCE(delay_seconds, 0)) AS actual_delay
                  FROM ops_trip_events
                  WHERE service_date BETWEEN :start_date AND :end_date
                    AND (actual_arrival IS NOT NULL OR scheduled_arrival IS NOT NULL)
                  GROUP BY service_date, route_id, date_trunc('hour', COALESCE(actual_arrival, scheduled_arrival))
                ),
                preds AS (
                  SELECT
                    service_date,
                    route_id,
                    date_trunc('hour', prediction_timestamp) AS hour_bucket,
                    AVG(predicted_delay_seconds) AS pred_delay
                  FROM delay_predictions
                  WHERE service_date BETWEEN :start_date AND :end_date
                    AND model_version = :model_version
                  GROUP BY service_date, route_id, date_trunc('hour', prediction_timestamp)
                ),
                joined AS (
                  SELECT
                    a.actual_delay,
                    p.pred_delay
                  FROM actuals a
                  JOIN preds p
                    ON a.service_date = p.service_date
                   AND a.route_id = p.route_id
                   AND a.hour_bucket = p.hour_bucket
                )
                SELECT
                  COUNT(*) AS n,
                  SUM(ABS(actual_delay - pred_delay)) AS sum_abs,
                  SUM((actual_delay - pred_delay)^2) AS sum_sq
                FROM joined;
                """
            ),
            {
                "start_date": start_date,
                "end_date": end_date,
                "model_version": model_version,
            },
        ).mappings().first()

        if not rows or rows["n"] in (None, 0):
            return

        n = float(rows["n"])
        mae = rows["sum_abs"] / n if rows["sum_abs"] is not None else 0.0
        rmse = sqrt(rows["sum_sq"] / n) if rows["sum_sq"] is not None else 0.0

        conn.execute(
            text(
                """
                INSERT INTO model_evaluations (
                  model_name,
                  model_version,
                  metric_name,
                  metric_value,
                  window_start,
                  window_end
                ) VALUES
                (:model_name, :model_version, :metric_name_mae, :mae, :window_start, :window_end),
                (:model_name, :model_version, :metric_name_rmse, :rmse, :window_start, :window_end);
                """
            ),
            {
                "model_name": "delay_predictions",
                "model_version": model_version,
                "metric_name_mae": "MAE",
                "metric_name_rmse": "RMSE",
                "mae": mae,
                "rmse": rmse,
                "window_start": start_date,
                "window_end": end_date,
            },
        )
    finally:
        if own_conn and conn is not None:
            conn.close()


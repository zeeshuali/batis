from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db import get_engine


def compute_stop_safety_scores(
    buffer_meters: int = 150,
    crime_weight: float = 1.0,
    collision_weight: float = 1.5,
    lighting_weight: float = -1.0,
    pedestrian_infra_weight: float = -1.0,
    conn: Optional[Connection] = None,
) -> None:
    """
    Compute composite safety scores for each stop based on nearby safety_incidents_raw.

    Positive weights increase risk (crime, collisions), negative weights reduce risk
    (better lighting, pedestrian infrastructure) once such attributes are available
    in safety_incidents_raw.properties.
    """
    own_conn = False
    if conn is None:
        engine = get_engine()
        conn = engine.connect()
        own_conn = True

    try:
        sql = text(
            """
            WITH incident_stats AS (
              SELECT
                s.stop_id,
                COUNT(*) FILTER (WHERE i.incident_type = 'crime') AS crime_incidents_nearby,
                COUNT(*) FILTER (WHERE i.incident_type = 'collision') AS collisions_nearby,
                AVG(
                  COALESCE((i.properties ->> 'lighting_score')::double precision, 0.0)
                ) AS lighting_score,
                AVG(
                  COALESCE((i.properties ->> 'ped_infra_score')::double precision, 0.0)
                ) AS pedestrian_infra_score
              FROM gtfs_stops s
              LEFT JOIN safety_incidents_raw i
                ON s.geom IS NOT NULL
               AND i.geom IS NOT NULL
               AND ST_DWithin(s.geom, i.geom, :buffer_meters)
              GROUP BY s.stop_id
            ),
            scored AS (
              SELECT
                stop_id,
                crime_incidents_nearby,
                collisions_nearby,
                lighting_score,
                pedestrian_infra_score,
                (
                  :crime_weight * COALESCE(crime_incidents_nearby, 0)
                  + :collision_weight * COALESCE(collisions_nearby, 0)
                  + :lighting_weight * COALESCE(lighting_score, 0)
                  + :pedestrian_infra_weight * COALESCE(pedestrian_infra_score, 0)
                ) AS safety_score
              FROM incident_stats
            )
            INSERT INTO stop_safety_scores AS dst (
              stop_id,
              safety_score,
              crime_incidents_nearby,
              collisions_nearby,
              lighting_score,
              pedestrian_infra_score,
              last_computed_at
            )
            SELECT
              stop_id,
              safety_score,
              crime_incidents_nearby,
              collisions_nearby,
              lighting_score,
              pedestrian_infra_score,
              now() AS last_computed_at
            FROM scored
            ON CONFLICT (stop_id) DO UPDATE
            SET
              safety_score = EXCLUDED.safety_score,
              crime_incidents_nearby = EXCLUDED.crime_incidents_nearby,
              collisions_nearby = EXCLUDED.collisions_nearby,
              lighting_score = EXCLUDED.lighting_score,
              pedestrian_infra_score = EXCLUDED.pedestrian_infra_score,
              last_computed_at = EXCLUDED.last_computed_at;
            """
        )

        conn.execute(
            sql,
            {
                "buffer_meters": buffer_meters,
                "crime_weight": crime_weight,
                "collision_weight": collision_weight,
                "lighting_weight": lighting_weight,
                "pedestrian_infra_weight": pedestrian_infra_weight,
            },
        )
    finally:
        if own_conn and conn is not None:
            conn.close()


from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db import get_engine

# Approximate bounding box for the AC Transit service area
_BBOX = {
    "min_lon": -122.36,
    "min_lat": 37.70,
    "max_lon": -122.11,
    "max_lat": 37.89,
    # ~500 m grid: 0.005° lon ≈ 440 m, 0.004° lat ≈ 445 m at 37.8° N
    "step_lon": 0.005,
    "step_lat": 0.004,
    # Walking distance threshold in degrees (≈ 400 m)
    "walk_deg": 0.0036,
    # Divisor to convert raw trip count to trips-per-hour (18 service hours/day)
    "service_hours": 18.0,
}


def build_coverage_cells(conn: Optional[Connection] = None) -> None:
    """
    Generate a ~500 m grid over the AC Transit service area and compute
    per-cell accessibility metrics using PostGIS and GTFS static data.

    Metrics per cell:
    - nearest_stop_id / distance_to_nearest_stop_m
    - stops_within_walk (within ~400 m of cell centroid)
    - effective_frequency_per_hour (average trips/hr across walk-accessible stops)

    Requires gtfs_stops and gtfs_stop_times to already be loaded.
    """
    own_conn = False
    if conn is None:
        engine = get_engine()
        conn = engine.connect()
        own_conn = True

    try:
        conn.execute(text("DELETE FROM coverage_cells"))

        conn.execute(
            text(
                """
                WITH grid AS (
                  -- Generate a rectangular grid of cells over the service area
                  SELECT
                    lon::double precision  AS lon,
                    lat::double precision  AS lat,
                    ST_MakeEnvelope(
                      lon::double precision,
                      lat::double precision,
                      (lon + :step_lon)::double precision,
                      (lat + :step_lat)::double precision,
                      4326
                    ) AS geom,
                    concat(
                      round(lon::numeric, 4), '_', round(lat::numeric, 4)
                    ) AS cell_id
                  FROM generate_series(
                    CAST(:min_lon AS numeric),
                    CAST(:max_lon AS numeric) - CAST(:step_lon AS numeric),
                    CAST(:step_lon AS numeric)
                  ) AS lon,
                  generate_series(
                    CAST(:min_lat AS numeric),
                    CAST(:max_lat AS numeric) - CAST(:step_lat AS numeric),
                    CAST(:step_lat AS numeric)
                  ) AS lat
                ),

                -- Nearest stop to each cell centroid (LATERAL avoids full cross-join)
                nearest_stop AS (
                  SELECT DISTINCT ON (g.cell_id)
                    g.cell_id,
                    s.stop_id AS nearest_stop_id,
                    ST_Distance(
                      ST_Centroid(g.geom)::geography,
                      s.geom::geography
                    ) AS distance_to_nearest_stop_m
                  FROM grid g
                  CROSS JOIN LATERAL (
                    SELECT stop_id, geom
                    FROM gtfs_stops
                    WHERE geom IS NOT NULL
                    ORDER BY ST_Centroid(g.geom) <-> geom
                    LIMIT 1
                  ) s
                ),

                -- Stops within walking distance of each cell centroid
                walk_stops AS (
                  SELECT
                    g.cell_id,
                    COUNT(s.stop_id) AS stops_within_walk
                  FROM grid g
                  JOIN gtfs_stops s
                    ON s.geom IS NOT NULL
                   AND ST_DWithin(ST_Centroid(g.geom), s.geom, :walk_deg)
                  GROUP BY g.cell_id
                ),

                -- Per-stop trip frequency (distinct trips / service hours as proxy for trips/hr)
                stop_freq AS (
                  SELECT
                    st.stop_id,
                    COUNT(DISTINCT st.trip_id)::double precision / :service_hours AS trips_per_hour
                  FROM gtfs_stop_times st
                  GROUP BY st.stop_id
                ),

                -- Average frequency across walk-accessible stops per cell
                cell_freq AS (
                  SELECT
                    g.cell_id,
                    AVG(f.trips_per_hour) AS effective_frequency_per_hour
                  FROM grid g
                  JOIN gtfs_stops s
                    ON s.geom IS NOT NULL
                   AND ST_DWithin(ST_Centroid(g.geom), s.geom, :walk_deg)
                  JOIN stop_freq f ON f.stop_id = s.stop_id
                  GROUP BY g.cell_id
                )

                INSERT INTO coverage_cells (
                  cell_id,
                  geom,
                  nearest_stop_id,
                  distance_to_nearest_stop_m,
                  stops_within_walk,
                  effective_frequency_per_hour
                )
                SELECT
                  g.cell_id,
                  g.geom,
                  n.nearest_stop_id,
                  n.distance_to_nearest_stop_m,
                  COALESCE(w.stops_within_walk, 0),
                  COALESCE(f.effective_frequency_per_hour, 0.0)
                FROM grid g
                LEFT JOIN nearest_stop n USING (cell_id)
                LEFT JOIN walk_stops   w USING (cell_id)
                LEFT JOIN cell_freq    f USING (cell_id)
                """
            ),
            _BBOX,
        )
    finally:
        if own_conn and conn is not None:
            conn.close()


def build_transit_deserts(
    desert_distance_m: float = 400.0,
    desert_frequency: float = 2.0,
    conn: Optional[Connection] = None,
) -> None:
    """
    Identify transit desert polygons from coverage_cells.

    A cell qualifies as a desert if:
    - Its nearest stop is more than desert_distance_m away, OR
    - Its effective frequency is below desert_frequency trips/hour.

    Adjacent desert cells are merged into single polygons using
    ST_ClusterDBSCAN, giving one row per contiguous desert region.

    Requires build_coverage_cells() to have been run first.
    """
    own_conn = False
    if conn is None:
        engine = get_engine()
        conn = engine.connect()
        own_conn = True

    try:
        conn.execute(text("DELETE FROM transit_deserts"))

        conn.execute(
            text(
                """
                WITH desert_cells AS (
                  SELECT
                    geom,
                    -- Score: 1.0 = no walkable stop, +0.5 = low frequency
                    (CASE WHEN distance_to_nearest_stop_m > :desert_distance_m THEN 1.0 ELSE 0.5 END
                     + CASE WHEN effective_frequency_per_hour < :desert_frequency  THEN 0.5 ELSE 0.0 END
                    ) AS desert_score
                  FROM coverage_cells
                  WHERE distance_to_nearest_stop_m > :desert_distance_m
                     OR effective_frequency_per_hour < :desert_frequency
                ),

                -- Cluster touching/overlapping cells so each contiguous region
                -- becomes one polygon. eps=0.0001° keeps only cells that share
                -- or nearly share a boundary.
                clustered AS (
                  SELECT
                    geom,
                    desert_score,
                    ST_ClusterDBSCAN(geom, eps := 0.0001, minpoints := 1) OVER () AS cluster_id
                  FROM desert_cells
                )

                INSERT INTO transit_deserts (geom, desert_score, notes)
                SELECT
                  ST_Multi(ST_Union(geom)) AS geom,
                  AVG(desert_score)    AS desert_score,
                  'auto-generated'     AS notes
                FROM clustered
                GROUP BY cluster_id
                """
            ),
            {
                "desert_distance_m": desert_distance_m,
                "desert_frequency": desert_frequency,
            },
        )
    finally:
        if own_conn and conn is not None:
            conn.close()

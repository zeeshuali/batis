from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection


def get_reliability_summary(
    conn: Connection,
    start_date: date,
    end_date: date,
    route_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Basic reliability KPIs per route over a date range.
    """
    params: Dict[str, Any] = {"start_date": start_date, "end_date": end_date}
    route_filter = ""
    if route_ids:
        route_filter = "AND route_id = ANY(:route_ids)"
        params["route_ids"] = route_ids

    sql = text(
        f"""
        SELECT
          route_id,
          COUNT(*) AS sample_events,
          AVG(CASE WHEN delay_seconds IS NULL THEN 0 ELSE delay_seconds END) AS avg_delay_seconds
        FROM ops_trip_events
        WHERE service_date BETWEEN :start_date AND :end_date
        {route_filter}
        GROUP BY route_id
        ORDER BY route_id
        """
    )
    rows = conn.execute(sql, params).mappings().all()
    return [dict(r) for r in rows]


def get_reliability_by_route(
    conn: Connection,
    route_id: str,
    service_date: date,
) -> List[Dict[str, Any]]:
    """
    Per-stop/per-trip view for a given route and service date.
    """
    sql = text(
        """
        SELECT
          trip_id,
          stop_id,
          stop_sequence,
          scheduled_arrival,
          actual_arrival,
          delay_seconds,
          headway_seconds
        FROM ops_trip_events
        WHERE service_date = :service_date
          AND route_id = :route_id
        ORDER BY trip_id, stop_sequence
        """
    )
    rows = conn.execute(sql, {"service_date": service_date, "route_id": route_id}).mappings().all()
    return [dict(r) for r in rows]


def get_coverage_cells(
    conn: Connection,
    bbox: Optional[Tuple[float, float, float, float]] = None,
) -> List[Dict[str, Any]]:
    """
    Returns coverage cells as GeoJSON features for mapping.
    """
    if bbox:
        min_lon, min_lat, max_lon, max_lat = bbox
        sql = text(
            """
            SELECT
              id,
              cell_id,
              ST_AsGeoJSON(geom)::json AS geometry,
              nearest_stop_id,
              distance_to_nearest_stop_m,
              stops_within_walk,
              effective_frequency_per_hour,
              equity_score
            FROM coverage_cells
            WHERE geom && ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)
            """
        )
        rows = conn.execute(
            sql,
            {
                "min_lon": min_lon,
                "min_lat": min_lat,
                "max_lon": max_lon,
                "max_lat": max_lat,
            },
        ).mappings().all()
    else:
        sql = text(
            """
            SELECT
              id,
              cell_id,
              ST_AsGeoJSON(geom)::json AS geometry,
              nearest_stop_id,
              distance_to_nearest_stop_m,
              stops_within_walk,
              effective_frequency_per_hour,
              equity_score
            FROM coverage_cells
            """
        )
        rows = conn.execute(sql).mappings().all()

    features: List[Dict[str, Any]] = []
    for r in rows:
        props = dict(r)
        geom = props.pop("geometry")
        features.append({"type": "Feature", "geometry": geom, "properties": props})
    return features


def get_transit_deserts(
    conn: Connection,
    bbox: Optional[Tuple[float, float, float, float]] = None,
) -> List[Dict[str, Any]]:
    """
    GeoJSON polygons representing transit deserts.
    """
    if bbox:
        min_lon, min_lat, max_lon, max_lat = bbox
        sql = text(
            """
            SELECT
              id,
              ST_AsGeoJSON(geom)::json AS geometry,
              desert_score,
              notes
            FROM transit_deserts
            WHERE geom && ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)
            """
        )
        rows = conn.execute(
            sql,
            {
                "min_lon": min_lon,
                "min_lat": min_lat,
                "max_lon": max_lon,
                "max_lat": max_lat,
            },
        ).mappings().all()
    else:
        sql = text(
            """
            SELECT
              id,
              ST_AsGeoJSON(geom)::json AS geometry,
              desert_score,
              notes
            FROM transit_deserts
            """
        )
        rows = conn.execute(sql).mappings().all()

    features: List[Dict[str, Any]] = []
    for r in rows:
        props = dict(r)
        geom = props.pop("geometry")
        features.append({"type": "Feature", "geometry": geom, "properties": props})
    return features


def get_stop_safety_scores(
    conn: Connection,
    min_score: Optional[float] = None,
    max_score: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Stop-level safety scores and contributing metrics.
    """
    clauses = []
    params: Dict[str, Any] = {}
    if min_score is not None:
        clauses.append("safety_score >= :min_score")
        params["min_score"] = min_score
    if max_score is not None:
        clauses.append("safety_score <= :max_score")
        params["max_score"] = max_score

    where = ""
    if clauses:
        where = "WHERE " + " AND ".join(clauses)

    sql = text(
        f"""
        SELECT
          stop_id,
          safety_score,
          crime_incidents_nearby,
          collisions_nearby,
          lighting_score,
          pedestrian_infra_score,
          last_computed_at
        FROM stop_safety_scores
        {where}
        """
    )
    rows = conn.execute(sql, params).mappings().all()
    return [dict(r) for r in rows]


def get_demand_forecasts(
    conn: Connection,
    route_id: Optional[str],
    start_date: date,
    end_date: date,
) -> List[Dict[str, Any]]:
    """
    Demand forecasts for given route (or all routes) and date range.
    """
    params: Dict[str, Any] = {"start_date": start_date, "end_date": end_date}
    route_clause = ""
    if route_id:
        route_clause = "AND route_id = :route_id"
        params["route_id"] = route_id

    sql = text(
        f"""
        SELECT
          route_id,
          trip_id,
          stop_id,
          service_date,
          time_bucket,
          forecast_boardings,
          lower_ci,
          upper_ci,
          model_version
        FROM demand_forecasts
        WHERE service_date BETWEEN :start_date AND :end_date
        {route_clause}
        ORDER BY route_id, service_date, time_bucket
        """
    )
    rows = conn.execute(sql, params).mappings().all()
    return [dict(r) for r in rows]


def get_delay_predictions(
    conn: Connection,
    start_date: date,
    end_date: date,
    route_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Delay predictions aggregated by route and prediction timestamp.
    """
    params: Dict[str, Any] = {"start_date": start_date, "end_date": end_date}
    route_filter = ""
    if route_ids:
        route_filter = "AND route_id = ANY(:route_ids)"
        params["route_ids"] = route_ids

    sql = text(
        f"""
        SELECT
          service_date,
          route_id,
          prediction_timestamp,
          predicted_delay_seconds,
          model_version
        FROM delay_predictions
        WHERE service_date BETWEEN :start_date AND :end_date
        {route_filter}
        ORDER BY route_id, prediction_timestamp
        """
    )
    rows = conn.execute(sql, params).mappings().all()
    return [dict(r) for r in rows]


def get_crowding_predictions(
    conn: Connection,
    start_date: date,
    end_date: date,
    route_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Crowding level predictions per route/stop/time bucket.
    """
    params: Dict[str, Any] = {"start_date": start_date, "end_date": end_date}
    route_clause = ""
    if route_id:
        route_clause = "AND route_id = :route_id"
        params["route_id"] = route_id

    sql = text(
        f"""
        SELECT
          route_id,
          trip_id,
          stop_id,
          service_date,
          time_bucket,
          crowding_level,
          model_version
        FROM crowding_predictions
        WHERE service_date BETWEEN :start_date AND :end_date
        {route_clause}
        ORDER BY route_id, service_date, time_bucket
        """
    )
    rows = conn.execute(sql, params).mappings().all()
    return [dict(r) for r in rows]


def get_reliability_stops_geo(
    conn: Connection,
    start_date: date,
    end_date: date,
    route_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    GeoJSON point features: one per stop, aggregating avg delay and sample count
    from ops_trip_events over the date range. Only stops with geometry are returned.
    """
    params: Dict[str, Any] = {"start_date": start_date, "end_date": end_date}
    route_filter = ""
    if route_ids:
        route_filter = "AND e.route_id = ANY(:route_ids)"
        params["route_ids"] = route_ids

    sql = text(
        f"""
        SELECT
          s.stop_id,
          s.stop_name,
          ST_AsGeoJSON(s.geom)::json AS geometry,
          AVG(COALESCE(e.delay_seconds, 0))::double precision AS avg_delay_seconds,
          COUNT(*) AS sample_count
        FROM gtfs_stops s
        JOIN ops_trip_events e ON e.stop_id = s.stop_id
        WHERE e.service_date BETWEEN :start_date AND :end_date
          AND s.geom IS NOT NULL
          {route_filter}
        GROUP BY s.stop_id, s.stop_name, s.geom
        ORDER BY avg_delay_seconds DESC
        """
    )
    rows = conn.execute(sql, params).mappings().all()
    features: List[Dict[str, Any]] = []
    for r in rows:
        props = dict(r)
        geom = props.pop("geometry")
        features.append({"type": "Feature", "geometry": geom, "properties": props})
    return features


def get_safety_stops_geo(
    conn: Connection,
    min_score: Optional[float] = None,
    max_score: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    GeoJSON point features: stops with safety scores and nearby incident counts,
    joined with stop geometry for map rendering.
    """
    clauses = ["s.geom IS NOT NULL", "ss.safety_score IS NOT NULL"]
    params: Dict[str, Any] = {}
    if min_score is not None:
        clauses.append("ss.safety_score >= :min_score")
        params["min_score"] = min_score
    if max_score is not None:
        clauses.append("ss.safety_score <= :max_score")
        params["max_score"] = max_score

    where = "WHERE " + " AND ".join(clauses)
    sql = text(
        f"""
        SELECT
          s.stop_id,
          s.stop_name,
          ST_AsGeoJSON(s.geom)::json AS geometry,
          ss.safety_score,
          ss.crime_incidents_nearby,
          ss.collisions_nearby,
          ss.lighting_score,
          ss.pedestrian_infra_score
        FROM gtfs_stops s
        JOIN stop_safety_scores ss ON ss.stop_id = s.stop_id
        {where}
        ORDER BY ss.safety_score DESC
        """
    )
    rows = conn.execute(sql, params).mappings().all()
    features: List[Dict[str, Any]] = []
    for r in rows:
        props = dict(r)
        geom = props.pop("geometry")
        features.append({"type": "Feature", "geometry": geom, "properties": props})
    return features


def get_crowding_stops_geo(
    conn: Connection,
    start_date: date,
    end_date: date,
    route_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    GeoJSON point features: stops with the most frequent (modal) crowding level
    predicted over the date range.
    """
    params: Dict[str, Any] = {"start_date": start_date, "end_date": end_date}
    route_clause = ""
    if route_id:
        route_clause = "AND cp.route_id = :route_id"
        params["route_id"] = route_id

    sql = text(
        f"""
        SELECT
          s.stop_id,
          s.stop_name,
          ST_AsGeoJSON(s.geom)::json AS geometry,
          MODE() WITHIN GROUP (ORDER BY cp.crowding_level) AS dominant_crowding_level,
          COUNT(*) AS prediction_count
        FROM gtfs_stops s
        JOIN crowding_predictions cp ON cp.stop_id = s.stop_id
        WHERE cp.service_date BETWEEN :start_date AND :end_date
          AND s.geom IS NOT NULL
          {route_clause}
        GROUP BY s.stop_id, s.stop_name, s.geom
        """
    )
    rows = conn.execute(sql, params).mappings().all()
    features: List[Dict[str, Any]] = []
    for r in rows:
        props = dict(r)
        geom = props.pop("geometry")
        features.append({"type": "Feature", "geometry": geom, "properties": props})
    return features


def get_demand_stops_geo(
    conn: Connection,
    start_date: date,
    end_date: date,
    route_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    GeoJSON point features: stops with total forecast boardings summed over
    the date range. Circle radius on the map is driven by total_boardings.
    """
    params: Dict[str, Any] = {"start_date": start_date, "end_date": end_date}
    route_clause = ""
    if route_id:
        route_clause = "AND df.route_id = :route_id"
        params["route_id"] = route_id

    sql = text(
        f"""
        SELECT
          s.stop_id,
          s.stop_name,
          ST_AsGeoJSON(s.geom)::json AS geometry,
          SUM(COALESCE(df.forecast_boardings, 0))::double precision AS total_boardings,
          COUNT(DISTINCT df.route_id) AS routes_serving
        FROM gtfs_stops s
        JOIN demand_forecasts df ON df.stop_id = s.stop_id
        WHERE df.service_date BETWEEN :start_date AND :end_date
          AND s.geom IS NOT NULL
          {route_clause}
        GROUP BY s.stop_id, s.stop_name, s.geom
        ORDER BY total_boardings DESC
        """
    )
    rows = conn.execute(sql, params).mappings().all()
    features: List[Dict[str, Any]] = []
    for r in rows:
        props = dict(r)
        geom = props.pop("geometry")
        features.append({"type": "Feature", "geometry": geom, "properties": props})
    return features


def get_stop_detail(conn: Connection, stop_id: str) -> Optional[Dict[str, Any]]:
    """Full detail for a single stop: info, delay history, routes, departures, nearby incidents."""
    row = conn.execute(
        text("""
        SELECT
            s.stop_id, s.stop_code, s.stop_name, s.stop_desc,
            s.stop_lat, s.stop_lon,
            COALESCE(sc.safety_score, 0)::double precision         AS safety_score,
            COALESCE(sc.crime_incidents_nearby, 0)                 AS crime_incidents_nearby,
            COALESCE(sc.collisions_nearby, 0)                      AS collisions_nearby
        FROM gtfs_stops s
        LEFT JOIN stop_safety_scores sc ON sc.stop_id = s.stop_id
        WHERE s.stop_id = :stop_id
        """),
        {"stop_id": stop_id},
    ).mappings().first()
    if not row:
        return None
    result: Dict[str, Any] = dict(row)

    # Per-day delay history (last 14 days)
    delay_rows = conn.execute(
        text("""
        SELECT service_date,
               ROUND(AVG(delay_seconds))::int  AS avg_delay,
               COUNT(*)                         AS n
        FROM ops_trip_events
        WHERE stop_id = :stop_id
        GROUP BY service_date
        ORDER BY service_date DESC
        LIMIT 14
        """),
        {"stop_id": stop_id},
    ).mappings().all()
    result["delay_history"] = [
        {"date": str(r["service_date"]), "avg_delay": r["avg_delay"], "n": r["n"]}
        for r in delay_rows
    ]

    # Routes serving this stop
    route_rows = conn.execute(
        text("""
        SELECT DISTINCT r.route_id, r.route_short_name, r.route_long_name,
               COALESCE(r.route_color, '3b82f6') AS route_color
        FROM gtfs_stop_times st
        JOIN gtfs_trips  t ON t.trip_id  = st.trip_id
        JOIN gtfs_routes r ON r.route_id = t.route_id
        WHERE st.stop_id = :stop_id
        ORDER BY r.route_short_name NULLS LAST
        """),
        {"stop_id": stop_id},
    ).mappings().all()
    result["routes"] = [dict(r) for r in route_rows]

    # Next 12 scheduled departures (sorted by time string — works for GTFS HH:MM:SS)
    dep_rows = conn.execute(
        text("""
        SELECT DISTINCT st.departure_time, t.route_id,
               r.route_short_name, t.trip_headsign, t.direction_id
        FROM gtfs_stop_times st
        JOIN gtfs_trips  t ON t.trip_id  = st.trip_id
        JOIN gtfs_routes r ON r.route_id = t.route_id
        WHERE st.stop_id = :stop_id
        ORDER BY st.departure_time
        LIMIT 12
        """),
        {"stop_id": stop_id},
    ).mappings().all()
    result["departures"] = [dict(r) for r in dep_rows]

    # Nearby incidents within 300 m
    incident_rows = conn.execute(
        text("""
        SELECT i.incident_type, i.severity,
               to_char(i.occurred_at, 'YYYY-MM-DD') AS date,
               ROUND(ST_Distance(i.geom::geography, s.geom::geography)) AS distance_m
        FROM safety_incidents_raw i
        CROSS JOIN gtfs_stops s
        WHERE s.stop_id = :stop_id
          AND s.geom IS NOT NULL
          AND ST_DWithin(i.geom::geography, s.geom::geography, 300)
        ORDER BY i.occurred_at DESC NULLS LAST
        LIMIT 8
        """),
        {"stop_id": stop_id},
    ).mappings().all()
    result["nearby_incidents"] = [dict(r) for r in incident_rows]

    return result


def get_routes_list(conn: Connection) -> List[Dict[str, Any]]:
    """All routes sorted by short name."""
    rows = conn.execute(
        text("""
        SELECT route_id, route_short_name, route_long_name,
               route_type, route_color, route_text_color, agency_id
        FROM gtfs_routes
        ORDER BY LPAD(COALESCE(route_short_name, route_id), 10, '0'), route_id
        """)
    ).mappings().all()
    return [dict(r) for r in rows]


def get_route_geo(conn: Connection, route_id: str) -> Dict[str, Any]:
    """GeoJSON FeatureCollection: the route's shape LineString + stop Points."""
    import json as _json
    features: List[Dict[str, Any]] = []

    # Pick the most-used shape_id for this route
    shape_row = conn.execute(
        text("""
        SELECT sg.shape_id, ST_AsGeoJSON(sg.geom)::json AS geometry
        FROM gtfs_shape_geoms sg
        JOIN (
            SELECT shape_id, COUNT(*) AS n
            FROM gtfs_trips
            WHERE route_id = :route_id AND shape_id IS NOT NULL
            GROUP BY shape_id
            ORDER BY n DESC
            LIMIT 1
        ) mc ON mc.shape_id = sg.shape_id
        """),
        {"route_id": route_id},
    ).mappings().first()
    if shape_row:
        features.append({
            "type": "Feature",
            "geometry": shape_row["geometry"],
            "properties": {"feature_type": "shape", "route_id": route_id},
        })

    # Unique stops along the route
    stop_rows = conn.execute(
        text("""
        SELECT s.stop_id, s.stop_name, s.stop_code, s.stop_lat, s.stop_lon,
               ST_AsGeoJSON(s.geom)::json AS geometry,
               MIN(st.stop_sequence) AS seq
        FROM gtfs_stop_times st
        JOIN gtfs_trips t ON t.trip_id  = st.trip_id
        JOIN gtfs_stops s ON s.stop_id  = st.stop_id
        WHERE t.route_id = :route_id
          AND s.geom IS NOT NULL
        GROUP BY s.stop_id, s.stop_name, s.stop_code, s.stop_lat, s.stop_lon, s.geom
        ORDER BY MIN(st.stop_sequence)
        """),
        {"route_id": route_id},
    ).mappings().all()
    for r in stop_rows:
        features.append({
            "type": "Feature",
            "geometry": r["geometry"],
            "properties": {
                "feature_type": "stop",
                "stop_id": r["stop_id"],
                "stop_name": r["stop_name"],
                "stop_code": r["stop_code"],
                "stop_sequence": r["seq"],
                "route_id": route_id,
            },
        })
    return {"type": "FeatureCollection", "features": features}


def get_live_vehicles(conn: Connection) -> Dict[str, Any]:
    """GeoJSON of vehicle positions from the last 3 minutes."""
    rows = conn.execute(
        text("""
        SELECT DISTINCT ON (vehicle_id)
            vehicle_id, trip_id, route_id,
            latitude, longitude, bearing, speed, occupancy_status,
            timestamp,
            ST_AsGeoJSON(geom)::json AS geometry
        FROM rt_vehicle_positions_raw
        WHERE timestamp >= NOW() - INTERVAL '3 minutes'
          AND geom IS NOT NULL
        ORDER BY vehicle_id, timestamp DESC
        """)
    ).mappings().all()
    features = []
    for r in rows:
        props = dict(r)
        geom = props.pop("geometry")
        props["timestamp"] = str(props["timestamp"]) if props.get("timestamp") else None
        features.append({"type": "Feature", "geometry": geom, "properties": props})
    return {"type": "FeatureCollection", "features": features}


def get_reliability_trend(
    conn: Connection,
    route_id: Optional[str],
    days: int = 30,
) -> List[Dict[str, Any]]:
    """Daily on-time % and avg delay (aggregated across all routes) over the last N days."""
    params: Dict[str, Any] = {"days": days}
    route_clause = ""
    if route_id:
        route_clause = "AND route_id = :route_id"
        params["route_id"] = route_id
    rows = conn.execute(
        text(f"""
        SELECT
            service_date::text AS date,
            COUNT(*) AS total_events,
            ROUND(AVG(delay_seconds)) AS avg_delay,
            ROUND(
                SUM(CASE WHEN delay_seconds <= 60 THEN 1 ELSE 0 END)::numeric
                / NULLIF(COUNT(*), 0) * 100, 1
            )::double precision AS on_time_pct
        FROM ops_trip_events
        WHERE service_date >= CURRENT_DATE - (:days || ' days')::interval
          AND delay_seconds IS NOT NULL
          {route_clause}
        GROUP BY service_date
        ORDER BY service_date
        """),
        params,
    ).mappings().all()
    return [dict(r) for r in rows]


def get_route_headways(
    conn: Connection,
    route_id: str,
    service_date: date,
) -> List[Dict[str, Any]]:
    """Headway by hour-of-day for a route on a given service date."""
    rows = conn.execute(
        text("""
        WITH arrivals AS (
            SELECT
                EXTRACT(HOUR FROM actual_arrival AT TIME ZONE 'America/Los_Angeles')::int AS hour,
                EXTRACT(EPOCH FROM (
                    actual_arrival - LAG(actual_arrival) OVER (
                        PARTITION BY stop_id ORDER BY actual_arrival
                    )
                )) AS gap_seconds
            FROM ops_trip_events
            WHERE route_id = :route_id
              AND service_date = :service_date
              AND actual_arrival IS NOT NULL
        )
        SELECT
            hour,
            ROUND(AVG(gap_seconds) / 60.0, 1)::double precision AS avg_headway_minutes
        FROM arrivals
        WHERE gap_seconds BETWEEN 60 AND 7200
        GROUP BY hour
        ORDER BY hour
        """),
        {"route_id": route_id, "service_date": service_date},
    ).mappings().all()
    return [dict(r) for r in rows]


def get_realtime_departures(
    conn: Connection,
    stop_id: str,
) -> List[Dict[str, Any]]:
    """Upcoming scheduled departures merged with latest RT delay for this stop."""
    rows = conn.execute(
        text("""
        SELECT
            st.departure_time,
            t.trip_id,
            t.route_id,
            r.route_short_name,
            r.route_color,
            t.trip_headsign,
            t.direction_id,
            -- latest known delay for this trip at this stop
            (
                SELECT e.delay_seconds
                FROM ops_trip_events e
                WHERE e.trip_id = t.trip_id
                  AND e.stop_id = st.stop_id
                  AND e.service_date = CURRENT_DATE
                ORDER BY e.actual_arrival DESC NULLS LAST
                LIMIT 1
            ) AS current_delay_seconds
        FROM gtfs_stop_times st
        JOIN gtfs_trips  t ON t.trip_id  = st.trip_id
        JOIN gtfs_routes r ON r.route_id = t.route_id
        WHERE st.stop_id = :stop_id
        ORDER BY st.departure_time
        LIMIT 20
        """),
        {"stop_id": stop_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def get_stop_reachability(
    conn: Connection,
    stop_id: str,
    minutes: int = 30,
) -> Dict[str, Any]:
    """
    Simplified reachability: find all stops served by routes that also serve
    the origin stop, within a transfer-time budget.
    Returns a GeoJSON Polygon (convex hull of reachable stops).
    """
    # Step 1: routes serving the origin stop
    route_rows = conn.execute(
        text("""
        SELECT DISTINCT t.route_id
        FROM gtfs_stop_times st
        JOIN gtfs_trips t ON t.trip_id = st.trip_id
        WHERE st.stop_id = :stop_id
        """),
        {"stop_id": stop_id},
    ).mappings().all()
    route_ids = [r["route_id"] for r in route_rows]
    if not route_ids:
        return {"type": "FeatureCollection", "features": []}

    # Step 2: all stops reachable on those routes (direct, no transfers)
    hull_row = conn.execute(
        text("""
        SELECT
            ST_AsGeoJSON(
                ST_ConvexHull(
                    ST_Collect(s.geom)
                )
            )::json AS hull_geom,
            COUNT(DISTINCT s.stop_id) AS stop_count
        FROM gtfs_stop_times st
        JOIN gtfs_trips t ON t.trip_id = st.trip_id
        JOIN gtfs_stops s ON s.stop_id = st.stop_id
        WHERE t.route_id = ANY(:route_ids)
          AND s.geom IS NOT NULL
        """),
        {"route_ids": route_ids},
    ).mappings().first()

    if not hull_row or not hull_row["hull_geom"]:
        return {"type": "FeatureCollection", "features": []}

    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": hull_row["hull_geom"],
            "properties": {
                "stop_id": stop_id,
                "minutes": minutes,
                "route_count": len(route_ids),
                "stop_count": hull_row["stop_count"],
            },
        }],
    }


def get_route_comparison(
    conn: Connection,
    route_ids: List[str],
    start_date: date,
    end_date: date,
) -> List[Dict[str, Any]]:
    """Side-by-side KPI comparison for up to 3 routes."""
    rows = conn.execute(
        text("""
        SELECT
            r.route_id,
            r.route_short_name,
            r.route_long_name,
            r.route_color,
            COUNT(e.id)                                                                AS event_count,
            ROUND(AVG(e.delay_seconds))::int                                           AS avg_delay_seconds,
            ROUND(STDDEV(e.delay_seconds))::int                                        AS delay_stddev,
            ROUND(
                SUM(CASE WHEN e.delay_seconds <= 60 THEN 1 ELSE 0 END)::numeric
                / NULLIF(COUNT(e.id), 0) * 100, 1
            )::double precision                                                        AS on_time_pct,
            (
                SELECT COUNT(DISTINCT st.stop_id)
                FROM gtfs_stop_times st
                JOIN gtfs_trips t2 ON t2.trip_id = st.trip_id
                WHERE t2.route_id = r.route_id
            ) AS stop_count,
            (
                SELECT COUNT(DISTINCT t2.trip_id)
                FROM gtfs_trips t2
                WHERE t2.route_id = r.route_id
            ) AS trip_count
        FROM gtfs_routes r
        LEFT JOIN ops_trip_events e
            ON e.route_id = r.route_id
           AND e.service_date BETWEEN :start_date AND :end_date
           AND e.delay_seconds IS NOT NULL
        WHERE r.route_id = ANY(:route_ids)
        GROUP BY r.route_id, r.route_short_name, r.route_long_name, r.route_color
        ORDER BY ARRAY_POSITION(:route_ids::text[], r.route_id)
        """),
        {"route_ids": route_ids, "start_date": start_date, "end_date": end_date},
    ).mappings().all()
    return [dict(r) for r in rows]


def get_bunching_summary(
    conn: Connection,
    start_date: date,
    end_date: date,
) -> List[Dict[str, Any]]:
    """
    Ranks routes by delay variance (stddev) as a proxy for bunching / service irregularity.
    Also returns avg delay, max delay, and % of late arrivals (> 5 min).
    """
    rows = conn.execute(
        text("""
        SELECT
            route_id,
            COUNT(*)                                                         AS event_count,
            ROUND(AVG(delay_seconds))::int                                   AS avg_delay_seconds,
            ROUND(STDDEV(delay_seconds))::int                                AS delay_stddev,
            ROUND(MAX(delay_seconds))::int                                   AS max_delay_seconds,
            SUM(CASE WHEN delay_seconds > 300 THEN 1 ELSE 0 END)::int        AS late_events,
            ROUND(
                SUM(CASE WHEN delay_seconds > 300 THEN 1 ELSE 0 END)::numeric
                / NULLIF(COUNT(*), 0) * 100, 1
            )::double precision                                              AS late_pct
        FROM ops_trip_events
        WHERE service_date BETWEEN :start_date AND :end_date
          AND delay_seconds IS NOT NULL
        GROUP BY route_id
        HAVING COUNT(*) > 5
        ORDER BY delay_stddev DESC NULLS LAST
        LIMIT 50
        """),
        {"start_date": start_date, "end_date": end_date},
    ).mappings().all()
    return [dict(r) for r in rows]

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection


def get_reliability_summary(
    conn: Connection,
    start_date: date,
    end_date: date,
    route_ids: Optional[List[str]] = None,
    agency_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Basic reliability KPIs per route over a date range.
    """
    params: Dict[str, Any] = {"start_date": start_date, "end_date": end_date}
    route_filter = ""
    if route_ids:
        route_filter = "AND route_id = ANY(:route_ids)"
        params["route_ids"] = route_ids
    agency_filter = ""
    if agency_id:
        agency_filter = "AND agency_id = :agency_id"
        params["agency_id"] = agency_id

    sql = text(
        f"""
        SELECT
          route_id,
          COUNT(*) AS sample_events,
          AVG(CASE WHEN delay_seconds IS NULL THEN 0 ELSE delay_seconds END) AS avg_delay_seconds,
          ROUND(
            SUM(CASE WHEN delay_seconds <= 60 THEN 1 ELSE 0 END)::numeric
            / NULLIF(COUNT(*), 0) * 100, 1
          )::double precision AS on_time_pct
        FROM ops_trip_events
        WHERE service_date BETWEEN :start_date AND :end_date
        {route_filter}
        {agency_filter}
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
    agency_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Stop-level safety scores and contributing metrics.
    """
    clauses = []
    params: Dict[str, Any] = {}
    if min_score is not None:
        clauses.append("ss.safety_score >= :min_score")
        params["min_score"] = min_score
    if max_score is not None:
        clauses.append("ss.safety_score <= :max_score")
        params["max_score"] = max_score
    if agency_id:
        clauses.append("s.agency_id = :agency_id")
        params["agency_id"] = agency_id

    where = ""
    if clauses:
        where = "WHERE " + " AND ".join(clauses)

    sql = text(
        f"""
        SELECT
          ss.stop_id,
          ss.safety_score,
          ss.crime_incidents_nearby,
          ss.collisions_nearby,
          ss.lighting_score,
          ss.pedestrian_infra_score,
          ss.last_computed_at
        FROM stop_safety_scores ss
        JOIN gtfs_stops s USING (stop_id)
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
    agency_id: Optional[str] = None,
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
    agency_filter = ""
    if agency_id:
        agency_filter = "AND s.agency_id = :agency_id"
        params["agency_id"] = agency_id

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
          {agency_filter}
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
    agency_id: Optional[str] = None,
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
    if agency_id:
        clauses.append("s.agency_id = :agency_id")
        params["agency_id"] = agency_id

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
            s.stop_lat, s.stop_lon, s.agency_id,
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

    # Routes serving this stop. agency_id added to every join clause so
    # we don't pull in another agency's route_id="31" when this stop's
    # agency also uses "31" (post-009 the data is correctly partitioned;
    # this protects the query from cross-agency JOIN bleed).
    route_rows = conn.execute(
        text("""
        SELECT DISTINCT r.route_id, r.route_short_name, r.route_long_name,
               COALESCE(r.route_color, '3b82f6') AS route_color
        FROM gtfs_stop_times st
        JOIN gtfs_trips  t ON t.agency_id = st.agency_id
                          AND t.trip_id   = st.trip_id
        JOIN gtfs_routes r ON r.agency_id = t.agency_id
                          AND r.route_id  = t.route_id
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
        JOIN gtfs_trips  t ON t.agency_id = st.agency_id
                          AND t.trip_id   = st.trip_id
        JOIN gtfs_routes r ON r.agency_id = t.agency_id
                          AND r.route_id  = t.route_id
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

    # Pick the most-used (agency_id, shape_id) for this route_id.
    # NOTE: this function takes route_id alone — when multiple agencies use
    # the same route_id (post-009 with composite PKs they coexist), the
    # subquery's GROUP BY now keys by (agency_id, shape_id) so the JOIN to
    # gtfs_shape_geoms is unambiguous. The most-trip-popular agency wins.
    # A follow-up sprint should add an explicit agency_id query param to
    # /routes/{route_id}/geo for disambiguation.
    shape_row = conn.execute(
        text("""
        SELECT sg.shape_id, sg.agency_id, ST_AsGeoJSON(sg.geom)::json AS geometry
        FROM gtfs_shape_geoms sg
        JOIN (
            SELECT agency_id, shape_id, COUNT(*) AS n
            FROM gtfs_trips
            WHERE route_id = :route_id AND shape_id IS NOT NULL
            GROUP BY agency_id, shape_id
            ORDER BY n DESC
            LIMIT 1
        ) mc ON mc.agency_id = sg.agency_id
            AND mc.shape_id  = sg.shape_id
        """),
        {"route_id": route_id},
    ).mappings().first()
    if shape_row:
        features.append({
            "type": "Feature",
            "geometry": shape_row["geometry"],
            "properties": {"feature_type": "shape", "route_id": route_id},
        })

    # Unique stops along the route. As above, JOINs use composite
    # (agency_id, trip_id) so cross-agency JOIN bleed can't happen; result
    # still aggregates across agencies that share the route_id.
    stop_rows = conn.execute(
        text("""
        SELECT s.stop_id, s.stop_name, s.stop_code, s.stop_lat, s.stop_lon,
               ST_AsGeoJSON(s.geom)::json AS geometry,
               MIN(st.stop_sequence) AS seq
        FROM gtfs_stop_times st
        JOIN gtfs_trips t ON t.agency_id = st.agency_id
                         AND t.trip_id   = st.trip_id
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


def get_live_vehicles(conn: Connection, agency_id: Optional[str] = None) -> Dict[str, Any]:
    """GeoJSON of the most recent position per vehicle, within the last 15 minutes."""
    agency_filter = ""
    params: Dict[str, Any] = {}
    if agency_id:
        agency_filter = "AND agency_id = :agency_id"
        params["agency_id"] = agency_id
    rows = conn.execute(
        text(f"""
        SELECT DISTINCT ON (vehicle_id)
            vehicle_id, trip_id, route_id, agency_id,
            latitude, longitude, bearing, speed, occupancy_status,
            timestamp,
            ST_AsGeoJSON(geom)::json AS geometry
        FROM rt_vehicle_positions_raw
        WHERE timestamp >= NOW() - INTERVAL '15 minutes'
          AND geom IS NOT NULL
          {agency_filter}
        ORDER BY vehicle_id, timestamp DESC
        """),
        params,
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
    agency_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Daily on-time % and avg delay (aggregated across all routes) over the last N days."""
    params: Dict[str, Any] = {"days": days}
    route_clause = ""
    if route_id:
        route_clause = "AND route_id = :route_id"
        params["route_id"] = route_id
    agency_clause = ""
    if agency_id:
        agency_clause = "AND agency_id = :agency_id"
        params["agency_id"] = agency_id
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
          {agency_clause}
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
        JOIN gtfs_trips  t ON t.agency_id = st.agency_id
                          AND t.trip_id   = st.trip_id
        JOIN gtfs_routes r ON r.agency_id = t.agency_id
                          AND r.route_id  = t.route_id
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
    # Step 1: routes serving the origin stop. Carry agency_id forward so
    # Step 2 can filter to only that agency's routes (not all agencies
    # sharing the same route_id label).
    route_rows = conn.execute(
        text("""
        SELECT DISTINCT t.agency_id, t.route_id
        FROM gtfs_stop_times st
        JOIN gtfs_trips t ON t.agency_id = st.agency_id
                         AND t.trip_id   = st.trip_id
        WHERE st.stop_id = :stop_id
        """),
        {"stop_id": stop_id},
    ).mappings().all()
    route_ids = [r["route_id"] for r in route_rows]
    agency_ids = list({r["agency_id"] for r in route_rows})
    if not route_ids:
        return {"type": "FeatureCollection", "features": []}

    # Step 2: all stops reachable on those routes (direct, no transfers).
    # Filtering by t.agency_id keeps us within the origin stop's agency
    # network so we don't pull in another agency's route="31" stops.
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
        JOIN gtfs_trips t ON t.agency_id = st.agency_id
                         AND t.trip_id   = st.trip_id
        JOIN gtfs_stops s ON s.stop_id = st.stop_id
        WHERE t.route_id  = ANY(:route_ids)
          AND t.agency_id = ANY(:agency_ids)
          AND s.geom IS NOT NULL
        """),
        {"route_ids": route_ids, "agency_ids": agency_ids},
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
                JOIN gtfs_trips t2 ON t2.agency_id = st.agency_id
                                  AND t2.trip_id   = st.trip_id
                WHERE t2.route_id  = r.route_id
                  AND t2.agency_id = r.agency_id
            ) AS stop_count,
            (
                SELECT COUNT(DISTINCT t2.trip_id)
                FROM gtfs_trips t2
                WHERE t2.route_id  = r.route_id
                  AND t2.agency_id = r.agency_id
            ) AS trip_count
        FROM gtfs_routes r
        LEFT JOIN ops_trip_events e
            ON e.route_id = r.route_id
           AND e.service_date BETWEEN :start_date AND :end_date
           AND e.delay_seconds IS NOT NULL
        WHERE r.route_id = ANY(:route_ids)
        GROUP BY r.route_id, r.agency_id, r.route_short_name,
                 r.route_long_name, r.route_color
        ORDER BY ARRAY_POSITION(CAST(:route_ids_ord AS text[]), r.route_id)
        """),
        {"route_ids": route_ids, "route_ids_ord": route_ids, "start_date": start_date, "end_date": end_date},
    ).mappings().all()
    return [dict(r) for r in rows]


def get_trip_plan(
    conn: Connection,
    from_lat: float,
    from_lng: float,
    to_lat: float,
    to_lng: float,
) -> Dict[str, Any]:
    """
    Find direct transit itineraries from near (from_lat, from_lng) to near (to_lat, to_lng).
    Searches for stops within 600 m of each point, finds trips serving both origin and
    destination stops (origin sequence before dest), and overlays delay predictions.
    Returns up to 10 itineraries, one per unique route.
    """
    rows = conn.execute(
        text("""
        WITH origin_ids AS (
            SELECT stop_id
            FROM gtfs_stops
            WHERE ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:from_lng, :from_lat), 4326)::geography, 600)
              AND geom IS NOT NULL
            LIMIT 5
        ),
        dest_ids AS (
            SELECT stop_id
            FROM gtfs_stops
            WHERE ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:to_lng, :to_lat), 4326)::geography, 600)
              AND geom IS NOT NULL
            LIMIT 5
        ),
        matched_trips AS (
            SELECT DISTINCT ON (t.route_id)
                st_o.trip_id,
                t.route_id,
                r.route_short_name,
                r.route_color,
                t.trip_headsign,
                st_o.stop_id          AS origin_stop_id,
                s_o.stop_name         AS origin_stop_name,
                ROUND(ST_Distance(s_o.geom::geography, ST_SetSRID(ST_MakePoint(:from_lng, :from_lat), 4326)::geography))::int AS origin_walk_m,
                st_d.stop_id          AS dest_stop_id,
                s_d.stop_name         AS dest_stop_name,
                ROUND(ST_Distance(s_d.geom::geography, ST_SetSRID(ST_MakePoint(:to_lng, :to_lat), 4326)::geography))::int AS dest_walk_m,
                st_o.departure_time   AS depart_time,
                st_d.arrival_time     AS arrive_time
            FROM origin_ids oi
            JOIN gtfs_stop_times st_o ON st_o.stop_id = oi.stop_id
            CROSS JOIN dest_ids di
            -- Destination stop_times must be in the same agency as the
            -- origin's trip, so trip_id matches the right agency_id.
            JOIN gtfs_stop_times st_d
                ON  st_d.agency_id     = st_o.agency_id
                AND st_d.trip_id       = st_o.trip_id
                AND st_d.stop_id       = di.stop_id
                AND st_d.stop_sequence > st_o.stop_sequence
            JOIN gtfs_trips  t   ON t.agency_id = st_o.agency_id
                                AND t.trip_id   = st_o.trip_id
            JOIN gtfs_routes r   ON r.agency_id = t.agency_id
                                AND r.route_id  = t.route_id
            JOIN gtfs_stops  s_o ON s_o.stop_id = st_o.stop_id
            JOIN gtfs_stops  s_d ON s_d.stop_id = st_d.stop_id
            ORDER BY t.route_id, st_o.departure_time
        )
        SELECT
            mt.*,
            dp.predicted_delay_seconds
        FROM matched_trips mt
        LEFT JOIN LATERAL (
            SELECT AVG(predicted_delay_seconds) AS predicted_delay_seconds
            FROM delay_predictions
            WHERE route_id = mt.route_id
              AND service_date = CURRENT_DATE
        ) dp ON TRUE
        ORDER BY mt.depart_time
        LIMIT 10
        """),
        {
            "from_lat": from_lat,
            "from_lng": from_lng,
            "to_lat": to_lat,
            "to_lng": to_lng,
        },
    ).mappings().all()

    itineraries = []
    for r in rows:
        d = dict(r)
        if d.get("predicted_delay_seconds") is not None:
            d["predicted_delay_seconds"] = float(d["predicted_delay_seconds"])
        itineraries.append(d)

    return {
        "from": {"lat": from_lat, "lng": from_lng},
        "to": {"lat": to_lat, "lng": to_lng},
        "itineraries": itineraries,
    }


def get_bunching_summary(
    conn: Connection,
    start_date: date,
    end_date: date,
    agency_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Ranks routes by delay variance (stddev) as a proxy for bunching / service irregularity.
    Also returns avg delay, max delay, and % of late arrivals (> 5 min).
    """
    params: Dict[str, Any] = {"start_date": start_date, "end_date": end_date}
    agency_filter = ""
    if agency_id:
        agency_filter = "AND agency_id = :agency_id"
        params["agency_id"] = agency_id
    rows = conn.execute(
        text(f"""
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
          {agency_filter}
        GROUP BY route_id
        HAVING COUNT(*) > 5
        ORDER BY delay_stddev DESC NULLS LAST
        LIMIT 50
        """),
        params,
    ).mappings().all()
    return [dict(r) for r in rows]


# ── Agency catalog ─────────────────────────────────────────────────────────────

def get_agencies_list(conn: Connection) -> List[Dict[str, Any]]:
    """All rows from the agencies catalog populated by
    five11_operators.run_operators_sync(). Powers GET /agencies.

    Each row carries a `has_data` flag that the UI uses to hide 511.org's
    internal admin entries (5E, 5F, 5O, 5S) and operators with no rows in
    gtfs_routes. The flag is computed, not stored — adding agencies to
    the GTFS feed should make them filter-eligible without a re-sync.
    """
    rows = conn.execute(text("""
        SELECT
            a.agency_id,
            a.agency_name,
            a.agency_type,
            a.monitored,
            a.agency_url,
            a.agency_phone,
            (
                EXISTS (SELECT 1 FROM gtfs_routes r WHERE r.agency_id = a.agency_id)
                AND a.agency_id !~ '^5[A-Z]$'
            ) AS has_data
        FROM agencies a
        ORDER BY a.agency_name
    """)).mappings().all()
    return [dict(r) for r in rows]


def get_agencies_rollup(
    conn: Connection,
    start_date: date,
    end_date: date,
) -> List[Dict[str, Any]]:
    """One row per agency: routes_count, stops_count, otp_pct,
    avg_delay_seconds, hot_stops, sample_events. Powers Overview's
    "By agency" card.

    alerts_active is a placeholder (0) — service alerts come from the
    live 511.org feed and aren't queryable historically; the per-agency
    detail view fetches them at request time.
    """
    rows = conn.execute(text("""
        WITH route_counts AS (
            SELECT agency_id, COUNT(*) AS routes_count
            FROM gtfs_routes
            GROUP BY agency_id
        ),
        stop_counts AS (
            SELECT agency_id, COUNT(*) AS stops_count
            FROM gtfs_stops
            GROUP BY agency_id
        ),
        otp_stats AS (
            SELECT
                agency_id,
                COUNT(*) AS sample_events,
                AVG(delay_seconds)::double precision AS avg_delay_seconds,
                100.0 * SUM(CASE WHEN on_time THEN 1 ELSE 0 END)::double precision
                  / NULLIF(COUNT(*), 0) AS otp_pct
            FROM stop_observations
            WHERE service_date BETWEEN :start_date AND :end_date
              AND observed_arrival IS NOT NULL
            GROUP BY agency_id
        ),
        hot_stops AS (
            SELECT s.agency_id, COUNT(*) AS hot_stops
            FROM stop_safety_scores ss
            JOIN gtfs_stops s ON s.stop_id = ss.stop_id
            WHERE ss.safety_score >= 8
            GROUP BY s.agency_id
        )
        SELECT
            a.agency_id,
            a.agency_name,
            a.monitored,
            COALESCE(rc.routes_count, 0)  AS routes_count,
            COALESCE(sc.stops_count, 0)   AS stops_count,
            os.otp_pct,
            os.avg_delay_seconds,
            COALESCE(os.sample_events, 0) AS sample_events,
            COALESCE(hs.hot_stops, 0)     AS hot_stops,
            0                              AS alerts_active
        FROM agencies a
        LEFT JOIN route_counts rc USING (agency_id)
        LEFT JOIN stop_counts  sc USING (agency_id)
        LEFT JOIN otp_stats    os USING (agency_id)
        LEFT JOIN hot_stops    hs USING (agency_id)
        ORDER BY routes_count DESC, a.agency_name
    """), {"start_date": start_date, "end_date": end_date}).mappings().all()
    return [dict(r) for r in rows]


# ── Cross-agency OTP benchmarking ──────────────────────────────────────────────

def get_agency_otp_benchmarks(
    conn: Connection,
    start_date: date,
    end_date: date,
) -> List[Dict[str, Any]]:
    """
    Cross-agency on-time performance benchmarks from stop_observations.

    Computes OTP %, avg/median/p90 delay, and trend (vs. the prior period of
    equal length) for every agency that has data in the requested window.
    Sorted by on_time_pct descending.
    """
    period_days = (end_date - start_date).days + 1
    prior_end = start_date - timedelta(days=1)
    prior_start = prior_end - timedelta(days=period_days - 1)

    rows = conn.execute(
        text("""
        WITH period_stats AS (
            SELECT
                agency_id,
                COUNT(*)                                                  AS total_observations,
                SUM(CASE WHEN on_time THEN 1 ELSE 0 END)::bigint          AS on_time_count,
                ROUND(
                    100.0 * SUM(CASE WHEN on_time THEN 1 ELSE 0 END)
                    / NULLIF(COUNT(*), 0), 2
                )::double precision                                       AS on_time_pct,
                ROUND(AVG(delay_seconds::float))::double precision        AS avg_delay_seconds,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY delay_seconds)
                    ::double precision                                    AS median_delay_seconds,
                PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY delay_seconds)
                    ::double precision                                    AS p90_delay_seconds
            FROM stop_observations
            WHERE service_date BETWEEN :start_date AND :end_date
              AND on_time IS NOT NULL
            GROUP BY agency_id
        ),
        prior_stats AS (
            SELECT
                agency_id,
                ROUND(
                    100.0 * SUM(CASE WHEN on_time THEN 1 ELSE 0 END)
                    / NULLIF(COUNT(*), 0), 2
                )::double precision AS on_time_pct
            FROM stop_observations
            WHERE service_date BETWEEN :prior_start AND :prior_end
              AND on_time IS NOT NULL
            GROUP BY agency_id
        )
        SELECT
            ps.agency_id,
            COALESCE(a.agency_name, ps.agency_id) AS agency_name,
            ps.total_observations,
            ps.on_time_count,
            ps.on_time_pct,
            ps.avg_delay_seconds,
            ps.median_delay_seconds,
            ps.p90_delay_seconds,
            ROUND(
                (ps.on_time_pct - COALESCE(pr.on_time_pct, ps.on_time_pct))::numeric, 2
            )::double precision AS trend
        FROM period_stats ps
        LEFT JOIN prior_stats pr USING (agency_id)
        LEFT JOIN agencies   a  USING (agency_id)
        ORDER BY ps.on_time_pct DESC NULLS LAST
        """),
        {
            "start_date": start_date,
            "end_date": end_date,
            "prior_start": prior_start,
            "prior_end": prior_end,
        },
    ).mappings().all()

    return [dict(r) for r in rows]


def get_schedule_drift(conn: Connection, agency_id: str, route_id: str, months_back: int = 3) -> list[dict]:
    cutoff_date = date.today() - timedelta(days=months_back * 30)

    rows = conn.execute(text("""
        WITH ordered AS (
            SELECT
                so.trip_id,
                so.service_date,
                so.stop_id,
                so.scheduled_arrival,
                so.observed_arrival,
                gst.stop_sequence,
                gt.direction_id,
                LEAD(so.stop_id)            OVER w AS next_stop_id,
                LEAD(gst.stop_sequence)     OVER w AS next_stop_seq,
                LEAD(so.scheduled_arrival)  OVER w AS next_scheduled,
                LEAD(so.observed_arrival)   OVER w AS next_observed
            FROM stop_observations so
            JOIN gtfs_stop_times gst
                ON gst.agency_id = so.agency_id
               AND gst.trip_id   = so.trip_id
               AND gst.stop_id   = so.stop_id
            JOIN gtfs_trips gt ON gt.agency_id = so.agency_id
                              AND gt.trip_id   = so.trip_id
            WHERE so.agency_id     = :agency_id
              AND so.route_id      = :route_id
              AND so.service_date >= :cutoff_date
              AND so.scheduled_arrival IS NOT NULL
              AND so.observed_arrival  IS NOT NULL
            WINDOW w AS (PARTITION BY so.trip_id, so.service_date ORDER BY gst.stop_sequence)
        ),
        pairs AS (
            SELECT
                stop_id      AS from_stop_id,
                next_stop_id AS to_stop_id,
                direction_id,
                EXTRACT(EPOCH FROM (next_scheduled - scheduled_arrival)) AS sched_secs,
                EXTRACT(EPOCH FROM (next_observed  - observed_arrival))  AS actual_secs
            FROM ordered
            WHERE next_stop_id IS NOT NULL
              AND next_stop_seq = stop_sequence + 1
              AND EXTRACT(EPOCH FROM (next_scheduled - scheduled_arrival)) > 0
              AND EXTRACT(EPOCH FROM (next_observed  - observed_arrival))  BETWEEN 0 AND 3600
        ),
        aggregated AS (
            SELECT
                from_stop_id,
                to_stop_id,
                direction_id,
                COUNT(*)                                                          AS obs_count,
                AVG(sched_secs)                                                   AS avg_sched_secs,
                AVG(actual_secs)                                                  AS avg_actual_secs,
                PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY actual_secs)          AS p90_actual_secs
            FROM pairs
            GROUP BY from_stop_id, to_stop_id, direction_id
            HAVING COUNT(*) >= 5
        )
        SELECT
            a.from_stop_id,
            COALESCE(fs.stop_name, a.from_stop_id) AS from_stop_name,
            a.to_stop_id,
            COALESCE(ts.stop_name, a.to_stop_id)   AS to_stop_name,
            a.direction_id,
            a.obs_count,
            ROUND(a.avg_sched_secs::numeric,  1)::double precision AS avg_sched_secs,
            ROUND(a.avg_actual_secs::numeric, 1)::double precision AS avg_actual_secs,
            ROUND(a.p90_actual_secs::numeric, 1)::double precision AS p90_actual_secs,
            ROUND(
                ((a.avg_actual_secs - a.avg_sched_secs)
                 / NULLIF(a.avg_sched_secs, 0) * 100)::numeric, 1
            )::double precision AS drift_pct,
            CASE
                WHEN ABS((a.avg_actual_secs - a.avg_sched_secs)
                         / NULLIF(a.avg_sched_secs, 0) * 100) > 15 THEN 'HIGH'
                WHEN ABS((a.avg_actual_secs - a.avg_sched_secs)
                         / NULLIF(a.avg_sched_secs, 0) * 100) > 5  THEN 'MODERATE'
                ELSE 'OK'
            END AS drift_flag
        FROM aggregated a
        LEFT JOIN gtfs_stops fs ON fs.stop_id = a.from_stop_id
        LEFT JOIN gtfs_stops ts ON ts.stop_id = a.to_stop_id
        ORDER BY ABS(a.avg_actual_secs - a.avg_sched_secs) DESC
    """), {
        "agency_id": agency_id,
        "route_id":  route_id,
        "cutoff_date": cutoff_date,
    }).mappings().all()

    return [dict(r) for r in rows]


def get_service_delivery_gap(
    conn: Connection,
    agency_id: str,
    start_date: date,
    end_date: date,
) -> List[Dict[str, Any]]:
    """
    Per-route service delivery rate from stop_observations.

    service_delivery_rate = 100 × rows_with_observed_arrival / total_rows  (0–100 %).
    A rate below 100 indicates trips that were scheduled but not observed by the archive.
    Returns an empty list when no observations exist for the requested window.
    """
    rows = conn.execute(
        text("""
        SELECT
            route_id,
            COUNT(*)                                                                      AS total_observations,
            SUM(CASE WHEN observed_arrival IS NOT NULL THEN 1 ELSE 0 END)::bigint        AS delivered_count,
            ROUND(
                100.0 * SUM(CASE WHEN observed_arrival IS NOT NULL THEN 1 ELSE 0 END)
                / NULLIF(COUNT(*), 0), 2
            )::double precision                                                           AS service_delivery_rate
        FROM stop_observations
        WHERE agency_id    = :agency_id
          AND service_date BETWEEN :start_date AND :end_date
        GROUP BY route_id
        ORDER BY route_id
        """),
        {"agency_id": agency_id, "start_date": start_date, "end_date": end_date},
    ).mappings().all()
    return [dict(r) for r in rows]


def get_traffic_transit_impact(conn: Connection) -> list[dict]:
    """
    For every active traffic event / work zone, find bus routes whose stops
    fall within 800 m, then enrich with historical delay context.
    Returns one row per (event, route) pair with an alert_level classification.
    """
    cutoff_12w = date.today() - timedelta(days=84)

    rows = conn.execute(text("""
        WITH active_events AS (
            SELECT event_id,
                   'event'   AS source_type,
                   event_type,
                   severity,
                   COALESCE(road_name, description, event_type) AS road_name,
                   geom::geometry AS geom
            FROM traffic_events
            WHERE geom IS NOT NULL
              AND (end_time IS NULL OR end_time > now())
            UNION ALL
            SELECT zone_id AS event_id,
                   'workzone' AS source_type,
                   'WORKZONE'  AS event_type,
                   CASE
                       WHEN description ILIKE '%major%' OR description ILIKE '%closure%'
                       THEN 'Major'
                       ELSE 'Moderate'
                   END         AS severity,
                   COALESCE(road_name, description) AS road_name,
                   ST_Centroid(geom::geometry)       AS geom
            FROM work_zones
            WHERE geom IS NOT NULL
              AND (end_time IS NULL OR end_time > now())
        ),
        affected_stops AS (
            SELECT e.event_id,
                   e.source_type,
                   e.event_type,
                   e.severity,
                   e.road_name,
                   s.stop_id,
                   ST_Distance(s.geom::geography, e.geom::geography) AS proximity_meters
            FROM active_events e
            JOIN gtfs_stops s
              ON ST_DWithin(s.geom::geography, e.geom::geography, 800)
        ),
        route_stops AS (
            SELECT DISTINCT
                   ast.event_id,
                   ast.source_type,
                   ast.event_type,
                   ast.severity,
                   ast.road_name,
                   ast.stop_id,
                   ast.proximity_meters,
                   gr.route_id,
                   gr.agency_id,
                   gr.route_short_name,
                   gr.route_color
            FROM affected_stops ast
            JOIN gtfs_stop_times gst ON gst.stop_id = ast.stop_id
            JOIN gtfs_trips      gt  ON gt.agency_id = gst.agency_id
                                    AND gt.trip_id   = gst.trip_id
            JOIN gtfs_routes     gr  ON gr.agency_id = gt.agency_id
                                    AND gr.route_id  = gt.route_id
        ),
        historical AS (
            SELECT route_id,
                   stop_id,
                   AVG(NULLIF(delay_seconds, 0)) AS avg_delay_seconds
            FROM stop_observations
            WHERE service_date >= :cutoff_12w
              AND delay_seconds IS NOT NULL
              AND EXTRACT(DOW  FROM service_date) =
                  EXTRACT(DOW  FROM CURRENT_DATE)
              AND EXTRACT(HOUR FROM scheduled_arrival AT TIME ZONE 'America/Los_Angeles') =
                  EXTRACT(HOUR FROM NOW()             AT TIME ZONE 'America/Los_Angeles')
            GROUP BY route_id, stop_id
        )
        SELECT
            rs.event_id,
            rs.source_type,
            rs.event_type,
            rs.severity,
            rs.road_name,
            rs.route_id,
            rs.agency_id,
            rs.route_short_name,
            COALESCE(rs.route_color, '3b82f6')                        AS route_color,
            ARRAY_AGG(DISTINCT rs.stop_id)                            AS affected_stop_ids,
            MIN(rs.proximity_meters)::double precision                AS proximity_meters,
            COALESCE(AVG(h.avg_delay_seconds), 0)::double precision   AS historical_avg_delay_seconds,
            CASE
                WHEN rs.severity ILIKE 'major' OR MIN(rs.proximity_meters) < 200
                THEN 'CRITICAL'
                WHEN rs.severity ILIKE 'moderate' OR MIN(rs.proximity_meters) < 500
                THEN 'WARNING'
                ELSE 'WATCH'
            END AS alert_level
        FROM route_stops rs
        LEFT JOIN historical h
          ON h.route_id = rs.route_id AND h.stop_id = rs.stop_id
        GROUP BY
            rs.event_id, rs.source_type, rs.event_type, rs.severity, rs.road_name,
            rs.route_id, rs.agency_id, rs.route_short_name, rs.route_color
        ORDER BY
            CASE WHEN rs.severity ILIKE 'major' OR MIN(rs.proximity_meters) < 200
                 THEN 0
                 WHEN rs.severity ILIKE 'moderate' OR MIN(rs.proximity_meters) < 500
                 THEN 1 ELSE 2 END,
            MIN(rs.proximity_meters)
    """), {"cutoff_12w": cutoff_12w}).mappings().all()

    result = []
    for r in rows:
        d = dict(r)
        # Convert PostgreSQL array to a plain Python list
        if d.get("affected_stop_ids") and not isinstance(d["affected_stop_ids"], list):
            d["affected_stop_ids"] = list(d["affected_stop_ids"])
        result.append(d)
    return result


# ── Planning → Scenarios builder ──────────────────────────────────────────────
#
# Scenarios are hypothetical service additions (a list of new stops at lat/lng
# with a service frequency). The impact computation uses a *radius-coverage
# model*: a coverage cell counts as "newly covered" if its centroid falls
# within SCENARIO_COVERAGE_RADIUS_M of any scenario stop AND it wasn't already
# covered by an existing stop. Equivalent to the Coverage page's composite
# logic, but applied to a hypothetical stop set.
#
# Why radius-coverage instead of true GTFS isochrones?
#   - PostGIS does it correctly in one CTE: ST_DWithin(geom::geography, …, m).
#   - True isochrones need a routing graph (OSRM/Valhalla) we don't have.
#   - The radius model is the same one the existing Coverage page uses for the
#     baseline, so deltas are computed against an internally consistent metric.

SCENARIO_COVERAGE_RADIUS_M = 400


def list_scenarios(conn: Connection) -> List[Dict[str, Any]]:
    """All scenarios, newest first. Powers GET /scenarios."""
    rows = conn.execute(text("""
        SELECT id, name, description, stops, frequency_min, agency_id,
               created_at, updated_at
        FROM scenarios
        ORDER BY created_at DESC
    """)).mappings().all()
    return [dict(r) for r in rows]


def get_scenario(conn: Connection, scenario_id: int) -> Optional[Dict[str, Any]]:
    """Single scenario by id, or None if missing."""
    row = conn.execute(text("""
        SELECT id, name, description, stops, frequency_min, agency_id,
               created_at, updated_at
        FROM scenarios
        WHERE id = :id
    """), {"id": scenario_id}).mappings().first()
    return dict(row) if row else None


def create_scenario(
    conn: Connection,
    name: str,
    stops: List[Dict[str, Any]],
    frequency_min: int = 15,
    description: Optional[str] = None,
    agency_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert a scenario; returns the persisted row."""
    import json
    row = conn.execute(text("""
        INSERT INTO scenarios (name, description, stops, frequency_min, agency_id)
        VALUES (:name, :description, CAST(:stops AS jsonb), :frequency_min, :agency_id)
        RETURNING id, name, description, stops, frequency_min, agency_id,
                  created_at, updated_at
    """), {
        "name": name,
        "description": description,
        "stops": json.dumps(stops),
        "frequency_min": frequency_min,
        "agency_id": agency_id,
    }).mappings().first()
    return dict(row) if row else {}


def delete_scenario(conn: Connection, scenario_id: int) -> bool:
    """Delete a scenario; returns True if a row was removed."""
    result = conn.execute(text("""
        DELETE FROM scenarios WHERE id = :id
    """), {"id": scenario_id})
    return result.rowcount > 0


def compute_scenario_impact(
    conn: Connection,
    scenario_id: int,
) -> Optional[Dict[str, Any]]:
    """Coverage / equity delta vs baseline for a scenario.

    Baseline-covered = coverage_cells with distance_to_nearest_stop_m ≤ 400.
    Scenario-covered = coverage_cells whose geom is within 400 m of any
    scenario stop. Newly covered = scenario_covered − baseline_covered.

    Returns aggregates per equity tier (population reached, cell counts) plus
    the scenario's own stop_count and frequency_min so the frontend can render
    the delta panel without a second round-trip.
    """
    scenario = get_scenario(conn, scenario_id)
    if scenario is None:
        return None

    stops = scenario.get("stops") or []
    if not isinstance(stops, list) or len(stops) == 0:
        # No stops → no impact, but still return a well-formed shape so the
        # frontend doesn't have to special-case the "I just created it" state.
        return {
            "scenario_id":              scenario_id,
            "stop_count":               0,
            "frequency_min":            scenario.get("frequency_min"),
            "newly_covered_cells":      0,
            "newly_covered_population": 0,
            "newly_covered_high_need":  0,
            "by_tier":                  {"very_high": 0, "high": 0, "medium": 0, "low": 0},
            "baseline_covered_cells":   0,
            "scenario_covered_cells":   0,
        }

    import json
    row = conn.execute(text("""
        WITH scenario_points AS (
            SELECT
                (s.value ->> 'lat')::float AS lat,
                (s.value ->> 'lng')::float AS lng
            FROM jsonb_array_elements(CAST(:stops AS jsonb)) AS s(value)
        ),
        scenario_geoms AS (
            SELECT ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography AS g
            FROM scenario_points
            WHERE lat IS NOT NULL AND lng IS NOT NULL
        ),
        scenario_covered AS (
            SELECT DISTINCT cc.cell_id
            FROM coverage_cells cc
            JOIN scenario_geoms sg
              ON ST_DWithin(cc.geom::geography, sg.g, :radius)
        ),
        baseline_covered AS (
            SELECT cell_id
            FROM coverage_cells
            WHERE distance_to_nearest_stop_m IS NOT NULL
              AND distance_to_nearest_stop_m <= :radius
        ),
        newly_covered AS (
            SELECT cell_id FROM scenario_covered
            EXCEPT
            SELECT cell_id FROM baseline_covered
        ),
        newly_covered_cells AS (
            SELECT
                cc.cell_id,
                COALESCE(cc.population, 0)        AS population,
                COALESCE(cc.equity_score, 0)      AS equity_score,
                CASE
                    WHEN COALESCE(cc.equity_score, 0) >= 0.25 THEN 'very_high'
                    WHEN COALESCE(cc.equity_score, 0) >= 0.15 THEN 'high'
                    WHEN COALESCE(cc.equity_score, 0) >= 0.08 THEN 'medium'
                    ELSE 'low'
                END AS equity_tier
            FROM coverage_cells cc
            JOIN newly_covered nc USING (cell_id)
        )
        SELECT
            (SELECT COUNT(*) FROM baseline_covered) AS baseline_covered_cells,
            (SELECT COUNT(*) FROM scenario_covered) AS scenario_covered_cells,
            COUNT(*)                                  AS newly_covered_cells,
            COALESCE(SUM(population), 0)              AS newly_covered_population,
            COALESCE(SUM(CASE WHEN equity_tier IN ('very_high', 'high') THEN population ELSE 0 END), 0) AS newly_covered_high_need,
            COALESCE(SUM(CASE WHEN equity_tier = 'very_high' THEN population ELSE 0 END), 0) AS pop_very_high,
            COALESCE(SUM(CASE WHEN equity_tier = 'high'      THEN population ELSE 0 END), 0) AS pop_high,
            COALESCE(SUM(CASE WHEN equity_tier = 'medium'    THEN population ELSE 0 END), 0) AS pop_medium,
            COALESCE(SUM(CASE WHEN equity_tier = 'low'       THEN population ELSE 0 END), 0) AS pop_low
        FROM newly_covered_cells
    """), {"stops": json.dumps(stops), "radius": SCENARIO_COVERAGE_RADIUS_M}).mappings().first()

    return {
        "scenario_id":              scenario_id,
        "stop_count":               len(stops),
        "frequency_min":            scenario.get("frequency_min"),
        "newly_covered_cells":      int(row["newly_covered_cells"] or 0),
        "newly_covered_population": int(row["newly_covered_population"] or 0),
        "newly_covered_high_need":  int(row["newly_covered_high_need"] or 0),
        "by_tier": {
            "very_high": int(row["pop_very_high"] or 0),
            "high":      int(row["pop_high"]      or 0),
            "medium":    int(row["pop_medium"]    or 0),
            "low":       int(row["pop_low"]       or 0),
        },
        "baseline_covered_cells": int(row["baseline_covered_cells"] or 0),
        "scenario_covered_cells": int(row["scenario_covered_cells"] or 0),
    }

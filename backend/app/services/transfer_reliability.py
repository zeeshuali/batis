"""Compute the cross-agency transfer reliability matrix (spatial matching).

Two stops of different agencies form a transfer point when they are within the
largest configured radius (settings.transfer_radii_m, default max 400 m).
`stop_transfer_links` stores those pairs with their distance. For every arrival
at the "from" stop we look at the next arrival at the linked "to" stop within
GIVE_UP_SECONDS. The transfer succeeds when that gap is at least the walk time
(max(60 s, distance / walking speed)).

The radius the user picks (50..400 m) is applied at READ time on `distance_m`, so
changing it never needs a recompute.

Sources: `stop_observations` (observed_arrival, from the 511 archive) and
`ops_trip_events` (live RT). RT rows are skipped for any (agency, service_date)
already present in stop_observations so no arrival is counted twice.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.config import get_settings


# Floor for the walk time (seconds): even co-located stops need time to change vehicles.
WALK_TIME_SAME_STOP_SECONDS = 60

# Beyond this gap the passenger has given up: operationally a different trip.
GIVE_UP_SECONDS = 1800

# How many days back the compute job looks, counted from the newest data available.
DEFAULT_LOOKBACK_DAYS = 7


def refresh_stop_transfer_links(conn: Connection, max_radius_m: int | None = None) -> int:
    """Rebuild stop_transfer_links: every cross-agency stop pair within max_radius_m.

    Uses the GiST index on (geom::geography). Returns the number of directed pairs.
    """
    if max_radius_m is None:
        max_radius_m = max(get_settings().transfer_radii_m)
    conn.execute(text("TRUNCATE stop_transfer_links"))
    n = conn.execute(text("""
        INSERT INTO stop_transfer_links (from_stop_pk, to_stop_pk, distance_m)
        SELECT a.stop_pk, b.stop_pk,
               ROUND(ST_Distance(a.geom::geography, b.geom::geography))::int
        FROM gtfs_stops a
        JOIN gtfs_stops b
          ON b.agency_id <> a.agency_id
         AND ST_DWithin(a.geom::geography, b.geom::geography, :r)
        WHERE a.geom IS NOT NULL AND b.geom IS NOT NULL
    """), {"r": max_radius_m}).rowcount
    return int(n or 0)


def compute_transfer_reliability(
    conn: Connection,
    *,
    days: int = DEFAULT_LOOKBACK_DAYS,
    end_date: date | None = None,
    give_up_seconds: int = GIVE_UP_SECONDS,
    refresh_links: bool = True,
) -> int:
    """Recompute the entire `transfer_reliability` table. Returns rows written.

    The window is [end_date - days, end_date]; end_date defaults to the newest
    service_date found in stop_observations / ops_trip_events.
    """
    s = get_settings()
    if refresh_links:
        refresh_stop_transfer_links(conn)

    if end_date is None:
        end_date = conn.execute(text("""
            SELECT GREATEST(
                (SELECT MAX(service_date) FROM stop_observations),
                (SELECT MAX(service_date) FROM ops_trip_events))
        """)).scalar() or date.today()
    start_date = end_date - timedelta(days=days)

    conn.execute(text("DROP TABLE IF EXISTS _tr_events"))
    conn.execute(text("""
        CREATE TEMP TABLE _tr_events ON COMMIT DROP AS
        WITH linked AS (SELECT DISTINCT from_stop_pk AS stop_pk FROM stop_transfer_links)
        SELECT o.stop_pk, o.agency_id, o.scheduled_arrival, o.observed_arrival AS actual_arrival
        FROM stop_observations o
        JOIN linked l ON l.stop_pk = o.stop_pk
        WHERE o.service_date BETWEEN :sd AND :ed AND o.observed_arrival IS NOT NULL
        UNION ALL
        SELECT e.stop_pk, e.agency_id, e.scheduled_arrival, e.actual_arrival
        FROM ops_trip_events e
        JOIN linked l ON l.stop_pk = e.stop_pk
        WHERE e.service_date BETWEEN :sd AND :ed AND e.actual_arrival IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM stop_observations o
              WHERE o.agency_id = e.agency_id AND o.service_date = e.service_date
              LIMIT 1)
    """), {"sd": start_date, "ed": end_date})
    conn.execute(text("CREATE INDEX ON _tr_events (stop_pk, actual_arrival)"))
    conn.execute(text("ANALYZE _tr_events"))

    conn.execute(text("DELETE FROM transfer_reliability"))
    rows = conn.execute(text("""
        WITH pairs AS (
            SELECT l.from_stop_pk, l.to_stop_pk, l.distance_m,
                   GREATEST(:floor_s, CEIL(l.distance_m / :speed))::int AS walk_s
            FROM stop_transfer_links l
        ),
        event_pairs AS (
            SELECT p.from_stop_pk, p.to_stop_pk, p.distance_m, p.walk_s,
                   a.actual_arrival AS from_actual, a.scheduled_arrival AS from_sched,
                   b.actual_arrival AS to_actual,   b.scheduled_arrival AS to_sched
            FROM pairs p
            JOIN _tr_events a ON a.stop_pk = p.from_stop_pk
            CROSS JOIN LATERAL (
                SELECT actual_arrival, scheduled_arrival
                FROM _tr_events
                WHERE stop_pk = p.to_stop_pk
                  AND actual_arrival >  a.actual_arrival
                  AND actual_arrival <= a.actual_arrival + make_interval(secs => :give_up)
                ORDER BY actual_arrival ASC
                LIMIT 1
            ) b
        ),
        aggregated AS (
            SELECT from_stop_pk, to_stop_pk, distance_m,
                COUNT(*)::int AS n_observations,
                ROUND(100.0 * SUM(CASE WHEN EXTRACT(EPOCH FROM (to_actual - from_actual)) >= walk_s
                                       THEN 1 ELSE 0 END)::numeric / COUNT(*), 2) AS success_rate_pct,
                EXTRACT(EPOCH FROM percentile_cont(0.5) WITHIN GROUP (
                    ORDER BY (to_actual - from_actual)))::int AS median_gap_seconds,
                ROUND((EXTRACT(EPOCH FROM percentile_cont(0.5) WITHIN GROUP (
                    ORDER BY (to_sched - from_sched))
                    FILTER (WHERE from_sched IS NOT NULL AND to_sched IS NOT NULL)) / 60.0)::numeric, 2)
                    AS scheduled_transfer_minutes
            FROM event_pairs
            GROUP BY from_stop_pk, to_stop_pk, distance_m
        )
        INSERT INTO transfer_reliability (
            from_agency, to_agency, transfer_stop_id, from_stop_pk, to_stop_pk, to_stop_id,
            distance_m, scheduled_transfer_minutes, success_rate_pct, median_gap_seconds,
            n_observations)
        SELECT fs.agency_id, ts.agency_id, fs.stop_id, g.from_stop_pk, g.to_stop_pk, ts.stop_id,
               g.distance_m, g.scheduled_transfer_minutes, g.success_rate_pct,
               g.median_gap_seconds, g.n_observations
        FROM aggregated g
        JOIN gtfs_stops fs ON fs.stop_pk = g.from_stop_pk
        JOIN gtfs_stops ts ON ts.stop_pk = g.to_stop_pk
        RETURNING id
    """), {
        "sd": start_date, "ed": end_date,
        "floor_s": WALK_TIME_SAME_STOP_SECONDS,
        "speed": s.transfer_walk_speed_mps,
        "give_up": give_up_seconds,
    }).fetchall()
    return len(rows)


def get_transfer_radii() -> Dict[str, Any]:
    s = get_settings()
    return {"radii_m": sorted(s.transfer_radii_m), "default_m": s.transfer_default_radius_m}


def get_transfer_reliability(
    conn: Connection,
    *,
    from_agency: str | None = None,
    to_agency:   str | None = None,
    min_observations: int = 0,
    radius_m: int | None = None,
    limit: int = 500,
) -> list[Dict[str, Any]]:
    """Read the transfer_reliability table for the API.

    Only pairs with distance_m <= radius_m are returned (default radius from
    settings). transfer_stop_* describe the "from" stop and to_stop_* the "to" stop.
    """
    if radius_m is None:
        radius_m = get_settings().transfer_default_radius_m
    clauses = ["tr.n_observations >= :min_observations", "tr.distance_m <= :radius_m"]
    params: Dict[str, Any] = {"min_observations": min_observations, "limit": limit,
                              "radius_m": radius_m}
    if from_agency:
        clauses.append("tr.from_agency = :from_agency")
        params["from_agency"] = from_agency
    if to_agency:
        clauses.append("tr.to_agency = :to_agency")
        params["to_agency"] = to_agency

    where = " AND ".join(clauses)
    rows = conn.execute(text(f"""
        SELECT
            tr.from_agency,
            tr.to_agency,
            tr.transfer_stop_id,
            tr.from_stop_pk,
            fs.stop_name AS transfer_stop_name,
            tr.to_stop_pk,
            tr.to_stop_id,
            ts.stop_name AS to_stop_name,
            tr.distance_m,
            tr.scheduled_transfer_minutes,
            tr.success_rate_pct,
            tr.median_gap_seconds,
            tr.n_observations,
            tr.computed_at
        FROM transfer_reliability tr
        JOIN gtfs_stops fs ON fs.stop_pk = tr.from_stop_pk
        JOIN gtfs_stops ts ON ts.stop_pk = tr.to_stop_pk
        WHERE {where}
        ORDER BY tr.n_observations DESC, tr.success_rate_pct ASC
        LIMIT :limit
    """), params).mappings().all()
    return [dict(r) for r in rows]

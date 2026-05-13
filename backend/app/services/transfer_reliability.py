"""Compute the cross-agency transfer reliability matrix.

For each (from_agency, to_agency, transfer_stop_id) tuple, count how often
a passenger arriving on `from_agency` at the stop could catch the next
`to_agency` vehicle at the same stop within an acceptable wait.

Output goes into the `transfer_reliability` table; populated nightly by
`run_data_jobs.py`.

Source: `ops_trip_events`. When the 511.org historic archive ingestor lands
the input table swaps to `stop_observations` without a schema change — same
columns (agency_id, stop_id, scheduled_arrival, actual_arrival) on both.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, Any

from sqlalchemy import text
from sqlalchemy.engine import Connection


# Minimum gap (seconds) between the "from" agency's arrival and the "to"
# agency's arrival for the transfer to be considered feasible.
WALK_TIME_SAME_STOP_SECONDS = 60

# Beyond this gap the passenger has given up — the connection is "missed".
# Anything past 30 minutes is operationally a different trip, not a transfer.
GIVE_UP_SECONDS = 1800

# How many days back the compute job looks.
DEFAULT_LOOKBACK_DAYS = 7


def compute_transfer_reliability(
    conn: Connection,
    *,
    days: int = DEFAULT_LOOKBACK_DAYS,
    walk_time_seconds: int = WALK_TIME_SAME_STOP_SECONDS,
    give_up_seconds: int = GIVE_UP_SECONDS,
) -> int:
    """Recompute the entire `transfer_reliability` table.

    Returns the number of (from, to, stop) rows written. Idempotent — the
    UNIQUE constraint on (from_agency, to_agency, transfer_stop_id) is the
    upsert key.
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    # Compute strategy:
    # 1. transfer_stops — pre-filter to stops served by ≥2 distinct agencies
    #    in the window.  Most stops in the catalog only see one agency, so
    #    this trims the outer rowset by ~99% before the LATERAL kicks in.
    # 2. event_pairs — for each "from" arrival at a transfer stop, find the
    #    next arrival of any *different* agency at the same stop within
    #    GIVE_UP_SECONDS.  The LATERAL is O(N log N) on top of
    #    idx_ops_trip_events_stop_arrival (added by migration 004).
    # 3. aggregated — success_rate + median gap per (from, to, stop) tuple.
    #
    # FILTER (WHERE ... IS NOT NULL) on the scheduled-percentile aggregate
    # silently drops pairs where either side has no schedule — common in
    # the dev DB since only ~3% of rows have scheduled_arrival populated
    # (the rest never matched gtfs_stop_times).  Without FILTER, NULL would
    # poison the median.
    rows = conn.execute(text("""
        WITH transfer_stops AS (
            SELECT stop_id
            FROM ops_trip_events
            WHERE service_date BETWEEN :start_date AND :end_date
              AND stop_id IS NOT NULL
              AND actual_arrival IS NOT NULL
            GROUP BY stop_id
            HAVING COUNT(DISTINCT agency_id) >= 2
        ),
        event_pairs AS (
            SELECT
                a.agency_id              AS from_agency,
                b.agency_id              AS to_agency,
                a.stop_id                AS transfer_stop_id,
                a.actual_arrival         AS from_actual,
                a.scheduled_arrival      AS from_sched,
                b.actual_arrival         AS to_actual,
                b.scheduled_arrival      AS to_sched
            FROM ops_trip_events a
            JOIN transfer_stops ts ON ts.stop_id = a.stop_id
            CROSS JOIN LATERAL (
                SELECT agency_id, actual_arrival, scheduled_arrival
                FROM ops_trip_events
                WHERE stop_id = a.stop_id
                  AND actual_arrival >  a.actual_arrival
                  AND actual_arrival <= a.actual_arrival + (:give_up_seconds || ' seconds')::interval
                  AND agency_id <> a.agency_id
                  AND actual_arrival IS NOT NULL
                ORDER BY actual_arrival ASC
                LIMIT 1
            ) b
            WHERE a.service_date BETWEEN :start_date AND :end_date
              AND a.actual_arrival IS NOT NULL
        ),
        aggregated AS (
            SELECT
                from_agency,
                to_agency,
                transfer_stop_id,
                COUNT(*)::int                                            AS n_observations,
                ROUND((
                    100.0
                    * SUM(CASE WHEN EXTRACT(EPOCH FROM (to_actual - from_actual)) >= :walk_time_seconds THEN 1 ELSE 0 END)::numeric
                    / COUNT(*)
                ), 2)                                                    AS success_rate_pct,
                EXTRACT(EPOCH FROM percentile_cont(0.5) WITHIN GROUP (
                    ORDER BY (to_actual - from_actual)
                ))::int                                                  AS median_gap_seconds,
                ROUND((
                    EXTRACT(EPOCH FROM percentile_cont(0.5) WITHIN GROUP (
                        ORDER BY (to_sched - from_sched)
                    ) FILTER (WHERE from_sched IS NOT NULL AND to_sched IS NOT NULL))
                    / 60.0
                )::numeric, 2)                                           AS scheduled_transfer_minutes
            FROM event_pairs
            GROUP BY from_agency, to_agency, transfer_stop_id
        )
        INSERT INTO transfer_reliability (
            from_agency, to_agency, transfer_stop_id,
            scheduled_transfer_minutes, success_rate_pct, median_gap_seconds,
            n_observations
        )
        SELECT
            from_agency, to_agency, transfer_stop_id,
            scheduled_transfer_minutes, success_rate_pct, median_gap_seconds,
            n_observations
        FROM aggregated
        ON CONFLICT (from_agency, to_agency, transfer_stop_id)
        DO UPDATE SET
            scheduled_transfer_minutes = EXCLUDED.scheduled_transfer_minutes,
            success_rate_pct           = EXCLUDED.success_rate_pct,
            median_gap_seconds         = EXCLUDED.median_gap_seconds,
            n_observations             = EXCLUDED.n_observations,
            computed_at                = now()
        RETURNING id
    """), {
        "start_date":         start_date,
        "end_date":           end_date,
        "walk_time_seconds":  walk_time_seconds,
        "give_up_seconds":    give_up_seconds,
    }).fetchall()

    return len(rows)


def get_transfer_reliability(
    conn: Connection,
    *,
    from_agency: str | None = None,
    to_agency:   str | None = None,
    min_observations: int = 0,
    limit: int = 500,
) -> list[Dict[str, Any]]:
    """Read the transfer_reliability table for the API.

    Joins to gtfs_stops to surface a human-readable `transfer_stop_name`
    alongside the bare id — the heatmap drill-down panel needs names so
    planners can recognise the corridor.
    """
    clauses = ["tr.n_observations >= :min_observations"]
    params: Dict[str, Any] = {"min_observations": min_observations, "limit": limit}
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
            s.stop_name AS transfer_stop_name,
            tr.scheduled_transfer_minutes,
            tr.success_rate_pct,
            tr.median_gap_seconds,
            tr.n_observations,
            tr.computed_at
        FROM transfer_reliability tr
        LEFT JOIN gtfs_stops s ON s.stop_id = tr.transfer_stop_id
        WHERE {where}
        ORDER BY tr.n_observations DESC, tr.success_rate_pct ASC
        LIMIT :limit
    """), params).mappings().all()
    return [dict(r) for r in rows]

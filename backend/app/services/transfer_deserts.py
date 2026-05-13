"""Transfer desert computation (Sprint 4a, Feature 3).

A *transfer desert* is a cell where two agencies are both technically
reachable but the second one is so far away that a real-world transfer
is implausible.  Concretely, for each (cell, agency_a, agency_b) we
require:

    LEAST  (dist_a, dist_b) <  CLOSE_ENOUGH_M   — at least one agency is here
    GREATEST(dist_a, dist_b) > DESERT_THRESHOLD_M — but the other is far

This distinguishes a *transfer* desert from a generic transit desert.
Planners care about transfer deserts when arguing for new service to
bridge two existing networks.

No persistent storage — computed on demand against the existing
`coverage_cells` hex grid and `gtfs_stops`.  The dataset is small
(~2,350 cells × ~13 agencies) and the dependencies change infrequently
enough that caching adds staleness without a perf win.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection


# Tunables, surfaced as query params so they can be adjusted from the UI
# without code churn.
DEFAULT_DESERT_THRESHOLD_M = 800   # "the other agency is too far for a transfer"
DEFAULT_CLOSE_ENOUGH_M     = 2000  # "at least one agency is realistically here"
# Upper bound on per-cell-per-agency search distance.  Beyond this we
# treat the agency as "not relevant to this cell" — not a missing
# transfer.  Without this, every Oakland cell would flag Sonoma-Marin
# (~70 km away) as a "missing pair", which is geographic nonsense.
# Also the perf knob: ST_DWithin prunes via the GIST index so each
# lookup is cheap when there's no candidate within range.
DEFAULT_MAX_SEARCH_M       = 3000


def compute_transfer_deserts(
    conn: Connection,
    *,
    agencies: Optional[List[str]] = None,
    min_population: int = 0,
    desert_threshold_m: int = DEFAULT_DESERT_THRESHOLD_M,
    close_enough_m:     int = DEFAULT_CLOSE_ENOUGH_M,
    max_search_m:       int = DEFAULT_MAX_SEARCH_M,
    limit: int = 1000,
) -> List[Dict[str, Any]]:
    """Find cells that are transfer deserts for at least one agency pair.

    Args:
        agencies: if provided, restrict the pairwise analysis to this subset
                  of agency_ids. Default = every agency with has_data = true.
        min_population: ignore cells with population below this. Default 0.
        desert_threshold_m: > this distance to the second agency → desert.
        close_enough_m: < this distance to the closer agency → real candidate.
        limit: cap on returned cells. Sorted by worst_distance_m DESC.

    Returns:
        List of {cell_id, geometry (GeoJSON), population, equity_score,
                 desert_pairs: [[agency_a, agency_b], ...],
                 worst_distance_m, pair_count}
    """
    params: Dict[str, Any] = {
        "desert_threshold_m": desert_threshold_m,
        "close_enough_m":     close_enough_m,
        "max_search_m":       max_search_m,
        "min_population":     min_population,
        "limit":              limit,
    }
    agency_filter = ""
    if agencies:
        agency_filter = "AND aa.agency_id = ANY(:agencies)"
        params["agencies"] = list(agencies)

    rows = conn.execute(text(f"""
        WITH active_agencies AS (
            -- The pairwise analysis is restricted to agencies that actually
            -- have stops in gtfs_stops.  We use an EXISTS check instead of
            -- the agencies.has_data column because has_data is computed at
            -- query time by get_agencies_list, not stored.
            SELECT DISTINCT s.agency_id
            FROM gtfs_stops s
            JOIN agencies aa ON aa.agency_id = s.agency_id
            WHERE s.geom IS NOT NULL
              AND s.agency_id IS NOT NULL
              {agency_filter}
        ),
        cells AS (
            SELECT id AS cell_id_pk, cell_id, geom AS cell_geom,
                   COALESCE(population, 0)   AS population,
                   COALESCE(equity_score, 0) AS equity_score
            FROM coverage_cells
            WHERE geom IS NOT NULL
              AND COALESCE(population, 0) >= :min_population
        ),
        nearest_per_pair AS (
            -- One spatial join over the whole grid: every (cell, stop)
            -- within max_search_m in degree-space is a candidate, then
            -- aggregate to MIN distance per (cell, agency).
            --
            -- Using `&&` against ST_Expand(geom, deg) so the GIST index on
            -- gtfs_stops(geom) (geometry, not geography) actually fires.
            -- A 3000 m degree-bound at Bay Area latitude is ~0.04 deg;
            -- /50000 gives a generous lat-deg padding.  Final accuracy
            -- comes from ST_Distance over geography.
            SELECT
                cc.cell_id_pk, cc.cell_id, cc.cell_geom,
                cc.population, cc.equity_score,
                aa.agency_id,
                MIN(ST_Distance(cc.cell_geom::geography, s.geom::geography))::int AS nearest_dist_m
            FROM cells cc
            CROSS JOIN active_agencies aa
            JOIN gtfs_stops s
              ON s.agency_id = aa.agency_id
             AND s.geom && ST_Expand(cc.cell_geom, CAST(:max_search_m AS float) / 50000)
            WHERE s.geom IS NOT NULL
            GROUP BY cc.cell_id_pk, cc.cell_id, cc.cell_geom,
                     cc.population, cc.equity_score, aa.agency_id
            HAVING MIN(ST_Distance(cc.cell_geom::geography, s.geom::geography)) <= :max_search_m
        ),
        desert_edges AS (
            -- Cross-join the cell × agency pairs to themselves to get
            -- agency_a < agency_b (unordered pairs).  Filter to the
            -- "transfer desert" condition.
            SELECT
                a.cell_id_pk, a.cell_id, a.cell_geom,
                a.population, a.equity_score,
                a.agency_id AS agency_a, b.agency_id AS agency_b,
                GREATEST(a.nearest_dist_m, b.nearest_dist_m) AS worst_distance_m
            FROM nearest_per_pair a
            JOIN nearest_per_pair b
              ON a.cell_id_pk = b.cell_id_pk
             AND a.agency_id < b.agency_id
            WHERE a.nearest_dist_m IS NOT NULL
              AND b.nearest_dist_m IS NOT NULL
              AND LEAST(a.nearest_dist_m, b.nearest_dist_m) <  :close_enough_m
              AND GREATEST(a.nearest_dist_m, b.nearest_dist_m) > :desert_threshold_m
        ),
        per_cell AS (
            SELECT
                cell_id_pk, cell_id, cell_geom, population, equity_score,
                ARRAY_AGG(
                    ARRAY[agency_a, agency_b]
                    ORDER BY worst_distance_m DESC
                )                       AS desert_pairs,
                MAX(worst_distance_m)   AS worst_distance_m,
                COUNT(*)::int           AS pair_count
            FROM desert_edges
            GROUP BY cell_id_pk, cell_id, cell_geom, population, equity_score
        )
        SELECT
            cell_id,
            ST_AsGeoJSON(cell_geom)::json AS geometry,
            population,
            equity_score,
            desert_pairs,
            worst_distance_m::int   AS worst_distance_m,
            pair_count
        FROM per_cell
        ORDER BY (population * pair_count) DESC, worst_distance_m DESC
        LIMIT :limit
    """), params).mappings().all()

    return [dict(r) for r in rows]


def transfer_deserts_geojson(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Wrap the row list in a GeoJSON FeatureCollection for /transfers/deserts."""
    features = []
    for r in rows:
        props = dict(r)
        geom  = props.pop("geometry")
        features.append({"type": "Feature", "geometry": geom, "properties": props})
    return {"type": "FeatureCollection", "features": features}

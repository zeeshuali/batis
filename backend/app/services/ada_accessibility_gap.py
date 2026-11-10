"""ADA Accessibility Gap — per-stop scoring of supply_penalty
(wheelchair_boarding + Pathways override) × demand (areal-
interpolated ACS B18105 ambulatory pop in 400m catchment).

See docs/superpowers/specs/2026-05-13-sprint-5c-design.md.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection


logger = logging.getLogger(__name__)


def _supply_penalty(
    wheelchair_boarding: Optional[int],
    has_accessible_pathway: Optional[bool],
    location_type: Optional[int],
) -> float:
    """Map wheelchair_boarding + Pathways-override to penalty in [0, 1].

      wheelchair_boarding = 1 (accessible)        → 0.0
      wheelchair_boarding = 0 / None (unknown)    → 0.5
      wheelchair_boarding = 2 (not accessible)    → 1.0

    Pathways override (rail stations only — location_type in {1, 2}):
      has_accessible_pathway is False
        → 1.0 (regardless of wheelchair_boarding)

    has_accessible_pathway = None means "no pathways data for this
    stop" — do not override; fall through to wheelchair_boarding.
    """
    if location_type in (1, 2) and has_accessible_pathway is False:
        return 1.0
    if wheelchair_boarding == 1:
        return 0.0
    if wheelchair_boarding == 2:
        return 1.0
    return 0.5


def _gap_tier(score: float, *, p90: float, p75: float, p50: float) -> str:
    """Percentile-banded tier label.

    Stops with score == 0 always return 'low' (already accessible —
    no investment need regardless of demand).
    """
    if score <= 0:
        return "low"
    if score >= p90:
        return "very_high"
    if score >= p75:
        return "high"
    if score >= p50:
        return "moderate"
    return "low"


def _catchment_radius() -> int:
    """Read the per-stop catchment radius from Settings.

    Field is typed `int` (non-Optional, default 400), so pydantic-
    settings guarantees an int at runtime.  Falsy-zero is left alone
    on purpose — a configured 0 would be a misconfiguration but not
    silently rewritten.
    """
    from app.core.config import get_settings
    return get_settings().ada_catchment_radius_m


def _percentile_thresholds() -> tuple[float, float, float]:
    """Read the three percentile cutoffs from Settings (defaults 0.9 /
    0.75 / 0.5)."""
    from app.core.config import get_settings
    s = get_settings()
    return (s.ada_tier_percentile_high,
            s.ada_tier_percentile_moderate,
            s.ada_tier_percentile_low)


def compute_stop_ada_gap_for_all_stops(
    conn: Connection,
    *,
    catchment_radius_m: Optional[int] = None,
) -> int:
    """Recompute per-stop ADA gap scores in one SQL pass.

    CTE pipeline:
      supply       — wheelchair_boarding + Pathways override (rail only)
      demand       — areal-interpolated B18105 into a buffer of
                     `catchment_radius_m` meters around each stop
      combined     — supply × demand → gap_score
      percentiles  — PERCENTILE_CONT over non-zero gap_scores
      INSERT … ON CONFLICT (stop_pk) DO UPDATE  with banded gap_tier.

    Returns rowcount.
    """
    if catchment_radius_m is None:
        catchment_radius_m = _catchment_radius()
    p_high, p_moderate, p_low = _percentile_thresholds()

    result = conn.execute(text("""
        WITH supply AS (
          SELECT s.stop_pk,
                 s.stop_id,
                 s.agency_id,
                 s.location_type,
                 s.wheelchair_boarding,
                 EXISTS (
                   SELECT 1 FROM gtfs_pathways p
                    WHERE p.agency_id = s.agency_id
                      AND (p.from_stop_id = s.stop_id
                           OR p.to_stop_id = s.stop_id)
                 ) AS has_pathways_data,
                 EXISTS (
                   SELECT 1 FROM gtfs_pathways p
                    WHERE p.agency_id = s.agency_id
                      AND (p.from_stop_id = s.stop_id
                           OR p.to_stop_id = s.stop_id)
                      -- "Accessible" = any non-stairs pathway (mode 2 = stairs).
                      -- Includes walkways, moving sidewalks, escalators, elevators,
                      -- and gate-type edges. Permissive but defensible — matches the
                      -- spec's "Pathways override fires only when the only path is
                      -- stairs" intent.
                      AND p.pathway_mode <> 2
                 ) AS has_accessible_pathway
            FROM gtfs_stops s
           WHERE s.geom IS NOT NULL
        ),
        demand AS (
          SELECT s.stop_pk,
                 COALESCE(SUM(
                   ca.ambulatory_pop
                   * ST_Area(ST_Intersection(buf.geom, t.geom))
                   / NULLIF(ST_Area(t.geom), 0)
                 ), 0)::int AS ambulatory_pop_400m
            FROM gtfs_stops s
            CROSS JOIN LATERAL (
              SELECT ST_Buffer(s.geom::geography, :r)::geometry AS geom
            ) buf
            LEFT JOIN census_tracts     t  ON ST_Intersects(buf.geom, t.geom)
            LEFT JOIN census_ambulatory ca USING (tract_geoid)
           WHERE s.geom IS NOT NULL
           GROUP BY s.stop_pk
        ),
        combined AS (
          SELECT supply.stop_pk, supply.stop_id, supply.agency_id,
                 CASE
                   WHEN supply.location_type IN (1, 2)
                    AND supply.has_pathways_data
                    AND NOT supply.has_accessible_pathway
                       THEN 1.0
                   WHEN supply.wheelchair_boarding = 1 THEN 0.0
                   WHEN supply.wheelchair_boarding = 2 THEN 1.0
                   ELSE 0.5
                 END AS supply_penalty,
                 (supply.location_type IN (1, 2)
                    AND supply.has_pathways_data
                    AND NOT supply.has_accessible_pathway) AS pathways_override,
                 demand.ambulatory_pop_400m
            FROM supply
            JOIN demand USING (stop_pk)
        ),
        scored AS (
          SELECT *,
                 (supply_penalty * ambulatory_pop_400m)::numeric(10,2)
                   AS gap_score
            FROM combined
        ),
        percentiles AS (
          SELECT PERCENTILE_CONT(:p_high)     WITHIN GROUP (ORDER BY gap_score) AS p_high,
                 PERCENTILE_CONT(:p_moderate) WITHIN GROUP (ORDER BY gap_score) AS p_moderate,
                 PERCENTILE_CONT(:p_low)      WITHIN GROUP (ORDER BY gap_score) AS p_low
            FROM scored
           WHERE gap_score > 0
        )
        INSERT INTO stop_ada_gap (
          stop_pk, stop_id, agency_id, supply_penalty, ambulatory_pop_400m,
          gap_score, gap_tier, pathways_override,
          catchment_radius_m, computed_at
        )
        SELECT scored.stop_pk, scored.stop_id, scored.agency_id,
               scored.supply_penalty, scored.ambulatory_pop_400m,
               scored.gap_score,
               CASE
                 WHEN scored.gap_score <= 0                  THEN 'low'
                 WHEN scored.gap_score >= COALESCE(percentiles.p_high, 0)
                   AND COALESCE(percentiles.p_high, 0) > 0   THEN 'very_high'
                 WHEN scored.gap_score >= COALESCE(percentiles.p_moderate, 0)
                   AND COALESCE(percentiles.p_moderate, 0) > 0 THEN 'high'
                 WHEN scored.gap_score >= COALESCE(percentiles.p_low, 0)
                   AND COALESCE(percentiles.p_low, 0) > 0    THEN 'moderate'
                 ELSE 'low'
               END,
               scored.pathways_override,
               :r,
               now()
          FROM scored, percentiles
        ON CONFLICT (stop_pk) DO UPDATE
          SET agency_id            = EXCLUDED.agency_id,
              supply_penalty       = EXCLUDED.supply_penalty,
              ambulatory_pop_400m  = EXCLUDED.ambulatory_pop_400m,
              gap_score            = EXCLUDED.gap_score,
              gap_tier             = EXCLUDED.gap_tier,
              pathways_override    = EXCLUDED.pathways_override,
              catchment_radius_m   = EXCLUDED.catchment_radius_m,
              computed_at          = EXCLUDED.computed_at
    """), {"r": catchment_radius_m,
           "p_high": p_high,
           "p_moderate": p_moderate,
           "p_low": p_low})
    return result.rowcount


def refresh_cell_ada_gap(conn: Connection) -> None:
    """Refresh the cell_ada_gap materialized view.  Not CONCURRENTLY
    because the view has no unique index (same precedent as Sprint
    5b's stop_cell)."""
    conn.execute(text("REFRESH MATERIALIZED VIEW cell_ada_gap"))


def get_cell_ada_gap_features(
    conn: Connection,
    *,
    min_population: int = 0,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    """Read cell_ada_gap joined with coverage_cells.geom + equity
    columns, return GeoJSON-ready Feature dicts.  Sorted by
    max_gap_score DESC.
    """
    rows = conn.execute(text("""
        SELECT cag.cell_id,
               ST_AsGeoJSON(cc.geom)::json AS geometry,
               cag.stop_count,
               cag.max_gap_score,
               cag.mean_gap_score,
               cag.worst_tier,
               cc.population,
               cc.equity_score
          FROM cell_ada_gap cag
          JOIN coverage_cells cc USING (cell_id)
         WHERE COALESCE(cc.population, 0) >= :min_pop
           AND cag.max_gap_score IS NOT NULL
         ORDER BY cag.max_gap_score DESC NULLS LAST, cag.cell_id
         LIMIT :lim
    """), {"min_pop": min_population, "lim": limit}).mappings().all()

    features: list[dict[str, Any]] = []
    for r in rows:
        features.append({
            "type":     "Feature",
            "geometry": r["geometry"],
            "properties": {
                "cell_id":         r["cell_id"],
                "stop_count":      int(r["stop_count"] or 0),
                "max_gap_score":   float(r["max_gap_score"])
                                   if r["max_gap_score"] is not None else None,
                "mean_gap_score":  float(r["mean_gap_score"])
                                   if r["mean_gap_score"] is not None else None,
                "worst_tier":      r["worst_tier"],
                "population":      r["population"],
                "equity_score":    float(r["equity_score"])
                                   if r["equity_score"] is not None else None,
            },
        })
    return features


def get_stop_ada_gap_breakdown(
    conn: Connection,
    stop_id: str,
    agency_id: Optional[str] = None,
) -> dict[str, Any]:
    """Per-stop drill: stop metadata + routes serving + top-3
    contributing tracts by area-weighted ambulatory pop.

    stop_id is agency-assigned and may repeat across agencies; pass
    agency_id to disambiguate (otherwise the lowest agency_id wins)."""
    meta_row = conn.execute(text("""
        SELECT sag.stop_pk, sag.stop_id, sag.agency_id, s.stop_name,
               sag.gap_score, sag.gap_tier, sag.supply_penalty,
               sag.pathways_override, sag.catchment_radius_m
          FROM stop_ada_gap sag
          JOIN gtfs_stops    s ON s.stop_pk = sag.stop_pk
         WHERE sag.stop_id = :sid
           AND (CAST(:aid AS text) IS NULL OR sag.agency_id = :aid)
         ORDER BY sag.agency_id
         LIMIT 1
    """), {"sid": stop_id, "aid": agency_id}).mappings().fetchone()

    if not meta_row:
        return {"stop_id": stop_id, "routes": [], "tracts": []}

    # Source the route identifier from gtfs_trips (where agency_id is
    # trustworthy — set by the loader from the feed being processed) and
    # LEFT JOIN gtfs_routes on the composite (agency_id, route_id). This
    # survives the pre-009 corruption gracefully: if a route row exists
    # for the right agency, we get its short_name; if it was clobbered by
    # another agency's load, we fall back to route_id rather than
    # eliminating the entire row from the result.
    routes = conn.execute(text("""
        SELECT tr.route_id,
               COALESCE(r.route_short_name, tr.route_id) AS route_short_name,
               COUNT(DISTINCT tr.trip_id)::int AS trips_per_day
          FROM gtfs_stop_times st
          JOIN gtfs_trips      tr ON tr.agency_id = st.agency_id
                                 AND tr.trip_id   = st.trip_id
          LEFT JOIN gtfs_routes r  ON r.agency_id = tr.agency_id
                                 AND r.route_id   = tr.route_id
         WHERE st.stop_pk   = :pk
         GROUP BY tr.route_id, r.route_short_name
         ORDER BY trips_per_day DESC
         LIMIT 10
    """), {"pk": meta_row["stop_pk"]}).mappings().all()

    radius = meta_row["catchment_radius_m"] or 400
    tracts = conn.execute(text("""
        WITH stop_geom AS (
          SELECT geom FROM gtfs_stops WHERE stop_pk = :pk
        ),
        buf AS (
          SELECT ST_Buffer((SELECT geom FROM stop_geom)::geography, :r)::geometry AS geom
        ),
        contributions AS (
          SELECT t.tract_geoid,
                 ca.ambulatory_pop,
                 ST_Area(ST_Intersection(buf.geom, t.geom)) AS overlap_area,
                 ST_Area(t.geom) AS tract_area
            FROM census_tracts     t
            CROSS JOIN buf
            JOIN census_ambulatory ca USING (tract_geoid)
           WHERE ST_Intersects(buf.geom, t.geom)
        )
        SELECT tract_geoid,
               ambulatory_pop,
               ROUND((overlap_area / NULLIF(tract_area, 0))::numeric, 3)::float
                 AS area_weighted_share
          FROM contributions
         ORDER BY (ambulatory_pop * overlap_area / NULLIF(tract_area, 0)) DESC
         LIMIT 3
    """), {"pk": meta_row["stop_pk"], "r": radius}).mappings().all()

    return {
        "stop_id":           meta_row["stop_id"],
        "stop_name":         meta_row["stop_name"],
        "agency_id":         meta_row["agency_id"],
        "gap_score":         float(meta_row["gap_score"]) if meta_row["gap_score"] is not None else None,
        "gap_tier":          meta_row["gap_tier"],
        "supply_penalty":    float(meta_row["supply_penalty"]) if meta_row["supply_penalty"] is not None else None,
        "pathways_override": bool(meta_row["pathways_override"]),
        "routes":  [{"route_id":         r["route_id"],
                     "route_short_name": r["route_short_name"],
                     "trips_per_day":    int(r["trips_per_day"]),
                     "agency_id":        meta_row["agency_id"]}
                    for r in routes],
        "tracts":  [{"tract_geoid":         t["tract_geoid"],
                     "ambulatory_pop":      int(t["ambulatory_pop"] or 0),
                     "area_weighted_share": float(t["area_weighted_share"] or 0.0)}
                    for t in tracts],
    }


def get_stop_ada_gap_features(
    conn: Connection,
    *,
    tier: Optional[str] = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    """Read stop_ada_gap joined with gtfs_stops geometry + routes
    serving (from gtfs_stop_times + gtfs_trips), return GeoJSON-ready
    Feature dicts.  Sorted by gap_score DESC.
    """
    rows = conn.execute(text("""
        SELECT sag.stop_id,
               sag.agency_id,
               s.stop_name,
               s.wheelchair_boarding,
               sag.supply_penalty,
               sag.ambulatory_pop_400m,
               sag.gap_score,
               sag.gap_tier,
               sag.pathways_override,
               ST_AsGeoJSON(s.geom)::json AS geometry,
               -- Trust gtfs_trips.agency_id (set by the loader); LEFT JOIN
               -- to gtfs_routes on composite (agency_id, route_id) and
               -- fall back to route_id when the routes row was clobbered
               -- pre-009. See get_stop_ada_gap_breakdown for the same pattern.
               COALESCE(
                 (SELECT array_agg(DISTINCT
                          COALESCE(r.route_short_name, tr.route_id)
                          ORDER BY COALESCE(r.route_short_name, tr.route_id))
                    FROM gtfs_stop_times st
                    JOIN gtfs_trips      tr ON tr.agency_id = st.agency_id
                                           AND tr.trip_id   = st.trip_id
                    LEFT JOIN gtfs_routes r  ON r.agency_id = tr.agency_id
                                           AND r.route_id   = tr.route_id
                   WHERE st.stop_pk = sag.stop_pk), ARRAY[]::text[]
               ) AS routes_serving
          FROM stop_ada_gap sag
          JOIN gtfs_stops    s ON s.stop_pk = sag.stop_pk
         WHERE (:tier IS NULL OR sag.gap_tier = :tier)
         ORDER BY sag.gap_score DESC NULLS LAST, sag.stop_pk
         LIMIT :lim
    """), {"tier": tier, "lim": limit}).mappings().all()

    features: list[dict[str, Any]] = []
    for r in rows:
        features.append({
            "type":     "Feature",
            "geometry": r["geometry"],
            "properties": {
                "stop_id":             r["stop_id"],
                "agency_id":           r["agency_id"],
                "stop_name":           r["stop_name"],
                "wheelchair_boarding": r["wheelchair_boarding"],
                "supply_penalty":      float(r["supply_penalty"])
                                       if r["supply_penalty"] is not None else None,
                "ambulatory_pop_400m": int(r["ambulatory_pop_400m"])
                                       if r["ambulatory_pop_400m"] is not None else 0,
                "gap_score":           float(r["gap_score"])
                                       if r["gap_score"] is not None else 0.0,
                "gap_tier":            r["gap_tier"],
                "pathways_override":   bool(r["pathways_override"]),
                "routes_serving":      list(r["routes_serving"] or []),
            },
        })
    return features

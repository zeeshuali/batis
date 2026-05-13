"""Service Delivery Gap — per-cell scheduled-vs-observed trip
completion over a trailing 12-month window.

See docs/superpowers/specs/2026-05-12-sprint-5b-design.md.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection


def _gap_tier(pct: Optional[float]) -> Optional[str]:
    """Map gap_pct to a 4-tier label.  None when pct is None.

    Tier bands derive from FTA's "OTP ≥ 95%" benchmark:
      <2     low         — well within tolerance
      2–5    moderate    — below benchmark, not yet a problem
      5–10   high        — operationally problematic
      ≥10    very_high   — a real service-delivery failure
    """
    if pct is None:
        return None
    if pct >= 10: return "very_high"
    if pct >= 5:  return "high"
    if pct >= 2:  return "moderate"
    return "low"


# Tolerance window for "on time": ±5 minutes.  A scheduled arrival is
# "missed" if observed_arrival is NULL OR abs(observed - scheduled)
# exceeds this tolerance.  Configurable via Settings.
_DEFAULT_TOLERANCE_SECONDS = 5 * 60


def compute_service_delivery_gap_for_all_cells(
    conn: Connection,
    *,
    window_days: int = 365,
    min_scheduled: int = 50,
    tolerance_seconds: int = _DEFAULT_TOLERANCE_SECONDS,
) -> int:
    """Recompute gap_pct for every cell with >= min_scheduled scheduled
    arrivals in the trailing window_days.  UPSERTs into
    service_delivery_gap.  Returns number of cells written.
    """
    window_end   = date.today()
    window_start = window_end - timedelta(days=window_days)

    rows = conn.execute(text("""
        WITH per_cell AS (
            SELECT sc.cell_id,
                   COUNT(*) AS scheduled,
                   COUNT(*) FILTER (
                       WHERE so.observed_arrival IS NULL
                          OR ABS(EXTRACT(EPOCH FROM (
                                so.observed_arrival - so.scheduled_arrival))) > :tol
                   ) AS missed
              FROM stop_observations so
              JOIN stop_cell sc USING (stop_id)
             WHERE so.service_date >= :ws
               AND so.service_date <= :we
             GROUP BY sc.cell_id
            HAVING COUNT(*) >= :minN
        )
        INSERT INTO service_delivery_gap
              (cell_id, scheduled_arrivals, missed_arrivals,
               gap_pct, window_start, window_end, computed_at)
        SELECT cell_id, scheduled, missed,
               ROUND(100.0 * missed / scheduled, 3),
               :ws, :we, now()
          FROM per_cell
        ON CONFLICT (cell_id) DO UPDATE
           SET scheduled_arrivals = EXCLUDED.scheduled_arrivals,
               missed_arrivals    = EXCLUDED.missed_arrivals,
               gap_pct            = EXCLUDED.gap_pct,
               window_start       = EXCLUDED.window_start,
               window_end         = EXCLUDED.window_end,
               computed_at        = EXCLUDED.computed_at
        RETURNING cell_id
    """), {"tol": tolerance_seconds, "ws": window_start,
           "we": window_end, "minN": min_scheduled})
    return rows.rowcount


def get_service_delivery_gap_features(
    conn: Connection,
    *,
    min_population: int = 0,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    """Read service_delivery_gap joined with coverage_cells.geom +
    equity columns, return GeoJSON-ready Feature dicts.

    equity_adjusted_gap = gap_pct * equity_score, used by the UI as
    the secondary sort key for the top-10 list.
    """
    rows = conn.execute(text("""
        SELECT sdg.cell_id,
               ST_AsGeoJSON(cc.geom)::json AS geometry,
               sdg.scheduled_arrivals,
               sdg.missed_arrivals,
               sdg.gap_pct,
               sdg.window_start,
               sdg.window_end,
               cc.equity_score,
               cc.population
          FROM service_delivery_gap sdg
          JOIN coverage_cells     cc USING (cell_id)
         WHERE COALESCE(cc.population, 0) >= :min_pop
         ORDER BY sdg.gap_pct DESC, sdg.cell_id
         LIMIT :lim
    """), {"min_pop": min_population, "lim": limit}).mappings().all()

    features: list[dict[str, Any]] = []
    for r in rows:
        gap_pct      = float(r["gap_pct"])
        equity       = float(r["equity_score"]) if r["equity_score"] is not None else None
        adjusted_gap = gap_pct * equity if equity is not None else None

        features.append({
            "type":     "Feature",
            "geometry": r["geometry"],
            "properties": {
                "cell_id":             r["cell_id"],
                "gap_pct":             gap_pct,
                "gap_tier":            _gap_tier(gap_pct),
                "scheduled_arrivals":  r["scheduled_arrivals"],
                "missed_arrivals":     r["missed_arrivals"],
                "window_start":        r["window_start"].isoformat(),
                "window_end":          r["window_end"].isoformat(),
                "equity_score":        equity,
                "equity_adjusted_gap": adjusted_gap,
                "population":          r["population"],
            },
        })
    return features

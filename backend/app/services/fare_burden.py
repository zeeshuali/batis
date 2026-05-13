"""Per-cell fare burden compute (Sprint 5a, Feature 1 — backend).

For every coverage_cell, sample N OD stop pairs to each of 3 Bay Area
job-centre anchors, compute the median fare via the Sprint 4b sampler,
and cache the result in `fare_burden`.  The endpoint multiplies by
`median_household_income` at query time to produce burden_pct so the
UI can reweight anchors without re-running the heavy compute.

Cells with no single-agency path to a given anchor get NULL for that
anchor.  A cell with 0 reachable anchors is rendered hatched in the UI
and excluded from the top-N burden list.
"""
from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.services.fare_calculator import Leg, calculate_fare
from app.services.fare_sampler import LatLng, _nearest_stops


# Anchor destinations — pinned to actual BART station entrances so the
# sampler's nearest-stops scan reliably finds the anchor agency at each
# point.  Verify against gtfs_stops on first run; if any anchor drifts
# more than ~300 m from its real station the scan won't pick up the
# right agency and that anchor's column ends up NULL for many cells.
ANCHORS: List[Dict[str, Any]] = [
    {"id": "sf",      "name": "Downtown SF",      "lat": 37.7929, "lng": -122.3970},
    {"id": "oakland", "name": "Downtown Oakland", "lat": 37.8038, "lng": -122.2715},
    {"id": "sfo",     "name": "SFO Airport",      "lat": 37.6157, "lng": -122.3925},
]


# Number of OD stop pairs to sample per (cell, anchor) before computing
# the median.  10 trades off precision against compute time:
#   2,350 cells * 3 anchors * 10 samples ≈ 70k fare lookups.
DEFAULT_SAMPLES_PER_PAIR = 10


def _median_fare_for_pair(
    conn: Connection,
    cell_centroid: LatLng,
    anchor: LatLng,
    n_samples: int,
) -> Optional[float]:
    """Sample up to `n_samples` single-agency OD stop pairs between the
    cell centroid and the anchor, return median fare.  None if no
    single-agency path exists (agencies serving the cell-neighbourhood
    and the anchor-neighbourhood don't overlap).

    Re-uses the Sprint 4b `_nearest_stops` primitive but builds its own
    candidate list rather than calling `sample_corridor`, because the
    sampler's overhead (cell-mapping, equity-tier rollup, ~30 candidate
    fares) is wasted here — we only need a small set of fares back.
    """
    origin_stops = _nearest_stops(conn, cell_centroid, n_samples * 5)
    dest_stops   = _nearest_stops(conn, anchor,        n_samples * 5)
    if not origin_stops or not dest_stops:
        return None

    o_by_agency: Dict[str, List[dict]] = {}
    for s in origin_stops:
        o_by_agency.setdefault(s["agency_id"], []).append(s)
    d_by_agency: Dict[str, List[dict]] = {}
    for s in dest_stops:
        d_by_agency.setdefault(s["agency_id"], []).append(s)

    shared = sorted(set(o_by_agency) & set(d_by_agency))
    if not shared:
        return None

    fares: List[float] = []
    # Round-robin across agencies so a one-agency-dominant origin doesn't
    # crowd out a less-represented one's signal.
    pairs_per_agency = max(1, n_samples // len(shared))
    for agency_id in shared:
        os = o_by_agency[agency_id][:pairs_per_agency]
        ds = d_by_agency[agency_id][:pairs_per_agency]
        for o in os:
            for d in ds:
                if len(fares) >= n_samples:
                    break
                leg = Leg(
                    agency_id=agency_id,
                    origin_stop_id=o["stop_id"],
                    destination_stop_id=d["stop_id"],
                )
                result = calculate_fare(conn, [leg])
                if result.legs and result.legs[0].fare is not None:
                    fares.append(float(result.legs[0].fare))
            if len(fares) >= n_samples:
                break

    if not fares:
        return None
    return statistics.median(fares)


def compute_fare_burden_for_all_cells(
    conn: Connection,
    *,
    anchors: List[Dict[str, Any]] = None,
    n_samples: int = DEFAULT_SAMPLES_PER_PAIR,
) -> int:
    """Recompute the `fare_burden` table for every coverage_cell.

    Returns the number of rows UPSERTed.  Idempotent — the PRIMARY KEY
    on cell_id is the conflict target.
    """
    use_anchors = anchors if anchors is not None else ANCHORS

    # Pull every cell's centroid + the population/income context the
    # endpoint needs.
    cells = conn.execute(text("""
        SELECT cell_id,
               ST_Y(ST_Centroid(geom)) AS lat,
               ST_X(ST_Centroid(geom)) AS lng,
               COALESCE(population, 0)              AS population,
               median_household_income
        FROM coverage_cells
        WHERE geom IS NOT NULL
    """)).mappings().all()

    n_written = 0
    for row in cells:
        cell_centroid = LatLng(lat=row["lat"], lng=row["lng"])
        per_anchor: Dict[str, Optional[float]] = {}
        for anchor in use_anchors:
            median = _median_fare_for_pair(
                conn, cell_centroid,
                LatLng(lat=anchor["lat"], lng=anchor["lng"]),
                n_samples=n_samples,
            )
            per_anchor[anchor["id"]] = median

        reachable = sum(1 for v in per_anchor.values() if v is not None)
        conn.execute(text("""
            INSERT INTO fare_burden (
                cell_id, median_fare_to_sf, median_fare_to_oakland,
                median_fare_to_sfo, reachable_anchor_count,
                population, median_household_income, computed_at
            ) VALUES (
                :cell_id, :sf, :oakland, :sfo,
                :reachable, :population, :income, now()
            )
            ON CONFLICT (cell_id) DO UPDATE SET
                median_fare_to_sf       = EXCLUDED.median_fare_to_sf,
                median_fare_to_oakland  = EXCLUDED.median_fare_to_oakland,
                median_fare_to_sfo      = EXCLUDED.median_fare_to_sfo,
                reachable_anchor_count  = EXCLUDED.reachable_anchor_count,
                population              = EXCLUDED.population,
                median_household_income = EXCLUDED.median_household_income,
                computed_at             = now()
        """), {
            "cell_id":   row["cell_id"],
            "sf":        per_anchor.get("sf"),
            "oakland":   per_anchor.get("oakland"),
            "sfo":       per_anchor.get("sfo"),
            "reachable": reachable,
            "population": row["population"],
            "income":    row["median_household_income"],
        })
        n_written += 1

    return n_written


# ── Endpoint helper ──────────────────────────────────────────────────────────

def get_fare_burden_features(
    conn: Connection,
    *,
    anchor_weights: Optional[Dict[str, float]] = None,
    min_population: int = 0,
    limit: int = 2000,
) -> List[Dict[str, Any]]:
    """Read fare_burden + coverage_cells.geom, compute burden_pct + tier
    on the fly, return GeoJSON-ready Feature dicts.

    anchor_weights: e.g. {"sf": 1.0, "oakland": 1.0, "sfo": 0.5}.
    Default is equal weight across the three.  A weighted "worst fare"
    is the max of (fare * weight) across reachable anchors.
    """
    weights = anchor_weights or {"sf": 1.0, "oakland": 1.0, "sfo": 1.0}
    rows = conn.execute(text("""
        SELECT fb.cell_id,
               ST_AsGeoJSON(cc.geom)::json AS geometry,
               fb.median_fare_to_sf,
               fb.median_fare_to_oakland,
               fb.median_fare_to_sfo,
               fb.reachable_anchor_count,
               fb.population,
               fb.median_household_income
        FROM fare_burden fb
        JOIN coverage_cells cc USING (cell_id)
        WHERE COALESCE(fb.population, 0) >= :min_population
        ORDER BY fb.reachable_anchor_count DESC, fb.cell_id
        LIMIT :limit
    """), {"min_population": min_population, "limit": limit}).mappings().all()

    features: List[Dict[str, Any]] = []
    for r in rows:
        per_anchor = {
            "sf":      r["median_fare_to_sf"],
            "oakland": r["median_fare_to_oakland"],
            "sfo":     r["median_fare_to_sfo"],
        }
        weighted = [
            float(v) * weights.get(k, 1.0)
            for k, v in per_anchor.items()
            if v is not None
        ]
        worst_fare = max(weighted) if weighted else None

        income = r["median_household_income"]
        if worst_fare is not None and income and income > 0:
            monthly_cost  = worst_fare * 2 * 22   # round-trip × workdays
            monthly_inc   = income / 12.0
            burden_pct    = 100.0 * monthly_cost / monthly_inc
        else:
            burden_pct = None

        tier = _burden_tier(burden_pct)

        props = {
            "cell_id":                 r["cell_id"],
            "median_fare_to_sf":       float(r["median_fare_to_sf"])      if r["median_fare_to_sf"]      is not None else None,
            "median_fare_to_oakland":  float(r["median_fare_to_oakland"]) if r["median_fare_to_oakland"] is not None else None,
            "median_fare_to_sfo":      float(r["median_fare_to_sfo"])     if r["median_fare_to_sfo"]     is not None else None,
            "worst_fare":              worst_fare,
            "burden_pct":              burden_pct,
            "burden_tier":             tier,
            "reachable_anchor_count":  r["reachable_anchor_count"],
            "population":              r["population"],
            "median_household_income": income,
        }
        features.append({
            "type": "Feature",
            "geometry": r["geometry"],
            "properties": props,
        })
    return features


def _burden_tier(pct: Optional[float]) -> Optional[str]:
    """Map burden_pct to a 4-tier label. None when burden_pct is None
    (cell is unreachable or has no income data)."""
    if pct is None:
        return None
    if pct >= 15: return "very_high"
    if pct >= 10: return "high"
    if pct >= 5:  return "moderate"
    return "low"

"""Corridor fare sampler (Sprint 4b, Feature 2 backend support).

Given two geographic clicks (origin + destination), sample N stop pairs
between them, compute the fare for each via `fare_calculator`, and
aggregate into a corridor summary that the Planning → Fares page renders.

V1: single-agency pairs only.  Multi-agency multi-leg sampling (composing
AC + BART via a transfer point) defers to v2 once we see what users
actually click on.  When the clicks span two different single-agency
networks the response surfaces notice="no direct connection between
regions" so the UI can render a clear empty-state.
"""
from __future__ import annotations

import random
import statistics
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.services.fare_calculator import Leg, calculate_fare


# Number of nearest stops considered around each click before pairing.
_STOPS_PER_CLICK = 50

# Maximum walk distance from the click point to any candidate stop.  A
# generous bound — the corridor analysis should reach across a neighbourhood
# even if the user clicks in a low-density area.
_STOP_RADIUS_M = 1500

# Below this floor we render a "not enough OD pairs" empty state rather than
# misleading the planner with a sparse histogram.
_MIN_PAIRS_FOR_SUMMARY = 5

# Coverage cells live at ~250 m hex spacing; 400 m maps an origin stop to
# at most a couple of adjacent cells.  Pairs whose origin stop maps to no
# cell are excluded from the equity breakdown but still counted in
# overall medians.
_CELL_LOOKUP_RADIUS_M = 400


# ── Request / response shapes ────────────────────────────────────────────────

class LatLng(BaseModel):
    lat: float
    lng: float


class SampleCorridorRequest(BaseModel):
    origin:      LatLng
    destination: LatLng
    n:           int = 30


class TierBreakdown(BaseModel):
    n:           int
    median_fare: Optional[float]


class HighBurdenCell(BaseModel):
    cell_id:        str
    equity_score:   float
    median_fare:    float
    burden:         float


class SampleCorridorResult(BaseModel):
    n_sampled:        int
    median_fare:      Optional[float]
    p25_fare:         Optional[float]
    p75_fare:         Optional[float]
    max_fare:         Optional[float]
    agencies:         List[str]
    by_equity_tier:   Dict[str, TierBreakdown]
    high_burden_cells: List[HighBurdenCell]
    notice:           Optional[str]


# ── Stop discovery ───────────────────────────────────────────────────────────

def _nearest_stops(conn: Connection, point: LatLng, limit: int) -> List[Dict[str, Any]]:
    """Return the `limit` stops nearest to `point`, with their agency.

    Joined to the agencies table to filter out 511.org admin entries
    (5E/5F/etc.) — they have no fare data and would skew the sampler.
    """
    rows = conn.execute(text("""
        SELECT s.stop_id, s.agency_id, s.stop_name,
               s.stop_lat, s.stop_lon,
               ST_Distance(
                   s.geom::geography,
                   ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
               ) AS dist_m
        FROM gtfs_stops s
        WHERE s.geom IS NOT NULL
          AND s.agency_id NOT LIKE '5_'
          AND ST_DWithin(
              s.geom::geography,
              ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
              :radius_m
          )
        ORDER BY s.geom <-> ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)
        LIMIT :limit
    """), {
        "lat": point.lat, "lng": point.lng,
        "radius_m": _STOP_RADIUS_M, "limit": limit,
    }).mappings().all()
    return [dict(r) for r in rows]


# ── Equity-cell lookup ───────────────────────────────────────────────────────

def _cell_for_stop(conn: Connection, stop_lat: float, stop_lon: float) -> Optional[Dict[str, Any]]:
    """Map a stop's coordinates to the nearest coverage_cell within
    _CELL_LOOKUP_RADIUS_M.  Cells are hex polygons; we use ST_DWithin
    against the stop point and pick the closest centroid."""
    row = conn.execute(text("""
        SELECT cc.cell_id,
               COALESCE(cc.equity_score, 0)  AS equity_score,
               CASE
                 WHEN COALESCE(cc.equity_score, 0) >= 0.25 THEN 'very_high'
                 WHEN COALESCE(cc.equity_score, 0) >= 0.15 THEN 'high'
                 WHEN COALESCE(cc.equity_score, 0) >= 0.08 THEN 'medium'
                 ELSE 'low'
               END AS equity_tier
        FROM coverage_cells cc
        WHERE cc.geom IS NOT NULL
          AND ST_DWithin(
              cc.geom::geography,
              ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
              :radius_m
          )
        ORDER BY cc.geom <-> ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)
        LIMIT 1
    """), {
        "lat": stop_lat, "lng": stop_lon,
        "radius_m": _CELL_LOOKUP_RADIUS_M,
    }).mappings().first()
    return dict(row) if row else None


# ── Main entry point ─────────────────────────────────────────────────────────

def sample_corridor(
    conn: Connection,
    origin:      LatLng,
    destination: LatLng,
    n:           int = 30,
    *,
    rng_seed: Optional[int] = None,
) -> SampleCorridorResult:
    """Sample up to `n` single-agency OD pairs between the two clicks and
    aggregate fare statistics.

    Returns SampleCorridorResult with summary stats + per-cell equity
    breakdown + a `notice` string when the corridor isn't single-agency-
    reachable.  Empty / sparse corridors return n_sampled=0 with notice
    set so the UI can show a clear empty state.
    """
    rng = random.Random(rng_seed) if rng_seed is not None else random.Random()

    origin_stops = _nearest_stops(conn, origin,      _STOPS_PER_CLICK)
    dest_stops   = _nearest_stops(conn, destination, _STOPS_PER_CLICK)

    if not origin_stops or not dest_stops:
        return _empty_result("origin or destination has no stops within reach")

    # Group by agency on each side, then intersect the agency sets so we
    # only consider pairs reachable on a single network.
    o_by_agency: Dict[str, List[dict]] = {}
    for s in origin_stops:
        o_by_agency.setdefault(s["agency_id"], []).append(s)
    d_by_agency: Dict[str, List[dict]] = {}
    for s in dest_stops:
        d_by_agency.setdefault(s["agency_id"], []).append(s)

    shared = sorted(set(o_by_agency) & set(d_by_agency))
    if not shared:
        return _empty_result("no direct connection between regions")

    # Build candidate (origin_stop, dest_stop, agency) tuples, capped per
    # agency so one large agency doesn't dominate the sample.
    per_agency_cap = max(1, n // len(shared))
    candidates: List[Dict[str, Any]] = []
    for agency_id in shared:
        os = o_by_agency[agency_id]
        ds = d_by_agency[agency_id]
        # Cartesian product, then random sample within the agency's cap.
        pairs = [(o, d) for o in os for d in ds if o["stop_id"] != d["stop_id"]]
        rng.shuffle(pairs)
        for (o, d) in pairs[:per_agency_cap]:
            candidates.append({"agency_id": agency_id, "origin": o, "dest": d})

    rng.shuffle(candidates)
    candidates = candidates[:n]

    # Compute fare for each candidate.  Group by origin cell for the
    # equity breakdown.
    fares: List[float] = []
    per_cell: Dict[str, Dict[str, Any]] = {}
    agencies_seen: set[str] = set()

    for c in candidates:
        leg = Leg(
            agency_id=c["agency_id"],
            origin_stop_id=c["origin"]["stop_id"],
            destination_stop_id=c["dest"]["stop_id"],
        )
        result = calculate_fare(conn, [leg])
        if not result.legs or result.legs[0].fare is None:
            continue   # no_data — skip rather than coerce to 0

        fare = float(result.legs[0].fare)
        fares.append(fare)
        agencies_seen.add(c["agency_id"])

        cell = _cell_for_stop(conn, c["origin"]["stop_lat"], c["origin"]["stop_lon"])
        if cell is not None:
            bucket = per_cell.setdefault(cell["cell_id"], {
                "cell_id":      cell["cell_id"],
                "equity_score": float(cell["equity_score"]),
                "equity_tier":  cell["equity_tier"],
                "fares":        [],
            })
            bucket["fares"].append(fare)

    n_sampled = len(fares)
    if n_sampled < _MIN_PAIRS_FOR_SUMMARY:
        return _empty_result(
            "fewer than n pairs found",
            n_sampled=n_sampled,
            agencies=sorted(agencies_seen),
        )

    # Aggregate.
    sorted_fares = sorted(fares)
    median   = statistics.median(sorted_fares)
    p25, p75 = _quartiles(sorted_fares)
    max_fare = sorted_fares[-1]

    # Per equity tier.
    tier_buckets: Dict[str, List[float]] = {
        "very_high": [], "high": [], "medium": [], "low": [],
    }
    for cb in per_cell.values():
        tier_buckets[cb["equity_tier"]].extend(cb["fares"])
    by_tier = {
        tier: TierBreakdown(
            n=len(vals),
            median_fare=statistics.median(vals) if vals else None,
        )
        for tier, vals in tier_buckets.items()
    }

    # High-burden cells: median_fare × equity_score, descending.
    cell_summaries = []
    for cb in per_cell.values():
        if not cb["fares"]:
            continue
        cell_median = statistics.median(cb["fares"])
        cell_summaries.append(HighBurdenCell(
            cell_id=cb["cell_id"],
            equity_score=cb["equity_score"],
            median_fare=cell_median,
            burden=cell_median * cb["equity_score"],
        ))
    cell_summaries.sort(key=lambda r: r.burden, reverse=True)
    high_burden = cell_summaries[:10]

    notice = "single-agency only"

    return SampleCorridorResult(
        n_sampled=n_sampled,
        median_fare=median,
        p25_fare=p25,
        p75_fare=p75,
        max_fare=max_fare,
        agencies=sorted(agencies_seen),
        by_equity_tier=by_tier,
        high_burden_cells=high_burden,
        notice=notice,
    )


def _quartiles(sorted_fares: List[float]) -> tuple[Optional[float], Optional[float]]:
    """Compute p25 and p75 from a sorted list.  statistics.quantiles needs
    n >= 2; below that we return None for both."""
    if len(sorted_fares) < 2:
        return (None, None)
    qs = statistics.quantiles(sorted_fares, n=4, method="inclusive")
    return (qs[0], qs[2])   # q1=p25, q2=p50 (median), q3=p75


def _empty_result(
    notice: str,
    n_sampled: int = 0,
    agencies: Optional[List[str]] = None,
) -> SampleCorridorResult:
    """Build a zero-data response with a notice string."""
    return SampleCorridorResult(
        n_sampled=n_sampled,
        median_fare=None,
        p25_fare=None,
        p75_fare=None,
        max_fare=None,
        agencies=agencies or [],
        by_equity_tier={
            t: TierBreakdown(n=0, median_fare=None)
            for t in ("very_high", "high", "medium", "low")
        },
        high_burden_cells=[],
        notice=notice,
    )

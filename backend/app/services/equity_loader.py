"""
Populate coverage_cells equity columns from US Census ACS 5-year estimates.

Covers all 9 Bay Area counties. Spatial assignment uses approximate county
bounding-box polygons (ST_MakeEnvelope) so no TIGER geometry download is needed.
Cells outside all county boxes receive a neutral equity_score of 0.5.
"""
from __future__ import annotations

from typing import Optional

import certifi
import requests
from app.core.run_log import tracked_get
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db import get_engine

_CENSUS_API = "https://api.census.gov/data/2022/acs/acs5"

# (fips, display_name, min_lon, min_lat, max_lon, max_lat)
#
# Bounding boxes are trimmed at shared county boundaries to prevent overlap:
#   Alameda/Contra Costa split at lat 37.88 (East Bay Hills ridge)
#   SF west boundary is -122.52; Alameda extends to -122.36 (slightly wider) to capture
#   the West Oakland shoreline cells that lie east of SF
_COUNTIES = [
    ("06001", "Alameda",       -122.36, 37.45, -121.47, 37.88),  # Oakland→Fremont, south of Hills
    ("06013", "Contra Costa",  -122.38, 37.88, -121.55, 38.07),  # Richmond→Concord, north of Hills
    ("06075", "San Francisco", -122.52, 37.70, -122.35, 37.83),
    ("06081", "San Mateo",     -122.52, 37.11, -122.06, 37.71),
    ("06085", "Santa Clara",   -122.20, 36.89, -121.21, 37.48),
    ("06097", "Sonoma",        -123.53, 38.08, -122.35, 38.85),
    ("06055", "Napa",          -122.62, 38.10, -122.04, 38.86),
    ("06095", "Solano",        -122.39, 37.97, -121.54, 38.54),
    ("06041", "Marin",         -123.03, 37.85, -122.35, 38.20),
]

# ACS variables:
#   B17001_001E = total pop in poverty universe
#   B17001_002E = pop below poverty level
#   B08141_001E = total HH in vehicle-availability universe
#   B08141_002E = no-vehicle HHs
#   B01001_001E = total population
#   B19013_001E = median household income (past 12 months, dollars)
_VARIABLES = ["B17001_001E", "B17001_002E", "B08141_001E", "B08141_002E",
              "B01001_001E", "B19013_001E"]

# ACS uses large negative sentinels (e.g. -666666666) for tracts where
# the estimate is suppressed or unavailable.  Filter anything well below
# zero out of the aggregation.
_ACS_SUPPRESSED_THRESHOLD = -1000


def _fetch_census(county_fips: str) -> list[dict]:
    state  = county_fips[:2]
    county = county_fips[2:]
    params = {
        "get": ",".join(["NAME"] + _VARIABLES),
        "for": "tract:*",
        "in":  f"state:{state} county:{county}",
    }
    # As of ~2024 api.census.gov requires a key on every request.  Free
    # signup at https://api.census.gov/data/key_signup.html.  Without it
    # the API 302-redirects to a missing-key page (no JSON body).
    from app.core.config import get_settings
    key = get_settings().census_api_key
    if key:
        params["key"] = key
    try:
        resp = tracked_get(_CENSUS_API, params=params, timeout=30, verify=certifi.where())
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  [equity] Census fetch failed for {county_fips}: {e}")
        return []
    if len(data) < 2:
        return []
    headers = data[0]
    return [dict(zip(headers, row)) for row in data[1:]]


def _aggregate_county(tracts: list[dict]) -> dict:
    """Sum Census tract rows to county-level metrics + median household income.

    median_household_income is computed as the median across tract-level
    medians (B19013_001E). Tract medians where ACS suppressed the
    estimate (sentinel value far below zero) are excluded. A
    population-weighted mean would be more precise but requires joining
    against B19013 with B01001 at the tract level — deferred refinement.
    """
    total_pop = poverty_sum = total_hh = no_veh_sum = 0
    tract_incomes: list[int] = []
    for t in tracts:
        try:
            total_pop   += max(0, int(t.get("B17001_001E") or 0))
            poverty_sum += max(0, int(t.get("B17001_002E") or 0))
            total_hh    += max(0, int(t.get("B08141_001E") or 0))
            no_veh_sum  += max(0, int(t.get("B08141_002E") or 0))
            inc = int(t.get("B19013_001E") or 0)
            if inc > _ACS_SUPPRESSED_THRESHOLD and inc > 0:
                tract_incomes.append(inc)
        except (ValueError, TypeError):
            continue

    poverty_pct  = poverty_sum / total_pop if total_pop > 0 else 0.0
    no_veh_pct   = no_veh_sum  / total_hh  if total_hh  > 0 else 0.0
    equity_score = (poverty_pct + no_veh_pct) / 2.0

    median_income = 0
    if tract_incomes:
        import statistics
        median_income = int(statistics.median(tract_incomes))

    return {
        "total_pop":                 total_pop,
        "poverty_pct":                poverty_pct,
        "no_veh_pct":                 no_veh_pct,
        "equity_score":               equity_score,
        "median_household_income":    median_income,
    }


def populate_equity_columns(conn: Optional[Connection] = None) -> None:
    """
    Update coverage_cells with per-county Census-derived equity metrics.
    Each cell's centroid is matched to the first county bounding box that contains it.
    Cells outside all county boxes default to equity_score=0.5.
    """
    if conn is None:
        with get_engine().begin() as _conn:
            populate_equity_columns(_conn)
        return

    # ── Step 1: fetch and aggregate Census data per county ───────────────────
    county_data: list[tuple] = []  # (fips, name, min_lon, min_lat, max_lon, max_lat, metrics)
    for fips, name, min_lon, min_lat, max_lon, max_lat in _COUNTIES:
        tracts  = _fetch_census(fips)
        metrics = _aggregate_county(tracts)
        county_data.append((fips, name, min_lon, min_lat, max_lon, max_lat, metrics))
        if tracts:
            m = metrics
            print(
                f"  [equity] {name}: pop={m['total_pop']:,} "
                f"poverty={m['poverty_pct']:.1%} no_veh={m['no_veh_pct']:.1%} "
                f"score={m['equity_score']:.3f} "
                f"median_income=${m['median_household_income']:,}"
            )

    fetched = [cd for cd in county_data if cd[6]["total_pop"] > 0]
    if not fetched:
        print("  [equity] No Census data returned — setting default equity_score=0.5")
        conn.execute(text("UPDATE coverage_cells SET equity_score = 0.5"))
        return

    # ── Step 2: mark all cells unassigned (NULL = not yet claimed) ──────────
    conn.execute(text("UPDATE coverage_cells SET equity_score = NULL"))

    # ── Step 3: per-county spatial update — smallest bbox first ─────────────
    # Process smallest counties first. Each UPDATE only touches cells that are
    # still NULL (unassigned), so a small county claiming its cells prevents
    # a larger overlapping county bbox from overwriting them.
    def _bbox_area(entry: tuple) -> float:
        _, _, min_lon, min_lat, max_lon, max_lat, _ = entry
        return abs(max_lon - min_lon) * abs(max_lat - min_lat)

    for fips, name, min_lon, min_lat, max_lon, max_lat, m in sorted(county_data, key=_bbox_area):
        if m["total_pop"] == 0:
            continue

        # Count unassigned cells falling inside this county bbox
        cnt_row = conn.execute(text("""
            SELECT COUNT(*) FROM coverage_cells
            WHERE equity_score IS NULL
              AND ST_Within(
                    ST_Centroid(geom),
                    ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)
                  )
        """), {"min_lon": min_lon, "min_lat": min_lat,
               "max_lon": max_lon, "max_lat": max_lat}).fetchone()

        cell_count   = int(cnt_row[0]) if cnt_row else 0
        per_cell_pop = int(m["total_pop"] / cell_count) if cell_count > 0 else 0

        conn.execute(text("""
            UPDATE coverage_cells SET
                equity_score             = :equity_score,
                population               = :per_cell_pop,
                low_income_population    = ROUND(:per_cell_pop * :poverty_pct)::int,
                no_car_households        = ROUND(:per_cell_pop * :no_veh_pct)::int,
                median_household_income  = NULLIF(:median_income, 0)
            WHERE equity_score IS NULL
              AND ST_Within(
                    ST_Centroid(geom),
                    ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)
                  )
        """), {
            "equity_score":   m["equity_score"],
            "per_cell_pop":   per_cell_pop,
            "poverty_pct":    m["poverty_pct"],
            "no_veh_pct":     m["no_veh_pct"],
            "median_income":  m["median_household_income"],
            "min_lon":        min_lon,
            "min_lat":        min_lat,
            "max_lon":        max_lon,
            "max_lat":        max_lat,
        })

        print(f"  [equity] {name}: {cell_count} cells → equity_score={m['equity_score']:.3f}")

    # ── Step 4: neutral default for any cells outside all county bboxes ──────
    defaulted = conn.execute(text(
        "UPDATE coverage_cells SET equity_score = 0.5 WHERE equity_score IS NULL"
    )).rowcount
    if defaulted:
        print(f"  [equity] {defaulted} cells outside all county bboxes → default 0.5")

    print(f"  [equity] Done. {len(fetched)}/9 counties populated.")

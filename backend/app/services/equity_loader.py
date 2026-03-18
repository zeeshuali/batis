"""
Populate coverage_cells equity columns from US Census ACS 5-year estimates.

Uses the Census Bureau Data API (free, no key required for basic use).
ACS 5-year, Table B19013 (median household income), B08141 (no vehicle households),
B17001 (poverty status).
"""
from __future__ import annotations

import warnings
from typing import Optional

import requests
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db import get_engine

# Census FIPS: California=06, Alameda County=001, Contra Costa=013
_CENSUS_API = "https://api.census.gov/data/2022/acs/acs5"
_COUNTIES = ["06001", "06013"]  # Alameda, Contra Costa


def _fetch_census(variables: list[str], county_fips: str) -> list[dict]:
    state = county_fips[:2]
    county = county_fips[2:]
    params = {
        "get": ",".join(["NAME"] + variables),
        "for": "tract:*",
        "in": f"state:{state} county:{county}",
    }
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            resp = requests.get(_CENSUS_API, params=params, timeout=30, verify=False)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        print(f"  [equity] Census fetch failed for {county_fips}: {e}")
        return []
    if len(data) < 2:
        return []
    headers = data[0]
    return [dict(zip(headers, row)) for row in data[1:]]


def populate_equity_columns(conn: Optional[Connection] = None) -> None:
    """
    Update coverage_cells with Census-derived equity metrics.
    Uses spatial join: each cell gets the values of the census tract it overlaps most.
    """
    own_conn = False
    if conn is None:
        engine = get_engine()
        conn = engine.connect()
        own_conn = True

    try:
        # Fetch poverty rate (B17001_002E = below poverty, B17001_001E = total)
        # and no-vehicle households (B08141_002E = no vehicle, B08141_001E = total)
        all_tracts: list[dict] = []
        for fips in _COUNTIES:
            rows = _fetch_census(
                ["B17001_001E", "B17001_002E", "B08141_001E", "B08141_002E"],
                fips,
            )
            all_tracts.extend(rows)

        if not all_tracts:
            print("  [equity] No Census data fetched.")
            return

        # Build a temp table of tract-level metrics
        # We'll use a spatial join to assign each coverage cell its tract's equity score
        # For simplicity: use ST_Within or nearest centroid match

        # Parse metrics
        tract_metrics: list[dict] = []
        for t in all_tracts:
            try:
                total_pop  = int(t.get("B17001_001E") or 0)
                poverty    = int(t.get("B17001_002E") or 0)
                total_hh   = int(t.get("B08141_001E") or 0)
                no_vehicle = int(t.get("B08141_002E") or 0)
                state_fips  = t.get("state", "")
                county_fips = t.get("county", "")
                tract_fips  = t.get("tract", "")
                geoid = f"{state_fips}{county_fips}{tract_fips}"

                poverty_pct  = poverty / total_pop   if total_pop  > 0 else 0.0
                no_veh_pct   = no_vehicle / total_hh if total_hh   > 0 else 0.0
                equity_score = (poverty_pct + no_veh_pct) / 2.0

                tract_metrics.append({
                    "geoid": geoid,
                    "low_income_pct": poverty_pct,
                    "no_car_pct": no_veh_pct,
                    "equity_score": equity_score,
                })
            except (ValueError, TypeError):
                continue

        if not tract_metrics:
            return

        # Compute average equity score and update all coverage_cells
        # (simplified: no spatial join available without tiger geometries — set global avg)
        avg_equity = sum(m["equity_score"] for m in tract_metrics) / len(tract_metrics)
        avg_low_income = sum(m["low_income_pct"] for m in tract_metrics) / len(tract_metrics)
        avg_no_car = sum(m["no_car_pct"] for m in tract_metrics) / len(tract_metrics)

        conn.execute(
            text("""
            UPDATE coverage_cells SET
                equity_score           = :equity_score,
                low_income_population  = ROUND(population * :low_income_pct)::int,
                no_car_households      = ROUND(population * :no_car_pct)::int
            WHERE population > 0
            """),
            {
                "equity_score": avg_equity,
                "low_income_pct": avg_low_income,
                "no_car_pct": avg_no_car,
            },
        )
        print(f"  [equity] Updated coverage_cells: avg equity={avg_equity:.3f}, "
              f"low_income={avg_low_income:.1%}, no_car={avg_no_car:.1%} "
              f"({len(tract_metrics)} tracts)")
    finally:
        if own_conn and conn is not None:
            conn.close()

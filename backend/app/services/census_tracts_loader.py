"""Census TIGERweb tract geometry loader for the 9-county Bay Area.

See docs/superpowers/specs/2026-05-13-sprint-5c-design.md.

The Census Bureau's TIGERweb REST service serves authoritative tract
polygons as GeoJSON, sidestepping the need for geopandas / pyshp.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import certifi
import requests
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.config import get_settings

logger = logging.getLogger(__name__)


# 9-county Bay Area FIPS — county code only (state code 06 is California).
# Matches _COUNTIES in equity_loader.py.
_COUNTY_FIPS = [
    ("001", "Alameda"),
    ("013", "Contra Costa"),
    ("041", "Marin"),
    ("055", "Napa"),
    ("075", "San Francisco"),
    ("081", "San Mateo"),
    ("085", "Santa Clara"),
    ("095", "Solano"),
    ("097", "Sonoma"),
]


def _fetch_county(county_fips: str) -> list[dict[str, Any]]:
    """Fetch tract GeoJSON features for one Bay Area county."""
    s = get_settings()
    resp = requests.get(
        s.tigerweb_base_url,
        params={
            "where": f"STATE='06' AND COUNTY='{county_fips}'",
            "outFields": "GEOID,STATE,COUNTY,TRACT",
            "outSR": "4326",
            "f": "geojson",
        },
        timeout=60,
        verify=certifi.where(),
    )
    resp.raise_for_status()
    data = resp.json()
    return list(data.get("features", []))


def load_bay_area_tracts(conn: Connection) -> int:
    """Fetch and upsert Bay Area tract geometries.

    Idempotent: ON CONFLICT (tract_geoid) DO UPDATE.  Promotes Polygon
    geometry to MultiPolygon via ST_Multi for column-type compatibility.

    Returns rowcount written across all 9 counties.
    """
    total = 0
    for county_fips, county_name in _COUNTY_FIPS:
        try:
            features = _fetch_county(county_fips)
        except Exception as e:  # noqa: BLE001
            logger.warning("[tracts] %s (%s) fetch failed: %s",
                           county_name, county_fips, e)
            continue

        for feat in features:
            props = feat.get("properties") or {}
            geoid = props.get("GEOID")
            geom = feat.get("geometry")
            if not geoid or not geom:
                continue
            conn.execute(text("""
                INSERT INTO census_tracts (tract_geoid, county_fips, geom, computed_at)
                VALUES (
                    :geoid, :county,
                    ST_Multi(ST_GeomFromGeoJSON(:geom_json)),
                    now()
                )
                ON CONFLICT (tract_geoid) DO UPDATE
                  SET county_fips = EXCLUDED.county_fips,
                      geom        = EXCLUDED.geom,
                      computed_at = EXCLUDED.computed_at
            """), {"geoid": geoid, "county": county_fips,
                   "geom_json": json.dumps(geom)})
            total += 1
        logger.info("[tracts] %s (%s): %d features", county_name,
                    county_fips, len(features))
    return total

"""ACS B18105 (Sex by Age by Ambulatory Difficulty) loader for the
9-county Bay Area.  Sums ambulatory-difficulty bins across age and
sex to produce one ambulatory_pop value per tract.
"""
from __future__ import annotations

import logging

import certifi
import requests
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.config import get_settings


logger = logging.getLogger(__name__)


_COUNTY_FIPS = [
    "001", "013", "041", "055", "075", "081", "085", "095", "097",
]

# "With ambulatory difficulty" subtotal cells across age × sex bins.
# Source: ACS B18105 table.
_AMBULATORY_BINS = [
    "B18105_004E", "B18105_007E", "B18105_010E",
    "B18105_013E", "B18105_016E", "B18105_019E",
    "B18105_023E", "B18105_026E", "B18105_029E",
    "B18105_032E", "B18105_035E", "B18105_038E",
]
_TOTAL_POP = "B18105_001E"


def _safe_int(s: str) -> int:
    """Cast ACS string to int, treating negative sentinels as 0."""
    try:
        v = int(s)
    except (TypeError, ValueError):
        return 0
    return v if v >= 0 else 0


def _fetch_county_tracts(county_fips: str) -> list[list[str]]:
    s = get_settings()
    var_list = ",".join([_TOTAL_POP] + _AMBULATORY_BINS)
    url = (
        f"{s.census_acs5_base_url}"
        f"?get={var_list}"
        f"&for=tract:*"
        f"&in=state:06+county:{county_fips}"
        f"&key={s.census_api_key}"
    )
    resp = requests.get(url, timeout=60, verify=certifi.where())
    resp.raise_for_status()
    return resp.json()


def load_b18105(conn: Connection) -> int:
    """Fetch B18105 for every Bay Area tract, sum ambulatory-difficulty
    bins per tract, upsert into census_ambulatory.  Returns rowcount.
    """
    s = get_settings()
    if not s.census_api_key:
        logger.warning("[ambulatory] CENSUS_API_KEY missing; skipping load")
        return 0

    total_rows = 0
    for county in _COUNTY_FIPS:
        try:
            data = _fetch_county_tracts(county)
        except Exception as e:  # noqa: BLE001
            logger.warning("[ambulatory] county %s fetch failed: %s",
                           county, e)
            continue

        if not data or len(data) < 2:
            continue

        header = data[0]
        idx_total = header.index(_TOTAL_POP)
        idx_amb   = [header.index(b) for b in _AMBULATORY_BINS]
        idx_state = header.index("state")
        idx_cnty  = header.index("county")
        idx_tract = header.index("tract")

        for row in data[1:]:
            geoid = f"{row[idx_state]}{row[idx_cnty]}{row[idx_tract]}"
            total = _safe_int(row[idx_total])
            amb   = sum(_safe_int(row[i]) for i in idx_amb)
            conn.execute(text("""
                INSERT INTO census_ambulatory
                  (tract_geoid, ambulatory_pop, total_pop, computed_at)
                VALUES (:g, :a, :t, now())
                ON CONFLICT (tract_geoid) DO UPDATE
                  SET ambulatory_pop = EXCLUDED.ambulatory_pop,
                      total_pop      = EXCLUDED.total_pop,
                      computed_at    = EXCLUDED.computed_at
            """), {"g": geoid, "a": amb, "t": total})
            total_rows += 1
        logger.info("[ambulatory] county %s: %d tracts",
                    county, len(data) - 1)
    return total_rows

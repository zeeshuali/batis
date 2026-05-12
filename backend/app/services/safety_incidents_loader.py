from __future__ import annotations

import certifi
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db import get_engine

logger = logging.getLogger(__name__)

# Oakland Crime Watch — Socrata open dataset, no auth required
# https://data.oaklandca.gov/Public-Safety/Oakland-Crime-Watch-Data/ppgh-7dqv
OAKLAND_CRIME_URL = "https://data.oaklandca.gov/resource/ppgh-7dqv.json"

# Oakland Traffic Collision Data
# https://data.oaklandca.gov/Transportation/Oakland-Traffic-Collision-Data/ym6k-rx7a
OAKLAND_COLLISION_URL = "https://data.oaklandca.gov/resource/ym6k-rx7a.json"

# Berkeley Police Department crime data
# https://data.cityofberkeley.info/Public-Safety/Berkeley-PD-UCR-Annual-Part-I-Crimes/s24d-wsnp
BERKELEY_CRIME_URL = "https://data.cityofberkeley.info/resource/s24d-wsnp.json"

_PAGE_SIZE = 1000
_MAX_PAGES = 50


def _fetch_socrata_all(url: str, where: str = "") -> list[dict]:
    """Paginate through a Socrata endpoint, collecting up to _MAX_PAGES * _PAGE_SIZE rows."""
    all_rows: list[dict] = []
    offset = 0
    for page in range(_MAX_PAGES):
        logger.info("Fetching %s page %d, offset %d", url, page + 1, offset)
        params: dict = {"$limit": _PAGE_SIZE, "$offset": offset, "$order": ":id"}
        if where:
            params["$where"] = where
        resp = requests.get(url, params=params, timeout=30, verify=certifi.where())
        resp.raise_for_status()
        page_rows: list[dict] = resp.json()
        all_rows.extend(page_rows)
        if len(page_rows) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return all_rows


def _extract_coords(row: dict) -> tuple[float, float] | None:
    """Try common Socrata location field patterns to extract (lat, lon)."""
    # Pattern 1: GeoJSON-style {"coordinates": [lon, lat]}
    for key in ("location_1", "location", "geolocation"):
        loc = row.get(key)
        if isinstance(loc, dict):
            coords = loc.get("coordinates")
            if coords and len(coords) == 2:
                return float(coords[1]), float(coords[0])

    # Pattern 2: flat lat / lon fields
    for lat_key, lon_key in [("latitude", "longitude"), ("lat", "lon"), ("lat", "long_"), ("y", "x")]:
        if row.get(lat_key) and row.get(lon_key):
            try:
                return float(row[lat_key]), float(row[lon_key])
            except (ValueError, TypeError):
                pass

    return None


def _parse_ts(row: dict, *keys: str) -> datetime | None:
    for key in keys:
        val = row.get(key)
        if val:
            try:
                return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
            except ValueError:
                pass
    return None


def _load_crime_incidents(conn: Connection, days_back: int) -> int:
    since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%S")
    rows = _fetch_socrata_all(OAKLAND_CRIME_URL, where=f"datetime > '{since}'")
    if not rows:
        return 0

    incident_rows = []
    for r in rows:
        coords = _extract_coords(r)
        if coords is None:
            continue
        lat, lon = coords
        incident_rows.append({
            "source": "oakland_crime_watch",
            "incident_type": "crime",
            "occurred_at": _parse_ts(r, "datetime", "date"),
            "severity": 1,
            "lat": lat,
            "lon": lon,
            "properties": json.dumps({
                "description": r.get("description", ""),
                "crimetype": r.get("crimetype", ""),
            }),
        })

    if not incident_rows:
        return 0

    _bulk_insert_incidents(conn, incident_rows)
    return len(incident_rows)


def _load_collision_incidents(conn: Connection) -> int:
    rows = _fetch_socrata_all(OAKLAND_COLLISION_URL)
    if not rows:
        return 0

    incident_rows = []
    for r in rows:
        coords = _extract_coords(r)
        if coords is None:
            continue
        lat, lon = coords

        severity = 1
        sev_str = str(r.get("collision_severity", r.get("severity", ""))).lower()
        if "fatal" in sev_str or "killed" in sev_str:
            severity = 4
        elif "severe" in sev_str or "serious" in sev_str:
            severity = 3
        elif "injur" in sev_str:
            severity = 2

        incident_rows.append({
            "source": "oakland_collisions",
            "incident_type": "collision",
            "occurred_at": _parse_ts(r, "accident_date", "date", "datetime", "collision_date"),
            "severity": severity,
            "lat": lat,
            "lon": lon,
            "properties": json.dumps({k: v for k, v in r.items() if k not in ("location", "location_1", "geolocation")}),
        })

    if not incident_rows:
        return 0

    _bulk_insert_incidents(conn, incident_rows)
    return len(incident_rows)


def _load_berkeley_crime_incidents(conn: Connection, days_back: int) -> int:
    since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%S")
    rows = _fetch_socrata_all(BERKELEY_CRIME_URL, where=f"eventdt > '{since}'")
    if not rows:
        return 0

    incident_rows = []
    for r in rows:
        coords = _extract_coords(r)
        if coords is None:
            continue
        lat, lon = coords
        incident_rows.append({
            "source": "berkeley_crime",
            "incident_type": "crime",
            "occurred_at": _parse_ts(r, "eventdt", "datetime", "date"),
            "severity": 1,
            "lat": lat,
            "lon": lon,
            "properties": json.dumps({
                "description": r.get("offense", r.get("description", "")),
                "crimetype": r.get("offense", ""),
            }),
        })

    if not incident_rows:
        return 0

    _bulk_insert_incidents(conn, incident_rows)
    return len(incident_rows)


def _bulk_insert_incidents(conn: Connection, rows: list[dict]) -> None:
    conn.execute(
        text(
            """
            INSERT INTO safety_incidents_raw (
              source, incident_type, occurred_at, severity, geom, properties
            ) VALUES (
              :source,
              :incident_type,
              :occurred_at,
              :severity,
              ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
              CAST(:properties AS jsonb)
            )
            """
        ),
        rows,
    )


def _run_load(conn: Connection, days_back: int) -> None:
    """Execute DELETE + INSERT within the caller-provided transaction."""
    conn.execute(
        text(
            "DELETE FROM safety_incidents_raw "
            "WHERE source IN ('oakland_crime_watch', 'oakland_collisions', 'berkeley_crime')"
        )
    )

    crime_count = 0
    try:
        crime_count = _load_crime_incidents(conn, days_back=days_back)
    except Exception as exc:
        logger.error("Oakland crime fetch failed (skipping): %s", exc)

    collision_count = 0
    try:
        collision_count = _load_collision_incidents(conn)
    except Exception as exc:
        logger.error("Oakland collision fetch failed (skipping): %s", exc)

    berkeley_count = 0
    try:
        berkeley_count = _load_berkeley_crime_incidents(conn, days_back=days_back)
    except Exception as exc:
        logger.error("Berkeley crime fetch failed (skipping): %s", exc)

    logger.info(
        "Loaded %d crime incidents, %d collision incidents, %d Berkeley crime incidents.",
        crime_count,
        collision_count,
        berkeley_count,
    )


def load_safety_incidents(
    days_back: int = 180,
    conn: Optional[Connection] = None,
) -> None:
    """
    Load crime and collision data from Oakland's and Berkeley's open data portals
    into safety_incidents_raw, replacing previously loaded records from the same sources.

    Data sources (public Socrata APIs, no key required):
    - Oakland Crime Watch (ppgh-7dqv)
    - Oakland Traffic Collision Data (ym6k-rx7a)
    - Berkeley PD crime data (s24d-wsnp)
    """
    if conn is None:
        with get_engine().begin() as _conn:
            _run_load(_conn, days_back)
    else:
        _run_load(conn, days_back)

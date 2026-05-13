"""GTFS Pathways loader for monitored Bay Area agencies.

See docs/superpowers/specs/2026-05-13-sprint-5c-design.md.

Most agencies don't publish pathways.txt — the loader silently skips
those.  Idempotent per agency_id.
"""
from __future__ import annotations

import csv
import io
import logging
import zipfile
from typing import Optional

import certifi
import requests
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.config import get_settings


logger = logging.getLogger(__name__)


def _maybe_int(s: str | None) -> Optional[int]:
    if s is None or s == "":
        return None
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _maybe_float(s: str | None) -> Optional[float]:
    if s is None or s == "":
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _maybe_bool(s: str | None) -> Optional[bool]:
    if s is None or s == "":
        return None
    return s.strip() == "1"


def load_pathways_from_zip_bytes(
    conn: Connection, agency_id: str, zip_bytes: bytes
) -> int:
    """Parse pathways.txt and levels.txt out of a GTFS zip byte blob,
    upsert into gtfs_pathways and gtfs_levels.  Returns combined row
    count (pathways + levels).  Idempotent: deletes existing rows for
    agency_id before re-insert.
    """
    pathways_rows = 0
    levels_rows = 0

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        namelist = zf.namelist()

        if "pathways.txt" in namelist:
            # Idempotency: only delete when we have fresh data to replace it.
            conn.execute(text("DELETE FROM gtfs_pathways WHERE agency_id = :a"),
                         {"a": agency_id})
            with zf.open("pathways.txt") as f:
                reader = csv.DictReader(
                    io.TextIOWrapper(f, encoding="utf-8-sig")
                )
                for row in reader:
                    conn.execute(text("""
                        INSERT INTO gtfs_pathways
                          (agency_id, pathway_id, from_stop_id, to_stop_id,
                           pathway_mode, is_bidirectional, length_m,
                           traversal_time, stair_count, max_slope)
                        VALUES (:a, :pid, :f, :t, :m, :b, :l, :tt, :sc, :ms)
                    """), {
                        "a":   agency_id,
                        "pid": row.get("pathway_id"),
                        "f":   row.get("from_stop_id"),
                        "t":   row.get("to_stop_id"),
                        "m":   _maybe_int(row.get("pathway_mode")),
                        "b":   _maybe_bool(row.get("is_bidirectional")),
                        "l":   _maybe_float(row.get("length")),
                        "tt":  _maybe_int(row.get("traversal_time")),
                        "sc":  _maybe_int(row.get("stair_count")),
                        "ms":  _maybe_float(row.get("max_slope")),
                    })
                    pathways_rows += 1

        if "levels.txt" in namelist:
            # Idempotency: only delete when we have fresh data to replace it.
            conn.execute(text("DELETE FROM gtfs_levels WHERE agency_id = :a"),
                         {"a": agency_id})
            with zf.open("levels.txt") as f:
                reader = csv.DictReader(
                    io.TextIOWrapper(f, encoding="utf-8-sig")
                )
                for row in reader:
                    conn.execute(text("""
                        INSERT INTO gtfs_levels
                          (agency_id, level_id, level_index, level_name)
                        VALUES (:a, :lid, :idx, :name)
                    """), {
                        "a":    agency_id,
                        "lid":  row.get("level_id"),
                        "idx":  _maybe_float(row.get("level_index")),
                        "name": row.get("level_name"),
                    })
                    levels_rows += 1

    if pathways_rows or levels_rows:
        logger.info("[pathways] %s: %d pathways + %d levels",
                    agency_id, pathways_rows, levels_rows)
    return pathways_rows + levels_rows


def load_all_pathways(conn: Connection) -> dict[str, int]:
    """Iterate `SELECT agency_id FROM agencies WHERE monitored = true`
    (or fall back to settings.five11_agencies if the agencies table
    is empty / missing) and load pathways for each.

    Returns {agency_id: rowcount} for agencies that contributed any
    rows; agencies whose GTFS zip lacks pathways.txt are not included
    in the result map.
    """
    s = get_settings()
    base = f"{s.five11_base_url}/transit/datafeeds"

    try:
        rows = conn.execute(text(
            "SELECT agency_id FROM agencies WHERE monitored IS TRUE "
            "ORDER BY agency_id"
        )).all()
        agencies = [r[0] for r in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[pathways] agencies table unavailable (%s); "
                       "falling back to settings.five11_agencies / hardcoded list", exc)
        agencies = list(getattr(s, "five11_agencies", None) or ["AC", "BA", "SF"])

    if not agencies:
        logger.warning("[pathways] no agencies to load — skipping")
        return {}

    result: dict[str, int] = {}
    for agency_id in agencies:
        try:
            url = f"{base}?operator_id={agency_id}&api_key={s.five11_api_key}"
            resp = requests.get(url, timeout=120, verify=certifi.where())
            resp.raise_for_status()
            n = load_pathways_from_zip_bytes(conn, agency_id, resp.content)
            if n > 0:
                result[agency_id] = n
        except Exception as e:  # noqa: BLE001
            logger.warning("[pathways] %s download/parse failed: %s",
                           agency_id, e)
    return result

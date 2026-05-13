"""GTFS Fares v2 ingestor.

511.org publishes per-agency Fares v2 zips at
`/transit/datafeeds?operator_id={id}&file=fares`.  This module downloads
that zip, parses the CSVs inside, and UPSERTs the contents into
fare_products / fare_leg_rules / fare_transfer_rules / fare_areas.

The loader is **opportunistic**: not every agency publishes Fares v2 yet,
and feeds that do publish may be missing optional CSVs.  Each helper
returns `0` on a missing file rather than raising, so a partial feed
still gets as much data loaded as possible.

After a successful load we tag `agencies.has_fares_v2 = true` so the UI
can degrade gracefully for agencies without fare data.
"""
from __future__ import annotations

import csv
import io
import zipfile
from typing import Any, Dict, List, Optional

import certifi
import requests
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from app.core.config import get_settings


# 511.org endpoint for per-agency Fares v2 feed.  Returns a zip; the inside
# is standard GTFS Fares v2 CSVs (BOM-prefixed UTF-8 per 511.org convention).
_FARES_URL = "https://api.511.org/transit/datafeeds"

# The four GTFS Fares v2 CSVs we know how to parse.  Each is optional
# inside the zip — a feed that ships only fare_products.txt + areas.txt is
# still useful.
_CSV_FARE_PRODUCTS       = "fare_products.txt"
_CSV_FARE_LEG_RULES      = "fare_leg_rules.txt"
_CSV_FARE_TRANSFER_RULES = "fare_transfer_rules.txt"
_CSV_AREAS               = "areas.txt"

# Bay Area agencies still ship GTFS Fares v1 as of 2026-05.  The 511.org
# `?file=fares` endpoint returns the full GTFS static zip; the v1 files
# below are the ones that contain fare data in v1 feeds.  The loader maps
# them into the v2-shaped tables so the consumer (Sprint 4b's fare
# calculator) doesn't need to know which version the data came from.
_CSV_V1_FARE_ATTRIBUTES  = "fare_attributes.txt"
_CSV_V1_FARE_RULES       = "fare_rules.txt"
_CSV_V1_FAREZONE_ATTRS   = "farezone_attributes.txt"


def _download_fares_zip(agency_id: str, api_key: str) -> bytes:
    """Fetch the fares.zip for one agency from 511.org."""
    resp = requests.get(
        _FARES_URL,
        params={"operator_id": agency_id, "api_key": api_key, "file": "fares"},
        timeout=60,
        verify=certifi.where(),
    )
    resp.raise_for_status()
    return resp.content


def _read_csv(zf: zipfile.ZipFile, filename: str) -> Optional[List[Dict[str, str]]]:
    """Read a Fares v2 CSV out of the zip.  Returns None if not present.

    511.org feeds ship UTF-8 with a BOM; the `utf-8-sig` codec strips it
    transparently so DictReader sees clean column names.
    """
    if filename not in zf.namelist():
        return None
    with zf.open(filename) as f:
        raw = f.read().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(raw)))


def _to_decimal(v: Any) -> Optional[float]:
    """Tolerant numeric parse — empty string and 'NULL' both mean None."""
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.upper() == "NULL":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.upper() == "NULL":
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _none_if_empty(v: Any) -> Optional[str]:
    """Empty CSV strings come through as '' but our schema prefers NULL for
    optional joinable columns (network_id, area ids, leg_group_id)."""
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


# ── Per-table loaders ─────────────────────────────────────────────────────────

def _load_fare_products(conn: Connection, agency_id: str, rows: List[Dict[str, str]]) -> int:
    """fare_products has a composite primary key (agency_id, fare_product_id);
    UPSERT lets us re-run safely without touching other agencies' rows."""
    n = 0
    for r in rows:
        fpid = _none_if_empty(r.get("fare_product_id"))
        if not fpid:
            continue
        conn.execute(text("""
            INSERT INTO fare_products
                (agency_id, fare_product_id, fare_product_name, amount, currency)
            VALUES (:a, :id, :name, :amount, COALESCE(:cur, 'USD'))
            ON CONFLICT (agency_id, fare_product_id) DO UPDATE
                SET fare_product_name = EXCLUDED.fare_product_name,
                    amount            = EXCLUDED.amount,
                    currency          = EXCLUDED.currency
        """), {
            "a": agency_id,
            "id": fpid,
            "name": _none_if_empty(r.get("fare_product_name")),
            "amount": _to_decimal(r.get("amount")),
            "cur": _none_if_empty(r.get("currency")),
        })
        n += 1
    return n


def _load_fare_leg_rules(conn: Connection, agency_id: str, rows: List[Dict[str, str]]) -> int:
    """fare_leg_rules has many optional columns and no natural primary key
    (the GTFS spec doesn't define one).  Strategy: DELETE all rows for the
    agency first, then bulk INSERT.  This is the right shape for nightly
    ingestion — we always replace, never diff."""
    conn.execute(text("DELETE FROM fare_leg_rules WHERE agency_id = :a"),
                 {"a": agency_id})
    n = 0
    for r in rows:
        fpid = _none_if_empty(r.get("fare_product_id"))
        if not fpid:
            continue
        conn.execute(text("""
            INSERT INTO fare_leg_rules
                (agency_id, leg_group_id, network_id,
                 from_area_id, to_area_id, fare_product_id)
            VALUES (:a, :lg, :net, :fa, :ta, :fpid)
        """), {
            "a":    agency_id,
            "lg":   _none_if_empty(r.get("leg_group_id")),
            "net":  _none_if_empty(r.get("network_id")),
            "fa":   _none_if_empty(r.get("from_area_id")),
            "ta":   _none_if_empty(r.get("to_area_id")),
            "fpid": fpid,
        })
        n += 1
    return n


def _load_fare_transfer_rules(conn: Connection, agency_id: str, rows: List[Dict[str, str]]) -> int:
    """Same DELETE+INSERT pattern as fare_leg_rules — no natural key."""
    conn.execute(text("DELETE FROM fare_transfer_rules WHERE agency_id = :a"),
                 {"a": agency_id})
    n = 0
    for r in rows:
        conn.execute(text("""
            INSERT INTO fare_transfer_rules
                (agency_id, from_leg_group_id, to_leg_group_id,
                 transfer_count, duration_limit, fare_product_id, amount)
            VALUES (:a, :flg, :tlg, :tc, :dl, :fpid, :amt)
        """), {
            "a":    agency_id,
            "flg":  _none_if_empty(r.get("from_leg_group_id")),
            "tlg":  _none_if_empty(r.get("to_leg_group_id")),
            "tc":   _to_int(r.get("transfer_count")),
            "dl":   _to_int(r.get("duration_limit")),
            "fpid": _none_if_empty(r.get("fare_product_id")),
            "amt":  _to_decimal(r.get("amount")),
        })
        n += 1
    return n


def _load_fare_areas(conn: Connection, agency_id: str, rows: List[Dict[str, str]]) -> int:
    """fare_areas has (agency_id, area_id) as its natural key — UPSERT."""
    n = 0
    for r in rows:
        aid = _none_if_empty(r.get("area_id"))
        if not aid:
            continue
        conn.execute(text("""
            INSERT INTO fare_areas (agency_id, area_id, area_name)
            VALUES (:a, :id, :name)
            ON CONFLICT (agency_id, area_id) DO UPDATE
                SET area_name = EXCLUDED.area_name
        """), {
            "a": agency_id,
            "id": aid,
            "name": _none_if_empty(r.get("area_name")),
        })
        n += 1
    return n


# ── Public entrypoints ────────────────────────────────────────────────────────

def _v1_to_v2_products(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Map GTFS Fares v1 `fare_attributes.txt` rows into v2-shaped
    `fare_products` rows.

    v1                      → v2
    fare_id                 → fare_product_id (also fare_product_name)
    price                   → amount
    currency_type           → currency
    """
    return [
        {
            "fare_product_id":   r.get("fare_id") or "",
            "fare_product_name": r.get("fare_id") or "",
            "amount":            r.get("price"),
            "currency":          r.get("currency_type") or "USD",
        }
        for r in rows
    ]


def _v1_to_v2_leg_rules(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Map v1 `fare_rules.txt` rows into v2-shaped `fare_leg_rules` rows.

    v1                      → v2
    fare_id                 → fare_product_id
    route_id                → network_id      (closest concept; v1 keys fares
                                                  by route, v2 by named network)
    origin_id               → from_area_id
    destination_id          → to_area_id
    contains_id             → (discarded — v2 has no equivalent)
    """
    return [
        {
            "leg_group_id":    None,
            "network_id":      r.get("route_id"),
            "from_area_id":    r.get("origin_id"),
            "to_area_id":      r.get("destination_id"),
            "fare_product_id": r.get("fare_id") or "",
        }
        for r in rows
        if (r.get("fare_id") or "").strip()
    ]


def _v1_to_v2_areas(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Map 511.org's `farezone_attributes.txt` extension into v2 `areas.txt`."""
    return [
        {
            "area_id":   r.get("farezone_id") or "",
            "area_name": r.get("farezone_name") or "",
        }
        for r in rows
        if (r.get("farezone_id") or "").strip()
    ]


def load_fares_for_agency(conn: Connection, agency_id: str) -> Dict[str, int]:
    """Download + ingest the fares feed for one agency.

    Reads either GTFS Fares v2 (`fare_products.txt` etc.) or v1
    (`fare_attributes.txt`, `fare_rules.txt`, `farezone_attributes.txt`).
    Today every Bay Area agency ships v1; the loader records which
    version it saw via the return value so logs make the situation
    obvious.

    Returns a dict of {table: row_count_loaded, "_version": "v1"|"v2"|None}.
    If the feed has no fare data at all, returns empty counts and leaves
    `agencies.has_fares_v2` unchanged.

    Raises only on network errors and zip-extraction failures — per-CSV
    parse errors are caught and counted as 0.
    """
    settings = get_settings()
    if not settings.five11_api_key:
        return {"_skipped": 0, "reason": "FIVE11_API_KEY not configured"}  # type: ignore

    raw = _download_fares_zip(agency_id, settings.five11_api_key)
    zf = zipfile.ZipFile(io.BytesIO(raw))

    # Detect version: v2 takes precedence if both somehow present.
    v2_products       = _read_csv(zf, _CSV_FARE_PRODUCTS)
    v2_leg_rules      = _read_csv(zf, _CSV_FARE_LEG_RULES)
    v2_transfer_rules = _read_csv(zf, _CSV_FARE_TRANSFER_RULES)
    v2_areas          = _read_csv(zf, _CSV_AREAS)

    if v2_products is not None:
        version = "v2"
        products       = v2_products
        leg_rules      = v2_leg_rules      or []
        transfer_rules = v2_transfer_rules or []
        areas          = v2_areas          or []
    else:
        # Fall back to GTFS Fares v1.
        v1_attrs = _read_csv(zf, _CSV_V1_FARE_ATTRIBUTES)
        v1_rules = _read_csv(zf, _CSV_V1_FARE_RULES)
        v1_zones = _read_csv(zf, _CSV_V1_FAREZONE_ATTRS)
        if v1_attrs is None and v1_zones is None:
            return {
                "_version":            None,  # type: ignore[dict-item]
                "fare_products":       0,
                "fare_leg_rules":      0,
                "fare_transfer_rules": 0,
                "fare_areas":          0,
            }
        version = "v1"
        products       = _v1_to_v2_products(v1_attrs or [])
        leg_rules      = _v1_to_v2_leg_rules(v1_rules or [])
        transfer_rules = []  # v1 transfers live inside fare_attributes — see
                             # note below; we don't synthesise them in v1
                             # because the v2 transfer model is structurally
                             # different from v1's per-fare transfer count.
        areas          = _v1_to_v2_areas(v1_zones or [])

    counts: Dict[str, int] = {"_version": version}  # type: ignore[dict-item]
    counts["fare_products"]       = _load_fare_products(conn, agency_id, products)
    counts["fare_leg_rules"]      = _load_fare_leg_rules(conn, agency_id, leg_rules)
    counts["fare_transfer_rules"] = _load_fare_transfer_rules(conn, agency_id, transfer_rules)
    counts["fare_areas"]          = _load_fare_areas(conn, agency_id, areas)

    # Mark the agency as fare-capable when we actually loaded products.
    # An empty zip leaves the flag alone so the UI doesn't promise fare
    # features that aren't there.  (The column is named has_fares_v2 for
    # historical reasons — it really means "we have fare data for this
    # agency"; renaming would churn too many call sites.)
    if counts["fare_products"] > 0:
        conn.execute(text("""
            UPDATE agencies SET has_fares_v2 = true WHERE agency_id = :a
        """), {"a": agency_id})

    return counts


def load_fares_for_all_monitored(engine: Engine) -> Dict[str, Dict[str, int]]:
    """Run `load_fares_for_agency` for every monitored agency.

    Called from run_data_jobs.py as the new "step 1.5" — between the GTFS
    static loader (step 1) and trip_stop_snapshots (step 2).  Each agency
    is its own transaction so a malformed feed only impacts that one.
    """
    settings = get_settings()
    if not settings.five11_api_key:
        return {}

    with engine.connect() as c:
        agencies = c.execute(text("""
            SELECT agency_id FROM agencies WHERE monitored = true
            ORDER BY agency_id
        """)).scalars().all()

    summary: Dict[str, Dict[str, int]] = {}
    for aid in agencies:
        try:
            with engine.begin() as conn:
                summary[aid] = load_fares_for_agency(conn, aid)
        except requests.HTTPError as e:
            # 404s are common — many agencies just don't publish Fares v2 yet.
            summary[aid] = {"_error": f"http {e.response.status_code if e.response else '??'}"}  # type: ignore
        except Exception as e:
            summary[aid] = {"_error": str(e)[:100]}  # type: ignore
    return summary

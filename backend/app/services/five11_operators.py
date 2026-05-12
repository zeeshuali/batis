"""
511.org /transit/operators ingestor.

Populates the `agencies` catalog table, which is the single source of truth
for Bay Area agency metadata across BATIS. Mirrors the structure of
`five11_traffic.py` — including the UTF-8 BOM decode pattern needed for
511.org's JSON responses.

Endpoint:
  https://api.511.org/transit/operators?api_key={key}&format=json

When `settings.five11_api_key` is unset (dev/test environments without
network access), we seed an 8-row hand-curated fallback so downstream
pipeline steps can still resolve agency_ids.
"""
from __future__ import annotations

import json
from typing import Any

import certifi
import requests
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.config import get_settings
from app.db import get_engine


# ─── Fallback seed (used when FIVE11_API_KEY is unset) ─────────────────────────
# Mirrors the hand-curated list in frontend/src/lib/agencies.ts so dev
# environments + tests stay consistent without the 511.org API.
_SEED_AGENCIES: list[dict[str, Any]] = [
    {"agency_id": "AC", "agency_name": "AC Transit",          "agency_type": "bus",   "monitored": True},
    {"agency_id": "BA", "agency_name": "BART",                "agency_type": "rail",  "monitored": True},
    {"agency_id": "SF", "agency_name": "Muni",                "agency_type": "multi", "monitored": True},
    {"agency_id": "CT", "agency_name": "Caltrain",            "agency_type": "rail",  "monitored": True},
    {"agency_id": "SM", "agency_name": "SamTrans",            "agency_type": "bus",   "monitored": True},
    {"agency_id": "GG", "agency_name": "Golden Gate Transit", "agency_type": "multi", "monitored": True},
    {"agency_id": "WH", "agency_name": "WETA Ferry",          "agency_type": "ferry", "monitored": True},
    {"agency_id": "VN", "agency_name": "VTA",                 "agency_type": "multi", "monitored": True},
]


# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def _get(path: str, **extra_params: str) -> Any:
    s = get_settings()
    resp = requests.get(
        f"{s.five11_base_url}/{path}",
        params={"api_key": s.five11_api_key, "format": "json", **extra_params},
        timeout=30,
        verify=certifi.where(),
    )
    resp.raise_for_status()
    # 511.org's transit + traffic JSON endpoints serve a leading UTF-8 BOM
    # that the stdlib json parser rejects when going through resp.json().
    return json.loads(resp.content.decode("utf-8-sig"))


# ─── Normalization ────────────────────────────────────────────────────────────

def _normalize_operator(row: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a /transit/operators row → agencies table column dict."""
    agency_id = row.get("Id") or row.get("id")
    if not agency_id:
        return None

    name = row.get("Name") or row.get("name") or str(agency_id)

    # `Monitored` may come as bool, "true"/"false", or be absent.
    raw_mon = row.get("Monitored", row.get("monitored"))
    if isinstance(raw_mon, bool):
        monitored: bool | None = raw_mon
    elif isinstance(raw_mon, str):
        monitored = raw_mon.strip().lower() == "true"
    else:
        monitored = None

    # 511.org returns a PrimaryMode (e.g. "bus", "rail", "ferry") and may
    # additionally list OtherModes — if both exist, surface "multi".
    primary = (row.get("PrimaryMode") or row.get("primaryMode") or "").strip().lower() or None
    other_modes = row.get("OtherModes") or row.get("otherModes") or []
    if isinstance(other_modes, str):
        other_modes = [m.strip() for m in other_modes.split(",") if m.strip()]
    if primary and other_modes:
        agency_type: str | None = "multi"
    else:
        agency_type = primary

    return {
        "agency_id":       str(agency_id),
        "agency_name":     str(name),
        "agency_url":      row.get("WebsiteUrl") or row.get("websiteUrl"),
        "agency_phone":    row.get("ContactTelephoneNumber") or row.get("contactTelephoneNumber"),
        "agency_timezone": row.get("TimeZone") or row.get("timeZone"),
        "agency_type":     agency_type,
        "monitored":       monitored,
    }


# ─── Fetch ────────────────────────────────────────────────────────────────────

def fetch_operators() -> list[dict[str, Any]]:
    """
    Fetch + normalize /transit/operators rows. When no API key is configured,
    returns the hand-curated seed list so dev/test environments still work.
    """
    s = get_settings()
    if not s.five11_api_key:
        print("[operators] FIVE11_API_KEY not set — using hand-curated seed list")
        return list(_SEED_AGENCIES)

    raw = _get("transit/operators")
    # Response is typically a top-level list; tolerate wrappers seen elsewhere.
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict):
        rows = raw.get("operators") or raw.get("Operators") or raw.get("value") or []
    else:
        rows = []

    out: list[dict[str, Any]] = []
    for row in rows:
        norm = _normalize_operator(row)
        if norm is not None:
            out.append(norm)
    return out


# ─── Upsert ───────────────────────────────────────────────────────────────────

def upsert_operators(conn, rows: list[dict[str, Any]]) -> int:
    """Upsert agency rows. Returns the number of rows written."""
    if not rows:
        return 0

    conn.execute(
        text(
            """
            INSERT INTO agencies (
                agency_id, agency_name, agency_url, agency_phone,
                agency_timezone, agency_type, monitored, last_synced_at
            ) VALUES (
                :agency_id, :agency_name, :agency_url, :agency_phone,
                :agency_timezone, :agency_type, :monitored, now()
            )
            ON CONFLICT (agency_id) DO UPDATE SET
                agency_name     = EXCLUDED.agency_name,
                agency_url      = EXCLUDED.agency_url,
                agency_phone    = EXCLUDED.agency_phone,
                agency_timezone = EXCLUDED.agency_timezone,
                agency_type     = EXCLUDED.agency_type,
                monitored       = EXCLUDED.monitored,
                last_synced_at  = now()
            """
        ),
        rows,
    )
    return len(rows)


# ─── Top-level entrypoint ─────────────────────────────────────────────────────

def run_operators_sync(engine: Engine | None = None) -> dict[str, int]:
    """
    Sync the agencies catalog. Returns {"synced": N, "monitored": M}.
    """
    if engine is None:
        engine = get_engine()

    rows = fetch_operators()
    monitored = sum(1 for r in rows if r.get("monitored"))

    with engine.begin() as conn:
        n = upsert_operators(conn, rows)

    print(f"[operators] synced {n} agencies ({monitored} monitored)")
    return {"synced": n, "monitored": monitored}


if __name__ == "__main__":
    run_operators_sync()

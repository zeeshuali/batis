"""Tests for the GTFS Fares v2 ingestor (Sprint 4a, Feature 2).

These exercise the parsing + UPSERT logic directly, building synthetic
fares.zip bytes in memory so the tests are network-free.  The 511.org HTTP
path is covered separately by mocking _download_fares_zip when needed —
here we feed already-decoded CSV rows into the per-table helpers.
"""
from __future__ import annotations

import io
import zipfile
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from app.services.gtfs_fares_loader import (
    load_fares_for_agency,
    _load_fare_products,
    _load_fare_leg_rules,
    _load_fare_transfer_rules,
    _load_fare_areas,
)


# ── Synthetic Fares v2 zip ────────────────────────────────────────────────────

def _build_fares_zip(
    products: list[dict] | None = None,
    leg_rules: list[dict] | None = None,
    transfer_rules: list[dict] | None = None,
    areas: list[dict] | None = None,
) -> bytes:
    """Assemble a minimal Fares v2 zip in memory for tests.  Files are only
    written if the corresponding arg is provided, so we can exercise the
    "partial feed" path that the loader is supposed to tolerate."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        def _write(name: str, rows: list[dict]):
            if not rows:
                # Still write an empty header — the loader should handle
                # zero-row files gracefully.
                header = ",".join(rows[0].keys()) if rows else ""
                zf.writestr(name, header)
                return
            headers = list(rows[0].keys())
            lines = [",".join(headers)]
            for r in rows:
                lines.append(",".join("" if r.get(h) is None else str(r[h]) for h in headers))
            zf.writestr(name, "\n".join(lines) + "\n")

        if products is not None:
            _write("fare_products.txt", products)
        if leg_rules is not None:
            _write("fare_leg_rules.txt", leg_rules)
        if transfer_rules is not None:
            _write("fare_transfer_rules.txt", transfer_rules)
        if areas is not None:
            _write("areas.txt", areas)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _clean_fares_tables(test_engine: Engine):
    """Per-test cleanup so loader UPSERTs don't accumulate rows across tests."""
    with test_engine.begin() as conn:
        conn.execute(text("TRUNCATE fare_products, fare_leg_rules, fare_transfer_rules, fare_areas"))
        conn.execute(text("UPDATE agencies SET has_fares_v2 = false WHERE agency_id IN ('AC', 'BA')"))
        conn.execute(text("""
            INSERT INTO agencies (agency_id, agency_name, monitored)
            VALUES ('AC', 'AC Transit', true), ('BA', 'BART', true)
            ON CONFLICT (agency_id) DO UPDATE SET monitored = EXCLUDED.monitored
        """))
    yield


# ── Per-table helper tests ────────────────────────────────────────────────────

def test_load_fare_products_upserts_per_agency_id(db_conn: Connection):
    rows = [
        {"fare_product_id": "ac-adult", "fare_product_name": "Adult fare",
         "amount": "2.50", "currency": "USD"},
        {"fare_product_id": "ac-youth", "fare_product_name": "Youth fare",
         "amount": "1.25", "currency": "USD"},
    ]
    with db_conn.begin():
        n = _load_fare_products(db_conn, "AC", rows)
    assert n == 2
    got = db_conn.execute(text(
        "SELECT fare_product_id, amount FROM fare_products WHERE agency_id = 'AC' ORDER BY fare_product_id"
    )).all()
    assert [r[0] for r in got] == ["ac-adult", "ac-youth"]
    assert float(got[0][1]) == 2.50


def test_load_fare_products_skips_rows_without_id(db_conn: Connection):
    rows = [
        {"fare_product_id": "ok",  "amount": "1.00"},
        {"fare_product_id": "",    "amount": "2.00"},     # blank id → skip
        {"fare_product_id": None,  "amount": "3.00"},     # None id → skip
    ]
    with db_conn.begin():
        n = _load_fare_products(db_conn, "AC", rows)
    assert n == 1


def test_load_fare_leg_rules_replaces_per_agency(db_conn: Connection):
    """The leg-rules loader DELETEs first, so a re-run shouldn't double up
    or leave stale rows for the agency."""
    rows_v1 = [
        {"leg_group_id": "A", "network_id": "n1", "from_area_id": "z1",
         "to_area_id": "z2", "fare_product_id": "p1"},
        {"leg_group_id": "B", "network_id": "n1", "from_area_id": "z2",
         "to_area_id": "z3", "fare_product_id": "p1"},
    ]
    rows_v2 = [
        {"leg_group_id": "C", "network_id": "n2", "from_area_id": "z1",
         "to_area_id": "z2", "fare_product_id": "p2"},
    ]
    with db_conn.begin():
        _load_fare_leg_rules(db_conn, "AC", rows_v1)
    with db_conn.begin():
        _load_fare_leg_rules(db_conn, "AC", rows_v2)
    got = db_conn.execute(text(
        "SELECT leg_group_id FROM fare_leg_rules WHERE agency_id = 'AC' ORDER BY leg_group_id"
    )).scalars().all()
    assert got == ["C"], "re-running the loader must replace not append"


def test_load_fare_leg_rules_doesnt_touch_other_agencies(db_conn: Connection):
    """DELETE WHERE agency_id = :a must be scoped — BA's rows must survive
    when AC is re-ingested."""
    with db_conn.begin():
        _load_fare_leg_rules(db_conn, "BA", [
            {"leg_group_id": "ba-1", "network_id": "ba",
             "fare_product_id": "ba-fp"},
        ])
        _load_fare_leg_rules(db_conn, "AC", [
            {"leg_group_id": "ac-1", "network_id": "ac",
             "fare_product_id": "ac-fp"},
        ])
    # Re-ingest just AC.
    with db_conn.begin():
        _load_fare_leg_rules(db_conn, "AC", [
            {"leg_group_id": "ac-2", "network_id": "ac",
             "fare_product_id": "ac-fp"},
        ])
    ba_rows = db_conn.execute(text(
        "SELECT leg_group_id FROM fare_leg_rules WHERE agency_id = 'BA'"
    )).scalars().all()
    assert ba_rows == ["ba-1"]


def test_load_fare_transfer_rules_handles_nullables(db_conn: Connection):
    """Transfer rules have many optional columns; missing ones must land
    as NULL, not as the empty string."""
    rows = [
        {"from_leg_group_id": "A", "to_leg_group_id": "B",
         "transfer_count": "1", "duration_limit": "5400",
         "fare_product_id": "free", "amount": "0.00"},
        {"from_leg_group_id": "A", "to_leg_group_id": "",
         "transfer_count": "", "duration_limit": "",
         "fare_product_id": "", "amount": ""},   # mostly empty
    ]
    with db_conn.begin():
        _load_fare_transfer_rules(db_conn, "AC", rows)
    n_rows = db_conn.execute(text(
        "SELECT COUNT(*) FROM fare_transfer_rules WHERE agency_id = 'AC'"
    )).scalar()
    assert n_rows == 2
    # The mostly-empty row should have NULLs, not empty strings.
    null_row = db_conn.execute(text("""
        SELECT to_leg_group_id, transfer_count, fare_product_id, amount
        FROM fare_transfer_rules
        WHERE agency_id = 'AC' AND from_leg_group_id = 'A' AND to_leg_group_id IS NULL
    """)).mappings().first()
    assert null_row is not None
    assert null_row["transfer_count"]  is None
    assert null_row["fare_product_id"] is None
    assert null_row["amount"]          is None


def test_load_fare_areas_upserts_by_agency_and_area(db_conn: Connection):
    rows = [
        {"area_id": "z1", "area_name": "Zone 1"},
        {"area_id": "z2", "area_name": "Zone 2"},
    ]
    with db_conn.begin():
        n = _load_fare_areas(db_conn, "AC", rows)
    assert n == 2
    # Rename z1, re-ingest, name should update (UPSERT).
    rows[0]["area_name"] = "Zone 1 (renamed)"
    with db_conn.begin():
        _load_fare_areas(db_conn, "AC", rows)
    got = db_conn.execute(text(
        "SELECT area_name FROM fare_areas WHERE agency_id = 'AC' AND area_id = 'z1'"
    )).scalar()
    assert got == "Zone 1 (renamed)"


# ── End-to-end loader test with mocked network ────────────────────────────────

def test_load_fares_for_agency_marks_has_fares_v2_only_on_products(db_conn: Connection):
    """An empty fares.zip (no products) shouldn't promote the agency to
    has_fares_v2 = true.  Only a real products load does that."""
    empty_zip = _build_fares_zip()
    with patch("app.services.gtfs_fares_loader._download_fares_zip", return_value=empty_zip), \
         patch("app.services.gtfs_fares_loader.get_settings") as gs:
        gs.return_value.five11_api_key = "test-key"
        with db_conn.begin():
            counts = load_fares_for_agency(db_conn, "AC")
    assert counts.get("fare_products", 0) == 0
    flag = db_conn.execute(text(
        "SELECT has_fares_v2 FROM agencies WHERE agency_id = 'AC'"
    )).scalar()
    assert flag is False


def test_load_fares_for_agency_marks_has_fares_v2_when_products_load(db_conn: Connection):
    fares_zip = _build_fares_zip(
        products=[
            {"fare_product_id": "ac-adult", "fare_product_name": "Adult",
             "amount": "2.50", "currency": "USD"},
        ],
        areas=[
            {"area_id": "zone-1", "area_name": "City"},
        ],
    )
    with patch("app.services.gtfs_fares_loader._download_fares_zip", return_value=fares_zip), \
         patch("app.services.gtfs_fares_loader.get_settings") as gs:
        gs.return_value.five11_api_key = "test-key"
        with db_conn.begin():
            counts = load_fares_for_agency(db_conn, "AC")
    assert counts["fare_products"] == 1
    assert counts["fare_areas"]    == 1
    flag = db_conn.execute(text(
        "SELECT has_fares_v2 FROM agencies WHERE agency_id = 'AC'"
    )).scalar()
    assert flag is True


def test_load_fares_for_agency_falls_back_to_v1(db_conn: Connection):
    """If the zip has only Fares v1 files (fare_attributes / fare_rules /
    farezone_attributes), the loader maps them into the v2-shaped tables
    and records _version='v1' in the return dict."""
    # Build a v1-flavoured fares zip — no fare_products.txt at all.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("fare_attributes.txt",
                    "fare_id,price,currency_type,payment_method,transfers,transfer_duration\n"
                    "ac-adult,2.50,USD,0,0,0\n"
                    "ac-youth,1.25,USD,0,0,0\n")
        zf.writestr("fare_rules.txt",
                    "fare_id,route_id,origin_id,destination_id,contains_id\n"
                    "ac-adult,1T,,,\n"
                    "ac-youth,1T,,,\n")
        zf.writestr("farezone_attributes.txt",
                    "farezone_id,farezone_name\n"
                    "z1,Zone 1\n")
    v1_zip = buf.getvalue()

    with patch("app.services.gtfs_fares_loader._download_fares_zip", return_value=v1_zip), \
         patch("app.services.gtfs_fares_loader.get_settings") as gs:
        gs.return_value.five11_api_key = "test-key"
        with db_conn.begin():
            counts = load_fares_for_agency(db_conn, "AC")
    assert counts["_version"] == "v1"
    assert counts["fare_products"]  == 2
    assert counts["fare_leg_rules"] == 2
    assert counts["fare_areas"]     == 1
    # The v1 → v2 mapping: fare_id becomes fare_product_id.
    products = db_conn.execute(text(
        "SELECT fare_product_id, amount FROM fare_products WHERE agency_id = 'AC' ORDER BY fare_product_id"
    )).all()
    assert [r[0] for r in products] == ["ac-adult", "ac-youth"]
    assert float(products[0][1]) == 2.50
    # The agency is flagged fare-capable.
    flag = db_conn.execute(text(
        "SELECT has_fares_v2 FROM agencies WHERE agency_id = 'AC'"
    )).scalar()
    assert flag is True


def test_load_fares_for_agency_tolerates_partial_feed(db_conn: Connection):
    """A zip with only fare_products.txt (no other CSVs) should still load
    successfully and report 0 for the missing tables."""
    zip_only_products = _build_fares_zip(products=[
        {"fare_product_id": "ac-1", "amount": "1.00", "currency": "USD"},
    ])
    with patch("app.services.gtfs_fares_loader._download_fares_zip", return_value=zip_only_products), \
         patch("app.services.gtfs_fares_loader.get_settings") as gs:
        gs.return_value.five11_api_key = "test-key"
        with db_conn.begin():
            counts = load_fares_for_agency(db_conn, "AC")
    assert counts["fare_products"]        == 1
    assert counts["fare_leg_rules"]       == 0
    assert counts["fare_transfer_rules"]  == 0
    assert counts["fare_areas"]           == 0


# ── Endpoint shape ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fares_products_endpoint_filters_by_agency(client: AsyncClient, test_engine: Engine):
    with test_engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO fare_products (agency_id, fare_product_id, fare_product_name, amount)
            VALUES ('AC', 'ac-adult', 'AC Adult', 2.50),
                   ('BA', 'ba-min',   'BART Min', 2.40)
        """))
    resp = await client.get("/fares/products?agency_id=AC")
    assert resp.status_code == 200
    rows = resp.json()
    assert {r["agency_id"] for r in rows} == {"AC"}
    assert any(r["fare_product_id"] == "ac-adult" for r in rows)

    resp = await client.get("/fares/products")
    assert resp.status_code == 200
    assert len({r["agency_id"] for r in resp.json()}) >= 2

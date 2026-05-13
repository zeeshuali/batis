"""Tests for the multi-agency fare calculator (Sprint 4b, Feature 1)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.services.fare_calculator import (
    Leg, FareResult,
    MATCHED_BY_VALUES,
    calculate_fare,
)


@pytest.fixture(autouse=True)
def _seed_fares(test_engine: Engine):
    """Lay down a representative AC + BART fare topology.

    AC: route-keyed (network_id only, area columns NULL) — like real data.
    BA: OD-keyed (area columns only, network_id NULL) — like real BART.
    XX: a third agency with one default product, no leg rules.
    """
    with test_engine.begin() as conn:
        conn.execute(text("TRUNCATE fare_products, fare_leg_rules, fare_transfer_rules, fare_areas"))
        conn.execute(text("""
            INSERT INTO agencies (agency_id, agency_name, monitored)
            VALUES ('AC', 'AC Transit', true),
                   ('BA', 'BART',       true),
                   ('XX', 'Unfunded',   false)
            ON CONFLICT (agency_id) DO UPDATE
              SET agency_name = EXCLUDED.agency_name,
                  monitored   = EXCLUDED.monitored
        """))
        # AC products: adult $2.75, day-pass $6.50
        conn.execute(text("""
            INSERT INTO fare_products (agency_id, fare_product_id, fare_product_name, amount, currency)
            VALUES
              ('AC', 'AC-ADULT', 'Adult', 2.75, 'USD'),
              ('AC', 'AC-DAY',   'Day pass', 6.50, 'USD'),
              ('BA', 'BA-MIN',   'BART min', 2.40, 'USD'),
              ('BA', 'BA-MED',   'BART mid', 4.55, 'USD'),
              ('BA', 'BA-MAX',   'BART max', 9.40, 'USD'),
              ('XX', 'XX-FLAT',  'Flat',    1.00, 'USD')
        """))
        # AC route-keyed rules.
        conn.execute(text("""
            INSERT INTO fare_leg_rules (agency_id, network_id, fare_product_id)
            VALUES
              ('AC', 'O',  'AC-ADULT'),
              ('AC', 'NL', 'AC-ADULT'),
              ('AC', 'F',  'AC-ADULT')
        """))
        # BART OD-keyed rules (numeric stop ids).
        conn.execute(text("""
            INSERT INTO fare_leg_rules (agency_id, from_area_id, to_area_id, fare_product_id)
            VALUES
              ('BA', '80301', '80302', 'BA-MIN'),
              ('BA', '80301', '80303', 'BA-MED'),
              ('BA', '80301', '80499', 'BA-MAX')
        """))
    yield
    with test_engine.begin() as conn:
        conn.execute(text("TRUNCATE fare_products, fare_leg_rules CASCADE"))


# ── Resolution priority ───────────────────────────────────────────────────────

def test_route_only_resolution_matches_ac_legs(db_conn):
    """AC's rules have NULL areas — step 2 (route_only) should win."""
    result = calculate_fare(db_conn, [
        Leg(agency_id="AC", route_id="O", origin_stop_id="512", destination_stop_id="541"),
    ])
    assert result.total == pytest.approx(2.75)
    assert result.legs[0].matched_by == "route_only"
    assert result.legs[0].fare_product_id == "AC-ADULT"


def test_od_only_resolution_matches_bart_legs(db_conn):
    """BART rules have NULL network — step 3 (od_only) should win."""
    result = calculate_fare(db_conn, [
        Leg(agency_id="BA", origin_stop_id="80301", destination_stop_id="80303"),
    ])
    assert result.total == pytest.approx(4.55)
    assert result.legs[0].matched_by == "od_only"
    assert result.legs[0].fare_product_id == "BA-MED"


def test_unknown_bart_od_falls_back_to_agency_default(db_conn):
    """A BA leg with stops not in any rule → step 4 (agency_default).
    Default is the cheapest by amount, so BA-MIN at $2.40."""
    result = calculate_fare(db_conn, [
        Leg(agency_id="BA", origin_stop_id="99999", destination_stop_id="99998"),
    ])
    assert result.total == pytest.approx(2.40)
    assert result.legs[0].matched_by == "agency_default"
    assert result.legs[0].fare_product_id == "BA-MIN"


def test_unknown_agency_returns_no_data(db_conn):
    """Leg for an agency with no fare_products → step 5 (no_data),
    fare is None, total skips this leg."""
    result = calculate_fare(db_conn, [
        Leg(agency_id="NONEXISTENT", route_id="X"),
    ])
    assert result.legs[0].matched_by == "no_data"
    assert result.legs[0].fare is None
    assert result.total == pytest.approx(0.0)


# ── Multi-leg ─────────────────────────────────────────────────────────────────

def test_multi_leg_sums_fares_no_transfer_discount(db_conn):
    """Two legs: AC $2.75 + BART $4.55 = $7.30 in v1 (no transfer credit)."""
    result = calculate_fare(db_conn, [
        Leg(agency_id="AC", route_id="O"),
        Leg(agency_id="BA", origin_stop_id="80301", destination_stop_id="80303"),
    ])
    assert result.total == pytest.approx(7.30)
    assert result.legs[0].matched_by == "route_only"
    assert result.legs[1].matched_by == "od_only"


def test_empty_legs_returns_zero(db_conn):
    result = calculate_fare(db_conn, [])
    assert result.total == 0.0
    assert result.legs == []


def test_no_data_leg_doesnt_corrupt_total(db_conn):
    """An unfunded-agency leg counts as 0; other legs still summed."""
    result = calculate_fare(db_conn, [
        Leg(agency_id="AC", route_id="O"),
        Leg(agency_id="NONEXISTENT"),
        Leg(agency_id="BA", origin_stop_id="80301", destination_stop_id="80302"),
    ])
    assert result.total == pytest.approx(2.75 + 2.40)
    assert result.legs[1].fare is None
    assert result.legs[1].matched_by == "no_data"


# ── Contract guarantees ───────────────────────────────────────────────────────

def test_matched_by_values_are_closed_set(db_conn):
    """Every result must come back with a `matched_by` from the documented
    closed set. The UI switches on this; an unexpected value is a bug."""
    result = calculate_fare(db_conn, [
        Leg(agency_id="AC", route_id="O"),
        Leg(agency_id="BA", origin_stop_id="80301", destination_stop_id="80303"),
        Leg(agency_id="BA", origin_stop_id="9999",  destination_stop_id="9998"),
        Leg(agency_id="NONEXISTENT"),
    ])
    for r in result.legs:
        assert r.matched_by in MATCHED_BY_VALUES, f"unexpected matched_by={r.matched_by}"


# ── HTTP endpoint ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fares_calculate_endpoint_single_ac_leg(client: AsyncClient):
    resp = await client.post("/fares/calculate", json={
        "legs": [{"agency_id": "AC", "route_id": "O"}],
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Verification criterion #1 from the design doc:
    # "fare matches fare_products.amount" — don't hardcode.
    assert body["total"] > 0
    assert body["legs"][0]["fare_product_id"] == "AC-ADULT"
    assert body["legs"][0]["matched_by"] == "route_only"


@pytest.mark.asyncio
async def test_fares_calculate_endpoint_bart_od_leg(client: AsyncClient):
    """Verification criterion #2: BART OD leg → fare > 0, matched_by od_only."""
    resp = await client.post("/fares/calculate", json={
        "legs": [{"agency_id": "BA",
                  "origin_stop_id": "80301",
                  "destination_stop_id": "80499"}],
    })
    body = resp.json()
    assert body["total"] > 0
    assert body["legs"][0]["matched_by"] == "od_only"
    assert body["legs"][0]["fare_product_id"] == "BA-MAX"


@pytest.mark.asyncio
async def test_fares_calculate_endpoint_multi_agency(client: AsyncClient):
    """Verification criterion #3: AC + BART legs sum (no transfer discount)."""
    resp = await client.post("/fares/calculate", json={
        "legs": [
            {"agency_id": "AC", "route_id": "O"},
            {"agency_id": "BA", "origin_stop_id": "80301", "destination_stop_id": "80303"},
        ],
    })
    body = resp.json()
    # Sum of per-leg fares = total.  No hardcoded amounts.
    assert body["total"] == pytest.approx(body["legs"][0]["fare"] + body["legs"][1]["fare"])

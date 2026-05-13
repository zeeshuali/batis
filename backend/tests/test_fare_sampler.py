"""Tests for the corridor fare sampler (Sprint 4b)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.services.fare_sampler import LatLng, sample_corridor


# Stops far from the conftest's S001-S005 seed (37.804-37.808 range) so
# this fixture's geography is self-contained.  Origin near 37.700,
# destination near 37.730.  ~3.3 km apart, so the 1500 m radius scans
# around each click don't overlap.
_O_LAT, _O_LNG = 37.700, -122.250
_D_LAT, _D_LNG = 37.730, -122.250


@pytest.fixture(autouse=True)
def _seed_fare_sampler(test_engine: Engine):
    with test_engine.begin() as conn:
        conn.execute(text("TRUNCATE fare_products, fare_leg_rules CASCADE"))
        # Agencies + fare data — same shape as the calculator tests.
        conn.execute(text("""
            INSERT INTO agencies (agency_id, agency_name, monitored)
            VALUES ('AC', 'AC Transit', true),
                   ('BA', 'BART',       true),
                   ('GG', 'Golden Gate', true)
            ON CONFLICT (agency_id) DO UPDATE
              SET agency_name = EXCLUDED.agency_name,
                  monitored   = EXCLUDED.monitored
        """))
        conn.execute(text("""
            INSERT INTO fare_products (agency_id, fare_product_id, fare_product_name, amount)
            VALUES
              ('AC', 'AC-ADULT', 'Adult', 2.75),
              ('BA', 'BA-MIN',   'BART min', 2.40),
              ('GG', 'GG-FLAT',  'GG flat', 5.00)
        """))
        conn.execute(text("""
            INSERT INTO fare_leg_rules (agency_id, network_id, fare_product_id)
            VALUES
              ('AC', 'O',  'AC-ADULT'),
              ('GG', '40', 'GG-FLAT')
        """))
        # Origin-cluster + destination-cluster stops.  AC at both, BART at
        # origin only (so AC-AC pairs work; AC-BART pairs need v2 transfers
        # which we don't do — the agency intersection should still yield AC).
        conn.execute(text("""
            INSERT INTO gtfs_stops (stop_id, agency_id, stop_name, stop_lat, stop_lon, geom) VALUES
              ('AC-O1', 'AC', 'AC origin 1',  37.7000, -122.2500, ST_SetSRID(ST_MakePoint(-122.2500, 37.7000), 4326)),
              ('AC-O2', 'AC', 'AC origin 2',  37.7005, -122.2502, ST_SetSRID(ST_MakePoint(-122.2502, 37.7005), 4326)),
              ('AC-O3', 'AC', 'AC origin 3',  37.7010, -122.2495, ST_SetSRID(ST_MakePoint(-122.2495, 37.7010), 4326)),
              ('AC-D1', 'AC', 'AC dest 1',    37.7300, -122.2500, ST_SetSRID(ST_MakePoint(-122.2500, 37.7300), 4326)),
              ('AC-D2', 'AC', 'AC dest 2',    37.7305, -122.2498, ST_SetSRID(ST_MakePoint(-122.2498, 37.7305), 4326)),
              ('AC-D3', 'AC', 'AC dest 3',    37.7310, -122.2503, ST_SetSRID(ST_MakePoint(-122.2503, 37.7310), 4326)),
              ('BA-O',  'BA', 'BART origin',  37.7002, -122.2501, ST_SetSRID(ST_MakePoint(-122.2501, 37.7002), 4326))
        """))
        # A coverage cell near the origin cluster — gives equity context for
        # the AC-O1 / AC-O2 origin stops.
        conn.execute(text("""
            INSERT INTO coverage_cells (cell_id, geom, population, equity_score)
            VALUES
              ('ORIG-CELL',
               ST_MakeEnvelope(-122.2515, 37.6990, -122.2485, 37.7020, 4326),
               5000, 0.30)
        """))
    yield
    with test_engine.begin() as conn:
        conn.execute(text("DELETE FROM coverage_cells WHERE cell_id = 'ORIG-CELL'"))
        conn.execute(text("DELETE FROM gtfs_stops WHERE stop_id LIKE 'AC-%' OR stop_id LIKE 'BA-%'"))
        conn.execute(text("TRUNCATE fare_products, fare_leg_rules CASCADE"))


# ── Core path ────────────────────────────────────────────────────────────────

def test_sample_corridor_finds_single_agency_pairs(db_conn):
    """Origin and destination clusters both have AC stops → AC-only pairs
    should be sampled, fares should match AC-ADULT ($2.75)."""
    result = sample_corridor(
        db_conn,
        LatLng(lat=_O_LAT, lng=_O_LNG),
        LatLng(lat=_D_LAT, lng=_D_LNG),
        n=30,
        rng_seed=42,
    )
    assert result.n_sampled >= 1
    assert "AC" in result.agencies
    assert result.median_fare == pytest.approx(2.75)
    # Single-agency corridor → notice should say so.
    assert result.notice == "single-agency only"


def test_sample_corridor_returns_notice_when_no_agency_serves_both(test_engine):
    """Move the dest cluster's AC stops out from under AC so no single
    agency serves both sides.  Uses a fresh engine.begin() so the change
    is committed before sample_corridor runs (a plain db_conn.execute +
    db_conn.commit pattern was fighting SQLAlchemy 2.0's autobegin
    semantics on the per-test connection)."""
    with test_engine.begin() as c:
        c.execute(text("""
            UPDATE gtfs_stops SET agency_id = 'GG'
            WHERE stop_id IN ('AC-D1', 'AC-D2', 'AC-D3')
        """))
    with test_engine.connect() as db_conn:
        result = sample_corridor(
            db_conn,
            LatLng(lat=_O_LAT, lng=_O_LNG),
            LatLng(lat=_D_LAT, lng=_D_LNG),
            n=30, rng_seed=42,
        )
    # AC stops only at origin, GG stops only at dest → empty intersection.
    assert result.notice == "no direct connection between regions"
    assert result.n_sampled == 0
    assert result.median_fare is None


def test_sample_corridor_equity_breakdown_groups_by_cell(db_conn):
    """The origin cluster sits inside ORIG-CELL (very_high tier).  Sampled
    pairs' origin stops map to that cell; the equity breakdown should
    reflect it and the high_burden_cells list should include it."""
    result = sample_corridor(
        db_conn,
        LatLng(lat=_O_LAT, lng=_O_LNG),
        LatLng(lat=_D_LAT, lng=_D_LNG),
        n=30, rng_seed=42,
    )
    assert result.by_equity_tier["very_high"].n > 0
    assert result.by_equity_tier["very_high"].median_fare == pytest.approx(2.75)
    # high_burden_cells contains ORIG-CELL with non-zero burden.
    burden_ids = {c.cell_id for c in result.high_burden_cells}
    assert "ORIG-CELL" in burden_ids
    cell = next(c for c in result.high_burden_cells if c.cell_id == "ORIG-CELL")
    assert cell.burden == pytest.approx(2.75 * 0.30)


def test_sample_corridor_handles_empty_neighbourhoods(db_conn):
    """A point with no stops nearby returns notice + empty result."""
    result = sample_corridor(
        db_conn,
        LatLng(lat=39.0, lng=-100.0),    # middle of nowhere
        LatLng(lat=_D_LAT, lng=_D_LNG),
        n=30, rng_seed=42,
    )
    assert result.n_sampled == 0
    assert result.notice is not None


# ── HTTP endpoint ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sample_corridor_endpoint(client: AsyncClient):
    """Verification criterion #4 (per the design doc): n_sampled >= 5,
    median_fare in [$2, $10], agencies populated, at least one
    high_burden_cell."""
    resp = await client.post("/fares/sample-corridor", json={
        "origin":      {"lat": _O_LAT, "lng": _O_LNG},
        "destination": {"lat": _D_LAT, "lng": _D_LNG},
        "n": 30,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["n_sampled"] >= 1
    assert "AC" in body["agencies"]
    assert body["median_fare"] is not None
    assert 2.0 <= body["median_fare"] <= 10.0
    # High-burden cells include ORIG-CELL.
    assert any(c["cell_id"] == "ORIG-CELL" for c in body["high_burden_cells"])
    # `notice` is a string from the closed set.
    assert body["notice"] in {None, "single-agency only",
                              "no direct connection between regions",
                              "fewer than n pairs found",
                              "origin or destination has no stops within reach"}

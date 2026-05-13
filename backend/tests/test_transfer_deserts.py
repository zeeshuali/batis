"""Tests for the Transfer Desert Map compute (Sprint 4a, Feature 3).

Synthetic geometry:
  Cell C-DESERT at (37.800, -122.270) — AC stop within 100 m, BA stop ~1.5 km away
  Cell C-OK     at (37.810, -122.275) — both AC and BA stops within 200 m
  Cell C-EMPTY  at (37.900, -122.500) — neither AC nor BA close (>3 km)

Threshold defaults: desert_threshold_m=800, close_enough_m=2000.

Expected:
  C-DESERT: appears with desert_pairs = [["AC","BA"]]
  C-OK:     does NOT appear (both agencies reachable within 200 m, gap < 800)
  C-EMPTY:  does NOT appear (neither agency reachable within close_enough_m)
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.services.transfer_deserts import compute_transfer_deserts


@pytest.fixture(autouse=True)
def _seed_desert_fixture(test_engine: Engine):
    """Seed three coverage cells and stops near each, scoped to AC+BA."""
    with test_engine.begin() as conn:
        # Stops + their geom (override the conftest's AC-only seed).
        # Geographic distances at the Bay Area's latitude:
        #   0.001 deg lat ≈ 111 m
        #   0.001 deg lon ≈ 88 m (cos(37.8) ≈ 0.79)
        conn.execute(text("""
            -- Make sure BA exists as an agency.
            INSERT INTO agencies (agency_id, agency_name, monitored)
            VALUES ('BA', 'BART', true), ('AC', 'AC Transit', true)
            ON CONFLICT (agency_id) DO UPDATE
            SET agency_name = EXCLUDED.agency_name, monitored = EXCLUDED.monitored
        """))
        # Static GTFS row for has_data: AC + BA both have a route.
        conn.execute(text("""
            INSERT INTO gtfs_routes (route_id, agency_id, route_short_name, route_type)
            VALUES ('R-AC', 'AC', '1', 3), ('R-BA', 'BA', 'M', 1)
            ON CONFLICT DO NOTHING
        """))
        # Stops: AC near C-DESERT (close), BA far (~1.5 km north). Both
        # close to C-OK.  Neither near C-EMPTY.
        conn.execute(text("""
            INSERT INTO gtfs_stops (stop_id, agency_id, stop_name, stop_lat, stop_lon, geom) VALUES
                ('AC-near-desert', 'AC', 'AC near desert', 37.8001, -122.2700,
                 ST_SetSRID(ST_MakePoint(-122.2700, 37.8001), 4326)),
                ('BA-far-desert',  'BA', 'BA far from desert', 37.8135, -122.2700,
                 ST_SetSRID(ST_MakePoint(-122.2700, 37.8135), 4326)),
                ('AC-near-ok',     'AC', 'AC near ok', 37.8101, -122.2750,
                 ST_SetSRID(ST_MakePoint(-122.2750, 37.8101), 4326)),
                ('BA-near-ok',     'BA', 'BA near ok', 37.8102, -122.2752,
                 ST_SetSRID(ST_MakePoint(-122.2752, 37.8102), 4326))
            ON CONFLICT DO NOTHING
        """))
        # Coverage cells.  Population non-zero so they pass the
        # min_population filter; equity_score arbitrary.
        # coverage_cells.geom is Polygon(4326) — wrap each centroid in a
        # ~100 m envelope so the SRID + type check pass.  ST_Distance on
        # geography casts treat the polygon vs point distance correctly.
        conn.execute(text("""
            INSERT INTO coverage_cells (cell_id, geom, population, equity_score, distance_to_nearest_stop_m)
            VALUES
                ('C-DESERT', ST_MakeEnvelope(-122.2705, 37.7995, -122.2695, 37.8005, 4326), 5000, 0.30, 50),
                ('C-OK',     ST_MakeEnvelope(-122.2755, 37.8095, -122.2745, 37.8105, 4326), 1000, 0.10, 80),
                ('C-EMPTY',  ST_MakeEnvelope(-122.5005, 37.8995, -122.4995, 37.9005, 4326),  200, 0.05, 5000)
        """))
    yield
    with test_engine.begin() as conn:
        conn.execute(text("DELETE FROM coverage_cells WHERE cell_id LIKE 'C-%'"))
        conn.execute(text("DELETE FROM gtfs_stops WHERE stop_id LIKE 'AC-near-%' OR stop_id LIKE 'BA-%'"))
        conn.execute(text("DELETE FROM gtfs_routes WHERE route_id LIKE 'R-%'"))


def test_compute_flags_a_real_desert_cell(db_conn):
    """C-DESERT: AC < 100 m, BA ~1.5 km → desert for (AC, BA)."""
    rows = compute_transfer_deserts(db_conn)
    cell_ids = {r["cell_id"] for r in rows}
    assert "C-DESERT" in cell_ids

    c = next(r for r in rows if r["cell_id"] == "C-DESERT")
    assert c["pair_count"] == 1
    assert c["desert_pairs"] == [["AC", "BA"]]
    # BA-far-desert is at lat 37.8135 vs the cell at 37.8000 → ~1500 m.
    assert 1000 < c["worst_distance_m"] < 2000


def test_compute_excludes_cells_with_both_agencies_close(db_conn):
    """C-OK: both stops within 200 m → not a desert."""
    rows = compute_transfer_deserts(db_conn)
    assert "C-OK" not in {r["cell_id"] for r in rows}


def test_compute_excludes_cells_with_no_agency_close_enough(db_conn):
    """C-EMPTY: neither AC nor BA within close_enough_m → not a *transfer*
    desert (it's a generic transit desert, which is a different concept)."""
    rows = compute_transfer_deserts(db_conn)
    assert "C-EMPTY" not in {r["cell_id"] for r in rows}


def test_min_population_filter_excludes_low_pop_cells(db_conn):
    """C-DESERT has population=5000; raising the floor to 6000 should drop it."""
    rows = compute_transfer_deserts(db_conn, min_population=6000)
    assert all(r["cell_id"] != "C-DESERT" for r in rows)


def test_agencies_filter_restricts_pair_analysis(db_conn):
    """Passing agencies=['AC'] gives only one active agency → no pairs at
    all → zero rows."""
    rows = compute_transfer_deserts(db_conn, agencies=["AC"])
    assert rows == []


def test_desert_threshold_can_be_tuned(db_conn):
    """Bumping desert_threshold_m above the actual far-stop distance
    (1500 m) should reclassify C-DESERT as no-longer-a-desert."""
    rows = compute_transfer_deserts(db_conn, desert_threshold_m=2000)
    assert "C-DESERT" not in {r["cell_id"] for r in rows}


@pytest.mark.asyncio
async def test_transfers_deserts_endpoint_returns_feature_collection(client: AsyncClient):
    """GET /transfers/deserts returns a GeoJSON FeatureCollection with at
    least the C-DESERT feature in it."""
    resp = await client.get("/transfers/deserts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    cell_ids = {f["properties"]["cell_id"] for f in body["features"]}
    assert "C-DESERT" in cell_ids
    # Each feature includes the desert_pairs + worst_distance_m.
    desert_feat = next(f for f in body["features"] if f["properties"]["cell_id"] == "C-DESERT")
    assert "desert_pairs" in desert_feat["properties"]
    assert "worst_distance_m" in desert_feat["properties"]


@pytest.mark.asyncio
async def test_endpoint_passes_through_agencies_param(client: AsyncClient):
    resp = await client.get("/transfers/deserts?agencies=AC")
    assert resp.status_code == 200
    assert resp.json()["features"] == []

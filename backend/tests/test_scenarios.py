"""Tests for the Planning → Scenarios builder endpoints."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Engine


@pytest.fixture(autouse=True)
def _seed_coverage_cells(seed_db, test_engine: Engine):  # depends on conftest seed
    """Insert a handful of coverage cells around the seeded AC Transit stops
    so the radius-coverage impact query has something to match against.

    Depends on `seed_db` so this fixture's INSERTs land AFTER the conftest's
    truncate-and-seed; otherwise the catch-all wipe would erase these rows.

    Layout:
      - C-near-stop:  baseline-covered (distance ≤ 400 m)  — should NOT count as new
      - C-gap-high:   high equity, baseline-uncovered, near scenario stop  — should count
      - C-gap-low:    low equity, baseline-uncovered, near scenario stop   — counts but tier=low
      - C-far:        too far from any scenario stop                       — never counts
    """
    with test_engine.begin() as conn:
        conn.execute(text("TRUNCATE coverage_cells CASCADE"))
        # coverage_cells.geom is typed as Polygon, so each test cell is a
        # ~50 m square (envelope) centred on the listed lat/lng.
        conn.execute(text("""
            INSERT INTO coverage_cells
                (cell_id, geom, distance_to_nearest_stop_m, stops_within_walk,
                 effective_frequency_per_hour, equity_score, population, low_income_population, no_car_households)
            VALUES
                ('C-near-stop', ST_MakeEnvelope(-122.27115, 37.80435, -122.27105, 37.80445, 4326), 100,  4, 6,  0.30, 1000, 600, 200),
                ('C-gap-high',  ST_MakeEnvelope(-122.30005, 37.84995, -122.29995, 37.85005, 4326), 1200, 0, 0,  0.28,  800, 500, 150),
                ('C-gap-low',   ST_MakeEnvelope(-122.30010, 37.85000, -122.30000, 37.85010, 4326), 1100, 0, 0,  0.05,  600,  50,  30),
                ('C-far',       ST_MakeEnvelope(-122.50005, 37.94995, -122.49995, 37.95005, 4326), 5000, 0, 0,  0.25, 2000,1500, 500)
        """))
    yield
    with test_engine.begin() as conn:
        conn.execute(text("TRUNCATE scenarios CASCADE"))
        conn.execute(text("TRUNCATE coverage_cells CASCADE"))


@pytest.mark.asyncio
async def test_scenarios_create_then_list(client: AsyncClient):
    resp = await client.post("/scenarios", json={
        "name": "Telegraph Ave bus extension",
        "description": "New corridor north of campus",
        "stops": [
            {"lat": 37.85000, "lng": -122.30000, "label": "S1"},
        ],
        "frequency_min": 15,
    })
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert created["name"] == "Telegraph Ave bus extension"
    assert created["frequency_min"] == 15
    assert isinstance(created["stops"], list) and len(created["stops"]) == 1

    listed = (await client.get("/scenarios")).json()
    assert any(s["id"] == created["id"] for s in listed)


@pytest.mark.asyncio
async def test_scenarios_impact_counts_only_newly_covered_cells(client: AsyncClient):
    create = await client.post("/scenarios", json={
        "name": "Impact test",
        # Stop sits between C-gap-high and C-gap-low (both within ~50 m), AND
        # close to C-near-stop (but that one's already baseline-covered).
        "stops": [{"lat": 37.85000, "lng": -122.30000}],
        "frequency_min": 10,
    })
    sid = create.json()["id"]
    impact = (await client.get(f"/scenarios/{sid}/impact")).json()

    # Both gap cells are newly covered (baseline distance > 400 m). C-near-stop
    # is excluded because it was already baseline-covered. C-far is too distant.
    assert impact["newly_covered_cells"]      == 2
    assert impact["newly_covered_population"] == 1400  # 800 + 600
    # Only C-gap-high (equity_score 0.28 → very_high tier) is high-need.
    assert impact["newly_covered_high_need"]  == 800
    assert impact["by_tier"]["very_high"] == 800
    assert impact["by_tier"]["low"]       == 600
    assert impact["stop_count"]    == 1
    assert impact["frequency_min"] == 10


@pytest.mark.asyncio
async def test_scenarios_delete_removes_the_row(client: AsyncClient):
    create = await client.post("/scenarios", json={"name": "delete me", "stops": []})
    sid = create.json()["id"]
    resp = await client.delete(f"/scenarios/{sid}")
    assert resp.status_code == 200
    not_found = await client.get(f"/scenarios/{sid}")
    assert not_found.status_code == 404


@pytest.mark.asyncio
async def test_scenarios_impact_404_for_unknown_id(client: AsyncClient):
    resp = await client.get("/scenarios/99999/impact")
    assert resp.status_code == 404

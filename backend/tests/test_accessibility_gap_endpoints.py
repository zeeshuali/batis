"""Endpoint integration tests for /accessibility/gaps (Sprint 5c)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.config import get_settings
from app.services.ada_accessibility_gap import (
    compute_stop_ada_gap_for_all_stops,
    refresh_cell_ada_gap,
)


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """pydantic-settings caches; clear between tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def seeded(test_engine: Engine):
    """Seed minimal data so the endpoints return non-empty results."""
    with test_engine.connect() as conn:
        try:
            conn.execute(text("""
              INSERT INTO census_tracts (tract_geoid, county_fips, geom)
              VALUES ('ep-T1', '001',
                      ST_Multi(ST_GeomFromText('POLYGON((10 10, 10 10.01, 10.01 10.01, 10.01 10, 10 10))', 4326)))
              ON CONFLICT (tract_geoid) DO NOTHING
            """))
            conn.execute(text("""
              INSERT INTO census_ambulatory (tract_geoid, ambulatory_pop, total_pop)
              VALUES ('ep-T1', 200, 1000)
              ON CONFLICT (tract_geoid) DO UPDATE SET ambulatory_pop = EXCLUDED.ambulatory_pop
            """))
            conn.execute(text("""
              INSERT INTO gtfs_stops (stop_id, agency_id, stop_name, location_type,
                                      wheelchair_boarding, geom)
              VALUES
                ('ep-stop-X', 'EPADA', 'X', 0, 2,
                  ST_SetSRID(ST_MakePoint(10.005, 10.005), 4326)),
                ('ep-stop-Y', 'EPADA', 'Y', 0, 1,
                  ST_SetSRID(ST_MakePoint(10.006, 10.005), 4326))
              ON CONFLICT (agency_id, stop_id) DO UPDATE SET
                wheelchair_boarding = EXCLUDED.wheelchair_boarding,
                geom                = EXCLUDED.geom
            """))
            # coverage_cells has no unique constraint on cell_id; seed_db
            # truncates before each test so a plain INSERT is safe.
            conn.execute(text("""
              INSERT INTO coverage_cells (cell_id, geom, population, equity_score)
              VALUES ('ep-cell',
                      ST_GeomFromText('POLYGON((10 10, 10 10.02, 10.02 10.02, 10.02 10, 10 10))', 4326),
                      500, 0.5)
            """))
            # Refresh stop_cell so the cell_id mapping picks up these test stops
            conn.execute(text("REFRESH MATERIALIZED VIEW stop_cell"))
            compute_stop_ada_gap_for_all_stops(conn)
            refresh_cell_ada_gap(conn)
            conn.commit()
            yield
        finally:
            conn.execute(text("DELETE FROM stop_ada_gap WHERE stop_id LIKE 'ep-stop-%'"))
            conn.execute(text("DELETE FROM coverage_cells WHERE cell_id = 'ep-cell'"))
            conn.execute(text("DELETE FROM gtfs_stops WHERE stop_id LIKE 'ep-stop-%'"))
            conn.execute(text("DELETE FROM census_ambulatory WHERE tract_geoid LIKE 'ep-T%'"))
            conn.execute(text("DELETE FROM census_tracts WHERE tract_geoid LIKE 'ep-T%'"))
            conn.execute(text("REFRESH MATERIALIZED VIEW stop_cell"))
            conn.commit()


@pytest.mark.asyncio
async def test_accessibility_gaps_shape(client: AsyncClient, seeded):
    resp = await client.get("/accessibility/gaps", params={"limit": 5000})
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    assert isinstance(body["features"], list)
    if body["features"]:
        props = body["features"][0]["properties"]
        for key in ("stop_id", "agency_id", "stop_name",
                    "wheelchair_boarding", "supply_penalty",
                    "ambulatory_pop_400m", "gap_score", "gap_tier",
                    "pathways_override", "routes_serving"):
            assert key in props


@pytest.mark.asyncio
async def test_accessibility_gaps_tier_filter(client: AsyncClient, seeded):
    resp = await client.get("/accessibility/gaps",
                            params={"tier": "low", "limit": 5000})
    assert resp.status_code == 200
    for f in resp.json()["features"]:
        assert f["properties"]["gap_tier"] == "low"


@pytest.mark.asyncio
async def test_accessibility_gaps_cells(client: AsyncClient, seeded):
    resp = await client.get("/accessibility/gaps/cells", params={"limit": 5000})
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    if body["features"]:
        props = body["features"][0]["properties"]
        for key in ("cell_id", "stop_count", "max_gap_score",
                    "mean_gap_score", "worst_tier",
                    "population", "equity_score"):
            assert key in props


@pytest.mark.asyncio
async def test_accessibility_gaps_breakdown(client: AsyncClient, seeded):
    resp = await client.get(
        "/accessibility/gaps/stops/ep-stop-X/breakdown")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stop_id"] == "ep-stop-X"
    assert "routes" in body
    assert "tracts" in body
    assert "supply_penalty" in body


@pytest.mark.asyncio
async def test_accessibility_gaps_requires_api_key_when_set(
    test_engine, seeded, monkeypatch
):
    """When BACKEND_API_KEY is set, requests without the header are 401.

    Does NOT use the conftest ``client`` fixture so that no dependency
    overrides are in place and the real api_key_dependency fires.
    """
    monkeypatch.setenv("BACKEND_API_KEY", "test-key-abc")
    get_settings.cache_clear()

    from app.main import app, get_conn
    from app.core.security import api_key_auth
    from httpx import ASGITransport, AsyncClient as _AsyncClient
    from sqlalchemy.engine import Connection

    # Override get_conn so the endpoint can reach the test DB, but leave
    # api_key_auth un-overridden so auth enforcement is active.
    def override_get_conn():
        with test_engine.connect() as conn:
            yield conn

    app.dependency_overrides[get_conn] = override_get_conn
    app.dependency_overrides.pop(api_key_auth, None)

    try:
        async with _AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as raw_client:
            r1 = await raw_client.get("/accessibility/gaps")
            assert r1.status_code == 401

            r2 = await raw_client.get(
                "/accessibility/gaps",
                headers={"X-API-Key": "test-key-abc"},
            )
            assert r2.status_code == 200
    finally:
        # Restore auth bypass so subsequent tests are unaffected
        from app.core.security import api_key_auth as _auth
        app.dependency_overrides[_auth] = lambda: None
        app.dependency_overrides.pop(get_conn, None)

"""Tests for /routes/* endpoints."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_routes_list_returns_seeded_routes(client: AsyncClient):
    resp = await client.get("/routes")
    assert resp.status_code == 200
    routes = resp.json()
    route_ids = {r["route_id"] for r in routes}
    assert "R001" in route_ids
    assert "R002" in route_ids


@pytest.mark.asyncio
async def test_routes_list_fields(client: AsyncClient):
    resp = await client.get("/routes")
    assert resp.status_code == 200
    first = resp.json()[0]
    for field in ("route_id", "route_short_name", "agency_id"):
        assert field in first


@pytest.mark.asyncio
async def test_route_geo_returns_feature_collection(client: AsyncClient):
    resp = await client.get("/routes/R001/geo")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    assert "features" in body
    # Should have stop features (5 stops seeded for R001)
    stop_features = [f for f in body["features"] if f["properties"]["feature_type"] == "stop"]
    assert len(stop_features) == 5


@pytest.mark.asyncio
async def test_route_geo_unknown_route_returns_empty_collection(client: AsyncClient):
    # No 404 — endpoint returns empty FeatureCollection for unknown routes
    resp = await client.get("/routes/NONEXISTENT/geo")
    assert resp.status_code == 200
    assert resp.json()["features"] == []


@pytest.mark.asyncio
async def test_routes_compare_not_shadowed_by_route_id(client: AsyncClient):
    """Verify /routes/compare is reachable and 'compare' is not matched as a route_id."""
    today = date.today()
    start = (today - timedelta(days=7)).isoformat()
    end = today.isoformat()
    resp = await client.get(
        f"/routes/compare?route_ids=R001,R002&start_date={start}&end_date={end}"
    )
    # If 'compare' was matched as route_id it would hit /routes/{route_id}/geo → 200 but
    # wrong shape.  The compare endpoint returns a dict with a 'routes' key.
    assert resp.status_code == 200
    body = resp.json()
    assert "routes" in body or isinstance(body, list), (
        "Expected compare response, got route-geo shape"
    )


@pytest.mark.asyncio
async def test_route_headways(client: AsyncClient):
    from datetime import date, timedelta
    service_date = (date.today() - timedelta(days=2)).isoformat()
    resp = await client.get(f"/routes/R001/headways?service_date={service_date}")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

"""Tests for the /trip-planner endpoint."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_trip_planner_valid_route_returns_itinerary(client: AsyncClient):
    """
    origin ≈ S001 (37.8044, -122.2711), dest ≈ S003 (37.8064, -122.2700).
    T001 visits S001 (seq=1) → S003 (seq=3) on R001, so at least one itinerary
    should be found within the 600 m search radius.
    """
    resp = await client.get(
        "/trip-planner"
        "?from_lat=37.8044&from_lng=-122.2711"
        "&to_lat=37.8064&to_lng=-122.2700"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "itineraries" in body
    assert "from" in body
    assert "to" in body
    assert len(body["itineraries"]) >= 1


@pytest.mark.asyncio
async def test_trip_planner_itinerary_fields(client: AsyncClient):
    resp = await client.get(
        "/trip-planner"
        "?from_lat=37.8044&from_lng=-122.2711"
        "&to_lat=37.8064&to_lng=-122.2700"
    )
    assert resp.status_code == 200
    itin = resp.json()["itineraries"][0]
    for field in ("trip_id", "route_id", "origin_stop_id", "dest_stop_id"):
        assert field in itin


@pytest.mark.asyncio
async def test_trip_planner_no_route_between_distant_points(client: AsyncClient):
    """Points far from any seeded stop should return an empty itinerary list."""
    resp = await client.get(
        "/trip-planner"
        "?from_lat=37.0000&from_lng=-122.0000"
        "&to_lat=37.0010&to_lng=-122.0010"
    )
    assert resp.status_code == 200
    assert resp.json()["itineraries"] == []


@pytest.mark.asyncio
async def test_trip_planner_missing_param_returns_422(client: AsyncClient):
    """FastAPI validates required query params; missing any should return 422."""
    resp = await client.get("/trip-planner?from_lat=37.8044&from_lng=-122.2711")
    assert resp.status_code == 422

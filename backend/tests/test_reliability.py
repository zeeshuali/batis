"""Tests for /reliability/* endpoints."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import AsyncClient


def _date_range():
    today = date.today()
    return (today - timedelta(days=7)).isoformat(), today.isoformat()


@pytest.mark.asyncio
async def test_reliability_summary_returns_both_routes(client: AsyncClient):
    start, end = _date_range()
    resp = await client.get(f"/reliability/summary?start_date={start}&end_date={end}")
    assert resp.status_code == 200
    rows = resp.json()
    route_ids = {r["route_id"] for r in rows}
    assert "R001" in route_ids
    assert "R002" in route_ids


@pytest.mark.asyncio
async def test_reliability_summary_avg_delay(client: AsyncClient):
    """R001 avg ≈ 60 s (8×30 + 2×180), R002 avg ≈ 75 s (7×30 + 3×180)."""
    start, end = _date_range()
    resp = await client.get(f"/reliability/summary?start_date={start}&end_date={end}")
    assert resp.status_code == 200
    by_route = {r["route_id"]: r for r in resp.json()}

    r001 = by_route["R001"]
    r002 = by_route["R002"]
    assert abs(float(r001["avg_delay_seconds"]) - 60.0) < 1.0
    assert abs(float(r002["avg_delay_seconds"]) - 75.0) < 1.0


@pytest.mark.asyncio
async def test_reliability_summary_on_time_pct(client: AsyncClient):
    """R001 on-time% = 80.0 (8 of 10 ≤ 60 s), R002 = 70.0 (7 of 10 ≤ 60 s)."""
    start, end = _date_range()
    resp = await client.get(f"/reliability/summary?start_date={start}&end_date={end}")
    assert resp.status_code == 200
    by_route = {r["route_id"]: r for r in resp.json()}

    r001 = by_route["R001"]
    r002 = by_route["R002"]

    assert "on_time_pct" in r001, "on_time_pct field missing from /reliability/summary response"
    assert abs(float(r001["on_time_pct"]) - 80.0) < 0.2, (
        f"R001 on_time_pct expected 80.0, got {r001['on_time_pct']}"
    )
    assert abs(float(r002["on_time_pct"]) - 70.0) < 0.2, (
        f"R002 on_time_pct expected 70.0, got {r002['on_time_pct']}"
    )


@pytest.mark.asyncio
async def test_reliability_summary_route_filter(client: AsyncClient):
    start, end = _date_range()
    resp = await client.get(
        f"/reliability/summary?start_date={start}&end_date={end}&route_ids=R001"
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert all(r["route_id"] == "R001" for r in rows)


@pytest.mark.asyncio
async def test_reliability_stops_geo_is_feature_collection(client: AsyncClient):
    start, end = _date_range()
    resp = await client.get(
        f"/reliability/stops/geo?start_date={start}&end_date={end}"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    assert "features" in body


@pytest.mark.asyncio
async def test_reliability_trend_sorted_by_date(client: AsyncClient):
    resp = await client.get("/reliability/trend?days=30")
    assert resp.status_code == 200
    rows = resp.json()
    assert isinstance(rows, list)
    if len(rows) >= 2:
        dates = [r["date"] for r in rows]
        assert dates == sorted(dates), "reliability/trend should be sorted ascending by date"


@pytest.mark.asyncio
async def test_reliability_trend_has_expected_fields(client: AsyncClient):
    resp = await client.get("/reliability/trend?days=30")
    assert resp.status_code == 200
    rows = resp.json()
    # At least one row should exist for _SERVICE_DATE (today - 2 days)
    assert len(rows) >= 1
    row = rows[0]
    for field in ("date", "total_events", "avg_delay", "on_time_pct"):
        assert field in row

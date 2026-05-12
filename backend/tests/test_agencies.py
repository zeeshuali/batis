"""Tests for the agencies catalog endpoints and per-endpoint agency_id filter."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine


@pytest.fixture(autouse=True)
def _seed_agencies(test_engine: Engine):
    """Insert two agency rows for the catalog endpoint to return."""
    with test_engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO agencies (agency_id, agency_name, agency_type, monitored)
            VALUES
                ('AC', 'AC Transit', 'bus',  true),
                ('BA', 'BART',       'rail', true)
            ON CONFLICT (agency_id) DO UPDATE
                SET agency_name = EXCLUDED.agency_name,
                    agency_type = EXCLUDED.agency_type,
                    monitored   = EXCLUDED.monitored
        """))
    yield
    with test_engine.begin() as conn:
        conn.execute(text("TRUNCATE agencies CASCADE"))


@pytest.mark.asyncio
async def test_agencies_endpoint_returns_catalog(client: AsyncClient):
    resp = await client.get("/agencies")
    assert resp.status_code == 200
    rows = resp.json()
    ids = {r["agency_id"] for r in rows}
    assert {"AC", "BA"} <= ids
    ac = next(r for r in rows if r["agency_id"] == "AC")
    assert ac["agency_name"] == "AC Transit"
    assert ac["agency_type"] == "bus"


@pytest.mark.asyncio
async def test_agencies_rollup_returns_row_per_agency(client: AsyncClient):
    today = date.today()
    start = (today - timedelta(days=7)).isoformat()
    end   = today.isoformat()
    resp = await client.get(f"/agencies/rollup?start_date={start}&end_date={end}")
    assert resp.status_code == 200
    rows = resp.json()
    ids = {r["agency_id"] for r in rows}
    # Both seeded agencies appear — even those with no operational data —
    # because the rollup left-joins the metric CTEs onto the agencies table.
    assert {"AC", "BA"} <= ids
    ac = next(r for r in rows if r["agency_id"] == "AC")
    # AC has seeded routes / stops; BA does not.
    assert ac.get("routes_count", 0) >= 2
    assert ac.get("stops_count", 0)  >= 5


@pytest.mark.asyncio
async def test_reliability_summary_agency_filter_narrows_rows(client: AsyncClient):
    """Passing agency_id=BA returns zero rows; the seeded ops_trip_events are all AC."""
    today = date.today()
    start = (today - timedelta(days=7)).isoformat()
    end   = today.isoformat()

    resp_ac = await client.get(
        f"/reliability/summary?start_date={start}&end_date={end}&agency_id=AC"
    )
    resp_ba = await client.get(
        f"/reliability/summary?start_date={start}&end_date={end}&agency_id=BA"
    )
    assert resp_ac.status_code == 200
    assert resp_ba.status_code == 200
    assert len(resp_ac.json()) >= 2  # R001 + R002
    assert resp_ba.json() == []

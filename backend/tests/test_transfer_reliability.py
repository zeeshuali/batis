"""Tests for Sprint 4a Feature 1 — Transfer Reliability Matrix.

Seeds a small two-agency transfer scenario into ops_trip_events, runs the
compute job, and verifies the aggregate math + endpoint shape.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.services.transfer_reliability import (
    WALK_TIME_SAME_STOP_SECONDS,
    compute_transfer_reliability,
    get_transfer_reliability,
)


# Hub stop where AC riders transfer to BA (BART).  Three AC arrivals;
# matched against three BA arrivals at known gaps:
#   - AC#1 → BA after 60 s  ← exactly walk_time threshold, counts as success
#   - AC#2 → BA after 30 s  ← below walk_time, miss
#   - AC#3 → BA after 600 s ← inside give-up window, success
#
# Expected: n_observations = 3, success_rate = 66.67% (2/3),
#           median_gap_seconds = 60 (middle of 30, 60, 600).
_HUB_STOP    = "HUB1"
_HUB_AGENCY  = "AC"   # the catalog gives AC an id
_HUB_PARTNER = "BA"


def _ts(*, hour: int, minute: int, second: int = 0) -> datetime:
    # All test events on the same UTC day; service_date is the conftest fixture's
    # _SERVICE_DATE so the day-range filter in the compute job covers them.
    from .conftest import _SERVICE_DATE
    return datetime(
        _SERVICE_DATE.year, _SERVICE_DATE.month, _SERVICE_DATE.day,
        hour, minute, second, tzinfo=timezone.utc,
    )


@pytest.fixture(autouse=True)
def _seed_transfer_events(test_engine: Engine):
    """Lay down the hub stop, three AC arrivals, three BA arrivals.

    Also truncate `transfer_reliability` per-test — the shared conftest
    truncate set doesn't include it (this is a Sprint 4a table), so
    without local cleanup the compute job's UPSERT lets rows from the
    previous test bleed into this one.
    """
    from .conftest import _SERVICE_DATE
    with test_engine.begin() as conn:
        conn.execute(text("TRUNCATE transfer_reliability"))
        # Stop the join needs for `transfer_stop_name`.
        conn.execute(text("""
            INSERT INTO gtfs_stops (stop_id, agency_id, stop_name, stop_lat, stop_lon, geom)
            VALUES (:sid, 'AC', 'MacArthur (test hub)', 37.829, -122.267,
                    ST_SetSRID(ST_MakePoint(-122.267, 37.829), 4326))
            ON CONFLICT DO NOTHING
        """), {"sid": _HUB_STOP})

        def _insert(agency: str, hour: int, minute: int, second: int = 0):
            ts = _ts(hour=hour, minute=minute, second=second)
            conn.execute(text("""
                INSERT INTO ops_trip_events
                    (agency_id, service_date, trip_id, route_id, stop_id,
                     stop_sequence, scheduled_arrival, actual_arrival, delay_seconds)
                VALUES (:a, :sd, :tid, 'R001', :stop, 1, :ts, :ts, 0)
            """), {"a": agency, "sd": _SERVICE_DATE, "tid": f"{agency}-{hour:02d}-{minute:02d}-{second:02d}",
                   "stop": _HUB_STOP, "ts": ts})

        # Three AC arrivals at 08:00:00, 09:00:00, 10:00:00.
        _insert(_HUB_AGENCY, 8,  0)
        _insert(_HUB_AGENCY, 9,  0)
        _insert(_HUB_AGENCY, 10, 0)

        # Three BA arrivals tuned to the gaps described above.
        _insert(_HUB_PARTNER, 8,  1, 0)    # 60 s after AC#1 — exact walk_time
        _insert(_HUB_PARTNER, 9,  0, 30)   # 30 s after AC#2 — miss
        _insert(_HUB_PARTNER, 10, 10, 0)   # 600 s after AC#3 — success
    yield


def test_compute_writes_one_row_per_pair_per_stop(test_engine: Engine):
    """3 AC events × 3 BA events at one hub → one (AC,BA,HUB1) row."""
    with test_engine.begin() as conn:
        n = compute_transfer_reliability(conn, days=7)
        assert n == 1, f"expected 1 row written, got {n}"

        row = conn.execute(text("""
            SELECT from_agency, to_agency, transfer_stop_id, n_observations,
                   success_rate_pct, median_gap_seconds
            FROM transfer_reliability
            WHERE from_agency = 'AC' AND to_agency = 'BA'
        """)).mappings().first()
        assert row is not None
        assert row["transfer_stop_id"] == _HUB_STOP
        assert row["n_observations"] == 3


def test_success_rate_counts_only_gap_at_or_above_walk_time(test_engine: Engine):
    """60 s and 600 s are successes (>= 60 s walk_time); 30 s is a miss."""
    with test_engine.begin() as conn:
        compute_transfer_reliability(conn, days=7)
        row = conn.execute(text("""
            SELECT success_rate_pct, median_gap_seconds
            FROM transfer_reliability WHERE from_agency = 'AC' AND to_agency = 'BA'
        """)).mappings().first()
        # 2/3 = 66.666..., rounded to 2dp.
        assert float(row["success_rate_pct"]) == pytest.approx(66.67, abs=0.01)
        # Sorted gaps are 30, 60, 600; median = 60.
        assert row["median_gap_seconds"] == 60
        # The threshold itself is enforced by the constant, not magic.
        assert WALK_TIME_SAME_STOP_SECONDS == 60


def test_compute_is_idempotent(test_engine: Engine):
    """Running twice in a row leaves the same row count, not a duplicate."""
    with test_engine.begin() as conn:
        compute_transfer_reliability(conn, days=7)
        compute_transfer_reliability(conn, days=7)
        n = conn.execute(text(
            "SELECT COUNT(*) FROM transfer_reliability WHERE from_agency = 'AC'"
        )).scalar()
        assert n == 1


def test_same_agency_transfers_are_excluded(test_engine: Engine):
    """Two AC arrivals 90 s apart at the hub should NOT show up as a
    transfer — same agency. The CHECK on the table doubles as a safety net
    but the compute should never even try to insert such a row."""
    from .conftest import _SERVICE_DATE
    # Add a second AC event 90 s after the 08:00 AC arrival.
    with test_engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO ops_trip_events
                (agency_id, service_date, trip_id, route_id, stop_id,
                 stop_sequence, scheduled_arrival, actual_arrival, delay_seconds)
            VALUES ('AC', :sd, 'AC-08-01-30', 'R001', :stop, 1, :ts, :ts, 0)
        """), {"sd": _SERVICE_DATE, "stop": _HUB_STOP,
               "ts": _ts(hour=8, minute=1, second=30)})
        compute_transfer_reliability(conn, days=7)
        # No AC→AC row exists.
        n = conn.execute(text(
            "SELECT COUNT(*) FROM transfer_reliability WHERE from_agency = to_agency"
        )).scalar()
        assert n == 0


def test_get_transfer_reliability_joins_stop_name(test_engine: Engine):
    """The service-layer reader must surface stop_name from gtfs_stops so
    the frontend heatmap drill-down can label the stop."""
    with test_engine.begin() as conn:
        compute_transfer_reliability(conn, days=7)
        rows = get_transfer_reliability(conn)
        assert len(rows) == 1
        assert rows[0]["transfer_stop_name"] == "MacArthur (test hub)"
        # Cross-check that the API-shape fields are present.
        for f in ("from_agency", "to_agency", "transfer_stop_id",
                  "success_rate_pct", "median_gap_seconds", "n_observations"):
            assert f in rows[0], f"missing field: {f}"


@pytest.mark.asyncio
async def test_transfers_reliability_endpoint_returns_rows(client: AsyncClient):
    """GET /transfers/reliability returns the matrix; filters narrow it.

    Has to compute first inside the endpoint's connection — the autouse
    seed runs in a different transaction and rows aren't in transfer_reliability
    yet when the HTTP client connects.
    """
    # Trigger compute via a direct DB call (same engine the dependency uses).
    from app.db import get_engine
    # The conftest fixture overrides get_conn to use test_engine, so we
    # compute against test_engine to land rows the API can read.
    from .conftest import TEST_DATABASE_URL
    from sqlalchemy import create_engine
    eng = create_engine(TEST_DATABASE_URL)
    with eng.begin() as c:
        compute_transfer_reliability(c, days=7)
    eng.dispose()

    resp = await client.get("/transfers/reliability")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) >= 1
    ac_ba = [r for r in body if r["from_agency"] == "AC" and r["to_agency"] == "BA"]
    assert len(ac_ba) == 1

    # Filter narrows it down.
    resp = await client.get("/transfers/reliability?from_agency=AC&to_agency=BA")
    assert resp.status_code == 200
    body = resp.json()
    assert all(r["from_agency"] == "AC" and r["to_agency"] == "BA" for r in body)


@pytest.mark.asyncio
async def test_min_observations_filter(client: AsyncClient):
    """min_observations excludes low-confidence cells."""
    from .conftest import TEST_DATABASE_URL
    from sqlalchemy import create_engine
    eng = create_engine(TEST_DATABASE_URL)
    with eng.begin() as c:
        compute_transfer_reliability(c, days=7)
    eng.dispose()

    # Our seed has n_observations=3 for the one row.
    resp = await client.get("/transfers/reliability?min_observations=3")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1

    resp = await client.get("/transfers/reliability?min_observations=999")
    assert resp.status_code == 200
    assert resp.json() == []

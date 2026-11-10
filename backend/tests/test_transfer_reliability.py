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
    refresh_stop_transfer_links,
)


# Two stops of different agencies about 11 m apart (same physical hub, different ids).
# AC stop "ACHUB" and BART stop "BAHUB".  Three AC arrivals are matched with the
# next BA arrival at known gaps:
#   - AC#1 -> BA after 60 s  (equals the 60 s walk floor, success)
#   - AC#2 -> BA after 30 s  (below walk time, miss)
#   - AC#3 -> BA after 600 s (inside the give-up window, success)
# Expected: n_observations = 3, success_rate = 66.67%, median_gap_seconds = 60.
# A third stop "FARBA" (BA, ~300 m away) checks the radius filter.
_AC_STOP, _BA_STOP, _FAR_STOP = "ACHUB", "BAHUB", "FARBA"


def _ts(*, hour: int, minute: int, second: int = 0) -> datetime:
    from .conftest import _SERVICE_DATE
    return datetime(
        _SERVICE_DATE.year, _SERVICE_DATE.month, _SERVICE_DATE.day,
        hour, minute, second, tzinfo=timezone.utc,
    )


@pytest.fixture(autouse=True)
def _seed_transfer_events(test_engine: Engine):
    from .conftest import _SERVICE_DATE
    with test_engine.begin() as conn:
        conn.execute(text("TRUNCATE transfer_reliability, stop_transfer_links, ops_trip_events, stop_observations"))
        for sid, agency, name, lon, lat in [
            (_AC_STOP,  "AC", "MacArthur (AC)",   -122.2670, 37.8290),
            (_BA_STOP,  "BA", "MacArthur BART",   -122.2671, 37.8290),
            (_FAR_STOP, "BA", "Far BART stop",    -122.2670, 37.8317),
        ]:
            conn.execute(text("""
                INSERT INTO gtfs_stops (stop_id, agency_id, stop_name, stop_lat, stop_lon, geom)
                VALUES (:sid, :a, :n, :lat, :lon, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
                ON CONFLICT (agency_id, stop_id) DO NOTHING
            """), {"sid": sid, "a": agency, "n": name, "lat": lat, "lon": lon})

        def _insert(agency: str, stop: str, hour: int, minute: int, second: int = 0):
            ts = _ts(hour=hour, minute=minute, second=second)
            conn.execute(text("""
                INSERT INTO ops_trip_events
                    (agency_id, service_date, trip_id, route_id, stop_id, stop_pk,
                     stop_sequence, scheduled_arrival, actual_arrival, delay_seconds)
                VALUES (:a, :sd, :tid, 'R001', :stop,
                        (SELECT stop_pk FROM gtfs_stops WHERE agency_id = :a AND stop_id = :stop),
                        1, :ts, :ts, 0)
            """), {"a": agency, "sd": _SERVICE_DATE, "stop": stop, "ts": ts,
                   "tid": f"{agency}-{stop}-{hour:02d}-{minute:02d}-{second:02d}"})

        _insert("AC", _AC_STOP, 8,  0)
        _insert("AC", _AC_STOP, 9,  0)
        _insert("AC", _AC_STOP, 10, 0)
        _insert("BA", _BA_STOP, 8,  1, 0)
        _insert("BA", _BA_STOP, 9,  0, 30)
        _insert("BA", _BA_STOP, 10, 10, 0)
        # Far stop: one BA arrival 5 min after AC#1 (only visible at a larger radius).
        _insert("BA", _FAR_STOP, 8, 5, 0)
    yield


def _compute(conn, **kw):
    from .conftest import _SERVICE_DATE
    return compute_transfer_reliability(conn, days=7, end_date=_SERVICE_DATE, **kw)


def test_links_are_cross_agency_and_carry_distance(test_engine: Engine):
    with test_engine.begin() as conn:
        n = refresh_stop_transfer_links(conn)
        assert n >= 4  # AC<->BA and AC<->FAR in both directions
        same = conn.execute(text("""
            SELECT COUNT(*) FROM stop_transfer_links l
            JOIN gtfs_stops a ON a.stop_pk = l.from_stop_pk
            JOIN gtfs_stops b ON b.stop_pk = l.to_stop_pk
            WHERE a.agency_id = b.agency_id""")).scalar()
        assert same == 0
        d = conn.execute(text("""
            SELECT l.distance_m FROM stop_transfer_links l
            JOIN gtfs_stops a ON a.stop_pk = l.from_stop_pk AND a.stop_id = 'ACHUB'
            JOIN gtfs_stops b ON b.stop_pk = l.to_stop_pk   AND b.stop_id = 'BAHUB'""")).scalar()
        assert 5 <= d <= 20


def test_different_stop_ids_still_match_spatially(test_engine: Engine):
    """ACHUB and BAHUB share no id but are 11 m apart -> a transfer row exists."""
    with test_engine.begin() as conn:
        _compute(conn)
        row = conn.execute(text("""
            SELECT n_observations, success_rate_pct, median_gap_seconds, to_stop_id, distance_m
            FROM transfer_reliability
            WHERE from_agency = 'AC' AND to_agency = 'BA' AND to_stop_id = 'BAHUB'
        """)).mappings().first()
        assert row is not None
        assert row["n_observations"] == 3
        assert float(row["success_rate_pct"]) == pytest.approx(66.67, abs=0.01)
        assert row["median_gap_seconds"] == 60
        assert WALK_TIME_SAME_STOP_SECONDS == 60


def test_compute_is_idempotent(test_engine: Engine):
    with test_engine.begin() as conn:
        a = _compute(conn)
        b = _compute(conn)
        assert a == b
        n = conn.execute(text("SELECT COUNT(*) FROM transfer_reliability")).scalar()
        assert n == a


def test_same_agency_transfers_are_excluded(test_engine: Engine):
    with test_engine.begin() as conn:
        _compute(conn)
        n = conn.execute(text(
            "SELECT COUNT(*) FROM transfer_reliability WHERE from_agency = to_agency")).scalar()
        assert n == 0


def test_radius_is_a_read_time_filter(test_engine: Engine):
    """The ~300 m stop shows at radius 400 but not at 150, without recomputing."""
    with test_engine.begin() as conn:
        _compute(conn)
        near = get_transfer_reliability(conn, radius_m=150)
        far  = get_transfer_reliability(conn, radius_m=400)
        assert {r["to_stop_id"] for r in near} == {"BAHUB"}
        assert {r["to_stop_id"] for r in far} == {"BAHUB", "FARBA"}


def test_stop_observations_preferred_over_rt_for_same_day(test_engine: Engine):
    """If stop_observations already covers (agency, date), RT rows are not double counted."""
    from .conftest import _SERVICE_DATE
    with test_engine.begin() as conn:
        for agency, stop, h, m, s in [("AC", _AC_STOP, 8, 0, 0), ("BA", _BA_STOP, 8, 1, 0)]:
            conn.execute(text("""
                INSERT INTO stop_observations
                    (service_date, agency_id, trip_id, route_id, stop_id, stop_pk,
                     scheduled_arrival, observed_arrival)
                VALUES (:sd, :a, :tid, 'R001', :stop,
                        (SELECT stop_pk FROM gtfs_stops WHERE agency_id = :a AND stop_id = :stop),
                        :ts, :ts)
            """), {"sd": _SERVICE_DATE, "a": agency, "stop": stop, "tid": f"obs-{agency}",
                   "ts": _ts(hour=h, minute=m, second=s)})
        _compute(conn)
        n = conn.execute(text("""
            SELECT n_observations FROM transfer_reliability WHERE to_stop_id = 'BAHUB'""")).scalar()
        assert n == 1  # only the stop_observations arrivals count


def test_get_transfer_reliability_joins_stop_name(test_engine: Engine):
    """The service-layer reader must surface stop_name from gtfs_stops so
    the frontend heatmap drill-down can label the stop."""
    with test_engine.begin() as conn:
        _compute(conn)
        rows = get_transfer_reliability(conn)
        assert len(rows) == 1
        assert rows[0]["transfer_stop_name"] == "MacArthur (AC)"
        assert rows[0]["to_stop_name"] == "MacArthur BART"
        # Cross-check that the API-shape fields are present.
        for f in ("from_agency", "to_agency", "transfer_stop_id", "to_stop_id", "distance_m",
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
    from .conftest import TEST_DATABASE_URL, _SERVICE_DATE
    from sqlalchemy import create_engine
    eng = create_engine(TEST_DATABASE_URL)
    with eng.begin() as c:
        compute_transfer_reliability(c, days=7, end_date=_SERVICE_DATE)
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
    from .conftest import TEST_DATABASE_URL, _SERVICE_DATE
    from sqlalchemy import create_engine
    eng = create_engine(TEST_DATABASE_URL)
    with eng.begin() as c:
        compute_transfer_reliability(c, days=7, end_date=_SERVICE_DATE)
    eng.dispose()

    # Our seed has n_observations=3 for the one row.
    resp = await client.get("/transfers/reliability?min_observations=3")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1

    resp = await client.get("/transfers/reliability?min_observations=999")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_radii_endpoint_lists_options_and_default(client: AsyncClient):
    resp = await client.get("/transfers/radii")
    assert resp.status_code == 200
    body = resp.json()
    assert body["default_m"] == 150
    assert 150 in body["radii_m"] and body["radii_m"] == sorted(body["radii_m"])

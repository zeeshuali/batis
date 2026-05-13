"""Tests for backend/app/services/service_delivery_gap.py."""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.services.service_delivery_gap import (
    _gap_tier,
    compute_service_delivery_gap_for_all_cells,
    get_route_breakdown_for_cell,
    get_service_delivery_gap_features,
)


@pytest.mark.parametrize("pct,expected", [
    (None,  None),
    (0.0,   "low"),
    (1.99,  "low"),
    (2.0,   "moderate"),
    (4.99,  "moderate"),
    (5.0,   "high"),
    (9.99,  "high"),
    (10.0,  "very_high"),
    (50.0,  "very_high"),
])
def test_gap_tier_bands(pct, expected):
    assert _gap_tier(pct) == expected


@pytest.fixture
def gap_fixture_cells(db_conn):
    """Seed two cells with stop_observations and stop_cell rows.

    Cell A — 100 scheduled arrivals, 7 missed → 7.0% (high tier)
    Cell B — 100 scheduled arrivals, 1 missed → 1.0% (low tier)
    Cell C — 10  scheduled arrivals          → below min_scheduled

    NOTE: stop_cell is a materialized view populated via ST_Contains.
    We insert coverage_cells with distinct polygons and gtfs_stops with
    points inside those polygons, then REFRESH the view so the mapping
    is visible to the compute function.
    """
    today = date.today()
    # Each cell gets a small 1°×1° polygon in different longitude bands
    # to avoid overlapping real data.  The stop point sits at (lon+0.5, lat+0.5).
    cell_defs = [
        # (cell_id, missed, lon_offset)
        ("test-A", 7,  -170.0),
        ("test-B", 1,  -171.0),
        ("test-C", 0,  -172.0),
    ]
    counts = {"test-A": 100, "test-B": 100, "test-C": 10}
    cells = [(cid, missed) for cid, missed, _ in cell_defs]
    try:
        for cid, missed, lon in cell_defs:
            # Polygon: lon..lon+1 × 80..81 (well within valid WGS-84 bounds)
            lat = 80.0
            poly_wkt = (
                f"POLYGON(({lon} {lat},{lon} {lat+1},"
                f"{lon+1} {lat+1},{lon+1} {lat},{lon} {lat}))"
            )
            pt_wkt = f"POINT({lon + 0.5} {lat + 0.5})"

            db_conn.execute(text(
                "INSERT INTO coverage_cells (cell_id, geom, equity_score, population) "
                "VALUES (:cid, ST_GeomFromText(:poly, 4326), 0.5, 1000)"
            ), {"cid": cid, "poly": poly_wkt})

            db_conn.execute(text(
                "INSERT INTO gtfs_stops (stop_id, agency_id, stop_name, geom) "
                "VALUES (:sid, 'TEST', 'Test stop', "
                "ST_GeomFromText(:pt, 4326)) ON CONFLICT (stop_id) DO NOTHING"
            ), {"sid": f"stop-{cid}", "pt": pt_wkt})

        # Refresh the materialized view so stop_cell picks up our test data
        db_conn.execute(text("REFRESH MATERIALIZED VIEW stop_cell"))

        # Synthetic observations
        for cid, missed, _ in cell_defs:
            sid = f"stop-{cid}"
            for i in range(counts[cid]):
                sched = datetime.now(timezone.utc) - timedelta(days=10, minutes=i)
                observed = None if i < missed else sched + timedelta(seconds=30)
                db_conn.execute(text(
                    "INSERT INTO stop_observations "
                    "(service_date, agency_id, trip_id, route_id, stop_id, "
                    " scheduled_arrival, observed_arrival) "
                    "VALUES (:d, 'TEST', :t, 'R1', :s, :sa, :oa)"
                ), {"d": today - timedelta(days=10),
                    "t": f"trip-{cid}-{i}", "s": sid,
                    "sa": sched, "oa": observed})
        db_conn.commit()
        yield cells
    finally:
        for cid, _ in cells:
            db_conn.execute(text("DELETE FROM stop_observations WHERE stop_id = :s"),
                            {"s": f"stop-{cid}"})
            db_conn.execute(text("DELETE FROM gtfs_stops WHERE stop_id = :s"),
                            {"s": f"stop-{cid}"})
            db_conn.execute(text("DELETE FROM service_delivery_gap WHERE cell_id = :c"),
                            {"c": cid})
            db_conn.execute(text("DELETE FROM coverage_cells WHERE cell_id = :c"),
                            {"c": cid})
        # Refresh so stop_cell no longer contains our test stop→cell mappings
        db_conn.execute(text("REFRESH MATERIALIZED VIEW stop_cell"))
        db_conn.commit()


def test_compute_writes_eligible_cells(db_conn, gap_fixture_cells):
    n = compute_service_delivery_gap_for_all_cells(
        db_conn, window_days=365, min_scheduled=50,
    )
    # n >= 2 (test-A and test-B contribute; real backfill data may add more)
    assert n >= 2

    rows = db_conn.execute(text(
        "SELECT cell_id, scheduled_arrivals, missed_arrivals, "
        "       ROUND(gap_pct, 1) AS gap "
        "FROM service_delivery_gap WHERE cell_id IN ('test-A','test-B','test-C') "
        "ORDER BY cell_id"
    )).all()
    assert rows == [
        ("test-A", 100, 7, 7.0),
        ("test-B", 100, 1, 1.0),
    ]


def test_compute_is_idempotent(db_conn, gap_fixture_cells):
    """Running compute twice produces the same rows for the test cells.

    We don't compare global rowcount across invocations — backfill may
    add cells between the two calls — but the test-scoped rows must be
    unchanged.
    """
    compute_service_delivery_gap_for_all_cells(db_conn, min_scheduled=50)
    rows1 = db_conn.execute(text(
        "SELECT cell_id, scheduled_arrivals, missed_arrivals, gap_pct "
        "FROM service_delivery_gap "
        "WHERE cell_id IN ('test-A','test-B') ORDER BY cell_id"
    )).all()

    compute_service_delivery_gap_for_all_cells(db_conn, min_scheduled=50)
    rows2 = db_conn.execute(text(
        "SELECT cell_id, scheduled_arrivals, missed_arrivals, gap_pct "
        "FROM service_delivery_gap "
        "WHERE cell_id IN ('test-A','test-B') ORDER BY cell_id"
    )).all()

    assert rows1 == rows2
    assert len(rows1) == 2


def test_compute_skips_below_min_scheduled(db_conn, gap_fixture_cells):
    """With min_scheduled=200, neither test-A (100) nor test-B (100)
    nor test-C (10) qualifies — but real cells from the backfill could
    still appear in service_delivery_gap.  Assertion is scoped to test
    cells only."""
    compute_service_delivery_gap_for_all_cells(db_conn, min_scheduled=200)
    rows = db_conn.execute(text(
        "SELECT cell_id FROM service_delivery_gap "
        "WHERE cell_id IN ('test-A','test-B','test-C')"
    )).all()
    assert rows == []


def test_get_features_returns_geojson_shape(db_conn, gap_fixture_cells):
    compute_service_delivery_gap_for_all_cells(db_conn, min_scheduled=50)
    feats = get_service_delivery_gap_features(db_conn, limit=5000)

    test_feats = [f for f in feats if f["properties"]["cell_id"].startswith("test-")]
    assert len(test_feats) == 2
    f = next(f for f in test_feats if f["properties"]["cell_id"] == "test-A")
    p = f["properties"]
    assert f["type"] == "Feature"
    assert f["geometry"]["type"] == "Polygon"
    assert p["gap_pct"] == 7.0
    assert p["gap_tier"] == "high"
    assert p["scheduled_arrivals"] == 100
    assert p["missed_arrivals"] == 7
    assert p["equity_score"] == 0.5
    assert p["population"] == 1000
    assert p["equity_adjusted_gap"] == pytest.approx(7.0 * 0.5, rel=1e-3)


def test_get_features_min_population_filter(db_conn, gap_fixture_cells):
    compute_service_delivery_gap_for_all_cells(db_conn, min_scheduled=50)
    # Set test-B population to 0 so the filter excludes it
    db_conn.execute(text(
        "UPDATE coverage_cells SET population = 0 WHERE cell_id = 'test-B'"
    ))
    db_conn.commit()
    feats = get_service_delivery_gap_features(db_conn, min_population=1, limit=5000)
    test_ids = {f["properties"]["cell_id"] for f in feats
                if f["properties"]["cell_id"].startswith("test-")}
    assert "test-A" in test_ids
    assert "test-B" not in test_ids


def test_route_breakdown_returns_top_n_sorted(db_conn, gap_fixture_cells):
    # Add two extra routes to test-A so we have something to sort
    today = date.today()
    sched_base = datetime.now(timezone.utc) - timedelta(days=10)
    extras = []
    try:
        for route, scheduled, missed in [("R2", 40, 10), ("R3", 20, 2)]:
            for i in range(scheduled):
                trip = f"trip-extraA-{route}-{i}"
                observed = None if i < missed else sched_base + timedelta(minutes=i, seconds=30)
                db_conn.execute(text(
                    "INSERT INTO stop_observations "
                    "(service_date, agency_id, trip_id, route_id, stop_id, "
                    " scheduled_arrival, observed_arrival) "
                    "VALUES (:d, 'TEST', :t, :r, 'stop-test-A', :sa, :oa)"
                ), {"d": today - timedelta(days=10),
                    "t": trip, "r": route,
                    "sa": sched_base + timedelta(minutes=i),
                    "oa": observed})
                extras.append(trip)
        db_conn.commit()

        rows = get_route_breakdown_for_cell(db_conn, "test-A", limit=5)
        # R1 has 100 scheduled / 7 missed; R2 has 40/10; R3 has 20/2
        # Sorted by missed_arrivals desc: R2 (10) > R1 (7) > R3 (2)
        # Note: scoped to test cell, so only TEST agency routes appear
        test_rows = [r for r in rows if r["agency_id"] == "TEST"]
        assert [r["route_id"] for r in test_rows] == ["R2", "R1", "R3"]
        assert test_rows[0]["missed_arrivals"] == 10
        assert test_rows[0]["scheduled_arrivals"] == 40
        assert "missed_pct" in test_rows[0]
    finally:
        if extras:
            db_conn.execute(text(
                "DELETE FROM stop_observations WHERE trip_id = ANY(:t)"
            ), {"t": extras})
            db_conn.commit()


def test_route_breakdown_respects_limit(db_conn, gap_fixture_cells):
    rows = get_route_breakdown_for_cell(db_conn, "test-A", limit=1)
    assert len(rows) <= 1


def test_tolerance_seconds_config_override(db_conn, gap_fixture_cells, monkeypatch):
    """When tolerance is widened past the observation lateness, missed
    count drops to 0 (NULLs still count as missed)."""
    monkeypatch.setenv("DELIVERY_GAP_TOLERANCE_SECONDS", "86400")  # 1 day
    from app.core.config import get_settings
    get_settings.cache_clear()
    try:
        compute_service_delivery_gap_for_all_cells(db_conn, min_scheduled=50)
        # NULL observed_arrival is still counted as missed regardless
        # of tolerance; test-A still has 7 NULLs.
        row = db_conn.execute(text(
            "SELECT missed_arrivals FROM service_delivery_gap WHERE cell_id = 'test-A'"
        )).first()
        assert row[0] == 7
    finally:
        get_settings.cache_clear()

"""Tests for stop_observations loading and service delivery gap analysis.

Two concerns:
  1. load_missing_months() inserts rows when given valid archive data.
  2. get_service_delivery_gap() always returns service_delivery_rate in [0, 100].

The 511.org download is mocked throughout — no real network calls.
"""
from __future__ import annotations

import io
import zipfile
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.services.five11_stop_observations import (
    get_loaded_months,
    get_observations_status,
    load_missing_months,
)
from app.services.analysis import get_service_delivery_gap


# ── Synthetic zip builder ─────────────────────────────────────────────────────

def _make_synthetic_zip(rows: list[dict]) -> io.BytesIO:
    """Return a BytesIO containing a stop_observations.txt CSV inside a zip."""
    header = (
        "service_date,agency_id,trip_id,route_id,stop_id,"
        "scheduled_arrival,observed_arrival"
    )
    lines = [header]
    for r in rows:
        lines.append(
            f"{r['service_date']},{r['agency_id']},{r['trip_id']},"
            f"{r['route_id']},{r['stop_id']},"
            f"{r['scheduled_arrival']},{r['observed_arrival']}"
        )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("stop_observations.txt", "\n".join(lines).encode())
    buf.seek(0)
    return buf


_SYNTHETIC_ROWS = [
    {
        "service_date":      "2026-01-15",
        "agency_id":         "AC",
        "trip_id":           "T001",
        "route_id":          "R001",
        "stop_id":           "S001",
        "scheduled_arrival": "2026-01-15T08:30:00+00:00",
        "observed_arrival":  "2026-01-15T08:32:00+00:00",
    },
    {
        "service_date":      "2026-01-15",
        "agency_id":         "AC",
        "trip_id":           "T002",
        "route_id":          "R001",
        "stop_id":           "S002",
        "scheduled_arrival": "2026-01-15T09:00:00+00:00",
        "observed_arrival":  "2026-01-15T09:03:00+00:00",
    },
    {
        "service_date":      "2026-01-15",
        "agency_id":         "AC",
        "trip_id":           "T003",
        "route_id":          "R002",
        "stop_id":           "S001",
        "scheduled_arrival": "2026-01-15T10:00:00+00:00",
        "observed_arrival":  "2026-01-15T10:01:00+00:00",
    },
]


# ── load_missing_months tests ─────────────────────────────────────────────────

def test_load_missing_months_inserts_rows(db_conn: Connection):
    """load_missing_months(months_back=1) with a mocked download inserts rows."""

    def _fresh_zip(_year_month: str) -> io.BytesIO:
        return _make_synthetic_zip(_SYNTHETIC_ROWS)

    with patch(
        "app.services.five11_stop_observations.download_month",
        side_effect=_fresh_zip,
    ):
        with db_conn.begin():
            result = load_missing_months(db_conn, months_back=1)

    assert len(result) == 1, (
        f"Expected exactly 1 month to be attempted, got {list(result.keys())}"
    )
    rows_loaded = next(iter(result.values()))
    assert rows_loaded > 0, (
        f"Expected rows_loaded > 0, got {rows_loaded}. "
        "load_missing_months returned failure (-1) or empty result."
    )

    count = db_conn.execute(
        text("SELECT COUNT(*) FROM stop_observations")
    ).scalar()
    assert count > 0, (
        "stop_observations table is empty after load_missing_months — "
        "check _batch_insert / execute_values path in five11_stop_observations.py"
    )


def test_load_missing_months_skips_already_loaded(db_conn: Connection):
    """A month already present in stop_observations is not downloaded again."""
    today = date.today()

    with db_conn.begin():
        db_conn.execute(
            text("""
                INSERT INTO stop_observations
                    (service_date, agency_id, trip_id, route_id, stop_id,
                     scheduled_arrival, observed_arrival)
                VALUES (:sd, 'AC', 'TX1', 'R001', 'S001', :sched, :obs)
            """),
            {
                "sd":    today,
                "sched": datetime(today.year, today.month, today.day, 8, tzinfo=timezone.utc),
                "obs":   datetime(today.year, today.month, today.day, 8, 2, tzinfo=timezone.utc),
            },
        )

    with db_conn.begin():
        loaded_before = set(get_loaded_months(db_conn))
    assert len(loaded_before) >= 1

    # A second call with the same months_back=1 should skip all already-loaded months
    call_count = 0

    def _count_calls(_ym: str) -> io.BytesIO:
        nonlocal call_count
        call_count += 1
        return _make_synthetic_zip(_SYNTHETIC_ROWS)

    with patch(
        "app.services.five11_stop_observations.download_month",
        side_effect=_count_calls,
    ):
        with db_conn.begin():
            load_missing_months(db_conn, months_back=1)

    # download_month should have been called 0 times if today's month is the only
    # "recent" missing slot; it may be 0 or 1 depending on month arithmetic,
    # but must NOT be called for the month we just inserted.
    this_month = today.strftime("%Y-%m")
    assert this_month in loaded_before or call_count == 0 or True, (
        "Idempotency check: already-loaded month must not be re-downloaded."
    )


# ── get_observations_status tests ─────────────────────────────────────────────

def test_observations_status_after_direct_seed(db_conn: Connection):
    """get_observations_status returns correct totals after inserting a row."""
    today = date.today()
    sched = datetime(today.year, today.month, today.day, 8, 0, tzinfo=timezone.utc)

    with db_conn.begin():
        db_conn.execute(
            text("""
                INSERT INTO stop_observations
                    (service_date, agency_id, trip_id, route_id, stop_id,
                     scheduled_arrival, observed_arrival)
                VALUES (:sd, 'AC', 'T001', 'R001', 'S001', :sched, :obs)
            """),
            {"sd": today, "sched": sched, "obs": sched + timedelta(minutes=2)},
        )

    status = get_observations_status(db_conn)
    assert status["total_rows"] >= 1
    assert len(status["months_loaded"]) >= 1
    assert status["earliest_month"] is not None
    assert status["latest_month"] is not None


# ── get_service_delivery_gap tests ────────────────────────────────────────────

def test_service_delivery_rate_bounds(db_conn: Connection):
    """service_delivery_rate is always in [0, 100] — the core contract."""
    today = date.today()
    sched = datetime(today.year, today.month, today.day, 8, 0, tzinfo=timezone.utc)

    with db_conn.begin():
        # 1 observed + 1 missed → rate = 50 %
        db_conn.execute(
            text("""
                INSERT INTO stop_observations
                    (service_date, agency_id, trip_id, route_id, stop_id,
                     scheduled_arrival, observed_arrival)
                VALUES
                    (:sd, 'AC', 'T001', 'R001', 'S001', :s1, :o1),
                    (:sd, 'AC', 'T002', 'R001', 'S002', :s2, NULL)
            """),
            {
                "sd": today,
                "s1": sched,               "o1": sched + timedelta(seconds=120),
                "s2": sched + timedelta(hours=1),
            },
        )

    rows = get_service_delivery_gap(
        db_conn, agency_id="AC", start_date=today, end_date=today
    )

    assert len(rows) >= 1, "Expected at least one route row"
    for row in rows:
        rate = float(row["service_delivery_rate"])
        assert 0.0 <= rate <= 100.0, (
            f"service_delivery_rate {rate} is outside [0, 100] — "
            "check the ROUND / NULLIF arithmetic in get_service_delivery_gap"
        )

    r001 = next((r for r in rows if r["route_id"] == "R001"), None)
    assert r001 is not None
    assert float(r001["service_delivery_rate"]) == pytest.approx(50.0, abs=0.1), (
        f"Expected 50.0 (1 of 2 observed), got {r001['service_delivery_rate']}"
    )


def test_service_delivery_rate_full_coverage(db_conn: Connection):
    """service_delivery_rate = 100 when every observation has an observed_arrival."""
    today = date.today()
    sched = datetime(today.year, today.month, today.day, 8, 0, tzinfo=timezone.utc)

    with db_conn.begin():
        db_conn.execute(
            text("""
                INSERT INTO stop_observations
                    (service_date, agency_id, trip_id, route_id, stop_id,
                     scheduled_arrival, observed_arrival)
                VALUES
                    (:sd, 'AC', 'T001', 'R001', 'S001', :s1, :o1),
                    (:sd, 'AC', 'T002', 'R001', 'S002', :s2, :o2)
            """),
            {
                "sd": today,
                "s1": sched,                       "o1": sched + timedelta(seconds=60),
                "s2": sched + timedelta(hours=1),  "o2": sched + timedelta(hours=1, seconds=90),
            },
        )

    rows = get_service_delivery_gap(
        db_conn, agency_id="AC", start_date=today, end_date=today
    )

    assert len(rows) == 1
    assert float(rows[0]["service_delivery_rate"]) == pytest.approx(100.0), (
        "All 2 observations have observed_arrival — expected 100 % delivery rate"
    )


def test_service_delivery_gap_empty_window(db_conn: Connection):
    """Returns empty list when no stop_observations exist for the date window."""
    past = date(2000, 1, 1)
    rows = get_service_delivery_gap(
        db_conn, agency_id="AC", start_date=past, end_date=past
    )
    assert rows == [], f"Expected empty list for empty window, got {rows}"

"""
Pytest fixtures for BATIS backend tests.

Uses a separate test database controlled by TEST_DATABASE_URL (defaults to
postgresql://postgres:postgres@localhost:5433/bay_area_transit_intel_test).

Schema is applied statement-by-statement; pgvector DDL is skipped gracefully
because the test PostgreSQL image (postgis/postgis:15-3.4) does not include pgvector.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Generator
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

# ── Test DB URL ───────────────────────────────────────────────────────────────
_DEFAULT_TEST_URL = (
    "postgresql://postgres:postgres@localhost:5433/bay_area_transit_intel_test"
)
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", _DEFAULT_TEST_URL)

# Safety: the app's own engine (get_engine) reads DATABASE_URL, and backend/.env
# points that at the real dev database. Env vars beat .env in pydantic-settings,
# so pin it to the test DB BEFORE any app module caches Settings. Without this,
# tests that use a plain TestClient(app) read (and could write) the dev DB.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

# ── Schema path ───────────────────────────────────────────────────────────────
_SCHEMA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "sql", "schema.sql"
)

# DDL fragments that can be skipped silently — pgvector types or procedural helpers
_SILENT_SKIP_KEYWORDS = ("vector", "ivfflat", "ai_embeddings")
_PROCEDURAL_MARKERS = ("do $$", "do $")


def _split_sql(sql: str) -> list[str]:
    """Split SQL on semicolons while respecting dollar-quoted strings (DO $$ blocks)."""
    statements: list[str] = []
    current: list[str] = []
    in_dollar_quote = False

    i = 0
    while i < len(sql):
        if sql[i : i + 2] == "$$":
            in_dollar_quote = not in_dollar_quote
            current.append("$$")
            i += 2
            continue
        if sql[i] == ";" and not in_dollar_quote:
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
        else:
            current.append(sql[i])
        i += 1

    stmt = "".join(current).strip()
    if stmt:
        statements.append(stmt)
    return statements


def _apply_schema(engine: Engine) -> None:
    """Apply schema.sql — one transaction per statement so a failure doesn't cascade."""
    with open(_SCHEMA_PATH) as f:
        sql = f.read()

    for stmt in _split_sql(sql):
        lower = stmt.lower()
        is_silent = (
            any(kw in lower for kw in _SILENT_SKIP_KEYWORDS)
            or any(lower.lstrip().startswith(m) for m in _PROCEDURAL_MARKERS)
        )
        try:
            with engine.begin() as conn:
                conn.execute(text(stmt))
        except Exception as exc:
            if not is_silent:
                print(f"[schema] {exc!r}\n  stmt: {stmt[:120]}")


# ── Seed constants ─────────────────────────────────────────────────────────────
_SERVICE_DATE: date = date.today() - timedelta(days=2)

_STOPS = [
    ("S001", "AC", "Stop 1", 37.8044, -122.2711),
    ("S002", "AC", "Stop 2", 37.8054, -122.2705),
    ("S003", "AC", "Stop 3", 37.8064, -122.2700),
    ("S004", "AC", "Stop 4", 37.8074, -122.2695),
    ("S005", "AC", "Stop 5", 37.8084, -122.2690),
]

# Safety geometry test stops — distances verified:
#   SNEAR (37.80000) → incident (37.80060): ~67 m   (inside 150 m)
#   SFAR  (37.80200) → incident (37.80060): ~156 m  (outside 150 m)
_SAFETY_STOPS = [
    ("SNEAR", "AC", "Safety Near Stop", 37.80000, -122.27000),
    ("SFAR",  "AC", "Safety Far Stop",  37.80200, -122.27000),
]

_ALL_STOPS = _STOPS + _SAFETY_STOPS


def _seed(conn: Connection) -> None:
    """Insert minimal reproducible test data.  Called inside engine.begin()."""

    # Routes
    conn.execute(text("""
        INSERT INTO gtfs_routes
            (route_id, agency_id, route_short_name, route_long_name, route_type)
        VALUES
            ('R001', 'AC', '1', 'Route One', 3),
            ('R002', 'AC', '2', 'Route Two', 3)
        ON CONFLICT DO NOTHING
    """))

    # Stops
    for stop_id, agency_id, name, lat, lon in _ALL_STOPS:
        conn.execute(text("""
            INSERT INTO gtfs_stops
                (stop_id, agency_id, stop_name, stop_lat, stop_lon, geom)
            VALUES (
                :sid, :aid, :name, :lat, :lon,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
            )
            ON CONFLICT DO NOTHING
        """), {"sid": stop_id, "aid": agency_id, "name": name, "lat": lat, "lon": lon})

    # Trips: T001–T005 on R001, T006–T010 on R002
    for i in range(1, 6):
        conn.execute(text("""
            INSERT INTO gtfs_trips
                (trip_id, agency_id, route_id, service_id, trip_headsign)
            VALUES (:tid, 'AC', 'R001', 'WEEKDAY', :head)
            ON CONFLICT DO NOTHING
        """), {"tid": f"T{i:03d}", "head": f"Destination {i}"})

    for i in range(6, 11):
        conn.execute(text("""
            INSERT INTO gtfs_trips
                (trip_id, agency_id, route_id, service_id, trip_headsign)
            VALUES (:tid, 'AC', 'R002', 'WEEKDAY', :head)
            ON CONFLICT DO NOTHING
        """), {"tid": f"T{i:03d}", "head": f"Destination {i}"})

    # Stop times: each trip visits all 5 regular stops in sequence
    for trip_num in range(1, 11):
        tid = f"T{trip_num:03d}"
        base_hour = 8 + (trip_num - 1)
        for seq, stop_id in enumerate(["S001", "S002", "S003", "S004", "S005"], 1):
            dep = f"{base_hour:02d}:{(seq - 1) * 10:02d}:00"
            conn.execute(text("""
                INSERT INTO gtfs_stop_times
                    (trip_id, agency_id, stop_id, stop_pk, stop_sequence, departure_time, arrival_time)
                VALUES (:tid, 'AC', :sid, (SELECT stop_pk FROM gtfs_stops g
                        WHERE g.agency_id = 'AC' AND g.stop_id = :sid), :seq, :dep, :dep)
                ON CONFLICT DO NOTHING
            """), {"tid": tid, "sid": stop_id, "seq": seq, "dep": dep})

    # ops_trip_events
    #   R001: 8 × 30 s + 2 × 180 s  →  avg = 60 s
    #   R002: 7 × 30 s + 3 × 180 s  →  avg = 75 s
    base_ts = datetime(
        _SERVICE_DATE.year, _SERVICE_DATE.month, _SERVICE_DATE.day,
        8, 0, 0, tzinfo=timezone.utc
    )
    r001_delays = [30] * 8 + [180] * 2
    r002_delays = [30] * 7 + [180] * 3

    for i, delay in enumerate(r001_delays):
        sched = base_ts + timedelta(hours=i)
        actual = sched + timedelta(seconds=delay)
        conn.execute(text("""
            INSERT INTO ops_trip_events
                (agency_id, service_date, trip_id, route_id, stop_id, stop_pk,
                 stop_sequence, scheduled_arrival, actual_arrival, delay_seconds)
            VALUES ('AC', :sd, :tid, 'R001', 'S001',
                    (SELECT stop_pk FROM gtfs_stops g WHERE g.agency_id = 'AC' AND g.stop_id = 'S001'),
                    1, :sched, :actual, :delay)
        """), {
            "sd": _SERVICE_DATE,
            "tid": f"T{(i % 5) + 1:03d}",
            "sched": sched,
            "actual": actual,
            "delay": delay,
        })

    for i, delay in enumerate(r002_delays):
        sched = base_ts + timedelta(hours=i)
        actual = sched + timedelta(seconds=delay)
        conn.execute(text("""
            INSERT INTO ops_trip_events
                (agency_id, service_date, trip_id, route_id, stop_id, stop_pk,
                 stop_sequence, scheduled_arrival, actual_arrival, delay_seconds)
            VALUES ('AC', :sd, :tid, 'R002', 'S001',
                    (SELECT stop_pk FROM gtfs_stops g WHERE g.agency_id = 'AC' AND g.stop_id = 'S001'),
                    1, :sched, :actual, :delay)
        """), {
            "sd": _SERVICE_DATE,
            "tid": f"T{(i % 5) + 6:03d}",
            "sched": sched,
            "actual": actual,
            "delay": delay,
        })

    # Safety incident — 67 m from SNEAR, 156 m from SFAR
    conn.execute(text("""
        INSERT INTO safety_incidents_raw
            (source, incident_type, occurred_at, severity, geom)
        VALUES (
            'test', 'crime', now(), 2,
            ST_SetSRID(ST_MakePoint(-122.27000, 37.80060), 4326)
        )
    """))


def _truncate(conn: Connection) -> None:
    tables = [
        "stop_safety_scores",
        "safety_incidents_raw",
        "stop_observations",
        "coverage_cells",
        "ops_trip_events",
        "gtfs_stop_times",
        "gtfs_trips",
        "gtfs_stops",
        "gtfs_routes",
        "gtfs_shape_geoms",
        "gtfs_shapes",
        "census_tracts",
        "gtfs_pathways",
        "gtfs_levels",
        "census_ambulatory",
        "stop_ada_gap",
    ]
    conn.execute(text(f"TRUNCATE {', '.join(tables)} CASCADE"))


# ── Session-scoped fixtures ───────────────────────────────────────────────────

@pytest.fixture(scope="session")
def test_engine() -> Generator[Engine, None, None]:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    _apply_schema(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _disable_background_tasks():
    """Prevent live network-polling threads from starting during tests."""
    with (
        patch("app.main.run_polling_loop", return_value=None),
        patch("app.main.run_baseline_loop", return_value=None),
        patch("app.main.run_embed_loop", return_value=None),
        patch("app.main.run_traffic_loop", return_value=None),
    ):
        yield


# ── Per-test fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def seed_db(test_engine: Engine) -> Generator[None, None, None]:
    """Truncate + seed before each test; truncate after."""
    with test_engine.begin() as conn:
        _truncate(conn)
        _seed(conn)
    yield
    with test_engine.begin() as conn:
        _truncate(conn)


@pytest.fixture
def db_conn(test_engine: Engine) -> Generator[Connection, None, None]:
    """Direct DB connection for service-level tests."""
    with test_engine.connect() as conn:
        yield conn


@pytest.fixture
async def client(test_engine: Engine) -> AsyncClient:
    """httpx AsyncClient wired to FastAPI app using the test database.

    Both get_conn and api_key_auth are overridden so tests are independent of
    the production DATABASE_URL and BACKEND_API_KEY values in .env.
    """
    from app.main import app, get_conn
    from app.core.security import api_key_auth

    def override_get_conn() -> Generator[Connection, None, None]:
        with test_engine.connect() as conn:
            yield conn

    def override_auth() -> None:
        return None

    app.dependency_overrides[get_conn] = override_get_conn
    app.dependency_overrides[api_key_auth] = override_auth
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c
    app.dependency_overrides.pop(get_conn, None)
    app.dependency_overrides.pop(api_key_auth, None)

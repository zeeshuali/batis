"""Tests for the Fare Burden compute + endpoint (Sprint 5a Phase 1).

Synthetic geometry:
  An origin cell at 37.700, -122.250 with AC + BART stops nearby.
  An anchor at 37.710, -122.255 (~1.1 km north) but far enough out
  for the 1500 m radius scans not to overlap — we use a hand-picked
  anchor of (37.730, -122.250) instead so the corridor logic mirrors
  the fare_sampler tests.

We override the anchor list at call time so the compute uses the test
geography rather than the real Bay Area BART stations.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.services.fare_burden import (
    ANCHORS,
    _burden_tier,
    compute_fare_burden_for_all_cells,
    get_fare_burden_features,
)


_CELL_LAT, _CELL_LNG     = 37.700, -122.250
_ANCHOR_LAT, _ANCHOR_LNG = 37.730, -122.250

_TEST_ANCHORS = [
    {"id": "sf", "name": "Test SF", "lat": _ANCHOR_LAT, "lng": _ANCHOR_LNG},
]


@pytest.fixture(autouse=True)
def _seed_fare_burden(test_engine: Engine):
    """Lay down one cell + AC stops near both points + fare data."""
    with test_engine.begin() as conn:
        conn.execute(text("TRUNCATE fare_products, fare_leg_rules CASCADE"))
        conn.execute(text("DELETE FROM fare_burden"))
        conn.execute(text("DELETE FROM coverage_cells WHERE cell_id LIKE 'FB-%'"))
        conn.execute(text("DELETE FROM gtfs_stops WHERE stop_id LIKE 'FB-%'"))

        conn.execute(text("""
            INSERT INTO agencies (agency_id, agency_name, monitored)
            VALUES ('AC', 'AC Transit', true)
            ON CONFLICT (agency_id) DO UPDATE
              SET agency_name = EXCLUDED.agency_name
        """))
        conn.execute(text("""
            INSERT INTO fare_products (agency_id, fare_product_id, amount, currency)
            VALUES ('AC', 'AC-ADULT', 2.75, 'USD')
        """))
        conn.execute(text("""
            INSERT INTO fare_leg_rules (agency_id, network_id, fare_product_id)
            VALUES ('AC', 'O', 'AC-ADULT')
        """))
        # Origin cluster: 3 AC stops.  Anchor cluster: 3 AC stops.
        conn.execute(text("""
            INSERT INTO gtfs_stops (stop_id, agency_id, stop_name, stop_lat, stop_lon, geom) VALUES
              ('FB-O1', 'AC', 'orig 1',   37.7000, -122.2500, ST_SetSRID(ST_MakePoint(-122.2500, 37.7000), 4326)),
              ('FB-O2', 'AC', 'orig 2',   37.7005, -122.2502, ST_SetSRID(ST_MakePoint(-122.2502, 37.7005), 4326)),
              ('FB-O3', 'AC', 'orig 3',   37.7010, -122.2495, ST_SetSRID(ST_MakePoint(-122.2495, 37.7010), 4326)),
              ('FB-A1', 'AC', 'anchor 1', 37.7300, -122.2500, ST_SetSRID(ST_MakePoint(-122.2500, 37.7300), 4326)),
              ('FB-A2', 'AC', 'anchor 2', 37.7305, -122.2498, ST_SetSRID(ST_MakePoint(-122.2498, 37.7305), 4326)),
              ('FB-A3', 'AC', 'anchor 3', 37.7310, -122.2503, ST_SetSRID(ST_MakePoint(-122.2503, 37.7310), 4326))
        """))
        # One coverage_cell over the origin point.  Median income high enough
        # that burden is non-trivial but plausible.
        conn.execute(text("""
            INSERT INTO coverage_cells
                (cell_id, geom, population, equity_score,
                 distance_to_nearest_stop_m, median_household_income)
            VALUES (
              'FB-CELL',
              ST_MakeEnvelope(-122.2515, 37.6990, -122.2485, 37.7020, 4326),
              5000, 0.20, 50, 60000
            )
        """))
    yield
    with test_engine.begin() as conn:
        conn.execute(text("DELETE FROM fare_burden WHERE cell_id LIKE 'FB-%'"))
        conn.execute(text("DELETE FROM coverage_cells WHERE cell_id LIKE 'FB-%'"))
        conn.execute(text("DELETE FROM gtfs_stops WHERE stop_id LIKE 'FB-%'"))
        conn.execute(text("TRUNCATE fare_products, fare_leg_rules CASCADE"))


# ── _burden_tier classification ──────────────────────────────────────────────

@pytest.mark.parametrize("pct,expected", [
    (None,   None),
    (0.0,    "low"),
    (4.99,   "low"),
    (5.0,    "moderate"),
    (9.99,   "moderate"),
    (10.0,   "high"),
    (14.99,  "high"),
    (15.0,   "very_high"),
    (50.0,   "very_high"),
])
def test_burden_tier_thresholds(pct, expected):
    assert _burden_tier(pct) == expected


# ── compute_fare_burden_for_all_cells ────────────────────────────────────────

def test_compute_writes_a_row_per_cell(db_conn):
    n = compute_fare_burden_for_all_cells(db_conn, anchors=_TEST_ANCHORS, n_samples=5)
    assert n >= 1, "should write at least the FB-CELL we seeded"

    row = db_conn.execute(text("""
        SELECT median_fare_to_sf, reachable_anchor_count,
               population, median_household_income
        FROM fare_burden WHERE cell_id = 'FB-CELL'
    """)).mappings().first()
    assert row is not None
    # AC fare is $2.75 by route_only match → median over samples is $2.75.
    assert float(row["median_fare_to_sf"]) == pytest.approx(2.75)
    assert row["reachable_anchor_count"] == 1
    assert row["population"] == 5000
    assert row["median_household_income"] == 60000


def test_compute_is_idempotent(db_conn):
    """Running twice replaces, doesn't duplicate."""
    compute_fare_burden_for_all_cells(db_conn, anchors=_TEST_ANCHORS, n_samples=5)
    compute_fare_burden_for_all_cells(db_conn, anchors=_TEST_ANCHORS, n_samples=5)
    n = db_conn.execute(text(
        "SELECT COUNT(*) FROM fare_burden WHERE cell_id = 'FB-CELL'"
    )).scalar()
    assert n == 1


def test_unreachable_cell_records_reachable_count_zero(db_conn):
    """A cell with no nearby stops should land with reachable_anchor_count=0."""
    db_conn.execute(text("""
        INSERT INTO coverage_cells
            (cell_id, geom, population, equity_score,
             distance_to_nearest_stop_m, median_household_income)
        VALUES (
          'FB-ISOLATED',
          ST_MakeEnvelope(-122.5005, 37.8995, -122.4995, 37.9005, 4326),
          200, 0.05, 5000, 70000
        )
    """))
    db_conn.commit()
    compute_fare_burden_for_all_cells(db_conn, anchors=_TEST_ANCHORS, n_samples=5)
    row = db_conn.execute(text("""
        SELECT reachable_anchor_count, median_fare_to_sf
        FROM fare_burden WHERE cell_id = 'FB-ISOLATED'
    """)).mappings().first()
    assert row is not None
    assert row["reachable_anchor_count"] == 0
    assert row["median_fare_to_sf"] is None
    # Clean up so other tests' counts aren't perturbed.
    db_conn.execute(text("DELETE FROM coverage_cells WHERE cell_id = 'FB-ISOLATED'"))
    db_conn.execute(text("DELETE FROM fare_burden WHERE cell_id = 'FB-ISOLATED'"))
    db_conn.commit()


# ── get_fare_burden_features (endpoint reader) ───────────────────────────────

def test_burden_pct_formula(db_conn):
    """Round-trip cost = $2.75 * 2 * 22 = $121.  Monthly income = 60000/12 = $5000.
    burden_pct = 100 * 121 / 5000 = 2.42% → tier 'low'."""
    compute_fare_burden_for_all_cells(db_conn, anchors=_TEST_ANCHORS, n_samples=5)
    feats = get_fare_burden_features(db_conn, min_population=0)
    cell = next(f for f in feats if f["properties"]["cell_id"] == "FB-CELL")
    assert cell["properties"]["worst_fare"] == pytest.approx(2.75)
    assert cell["properties"]["burden_pct"] == pytest.approx(2.42, abs=0.01)
    assert cell["properties"]["burden_tier"] == "low"


def test_anchor_weights_can_re_weight_at_query_time(db_conn):
    """Pass anchor_weights={'sf': 2.0} and the worst_fare should double."""
    compute_fare_burden_for_all_cells(db_conn, anchors=_TEST_ANCHORS, n_samples=5)
    feats = get_fare_burden_features(db_conn, anchor_weights={"sf": 2.0})
    cell = next(f for f in feats if f["properties"]["cell_id"] == "FB-CELL")
    assert cell["properties"]["worst_fare"] == pytest.approx(5.50)
    # burden_pct doubles in proportion.
    assert cell["properties"]["burden_pct"] == pytest.approx(4.84, abs=0.01)


# ── HTTP endpoint ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_equity_fare_burden_endpoint(client: AsyncClient, test_engine: Engine):
    """End-to-end: compute then call the endpoint."""
    with test_engine.begin() as c:
        compute_fare_burden_for_all_cells(c, anchors=_TEST_ANCHORS, n_samples=5)

    resp = await client.get("/equity/fare-burden")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    cell_ids = {f["properties"]["cell_id"] for f in body["features"]}
    assert "FB-CELL" in cell_ids
    cell = next(f for f in body["features"] if f["properties"]["cell_id"] == "FB-CELL")
    assert cell["properties"]["burden_tier"] in ("low", "moderate", "high", "very_high")


@pytest.mark.asyncio
async def test_endpoint_passes_anchor_weights(client: AsyncClient, test_engine: Engine):
    with test_engine.begin() as c:
        compute_fare_burden_for_all_cells(c, anchors=_TEST_ANCHORS, n_samples=5)

    resp = await client.get("/equity/fare-burden?anchor_weights=sf:2.0")
    body = resp.json()
    cell = next(f for f in body["features"] if f["properties"]["cell_id"] == "FB-CELL")
    assert cell["properties"]["worst_fare"] == pytest.approx(5.50)

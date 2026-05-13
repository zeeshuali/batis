import pytest
from sqlalchemy import text

from app.services.ada_accessibility_gap import _gap_tier, _supply_penalty


# ── _supply_penalty ──────────────────────────────────────────────────────────

def test_supply_penalty_accessible():
    # wheelchair_boarding=1 means accessible → 0.0 (regardless of pathways)
    assert _supply_penalty(1, has_accessible_pathway=True, location_type=0) == 0.0
    assert _supply_penalty(1, has_accessible_pathway=None, location_type=1) == 0.0


def test_supply_penalty_not_accessible():
    # wheelchair_boarding=2 means not accessible → 1.0
    assert _supply_penalty(2, has_accessible_pathway=True, location_type=0) == 1.0


def test_supply_penalty_unknown():
    # wheelchair_boarding=0 / None means unknown → 0.5
    assert _supply_penalty(0, has_accessible_pathway=None, location_type=0) == 0.5
    assert _supply_penalty(None, has_accessible_pathway=None, location_type=0) == 0.5


def test_supply_penalty_pathways_override_rail_only():
    # Rail station with explicit pathways data, no accessible path:
    # override to 1.0 regardless of wheelchair_boarding.
    assert _supply_penalty(1, has_accessible_pathway=False, location_type=1) == 1.0
    assert _supply_penalty(1, has_accessible_pathway=False, location_type=2) == 1.0
    # Bus stop with the same flag should NOT override.
    assert _supply_penalty(1, has_accessible_pathway=False, location_type=0) == 0.0


def test_supply_penalty_pathways_override_only_when_explicit_false():
    # has_accessible_pathway = None means "no pathways data for this stop"
    # — do not override; fall through to wheelchair_boarding.
    assert _supply_penalty(1, has_accessible_pathway=None, location_type=1) == 0.0
    assert _supply_penalty(2, has_accessible_pathway=None, location_type=1) == 1.0


# ── _gap_tier ────────────────────────────────────────────────────────────────

def test_gap_tier_zero_is_low():
    # Already-accessible stops have gap_score = 0; always 'low'.
    assert _gap_tier(0.0, p90=100, p75=50, p50=20) == "low"


def test_gap_tier_percentile_bands():
    # gap_score >= p90 → very_high
    assert _gap_tier(150.0, p90=100, p75=50, p50=20) == "very_high"
    # p75 <= gap_score < p90 → high
    assert _gap_tier(75.0,  p90=100, p75=50, p50=20) == "high"
    # p50 <= gap_score < p75 → moderate
    assert _gap_tier(30.0,  p90=100, p75=50, p50=20) == "moderate"
    # gap_score < p50 → low
    assert _gap_tier(5.0,   p90=100, p75=50, p50=20) == "low"


def test_gap_tier_boundaries_inclusive_at_lower_edge():
    # Exactly at p90 → very_high (>=)
    assert _gap_tier(100.0, p90=100, p75=50, p50=20) == "very_high"
    assert _gap_tier(50.0,  p90=100, p75=50, p50=20) == "high"
    assert _gap_tier(20.0,  p90=100, p75=50, p50=20) == "moderate"


# ── Integration: compute_stop_ada_gap_for_all_stops + refresh_cell_ada_gap ───

from app.services.ada_accessibility_gap import (
    compute_stop_ada_gap_for_all_stops,
    refresh_cell_ada_gap,
)


@pytest.fixture
def ada_fixture(db_conn):
    """Seed 4 stops in 2 tracts and 2 cells:

      stop-A: wheelchair_boarding=2, in tract T1 (amb_pop=300) → high score
      stop-B: wheelchair_boarding=1, in tract T1                → score 0
      stop-C: wheelchair_boarding=0, in tract T2 (amb_pop=100) → mid score
      stop-D: wheelchair_boarding=1, location_type=1, has_pathways but
              no accessible path → Pathways override fires.
    """
    try:
        # Tract geometry — two tiny squares well-separated so a 400m buffer
        # at stop-A doesn't reach test-T2 etc.
        db_conn.execute(text("""
          INSERT INTO census_tracts (tract_geoid, county_fips, geom, computed_at)
          VALUES
            ('test-T1', '001',
              ST_Multi(ST_GeomFromText('POLYGON((0 0, 0 0.01, 0.01 0.01, 0.01 0, 0 0))', 4326)),
              now()),
            ('test-T2', '001',
              ST_Multi(ST_GeomFromText('POLYGON((1 0, 1 0.01, 1.01 0.01, 1.01 0, 1 0))', 4326)),
              now())
          ON CONFLICT (tract_geoid) DO NOTHING
        """))

        # Demand data
        db_conn.execute(text("""
          INSERT INTO census_ambulatory (tract_geoid, ambulatory_pop, total_pop, computed_at)
          VALUES
            ('test-T1', 300, 1000, now()),
            ('test-T2', 100, 1000, now())
          ON CONFLICT (tract_geoid) DO UPDATE
            SET ambulatory_pop = EXCLUDED.ambulatory_pop
        """))

        # Stops — coords chosen so each stop's 400m buffer intersects its
        # tract but not the other.
        rows = [
            ("test-stop-A", "TESTADA", 2, 0,   0.005, 0.005),
            ("test-stop-B", "TESTADA", 1, 0,   0.006, 0.005),
            ("test-stop-C", "TESTADA", 0, 0,   1.005, 0.005),
            ("test-stop-D", "TESTADA", 1, 1,   0.0055, 0.0055),
        ]
        for sid, aid, wb, lt, lon, lat in rows:
            db_conn.execute(text("""
              INSERT INTO gtfs_stops
                (stop_id, agency_id, stop_name, location_type,
                 wheelchair_boarding, geom)
              VALUES (:sid, :aid, 'Test', :lt, :wb,
                      ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
              ON CONFLICT (stop_id) DO UPDATE
                SET location_type        = EXCLUDED.location_type,
                    wheelchair_boarding  = EXCLUDED.wheelchair_boarding,
                    geom                 = EXCLUDED.geom
            """), {"sid": sid, "aid": aid, "lt": lt, "wb": wb,
                   "lon": lon, "lat": lat})

        # Pathways for stop-D: stairs-only edge → has_accessible_pathway=False
        db_conn.execute(text("""
          INSERT INTO gtfs_pathways
            (agency_id, pathway_id, from_stop_id, to_stop_id, pathway_mode)
          VALUES ('TESTADA', 'pwD', 'test-stop-D', 'test-stop-D-platform', 2)
          ON CONFLICT (agency_id, pathway_id) DO NOTHING
        """))

        # Seed a coverage_cell for the cell rollup test.
        # The cell polygon fully contains stops A, B, and D
        # (all near (0.005-0.006, 0.005-0.006)).
        # coverage_cells has no unique constraint on cell_id so we cannot use
        # ON CONFLICT; seed_db truncates the table before each test so a plain
        # INSERT is safe.
        db_conn.execute(text("""
          INSERT INTO coverage_cells (cell_id, geom, population, equity_score)
          VALUES ('test-cellA',
                  ST_GeomFromText('POLYGON((0 0, 0 0.02, 0.02 0.02, 0.02 0, 0 0))', 4326),
                  500, 0.4)
        """))

        db_conn.commit()

        # Refresh stop_cell so the new coverage_cells + stops are reflected.
        db_conn.execute(text("REFRESH MATERIALIZED VIEW stop_cell"))
        db_conn.commit()

        yield rows
    finally:
        db_conn.execute(text("DELETE FROM stop_ada_gap WHERE stop_id LIKE 'test-stop-%'"))
        db_conn.execute(text("DELETE FROM gtfs_pathways WHERE agency_id = 'TESTADA'"))
        db_conn.execute(text("DELETE FROM gtfs_stops WHERE stop_id LIKE 'test-stop-%'"))
        db_conn.execute(text("DELETE FROM census_ambulatory WHERE tract_geoid LIKE 'test-T%'"))
        db_conn.execute(text("DELETE FROM census_tracts WHERE tract_geoid LIKE 'test-T%'"))
        db_conn.execute(text("DELETE FROM coverage_cells WHERE cell_id = 'test-cellA'"))
        db_conn.commit()
        # Re-refresh so the materialized view doesn't hold stale test data
        db_conn.execute(text("REFRESH MATERIALIZED VIEW stop_cell"))
        db_conn.commit()


def test_compute_writes_per_stop_rows(db_conn, ada_fixture):
    n = compute_stop_ada_gap_for_all_stops(db_conn)
    db_conn.commit()
    assert n >= 4   # at least our 4 seeded stops

    rows = db_conn.execute(text(
        "SELECT stop_id, supply_penalty, ambulatory_pop_400m, pathways_override "
        "FROM stop_ada_gap WHERE stop_id LIKE 'test-stop-%' ORDER BY stop_id"
    )).all()
    by_stop = {r[0]: r for r in rows}

    # stop-A: wheelchair_boarding=2 → supply_penalty=1.0
    assert float(by_stop["test-stop-A"][1]) == 1.0
    # stop-B: wheelchair_boarding=1, no pathways override → 0.0
    assert float(by_stop["test-stop-B"][1]) == 0.0
    # stop-C: wheelchair_boarding=0 → 0.5
    assert float(by_stop["test-stop-C"][1]) == 0.5
    # stop-D: pathways override (rail + stairs-only) → 1.0
    assert float(by_stop["test-stop-D"][1]) == 1.0
    assert by_stop["test-stop-D"][3] is True   # pathways_override=true


def test_compute_gap_score_is_supply_times_demand(db_conn, ada_fixture):
    compute_stop_ada_gap_for_all_stops(db_conn)
    db_conn.commit()
    row = db_conn.execute(text(
        "SELECT supply_penalty, ambulatory_pop_400m, gap_score "
        "FROM stop_ada_gap WHERE stop_id = 'test-stop-A'"
    )).fetchone()
    assert row is not None
    sp, demand, score = float(row[0]), int(row[1]), float(row[2])
    assert score == round(sp * demand, 2)


def test_compute_is_idempotent(db_conn, ada_fixture):
    n1 = compute_stop_ada_gap_for_all_stops(db_conn); db_conn.commit()
    n2 = compute_stop_ada_gap_for_all_stops(db_conn); db_conn.commit()
    assert n1 == n2

    cnt = db_conn.execute(text(
        "SELECT COUNT(*) FROM stop_ada_gap WHERE stop_id LIKE 'test-stop-%'"
    )).scalar()
    assert cnt == 4   # not 8


def test_refresh_cell_ada_gap_populates_view(db_conn, ada_fixture):
    compute_stop_ada_gap_for_all_stops(db_conn)
    db_conn.commit()
    refresh_cell_ada_gap(db_conn)
    db_conn.commit()

    row = db_conn.execute(text(
        "SELECT stop_count, max_gap_score, worst_tier "
        "FROM cell_ada_gap WHERE cell_id = 'test-cellA'"
    )).fetchone()
    assert row is not None
    assert row[0] == 3   # A, B, D mapped to this cell
    # max gap_score in test-cellA is whichever of A (1.0×demand) or D
    # (1.0×demand) is larger; both > 0 → max > 0.
    assert float(row[1]) > 0


from app.services.ada_accessibility_gap import (
    get_stop_ada_gap_features,
)


def test_get_stop_ada_gap_features_returns_features(db_conn, ada_fixture):
    compute_stop_ada_gap_for_all_stops(db_conn)
    db_conn.commit()

    features = get_stop_ada_gap_features(db_conn, limit=5000)
    test_features = [f for f in features
                     if f["properties"]["stop_id"].startswith("test-stop-")]
    assert len(test_features) == 4

    sample = next(f for f in test_features
                  if f["properties"]["stop_id"] == "test-stop-A")
    props = sample["properties"]
    assert props["agency_id"] == "TESTADA"
    assert props["wheelchair_boarding"] == 2
    assert props["supply_penalty"] == 1.0
    assert props["gap_tier"] in {"low", "moderate", "high", "very_high"}
    assert "ambulatory_pop_400m" in props
    assert "gap_score" in props
    assert "pathways_override" in props
    assert "routes_serving" in props   # may be empty list
    assert sample["geometry"]["type"] == "Point"


def test_get_stop_ada_gap_features_sorted_desc(db_conn, ada_fixture):
    compute_stop_ada_gap_for_all_stops(db_conn)
    db_conn.commit()
    features = get_stop_ada_gap_features(db_conn, limit=50)
    scores = [float(f["properties"]["gap_score"]) for f in features]
    assert scores == sorted(scores, reverse=True)


def test_get_stop_ada_gap_features_tier_filter(db_conn, ada_fixture):
    compute_stop_ada_gap_for_all_stops(db_conn)
    db_conn.commit()
    features = get_stop_ada_gap_features(db_conn, tier="low", limit=5000)
    for f in features:
        assert f["properties"]["gap_tier"] == "low"


from app.services.ada_accessibility_gap import (
    get_cell_ada_gap_features,
)


def test_get_cell_ada_gap_features_returns_cells(db_conn, ada_fixture):
    compute_stop_ada_gap_for_all_stops(db_conn)
    db_conn.commit()
    refresh_cell_ada_gap(db_conn)
    db_conn.commit()

    features = get_cell_ada_gap_features(db_conn, min_population=0, limit=5000)
    test_cell = next(
        (f for f in features
         if f["properties"]["cell_id"] == "test-cellA"), None)
    assert test_cell is not None
    props = test_cell["properties"]
    assert props["stop_count"] == 3
    assert props["max_gap_score"] is not None
    assert props["worst_tier"] in {"low", "moderate", "high", "very_high"}
    assert "population" in props
    assert "equity_score" in props
    assert test_cell["geometry"]["type"] == "Polygon"


from app.services.ada_accessibility_gap import (
    get_stop_ada_gap_breakdown,
)


def test_get_stop_ada_gap_breakdown_returns_stop_meta(db_conn, ada_fixture):
    compute_stop_ada_gap_for_all_stops(db_conn)
    db_conn.commit()

    breakdown = get_stop_ada_gap_breakdown(db_conn, "test-stop-A")
    assert breakdown["stop_id"] == "test-stop-A"
    assert breakdown["agency_id"] == "TESTADA"
    assert breakdown["stop_name"] == "Test"
    assert "gap_score" in breakdown
    assert "gap_tier" in breakdown
    assert "supply_penalty" in breakdown
    assert "pathways_override" in breakdown
    assert "routes" in breakdown
    assert "tracts" in breakdown


def test_get_stop_ada_gap_breakdown_tracts_within_buffer(db_conn, ada_fixture):
    compute_stop_ada_gap_for_all_stops(db_conn)
    db_conn.commit()

    breakdown = get_stop_ada_gap_breakdown(db_conn, "test-stop-A")
    tract_ids = {t["tract_geoid"] for t in breakdown["tracts"]}
    # stop-A is at (0.005, 0.005) — buffer should reach test-T1.
    assert "test-T1" in tract_ids


def test_get_stop_ada_gap_breakdown_unknown_stop_returns_empty(db_conn, ada_fixture):
    compute_stop_ada_gap_for_all_stops(db_conn)
    db_conn.commit()
    breakdown = get_stop_ada_gap_breakdown(db_conn, "does-not-exist-xyz")
    assert breakdown.get("stop_id") in (None, "does-not-exist-xyz")
    assert breakdown.get("routes")  == []
    assert breakdown.get("tracts")  == []

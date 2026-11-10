"""Regression: loader must not clobber Agency A's data when Agency B
loads a feed sharing route_id / stop_id / trip_id / shape_id values.

Guards the bug that prompted migration 009: 47% of route_ids in
gtfs_routes were misattributed because single-column PKs let a second
agency's upsert silently overwrite the first.

These tests don't invoke the real loader (which would require an HTTP
fetch). They exercise the composite ON CONFLICT semantics directly with
the same SQL shapes the loader emits.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def test_two_agencies_sharing_route_id_keep_both_rows(db_conn):
    """Two agencies both using route_id '31' must coexist. Pre-009, the
    second insert silently overwrote the first."""
    try:
        db_conn.execute(text("""
          INSERT INTO gtfs_routes (route_id, agency_id, route_short_name,
                                   route_long_name, route_type)
          VALUES ('31', 'TST_A', 'A31', 'A line 31', 3),
                 ('31', 'TST_B', 'B31', 'B line 31', 3)
          ON CONFLICT (agency_id, route_id) DO UPDATE
            SET route_short_name = EXCLUDED.route_short_name
        """))
        rows = db_conn.execute(text(
          "SELECT agency_id, route_short_name FROM gtfs_routes "
          "WHERE route_id = '31' AND agency_id LIKE 'TST_%'"
        )).all()
        assert {(r[0], r[1]) for r in rows} == {
            ("TST_A", "A31"), ("TST_B", "B31")
        }
    finally:
        db_conn.execute(text(
          "DELETE FROM gtfs_routes WHERE agency_id LIKE 'TST_%'"
        ))


def test_two_agencies_sharing_stop_id_keep_both_with_distinct_stop_pk(db_conn):
    """Migration 010: gtfs_stops PK is the surrogate stop_pk, so two agencies
    may reuse the same agency-assigned stop_id (e.g. DE/MA/MV vs others)."""
    try:
        db_conn.execute(text("""
          INSERT INTO gtfs_stops (stop_id, agency_id, stop_name,
                                  stop_lat, stop_lon)
          VALUES ('TST_S1', 'TST_A', 'Stop 1', 37.8, -122.3),
                 ('TST_S1', 'TST_B', 'Stop 1 again', 37.9, -122.2)
          ON CONFLICT (agency_id, stop_id) DO NOTHING
        """))
        rows = db_conn.execute(text(
          "SELECT agency_id, stop_name, stop_pk FROM gtfs_stops "
          "WHERE stop_id = 'TST_S1' AND agency_id LIKE 'TST_%'"
        )).all()
        assert {(r[0], r[1]) for r in rows} == {
            ("TST_A", "Stop 1"), ("TST_B", "Stop 1 again")
        }
        assert len({r[2] for r in rows}) == 2  # distinct surrogate keys
    finally:
        db_conn.execute(text(
          "DELETE FROM gtfs_stops WHERE agency_id LIKE 'TST_%'"
        ))


def test_same_agency_duplicate_stop_id_is_rejected(db_conn):
    """The natural key (agency_id, stop_id) must stay unique within an agency
    so a reload upserts instead of duplicating."""
    try:
        db_conn.execute(text("""
          INSERT INTO gtfs_stops (stop_id, agency_id, stop_name)
          VALUES ('TST_S2', 'TST_A', 'Stop 2')
        """))
        with pytest.raises(IntegrityError):
            db_conn.execute(text("""
              INSERT INTO gtfs_stops (stop_id, agency_id, stop_name)
              VALUES ('TST_S2', 'TST_A', 'Stop 2 dup')
            """))
    finally:
        db_conn.rollback()
        db_conn.execute(text(
          "DELETE FROM gtfs_stops WHERE agency_id LIKE 'TST_%'"
        ))


def test_stop_times_reference_the_right_agencys_stop_via_stop_pk(db_conn):
    """stop_times.stop_pk must point at the owning agency's stop, even when
    another agency has a stop with the same stop_id."""
    try:
        db_conn.execute(text("""
          INSERT INTO gtfs_routes (route_id, agency_id, route_type)
          VALUES ('R1', 'TST_A', 3) ON CONFLICT DO NOTHING
        """))
        db_conn.execute(text("""
          INSERT INTO gtfs_trips (trip_id, agency_id, route_id, service_id)
          VALUES ('T1', 'TST_A', 'R1', 'WD') ON CONFLICT DO NOTHING
        """))
        db_conn.execute(text("""
          INSERT INTO gtfs_stops (stop_id, agency_id, stop_name)
          VALUES ('TST_S3', 'TST_A', 'A stop'), ('TST_S3', 'TST_B', 'B stop')
        """))
        pk_a = db_conn.execute(text(
          "SELECT stop_pk FROM gtfs_stops WHERE agency_id='TST_A' AND stop_id='TST_S3'"
        )).scalar()
        db_conn.execute(text("""
          INSERT INTO gtfs_stop_times (trip_id, agency_id, stop_id, stop_pk, stop_sequence)
          VALUES ('T1', 'TST_A', 'TST_S3', :pk, 1)
        """), {"pk": pk_a})
        name = db_conn.execute(text("""
          SELECT s.stop_name FROM gtfs_stop_times st
          JOIN gtfs_stops s ON s.stop_pk = st.stop_pk
          WHERE st.trip_id = 'T1' AND st.agency_id = 'TST_A'
        """)).scalar()
        assert name == "A stop"
    finally:
        db_conn.execute(text("DELETE FROM gtfs_stop_times WHERE agency_id LIKE 'TST_%'"))
        db_conn.execute(text("DELETE FROM gtfs_trips  WHERE agency_id LIKE 'TST_%'"))
        db_conn.execute(text("DELETE FROM gtfs_routes WHERE agency_id LIKE 'TST_%'"))
        db_conn.execute(text("DELETE FROM gtfs_stops  WHERE agency_id LIKE 'TST_%'"))


def test_two_agencies_sharing_trip_id_keep_both(db_conn):
    """trip_id collisions across agencies must keep both rows."""
    try:
        # Seed routes first so gtfs_trips_route_id_fkey (NOT VALID, but
        # validated for new rows) is satisfied.
        db_conn.execute(text("""
          INSERT INTO gtfs_routes (route_id, agency_id, route_short_name,
                                   route_long_name, route_type)
          VALUES ('R1', 'TST_A', 'A', 'A', 3),
                 ('R1', 'TST_B', 'B', 'B', 3)
          ON CONFLICT (agency_id, route_id) DO NOTHING
        """))
        db_conn.execute(text("""
          INSERT INTO gtfs_trips (trip_id, agency_id, route_id, service_id,
                                  trip_headsign)
          VALUES ('T1', 'TST_A', 'R1', 'WD', 'A trip'),
                 ('T1', 'TST_B', 'R1', 'WD', 'B trip')
          ON CONFLICT (agency_id, trip_id) DO NOTHING
        """))
        n = db_conn.execute(text(
          "SELECT COUNT(*) FROM gtfs_trips "
          "WHERE trip_id = 'T1' AND agency_id LIKE 'TST_%'"
        )).scalar()
        assert n == 2
    finally:
        db_conn.execute(text("DELETE FROM gtfs_trips  WHERE agency_id LIKE 'TST_%'"))
        db_conn.execute(text("DELETE FROM gtfs_routes WHERE agency_id LIKE 'TST_%'"))


def test_two_agencies_sharing_shape_id_keep_both(db_conn):
    """shape_id collisions across agencies must keep both rows in
    gtfs_shapes and gtfs_shape_geoms. gtfs_shapes only got agency_id
    in migration 009 — the loader had previously assumed shape_id was
    globally unique within a feed."""
    try:
        db_conn.execute(text("""
          INSERT INTO gtfs_shapes (shape_id, agency_id, shape_pt_lat,
                                   shape_pt_lon, shape_pt_sequence)
          VALUES ('SH1', 'TST_A', 37.8, -122.3, 1),
                 ('SH1', 'TST_B', 37.9, -122.2, 1)
          ON CONFLICT (agency_id, shape_id, shape_pt_sequence) DO NOTHING
        """))
        db_conn.execute(text("""
          INSERT INTO gtfs_shape_geoms (shape_id, agency_id, geom)
          VALUES ('SH1', 'TST_A',
                  ST_SetSRID(ST_MakeLine(
                    ST_MakePoint(-122.3, 37.8), ST_MakePoint(-122.31, 37.81)
                  ), 4326)),
                 ('SH1', 'TST_B',
                  ST_SetSRID(ST_MakeLine(
                    ST_MakePoint(-122.2, 37.9), ST_MakePoint(-122.21, 37.91)
                  ), 4326))
          ON CONFLICT (agency_id, shape_id) DO NOTHING
        """))
        n_shapes = db_conn.execute(text(
          "SELECT COUNT(*) FROM gtfs_shapes "
          "WHERE shape_id = 'SH1' AND agency_id LIKE 'TST_%'"
        )).scalar()
        n_shape_geoms = db_conn.execute(text(
          "SELECT COUNT(*) FROM gtfs_shape_geoms "
          "WHERE shape_id = 'SH1' AND agency_id LIKE 'TST_%'"
        )).scalar()
        assert n_shapes == 2
        assert n_shape_geoms == 2
    finally:
        db_conn.execute(text(
          "DELETE FROM gtfs_shape_geoms WHERE agency_id LIKE 'TST_%'"
        ))
        db_conn.execute(text(
          "DELETE FROM gtfs_shapes      WHERE agency_id LIKE 'TST_%'"
        ))

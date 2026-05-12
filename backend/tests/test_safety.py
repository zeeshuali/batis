"""
Tests for stop safety scoring geometry.

Verifies that the buffer uses geography (metric) units, not degrees.

Seed geometry (from conftest.py):
  SNEAR  37.80000, -122.27000  — should be within 150 m of the incident
  SFAR   37.80200, -122.27000  — ~222 m north, should be OUTSIDE 150 m
  Incident at 37.80060, -122.27000  — 67 m from SNEAR, 156 m from SFAR
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.services.safety_scoring import compute_stop_safety_scores


def test_safety_scoring_buffer_is_metric(db_conn: Connection):
    """SNEAR should capture the incident; SFAR should not."""
    with db_conn.begin():
        compute_stop_safety_scores(buffer_meters=150, conn=db_conn)

    near = db_conn.execute(
        text("SELECT crime_incidents_nearby FROM stop_safety_scores WHERE stop_id = 'SNEAR'")
    ).scalar()
    far = db_conn.execute(
        text("SELECT crime_incidents_nearby FROM stop_safety_scores WHERE stop_id = 'SFAR'")
    ).scalar()

    assert near == 1, (
        f"SNEAR (67 m from incident) should have crime_incidents_nearby=1, got {near}. "
        "Likely cause: ST_DWithin using degrees instead of metres (missing ::geography cast)."
    )
    assert far == 0, (
        f"SFAR (156 m from incident) should have crime_incidents_nearby=0, got {far}. "
        "Likely cause: buffer too large (degrees mode: 150° ≈ planet Earth)."
    )


def test_safety_scoring_larger_buffer_captures_far_stop(db_conn: Connection):
    """With buffer_meters=200 both stops should be inside."""
    with db_conn.begin():
        compute_stop_safety_scores(buffer_meters=200, conn=db_conn)

    far = db_conn.execute(
        text("SELECT crime_incidents_nearby FROM stop_safety_scores WHERE stop_id = 'SFAR'")
    ).scalar()
    assert far == 1, (
        "With 200 m buffer SFAR (156 m away) should have crime_incidents_nearby=1"
    )


def test_safety_scoring_populates_all_stops(db_conn: Connection):
    """Every stop in gtfs_stops should have a row in stop_safety_scores after scoring."""
    with db_conn.begin():
        compute_stop_safety_scores(buffer_meters=150, conn=db_conn)

    stop_count = db_conn.execute(text("SELECT COUNT(*) FROM gtfs_stops")).scalar()
    score_count = db_conn.execute(text("SELECT COUNT(*) FROM stop_safety_scores")).scalar()
    assert score_count == stop_count, (
        f"Expected {stop_count} score rows (one per stop), got {score_count}"
    )

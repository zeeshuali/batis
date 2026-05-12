"""Tests for equity score computation (coverage_cells.equity_score).

Verifies that populate_equity_columns() sets equity_score on every cell
and that Bay Area cells receive a positive score derived from Census data.

Seed geometry:
  All EC* cells are placed inside Alameda County's bounding box
  (-122.36, 37.45, -121.47, 37.88) so they get claimed by the county loop
  rather than the fallback default (0.5).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.services.equity_loader import populate_equity_columns

# Synthetic Census tract rows returned by the mocked _fetch_census for every county.
# Keys match the ACS variable names used in _aggregate_county().
_MOCK_TRACTS = [
    {
        "B17001_001E": "10000", "B17001_002E": "1500",
        "B08141_001E": "4000",  "B08141_002E": "600",
        "B01001_001E": "12000",
    },
    {
        "B17001_001E": "8000",  "B17001_002E": "2000",
        "B08141_001E": "3000",  "B08141_002E": "900",
        "B01001_001E": "9000",
    },
]
# Expected equity_score = (poverty_pct + no_veh_pct) / 2
#   poverty_pct = (1500+2000) / (10000+8000) = 3500/18000 ≈ 0.1944
#   no_veh_pct  = (600+900)  / (4000+3000)  = 1500/7000  ≈ 0.2143
#   equity_score ≈ 0.204
_EXPECTED_EQUITY = (3500 / 18000 + 1500 / 7000) / 2


def test_equity_score_not_null_after_populate(db_conn: Connection):
    """All coverage_cells must have equity_score set after populate_equity_columns()."""
    with db_conn.begin():
        # Insert three cells inside Alameda County bbox (-122.36...-121.47, 37.45...37.88)
        for cell_id, x0 in [("EC001", -121.93), ("EC002", -121.91), ("EC003", -121.89)]:
            db_conn.execute(
                text("""
                    INSERT INTO coverage_cells (cell_id, geom)
                    VALUES (:cid, ST_MakeEnvelope(:x0, 37.63, :x1, 37.65, 4326))
                """),
                {"cid": cell_id, "x0": x0, "x1": x0 + 0.02},
            )

        with patch(
            "app.services.equity_loader._fetch_census",
            return_value=_MOCK_TRACTS,
        ):
            populate_equity_columns(db_conn)

    null_count = db_conn.execute(
        text(
            "SELECT COUNT(*) FROM coverage_cells "
            "WHERE cell_id LIKE 'EC%' AND equity_score IS NULL"
        )
    ).scalar()
    assert null_count == 0, (
        f"{null_count} coverage_cells still have NULL equity_score after populate. "
        "Check the county spatial UPDATE loop and the fallback UPDATE in equity_loader.py."
    )


def test_equity_score_positive_for_bay_area_cells(db_conn: Connection):
    """Cells inside a Bay Area county bbox receive equity_score > 0."""
    with db_conn.begin():
        db_conn.execute(
            text("""
                INSERT INTO coverage_cells (cell_id, geom)
                VALUES ('EC_AL', ST_MakeEnvelope(-121.93, 37.63, -121.91, 37.65, 4326))
            """)
        )
        with patch(
            "app.services.equity_loader._fetch_census",
            return_value=_MOCK_TRACTS,
        ):
            populate_equity_columns(db_conn)

    score = db_conn.execute(
        text("SELECT equity_score FROM coverage_cells WHERE cell_id = 'EC_AL'")
    ).scalar()
    assert score is not None, "equity_score is NULL — populate_equity_columns did not update the cell"
    assert score > 0, f"Expected equity_score > 0 for Alameda County cell, got {score}"


def test_equity_score_outside_all_county_bboxes_gets_default(db_conn: Connection):
    """Cells outside all 9 county bounding boxes receive the neutral default (0.5)."""
    with db_conn.begin():
        # Pacific Ocean west of the Bay Area — outside every county bbox
        db_conn.execute(
            text("""
                INSERT INTO coverage_cells (cell_id, geom)
                VALUES ('EC_OCEAN', ST_MakeEnvelope(-125.0, 36.0, -124.9, 36.1, 4326))
            """)
        )
        with patch(
            "app.services.equity_loader._fetch_census",
            return_value=_MOCK_TRACTS,
        ):
            populate_equity_columns(db_conn)

    score = db_conn.execute(
        text("SELECT equity_score FROM coverage_cells WHERE cell_id = 'EC_OCEAN'")
    ).scalar()
    assert score is not None
    assert score == pytest.approx(0.5, abs=1e-6), (
        f"Cells outside all county bboxes should default to 0.5, got {score}"
    )

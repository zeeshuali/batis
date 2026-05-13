"""Schema-lint tests — purely textual checks against schema.sql.

These guard against regressions that can't be exercised by the integration
suite (the test postgres image lacks pgvector, so it can't fail at runtime).
"""
from __future__ import annotations

import os
import re

import pytest
from sqlalchemy import text


_SCHEMA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "sql", "schema.sql"
)


def _read_schema() -> str:
    with open(_SCHEMA_PATH) as f:
        return f.read()


def test_pgvector_extension_declared_before_vector_column():
    """schema.sql must CREATE EXTENSION vector before any vector(N) column."""
    sql = _read_schema()

    ext_match = re.search(
        r"CREATE\s+EXTENSION\s+IF\s+NOT\s+EXISTS\s+vector\s*;",
        sql,
        re.IGNORECASE,
    )
    assert ext_match, (
        "schema.sql is missing `CREATE EXTENSION IF NOT EXISTS vector;`. "
        "Without it, the ai_embeddings table fails to create."
    )

    col_match = re.search(r"vector\s*\(\s*\d+\s*\)", sql)
    assert col_match, "schema.sql declares no `vector(N)` column — has the AI feature been removed?"

    assert ext_match.start() < col_match.start(), (
        "CREATE EXTENSION vector is declared AFTER a vector(N) column. "
        f"Extension at offset {ext_match.start()}, column at offset {col_match.start()}. "
        "Move the extension declaration earlier in schema.sql."
    )


def test_postgis_extension_declared():
    """PostGIS is the other extension the schema relies on; guard it too."""
    sql = _read_schema()
    assert re.search(
        r"CREATE\s+EXTENSION\s+IF\s+NOT\s+EXISTS\s+postgis\s*;",
        sql,
        re.IGNORECASE,
    ), "schema.sql is missing `CREATE EXTENSION IF NOT EXISTS postgis;`."


def test_service_delivery_gap_table_exists(db_conn):
    row = db_conn.execute(text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'service_delivery_gap'"
    )).first()
    assert row is not None, "migration 007 not applied"


def test_stop_cell_view_exists(db_conn):
    row = db_conn.execute(text(
        "SELECT 1 FROM pg_matviews WHERE matviewname = 'stop_cell'"
    )).first()
    assert row is not None, "stop_cell materialized view missing"


@pytest.mark.parametrize("table_name", [
    "census_tracts",
    "gtfs_pathways",
    "gtfs_levels",
    "census_ambulatory",
    "stop_ada_gap",
])
def test_sprint5c_tables_exist(db_conn, table_name):
    row = db_conn.execute(text(
        "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
    ), {"t": table_name}).first()
    assert row is not None, f"Sprint 5c table '{table_name}' missing — migration 008 not applied"


def test_cell_ada_gap_view_exists(db_conn):
    row = db_conn.execute(text(
        "SELECT 1 FROM pg_matviews WHERE matviewname = 'cell_ada_gap'"
    )).first()
    assert row is not None, "cell_ada_gap materialized view missing — migration 008 not applied"


# ── Migration 009: GTFS composite primary keys ────────────────────────────────

@pytest.mark.parametrize("table, expected_cols", [
    ("gtfs_routes",      ["agency_id", "route_id"]),
    ("gtfs_trips",       ["agency_id", "trip_id"]),
    ("gtfs_stop_times",  ["agency_id", "trip_id", "stop_sequence"]),
    ("gtfs_shapes",      ["agency_id", "shape_id", "shape_pt_sequence"]),
    ("gtfs_shape_geoms", ["agency_id", "shape_id"]),
])
def test_gtfs_pks_are_composite(db_conn, table, expected_cols):
    """Regression guard for migration 009: every multi-agency GTFS table
    must have agency_id as the first column of its PK. Without this,
    cross-agency ID collisions silently overwrite one agency's data
    (e.g. SF Muni and Santa Clara VTA both using route_id '31')."""
    # Table names come from the parametrize list above, not user input —
    # safe to interpolate into the SQL string. (`:rel::regclass` doesn't
    # work because Postgres needs the cast target known at parse time.)
    actual = db_conn.execute(text(f"""
        SELECT a.attname
          FROM pg_constraint c
          JOIN pg_attribute a
            ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
         WHERE c.conrelid = '{table}'::regclass AND c.contype = 'p'
         ORDER BY array_position(c.conkey, a.attnum)
    """)).scalars().all()
    assert actual == expected_cols, (
        f"{table} PK = {actual}, expected {expected_cols} — migration 009 "
        f"not applied (or schema.sql drifted)."
    )


def test_gtfs_stops_has_composite_unique_index(db_conn):
    """gtfs_stops keeps single-column PK (stop_safety_scores / stop_features
    FK to it), but migration 009 adds a composite UNIQUE index so the loader's
    ON CONFLICT (agency_id, stop_id) clause has a target and future
    cross-agency stop_id collisions error loudly."""
    indexdef = db_conn.execute(text(
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'gtfs_stops_agency_stop_uniq'"
    )).scalar()
    assert indexdef is not None, (
        "gtfs_stops_agency_stop_uniq index missing — migration 009 not applied."
    )
    assert "agency_id" in indexdef and "stop_id" in indexdef, (
        f"gtfs_stops_agency_stop_uniq has unexpected definition: {indexdef}"
    )


def test_gtfs_shapes_has_agency_id_column(db_conn):
    """Migration 009 adds NOT NULL agency_id to gtfs_shapes (the original
    loader assumed shape_ids were globally unique, which is false across
    multi-agency feeds)."""
    row = db_conn.execute(text("""
        SELECT is_nullable
          FROM information_schema.columns
         WHERE table_name = 'gtfs_shapes' AND column_name = 'agency_id'
    """)).first()
    assert row is not None, "gtfs_shapes.agency_id column missing — migration 009 not applied."
    assert row[0] == "NO", f"gtfs_shapes.agency_id must be NOT NULL, got is_nullable={row[0]}"

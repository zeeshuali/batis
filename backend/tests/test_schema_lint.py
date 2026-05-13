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

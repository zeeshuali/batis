"""Schema-lint tests — purely textual checks against schema.sql.

These guard against regressions that can't be exercised by the integration
suite (the test postgres image lacks pgvector, so it can't fail at runtime).
"""
from __future__ import annotations

import os
import re


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

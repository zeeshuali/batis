# BATIS Phase 0 — Bug Bash Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the six in-flight bug fixes from CLAUDE.md on `main` with regression tests, leaving a green test suite and a documented baseline before Phase 1 (dashboard shell) begins.

**Architecture:** The six fixes already exist in the working tree (uncommitted), and a partial pytest suite exists for them but is also uncommitted. The plan: provision a test database, audit each fix against its bug description, add the two missing regression tests, then commit fixes + tests in scoped chunks. The working tree contains substantial unrelated work-in-progress (511.org, ai_assistant, etc.); this plan deliberately stays narrow and commits only Phase 0 surface area.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2.0 (raw SQL), PostgreSQL 15 + PostGIS + pgvector, pytest + httpx ASGITransport, React 18 + TypeScript + Vite, docker-compose.

---

## Pre-flight: what to know before starting

This plan operates in `/home/mza/projects/batis` on branch `main`. The git working tree has many modified and untracked files at the start of this plan; do not run `git add -A` or `git commit -a`. Every commit step below names exact paths.

The six bugs from CLAUDE.md and their current in-tree status:

| # | Bug | Fix file | In tree? | Test file | In tree? |
|---|---|---|---|---|---|
| 1 | `/routes/compare` shadowed by `/routes/{route_id}/geo` | `backend/app/main.py` | Yes (~line 322 has the comment + ordering) | `backend/tests/test_routes.py` | Yes (`test_routes_compare_not_shadowed_by_route_id`) |
| 2 | `ST_DWithin` on `geometry` uses degrees | `backend/app/services/safety_scoring.py` (~line 51) | Yes (`::geography` cast applied) | `backend/tests/test_safety.py` | Yes (3 tests) |
| 3 | `CREATE EXTENSION vector` missing from `schema.sql` | `backend/sql/schema.sql` (~line 326) | Yes | none | **No** — Task 4 adds it |
| 4 | `sentence-transformers` + `httpx` missing from `requirements.txt` | `backend/requirements.txt` | Yes (lines 12–13) | none | **No** — Task 5 adds it |
| 5 | `equity_score` never populated | `backend/app/services/equity_loader.py` (rewritten) | Yes | `backend/tests/test_equity.py` | Yes (3 tests) |
| 6 | StopDrawer shows scheduled, not live, departures | `frontend/src/components/StopDrawer.tsx` (line 62 fetches `/live-departures`) | Yes | none (no frontend test infra yet) | **Deferred** — covered in Phase 1 |

`backend/tests/conftest.py` uses a separate test database at `postgresql://postgres:postgres@localhost:5433/bay_area_transit_intel_test`. Today `docker-compose.yml` does not start one — Task 1 fixes that.

---

## File Structure

**Modified files (committed by this plan):**

- `docker-compose.yml` — adds `postgres-test` service at port 5433
- `backend/sql/schema.sql` — already has the pgvector fix; the only file edit is none, but it gets committed
- `backend/requirements.txt` — already has the deps; gets committed
- `backend/app/main.py` — **only the route-ordering hunk** (line 322–335) gets committed in Phase 0; other hunks belong to later phases and stay uncommitted
- `backend/app/services/safety_scoring.py` — committed
- `backend/app/services/equity_loader.py` — committed
- `frontend/src/components/StopDrawer.tsx` — committed
- `CLAUDE.md` — committed (currently untracked); the "Known Critical Bugs" section is rewritten to reflect Phase 0 completion

**New files (created by this plan):**

- `backend/tests/test_schema_lint.py` — pgvector + extension presence check (Task 4)
- `backend/tests/test_imports_smoke.py` — verifies all app/ml modules import without ImportError (Task 5)

**New files created in earlier work, committed by this plan:**

- `backend/pytest.ini`
- `backend/tests/__init__.py`
- `backend/tests/conftest.py`
- `backend/tests/test_ai.py`
- `backend/tests/test_equity.py`
- `backend/tests/test_reliability.py`
- `backend/tests/test_routes.py`
- `backend/tests/test_safety.py`
- `backend/tests/test_stop_observations.py`
- `backend/tests/test_trip_planner.py`

**Explicitly NOT in scope for Phase 0** (left in the working tree for later plans):

- `backend/app/services/five11_*.py`, `backend/app/services/ai_assistant.py`, `backend/ml/embed.py`
- `backend/sql/migrations/`, `backend/app/workers/load_stop_observations.py`
- `frontend/src/components/AiAssistant.tsx`, `frontend/src/components/BenchmarkPanel.tsx`
- All other `M` files in `git status` that don't appear in the table above

---

## Task 1: Provision the test database via docker-compose

**Files:**
- Modify: `docker-compose.yml`

The `conftest.py` test fixtures connect to `postgresql://postgres:postgres@localhost:5433/bay_area_transit_intel_test`. Today no service listens on 5433. Add a sibling postgres service so any developer can run the test suite.

- [ ] **Step 1: Read the current docker-compose.yml**

Run: `cat docker-compose.yml`

Confirm there is exactly one `postgres` service on port 5432, no test sibling.

- [ ] **Step 2: Add the `postgres-test` service**

Edit `docker-compose.yml`. Insert this block **after** the existing `postgres:` service (before `backend:`):

```yaml
  postgres-test:
    image: postgis/postgis:15-3.4
    environment:
      POSTGRES_DB: bay_area_transit_intel_test
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports:
      - "5433:5432"
    tmpfs:
      - /var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 3s
      retries: 10
```

Use `tmpfs` (not a volume) so test data is wiped on container restart — tests must be reproducible. Use image `postgis/postgis:15-3.4` to match `conftest.py`'s comment (which notes the image lacks pgvector, expected).

- [ ] **Step 3: Start the test database**

Run: `docker compose up -d postgres-test`

Expected: container starts; `docker compose ps postgres-test` shows it as healthy within ~10s.

- [ ] **Step 4: Verify connectivity**

Run: `docker compose exec postgres-test psql -U postgres -d bay_area_transit_intel_test -c "SELECT 1"`

Expected output:
```
 ?column?
----------
        1
```

- [ ] **Step 5: Do not commit yet**

The commit happens in Task 6, bundled with `pytest.ini` and the rest of the test infrastructure.

---

## Task 2: Audit the six in-tree fixes against their bug descriptions

**Files:**
- Read-only inspection of: `backend/app/main.py`, `backend/app/services/safety_scoring.py`, `backend/sql/schema.sql`, `backend/requirements.txt`, `backend/app/services/equity_loader.py`, `frontend/src/components/StopDrawer.tsx`

This task creates no commits; it produces a documented audit so the rest of the plan rests on solid ground.

- [ ] **Step 1: Verify route ordering (Bug 1)**

Run: `grep -n "^@app\." backend/app/main.py | grep -E "(routes/compare|routes/\{route_id\}/geo)"`

Expected: `/routes/compare` line number is **less than** `/routes/{route_id}/geo` line number.

Also run: `grep -n "IMPORTANT: /routes/compare" backend/app/main.py`

Expected: matches a comment line immediately above the `/routes/compare` decorator.

If either check fails, stop and reorder routes in `backend/app/main.py` so `/routes/compare` is registered first.

- [ ] **Step 2: Verify safety geometry cast (Bug 2)**

Run: `grep -n "ST_DWithin" backend/app/services/safety_scoring.py`

Expected: the only matching line contains `s.geom::geography, i.geom::geography` (both arguments cast to `::geography`). If the file still has `s.geom, i.geom` without the cast, the fix has regressed — restore the cast before continuing.

- [ ] **Step 3: Verify pgvector extension is enabled in schema (Bug 3)**

Run: `grep -nB1 "CREATE EXTENSION IF NOT EXISTS vector" backend/sql/schema.sql`

Expected: one match.

Run: `grep -n "vector(384)" backend/sql/schema.sql`

Expected: one match.

Confirm the `CREATE EXTENSION` line number is **less than** the `vector(384)` line number (the extension must be created before the column type is used).

- [ ] **Step 4: Verify requirements.txt has the AI deps (Bug 4)**

Run: `grep -E "^(sentence-transformers|httpx)" backend/requirements.txt`

Expected: both lines present.

- [ ] **Step 5: Verify equity_loader populates equity_score (Bug 5)**

Run: `grep -n "equity_score" backend/app/services/equity_loader.py`

Expected: at least one `UPDATE coverage_cells SET equity_score` line, plus the fallback `SET equity_score = 0.5 WHERE equity_score IS NULL`. The old broken `WHERE population > 0` filter must be absent.

Run: `grep -n "WHERE population" backend/app/services/equity_loader.py`

Expected: zero matches (the old broken filter is gone).

- [ ] **Step 6: Verify StopDrawer fetches live departures (Bug 6)**

Run: `grep -n "live-departures\|realtime-departures" frontend/src/components/StopDrawer.tsx`

Expected: at least one call to `/stops/${sid}/live-departures`.

Also confirm the render code prefers `liveDepartures` over scheduled `detail.departures` (look for a ternary like `liveDepartures.length > 0 ? ... : detail.departures.map(...)`).

- [ ] **Step 7: Record audit results**

If every step above passed, no edits are needed in Task 2. If any step failed, fix the regression in the same file, do **not** commit yet — the commit happens in Tasks 7–8.

---

## Task 3: Run the existing test suite to establish a green baseline

**Files:** none modified.

This task verifies the in-tree fixes plus their tests work against the test database from Task 1.

- [ ] **Step 1: Install backend dependencies into a virtualenv**

From the repo root:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

- [ ] **Step 2: Confirm test DB is reachable**

Run: `PGPASSWORD=postgres psql -h localhost -p 5433 -U postgres -d bay_area_transit_intel_test -c "SELECT version()"`

Expected: prints a PostgreSQL 15 version string. If `psql` is not installed locally, substitute `docker compose exec postgres-test psql ...` from the host shell.

- [ ] **Step 3: Run pytest**

From `backend/` with the virtualenv active:

```bash
pytest -q
```

Expected: all collected tests pass. Specifically:
- `tests/test_routes.py::test_routes_compare_not_shadowed_by_route_id` — Bug 1
- `tests/test_safety.py::test_safety_scoring_buffer_is_metric` — Bug 2
- `tests/test_safety.py::test_safety_scoring_larger_buffer_captures_far_stop`
- `tests/test_safety.py::test_safety_scoring_populates_all_stops`
- `tests/test_equity.py::test_equity_score_not_null_after_populate` — Bug 5
- `tests/test_equity.py::test_equity_score_positive_for_bay_area_cells`
- `tests/test_equity.py::test_equity_score_outside_all_county_bboxes_gets_default`
- All other tests in `test_ai.py`, `test_reliability.py`, `test_stop_observations.py`, `test_trip_planner.py`

If any test fails, stop and investigate. Do **not** continue to Task 4 with a red baseline.

- [ ] **Step 4: Capture the test count for the CLAUDE.md update later**

Run: `pytest --collect-only -q | tail -1`

Record the number (e.g. `42 tests collected`). It will be referenced in Task 9's CLAUDE.md edit.

---

## Task 4: Add the missing pgvector schema regression test (Bug 3)

**Files:**
- Create: `backend/tests/test_schema_lint.py`

`conftest.py` deliberately skips pgvector DDL because the test postgres image lacks the extension. So Bug 3 ("`CREATE EXTENSION vector` missing") cannot be caught by an integration test — it needs a text-level lint of `schema.sql`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_schema_lint.py`:

```python
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
```

- [ ] **Step 2: Run the test to confirm it passes**

Run: `pytest backend/tests/test_schema_lint.py -v`

Expected: both tests pass. If `test_pgvector_extension_declared_before_vector_column` fails, the in-tree fix has regressed — restore the `CREATE EXTENSION IF NOT EXISTS vector;` line in `schema.sql` before the `ai_embeddings` table DDL.

- [ ] **Step 3: Sanity-check the test by temporarily breaking the schema**

To prove the test actually catches the bug:

```bash
cp backend/sql/schema.sql /tmp/schema.sql.bak
sed -i 's/CREATE EXTENSION IF NOT EXISTS vector/-- CREATE EXTENSION IF NOT EXISTS vector/' backend/sql/schema.sql
pytest backend/tests/test_schema_lint.py::test_pgvector_extension_declared_before_vector_column -v
```

Expected: the test now FAILS with the assertion message.

Restore:

```bash
mv /tmp/schema.sql.bak backend/sql/schema.sql
pytest backend/tests/test_schema_lint.py -v
```

Expected: tests pass again. Do not commit anything yet.

---

## Task 5: Add the missing import-smoke test (Bug 4)

**Files:**
- Create: `backend/tests/test_imports_smoke.py`

Bug 4 (`sentence-transformers` / `httpx` missing from `requirements.txt`) manifests as `ImportError` at server startup. A test that imports every app module is the simplest regression guard.

- [ ] **Step 1: Write the test**

Create `backend/tests/test_imports_smoke.py`:

```python
"""Smoke test: every importable app/ml module must import without error.

Guards against missing entries in requirements.txt (e.g. sentence-transformers
or httpx not declared, causing ImportError at server startup).
"""
from __future__ import annotations

import importlib
import os
import pkgutil
from typing import Iterator


_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _iter_module_names(package_root: str, package_name: str) -> Iterator[str]:
    """Yield dotted module names under package_root/package_name."""
    pkg_path = os.path.join(package_root, package_name)
    for _, modname, _ in pkgutil.walk_packages(
        [pkg_path], prefix=f"{package_name}."
    ):
        yield modname


def test_app_modules_import_cleanly():
    """Every module under app.* must import — proves requirements.txt is complete."""
    failures: list[tuple[str, str]] = []
    for modname in _iter_module_names(_BACKEND_ROOT, "app"):
        try:
            importlib.import_module(modname)
        except ImportError as exc:
            failures.append((modname, repr(exc)))

    assert not failures, (
        "ImportError in app modules — likely a missing dependency in "
        "requirements.txt:\n  " + "\n  ".join(f"{m}: {e}" for m, e in failures)
    )


def test_ml_modules_import_cleanly():
    """Every module under ml.* must import — guards the AI pipeline deps."""
    failures: list[tuple[str, str]] = []
    for modname in _iter_module_names(_BACKEND_ROOT, "ml"):
        try:
            importlib.import_module(modname)
        except ImportError as exc:
            failures.append((modname, repr(exc)))

    assert not failures, (
        "ImportError in ml modules — likely sentence-transformers or another "
        "AI dep missing from requirements.txt:\n  "
        + "\n  ".join(f"{m}: {e}" for m, e in failures)
    )
```

- [ ] **Step 2: Run the test**

Run: `pytest backend/tests/test_imports_smoke.py -v`

Expected: both tests pass. If either fails with `ImportError: No module named 'X'`, add `X` to `backend/requirements.txt` and reinstall (`pip install -r requirements.txt`) before continuing.

- [ ] **Step 3: Sanity-check by temporarily uninstalling httpx**

```bash
pip uninstall -y httpx
pytest backend/tests/test_imports_smoke.py::test_app_modules_import_cleanly -v
```

Expected: test FAILS with an ImportError mentioning `httpx`. Then:

```bash
pip install httpx==0.27.2
pytest backend/tests/test_imports_smoke.py -v
```

Expected: tests pass again.

---

## Task 6: Commit test infrastructure

**Files committed:**
- `docker-compose.yml` (modified)
- `backend/pytest.ini` (new, currently untracked)
- `backend/tests/__init__.py` (new)
- `backend/tests/conftest.py` (new)
- `backend/tests/test_ai.py` (new)
- `backend/tests/test_reliability.py` (new)
- `backend/tests/test_stop_observations.py` (new)
- `backend/tests/test_trip_planner.py` (new)
- `backend/tests/test_schema_lint.py` (new — from Task 4)
- `backend/tests/test_imports_smoke.py` (new — from Task 5)

The bug-specific tests (`test_routes.py`, `test_safety.py`, `test_equity.py`) are deliberately held back to Tasks 7a–c so each bug's commit is self-contained (fix + test).

- [ ] **Step 1: Stage exactly these files**

From the repo root:

```bash
git add docker-compose.yml \
        backend/pytest.ini \
        backend/tests/__init__.py \
        backend/tests/conftest.py \
        backend/tests/test_ai.py \
        backend/tests/test_reliability.py \
        backend/tests/test_stop_observations.py \
        backend/tests/test_trip_planner.py \
        backend/tests/test_schema_lint.py \
        backend/tests/test_imports_smoke.py
```

- [ ] **Step 2: Verify the staged set is exactly what is expected**

Run: `git diff --cached --name-only`

Expected output (exactly these 10 lines, order may differ):
```
backend/pytest.ini
backend/tests/__init__.py
backend/tests/conftest.py
backend/tests/test_ai.py
backend/tests/test_imports_smoke.py
backend/tests/test_reliability.py
backend/tests/test_schema_lint.py
backend/tests/test_stop_observations.py
backend/tests/test_trip_planner.py
docker-compose.yml
```

If any other file is staged, run `git restore --staged <file>` and repeat Step 1.

- [ ] **Step 3: Commit**

```bash
git commit -m "$(cat <<'EOF'
Add backend test infrastructure and non-bug regression tests

Provisions a postgres-test service on port 5433 for the pytest suite,
introduces the shared conftest with schema replay + seeded fixtures, and
lands schema-lint + import-smoke tests (Bugs 3 and 4 regression guards).
Bug-specific tests for routes/safety/equity land alongside their fixes in
the next commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Verify nothing extra was committed**

Run: `git show --stat HEAD`

Expected: 10 files, no unexpected `backend/app/...` or `backend/ml/...` paths.

---

## Task 7a: Commit Bug 1 — /routes/compare ordering

**Files committed:**
- `backend/app/main.py` — **only the route-ordering hunk** (the lines around the `/routes/compare` and `/routes/{route_id}/geo` decorators with the explanatory comment)
- `backend/tests/test_routes.py` — new file, includes `test_routes_compare_not_shadowed_by_route_id`

The working-tree diff of `main.py` mixes Phase 0 (route ordering) with multi-agency / embed pipeline work that belongs to later phases. Use `git add -p` to stage only the Phase 0 hunk.

- [ ] **Step 1: Inspect the working-tree diff**

Run: `git diff backend/app/main.py | head -80`

Identify the hunk that contains the line `# IMPORTANT: /routes/compare MUST be registered before /routes/{route_id}/geo` and the two affected `@app.get(...)` decorators. That is the only `main.py` hunk for Phase 0.

- [ ] **Step 2: Interactively stage only that hunk**

```bash
git add -p backend/app/main.py
```

For each hunk shown, answer:
- `y` — only for the hunk containing the routes/compare ordering comment
- `n` — for every other hunk (511.org imports, embed pipeline, traffic loop, new endpoints, etc.)

If a hunk contains both Phase 0 and unrelated changes, answer `e` to edit and remove the unrelated lines.

- [ ] **Step 3: Verify the staged diff is small and scoped**

Run: `git diff --cached backend/app/main.py`

Expected: ~5–15 lines, all around the `/routes/compare` and `/routes/{route_id}/geo` decorators. No imports, no lifespan changes, no new endpoints.

- [ ] **Step 4: Stage the routes test**

```bash
git add backend/tests/test_routes.py
```

- [ ] **Step 5: Confirm staged set**

Run: `git diff --cached --name-only`

Expected:
```
backend/app/main.py
backend/tests/test_routes.py
```

- [ ] **Step 6: Run the regression test against the staged state**

```bash
pytest backend/tests/test_routes.py::test_routes_compare_not_shadowed_by_route_id -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git commit -m "$(cat <<'EOF'
Fix /routes/compare being shadowed by /routes/{route_id}/geo

FastAPI matches routes in registration order; the parameterised
/routes/{route_id}/geo registered first was capturing 'compare' as a
route_id and shadowing the comparison endpoint. Reorder so the literal
path is registered first.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7b: Commit Bug 2 — Safety geometry units

**Files committed:**
- `backend/app/services/safety_scoring.py`
- `backend/tests/test_safety.py`

- [ ] **Step 1: Stage exactly these two files**

```bash
git add backend/app/services/safety_scoring.py backend/tests/test_safety.py
```

- [ ] **Step 2: Verify staged set**

Run: `git diff --cached --name-only`

Expected:
```
backend/app/services/safety_scoring.py
backend/tests/test_safety.py
```

- [ ] **Step 3: Verify the diff shows the geography cast**

Run: `git diff --cached backend/app/services/safety_scoring.py | grep -E "^\+.*geography"`

Expected: at least one line showing `+ ... s.geom::geography, i.geom::geography, :buffer_meters`.

- [ ] **Step 4: Run the safety tests**

```bash
pytest backend/tests/test_safety.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
Fix safety scoring buffer using degrees instead of metres

ST_DWithin on geometry(Point, 4326) computes distance in degrees, so a
150 m buffer was effectively 150 degrees (planet-scale). Cast both sides
to ::geography so the parameter is interpreted as metres. Adds three
regression tests covering near/far/coverage cases.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7c: Commit Bug 3 — pgvector extension in schema

**Files committed:**
- `backend/sql/schema.sql`

The regression test for this bug already shipped in Task 6 (`test_schema_lint.py`).

- [ ] **Step 1: Inspect the working-tree diff**

Run: `git diff backend/sql/schema.sql`

Identify the hunk containing `CREATE EXTENSION IF NOT EXISTS vector;` and any related comment lines. There may be other schema changes mixed in (multi-agency, new tables) — those belong to a later phase.

- [ ] **Step 2: Stage only the pgvector hunk**

```bash
git add -p backend/sql/schema.sql
```

Answer `y` only for the hunk introducing `CREATE EXTENSION IF NOT EXISTS vector;` (and the immediately surrounding comment). Answer `n` for any multi-agency / new-table hunks.

- [ ] **Step 3: Verify staged diff is scoped**

Run: `git diff --cached backend/sql/schema.sql`

Expected: a small diff, ~2–5 lines, adding the extension line before the `ai_embeddings` table DDL.

- [ ] **Step 4: Run the schema-lint test**

```bash
pytest backend/tests/test_schema_lint.py -v
```

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
Enable pgvector extension in schema.sql before ai_embeddings DDL

Without CREATE EXTENSION IF NOT EXISTS vector, a fresh database fails to
create the ai_embeddings table on first boot. test_schema_lint.py guards
this from regressing.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7d: Commit Bug 4 — requirements.txt completeness

**Files committed:**
- `backend/requirements.txt`

The regression test (`test_imports_smoke.py`) already shipped in Task 6.

- [ ] **Step 1: Inspect the diff**

Run: `git diff backend/requirements.txt`

Expected: shows additions for `sentence-transformers`, `httpx`, and probably `certifi` and the pytest deps.

- [ ] **Step 2: Stage the file**

```bash
git add backend/requirements.txt
```

- [ ] **Step 3: Verify staged set**

Run: `git diff --cached --name-only`

Expected:
```
backend/requirements.txt
```

- [ ] **Step 4: Run the import smoke test**

```bash
pytest backend/tests/test_imports_smoke.py -v
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
Add sentence-transformers, httpx, certifi, pytest to requirements.txt

These were imported by app modules and the AI pipeline but never declared,
causing ImportError on a clean install. test_imports_smoke.py walks every
app.* and ml.* module to catch this regressing again.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7e: Commit Bug 5 — equity_score populated from Census

**Files committed:**
- `backend/app/services/equity_loader.py`
- `backend/tests/test_equity.py`

- [ ] **Step 1: Stage both files**

```bash
git add backend/app/services/equity_loader.py backend/tests/test_equity.py
```

- [ ] **Step 2: Verify staged set**

Run: `git diff --cached --name-only`

Expected:
```
backend/app/services/equity_loader.py
backend/tests/test_equity.py
```

- [ ] **Step 3: Run the equity tests**

```bash
pytest backend/tests/test_equity.py -v
```

Expected: 3 tests pass.

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
Populate equity_score per coverage_cell from Census ACS data

Replaces the no-op implementation (which filtered WHERE population > 0
but never populated population) with per-county spatial UPDATEs sourced
from Census ACS 5-year estimates. Cells outside all 9 Bay Area county
bounding boxes receive a neutral 0.5 default. Three regression tests
cover the populated, positive-score, and default-fallback cases.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Commit Bug 6 — StopDrawer live departures

**Files committed:**
- `frontend/src/components/StopDrawer.tsx`

No frontend test infrastructure exists yet; the Phase 1 plan will introduce it. For Phase 0 the fix ships without an automated test — manual verification is documented in the verification section.

- [ ] **Step 1: Stage the file**

```bash
git add frontend/src/components/StopDrawer.tsx
```

- [ ] **Step 2: Verify staged set**

Run: `git diff --cached --name-only`

Expected:
```
frontend/src/components/StopDrawer.tsx
```

- [ ] **Step 3: Inspect the diff to confirm the fix is there**

Run: `git diff --cached frontend/src/components/StopDrawer.tsx | grep -E "live-departures|liveDepartures"`

Expected: shows additions referencing `/stops/${sid}/live-departures` and a `liveDepartures` state variable.

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
Wire StopDrawer to /stops/{stop_id}/live-departures for real-time ETAs

StopDrawer previously rendered only scheduled departures even when SIRI
live ETAs were available. Now fetches /live-departures in parallel with
/stops/{id} and prefers the live rows (badged 'LIVE') over scheduled,
falling back to scheduled when no live data is present. No automated
frontend test ships here — Phase 1 introduces the test substrate.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Update CLAUDE.md and commit

**Files committed:**
- `CLAUDE.md` (currently untracked)

CLAUDE.md is in the working tree but never committed. After Phase 0 lands, its "Known Critical Bugs" section is wrong (every listed bug is now fixed + tested). Rewrite that section to reflect the new baseline.

- [ ] **Step 1: Read the current CLAUDE.md**

Run: `cat CLAUDE.md`

Locate the section starting with `## Known Critical Bugs (Fix Before Anything Else)`.

- [ ] **Step 2: Replace the bug list with a Phase 0 baseline note**

Edit `CLAUDE.md`. Replace the entire `## Known Critical Bugs` section (header plus the 6 bullets and any closing text) with:

```markdown
## Phase 0 Baseline (completed 2026-05-11)

The six critical bugs previously listed in this section have been fixed
and locked in with regression tests. Plan: `docs/superpowers/plans/2026-05-11-batis-phase-0-bug-bash.md`.

To run the test suite: `docker compose up -d postgres-test && cd backend && pytest -q`.
Current test count: <N>.

If a Phase 0 regression appears, the corresponding test in `backend/tests/`
will catch it before merge.
```

Replace `<N>` with the test count captured in Task 3 Step 4.

- [ ] **Step 3: Stage and commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
Mark Phase 0 baseline complete in CLAUDE.md

The six bugs previously listed under 'Known Critical Bugs' have all been
fixed and have regression tests. Phase 0 plan referenced for traceability.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Final check — Phase 0 is closed**

Run:

```bash
git log --oneline -10
pytest backend -q
```

Expected:
- `git log` shows 8 new commits on top of the spec commit (`80c8815`): test infra, 5 bug fixes, StopDrawer fix, CLAUDE.md update
- `pytest` reports the same pass count as Task 3 Step 4

---

## Verification (end-to-end)

After all tasks complete, an engineer joining the project should be able to:

1. **Clone the repo, start the test DB, install deps, run tests, and see green:**
   ```bash
   docker compose up -d postgres-test
   cd backend && python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   pytest -q
   ```
   Expected: all tests pass.

2. **Verify each fix manually:**
   - **Bug 1**: `curl http://localhost:8000/routes/compare?route_ids=R001,R002&start_date=2026-05-01&end_date=2026-05-08` returns a comparison body, not a route-geo FeatureCollection.
   - **Bug 2**: Run `compute_stop_safety_scores(buffer_meters=150)` and confirm `stop_safety_scores.crime_incidents_nearby` is plausible (a handful, not all incidents in the state).
   - **Bug 3**: On a fresh database, applying `schema.sql` succeeds end-to-end with no error about `type "vector" does not exist`.
   - **Bug 4**: A fresh `pip install -r requirements.txt && python -c "import app.main"` succeeds with no ImportError.
   - **Bug 5**: After running `populate_equity_columns()`, `SELECT COUNT(*) FROM coverage_cells WHERE equity_score IS NULL` returns 0.
   - **Bug 6**: Open the frontend, click a stop with active service; departures show a `LIVE` badge for real-time arrivals and `Scheduled` for fallbacks.

3. **Confirm the Phase 0 commits are the only commits added by this plan:**
   ```bash
   git log --oneline 80c8815..HEAD
   ```
   Expected: 8 commits (test infra, 5 bug fixes, StopDrawer, CLAUDE.md), each scoped to its claimed files, no surprise inclusions.

---

## What this plan does NOT do

To prevent scope creep, the following are explicitly deferred to later plans:

- **Phase 1 — Dashboard shell** (next plan): new 5-section nav, design tokens, global filter bar, cross-filter context, primitives extraction, Overview home page. Will be authored once Phase 0 lands.
- **Frontend test infrastructure**: introduced in Phase 1 alongside the section components.
- **Multi-agency activation**, **511.org ingestion**, **AI Agent**: spec phases 2–5; their own plans later.
- **Committing the broader working-tree work**: many `M` and `??` files (five11_*, ai_assistant.py, embed.py, migrations, BLUEPRINT.md, GAPS.md, etc.) remain uncommitted after this plan finishes. They are intentionally untouched so each subsequent plan can claim them in scoped chunks.

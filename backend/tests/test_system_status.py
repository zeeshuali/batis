"""System Status dashboard: run log helpers and /admin/* endpoints."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core import run_log
from app.core.run_log import job_run, log_api_call, source_for_url, tracked_get


@pytest.fixture(autouse=True)
def _clean(test_engine: Engine):
    with test_engine.begin() as conn:
        conn.execute(text("TRUNCATE api_call_log, job_runs"))
    yield


def test_source_for_url():
    assert source_for_url("https://api.511.org/Transit/x?api_key=SECRET") == "511"
    assert source_for_url("https://data.oaklandca.gov/resource/a.json") == "oakland_open_data"
    assert source_for_url("https://tigerweb.geo.census.gov/arcgis") == "census"
    assert source_for_url("https://example.org/a") == "example.org"


def test_logged_call_never_stores_query_string_or_key(test_engine: Engine):
    log_api_call("https://api.511.org/Transit/VehiclePositions?api_key=SECRET&agency=RG",
                 status_code=500, ok=False, duration_ms=12,
                 error="500 for url: https://api.511.org/x?api_key=SECRET")
    with test_engine.connect() as conn:
        row = conn.execute(text("SELECT source, endpoint, error, ok FROM api_call_log")).mappings().one()
    assert row["source"] == "511" and row["ok"] is False
    assert row["endpoint"] == "api.511.org/Transit/VehiclePositions"
    assert "SECRET" not in row["endpoint"] and "SECRET" not in row["error"]


def test_tracked_get_records_success_and_failure(test_engine: Engine, monkeypatch):
    class R:
        status_code = 200
        reason = "OK"

    monkeypatch.setattr(run_log.requests, "get", lambda url, **kw: R())
    assert tracked_get("https://api.511.org/a?api_key=K").status_code == 200

    def boom(url, **kw):
        raise ConnectionError("down api_key=K")

    monkeypatch.setattr(run_log.requests, "get", boom)
    with pytest.raises(ConnectionError):
        tracked_get("https://api.511.org/b?api_key=K")
    with test_engine.connect() as conn:
        rows = conn.execute(text("SELECT ok, status_code, error FROM api_call_log ORDER BY id")).all()
    assert [r.ok for r in rows] == [True, False]
    assert rows[1].status_code is None and "api_key=K" not in rows[1].error


def test_job_run_records_ok_error_and_soft_fail(test_engine: Engine):
    with job_run("unit_ok") as jr:
        jr.set(rows=5, month="2026-10")
    with pytest.raises(ValueError):
        with job_run("unit_err"):
            raise ValueError("bad thing")
    with job_run("unit_soft") as jr:
        jr.fail("partial: vehicle insert failed")
    with test_engine.connect() as conn:
        got = {r.job: r for r in conn.execute(text("SELECT * FROM job_runs"))}
    assert got["unit_ok"].status == "ok" and got["unit_ok"].rows_written == 5
    assert got["unit_ok"].details["month"] == "2026-10" and got["unit_ok"].finished_at is not None
    assert got["unit_err"].status == "error" and "bad thing" in got["unit_err"].error
    assert got["unit_soft"].status == "error" and "partial" in got["unit_soft"].error


def test_status_snapshot_shape_and_511_budget(test_engine: Engine):
    from app.services.system_status import get_system_status
    for _ in range(3):
        log_api_call("https://api.511.org/Transit/TripUpdates", status_code=200, ok=True, duration_ms=100)
    log_api_call("https://api.511.org/Transit/TripUpdates", status_code=429, ok=False,
                 duration_ms=50, error="HTTP 429 Too Many Requests")
    with job_run("rt_ingestor") as jr:
        jr.set(rows=10)
    with test_engine.connect() as conn:
        snap = get_system_status(conn)
    assert snap["overall"] in ("ok", "warn", "error")
    assert snap["db"]["ok"] is True
    assert snap["api"]["rate_limit"]["used_last_hour"] == 4
    src = next(s for s in snap["api"]["sources"] if s["source"] == "511")
    assert src["calls_24h"] == 4 and src["errors_24h"] == 1 and src["error_rate_pct"] == 25.0
    assert src["last_error"] == "HTTP 429 Too Many Requests"
    assert any(j["job"] == "rt_ingestor" for j in snap["jobs"])
    assert {c["key"] for c in snap["checks"]} >= {"database", "five11_key", "five11_budget"}


@pytest.mark.asyncio
async def test_admin_endpoints(client: AsyncClient, test_engine: Engine):
    log_api_call("https://api.511.org/a", status_code=200, ok=True, duration_ms=5)
    log_api_call("https://api.511.org/b", status_code=500, ok=False, duration_ms=5, error="HTTP 500")
    with job_run("unit_job") as jr:
        jr.set(rows=1)
    r = await client.get("/admin/status")
    assert r.status_code == 200 and "checks" in r.json()
    r = await client.get("/admin/api-calls?errors_only=true")
    assert r.status_code == 200 and [x["endpoint"] for x in r.json()] == ["api.511.org/b"]
    r = await client.get("/admin/api-calls?source=511&limit=1")
    assert len(r.json()) == 1
    r = await client.get("/admin/job-runs?job=unit_job")
    assert r.status_code == 200 and r.json()[0]["status"] == "ok"
    r = await client.get("/admin/job-runs?status=bogus")
    assert r.status_code == 422

"""Run log: records outbound API calls and job runs for the System Status dashboard.

Everything here is best effort. A failure to write the log must never break an
ingest, so every DB write is wrapped and swallowed.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from urllib.parse import urlsplit

import requests
from sqlalchemy import text

from app.core.redact import redact_secrets

_SOURCE_BY_HOST = {
    "api.511.org": "511",
    "data.oaklandca.gov": "oakland_open_data",
    "api.census.gov": "census",
    "tigerweb.geo.census.gov": "census",
    "opendata.actransit.org": "actransit",
}


def source_for_url(url: str) -> str:
    host = urlsplit(url).hostname or "unknown"
    return _SOURCE_BY_HOST.get(host, host)


def _endpoint(url: str) -> str:
    """Host + path only. The query string (api_key!) is never stored."""
    p = urlsplit(url)
    return f"{p.hostname or ''}{p.path}"[:300]


def log_api_call(url: str, *, status_code: int | None, ok: bool,
                 duration_ms: int | None, error: str | None = None,
                 source: str | None = None) -> None:
    try:
        from app.db import get_engine
        with get_engine().begin() as conn:
            conn.execute(
                text("""INSERT INTO api_call_log
                        (source, endpoint, status_code, ok, duration_ms, error)
                        VALUES (:s, :e, :c, :ok, :d, :err)"""),
                {"s": source or source_for_url(url), "e": _endpoint(url), "c": status_code,
                 "ok": ok, "d": duration_ms,
                 "err": redact_secrets(error)[:500] if error else None},
            )
    except Exception:
        pass


def tracked_get(url: str, **kwargs) -> requests.Response:
    """Drop-in for requests.get that records the call (status, latency, error)."""
    t0 = time.monotonic()
    try:
        resp = requests.get(url, **kwargs)
    except Exception as exc:
        log_api_call(url, status_code=None, ok=False,
                     duration_ms=int((time.monotonic() - t0) * 1000), error=str(exc))
        raise
    code = resp.status_code if isinstance(resp.status_code, int) else None
    ok = code is None or code < 400
    log_api_call(url, status_code=code, ok=ok,
                 duration_ms=int((time.monotonic() - t0) * 1000),
                 error=None if ok else f"HTTP {code} {resp.reason}")
    return resp


class JobRun:
    """Handle yielded by job_run(); call .set(rows=..., key=value) to add results."""

    def __init__(self) -> None:
        self.rows: int | None = None
        self.details: dict = {}
        self.error: str | None = None

    def fail(self, message: str) -> None:
        """Mark the run as failed without raising (e.g. partial errors reported in a result)."""
        self.error = message

    def set(self, rows: int | None = None, **details) -> None:
        if rows is not None:
            self.rows = int(rows)
        self.details.update(details)


@contextmanager
def job_run(job: str):
    """Record one run of `job`: running -> ok/error, with duration and any error text.

    Exceptions are re-raised after being recorded.
    """
    run_id = None
    try:
        from app.db import get_engine
        with get_engine().begin() as conn:
            run_id = conn.execute(
                text("INSERT INTO job_runs (job) VALUES (:j) RETURNING id"), {"j": job}
            ).scalar()
    except Exception:
        pass
    handle = JobRun()
    try:
        yield handle
    except Exception as exc:
        _finish(run_id, "error", handle, redact_secrets(f"{type(exc).__name__}: {exc}")[:1000])
        raise
    else:
        if handle.error:
            _finish(run_id, "error", handle, redact_secrets(handle.error)[:1000])
        else:
            _finish(run_id, "ok", handle, None)


def _finish(run_id, status: str, handle: JobRun, error: str | None) -> None:
    if run_id is None:
        return
    try:
        from app.db import get_engine
        with get_engine().begin() as conn:
            conn.execute(
                text("""UPDATE job_runs SET finished_at = now(), status = :s,
                        rows_written = :r, details = CAST(:d AS jsonb), error = :e
                        WHERE id = :id"""),
                {"s": status, "r": handle.rows, "d": json.dumps(handle.details, default=str),
                 "e": error, "id": run_id},
            )
    except Exception:
        pass


def prune_run_log(conn, days: int) -> None:
    conn.execute(text("DELETE FROM api_call_log WHERE called_at < now() - make_interval(days => :d)"), {"d": days})
    conn.execute(text("DELETE FROM job_runs WHERE started_at < now() - make_interval(days => :d)"), {"d": days})

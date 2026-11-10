"""System status snapshot for the System Status dashboard.

Read-only. Combines DB health, data freshness, 511 rate-limit usage, API call
error rates, job run history, background threads and external services so a
failure can be traced without reading logs. Every probe is isolated: one failing
query reports an error for that item instead of failing the whole snapshot.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.config import get_settings

_ORDER = {"ok": 0, "warn": 1, "error": 2}

# (table, label, timestamp SQL for "latest", stale_after_minutes setting name or None)
_FRESHNESS = [
    ("rt_vehicle_positions_raw", "Live vehicle positions", "MAX(timestamp)", "status_rt_stale_minutes"),
    ("ops_trip_events", "Trip events (RT delays)", "MAX(service_date)::timestamptz", None),
    ("stop_observations", "Stop observations (archive)", "MAX(service_date)::timestamptz", None),
    ("gtfs_stops", "GTFS stops", None, None),
    ("gtfs_stop_times", "GTFS stop times", None, None),
    ("transfer_reliability", "Transfer reliability", "MAX(computed_at)", None),
    ("stop_transfer_links", "Stop transfer links", None, None),
    ("ai_embeddings", "AI embeddings", "MAX(updated_at)", None),
    ("delay_predictions", "Delay predictions", None, None),
    ("safety_incidents_raw", "Safety incidents", None, None),
    ("api_call_log", "API call log", "MAX(called_at)", None),
]


def _worst(*statuses: str) -> str:
    return max(statuses, key=lambda s: _ORDER[s]) if statuses else "ok"


def _age_minutes(ts: datetime | None) -> float | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - ts).total_seconds() / 60.0, 1)


def _probe_db(conn: Connection) -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        version = conn.execute(text("SHOW server_version")).scalar()
        exts = [r[0] for r in conn.execute(text(
            "SELECT extname FROM pg_extension WHERE extname IN ('postgis','vector') ORDER BY 1"))]
        size_mb = conn.execute(text("SELECT pg_database_size(current_database()) / 1048576")).scalar()
        return {"ok": True, "latency_ms": int((time.monotonic() - t0) * 1000),
                "version": version, "extensions": exts, "size_mb": int(size_mb or 0)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300], "extensions": []}


def _probe_data(conn: Connection) -> list[dict[str, Any]]:
    s = get_settings()
    out = []
    for table, label, ts_sql, stale_attr in _FRESHNESS:
        item: dict[str, Any] = {"table": table, "label": label, "rows": None,
                                "latest": None, "age_minutes": None, "status": "ok", "note": None}
        try:
            with conn.begin_nested():
                exists = conn.execute(text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}).scalar()
                if not exists:
                    item.update(status="warn", note="table missing")
                    out.append(item)
                    continue
                est = conn.execute(text(
                    "SELECT reltuples::bigint FROM pg_class WHERE oid = to_regclass(:t)"),
                    {"t": f"public.{table}"}).scalar() or 0
                # reltuples is -1/0 before the first ANALYZE and a stale estimate for
                # tiny tables, so count exactly when the estimate is small.
                if est < 200000:
                    item["rows"] = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                else:
                    item["rows"] = int(est)
                    item["note"] = "row count is an estimate"
                if ts_sql:
                    latest = conn.execute(text(f"SELECT {ts_sql} FROM {table}")).scalar()
                    item["latest"] = latest.isoformat() if latest else None
                    item["age_minutes"] = _age_minutes(latest)
                if item["rows"] == 0:
                    item.update(status="warn", note="empty")
                elif stale_attr and item["age_minutes"] is not None:
                    limit = getattr(s, stale_attr)
                    if item["age_minutes"] > limit * 4:
                        item.update(status="error", note=f"no new data for {item['age_minutes']:.0f} min")
                    elif item["age_minutes"] > limit:
                        item.update(status="warn", note=f"no new data for {item['age_minutes']:.0f} min")
        except Exception as exc:
            item.update(status="error", note=str(exc)[:200])
        out.append(item)
    return out


def _probe_api(conn: Connection) -> dict[str, Any]:
    s = get_settings()
    res: dict[str, Any] = {"rate_limit": None, "sources": [], "error": None}
    try:
        with conn.begin_nested():
            used, oldest = conn.execute(text("""
                SELECT COUNT(*), MIN(called_at) FROM api_call_log
                WHERE source = '511' AND called_at > now() - interval '1 hour'""")).one()
            limit = s.five11_rate_limit_per_hour
            resets = None
            if oldest is not None:
                resets = max(0.0, round(60 - (_age_minutes(oldest) or 0), 1))
            res["rate_limit"] = {"limit": limit, "used_last_hour": int(used),
                                 "remaining": max(0, limit - int(used)),
                                 "pct_used": round(100.0 * int(used) / limit, 1) if limit else None,
                                 "oldest_call_expires_in_minutes": resets}
            rows = conn.execute(text("""
                SELECT source,
                       COUNT(*) AS calls,
                       COUNT(*) FILTER (WHERE NOT ok) AS errors,
                       ROUND(AVG(duration_ms))::int AS avg_ms,
                       MAX(called_at) AS last_call
                FROM api_call_log WHERE called_at > now() - interval '24 hours'
                GROUP BY source ORDER BY calls DESC""")).mappings().all()
            for r in rows:
                last = conn.execute(text("""
                    SELECT status_code, ok, error FROM api_call_log
                    WHERE source = :s ORDER BY called_at DESC LIMIT 1"""), {"s": r["source"]}).mappings().first()
                res["sources"].append({
                    "source": r["source"], "calls_24h": r["calls"], "errors_24h": r["errors"],
                    "error_rate_pct": round(100.0 * r["errors"] / r["calls"], 1) if r["calls"] else 0,
                    "avg_ms": r["avg_ms"], "last_call": r["last_call"].isoformat() if r["last_call"] else None,
                    "last_status_code": last["status_code"] if last else None,
                    "last_ok": last["ok"] if last else None,
                    "last_error": last["error"] if last else None,
                })
    except Exception as exc:
        res["error"] = str(exc)[:300]
    return res


def _probe_jobs(conn: Connection) -> list[dict[str, Any]]:
    s = get_settings()
    out = []
    try:
        with conn.begin_nested():
            rows = conn.execute(text("""
                SELECT DISTINCT ON (job) job, started_at, finished_at, status, rows_written, error, details
                FROM job_runs ORDER BY job, started_at DESC""")).mappings().all()
            for r in rows:
                agg = conn.execute(text("""
                    SELECT COUNT(*) AS runs, COUNT(*) FILTER (WHERE status = 'error') AS errors
                    FROM job_runs WHERE job = :j AND started_at > now() - interval '24 hours'"""),
                    {"j": r["job"]}).one()
                age = _age_minutes(r["started_at"])
                status = "ok"
                note = None
                if r["status"] == "error":
                    status, note = "error", r["error"]
                elif r["status"] == "running" and age is not None and age > s.status_job_stale_minutes:
                    status, note = "warn", f"still 'running' after {age:.0f} min (crashed?)"
                elif age is not None and age > s.status_job_stale_minutes and r["job"] in ("rt_ingestor",):
                    status, note = "warn", f"last run {age:.0f} min ago"
                duration = None
                if r["finished_at"] and r["started_at"]:
                    duration = round((r["finished_at"] - r["started_at"]).total_seconds(), 1)
                out.append({"job": r["job"], "status": status, "last_status": r["status"],
                            "last_started": r["started_at"].isoformat(),
                            "age_minutes": age, "duration_s": duration,
                            "rows_written": r["rows_written"], "error": r["error"], "note": note,
                            "details": r["details"], "runs_24h": agg.runs, "errors_24h": agg.errors})
    except Exception as exc:
        out.append({"job": "(job_runs unreadable)", "status": "error", "note": str(exc)[:200]})
    return out


def _probe_threads() -> list[dict[str, Any]]:
    expected = ["five11-rt-ingestor", "baseline-predictor"]
    alive = {t.name for t in threading.enumerate()}
    names = sorted({t.name for t in threading.enumerate()
                    if t.name in expected or "ingestor" in t.name or "predictor" in t.name
                    or "embed" in t.name or "traffic" in t.name or "alert" in t.name})
    return [{"name": n, "alive": n in alive} for n in sorted(set(names) | set(expected))]


def _probe_ollama() -> dict[str, Any]:
    s = get_settings()
    info: dict[str, Any] = {"url": s.ollama_url, "configured_model": s.ollama_model,
                            "reachable": False, "models": [], "model_present": False, "error": None}
    try:
        r = httpx.get(f"{s.ollama_url}/api/tags", timeout=2.0)
        r.raise_for_status()
        info["models"] = [m.get("name") for m in r.json().get("models", [])]
        info["reachable"] = True
        info["model_present"] = any(
            m == s.ollama_model or (m or "").split(":")[0] == s.ollama_model.split(":")[0] and ":" not in s.ollama_model
            for m in info["models"])
    except Exception as exc:
        info["error"] = str(exc)[:200]
    return info


def get_system_status(conn: Connection) -> dict[str, Any]:
    s = get_settings()
    db = _probe_db(conn)
    if not db["ok"]:
        return {"generated_at": datetime.now(timezone.utc).isoformat(), "overall": "error",
                "checks": [{"key": "database", "label": "Database", "status": "error",
                            "detail": db.get("error")}],
                "db": db, "data": [], "api": {"rate_limit": None, "sources": [], "error": None},
                "jobs": [], "threads": _probe_threads(), "services": {}}
    data = _probe_data(conn)
    api = _probe_api(conn)
    jobs = _probe_jobs(conn)
    threads = _probe_threads()
    ollama = _probe_ollama()

    checks: list[dict[str, Any]] = []

    def add(key: str, label: str, status: str, detail: str) -> None:
        checks.append({"key": key, "label": label, "status": status, "detail": detail})

    add("database", "Database", "ok", f"PostgreSQL {db['version']}, {db['latency_ms']} ms, {db['size_mb']} MB")
    add("pgvector", "pgvector extension", "ok" if "vector" in db["extensions"] else "warn",
        "installed" if "vector" in db["extensions"] else "missing: AI assistant RAG is inactive")
    add("five11_key", "511 API key", "ok" if s.five11_api_key else "error",
        "configured" if s.five11_api_key else "FIVE11_API_KEY is not set: no 511 data can load")

    rl = api["rate_limit"]
    if rl:
        pct = rl["pct_used"] or 0
        st = "error" if pct >= 100 else "warn" if pct >= 80 else "ok"
        add("five11_budget", "511 rate limit", st,
            f"{rl['used_last_hour']} of {rl['limit']} requests used in the last hour")
    elif api["error"]:
        add("five11_budget", "511 rate limit", "error", f"cannot read api_call_log: {api['error']}")

    src511 = next((x for x in api["sources"] if x["source"] == "511"), None)
    if src511 and src511["calls_24h"]:
        st = "error" if src511["error_rate_pct"] >= 50 else "warn" if src511["error_rate_pct"] >= 10 else "ok"
        detail = f"{src511['errors_24h']} of {src511['calls_24h']} calls failed in 24 h"
        if src511["last_ok"] is False:
            detail += f"; latest: {src511['last_error']}"
        add("five11_errors", "511 call errors", st, detail)

    for d in data:
        if d["table"] == "rt_vehicle_positions_raw":
            add("rt_fresh", "Live data freshness", d["status"],
                d["note"] or (f"latest position {d['age_minutes']:.0f} min ago" if d["age_minutes"] is not None
                              else "no data"))
    for j in jobs:
        add(f"job_{j['job']}", f"Job: {j['job']}", j["status"],
            j.get("note") or f"last run {j['last_status']}, {j['runs_24h']} runs / {j['errors_24h']} errors in 24 h")
    rt_thread = next((t for t in threads if t["name"] == "five11-rt-ingestor"), None)
    if rt_thread is not None:
        add("rt_thread", "RT ingestor in this API process", "ok" if rt_thread["alive"] else "warn",
            "running" if rt_thread["alive"] else
            "not running in this process (start uvicorn or python -m app.workers.run_rt_ingestor)")
    if ollama["reachable"]:
        add("ollama", "Ollama (AI chat)", "ok" if ollama["model_present"] else "warn",
            "model available" if ollama["model_present"] else
            f"model '{ollama['configured_model']}' not pulled (have: {', '.join(ollama['models']) or 'none'})")
    else:
        add("ollama", "Ollama (AI chat)", "warn", f"not reachable at {ollama['url']}")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall": _worst(*[c["status"] for c in checks]),
        "checks": checks, "db": db, "data": data, "api": api, "jobs": jobs,
        "threads": threads,
        "services": {"ollama": ollama, "five11_key_configured": bool(s.five11_api_key),
                     "backend_api_key_configured": bool(s.backend_api_key)},
    }


def get_api_calls(conn: Connection, *, source: str | None, errors_only: bool,
                  hours: int, limit: int) -> list[dict[str, Any]]:
    clauses = ["called_at > now() - make_interval(hours => :h)"]
    params: dict[str, Any] = {"h": hours, "limit": limit}
    if source:
        clauses.append("source = :source")
        params["source"] = source
    if errors_only:
        clauses.append("NOT ok")
    rows = conn.execute(text(f"""
        SELECT id, called_at, source, endpoint, status_code, ok, duration_ms, error
        FROM api_call_log WHERE {' AND '.join(clauses)}
        ORDER BY called_at DESC LIMIT :limit"""), params).mappings().all()
    return [{**dict(r), "called_at": r["called_at"].isoformat()} for r in rows]


def get_job_runs(conn: Connection, *, job: str | None, status: str | None,
                 limit: int) -> list[dict[str, Any]]:
    clauses = ["TRUE"]
    params: dict[str, Any] = {"limit": limit}
    if job:
        clauses.append("job = :job")
        params["job"] = job
    if status:
        clauses.append("status = :status")
        params["status"] = status
    rows = conn.execute(text(f"""
        SELECT id, job, started_at, finished_at, status, rows_written, details, error
        FROM job_runs WHERE {' AND '.join(clauses)}
        ORDER BY started_at DESC LIMIT :limit"""), params).mappings().all()
    return [{**dict(r), "started_at": r["started_at"].isoformat(),
             "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None}
            for r in rows]

"""Activity cards for the System Status dashboard.

Every backend operation (ingestors, loaders, schedulers, external APIs, the
database) is one *activity*. `list_activities()` returns one summary card per
activity; `get_activity_detail()` returns the full breakdown of one activity in
categories (overview, progress, runs, api_calls, data, errors, config, logs).
Read-only, and each probe is isolated so one failure never hides the others.
"""
from __future__ import annotations

import re
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.config import get_settings
from app.core.redact import redact_secrets

REPO_ROOT = Path(__file__).resolve().parents[3]
_LOG_TAIL_LINES = 120

# ── Catalog ───────────────────────────────────────────────────────────────────
# kind: job (has job_runs) | api (external HTTP source) | service | infra
CATALOG: list[dict[str, Any]] = [
    {
        "key": "rt_ingestor", "title": "Live vehicles & trip updates", "category": "Ingestion", "kind": "job",
        "description": "Polls the 511.org GTFS-Realtime feeds for every Bay Area agency and stores vehicle "
                       "positions and stop-level delays. This is the only source of live delay data.",
        "how": ["Fetch /Transit/VehiclePositions and /Transit/TripUpdates (agency=RG): 2 requests per cycle",
                "Strip the agency prefix from trip, route and stop ids and resolve stop_pk",
                "Insert vehicle positions into rt_vehicle_positions_raw",
                "Replace stop-level events per trip in ops_trip_events (delays beyond 2 h are nulled)",
                "Delete positions older than 30 days"],
        "jobs": ["rt_ingestor"], "api_source": "511", "api_like": ["%/Transit/VehiclePositions%", "%/Transit/TripUpdates%"],
        "tables": [("rt_vehicle_positions_raw", "Vehicle positions"), ("ops_trip_events", "Trip events (delays)")],
        "schedule": "Every {five11_rt_poll_seconds}s while uvicorn or the run_rt_ingestor worker is running",
        "command": "python -m app.workers.run_rt_ingestor   (or start uvicorn, which runs it as a thread)",
        "settings": ["five11_rt_poll_seconds", "five11_rate_limit_per_hour", "five11_base_url"],
        "stale_attr": "five11_rt_poll_seconds", "stale_factor": 3,
    },
    {
        "key": "stop_obs_backfill", "title": "Stop observations backfill", "category": "Ingestion", "kind": "job",
        "description": "Loads the 511.org monthly archive of actual vs scheduled arrival times, up to two months "
                       "per night, newest first. Daily cron fills history gradually.",
        "how": ["Pick the newest missing month within the backfill horizon (repeat for each month per run, one transaction each)",
                "Take a Postgres advisory lock so two loaders cannot run at once",
                "Download the month's zip from /transit/datafeeds (about 500 MB)",
                "Stream the CSV in 100k-row chunks, parse arrival times, insert into stop_observations",
                "Resolve stop_pk for the month, then commit"],
        "jobs": ["stop_observations_load"], "api_source": "511", "api_like": ["%/transit/datafeeds%"],
        "tables": [("stop_observations", "Stop observations")],
        "schedule": "Daily 03:00 (user crontab)",
        "command": "python -m app.workers.backfill_stop_observations   (a number loads that many months)",
        "settings": ["stop_obs_backfill_months_per_run", "stop_obs_backfill_max_months_back"],
        "log_file": "backend/logs/backfill_stop_observations.log", "stale_minutes": 360,
    },
    {
        "key": "etl", "title": "Data jobs (ETL)", "category": "Ingestion", "kind": "job",
        "description": "The 20-step pipeline that loads GTFS, census, safety and fare data and rebuilds "
                       "features, predictions, coverage and gap tables.",
        "how": ["Step through 0..17 in run_data_jobs.py; each step is isolated, a failed step is skipped",
                "Progress and per-step notes are recorded below"],
        "jobs": ["etl_run_data_jobs"], "api_source": None, "api_like": [],
        "tables": [("gtfs_stops", "GTFS stops"), ("gtfs_stop_times", "GTFS stop times"),
                   ("safety_incidents_raw", "Safety incidents"), ("coverage_cells", "Coverage cells"),
                   ("stop_features", "Stop features"), ("stop_ada_gap", "ADA gap")],
        "schedule": "Manual", "command": "python -m app.workers.run_data_jobs",
        "settings": [], "stale_minutes": 720,
    },
    {
        "key": "traffic", "title": "Traffic, work zones & tolls", "category": "Ingestion", "kind": "job",
        "description": "Polls 511 for road incidents, work zones and toll rates.",
        "how": ["Fetch /traffic/events, /traffic/wzdx and /toll/programs", "Upsert traffic_events, work_zones, toll_rates"],
        "jobs": ["traffic_loop"], "api_source": "511", "api_like": ["%/traffic/%", "%/toll/%"],
        "tables": [("traffic_events", "Traffic events"), ("work_zones", "Work zones"), ("toll_rates", "Toll rates")],
        "schedule": "Every {five11_traffic_poll_seconds}s while uvicorn is running", "command": "started by uvicorn (app.main lifespan)",
        "settings": ["five11_traffic_poll_seconds", "five11_rate_limit_per_hour"], "stale_minutes": 45,
    },
    {
        "key": "baseline", "title": "Delay baseline predictor", "category": "Processing", "kind": "job",
        "description": "SQL baseline that refreshes delay, bunching, demand and crowding predictions from observed events.",
        "how": ["Aggregate recent ops_trip_events", "Write delay, bunching, demand and crowding prediction tables"],
        "jobs": ["baseline_predictor"], "api_source": None, "api_like": [],
        "tables": [("delay_predictions", "Delay predictions"), ("bunching_predictions", "Bunching predictions"),
                   ("demand_forecasts", "Demand forecasts"), ("crowding_predictions", "Crowding predictions")],
        "schedule": "Every 30 min while uvicorn is running", "command": "started by uvicorn (ml.baseline)",
        "settings": [], "stale_minutes": 90,
    },
    {
        "key": "embed", "title": "AI embeddings", "category": "Processing", "kind": "job",
        "description": "Builds sentence-transformer embeddings of routes, stops and operations summaries for the AI assistant's retrieval.",
        "how": ["Build route, stop and ops-summary texts", "Embed with the configured model", "Upsert into ai_embeddings (pgvector)"],
        "jobs": ["embed_pipeline"], "api_source": None, "api_like": [],
        "tables": [("ai_embeddings", "Embeddings")],
        "schedule": "Every 30 min while uvicorn is running", "command": "started by uvicorn (ml.embed)",
        "settings": ["embed_model_name"], "stale_minutes": 90,
    },
    {
        "key": "transfer", "title": "Transfer reliability", "category": "Processing", "kind": "job",
        "description": "Matches stops of different agencies by distance and measures how often a connection can be made.",
        "how": ["Rebuild stop_transfer_links (cross-agency pairs up to the largest radius)",
                "Collect arrivals from stop_observations and ops_trip_events",
                "For each arrival find the next arrival at the linked stop and test it against the walk time",
                "Write one row per stop pair; the radius is applied when reading"],
        "jobs": ["transfer_reliability_compute"], "api_source": None, "api_like": [],
        "tables": [("transfer_reliability", "Transfer reliability"), ("stop_transfer_links", "Stop transfer links")],
        "schedule": "ETL step 12, or on demand", "command": "compute_transfer_reliability(conn, days=14)",
        "settings": ["transfer_radii_m", "transfer_default_radius_m", "transfer_walk_speed_mps"], "stale_minutes": 10080,
    },
    {
        "key": "api_511", "title": "511.org API", "category": "External APIs", "kind": "api",
        "description": "Regional transit data. Limit: 60 requests per rolling hour, shared by every 511 activity.",
        "how": [], "jobs": [], "api_source": "511", "api_like": [], "tables": [],
        "schedule": "On demand", "command": "", "settings": ["five11_base_url", "five11_rate_limit_per_hour"],
    },
    {
        "key": "api_oakland", "title": "Oakland open data", "category": "External APIs", "kind": "api",
        "description": "Oakland crime and collision data (Socrata) used for safety scores.",
        "how": [], "jobs": [], "api_source": "oakland_open_data", "api_like": [], "tables": [],
        "schedule": "ETL steps 8 and 9", "command": "", "settings": [],
    },
    {
        "key": "api_census", "title": "Census (ACS + TIGERweb)", "category": "External APIs", "kind": "api",
        "description": "Tract geometry and demographic tables for equity, ADA and fare burden.",
        "how": [], "jobs": [], "api_source": "census", "api_like": [], "tables": [],
        "schedule": "ETL steps 3.5, 4.5 and 11", "command": "", "settings": ["tigerweb_base_url"],
    },
    {
        "key": "ollama", "title": "Ollama (local LLM)", "category": "External APIs", "kind": "service",
        "description": "Local language model that answers AI assistant questions.",
        "how": [], "jobs": [], "api_source": None, "api_like": [], "tables": [],
        "schedule": "On demand", "command": "ollama pull <model>", "settings": ["ollama_url", "ollama_model"],
    },
    {
        "key": "database", "title": "PostgreSQL database", "category": "Infrastructure", "kind": "infra",
        "description": "PostGIS + pgvector database that holds everything.",
        "how": [], "jobs": [], "api_source": None, "api_like": [], "tables": [],
        "schedule": "Always on", "command": "docker compose up -d postgres", "settings": ["run_log_retention_days"],
    },
    {
        "key": "scheduler", "title": "Scheduler (cron)", "category": "Infrastructure", "kind": "infra",
        "description": "User crontab entries that run BATIS jobs.",
        "how": [], "jobs": ["stop_observations_load"], "api_source": None, "api_like": [], "tables": [],
        "schedule": "Daily 03:00", "command": "crontab -l", "settings": [],
        "log_file": "backend/logs/backfill_stop_observations.log",
    },
    {
        "key": "api_process", "title": "API process threads", "category": "Infrastructure", "kind": "infra",
        "description": "Background threads that uvicorn starts (RT ingestor, baseline, embeddings, traffic).",
        "how": [], "jobs": [], "api_source": None, "api_like": [], "tables": [],
        "schedule": "While uvicorn runs", "command": "uvicorn app.main:app", "settings": [],
    },
]
_BY_KEY = {a["key"]: a for a in CATALOG}
CATEGORY_ORDER = ["Ingestion", "Processing", "External APIs", "Infrastructure"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _age_min(ts: datetime | None) -> float | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return round((_now() - ts).total_seconds() / 60.0, 1)


def _iso(ts: datetime | None) -> str | None:
    return ts.isoformat() if ts else None


def _fmt_schedule(act: dict[str, Any]) -> str:
    s = get_settings()
    try:
        return act["schedule"].format(**{k: getattr(s, k) for k in ("five11_rt_poll_seconds", "five11_traffic_poll_seconds")})
    except Exception:
        return act["schedule"]


def _stale_minutes(act: dict[str, Any]) -> float:
    s = get_settings()
    if act.get("stale_attr"):
        return getattr(s, act["stale_attr"]) * act.get("stale_factor", 3) / 60.0 + 1
    return float(act.get("stale_minutes", s.status_job_stale_minutes))


def _cron_lines() -> list[str]:
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=3).stdout
    except Exception:
        return []
    return [ln for ln in out.splitlines() if "batis" in ln.lower() and not ln.strip().startswith("#")]


def _next_cron_run() -> datetime | None:
    """Next local run of the BATIS backfill entry, for simple 'M H * * *' lines."""
    for ln in _cron_lines():
        m = re.match(r"^\s*(\d+)\s+(\d+)\s+\*\s+\*\s+\*\s", ln)
        if m:
            now = datetime.now().astimezone()
            nxt = now.replace(hour=int(m.group(2)), minute=int(m.group(1)), second=0, microsecond=0)
            if nxt <= now:
                nxt += timedelta(days=1)
            return nxt
    return None


def _setting_values(names: list[str]) -> list[dict[str, Any]]:
    s = get_settings()
    out = []
    for n in names:
        if hasattr(s, n):
            out.append({"name": n.upper(), "value": getattr(s, n)})
    return out


def _tail(path: Path, n: int = _LOG_TAIL_LINES) -> list[str]:
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 200_000))
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    lines = [redact_secrets(ln.rstrip()) for ln in data.splitlines()]
    # Drop pandas' repeated per-chunk UserWarning noise, it hides real messages.
    lines = [ln for ln in lines if "UserWarning" not in ln and "pd.to_datetime(series" not in ln]
    return lines[-n:]


# ── Per-source / per-job queries ──────────────────────────────────────────────

def _like_clause(patterns: list[str], col: str = "endpoint") -> tuple[str, dict[str, Any]]:
    if not patterns:
        return "TRUE", {}
    parts = [f"{col} LIKE :p{i}" for i in range(len(patterns))]
    return "(" + " OR ".join(parts) + ")", {f"p{i}": p for i, p in enumerate(patterns)}


def _api_stats(conn: Connection, source: str | None, like: list[str], hours: int = 24) -> dict[str, Any]:
    if not source:
        return {"calls": 0, "errors": 0, "avg_ms": None, "last_call": None, "last_ok": None, "last_error": None}
    clause, params = _like_clause(like)
    params.update({"s": source, "h": hours})
    row = conn.execute(text(f"""
        SELECT COUNT(*) calls, COUNT(*) FILTER (WHERE NOT ok) errors,
               ROUND(AVG(duration_ms))::int avg_ms, MAX(called_at) last_call
        FROM api_call_log
        WHERE source = :s AND called_at > now() - make_interval(hours => :h) AND {clause}"""), params).mappings().one()
    last = conn.execute(text(f"""
        SELECT ok, error, status_code FROM api_call_log
        WHERE source = :s AND {clause} ORDER BY called_at DESC LIMIT 1"""), params).mappings().first()
    return {"calls": row["calls"], "errors": row["errors"], "avg_ms": row["avg_ms"],
            "last_call": _iso(row["last_call"]),
            "last_ok": last["ok"] if last else None,
            "last_error": last["error"] if last else None,
            "last_status": last["status_code"] if last else None}


def _job_summary(conn: Connection, jobs: list[str]) -> dict[str, Any]:
    if not jobs:
        return {}
    last = conn.execute(text("""
        SELECT id, job, started_at, finished_at, status, rows_written, error, details
        FROM job_runs WHERE job = ANY(:j) ORDER BY started_at DESC LIMIT 1"""), {"j": jobs}).mappings().first()
    agg = conn.execute(text("""
        SELECT COUNT(*) runs, COUNT(*) FILTER (WHERE status = 'error') errors,
               COUNT(*) FILTER (WHERE status = 'ok') oks
        FROM job_runs WHERE job = ANY(:j) AND started_at > now() - interval '24 hours'"""), {"j": jobs}).mappings().one()
    last_ok = conn.execute(text("""
        SELECT started_at, finished_at, rows_written FROM job_runs
        WHERE job = ANY(:j) AND status = 'ok' ORDER BY started_at DESC LIMIT 1"""), {"j": jobs}).mappings().first()
    return {"last": dict(last) if last else None, "runs_24h": agg["runs"], "errors_24h": agg["errors"],
            "last_ok": dict(last_ok) if last_ok else None}


def _backfill_months(conn: Connection) -> list[dict[str, Any]]:
    """Per-month state of the stop_observations backfill horizon."""
    from app.services.five11_stop_observations import _month_date_range, get_available_months
    s = get_settings()
    months = get_available_months()[-s.stop_obs_backfill_max_months_back:]
    rows_by_month = {r["month"]: r for r in conn.execute(text("""
        SELECT details->>'month' AS month, rows_written, finished_at FROM job_runs
        WHERE job = 'stop_observations_load' AND status = 'ok' AND details ? 'month'
        ORDER BY started_at""")).mappings()}
    running = conn.execute(text("""
        SELECT details FROM job_runs WHERE job = 'stop_observations_load' AND status = 'running'
        ORDER BY started_at DESC LIMIT 1""")).scalar()
    running_month = (running or {}).get("month")
    out = []
    for ym in reversed(months):  # newest first
        first, last = _month_date_range(ym)
        loaded = bool(conn.execute(text(
            "SELECT EXISTS (SELECT 1 FROM stop_observations WHERE service_date >= :a AND service_date <= :b)"),
            {"a": first, "b": last}).scalar())
        rec = rows_by_month.get(ym)
        if ym == running_month and not loaded:
            state = "loading"
        elif loaded:
            state = "loaded"
        else:
            state = "waiting"
        out.append({"month": ym, "state": state, "rows": rec["rows_written"] if rec else None,
                    "loaded_at": _iso(rec["finished_at"]) if rec else None,
                    "source": "backfill run" if rec else ("earlier load" if loaded else None)})
    return out


def _expected_month_rows(conn: Connection, loaded_months: int) -> int | None:
    """Average rows per loaded month (estimated table rows / loaded months), used to turn
    rows-inserted into an approximate percentage."""
    est = conn.execute(text(
        "SELECT reltuples::bigint FROM pg_class WHERE oid = to_regclass('public.stop_observations')")).scalar() or 0
    return int(est / loaded_months) if est and loaded_months else None


def _progress_for(conn: Connection, act: dict[str, Any], summary: dict[str, Any],
                  ctx: dict[str, Any]) -> dict[str, Any] | None:
    last = (summary.get("last") or {})
    if last.get("status") != "running":
        return None
    d = last.get("details") or {}
    started = last.get("started_at")
    elapsed = round((_now() - started).total_seconds() / 60.0, 1) if started else None
    key = act["key"]
    if key == "stop_obs_backfill":
        phase = d.get("phase", "starting")
        label = f"{d.get('month', '?')}: {phase}"
        pct = None
        if phase == "downloading":
            mb = (d.get("bytes_done") or 0) / 1_048_576
            label += f" ({mb:,.0f} MB" + (f" of {d['bytes_total'] / 1_048_576:,.0f} MB)" if d.get("bytes_total") else ")")
        elif phase.startswith("parsing") or phase.startswith("resolving"):
            rows = d.get("rows_inserted") or 0
            label += f" ({rows:,} rows)"
            exp = _expected_month_rows(conn, sum(1 for m in ctx.get('months', []) if m['state'] == 'loaded'))
            if exp:
                pct = min(99, round(100 * rows / exp))
                label += f", about {pct}% of a typical month"
        return {"label": label, "pct": pct, "elapsed_minutes": elapsed, "details": d}
    if key == "etl":
        step = d.get("current_step")
        steps = d.get("steps") or []
        title = steps[-1]["title"] if steps else ""
        pct = None
        if step:
            try:
                pct = round(100 * float(step.split("/")[0]) / 18)
            except ValueError:
                pass
        return {"label": f"Step {step}: {title}" if step else "starting", "pct": pct,
                "elapsed_minutes": elapsed, "details": d}
    return {"label": d.get("phase", "running"), "pct": None, "elapsed_minutes": elapsed, "details": d}


# ── Summary cards ─────────────────────────────────────────────────────────────

def _status_for_job(act: dict[str, Any], js: dict[str, Any]) -> tuple[str, str]:
    last = js.get("last")
    if not last:
        return "idle", "Not run yet"
    age = _age_min(last["started_at"])
    stale = _stale_minutes(act)
    if last["status"] == "running":
        if age is not None and age > stale:
            return "warn", f"Running for {age:.0f} min, may be stuck"
        return "running", f"Running for {age:.0f} min" if age is not None else "Running"
    if last["status"] == "error":
        return "error", (last.get("error") or "Last run failed")[:140]
    if age is not None and age > stale and act["key"] in ("rt_ingestor", "traffic", "baseline", "embed"):
        return "warn", f"Last run {age:.0f} min ago, not running now"
    rows = last.get("rows_written")
    return "ok", f"Last run {_ago(age)}" + (f", {rows:,} rows" if rows is not None else "")


def _ago(age_min: float | None) -> str:
    if age_min is None:
        return "never"
    if age_min < 1:
        return "just now"
    if age_min < 90:
        return f"{age_min:.0f} min ago"
    if age_min < 2880:
        return f"{age_min / 60:.1f} h ago"
    return f"{age_min / 1440:.0f} d ago"


def _card(conn: Connection, act: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    card: dict[str, Any] = {
        "key": act["key"], "title": act["title"], "category": act["category"], "kind": act["kind"],
        "description": act["description"], "schedule": _fmt_schedule(act),
        "status": "ok", "headline": "", "metrics": [], "progress": None, "next_run": None,
    }
    s = get_settings()
    kind = act["kind"]
    if kind == "job":
        js = _job_summary(conn, act["jobs"])
        card["status"], card["headline"] = _status_for_job(act, js)
        card["metrics"] = [{"label": "Runs (24 h)", "value": str(js.get("runs_24h", 0))},
                           {"label": "Errors (24 h)", "value": str(js.get("errors_24h", 0))}]
        last_ok = js.get("last_ok")
        if last_ok and last_ok.get("rows_written") is not None:
            card["metrics"].append({"label": "Rows, last ok run", "value": f"{last_ok['rows_written']:,}"})
        card["progress"] = _progress_for(conn, act, js, ctx)
        if act["key"] == "stop_obs_backfill":
            months = ctx["months"]
            done = sum(1 for m in months if m["state"] == "loaded")
            card["metrics"].insert(0, {"label": "Months loaded", "value": f"{done} of {len(months)}"})
            frac = 0.0
            if card["progress"] and card["progress"].get("pct") is not None:
                frac = card["progress"]["pct"] / 100.0
            overall = round(100 * (done + frac) / max(1, len(months)))
            if card["progress"]:
                card["progress"] = {**card["progress"], "overall_pct": overall,
                                    "overall_label": f"{done} of {len(months)} months loaded"}
            else:
                card["progress"] = {"label": f"{done} of {len(months)} months loaded", "pct": overall,
                                    "overall_pct": overall, "overall_label": None, "elapsed_minutes": None, "details": {}}
            if done == len(months) and card["status"] not in ("error", "running"):
                card["status"], card["headline"] = "ok", f"Complete: all {len(months)} months in range loaded"
            card["next_run"] = _iso(_next_cron_run())
        if act["key"] == "rt_ingestor" and ctx.get("rt"):
            card["metrics"].append({"label": "511 budget used", "value": ctx["rt"]})
    elif kind == "api":
        st = _api_stats(conn, act["api_source"], act["api_like"])
        card["metrics"] = [{"label": "Calls (24 h)", "value": str(st["calls"])},
                           {"label": "Errors (24 h)", "value": str(st["errors"])},
                           {"label": "Avg latency", "value": f"{st['avg_ms']} ms" if st["avg_ms"] is not None else "—"}]
        if not st["calls"]:
            card["status"], card["headline"] = "idle", "No calls in the last 24 h"
        else:
            rate = 100.0 * st["errors"] / st["calls"]
            card["status"] = "error" if rate >= 50 else "warn" if rate >= 10 else "ok"
            card["headline"] = (f"Last call failed: {st['last_error']}" if st["last_ok"] is False
                                else f"Last call {_ago(_age_min(datetime.fromisoformat(st['last_call'])))}")
        if act["key"] == "api_511":
            used = ctx.get("used_511", 0)
            card["metrics"].insert(0, {"label": "Used this hour", "value": f"{used} / {s.five11_rate_limit_per_hour}"})
            pct = 100.0 * used / s.five11_rate_limit_per_hour if s.five11_rate_limit_per_hour else 0
            if pct >= 100:
                card["status"] = "error"
            elif pct >= 80 and card["status"] == "ok":
                card["status"] = "warn"
            card["progress"] = {"label": f"{used} of {s.five11_rate_limit_per_hour} requests this hour",
                                "pct": round(min(100, pct)), "elapsed_minutes": None, "details": {}}
    elif act["key"] == "ollama":
        info = ctx["ollama"]
        card["metrics"] = [{"label": "Models", "value": str(len(info["models"]))},
                           {"label": "Configured", "value": info["configured_model"]}]
        if not info["reachable"]:
            card["status"], card["headline"] = "warn", f"Not reachable at {info['url']}"
        elif not info["model_present"]:
            card["status"], card["headline"] = "warn", f"Model {info['configured_model']} is not pulled"
        else:
            card["status"], card["headline"] = "ok", "Reachable, configured model available"
    elif act["key"] == "database":
        db = ctx["db"]
        card["metrics"] = [{"label": "Size", "value": f"{db['size_mb'] / 1024:.1f} GB"},
                           {"label": "Latency", "value": f"{db['latency_ms']} ms"},
                           {"label": "Connections", "value": str(db["connections"])}]
        card["status"] = "ok" if "vector" in db["extensions"] else "warn"
        card["headline"] = f"PostgreSQL {db['version'].split()[0]}, extensions: {', '.join(db['extensions'])}"
    elif act["key"] == "scheduler":
        lines = _cron_lines()
        nxt = _next_cron_run()
        card["metrics"] = [{"label": "BATIS entries", "value": str(len(lines))}]
        card["status"] = "ok" if lines else "warn"
        card["headline"] = (f"Next run {nxt.strftime('%Y-%m-%d %H:%M')}" if nxt else
                            "No BATIS cron entry found for this user" if not lines else "Entry installed")
        card["next_run"] = _iso(nxt)
    elif act["key"] == "api_process":
        threads = ctx["threads"]
        alive = sum(1 for t in threads if t["alive"])
        card["metrics"] = [{"label": "Threads running", "value": f"{alive} of {len(threads)}"}]
        card["status"] = "ok" if alive == len(threads) else "warn"
        card["headline"] = ("All background threads running" if alive == len(threads)
                            else "Not running in this process: start uvicorn or run_rt_ingestor")
    return card


def list_activities(conn: Connection) -> dict[str, Any]:
    from app.services.system_status import _probe_ollama, _probe_threads
    s = get_settings()
    ctx: dict[str, Any] = {"threads": _probe_threads(), "ollama": _probe_ollama()}
    try:
        ctx["used_511"] = conn.execute(text(
            "SELECT COUNT(*) FROM api_call_log WHERE source = '511' AND called_at > now() - interval '1 hour'")).scalar() or 0
        ctx["rt"] = f"{ctx['used_511']} / {s.five11_rate_limit_per_hour}"
    except Exception:
        ctx["used_511"] = 0
    try:
        t0 = time.monotonic()
        ver = conn.execute(text("SHOW server_version")).scalar()
        ctx["db"] = {
            "version": ver, "latency_ms": int((time.monotonic() - t0) * 1000),
            "size_mb": int(conn.execute(text("SELECT pg_database_size(current_database()) / 1048576")).scalar() or 0),
            "connections": conn.execute(text("SELECT COUNT(*) FROM pg_stat_activity WHERE datname = current_database()")).scalar(),
            "extensions": [r[0] for r in conn.execute(text("SELECT extname FROM pg_extension WHERE extname IN ('postgis','vector') ORDER BY 1"))],
        }
    except Exception as exc:
        ctx["db"] = {"version": "unknown", "latency_ms": -1, "size_mb": 0, "connections": 0, "extensions": [], "error": str(exc)}
    try:
        ctx["months"] = _backfill_months(conn)
    except Exception:
        ctx["months"] = []
    cards = []
    for act in CATALOG:
        try:
            with conn.begin_nested():
                cards.append(_card(conn, act, ctx))
        except Exception as exc:
            cards.append({"key": act["key"], "title": act["title"], "category": act["category"], "kind": act["kind"],
                          "description": act["description"], "schedule": _fmt_schedule(act), "status": "error",
                          "headline": f"Cannot read status: {str(exc)[:120]}", "metrics": [], "progress": None, "next_run": None})
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    cards.sort(key=lambda c: order.get(c["category"], 99))
    worst = max((c["status"] for c in cards), key=lambda x: {"ok": 0, "idle": 0, "running": 0, "warn": 1, "error": 2}[x], default="ok")
    return {"generated_at": _now().isoformat(), "categories": CATEGORY_ORDER, "cards": cards,
            "overall": "error" if worst == "error" else "warn" if worst == "warn" else "ok"}


# ── Detail ────────────────────────────────────────────────────────────────────

def _table_info(conn: Connection, table: str, label: str) -> dict[str, Any]:
    item: dict[str, Any] = {"table": table, "label": label, "rows": None, "size": None, "latest": None, "note": None}
    try:
        with conn.begin_nested():
            reg = conn.execute(text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}).scalar()
            if not reg:
                item["note"] = "table missing"
                return item
            est = conn.execute(text("SELECT reltuples::bigint FROM pg_class WHERE oid = to_regclass(:t)"), {"t": f"public.{table}"}).scalar() or 0
            if est < 200000:
                item["rows"] = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            else:
                item["rows"], item["note"] = int(est), "row count is an estimate"
            item["size"] = conn.execute(text("SELECT pg_size_pretty(pg_total_relation_size(to_regclass(:t)))"), {"t": f"public.{table}"}).scalar()
            ts = {"rt_vehicle_positions_raw": "MAX(timestamp)", "ops_trip_events": "MAX(service_date)::timestamptz",
                  "stop_observations": "MAX(service_date)::timestamptz", "transfer_reliability": "MAX(computed_at)",
                  "ai_embeddings": "MAX(updated_at)"}.get(table)
            if ts:
                latest = conn.execute(text(f"SELECT {ts} FROM {table}")).scalar()
                item["latest"] = _iso(latest)
    except Exception as exc:
        item["note"] = str(exc)[:160]
    return item


def _runs(conn: Connection, jobs: list[str], limit: int = 25) -> list[dict[str, Any]]:
    rows = conn.execute(text("""
        SELECT id, job, started_at, finished_at, status, rows_written, details, error
        FROM job_runs WHERE job = ANY(:j) ORDER BY started_at DESC LIMIT :n"""), {"j": jobs, "n": limit}).mappings().all()
    out = []
    for r in rows:
        end = r["finished_at"] or (_now() if r["status"] == "running" else None)
        out.append({"id": r["id"], "job": r["job"], "started_at": _iso(r["started_at"]),
                    "finished_at": _iso(r["finished_at"]), "status": r["status"], "rows_written": r["rows_written"],
                    "duration_s": round((end - r["started_at"]).total_seconds(), 1) if end else None,
                    "details": r["details"], "error": r["error"]})
    return out


def _api_section(conn: Connection, act: dict[str, Any]) -> dict[str, Any] | None:
    if not act.get("api_source"):
        return None
    clause, params = _like_clause(act["api_like"])
    params["s"] = act["api_source"]
    calls = conn.execute(text(f"""
        SELECT id, called_at, endpoint, status_code, ok, duration_ms, error FROM api_call_log
        WHERE source = :s AND {clause} ORDER BY called_at DESC LIMIT 60"""), params).mappings().all()
    by_ep = conn.execute(text(f"""
        SELECT endpoint, COUNT(*) calls, COUNT(*) FILTER (WHERE NOT ok) errors,
               ROUND(AVG(duration_ms))::int avg_ms, MAX(called_at) last_call
        FROM api_call_log WHERE source = :s AND {clause} AND called_at > now() - interval '24 hours'
        GROUP BY endpoint ORDER BY calls DESC"""), params).mappings().all()
    return {
        "summary": _api_stats(conn, act["api_source"], act["api_like"]),
        "by_endpoint": [{**dict(r), "last_call": _iso(r["last_call"])} for r in by_ep],
        "calls": [{**dict(r), "called_at": _iso(r["called_at"])} for r in calls],
    }


def get_activity_detail(conn: Connection, key: str) -> dict[str, Any] | None:
    act = _BY_KEY.get(key)
    if not act:
        return None
    from app.services.system_status import _probe_ollama, _probe_threads
    s = get_settings()
    ctx: dict[str, Any] = {"threads": _probe_threads(), "ollama": _probe_ollama()}
    try:
        ctx["months"] = _backfill_months(conn) if key == "stop_obs_backfill" else []
        ctx["used_511"] = conn.execute(text(
            "SELECT COUNT(*) FROM api_call_log WHERE source = '511' AND called_at > now() - interval '1 hour'")).scalar() or 0
        ctx["db"] = {"version": conn.execute(text("SHOW server_version")).scalar(), "latency_ms": 0,
                     "size_mb": int(conn.execute(text("SELECT pg_database_size(current_database()) / 1048576")).scalar() or 0),
                     "connections": conn.execute(text("SELECT COUNT(*) FROM pg_stat_activity WHERE datname = current_database()")).scalar(),
                     "extensions": [r[0] for r in conn.execute(text("SELECT extname FROM pg_extension WHERE extname IN ('postgis','vector') ORDER BY 1"))]}
    except Exception:
        pass
    ctx.setdefault("db", {"version": "?", "latency_ms": -1, "size_mb": 0, "connections": 0, "extensions": []})
    card = _card(conn, act, ctx)
    sections: dict[str, Any] = {}

    # overview
    sections["overview"] = {
        "description": act["description"], "how_it_works": act["how"], "schedule": _fmt_schedule(act),
        "command": act["command"], "next_run": card["next_run"],
        "status": card["status"], "headline": card["headline"], "metrics": card["metrics"],
        "used_by_note": "Shares the 511 limit of 60 requests per hour with every other 511 activity."
                        if act.get("api_source") == "511" else None,
    }

    # progress / breakdown
    progress: dict[str, Any] = {"current": card["progress"]}
    if key == "stop_obs_backfill":
        months = ctx["months"]
        progress["months"] = months
        progress["target"] = {"horizon_months": s.stop_obs_backfill_max_months_back,
                              "months_per_run": s.stop_obs_backfill_months_per_run}
    elif key == "etl":
        last = (_job_summary(conn, act["jobs"]).get("last") or {})
        d = last.get("details") or {}
        steps = []
        for st in d.get("steps") or []:
            a = datetime.fromisoformat(st["started_at"])
            b = datetime.fromisoformat(st["finished_at"]) if st.get("finished_at") else (_now() if last.get("status") == "running" else None)
            steps.append({**st, "duration_s": round((b - a).total_seconds(), 1) if b else None,
                          "state": "running" if not st.get("finished_at") and last.get("status") == "running"
                          else "warn" if st.get("notes") else "done"})
        progress["steps"] = steps
        progress["run_started_at"] = _iso(last.get("started_at"))
    elif key == "rt_ingestor":
        try:
            rows = conn.execute(text("""
                SELECT agency_id, COUNT(*) vehicles, MAX(timestamp) latest
                FROM rt_vehicle_positions_raw WHERE timestamp > now() - interval '30 minutes'
                GROUP BY agency_id ORDER BY vehicles DESC""")).mappings().all()
            progress["agencies_last_30_min"] = [{**dict(r), "latest": _iso(r["latest"])} for r in rows]
        except Exception:
            progress["agencies_last_30_min"] = []
    elif key == "api_process":
        progress["threads"] = ctx["threads"]
    # Only show a Progress tab when there is something to show.
    if (progress["current"] or len(progress) > 1):
        sections["progress"] = progress

    # runs
    if act["jobs"]:
        sections["runs"] = {"runs": _runs(conn, act["jobs"])}

    # api calls
    api = _api_section(conn, act)
    if api is not None:
        sections["api_calls"] = api

    # data written
    if act["tables"]:
        sections["data"] = {"tables": [_table_info(conn, t, lbl) for t, lbl in act["tables"]]}

    # activity-specific extras
    if key == "database":
        big = conn.execute(text("""
            SELECT relname AS table, pg_size_pretty(pg_total_relation_size(c.oid)) AS size,
                   c.reltuples::bigint AS est_rows
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
            ORDER BY pg_total_relation_size(c.oid) DESC LIMIT 15""")).mappings().all()
        sections["data"] = {"tables": [{"table": r["table"], "label": r["table"], "rows": max(0, r["est_rows"]),
                                        "size": r["size"], "latest": None, "note": "row count is an estimate"} for r in big]}
        active = conn.execute(text("""
            SELECT pid, state, clock_timestamp() - query_start AS running_for, wait_event_type,
                   LEFT(regexp_replace(query, '\\s+', ' ', 'g'), 220) AS query
            FROM pg_stat_activity
            WHERE datname = current_database() AND pid <> pg_backend_pid() AND state <> 'idle'
            ORDER BY query_start LIMIT 15""")).mappings().all()
        sections["activity"] = {"queries": [{**dict(r), "running_for": str(r["running_for"]).split(".")[0]} for r in active]}
        sections["overview"]["database"] = {k: v for k, v in ctx["db"].items() if k != "error"}
    if key == "scheduler":
        lines = _cron_lines()
        sections["config"] = {"crontab": lines}
        sections["runs"] = {"runs": _runs(conn, act["jobs"], 10)}
    if key == "ollama":
        sections["service"] = ctx["ollama"]
    if key == "api_511":
        sections["overview"]["budget"] = {"used_last_hour": ctx["used_511"], "limit": s.five11_rate_limit_per_hour}

    # errors (failed runs + failed calls)
    errs: list[dict[str, Any]] = []
    for r in (sections.get("runs", {}).get("runs") or []):
        if r["status"] == "error":
            errs.append({"when": r["started_at"], "kind": "job run", "where": r["job"], "message": r["error"] or "failed"})
    if api is not None:
        for c in api["calls"]:
            if not c["ok"]:
                errs.append({"when": c["called_at"], "kind": "API call", "where": c["endpoint"],
                             "message": c["error"] or f"HTTP {c['status_code']}"})
    errs.sort(key=lambda e: e["when"] or "", reverse=True)
    sections["errors"] = {"items": errs[:50]}

    # config
    cfg = sections.setdefault("config", {})
    cfg["settings"] = _setting_values(act["settings"])
    cfg["command"] = act["command"]
    cfg["schedule"] = _fmt_schedule(act)
    cfg["log_file"] = act.get("log_file")
    cfg["tables"] = [t for t, _ in act["tables"]]

    # logs
    if act.get("log_file"):
        sections["logs"] = {"path": act["log_file"], "lines": _tail(REPO_ROOT / act["log_file"])}

    return {"key": key, "title": act["title"], "category": act["category"], "kind": act["kind"],
            "status": card["status"], "headline": card["headline"], "generated_at": _now().isoformat(),
            "sections": sections}

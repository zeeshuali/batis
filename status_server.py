#!/usr/bin/env python3
"""
BATIS Service Status Dashboard
Run: backend/.venv/bin/python3 status_server.py
Serves: http://localhost:8080
"""

import json, os, sys, time, threading, socket
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# ── Config ────────────────────────────────────────────────────────────────────

PORT        = 8080
CACHE_TTL   = 15          # seconds between background refreshes
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))

def _load_env():
    env = {}
    try:
        with open(os.path.join(SCRIPT_DIR, "backend", ".env")) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip()
    except Exception:
        pass
    return env

_ENV         = _load_env()
DB_URL       = _ENV.get("DATABASE_URL", "")
GTFS_RT_URL  = _ENV.get("GTFS_RT_VEHICLE_POSITIONS_URL", "")

# ── Helpers ───────────────────────────────────────────────────────────────────

def _http(url, timeout=5):
    """GET url → (ok, latency_ms, status_code, body)"""
    t0 = time.monotonic()
    try:
        req = Request(url, headers={"User-Agent": "BATIS-Status/1.0"})
        with urlopen(req, timeout=timeout) as r:
            body   = r.read(32768).decode("utf-8", errors="replace")
            status = r.status
        return True, int((time.monotonic() - t0) * 1000), status, body
    except HTTPError as e:
        return False, int((time.monotonic() - t0) * 1000), e.code, ""
    except Exception as e:
        return False, int((time.monotonic() - t0) * 1000), 0, str(e)


def _aware(ts):
    """Make a datetime timezone-aware (assume UTC if naive)."""
    if ts is None:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _age(ts):
    """Human-readable age string from a datetime."""
    if ts is None:
        return "never"
    secs = max(0, int((datetime.now(timezone.utc) - _aware(ts)).total_seconds()))
    if secs < 60:    return f"{secs}s ago"
    if secs < 3600:  return f"{secs // 60}m ago"
    return f"{secs // 3600}h ago"


def _secs_since(ts):
    if ts is None:
        return float("inf")
    return max(0.0, (datetime.now(timezone.utc) - _aware(ts)).total_seconds())

# ── Individual checks ─────────────────────────────────────────────────────────

def check_backend():
    ok, ms, code, body = _http("http://localhost:8000/health")
    if ok:
        try:
            d = json.loads(body)
            return {
                "ok":            d.get("status") == "ok",
                "latency_ms":    ms,
                "db_configured": bool(d.get("database_url_configured")),
            }
        except Exception:
            pass
    return {"ok": False, "latency_ms": ms, "error": f"HTTP {code}"}


def check_database():
    if not DB_URL:
        return {"ok": False, "error": "DATABASE_URL not set"}
    try:
        import psycopg2
        t0   = time.monotonic()
        conn = psycopg2.connect(DB_URL, connect_timeout=5)
        cur  = conn.cursor()
        cur.execute("""
            SELECT
                (SELECT COUNT(*)          FROM ops_trip_events)::bigint,
                (SELECT COUNT(*)          FROM ops_trip_events
                   WHERE delay_seconds IS NOT NULL)::bigint,
                (SELECT COUNT(*)          FROM rt_vehicle_positions_raw)::bigint,
                (SELECT COUNT(*)          FROM delay_predictions)::bigint,
                (SELECT COUNT(*)          FROM crowding_predictions)::bigint,
                (SELECT COUNT(*)          FROM demand_forecasts)::bigint,
                (SELECT COUNT(*)          FROM ai_embeddings)::bigint,
                (SELECT MAX(created_at)   FROM ops_trip_events),
                (SELECT MAX(updated_at)   FROM ai_embeddings),
                (SELECT MAX(created_at)   FROM delay_predictions)
        """)
        row = cur.fetchone()
        ms  = int((time.monotonic() - t0) * 1000)
        conn.close()

        (trip_events, with_delay, veh_pos, delay_preds, crowding_preds,
         demand_preds, embeddings,
         last_event_ts, last_embed_ts, last_pred_ts) = row

        return {
            "ok":              True,
            "latency_ms":      ms,
            "trip_events":     int(trip_events   or 0),
            "events_with_delay": int(with_delay  or 0),
            "vehicle_positions": int(veh_pos     or 0),
            "delay_predictions": int(delay_preds or 0),
            "crowding_predictions": int(crowding_preds or 0),
            "demand_forecasts":  int(demand_preds or 0),
            "embeddings":        int(embeddings  or 0),
            "last_event_age":  _age(last_event_ts),
            "last_embed_age":  _age(last_embed_ts),
            "last_pred_age":   _age(last_pred_ts),
            # Thread health thresholds
            "gtfs_rt_ok":      _secs_since(last_event_ts)  < 300,    # 5 min
            "embed_ok":        _secs_since(last_embed_ts)  < 2100,   # 35 min
            "baseline_ok":     _secs_since(last_pred_ts)   < 2100,   # 35 min
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:140]}


def check_ollama():
    ok, ms, code, body = _http("http://localhost:11434/api/tags")
    if ok:
        try:
            d      = json.loads(body)
            models = [m["name"] for m in d.get("models", [])]
            target = "llama3.1:8b"
            return {
                "ok":           True,
                "latency_ms":   ms,
                "models":       models,
                "target":       target,
                "target_ready": any(target in m for m in models),
            }
        except Exception:
            pass
    return {"ok": False, "latency_ms": ms, "error": f"HTTP {code}"}


def check_frontend():
    ok, ms, code, _ = _http("http://localhost:5173", timeout=3)
    return {"ok": ok, "latency_ms": ms, "port": 5173}


def check_actransit():
    if not GTFS_RT_URL:
        return {"ok": False, "error": "GTFS_RT_VEHICLE_POSITIONS_URL not set"}
    ok, ms, code, body = _http(GTFS_RT_URL, timeout=12)
    return {
        "ok":          ok and code == 200,
        "latency_ms":  ms,
        "response_kb": len(body) // 1024 if body else 0,
        **({"error": f"HTTP {code}"} if not ok else {}),
    }

# ── Aggregate ─────────────────────────────────────────────────────────────────

def gather_all():
    results: dict = {}
    fns = {
        "backend":   check_backend,
        "database":  check_database,
        "ollama":    check_ollama,
        "frontend":  check_frontend,
        "actransit": check_actransit,
    }
    threads = {}
    for name, fn in fns.items():
        def _run(n=name, f=fn):
            try:
                results[n] = f()
            except Exception as e:
                results[n] = {"ok": False, "error": str(e)[:80]}
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        threads[name] = t
    for t in threads.values():
        t.join(timeout=15)

    db = results.get("database", {})

    results["gtfs_rt_ingestor"] = {
        "ok":     db.get("gtfs_rt_ok", False),
        "detail": db.get("last_event_age", "unknown"),
        "events": db.get("trip_events", 0),
    }
    results["embed_pipeline"] = {
        "ok":         db.get("embed_ok", False),
        "detail":     db.get("last_embed_age", "unknown"),
        "embeddings": db.get("embeddings", 0),
    }
    results["baseline_predictor"] = {
        "ok":          db.get("baseline_ok", False),
        "detail":      db.get("last_pred_age", "unknown"),
        "predictions": db.get("delay_predictions", 0),
    }

    results["_meta"] = {
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "overall_ok": all(
            r.get("ok", False)
            for k, r in results.items()
            if not k.startswith("_") and isinstance(r, dict)
        ),
    }
    return results

# ── Cache (background refresh) ────────────────────────────────────────────────

_lock  = threading.Lock()
_cache = {"data": {}, "ts": 0.0}


def _refresh():
    data = gather_all()
    with _lock:
        _cache["data"] = data
        _cache["ts"]   = time.monotonic()


def _start_bg():
    def loop():
        while True:
            try:
                _refresh()
            except Exception:
                pass
            time.sleep(CACHE_TTL)
    threading.Thread(target=loop, daemon=True).start()

# ── HTML ──────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>BATIS — Service Status</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --bg:          #080d1a;
      --bg2:         #0c1223;
      --bg3:         #111827;
      --card:        rgba(255,255,255,0.035);
      --card-hover:  rgba(255,255,255,0.055);
      --border:      rgba(255,255,255,0.07);
      --border-hi:   rgba(99,102,241,0.45);
      --text:        #e2e8f0;
      --text2:       #94a3b8;
      --muted:       #475569;
      --green:       #10b981;
      --green-dim:   rgba(16,185,129,0.12);
      --green-ring:  rgba(16,185,129,0.25);
      --red:         #f87171;
      --red-dim:     rgba(248,113,113,0.12);
      --red-ring:    rgba(248,113,113,0.25);
      --yellow:      #fbbf24;
      --yellow-dim:  rgba(251,191,36,0.12);
      --accent:      #6366f1;
      --accent2:     #818cf8;
      --accent3:     #a5b4fc;
      --radius:      14px;
      --radius-sm:   8px;
      --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    }

    html, body {
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: var(--font);
      font-size: 13px;
      line-height: 1.55;
      -webkit-font-smoothing: antialiased;
    }

    /* ── Top progress bar ── */
    #progress {
      position: fixed; top: 0; left: 0;
      height: 2px; width: 0%;
      background: linear-gradient(90deg, var(--accent) 0%, var(--accent2) 60%, #c084fc 100%);
      transition: width 0.12s linear;
      z-index: 200;
    }

    /* ── Header ── */
    header {
      position: sticky; top: 0; z-index: 100;
      background: rgba(8,13,26,0.92);
      backdrop-filter: blur(16px) saturate(180%);
      border-bottom: 1px solid var(--border);
      padding: 0 32px;
      height: 60px;
      display: flex; align-items: center; gap: 14px;
    }

    .logo {
      width: 34px; height: 34px; flex-shrink: 0;
      background: linear-gradient(135deg, var(--accent) 0%, #a855f7 100%);
      border-radius: 9px;
      display: flex; align-items: center; justify-content: center;
      font-weight: 800; font-size: 13px; letter-spacing: -0.04em; color: #fff;
      box-shadow: 0 0 20px rgba(99,102,241,0.35);
    }

    .header-title { font-size: 14px; font-weight: 700; letter-spacing: -0.02em; }
    .header-sub   { font-size: 11px; color: var(--muted); margin-top: 1px; }

    .header-right { margin-left: auto; display: flex; align-items: center; gap: 18px; }

    #overall {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 4px 11px; border-radius: 999px;
      font-size: 11px; font-weight: 600; letter-spacing: 0.04em;
      border: 1px solid transparent; transition: all 0.3s;
    }
    #overall.ok    { background: var(--green-dim); color: var(--green); border-color: var(--green-ring); }
    #overall.error { background: var(--red-dim);   color: var(--red);   border-color: var(--red-ring);  }
    #overall.init  { background: rgba(71,85,105,.2); color: var(--muted); }

    .header-meta { font-size: 11px; color: var(--muted); text-align: right; line-height: 1.7; }

    /* ── Main ── */
    main { max-width: 1200px; margin: 0 auto; padding: 36px 32px 56px; }

    .section-label {
      font-size: 10px; font-weight: 700; letter-spacing: 0.1em;
      text-transform: uppercase; color: var(--muted);
      margin-bottom: 14px;
    }

    /* ── Grid ── */
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 14px;
      margin-bottom: 36px;
    }

    /* ── Card ── */
    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 18px 18px 16px;
      position: relative; overflow: hidden;
      transition: border-color 0.2s, background 0.2s, transform 0.2s, box-shadow 0.2s;
      cursor: default;
    }
    .card:hover {
      background: var(--card-hover);
      border-color: var(--border-hi);
      transform: translateY(-2px);
      box-shadow: 0 8px 32px rgba(0,0,0,0.3), 0 0 0 1px rgba(99,102,241,0.08);
    }
    .card::after {
      content: '';
      position: absolute; top: 0; left: 0; right: 0; height: 1px;
      background: linear-gradient(90deg, transparent 0%, rgba(99,102,241,0.5) 50%, transparent 100%);
      opacity: 0; transition: opacity 0.25s;
    }
    .card:hover::after { opacity: 1; }

    .card-header {
      display: flex; justify-content: space-between; align-items: flex-start;
      margin-bottom: 14px;
    }

    .card-icon {
      width: 30px; height: 30px;
      background: rgba(255,255,255,0.06);
      border-radius: var(--radius-sm);
      display: flex; align-items: center; justify-content: center;
      font-size: 14px; flex-shrink: 0;
    }

    .pill {
      display: inline-flex; align-items: center; gap: 5px;
      padding: 2px 8px; border-radius: 999px;
      font-size: 9.5px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
      border: 1px solid transparent; transition: all 0.3s;
    }
    .pill.ok     { background: var(--green-dim); color: var(--green); border-color: var(--green-ring); }
    .pill.error  { background: var(--red-dim);   color: var(--red);   border-color: var(--red-ring);  }
    .pill.warn   { background: var(--yellow-dim); color: var(--yellow); }
    .pill.init   { background: rgba(71,85,105,.15); color: var(--muted); }

    .dot {
      width: 5px; height: 5px; border-radius: 50%;
      background: currentColor; flex-shrink: 0;
    }
    .dot.pulse { animation: pulse 2s ease-in-out infinite; }
    @keyframes pulse {
      0%,100% { opacity:1; transform:scale(1); }
      50%      { opacity:.45; transform:scale(.75); }
    }

    .card-name { font-size: 13px; font-weight: 650; color: var(--text); margin-bottom: 2px; }
    .card-desc { font-size: 11px; color: var(--muted); margin-bottom: 12px; }

    .divider { height: 1px; background: var(--border); margin: 10px 0; }

    .metrics { display: flex; flex-direction: column; gap: 5px; }
    .metric  { display: flex; justify-content: space-between; align-items: center; }
    .m-label { font-size: 11px; color: var(--text2); }
    .m-val   { font-size: 11px; font-weight: 600; color: var(--text); font-variant-numeric: tabular-nums; }
    .m-val.g { color: var(--green); }
    .m-val.r { color: var(--red);   }
    .m-val.y { color: var(--yellow);}
    .m-val.a { color: var(--accent3);}

    /* ── DB table ── */
    .db-wrap {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      overflow: hidden;
      margin-bottom: 0;
    }
    table { width: 100%; border-collapse: collapse; }
    thead th {
      padding: 10px 16px;
      text-align: left;
      font-size: 10px; font-weight: 700; letter-spacing: 0.07em; text-transform: uppercase;
      color: var(--muted);
      background: rgba(255,255,255,0.02);
      border-bottom: 1px solid var(--border);
    }
    tbody td {
      padding: 10px 16px;
      font-size: 12px;
      border-bottom: 1px solid rgba(255,255,255,0.035);
      font-variant-numeric: tabular-nums;
    }
    tbody tr:last-child td { border-bottom: none; }
    tbody tr:hover td      { background: rgba(255,255,255,0.02); }

    .tag {
      display: inline-block; padding: 2px 7px; border-radius: 5px;
      font-size: 10.5px; font-weight: 600;
      background: rgba(99,102,241,0.14); color: var(--accent3);
      font-family: 'SF Mono', 'Fira Code', monospace;
    }
    .count-hi { color: var(--text); font-weight: 600; }
    .count-lo { color: var(--muted); }

    /* ── Footer ── */
    footer {
      border-top: 1px solid var(--border);
      padding: 20px 32px;
      display: flex; align-items: center; justify-content: space-between;
      font-size: 11px; color: var(--muted);
    }
    footer b { color: var(--accent3); font-weight: 600; }

    /* ── Skeleton ── */
    .skel {
      height: 9px; border-radius: 4px;
      background: linear-gradient(90deg, rgba(255,255,255,0.04) 25%, rgba(255,255,255,0.08) 50%, rgba(255,255,255,0.04) 75%);
      background-size: 200% 100%;
      animation: shimmer 1.4s ease-in-out infinite;
    }
    @keyframes shimmer { 0%{background-position:200% 0} 100%{background-position:-200% 0} }

    @media(max-width:640px) {
      header  { padding: 0 16px; }
      main    { padding: 24px 16px 40px; }
      footer  { padding: 16px; flex-direction: column; gap: 6px; text-align: center; }
      .header-right { display: none; }
    }
  </style>
</head>
<body>

<div id="progress"></div>

<header>
  <div class="logo">B</div>
  <div>
    <div class="header-title">BATIS Status</div>
    <div class="header-sub">Bay Area Transit Intelligence System</div>
  </div>
  <div class="header-right">
    <div id="overall" class="init"><span class="dot"></span><span id="overall-text">Initialising…</span></div>
    <div class="header-meta">
      <div id="ts-updated">Checking services…</div>
      <div id="ts-next">—</div>
    </div>
  </div>
</header>

<main>
  <div class="section-label">Core Services</div>
  <div class="grid" id="core-grid">
    <div class="card"><div class="skel" style="width:60%;margin-bottom:8px"></div><div class="skel" style="width:40%"></div></div>
    <div class="card"><div class="skel" style="width:60%;margin-bottom:8px"></div><div class="skel" style="width:40%"></div></div>
    <div class="card"><div class="skel" style="width:60%;margin-bottom:8px"></div><div class="skel" style="width:40%"></div></div>
    <div class="card"><div class="skel" style="width:60%;margin-bottom:8px"></div><div class="skel" style="width:40%"></div></div>
    <div class="card"><div class="skel" style="width:60%;margin-bottom:8px"></div><div class="skel" style="width:40%"></div></div>
  </div>

  <div class="section-label">Background Pipelines</div>
  <div class="grid" id="pipeline-grid">
    <div class="card"><div class="skel" style="width:60%;margin-bottom:8px"></div><div class="skel" style="width:40%"></div></div>
    <div class="card"><div class="skel" style="width:60%;margin-bottom:8px"></div><div class="skel" style="width:40%"></div></div>
    <div class="card"><div class="skel" style="width:60%;margin-bottom:8px"></div><div class="skel" style="width:40%"></div></div>
  </div>

  <div class="section-label">Database Tables</div>
  <div class="db-wrap">
    <table>
      <thead>
        <tr><th>Table</th><th>Rows</th><th>Description</th><th>Status</th></tr>
      </thead>
      <tbody id="db-body">
        <tr><td colspan="4"><div class="skel"></div></td></tr>
      </tbody>
    </table>
  </div>
</main>

<footer>
  <div>BATIS &mdash; Bay Area Transit Intelligence &nbsp;·&nbsp; Status page</div>
  <div>Auto-refreshes every <b>15 s</b> &nbsp;·&nbsp; <span id="footer-ts">—</span></div>
</footer>

<script>
const INTERVAL = 15000;
let tick = INTERVAL, timer = null;

function n(v) {
  if (v == null) return '—';
  if (typeof v === 'number') return v.toLocaleString();
  return v;
}

function pill(ok, label) {
  const cls = ok == null ? 'init' : ok ? 'ok' : 'error';
  const lbl = ok == null ? 'Loading' : label || (ok ? 'Operational' : 'Degraded');
  return `<span class="pill ${cls}"><span class="dot${ok ? ' pulse' : ''}"></span>${lbl}</span>`;
}

function row(label, val, cls='') {
  return `<div class="metric"><span class="m-label">${label}</span><span class="m-val ${cls}">${n(val)}</span></div>`;
}

function card(icon, name, desc, ok, body) {
  return `<div class="card">
    <div class="card-header"><div class="card-icon">${icon}</div>${pill(ok)}</div>
    <div class="card-name">${name}</div>
    <div class="card-desc">${desc}</div>
    <div class="divider"></div>
    <div class="metrics">${body}</div>
  </div>`;
}

function latClass(ms) {
  if (ms == null) return '';
  if (ms <  80)   return 'g';
  if (ms < 300)   return '';
  return 'y';
}

function render(d) {
  const meta = d._meta || {};
  const be   = d.backend   || {};
  const db   = d.database  || {};
  const ol   = d.ollama    || {};
  const fe   = d.frontend  || {};
  const ac   = d.actransit || {};
  const rt   = d.gtfs_rt_ingestor  || {};
  const em   = d.embed_pipeline    || {};
  const bl   = d.baseline_predictor || {};

  // Overall badge
  const overall = document.getElementById('overall');
  const ok = meta.overall_ok;
  overall.className = ok ? 'ok' : 'error';
  document.getElementById('overall-text').textContent = ok ? 'All Systems Operational' : 'Degraded';
  overall.querySelector('.dot').className = 'dot' + (ok ? ' pulse' : '');

  // Timestamps
  document.getElementById('ts-updated').textContent = 'Updated ' + (meta.checked_at || '—');
  document.getElementById('footer-ts').textContent  = meta.checked_at || '—';

  // Core cards
  document.getElementById('core-grid').innerHTML = [
    card('⚡', 'FastAPI Backend', 'REST API · port 8000', be.ok,
      row('Latency', be.latency_ms != null ? be.latency_ms + ' ms' : '—', latClass(be.latency_ms)) +
      row('DB configured', be.db_configured ? 'Yes' : 'No', be.db_configured ? 'g' : 'r') +
      (be.error ? row('Error', be.error, 'r') : '')
    ),
    card('🗄️', 'PostgreSQL', 'PostGIS + pgvector · port 54322', db.ok,
      row('Query latency', db.latency_ms != null ? db.latency_ms + ' ms' : '—', latClass(db.latency_ms)) +
      row('Trip events', db.trip_events) +
      row('Vehicle positions', db.vehicle_positions) +
      (db.error ? row('Error', db.error, 'r') : '')
    ),
    card('🤖', 'Ollama LLM', 'Local inference · port 11434', ol.ok,
      row('Latency', ol.latency_ms != null ? ol.latency_ms + ' ms' : '—', latClass(ol.latency_ms)) +
      row('Model', ol.target || 'llama3.1:8b') +
      row('Loaded', ol.target_ready ? 'Yes' : 'No', ol.target_ready ? 'g' : 'r') +
      (ol.error ? row('Error', ol.error, 'r') : '')
    ),
    card('🌐', 'Vite Dev Server', 'React frontend · port 5173', fe.ok,
      row('Latency', fe.latency_ms != null ? fe.latency_ms + ' ms' : '—', latClass(fe.latency_ms)) +
      row('Port', '5173') +
      row('Status', fe.ok ? 'Serving' : 'Unreachable', fe.ok ? 'g' : 'r')
    ),
    card('🚌', 'AC Transit API', 'GTFS-RT vehicle feed (external)', ac.ok,
      row('Latency', ac.latency_ms != null ? ac.latency_ms + ' ms' : '—', latClass(ac.latency_ms)) +
      row('Response', ac.response_kb != null ? ac.response_kb + ' KB' : '—') +
      (ac.error ? row('Error', ac.error, 'r') : row('Feed', 'Live', 'g'))
    ),
  ].join('');

  // Pipeline cards
  document.getElementById('pipeline-grid').innerHTML = [
    card('📡', 'GTFS-RT Ingestor', 'Polls AC Transit every 30 s', rt.ok,
      row('Last ingest', rt.detail || '—', rt.ok ? 'g' : 'r') +
      row('Trip events (total)', rt.events) +
      row('Interval', '30 s')
    ),
    card('🧠', 'Embedding Pipeline', 'pgvector RAG · every 30 min', em.ok,
      row('Last run', em.detail || '—', em.ok ? 'g' : 'y') +
      row('Embeddings', em.embeddings) +
      row('Model', 'all-MiniLM-L6-v2')
    ),
    card('📊', 'Baseline Predictor', 'SQL median delays · every 30 min', bl.ok,
      row('Last run', bl.detail || '—', bl.ok ? 'g' : 'y') +
      row('Predictions', bl.predictions) +
      row('Method', 'SQL median')
    ),
  ].join('');

  // DB table
  const tables = [
    ['ops_trip_events',            db.trip_events,           'RT + historical trip events'],
    ['ops_trip_events (delayed)',  db.events_with_delay,     'Rows with delay_seconds label'],
    ['rt_vehicle_positions_raw',   db.vehicle_positions,     'Rolling 30-day GTFS-RT positions'],
    ['delay_predictions',          db.delay_predictions,     'SQL baseline + XGBoost output'],
    ['ai_embeddings',              db.embeddings,            'pgvector RAG context (384-dim)'],
    ['crowding_predictions',       db.crowding_predictions,  'Phase 4 — awaiting training data'],
    ['demand_forecasts',           db.demand_forecasts,      'Phase 4 — Prophet per-route model'],
  ];
  document.getElementById('db-body').innerHTML = tables.map(([tbl, cnt, desc]) => {
    const hasRows  = cnt > 0;
    const cntClass = cnt == null ? '' : hasRows ? 'count-hi' : 'count-lo';
    const badge    = hasRows
      ? `<span class="pill ok" style="font-size:9px"><span class="dot pulse"></span>Live</span>`
      : `<span class="pill init" style="font-size:9px"><span class="dot"></span>Empty</span>`;
    return `<tr>
      <td><span class="tag">${tbl}</span></td>
      <td class="${cntClass}">${cnt != null ? cnt.toLocaleString() : '—'}</td>
      <td style="color:var(--text2)">${desc}</td>
      <td>${badge}</td>
    </tr>`;
  }).join('');
}

async function doRefresh() {
  try {
    const r = await fetch('/status');
    const d = await r.json();
    render(d);
  } catch(e) {
    console.warn('Status poll failed:', e);
  }
}

function startCountdown() {
  clearInterval(timer);
  tick  = INTERVAL;
  const bar = document.getElementById('progress');
  timer = setInterval(() => {
    tick -= 100;
    const pct = ((INTERVAL - tick) / INTERVAL * 100).toFixed(1);
    bar.style.width = pct + '%';
    const sec = Math.max(0, Math.ceil(tick / 1000));
    document.getElementById('ts-next').textContent = `Next refresh in ${sec}s`;
    if (tick <= 0) {
      clearInterval(timer);
      bar.style.width = '100%';
      doRefresh().then(() => { bar.style.width = '0%'; startCountdown(); });
    }
  }, 100);
}

doRefresh().then(startCountdown);
</script>
</body>
</html>
"""

# ── HTTP handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # suppress per-request logging

    def do_GET(self):
        if self.path == "/status":
            with _lock:
                body = json.dumps(_cache["data"]).encode()
            self._respond(200, "application/json", body)
        elif self.path in ("/", "/index.html"):
            self._respond(200, "text/html; charset=utf-8", HTML.encode())
        else:
            self.send_error(404)

    def _respond(self, code, ctype, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type",   ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT

    print("[batis-status] Performing initial health checks…")
    _refresh()
    _start_bg()

    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"[batis-status] Serving at \033[1;36mhttp://localhost:{port}\033[0m")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[batis-status] Stopped.")

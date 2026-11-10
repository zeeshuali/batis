"""
511.org Traffic & Toll data ingestor.

Endpoints:
  Traffic events: https://api.511.org/traffic/events?api_key={key}
  Work zones:     https://api.511.org/traffic/wzdx?api_key={key}
  Toll rates:     https://api.511.org/toll/programs?api_key={key}
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

import certifi
import requests
from app.core.run_log import tracked_get
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.config import get_settings
from app.db import get_engine


# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def _get(path: str, **extra_params: str) -> Any:
    s = get_settings()
    resp = tracked_get(
        f"{s.five11_base_url}/{path}",
        params={"api_key": s.five11_api_key, **extra_params},
        timeout=30,
        verify=certifi.where(),
    )
    resp.raise_for_status()
    # 511.org's /traffic/events and /toll/programs serve a leading UTF-8 BOM.
    # requests.Response.json() forwards the raw bytes to the stdlib json
    # parser, which rejects the BOM. Decode with utf-8-sig to strip it.
    return json.loads(resp.content.decode("utf-8-sig"))


def _parse_dt(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


# ─── Table bootstrap (idempotent) ─────────────────────────────────────────────

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS traffic_events (
        event_id    text PRIMARY KEY,
        event_type  text,
        severity    text,
        geom        geometry(Point, 4326),
        description text,
        road_name   text,
        start_time  timestamptz,
        end_time    timestamptz,
        created_at  timestamptz DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS traffic_events_geom_idx   ON traffic_events USING gist(geom)",
    "CREATE INDEX IF NOT EXISTS traffic_events_active_idx ON traffic_events(start_time, end_time)",
    """
    CREATE TABLE IF NOT EXISTS work_zones (
        zone_id     text PRIMARY KEY,
        geom        geometry(MultiLineString, 4326),
        road_name   text,
        description text,
        start_time  timestamptz,
        end_time    timestamptz,
        created_at  timestamptz DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS work_zones_geom_idx ON work_zones USING gist(geom)",
    """
    CREATE TABLE IF NOT EXISTS toll_rates (
        id            bigserial PRIMARY KEY,
        facility_id   text NOT NULL,
        facility_name text,
        direction     text,
        vehicle_class text DEFAULT 'standard',
        rate_usd      numeric(6,2),
        valid_from    timestamptz,
        valid_to      timestamptz,
        created_at    timestamptz DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS toll_rates_facility_idx ON toll_rates(facility_id, valid_from)",
]


def _ensure_tables(engine) -> None:
    for ddl in _DDL:
        try:
            with engine.begin() as c:
                c.execute(text(ddl.strip()))
        except Exception:
            pass


# ─── Loaders ──────────────────────────────────────────────────────────────────

def load_traffic_events(conn: Connection) -> int:
    raw = _get("traffic/events")
    # Response is either a direct list or {"events": [...]}
    if isinstance(raw, list):
        events = raw
    else:
        events = raw.get("events") or raw.get("Events") or []

    count = 0
    for ev in events:
        eid = str(ev.get("id") or ev.get("Id") or "")
        if not eid:
            continue

        geo = ev.get("geography") or ev.get("Geography") or {}
        geom_wkt = None
        if geo.get("type") == "Point":
            coords = geo.get("coordinates", [])
            if len(coords) >= 2:
                geom_wkt = f"SRID=4326;POINT({coords[0]} {coords[1]})"

        roads = ev.get("roads") or ev.get("Roads") or []
        road_name = roads[0].get("name") if roads else None

        sched = ev.get("schedule") or ev.get("Schedule") or {}

        conn.execute(text("""
            INSERT INTO traffic_events (
                event_id, event_type, severity, geom,
                description, road_name, start_time, end_time, created_at
            ) VALUES (
                :event_id, :event_type, :severity,
                CASE WHEN :geom IS NOT NULL
                     THEN ST_GeomFromEWKT(:geom) ELSE NULL END,
                :description, :road_name, :start_time, :end_time, now()
            )
            ON CONFLICT (event_id) DO UPDATE SET
                severity    = EXCLUDED.severity,
                description = EXCLUDED.description,
                road_name   = EXCLUDED.road_name,
                end_time    = EXCLUDED.end_time
        """), {
            "event_id":    eid,
            "event_type":  ev.get("event_type") or ev.get("EventType"),
            "severity":    ev.get("severity")   or ev.get("Severity"),
            "geom":        geom_wkt,
            "description": ev.get("headline")   or ev.get("Headline") or ev.get("description"),
            "road_name":   road_name,
            "start_time":  _parse_dt(sched.get("start_time") or sched.get("StartTime")),
            "end_time":    _parse_dt(sched.get("end_time")   or sched.get("EndTime")),
        })
        count += 1

    return count


def load_work_zones(conn: Connection) -> int:
    fc = _get("traffic/wzdx")
    features = fc.get("features", []) if isinstance(fc, dict) else []

    count = 0
    for feat in features:
        # WZDx id can be at feature level or in properties
        zone_id = str(feat.get("id") or "")
        props = feat.get("properties") or {}
        if not zone_id:
            zone_id = str(props.get("id") or props.get("Id") or "")
        if not zone_id:
            continue

        # WZDx 4.0 nests road names under core_details; older versions are flat
        core = props.get("core_details") or {}
        road_names = (
            core.get("road_names")
            or props.get("road_names")
            or ([props["road_name"]] if props.get("road_name") else [])
        )
        road_name   = road_names[0] if road_names else None
        description = core.get("description") or props.get("description")
        start_time  = _parse_dt(props.get("start_date") or props.get("start_time"))
        end_time    = _parse_dt(props.get("end_date")   or props.get("end_time"))

        # Build WKT; ST_Multi() in SQL coerces LineString → MultiLineString
        geom = feat.get("geometry") or {}
        gtype  = geom.get("type", "")
        coords = geom.get("coordinates", [])
        geom_wkt = None
        if gtype == "LineString" and coords:
            pts = ", ".join(f"{c[0]} {c[1]}" for c in coords)
            geom_wkt = f"SRID=4326;LINESTRING({pts})"
        elif gtype == "MultiLineString" and coords:
            lines = ", ".join(
                "(" + ", ".join(f"{c[0]} {c[1]}" for c in line) + ")"
                for line in coords
            )
            geom_wkt = f"SRID=4326;MULTILINESTRING({lines})"

        conn.execute(text("""
            INSERT INTO work_zones (
                zone_id, geom, road_name, description,
                start_time, end_time, created_at
            ) VALUES (
                :zone_id,
                CASE WHEN :geom IS NOT NULL
                     THEN ST_Multi(ST_GeomFromEWKT(:geom))::geometry(MultiLineString,4326)
                     ELSE NULL END,
                :road_name, :description, :start_time, :end_time, now()
            )
            ON CONFLICT (zone_id) DO UPDATE SET
                geom        = EXCLUDED.geom,
                road_name   = EXCLUDED.road_name,
                description = EXCLUDED.description,
                end_time    = EXCLUDED.end_time
        """), {
            "zone_id":     zone_id,
            "geom":        geom_wkt,
            "road_name":   road_name,
            "description": description,
            "start_time":  start_time,
            "end_time":    end_time,
        })
        count += 1

    return count


def load_toll_rates(conn: Connection) -> int:
    raw = _get("toll/programs")
    programs = raw if isinstance(raw, list) else (
        raw.get("programs") or raw.get("Programs") or [raw]
    )

    now = datetime.now(timezone.utc)
    count = 0
    for program in programs:
        fac_id   = str(program.get("id") or program.get("Id") or "")
        fac_name = program.get("name") or program.get("Name") or fac_id

        rates = program.get("rates") or program.get("Rates") or []
        # Some responses embed rates at the top level
        if not rates and program.get("amount") is not None:
            rates = [program]

        for rate in rates:
            rate_usd = rate.get("amount") or rate.get("rate") or rate.get("toll")
            if rate_usd is None:
                continue
            conn.execute(text("""
                INSERT INTO toll_rates (
                    facility_id, facility_name, direction,
                    vehicle_class, rate_usd, valid_from, valid_to, created_at
                ) VALUES (
                    :facility_id, :facility_name, :direction,
                    :vehicle_class, :rate_usd, :valid_from, :valid_to, now()
                )
            """), {
                "facility_id":   fac_id,
                "facility_name": fac_name,
                "direction":     rate.get("direction") or program.get("direction"),
                "vehicle_class": rate.get("vehicle_class") or rate.get("vehicleClass") or "standard",
                "rate_usd":      float(rate_usd),
                "valid_from":    _parse_dt(rate.get("valid_from") or rate.get("start_date")) or now,
                "valid_to":      _parse_dt(rate.get("valid_to")   or rate.get("end_date")),
            })
            count += 1

    return count


# ─── Background loop ──────────────────────────────────────────────────────────

def run_traffic_loop(interval_seconds: int = 300, stop_event=None) -> None:
    print(f"[traffic] Starting — poll interval {interval_seconds}s", flush=True)
    engine = get_engine()
    _ensure_tables(engine)

    while not (stop_event and stop_event.is_set()):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")

        from app.core.run_log import job_run
        with job_run("traffic_loop") as jr:
            counts: dict = {}
            errors: list[str] = []
            for label, loader in [
                ("events",     load_traffic_events),
                ("work_zones", load_work_zones),
                ("toll_rates", load_toll_rates),
            ]:
                try:
                    with engine.begin() as conn:
                        n = loader(conn)
                    counts[label] = n
                    print(f"[traffic] {label}={n} at {ts}", flush=True)
                except Exception as exc:
                    errors.append(f"{label}: {exc}")
                    print(f"[traffic] {label} error: {exc}", flush=True)
            jr.set(rows=sum(v for v in counts.values() if isinstance(v, int)), **counts)
            if errors:
                jr.fail("; ".join(errors))

        for _ in range(interval_seconds):
            if stop_event and stop_event.is_set():
                return
            time.sleep(1)

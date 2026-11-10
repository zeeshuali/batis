# DEPRECATED — replaced by five11_rt_ingestor.py (511.org multi-agency feed).
# Kept for reference; no longer wired into the application lifespan.
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

import certifi
import requests
from dateutil import tz
from google.transit import gtfs_realtime_pb2
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.config import get_settings
from app.db import get_engine


def _build_url(base: str | None, default_path: str, token: str | None) -> str:
    if base:
        return base
    if not token:
        raise RuntimeError("GTFS-RT URL is not configured and ACTRANSIT_API_KEY is missing.")
    return f"https://api.actransit.org/transit/gtfsrt/{default_path}?token={token}"


def _fetch_feed(url: str) -> gtfs_realtime_pb2.FeedMessage:
    resp = requests.get(url, timeout=30, verify=certifi.where())
    resp.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(resp.content)
    return feed


def _insert_vehicle_positions(conn: Connection, feed: gtfs_realtime_pb2.FeedMessage) -> list[dict]:
    rows: list[dict] = []
    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue
        v = entity.vehicle
        pos = v.position
        ts = v.timestamp or int(time.time())
        ts_dt = datetime.fromtimestamp(ts, tz=timezone.utc)

        row = {
            "vehicle_id": v.vehicle.id if v.vehicle and v.vehicle.id else None,
            "trip_id": v.trip.trip_id if v.trip and v.trip.trip_id else None,
            "route_id": v.trip.route_id if v.trip and v.trip.route_id else None,
            "timestamp": ts_dt,
            "latitude": pos.latitude if pos else None,
            "longitude": pos.longitude if pos else None,
            "bearing": pos.bearing if pos else None,
            "speed": pos.speed if pos else None,
            "occupancy_status": (
                v.occupancy_status.name
                if hasattr(v.occupancy_status, "name")
                else str(v.occupancy_status) if v.occupancy_status else None
            ),
            "geom_wkt": None,
            "raw_payload": json.dumps({}),
        }

        if row["latitude"] is not None and row["longitude"] is not None:
            row["geom_wkt"] = f"SRID=4326;POINT({row['longitude']} {row['latitude']})"

        rows.append(row)

    if not rows:
        return []

    insert_sql = text(
        """
        INSERT INTO rt_vehicle_positions_raw (
          vehicle_id,
          trip_id,
          route_id,
          timestamp,
          latitude,
          longitude,
          bearing,
          speed,
          occupancy_status,
          raw_payload,
          geom
        )
        VALUES (
          :vehicle_id,
          :trip_id,
          :route_id,
          :timestamp,
          :latitude,
          :longitude,
          :bearing,
          :speed,
          :occupancy_status,
          :raw_payload,
          CASE
            WHEN :geom_wkt IS NOT NULL THEN ST_GeomFromEWKT(:geom_wkt)
            ELSE NULL
          END
        )
        """
    )

    conn.execute(insert_sql, rows)
    return rows


def _insert_ops_trip_events(conn: Connection, rows: Iterable[dict]) -> None:
    ops_rows: list[dict] = []
    for r in rows:
        if not r.get("trip_id") or not r.get("route_id"):
            continue
        ts = r["timestamp"]
        # Ensure timezone-aware datetime
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        service_date = ts.astimezone(tz.gettz("America/Los_Angeles")).date()

        ops_rows.append(
            {
                "service_date": service_date,
                "trip_id": r["trip_id"],
                "route_id": r["route_id"],
                "stop_id": None,
                "stop_sequence": None,
                "scheduled_arrival": None,
                "actual_arrival": ts,
                "delay_seconds": None,
                "headway_seconds": None,
                "occupancy_level": r.get("occupancy_status"),
            }
        )

    if not ops_rows:
        return

    insert_sql = text(
        """
        INSERT INTO ops_trip_events (
          service_date,
          trip_id,
          route_id,
          stop_id,
          stop_sequence,
          scheduled_arrival,
          actual_arrival,
          delay_seconds,
          headway_seconds,
          occupancy_level
        ) VALUES (
          :service_date,
          :trip_id,
          :route_id,
          :stop_id,
          :stop_sequence,
          :scheduled_arrival,
          :actual_arrival,
          :delay_seconds,
          :headway_seconds,
          :occupancy_level
        )
        """
    )
    conn.execute(insert_sql, ops_rows)


def _parse_gtfs_time(service_date: date, time_str: str) -> datetime | None:
    """
    Convert a GTFS arrival_time string (HH:MM:SS, hours may exceed 24 for overnight service)
    on a given service_date in America/Los_Angeles to a UTC-aware datetime.
    """
    try:
        parts = time_str.strip().split(":")
        h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
        la_tz = tz.gettz("America/Los_Angeles")
        midnight = datetime(service_date.year, service_date.month, service_date.day, 0, 0, 0, tzinfo=la_tz)
        return midnight + timedelta(hours=h, minutes=m, seconds=s)
    except Exception:
        return None


def _process_trip_updates(conn: Connection, feed: gtfs_realtime_pb2.FeedMessage) -> None:
    """
    Parse GTFS-RT trip updates and write stop-level ops events into ops_trip_events,
    including scheduled_arrival (from gtfs_stop_times), actual_arrival, and delay_seconds.

    Existing stop-level rows (stop_sequence IS NOT NULL) for the same trip+service_date
    are deleted first to avoid duplicates on repeated polling.
    """
    la_tz = tz.gettz("America/Los_Angeles")
    today = datetime.now(timezone.utc).astimezone(la_tz).date()

    updates: list[dict] = []
    trip_ids: set[str] = set()

    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        tu = entity.trip_update
        trip_desc = tu.trip
        trip_id = trip_desc.trip_id or None
        route_id = trip_desc.route_id or None
        if not trip_id:
            continue
        trip_ids.add(trip_id)

        service_date = today
        if trip_desc.start_date:
            try:
                service_date = datetime.strptime(trip_desc.start_date, "%Y%m%d").date()
            except ValueError:
                pass

        for stu in tu.stop_time_update:
            stop_id = stu.stop_id or None
            # stop_sequence=0 is invalid in GTFS; treat as unset
            stop_sequence = stu.stop_sequence if stu.stop_sequence else None

            delay_seconds = None
            actual_arrival_ts = None

            if stu.HasField("arrival"):
                arr = stu.arrival
                if arr.HasField("delay"):
                    delay_seconds = arr.delay
                if arr.HasField("time") and arr.time:
                    actual_arrival_ts = datetime.fromtimestamp(arr.time, tz=timezone.utc)

            updates.append({
                "service_date": service_date,
                "trip_id": trip_id,
                "route_id": route_id,
                "stop_id": stop_id,
                "stop_sequence": stop_sequence,
                "actual_arrival": actual_arrival_ts,
                "delay_seconds": delay_seconds,
            })

    if not updates:
        return

    # Batch-fetch scheduled arrivals from GTFS static for all relevant trips
    scheduled: dict[tuple[str, int], str] = {}
    if trip_ids:
        rows = conn.execute(
            text(
                "SELECT trip_id, stop_sequence, arrival_time FROM gtfs_stop_times "
                "WHERE trip_id = ANY(:trip_ids)"
            ),
            {"trip_ids": list(trip_ids)},
        ).mappings().all()
        for r in rows:
            if r["stop_sequence"] is not None:
                scheduled[(r["trip_id"], r["stop_sequence"])] = r["arrival_time"]

    # Resolve scheduled_arrival and derive actual_arrival when only delay is known
    final_rows: list[dict] = []
    for u in updates:
        key = (u["trip_id"], u["stop_sequence"]) if u["stop_sequence"] is not None else None
        sched_time_str = scheduled.get(key) if key else None
        scheduled_arrival = _parse_gtfs_time(u["service_date"], sched_time_str) if sched_time_str else None

        actual_arrival = u["actual_arrival"]
        if actual_arrival is None and scheduled_arrival is not None and u["delay_seconds"] is not None:
            actual_arrival = scheduled_arrival + timedelta(seconds=u["delay_seconds"])

        final_rows.append({
            "service_date": u["service_date"],
            "trip_id": u["trip_id"],
            "route_id": u["route_id"],
            "stop_id": u["stop_id"],
            "stop_sequence": u["stop_sequence"],
            "scheduled_arrival": scheduled_arrival,
            "actual_arrival": actual_arrival,
            "delay_seconds": u["delay_seconds"],
            "headway_seconds": None,
            "occupancy_level": None,
        })

    if not final_rows:
        return

    # Delete existing stop-level rows for these trips before re-inserting
    trip_date_pairs = list({(r["service_date"], r["trip_id"]) for r in final_rows})
    for sd, tid in trip_date_pairs:
        conn.execute(
            text(
                "DELETE FROM ops_trip_events "
                "WHERE service_date = :service_date "
                "  AND trip_id = :trip_id "
                "  AND stop_sequence IS NOT NULL"
            ),
            {"service_date": sd, "trip_id": tid},
        )

    conn.execute(
        text(
            """
            INSERT INTO ops_trip_events (
              service_date, trip_id, route_id, stop_id, stop_pk, stop_sequence,
              scheduled_arrival, actual_arrival, delay_seconds, headway_seconds, occupancy_level
            ) VALUES (
              :service_date, :trip_id, :route_id, :stop_id, (SELECT stop_pk FROM gtfs_stops g WHERE g.agency_id = 'AC' AND g.stop_id = :stop_id), :stop_sequence,
              :scheduled_arrival, :actual_arrival, :delay_seconds, :headway_seconds, :occupancy_level
            )
            """
        ),
        final_rows,
    )


def _cleanup_old_positions(conn: Connection, retain_days: int = 30) -> None:
    """Delete vehicle position rows older than retain_days for ML feature history."""
    conn.execute(
        text(f"DELETE FROM rt_vehicle_positions_raw WHERE timestamp < NOW() - INTERVAL '{retain_days} days'")
    )


def ingest_gtfs_realtime_once() -> None:
    """
    Fetch GTFS-Realtime vehicle positions and trip updates once and persist
    to Postgres, creating basic historical operations records.
    """
    settings = get_settings()
    engine = get_engine()

    vehicle_url = _build_url(
        settings.gtfs_rt_vehicle_positions_url, "vehicles", settings.actransit_api_key
    )
    trip_updates_url = _build_url(
        settings.gtfs_rt_trip_updates_url, "tripupdates", settings.actransit_api_key
    )

    vehicle_feed = _fetch_feed(vehicle_url)
    trip_updates_feed = _fetch_feed(trip_updates_url)

    with engine.begin() as conn:
        rows = _insert_vehicle_positions(conn, vehicle_feed)
        _insert_ops_trip_events(conn, rows)
        _process_trip_updates(conn, trip_updates_feed)
        _cleanup_old_positions(conn)


def run_polling_loop(poll_interval_seconds: int = 30, stop_event: "threading.Event | None" = None) -> None:
    """
    Long-running loop that polls GTFS-Realtime feeds on an interval.
    Pass a threading.Event to allow graceful shutdown.
    """
    import threading
    _stop = stop_event or threading.Event()
    print(f"[gtfs-rt-ingestor] Starting — poll interval {poll_interval_seconds}s")
    while not _stop.is_set():
        try:
            ingest_gtfs_realtime_once()
            print(f"[gtfs-rt-ingestor] Ingested OK at {time.strftime('%H:%M:%S')}")
        except Exception as exc:
            print(f"[gtfs-rt-ingestor] Error: {exc}")
        _stop.wait(poll_interval_seconds)


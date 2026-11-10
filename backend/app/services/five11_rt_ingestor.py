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


# Any GTFS-RT `arr.delay` outside ±2 hours is treated as corrupt and dropped
# (we set delay_seconds = NULL rather than skip the row, so the stop event
# itself is still recorded).  Some agencies' feeds emit huge negative deltas
# when their internal `scheduled_time` is uninitialised — see the prior bug
# where SF Muni rows accumulated delay_seconds = -70 million.
_MAX_PLAUSIBLE_DELAY_SECONDS = 7200


def _strip_agency_prefix(value: str | None, agency_id: str | None) -> str | None:
    """511.org's regional feed namespaces trip_id / route_id with `{agency}:`
    (e.g. `SF:11996421_M11`), but the static GTFS we load stores the raw
    ids (`11996421_M11`).  Joining the two requires the same form on both
    sides — strip the agency prefix on the RT side so lookups against
    gtfs_stop_times / gtfs_routes succeed.

    A no-op for feeds that don't prefix.
    """
    if not value or not agency_id:
        return value or None
    prefix = f"{agency_id}:"
    return value[len(prefix):] if value.startswith(prefix) else value


def _build_vehicle_url() -> str:
    s = get_settings()
    return f"{s.five11_base_url}/Transit/VehiclePositions?api_key={s.five11_api_key}&agency=RG"


def _build_trip_updates_url() -> str:
    s = get_settings()
    return f"{s.five11_base_url}/Transit/TripUpdates?api_key={s.five11_api_key}&agency=RG"


def _fetch_feed(url: str) -> gtfs_realtime_pb2.FeedMessage:
    resp = requests.get(url, timeout=30, verify=certifi.where())
    resp.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(resp.content)
    return feed


def _extract_agency_id(trip_descriptor, route_id: str | None) -> str:
    """
    Resolve agency_id from a GTFS-RT TripDescriptor.
    Checks the agency_id field first (present in some 511.org feeds), then
    falls back to a 'AGENCY:route' prefix in route_id (e.g. 'AC:1T' → 'AC').
    """
    agency_field = getattr(trip_descriptor, "agency_id", "") or ""
    if agency_field:
        return agency_field
    if route_id and ":" in route_id:
        return route_id.split(":", 1)[0]
    return "AC"


def _insert_vehicle_positions(conn: Connection, feed: gtfs_realtime_pb2.FeedMessage) -> list[dict]:
    rows: list[dict] = []
    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue
        v = entity.vehicle
        pos = v.position
        ts = v.timestamp or int(time.time())
        ts_dt = datetime.fromtimestamp(ts, tz=timezone.utc)

        trip = v.trip
        route_id = (trip.route_id or None) if trip else None

        agency_id = _extract_agency_id(trip, route_id) if trip else "AC"
        row = {
            "agency_id": agency_id,
            "vehicle_id": v.vehicle.id if v.vehicle and v.vehicle.id else None,
            "trip_id": _strip_agency_prefix((trip.trip_id or None) if trip else None, agency_id),
            "route_id": _strip_agency_prefix(route_id, agency_id),
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

    conn.execute(
        text(
            """
            INSERT INTO rt_vehicle_positions_raw (
              agency_id, vehicle_id, trip_id, route_id, timestamp,
              latitude, longitude, bearing, speed, occupancy_status,
              raw_payload, geom
            ) VALUES (
              :agency_id, :vehicle_id, :trip_id, :route_id, :timestamp,
              :latitude, :longitude, :bearing, :speed, :occupancy_status,
              :raw_payload,
              CASE WHEN :geom_wkt IS NOT NULL THEN ST_GeomFromEWKT(:geom_wkt) ELSE NULL END
            )
            """
        ),
        rows,
    )
    return rows


def _insert_ops_trip_events(conn: Connection, rows: Iterable[dict]) -> None:
    ops_rows: list[dict] = []
    for r in rows:
        if not r.get("trip_id") or not r.get("route_id"):
            continue
        ts = r["timestamp"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        service_date = ts.astimezone(tz.gettz("America/Los_Angeles")).date()

        ops_rows.append(
            {
                "agency_id": r.get("agency_id", "AC"),
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

    conn.execute(
        text(
            """
            INSERT INTO ops_trip_events (
              agency_id, service_date, trip_id, route_id, stop_id, stop_pk, stop_sequence,
              scheduled_arrival, actual_arrival, delay_seconds, headway_seconds, occupancy_level
            ) VALUES (
              :agency_id, :service_date, :trip_id, :route_id, :stop_id, (SELECT stop_pk FROM gtfs_stops g WHERE g.agency_id = :agency_id AND g.stop_id = :stop_id), :stop_sequence,
              :scheduled_arrival, :actual_arrival, :delay_seconds, :headway_seconds, :occupancy_level
            )
            """
        ),
        ops_rows,
    )


def _parse_gtfs_time(service_date: date, time_str: str) -> datetime | None:
    """
    Convert a GTFS arrival_time string (HH:MM:SS, hours may exceed 24 for overnight
    service) on a given service_date in America/Los_Angeles to a UTC-aware datetime.
    """
    try:
        parts = time_str.strip().split(":")
        h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
        la_tz = tz.gettz("America/Los_Angeles")
        midnight = datetime(service_date.year, service_date.month, service_date.day, 0, 0, 0, tzinfo=la_tz)
        return midnight + timedelta(hours=h, minutes=m, seconds=s)
    except Exception:
        return None


def _process_trip_updates(conn: Connection, feed: gtfs_realtime_pb2.FeedMessage) -> int:
    """
    Parse GTFS-RT trip updates and write stop-level ops events into ops_trip_events.
    Existing stop-level rows for the same trip+service_date are replaced on each poll.
    Returns the number of stop-time rows written.
    """
    la_tz = tz.gettz("America/Los_Angeles")
    today = datetime.now(timezone.utc).astimezone(la_tz).date()

    updates: list[dict] = []
    trip_ids: set[tuple[str, str]] = set()

    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        tu = entity.trip_update
        trip_desc = tu.trip
        # Resolve the agency from the raw (still prefixed) route_id first, then strip.
        agency_id = _extract_agency_id(trip_desc, trip_desc.route_id or None)
        trip_id  = _strip_agency_prefix(trip_desc.trip_id  or None, agency_id)
        route_id = _strip_agency_prefix(trip_desc.route_id or None, agency_id)
        if not trip_id:
            continue
        trip_ids.add((agency_id, trip_id))

        service_date = today
        if trip_desc.start_date:
            try:
                service_date = datetime.strptime(trip_desc.start_date, "%Y%m%d").date()
            except ValueError:
                pass

        for stu in tu.stop_time_update:
            stop_id = _strip_agency_prefix(stu.stop_id or None, agency_id)
            stop_sequence = stu.stop_sequence if stu.stop_sequence else None

            delay_seconds = None
            actual_arrival_ts = None

            if stu.HasField("arrival"):
                arr = stu.arrival
                if arr.HasField("delay"):
                    delay_seconds = arr.delay
                if arr.HasField("time") and arr.time:
                    actual_arrival_ts = datetime.fromtimestamp(arr.time, tz=timezone.utc)

            updates.append(
                {
                    "agency_id": agency_id,
                    "service_date": service_date,
                    "trip_id": trip_id,
                    "route_id": route_id,
                    "stop_id": stop_id,
                    "stop_sequence": stop_sequence,
                    "actual_arrival": actual_arrival_ts,
                    "delay_seconds": delay_seconds,
                }
            )

    if not updates:
        return 0

    # Batch-fetch scheduled arrivals for all trips in this feed
    scheduled: dict[tuple[str, str, int], str] = {}
    if trip_ids:
        sched_rows = conn.execute(
            text(
                "SELECT agency_id, trip_id, stop_sequence, arrival_time FROM gtfs_stop_times "
                "WHERE (agency_id, trip_id) IN (SELECT * FROM unnest(CAST(:aids AS text[]), CAST(:tids AS text[])))"
            ),
            {"aids": [a for a, _ in trip_ids], "tids": [t for _, t in trip_ids]},
        ).mappings().all()
        for r in sched_rows:
            if r["stop_sequence"] is not None:
                scheduled[(r["agency_id"], r["trip_id"], r["stop_sequence"])] = r["arrival_time"]

    final_rows: list[dict] = []
    for u in updates:
        key = (u["agency_id"], u["trip_id"], u["stop_sequence"]) if u["stop_sequence"] is not None else None
        sched_time_str = scheduled.get(key) if key else None
        scheduled_arrival = _parse_gtfs_time(u["service_date"], sched_time_str) if sched_time_str else None

        # Validate delay_seconds.
        # 1. If we couldn't resolve a scheduled_arrival, we have no way to
        #    sanity-check the delta the feed gave us — null it out.
        # 2. If the feed gave us a delay outside ±2 hours, it's bogus
        #    (a real-world transit delay > 2h is data corruption, not service).
        #    Several agencies' GTFS-RT feeds occasionally emit huge negative
        #    deltas when their internal `scheduled_time` is uninitialised.
        delay = u["delay_seconds"]
        if scheduled_arrival is None or delay is None:
            delay = None
        elif abs(delay) > _MAX_PLAUSIBLE_DELAY_SECONDS:
            delay = None

        actual_arrival = u["actual_arrival"]
        if actual_arrival is None and scheduled_arrival is not None and delay is not None:
            actual_arrival = scheduled_arrival + timedelta(seconds=delay)

        final_rows.append(
            {
                "agency_id": u["agency_id"],
                "service_date": u["service_date"],
                "trip_id": u["trip_id"],
                "route_id": u["route_id"],
                "stop_id": u["stop_id"],
                "stop_sequence": u["stop_sequence"],
                "scheduled_arrival": scheduled_arrival,
                "actual_arrival": actual_arrival,
                "delay_seconds": delay,
                "headway_seconds": None,
                "occupancy_level": None,
            }
        )

    if not final_rows:
        return 0

    # Replace stop-level rows for each trip to handle repeated polling
    trip_date_pairs = list({(r["agency_id"], r["service_date"], r["trip_id"]) for r in final_rows})
    for aid, sd, tid in trip_date_pairs:
        conn.execute(
            text(
                "DELETE FROM ops_trip_events "
                "WHERE agency_id = :agency_id AND service_date = :service_date AND trip_id = :trip_id "
                "  AND stop_sequence IS NOT NULL"
            ),
            {"agency_id": aid, "service_date": sd, "trip_id": tid},
        )

    conn.execute(
        text(
            """
            INSERT INTO ops_trip_events (
              agency_id, service_date, trip_id, route_id, stop_id, stop_pk, stop_sequence,
              scheduled_arrival, actual_arrival, delay_seconds, headway_seconds, occupancy_level
            ) VALUES (
              :agency_id, :service_date, :trip_id, :route_id, :stop_id, (SELECT stop_pk FROM gtfs_stops g WHERE g.agency_id = :agency_id AND g.stop_id = :stop_id), :stop_sequence,
              :scheduled_arrival, :actual_arrival, :delay_seconds, :headway_seconds, :occupancy_level
            )
            """
        ),
        final_rows,
    )
    return len(final_rows)


def _cleanup_old_positions(conn: Connection, retain_days: int = 30) -> None:
    conn.execute(
        text(f"DELETE FROM rt_vehicle_positions_raw WHERE timestamp < NOW() - INTERVAL '{retain_days} days'")
    )


def ingest_five11_realtime_once() -> dict:
    """Fetch and ingest GTFS-RT from 511.org regional feed. Returns counts dict."""
    settings = get_settings()
    if not settings.five11_api_key:
        raise RuntimeError("FIVE11_API_KEY is not configured.")

    engine = get_engine()
    counts: dict = {"vehicles": 0, "trip_events": 0, "trip_update_rows": 0, "errors": []}

    vehicle_feed: gtfs_realtime_pb2.FeedMessage | None = None
    trip_updates_feed: gtfs_realtime_pb2.FeedMessage | None = None

    try:
        vehicle_feed = _fetch_feed(_build_vehicle_url())
    except Exception as exc:
        counts["errors"].append(f"vehicle-positions fetch: {exc}")

    try:
        trip_updates_feed = _fetch_feed(_build_trip_updates_url())
    except Exception as exc:
        counts["errors"].append(f"trip-updates fetch: {exc}")

    with engine.begin() as conn:
        if vehicle_feed is not None:
            try:
                rows = _insert_vehicle_positions(conn, vehicle_feed)
                _insert_ops_trip_events(conn, rows)
                counts["vehicles"] = len(rows)
                counts["trip_events"] = sum(1 for r in rows if r.get("trip_id") and r.get("route_id"))
            except Exception as exc:
                counts["errors"].append(f"vehicle insert: {exc}")

        if trip_updates_feed is not None:
            try:
                counts["trip_update_rows"] = _process_trip_updates(conn, trip_updates_feed)
            except Exception as exc:
                counts["errors"].append(f"trip-updates insert: {exc}")

        try:
            _cleanup_old_positions(conn)
        except Exception as exc:
            counts["errors"].append(f"cleanup: {exc}")

    return counts


def run_polling_loop(poll_interval_seconds: int = 30, stop_event: "threading.Event | None" = None) -> None:
    """Long-running loop that polls 511.org GTFS-RT feeds on an interval."""
    import threading

    _stop = stop_event or threading.Event()
    print(f"[five11-rt-ingestor] Starting — poll interval {poll_interval_seconds}s")
    while not _stop.is_set():
        try:
            counts = ingest_five11_realtime_once()
            errors = counts.get("errors", [])
            status = "with errors" if errors else "OK"
            print(
                f"[five11-rt-ingestor] {status} at {time.strftime('%H:%M:%S')} — "
                f"vehicles={counts['vehicles']}, trip_update_rows={counts['trip_update_rows']}"
            )
            for e in errors:
                print(f"[five11-rt-ingestor] Error: {e}")
        except Exception as exc:
            print(f"[five11-rt-ingestor] Fatal error: {exc}")
        _stop.wait(poll_interval_seconds)

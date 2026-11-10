"""Fetch live stop ETAs from 511.org SIRI Stop Monitoring API."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import certifi
import requests
from app.core.run_log import tracked_get

from app.core.config import get_settings


def get_live_departures(stop_code: str, agency_id: str) -> list[dict[str, Any]]:
    """
    Fetch live ETAs for a stop from 511.org SIRI Stop Monitoring.

    Returns a list of departure dicts:
        route_id, route_short_name, headsign,
        expected_arrival (ISO str), aimed_arrival (ISO str),
        delay_seconds (int | None), is_realtime (bool)

    Falls back to empty list if FIVE11_API_KEY is not configured, agency_id is
    unknown to 511.org, or stop_code is absent.
    """
    settings = get_settings()
    if not settings.five11_api_key or not stop_code:
        return []

    url = (
        f"{settings.five11_base_url}/transit/StopMonitoring"
        f"?api_key={settings.five11_api_key}"
        f"&agency={agency_id}"
        f"&stopCode={stop_code}"
        f"&Format=json"
    )

    try:
        resp = tracked_get(url, timeout=10, verify=certifi.where())
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"[stop-monitoring] {agency_id}/{stop_code}: {exc}")
        return []

    deliveries = (
        data.get("ServiceDelivery", {}).get("StopMonitoringDelivery", [])
    )
    if not deliveries:
        return []

    visits = deliveries[0].get("MonitoredStopVisit", [])
    departures: list[dict[str, Any]] = []

    for visit in visits:
        mvj = visit.get("MonitoredVehicleJourney", {})
        call = mvj.get("MonitoredCall", {})

        # Prefer Arrival fields; fall back to Departure for routes that only publish departure
        expected_str: str | None = (
            call.get("ExpectedArrivalTime") or call.get("ExpectedDepartureTime")
        )
        aimed_str: str | None = (
            call.get("AimedArrivalTime") or call.get("AimedDepartureTime")
        )

        delay_seconds: int | None = None
        if expected_str and aimed_str:
            try:
                exp = datetime.fromisoformat(expected_str.replace("Z", "+00:00"))
                aim = datetime.fromisoformat(aimed_str.replace("Z", "+00:00"))
                delay_seconds = int((exp - aim).total_seconds())
            except Exception:
                pass

        departures.append(
            {
                "route_id": mvj.get("LineRef") or "",
                "route_short_name": (
                    mvj.get("PublishedLineName") or mvj.get("LineRef") or ""
                ),
                "headsign": (
                    mvj.get("DestinationName") or mvj.get("DirectionName") or ""
                ),
                "expected_arrival": expected_str,
                "aimed_arrival": aimed_str,
                "delay_seconds": delay_seconds,
                "is_realtime": expected_str is not None,
            }
        )

    # Sort soonest first
    departures.sort(key=lambda d: d["expected_arrival"] or "")
    return departures

"""Fetch and parse GTFS-RT service alerts from AC Transit."""
from __future__ import annotations

import warnings
from typing import Any

import requests

from app.core.config import get_settings


def get_service_alerts() -> list[dict[str, Any]]:
    """
    Fetch current service alerts from AC Transit GTFS-RT alerts feed.
    Returns a list of parsed alert dicts.
    """
    settings = get_settings()
    token = settings.actransit_api_key
    if not token or token == "your_actransit_api_key_here":
        return []

    url = f"https://api.actransit.org/transit/gtfsrt/alerts?token={token}"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            resp = requests.get(url, timeout=15, verify=False)
            resp.raise_for_status()
    except Exception:
        return []

    try:
        from google.transit import gtfs_realtime_pb2
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(resp.content)
    except Exception:
        return []

    alerts = []
    for entity in feed.entity:
        if not entity.HasField("alert"):
            continue
        a = entity.alert
        # Header text
        header = ""
        for tr in a.header_text.translation:
            if tr.language in ("en", "") or not header:
                header = tr.text
        # Description
        description = ""
        for tr in a.description_text.translation:
            if tr.language in ("en", "") or not description:
                description = tr.text
        # Affected routes/stops
        informed = []
        for ie in a.informed_entity:
            entry: dict[str, Any] = {}
            if ie.route_id:
                entry["route_id"] = ie.route_id
            if ie.stop_id:
                entry["stop_id"] = ie.stop_id
            if entry:
                informed.append(entry)
        # Active period
        active_periods = []
        for ap in a.active_period:
            active_periods.append({
                "start": ap.start if ap.start else None,
                "end":   ap.end   if ap.end   else None,
            })
        cause_map = {0: "UNKNOWN", 1: "OTHER", 2: "TECHNICAL", 3: "STRIKE", 4: "DEMONSTRATION",
                     5: "ACCIDENT", 6: "HOLIDAY", 7: "WEATHER", 8: "MAINTENANCE",
                     9: "CONSTRUCTION", 10: "POLICE", 11: "MEDICAL"}
        effect_map = {0: "UNKNOWN", 1: "NO_SERVICE", 2: "REDUCED_SERVICE", 3: "SIGNIFICANT_DELAYS",
                      4: "DETOUR", 5: "ADDITIONAL_SERVICE", 6: "MODIFIED_SERVICE",
                      7: "OTHER", 8: "STOP_MOVED", 9: "NO_EFFECT", 10: "ACCESSIBILITY"}
        alerts.append({
            "id":             entity.id,
            "header":         header,
            "description":    description,
            "cause":          cause_map.get(a.cause, "UNKNOWN"),
            "effect":         effect_map.get(a.effect, "UNKNOWN"),
            "informed_entities": informed,
            "active_periods": active_periods,
        })
    return alerts

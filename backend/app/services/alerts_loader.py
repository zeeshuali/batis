"""Fetch and parse GTFS-RT service alerts — 511.org (preferred) or AC Transit fallback."""
from __future__ import annotations

from typing import Any

import certifi
import requests
from app.core.run_log import tracked_get

from app.core.config import get_settings


def get_service_alerts() -> list[dict[str, Any]]:
    """
    Fetch current service alerts from 511.org (all Bay Area agencies) if FIVE11_API_KEY
    is configured, otherwise fall back to the AC Transit direct feed.
    Returns a list of parsed alert dicts.
    """
    settings = get_settings()

    # Prefer 511.org — covers all Bay Area agencies
    if settings.five11_api_key:
        url = (
            f"https://api.511.org/transit/servicealerts"
            f"?agency=RG&api_key={settings.five11_api_key}&format=json"
        )
        try:
            resp = tracked_get(url, timeout=15, verify=certifi.where())
            resp.raise_for_status()
            data = resp.json()
            # 511.org returns JSON-formatted GTFS-RT
            entities = (
                data.get("Entities", [])
                or data.get("entity", [])
                or []
            )
            return _parse_json_entities(entities)
        except Exception as exc:
            print(f"[alerts] 511.org fetch failed: {exc}")
            return []

    # Fallback: AC Transit direct protobuf feed
    token = settings.actransit_api_key
    if not token or token == "your_actransit_api_key_here":
        return []

    url = f"https://api.actransit.org/transit/gtfsrt/alerts?token={token}"
    try:
        resp = tracked_get(url, timeout=15, verify=certifi.where())
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
            if ie.agency_id:
                entry["agency_id"] = ie.agency_id
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
        alert_agency_id = next(
            (e["agency_id"] for e in informed if e.get("agency_id")), "AC"
        )
        alerts.append({
            "id":             entity.id,
            "agency_id":      alert_agency_id,
            "header":         header,
            "description":    description,
            "cause":          cause_map.get(a.cause, "UNKNOWN"),
            "effect":         effect_map.get(a.effect, "UNKNOWN"),
            "informed_entities": informed,
            "active_periods": active_periods,
        })
    return alerts


def _parse_json_entities(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse 511.org JSON-format alert entities into our standard shape."""
    alerts = []
    for entity in entities:
        alert = entity.get("Alert") or entity.get("alert") or {}
        if not alert:
            continue
        header_translations = (
            alert.get("HeaderText", {}).get("Translation", [])
            or alert.get("header_text", {}).get("translation", [])
        )
        header = next(
            (t.get("Text") or t.get("text", "") for t in header_translations
             if t.get("Language", t.get("language", "")) in ("en", "")),
            (header_translations[0].get("Text") or header_translations[0].get("text", ""))
            if header_translations else "",
        )
        desc_translations = (
            alert.get("DescriptionText", {}).get("Translation", [])
            or alert.get("description_text", {}).get("translation", [])
        )
        description = next(
            (t.get("Text") or t.get("text", "") for t in desc_translations
             if t.get("Language", t.get("language", "")) in ("en", "")),
            (desc_translations[0].get("Text") or desc_translations[0].get("text", ""))
            if desc_translations else "",
        )
        informed_raw = (
            alert.get("InformedEntity", []) or alert.get("informed_entity", [])
        )
        informed = []
        alert_agency_id: str | None = None
        for ie in informed_raw:
            entry: dict[str, Any] = {}
            rid = ie.get("RouteId") or ie.get("route_id")
            sid = ie.get("StopId") or ie.get("stop_id")
            aid = ie.get("AgencyId") or ie.get("agency_id")
            if rid:
                entry["route_id"] = rid
            if sid:
                entry["stop_id"] = sid
            if aid:
                entry["agency_id"] = aid
                if alert_agency_id is None:
                    alert_agency_id = aid
            if entry:
                informed.append(entry)
        alerts.append({
            "id":                entity.get("Id") or entity.get("id", ""),
            "agency_id":         alert_agency_id,
            "header":            header,
            "description":       description,
            "cause":             str(alert.get("Cause") or alert.get("cause", "UNKNOWN")),
            "effect":            str(alert.get("Effect") or alert.get("effect", "UNKNOWN")),
            "informed_entities": informed,
            "active_periods":    [],
        })
    return alerts

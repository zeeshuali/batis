import threading
from contextlib import asynccontextmanager
from datetime import date
from typing import List, Optional, Tuple

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.config import get_settings
from app.db import get_engine
from app.services.analysis import (
    compute_scenario_impact,
    create_scenario,
    delete_scenario,
    get_scenario,
    list_scenarios,
    get_agencies_list,
    get_agencies_rollup,
    get_agency_otp_benchmarks,
    get_schedule_drift,
    get_traffic_transit_impact,
    get_bunching_summary,
    get_coverage_cells,
    get_crowding_predictions,
    get_crowding_stops_geo,
    get_delay_predictions,
    get_demand_forecasts,
    get_demand_stops_geo,
    get_live_vehicles,
    get_realtime_departures,
    get_reliability_by_route,
    get_reliability_stops_geo,
    get_reliability_summary,
    get_reliability_trend,
    get_route_comparison,
    get_route_geo,
    get_route_headways,
    get_routes_list,
    get_safety_stops_geo,
    get_stop_detail,
    get_stop_reachability,
    get_stop_safety_scores,
    get_transit_deserts,
    get_trip_plan,
)
from app.services.five11_rt_ingestor import run_polling_loop
from app.services.five11_traffic import run_traffic_loop
from app.core.security import api_key_dependency
from ml.baseline import run_baseline_loop
from ml.embed import run_embed_loop

_stop_event = threading.Event()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _stop_event.clear()

    # 511.org multi-agency RT ingestor — polls every 30s
    t_rt = threading.Thread(
        target=run_polling_loop,
        kwargs={"poll_interval_seconds": 30, "stop_event": _stop_event},
        daemon=True,
        name="five11-rt-ingestor",
    )
    t_rt.start()

    # SQL baseline predictions — refreshes every 30 min
    t_baseline = threading.Thread(
        target=run_baseline_loop,
        kwargs={"interval_seconds": 1800, "stop_event": _stop_event},
        daemon=True,
        name="baseline-predictor",
    )
    t_baseline.start()

    # RAG embedding pipeline — refreshes every 30 min
    t_embed = threading.Thread(
        target=run_embed_loop,
        kwargs={"interval_seconds": 1800, "stop_event": _stop_event},
        daemon=True,
        name="embed-pipeline",
    )
    t_embed.start()

    # 511.org traffic events, work zones, toll rates — polls every 5 min
    t_traffic = threading.Thread(
        target=run_traffic_loop,
        kwargs={"interval_seconds": 300, "stop_event": _stop_event},
        daemon=True,
        name="traffic-ingestor",
    )
    t_traffic.start()

    yield

    # Graceful shutdown
    _stop_event.set()
    t_rt.join(timeout=5)
    t_baseline.join(timeout=5)
    t_embed.join(timeout=5)
    t_traffic.join(timeout=5)


app = FastAPI(title="Bay Area Transit Intelligence API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_conn() -> Connection:
    engine = get_engine()
    with engine.connect() as conn:
        yield conn


@app.get("/health")
def health():
    settings = get_settings()
    return {
        "status": "ok",
        "database_url_configured": bool(settings.database_url),
        "gtfs_static_url": settings.gtfs_static_url,
    }


@app.get("/")
def root():
    return {"message": "Bay Area Transit Intelligence API"}


# ── Agencies catalog ──────────────────────────────────────────────────────────
# NOTE: register /agencies/rollup BEFORE /agencies/{agency_id} if any
# parameterised /agencies/{...} route is ever added — same lesson as the
# /routes/compare vs /routes/{route_id}/geo ordering documented around line 322.

@app.get("/agencies/rollup", dependencies=[Depends(api_key_dependency)])
def agencies_rollup(
    start_date: date,
    end_date: date,
    conn: Connection = Depends(get_conn),
):
    return get_agencies_rollup(conn, start_date=start_date, end_date=end_date)


@app.get("/agencies", dependencies=[Depends(api_key_dependency)])
def agencies_list(conn: Connection = Depends(get_conn)):
    return get_agencies_list(conn)


# ── Planning → Scenarios builder ─────────────────────────────────────────────
# NOTE: register /scenarios/{scenario_id}/impact BEFORE /scenarios/{scenario_id}
# (same precedence lesson as /routes/compare vs /routes/{route_id}/geo above).

class ScenarioStop(BaseModel):
    lat: float
    lng: float
    label: Optional[str] = None


class ScenarioCreate(BaseModel):
    name: str
    description: Optional[str] = None
    stops: List[ScenarioStop] = []
    frequency_min: int = 15
    agency_id: Optional[str] = None


@app.get("/scenarios", dependencies=[Depends(api_key_dependency)])
def scenarios_list(conn: Connection = Depends(get_conn)):
    return list_scenarios(conn)


@app.post("/scenarios", dependencies=[Depends(api_key_dependency)])
def scenarios_create(payload: ScenarioCreate, conn: Connection = Depends(get_conn)):
    with conn.begin():
        return create_scenario(
            conn,
            name=payload.name,
            description=payload.description,
            stops=[s.model_dump() for s in payload.stops],
            frequency_min=payload.frequency_min,
            agency_id=payload.agency_id,
        )


@app.get("/scenarios/{scenario_id}/impact", dependencies=[Depends(api_key_dependency)])
def scenarios_impact(scenario_id: int, conn: Connection = Depends(get_conn)):
    impact = compute_scenario_impact(conn, scenario_id)
    if impact is None:
        raise HTTPException(status_code=404, detail=f"Scenario {scenario_id} not found")
    return impact


@app.get("/scenarios/{scenario_id}", dependencies=[Depends(api_key_dependency)])
def scenarios_get(scenario_id: int, conn: Connection = Depends(get_conn)):
    s = get_scenario(conn, scenario_id)
    if s is None:
        raise HTTPException(status_code=404, detail=f"Scenario {scenario_id} not found")
    return s


@app.delete("/scenarios/{scenario_id}", dependencies=[Depends(api_key_dependency)])
def scenarios_delete(scenario_id: int, conn: Connection = Depends(get_conn)):
    with conn.begin():
        ok = delete_scenario(conn, scenario_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Scenario {scenario_id} not found")
    return {"deleted": scenario_id}


# ── Sprint 4a → Fares v2 (debug-only endpoint for now) ──────────────────────

@app.get("/fares/products", dependencies=[Depends(api_key_dependency)])
def fares_products(
    agency_id: Optional[str] = Query(default=None),
    conn: Connection = Depends(get_conn),
):
    """List ingested fare products. Sprint 4a is ingest-only — this exists
    so the live data can be inspected from the dashboard / curl without
    diving into psql.  The Sprint 4b fare calculator will replace this."""
    clauses = []
    params: dict = {}
    if agency_id:
        clauses.append("agency_id = :agency_id")
        params["agency_id"] = agency_id
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(text(f"""
        SELECT agency_id, fare_product_id, fare_product_name, amount, currency
        FROM fare_products
        {where}
        ORDER BY agency_id, amount NULLS LAST, fare_product_id
    """), params).mappings().all()
    return [dict(r) for r in rows]


# ── Sprint 4a → Transfer reliability ────────────────────────────────────────

@app.get("/transfers/reliability", dependencies=[Depends(api_key_dependency)])
def transfers_reliability(
    from_agency: Optional[str] = Query(default=None),
    to_agency:   Optional[str] = Query(default=None),
    min_observations: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
    conn: Connection = Depends(get_conn),
):
    """Read the transfer reliability matrix. Filter by from_agency /
    to_agency for a single matrix cell; omit both to get the flattened
    matrix (sorted by observation count, then by worst success rate)."""
    from app.services.transfer_reliability import get_transfer_reliability
    return get_transfer_reliability(
        conn,
        from_agency=from_agency,
        to_agency=to_agency,
        min_observations=min_observations,
        limit=limit,
    )


@app.get("/reliability/summary", dependencies=[Depends(api_key_dependency)])
def reliability_summary(
    start_date: date,
    end_date: date,
    route_ids: Optional[List[str]] = Query(default=None),
    agency_id: Optional[str] = Query(default=None),
    conn: Connection = Depends(get_conn),
):
    return get_reliability_summary(
        conn,
        start_date=start_date,
        end_date=end_date,
        route_ids=route_ids,
        agency_id=agency_id,
    )


@app.get("/reliability/route/{route_id}", dependencies=[Depends(api_key_dependency)])
def reliability_by_route(
    route_id: str,
    service_date: date,
    conn: Connection = Depends(get_conn),
):
    return get_reliability_by_route(conn, route_id=route_id, service_date=service_date)


@app.get("/reliability/predictions", dependencies=[Depends(api_key_dependency)])
def reliability_predictions(
    start_date: date,
    end_date: date,
    route_ids: Optional[List[str]] = Query(default=None),
    conn: Connection = Depends(get_conn),
):
    return get_delay_predictions(conn, start_date=start_date, end_date=end_date, route_ids=route_ids)


@app.get("/coverage/cells", dependencies=[Depends(api_key_dependency)])
def coverage_cells(
    bbox: Optional[str] = Query(
        default=None,
        description="Optional bounding box as min_lon,min_lat,max_lon,max_lat",
    ),
    conn: Connection = Depends(get_conn),
):
    bbox_tuple: Optional[Tuple[float, float, float, float]] = None
    if bbox:
        parts = [float(p) for p in bbox.split(",")]
        if len(parts) == 4:
            bbox_tuple = (parts[0], parts[1], parts[2], parts[3])
    return {"type": "FeatureCollection", "features": get_coverage_cells(conn, bbox_tuple)}


@app.get("/coverage/deserts", dependencies=[Depends(api_key_dependency)])
def coverage_deserts(
    bbox: Optional[str] = Query(
        default=None,
        description="Optional bounding box as min_lon,min_lat,max_lon,max_lat",
    ),
    conn: Connection = Depends(get_conn),
):
    bbox_tuple: Optional[Tuple[float, float, float, float]] = None
    if bbox:
        parts = [float(p) for p in bbox.split(",")]
        if len(parts) == 4:
            bbox_tuple = (parts[0], parts[1], parts[2], parts[3])
    return {"type": "FeatureCollection", "features": get_transit_deserts(conn, bbox_tuple)}


@app.get("/equity/score", dependencies=[Depends(api_key_dependency)])
def equity_score(conn: Connection = Depends(get_conn)):
    """
    GeoJSON FeatureCollection of coverage cells with equity metrics.
    equity_tier: 'very_high' / 'high' / 'medium' / 'low'
    """
    rows = conn.execute(text("""
        SELECT
            cell_id,
            ST_AsGeoJSON(geom)::json AS geometry,
            COALESCE(equity_score, 0.5)              AS equity_score,
            COALESCE(low_income_population, 0)        AS low_income_population,
            COALESCE(no_car_households, 0)            AS no_car_households,
            COALESCE(population, 0)                   AS population,
            CASE
                WHEN COALESCE(equity_score, 0.5) >= 0.25 THEN 'very_high'
                WHEN COALESCE(equity_score, 0.5) >= 0.15 THEN 'high'
                WHEN COALESCE(equity_score, 0.5) >= 0.08 THEN 'medium'
                ELSE 'low'
            END AS equity_tier
        FROM coverage_cells
        WHERE equity_score IS NOT NULL
        ORDER BY equity_score DESC
    """)).mappings().all()

    features = []
    for r in rows:
        props = dict(r)
        geom  = props.pop("geometry")
        features.append({"type": "Feature", "geometry": geom, "properties": props})
    return {"type": "FeatureCollection", "features": features}


@app.get("/safety/stops", dependencies=[Depends(api_key_dependency)])
def safety_stops(
    min_score: Optional[float] = Query(default=None),
    max_score: Optional[float] = Query(default=None),
    agency_id: Optional[str] = Query(default=None),
    conn: Connection = Depends(get_conn),
):
    return get_stop_safety_scores(
        conn,
        min_score=min_score,
        max_score=max_score,
        agency_id=agency_id,
    )


@app.get("/demand/forecasts", dependencies=[Depends(api_key_dependency)])
def demand_forecasts(
    start_date: date,
    end_date: date,
    route_id: Optional[str] = Query(default=None),
    conn: Connection = Depends(get_conn),
):
    return get_demand_forecasts(conn, route_id=route_id, start_date=start_date, end_date=end_date)


@app.get("/crowding/predictions", dependencies=[Depends(api_key_dependency)])
def crowding_predictions(
    start_date: date,
    end_date: date,
    route_id: Optional[str] = Query(default=None),
    conn: Connection = Depends(get_conn),
):
    return get_crowding_predictions(conn, start_date=start_date, end_date=end_date, route_id=route_id)


@app.get("/reliability/stops/geo", dependencies=[Depends(api_key_dependency)])
def reliability_stops_geo(
    start_date: date,
    end_date: date,
    route_ids: Optional[List[str]] = Query(default=None),
    agency_id: Optional[str] = Query(default=None),
    conn: Connection = Depends(get_conn),
):
    return {
        "type": "FeatureCollection",
        "features": get_reliability_stops_geo(
            conn,
            start_date=start_date,
            end_date=end_date,
            route_ids=route_ids,
            agency_id=agency_id,
        ),
    }


@app.get("/safety/stops/geo", dependencies=[Depends(api_key_dependency)])
def safety_stops_geo(
    min_score: Optional[float] = Query(default=None),
    max_score: Optional[float] = Query(default=None),
    agency_id: Optional[str] = Query(default=None),
    conn: Connection = Depends(get_conn),
):
    return {
        "type": "FeatureCollection",
        "features": get_safety_stops_geo(
            conn,
            min_score=min_score,
            max_score=max_score,
            agency_id=agency_id,
        ),
    }


@app.get("/crowding/stops/geo", dependencies=[Depends(api_key_dependency)])
def crowding_stops_geo(
    start_date: date,
    end_date: date,
    route_id: Optional[str] = Query(default=None),
    conn: Connection = Depends(get_conn),
):
    return {
        "type": "FeatureCollection",
        "features": get_crowding_stops_geo(conn, start_date=start_date, end_date=end_date, route_id=route_id),
    }


@app.get("/demand/stops/geo", dependencies=[Depends(api_key_dependency)])
def demand_stops_geo(
    start_date: date,
    end_date: date,
    route_id: Optional[str] = Query(default=None),
    conn: Connection = Depends(get_conn),
):
    return {
        "type": "FeatureCollection",
        "features": get_demand_stops_geo(conn, start_date=start_date, end_date=end_date, route_id=route_id),
    }


@app.get("/stops/{stop_id}", dependencies=[Depends(api_key_dependency)])
def stop_detail(
    stop_id: str,
    conn: Connection = Depends(get_conn),
):
    from fastapi import HTTPException
    detail = get_stop_detail(conn, stop_id=stop_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Stop not found")
    return detail


@app.get("/routes", dependencies=[Depends(api_key_dependency)])
def routes_list(conn: Connection = Depends(get_conn)):
    return get_routes_list(conn)


# IMPORTANT: /routes/compare MUST be registered before /routes/{route_id}/geo
# or FastAPI will match "compare" as a route_id path parameter.
@app.get("/routes/compare", dependencies=[Depends(api_key_dependency)])
def routes_compare(
    route_ids: str = Query(description="Comma-separated route IDs, e.g. 1T,2T,72"),
    start_date: date = Query(),
    end_date: date = Query(),
    conn: Connection = Depends(get_conn),
):
    ids = [r.strip() for r in route_ids.split(",") if r.strip()][:5]
    return get_route_comparison(conn, route_ids=ids, start_date=start_date, end_date=end_date)


@app.get("/routes/{route_id}/geo", dependencies=[Depends(api_key_dependency)])
def route_geo(route_id: str, conn: Connection = Depends(get_conn)):
    return get_route_geo(conn, route_id=route_id)


@app.get("/bunching/summary", dependencies=[Depends(api_key_dependency)])
def bunching_summary(
    start_date: date,
    end_date: date,
    agency_id: Optional[str] = Query(default=None),
    conn: Connection = Depends(get_conn),
):
    return get_bunching_summary(
        conn,
        start_date=start_date,
        end_date=end_date,
        agency_id=agency_id,
    )


@app.get("/vehicles/live")
def vehicles_live(
    agency_id: Optional[str] = Query(default=None),
    conn: Connection = Depends(get_conn),
):
    """Live vehicle positions — no API key required for real-time map."""
    return get_live_vehicles(conn, agency_id=agency_id)


@app.get("/reliability/trend", dependencies=[Depends(api_key_dependency)])
def reliability_trend(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    days: int = Query(default=30, ge=1, le=90),
    route_id: Optional[str] = Query(default=None),
    agency_id: Optional[str] = Query(default=None),
    conn: Connection = Depends(get_conn),
):
    # Compute days from start_date/end_date if provided
    if start_date and end_date:
        from datetime import date as date_type
        days = max(1, (end_date - start_date).days + 1)
    return get_reliability_trend(conn, route_id=route_id, days=days, agency_id=agency_id)


@app.get("/routes/{route_id}/headways", dependencies=[Depends(api_key_dependency)])
def route_headways(
    route_id: str,
    service_date: Optional[date] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    conn: Connection = Depends(get_conn),
):
    from datetime import date as date_type
    sd = service_date or end_date or date_type.today()
    return get_route_headways(conn, route_id=route_id, service_date=sd)


@app.get("/stops/{stop_id}/realtime-departures", dependencies=[Depends(api_key_dependency)])
def realtime_departures(
    stop_id: str,
    conn: Connection = Depends(get_conn),
):
    return get_realtime_departures(conn, stop_id=stop_id)


@app.get("/stops/{stop_id}/live-departures", dependencies=[Depends(api_key_dependency)])
def live_departures(
    stop_id: str,
    conn: Connection = Depends(get_conn),
):
    """
    Live ETAs from 511.org SIRI Stop Monitoring when available.
    Falls back to DB-backed scheduled departures with delay overlay.
    Every row includes is_realtime: bool.
    """
    from app.services.five11_stop_monitoring import get_live_departures as _siri

    stop_row = conn.execute(
        text("SELECT stop_code, agency_id FROM gtfs_stops WHERE stop_id = :sid"),
        {"sid": stop_id},
    ).mappings().first()

    stop_code = stop_row["stop_code"] if stop_row else None
    agency_id = (stop_row["agency_id"] if stop_row else None) or "AC"

    if stop_code:
        try:
            live = _siri(stop_code, agency_id)
            if live:
                return live
        except Exception:
            pass

    # Fallback: normalize DB realtime-departures to the same response shape
    rows = get_realtime_departures(conn, stop_id=stop_id)
    return [
        {
            "route_id": r["route_id"],
            "route_short_name": r.get("route_short_name") or r["route_id"],
            "headsign": r.get("trip_headsign"),
            "expected_arrival": r.get("departure_time"),
            "aimed_arrival": r.get("departure_time"),
            "delay_seconds": r.get("current_delay_seconds"),
            "is_realtime": False,
        }
        for r in rows
    ]


@app.get("/stops/{stop_id}/reachability", dependencies=[Depends(api_key_dependency)])
def stop_reachability(
    stop_id: str,
    minutes: int = Query(default=30, ge=10, le=90),
    conn: Connection = Depends(get_conn),
):
    return get_stop_reachability(conn, stop_id=stop_id, minutes=minutes)


@app.get("/trip-planner", dependencies=[Depends(api_key_dependency)])
def trip_planner(
    from_lat: float = Query(),
    from_lng: float = Query(),
    to_lat: float = Query(),
    to_lng: float = Query(),
    conn: Connection = Depends(get_conn),
):
    return get_trip_plan(conn, from_lat=from_lat, from_lng=from_lng, to_lat=to_lat, to_lng=to_lng)


@app.get("/alerts")
def service_alerts():
    """Live service alerts — no API key required."""
    from app.services.alerts_loader import get_service_alerts
    return get_service_alerts()


# ── Benchmarks endpoints ─────────────────────────────────────────────────────

@app.get("/benchmarks/agency-otp", dependencies=[Depends(api_key_dependency)])
def benchmarks_agency_otp(
    start_date: date,
    end_date: date,
    conn: Connection = Depends(get_conn),
):
    """Cross-agency on-time performance benchmarks from the stop_observations archive."""
    return get_agency_otp_benchmarks(conn, start_date=start_date, end_date=end_date)


@app.get("/schedule-drift/{agency_id}/{route_id}", dependencies=[Depends(api_key_dependency)])
def schedule_drift(
    agency_id: str,
    route_id: str,
    months_back: int = 3,
    conn: Connection = Depends(get_conn),
):
    """Detect segments where actual run times have drifted from the schedule."""
    return get_schedule_drift(conn, agency_id=agency_id, route_id=route_id, months_back=months_back)


# ── Traffic / Work-zones / Toll endpoints ─────────────────────────────────────

@app.get("/traffic/events", dependencies=[Depends(api_key_dependency)])
def traffic_events(conn: Connection = Depends(get_conn)):
    """Active traffic incidents as a GeoJSON FeatureCollection."""
    rows = conn.execute(text("""
        SELECT event_id, event_type, severity, description, road_name,
               start_time, end_time,
               ST_AsGeoJSON(geom)::json AS geometry
        FROM traffic_events
        WHERE end_time IS NULL OR end_time > now()
        ORDER BY start_time DESC NULLS LAST
    """)).mappings().all()
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": row["geometry"],
                "properties": {
                    "event_id":    row["event_id"],
                    "event_type":  row["event_type"],
                    "severity":    row["severity"],
                    "description": row["description"],
                    "road_name":   row["road_name"],
                    "start_time":  row["start_time"].isoformat() if row["start_time"] else None,
                    "end_time":    row["end_time"].isoformat()   if row["end_time"]   else None,
                },
            }
            for row in rows
            if row["geometry"] is not None
        ],
    }


@app.get("/traffic/work-zones", dependencies=[Depends(api_key_dependency)])
def traffic_work_zones(conn: Connection = Depends(get_conn)):
    """Active work zones as a GeoJSON FeatureCollection."""
    rows = conn.execute(text("""
        SELECT zone_id, road_name, description, start_time, end_time,
               ST_AsGeoJSON(geom)::json AS geometry
        FROM work_zones
        WHERE end_time IS NULL OR end_time > now()
        ORDER BY start_time DESC NULLS LAST
    """)).mappings().all()
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": row["geometry"],
                "properties": {
                    "zone_id":     row["zone_id"],
                    "road_name":   row["road_name"],
                    "description": row["description"],
                    "start_time":  row["start_time"].isoformat() if row["start_time"] else None,
                    "end_time":    row["end_time"].isoformat()   if row["end_time"]   else None,
                },
            }
            for row in rows
            if row["geometry"] is not None
        ],
    }


@app.get("/traffic/toll-rates", dependencies=[Depends(api_key_dependency)])
def traffic_toll_rates(conn: Connection = Depends(get_conn)):
    """Latest toll rate snapshot for each facility/direction/vehicle_class."""
    rows = conn.execute(text("""
        SELECT DISTINCT ON (facility_id, direction, vehicle_class)
               facility_id, facility_name, direction, vehicle_class,
               rate_usd, valid_from, valid_to
        FROM toll_rates
        ORDER BY facility_id, direction, vehicle_class, valid_from DESC
    """)).mappings().all()
    return [dict(r) for r in rows]


@app.get("/traffic/transit-impact", dependencies=[Depends(api_key_dependency)])
def traffic_transit_impact(conn: Connection = Depends(get_conn)):
    """
    For every active traffic event / work zone, return the bus routes whose
    stops fall within 800 m, enriched with historical delay context and an
    alert_level (CRITICAL / WARNING / WATCH).
    """
    return get_traffic_transit_impact(conn)


# ── Stop Observations endpoints ───────────────────────────────────────────────

@app.get("/observations/status", dependencies=[Depends(api_key_dependency)])
def observations_status(conn: Connection = Depends(get_conn)):
    """
    Summary of loaded stop_observations data.
    Returns months_loaded list, total_rows, earliest_month, latest_month.
    """
    from app.services.five11_stop_observations import get_observations_status
    return get_observations_status(conn)


# ── AI / RAG endpoints ────────────────────────────────────────────────────────

@app.post("/ai/ask", dependencies=[Depends(api_key_dependency)])
def ai_ask(
    body: dict,
    conn: Connection = Depends(get_conn),
):
    """Ask a natural language question about AC Transit service."""
    from app.services.ai_assistant import ask
    question = (body.get("question") or "").strip()
    if not question:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="'question' field is required")
    top_k = int(body.get("top_k", 6))
    return ask(conn, question=question, top_k=top_k)


@app.get("/ai/explain/{route_id}", dependencies=[Depends(api_key_dependency)])
def ai_explain_route(
    route_id: str,
    conn: Connection = Depends(get_conn),
):
    """Generate a natural language performance summary for a route."""
    from app.services.ai_assistant import explain_route
    return explain_route(conn, route_id=route_id)


@app.get("/ai/status")
def ai_status():
    """Check Ollama connectivity and model availability — no API key required."""
    from app.services.ai_assistant import get_status
    return get_status()


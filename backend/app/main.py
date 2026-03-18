from datetime import date
from typing import List, Optional, Tuple

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.engine import Connection

from app.core.config import get_settings
from app.db import get_engine
from app.services.analysis import (
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
)
from app.core.security import api_key_dependency

app = FastAPI(title="Bay Area Transit Intelligence API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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


@app.get("/reliability/summary", dependencies=[Depends(api_key_dependency)])
def reliability_summary(
    start_date: date,
    end_date: date,
    route_ids: Optional[List[str]] = Query(default=None),
    conn: Connection = Depends(get_conn),
):
    return get_reliability_summary(conn, start_date=start_date, end_date=end_date, route_ids=route_ids)


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


@app.get("/safety/stops", dependencies=[Depends(api_key_dependency)])
def safety_stops(
    min_score: Optional[float] = Query(default=None),
    max_score: Optional[float] = Query(default=None),
    conn: Connection = Depends(get_conn),
):
    return get_stop_safety_scores(conn, min_score=min_score, max_score=max_score)


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
    conn: Connection = Depends(get_conn),
):
    return {
        "type": "FeatureCollection",
        "features": get_reliability_stops_geo(conn, start_date=start_date, end_date=end_date, route_ids=route_ids),
    }


@app.get("/safety/stops/geo", dependencies=[Depends(api_key_dependency)])
def safety_stops_geo(
    min_score: Optional[float] = Query(default=None),
    max_score: Optional[float] = Query(default=None),
    conn: Connection = Depends(get_conn),
):
    return {
        "type": "FeatureCollection",
        "features": get_safety_stops_geo(conn, min_score=min_score, max_score=max_score),
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


@app.get("/routes/{route_id}/geo", dependencies=[Depends(api_key_dependency)])
def route_geo(route_id: str, conn: Connection = Depends(get_conn)):
    return get_route_geo(conn, route_id=route_id)


@app.get("/bunching/summary", dependencies=[Depends(api_key_dependency)])
def bunching_summary(
    start_date: date,
    end_date: date,
    conn: Connection = Depends(get_conn),
):
    return get_bunching_summary(conn, start_date=start_date, end_date=end_date)


@app.get("/vehicles/live")
def vehicles_live(conn: Connection = Depends(get_conn)):
    """Live vehicle positions — no API key required for real-time map."""
    return get_live_vehicles(conn)


@app.get("/reliability/trend", dependencies=[Depends(api_key_dependency)])
def reliability_trend(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    days: int = Query(default=30, ge=1, le=90),
    route_id: Optional[str] = Query(default=None),
    conn: Connection = Depends(get_conn),
):
    # Compute days from start_date/end_date if provided
    if start_date and end_date:
        from datetime import date as date_type
        days = max(1, (end_date - start_date).days + 1)
    return get_reliability_trend(conn, route_id=route_id, days=days)


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


@app.get("/stops/{stop_id}/reachability", dependencies=[Depends(api_key_dependency)])
def stop_reachability(
    stop_id: str,
    minutes: int = Query(default=30, ge=10, le=90),
    conn: Connection = Depends(get_conn),
):
    return get_stop_reachability(conn, stop_id=stop_id, minutes=minutes)


@app.get("/routes/compare", dependencies=[Depends(api_key_dependency)])
def routes_compare(
    route_ids: str = Query(description="Comma-separated route IDs, e.g. 1T,2T,72"),
    start_date: date = Query(),
    end_date: date = Query(),
    conn: Connection = Depends(get_conn),
):
    ids = [r.strip() for r in route_ids.split(",") if r.strip()][:5]
    return get_route_comparison(conn, route_ids=ids, start_date=start_date, end_date=end_date)


@app.get("/alerts")
def service_alerts():
    """Live service alerts — no API key required."""
    from app.services.alerts_loader import get_service_alerts
    return get_service_alerts()


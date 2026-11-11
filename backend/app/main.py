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
    try:
        from app.core.run_log import prune_run_log, reap_interrupted_runs
        with get_engine().begin() as _c:
            reap_interrupted_runs(_c, ["rt_ingestor", "traffic_loop", "baseline_predictor", "embed_pipeline"])
            prune_run_log(_c, get_settings().run_log_retention_days)
    except Exception:
        pass  # log tables may not exist yet (migration 012 not applied)

    # 511.org multi-agency RT ingestor — interval from settings (rate limit 60 req/hr)
    t_rt = threading.Thread(
        target=run_polling_loop,
        kwargs={"poll_interval_seconds": get_settings().five11_rt_poll_seconds, "stop_event": _stop_event},
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

    # 511.org traffic events, work zones, toll rates — interval from config (511 budget)
    t_traffic = threading.Thread(
        target=run_traffic_loop,
        kwargs={"interval_seconds": get_settings().five11_traffic_poll_seconds, "stop_event": _stop_event},
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


from app.core.redact import install_redaction

install_redaction()  # scrub API keys from any log/print output

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


# ── System status (troubleshooting dashboard) ─────────────────────────────────

@app.get("/admin/status", dependencies=[Depends(api_key_dependency)])
def admin_status(conn: Connection = Depends(get_conn)):
    """One-call health snapshot: DB, data freshness, 511 budget, jobs, threads, Ollama."""
    from app.services.system_status import get_system_status
    return get_system_status(conn)


@app.get("/admin/activities", dependencies=[Depends(api_key_dependency)])
def admin_activities(conn: Connection = Depends(get_conn)):
    """One card per backend activity (ingestors, loaders, schedulers, external APIs, database)."""
    from app.services.activities import list_activities
    return list_activities(conn)


@app.get("/admin/activities/{key}", dependencies=[Depends(api_key_dependency)])
def admin_activity_detail(key: str, conn: Connection = Depends(get_conn)):
    """Full breakdown of one activity: overview, progress, runs, API calls, data, errors, config, logs."""
    from app.services.activities import get_activity_detail
    detail = get_activity_detail(conn, key)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Unknown activity '{key}'")
    return detail


@app.get("/admin/api-calls", dependencies=[Depends(api_key_dependency)])
def admin_api_calls(
    source: Optional[str] = Query(default=None),
    errors_only: bool = Query(default=False),
    hours: int = Query(default=24, ge=1, le=336),
    limit: int = Query(default=100, ge=1, le=1000),
    conn: Connection = Depends(get_conn),
):
    """Recent outbound API calls (host + path only, never the query string)."""
    from app.services.system_status import get_api_calls
    return get_api_calls(conn, source=source, errors_only=errors_only, hours=hours, limit=limit)


@app.get("/admin/job-runs", dependencies=[Depends(api_key_dependency)])
def admin_job_runs(
    job: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None, pattern="^(running|ok|error)$"),
    limit: int = Query(default=100, ge=1, le=1000),
    conn: Connection = Depends(get_conn),
):
    """Recent worker/loop runs with status, rows written and error text."""
    from app.services.system_status import get_job_runs
    return get_job_runs(conn, job=job, status=status, limit=limit)


@app.get("/")
def root():
    s = get_settings()
    return {
        "message": "Bay Area Transit Intelligence API",
        "dashboard": f"{s.frontend_url}/#status",
        "api_docs": "/docs",
        "status_endpoints": ["/admin/status", "/admin/activities", "/admin/job-runs", "/admin/api-calls"],
    }


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


# ── Sprint 5a → Fare Burden Mapper ──────────────────────────────────────────

@app.get("/equity/fare-burden", dependencies=[Depends(api_key_dependency)])
def equity_fare_burden(
    anchor_weights: Optional[str] = Query(default=None,
        description="Comma-separated key:weight pairs e.g. 'sf:1,oakland:1,sfo:0.5'"),
    min_population: int = Query(default=0, ge=0),
    limit:          int = Query(default=2000, ge=1, le=5000),
    conn: Connection = Depends(get_conn),
):
    """GeoJSON FeatureCollection of coverage_cells with per-cell fare
    burden.  Source: `fare_burden` table (nightly recompute); burden_pct
    is computed at query time from the cached per-anchor fares and the
    cell's median_household_income so the UI can re-weight anchors
    without re-running the heavy job."""
    from app.services.fare_burden import get_fare_burden_features
    weights: Optional[dict] = None
    if anchor_weights:
        weights = {}
        for pair in anchor_weights.split(","):
            if ":" not in pair:
                continue
            k, v = pair.split(":", 1)
            try:
                weights[k.strip()] = float(v.strip())
            except ValueError:
                continue
    features = get_fare_burden_features(
        conn,
        anchor_weights=weights,
        min_population=min_population,
        limit=limit,
    )
    return {"type": "FeatureCollection", "features": features}


# ── Sprint 5b → Service Delivery Gap ────────────────────────────────────────

@app.get("/equity/service-delivery-gap", dependencies=[Depends(api_key_dependency)])
def equity_service_delivery_gap(
    min_population: int = Query(default=0, ge=0),
    limit:          int = Query(default=2000, ge=1, le=5000),
    conn: Connection = Depends(get_conn),
):
    """GeoJSON FeatureCollection — one polygon per cell with gap_pct,
    gap_tier, equity_adjusted_gap, and window dates.  Sprint 5b."""
    from app.services.service_delivery_gap import get_service_delivery_gap_features
    features = get_service_delivery_gap_features(
        conn, min_population=min_population, limit=limit,
    )
    return {"type": "FeatureCollection", "features": features}


@app.get(
    "/equity/service-delivery-gap/cells/{cell_id}/routes",
    dependencies=[Depends(api_key_dependency)],
)
def equity_service_delivery_gap_routes(
    cell_id: str,
    limit:   int = Query(default=5, ge=1, le=20),
    conn: Connection = Depends(get_conn),
):
    """Top-N routes by missed-arrival count inside cell_id over the
    same 12-month window.  Used by the Planning → Service Delivery Gap
    sub-page's click-to-drawer drill-down."""
    from app.services.service_delivery_gap import get_route_breakdown_for_cell
    return get_route_breakdown_for_cell(conn, cell_id, limit=limit)


# ── Sprint 5c → ADA Accessibility Gap ───────────────────────────────────────
# More-specific paths (/cells, /stops/{id}/breakdown) registered BEFORE the
# bare /accessibility/gaps collection endpoint per CLAUDE.md convention.

@app.get(
    "/accessibility/gaps/cells",
    dependencies=[Depends(api_key_dependency)],
)
def accessibility_gaps_cells(
    min_population: int = Query(default=0, ge=0),
    limit:          int = Query(default=2000, ge=1, le=10000),
    conn: Connection = Depends(get_conn),
):
    """Cell-rollup heatmap for the ADA Accessibility Gap."""
    from app.services.ada_accessibility_gap import (
        get_cell_ada_gap_features,
    )
    return {
        "type": "FeatureCollection",
        "features": get_cell_ada_gap_features(
            conn, min_population=min_population, limit=limit
        ),
    }


@app.get(
    "/accessibility/gaps/stops/{stop_id}/breakdown",
    dependencies=[Depends(api_key_dependency)],
)
def accessibility_gaps_breakdown(
    stop_id: str,
    agency_id: Optional[str] = None,
    conn: Connection = Depends(get_conn),
):
    """Per-stop drill: routes serving + top-3 contributing tracts.
    stop_id repeats across agencies, so pass ?agency_id= to disambiguate."""
    from app.services.ada_accessibility_gap import (
        get_stop_ada_gap_breakdown,
    )
    return get_stop_ada_gap_breakdown(conn, stop_id, agency_id)


@app.get(
    "/accessibility/gaps",
    dependencies=[Depends(api_key_dependency)],
)
def accessibility_gaps(
    tier:  str | None = Query(default=None,
        description="Filter: low | moderate | high | very_high"),
    limit: int        = Query(default=5000, ge=1, le=20000),
    conn: Connection = Depends(get_conn),
):
    """Primary ADA Accessibility Gap stops FeatureCollection."""
    from app.services.ada_accessibility_gap import (
        get_stop_ada_gap_features,
    )
    return {
        "type": "FeatureCollection",
        "features": get_stop_ada_gap_features(conn, tier=tier, limit=limit),
    }


# ── Sprint 4a → Fares v2 (debug-only endpoint for now) ──────────────────────

from app.services.fare_calculator import FareRequest as _FareRequest, calculate_fare as _calculate_fare
from app.services.fare_sampler import (
    SampleCorridorRequest as _SampleCorridorRequest,
    sample_corridor as _sample_corridor,
)


@app.post("/fares/sample-corridor", dependencies=[Depends(api_key_dependency)])
def fares_sample_corridor(
    payload: _SampleCorridorRequest,
    conn: Connection = Depends(get_conn),
):
    """Sample up to `n` single-agency OD pairs between the two clicks and
    return summary stats + equity breakdown.  v1 doesn't traverse multi-
    agency transfers — corridors that span unconnected networks return a
    `notice` and zero rows."""
    result = _sample_corridor(conn, payload.origin, payload.destination, n=payload.n)
    return result


@app.post("/fares/calculate", dependencies=[Depends(api_key_dependency)])
def fares_calculate(
    payload: _FareRequest,
    conn: Connection = Depends(get_conn),
):
    """Sum the fare across a list of legs. v1 has no transfer discounts;
    sum-of-legs is structurally correct for current Bay Area fare data
    (Clipper transfer credits are rider-pass-layer, not fare-rule-layer).

    Each leg result includes `matched_by` so the UI can mark structurally-
    less-certain matches (anything past `route_only`).  Closed value set
    is in app.services.fare_calculator.MATCHED_BY_VALUES."""
    return _calculate_fare(conn, payload.legs)


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

@app.get("/transfers/deserts", dependencies=[Depends(api_key_dependency)])
def transfers_deserts(
    agencies: Optional[str] = Query(default=None, description="Comma-separated agency_ids; defaults to all has_data=true"),
    min_population: int = Query(default=0, ge=0),
    desert_threshold_m: int = Query(default=800, ge=100, le=5000),
    close_enough_m: int = Query(default=2000, ge=100, le=10000),
    max_search_m: int = Query(default=3000, ge=100, le=20000),
    limit: int = Query(default=1000, ge=1, le=5000),
    conn: Connection = Depends(get_conn),
):
    """GeoJSON FeatureCollection of cells that are transfer deserts.

    A cell is a desert for agency pair (A, B) when one agency is reachable
    within `close_enough_m` but the other is farther than `desert_threshold_m`.
    `max_search_m` bounds how far we look for either agency's stop — beyond
    that an agency is "not relevant to this cell" rather than "missing".
    Sorted by population × number-of-deserts so the highest-impact cells
    surface first."""
    from app.services.transfer_deserts import compute_transfer_deserts, transfer_deserts_geojson
    agency_list = [a.strip() for a in agencies.split(",") if a.strip()] if agencies else None
    rows = compute_transfer_deserts(
        conn,
        agencies=agency_list,
        min_population=min_population,
        desert_threshold_m=desert_threshold_m,
        close_enough_m=close_enough_m,
        max_search_m=max_search_m,
        limit=limit,
    )
    return transfer_deserts_geojson(rows)


@app.get("/transfers/radii", dependencies=[Depends(api_key_dependency)])
def transfers_radii():
    """Walking-distance radii (metres) the user can pick for transfer matching, plus the default."""
    from app.services.transfer_reliability import get_transfer_radii
    return get_transfer_radii()


@app.get("/transfers/reliability", dependencies=[Depends(api_key_dependency)])
def transfers_reliability(
    from_agency: Optional[str] = Query(default=None),
    to_agency:   Optional[str] = Query(default=None),
    min_observations: int = Query(default=0, ge=0),
    radius_m: Optional[int] = Query(default=None, ge=0, le=1000,
                                    description="Max walking distance between stops; see /transfers/radii"),
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
        radius_m=radius_m,
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
    agency_id: Optional[str] = None,
    conn: Connection = Depends(get_conn),
):
    from fastapi import HTTPException
    detail = get_stop_detail(conn, stop_id=stop_id, agency_id=agency_id)
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
    agency_id: Optional[str] = None,
    conn: Connection = Depends(get_conn),
):
    return get_realtime_departures(conn, stop_id=stop_id, agency_id=agency_id)


@app.get("/stops/{stop_id}/live-departures", dependencies=[Depends(api_key_dependency)])
def live_departures(
    stop_id: str,
    agency_id: Optional[str] = None,
    conn: Connection = Depends(get_conn),
):
    """
    Live ETAs from 511.org SIRI Stop Monitoring when available.
    Falls back to DB-backed scheduled departures with delay overlay.
    Every row includes is_realtime: bool.
    """
    from app.services.five11_stop_monitoring import get_live_departures as _siri

    stop_row = conn.execute(
        text("SELECT stop_code, agency_id FROM gtfs_stops "
             "WHERE stop_id = :sid "
             "  AND (CAST(:aid AS text) IS NULL OR agency_id = :aid) "
             "ORDER BY agency_id LIMIT 1"),
        {"sid": stop_id, "aid": agency_id},
    ).mappings().first()

    stop_code = stop_row["stop_code"] if stop_row else None
    agency_id = (stop_row["agency_id"] if stop_row else None) or agency_id or "AC"

    if stop_code:
        try:
            live = _siri(stop_code, agency_id)
            if live:
                return live
        except Exception:
            pass

    # Fallback: normalize DB realtime-departures to the same response shape
    rows = get_realtime_departures(conn, stop_id=stop_id, agency_id=agency_id)
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
    agency_id: Optional[str] = None,
    conn: Connection = Depends(get_conn),
):
    return get_stop_reachability(conn, stop_id=stop_id, minutes=minutes, agency_id=agency_id)


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


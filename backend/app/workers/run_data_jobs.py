"""
Run all data pipeline jobs for the Bay Area Transit Intelligence app.

Usage (from backend directory):
  python -m app.workers.run_data_jobs

Uses DATABASE_URL and other env from .env. Date range defaults to last 7 days
for jobs that need it; override with env DATA_START_DATE, DATA_END_DATE (YYYY-MM-DD).
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

# Ensure backend app is on path when run as script
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text

from app.db import get_engine
from app.services.coverage_builder import build_coverage_cells, build_transit_deserts
from app.services.features_builder import rebuild_stop_features, rebuild_trip_stop_snapshots
from app.services.gtfs_static_loader import load_all_agencies_gtfs, load_gtfs_static
from app.services.headways import compute_headways
from app.services.models_delay_bunching import generate_bunching_predictions, generate_delay_predictions
from app.services.models_demand_crowding import (
    generate_crowding_predictions_from_demand,
    generate_demand_forecasts,
)
from app.services.safety_incidents_loader import load_safety_incidents
from app.services.equity_loader import populate_equity_columns
from app.services.safety_scoring import compute_stop_safety_scores
from app.services.seed_from_static import seed_ops_from_static
from app.services.five11_stop_observations import load_missing_months


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s.strip())
    except ValueError:
        return None


def main() -> None:
    from app.core.redact import install_redaction
    install_redaction()
    today = date.today()
    start_s = os.environ.get("DATA_START_DATE")
    end_s = os.environ.get("DATA_END_DATE")
    start_date = _parse_date(start_s) or (today - timedelta(days=7))
    end_date = _parse_date(end_s) or today

    print("Data jobs date range:", start_date, "->", end_date)

    engine = get_engine()

    # Step 0: hydrate the agencies catalog before anything else, so the
    # downstream GTFS loader can read `agencies WHERE monitored=true`.
    print("0/20 Syncing agency catalog from 511.org...")
    try:
        from app.services.five11_operators import run_operators_sync
        run_operators_sync(engine)
        print("    Done.")
    except Exception as e:
        print(f"    Agency sync failed (continuing — GTFS loader will fall back): {e}")

    print("1/20 Loading GTFS static feeds...")
    try:
        from app.core.config import get_settings as _gs
        if _gs().five11_api_key:
            summary = load_all_agencies_gtfs()
            ok = sum(1 for v in summary.values() if v == "ok")
            failed = sum(1 for v in summary.values() if v.startswith("failed"))
            print(f"     Multi-agency GTFS load done: {ok} ok, {failed} failed.")
            for agency_id, status in summary.items():
                if status != "ok":
                    print(f"     [{agency_id}] {status}")
        else:
            load_gtfs_static()
            print("     GTFS static load done (AC Transit only — FIVE11_API_KEY not set).")
    except Exception as e:
        print("     GTFS static load failed (skipping):", e)
        print("     Continuing; other jobs need GTFS data already in DB.")

    # Sprint 5b: refresh the stop→cell mapping after every GTFS
    # static reload so newly-added/removed stops are reflected.
    with engine.begin() as conn:
        conn.execute(text("REFRESH MATERIALIZED VIEW stop_cell"))
    print("     stop_cell materialized view refreshed")

    # Seed synthetic ops data from GTFS static when no RT data exists
    with engine.connect() as chk:
        rt_count = chk.execute(text("SELECT COUNT(*) FROM ops_trip_events")).scalar()
    if rt_count == 0:
        print("     No RT ops data found — seeding from GTFS static schedule...")
        current = start_date
        total_seeded = 0
        while current <= end_date:
            with engine.begin() as conn:
                n = seed_ops_from_static(current, max_trips=300, conn=conn)
                total_seeded += n
            current += timedelta(days=1)
        print(f"     Seeded {total_seeded} ops events across {(end_date - start_date).days + 1} days.")

    print("1.5/20 Loading GTFS Fares v2 for monitored agencies...")
    try:
        from app.services.gtfs_fares_loader import load_fares_for_all_monitored
        summary = load_fares_for_all_monitored(engine)
        ok = sum(1 for v in summary.values() if isinstance(v, dict) and "_error" not in v
                 and v.get("fare_products", 0) > 0)
        skipped = sum(1 for v in summary.values() if isinstance(v, dict) and "_error" in v)
        print(f"     Fares v2: {ok} ingested, {skipped} skipped (no feed or error).")
        for aid, res in summary.items():
            if isinstance(res, dict) and res.get("fare_products", 0) > 0:
                fp = res.get("fare_products", 0); flr = res.get("fare_leg_rules", 0)
                ftr = res.get("fare_transfer_rules", 0); fa = res.get("fare_areas", 0)
                print(f"     [{aid}] {fp} products, {flr} leg-rules, {ftr} transfer-rules, {fa} areas")
    except Exception as e:
        print(f"     Fares v2 load failed (skipping): {e}")

    print("1.6/20 Loading GTFS Pathways for monitored agencies...")
    try:
        from app.services.gtfs_pathways_loader import load_all_pathways
        with engine.begin() as conn:
            counts = load_all_pathways(conn)
        if counts:
            print(f"     Pathways loaded from {len(counts)} agencies: "
                  f"{sum(counts.values())} total rows")
        else:
            print("     No agencies published pathways.txt; skipping")
    except Exception as e:
        print(f"     Pathways load failed (skipping): {e}")

    print("2/20 Rebuilding trip_stop_snapshots...")
    try:
        with engine.begin() as conn:
            rebuild_trip_stop_snapshots(start_date, end_date, conn=conn)
        print("     Done.")
    except Exception as e:
        print("     trip_stop_snapshots failed (skipping):", e)

    print("3/20 Rebuilding stop_features...")
    try:
        with engine.begin() as conn:
            rebuild_stop_features(conn=conn)
        print("     Done.")
    except Exception as e:
        print("     stop_features failed (skipping):", e)

    print("3.5/20 Loading Bay Area census tract geometry (TIGERweb)...")
    try:
        from app.services.census_tracts_loader import load_bay_area_tracts
        with engine.begin() as conn:
            n = load_bay_area_tracts(conn)
        print(f"     Tracts loaded: {n}")
    except Exception as e:
        print(f"     Tract load failed (skipping): {e}")

    print("4/20 Computing headways for each service date...")
    current = start_date
    while current <= end_date:
        try:
            with engine.begin() as conn:
                compute_headways(current, conn=conn)
        except Exception as e:
            print(f"     Headways for {current} failed (skipping): {e}")
        current += timedelta(days=1)
    print("     Done.")

    print("4.5/20 Loading Census B18105 (Ambulatory Difficulty)...")
    try:
        from app.services.census_ambulatory_loader import load_b18105
        with engine.begin() as conn:
            n = load_b18105(conn)
        print(f"     B18105 loaded: {n} tracts")
    except Exception as e:
        print(f"     B18105 load failed (skipping): {e}")

    print("5/20 Generating delay predictions...")
    try:
        with engine.begin() as conn:
            generate_delay_predictions(start_date, end_date, conn=conn)
        print("     Done.")
    except Exception as e:
        print("     Delay predictions failed (skipping):", e)

    print("6/20 Generating bunching predictions...")
    try:
        with engine.begin() as conn:
            generate_bunching_predictions(start_date, end_date, conn=conn)
        print("     Done.")
    except Exception as e:
        print("     Bunching predictions failed (skipping):", e)

    print("7/20 Generating demand forecasts and crowding predictions...")
    try:
        with engine.begin() as conn:
            generate_demand_forecasts(start_date, end_date, conn=conn)
            generate_crowding_predictions_from_demand(start_date, end_date, conn=conn)
        print("     Done.")
    except Exception as e:
        print("     Demand/crowding predictions failed (skipping):", e)

    print("8/20 Loading safety incidents from Oakland open data...")
    try:
        with engine.begin() as conn:
            load_safety_incidents(conn=conn)
    except Exception as e:
        print("     Safety incident load failed (skipping):", e)
    print("     Done.")

    print("9/20 Computing stop safety scores...")
    with engine.begin() as conn:
        compute_stop_safety_scores(conn=conn)
    print("     Done.")

    print("10/20 Building coverage cells and transit deserts...")
    try:
        with engine.begin() as conn:
            build_coverage_cells(conn=conn)
        with engine.begin() as conn:
            build_transit_deserts(conn=conn)
    except Exception as e:
        print("     Coverage build failed (skipping):", e)
    print("     Done.")

    print("11/20 Populating equity columns from Census ACS...")
    try:
        with engine.begin() as conn:
            populate_equity_columns(conn=conn)
    except Exception as e:
        print(f"     Equity population failed (skipping): {e}")
    print("     Done.")

    print("12/20 Computing cross-agency transfer reliability matrix...")
    try:
        from app.services.transfer_reliability import compute_transfer_reliability
        with engine.begin() as conn:
            n = compute_transfer_reliability(conn, days=14)
        print(f"     Wrote {n} (from_agency, to_agency, transfer_stop) rows.")
    except Exception as e:
        print(f"     transfer_reliability failed (skipping): {e}")

    print("13/20 Loading previous month stop_observations (if not already loaded)...")
    try:
        from app.core.config import get_settings as _gs2
        if _gs2().five11_api_key:
            with engine.begin() as conn:
                results = load_missing_months(conn, months_back=1)
            if results:
                for month, n in results.items():
                    print(f"     {month}: {n:,} rows" if n >= 0 else f"     {month}: FAILED")
            else:
                print("     Already up to date.")
        else:
            print("     Skipped — FIVE11_API_KEY not configured.")
    except Exception as e:
        print(f"     stop_observations load failed (skipping): {e}")
    print("     Done.")

    print("14/20 Computing fare burden by cell...")
    try:
        from app.services.fare_burden import compute_fare_burden_for_all_cells
        with engine.begin() as conn:
            n = compute_fare_burden_for_all_cells(conn)
        print(f"     Wrote {n} fare_burden rows.")
    except Exception as e:
        print(f"     fare_burden failed (skipping): {e}")

    # ── Step 15/20  Service Delivery Gap compute (Sprint 5b) ────────────────
    print("\n[ETL] 15/20  Computing service delivery gap...")
    try:
        from app.services.service_delivery_gap import (
            compute_service_delivery_gap_for_all_cells,
        )
        with engine.begin() as conn:
            n = compute_service_delivery_gap_for_all_cells(conn)
        print(f"     Wrote {n} service_delivery_gap rows.")
    except Exception as e:
        print(f"     Service delivery gap compute failed (skipping): {e}")

    print("16/20 Computing ADA accessibility gap per stop...")
    try:
        from app.services.ada_accessibility_gap import (
            compute_stop_ada_gap_for_all_stops,
        )
        with engine.begin() as conn:
            n = compute_stop_ada_gap_for_all_stops(conn)
        print(f"     Stops scored: {n}")
    except Exception as e:
        print(f"     ADA gap compute failed (skipping): {e}")

    print("17/20 Refreshing cell_ada_gap materialized view...")
    try:
        from app.services.ada_accessibility_gap import refresh_cell_ada_gap
        with engine.begin() as conn:
            refresh_cell_ada_gap(conn)
        print("     cell_ada_gap refreshed")
    except Exception as e:
        print(f"     cell_ada_gap refresh failed (skipping): {e}")

    print("All data jobs completed.")


if __name__ == "__main__":
    main()

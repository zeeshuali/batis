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
from app.services.gtfs_static_loader import load_gtfs_static
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


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s.strip())
    except ValueError:
        return None


def main() -> None:
    today = date.today()
    start_s = os.environ.get("DATA_START_DATE")
    end_s = os.environ.get("DATA_END_DATE")
    start_date = _parse_date(start_s) or (today - timedelta(days=7))
    end_date = _parse_date(end_s) or today

    print("Data jobs date range:", start_date, "->", end_date)

    engine = get_engine()

    print("1/10 Loading GTFS static feed...")
    try:
        load_gtfs_static()
        print("     GTFS static load done.")
    except Exception as e:
        print("     GTFS static load failed (skipping):", e)
        print("     Continuing; other jobs need GTFS data already in DB.")

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

    print("2/10 Rebuilding trip_stop_snapshots...")
    with engine.begin() as conn:
        rebuild_trip_stop_snapshots(start_date, end_date, conn=conn)
    print("     Done.")

    print("3/10 Rebuilding stop_features...")
    with engine.begin() as conn:
        rebuild_stop_features(conn=conn)
    print("     Done.")

    print("4/10 Computing headways for each service date...")
    current = start_date
    while current <= end_date:
        try:
            with engine.begin() as conn:
                compute_headways(current, conn=conn)
        except Exception as e:
            print(f"     Headways for {current} failed (skipping): {e}")
        current += timedelta(days=1)
    print("     Done.")

    print("5/10 Generating delay predictions...")
    with engine.begin() as conn:
        generate_delay_predictions(start_date, end_date, conn=conn)
    print("     Done.")

    print("6/10 Generating bunching predictions...")
    with engine.begin() as conn:
        generate_bunching_predictions(start_date, end_date, conn=conn)
    print("     Done.")

    print("7/10 Generating demand forecasts and crowding predictions...")
    with engine.begin() as conn:
        generate_demand_forecasts(start_date, end_date, conn=conn)
        generate_crowding_predictions_from_demand(start_date, end_date, conn=conn)
    print("     Done.")

    print("8/10 Loading safety incidents from Oakland open data...")
    try:
        with engine.begin() as conn:
            load_safety_incidents(conn=conn)
    except Exception as e:
        print("     Safety incident load failed (skipping):", e)
    print("     Done.")

    print("9/10 Computing stop safety scores...")
    with engine.begin() as conn:
        compute_stop_safety_scores(conn=conn)
    print("     Done.")

    print("10/10 Building coverage cells and transit deserts...")
    try:
        with engine.begin() as conn:
            build_coverage_cells(conn=conn)
        with engine.begin() as conn:
            build_transit_deserts(conn=conn)
    except Exception as e:
        print("     Coverage build failed (skipping):", e)
    print("     Done.")

    print("11/11 Populating equity columns from Census ACS...")
    try:
        with engine.begin() as conn:
            populate_equity_columns(conn=conn)
    except Exception as e:
        print(f"     Equity population failed (skipping): {e}")
    print("     Done.")

    print("All data jobs completed.")


if __name__ == "__main__":
    main()

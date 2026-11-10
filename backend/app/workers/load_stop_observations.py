#!/usr/bin/env python3
"""
Load 511.org monthly stop_observations data into PostgreSQL.

Usage (from the backend/ directory):
  python -m app.workers.load_stop_observations                 # Load last 3 months
  python -m app.workers.load_stop_observations --backfill      # Load all history (2022-03 to now)
  python -m app.workers.load_stop_observations --month 2026-03 # Load one specific month
  python -m app.workers.load_stop_observations --status        # Show what's loaded
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

# Allow running as   python -m app.workers.load_stop_observations
if __name__ == "__main__":
    sys.path.insert(
        0,
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    )

from app.db import get_engine
from app.services.five11_stop_observations import (
    backfill_all_history,
    get_available_months,
    get_loaded_months,
    get_observations_status,
    load_missing_months,
    load_month,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def main() -> None:
    from app.core.redact import install_redaction
    install_redaction()
    parser = argparse.ArgumentParser(
        description="Load 511.org monthly stop_observations into BATIS DB"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--backfill",
        action="store_true",
        help="Load all history from 2022-03 to last month (can take hours)",
    )
    group.add_argument(
        "--month",
        metavar="YYYY-MM",
        help="Load one specific month",
    )
    group.add_argument(
        "--status",
        action="store_true",
        help="Show loaded months and total row count, then exit",
    )
    parser.add_argument(
        "--months-back",
        type=int,
        default=3,
        metavar="N",
        help="Number of recent months to load when no other flag is given (default: 3)",
    )
    args = parser.parse_args()

    engine = get_engine()

    if args.status:
        with engine.connect() as conn:
            status = get_observations_status(conn)
        available = get_available_months()
        print(f"Available months (511.org archive): {len(available)}")
        print(f"Months loaded:  {len(status['months_loaded'])}")
        print(f"Total rows:     {status['total_rows']:,}")
        print(f"Earliest month: {status['earliest_month'] or '—'}")
        print(f"Latest month:   {status['latest_month'] or '—'}")
        missing = set(available) - set(status["months_loaded"])
        if missing:
            print(f"\nMissing months ({len(missing)}):")
            for m in sorted(missing):
                print(f"  {m}")
        return

    if args.month:
        ym = args.month.strip()
        available = get_available_months()
        if ym not in available:
            log.error("Month %s is not in the available range (2022-03 to last month)", ym)
            sys.exit(1)
        with engine.begin() as conn:
            n = load_month(ym, conn)
        print(f"Loaded {n:,} rows for {ym}")
        return

    if args.backfill:
        log.info("Starting full backfill — this may take several hours…")
        with engine.begin() as conn:
            results = backfill_all_history(conn)
        ok = {m: n for m, n in results.items() if n >= 0}
        failed = {m: n for m, n in results.items() if n < 0}
        total = sum(ok.values())
        print(f"\nBackfill complete: {len(ok)} months loaded, {len(failed)} failed")
        print(f"Total rows inserted: {total:,}")
        if failed:
            print(f"Failed months: {sorted(failed)}")
        return

    # Default: load most recent N months
    log.info("Loading last %d missing months…", args.months_back)
    with engine.begin() as conn:
        results = load_missing_months(conn, months_back=args.months_back)
    if not results:
        print("Nothing to load — all recent months already in DB.")
    else:
        for month, n in sorted(results.items()):
            status_str = f"{n:,} rows" if n >= 0 else "FAILED"
            print(f"  {month}: {status_str}")
        total = sum(n for n in results.values() if n >= 0)
        print(f"Total rows inserted: {total:,}")


if __name__ == "__main__":
    main()

"""Backfill stop_observations from the 511.org monthly archive.

Usage:
   python -m app.workers.backfill_stop_observations          # daily step (cron)
   python -m app.workers.backfill_stop_observations N        # load the N newest missing months

With no argument it does one small step: it loads the newest missing months, at most
`stop_obs_backfill_months_per_run` (default 1), going back no further than
`stop_obs_backfill_max_months_back` (default 12) months. Run it daily and history
fills in over time. With nothing left to load it exits 0 and does nothing.

511.org's 60 req/hr limit is shared with the live ingestor. Each month is one large
download. Per-month idempotent, so retries are safe.
"""
from __future__ import annotations

import logging
import sys

from app.db import get_engine
from app.services.five11_stop_observations import backfill_last_n_months, backfill_step


def main() -> int:
    from app.core.redact import install_redaction
    install_redaction()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with get_engine().begin() as conn:
        if len(sys.argv) > 1:
            n = int(sys.argv[1])
            print(f"[backfill] Loading the {n} newest missing months of stop_observations...")
            results = backfill_last_n_months(conn, n=n)
        else:
            print("[backfill] Daily step: loading the newest missing month(s)...")
            results = backfill_step(conn)
    if not results:
        print("[backfill] Nothing to load: every month in range is already present.")
        return 0
    print(f"[backfill] Done: {len(results)} month(s) processed")
    failed = 0
    for ym in sorted(results):
        rows = results[ym]
        if rows >= 0:
            print(f"  {ym}: {rows:,} rows")
        else:
            failed += 1
            print(f"  {ym}: FAILED (see job_runs / the Status tab)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

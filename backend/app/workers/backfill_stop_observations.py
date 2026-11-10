"""Backfill stop_observations from the 511.org monthly archive.

Usage:
   python -m app.workers.backfill_stop_observations          # daily step (cron)
   python -m app.workers.backfill_stop_observations N        # load the N newest missing months

With no argument it does one small step: it loads the newest missing months, at most
`stop_obs_backfill_months_per_run` (default 2, each month in its own transaction), going back no further than
`stop_obs_backfill_max_months_back` (default 12) months. Run it daily and history
fills in over time. With nothing left to load it exits 0 and does nothing.

511.org's 60 req/hr limit is shared with the live ingestor. Each month is one large
download. Per-month idempotent, so retries are safe.
"""
from __future__ import annotations

import logging
import sys

from app.core.config import get_settings
from app.core.run_log import five11_budget_remaining
from app.db import get_engine
from app.services.five11_stop_observations import backfill_last_n_months, backfill_step


def main() -> int:
    from app.core.redact import install_redaction
    install_redaction()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    engine = get_engine()
    if len(sys.argv) > 1:
        n = int(sys.argv[1])
        print(f"[backfill] Loading the {n} newest missing months of stop_observations...")
        with engine.begin() as conn:
            results = backfill_last_n_months(conn, n=n)
    else:
        per_run = get_settings().stop_obs_backfill_months_per_run
        print(f"[backfill] Daily step: loading up to {per_run} missing month(s), one transaction each...")
        results = {}
        for _ in range(per_run):
            s = get_settings()
            with engine.connect() as chk:
                left = five11_budget_remaining(chk, s.five11_rate_limit_per_hour)
            if left < s.stop_obs_backfill_min_budget:
                print(f"[backfill] 511 budget low ({left} of {s.five11_rate_limit_per_hour} requests left "
                      f"this hour, need {s.stop_obs_backfill_min_budget}). Stopping; the next scheduled run retries.")
                return 0
            # Commit each month separately so a failure in a later month keeps earlier ones.
            with engine.begin() as conn:
                step = backfill_step(conn, months_per_run=1)
            results.update(step)
            if not step or any(v < 0 for v in step.values()):
                break
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
            print(f"  {ym}: FAILED (see the Backend tab). It stays missing, so the next scheduled run retries it.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

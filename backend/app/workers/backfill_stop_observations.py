"""One-shot 12-month backfill of stop_observations.

Usage:
   python -m app.workers.backfill_stop_observations [N=12]

511.org's 60 req/hr rate limit makes this a multi-hour operation;
launch with nohup if running interactively.  Per-month idempotent —
safe to retry partial runs.
"""
from __future__ import annotations

import sys

from app.db import get_engine
from app.services.five11_stop_observations import backfill_last_n_months


def main() -> int:
    from app.core.redact import install_redaction
    install_redaction()
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    print(f"[backfill] Loading last {n} months of stop_observations...")
    with get_engine().begin() as conn:
        results = backfill_last_n_months(conn, n=n)
    print(f"[backfill] Done — {len(results)} months processed")
    for ym in sorted(results):
        rows = results[ym]
        if rows >= 0:
            print(f"  {ym}: {rows:,} rows")
        else:
            print(f"  {ym}: FAILED — see logs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

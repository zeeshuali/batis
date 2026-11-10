#!/bin/sh
# Daily BATIS stop_observations backfill: one small step (newest missing month, max 12 months back).
# Installed in the user crontab. Safe to run by hand. Skips if another run holds the lock.
# Tune with STOP_OBS_BACKFILL_MONTHS_PER_RUN / STOP_OBS_BACKFILL_MAX_MONTHS_BACK in backend/.env.
cd "$(dirname "$0")/../backend" || exit 1
mkdir -p logs
exec flock -n /tmp/batis_stop_obs.lock timeout 6h \
  .venv/bin/python -m app.workers.backfill_stop_observations >> logs/backfill_stop_observations.log 2>&1

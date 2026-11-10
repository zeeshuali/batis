"""Download and ingest the 511.org monthly stop_observations archive.

511.org publishes a monthly GTFS zip that includes stop_observations.txt —
actual vs. scheduled arrival times for every stop on every Bay Area agency
going back to March 2022.

Download URL pattern:
  https://api.511.org/transit/datafeeds?api_key=KEY&operator_id=RG&historic=YYYY-MM-so
"""
from __future__ import annotations

import io
import logging
import zipfile
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Any

import certifi
import pandas as pd
import requests
from app.core.run_log import job_run, tracked_get
from psycopg2.extras import execute_values
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.config import get_settings
from app.db import get_engine

log = logging.getLogger(__name__)

# 511.org publishes stop_observations starting March 2022
_ARCHIVE_START_YEAR = 2022
_ARCHIVE_START_MONTH = 3

# Columns writable into stop_observations (excludes GENERATED: delay_seconds, on_time, id, created_at)
_INSERT_COLS = (
    "service_date", "agency_id", "trip_id", "route_id",
    "stop_id", "scheduled_arrival", "observed_arrival",
)

# Candidate column names for each target DB column (tried left-to-right)
_COL_CANDIDATES: dict[str, list[str]] = {
    "service_date":      ["service_date", "service_id", "date", "operating_day"],
    "trip_id":           ["trip_id", "trip"],
    # 511.org's stop_observations.txt switched to an edge schema with
    # (from_stop_id, to_stop_id) columns.  Each row represents an
    # arrival at to_stop_id from from_stop_id, so to_stop_id is the
    # one observed_arrival_time refers to — preferred over from_stop_id.
    "stop_id":           ["stop_id", "to_stop_id", "from_stop_id", "stop"],
    "route_id":          ["route_id", "line_id", "route", "line"],
    "agency_id":         ["agency_id", "operator_id", "agency", "operator"],
    "scheduled_arrival": [
        "scheduled_arrival", "scheduled_arrival_time",
        "aimed_arrival_time", "aimed_arrival",
        "scheduled_time", "sched_arrival",
    ],
    "observed_arrival":  [
        "observed_arrival", "observed_arrival_time",
        "actual_arrival_time", "actual_arrival",
        "actual_time", "obs_arrival",
    ],
}


# ── Public helpers ─────────────────────────────────────────────────────────────

def get_available_months() -> list[str]:
    """Return all YYYY-MM strings from 2022-03 to last complete month (inclusive)."""
    today = date.today()
    # Last complete month = first day of this month minus one day
    last = date(today.year, today.month, 1) - timedelta(days=1)

    months: list[str] = []
    year, month = _ARCHIVE_START_YEAR, _ARCHIVE_START_MONTH
    while (year, month) <= (last.year, last.month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months


def get_loaded_months(conn: Connection) -> list[str]:
    """Return YYYY-MM strings that already have data in stop_observations."""
    rows = conn.execute(
        text(
            "SELECT DISTINCT TO_CHAR(service_date, 'YYYY-MM') AS month "
            "FROM stop_observations ORDER BY month"
        )
    ).fetchall()
    return [r[0] for r in rows]


# ── Download ───────────────────────────────────────────────────────────────────

def download_month(year_month: str) -> io.BytesIO:
    """Download the YYYY-MM stop_observations zip from 511.org. Returns zip bytes."""
    settings = get_settings()
    if not settings.five11_api_key:
        raise RuntimeError("FIVE11_API_KEY is not configured")

    url = (
        f"{settings.five11_base_url}/transit/datafeeds"
        f"?api_key={settings.five11_api_key}"
        f"&operator_id=RG"
        f"&historic={year_month}-so"
    )
    log.info("[stop-obs] Downloading %s …", year_month)
    resp = tracked_get(url, timeout=300, stream=True, verify=certifi.where())
    resp.raise_for_status()

    buf = io.BytesIO()
    total = 0
    for chunk in resp.iter_content(chunk_size=1024 * 1024):
        buf.write(chunk)
        total += len(chunk)
    buf.seek(0)
    log.info("[stop-obs] Downloaded %s — %.1f MB", year_month, total / 1_048_576)
    return buf


# ── Parsing ────────────────────────────────────────────────────────────────────

def _find_stop_obs_entry(zf: zipfile.ZipFile) -> str:
    """Locate stop_observations.txt inside the zip (handles subdirectory nesting)."""
    for name in zf.namelist():
        if name.endswith("stop_observations.txt"):
            return name
    raise FileNotFoundError(
        f"stop_observations.txt not found in zip. Contents: {zf.namelist()[:20]}"
    )


def _resolve_columns(csv_cols: list[str]) -> dict[str, str]:
    """Map target DB column names to the actual CSV column names found in the file."""
    csv_lower = {c.lower().strip(): c for c in csv_cols}
    mapping: dict[str, str] = {}
    for db_col, candidates in _COL_CANDIDATES.items():
        for cand in candidates:
            if cand in csv_lower:
                mapping[db_col] = csv_lower[cand]
                break
    return mapping


def _parse_arrival_col(series: pd.Series, date_series: pd.Series) -> pd.Series:
    """
    Convert an arrival time column to UTC-aware Timestamps.
    Handles three formats:
      - ISO 8601 with timezone offset  ("2026-04-15T08:30:00-07:00")
      - GTFS HH:MM:SS (may exceed 24h) ("08:30:00", "25:10:00")
      - Integer/float seconds-since-midnight (30600)
    """
    # Try ISO datetime parse first (fast vectorised path)
    result = pd.to_datetime(series, utc=True, errors="coerce")
    if result.notna().mean() > 0.5:
        return result

    # GTFS HH:MM:SS or seconds-since-midnight — process row by row on non-null subset
    out = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns, UTC]")
    for idx in series.index[series.notna()]:
        raw = str(series[idx]).strip()
        svc = date_series[idx]
        if pd.isna(svc):
            continue
        try:
            svc_date: date = svc if isinstance(svc, date) else pd.to_datetime(svc).date()
        except Exception:
            continue
        dt = _parse_single_arrival(raw, svc_date)
        if dt is not None:
            out[idx] = pd.Timestamp(dt)
    return out


def _parse_single_arrival(raw: str, svc_date: date) -> datetime | None:
    """Parse one arrival time string to a UTC datetime, returning None on failure."""
    if not raw or raw in ("", "nan", "NaT", "None"):
        return None

    # ISO datetime
    if "T" in raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass

    # HH:MM:SS (GTFS — hours ≥ 24 roll to next day)
    if ":" in raw:
        try:
            parts = raw.split(":")
            h, m, s = int(parts[0]), int(parts[1]), int(float(parts[2]))
            midnight = datetime(svc_date.year, svc_date.month, svc_date.day, tzinfo=timezone.utc)
            return midnight + timedelta(hours=h, minutes=m, seconds=s)
        except (ValueError, IndexError):
            pass

    # Seconds since midnight
    try:
        secs = int(float(raw))
        midnight = datetime(svc_date.year, svc_date.month, svc_date.day, tzinfo=timezone.utc)
        return midnight + timedelta(seconds=secs)
    except ValueError:
        pass

    return None


def parse_stop_observations(zip_bytes: io.BytesIO) -> pd.DataFrame:
    """
    Parse stop_observations.txt from a zip BytesIO.

    Handles flexible column naming — logs actual CSV columns found.
    Returns DataFrame with canonical columns:
        service_date, agency_id, trip_id, route_id, stop_id,
        scheduled_arrival, observed_arrival
    """
    with zipfile.ZipFile(zip_bytes) as zf:
        entry = _find_stop_obs_entry(zf)
        with zf.open(entry) as f:
            raw = pd.read_csv(f, dtype=str, low_memory=False)

    log.info("[stop-obs] CSV columns: %s", list(raw.columns))
    mapping = _resolve_columns(list(raw.columns))
    log.info("[stop-obs] Column mapping: %s", mapping)

    if "service_date" not in mapping:
        raise ValueError(f"Cannot find service_date column. CSV cols: {list(raw.columns)}")

    df = pd.DataFrame()
    for db_col, csv_col in mapping.items():
        df[db_col] = raw[csv_col]

    # Fill missing optional columns
    for col in _INSERT_COLS:
        if col not in df.columns:
            df[col] = None

    # Parse service_date
    df["service_date"] = pd.to_datetime(df["service_date"], errors="coerce").dt.date

    # Parse arrival times against service_date
    date_series = df["service_date"]
    if "scheduled_arrival" in mapping:
        df["scheduled_arrival"] = _parse_arrival_col(df["scheduled_arrival"], date_series)
    if "observed_arrival" in mapping:
        df["observed_arrival"] = _parse_arrival_col(df["observed_arrival"], date_series)

    # Drop rows with no service_date, trip_id, or stop_id
    df = df.dropna(subset=["service_date", "trip_id", "stop_id"])
    return df[list(_INSERT_COLS)]


# ── Database loading ───────────────────────────────────────────────────────────

def _month_date_range(year_month: str) -> tuple[date, date]:
    """Return (first_day, last_day) for a YYYY-MM string."""
    year, month = int(year_month[:4]), int(year_month[5:7])
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _batch_insert(raw_cur: Any, df: pd.DataFrame) -> int:
    """Insert rows into stop_observations via psycopg2 execute_values. Returns row count."""
    if df.empty:
        return 0

    cols = list(_INSERT_COLS)
    # NaN/NaT → None for psycopg2
    clean = df[cols].astype(object).where(df[cols].notna(), other=None)
    records = [tuple(row) for row in clean.itertuples(index=False, name=None)]

    col_sql = ", ".join(cols)
    execute_values(
        raw_cur,
        f"INSERT INTO stop_observations ({col_sql}) VALUES %s",
        records,
        page_size=5000,
    )
    return len(records)


def load_month(year_month: str, conn: Connection) -> int:
    """Load one archive month, recording the run for the status dashboard."""
    with job_run("stop_observations_load") as jr:
        n = _load_month_impl(year_month, conn)
        jr.set(rows=n, month=year_month)
        return n


def _load_month_impl(year_month: str, conn: Connection) -> int:
    """
    Download and load one month of stop_observations.
    Idempotent: deletes existing rows for the month before inserting.
    Streams the CSV in 100k-row chunks to avoid loading gigabytes into memory.
    Returns the number of rows inserted.
    """
    loaded = get_loaded_months(conn)
    if year_month in loaded:
        log.info("[stop-obs] %s already loaded — skipping", year_month)
        return 0

    first_day, last_day = _month_date_range(year_month)

    # Clear any partial data from a previous failed attempt
    deleted = conn.execute(
        text(
            "DELETE FROM stop_observations "
            "WHERE service_date >= :first AND service_date <= :last"
        ),
        {"first": first_day, "last": last_day},
    ).rowcount
    if deleted:
        log.info("[stop-obs] Cleared %d stale rows for %s", deleted, year_month)

    zip_bytes = download_month(year_month)

    with zipfile.ZipFile(zip_bytes) as zf:
        entry = _find_stop_obs_entry(zf)
        with zf.open(entry) as f:
            # Detect columns from the first chunk only
            reader = pd.read_csv(f, dtype=str, low_memory=False, chunksize=100_000)
            total_inserted = 0
            mapping: dict[str, str] | None = None
            raw_cur = conn.connection.cursor()

            for chunk_num, chunk in enumerate(reader):
                if mapping is None:
                    mapping = _resolve_columns(list(chunk.columns))
                    log.info("[stop-obs] %s — CSV columns: %s", year_month, list(chunk.columns))
                    log.info("[stop-obs] %s — Resolved mapping: %s", year_month, mapping)
                    if "service_date" not in mapping:
                        raise ValueError(
                            f"[stop-obs] Cannot map service_date for {year_month}. "
                            f"CSV cols: {list(chunk.columns)}"
                        )

                # Normalise column names
                df = pd.DataFrame()
                for db_col, csv_col in mapping.items():
                    df[db_col] = chunk[csv_col]
                for col in _INSERT_COLS:
                    if col not in df.columns:
                        df[col] = None

                df["service_date"] = pd.to_datetime(df["service_date"], errors="coerce").dt.date
                df = df.dropna(subset=["service_date", "trip_id", "stop_id"])
                if df.empty:
                    continue

                date_series = df["service_date"]
                if "scheduled_arrival" in mapping:
                    df["scheduled_arrival"] = _parse_arrival_col(df["scheduled_arrival"], date_series)
                if "observed_arrival" in mapping:
                    df["observed_arrival"] = _parse_arrival_col(df["observed_arrival"], date_series)

                n = _batch_insert(raw_cur, df[list(_INSERT_COLS)])
                total_inserted += n

                if chunk_num % 10 == 0:
                    log.info(
                        "[stop-obs] %s — chunk %d, %d rows so far",
                        year_month, chunk_num, total_inserted,
                    )

    # Resolve the surrogate stop key (migration 010) for the month just loaded.
    resolved = conn.execute(
        text(
            "UPDATE stop_observations so SET stop_pk = g.stop_pk "
            "FROM gtfs_stops g "
            "WHERE so.stop_pk IS NULL "
            "  AND so.service_date >= :first AND so.service_date <= :last "
            "  AND g.agency_id = so.agency_id AND g.stop_id = so.stop_id"
        ),
        {"first": first_day, "last": last_day},
    ).rowcount
    log.info("[stop-obs] %s — loaded %d rows, resolved stop_pk for %d",
             year_month, total_inserted, resolved)
    return total_inserted


def load_missing_months(conn: Connection, months_back: int = 3) -> dict[str, int]:
    """
    Load the most recent N months that aren't already in the DB.
    Returns {month: rows_loaded} dict.
    """
    available = get_available_months()
    loaded = set(get_loaded_months(conn))
    missing = [m for m in available if m not in loaded]

    # Most recent first, take up to months_back
    to_load = missing[-months_back:]

    results: dict[str, int] = {}
    for ym in to_load:
        try:
            n = load_month(ym, conn)
            results[ym] = n
        except Exception as exc:
            log.error("[stop-obs] Failed to load %s: %s", ym, exc)
            results[ym] = -1
    return results


def backfill_last_n_months(conn: Connection, n: int = 12) -> dict[str, int]:
    """Load the most recent N missing months from the 511.org archive.

    Thin wrapper over load_missing_months so the operator-facing
    runner module (workers/backfill_stop_observations.py) has a
    purpose-named entry point.  Per-month idempotent: months already
    loaded are skipped.
    """
    return load_missing_months(conn, months_back=n)


def backfill_all_history(conn: Connection) -> dict[str, int]:
    """
    Load all months from March 2022 to present that aren't already in the DB.
    This is a long-running one-time operation. Progress is logged per month.
    Returns {month: rows_loaded} dict.
    """
    available = get_available_months()
    loaded = set(get_loaded_months(conn))
    missing = [m for m in available if m not in loaded]

    log.info(
        "[stop-obs] Backfill: %d months available, %d loaded, %d to fetch",
        len(available), len(loaded), len(missing),
    )

    results: dict[str, int] = {}
    for i, ym in enumerate(missing, 1):
        log.info("[stop-obs] Backfill progress: %d/%d — loading %s", i, len(missing), ym)
        try:
            n = load_month(ym, conn)
            results[ym] = n
        except Exception as exc:
            log.error("[stop-obs] Backfill: failed to load %s: %s", ym, exc)
            results[ym] = -1

    ok = sum(1 for v in results.values() if v >= 0)
    failed = len(results) - ok
    log.info("[stop-obs] Backfill complete: %d ok, %d failed", ok, failed)
    return results


# ── Status query ───────────────────────────────────────────────────────────────

def get_observations_status(conn: Connection) -> dict:
    """Return summary stats for the stop_observations table."""
    row = conn.execute(
        text(
            "SELECT COUNT(*) AS total_rows, "
            "MIN(service_date) AS earliest_date, "
            "MAX(service_date) AS latest_date "
            "FROM stop_observations"
        )
    ).mappings().first()

    months_loaded = get_loaded_months(conn)

    earliest = str(row["earliest_date"])[:7] if row["earliest_date"] else None
    latest   = str(row["latest_date"])[:7]   if row["latest_date"]   else None

    return {
        "months_loaded":  months_loaded,
        "total_rows":     int(row["total_rows"] or 0),
        "earliest_month": earliest,
        "latest_month":   latest,
    }

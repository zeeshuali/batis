import io
import json
import zipfile
import hashlib
from datetime import datetime
from typing import Iterable

import certifi
import pandas as pd
import requests
from psycopg2.extras import execute_values
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.config import get_settings
from app.db import get_engine


# Shapes are optional: some agencies (ferries, rail) may not include shapes.txt
GTFS_REQUIRED_FILES = ["routes.txt", "stops.txt", "trips.txt", "stop_times.txt"]


def _download_gtfs_zip(url: str) -> bytes:
    resp = requests.get(url, timeout=120, verify=certifi.where())
    resp.raise_for_status()
    return resp.content


def _zip_entry(zf: zipfile.ZipFile, name: str) -> str:
    """Return the full zip entry path for a GTFS filename, handling subdirectory nesting."""
    if name in zf.namelist():
        return name
    for entry in zf.namelist():
        if entry.endswith("/" + name):
            return entry
    raise KeyError(f"{name} not found in GTFS zip")


def _read_gtfs_csv(zf: zipfile.ZipFile, name: str) -> pd.DataFrame:
    with zf.open(_zip_entry(zf, name)) as f:
        return pd.read_csv(f)


def _upsert_dataframe(
    conn: Connection, df: pd.DataFrame, table: str, conflict_cols: Iterable[str]
) -> None:
    """
    Batch upsert via a temp table + single INSERT … ON CONFLICT.

    Fills a typed temp table in one multi-row INSERT (psycopg2 execute_values),
    then merges into the target with a single SQL statement — avoiding the per-row
    round-trip cost of executemany on large tables like gtfs_stop_times.
    """
    if df.empty:
        return

    cols = list(df.columns)
    col_list = ", ".join(cols)
    conflict_set = set(conflict_cols)
    conflict_str = ", ".join(conflict_cols)
    update_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in conflict_set)

    # Temp table inherits column types from the real table; no FK or UNIQUE constraints.
    # ON COMMIT DROP keeps the temp table scoped to the current transaction.
    tmp = f"_gtfs_tmp_{table}"
    conn.execute(
        text(
            f"CREATE TEMP TABLE IF NOT EXISTS {tmp} ON COMMIT DROP "
            f"AS SELECT {col_list} FROM {table} WHERE FALSE"
        )
    )
    conn.execute(text(f"TRUNCATE {tmp}"))

    # Convert to list-of-tuples; NaN/NaT → None
    clean = df.astype(object).where(df.notna(), other=None)
    records = [tuple(row) for row in clean.itertuples(index=False, name=None)]

    # execute_values sends multi-row INSERT batches — single round-trip per page
    raw_cur = conn.connection.cursor()
    execute_values(
        raw_cur,
        f"INSERT INTO {tmp} ({col_list}) VALUES %s",
        records,
        page_size=1000,
    )

    conn.execute(
        text(
            f"INSERT INTO {table} ({col_list}) SELECT {col_list} FROM {tmp} "
            f"ON CONFLICT ({conflict_str}) DO UPDATE SET {update_set}"
        )
    )


def _prepare_dataframes(
    zf: zipfile.ZipFile, agency_id: str
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Read, clean, and tag all GTFS DataFrames for one agency.
    Returns (routes_df, stops_df, trips_df, stop_times_df, shapes_df).
    shapes_df is empty if shapes.txt is absent.
    """
    basenames = {e.rsplit("/", 1)[-1] for e in zf.namelist()}

    routes_df = _read_gtfs_csv(zf, "routes.txt")
    stops_df = _read_gtfs_csv(zf, "stops.txt")
    trips_df = _read_gtfs_csv(zf, "trips.txt")
    stop_times_df = _read_gtfs_csv(zf, "stop_times.txt")
    shapes_df = _read_gtfs_csv(zf, "shapes.txt") if "shapes.txt" in basenames else pd.DataFrame()

    # Clean integer columns that may contain blank strings in some feeds
    for col in ("location_type", "wheelchair_boarding"):
        if col in stops_df.columns:
            stops_df[col] = pd.to_numeric(stops_df[col], errors="coerce").where(
                stops_df[col].astype(str).str.strip() != "", other=None
            )
    if "direction_id" in trips_df.columns:
        trips_df["direction_id"] = pd.to_numeric(trips_df["direction_id"], errors="coerce")

    # Ensure ID columns are strings to match text PKs/FKs in DB
    stops_df["stop_id"] = stops_df["stop_id"].astype(str)
    if "route_id" in routes_df.columns:
        routes_df["route_id"] = routes_df["route_id"].astype(str)
    for col in ("trip_id", "route_id", "shape_id", "service_id"):
        if col in trips_df.columns:
            trips_df[col] = trips_df[col].astype(str)
    for col in ("trip_id", "stop_id"):
        if col in stop_times_df.columns:
            stop_times_df[col] = stop_times_df[col].astype(str)
    if not shapes_df.empty and "shape_id" in shapes_df.columns:
        shapes_df["shape_id"] = shapes_df["shape_id"].astype(str)

    # Tag every row with the agency this data came from
    routes_df["agency_id"] = agency_id
    stops_df["agency_id"] = agency_id
    trips_df["agency_id"] = agency_id
    stop_times_df["agency_id"] = agency_id
    if not shapes_df.empty:
        shapes_df["agency_id"] = agency_id

    return routes_df, stops_df, trips_df, stop_times_df, shapes_df


def _parse_feed_info(
    zf: zipfile.ZipFile, basenames: set[str]
) -> tuple[object, object, object]:
    """Return (feed_start_date, feed_end_date, feed_info_record) from feed_info.txt if present."""
    if "feed_info.txt" not in basenames:
        return None, None, None
    feed_info_df = _read_gtfs_csv(zf, "feed_info.txt")
    if feed_info_df.empty:
        return None, None, None
    row0 = feed_info_df.iloc[0].to_dict()
    start_date, end_date = None, None
    try:
        if row0.get("feed_start_date"):
            start_date = datetime.strptime(str(row0["feed_start_date"]), "%Y%m%d").date()
    except Exception:
        pass
    try:
        if row0.get("feed_end_date"):
            end_date = datetime.strptime(str(row0["feed_end_date"]), "%Y%m%d").date()
    except Exception:
        pass
    return start_date, end_date, row0


def load_agency_gtfs(agency_id: str) -> None:
    """
    Download and load GTFS static data for one agency into Postgres.

    Uses the 511.org datafeeds endpoint when FIVE11_API_KEY is configured.
    Falls back to settings.gtfs_static_url for agency 'AC' (backward-compat).
    """
    settings = get_settings()
    if settings.five11_api_key:
        url = (
            f"{settings.five11_base_url}/transit/datafeeds"
            f"?api_key={settings.five11_api_key}&operator_id={agency_id}"
        )
    elif agency_id == "AC":
        url = settings.gtfs_static_url
    else:
        raise RuntimeError(
            f"Cannot load agency '{agency_id}': FIVE11_API_KEY is not configured."
        )

    zip_bytes = _download_gtfs_zip(url)
    feed_hash = hashlib.sha256(zip_bytes).hexdigest()
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))

    basenames = {e.rsplit("/", 1)[-1] for e in zf.namelist()}
    missing = [f for f in GTFS_REQUIRED_FILES if f not in basenames]
    if missing:
        raise RuntimeError(f"[{agency_id}] Missing required GTFS files: {missing}")

    routes_df, stops_df, trips_df, stop_times_df, shapes_df = _prepare_dataframes(
        zf, agency_id
    )
    feed_start_date, feed_end_date, feed_info_record = _parse_feed_info(zf, basenames)

    # Column subsets that match the DB schema
    routes_cols = [
        c for c in routes_df.columns
        if c in {"route_id", "agency_id", "route_short_name", "route_long_name",
                 "route_desc", "route_type", "route_url", "route_color", "route_text_color"}
    ]
    stops_core_cols = [
        c for c in stops_df.columns
        if c in {"stop_id", "agency_id", "stop_code", "stop_name", "stop_desc",
                 "stop_lat", "stop_lon", "zone_id", "stop_url", "location_type",
                 "parent_station", "wheelchair_boarding"}
    ]
    trips_cols = [
        c for c in trips_df.columns
        if c in {"trip_id", "agency_id", "route_id", "service_id", "trip_headsign",
                 "direction_id", "block_id", "shape_id"}
    ]
    trips_subset = trips_df[trips_cols].copy()
    trips_subset["peak_offpeak"] = None

    stop_times_cols = [
        c for c in stop_times_df.columns
        if c in {"trip_id", "agency_id", "arrival_time", "departure_time", "stop_id",
                 "stop_sequence", "pickup_type", "drop_off_type", "timepoint"}
    ]
    shapes_cols = [
        c for c in shapes_df.columns
        if c in {"shape_id", "agency_id", "shape_pt_lat", "shape_pt_lon",
                 "shape_pt_sequence", "shape_dist_traveled"}
    ] if not shapes_df.empty else []

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO gtfs_feeds (
                  feed_url, downloaded_at, feed_start_date, feed_end_date,
                  feed_hash, raw_feed_info
                ) VALUES (
                  :feed_url, now(), :feed_start_date, :feed_end_date,
                  :feed_hash, :raw_feed_info
                )
                """
            ),
            {
                "feed_url": url,
                "feed_start_date": feed_start_date,
                "feed_end_date": feed_end_date,
                "feed_hash": feed_hash,
                "raw_feed_info": json.dumps(feed_info_record) if feed_info_record else None,
            },
        )

        _upsert_dataframe(conn, routes_df[routes_cols], "gtfs_routes",
                          ["agency_id", "route_id"])

        # Stops: upsert core columns, then set geometry in a single SQL statement.
        # gtfs_stops keeps a single-column PK; ON CONFLICT targets the composite
        # unique index gtfs_stops_agency_stop_uniq added by migration 009.
        _upsert_dataframe(conn, stops_df[stops_core_cols], "gtfs_stops",
                          ["agency_id", "stop_id"])
        conn.execute(
            text(
                "UPDATE gtfs_stops "
                "SET geom = ST_SetSRID(ST_MakePoint(stop_lon, stop_lat), 4326) "
                "WHERE agency_id = :agency_id AND geom IS NULL"
            ),
            {"agency_id": agency_id},
        )

        _upsert_dataframe(conn, trips_subset, "gtfs_trips",
                          ["agency_id", "trip_id"])

        _upsert_dataframe(
            conn,
            stop_times_df[stop_times_cols],
            "gtfs_stop_times",
            ["agency_id", "trip_id", "stop_sequence"],
        )

        if not shapes_df.empty and shapes_cols:
            _upsert_dataframe(
                conn, shapes_df[shapes_cols], "gtfs_shapes",
                ["agency_id", "shape_id", "shape_pt_sequence"],
            )
            loaded_shape_ids = shapes_df["shape_id"].unique().tolist()
            # Scope the delete by agency so one agency's reload doesn't wipe
            # another agency's shape_geoms rows that share a shape_id.
            conn.execute(
                text("DELETE FROM gtfs_shape_geoms "
                     "WHERE agency_id = :aid AND shape_id = ANY(:ids)"),
                {"aid": agency_id, "ids": loaded_shape_ids},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO gtfs_shape_geoms (shape_id, agency_id, geom)
                    SELECT
                        shape_id,
                        :agency_id,
                        ST_MakeLine(
                            ST_SetSRID(ST_MakePoint(shape_pt_lon, shape_pt_lat), 4326)
                            ORDER BY shape_pt_sequence
                        )
                    FROM gtfs_shapes
                    WHERE shape_id = ANY(:ids)
                    GROUP BY shape_id
                    """
                ),
                {"agency_id": agency_id, "ids": loaded_shape_ids},
            )


def load_all_agencies_gtfs() -> dict:
    """
    Download and load GTFS static data for all monitored Bay Area agencies via 511.org.
    The agency list is read from the `agencies` table (single source of truth,
    populated by five11_operators.run_operators_sync). If that table is empty
    or missing, fall back to a short hardcoded list of 3 anchor agencies.

    Each agency is loaded in its own transaction — one failure does not abort
    the others. Returns {agency_id: "ok" | "failed: <reason>"}.
    """
    engine = get_engine()
    agency_ids: list[str] = []
    try:
        with engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT agency_id FROM agencies WHERE monitored = true ORDER BY agency_id"
                )
            ).fetchall()
        agency_ids = [r[0] for r in rows]
    except Exception as exc:
        print(f"[gtfs-loader] could not read agencies table ({exc}); using fallback list")

    if not agency_ids:
        print("[gtfs-loader] WARNING: agencies table empty — falling back to AC/BA/SF only")
        agency_ids = ["AC", "BA", "SF"]

    results: dict[str, str] = {}
    for agency_id in agency_ids:
        print(f"[gtfs-loader] Loading {agency_id}...")
        try:
            load_agency_gtfs(agency_id)
            results[agency_id] = "ok"
            print(f"[gtfs-loader] {agency_id}: ok")
        except Exception as exc:
            results[agency_id] = f"failed: {exc}"
            print(f"[gtfs-loader] {agency_id}: failed: {exc}")
    return results


def load_gtfs_static() -> None:
    """
    AC Transit GTFS loader — backward-compatible entry point.
    Delegates to load_agency_gtfs('AC'), which uses the 511.org feed when
    FIVE11_API_KEY is set, or falls back to settings.gtfs_static_url otherwise.
    """
    load_agency_gtfs("AC")

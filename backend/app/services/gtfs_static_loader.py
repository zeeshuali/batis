import io
import json
import zipfile
import hashlib
from datetime import datetime
from typing import Iterable

import certifi
import pandas as pd
import requests
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.config import get_settings
from app.db import get_engine


GTFS_REQUIRED_FILES = [
    "routes.txt",
    "stops.txt",
    "trips.txt",
    "stop_times.txt",
    "shapes.txt",
]


def _download_gtfs_zip(url: str) -> bytes:
    # verify=False works around WSL SSL cert chain issues in dev; swap for certifi.where() in prod
    resp = requests.get(url, timeout=60, verify=False)
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
    if df.empty:
        return
    cols = list(df.columns)
    col_list = ", ".join(cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    update_assignments = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in conflict_cols)
    conflict_cols_list = ", ".join(conflict_cols)

    sql = text(
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict_cols_list}) DO UPDATE SET {update_assignments}"
    )
    records = df.astype(object).where(df.notna(), other=None).to_dict(orient="records")
    conn.execute(sql, records)


def load_gtfs_static() -> None:
    """
    Download the GTFS static feed and upsert core tables into Postgres.
    """
    settings = get_settings()
    engine = get_engine()

    zip_bytes = _download_gtfs_zip(settings.gtfs_static_url)
    feed_hash = hashlib.sha256(zip_bytes).hexdigest()
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))

    basenames = {entry.rsplit("/", 1)[-1] for entry in zf.namelist()}
    for required in GTFS_REQUIRED_FILES:
        if required not in basenames:
            raise RuntimeError(f"Missing required GTFS file: {required}")

    routes_df = _read_gtfs_csv(zf, "routes.txt")
    stops_df = _read_gtfs_csv(zf, "stops.txt")
    trips_df = _read_gtfs_csv(zf, "trips.txt")
    stop_times_df = _read_gtfs_csv(zf, "stop_times.txt")
    shapes_df = _read_gtfs_csv(zf, "shapes.txt")

    feed_start_date = None
    feed_end_date = None
    feed_info_record = None
    if "feed_info.txt" in basenames:
        feed_info_df = _read_gtfs_csv(zf, "feed_info.txt")
        if not feed_info_df.empty:
            row0 = feed_info_df.iloc[0].to_dict()
            feed_info_record = row0
            start_val = row0.get("feed_start_date")
            end_val = row0.get("feed_end_date")
            try:
                if start_val:
                    feed_start_date = datetime.strptime(str(start_val), "%Y%m%d").date()
            except Exception:
                feed_start_date = None
            try:
                if end_val:
                    feed_end_date = datetime.strptime(str(end_val), "%Y%m%d").date()
            except Exception:
                feed_end_date = None

    # Clean integer columns that may contain blank strings in some GTFS feeds
    for int_col in ("location_type", "wheelchair_boarding"):
        if int_col in stops_df.columns:
            stops_df[int_col] = pd.to_numeric(stops_df[int_col], errors="coerce").where(
                stops_df[int_col].astype(str).str.strip() != "", other=None
            )
    for int_col in ("direction_id",):
        if int_col in trips_df.columns:
            trips_df[int_col] = pd.to_numeric(trips_df[int_col], errors="coerce")

    # Ensure all ID columns are strings to match text PKs/FKs in DB
    stops_df["stop_id"] = stops_df["stop_id"].astype(str)
    for col in ("route_id",):
        if col in routes_df.columns:
            routes_df[col] = routes_df[col].astype(str)
    for col in ("trip_id", "route_id", "shape_id", "service_id"):
        if col in trips_df.columns:
            trips_df[col] = trips_df[col].astype(str)
    for col in ("trip_id", "stop_id"):
        if col in stop_times_df.columns:
            stop_times_df[col] = stop_times_df[col].astype(str)
    for col in ("shape_id",):
        if col in shapes_df.columns:
            shapes_df[col] = shapes_df[col].astype(str)

    # Add geometry column for stops
    if "stop_lat" in stops_df.columns and "stop_lon" in stops_df.columns:
        stops_df["geom_wkt"] = stops_df.apply(
            lambda r: f"SRID=4326;POINT({r['stop_lon']} {r['stop_lat']})", axis=1
        )

    with engine.begin() as conn:
        # Log this GTFS feed load for reproducibility and health checks
        conn.execute(
            text(
                """
                INSERT INTO gtfs_feeds (
                  feed_url,
                  downloaded_at,
                  feed_start_date,
                  feed_end_date,
                  feed_hash,
                  raw_feed_info
                ) VALUES (
                  :feed_url,
                  now(),
                  :feed_start_date,
                  :feed_end_date,
                  :feed_hash,
                  :raw_feed_info
                )
                """
            ),
            {
                "feed_url": settings.gtfs_static_url,
                "feed_start_date": feed_start_date,
                "feed_end_date": feed_end_date,
                "feed_hash": feed_hash,
                "raw_feed_info": json.dumps(feed_info_record) if feed_info_record else None,
            },
        )

        # Routes
        _upsert_dataframe(conn, routes_df, "gtfs_routes", ["route_id"])

        # Stops (two-phase to set geometry)
        stops_core_cols = [
            c
            for c in stops_df.columns
            if c
            in {
                "stop_id",
                "stop_code",
                "stop_name",
                "stop_desc",
                "stop_lat",
                "stop_lon",
                "zone_id",
                "stop_url",
                "location_type",
                "parent_station",
                "wheelchair_boarding",
            }
        ]
        _upsert_dataframe(conn, stops_df[stops_core_cols], "gtfs_stops", ["stop_id"])

        if "geom_wkt" in stops_df.columns:
            sql_geom = text(
                """
                UPDATE gtfs_stops s
                SET geom = ST_GeomFromEWKT(:geom_wkt)
                WHERE s.stop_id = :stop_id
                """
            )
            for row in stops_df[["stop_id", "geom_wkt"]].to_dict(orient="records"):
                conn.execute(sql_geom, row)

        # Trips
        trips_cols = [
            c
            for c in trips_df.columns
            if c
            in {
                "trip_id",
                "route_id",
                "service_id",
                "trip_headsign",
                "direction_id",
                "block_id",
                "shape_id",
            }
        ]
        trips_df_subset = trips_df[trips_cols].copy()
        trips_df_subset["peak_offpeak"] = None
        _upsert_dataframe(conn, trips_df_subset, "gtfs_trips", ["trip_id"])

        # Stop times
        stop_times_cols = [
            c
            for c in stop_times_df.columns
            if c
            in {
                "trip_id",
                "arrival_time",
                "departure_time",
                "stop_id",
                "stop_sequence",
                "pickup_type",
                "drop_off_type",
                "timepoint",
            }
        ]
        _upsert_dataframe(
            conn, stop_times_df[stop_times_cols], "gtfs_stop_times", ["trip_id", "stop_sequence"]
        )

        # Shapes
        shapes_cols = [
            c
            for c in shapes_df.columns
            if c
            in {
                "shape_id",
                "shape_pt_lat",
                "shape_pt_lon",
                "shape_pt_sequence",
                "shape_dist_traveled",
            }
        ]
        _upsert_dataframe(conn, shapes_df[shapes_cols], "gtfs_shapes", ["shape_id", "shape_pt_sequence"])

        # Aggregate shapes into LineStrings for mapping
        conn.execute(
            text(
                """
                DELETE FROM gtfs_shape_geoms;

                INSERT INTO gtfs_shape_geoms (shape_id, geom)
                SELECT
                  shape_id,
                  ST_MakeLine(
                    ST_SetSRID(
                      ST_MakePoint(shape_pt_lon, shape_pt_lat),
                      4326
                    )
                    ORDER BY shape_pt_sequence
                  ) AS geom
                FROM gtfs_shapes
                GROUP BY shape_id;
                """
            )
        )


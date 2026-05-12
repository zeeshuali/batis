"""
RAG Embedding Pipeline — Phase 2

Builds and maintains pgvector embeddings for:
  - routes        (one row per route with performance summary)
  - stops         (one row per stop with route/crowding context)
  - ops_summaries (one row per route per day — rolling 7-day window)

Uses all-MiniLM-L6-v2 (22 MB, runs locally, no GPU needed for inference).
Runs every 30 minutes alongside the GTFS-RT ingestor and baseline predictor.
"""
from __future__ import annotations

import threading
import time
from typing import List, Tuple

from sentence_transformers import SentenceTransformer
from sqlalchemy import text

from app.core.config import get_settings
from app.db import get_engine

_model: SentenceTransformer | None = None
_model_lock = threading.Lock()


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:  # double-checked locking
                model_name = get_settings().embed_model_name
                print(f"[embed] Loading {model_name} …")
                _model = SentenceTransformer(model_name)
                print(f"[embed] Model loaded")
    return _model


def _embed(texts: List[str]) -> List[List[float]]:
    model = _get_model()
    return model.encode(texts, batch_size=64, show_progress_bar=False).tolist()


def _upsert_embeddings(
    conn,
    rows: List[Tuple[str, str, str, List[float]]],
) -> int:
    """Upsert (content_type, content_id, content_text, embedding) rows."""
    if not rows:
        return 0
    conn.execute(
        text("""
        INSERT INTO ai_embeddings (content_type, content_id, content_text, embedding, updated_at)
        VALUES (:ctype, :cid, :ctext, CAST(:emb AS vector), NOW())
        ON CONFLICT (content_type, content_id)
        DO UPDATE SET
            content_text = EXCLUDED.content_text,
            embedding    = EXCLUDED.embedding,
            updated_at   = NOW()
        """),
        [
            {"ctype": ctype, "cid": cid, "ctext": ctext, "emb": str(emb)}
            for ctype, cid, ctext, emb in rows
        ],
    )
    return len(rows)


# ── Content builders ──────────────────────────────────────────────────────────

def _build_route_texts(conn) -> List[Tuple[str, str]]:
    """(route_id, descriptive text) for every route with recent data."""
    rows = conn.execute(text("""
        SELECT
            r.route_id,
            r.route_short_name,
            r.route_long_name,
            COUNT(DISTINCT e.trip_id)                                        AS trips_today,
            ROUND(AVG(e.delay_seconds))                                      AS avg_delay,
            ROUND(
                SUM(CASE WHEN e.delay_seconds <= 60 THEN 1 ELSE 0 END)::numeric
                / NULLIF(COUNT(e.id), 0) * 100, 1
            )                                                                AS on_time_pct,
            ROUND(MAX(e.delay_seconds))                                      AS max_delay,
            (SELECT COUNT(DISTINCT st.stop_id)
               FROM gtfs_stop_times st
               JOIN gtfs_trips t2 ON t2.trip_id = st.trip_id
              WHERE t2.route_id = r.route_id)                                AS stop_count
        FROM gtfs_routes r
        LEFT JOIN ops_trip_events e
            ON e.route_id = r.route_id
           AND e.service_date >= CURRENT_DATE - INTERVAL '7 days'
           AND e.delay_seconds IS NOT NULL
        GROUP BY r.route_id, r.route_short_name, r.route_long_name
        ORDER BY r.route_short_name
    """)).mappings().all()

    results = []
    for r in rows:
        name = r["route_short_name"] or r["route_id"]
        long_name = r["route_long_name"] or ""
        delay = int(r["avg_delay"] or 0)
        on_time = float(r["on_time_pct"] or 0)
        max_d = int(r["max_delay"] or 0)
        stops = r["stop_count"] or 0
        trips = r["trips_today"] or 0

        text_parts = [f"Route {name}"]
        if long_name:
            text_parts.append(f"({long_name})")
        text_parts.append(f"serves {stops} stops.")
        if trips > 0:
            text_parts.append(
                f"Over the last 7 days: average delay {delay} seconds, "
                f"{on_time:.1f}% on-time, maximum delay {max_d} seconds, "
                f"{trips} trip records."
            )
        else:
            text_parts.append("No recent delay data available.")

        results.append((r["route_id"], " ".join(text_parts)))
    return results


def _build_stop_texts(conn) -> List[Tuple[str, str]]:
    """(stop_id, descriptive text) for stops with route and delay context."""
    rows = conn.execute(text("""
        SELECT
            s.stop_id,
            s.stop_name,
            s.stop_code,
            COUNT(DISTINCT t.route_id)               AS route_count,
            STRING_AGG(DISTINCT r.route_short_name, ', '
                       ORDER BY r.route_short_name)  AS routes,
            ROUND(AVG(e.delay_seconds))              AS avg_delay
        FROM gtfs_stops s
        JOIN gtfs_stop_times st ON st.stop_id = s.stop_id
        JOIN gtfs_trips      t  ON t.trip_id  = st.trip_id
        JOIN gtfs_routes     r  ON r.route_id = t.route_id
        LEFT JOIN ops_trip_events e
            ON e.stop_id    = s.stop_id
           AND e.service_date >= CURRENT_DATE - INTERVAL '7 days'
        GROUP BY s.stop_id, s.stop_name, s.stop_code
        HAVING COUNT(DISTINCT t.route_id) >= 1
        LIMIT 2000
    """)).mappings().all()

    results = []
    for r in rows:
        name = r["stop_name"] or r["stop_id"]
        code = r["stop_code"] or ""
        routes = r["routes"] or "unknown"
        n_routes = r["route_count"] or 0
        delay = int(r["avg_delay"] or 0)

        parts = [f"Stop {name}"]
        if code:
            parts.append(f"(stop code {code})")
        parts.append(f"Served by {n_routes} route(s): {routes}.")
        if delay:
            parts.append(f"Average delay at this stop over the last 7 days: {delay} seconds.")

        results.append((r["stop_id"], " ".join(parts)))
    return results


def _build_ops_summary_texts(conn) -> List[Tuple[str, str]]:
    """Daily ops summaries per route for the last 7 days."""
    rows = conn.execute(text("""
        SELECT
            route_id,
            service_date::text                           AS day,
            ROUND(AVG(delay_seconds))                    AS avg_delay,
            ROUND(MAX(delay_seconds))                    AS max_delay,
            COUNT(*)                                     AS events,
            ROUND(
                SUM(CASE WHEN delay_seconds <= 60 THEN 1 ELSE 0 END)::numeric
                / NULLIF(COUNT(*), 0) * 100, 1
            )                                            AS on_time_pct
        FROM ops_trip_events
        WHERE delay_seconds IS NOT NULL
          AND service_date >= CURRENT_DATE - INTERVAL '7 days'
        GROUP BY route_id, service_date
        HAVING COUNT(*) >= 5
        ORDER BY service_date DESC, route_id
    """)).mappings().all()

    results = []
    for r in rows:
        cid = f"{r['route_id']}_{r['day']}"
        text_val = (
            f"Route {r['route_id']} on {r['day']}: "
            f"average delay {int(r['avg_delay'] or 0)}s, "
            f"max delay {int(r['max_delay'] or 0)}s, "
            f"{float(r['on_time_pct'] or 0):.1f}% on-time, "
            f"{r['events']} trip events recorded."
        )
        results.append((cid, text_val))
    return results


# ── Main loop ─────────────────────────────────────────────────────────────────

def run_embed_once() -> dict:
    engine = get_engine()
    counts = {}
    with engine.begin() as conn:
        for label, ctype, builder in [
            ("routes",       "route",       _build_route_texts),
            ("stops",        "stop",        _build_stop_texts),
            ("ops_summaries","ops_summary", _build_ops_summary_texts),
        ]:
            pairs = builder(conn)
            if not pairs:
                counts[label] = 0
                continue
            ids, texts = zip(*pairs)
            embeddings = _embed(list(texts))
            rows = list(zip([ctype] * len(ids), ids, texts, embeddings))
            n = _upsert_embeddings(conn, rows)
            counts[label] = n

    return counts


def run_embed_loop(
    interval_seconds: int = 1800,
    stop_event: "threading.Event | None" = None,
) -> None:
    _stop = stop_event or threading.Event()
    print("[embed] Starting embedding pipeline")
    while not _stop.is_set():
        try:
            counts = run_embed_once()
            total = sum(counts.values())
            print(f"[embed] Upserted {total} embeddings at {time.strftime('%H:%M:%S')} — {counts}")
        except Exception as exc:
            print(f"[embed] Error: {exc}")
        _stop.wait(interval_seconds)

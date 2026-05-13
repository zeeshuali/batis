# Sprint 5b — Service Delivery Gap Map

**Date:** 2026-05-12
**Sprint:** 5b (second slice of `BLUEPRINT.md` Sprint 5 — Equity & Accessibility)
**Status:** design approved; implementation pending

## Scope decision

`BLUEPRINT.md` Sprint 5 bundles five features. Sprint 5a shipped the
**Fare Burden Mapper**; Sprint 5b takes the next item — **Service
Delivery Gap Map** — which was blocked on `stop_observations` data
that the existing ingestor (`five11_stop_observations.py`) had never
been triggered to load.

| | Sprint 5a (shipped) | **Sprint 5b (this doc)** | Sprint 5c | Sprint 5d |
|---|---|---|---|---|
| **Feature** | Fare Burden Mapper | **Service Delivery Gap** | ADA Accessibility Gap | Service Equity Score composite |
| **Data needed** | 4b fares + ACS B19013 | `stop_observations` (12-month archive) | GTFS Pathways + Census B18101 | All of the above |
| **Status** | done | **ready** | needs new ingestor + new ACS variable | depends on a–c |

## What Sprint 5b delivers

**Persona:** equity researcher / MPO planner (Planning section).

**Product question:** "Of the trips that were *scheduled* to serve
each part of the Bay Area over the past 12 months, what percentage
actually arrived? Where does the gap between promised and delivered
service hit hardest?"

**One-line definition:**

```
gap_pct = (scheduled stop-arrivals where observed_arrival IS NULL
                                   OR |observed − scheduled| > 5 min)
        ÷ (total scheduled stop-arrivals)
```

…rolled up per `coverage_cell` over a trailing 365-day window.
Click a cell → see the top-5 routes responsible for the gap.

Two deliverables:

1. **Backend**: one-shot 12-month backfill of `stop_observations`, a
   new `service_delivery_gap` table populated nightly with per-cell
   scheduled/missed/gap_pct, and two endpoints (
   `GET /equity/service-delivery-gap` for the choropleth + 
   `GET /equity/service-delivery-gap/cells/{cell_id}/routes` for the
   drill-down).
2. **Frontend**: new **Planning → Service Delivery Gap** sub-page —
   choropleth coloured by `gap_tier` + top-10 cells (sorted by
   equity-adjusted gap) + click-to-drawer route breakdown.

Estimate: **~3 weeks** (1.5 weeks backend + ingest, 1 week frontend,
½ week integration + acceptance script).

---

## Data flow

```
511.org historic archive ──────────────────────────────────────────┐
  /transit/datafeeds?operator_id=RG&historic=YYYY-MM-so             │
  (existing ingestor: five11_stop_observations.py)                  │
                                                                    ▼
                              ┌──────────────────────────────────────────┐
                              │  stop_observations                        │
                              │  (~12M rows, 12 trailing months,          │
                              │   30+ agencies, GENERATED delay_seconds   │
                              │   + on_time columns from schema.sql)      │
                              └──────────────────────────────────────────┘
                                              │
                                              │  nightly ETL step 15
                                              ▼
  gtfs_stops ──────► stop→cell spatial join ──┐
                              (MATERIALIZED VIEW stop_cell — refreshed
                               in ETL step 1 after load_all_agencies_gtfs)
                                              ▼
                              ┌──────────────────────────────────────────┐
                              │  service_delivery_gap                     │
                              │  PK cell_id, scheduled_arrivals,          │
                              │     missed_arrivals, gap_pct,             │
                              │     window_start/end, computed_at         │
                              └──────────────────────────────────────────┘
                                              │
                                              ▼
                       GET /equity/service-delivery-gap
                       GET /equity/service-delivery-gap/cells/{id}/routes
                                              │
                                              ▼
                       Planning → Service Delivery Gap (frontend)
```

**Two ingest steps before the nightly job is meaningful:**

1. **One-shot 12-month backfill** of `stop_observations`. Run
   `python -m app.workers.backfill_stop_observations 12` in the
   backend container; estimated ~12 h end-to-end (511.org's 60 req/hr
   rate limit makes the request count the dominant cost — only 12
   monthly zips to fetch, but each is several hundred MB to stream and
   millions of rows to insert). Idempotent per month — safe to retry.
2. **`stop_cell` materialized view** refresh — runs automatically as
   part of ETL step 1 after `load_all_agencies_gtfs`.

After ingest is in place, **nightly ETL step 15** computes
`service_delivery_gap`. The per-route drill-down is **on-the-fly**
(not cached) — only computed when a user clicks a cell, kept fast by
the new `(route_id, service_date)` index on `stop_observations`.

---

## Feature 1 — Backend

### Schema (new migration `007_service_delivery_gap.sql`)

```sql
CREATE TABLE IF NOT EXISTS service_delivery_gap (
  cell_id            text PRIMARY KEY REFERENCES coverage_cells(cell_id),
  scheduled_arrivals integer NOT NULL,
  missed_arrivals    integer NOT NULL,
  gap_pct            numeric(6,3) NOT NULL,          -- 0.000 → 100.000
  window_start       date NOT NULL,
  window_end         date NOT NULL,
  computed_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_service_delivery_gap_gap_pct
  ON service_delivery_gap (gap_pct DESC);

-- Composite index for the per-route drill-down query.
CREATE INDEX IF NOT EXISTS ix_stop_observations_route_date
  ON stop_observations (route_id, service_date);

-- Helper view: which cell does each stop belong to?
CREATE MATERIALIZED VIEW IF NOT EXISTS stop_cell AS
  SELECT s.stop_id, c.cell_id
  FROM gtfs_stops s
  JOIN coverage_cells c
    ON ST_Contains(c.geom, s.geom);

CREATE INDEX IF NOT EXISTS ix_stop_cell_cell ON stop_cell (cell_id);
CREATE INDEX IF NOT EXISTS ix_stop_cell_stop ON stop_cell (stop_id);
```

Also append the same block to `backend/sql/schema.sql` so fresh
installs include it.

### Service module — `backend/app/services/service_delivery_gap.py`

```python
TOLERANCE_SECONDS = 5 * 60   # ±5 min; also a config knob in config.py

def compute_service_delivery_gap_for_all_cells(
    conn: Connection,
    *,
    window_days: int = 365,
    min_scheduled: int = 50,
) -> int:
    """Recompute gap_pct for every cell with >= min_scheduled
    arrivals in the trailing window_days. UPSERTs into
    service_delivery_gap. Returns number of cells written."""

def get_service_delivery_gap_features(
    conn: Connection,
    *,
    min_population: int = 0,
    limit: int = 2000,
) -> list[dict]:
    """Read service_delivery_gap + coverage_cells.geom, return GeoJSON
    Feature dicts. Each feature.properties has gap_pct, gap_tier,
    scheduled_arrivals, missed_arrivals, equity_score, population,
    equity_adjusted_gap (= gap_pct * equity_score), window_start/end."""

def get_route_breakdown_for_cell(
    conn: Connection,
    cell_id: str,
    *,
    limit: int = 5,
) -> list[dict]:
    """Top-N routes inside this cell over the same 12-month window,
    sorted by missed_arrivals desc. Each row: agency_id, route_id,
    scheduled, missed, missed_pct."""

def _gap_tier(pct: float | None) -> str | None:
    """≥10 very_high, 5-10 high, 2-5 moderate, <2 low."""
```

### Tier bands

| Tier | gap_pct | Color (hex) |
|---|---|---|
| `very_high` | ≥ 10% | `#dc2626` |
| `high` | 5–10% | `#f97316` |
| `moderate` | 2–5% | `#facc15` |
| `low` | < 2% | `#22c55e` |

The 2 / 5 / 10 boundaries derive from FTA's general "on-time
performance ≥ 95%" benchmark — a 5% gap is borderline acceptable;
10% is a real service-quality problem.

### Endpoints — `backend/app/main.py`

```python
@app.get("/equity/service-delivery-gap",
         dependencies=[Depends(api_key_dependency)])
def equity_service_delivery_gap(
    min_population: int = Query(default=0, ge=0),
    limit:          int = Query(default=2000, ge=1, le=5000),
    conn: Connection = Depends(get_conn),
):
    """GeoJSON FeatureCollection — one polygon per cell."""

@app.get("/equity/service-delivery-gap/cells/{cell_id}/routes",
         dependencies=[Depends(api_key_dependency)])
def equity_service_delivery_gap_routes(
    cell_id: str,
    limit:   int = Query(default=5, ge=1, le=20),
    conn: Connection = Depends(get_conn),
):
    """Top-N routes by missed-arrival count inside this cell over the
    same 12-month window."""
```

Both go BEFORE any parameterised path (no conflict expected — neither
matches an existing `/equity/{x}` route).

### Ingest helper change (minimal)

`five11_stop_observations.py` already has `load_missing_months(conn,
months_back)`. Wrap it in a sensibly-named helper:

```python
def backfill_last_n_months(conn: Connection, n: int = 12) -> dict[str, int]:
    """Load the most recent N missing months from the 511.org archive."""
    return load_missing_months(conn, months_back=n)
```

…and add a thin runner module `backend/app/workers/backfill_stop_observations.py`:

```python
"""One-shot 12-month backfill. Run as:
   python -m app.workers.backfill_stop_observations [N=12]
"""
import sys
from app.db import get_engine
from app.services.five11_stop_observations import backfill_last_n_months

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    with get_engine().begin() as conn:
        results = backfill_last_n_months(conn, n=n)
    for ym, rows in results.items():
        print(f"  {ym}: {rows:,} rows" if rows >= 0 else f"  {ym}: FAILED")
```

### ETL wiring — `backend/app/workers/run_data_jobs.py`

- **Step 1** (`load_all_agencies_gtfs`): append a
  `REFRESH MATERIALIZED VIEW CONCURRENTLY stop_cell` after the GTFS
  refresh completes. `CONCURRENTLY` requires the unique-row guarantee
  from the underlying join, so use a plain `REFRESH` if uniqueness
  isn't provable — the refresh is fast (~30k stops) either way.
- **New step 15/15**: call
  `compute_service_delivery_gap_for_all_cells`. Logs cell count
  written + the orphan-stop count (stops outside any cell).
- Renumber existing step labels from `/14` to `/15`.

### Tests — `backend/tests/test_service_delivery_gap.py`

- `_gap_tier()` threshold tests — 4 cases + None
- Compute writes rows only for cells with ≥ min_scheduled
- Compute is idempotent (second run produces identical row count)
- gap_pct formula: `missed / scheduled × 100` to 3 decimal places
- Route-breakdown returns ≤ N routes, sorted by missed_count desc
- min_population filter on the endpoint excludes low-pop cells
- HTTP endpoint shape: FeatureCollection, both endpoints, 401
  without API key

~8 tests, matching Sprint 5a's density.

---

## Feature 2 — Frontend

### New sub-page — `frontend/src/sections/planning/ServiceDeliveryGap.tsx`

Mirrors `FareBurden.tsx` so the Planning section reads consistently:

- **Header**: title + persona subtitle ("Scheduled vs. observed
  service per cell").
- **KPI strip** (5 cards): Cells, Mean gap, High-gap (≥5%), Worst gap,
  Total missed arrivals.
- **Map**: `<SectionMap mapMode="service-delivery-gap" height={520}>`.
- **Top-10 cells list**: sorted by `equity_adjusted_gap`
  (= `gap_pct × equity_score`), with `ExportButton` pulling all
  per-cell fields as CSV.
- **Click handler** on a cell: sets
  `selection.serviceGapDrillCell = cell_id`, which causes
  `ServiceGapDrawer` to mount and fetch
  `/equity/service-delivery-gap/cells/{cell_id}/routes`.

### MapView changes — `frontend/src/components/MapView.tsx`

- Add `"service-delivery-gap-cells"` to `SOURCES`.
- Add
  `SECTION_LAYERS["service-delivery-gap"] = ["service-delivery-gap-fill", "service-delivery-gap-outline"]`.
- Add `LEGENDS["service-delivery-gap"]` with 4 tier items.
- Add the paint expression:
  ```ts
  const GAP_COLOR: mapboxgl.Expression = [
    "match", ["coalesce", ["get", "gap_tier"], "none"],
    "very_high", "#dc2626",
    "high",      "#f97316",
    "moderate",  "#facc15",
    "low",       "#22c55e",
    /* else */   "#475569",
  ];
  ```
- Add `case "service-delivery-gap":` to the data-fetch switch.
- Register `service-delivery-gap-fill` as a clickable layer that
  emits the click to `SelectionContext.setServiceGapDrillCell`.

### SelectionContext extension — `frontend/src/context/SelectionContext.tsx`

```ts
serviceGapDrillCell: string | null;
setServiceGapDrillCell: (cellId: string | null) => void;
```

### Drawer component — `frontend/src/sections/planning/ServiceGapDrawer.tsx`

Slide-in panel rendered when `serviceGapDrillCell != null`. Fetches
`/equity/service-delivery-gap/cells/{cellId}/routes`, renders the
5-row list with agency chip, route_id, missed count, missed pct.
Close button clears the selection. Pattern matches the existing
`StopDrawer.tsx`. Estimated ~90 LOC.

### Types — `frontend/src/types.ts`

Add `"service-delivery-gap"` to the legacy `Section` union.

### Sub-nav wiring — `frontend/src/sections/Planning.tsx`

```ts
{ key: "service-delivery-gap", label: "Delivery Gap",
  persona: "Scheduled vs. observed service per cell" },
```

Plus a `<ServiceDeliveryGap />` route-case in the body switch.

### CSS — `frontend/src/sections/planning/planning.css`

Reuse the existing `.planning-fares__burden-*` classes for the
top-10 list. One new `.planning-gap__drawer` block (~30 lines).

### Tests

- `ServiceDeliveryGap.test.tsx` (~4 cases): KPI strip renders the
  right counts; top-10 sorts by `equity_adjusted_gap`; CSV export
  wired; empty-state on no rows.
- `ServiceGapDrawer.test.tsx` (~3 cases): renders top-5 routes from
  mock data; close clears the selection; empty drawer state when no
  routes returned.

~7 new frontend tests.

---

## Phasing

```
Phase 1 — Data ingest + backend (~1.5 weeks)
  Day 1     Migration 008 (table + indices + stop_cell view)
  Day 2     backfill_last_n_months helper + backfill_stop_observations
            runner module + unit tests against a fixture month
  Day 3-4   Launch 12-month backfill in background (long-running);
            in parallel write compute_service_delivery_gap_for_all_cells,
            get_service_delivery_gap_features,
            get_route_breakdown_for_cell + their tests
  Day 5     GET endpoints + endpoint tests
  Day 6-7   First live compute after backfill finishes; perf-tune
            indices if needed

Phase 2 — Frontend sub-page (~1 week)
  Day 1     Types + sub-nav + MapView source/layers/legend/paint
  Day 2-3   ServiceDeliveryGap.tsx layout (KPI strip + map + top-10)
  Day 4     Click handler + SelectionContext extension +
            ServiceGapDrawer
  Day 5     Tests + a11y pass + smoke

Phase 3 — Integration + acceptance script (~½ week)
  scripts/sprint-5b-acceptance.py with 7-8 verification criteria,
  mirroring 5a's pattern.
```

---

## Risks

1. **Backfill duration and 511.org rate-limits.** 60 req/hr documented
   limit, 12 monthly zips ≈ 12 sequential requests + the per-zip
   parse/insert time. Mitigation: run as `nohup python -m
   app.workers.backfill_stop_observations 12 &`, log every month
   boundary, the existing ingestor is per-month idempotent so partial
   retries are safe.
2. **`stop_observations` table size.** 12M rows + GENERATED
   `delay_seconds` + `on_time` columns = several GB on disk. Mitigation:
   spot-check `pg_size_pretty(pg_relation_size('stop_observations'))`
   after the first month; if it's heading > 100 GB, narrow the window
   or add monthly partitioning (deferred).
3. **NULL `observed_arrival` is ambiguous.** Could mean "trip didn't
   run" or "agency didn't report". Mitigation: document as v1 caveat
   in the UI tooltip and the spec. The acceptance script reports
   per-agency NULL rates so we can see how skewed any one agency's
   contribution is.
4. **Orphan stops outside the hex grid.** Cells cover the built-up Bay
   Area, but a few outlying stops (Petaluma, Antioch fringes) may sit
   outside any cell. Those arrivals contribute to neither numerator
   nor denominator. Mitigation: compute job logs orphan-stop count;
   if it's > 5% of stops, expand the cell grid (deferred).
5. **`stop_cell` view staleness.** GTFS-static refreshes nightly. The
   view doesn't auto-refresh. Mitigation: explicit `REFRESH
   MATERIALIZED VIEW stop_cell` in ETL step 1.
6. **Cell × route drill-down latency.** Per-cell click query walks
   `stop_observations` for ~20 stops × 365 days. With the new
   `(route_id, service_date)` index it should be sub-second.
   Mitigation: small in-memory LRU cache
   (`functools.lru_cache(maxsize=256)`) on the route-breakdown
   function so a planner's repeated drill-downs into the same cells
   stay fast within a session.

---

## What we're not building this sprint

- Time-of-day / day-of-week slicing of the gap (defer to Sprint 5d).
- Per-agency reporting-completeness audit (the NULL ambiguity in
  Risk #3).
- Tract-level granularity (defer; Sprint 5a's open finding still
  applies, but adding it here doubles the sprint).
- Historic trend ("did this cell get worse over 3 years?") —
  BLUEPRINT's separate "Historic Equity Trend" feature, Sprint 5d's
  remit.

---

## Verification (end of Sprint 5b)

1. `stop_observations` has ≥ 10M rows spanning 12 contiguous months
   (one month-string per month present in `loaded_months`).
2. `stop_cell` materialized view has rows for ≥ 95% of `gtfs_stops`
   (orphan rate < 5%).
3. `service_delivery_gap` has ≥ 1,500 cells after nightly compute.
4. `GET /equity/service-delivery-gap` returns a non-empty
   FeatureCollection with `gap_pct` + `gap_tier` populated on every
   feature.
5. At least 100 cells have `gap_pct ≥ 5%` (the "high" tier).
6. `GET /equity/service-delivery-gap/cells/{cell_id}/routes` returns
   ≥ 1 route for ≥ 80% of cells (sampled across 20 random cells).
7. `Planning → Service Delivery Gap` renders the choropleth + top-10
   list; clicking a high-gap cell opens the drawer with the top-5
   routes.
8. CSV export downloads with all per-cell fields.
9. `scripts/sprint-5b-acceptance.py` returns 0.
10. Backend ≥ 127 + ~8 new (~135). Frontend ≥ 98 + ~7 new (~105).

---

## Open questions deferred to Sprint 5c / later

- Tract-level granularity for both Fare Burden and Delivery Gap
  (Sprint 5a's open finding; pick up once an actual planner asks for
  it).
- Per-agency reporting-completeness audit to disambiguate NULL
  observed_arrival.
- Composite Service Equity Score that blends Fare Burden + Service
  Delivery Gap + ADA Gap into one number per cell (Sprint 5d).

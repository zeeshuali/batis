# Sprint 5c — ADA Accessibility Gap Tracker

**Date:** 2026-05-13
**Sprint:** 5c (third slice of `BLUEPRINT.md` Sprint 5 — Equity & Accessibility)
**Status:** design approved; implementation pending

## Scope decision

`BLUEPRINT.md` Sprint 5 bundles five features. Sprints 5a and 5b
shipped the **Fare Burden Mapper** and **Service Delivery Gap Map**.
Sprint 5c takes the next item — the **ADA Accessibility Gap
Tracker** — which BLUEPRINT frames as *"Stops/stations with high
disabled-population density but poor wheelchair accessibility"* with
the stated differentiator *"Actionable infrastructure investment
prioritization."*

|   | Sprint 5a (shipped) | Sprint 5b (shipped) | **Sprint 5c (this doc)** | Sprint 5d |
|---|---|---|---|---|
| **Feature** | Fare Burden Mapper | Service Delivery Gap | **ADA Accessibility Gap** | Service Equity Score composite |
| **Data needed** | 4b fares + ACS B19013 | `stop_observations` 12-month archive | GTFS Pathways + ACS B18105 | All of the above |
| **Status** | done | done | **ready** | depends on 5a–5c |

This sprint is the first 5x feature whose **primary unit of analysis
is the stop, not the cell** — capital planners deciding which
stations to retrofit need a ranked list of stops, not a neighborhood
heatmap. Cell-level rollup is retained as a secondary toggle for
consistency with the existing Planning sub-page idiom.

## What Sprint 5c delivers

**Persona:** capital planner / equity researcher (Planning section).

**Product question:** *"Which Bay Area transit stops should we
prioritize for wheelchair retrofit? Which stops sit in neighborhoods
with the most ambulatory-disabled residents but lack accessible
boarding?"*

**One-line definition:**

```
gap_score(stop) = supply_penalty(stop) × ambulatory_pop_400m(stop)

  supply_penalty:
    wheelchair_boarding = 1 (accessible)        → 0.0
    wheelchair_boarding = 0 (unknown)           → 0.5
    wheelchair_boarding = 2 (not accessible)    → 1.0
    Pathways override (rail stations only):
      location_type IN (1,2) AND has_accessible_pathway = false
        → 1.0 (regardless of wheelchair_boarding)

  ambulatory_pop_400m:
    areal-interpolated B18105 ambulatory-difficulty population
    intersecting the 400 m walk buffer around the stop's geometry
```

…computed per stop. Cell rollup (`cell_ada_gap`) is the
`MAX(gap_score)` and `MEAN(gap_score)` across stops in each cell.

Two deliverables:

1. **Backend**: GTFS Pathways ingester (one-time per ETL run, applied
   only where the agency publishes `pathways.txt`); Census ACS B18105
   loader; a new `stop_ada_gap` fact table populated each ETL run with
   per-stop supply/demand/score/tier; a `cell_ada_gap` materialized
   view for the secondary heatmap; and three endpoints:
   - `GET /accessibility/gaps` — stops FeatureCollection (primary)
   - `GET /accessibility/gaps/cells` — cell rollup FeatureCollection
   - `GET /accessibility/gaps/stops/{stop_id}/breakdown` — drill JSON
2. **Frontend**: new **Planning → ADA Gap** sub-page — stop-ranked
   table + map with circles sized by `gap_score` and colored by
   `gap_tier` + cell-rollup heatmap toggle + click-to-drawer per-stop
   breakdown.

Estimate: **~3 weeks** (1.5 weeks backend + ingest, 1 week frontend,
½ week integration + acceptance script). Same envelope as Sprint 5b.

---

## Data flow

```
GTFS static (already loaded)        ──▶ gtfs_stops (read-only):
                                          wheelchair_boarding, geom,
                                          location_type, agency_id

GTFS Pathways (new ingester)        ──▶ gtfs_pathways
                                        gtfs_levels

Census TIGERweb (new loader)        ──▶ census_tracts
                                          (tract_geoid + geom)

Census ACS B18105 (new loader)      ──▶ census_ambulatory
                                          (tract_geoid → ambulatory_pop)

Sprint 5b stop_cell (already built) ──▶ cell ←→ stop mapping
                                          (reused, not rebuilt)

                          ┌─────────────────────────────────┐
                          │ compute_stop_ada_gap_for_all_   │
                          │   stops()  — single SQL pass    │
                          │                                 │
                          │  CTE supply  ─┐                 │
                          │  CTE demand  ─┼──┐              │
                          │  CTE tiers   ─┘  │              │
                          │                  ▼              │
                          │      INSERT INTO stop_ada_gap   │
                          └──────────────┬──────────────────┘
                                         │
                          REFRESH MATERIALIZED VIEW cell_ada_gap
                                         │
                                         ▼
                          ┌─────────────────────────────────┐
                          │ FastAPI (3 endpoints)           │
                          │  /accessibility/gaps            │
                          │  /accessibility/gaps/cells      │
                          │  /accessibility/gaps/stops/     │
                          │     {stop_id}/breakdown         │
                          └──────────────┬──────────────────┘
                                         │
                                         ▼
                          ┌─────────────────────────────────┐
                          │ React — Planning → ADA Gap      │
                          │  KPI strip (5 cards)            │
                          │  Map: circle layer + cell toggle│
                          │  Top-10 stops table             │
                          │  ADAGapDrawer (per-stop drill)  │
                          │  CSV export                     │
                          └─────────────────────────────────┘
```

---

## Architecture & data model

### New tables (migration `008_ada_accessibility_gap.sql`)

```sql
-- Census tract geometry for the 9-county Bay Area (loaded from
-- TIGERweb GeoJSON REST endpoint; ~1500 tracts).  Required for the
-- areal interpolation that maps tract-level ambulatory_pop into
-- per-stop catchment buffers.  Fills the gap left by equity_loader,
-- which aggregates to county level only.
CREATE TABLE IF NOT EXISTS census_tracts (
  tract_geoid text PRIMARY KEY,
  county_fips text NOT NULL,
  geom        geometry(MultiPolygon, 4326),
  computed_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS census_tracts_geom_idx
  ON census_tracts USING GIST (geom);

-- GTFS Pathways static data
CREATE TABLE IF NOT EXISTS gtfs_pathways (
  agency_id        text NOT NULL,
  pathway_id       text NOT NULL,
  from_stop_id     text NOT NULL,
  to_stop_id       text NOT NULL,
  pathway_mode     integer,     -- 1=walkway, 2=stairs, 3=mvg-sidewalk,
                                -- 4=escalator, 5=elevator, 6=fare-gate,
                                -- 7=exit-gate
  is_bidirectional boolean,
  length_m         numeric,
  traversal_time   integer,     -- seconds
  stair_count      integer,
  max_slope        numeric,
  PRIMARY KEY (agency_id, pathway_id)
);
CREATE INDEX IF NOT EXISTS gtfs_pathways_from_idx
  ON gtfs_pathways (agency_id, from_stop_id);
CREATE INDEX IF NOT EXISTS gtfs_pathways_to_idx
  ON gtfs_pathways (agency_id, to_stop_id);

CREATE TABLE IF NOT EXISTS gtfs_levels (
  agency_id   text NOT NULL,
  level_id    text NOT NULL,
  level_index numeric,
  level_name  text,
  PRIMARY KEY (agency_id, level_id)
);

-- Tract-level ambulatory-difficulty population from ACS B18105
CREATE TABLE IF NOT EXISTS census_ambulatory (
  tract_geoid    text PRIMARY KEY,
  ambulatory_pop integer NOT NULL,
  total_pop      integer,
  computed_at    timestamptz DEFAULT now()
);

-- Sprint 5c fact table: per-stop ADA gap score
CREATE TABLE IF NOT EXISTS stop_ada_gap (
  stop_id              text PRIMARY KEY,
  agency_id            text,
  supply_penalty       numeric(3,2),     -- 0.00 / 0.50 / 1.00
  ambulatory_pop_400m  integer,          -- areal-interpolated count
  gap_score            numeric(10,2),    -- supply_penalty × ambulatory_pop
  gap_tier             text,             -- low / moderate / high / very_high
  pathways_override    boolean,          -- true if Pathways override fired
  catchment_radius_m   integer,          -- 400, recorded for transparency
  computed_at          timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS stop_ada_gap_tier_idx
  ON stop_ada_gap (gap_tier);
CREATE INDEX IF NOT EXISTS stop_ada_gap_score_idx
  ON stop_ada_gap (gap_score DESC);

-- Derived per-cell rollup
CREATE MATERIALIZED VIEW IF NOT EXISTS cell_ada_gap AS
  SELECT cc.cell_id,
         COUNT(sag.stop_id)                      AS stop_count,
         MAX(sag.gap_score)                      AS max_gap_score,
         AVG(sag.gap_score)                      AS mean_gap_score,
         MAX(sag.gap_tier ORDER BY
               CASE sag.gap_tier
                 WHEN 'very_high' THEN 4
                 WHEN 'high'      THEN 3
                 WHEN 'moderate'  THEN 2
                 WHEN 'low'       THEN 1
                 ELSE 0
               END DESC)                         AS worst_tier
    FROM coverage_cells cc
    LEFT JOIN stop_cell    sc  ON sc.cell_id  = cc.cell_id
    LEFT JOIN stop_ada_gap sag ON sag.stop_id = sc.stop_id
   GROUP BY cc.cell_id;
CREATE INDEX IF NOT EXISTS cell_ada_gap_score_idx
  ON cell_ada_gap (max_gap_score DESC NULLS LAST);
```

**Key shape decisions:**

- `stop_ada_gap` is the fact table. No FK to `gtfs_stops(stop_id)` —
  the column lacks a unique constraint (same precedent Sprint 5a's
  `fare_burden` and Sprint 5b's `service_delivery_gap` followed).
- `cell_ada_gap` reuses Sprint 5b's `stop_cell` materialized view for
  the stop→cell mapping. The mapping is already computed; this sprint
  only adds aggregation.
- `gtfs_pathways` / `gtfs_levels` mirror the GTFS Pathways spec.
  Composite PK `(agency_id, pathway_id)` because IDs are only unique
  within an agency.
- `worst_tier` aggregation uses ordered-set aggregation to pick the
  highest-severity tier (string ordering alone doesn't work because
  `'low'` sorts before `'moderate'`).

### Tier banding

Percentile-based, computed per ETL run over **non-zero** `gap_scores`:

- top 10% → `very_high`
- 10–25% → `high`
- 25–50% → `moderate`
- bottom 50% (and any zero-score stop) → `low`

Stops with `supply_penalty = 0` always end up `low` because
`gap_score = 0 × demand = 0`. This is correct: already-accessible
stops need no investment regardless of demand.

### Pathways override

The override fires only when **both** conditions hold:

1. `location_type IN (1, 2)` (rail station or station entrance per
   GTFS spec)
2. The stop appears in `gtfs_pathways` and no accessible path connects
   it (i.e. `NOT EXISTS` of any non-stair pathway edge involving the
   stop)

This intentionally narrow scope means bus stops with no Pathways data
fall through to the `wheelchair_boarding`-only rule. Pathways
ingestion is real and complete; the *user-visible* override is scoped
to a small, easy-to-verify subset (BART, partial Caltrain/Muni Metro
— roughly 50–100 stations regionwide).

---

## Service layer

### New files

```
backend/app/services/
  census_tracts_loader.py      — fetches Bay Area tract geometry
                                  from Census TIGERweb GeoJSON REST
  gtfs_pathways_loader.py      — pulls pathways.txt + levels.txt
  census_ambulatory_loader.py  — fetches B18105 from ACS
  ada_accessibility_gap.py     — compute fns + GeoJSON helpers
```

### `census_tracts_loader.py`

```python
def load_bay_area_tracts(conn: Connection) -> int:
    """Fetch Bay Area census tract geometries from the Census TIGERweb
    GeoJSON REST endpoint and upsert into census_tracts.

    Idempotent: ON CONFLICT (tract_geoid) DO UPDATE.  Skips download
    when SELECT COUNT(*) FROM census_tracts >= 1500 (geometry doesn't
    change year-over-year in practice; force re-fetch by truncating).

    TIGERweb returns GeoJSON; geom is written via ST_GeomFromGeoJSON
    then promoted to MultiPolygon via ST_Multi.  Returns rowcount.

    Queries the 9-county Bay Area FIPS list (matching _COUNTIES in
    equity_loader.py): 06001, 06013, 06041, 06055, 06075, 06081,
    06085, 06095, 06097.  Uses requests + certifi.where() per
    project SSL convention."""
```

No new Python dependency — uses `requests` (already a project dep)
and PostGIS `ST_GeomFromGeoJSON` for parsing.  The Census Bureau's
TIGERweb REST endpoint serves authoritative tract polygons in
GeoJSON, sidestepping the need for `geopandas` or shapefile parsing.

### `gtfs_pathways_loader.py`

```python
def load_pathways_for_agency(
    conn: Connection, agency_id: str, gtfs_zip_path: str
) -> int:
    """Load pathways.txt + levels.txt for one agency.
    Idempotent: DELETE existing rows for agency_id, re-INSERT.
    Returns total rows written (pathways + levels)."""

def load_all_pathways(conn: Connection) -> dict[str, int]:
    """Iterate `SELECT agency_id FROM agencies WHERE monitored = true`,
    download each GTFS zip via the existing 511.org datafeeds path,
    load pathways.  Returns {agency_id: rowcount}.
    Agencies whose GTFS zip lacks pathways.txt are skipped (logged)."""
```

Most agencies have no `pathways.txt`. The loader treats absence as
zero rows, not error. Logs which agencies contributed.

### `census_ambulatory_loader.py`

```python
def load_b18105(conn: Connection) -> int:
    """Fetch ACS B18105 (Sex by Age by Ambulatory Difficulty) at
    tract level for the 9-county Bay Area via the Census API,
    sum across age and sex bins, upsert into census_ambulatory.
    Reads settings.census_api_key.
    Returns tract rowcount."""
```

One ACS API call. Sums B18105_004E + B18105_007E + B18105_010E + …
(the "with ambulatory difficulty" subtotals across age bins) per
tract. Mirrors `equity_loader.py`'s fetch shape.

### `ada_accessibility_gap.py`

```python
def _supply_penalty(
    wheelchair_boarding: int,
    has_accessible_pathway: bool | None,
    location_type: int,
) -> float:
    """3-state wheelchair_boarding → penalty, with Pathways override
    applied only when location_type IN (1,2) AND
    has_accessible_pathway is False."""

def _gap_tier(score: float, p90: float, p75: float, p50: float) -> str:
    """Map gap_score to a 4-tier label using percentile thresholds.
    Stops with score = 0 always return 'low'."""

def compute_stop_ada_gap_for_all_stops(
    conn: Connection,
    *,
    catchment_radius_m: int | None = None,
) -> int:
    """Idempotent: TRUNCATE stop_ada_gap, recompute every row in one
    SQL statement with CTEs:
      supply  — wheelchair_boarding + Pathways override (rail only)
      demand  — areal-interpolated B18105 into 400 m stop buffers
      tiers   — PERCENTILE_CONT over non-zero gap_scores
    Reads `ada_catchment_radius_m` from Settings when None.
    Returns rowcount."""

def get_stop_ada_gap_features(
    conn: Connection,
    *,
    tier: str | None = None,
    limit: int = 5000,
) -> list[dict]:
    """GeoJSON Features for the stops layer. Sorted by gap_score DESC.
    Joins gtfs_stops for stop_name + geom, gtfs_stop_times +
    gtfs_trips for routes_serving."""

def get_cell_ada_gap_features(
    conn: Connection,
    *,
    min_population: int = 0,
    limit: int = 2000,
) -> list[dict]:
    """GeoJSON Features for the cell-rollup heatmap. Reads cell_ada_gap
    materialized view joined to coverage_cells.geom and .equity_score."""

def get_stop_ada_gap_breakdown(
    conn: Connection, stop_id: str
) -> dict:
    """Per-stop drill: routes serving stop (from gtfs_trips +
    gtfs_stop_times) + top-3 contributing tracts by area-weighted
    ambulatory_pop. Returns {stop_id, stop_name, agency_id, gap_score,
    gap_tier, supply_penalty, pathways_override, routes, tracts}."""

def refresh_cell_ada_gap(conn: Connection) -> None:
    conn.execute(text("REFRESH MATERIALIZED VIEW cell_ada_gap"))
```

### Settings additions (`backend/app/core/config.py`)

```python
ada_catchment_radius_m:       int   = 400
ada_tier_percentile_high:     float = 0.90
ada_tier_percentile_moderate: float = 0.75
ada_tier_percentile_low:      float = 0.50
```

Add **after** `delivery_gap_tolerance_seconds`. Reads in compute
function via `get_settings()`; falsy-zero treatment matches the
Sprint 5b lesson (no `or` fallback).

### The compute SQL (illustrative shape)

```sql
WITH supply AS (
  SELECT s.stop_id, s.agency_id, s.location_type, s.wheelchair_boarding,
         EXISTS (
           SELECT 1 FROM gtfs_pathways p
            WHERE p.agency_id = s.agency_id
              AND (p.from_stop_id = s.stop_id OR p.to_stop_id = s.stop_id)
              AND p.pathway_mode <> 2   -- 2 = stairs
         ) AS has_accessible_pathway
    FROM gtfs_stops s
),
demand AS (
  SELECT s.stop_id,
         COALESCE(SUM(
           ca.ambulatory_pop
           * ST_Area(ST_Intersection(
               ST_Buffer(s.geom::geography, :r)::geometry, t.geom
             ))
           / NULLIF(ST_Area(t.geom), 0)
         ), 0)::int AS ambulatory_pop_400m
    FROM gtfs_stops s
    LEFT JOIN census_tracts     t  ON ST_DWithin(
            s.geom::geography, t.geom::geography, :r)
    LEFT JOIN census_ambulatory ca USING (tract_geoid)
   GROUP BY s.stop_id
),
combined AS (
  SELECT supply.stop_id, supply.agency_id,
         CASE
           WHEN supply.location_type IN (1, 2)
            AND supply.has_accessible_pathway = false
             THEN 1.0
           WHEN supply.wheelchair_boarding = 1 THEN 0.0
           WHEN supply.wheelchair_boarding = 2 THEN 1.0
           ELSE 0.5
         END AS supply_penalty,
         (supply.location_type IN (1, 2)
            AND supply.has_accessible_pathway = false) AS pathways_override,
         demand.ambulatory_pop_400m
    FROM supply
    JOIN demand USING (stop_id)
),
scored AS (
  SELECT *,
         (supply_penalty * ambulatory_pop_400m)::numeric(10,2) AS gap_score
    FROM combined
),
percentiles AS (
  SELECT PERCENTILE_CONT(:p_high)     WITHIN GROUP (ORDER BY gap_score) AS p_high,
         PERCENTILE_CONT(:p_moderate) WITHIN GROUP (ORDER BY gap_score) AS p_moderate,
         PERCENTILE_CONT(:p_low)      WITHIN GROUP (ORDER BY gap_score) AS p_low
    FROM scored WHERE gap_score > 0
)
INSERT INTO stop_ada_gap (
  stop_id, agency_id, supply_penalty, ambulatory_pop_400m,
  gap_score, gap_tier, pathways_override, catchment_radius_m, computed_at
)
SELECT scored.stop_id, scored.agency_id, scored.supply_penalty,
       scored.ambulatory_pop_400m, scored.gap_score,
       CASE
         WHEN scored.gap_score >= percentiles.p_high     THEN 'very_high'
         WHEN scored.gap_score >= percentiles.p_moderate THEN 'high'
         WHEN scored.gap_score >= percentiles.p_low      THEN 'moderate'
         ELSE 'low'
       END,
       scored.pathways_override, :r, now()
  FROM scored, percentiles
ON CONFLICT (stop_id) DO UPDATE SET …;
```

`census_tracts` table must exist (it does — `equity_loader.py` already
populates it). Plan execution should verify before relying on it.

---

## API surface

Three new endpoints in `backend/app/main.py`, all behind
`Depends(api_key_dependency)`, all with lazy service imports.

### `GET /accessibility/gaps`

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Point", "coordinates": [-122.27, 37.81] },
      "properties": {
        "stop_id": "AC-58123",
        "agency_id": "AC",
        "stop_name": "14th St & Broadway",
        "wheelchair_boarding": 2,
        "supply_penalty": 1.0,
        "ambulatory_pop_400m": 412,
        "gap_score": 412.0,
        "gap_tier": "very_high",
        "pathways_override": false,
        "routes_serving": ["1", "1T", "12", "72"]
      }
    }
  ]
}
```

Query params: `tier` (filter to one of `low | moderate | high |
very_high`), `limit` (default 5000, max 20000). Sorted by `gap_score
DESC`.

### `GET /accessibility/gaps/cells`

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Polygon", "coordinates": [/* … */] },
      "properties": {
        "cell_id": "-122.2750_37.8120",
        "stop_count": 4,
        "max_gap_score": 412.0,
        "mean_gap_score": 178.5,
        "worst_tier": "very_high",
        "population": 1840,
        "equity_score": 0.74
      }
    }
  ]
}
```

Query params: `min_population` (default 0), `limit` (default 2000).

### `GET /accessibility/gaps/stops/{stop_id}/breakdown`

```json
{
  "stop_id": "AC-58123",
  "stop_name": "14th St & Broadway",
  "agency_id": "AC",
  "gap_score": 412.0,
  "gap_tier": "very_high",
  "supply_penalty": 1.0,
  "pathways_override": false,
  "routes": [
    { "route_id": "12", "route_short_name": "12", "trips_per_day": 142 },
    { "route_id": "72", "route_short_name": "72", "trips_per_day":  88 }
  ],
  "tracts": [
    { "tract_geoid": "06001401400", "ambulatory_pop": 215,
      "area_weighted_share": 0.62 },
    { "tract_geoid": "06001401500", "ambulatory_pop":  89,
      "area_weighted_share": 0.27 }
  ]
}
```

### Route order

Register all three in one block. `/accessibility/gaps/cells` and
`/accessibility/gaps/stops/{stop_id}/breakdown` declared **before**
`/accessibility/gaps` per `CLAUDE.md`'s "more specific paths before
parameterised ones" rule (defensive; FastAPI handles this correctly
either way but the project convention is to be explicit).

---

## Frontend layout

### New section + sub-nav

```ts
// frontend/src/types.ts — extend Section union
export type Section =
  | "overview" | "network" | "reliability" | "vehicles" | "stops"
  | "alerts" | "traffic" | "planning"
  | "fare-burden" | "service-delivery-gap"
  | "ada-gap"               // ← NEW
  | "ai-assistant";
```

```tsx
// frontend/src/sections/Planning.tsx — append to sub-nav list
{ id: "ada-gap",
  label: "ADA Gap",
  persona: "Stops to prioritize for wheelchair retrofit" }
```

### `SelectionContext` addition

```ts
adaGapDrillStop: string | null;
setAdaGapDrillStop: (stopId: string | null) => void;
// In clear() reducer:
setAdaGapDrillStopState(null);
```

Mirrors Sprint 5b's `serviceGapDrillCell` pattern exactly (state +
useRef-stable setter for the MapView click handler).

### New page — `frontend/src/sections/planning/ADAGap.tsx`

Layout:

1. **Header** — title "ADA Accessibility Gap" + persona +
   data-window note ("Snapshot from current GTFS static data and
   ACS B18105 5-year estimates.")
2. **KPI strip** (5 `KpiCard`s):
   - Stops scored (count)
   - Inaccessible stops (`wheelchair_boarding = 2` count)
   - Unknown-status stops (`wheelchair_boarding = 0` count)
   - Pathways-overridden stations (rail count where override fired)
   - Total underserved (sum of `gap_score` across very_high stops)
3. **Map** — `SectionMap mapMode="ada-gap"` (stops circles + optional
   cell-rollup heatmap toggle in legend)
4. **Top-10 stops table** — sorted by `gap_score DESC`. Columns:
   stop_name, agency, gap_score, gap_tier, ambulatory_pop_400m,
   supply_penalty. Row click → `setAdaGapDrillStop(stop_id)`.
5. **CSV export** — full ranked list (not just top-10), matching the
   Sprint 5a/5b CSV button shape.

### New drawer — `frontend/src/sections/planning/ADAGapDrawer.tsx`

Slide-in, opens when `adaGapDrillStop != null`. Body:

- Stop header (name, agency, lat/lon)
- Score line ("412 underserved riders within 400m · very_high")
- Routes-serving table (route, trips/day, agency)
- Top-3 contributing tracts (geoid, ambulatory_pop,
  area-weighted share)
- Close button → `setAdaGapDrillStop(null)`

### MapView changes (`frontend/src/components/MapView.tsx`)

```text
- Add source: ada-gap-stops
- Add layer:  ada-gap-stops-layer (circle)
    circle-color:
      [match, [get, gap_tier],
        'very_high', '#c81e1e',
        'high',      '#f59e0b',
        'moderate',  '#fbbf24',
        'low',       '#65a30d',
        /* default */ '#6b7280']
    circle-radius:
      [interpolate, [linear], [get, gap_score],
        0, 4,  100, 8,  500, 14,  2000, 22]
    circle-stroke-color: '#fff'
    circle-stroke-width: 1

- Secondary source: ada-gap-cells (lazy, fetched only when toggle on)
- Secondary layer:  ada-gap-cells-layer (fill, hidden by default,
    toggled by legend pill). Uses max_gap_score with same tier colors
    at fill-opacity 0.45.

- Section exhaustiveness: add 'ada-gap' to Record<Section, …> entries
- Data-fetch case: fetch('/accessibility/gaps') when mode === 'ada-gap'
- Click handler: setAdaGapDrillStopRef.current(f.properties.stop_id)
```

### Legend

Two-half block:

- Top half: stop circle samples (very_high / high / moderate / low)
- Bottom half: cell rollup toggle ("Show neighborhood rollup" pill)

### CSS

`frontend/src/sections/planning/planning.css` — add `.ada-gap-drawer`
class mirroring `.service-gap-drawer` (slide-in transform +
box-shadow).

---

## ETL wiring

The current 15-step pipeline in `backend/app/workers/run_data_jobs.py`
becomes 20 steps (5 new insertions):

```text
After step 1 (GTFS static load):
  1.5/20  Loading GTFS Pathways for monitored agencies...
          → load_all_pathways(conn)

Before step 4 (Census ACS income load) — TIGER tract geometry is
required by compute_stop_ada_gap_for_all_stops; B18105 loader
doesn't need it but the compute step does, so it loads earlier in
the run:
  3.5/20  Loading Bay Area census tract geometry (TIGERweb)...
          → load_bay_area_tracts(conn)

After step 4 (Census ACS income load):
  4.5/20  Loading Census B18105 (Ambulatory Difficulty)...
          → load_b18105(conn)

After step 15 (compute_service_delivery_gap_for_all_cells):
  16/20   Computing ADA accessibility gap per stop...
          → compute_stop_ada_gap_for_all_stops(conn)
  17/20   Refreshing cell_ada_gap materialized view...
          → refresh_cell_ada_gap(conn)
```

All `/15` step labels renumber to `/20` (mechanical search-replace,
same as Sprint 5b's `/14` → `/15`).

---

## Testing

### Backend

`backend/tests/test_accessibility_gap.py` (new):

- `GET /accessibility/gaps` shape + tier filter
- `GET /accessibility/gaps/cells` rollup correctness with two seeded
  stops in one cell
- `GET /accessibility/gaps/stops/{stop_id}/breakdown` returns routes
  + tracts
- 401 on all three when `BACKEND_API_KEY` is set and header missing
- `get_settings.cache_clear()` between monkeypatch overrides
  (pydantic-settings cache, Sprint 5b lesson)

`backend/tests/test_ada_accessibility_gap_service.py` (new):

- `_supply_penalty` 3-state correctness + Pathways override
- `_gap_tier` percentile mapping incl. zero-score → 'low'
- `compute_stop_ada_gap_for_all_stops` with seeded fixtures (3 stops,
  1 tract, no pathways → expected scores)
- Compute with pathways override seeded → override flag set on
  affected stops

`backend/tests/test_gtfs_pathways_loader.py` and
`test_census_ambulatory_loader.py` (new): unit-level coverage for
each loader's parsing + upsert behavior.

**Test counts:** Sprint 5b closed at **151** backend tests; Sprint 5c
adds ~12 → **target ≥163**.

### Frontend

`frontend/src/sections/planning/ADAGap.test.tsx` (new):

- KPI rendering with mocked endpoint data (5 cases)
- Top-10 sort order matches `gap_score DESC`
- Row click sets `adaGapDrillStop` in context
- CSV export contains all returned rows

`frontend/src/sections/planning/ADAGapDrawer.test.tsx` (new):

- Renders routes + tracts when `adaGapDrillStop` is set
- Close button clears state
- Hidden when `adaGapDrillStop` is null

`frontend/src/components/MapView.test.tsx` (extend):

- ADA stops layer paint expression set when `mode === 'ada-gap'`
- Cell-rollup layer toggles visibility

**Test counts:** Sprint 5b closed at **105** frontend tests; Sprint
5c adds ~8 → **target ≥113**.

---

## Verification (end of Sprint 5c)

A `scripts/sprint-5c-acceptance.py` script runs these 11 live checks
against a Dockerized backend (mirrors Sprint 5b's pattern, returns
exit 0 on full pass):

1. **Migration applied** — `gtfs_pathways`, `gtfs_levels`,
   `census_tracts`, `census_ambulatory`, `stop_ada_gap` tables exist;
   `cell_ada_gap` materialized view exists.
2. **Tract geometry loaded** — `SELECT COUNT(*) FROM census_tracts` ≥
   1500 tracts (Bay Area 9-county tract count).
3. **B18105 loaded** — `SELECT COUNT(*) FROM census_ambulatory` ≥
   1500 tracts (every loaded tract has an ambulatory_pop value).
4. **Pathways loaded for ≥1 rail agency** —
   `SELECT COUNT(*) FROM gtfs_pathways` ≥ 100 rows. Soft-pass with
   note if zero (agencies vary on what they publish).
5. **stop_ada_gap populated** — `SELECT COUNT(*) FROM stop_ada_gap`
   ≥ 1000 stops. `gap_score` is non-null for every row.
6. **GeoJSON shape** — `GET /accessibility/gaps` returns
   `type: "FeatureCollection"`, has 11 expected properties on every
   feature, sorted by `gap_score DESC`.
7. **Tier distribution sensible** — at least one stop in each of
   `very_high / high / moderate / low`; `very_high` count ≤ 15% of
   total (percentile-banding sanity check).
8. **Cell rollup populated** — `GET /accessibility/gaps/cells`
   returns ≥ 100 features with non-null `max_gap_score`.
9. **Stop drill works** — pick the highest-`gap_score` stop,
   `GET /accessibility/gaps/stops/{stop_id}/breakdown` returns ≥1
   route and ≥1 tract.
10. **Pathways override fires somewhere** — at least one row where
    `pathways_override = true` if any pathways data exists; soft-pass
    with note if pathways data is empty.
11. **Frontend reachable** — `GET http://localhost:5173/` returns
    200; ADA Gap section renders by inspecting bundled JS for the
    `"ada-gap"` Section literal (matches Sprint 5b's check shape).

---

## Sprint 5c commits

Following the Sprint 5b shape:

- **Phase 1 (~10–11 small commits)** — migration; Pathways loader;
  B18105 loader; service compute fn; service serve fns; ETL wiring;
  config; endpoints; backend tests.
- **Phase 2 (1 bundle commit)** — frontend types + section + sub-nav
  + SelectionContext + MapView + ADAGap page + Drawer + planning.css
  + frontend tests.
- **Phase 3 (1 commit)** — `scripts/sprint-5c-acceptance.py`.

Total: ~12–13 commits, matching the 14-commit envelope of Sprint 5b.

---

## Out of scope for Sprint 5c (explicit deferrals)

- **Full Pathways graph traversal** (per-station shortest-accessible-
  path computation). The override is a per-edge `EXISTS` check;
  graph algorithms are 5d+ territory.
- **Pathways for bus stops** — vanishingly few agencies publish, would
  be empty in practice.
- **Hearing / vision / cognitive disability tables** (B18102, B18103,
  B18104). B18105 (ambulatory) is the most causally aligned with
  wheelchair_boarding for capital prioritization.
- **Historic accessibility trend** — "did this stop improve year-over-
  year?" requires snapshotting `stop_ada_gap` over time. Belongs in
  BLUEPRINT's separate "Historic Equity Trend" sprint.
- **Pathways elevator realtime status** — 511.org has no feed; would
  need agency-specific scraping (e.g., BART's elevator-status feed).
- **Composite Service Equity Score** — combining 5a fare burden + 5b
  service gap + 5c ADA gap into one per-cell number. Reserved for
  Sprint 5d.

---

## Open questions deferred to Sprint 5d / later

- Whether to weight `gap_score` by `equity_score` (income-weighted
  ADA gap) as a secondary sort column. Could ship as
  `equity_adjusted_ada_gap` on the GeoJSON properties if a planner
  asks for it.
- Whether to include stops without any routes (orphans in
  `gtfs_stops` not in `gtfs_stop_times`). Default: exclude — they're
  typically deprecated stops; revisit if the count is meaningful.
- Tract-level (not catchment-level) cuts of the ADA gap for grant-
  application reporting.  Note: by loading `census_tracts` in this
  sprint, Sprint 5a's deferred tract-level fare-burden refinement is
  now structurally unblocked — Sprint 5d can pick it up directly.

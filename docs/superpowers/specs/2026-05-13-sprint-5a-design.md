# Sprint 5a — Fare Burden Mapper

**Date:** 2026-05-13
**Sprint:** 5a (first slice of `BLUEPRINT.md` Sprint 5 — Equity & Accessibility)
**Status:** design approved; implementation pending

## Scope decision

`BLUEPRINT.md` Sprint 5 bundles five features:

1. Service Delivery Gap Map (needs `stop_observations`)
2. Fare Burden Mapper (**unblocked today**)
3. ADA Accessibility Gap Tracker (needs GTFS Pathways)
4. Service Equity Score (composite of the others)
5. Historic Equity Trend (needs `stop_observations` monthly archive)

Sprint 5 split into four phases by data dependency:

| | Sprint 5a (this doc) | Sprint 5b | Sprint 5c | Sprint 5d |
|---|---|---|---|---|
| **Feature** | Fare Burden Mapper | Service Delivery Gap | ADA Accessibility Gap | Service Equity Score composite |
| **Data needed** | 4b fares + ACS B19013 | `stop_observations` (historic 511.org archive) | GTFS Pathways + Census B18101 | All of the above |
| **Status** | ready | needs new ingestor | needs new ingestor + new ACS variable | depends on a–c |

Sprint 5a ships the unblocked feature now; 5b/5c/5d each get their own
brainstorm + spec when reached. Pattern matches Sprint 4's split-and-defer
that worked.

## What Sprint 5a delivers

**Persona:** city/municipal planner, MPO planner (Planning section).

**Product question:** "Which census tracts pay the highest transit fare
as a share of household income? Where does fare burden hit hardest?"

Two deliverables:

1. **Backend**: extend the ACS loader to pull `B19013` (median household
   income), new `fare_burden` table populated nightly with per-cell
   median fare to 3 anchor destinations, `GET /equity/fare-burden`
   endpoint.
2. **Frontend**: new **Planning → Fare Burden** sub-page — choropleth
   map coloured by burden % + top-10 high-burden cells list with CSV
   export.

Estimate: **2 weeks** (1 week backend + ETL, 1 week frontend + smoke).

---

## Feature 1 — Backend: fare burden compute

### Data prerequisites

**ACS variable B19013** (Median Household Income, past 12 months) is one
line added to the existing equity loader's `_VARIABLES` list and one
line of aggregation in `_aggregate_county`. The loader's per-county
aggregation is preserved (cells inside a county all share the
county-level median income — a documented v1 approximation; refining
to per-tract requires ingesting TIGER tract shapefiles and is deferred).

Schema:

```sql
ALTER TABLE coverage_cells
    ADD COLUMN IF NOT EXISTS median_household_income integer;
```

### Anchor destinations

Three pre-defined Bay Area job centres. Coordinates picked from the
nearest BART station so they're real reachable points and won't drift:

```python
_ANCHORS = [
    # Coordinates pinned to the actual BART/Muni station entrances so the
    # sampler's nearest-stops scan reliably finds the anchor agency at
    # each point. Verify these against gtfs_stops on implementation —
    # picking a real stop_id outright is also acceptable.
    {"id": "sf",      "name": "Downtown SF",      "lat": 37.7929, "lng": -122.3970},  # Embarcadero BART
    {"id": "oakland", "name": "Downtown Oakland", "lat": 37.8038, "lng": -122.2715},  # 12th St / Oakland City Center
    {"id": "sfo",     "name": "SFO Airport",      "lat": 37.6157, "lng": -122.3925},  # SFO BART
]
```

Anchors stay in code (not a table) — they change at the speed of
"what's a Bay Area job centre", which is years. A future refinement
could move them to config so MPO users can add their own.

### Storage: hybrid precompute + query-time composition

A `fare_burden` table caches the **expensive part** (per-cell median
fare to each anchor) but **not** the burden percentage (which needs
income, which the table also stores, but might be reweighted at query
time). This lets the UI tune anchor weights without re-running the
heavy compute.

```sql
CREATE TABLE IF NOT EXISTS fare_burden (
    cell_id                    text PRIMARY KEY REFERENCES coverage_cells(cell_id),
    median_fare_to_sf          numeric(8,2),   -- NULL if cell has no
    median_fare_to_oakland     numeric(8,2),   --   single-agency path
    median_fare_to_sfo         numeric(8,2),
    reachable_anchor_count     integer NOT NULL DEFAULT 0,
    population                 integer,
    median_household_income    integer,
    computed_at                timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fare_burden_reachable
    ON fare_burden (reachable_anchor_count)
    WHERE reachable_anchor_count > 0;
```

The endpoint computes `worst_fare = MAX(non-null anchor fares)` and
`burden_pct` from income at query time (cheap arithmetic). UI can
override anchor weighting via a query param.

### Compute job

`backend/app/services/fare_burden.py`:

```python
def compute_fare_burden_for_all_cells(conn, anchors=_ANCHORS, n_per_cell=10) -> int:
    """For each cell, for each anchor, sample n_per_cell OD stop pairs from
    cell-neighbourhood → anchor-stop, compute median fare via
    fare_calculator.  UPSERT into fare_burden.  Cells that can't reach
    an anchor on a single-agency network get NULL for that anchor; if
    no anchor is reachable, reachable_anchor_count=0 and the UI marks
    the cell hatched."""
```

Algorithm details:
1. For each `coverage_cells` row, take the cell centroid as the click
   point.
2. Find nearest 30 stops (≤1500 m) per the Sprint 4b sampler's
   `_nearest_stops`. Same agency-intersection logic — if no agency
   serves both the cell-neighbourhood and the anchor-neighbourhood,
   that anchor fare is NULL.
3. For each (cell, anchor) pair, sample up to 10 OD stop pairs and
   compute the median fare via `calculate_fare`.
4. UPSERT into `fare_burden`.

Performance estimate: 2,350 cells × 3 anchors × 10 samples = 70,500
fare lookups. At ~3 ms each (post-Sprint-4b zone-translation fix),
~3.5 minutes total. Runs nightly via `run_data_jobs.py`.

Wired into `run_data_jobs.py` as a new step appended after the
existing 13/13 stop_observations step. All existing step labels bump
from `/13` to `/14`; the new step is `14/14 Computing fare burden by
cell...`. Pattern matches how Sprint 4a Phase 1 (transfer reliability)
was wired in.

```python
print("14/14 Computing fare burden by cell...")
try:
    from app.services.fare_burden import compute_fare_burden_for_all_cells
    with engine.begin() as conn:
        n = compute_fare_burden_for_all_cells(conn)
    print(f"     Wrote {n} fare_burden rows.")
except Exception as e:
    print(f"     fare_burden failed (skipping): {e}")
```

### API

```
GET /equity/fare-burden
  ?anchor_weights=sf:1,oakland:1,sfo:0.5   # optional; default all 1.0
  ?min_population=100                       # optional
  ?limit=2000                               # optional, default 2000
  → GeoJSON FeatureCollection of coverage_cells with properties:
    {
      "cell_id":                "...",
      "geometry":               { Polygon },
      "median_household_income": 84500,
      "median_fare_to_sf":       4.55,
      "median_fare_to_oakland":  2.75,
      "median_fare_to_sfo":      7.20,
      "worst_fare":              7.20,
      "burden_pct":              2.6,
      "burden_tier":             "moderate",       // very_high / high / moderate / low
      "reachable_anchor_count":  3
    }
```

`burden_pct` definition:

```
monthly_transit_cost = worst_fare * 2 (round trip) * 22 (workdays)
                     = worst_fare * 44
monthly_income       = median_household_income / 12
burden_pct           = 100 * monthly_transit_cost / monthly_income
```

This is the "monthly commute cost as % of monthly income" framing
planners quote. The 22 workdays × 2 trips assumption is the standard
v1 calculation; a future refinement could expose work-from-home %.

`burden_tier` — policy thresholds, not physics:

| Tier | Boundary |
|---|---|
| `very_high` | burden_pct ≥ 15 |
| `high` | 10 ≤ burden_pct < 15 |
| `moderate` | 5 ≤ burden_pct < 10 |
| `low` | burden_pct < 5 |

The 15%/10% boundaries are common in transit-equity literature (HUD's
"housing-+-transportation index" flags combined H+T burden ≥45%) but
are not a single federal definition. Treat as tunable.

### Edge cases

- **Cells with `reachable_anchor_count = 0`**: returned in the
  FeatureCollection with `burden_pct = null` so the UI can render them
  hatched. They're excluded from the "top 10 burden" list in the UI.
- **Cells with `median_household_income = null`**: same — `burden_pct
  = null`. Loader marks these so the UI can distinguish "unreachable"
  from "no income data" in the tooltip.
- **Cells where the worst-anchor fare is 0**: probably a sampler edge
  case (sample fell entirely into agency_default → cheapest product).
  Documented; surfaces in the UI as `burden_tier = low`.

---

## Feature 2 — Frontend: Planning → Fare Burden sub-page

### Layout

```
┌─ Planning → Fare Burden ─────────────────────────────────────────────┐
│ Sub-nav: [Diagnostics] [Coverage] [Regional] [Workbench] [Scenarios] │
│          [Fares] [Fare Burden ← active]                              │
│                                                                       │
│ KPI strip:                                                            │
│   Cells   Reachable   Median burden   High-burden cells   Worst       │
│   2350    1972        4.8%            187 (≥10%)           18.3%      │
│                                                                       │
│ ┌─────────────────────────────┐  ┌────────────────────────────────┐  │
│ │ Map (choropleth)            │  │ Top 10 high-burden cells       │  │
│ │  Cells colour-scaled by     │  │  cell_id  income  fare  burden │  │
│ │  burden_tier:               │  │  C-x      $42k    $7.20 16.8%  │  │
│ │   red    = very_high ≥15%   │  │  C-y      $48k    $6.80 13.8%  │  │
│ │   orange = high 10–15%      │  │  ...                            │  │
│ │   yellow = moderate 5–10%   │  │  [Export CSV]                   │  │
│ │   green  = low <5%          │  └────────────────────────────────┘  │
│ │   hatched = unreachable     │                                       │
│ └─────────────────────────────┘                                       │
└──────────────────────────────────────────────────────────────────────┘
```

### Map layer

Adds a new `fare-burden-fill` polygon layer to MapView, fed from a new
`fare-burden-cells` source. The colour-scale is a `match` expression on
`burden_tier`:

```js
"fill-color": [
  "match", ["coalesce", ["get", "burden_tier"], "none"],
  "very_high", "#dc2626",
  "high",      "#f97316",
  "moderate",  "#facc15",
  "low",       "#22c55e",
  /* else */   "transparent"
]
```

Hatched cells use a second pattern layer with `fill-pattern` over cells
where `reachable_anchor_count = 0`.

A new `mapMode === "fare-burden"` activates the layers + Section type.

### Component files

- `frontend/src/sections/planning/FareBurden.tsx` — new sub-page
  (mirrors Coverage.tsx shape).
- `frontend/src/sections/planning/FareBurden.test.tsx` — render +
  list + CSV export tests.
- `frontend/src/sections/Planning.tsx` — add `"fare-burden"` to the
  SubKey union + sub-nav strip + route switch.
- `frontend/src/types.ts` — add `"fare-burden"` to Section union.
- `frontend/src/components/MapView.tsx` — `fare-burden` layer + source
  + `fares mode` data fetch case.

### Anchor visualisation

The map shows the 3 anchor destinations as labelled markers
(diamond-shaped to distinguish from stop pins). Hovering a cell shows
its per-anchor fare in the tooltip.

### List panel

Top 10 cells by `burden_pct`. Each row:

```
cell_id           income   worst fare   burden    pair (worst anchor)
─────────────────────────────────────────────────────────────────
−122.37_37.68     $42k     $7.20        16.8%     → SFO
−122.42_37.71     $44k     $6.55        14.5%     → SF
...
```

CSV export with the full feature set so planners can pull into Sheets.

---

## Phasing

```
Week 1 — Backend (5 days)
  Day 1   ACS loader: add B19013 + median_household_income column
  Day 2   Migration 006_fare_burden + fare_burden service module
  Day 3   compute_fare_burden_for_all_cells + tests
  Day 4   GET /equity/fare-burden endpoint + tests + run_data_jobs wiring
  Day 5   Live smoke against real coverage_cells; perf tuning if needed

Week 2 — Frontend (5 days)
  Day 1   Section + sub-nav extension; SelectionContext untouched
  Day 2   MapView fare-burden layer + source + paint expression
  Day 3-4 FareBurden.tsx layout + list panel + CSV export
  Day 5   Tests + accessibility pass + smoke

Half-week — Integration + acceptance script
  scripts/sprint-5a-acceptance.py mirroring Sprint 4b's pattern.
```

## Risks

1. **Compute time**: 70,500 fare lookups at ~3 ms is ~3.5 minutes. If
   the live DB is slower (3.9M ops_trip_events rows competing for
   shared buffers), it could be 5–10 minutes. Mitigation: build the
   compute job as **idempotent per cell** so a partial run can resume,
   and let it run as a `pg_cron` job at 03:00 UTC.
2. **Sparse single-agency reachability**: many East Bay cells will hit
   `reachable_anchor_count = 0` because BART doesn't serve them and
   Marin Transit doesn't reach SF directly. The map will show a lot of
   hatched cells. That's honest about the data; documented in the UI
   empty-state copy and tooltip.
3. **Income approximation**: county-level B19013 means a Berkeley cell
   and a San Pablo cell share Alameda County's median income.
   Documented v1 caveat; the refinement to tract-level is deferred to
   when it actually matters for a planner.
4. **Federal poverty-line vs. county median**: the blueprint says "as
   % of household income" — county median is one defensible income
   denominator; some equity researchers use the federal poverty line
   instead. We use county median because the data shape supports it;
   a `?denominator=` query param could be added later if needed.
5. **Anchor selection bias**: the 3 anchors are tech-employment biased
   (Downtown SF, SFO). A planner studying healthcare-employment
   patterns might want UCSF, Stanford, etc. The blueprint doesn't
   commit to a specific anchor set — surfacing this as code, not
   config, is honest about the v1 choice.

## What we are not building this sprint

- Multi-agency leg composition for unreachable cells (Sprint 5b might
  pick it up once stop_observations data lets us model the journey
  more accurately).
- Tract-level median income (per-tract spatial join with TIGER
  shapefiles; deferred).
- User-tunable anchor sets (config table for anchors; deferred).
- Service Delivery Gap, ADA Tracker, Equity Score composite (Sprint
  5b/5c/5d).

## Verification (end of Sprint 5a)

1. `ALTER TABLE coverage_cells ADD COLUMN median_household_income` ran
   and ACS loader populates it.
2. `fare_burden` table has ≥ 2,000 rows after nightly compute.
3. `GET /equity/fare-burden` returns a non-empty FeatureCollection.
4. At least 50 cells have `burden_tier == "high"` or `"very_high"`.
5. At least 100 cells have `reachable_anchor_count == 0` (the
   expected sparse-network reality of the East Bay).
6. Planning → Fare Burden renders the choropleth + the top-10 list,
   with the 3 anchor markers visible.
7. CSV export downloads a file with all the per-cell fields.
8. `scripts/sprint-5a-acceptance.py` returns 0 (all live checks pass).
9. Backend ≥ 111 + ~8 new (~119). Frontend ≥ 94 + ~4 new (~98).

## Open questions deferred to Sprint 5b / later

- Should `fare_burden` rerun computation when only `fare_products`
  changes (BART fare table update) or also on Fares v2 schema changes?
  v1: full re-run nightly; revisit if perf becomes an issue.
- Multi-agency burden (compose via `transfer_reliability`): defer to
  Sprint 5b's brainstorm once we see how many cells in 5a end up
  hatched.

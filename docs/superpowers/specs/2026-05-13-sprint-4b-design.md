# Sprint 4b — Fare Calculator + Corridor Fares page

**Date:** 2026-05-13
**Sprint:** 4b (continuation of `BLUEPRINT.md` Sprint 4)
**Status:** design approved; implementation pending

## Scope decision

The blueprint's Sprint 4 originally bundled four features. Sprint 4a
shipped three (Transfer Reliability, Fares ingestor, Transfer Desert Map).
The remaining feature pair — Multi-Agency Fare Calculator + Multi-Modal
Trip Planner — got split:

| | Sprint 4b | Sprint 4c (deferred) |
|---|---|---|
| **POST /fares/calculate** | ✅ ships | uses it |
| **Planning → Fares sub-page** | ✅ ships | unaffected |
| **Multi-modal trip planner** | ❌ deferred | own brainstorm |
| **OTP sidecar vs own router** | irrelevant | open question |
| **GTFS Pathways ingest** | not needed | likely needed |
| **SIRI Stop Monitoring** | not needed | likely needed |

The split is pragmatic: a fare calculator and a corridor-analysis surface
deliver immediate planner value using Sprint 4a's already-loaded data,
**without** committing to the routing engine question. When/if we later
decide to ship a real multi-modal trip planner, it calls the same
`/fares/calculate` primitive — no rework.

## What's "Sprint 4b proper"

Two deliverables:

1. **Backend**: `POST /fares/calculate` — given a list of legs, return the
   total fare and per-leg breakdown. Resolves fare products from the
   already-ingested `fare_products` + `fare_leg_rules` tables (Sprint 4a
   Phase 2 loaded AC's 5 products + BART's 2,500 OD-pair products).
2. **Frontend**: a new **Planning → Fares** sub-page that uses
   `/fares/calculate` to evaluate corridor-level fare burden, with an
   equity overlay so MPO and city planners can see which high-need cells
   pay more.

3 sequential weeks total — 1 week backend, 1 week frontend, 0.5 week
polish + smoke.

---

## Feature 1: POST /fares/calculate

**Persona:** any caller — rider clients, planner UI, future trip planner.

### API contract

```
POST /fares/calculate
{
  "legs": [
    {
      "agency_id":           "AC",        required
      "route_id":            "1T",        optional; required for route-keyed agencies (AC)
      "origin_stop_id":      "512",       optional; required for OD-keyed agencies (BART)
      "destination_stop_id": "541"        optional
    },
    {
      "agency_id":           "BA",
      "route_id":            null,
      "origin_stop_id":      "MCAR",
      "destination_stop_id": "EMBR"
    }
  ]
}
→ 200 OK
{
  "total":    6.45,
  "currency": "USD",
  "legs": [
    {
      "agency_id":       "AC",
      "fare_product_id": "ac-adult",
      "fare":            2.50,
      "matched_by":      "route_id"
    },
    {
      "agency_id":       "BA",
      "fare_product_id": "BA-MCAR-EMBR",
      "fare":            3.95,
      "matched_by":      "origin+destination"
    }
  ]
}
```

### Resolution algorithm

For each leg, walk a priority list of lookups against `fare_leg_rules`:

```
1. (agency_id, network_id=route_id, from_area_id=origin_stop_id,
    to_area_id=destination_stop_id)                  — most specific
2. (agency_id, network_id=route_id)                  — route-only
3. (agency_id, from_area_id=origin_stop_id,
    to_area_id=destination_stop_id)                  — OD-only
4. (agency_id, network_id=route_id, from_area_id IS NULL,
    to_area_id IS NULL)                              — route + no area
5. First fare_product_id for the agency (default)    — fallback
6. NULL                                              — no fare data
```

The `matched_by` field surfaces which step in the priority list
succeeded so planners can audit unexpected fares.

### Edge cases

- Leg with `agency_id` not in `fare_products` → returns `fare: null` for
  that leg, includes it in the `total` as 0, surfaces `matched_by:
  "no_data"` so the UI can mark it.
- Leg with no `route_id` and no `origin_stop_id`/`destination_stop_id`
  → falls through to step 5 (agency default).
- Empty `legs` array → returns `total: 0`, empty `legs: []`.

### Multi-leg transfers

Sprint 4a Phase 2's loader deliberately did not synthesise v1 transfer
discounts into `fare_transfer_rules` (the v2 transfer model is
structurally different from v1's per-fare-product `transfers` count;
conflating them would mislead). The calculator **does not apply transfer
discounts in v1 mode** — the sum-of-legs is correct for current Bay Area
fare structures, where transfer credits live at the Clipper/rider-pass
level, not the fare-rule level.

When (if) a Bay Area agency ships true Fares v2 with `fare_transfer_rules`
populated, the calculator extends to look up matching transfer rules
between consecutive legs. Resolution priority for transfer rules:

```
1. Exact (from_leg_group_id, to_leg_group_id, transfer_count, duration_limit)
2. (from_leg_group_id, to_leg_group_id)
3. NULL → no discount, sum-of-legs applies
```

### Service module

`backend/app/services/fare_calculator.py`:

- `calculate_fare(conn, legs: list[Leg]) -> FareResult`
- `_resolve_product(conn, leg: Leg) -> tuple[product_id, fare, matched_by] | None`
- `_apply_transfer_rules(conn, products: list, agency_ids: list) -> Decimal`
  (a no-op stub for v1; returns 0 discount today, lifts to real logic
  when v2 data arrives)

### Endpoint registration

```python
@app.post("/fares/calculate", dependencies=[Depends(api_key_dependency)])
def fares_calculate(payload: FareRequest, conn=Depends(get_conn)):
    return calculate_fare(conn, payload.legs)
```

Place it next to the existing `GET /fares/products` debug endpoint in
`backend/app/main.py`.

---

## Feature 2: Planning → Fares sub-page

**Persona:** MPO / regional planner, city/municipal planner.

**Product question:** "What's the typical fare burden for trips across
this corridor, and does it fall harder on high-equity-need cells?"

### Layout

```
┌─ Planning → Fares ───────────────────────────────────────────────────┐
│ Sub-nav: [Diagnostics] [Coverage] [Regional] [Workbench] [Scenarios] │
│          [Fares ← active]                                             │
│                                                                       │
│ KPI strip:                                                            │
│   Pairs sampled   Median fare   p25 / p75   Max     Agencies         │
│   30              $4.75         $2.50/$6.20  $9.40   AC, BA           │
│                                                                       │
│ ┌─────────────────────────────┐  ┌────────────────────────────────┐  │
│ │ Map (corridor selector)     │  │ Fare distribution              │  │
│ │  • Click origin region pin  │  │  (histogram from sampled pairs)│  │
│ │  • Click destination pin    │  │                                │  │
│ │  • 30 stop-pairs sampled    │  │ Median fare by equity tier     │  │
│ │    between the two clicks   │  │  (bar chart, 4 tiers)          │  │
│ └─────────────────────────────┘  └────────────────────────────────┘  │
│                                                                       │
│ Panel: Top 10 high-burden cells                                       │
│  Cells with the worst (equity_score × median fare) — the ones where   │
│  high-need residents would pay the most for this corridor.            │
│  CSV export.                                                          │
└──────────────────────────────────────────────────────────────────────┘
```

### Corridor selection — map-click model

Same affordance as Planning → Workbench. Two new selection fields on
`SelectionContext`:

```ts
faresOrigin:      LatLng | null;
faresDestination: LatLng | null;
```

(Or repurpose existing `workbenchPoint` via context-namespacing — TBD in
implementation; cleaner to add new fields than overload one.)

The MapView click handler when `mapMode === "fares"`:
- Click 1: sets `faresOrigin`.
- Click 2: sets `faresDestination`.
- Click 3: replaces origin (cycle).

When both are set, the page samples 30 stop pairs between them and runs
the calculator.

### Sampling algorithm

```python
def sample_od_pairs(conn, origin: LatLng, dest: LatLng, n: int = 30) -> list:
    """Pick n random (origin_stop_id, destination_stop_id, agency_id, route_id)
    tuples in the corridor between the two clicks.

    Method:
    1. Find the ~50 stops nearest each click point (haversine-ranked).
    2. Build the cartesian product of (origin stop × destination stop).
    3. Filter: same agency must serve both (so the pair is plausibly
       reachable on one agency's network), OR the trip is multi-agency
       and we know a transfer point between them.
    4. For multi-agency, the leg list is constructed by picking a
       reasonable transfer point from transfer_reliability.
    5. Sample n pairs uniformly at random.
    """
```

This is the riskiest piece. v1 simplifies it:
- Sample 30 single-agency pairs (no transfers).
- If the user clicks regions served by different single agencies, surface
  a "no direct connection" notice.
- Multi-agency multi-leg sampling defers to v2 once we know if it's used.

### Equity overlay

For each sampled pair, look up the equity_score of the origin
coverage_cell. Compute `equity_burden = median_fare × equity_score`.
Rank cells by this score, show top 10 as the "high-burden cells" list.

### Frontend files

- `frontend/src/sections/planning/Fares.tsx` — new sub-page (mirrors
  shape of Coverage.tsx).
- `frontend/src/sections/planning/Fares.test.tsx` — render + click-
  through + KPI math.
- `frontend/src/sections/Planning.tsx` — add `"fares"` to the SubKey
  union + sub-nav strip + route switch.
- `frontend/src/context/SelectionContext.tsx` — new `faresOrigin` +
  `faresDestination` fields (or shared `workbenchPoint` reuse — pick
  during implementation).
- `frontend/src/components/MapView.tsx` — `mapMode === "fares"` click
  handler + two-point pin source/layers + cursor crosshair.

### Backend support endpoint

The frontend needs a way to ask "given two map clicks, sample 30 OD
pairs and tell me what the fare distribution is". Two options:

(a) **One round-trip**: `POST /fares/sample-corridor` — server does
sampling + calls calculate_fare internally + returns summary stats. UI
just renders.

(b) **Two round-trips**: frontend calls `GET /stops/nearby?lat=&lng=`
for each click, builds OD pairs client-side, hits `POST /fares/calculate`
30 times (or once with a batch). More chatty; more flexible.

Recommendation: **(a)**. Less network, server controls the sampling logic
(makes it easier to evolve), and the UI is simpler. The cost is one new
endpoint (`POST /fares/sample-corridor`).

```
POST /fares/sample-corridor
{ "origin": { "lat": 37.8, "lng": -122.27 },
  "destination": { "lat": 37.78, "lng": -122.42 },
  "n": 30 }
→ {
    "n_sampled":           30,
    "median_fare":         4.75,
    "p25_fare":            2.50,
    "p75_fare":            6.20,
    "max_fare":            9.40,
    "agencies":            ["AC", "BA"],
    "by_equity_tier": {
       "very_high": { "n": 8, "median_fare": 5.00 },
       "high":      { "n": 12, "median_fare": 4.50 },
       "medium":    { "n": 7, "median_fare": 4.25 },
       "low":       { "n": 3, "median_fare": 3.95 }
    },
    "high_burden_cells": [
      { "cell_id": "...", "equity_score": 0.31, "median_fare": 6.40, "burden": 1.98 },
      ...
    ]
  }
```

---

## Phasing

```
Week 1 — Backend: calculator + sampler
  Day 1-2: services/fare_calculator.py + tests
  Day 3:   POST /fares/calculate endpoint + endpoint tests
  Day 4-5: services/fare_sampler.py (sample_od_pairs + corridor
           summary) + POST /fares/sample-corridor + tests

Week 2 — Frontend: Planning → Fares sub-page
  Day 1:   Sub-nav extension; SelectionContext faresOrigin/Destination;
           MapView click handler for mapMode="fares"
  Day 2-3: Fares.tsx layout: KPI strip, corridor map, fare-distribution
           chart, equity-tier bar chart
  Day 4:   "High-burden cells" panel + CSV export
  Day 5:   Tests + accessibility pass

Half-week — Integration + smoke
  Live smoke against AC + BART corridors (Berkeley → Downtown SF,
  Oakland → SFO). Verify fare distribution matches Clipper-app
  expectations.
```

## Open questions deferred to Sprint 4c

- **Multi-modal trip planner** — own router (time-expanded Dijkstra on
  the federated GTFS graph) vs. OpenTripPlanner sidecar. Either choice
  depends on whether we still want a rider-facing planner once we see
  how the planner-facing Fares page lands.
- **GTFS Pathways ingest** — only needed if we build the trip planner
  and want in-station walk geometry (Embarcadero BART ↔ Embarcadero
  Muni transfer corridors).
- **SIRI Stop Monitoring real-time ETAs** — only needed for a rider
  trip planner that wants live arrival times. The dashboard's
  `/vehicles/live` is per-agency, not per-stop.

## Risks

1. **AC and BART have different fare structures** (flat vs OD-based).
   Median fare comparisons across agencies in the same corridor will be
   misleading (e.g. a Berkeley → SF corridor mixes AC's $2.50 flat with
   BART's distance-priced $4–6). Mitigation: surface fare distribution
   **per agency** in addition to overall, so planners see the right
   shape. Add this to the "Fare distribution" chart as faceted bars or
   layered histogram.
2. **No fare_areas data loaded** (AC and BART don't ship
   `farezone_attributes.txt`). The route + OD lookup falls back to
   `fare_leg_rules.network_id` (route_id) and `from_area_id`/
   `to_area_id` columns that hold stop_ids in v1. Documented in the
   loader; the calculator handles it via the priority list above.
3. **BART's 2,500 fare products** are essentially every OD pair as its
   own product_id. The lookup will hit step 3 in the priority list
   (OD-only). That's fine; the cost is one row read per leg.
4. **Multi-agency corridor sampling is hard.** Berkeley → SF must
   compose AC + BART legs via a transfer point. v1 of the sampler
   handles single-agency corridors only and shows a clear "multi-agency
   corridor — single-agency fares shown" notice; v2 picks a transfer
   point from `transfer_reliability` and builds the leg list.
5. **Equity overlay needs origin coverage_cells.** A click that lands
   outside any populated coverage_cell can't be tied to an equity tier.
   Mitigation: the sampler maps each sampled origin stop to its
   nearest coverage_cell within 400 m; pairs without one are excluded
   from the equity-tier breakdown but still counted in overall medians.

## What we are not building this sprint

- Multi-modal trip routing (Sprint 4c brainstorm).
- Fare calculation for rider clients (out of scope; planner-facing).
- Real-time live ETAs alongside fare (Sprint 4c).
- Pathways geometry for in-station transfers (Sprint 4c).
- Multi-leg corridor sampling with transfers (v2; v1 single-agency only).

---

## Verification (end of Sprint 4b)

1. `POST /fares/calculate` with a single AC leg → `total = 2.50`.
2. `POST /fares/calculate` with a BART OD leg → `total > 0` and
   `fare_product_id` is the matching BART OD product.
3. `POST /fares/calculate` with two legs (AC + BART) → `total =
   ac_fare + ba_fare` (no transfer discount in v1).
4. `POST /fares/sample-corridor` with Berkeley → Downtown SF returns
   `n_sampled ≥ 20`, `median_fare` between $2 and $10.
5. Planning → Fares renders, accepts two map clicks, shows
   fare-distribution histogram + median-by-equity-tier chart.
6. "Top 10 high-burden cells" panel populated with at least 1 row.
7. Backend ≥ 95 + 12 new (107). Frontend ≥ 88 + 6 new (94).

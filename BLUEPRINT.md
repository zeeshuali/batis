# BATIS — Product Blueprint
_Last updated: 2026-05-09_

This document defines the full vision for BATIS: what it is, who it's for, what it does, and how it's differentiated from every competing product. This is the north star — consult it before designing any new feature.

---

## The Product Vision

**BATIS** (Bay Area Transit Intelligence System) is the first **regional, multi-agency transit intelligence platform** for the San Francisco Bay Area — built entirely on public data from the 511.org open data API.

It is an **operator-facing analytics and planning tool**, not a rider app. Its audience is transit agency staff, city planners, MTC/regional body analysts, and equity researchers who need to understand transit performance, coverage, and equity at the regional level — not just within a single agency.

**The core insight**: No existing commercial product (Swiftly, Remix, Optibus, etc.) does cross-agency analysis. Each serves a single agency's operations. BATIS spans the entire Bay Area network with a single view.

---

## Who It's For (User Segments)

| Segment | Role | What They Need | How BATIS Serves Them |
|---------|------|----------------|----------------------|
| **Transit Operators** | AC Transit, BART, Muni planners and dispatchers | Real-time fleet status, delay patterns, bunching alerts | Live map (all agencies), reliability dashboard, bunching analysis |
| **Regional Planners** | MTC, ABAG staff | Cross-agency service coverage, equity, transfer connections | Agency benchmarking, service equity audit, transfer reliability matrix |
| **City Planners** | Oakland, SF, San Jose transportation staff | How transit serves their city, first/last mile gaps, work zone impact | Coverage analysis, accessibility gap tracker, traffic-transit correlation |
| **Equity Researchers** | Non-profits, academics, policy staff | Actual service delivery vs. scheduled; fare burden; ADA gaps | Service delivery gap map, fare burden mapper, ADA accessibility tracker |
| **Operational Analysts** | Agency performance teams | Historical OTP trends, schedule drift, NTD reporting prep | Stop observations analytics, schedule drift detection, cross-agency benchmarking |

---

## The Three Competitive Advantages

### 1. Regional Coverage (30+ Agencies in One View)
Every competitor tool is single-agency. BATIS ingests the 511.org regional consolidated feed and shows BART, Muni, AC Transit, Caltrain, VTA, Golden Gate, WETA, and 20+ more agencies simultaneously. A planner can see a BART delay and immediately see which downstream bus connections it affects — across agency boundaries.

### 2. Actual Historical Performance Data (Not Just Real-Time)
The 511.org Stop Observations archive (`stop_observations.txt`, monthly, March 2022–present) provides actual vs. scheduled arrival times for every stop on every agency in the Bay Area. This is 3+ years of ground-truth performance data that no competitor currently aggregates or analyzes. BATIS turns this into actionable analytics: schedule drift detection, transfer reliability scoring, equity-adjusted service audits.

### 3. Cross-Modal Intelligence (Traffic + Tolls + Transit)
511.org also provides the Bay Area's road incident feed, work zone data (WZDx), and dynamic toll rates. BATIS is the only platform that crosses these feeds with transit data to answer questions like: "When the Bay Bridge toll spikes to $10, does ridership on Transbay routes increase? Do those routes then become overcrowded?" These correlations are a genuinely unique Bay Area capability.

---

## Product Map: All Features

### 🔵 Core — Already Implemented (fix bugs, then build on)

| Feature | Description | Data Source | Status |
|---------|-------------|-------------|--------|
| Transit Reliability Dashboard | Per-route OTP, avg delay, worst routes, trend chart | `ops_trip_events` (AC Transit only) | ⚠️ Partial |
| Crowding Predictions | Stop-level crowding level by route + time | Synthetic demand proxy | ⚠️ Partial (proxy data) |
| Stop Safety Scores | Crime + collision proximity scoring per stop | Oakland open data | 🔴 Broken (geometry bug) |
| Transit Coverage Grid | Hex grid showing service frequency + transit deserts | GTFS static | ✅ Works |
| Demand Forecast | Boarding estimates by route/stop/time | Synthetic proxy | ⚠️ Partial (proxy data) |
| Route Explorer | All routes searchable, map shape + stops, headway chart | GTFS static | ✅ Works |
| Bunching Analysis | Headway irregularity ranking by route | `ops_trip_events` | ⚠️ Map wrong |
| Live Vehicles | Real-time vehicle positions map (30s poll) | AC Transit GTFS-RT | ⚠️ Single agency |
| Route Comparison | Side-by-side KPI table for up to 5 routes | `ops_trip_events` | 🔴 Broken (routing bug) |
| Trip Planner | Click-to-plan point-to-point journey with delay overlay | GTFS static + ops | ⚠️ No transfers |
| AI Assistant | RAG-powered Q&A about AC Transit | pgvector + Ollama | ⚠️ Needs Ollama setup |
| Service Alerts Banner | Live GTFS-RT alerts from AC Transit | AC Transit GTFS-RT | ⚠️ Single agency |
| Stop Detail Drawer | Stop info, safety, delay history, departures, incidents | Multiple tables | ⚠️ No live ETAs |

---

### 🟢 Sprint 1 — 511.org Integration (Multi-Agency Foundation)

| Feature | Description | Data Source | Differentiation |
|---------|-------------|-------------|-----------------|
| **Multi-Agency Live Map** | BART, Muni, AC Transit, VTA, Caltrain, Ferries all on one map simultaneously | 511.org GTFS-RT `agency=RG` | Only platform with all Bay Area agencies in one view |
| **Live Stop ETAs** | Real-time arrival predictions per stop via 511.org SIRI Stop Monitoring | 511.org `/StopMonitoring` | Replaces scheduled-time estimate with actual live ETA |
| **Multi-Agency Service Alerts** | Alerts from all Bay Area agencies in a single banner | 511.org GTFS-RT alerts | Aggregated view no app currently provides |
| **Multi-Agency Route Explorer** | Routes and stops from every agency, searchable by agency | 511.org GTFS static per agency | Regional scope |

---

### 🟡 Sprint 2 — Stop Observations (Historical Intelligence)

| Feature | Description | Data Source | Differentiation |
|---------|-------------|-------------|-----------------|
| **Cross-Agency OTP Benchmarking** | Monthly scorecards comparing all 30+ agencies by on-time %, avg delay, headway regularity | 511.org `stop_observations.txt` (monthly archive) | No existing platform benchmarks agencies against each other using actual observed arrival data |
| **Schedule Drift Detection** | Automatically flag routes/segments where actual run times have drifted >15% from scheduled | 511.org stop_observations | Proactive scheduling input; competes with Swiftly's run-time analysis but regional |
| **Historical Performance Explorer** | Filter any route's actual performance by month/day-of-week/hour over 3 years | 511.org stop_observations | 3-year retrospective at stop-level granularity for entire Bay Area |
| **Transfer Success Rate** | For any agency-to-agency transfer point: probability the connection is actually made | stop_observations + GTFS Fares v2 | Cross-agency, grounded in actual observed data |

---

### 🟠 Sprint 3 — Traffic, Tolls & Work Zones

| Feature | Description | Data Source | Differentiation |
|---------|-------------|-------------|-----------------|
| **Work Zone Transit Impact Predictor** | When a road closure is active, predict which bus routes will be delayed and by how much | 511.org WZDx + traffic events + stop_observations | 20–40 min early warning to dispatchers; Swiftly doesn't do this |
| **Traffic-Transit Delay Correlation** | Quantify how much of any day's transit delay is attributable to road incidents | 511.org traffic events + trip updates | Real operational insight for reporting to boards/councils |
| **Toll-Transit Ridership Correlation** | Track whether Bay Bridge/Express Lane price spikes increase transit ridership on parallel corridors | 511.org toll rates + stop_observations | Uniquely Bay Area; useful for MTC demand-management policy |
| **Congestion Alert → Transit Recommendation** | When major incident detected, surface which transit alternatives are currently reliable | Traffic events + live vehicle positions | Proactive commuter intelligence |

---

### 🔵 Sprint 4 — Transfer & Fare Intelligence

| Feature | Description | Data Source | Differentiation |
|---------|-------------|-------------|-----------------|
| **Multi-Agency Fare Calculator** | Exact fare for any multi-agency journey including transfer discounts | 511.org GTFS Fares v2 | First platform with accurate multi-agency Bay Area fare calculation (Google Maps doesn't have this) |
| **Transfer Reliability Matrix** | Heat map of all agency-pair transfers by success probability | stop_observations + Fares v2 | No competitor does cross-agency transfer scoring |
| **Transfer Desert Map** | Areas where two-agency transfers are geographically impossible within reasonable walk | GTFS stops + Fares v2 transfer rules | Regional planning insight unavailable elsewhere |
| **Multi-Stop Multi-Agency Trip Planning** | True multi-agency trip planning with real transfer times + fare calculation | GTFS Pathways + Fares v2 + SIRI Stop Monitoring | Rivals GTFS-based trip planners but with live ETAs and real fares |

---

### 🟣 Sprint 5 — Equity & Accessibility Intelligence

| Feature | Description | Data Source | Differentiation |
|---------|-------------|-------------|-----------------|
| **Service Delivery Gap Map** | For each census tract: does the scheduled service actually arrive? Compare observed vs. planned by equity index | stop_observations + Census ACS + GTFS | First stop-level equity audit grounded in actual observation data (not just demographic overlay) |
| **Fare Burden Mapper** | Transit cost as % of median household income per census tract, multi-agency | Fares v2 + Census ACS | First tool to combine GTFS Fares v2 with income data at tract level |
| **ADA Accessibility Gap Tracker** | Stops/stations with high disabled-population density but poor wheelchair accessibility | GTFS `wheelchair_boarding` + GTFS Pathways + Census B18101 | Actionable infrastructure investment prioritization |
| **Service Equity Score** | Single composite metric per tract: frequency + reliability + accessibility + fare burden | All of the above | One number for policy reporting and grant applications |
| **Historic Equity Trend** | Did service delivery in low-income tracts improve or worsen over the past 3 years? | stop_observations monthly archive | Longitudinal equity tracking; no commercial tool does this |

---

### 🔴 Sprint 6 — AI Intelligence Layer

| Feature | Description | Data Source | Differentiation |
|---------|-------------|-------------|-----------------|
| **Multi-Agency AI Assistant** | Natural language Q&A about any agency's performance, any transfer, any route | pgvector over all agency data + Ollama | Broader scope than current single-agency RAG |
| **Daily Operations Briefing** | Auto-generated morning brief: delays, work zones, below-threshold routes, transfer alerts | All data sources | Proactive, zero-effort daily intelligence |
| **Route Performance Explainer** | "Why did Route 51B underperform last Tuesday?" — narrative explanation with data | stop_observations + traffic events + schedule drift | Conversational analytics |
| **Schedule Optimization Suggestions** | "Route 72 consistently runs 12 minutes late at segment X between 8–9am. Proposed schedule adjustment: +10 min run time" | schedule drift detection | Actionable scheduling output; positioned against Swiftly run-time analysis |
| **Conversational Trip Planning** | "I need to get from Fruitvale to SFO with a connection, what's most reliable on a Tuesday?" | SIRI + Fares v2 + stop_observations | AI-powered multi-agency planning with reliability context |

---

## Technical Architecture (Target State)

```
┌─────────────────────────────────────────────────────────────┐
│                        Data Sources                          │
├──────────────┬──────────────┬───────────────┬───────────────┤
│  511.org RT  │ 511.org Static│ 511.org Archive│ 511.org Traffic│
│  GTFS-RT     │  GTFS + Fares │ stop_obs.txt   │ events/WZDx/  │
│  (all 30+    │  v2 + Pathways│ (monthly, 3yr) │ toll rates    │
│   agencies)  │  (all agencies│                │               │
└──────┬───────┴──────┬───────┴───────┬────────┴────────┬──────┘
       │              │               │                 │
       ▼              ▼               ▼                 ▼
┌─────────────────────────────────────────────────────────────┐
│                    Ingestion Layer (Python)                   │
│  five11_rt_ingestor.py   │  gtfs_static_loader.py (loop)    │
│  five11_stop_monitoring  │  five11_stop_observations.py     │
│  five11_traffic.py       │  safety_incidents_loader.py      │
│  equity_loader.py        │  five11_toll_poller.py           │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   PostgreSQL + PostGIS + pgvector            │
│                                                              │
│  Core reference:  gtfs_routes, gtfs_stops, gtfs_trips,       │
│                   gtfs_stop_times, gtfs_shape_geoms          │
│                   fare_products, fare_leg_rules               │
│                   gtfs_pathways                              │
│                                                              │
│  Operational:     ops_trip_events (multi-agency)             │
│                   rt_vehicle_positions_raw (multi-agency)    │
│                   ops_headways                               │
│                   stop_observations (30+ agencies, 3yr)      │
│                                                              │
│  Traffic/Toll:    traffic_events, work_zones, toll_rates     │
│                                                              │
│  Analysis:        stop_safety_scores (fixed)                 │
│                   coverage_cells (with real equity)          │
│                   transit_deserts                            │
│                   delay_predictions, bunching_predictions    │
│                   demand_forecasts, crowding_predictions     │
│                   transfer_reliability                       │
│                                                              │
│  AI:              ai_embeddings (384-dim, pgvector)          │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  FastAPI Backend (Python)                     │
│                                                              │
│  /reliability/*  /coverage/*  /safety/*  /demand/*           │
│  /crowding/*     /routes/*    /stops/*   /vehicles/*         │
│  /alerts         /bunching/*  /trip-planner                  │
│                                                              │
│  NEW:  /benchmarks/*  /schedule-drift/*  /transfers/*        │
│        /fares/*        /equity/*         /accessibility/*    │
│        /traffic/*      /analytics/*      /ai/*               │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              React + TypeScript Frontend (Vite)              │
│                                                              │
│  Sections (tabs):                                            │
│  Reliability │ Crowding │ Safety │ Coverage │ Demand         │
│  Routes │ Bunching │ Vehicles │ Comparison │ Planner │ AI    │
│                                                              │
│  NEW tabs:                                                   │
│  Benchmarks │ Schedule Drift │ Transfers │ Equity │ Traffic  │
│                                                              │
│  Map (Mapbox GL):                                            │
│  All agency vehicles │ Stop circles (all agencies)           │
│  Route shapes │ Coverage hex │ Traffic incidents             │
│  Work zones │ Equity choropleth │ Transfer desert zones      │
└─────────────────────────────────────────────────────────────┘
```

---

## Market Positioning

| Platform | Focus | Agencies | Historical Data | Cross-Modal | Equity Analysis |
|---------|--------|---------|-----------------|------------|-----------------|
| **Swiftly** | Ops analytics | Single agency | Real-time + 28 days | ❌ | ❌ |
| **Remix by Via** | Route planning | Single agency | Modeled demand only | ❌ | Demographic overlay only |
| **Optibus** | Scheduling | Single agency | APC (hardware req) | ❌ | ❌ |
| **TransitApp** | Rider app | Any | None for operators | ❌ | ❌ |
| **Google Maps** | Consumer nav | Any | None for operators | Partial | ❌ |
| **BATIS** | Regional analytics | **30+ agencies** | **3yr actual arrivals** | **Traffic + Tolls** | **Actual delivery gap** |

**BATIS's unfair advantage**: The 511.org stop_observations archive is publicly available but no commercial platform is currently mining it for regional analytics. This is a 3-year head start on historical data that competitors would need years to replicate.

---

## Data Model — New Tables Required

```sql
-- Multi-agency tagging (add to existing tables)
ALTER TABLE gtfs_routes ADD COLUMN IF NOT EXISTS agency_id text DEFAULT 'AC';
ALTER TABLE gtfs_stops ADD COLUMN IF NOT EXISTS agency_id text DEFAULT 'AC';
ALTER TABLE ops_trip_events ADD COLUMN IF NOT EXISTS agency_id text;
ALTER TABLE rt_vehicle_positions_raw ADD COLUMN IF NOT EXISTS agency_id text;

-- Sprint 2: Stop Observations
CREATE TABLE stop_observations (
    id bigserial PRIMARY KEY,
    service_date date NOT NULL,
    agency_id text NOT NULL,
    trip_id text NOT NULL,
    route_id text,
    stop_id text NOT NULL,
    scheduled_arrival timestamptz,
    observed_arrival timestamptz,
    delay_seconds integer GENERATED ALWAYS AS (
        EXTRACT(EPOCH FROM (observed_arrival - scheduled_arrival))::integer
    ) STORED,
    on_time boolean GENERATED ALWAYS AS (
        observed_arrival <= scheduled_arrival + INTERVAL '5 minutes'
    ) STORED,
    created_at timestamptz DEFAULT now()
);

-- Sprint 3: Traffic & Tolls
CREATE TABLE traffic_events (
    event_id text PRIMARY KEY,
    event_type text, severity text,
    geom geometry(Point, 4326),
    description text,
    start_time timestamptz, end_time timestamptz
);
CREATE TABLE work_zones (
    zone_id text PRIMARY KEY,
    geom geometry(MultiLineString, 4326),
    road_name text, description text,
    start_time timestamptz, end_time timestamptz
);
CREATE TABLE toll_rates (
    id bigserial PRIMARY KEY,
    facility_id text, facility_name text,
    rate_usd numeric(6,2),
    valid_from timestamptz, valid_to timestamptz
);

-- Sprint 4: Fares
CREATE TABLE fare_products (
    fare_product_id text PRIMARY KEY,
    fare_product_name text,
    agency_id text,
    amount numeric(8,2),
    currency text DEFAULT 'USD'
);
CREATE TABLE fare_transfer_rules (
    id bigserial PRIMARY KEY,
    from_leg_group_id text,
    to_leg_group_id text,
    transfer_count integer,
    fare_product_id text,
    amount numeric(8,2)
);
CREATE TABLE transfer_reliability (
    id bigserial PRIMARY KEY,
    from_agency text, to_agency text,
    transfer_stop_id text,
    scheduled_transfer_minutes numeric,
    success_rate_pct numeric,
    median_gap_seconds integer,
    n_observations integer,
    computed_at timestamptz DEFAULT now()
);
```

---

## New API Endpoints (Target)

```
# Sprint 1
GET  /agencies                              → List all 511.org agencies with RT status
GET  /stops/{stop_id}/live-departures       → SIRI Stop Monitoring live ETAs (replaces realtime-departures)

# Sprint 2
GET  /benchmarks/agency-otp                 → Cross-agency OTP scorecards (stop_observations)
GET  /schedule-drift/{agency_id}/{route_id} → Segment-level run time drift vs. scheduled
GET  /transfers/reliability                 → Agency-pair transfer success rates
GET  /observations/summary                  → Historical coverage: months loaded, agencies, row count

# Sprint 3
GET  /traffic/events                        → Active road incidents (GeoJSON)
GET  /traffic/transit-impact                → Routes affected by active work zones/incidents
GET  /analytics/toll-transit-correlation    → Toll rate vs. ridership scatter data
GET  /traffic/work-zones                    → Active WZDx work zones (GeoJSON)

# Sprint 4
POST /fares/calculate                       → Multi-agency fare with transfer discounts
GET  /transfers/deserts                     → Geographic areas with no viable inter-agency transfer
GET  /trip-planner/multimodal               → Full multi-agency trip plan (replaces trip-planner)

# Sprint 5
GET  /equity/service-delivery-gap          → Tract-level observed vs. scheduled service by equity score
GET  /equity/fare-burden                   → Transit fare as % income per tract
GET  /accessibility/gaps                   → Stops with high ADA-need but low wheelchair accessibility
GET  /equity/score                         → Composite equity score per tract (GeoJSON)

# Sprint 6
GET  /ai/daily-brief                       → AI-generated morning operations briefing
GET  /ai/schedule-suggestion/{route_id}    → Schedule optimization recommendation for a route
POST /ai/ask                               → Updated to support conversation_history
```

---

## What We're Not Building

- A rider-facing mobile app (that's TransitApp, Google Maps, Moovit)
- Hardware or on-board systems (that's Clever Devices, Cubic)
- Crew/driver scheduling optimization (that's Optibus, HASTUS)
- Payment processing (that's Clipper/Cubic)
- A single-agency deep-dive tool (that's Swiftly)

BATIS is the **regional intelligence layer** that sits above single-agency tools and uses freely available open data to give the Bay Area a cross-agency view no one has built before.

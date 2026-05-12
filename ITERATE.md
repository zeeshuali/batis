# BATIS — Iteration Plan
_Last updated: 2026-05-09_

Phased sprint plan ordered by impact and dependency. Each sprint is ~1–2 weeks of focused work.

---

## Sprint 0 — Stabilise & Fix Critical Bugs
**Goal**: Make what exists actually work correctly. No new features.

### 0.1 Backend fixes (half-day each)

| Task | File | Change |
|------|------|--------|
| Fix FastAPI route ordering bug | `main.py` | Move `/routes/compare` above `/routes/{route_id}/geo` |
| Fix safety scoring geometry units | `safety_scoring.py` | `ST_DWithin(s.geom::geography, i.geom::geography, :buffer_meters)` |
| Add `CREATE EXTENSION IF NOT EXISTS vector` | `schema.sql` | Add before `ai_embeddings` DDL |
| Fix missing dependencies | `requirements.txt` | Add `sentence-transformers>=2.7`, `httpx>=0.27`, `certifi` |
| Fix equity no-op | `equity_loader.py` | Remove `WHERE population > 0` filter; add `population` to coverage_cells builder OR update equity to update all cells |
| Fix SQL f-string in AI assistant | `ai_assistant.py` | Use `conn.execute(text("... :emb ::vector"), {"emb": str(vec.tolist())})` |
| Remove `verify=False` everywhere | All services | Replace with `verify=certifi.where()` |
| Add `BACKEND_API_KEY` to config.py | `config.py` | Move from `os.getenv()` in security.py into Settings |
| Add `OLLAMA_URL`, `OLLAMA_MODEL`, `EMBED_MODEL_NAME` to config.py | `config.py` + `ai_assistant.py` + `ml/embed.py` | |
| Add `CORS_ORIGINS` to config.py | `config.py` + `main.py` | Read allow_origins from env |
| Fix Vite proxy port | `vite.config.ts` | Change proxy target from 8002 to 8000 |

### 0.2 Frontend fixes

| Task | File | Change |
|------|------|--------|
| Wire real-time departures in StopDrawer | `StopDrawer.tsx` | Fetch `/stops/{stop_id}/realtime-departures` instead of relying on `stop_detail.departures` |
| Fix bunching map to show bunching data | `MapView.tsx` | Add `bunching-stops` source fetching `/reliability/stops/geo` with stddev coloring (distinct from delay coloring) |
| Fix demand legend colours | `MapView.tsx` | Three identical purple legend entries → replace with radius-based legend |
| Fix heatmap layer persistence | `MapView.tsx` | Include `reliability-heat` in `ALL_LAYERS` / `SECTION_LAYERS` so it hides on section switch |
| Fix date range picker visibility | `Sidebar.tsx` | Hide date range for sections that don't use it (vehicles, coverage) |
| Remove dead `void ALL_LAYERS;` | `MapView.tsx` | Delete or use the constant properly |
| Add error feedback to AlertsBanner | `AlertsBanner.tsx` | Show subtle "alerts unavailable" state instead of silent empty |
| Add error details to StopDrawer | `StopDrawer.tsx` | Show "404 – stop not found" vs "network error" |

### 0.3 Data pipeline fixes

| Task | File | Change |
|------|------|--------|
| Fix `generate_demand_forecasts` NULL coercion | `models_demand_crowding.py` | Use `delay_seconds IS NOT NULL` filter properly; don't coerce NULLs |
| Wrap all pipeline steps in try/except | `run_data_jobs.py` | Each step independently protected |
| Fix per-trip DELETE loop → batch DELETE | `gtfs_rt_ingestor.py` | `DELETE WHERE (service_date, trip_id) = ANY(...)` |
| Fix Socrata pagination | `safety_incidents_loader.py` | Add offset loop until all rows fetched |
| Remove duplicate `CREATE TABLE IF NOT EXISTS` | `models_demand_crowding.py` | Rely on schema.sql exclusively |
| Add `_get_model()` thread lock | `ml/embed.py` | `import threading; _lock = threading.Lock()` |

**Sprint 0 outcome**: Every existing feature works correctly. Safety scores are valid. Route comparison works. Equity shows real values. AI assistant installs cleanly.

---

## Sprint 1 — Wire Up 511.org (Core Integration)
**Goal**: Replace or supplement AC Transit–only feeds with 511.org regional feeds. Unlock multi-agency data.

### 1.1 Config & credentials

- Add `FIVE11_API_KEY` and `FIVE11_BASE_URL=https://api.511.org` to `config.py`
- Add `FIVE11_AGENCIES` list (default: `["AC", "BA", "SF", "CT", "SM", "GG", "WH", "VN"]`) to config

### 1.2 511.org GTFS-RT ingestor

**New file**: `backend/app/services/five11_rt_ingestor.py`

- Fetch from `https://api.511.org/Transit/VehiclePositions?api_key={key}&agency={id}` for each configured agency
- Fetch from `https://api.511.org/Transit/TripUpdates?api_key={key}&agency={id}`
- Add `agency_id` column to `rt_vehicle_positions_raw` and `ops_trip_events` (schema migration)
- Reuse existing `_insert_vehicle_positions` and `_process_trip_updates` logic with agency tag
- Switch the background RT ingestor thread to use 511.org feeds instead of (or in addition to) direct AC Transit feeds

### 1.3 511.org multi-agency GTFS static

- Update `config.py`: make `FIVE11_AGENCIES` drive a loop in `gtfs_static_loader.py`
- For each agency, fetch: `https://api.511.org/transit/datafeeds?api_key={key}&operator_id={id}`
- Tag each GTFS entity with `agency_id` (already a column in `gtfs_routes`; add to stops/trips as needed)
- `run_data_jobs.py` step 1 loops over all agencies

### 1.4 511.org Service Alerts (multi-agency)

- Update `alerts_loader.py`: loop over `FIVE11_AGENCIES`, fetch GTFS-RT alerts from 511.org per agency
- Merge + deduplicate, return combined list
- AlertsBanner then shows alerts from BART, Muni, AC Transit, etc.

### 1.5 Live Stop Monitoring (real ETAs via SIRI)

**New file**: `backend/app/services/five11_stop_monitoring.py`

- Endpoint: `GET https://api.511.org/transit/StopMonitoring?api_key={key}&agency={id}&monitoringref={stop_code}`
- Parse SIRI JSON response → extract `ExpectedArrivalTime`, `AimedArrivalTime`, vehicle ref, line ref
- New backend endpoint: `GET /stops/{stop_id}/live-departures` (replaces `realtime-departures`)
- StopDrawer calls this instead of the old scheduled+overlay approach
- **Impact**: Stop Drawer now shows real live ETAs, not estimates

### 1.6 Schema migration for multi-agency

```sql
ALTER TABLE rt_vehicle_positions_raw ADD COLUMN IF NOT EXISTS agency_id text;
ALTER TABLE ops_trip_events ADD COLUMN IF NOT EXISTS agency_id text;
ALTER TABLE gtfs_stops ADD COLUMN IF NOT EXISTS agency_id text DEFAULT 'AC';
ALTER TABLE gtfs_routes ADD COLUMN IF NOT EXISTS agency_id text DEFAULT 'AC';
```

**Sprint 1 outcome**: BATIS becomes a multi-agency Bay Area platform. Live vehicle map shows BART, Muni, AC Transit simultaneously. Stop drawer shows real ETAs. Alerts cover all agencies.

---

## Sprint 2 — Stop Observations Archive (Historical Intelligence)
**Goal**: Ingest the 511.org monthly stop_observations archive to build genuine historical analytics.

### 2.1 Stop Observations downloader

**New file**: `backend/app/services/five11_stop_observations.py`

- Download: `GET https://api.511.org/transit/datafeeds?api_key={key}&operator_id=RG&historic=YYYY-MM-so`
- Parse `stop_observations.txt` CSV from zip (fields: trip_id, stop_id, agency_id, scheduled_arrival, observed_arrival, service_date)
- Bulk-insert into new table `stop_observations` (see schema below)
- Incrementally download: check which months are already loaded, only fetch missing months
- Schedule: run once/month on the 5th (prior month data is available)

**New table**:
```sql
CREATE TABLE IF NOT EXISTS stop_observations (
    id bigserial PRIMARY KEY,
    service_date date NOT NULL,
    agency_id text NOT NULL,
    trip_id text NOT NULL,
    route_id text,
    stop_id text NOT NULL,
    scheduled_arrival timestamptz,
    observed_arrival timestamptz,
    delay_seconds integer GENERATED ALWAYS AS
        (EXTRACT(EPOCH FROM (observed_arrival - scheduled_arrival))::integer) STORED,
    on_time boolean GENERATED ALWAYS AS
        (observed_arrival <= scheduled_arrival + INTERVAL '5 minutes') STORED,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX so_service_date_idx ON stop_observations(service_date);
CREATE INDEX so_agency_route_idx ON stop_observations(agency_id, route_id);
CREATE INDEX so_stop_idx ON stop_observations(stop_id);
```

### 2.2 New Analytics: Cross-Agency OTP Benchmarking

**New endpoint**: `GET /benchmarks/agency-otp`
- Query `stop_observations` grouped by `agency_id`, `service_date` → `on_time_pct`, `avg_delay_seconds`
- Params: `start_date`, `end_date`
- Returns: per-agency monthly scorecards

**New Sidebar panel**: AgencyBenchmarkPanel
- Bar chart comparing all agencies by on-time % for the selected date range
- Highlight which agency is improving/declining (month-over-month trend)

### 2.3 New Analytics: Schedule Drift Detection

**New endpoint**: `GET /schedule-drift/{agency_id}/{route_id}`
- Query `stop_observations` for a specific route
- Compare scheduled vs. actual run times per segment (stop A → stop B) over last 3 months
- Flag segments where `avg(observed - scheduled) > 15%`
- Returns: list of segments with drift %, recommended schedule adjustment

### 2.4 Replace synthetic ops data with real observations

Once `stop_observations` is loaded with 2+ months of data:
- `ops_trip_events` can be backfilled from `stop_observations` for all agencies
- `generate_delay_predictions`, `generate_demand_forecasts` use real arrival data
- Remove `seed_from_static.py` from the pipeline (it was only needed without real RT data)

**Sprint 2 outcome**: BATIS has 3+ years of real historical arrival data for the entire Bay Area. Analytics become genuinely accurate. Schedule drift detection becomes the first unique feature not available in any competing product.

---

## Sprint 3 — Traffic, Tolls & Work Zones
**Goal**: Cross-correlate 511.org traffic data with transit performance — a uniquely Bay Area capability.

### 3.1 Traffic Events Ingestor

**New file**: `backend/app/services/five11_traffic.py`
- `GET https://api.511.org/traffic/events?api_key={key}` → parse incident type, location (lat/lon), severity, start/end time
- Store in new table `traffic_events` with PostGIS geometry
- Poll every 5 minutes

**New table**:
```sql
CREATE TABLE IF NOT EXISTS traffic_events (
    event_id text PRIMARY KEY,
    event_type text,          -- accident, congestion, roadwork, etc.
    severity text,            -- minor, moderate, major
    geom geometry(Point, 4326),
    description text,
    start_time timestamptz,
    end_time timestamptz,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX traffic_events_geom_idx ON traffic_events USING gist(geom);
```

### 3.2 Work Zone Ingestor

- `GET https://api.511.org/traffic/wzdx?api_key={key}` → road closures with geometry
- Store in `work_zones` table (linestring or polygon geometry)
- Refresh every 15 minutes

### 3.3 Toll Rate Poller

- `GET https://api.511.org/toll/programs?api_key={key}` → Bay Bridge + Express Lane rates
- Store in `toll_rates` table (facility_id, rate_usd, valid_from, valid_to)
- Refresh every 5 minutes (rates change with dynamic pricing)

### 3.4 New Feature: Work Zone Transit Impact Predictor

**New endpoint**: `GET /traffic/transit-impact`
- Find bus routes within 500m of active work zones or major incidents
- Estimate delay impact based on historical `stop_observations` delay on those segments
- Return: `{route_id, route_short_name, affected_stops[], estimated_additional_delay_seconds, confidence}`
- Update every 5 minutes
- **Frontend**: New "Traffic Impact" panel in Sidebar; map overlay showing affected routes highlighted red

### 3.5 New Feature: Toll-Transit Correlation Dashboard

**New endpoint**: `GET /analytics/toll-transit-correlation`
- Correlate daily `toll_rates` for Bay Bridge with ridership on Transbay bus routes from `stop_observations`
- Returns: scatter plot data (toll_rate_usd vs. estimated_boardings per day)

**Frontend**: Recharts scatter chart in a new "Analytics" section

**Sprint 3 outcome**: BATIS becomes the only platform that connects Bay Area toll pricing and traffic incidents to transit performance in real time.

---

## Sprint 4 — Transfer Reliability & Fare Intelligence
**Goal**: Use GTFS Fares v2 and multi-agency stop_observations to build unique transfer and fare features.

### 4.1 Multi-Agency GTFS with Fares v2

- Download regional GTFS: `GET https://api.511.org/transit/datafeeds?api_key={key}&operator_id=RG`
- Parse `fare_products.txt`, `fare_leg_rules.txt`, `fare_transfer_rules.txt` (Fares v2)
- New tables: `fare_products`, `fare_leg_rules`, `fare_transfer_rules`

### 4.2 New Feature: Transfer Reliability Score

**New endpoint**: `GET /transfers/reliability`
- For each agency-to-agency transfer pair (BART→AC, BART→Muni, etc.), compute:
  - Median time between BART arrival and connecting bus departure (from stop_observations)
  - % of times the connecting bus is available within the scheduled transfer window
- Returns: `{from_agency, to_agency, transfer_stop, success_rate_pct, median_gap_seconds, n_observations}`

**Frontend**: Transfer Reliability heatmap — a table/matrix of all agency pairs colored by success rate

### 4.3 New Feature: Multi-Agency Fare Calculator

**New endpoint**: `POST /fares/calculate`
- Input: `{from_stop, to_stop}` — GTFS stop IDs from any agency
- Compute: base fare + applicable transfer discounts from Fares v2 tables
- Returns: `{total_fare_usd, fare_breakdown: [{agency, product, amount}], transfer_discounts_applied}`

**Frontend**: Fare calculator in Trip Planner — after getting an itinerary, show exact fare

### 4.4 Implement Real Transfer Trip Planning

- Update `get_trip_plan()` in `analysis.py` to support multi-agency trips
- Find: nearest stop on any agency → transfer to connecting agency → destination
- Use Pathways data for transfer times at major hubs (BART-to-Muni, etc.)

**Sprint 4 outcome**: BATIS is the only platform with accurate multi-agency fare calculation and transfer reliability scoring in the Bay Area.

---

## Sprint 5 — Equity & Accessibility Intelligence
**Goal**: Build real, data-driven equity analytics using actual observed service quality, not just demographic overlays.

### 5.1 Actual Equity Computation

- Fix `equity_loader.py` to do a proper Census tract spatial join:
  - Download TIGER/Line census tract boundaries (once, cached)
  - `ST_Within(coverage_cell.geom, tract.geom)` to assign each cell to a tract
  - Apply per-tract equity metrics (income, car ownership, age) instead of county average
- Add `census_tract_id` column to `coverage_cells`

### 5.2 New Feature: Service Quality Equity Audit

**New endpoint**: `GET /equity/service-delivery-gap`
- For each census tract, compare:
  - Scheduled frequency (from GTFS)
  - Actual on-time rate (from `stop_observations`)
  - Equity score (low-income + no-car households)
- Compute: "service delivery gap" = routes/tracts where high-equity-need areas underperform scheduled service
- Returns: GeoJSON FeatureCollection of tracts coloured by delivery gap score

**Frontend**: New "Equity" section in the tab bar. Map shows tracts coloured by delivery gap. Sidebar shows top-10 underserved tracts.

### 5.3 New Feature: ADA Accessibility Gap Tracker

- Use GTFS `wheelchair_boarding` field per stop + Pathways data
- Cross-reference with Census elderly/disability population (ACS B18101)
- Endpoint: `GET /accessibility/gaps` → stops with high disabled-population density but low accessibility rating
- Map layer: orange circles = accessibility gap stops

### 5.4 New Feature: Fare Burden Mapper

- Use Fares v2 single-agency fares + multi-agency transfer costs
- Cross-reference with Census median household income per tract
- Compute: transit cost as % of median income for key origin-destination pairs
- Endpoint: `GET /equity/fare-burden` → GeoJSON of fare burden by tract

**Sprint 5 outcome**: BATIS becomes a genuine equity research tool — something no commercial competitor offers at stop level with actual observed data.

---

## Sprint 6 — AI & Intelligence Upgrades
**Goal**: Make the AI assistant genuinely useful for operational questions about the real multi-agency network.

### 6.1 Multi-Agency RAG Embeddings

- Update `ml/embed.py` to build embeddings for all agencies (not just AC Transit)
- Add agency context to each embedding document
- Build `stop_observations` summary embeddings (per-route monthly performance summaries)

### 6.2 Conversational History

- Update `POST /ai/ask` to accept `conversation_history: [{role, content}]`
- Include history in Ollama prompt
- AiAssistant.tsx maintains history in state, sends full context with each message

### 6.3 Proactive Alerts via AI

- New endpoint: `POST /ai/daily-brief` → generates a morning operational briefing:
  - Active traffic incidents affecting bus routes
  - Routes with below-threshold OTP yesterday
  - Upcoming work zones near major stops
  - Transfer success rate alerts (below 70%)
- Returns structured briefing + narrative summary

### 6.4 Route Explain Feature (wire up frontend)

- Add "Explain this route" button to RouteExplorerPanel when a route is selected
- Calls `GET /ai/explain/{route_id}`
- Shows AI summary in a modal or expanded panel section

**Sprint 6 outcome**: AI assistant answers real questions about the live network, gives daily operational briefings, and explains route performance trends.

---

## Sprint 7 — Hardening, Tests & Performance
**Goal**: Make BATIS production-ready.

### 7.1 Backend tests

- `pytest` + `httpx.AsyncClient` smoke tests for all 29+ endpoints
- Fixture: test PostgreSQL database with `schema.sql` applied
- Unit tests for `safety_scoring.py` (distance calculation), `coverage_builder.py` (bbox generation), `equity_loader.py` (tract assignment)
- Data pipeline integration test: run all 11 steps on a small GTFS sample

### 7.2 Frontend tests

- Playwright E2E:
  - Load the map, click a stop → verify StopDrawer opens with content
  - Switch between all 11 sections → verify map layers change
  - Submit a trip planner query → verify itinerary appears
  - Submit AI chat question → verify response renders

### 7.3 Performance fixes

- Add missing DB indexes (see GAPS.md §8)
- Batch stop geometry update in `gtfs_static_loader.py` (single `UPDATE ... FROM VALUES`)
- Add pagination to `GET /coverage/cells` (require bbox or LIMIT+offset)
- Batch GTFS stop_times upsert (executemany with ON CONFLICT)

### 7.4 Production hardening

- Rate limiting on all public endpoints (e.g., `slowapi`)
- Structured logging with `structlog`
- `/health` endpoint shows auth status, 511.org connectivity, Ollama status
- Docker compose file for full stack (Postgres + PostGIS + pgvector, FastAPI, Vite dev server)
- Environment variable documentation in `README.md`

**Sprint 7 outcome**: BATIS is production-deployable, tested, and observable.

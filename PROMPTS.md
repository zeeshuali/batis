# BATIS — Implementation Prompts Playbook
_Last updated: 2026-05-09_

This file contains copy-paste Claude prompts for every implementation step. Work through them in order. Each prompt is self-contained — paste it at the start of a fresh Claude session in Cowork mode with this project folder selected.

**Before you start any prompt**: make sure `backend/.env` has `FIVE11_API_KEY=your_token_here`.

**Strategy**: We are replacing AC Transit's direct API with 511.org as the primary data source for everything. 511.org covers AC Transit (agency code `AC`) plus 30+ other Bay Area agencies. The `ACTRANSIT_API_KEY` config field stays but becomes unused once 511.org is wired up.

---

## SPRINT 0 — Fix All Critical Bugs

These must be done before any new features. Do them in order.

---

### Prompt 0.1 — Fix Backend Critical Bugs

```
I'm working on the BATIS project at \\wsl.localhost\ubuntu\home\mza\projects\batis

Read CLAUDE.md first, then PROGRESS.md to understand current status.

Fix ALL of the following bugs in one session. Make the actual code changes:

1. **Fix FastAPI route ordering bug** in `backend/app/main.py`
   - `/routes/compare` is currently registered AFTER `/routes/{route_id}/geo`
   - FastAPI matches "compare" as a route_id — the endpoint is unreachable
   - Move the `GET /routes/compare` endpoint definition to BEFORE `GET /routes/{route_id}/geo`

2. **Fix safety scoring geometry units** in `backend/app/services/safety_scoring.py`
   - `ST_DWithin(s.geom, i.geom, :buffer_meters)` uses plain geometry (degrees), not geography (meters)
   - 150 "meters" currently means 150 degrees = the entire planet → all incidents match all stops
   - Fix: `ST_DWithin(s.geom::geography, i.geom::geography, :buffer_meters)`
   - Apply the same fix everywhere ST_DWithin appears in this file

3. **Fix missing pgvector extension** in `backend/sql/schema.sql`
   - Add `CREATE EXTENSION IF NOT EXISTS vector;` right after `CREATE EXTENSION IF NOT EXISTS postgis;`
   - This must appear before the `ai_embeddings` table definition

4. **Fix missing dependencies** in `backend/requirements.txt`
   - Add: `sentence-transformers>=2.7`
   - Add: `httpx>=0.27`
   - Add: `certifi>=2024.0`

5. **Fix equity no-op** in `backend/app/services/equity_loader.py`
   - `populate_equity_columns()` has `WHERE population > 0` but `population` is never set → always updates 0 rows
   - Remove the `WHERE population > 0` clause — update all coverage cells
   - Also do a proper per-county average applied to ALL cells (not just >0 population ones)

6. **Fix SQL f-string injection risk** in `backend/app/services/ai_assistant.py`
   - The embedding vector is interpolated as an f-string into SQL
   - Find the line that does `f"... '{emb_str}'::vector ..."` and replace with a parameterised query
   - Use SQLAlchemy `text()` with a named parameter: `text("... :emb ::vector ...")` and pass `{"emb": str(vec.tolist())}`

7. **Remove `verify=False` from all service files**
   - Search every file in `backend/app/services/` and `backend/ml/` for `verify=False`
   - Replace each with `verify=certifi.where()` (import certifi at the top of each file)
   - Files affected: `gtfs_rt_ingestor.py`, `alerts_loader.py`, `safety_incidents_loader.py`, `equity_loader.py`, `gtfs_static_loader.py`

8. **Move hardcoded config values to `config.py`** in `backend/app/core/config.py`
   - Add these fields to the Settings class:
     - `backend_api_key: str = ""`
     - `ollama_url: str = "http://localhost:11434"`
     - `ollama_model: str = "llama3.1:8b"`
     - `embed_model_name: str = "all-MiniLM-L6-v2"`
     - `cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]`
     - `five11_api_key: str = ""`
     - `five11_base_url: str = "https://api.511.org"`
   - Update `security.py` to use `get_settings().backend_api_key` instead of `os.getenv("BACKEND_API_KEY")`
   - Update `ai_assistant.py` to use `get_settings().ollama_url` and `get_settings().ollama_model`
   - Update `ml/embed.py` to use `get_settings().embed_model_name`
   - Update `main.py` CORS to use `get_settings().cors_origins`

9. **Wrap pipeline steps in try/except** in `backend/app/workers/run_data_jobs.py`
   - Steps 2–7 currently have no error handling — a failure stops the whole pipeline
   - Wrap each step in its own try/except block that logs the error and continues to the next step
   - Keep steps 1, 8, 10, 11 as-is (they may already be wrapped)

10. **Fix per-trip DELETE loop** in `backend/app/services/gtfs_rt_ingestor.py`
    - `_process_trip_updates()` issues one DELETE per trip in a Python loop (200+ DELETEs per 30s poll)
    - Replace with a single batch DELETE:
      `DELETE FROM ops_trip_events WHERE (service_date, trip_id) = ANY(:pairs)`
    - Pass pairs as a list of tuples

After all changes, verify there are no syntax errors by checking imports and function signatures are consistent.
```

---

### Prompt 0.2 — Fix Frontend Issues

```
I'm working on the BATIS project at \\wsl.localhost\ubuntu\home\mza\projects\batis

Read CLAUDE.md first, then PROGRESS.md.

Fix these frontend issues in `frontend/src/`:

1. **Wire real-time departures in StopDrawer** (`components/StopDrawer.tsx`)
   - Currently `StopDrawer` shows `stop_detail.departures` which is scheduled-only
   - There is a working endpoint `/stops/{stop_id}/realtime-departures` that returns live delay data
   - After fetching `/stops/{stop_id}`, also fetch `/stops/{stop_id}/realtime-departures`
   - Merge the results: prefer RT departure times when available; fall back to scheduled
   - Show a small "LIVE" badge (green dot) next to entries that have real-time data
   - Show the current delay in seconds next to each departure

2. **Fix bunching section map** (`components/MapView.tsx`)
   - The "bunching" section currently reuses the reliability layer (shows delay data, not bunching)
   - Add a new section-aware color: when `activeSection === 'bunching'`, colour stop circles by `delay_stddev` not `avg_delay`
   - The data already comes from the same `/reliability/stops/geo` endpoint (it includes both fields)
   - Use a purple gradient for stddev (0=grey, >120s stddev=deep purple)

3. **Fix demand legend** (`components/MapView.tsx`)
   - Three legend entries for demand all show the same colour `#a855f7`
   - Demand uses CIRCLE RADIUS not colour — replace the colour legend with a radius legend
   - Show three circle examples (small/medium/large) labelled "Low / Medium / High boardings"

4. **Fix heatmap layer persistence** (`components/MapView.tsx`)
   - The `reliability-heat` heatmap layer is NOT in `SECTION_LAYERS` or `ALL_LAYERS`
   - When switching sections the heatmap stays visible (it never gets hidden)
   - Add `reliability-heat` to the `ALL_LAYERS` array so `toggleLayers()` hides it when leaving the reliability section
   - Also add it to `SECTION_LAYERS.reliability` so it shows when in reliability section

5. **Hide date range for irrelevant sections** (`components/Sidebar.tsx`)
   - The date range picker shows for ALL sections including Vehicles (always live) and Coverage (all-time data)
   - Hide the date range picker when `activeSection` is one of: `vehicles`, `coverage`, `ai`, `planner`

6. **Fix Vite proxy port** (`vite.config.ts`)
   - Proxy target is `http://127.0.0.1:8002` but the backend runs on port 8000
   - Change to `http://127.0.0.1:8000`

7. **Add error feedback to AlertsBanner** (`components/AlertsBanner.tsx`)
   - Currently `.catch(() => {})` swallows all errors silently
   - Add a state variable `alertsError: boolean`
   - On error, show a tiny grey text: "Alert feed unavailable" instead of nothing

8. **Fix StopDrawer error handling** (`components/StopDrawer.tsx`)
   - `.catch(() => setDetail(null))` shows nothing on error
   - Distinguish between 404 (show "Stop not found") and network error (show "Could not reach server")
   - Check the response status code before setting detail

After making all changes, confirm no TypeScript compile errors by checking all type signatures match.
```

---

### Prompt 0.3 — Fix Socrata Pagination + Safety Incidents

```
I'm working on the BATIS project at \\wsl.localhost\ubuntu\home\mza\projects\batis

Read CLAUDE.md first.

Fix the safety incidents loader to actually load all data (not just the first 1000 rows):

**File**: `backend/app/services/safety_incidents_loader.py`

1. **Add Socrata pagination loop**
   - Currently `_fetch_socrata()` has a hardcoded `limit=1000` and fetches only once
   - Oakland's crime dataset has 100,000+ rows; only 1000 are loaded
   - Add a pagination loop: keep fetching with `$offset=0, 1000, 2000...` until a page returns fewer rows than the limit
   - Use `limit=1000` per page (Socrata's safe maximum)
   - Add a `max_pages=50` safety cap (50,000 rows maximum)

2. **Add `days_back` filter to crime query**
   - The crime fetch should add a Socrata WHERE clause: `$where=datetime > '{cutoff_date}'`
   - This keeps the pagination from loading the entire historical dataset on every run
   - Default: load last 180 days of crime data

3. **Wrap DELETE + INSERT in a single transaction**
   - Currently: DELETE all Oakland incidents, then INSERT new ones
   - If INSERT fails mid-batch, the DELETE already committed and data is lost
   - Wrap both operations in a single transaction so DELETE rolls back on INSERT failure

4. **Add logging**
   - Log `INFO` at start of each page fetch: "Fetching crime incidents page {n}, offset {offset}"
   - Log `INFO` at completion: "Loaded {N} crime incidents, {M} collision incidents"
   - Replace the bare `except Exception: return []` with `except Exception as e: logger.error(f"Safety load failed: {e}"); return []`

5. **Extend coverage area**
   - Currently only fetches Oakland crime data
   - Add a second Socrata fetch for Berkeley crime data (dataset ID: `s24d-wsnp`)
   - Berkeley endpoint: `https://data.cityofberkeley.info/resource/s24d-wsnp.json`
   - Tag rows with `source='berkeley_crime'`
```

---

## SPRINT 1 — 511.org Integration

Do these prompts in order. Each builds on the previous.

---

### Prompt 1.1 — Schema Migration for Multi-Agency

```
I'm working on the BATIS project at \\wsl.localhost\ubuntu\home\mza\projects\batis

Read CLAUDE.md and BLUEPRINT.md first.

Create a database migration file for multi-agency support.

**Create new file**: `backend/sql/migrations/001_multi_agency.sql`

Add these changes:
```sql
-- Add agency_id to all tables that need it
ALTER TABLE gtfs_routes ADD COLUMN IF NOT EXISTS agency_id text DEFAULT 'AC';
ALTER TABLE gtfs_stops ADD COLUMN IF NOT EXISTS agency_id text DEFAULT 'AC';
ALTER TABLE gtfs_trips ADD COLUMN IF NOT EXISTS agency_id text DEFAULT 'AC';
ALTER TABLE gtfs_stop_times ADD COLUMN IF NOT EXISTS agency_id text DEFAULT 'AC';
ALTER TABLE gtfs_shape_geoms ADD COLUMN IF NOT EXISTS agency_id text DEFAULT 'AC';
ALTER TABLE rt_vehicle_positions_raw ADD COLUMN IF NOT EXISTS agency_id text DEFAULT 'AC';
ALTER TABLE ops_trip_events ADD COLUMN IF NOT EXISTS agency_id text DEFAULT 'AC';
ALTER TABLE ops_headways ADD COLUMN IF NOT EXISTS agency_id text DEFAULT 'AC';

-- Add indexes for agency_id filtering
CREATE INDEX IF NOT EXISTS gtfs_routes_agency_idx ON gtfs_routes(agency_id);
CREATE INDEX IF NOT EXISTS gtfs_stops_agency_idx ON gtfs_stops(agency_id);
CREATE INDEX IF NOT EXISTS ops_trip_events_agency_idx ON ops_trip_events(agency_id);
CREATE INDEX IF NOT EXISTS rt_positions_agency_idx ON rt_vehicle_positions_raw(agency_id);

-- Stop Observations table (new — for 511.org historical archive)
CREATE TABLE IF NOT EXISTS stop_observations (
    id bigserial PRIMARY KEY,
    service_date date NOT NULL,
    agency_id text NOT NULL,
    trip_id text NOT NULL,
    route_id text,
    stop_id text NOT NULL,
    scheduled_arrival timestamptz,
    observed_arrival timestamptz,
    delay_seconds integer GENERATED ALWAYS AS (
        CASE WHEN observed_arrival IS NOT NULL AND scheduled_arrival IS NOT NULL
        THEN EXTRACT(EPOCH FROM (observed_arrival - scheduled_arrival))::integer
        ELSE NULL END
    ) STORED,
    on_time boolean GENERATED ALWAYS AS (
        observed_arrival <= scheduled_arrival + INTERVAL '5 minutes'
    ) STORED,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS so_date_agency_idx ON stop_observations(service_date, agency_id);
CREATE INDEX IF NOT EXISTS so_agency_route_idx ON stop_observations(agency_id, route_id);
CREATE INDEX IF NOT EXISTS so_stop_idx ON stop_observations(stop_id);
CREATE INDEX IF NOT EXISTS so_trip_idx ON stop_observations(trip_id);

-- Traffic events table (new — for 511.org traffic API)
CREATE TABLE IF NOT EXISTS traffic_events (
    event_id text PRIMARY KEY,
    event_type text,
    severity text,
    geom geometry(Point, 4326),
    description text,
    road_name text,
    start_time timestamptz,
    end_time timestamptz,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS traffic_events_geom_idx ON traffic_events USING gist(geom);
CREATE INDEX IF NOT EXISTS traffic_events_active_idx ON traffic_events(start_time, end_time);

-- Work zones table (new — for 511.org WZDx API)
CREATE TABLE IF NOT EXISTS work_zones (
    zone_id text PRIMARY KEY,
    geom geometry(MultiLineString, 4326),
    road_name text,
    description text,
    start_time timestamptz,
    end_time timestamptz,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS work_zones_geom_idx ON work_zones USING gist(geom);

-- Toll rates table (new — for 511.org toll API)
CREATE TABLE IF NOT EXISTS toll_rates (
    id bigserial PRIMARY KEY,
    facility_id text NOT NULL,
    facility_name text,
    direction text,
    vehicle_class text DEFAULT 'standard',
    rate_usd numeric(6,2),
    valid_from timestamptz,
    valid_to timestamptz,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS toll_rates_facility_idx ON toll_rates(facility_id, valid_from);
```

Also update `backend/sql/schema.sql` to include all the new tables at the bottom (append them) so a fresh install gets everything.

After creating the migration file, add a note in PROGRESS.md that this migration needs to be run against the database before Sprint 1 features will work.
```
done...

---

### Prompt 1.2 — Build 511.org RT Ingestor (Replaces AC Transit Direct)

```
I'm working on the BATIS project at \\wsl.localhost\ubuntu\home\mza\projects\batis

Read CLAUDE.md first.

**Goal**: Replace the AC Transit–specific GTFS-RT ingestor with a 511.org multi-agency ingestor.

511.org GTFS-RT endpoints (use `agency=RG` for all agencies at once, or per-agency):
- Vehicle Positions: `https://api.511.org/Transit/VehiclePositions?api_key={key}&agency=RG`
- Trip Updates: `https://api.511.org/Transit/TripUpdates?api_key={key}&agency=RG`
- Auth: query param `api_key`, read from `get_settings().five11_api_key`

**Create new file**: `backend/app/services/five11_rt_ingestor.py`

Model it closely on the existing `gtfs_rt_ingestor.py` but with these differences:

1. **Config**: read `five11_api_key` and `five11_base_url` from Settings (not hardcoded URLs)
2. **URL builder**: `f"{settings.five11_base_url}/Transit/VehiclePositions?api_key={settings.five11_api_key}&agency=RG"`
3. **Agency tagging**: extract `agency_id` from each GTFS-RT entity's `trip_descriptor.agency_id` field (or from the route_id prefix if not present). Write it to the `agency_id` column in both `rt_vehicle_positions_raw` and `ops_trip_events`
4. **SSL**: use `verify=certifi.where()` (never `verify=False`)
5. **Error handling**: wrap each agency fetch individually so one agency failing doesn't stop others
6. **Reuse existing insert functions**: call the same `_insert_vehicle_positions` and `_process_trip_updates` logic from the old file (or copy and adapt them)

**Expose a public function**:
```python
def ingest_five11_realtime_once() -> dict:
    """Fetch and ingest GTFS-RT from 511.org regional feed. Returns counts dict."""
```

**Then update `backend/app/main.py`**:
- In the `lifespan()` function, change the `gtfs-rt-ingestor` thread to use `five11_rt_ingestor.ingest_five11_realtime_once` instead of `gtfs_rt_ingestor.ingest_gtfs_realtime_once`
- Keep the old `gtfs_rt_ingestor.py` file but mark it as deprecated (add a comment at the top)
- The poll interval stays at 30 seconds

Also update `backend/app/core/config.py` to add `FIVE11_AGENCIES` field:
```python
five11_agencies: list[str] = ["AC", "BA", "SF", "CT", "SM", "GG", "WH", "VN", "SC", "SR", "CC", "MA", "WC"]
```
These are the agency codes for all major Bay Area operators.
```

--- DONE 

### Prompt 1.3 — Build 511.org Multi-Agency GTFS Static Loader

```
I'm working on the BATIS project at \\wsl.localhost\ubuntu\home\mza\projects\batis

Read CLAUDE.md first.

**Goal**: Update the GTFS static loader to download and load GTFS for all Bay Area agencies via 511.org.

511.org GTFS download endpoint:
`https://api.511.org/transit/datafeeds?api_key={key}&operator_id={agency_id}`

**Modify `backend/app/services/gtfs_static_loader.py`**:

1. Add a new function `load_agency_gtfs(agency_id: str, conn)` that:
   - Builds URL: `f"{settings.five11_base_url}/transit/datafeeds?api_key={settings.five11_api_key}&operator_id={agency_id}"`
   - Downloads the GTFS zip (using `certifi.where()`, not `verify=False`)
   - Parses routes, stops, trips, stop_times, shapes from the zip
   - Tags every row with `agency_id` before upserting
   - Calls the existing upsert functions

2. Add a new function `load_all_agencies_gtfs()` that:
   - Loops over `get_settings().five11_agencies`
   - Calls `load_agency_gtfs()` for each
   - Logs success/failure per agency
   - Continues to the next agency on failure (one bad agency feed shouldn't stop the rest)
   - Returns a summary dict: `{agency_id: "ok" | "failed: <reason>"}`

3. Update `backend/app/workers/run_data_jobs.py` step 1:
   - Change from `load_gtfs_static()` (AC Transit only) to `load_all_agencies_gtfs()`
   - Add a fallback: if 511.org key is not set, fall back to the old `load_gtfs_static()`

4. Performance fix in `_upsert_dataframe()`:
   - Currently this function does row-by-row upserts (very slow for stop_times with 100k+ rows)
   - Replace with a batch approach: write to a temp table, then do a single `INSERT ... ON CONFLICT DO UPDATE` from the temp table
   - This should make the stop_times load 10-100x faster

5. Performance fix for stop geometry:
   - Currently there is a Python loop doing one `UPDATE gtfs_stops SET geom = ...` per stop
   - Replace with a single SQL batch update:
     `UPDATE gtfs_stops SET geom = ST_SetSRID(ST_MakePoint(stop_lon, stop_lat), 4326) WHERE geom IS NULL`

Keep the old `load_gtfs_static()` function but have it call `load_agency_gtfs('AC', conn)` internally so existing code still works.
```

--- done

### Prompt 1.4 — Build 511.org Multi-Agency Alerts + Live Stop ETAs

```
I'm working on the BATIS project at \\wsl.localhost\ubuntu\home\mza\projects\batis

Read CLAUDE.md first.

**Task A: Multi-agency service alerts via 511.org**

**Modify `backend/app/services/alerts_loader.py`**:

511.org alerts endpoint: `https://api.511.org/transit/servicealerts?api_key={key}&agency={id}`
Or use the regional feed: `https://api.511.org/Transit/ServiceAlerts?api_key={key}&agency=RG`

1. Replace the AC Transit–specific URL with the 511.org URL using `get_settings().five11_api_key`
2. Use the regional `agency=RG` feed to get all agencies at once
3. Parse the GTFS-RT alerts protobuf the same way (same field names)
4. Add `agency_id` to each returned alert dict (parse from `informed_entities[].agency_id` in the feed)
5. Replace `verify=False` with `verify=certifi.where()`
6. Replace the bare `except Exception: return []` with proper logging
7. Keep returning a list of dicts compatible with the existing `GET /alerts` response format

---

**Task B: Live Stop ETAs via 511.org SIRI Stop Monitoring**

**Create new file**: `backend/app/services/five11_stop_monitoring.py`

511.org SIRI Stop Monitoring:
`https://api.511.org/transit/StopMonitoring?api_key={key}&agency={agency_id}&stopCode={stop_code}&Format=json`

Returns JSON with structure:
```json
{
  "ServiceDelivery": {
    "StopMonitoringDelivery": [{
      "MonitoredStopVisit": [{
        "MonitoredVehicleJourney": {
          "LineRef": "route_id",
          "PublishedLineName": "route_short_name",
          "DestinationName": "headsign",
          "MonitoredCall": {
            "ExpectedArrivalTime": "2026-01-01T10:30:00Z",
            "AimedArrivalTime": "2026-01-01T10:28:00Z"
          }
        }
      }]
    }]
  }
}
```

Implement:
```python
async def get_live_departures(stop_code: str, agency_id: str) -> list[dict]:
    """
    Fetch live ETAs for a stop from 511.org SIRI Stop Monitoring.
    Returns list of {route_id, route_short_name, headsign, expected_arrival, aimed_arrival, delay_seconds, is_realtime}
    Falls back to empty list if agency_id or stop_code are not available.
    """
```

**Add new backend endpoint** to `backend/app/main.py`:
```
GET /stops/{stop_id}/live-departures
```
- Look up the stop's `stop_code` and `agency_id` from `gtfs_stops`
- Call `get_live_departures(stop_code, agency_id)` from five11_stop_monitoring.py
- If 511.org returns data, return it
- If not (agency not supported, or stop_code missing), fall back to the existing `/stops/{stop_id}/realtime-departures` endpoint logic
- Mark each departure with `"is_realtime": true/false`

**Update `frontend/src/components/StopDrawer.tsx`**:
- Change the departures fetch from `/stops/{stop_id}` (scheduled only in the detail object) to call `/stops/{stop_id}/live-departures`
- Show a green "LIVE" pill badge on entries where `is_realtime === true`
- Show the delay in red/orange if `delay_seconds > 60`
- Show "Scheduled" label on entries where `is_realtime === false`
```

--- done


### Prompt 1.5 — Multi-Agency Frontend Updates

```
I'm working on the BATIS project at \\wsl.localhost\ubuntu\home\mza\projects\batis

Read CLAUDE.md and PROGRESS.md first.

**Goal**: Update the frontend to show data from all Bay Area agencies, not just AC Transit.

**1. Add an Agency Filter to the map** (`frontend/src/components/MapView.tsx` and `App.tsx`)

- Add a new piece of state to `App.tsx`: `selectedAgencies: string[]` (default: all agencies)
- Add a multi-select agency filter dropdown component at the top of the Sidebar
- Agency list: `[{id: "AC", name: "AC Transit"}, {id: "BA", name: "BART"}, {id: "SF", name: "Muni"}, {id: "CT", name: "Caltrain"}, {id: "SM", name: "SamTrans"}, {id: "GG", name: "Golden Gate"}, {id: "WH", name: "Ferry (WETA)"}, {id: "VN", name: "VTA"}]`
- Pass `selectedAgencies` to MapView and each Sidebar panel
- Add `agency_ids` query parameter to relevant API calls (e.g., `/reliability/summary?agency_ids=AC,BA,SF`)

**2. Update Live Vehicles panel** (`components/Sidebar.tsx` → `LiveVehiclesPanel`)
- Currently shows vehicle count and route list for AC Transit only
- Update to show vehicle count PER AGENCY with an agency breakdown table:
  ```
  AC Transit    142 vehicles
  BART           48 vehicles
  Muni          209 vehicles
  ...
  ```
- Add agency filter: clicking an agency name in the table filters the map to show only that agency's vehicles

**3. Add agency colour coding to the map** (`components/MapView.tsx`)
- When in "vehicles" section, colour vehicle dots by agency_id:
  - AC: `#FFD700` (gold — AC Transit yellow)
  - BA: `#0099CC` (BART blue)
  - SF: `#BF2B45` (Muni red)
  - CT: `#DB4026` (Caltrain red)
  - GG: `#FFA500` (Golden Gate orange)
  - WH: `#006DB6` (ferry blue)
  - default: `#888888`
- Add a map legend in the bottom-left corner showing agency → colour mapping

**4. Update Alerts Banner** (`components/AlertsBanner.tsx`)
- Add agency_id label to each alert pill so users know which agency the alert is from
- Use the same colour coding as vehicle dots for the agency badge

**5. Add agency badge to Stop Drawer** (`components/StopDrawer.tsx`)
- Show the stop's agency_id as a small badge in the drawer header
- Use the same colour coding

**6. Update Route Explorer** (`components/Sidebar.tsx` → `RouteExplorerPanel`)
- Add an agency filter dropdown at the top of the route list
- Group routes by agency when "All agencies" is selected
- Show the agency name as a section divider in the list
```

--- DONE0

## SPRINT 2 — Stop Observations Archive

### Prompt 2.1 — Build Stop Observations Downloader

```
I'm working on the BATIS project at \\wsl.localhost\ubuntu\home\mza\projects\batis

Read CLAUDE.md and BLUEPRINT.md first.

**Goal**: Build a service to download and ingest the 511.org monthly stop_observations archive.

Background: 511.org publishes monthly GTFS downloads that include `stop_observations.txt` — a file with actual vs. scheduled arrival times for every stop on every agency, going back to March 2022. This is the most valuable data asset in the entire 511.org ecosystem.

Download URL pattern: `https://api.511.org/transit/datafeeds?api_key={key}&operator_id=RG&historic=YYYY-MM-so`
Example: `https://api.511.org/transit/datafeeds?api_key={key}&operator_id=RG&historic=2026-04-so`

**Create new file**: `backend/app/services/five11_stop_observations.py`

Implement these functions:

```python
def get_available_months() -> list[str]:
    """Returns list of YYYY-MM strings from '2022-03' to last month."""

def get_loaded_months(conn) -> list[str]:
    """Returns months already in stop_observations table."""

def download_month(year_month: str) -> io.BytesIO:
    """Download YYYY-MM stop_observations zip from 511.org. Returns zip bytes."""

def parse_stop_observations(zip_bytes: io.BytesIO) -> pd.DataFrame:
    """
    Parse stop_observations.txt from zip.
    Expected columns: trip_id, stop_id, route_id, agency_id, 
                      scheduled_arrival, observed_arrival, service_date
    Return DataFrame with these columns typed correctly.
    """

def load_month(year_month: str, conn) -> int:
    """
    Download and load one month of stop_observations.
    Skip if already loaded. Returns rows inserted.
    """

def load_missing_months(conn, months_back: int = 3) -> dict:
    """
    Load the most recent N months that aren't already in the DB.
    Returns {month: rows_loaded} dict.
    """

def backfill_all_history(conn) -> dict:
    """
    Load all months from March 2022 to present that aren't loaded.
    This is a one-time operation. Can take hours. Logs progress.
    """
```

The `stop_observations.txt` columns to expect (map to DB columns):
- `service_id` → `service_date` (parse to date)
- `trip_id` → `trip_id`
- `stop_id` → `stop_id`
- `route_id` → `route_id`  
- `agency_id` → `agency_id`
- `scheduled_arrival` → `scheduled_arrival` (ISO datetime or seconds-since-midnight)
- `observed_arrival` → `observed_arrival` (ISO datetime or seconds-since-midnight)

Note: The exact column names in `stop_observations.txt` may vary — handle flexibly. Log the actual column names found in the file.

**Add a new CLI command** to `backend/app/workers/`:

**Create `backend/app/workers/load_stop_observations.py`**:
```python
#!/usr/bin/env python3
"""
Usage:
  python -m app.workers.load_stop_observations              # Load last 3 months
  python -m app.workers.load_stop_observations --backfill   # Load all history (2022-03 to now)
  python -m app.workers.load_stop_observations --month 2026-03  # Load specific month
"""
```

**Add to `run_data_jobs.py`** a step 12: call `load_missing_months(conn, months_back=1)` — loads the previous month if not already loaded. Put this after step 11.

**Add to `main.py`** a new endpoint:
```
GET /observations/status
```
Returns: `{months_loaded: ["2022-03", ...], total_rows: 12345678, earliest_month: "2022-03", latest_month: "2026-04"}`
```

--- DONE

### Prompt 2.2 — Cross-Agency OTP Benchmarking Dashboard

```
I'm working on the BATIS project at \\wsl.localhost\ubuntu\home\mza\projects\batis

Read CLAUDE.md, PROGRESS.md, and BLUEPRINT.md first.

**Goal**: Build a cross-agency on-time performance benchmarking feature using the stop_observations table.

**Backend: Add new endpoint** in `backend/app/main.py`:

```
GET /benchmarks/agency-otp
  Params: start_date (required), end_date (required)
  Auth: API key required
  Returns: [
    {
      agency_id: str,
      agency_name: str,
      total_observations: int,
      on_time_count: int,
      on_time_pct: float,        -- 0-100
      avg_delay_seconds: float,
      median_delay_seconds: float,
      p90_delay_seconds: float,  -- 90th percentile delay
      trend: float               -- change in on_time_pct vs prior equal-length period (positive = improving)
    }
  ]
  Sorted by on_time_pct descending.
```

Add the corresponding query function `get_agency_otp_benchmarks(start_date, end_date, conn)` in `backend/app/services/analysis.py`.

The query should use the `stop_observations` table (not `ops_trip_events`). Group by `agency_id`. Compute `on_time` rate (the generated column). Compute `trend` by comparing to the prior period of equal length.

Agency name lookup (hardcode in the function):
```python
AGENCY_NAMES = {
    "AC": "AC Transit", "BA": "BART", "SF": "Muni/SFMTA",
    "CT": "Caltrain", "SM": "SamTrans", "GG": "Golden Gate Transit",
    "WH": "SF Bay Ferry (WETA)", "VN": "VTA", "SC": "Sonoma County Transit",
    "MA": "Marin Transit", "WC": "WestCAT", "CC": "County Connection"
}
```

**Frontend: New "Benchmarks" section**

1. Add `'benchmarks'` to the `Section` type in `App.tsx`
2. Add a "Benchmarks" tab in the header nav
3. Create `frontend/src/components/BenchmarkPanel.tsx`:
   - Fetch from `GET /benchmarks/agency-otp` using the current date range
   - Render a horizontal bar chart (Recharts `BarChart` horizontal) showing on-time % per agency
   - Sort bars from best to worst
   - Colour bars green (>90% OTP), yellow (75-90%), red (<75%)
   - Show a trend arrow (▲▼) next to each bar — green if improving, red if declining
   - Show the three KPIs at top: Best Agency, Worst Agency, Regional Average OTP
   - Add a data table below the chart with all metrics including avg/median/p90 delay
4. No map layer needed for the Benchmarks section (set `fetchSection('benchmarks')` to make no API call in MapView)
```

--- DONE

### Prompt 2.3 — Schedule Drift Detection

```
I'm working on the BATIS project at \\wsl.localhost\ubuntu\home\mza\projects\batis

Read CLAUDE.md first.

**Goal**: Detect when a route's actual run times have drifted from the scheduled run times — a signal that the schedule needs updating.

**Backend: Add new endpoint**:

```
GET /schedule-drift/{agency_id}/{route_id}
  Params: months_back (default: 3)
  Auth: API key required
  Returns: {
    agency_id: str,
    route_id: str,
    route_short_name: str,
    analysis_months: int,
    segments: [
      {
        from_stop_id: str,
        from_stop_name: str,
        to_stop_id: str,
        to_stop_name: str,
        direction_id: int,
        scheduled_run_minutes: float,
        actual_run_minutes_avg: float,
        actual_run_minutes_p90: float,
        drift_pct: float,           -- (actual - scheduled) / scheduled * 100
        drift_flag: bool,           -- true if drift_pct > 15%
        sample_size: int
      }
    ],
    overall_drift_pct: float,
    recommendation: str             -- e.g. "Add 8 min to AM peak schedule on segments X, Y"
  }
```

Add query function `get_schedule_drift(agency_id, route_id, months_back, conn)` in `analysis.py`.

The query logic:
1. From `stop_observations`, get all (from_stop, to_stop) consecutive pairs for this route in the date range
2. Compute actual run time = `observed_arrival[stop N+1] - observed_arrival[stop N]`
3. Compute scheduled run time = `scheduled_arrival[stop N+1] - scheduled_arrival[stop N]`
4. Group by stop pair + direction, compute avg/p90 actual, avg scheduled
5. Flag segments where `(actual_avg - scheduled) / scheduled > 0.15` (15% drift threshold)
6. Generate a text recommendation based on flagged segments

**Frontend: Add "Drift" sub-panel to Route Explorer**

In `components/Sidebar.tsx` → `RouteExplorerPanel`:
- After selecting a route, add a "Schedule Health" section below the headway chart
- Add a "Check Schedule Drift" button that fetches `/schedule-drift/{agency_id}/{route_id}`
- Show a small table of flagged segments with drift % (colour-coded red/yellow/green)
- Show the overall recommendation text in a callout box
```

--- DONE

## SPRINT 3 — Traffic, Tolls & Work Zones

### Prompt 3.1 — Traffic Events + Work Zone Ingestor

```
I'm working on the BATIS project at \\wsl.localhost\ubuntu\home\mza\projects\batis

Read CLAUDE.md first.

**Goal**: Ingest 511.org traffic events, work zones, and toll rates into the database.

**Create new file**: `backend/app/services/five11_traffic.py`

```python
"""
511.org Traffic & Toll data ingestor.

Endpoints:
  Traffic events: https://api.511.org/traffic/events?api_key={key}
  Work zones:     https://api.511.org/traffic/wzdx?api_key={key}
  Toll rates:     https://api.511.org/toll/programs?api_key={key}
"""
```

Implement:

1. **`load_traffic_events(conn) -> int`**
   - Fetch: `GET https://api.511.org/traffic/events?api_key={key}`
   - Returns JSON array of events
   - Each event has: `id`, `event_type`, `severity`, `geography` (GeoJSON Point), `headline`, `roads[0].name`, `created`, `updated`, `schedule.start_time`, `schedule.end_time`
   - Upsert into `traffic_events` table (ON CONFLICT event_id DO UPDATE)
   - Return count of rows upserted

2. **`load_work_zones(conn) -> int`**
   - Fetch: `GET https://api.511.org/traffic/wzdx?api_key={key}`
   - Returns GeoJSON FeatureCollection (WZDx format)
   - Each feature: `id`, geometry (LineString or MultiLineString), `properties.road_name`, `properties.description`, `properties.start_date`, `properties.end_date`
   - Upsert into `work_zones` table
   - Return count upserted

3. **`load_toll_rates(conn) -> int`**
   - Fetch: `GET https://api.511.org/toll/programs?api_key={key}`
   - Parse toll facility rates (Bay Bridge, Carquinez, Dumbarton, San Mateo, SR-92, Express Lanes)
   - Insert into `toll_rates` (new row for each snapshot — don't upsert, track history)
   - Return count inserted

4. **`run_traffic_loop(interval_seconds: int, stop_event)`**
   - Loop: load_traffic_events, load_work_zones, load_toll_rates
   - Interval: 300 seconds (5 minutes)
   - Log counts after each load

**Add the traffic ingestor thread to `backend/app/main.py`**:
- Add a 4th background thread named `traffic-ingestor` in `lifespan()`
- Use the same pattern as the existing background threads

**Add new endpoints** to `main.py`:
```
GET /traffic/events    → returns active traffic_events as GeoJSON FeatureCollection
GET /traffic/work-zones → returns active work_zones as GeoJSON FeatureCollection
GET /traffic/toll-rates → returns latest toll_rates for each facility
```

**Add map layers** to `frontend/src/components/MapView.tsx`:
- Add `traffic-events-layer`: red warning triangles at each active incident location
- Add `work-zones-layer`: orange dashed lines along work zone routes
- Show these layers in a new "Traffic" section (add to Section type and nav tabs)
```

--- DONE

### Prompt 3.2 — Work Zone Transit Impact Predictor

```
I'm working on the BATIS project at \\wsl.localhost\ubuntu\home\mza\projects\batis

Read CLAUDE.md and BLUEPRINT.md first.

**Goal**: When a road closure or major incident is active, predict which bus routes will be delayed.

**Backend: Add new endpoint**:

```
GET /traffic/transit-impact
  Auth: API key required
  Returns: [
    {
      event_id: str,
      event_type: str,              -- "accident", "roadwork", etc.
      road_name: str,
      severity: str,
      affected_routes: [
        {
          route_id: str,
          agency_id: str,
          route_short_name: str,
          affected_stops: [stop_id],
          proximity_meters: float,
          historical_avg_delay_seconds: float,  -- from stop_observations on this segment
          alert_level: str                       -- "warning" | "critical"
        }
      ]
    }
  ]
  Only returns events with at least one affected route.
```

Add query function `get_traffic_transit_impact(conn)` in `analysis.py`:

1. Fetch active traffic events and work zones from their DB tables (where `end_time > NOW() OR end_time IS NULL`)
2. For each event geometry, find bus stops within 800m using PostGIS: `ST_DWithin(stop.geom::geography, event.geom::geography, 800)`
3. For each affected stop, find which routes serve it (from `gtfs_stop_times`)
4. From `stop_observations`, get the historical average delay on that route at that stop for the same day-of-week + hour-of-day (last 12 weeks)
5. Classify: `alert_level = "critical"` if `historical_avg_delay > 300s` on this segment, `"warning"` otherwise
6. Return grouped by event_id

**Frontend: New "Traffic Impact" panel** in `components/Sidebar.tsx`:
- Show in the Traffic section (new tab from Prompt 3.1)
- List each active event with its affected routes and estimated additional delay
- Each affected route shown as a coloured chip matching its route_color
- Sort by severity: critical events first
- Refresh every 5 minutes

**Map layer**: In MapView.tsx, when in "traffic" section, highlight affected route shapes in red/orange (fetch `/routes/{route_id}/geo` for each affected route and change line colour based on `alert_level`)
```

--- DONE

## SPRINT 4 — Equity Intelligence

### Prompt 4.1 — Fix Real Equity Analysis

```
I'm working on the BATIS project at \\wsl.localhost\ubuntu\home\mza\projects\batis

Read CLAUDE.md and PROGRESS.md first.

**Goal**: Fix the equity analysis so it actually works (currently equity_score is always NULL).

The problem:
- `populate_equity_columns()` in `equity_loader.py` applies a county-average equity score to all coverage cells, but filters `WHERE population > 0` — and the `population` column is never set. Result: zero rows updated.

**Fix `backend/app/services/equity_loader.py`**:

1. Remove the `WHERE population > 0` filter
2. Instead of a single county average, do a PROPER per-tract spatial join:
   - After fetching Census data (poverty_rate, no_car_pct per tract + county FIPS), we don't have tract geometries
   - Alternative: fetch Census data at the **block group** level (smaller geographic unit available from ACS API)
   - Use Census variable `B19013_001E` (median household income) and `B08201_002E` (no vehicle households)
   - Group by county + tract approximate matching using GEOID prefix
   - Apply to coverage cells by nearest county (Alameda vs Contra Costa)

3. Expand equity coverage to all Bay Area counties:
   - Add to `_COUNTIES`: `"06075"` (San Francisco), `"06081"` (San Mateo), `"06085"` (Santa Clara), `"06097"` (Sonoma), `"06055"` (Napa), `"06095"` (Solano), `"06041"` (Marin)
   - This gives equity coverage for the full 9-county Bay Area

4. Set a reasonable default for cells that can't be spatially matched:
   - `equity_score = 0.5` (neutral) for cells outside all county data

5. Also populate the `population` column:
   - Use Census variable `B01001_001E` (total population) at the county level divided by estimated cell count
   - This is still an approximation but makes the column non-null

**Add new endpoint**: `GET /equity/score`
- Returns GeoJSON FeatureCollection of coverage_cells with equity_score coloring
- Each feature has properties: `equity_score`, `low_income_population`, `no_car_households`, `equity_tier` (low/medium/high/very_high)

**Add "Equity" section to frontend** (`App.tsx` + `Sidebar.tsx`):
- New `'equity'` section in nav tabs
- New `EquityPanel` component in Sidebar:
  - Shows regional equity summary: % of Bay Area population in high-need areas
  - Shows top 10 highest-equity-need zones (cell_id + location description)
  - Links to service delivery gap analysis once Sprint 4 is complete
- MapView: add `equity-fill` layer that colours coverage cells by `equity_score` (low income = deeper red)
```

---

### Prompt 4.2 — Service Delivery Gap Analysis

```
I'm working on the BATIS project at \\wsl.localhost\ubuntu\home\mza\projects\batis

Read CLAUDE.md and BLUEPRINT.md first.

**Goal**: The flagship equity feature — compare actual service delivery (from stop_observations) with scheduled service by equity score.

This answers: "In high-need areas, is transit actually delivered as promised?"

**Backend: Add new endpoint**:

```
GET /equity/service-delivery-gap
  Params: start_date, end_date, agency_id (optional)
  Auth: API key required
  Returns: GeoJSON FeatureCollection where each feature is a coverage cell with:
    properties: {
      cell_id: str,
      equity_score: float,           -- 0-1, higher = more need
      equity_tier: str,              -- "very_high" | "high" | "medium" | "low"
      scheduled_trips_per_day: float,
      actual_trips_per_day: float,   -- from stop_observations (observed_arrival IS NOT NULL)
      service_delivery_rate: float,  -- actual / scheduled * 100
      avg_delay_seconds: float,      -- from stop_observations in this cell
      delivery_gap_score: float,     -- equity_score * (1 - service_delivery_rate/100) → higher = more concerning
      stop_ids: [str]                -- stops in this cell
    }
```

Add query function `get_service_delivery_gap(start_date, end_date, agency_id, conn)` in `analysis.py`:
1. Join `coverage_cells` → `gtfs_stops` (stops within each cell via ST_Within)
2. For each cell's stops, count scheduled trips from `gtfs_stop_times` (per day average)
3. For each cell's stops, count actual observed trips from `stop_observations` in date range
4. Compute `service_delivery_rate = actual / scheduled * 100`
5. Join with `coverage_cells.equity_score`
6. Compute `delivery_gap_score = equity_score * (100 - service_delivery_rate) / 100`
7. Return as GeoJSON with cells coloured by `delivery_gap_score`

**Frontend**:
- In the new "Equity" section, add a toggle: "Coverage Map" vs "Delivery Gap"
- "Delivery Gap" view: same hex grid but coloured by `delivery_gap_score` (white=no gap, dark red=high-need + poor delivery)
- Add to EquityPanel: "Top 5 Service Delivery Gaps" — list the cells with worst scores, show their equity_tier and delivery rate
- Add a callout: "Routes serving underperforming cells" — list routes with stops in the worst 10 cells
```

---

## SPRINT 5 — AI Upgrades

### Prompt 5.1 — Multi-Agency AI Assistant + Daily Brief

```
I'm working on the BATIS project at \\wsl.localhost\ubuntu\home\mza\projects\batis

Read CLAUDE.md first.

**Goal**: Upgrade the AI assistant to cover all Bay Area agencies and add a daily operational briefing.

**Part A: Multi-Agency Embeddings**

Update `backend/ml/embed.py`:

1. `_build_route_texts()`: currently only builds for AC Transit routes. Update to loop over all agencies: for each agency, build route descriptions. Add `agency_id` and agency name to the description text so RAG can find it.

2. `_build_stop_texts()`: currently limited to 2000 stops. Change to paginated approach (fetch in batches of 500, no hard limit). Include agency name in the text.

3. **Add new function** `_build_observation_summaries(conn)`:
   - For each agency + route, build a monthly performance summary from `stop_observations`:
     - "Route 1T (AC Transit) — April 2026: 87% on-time, average delay 2.3 minutes, worst segment: stop X to Y"
   - Build for the most recent 3 months
   - Upsert into `ai_embeddings` with `content_type='obs_summary'`

**Part B: Conversational History**

Update `backend/app/services/ai_assistant.py`:
1. Change `ask(conn, question, top_k)` to `ask(conn, question, top_k, history: list[dict] = None)`
2. If `history` is provided, prepend conversation turns to the Ollama prompt:
   ```
   Previous conversation:
   User: {prior question}
   Assistant: {prior answer}
   ---
   Current question: {question}
   ```
3. Limit history to last 5 turns to avoid context overflow

Update `POST /ai/ask` endpoint to accept:
```json
{"question": "...", "top_k": 6, "history": [{"role": "user"|"assistant", "content": "..."}]}
```

Update `frontend/src/components/AiAssistant.tsx`:
- Track `history` in state: `{role: 'user'|'assistant', content: string}[]`
- On each send, append the user message to history, send history with the request
- On response, append assistant message to history
- Add a "Clear conversation" button that resets history

**Part C: Daily Operations Briefing**

Add new endpoint: `GET /ai/daily-brief`
- No auth required (it's operational, not sensitive)
- Generates a briefing with:
  1. Active traffic incidents affecting transit routes (from `/traffic/transit-impact`)
  2. Routes with below-85% OTP yesterday (from `stop_observations`)  
  3. Active work zones near major stops (from `work_zones`)
  4. Any agencies with alerts active (from `traffic_events`)
- Assembles all this into a prompt and sends to Ollama
- Returns: `{briefing_text: str, generated_at: str, data_freshness: {...}}`

Add a "Daily Brief" button to the top of `AiAssistant.tsx`:
- Clicking it calls `GET /ai/daily-brief`
- Displays the briefing text in the chat as an assistant message
- Show the timestamp of generation
```

---

## SPRINT 6 — Transfer Reliability & Fare Intelligence

### Prompt 6.1 — Transfer Reliability Matrix

```
I'm working on the BATIS project at \\wsl.localhost\ubuntu\home\mza\projects\batis

Read CLAUDE.md and BLUEPRINT.md first.

**Goal**: For every pair of agencies that share transfer stops, compute the historical probability of successfully making the connection.

**Backend: Add new endpoint**:
```
GET /transfers/reliability
  Params: months_back (default: 3)
  Auth: API key required
  Returns: [
    {
      from_agency: str,
      to_agency: str,
      transfer_stop_id: str,
      transfer_stop_name: str,
      scheduled_transfer_minutes: float,    -- from GTFS stop_times
      avg_actual_gap_minutes: float,        -- from stop_observations: time between agencies' actual arrivals
      success_rate_pct: float,             -- % of times connection made within 5 min of scheduled
      n_observations: int,
      best_time_of_day: str,               -- hour where success rate is highest
      worst_time_of_day: str               -- hour where success rate is lowest
    }
  ]
```

Query logic for `get_transfer_reliability(months_back, conn)` in `analysis.py`:
1. Find stops served by 2+ different agencies: `SELECT stop_id FROM gtfs_stops GROUP BY stop_id HAVING COUNT(DISTINCT agency_id) > 1`
2. For each such stop, find all pairs of agency arrivals within a 15-minute window in `stop_observations`
3. For each pair (BART arrives at T, AC bus arrives at T+X), check if X is within the scheduled transfer window
4. The scheduled transfer window = `next_departure - prior_arrival` from `gtfs_stop_times`
5. Group by (from_agency, to_agency, stop_id), compute success_rate

**Frontend: Transfer Reliability Heat Map**

Create `frontend/src/components/TransferPanel.tsx`:
- Add `'transfers'` to Section type and nav tabs
- Show a matrix table (agencies on rows and columns)
- Each cell shows the success rate % for transferring from row-agency to column-agency
- Cell colours: green (>90%), yellow (70-90%), orange (50-70%), red (<50%), grey (no data)
- Clicking a cell shows a detail panel: which stops support this transfer, best/worst time of day

Map layer: When "transfers" section is active, show transfer stop locations as large diamonds coloured by their overall transfer success rate.
```

---

## ONGOING — Hardening Prompts

### Prompt H.1 — Add Backend Tests

```
I'm working on the BATIS project at \\wsl.localhost\ubuntu\home\mza\projects\batis

Read CLAUDE.md first.

**Goal**: Add a comprehensive pytest test suite for the backend.

Create `backend/tests/` directory with:

1. `conftest.py`:
   - Create a test PostgreSQL database fixture (uses a separate test DB)
   - Apply schema.sql to the test DB before tests run
   - Seed minimal test data: 2 routes, 5 stops, 10 trips, 50 stop_times, 20 ops_trip_events
   - Provide an `httpx.AsyncClient` fixture pointing at the FastAPI test app

2. `test_routes.py` — test all /routes/* endpoints:
   - `GET /routes` returns a list of routes
   - `GET /routes/{route_id}/geo` returns GeoJSON for a valid route_id, 404 for invalid
   - `GET /routes/compare` is reachable (not shadowed by parameterised route)
   - `GET /routes/{route_id}/headways` returns an empty list if no ops data

3. `test_reliability.py` — test all /reliability/* endpoints:
   - `GET /reliability/summary` returns correct on_time_pct for seeded data
   - `GET /reliability/stops/geo` returns GeoJSON
   - `GET /reliability/trend` returns a list sorted by date

4. `test_safety.py`:
   - `compute_stop_safety_scores()` with `buffer_meters=150` matches only incidents within 150 meters (not 150 degrees)
   - Test with synthetic incident placed 100m from a stop and 200m from another stop

5. `test_trip_planner.py`:
   - Valid origin/dest returns at least one itinerary
   - Invalid lat/lng returns 422

6. `test_ai.py`:
   - `GET /ai/status` returns a dict with `ollama_running` key
   - `POST /ai/ask` with missing question returns 422

Add `pytest.ini` and configure: testpaths=tests, asyncio_mode=auto

Add test command to a `Makefile`:
```makefile
test:
    cd backend && pytest tests/ -v --tb=short
```
```

---

### Prompt H.2 — Docker Compose Setup

```
I'm working on the BATIS project at \\wsl.localhost\ubuntu\home\mza\projects\batis

Read CLAUDE.md first.

**Goal**: Create a Docker Compose setup so the full stack can be started with one command.

Create `docker-compose.yml` at the project root:

```yaml
version: '3.9'
services:
  postgres:
    image: postgis/postgis:16-3.4
    environment:
      POSTGRES_DB: bay_area_transit_intel
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-batis_dev}
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./backend/sql/schema.sql:/docker-entrypoint-initdb.d/01_schema.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 3s
      retries: 10

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://postgres:${POSTGRES_PASSWORD:-batis_dev}@postgres:5432/bay_area_transit_intel
      FIVE11_API_KEY: ${FIVE11_API_KEY}
      BACKEND_API_KEY: ${BACKEND_API_KEY:-}
      OLLAMA_URL: http://host.docker.internal:11434
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - ./backend:/app
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "5173:5173"
    environment:
      VITE_MAPBOX_TOKEN: ${VITE_MAPBOX_TOKEN}
      VITE_API_BASE_URL: http://localhost:8000
    volumes:
      - ./frontend/src:/app/src

volumes:
  postgres_data:
```

Create `backend/Dockerfile`:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Create `frontend/Dockerfile`:
```dockerfile
FROM node:20-slim
WORKDIR /app
COPY package*.json .
RUN npm install
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
```

Create `.env.example` at the project root documenting all required variables.

Create `Makefile` with commands:
```makefile
up:       docker compose up -d
down:     docker compose down
logs:     docker compose logs -f
seed:     docker compose exec backend python -m app.workers.run_data_jobs
migrate:  docker compose exec backend psql $$DATABASE_URL -f sql/migrations/001_multi_agency.sql
test:     cd backend && pytest tests/ -v
```
```

---

## Quick Reference — Implementation Order

```
Sprint 0 (Fix bugs):
  → Prompt 0.1  Backend critical bugs
  → Prompt 0.2  Frontend issues  
  → Prompt 0.3  Socrata pagination + safety

Sprint 1 (511.org):
  → Prompt 1.1  Schema migration (run this against your DB first)
  → Prompt 1.2  511.org RT ingestor (replaces AC Transit direct)
  → Prompt 1.3  511.org multi-agency GTFS static loader
  → Prompt 1.4  Multi-agency alerts + live stop ETAs
  → Prompt 1.5  Frontend multi-agency updates

Sprint 2 (Stop Observations):
  → Prompt 2.1  Stop observations downloader + DB loader
  → Prompt 2.2  Cross-agency OTP benchmarking dashboard
  → Prompt 2.3  Schedule drift detection

Sprint 3 (Traffic & Tolls):
  → Prompt 3.1  Traffic events + work zone ingestor
  → Prompt 3.2  Work zone transit impact predictor

Sprint 4 (Equity):
  → Prompt 4.1  Fix real equity analysis (proper Census spatial join)
  → Prompt 4.2  Service delivery gap analysis

Sprint 5 (AI):
  → Prompt 5.1  Multi-agency AI + daily brief + conversational history

Sprint 6 (Transfers):
  → Prompt 6.1  Transfer reliability matrix

Ongoing:
  → Prompt H.1  Backend tests
  → Prompt H.2  Docker Compose
```

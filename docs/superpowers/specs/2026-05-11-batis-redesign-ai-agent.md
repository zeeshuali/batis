# BATIS 2.0 — Dashboard Redesign + AI Agent Companion

**Date:** 2026-05-11
**Status:** Design approved, pending implementation plan
**Owner:** mza

---

## Context

BATIS today is a 14-tab atlas — every transit question maps to a pre-built chart, and novel questions require new code. The current shell (`App.tsx`, `Sidebar.tsx` at ~1,862 lines, `MapView.tsx` at ~1,101 lines) is organized by data feature, not by user job; there is no landing surface, no cross-filtering, and the existing AI Assistant is a one-shot RAG widget against a single agency's narrative corpus.

The goal of this redesign is to turn BATIS into a **dashboard-first BI product** with polish and density comparable to Stripe Dashboard, Tableau, and Power BI, with a **single AI Agent companion** that operators, planners, and equity researchers can use to get insights without writing SQL. The Agent is a feature inside the product; the dashboard remains the product.

The intended outcome: a transit analyst can open BATIS, immediately see what needs their attention on an Overview, navigate to five well-designed sections organized by the questions they actually ask, and at any point ask the Agent for an explanation, comparison, or ad-hoc analysis with full provenance.

**Not in scope:** rider-facing features, chat-first product framing, multi-agent orchestration, schema migrations beyond what the Agent layer requires.

---

## 1 — Product surfaces

### 1.1 Five dashboard sections (replacing 14 tabs)

Organized by user job, not by data feature.

| Section | Job it answers | Absorbs today's tabs |
|---|---|---|
| **Overview** | "What needs my attention today?" — headline KPIs, anomalies, active alerts, regional health | (new — no current equivalent) |
| **Operations** | "How is the network performing now and over the past week?" | Reliability, Bunching, Live Vehicles, Crowding, Comparison |
| **Network** | "What does the network look like, and where does it serve?" | Routes, Coverage, Trip Planner |
| **Equity & Safety** | "Where is service delivery failing the people who need it most?" | Equity, Safety |
| **Benchmarks & Drift** | "How do agencies compare, and where is the schedule drifting?" | Benchmarks, Demand, Traffic |

Each section is a multi-widget dashboard: KPI strip → hero map or chart → 2–4 supporting charts → paginated data table. All share:

- A **global filter bar** (date range, agencies, route search) above the section content
- **Cross-filtering**: clicking a route in any chart filters every other chart and the map in the same section
- **Per-widget actions**: CSV export, PNG export, "Ask the Agent about this", pin to a thread

### 1.2 Agent rail (persistent, collapsible)

A right-side rail at ~25% width, always visible by default, collapsible to an icon strip via a chevron toggle. Contains, top to bottom:

- **Suggested questions** — 3–5 chips, context-aware to the current section/selection
- **Ask input** — single-line composer; press Enter to send
- **Conversation history** — current thread, scrollable, with tool-call disclosure blocks (collapsed by default)
- **Recent threads** — links to past conversations and pinned briefs

Conventions:
- **Tool-call disclosure** under every Agent response (collapsed): "▶ 3 tool calls" expands to show exact SQL, endpoint URLs, RAG hits
- **Citations**: every numeric claim in narrative text wraps its source query result
- **Pin-to-section**: any chart or map the Agent renders inline has a "Pin to Operations" button; pinned cards persist on the dashboard

### 1.3 Visual design direction

Reference quality bar: **Stripe Dashboard** (density without noise), **Vercel/Linear analytics** (typography and color discipline), **Mapbox Studio gallery** (map polish, especially in dark mode).

Concrete requirements:
- Design tokens for type scale, spacing scale, and semantic colors (success/warn/critical/info), with dark + light parity
- KPI cards with sparkline, period delta, and threshold coloring — not flat tiles
- Maps as hero elements with proper legends, hover affordances, and legend-driven filtering
- Calm motion: skeleton loading, smooth filter transitions, no flicker
- Saveable views (named filter+selection combos) with shareable URLs

---

## 2 — The Agent

### 2.1 Capabilities (six verbs)

| Verb | Trigger | Output |
|---|---|---|
| **Explain** | "Why is OTP 87%?" / click ⓘ on a KPI | Narrative + the producing SQL, cited |
| **Compare** | "vs. last month" / "vs. AC Transit average" | Side-by-side numbers + small inline chart |
| **Investigate** | "What changed Tuesday?" | Ranked probable causes with evidence from ops, traffic, alerts |
| **Build** | "Show toll spikes vs. Transbay ridership" | Inline chart; "Pin to section" button persists it |
| **Brief** | "Generate tomorrow's 9am ops brief" or scheduled | Multi-section markdown report with embedded charts |
| **Search** | "/catalog stops" | Semantic + structured lookup over the data catalog |

### 2.2 Tool registry (six tools)

A single Claude tool-use call. The registry is kept small on purpose for reliable tool selection.

```
query_view(view_name, filters, dims, limit)  → table     # curated SQL views only
call_endpoint(endpoint, params)              → json      # wraps existing FastAPI routes
search_knowledge(query, k)                   → chunks    # existing pgvector RAG
render_chart(data, encoding)                 → ChartSpec # Recharts-compatible spec
render_map_layer(geojson, paint)             → MapLayer  # adds to current map
pin_artifact(artifact, section, title)       → id        # saves to dashboard
```

The Agent never writes raw SQL against base tables. All reads go through `query_view` against the `agent_views` schema.

### 2.3 Always-on context

Every Agent turn receives a structured context blob alongside the user message:

```json
{
  "section": "operations",
  "filters": { "date_range": ["2026-04-01", "2026-04-07"], "agencies": ["AC", "BART"] },
  "selection": { "route_id": "51B", "stop_id": null },
  "visible_cards": ["route-otp-trend", "worst-routes-table", "live-vehicles-map"],
  "recent_actions": ["clicked Route 51B", "filtered to AC Transit only"]
}
```

This is how "Why is this dipping?" resolves "this" without the user spelling it out. Cursor's active-selection trick, applied to dashboards.

### 2.4 One Agent, multiple triggers

Proactive features (morning briefs, anomaly callouts) are **the same Agent invoked by a cron** with a system-generated prompt, not separate agents. Same model, same tools, same audit log — only the trigger differs.

---

## 3 — Model substrate

### 3.1 Default stack

| Path | Model | Notes |
|---|---|---|
| Agent (all verbs) | **Claude Haiku 4.5** | Anthropic API, sole production model |
| Embeddings | **all-MiniLM-L6-v2** | Already wired through pgvector ivfflat (50 lists); no change |
| Local-only install (opt-in) | Ollama llama3.1:8b | Env-flagged fallback; not the default; quality not guaranteed |

No Sonnet, no Opus, no model routing in v1. If Haiku ever proves insufficient for a specific verb, a Sonnet escape hatch can be added later as an opt-in.

### 3.2 Cost control

Four layers, applied in this order:

1. **Pre-LLM intent filter** — hard-coded classifier rejects off-topic prompts before any model call
2. **Prompt caching** on system prompt + data catalog (~10K tokens, 5-min ephemeral cache via `cache_control`)
3. **Per-verb response budgets** enforced server-side: Explain 250 tokens, Compare 400, Investigate 800, Brief 1500
4. **Tool result trimming**: `query_view` returns capped to 50 rows + summary stats; large tables paginated rather than streamed into context

**Projected per-question cost** (Haiku 4.5 with caching):

| Verb | Cost |
|---|---|
| Explain | ~$0.005 |
| Compare | ~$0.01 |
| Build | ~$0.02 |
| Investigate | ~$0.03 |
| Brief | ~$0.08 |

Analyst-scale economics: ~$25/month per heavy user (50 questions/day), ~$250/month for a 10-seat team.

### 3.3 Transparency

- **Tool-call disclosure** under every response, collapsed by default
- **Citation per numeric claim** in narrative output
- All token counts and cost recorded in the `agent_runs` audit table

---

## 4 — Data layer

Three new components. None modify the existing 18 tables; they sit on top.

### 4.1 Curated views: `agent_views` schema

The Agent reads only from this namespace. Initial set (~12 views), examples:

| View | Purpose | Base tables |
|---|---|---|
| `agent_route_reliability_daily` | OTP, avg delay, sample size by route × day × agency | `ops_trip_events`, `stop_observations` |
| `agent_stop_safety_with_equity` | Per-stop safety + nearest tract equity (geometry bug fixed in view) | `stop_safety_scores`, `coverage_cells` |
| `agent_active_disruptions` | Alerts + work zones + traffic events with affected routes | `service_alerts`, `traffic_events`, `work_zones`, `gtfs_shape_geoms` |
| `agent_anomaly_today` | Routes whose today's OTP is >2σ from 30-day baseline | `ops_trip_events` rolling stats |
| `agent_agency_otp_30d` | Cross-agency OTP scorecard, 30-day window | `stop_observations` |
| `agent_transbay_corridor` | Transbay routes joined with bridge toll history (post-511.org) | `gtfs_routes`, `toll_rates`, `ops_trip_events` |

Views are versioned by suffix (`_v2`). The catalog (4.2) tracks current versions; pinned artifacts and scheduled briefs bind to a specific version.

**Why views, not raw tables:** the safety geometry bug, equity_score NULL bug, and synthetic-vs-real-data caveats from GAPS.md are encapsulated once in the view layer. The Agent sees clean inputs.

### 4.2 Data catalog: `backend/agent/catalog.json`

Single JSON document describing every view: name, purpose, columns with types, valid filter dimensions, 2–3 example natural-language questions per view. Generated by a build script from view DDL + hand-curated annotations.

Consumed by three surfaces:
- Agent system prompt (loaded once per session, cached)
- Library "Data catalog" drawer (rendered for humans)
- `/catalog` slash command in the rail

### 4.3 Audit log + session state

```sql
CREATE TABLE agent_sessions (
  id uuid PRIMARY KEY,
  user_id text,
  started_at timestamptz,
  context jsonb
);

CREATE TABLE agent_runs (
  id bigserial PRIMARY KEY,
  session_id uuid REFERENCES agent_sessions(id),
  turn_idx int,
  user_message text,
  tool_calls jsonb,
  response_text text,
  input_tokens int,
  output_tokens int,
  cached_tokens int,
  cost_usd numeric(10,6),
  created_at timestamptz DEFAULT now()
);

CREATE TABLE pinned_artifacts (
  id uuid PRIMARY KEY,
  section text,
  title text,
  spec jsonb,
  source_session uuid REFERENCES agent_sessions(id),
  pinned_by text,
  created_at timestamptz DEFAULT now()
);

CREATE TABLE scheduled_briefs (
  id uuid PRIMARY KEY,
  prompt text,
  cadence text,            -- cron expression
  recipients jsonb,
  next_run timestamptz,
  last_run timestamptz,
  enabled boolean DEFAULT true
);
```

`agent_runs` is mandatory: it powers cost tracking, debugging, and the "show me how" disclosure.

---

## 5 — What survives and what dies in the existing code

### Survives (refactor, not rewrite)
- `frontend/src/components/MapView.tsx` — already factored into 14 named sources + per-section layer groups (lines 41–60); becomes the generic `MapArtifact` renderer driven by `render_map_layer` specs
- `frontend/src/lib/agencies.ts` — agency list/colors carry over unchanged
- Primitives in `frontend/src/components/Sidebar.tsx`: `KpiCard()` (~line 19), data-list rows, Recharts wrappers — extracted to a `frontend/src/components/primitives/` module
- All 29 FastAPI routes in `backend/app/main.py` — exposed to the Agent via `call_endpoint`
- Existing pgvector RAG pipeline (`backend/app/services/ai_assistant.py`, `backend/ml/embed.py`) — `search_knowledge` tool reuses it
- Service alerts and stop drawer components — reusable as widgets
- `backend/app/core/config.py` Settings, `backend/app/core/security.py` X-API-Key — extended, not replaced

### Demolished
- `frontend/src/App.tsx` 14-section nav (lines 60–93) — replaced with 5-section nav + filter bar + Agent rail
- The per-section panel router in `Sidebar.tsx` (the ~1,862-line file mostly empties out)
- The current `AiAssistant.tsx` one-shot widget — replaced by the rail UI; backend `/ai/ask` evolves into the tool-using Agent endpoint
- The current implicit "active section drives all data fetches" pattern — replaced by section components that subscribe to a shared filter/selection context

### Added
- `frontend/src/sections/` — one component per dashboard section (Overview, Operations, Network, EquitySafety, BenchmarksDrift)
- `frontend/src/agent/` — rail UI, conversation thread, tool-call disclosure, citation rendering, pin-to-section
- `frontend/src/context/` — global filter context, selection context
- `frontend/src/design/` — design tokens, typography, color, primitives
- `backend/agent/` — Haiku client, tool registry implementations, catalog.json, prompt builder
- `backend/sql/migrations/002_agent_views.sql` and `003_agent_runtime.sql`

---

## 6 — Phased roadmap

| Phase | Scope | Depends on | Ship signal |
|---|---|---|---|
| **0. Bug bash** | Fix 6 known critical bugs from CLAUDE.md (route ordering, geometry units, pgvector ext, requirements.txt, equity_score, live ETAs) | — | All endpoints pass smoke tests |
| **1. Dashboard shell** | New 5-section nav, design system, global filter bar, cross-filter context, salvaged primitives, Overview home page | Phase 0 | Users see "BATIS 2.0" without the Agent |
| **2. Agent foundation** | `agent_views` (first 6 views), `catalog.json`, `agent_sessions` + `agent_runs`, Haiku 4.5 wiring, 6-tool registry, rail UI, Explain + Search verbs | Phase 1 | Smallest end-to-end Agent loop working |
| **3. Agent v1** | Compare, Investigate, Build verbs; tool-call disclosure; citations; pin-to-section | Phase 2 | Daily-use-ready Agent |
| **4. Briefs + scheduling** | Brief verb; `scheduled_briefs`; UI to create/manage; optional email/Slack delivery | Phase 3 | Tableau Pulse parity |
| **5. Multi-agency activation** | 511.org integration (Sprint 1 of BLUEPRINT); new views for `stop_observations`, traffic, tolls; agency-aware filters | Phase 4 | The actual BLUEPRINT competitive story |

Each phase ships independently; users see a better product after every one. The Agent does not block the dashboard redesign — Phase 1 is shippable on its own.

---

## 7 — Open questions

These are deliberately deferred to keep the spec stable:

1. **Authentication for the Agent rail** — the current `X-API-Key` model is single-tenant. If BATIS goes multi-tenant, agents need per-user keys and the audit log needs `user_id` populated for real. Out of scope here.
2. **Brief delivery channel** — email vs. Slack vs. in-app only. Phase 4 decision.
3. **Visual design system specifics** — color palette, typography choice, exact spacing scale. Follow-up working session before Phase 1 implementation starts.
4. **Migration path for pinned artifacts when a view is versioned** — define when Phase 2 lands.

---

## 8 — Verification (how we'll know each phase worked)

**Phase 0** — All 6 bugs from CLAUDE.md are closed; `/routes/compare` returns; safety scores are in meters; `pgvector` extension installs cleanly from `schema.sql`; `sentence-transformers` and `httpx` are in `requirements.txt`; `equity_score` populates on at least one cell; StopDrawer renders live departures.

**Phase 1** — Manual smoke: open BATIS, see Overview as the landing page; switch to Operations and confirm cross-filter (click a route, every chart in the section reflects it); apply a date filter once at the top, confirm every widget in the section respects it; toggle light/dark mode and confirm parity. No Agent rail yet, no regressions.

**Phase 2** — Open the rail, type "explain the OTP number"; receive an answer with one `query_view` and one citation; expand the tool-call disclosure and see the SQL; check `agent_runs` table for one row with non-null `cost_usd`. Same for `/catalog stops` returning a relevant view description.

**Phase 3** — Type "compare Route 51B to similar routes" → inline chart appears in the rail with a Pin button; click Pin → the chart persists in the Operations section's Custom widgets band. Type "what changed Tuesday?" → response cites at least one traffic event or alert.

**Phase 4** — Create a scheduled brief from a pinned artifact; confirm it appears in `scheduled_briefs`; manually trigger the cron; new conversation thread appears with the generated brief.

**Phase 5** — Filter the global agency picker to BART; confirm Operations section reflects BART-only data; ask the Agent "compare AC Transit and BART OTP" → response uses `agent_agency_otp_30d` view.

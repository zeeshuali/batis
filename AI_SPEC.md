# BATIS AI System Specification
**Version:** 0.2 — Approved
**Date:** 2026-03-18
**Status:** Approved for implementation
**Hardware:** Intel Core Ultra 9 + NVIDIA RTX 5070 8GB VRAM
**LLM:** Llama 3.2 11B Q4_K_M via Ollama

---

## 1. Goals

Transform BATIS from a static analytics dashboard into a self-learning, locally-operated AI system that:

1. **Predicts** delays, crowding, and demand using models trained on AC Transit's own operational data
2. **Answers** natural language questions about the transit network from the existing database
3. **Explains** anomalies, alerts, and patterns in plain English
4. **Runs entirely on-premises** — no data leaves the system, no ongoing API costs after setup

### Non-Goals
- Training a foundation LLM from scratch (not feasible; not necessary)
- Replacing AC Transit's own operational systems
- Real-time hardware telemetry / IoT integration

---

## 2. Current Data Inventory

| Table | Records (as of 2026-03-18) | Notes |
|---|---|---|
| `ops_trip_events` | 485,496 total; 108,468 with `delay_seconds` | 8 days of RT data — growing daily |
| `rt_vehicle_positions_raw` | 63,283 | Last 2 hours retained (rolling window) |
| `gtfs_stop_times` | 627,703 | Full static schedule |
| `gtfs_trips` | 13,431 | All trips with headsign, direction |
| `gtfs_stops` | 4,717 | With PostGIS geometry |
| `gtfs_routes` | 123 | With color, short name |
| `delay_predictions` | 3,299 | Seeded; schema ready to receive model output |
| `crowding_predictions` | 0 | Schema exists, empty |
| `demand_forecasts` | 0 | Schema exists, empty |

**Key insight:** The GTFS-RT ingestor has been running since 2026-03-10. At ~30s polling, we accumulate ~2,880 ops_trip_events per day. By 2026-04-18 (30 days), we will have ~86K events/day with delay labels — sufficient to train a reliable delay model.

---

## 3. System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        BATIS AI Stack                            │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Layer A: Prediction Models  (backend/ml/)              │    │
│  │  ├── delay_model       XGBoost  → delay_predictions     │    │
│  │  ├── crowding_model    Classifier → crowding_predictions │    │
│  │  └── demand_model      Prophet  → demand_forecasts       │    │
│  └────────────────────────────┬────────────────────────────┘    │
│                               │ writes every 30 min             │
│  ┌────────────────────────────▼────────────────────────────┐    │
│  │  PostgreSQL + pgvector                                   │    │
│  │  ├── Existing tables (ops, gtfs, predictions)            │    │
│  │  └── New: embeddings table (stop/route/alert text)       │    │
│  └────────────────────────────┬────────────────────────────┘    │
│                               │ retrieval context               │
│  ┌────────────────────────────▼────────────────────────────┐    │
│  │  Layer B: Local LLM  (Ollama, localhost:11434)           │    │
│  │  ├── Base model: Llama 3.1 8B (or fine-tuned variant)    │    │
│  │  ├── RAG: pgvector similarity search for context         │    │
│  │  └── Tools: SQL query execution, prediction lookup       │    │
│  └────────────────────────────┬────────────────────────────┘    │
│                               │ JSON                            │
│  ┌────────────────────────────▼────────────────────────────┐    │
│  │  Layer C: FastAPI endpoints  (backend/app/main.py)       │    │
│  │  ├── POST /ai/ask          Natural language query        │    │
│  │  ├── GET  /ai/explain/{route_id}  Anomaly narration      │    │
│  │  └── GET  /ai/status       Model health + versions       │    │
│  └────────────────────────────┬────────────────────────────┘    │
│                               │                                 │
│  ┌────────────────────────────▼────────────────────────────┐    │
│  │  Layer D: Frontend  (React)                              │    │
│  │  ├── AI Assistant panel (new sidebar section)            │    │
│  │  └── Inline anomaly cards on existing panels            │    │
│  └─────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

---

## 4. Layer A — Prediction Models

### 4.1 Delay Prediction Model

**Purpose:** Predict `delay_seconds` for a trip at a given stop, given current conditions.

**Algorithm:** XGBoost regression (gradient boosted trees)
**Library:** `xgboost`, `scikit-learn`, `pandas`
**Training time:** ~5 minutes on CPU with 4 weeks of data
**Inference time:** <5ms per prediction

**Features (inputs):**

| Feature | Source | Notes |
|---|---|---|
| `route_id` | gtfs_trips | Label-encoded |
| `stop_sequence` | gtfs_stop_times | Integer |
| `hour_of_day` | ops_trip_events.actual_arrival | 0–23 |
| `day_of_week` | ops_trip_events.service_date | 0–6 |
| `is_peak` | derived | 7–9am or 4–7pm = 1 |
| `scheduled_headway_s` | ops_headways | Seconds between scheduled trips |
| `historical_avg_delay` | ops_trip_events aggregated | Per (route, stop, hour) |
| `current_delay_at_prev_stop` | ops_trip_events | Most recent obs for this trip |
| `vehicles_on_route` | rt_vehicle_positions_raw | Count of active vehicles on route |

**Target:** `delay_seconds` (continuous regression)
**Secondary target:** `is_late` (binary: delay > 60s) for classification variant

**Training pipeline:** `backend/ml/train_delay_model.py`
**Output artifact:** `backend/ml/models/delay_model_v{date}.pkl`
**Retrain schedule:** Weekly (Sundays, 2am) via cron job
**Minimum data to train:** 14 days of `ops_trip_events` with delay labels (~40K rows)

**Inference:**
- Runs in `backend/ml/inference.py` alongside GTFS-RT ingestor
- Writes output to `delay_predictions` table every 30 minutes
- Model version tracked in `delay_predictions.model_version`

---

### 4.2 Crowding Prediction Model

**Purpose:** Classify expected crowding level (low / medium / high) at a stop for an upcoming trip.

**Algorithm:** LightGBM classifier
**Features:**

| Feature | Source |
|---|---|
| `route_id`, `stop_id` | GTFS |
| `hour_of_day`, `day_of_week` | Derived |
| `is_peak` | Derived |
| `historical_occupancy_mode` | rt_vehicle_positions_raw aggregated |
| `trip_stop_sequence` | gtfs_stop_times |

**Target:** `occupancy_level` (low / medium / high) from `rt_vehicle_positions_raw.occupancy_status`
**Minimum data to train:** 21 days of occupancy data
**Note:** AC Transit GTFS-RT does provide `occupancy_status` — already being stored. At 8 days we have some data but need more for reliable training.

---

### 4.3 Demand Forecasting Model

**Purpose:** Forecast expected boardings per stop per hour for the next 7 days.

**Algorithm:** Facebook Prophet (time-series decomposition)
**Why Prophet:** Handles weekly seasonality, holidays, and missing data automatically — ideal for transit schedules.
**Input:** Aggregated `ops_trip_events` counts per (stop_id, hour, day)
**Output:** `demand_forecasts` table

**One model per route** (123 routes = 123 Prophet models, each trains in ~10s)
**Retrain schedule:** Weekly

---

### 4.4 SQL Baseline (Ship First, Replace Later)

Before any ML model is ready, populate `delay_predictions` with a statistical baseline:

```sql
INSERT INTO delay_predictions (service_date, route_id, predicted_delay_seconds, model_version)
SELECT
    CURRENT_DATE,
    route_id,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY delay_seconds) AS predicted_delay_seconds,
    'sql-baseline-v1'
FROM ops_trip_events
WHERE delay_seconds IS NOT NULL
  AND service_date >= CURRENT_DATE - INTERVAL '14 days'
  AND EXTRACT(DOW FROM service_date) = EXTRACT(DOW FROM CURRENT_DATE)
  AND EXTRACT(HOUR FROM actual_arrival AT TIME ZONE 'America/Los_Angeles')
      = EXTRACT(HOUR FROM NOW() AT TIME ZONE 'America/Los_Angeles')
GROUP BY route_id;
```

This gives the app real predictions from day one using the same-day-of-week, same-hour historical median. **Build this first.**

---

## 5. Layer B — Local LLM

### 5.1 Base Model Selection

| Model | Params | RAM | Quality | Recommendation |
|---|---|---|---|---|
| Llama 3.2 3B | 3B | 6 GB | Good | Dev/testing |
| **Llama 3.1 8B** | 8B | 16 GB | **Very good** | **Recommended for prod** |
| Mistral 7B Instruct | 7B | 14 GB | Very good | Alternative |
| Phi-3 Medium | 14B | 28 GB | Excellent | If 32GB+ RAM available |

**Default choice: Llama 3.1 8B via Ollama**

```bash
# Installation (one-time)
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull llama3.1:8b

# Service runs at localhost:11434
# BATIS backend calls it via HTTP — no Python SDK needed
```

**Hardware requirements (minimum):**
- RAM: 16 GB (model stays resident in memory)
- CPU: Modern 8-core (inference: ~2–5s per response)
- GPU (optional): NVIDIA RTX 3080+ (inference: ~0.3s per response)
- Disk: 5 GB for model weights

---

### 5.2 RAG (Retrieval Augmented Generation)

**Problem:** LLMs hallucinate route numbers, stop names, and schedules. RAG grounds the LLM in your actual database content.

**Implementation using pgvector (Postgres extension):**

```sql
-- New table in schema.sql
CREATE TABLE IF NOT EXISTS ai_embeddings (
    id bigserial PRIMARY KEY,
    content_type text NOT NULL,     -- 'route', 'stop', 'alert', 'ops_summary'
    content_id text NOT NULL,       -- route_id, stop_id, etc.
    content_text text NOT NULL,     -- human-readable description
    embedding vector(384),          -- from all-MiniLM-L6-v2 (local, fast)
    updated_at timestamptz DEFAULT now()
);

CREATE INDEX ON ai_embeddings USING ivfflat (embedding vector_cosine_ops);
```

**What gets embedded:**
- Route descriptions: `"Route 72 runs from Oakland to Hayward via East 14th Street, serving 47 stops. Average delay last 7 days: 2.3 minutes."`
- Stop summaries: `"Stop 2485 Broadway & 14th St (12th St BART). Served by routes 1T, 72, 840. Average crowding: medium in AM peak."`
- Live alerts: GTFS-RT service alert text
- Daily ops summaries: auto-generated from `ops_trip_events`

**Embedding model:** `all-MiniLM-L6-v2` (22MB, runs locally via `sentence-transformers`)
**Embedding pipeline:** `backend/ml/embed.py` — runs every 30 min, updates changed content

**RAG query flow:**
```
User: "Which routes are running late right now?"
         ↓
1. Embed the question (sentence-transformers, local)
2. pgvector similarity search → top 5 relevant chunks
3. Build prompt:
   [System: You are a transit assistant. Use only the context below.]
   [Context: Route 72 avg delay today 4.2 min. Route 30 avg delay 1.1 min ...]
   [User: Which routes are running late right now?]
4. Ollama (Llama 3.1 8B) generates answer
5. Return to frontend
```

---

### 5.3 Fine-Tuning (Phase 2 — optional)

**When to consider:** After the base model + RAG is running well and you want faster, more accurate transit-specific responses without the RAG overhead.

**Method:** LoRA (Low-Rank Adaptation) — fine-tunes only a small fraction of model weights, preserving the base model.

**Training data to generate:**
```python
# Use Claude API once to generate synthetic Q&A pairs
# Input: your actual route/stop/delay data
# Output: 1,000–5,000 transit-specific Q&A pairs

examples = [
    {"question": "What is Route 72?",
     "answer": "Route 72 runs along East 14th Street from downtown Oakland to Hayward..."},
    {"question": "Is Route 1T running late today?",
     "answer": "Based on current data, Route 1T has an average delay of 3.2 minutes..."},
    ...
]
```

**Tools:** Unsloth (free, fast LoRA fine-tuning)
**Hardware:** RTX 3090/4090 or 2x hours on RunPod (~$15–25 total)
**Output:** A LoRA adapter that can be loaded alongside Llama 3.1 8B in Ollama

---

## 6. New API Endpoints

### POST /ai/ask
Natural language query interface.

**Request:**
```json
{
  "question": "Which routes had the worst delays yesterday afternoon?",
  "context": "optional: current map view bbox or active section"
}
```

**Response:**
```json
{
  "answer": "Routes 72, 82, and 1T had the highest average delays yesterday between 3–7pm. Route 72 peaked at 8.4 minutes late around 5pm at the Fruitvale area stops.",
  "sources": ["ops_trip_events aggregation 2026-03-17", "route summaries"],
  "model": "llama3.1:8b",
  "latency_ms": 2340
}
```

**Auth:** Requires API key (same as other protected endpoints)

---

### GET /ai/explain/{route_id}
Auto-generated plain English summary of a route's current performance.

**Response:**
```json
{
  "route_id": "72",
  "summary": "Route 72 is running 3.1 minutes late on average today, which is 40% worse than its 7-day average of 2.2 minutes. The delay is concentrated between stops 14th Ave and Fruitvale BART during the PM peak. Two trips were bunched this morning around 8:15am.",
  "severity": "moderate",
  "generated_at": "2026-03-18T14:32:00Z"
}
```

---

### GET /ai/status
Model and pipeline health check.

**Response:**
```json
{
  "ollama": {"status": "ok", "model": "llama3.1:8b", "latency_ms": 320},
  "delay_model": {"status": "ok", "version": "2026-03-17", "training_rows": 98234},
  "crowding_model": {"status": "not_trained", "reason": "insufficient data"},
  "embeddings": {"status": "ok", "count": 5412, "last_updated": "2026-03-18T14:00:00Z"},
  "baseline_predictions": {"status": "ok", "rows_today": 3299}
}
```

---

## 7. Frontend Changes

### 7.1 AI Assistant Panel (new "ai" section)

New sidebar section alongside the existing tabs. Contains:
- **Text input:** "Ask anything about the network…"
- **Response area:** Markdown-formatted answer with source citations
- **Suggested questions:** Dynamic chips based on current map view
  - "What's causing delays on this route?"
  - "Which stops have the worst crowding right now?"
  - "Compare this route's performance to last week"

### 7.2 Inline Anomaly Cards

On existing panels (Reliability, Bunching), when a route is significantly above its baseline delay, show a small AI-generated explanation card:
```
⚠ Route 72 — Unusual delay spike
"3 trips bunched between 14th Ave and Fruitvale
since 4:45pm. Possibly related to service gap
earlier this afternoon."
[Ask AI →]
```

---

## 8. New Files and Directory Structure

```
backend/
├── ml/
│   ├── __init__.py
│   ├── features.py          # Feature engineering (shared)
│   ├── train_delay_model.py # Train XGBoost delay model
│   ├── train_crowding_model.py
│   ├── train_demand_model.py
│   ├── inference.py         # Run predictions → DB
│   ├── embed.py             # Build/update pgvector embeddings
│   ├── baseline.py          # SQL-based statistical baseline (ship first)
│   └── models/              # Saved model artifacts (.pkl files, gitignored)
├── app/
│   └── services/
│       ├── ai_assistant.py  # RAG + Ollama query logic
│       └── model_registry.py # Load/version model artifacts
└── sql/
    └── schema_ai.sql        # pgvector extension, ai_embeddings table

frontend/src/
└── components/
    ├── AiAssistant.tsx      # Chat panel component
    └── AnomalyCard.tsx      # Inline explanation card
```

---

## 9. Infrastructure Requirements

### New Python Dependencies
```
# backend/requirements.txt additions
xgboost>=2.0
lightgbm>=4.0
scikit-learn>=1.4
pandas>=2.0
prophet>=1.1          # demand forecasting
sentence-transformers>=2.6  # local embeddings (all-MiniLM-L6-v2)
pgvector>=0.3.0       # Postgres vector client
httpx>=0.27           # async Ollama calls
```

### New Postgres Extensions
```sql
CREATE EXTENSION IF NOT EXISTS vector;  -- pgvector
```
pgvector is available on standard Postgres 14+. Since the project uses Supabase Docker on port 54322, this needs to be enabled once.

### Ollama Service
- Runs as a separate local process on port 11434
- Started independently of FastAPI
- FastAPI calls it via HTTP — no tight coupling
- If Ollama is unavailable, `/ai/ask` returns a graceful fallback (no crash)

---

## 10. Build Phases

### Phase 0 — SQL Baseline (1–2 days)
- [ ] Write `backend/ml/baseline.py`
- [ ] Schedule it to run every hour via a thread in FastAPI lifespan
- [ ] `delay_predictions` table populated with real data
- [ ] Trip Planner delay overlay becomes meaningful

### Phase 1 — Prediction Models (1–2 weeks, after 14+ days of RT data)
- [ ] `backend/ml/features.py` — shared feature extraction
- [ ] `backend/ml/train_delay_model.py` — XGBoost delay model
- [ ] `backend/ml/inference.py` — run predictions every 30 min
- [ ] Weekly retrain cron
- [ ] `/ai/status` endpoint to monitor model health

### Phase 2 — Local LLM + RAG (1 week)
- [ ] Install Ollama, pull Llama 3.1 8B
- [ ] Enable pgvector on existing Postgres
- [ ] `backend/ml/embed.py` — build embeddings for routes, stops, alerts
- [ ] `backend/app/services/ai_assistant.py` — RAG query pipeline
- [ ] `/ai/ask` and `/ai/explain/{route_id}` endpoints
- [ ] `AiAssistant.tsx` frontend panel

### Phase 3 — Fine-Tuning (optional, 1–2 weeks)
- [ ] Generate synthetic Q&A dataset from real DB content
- [ ] Fine-tune Llama 3.1 8B with LoRA (Unsloth)
- [ ] Load fine-tuned adapter in Ollama
- [ ] A/B test vs base model on answer quality

### Phase 4 — Crowding + Demand Models (after 30+ days of data)
- [ ] `train_crowding_model.py` — LightGBM classifier
- [ ] `train_demand_model.py` — Prophet per route
- [ ] Inference for both, writing to existing prediction tables

---

## 11. Decisions (Locked)

| # | Question | Decision |
|---|---|---|
| 1 | Hardware | Intel Core Ultra 9 + RTX 5070 8GB. Model: Llama 3.2 11B Q4_K_M (~6.5GB VRAM, ~18 tok/s) |
| 2 | Data retention | **Yes** — extend `rt_vehicle_positions_raw` to 30 days. ~50MB/day, ~1.5GB/month |
| 3 | Baseline first | **Yes** — Phase 0 SQL baseline ships before any ML work |
| 4 | Ollama pull | One-time ~7GB internet download, then fully offline |
| 5 | Fine-tuning | **Yes** — on-device with Unsloth + RTX 5070, ~45 min, $0 hardware cost |
| 6 | Crowding bootstrap | Defer — wait for 21+ days of real occupancy data |
| 7 | Frontend scope | **Full sidebar panel** — same pattern as existing sections |

---

## 12. What This Is NOT

- Not a replacement for a dispatch system
- Not real-time passenger-facing (latency 1–5s per LLM response)
- Not a safety-critical system — all predictions are advisory
- Not dependent on any external AI API after initial setup

---

*This document is a draft. Review all open questions in Section 11 before beginning implementation.*

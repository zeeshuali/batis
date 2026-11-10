-- 012_run_log.sql
-- Operational status tables for the System Status dashboard.
--   api_call_log : one row per outbound HTTP call (511, Oakland, Census, ...).
--                  Stores host+path only, never the query string, so keys cannot leak.
--                  Used for the 511 rate-limit budget and error rates.
--   job_runs     : one row per run of a worker or loop iteration (RT ingestor poll,
--                  baseline, embeddings, ETL, stop_observations loads).
-- Both are append-only and pruned by prune_run_log() (default 14 days).

BEGIN;

CREATE TABLE IF NOT EXISTS api_call_log (
    id           bigserial PRIMARY KEY,
    called_at    timestamptz NOT NULL DEFAULT now(),
    source       text NOT NULL,
    endpoint     text NOT NULL,
    status_code  integer,
    ok           boolean NOT NULL,
    duration_ms  integer,
    error        text
);
CREATE INDEX IF NOT EXISTS idx_api_call_log_called_at ON api_call_log (called_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_call_log_source_time ON api_call_log (source, called_at DESC);

CREATE TABLE IF NOT EXISTS job_runs (
    id           bigserial PRIMARY KEY,
    job          text NOT NULL,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    status       text NOT NULL DEFAULT 'running',
    rows_written integer,
    details      jsonb,
    error        text,
    CONSTRAINT job_runs_status_chk CHECK (status IN ('running', 'ok', 'error'))
);
CREATE INDEX IF NOT EXISTS idx_job_runs_job_started ON job_runs (job, started_at DESC);

COMMIT;

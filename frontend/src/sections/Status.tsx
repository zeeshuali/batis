import React, { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { KpiCard, Spinner, EmptyState, SectionError, ExportButton } from "../components/primitives";
import "./sections.css";
import "./Status.css";

type Level = "ok" | "warn" | "error";

interface Check { key: string; label: string; status: Level; detail: string | null }
interface DataRow { table: string; label: string; rows: number | null; latest: string | null;
                    age_minutes: number | null; status: Level; note: string | null }
interface SourceRow { source: string; calls_24h: number; errors_24h: number; error_rate_pct: number;
                      avg_ms: number | null; last_call: string | null; last_status_code: number | null;
                      last_ok: boolean | null; last_error: string | null }
interface JobRow { job: string; status: Level; last_status: string; last_started: string;
                   age_minutes: number | null; duration_s: number | null; rows_written: number | null;
                   error: string | null; note: string | null; runs_24h: number; errors_24h: number }
interface RateLimit { limit: number; used_last_hour: number; remaining: number; pct_used: number | null;
                      oldest_call_expires_in_minutes: number | null }
interface Snapshot {
  generated_at: string; overall: Level; checks: Check[];
  db: { ok: boolean; version?: string; latency_ms?: number; size_mb?: number; extensions: string[]; error?: string };
  data: DataRow[];
  api: { rate_limit: RateLimit | null; sources: SourceRow[]; error: string | null };
  jobs: JobRow[];
  threads: { name: string; alive: boolean }[];
  services: { ollama?: { reachable: boolean; models: string[]; configured_model: string; model_present: boolean; url: string };
              five11_key_configured?: boolean; backend_api_key_configured?: boolean };
}
interface CallRow { id: number; called_at: string; source: string; endpoint: string;
                    status_code: number | null; ok: boolean; duration_ms: number | null; error: string | null }
interface RunRow { id: number; job: string; started_at: string; finished_at: string | null;
                   status: string; rows_written: number | null; error: string | null }

const REFRESH_MS = 30_000;
const LABEL: Record<Level, string> = { ok: "All systems OK", warn: "Needs attention", error: "Problem detected" };

function ago(iso: string | null): string {
  if (!iso) return "never";
  const min = (Date.now() - new Date(iso).getTime()) / 60000;
  if (min < 1) return "just now";
  if (min < 90) return `${Math.round(min)} min ago`;
  if (min < 2880) return `${(min / 60).toFixed(1)} h ago`;
  return `${Math.round(min / 1440)} d ago`;
}
function mins(m: number | null): string {
  if (m == null) return "—";
  return m < 90 ? `${Math.round(m)} min` : m < 2880 ? `${(m / 60).toFixed(1)} h` : `${Math.round(m / 1440)} d`;
}

const Dot: React.FC<{ level: Level }> = ({ level }) =>
  <span className={`status-dot status-dot--${level}`} role="img" aria-label={level} />;

/** System Status — API runs, jobs, data freshness and service health for troubleshooting. */
export const Status: React.FC = () => {
  const [snap, setSnap]       = useState<Snapshot | null>(null);
  const [error, setError]     = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [auto, setAuto]       = useState(true);
  const [calls, setCalls]     = useState<CallRow[]>([]);
  const [errorsOnly, setErrorsOnly] = useState(false);
  const [source, setSource]   = useState("");
  const [activeJob, setActiveJob] = useState<string | null>(null);
  const [runs, setRuns]       = useState<RunRow[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, c] = await Promise.all([
        api.get<Snapshot>("/admin/status"),
        api.get<CallRow[]>("/admin/api-calls", {
          params: { limit: 100, errors_only: errorsOnly, ...(source ? { source } : {}) } }),
      ]);
      setSnap(s.data); setCalls(Array.isArray(c.data) ? c.data : []); setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load status");
    } finally { setLoading(false); }
  }, [errorsOnly, source]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!auto) return;
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [auto, load]);

  useEffect(() => {
    if (!activeJob) { setRuns([]); return; }
    api.get<RunRow[]>("/admin/job-runs", { params: { job: activeJob, limit: 25 } })
      .then(r => setRuns(Array.isArray(r.data) ? r.data : []))
      .catch(() => setRuns([]));
  }, [activeJob]);

  if (error && !snap) return <SectionError message={error} onRetry={load} />;
  if (!snap) return <Spinner />;

  const rl = snap.api.rate_limit;
  const rlLevel: Level = !rl ? "ok" : (rl.pct_used ?? 0) >= 100 ? "error" : (rl.pct_used ?? 0) >= 80 ? "warn" : "ok";
  const sources = Array.from(new Set(snap.api.sources.map(s => s.source)));

  return (
    <div className="section">
      <div className={`status-banner status-banner--${snap.overall}`} data-testid="status-banner">
        <Dot level={snap.overall} />
        <span className="status-banner__title">{LABEL[snap.overall]}</span>
        <span className="status-banner__meta">
          updated {ago(snap.generated_at)}
          {" · "}
          <label><input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)} /> auto-refresh 30s</label>
          {" "}
          <button type="button" className="export-button" onClick={load} disabled={loading}>Refresh</button>
        </span>
      </div>
      {error && <SectionError message={error} onRetry={load} />}

      <div className="section__panel">
        <h3 className="section__panel-title">Checks</h3>
        <div className="status-checks">
          {snap.checks.map(c => (
            <div key={c.key} className="status-check">
              <Dot level={c.status} />
              <div>
                <div className="status-check__label">{c.label}</div>
                <div className="status-check__detail">{c.detail}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="section__kpis">
        <KpiCard label="511 requests (last hour)" value={rl ? `${rl.used_last_hour} / ${rl.limit}` : "—"}
                 sub={rl?.oldest_call_expires_in_minutes != null
                   ? `oldest call frees up in ${Math.round(rl.oldest_call_expires_in_minutes)} min` : undefined} />
        <KpiCard label="Database" value={snap.db.ok ? `${snap.db.latency_ms} ms` : "DOWN"}
                 sub={snap.db.ok ? `${snap.db.size_mb} MB · ${snap.db.extensions.join(", ")}` : snap.db.error} />
        <KpiCard label="Jobs failing (24 h)" value={String(snap.jobs.filter(j => j.errors_24h > 0).length)}
                 sub={`${snap.jobs.length} jobs tracked`} />
      </div>
      {rl && (
        <div className="section__panel">
          <h3 className="section__panel-title">511 rate-limit budget</h3>
          <div className="status-meter" role="progressbar" aria-valuemin={0} aria-valuemax={rl.limit}
               aria-valuenow={rl.used_last_hour} aria-label="511 requests used in the last hour">
            <div className={`status-meter__fill status-meter__fill--${rlLevel}`}
                 style={{ width: `${Math.min(100, rl.pct_used ?? 0)}%` }} />
          </div>
          <span className="status-check__detail">{rl.remaining} requests remaining. The live ingestor and any backfill share this limit.</span>
        </div>
      )}

      <div className="section__panel">
        <h3 className="section__panel-title">Jobs (click a row for recent runs)</h3>
        {snap.jobs.length === 0 ? <EmptyState message="No job runs recorded yet." hint="Runs appear once the RT ingestor, ETL or loaders have run after migration 012." /> : (
          <div className="status-scroll"><table className="status-table">
            <thead><tr><th></th><th>Job</th><th>Last run</th><th>Result</th><th>Rows</th><th>Duration</th><th>24 h</th><th>Error</th></tr></thead>
            <tbody>
              {snap.jobs.map(j => (
                <tr key={j.job} className="status-row--click" onClick={() => setActiveJob(activeJob === j.job ? null : j.job)}>
                  <td><Dot level={j.status} /></td><td>{j.job}</td><td>{ago(j.last_started)}</td>
                  <td>{j.last_status}</td><td>{j.rows_written ?? "—"}</td>
                  <td>{j.duration_s != null ? `${j.duration_s}s` : "—"}</td>
                  <td>{j.runs_24h} runs / {j.errors_24h} err</td>
                  <td className="status-err">{j.error ?? j.note ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
        {activeJob && (
          <div>
            <strong>Recent runs: {activeJob}</strong>
            <div className="status-scroll"><table className="status-table">
              <thead><tr><th>Started</th><th>Status</th><th>Rows</th><th>Error</th></tr></thead>
              <tbody>{runs.map(r => (
                <tr key={r.id}><td>{ago(r.started_at)}</td><td>{r.status}</td><td>{r.rows_written ?? "—"}</td>
                    <td className="status-err">{r.error ?? ""}</td></tr>))}</tbody>
            </table></div>
          </div>
        )}
      </div>

      <div className="section__panel">
        <h3 className="section__panel-title">API sources (last 24 h)</h3>
        {snap.api.sources.length === 0 ? <EmptyState message="No API calls recorded yet." /> : (
          <div className="status-scroll"><table className="status-table">
            <thead><tr><th>Source</th><th>Calls</th><th>Errors</th><th>Error rate</th><th>Avg latency</th><th>Last call</th><th>Last result</th></tr></thead>
            <tbody>{snap.api.sources.map(s => (
              <tr key={s.source}><td>{s.source}</td><td>{s.calls_24h}</td><td>{s.errors_24h}</td>
                  <td>{s.error_rate_pct}%</td><td>{s.avg_ms ?? "—"} ms</td><td>{ago(s.last_call)}</td>
                  <td className={s.last_ok === false ? "status-err" : ""}>
                    {s.last_ok === false ? (s.last_error ?? `HTTP ${s.last_status_code}`) : `HTTP ${s.last_status_code ?? "—"}`}</td></tr>))}</tbody>
          </table></div>
        )}
      </div>

      <div className="section__panel">
        <h3 className="section__panel-title">Data freshness</h3>
        <div className="status-scroll"><table className="status-table">
          <thead><tr><th></th><th>Dataset</th><th>Rows</th><th>Latest</th><th>Note</th></tr></thead>
          <tbody>{snap.data.map(d => (
            <tr key={d.table}><td><Dot level={d.status} /></td><td>{d.label} <code>{d.table}</code></td>
                <td>{d.rows?.toLocaleString() ?? "—"}</td><td>{d.latest ? `${mins(d.age_minutes)} ago` : "—"}</td>
                <td>{d.note ?? ""}</td></tr>))}</tbody>
        </table></div>
      </div>

      <div className="section__panel">
        <div className="status-toolbar">
          <h3 className="section__panel-title">Recent API calls</h3>
          <label><input type="checkbox" checked={errorsOnly} onChange={e => setErrorsOnly(e.target.checked)} /> errors only</label>
          <label>Source{" "}
            <select value={source} onChange={e => setSource(e.target.value)} aria-label="Filter by source">
              <option value="">all</option>
              {sources.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <ExportButton filename="api-calls.csv" rows={calls.map(c => ({ ...c }))} />
        </div>
        {calls.length === 0 ? <EmptyState message="No calls match." /> : (
          <div className="status-scroll"><table className="status-table">
            <thead><tr><th>When</th><th>Source</th><th>Endpoint</th><th>Status</th><th>ms</th><th>Error</th></tr></thead>
            <tbody>{calls.map(c => (
              <tr key={c.id}><td>{ago(c.called_at)}</td><td>{c.source}</td><td>{c.endpoint}</td>
                  <td>{c.status_code ?? "—"}</td><td>{c.duration_ms ?? "—"}</td>
                  <td className="status-err">{c.error ?? ""}</td></tr>))}</tbody>
          </table></div>
        )}
      </div>

      <div className="section__panel">
        <h3 className="section__panel-title">Background threads and services</h3>
        <div className="status-checks">
          {snap.threads.map(t => (
            <div key={t.name} className="status-check"><Dot level={t.alive ? "ok" : "warn"} />
              <div><div className="status-check__label">{t.name}</div>
              <div className="status-check__detail">{t.alive ? "running in the API process" : "not running in the API process"}</div></div></div>
          ))}
          {snap.services.ollama && (
            <div className="status-check"><Dot level={snap.services.ollama.reachable && snap.services.ollama.model_present ? "ok" : "warn"} />
              <div><div className="status-check__label">Ollama</div>
              <div className="status-check__detail">{snap.services.ollama.reachable
                ? `${snap.services.ollama.models.length} models · configured ${snap.services.ollama.configured_model}${snap.services.ollama.model_present ? "" : " (missing)"}`
                : `unreachable at ${snap.services.ollama.url}`}</div></div></div>
          )}
        </div>
      </div>
    </div>
  );
};

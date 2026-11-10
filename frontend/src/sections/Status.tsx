import React, { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { Spinner, EmptyState, SectionError, ExportButton } from "../components/primitives";
import "./sections.css";
import "./Status.css";

type Level = "ok" | "warn" | "error";
type CardStatus = Level | "running" | "idle";

interface Progress { label: string; pct: number | null; elapsed_minutes: number | null;
                     overall_pct?: number; overall_label?: string | null }
interface Metric { label: string; value: string }
interface Card { key: string; title: string; category: string; description: string; schedule: string;
                 status: CardStatus; headline: string; metrics: Metric[]; progress: Progress | null; next_run: string | null }
interface Activities { generated_at: string; categories: string[]; cards: Card[]; overall: Level }
interface Check { key: string; label: string; status: Level; detail: string | null }
interface StatusSnap { generated_at: string; overall: Level; checks: Check[] }

interface Run { id: number; job: string; started_at: string; finished_at: string | null; status: string;
                rows_written: number | null; duration_s: number | null; details: Record<string, unknown> | null; error: string | null }
interface ApiCall { id: number; called_at: string; endpoint: string; status_code: number | null; ok: boolean;
                    duration_ms: number | null; error: string | null }
interface TableInfo { table: string; label: string; rows: number | null; size: string | null; latest: string | null; note: string | null }
interface MonthRow { month: string; state: "loaded" | "loading" | "waiting"; rows: number | null; source: string | null; loaded_at: string | null }
interface StepRow { n: string; title: string; duration_s: number | null; state: string; notes: string[] }
interface Detail {
  key: string; title: string; status: CardStatus; headline: string;
  sections: {
    overview: { description: string; how_it_works: string[]; schedule: string; command: string; next_run: string | null;
                metrics: Metric[]; used_by_note: string | null };
    progress?: { current: Progress | null; months?: MonthRow[]; steps?: StepRow[];
                 agencies_last_30_min?: { agency_id: string; vehicles: number; latest: string }[];
                 threads?: { name: string; alive: boolean }[];
                 target?: { horizon_months: number; months_per_run: number } };
    runs?: { runs: Run[] };
    api_calls?: { summary: { calls: number; errors: number; avg_ms: number | null };
                  by_endpoint: { endpoint: string; calls: number; errors: number; avg_ms: number | null; last_call: string | null }[];
                  calls: ApiCall[] };
    data?: { tables: TableInfo[] };
    errors?: { items: { when: string | null; kind: string; where: string; message: string }[] };
    config?: { settings?: { name: string; value: unknown }[]; command?: string; schedule?: string;
               log_file?: string | null; tables?: string[]; crontab?: string[] };
    logs?: { path: string; lines: string[] };
    activity?: { queries: { pid: number; state: string; running_for: string; query: string }[] };
    service?: { reachable: boolean; models: string[]; configured_model: string; model_present: boolean; url: string };
  };
}

const LEVEL_LABEL: Record<Level, string> = { ok: "All systems OK", warn: "Needs attention", error: "Problem detected" };
const TAB_LABEL: Record<string, string> = { overview: "Overview", progress: "Progress", runs: "Runs", api_calls: "API calls",
  data: "Data", activity: "Live queries", service: "Service", errors: "Errors", config: "Config", logs: "Logs" };
const TAB_ORDER = ["overview", "progress", "runs", "api_calls", "data", "activity", "service", "errors", "config", "logs"];

function ago(iso: string | null): string {
  if (!iso) return "never";
  const min = (Date.now() - new Date(iso).getTime()) / 60000;
  if (min < 0) return "soon";
  if (min < 1) return "just now";
  if (min < 90) return `${Math.round(min)} min ago`;
  if (min < 2880) return `${(min / 60).toFixed(1)} h ago`;
  return `${Math.round(min / 1440)} d ago`;
}
function when(iso: string | null): string { return iso ? new Date(iso).toLocaleString() : "—"; }
function dur(s: number | null): string {
  if (s == null) return "—";
  if (s < 90) return `${Math.round(s)}s`;
  if (s < 5400) return `${(s / 60).toFixed(1)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}

const Dot: React.FC<{ level: CardStatus }> = ({ level }) =>
  <span className={`status-dot status-dot--${level}`} role="img" aria-label={level} />;

const Bar: React.FC<{ pct: number | null; label?: string }> = ({ pct, label }) => (
  <div>
    <div className="act-bar" role="progressbar" aria-label={label ?? "progress"}
         aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct ?? undefined}>
      <div className={`act-bar__fill ${pct == null ? "act-bar__fill--indeterminate" : ""}`}
           style={pct == null ? undefined : { width: `${pct}%` }} />
    </div>
    {label && <div className="act-bar__label">{label}</div>}
  </div>
);

const ActivityCard: React.FC<{ card: Card; selected: boolean; onOpen: () => void }> = ({ card, selected, onOpen }) => (
  <button type="button" className={`act-card ${selected ? "act-card--selected" : ""}`} onClick={onOpen}
          aria-label={`${card.title}, ${card.status}. Open details`}>
    <div className="act-card__head">
      <Dot level={card.status} />
      <span className="act-card__title">{card.title}</span>
      <span className={`act-pill act-pill--${card.status}`}>{card.status}</span>
    </div>
    <div className="act-card__headline">{card.headline}</div>
    {card.progress && <Bar pct={card.progress.overall_pct ?? card.progress.pct}
                           label={card.progress.overall_label ? `${card.progress.label} · ${card.progress.overall_label}` : card.progress.label} />}
    <div className="act-card__metrics">
      {card.metrics.slice(0, 4).map(m => (
        <div key={m.label} className="act-metric"><span className="act-metric__v">{m.value}</span><span className="act-metric__l">{m.label}</span></div>
      ))}
    </div>
    <div className="act-card__foot">{card.schedule}{card.next_run ? ` · next ${when(card.next_run)}` : ""}</div>
  </button>
);

const Chips: React.FC<{ obj: Record<string, unknown> | null }> = ({ obj }) => {
  if (!obj) return null;
  const entries = Object.entries(obj).filter(([k]) => k !== "steps");
  return <>{entries.map(([k, v]) => <span key={k} className="act-chip">{k}: {typeof v === "object" ? JSON.stringify(v) : String(v)}</span>)}</>;
};

const DetailBody: React.FC<{ d: Detail; tab: string }> = ({ d, tab }) => {
  const [errorsOnly, setErrorsOnly] = useState(false);
  const s = d.sections;

  if (tab === "overview") return (
    <>
      <p>{s.overview.description}</p>
      <dl className="act-kv">
        <dt>Status</dt><dd>{d.status}: {d.headline}</dd>
        <dt>Schedule</dt><dd>{s.overview.schedule}</dd>
        {s.overview.next_run && (<><dt>Next run</dt><dd>{when(s.overview.next_run)}</dd></>)}
        {s.overview.command && (<><dt>Command</dt><dd><code>{s.overview.command}</code></dd></>)}
        {s.overview.metrics.map(m => (<React.Fragment key={m.label}><dt>{m.label}</dt><dd>{m.value}</dd></React.Fragment>))}
      </dl>
      {s.overview.used_by_note && <p className="status-check__detail">{s.overview.used_by_note}</p>}
      {s.overview.how_it_works.length > 0 && (
        <div><strong>How it works</strong>
          <ol className="act-steps">{s.overview.how_it_works.map(h => <li key={h}>{h}</li>)}</ol></div>
      )}
    </>
  );

  if (tab === "progress" && s.progress) {
    const p = s.progress;
    return (
      <>
        {p.current
          ? <div><strong>Running now</strong><Bar pct={p.current.pct} label={p.current.label} />
              {p.current.elapsed_minutes != null && <div className="act-bar__label">elapsed {p.current.elapsed_minutes} min</div>}</div>
          : <div className="status-check__detail">Nothing is running right now.</div>}
        {p.target && <div className="status-check__detail">Target: the newest {p.target.horizon_months} months, {p.target.months_per_run} per run.</div>}
        {p.months && (
          <div className="status-scroll"><table className="status-table">
            <thead><tr><th>Month</th><th>State</th><th>Rows</th><th>Loaded by</th><th>When</th></tr></thead>
            <tbody>{p.months.map(m => (
              <tr key={m.month}><td>{m.month}</td>
                <td><Dot level={m.state === "loaded" ? "ok" : m.state === "loading" ? "running" : "idle"} /> {m.state}</td>
                <td>{m.rows != null ? m.rows.toLocaleString() : "—"}</td><td>{m.source ?? "—"}</td><td>{m.loaded_at ? ago(m.loaded_at) : "—"}</td></tr>))}</tbody>
          </table></div>
        )}
        {p.steps && (p.steps.length === 0 ? <EmptyState message="No ETL run recorded yet." /> : (
          <div className="status-scroll"><table className="status-table">
            <thead><tr><th>Step</th><th>What</th><th>State</th><th>Duration</th><th>Notes</th></tr></thead>
            <tbody>{p.steps.map(st => (
              <tr key={st.n}><td>{st.n}</td><td>{st.title}</td>
                <td><Dot level={st.state === "running" ? "running" : st.state === "warn" ? "warn" : "ok"} /> {st.state}</td>
                <td>{dur(st.duration_s)}</td><td className="status-err">{st.notes.join(" | ")}</td></tr>))}</tbody>
          </table></div>
        ))}
        {p.agencies_last_30_min && (
          p.agencies_last_30_min.length === 0 ? <EmptyState message="No vehicle positions in the last 30 minutes." /> : (
            <div className="status-scroll"><table className="status-table">
              <thead><tr><th>Agency</th><th>Positions (30 min)</th><th>Latest</th></tr></thead>
              <tbody>{p.agencies_last_30_min.map(a => (
                <tr key={a.agency_id}><td>{a.agency_id}</td><td>{a.vehicles.toLocaleString()}</td><td>{ago(a.latest)}</td></tr>))}</tbody>
            </table></div>))}
        {p.threads && (
          <div className="status-checks">{p.threads.map(t => (
            <div key={t.name} className="status-check"><Dot level={t.alive ? "ok" : "warn"} />
              <div><div className="status-check__label">{t.name}</div>
              <div className="status-check__detail">{t.alive ? "running" : "not running in this process"}</div></div></div>))}</div>
        )}
      </>
    );
  }

  if (tab === "runs" && s.runs) return s.runs.runs.length === 0
    ? <EmptyState message="No runs recorded yet." />
    : (<div className="status-scroll"><table className="status-table">
        <thead><tr><th>Started</th><th>Status</th><th>Duration</th><th>Rows</th><th>Details</th><th>Error</th></tr></thead>
        <tbody>{s.runs.runs.map(r => (
          <tr key={r.id}><td title={when(r.started_at)}>{ago(r.started_at)}</td>
            <td><Dot level={r.status === "ok" ? "ok" : r.status === "error" ? "error" : "running"} /> {r.status}</td>
            <td>{dur(r.duration_s)}</td><td>{r.rows_written != null ? r.rows_written.toLocaleString() : "—"}</td>
            <td><Chips obj={r.details} /></td><td className="status-err">{r.error ?? ""}</td></tr>))}</tbody>
      </table></div>);

  if (tab === "api_calls" && s.api_calls) {
    const a = s.api_calls;
    const calls = errorsOnly ? a.calls.filter(c => !c.ok) : a.calls;
    return (
      <>
        <dl className="act-kv"><dt>Calls (24 h)</dt><dd>{a.summary.calls}</dd><dt>Errors (24 h)</dt><dd>{a.summary.errors}</dd>
          <dt>Average latency</dt><dd>{a.summary.avg_ms ?? "—"} ms</dd></dl>
        {a.by_endpoint.length > 0 && (
          <div className="status-scroll"><table className="status-table">
            <thead><tr><th>Endpoint</th><th>Calls</th><th>Errors</th><th>Avg ms</th><th>Last</th></tr></thead>
            <tbody>{a.by_endpoint.map(e => (
              <tr key={e.endpoint}><td>{e.endpoint}</td><td>{e.calls}</td><td>{e.errors}</td><td>{e.avg_ms ?? "—"}</td><td>{ago(e.last_call)}</td></tr>))}</tbody>
          </table></div>)}
        <div className="status-toolbar">
          <strong>Recent calls</strong>
          <label><input type="checkbox" checked={errorsOnly} onChange={e => setErrorsOnly(e.target.checked)} /> errors only</label>
          <ExportButton filename={`${d.key}-api-calls.csv`} rows={a.calls.map(c => ({ ...c }))} />
        </div>
        {calls.length === 0 ? <EmptyState message="No calls match." /> : (
          <div className="status-scroll"><table className="status-table">
            <thead><tr><th>When</th><th>Endpoint</th><th>Status</th><th>ms</th><th>Error</th></tr></thead>
            <tbody>{calls.map(c => (
              <tr key={c.id}><td title={when(c.called_at)}>{ago(c.called_at)}</td><td>{c.endpoint}</td><td>{c.status_code ?? "—"}</td>
                <td>{c.duration_ms ?? "—"}</td><td className="status-err">{c.error ?? ""}</td></tr>))}</tbody>
          </table></div>)}
      </>
    );
  }

  if (tab === "data" && s.data) return (
    <div className="status-scroll"><table className="status-table">
      <thead><tr><th>Dataset</th><th>Rows</th><th>Size</th><th>Latest</th><th>Note</th></tr></thead>
      <tbody>{s.data.tables.map(t => (
        <tr key={t.table}><td>{t.label} <code>{t.table}</code></td><td>{t.rows != null ? t.rows.toLocaleString() : "—"}</td>
          <td>{t.size ?? "—"}</td><td>{t.latest ? ago(t.latest) : "—"}</td><td>{t.note ?? ""}</td></tr>))}</tbody>
    </table></div>
  );

  if (tab === "activity" && s.activity) return s.activity.queries.length === 0
    ? <EmptyState message="No active queries." />
    : (<div className="status-scroll"><table className="status-table">
        <thead><tr><th>PID</th><th>State</th><th>Running for</th><th>Query</th></tr></thead>
        <tbody>{s.activity.queries.map(q => (
          <tr key={q.pid}><td>{q.pid}</td><td>{q.state}</td><td>{q.running_for}</td><td><code>{q.query}</code></td></tr>))}</tbody>
      </table></div>);

  if (tab === "service" && s.service) return (
    <dl className="act-kv"><dt>URL</dt><dd>{s.service.url}</dd><dt>Reachable</dt><dd>{String(s.service.reachable)}</dd>
      <dt>Configured model</dt><dd>{s.service.configured_model} ({s.service.model_present ? "available" : "not pulled"})</dd>
      <dt>Models</dt><dd>{s.service.models.join(", ") || "none"}</dd></dl>
  );

  if (tab === "errors" && s.errors) return s.errors.items.length === 0
    ? <EmptyState message="No recent errors." />
    : (<div className="status-scroll"><table className="status-table">
        <thead><tr><th>When</th><th>Kind</th><th>Where</th><th>Message</th></tr></thead>
        <tbody>{s.errors.items.map((e, i) => (
          <tr key={i}><td title={when(e.when)}>{ago(e.when)}</td><td>{e.kind}</td><td>{e.where}</td><td className="status-err">{e.message}</td></tr>))}</tbody>
      </table></div>);

  if (tab === "config" && s.config) {
    const c = s.config;
    return (
      <>
        <dl className="act-kv">
          {c.schedule && (<><dt>Schedule</dt><dd>{c.schedule}</dd></>)}
          {c.command && (<><dt>Command</dt><dd><code>{c.command}</code></dd></>)}
          {c.log_file && (<><dt>Log file</dt><dd><code>{c.log_file}</code></dd></>)}
          {c.tables && c.tables.length > 0 && (<><dt>Writes tables</dt><dd>{c.tables.join(", ")}</dd></>)}
          {(c.settings ?? []).map(x => (<React.Fragment key={x.name}><dt>{x.name}</dt><dd>{JSON.stringify(x.value)}</dd></React.Fragment>))}
        </dl>
        {c.crontab && (c.crontab.length === 0 ? <EmptyState message="No BATIS crontab entries for this user." />
          : <pre className="act-pre">{c.crontab.join("\n")}</pre>)}
      </>
    );
  }

  if (tab === "logs" && s.logs) return (
    <>
      <div className="status-check__detail">Last lines of <code>{s.logs.path}</code></div>
      {s.logs.lines.length === 0 ? <EmptyState message="The log has no readable lines yet." /> : <pre className="act-pre">{s.logs.lines.join("\n")}</pre>}
    </>
  );

  return <EmptyState message="Nothing to show here." />;
};

const DetailDrawer: React.FC<{ activityKey: string; onClose: () => void }> = ({ activityKey, onClose }) => {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError]   = useState<string | null>(null);
  const [tab, setTab]       = useState("overview");

  const load = useCallback(async () => {
    try {
      const r = await api.get<Detail>(`/admin/activities/${activityKey}`);
      setDetail(r.data); setError(null);
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load details"); }
  }, [activityKey]);

  useEffect(() => { setDetail(null); setTab("overview"); load(); }, [load]);
  useEffect(() => {
    const ms = detail?.status === "running" ? 5000 : 15000;
    const id = setInterval(load, ms);
    return () => clearInterval(id);
  }, [load, detail?.status]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const tabs = detail ? TAB_ORDER.filter(t => t in detail.sections) : [];
  const errCount = detail?.sections.errors?.items.length ?? 0;

  return (
    <>
      <div className="act-backdrop" onClick={onClose} />
      <aside className="act-drawer" role="dialog" aria-label={detail ? `${detail.title} details` : "Activity details"}>
        <div className="act-drawer__head">
          {detail && <Dot level={detail.status} />}
          <span className="act-drawer__title">{detail?.title ?? "Loading…"}</span>
          <button type="button" className="export-button" onClick={load}>Refresh</button>
          <button type="button" className="export-button" onClick={onClose} aria-label="Close details">Close</button>
        </div>
        {error && !detail && <SectionError message={error} onRetry={load} />}
        {!detail && !error && <Spinner />}
        {detail && (
          <>
            <div className="act-tabs" role="tablist">
              {tabs.map(t => (
                <button key={t} role="tab" type="button" className="act-tab" aria-selected={tab === t} onClick={() => setTab(t)}>
                  {TAB_LABEL[t]}{t === "errors" && errCount > 0 && <span className="act-tab__badge">{errCount}</span>}
                </button>
              ))}
            </div>
            <div className="act-drawer__body"><DetailBody d={detail} tab={tab} /></div>
          </>
        )}
      </aside>
    </>
  );
};

/** System Status: one card per backend activity. Click a card for its full breakdown. */
export const Status: React.FC = () => {
  const [acts, setActs]     = useState<Activities | null>(null);
  const [snap, setSnap]     = useState<StatusSnap | null>(null);
  const [error, setError]   = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [auto, setAuto]     = useState(true);
  const [open, setOpen]     = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [a, s] = await Promise.all([api.get<Activities>("/admin/activities"), api.get<StatusSnap>("/admin/status")]);
      setActs(a.data); setSnap(s.data); setError(null);
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load status"); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);
  const anyRunning = acts?.cards.some(c => c.status === "running") ?? false;
  useEffect(() => {
    if (!auto) return;
    const id = setInterval(load, anyRunning ? 8000 : 30000);
    return () => clearInterval(id);
  }, [auto, load, anyRunning]);

  if (error && !acts) return <SectionError message={error} onRetry={load} />;
  if (!acts || !snap) return <Spinner />;

  const overall = snap.overall === "error" || acts.overall === "error" ? "error"
                : snap.overall === "warn" || acts.overall === "warn" ? "warn" : "ok";
  const attention = snap.checks.filter(c => c.status !== "ok");

  return (
    <div className="section">
      <div className={`status-banner status-banner--${overall}`} data-testid="status-banner">
        <Dot level={overall} />
        <span className="status-banner__title">{LEVEL_LABEL[overall]}</span>
        <span className="status-banner__meta">
          updated {ago(acts.generated_at)}{" · "}
          <label><input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)} /> auto-refresh</label>{" "}
          <button type="button" className="export-button" onClick={load} disabled={loading}>Refresh</button>
        </span>
      </div>
      {error && <SectionError message={error} onRetry={load} />}

      {attention.length > 0 && (
        <div className="section__panel">
          <h3 className="section__panel-title">Needs attention</h3>
          <div className="status-checks">
            {attention.map(c => (
              <div key={c.key} className="status-check"><Dot level={c.status} />
                <div><div className="status-check__label">{c.label}</div><div className="status-check__detail">{c.detail}</div></div></div>
            ))}
          </div>
        </div>
      )}

      {acts.categories.map(cat => {
        const cards = acts.cards.filter(c => c.category === cat);
        if (cards.length === 0) return null;
        return (
          <section key={cat} aria-label={cat}>
            <h3 className="act-category">{cat}</h3>
            <div className="act-grid">
              {cards.map(c => <ActivityCard key={c.key} card={c} selected={open === c.key} onOpen={() => setOpen(c.key)} />)}
            </div>
          </section>
        );
      })}

      {open && <DetailDrawer activityKey={open} onClose={() => setOpen(null)} />}
    </div>
  );
};

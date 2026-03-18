import React, { useEffect, useState } from "react";
import axios from "axios";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import type { Section } from "../App";

// ─── Config ───────────────────────────────────────────────────────────────────

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string) || "http://localhost:8000";
const API_KEY  = (import.meta.env.VITE_API_KEY  as string) || "";

function apiHeaders(): Record<string, string> {
  return API_KEY ? { "X-API-Key": API_KEY } : {};
}

// ─── Shared sub-components ────────────────────────────────────────────────────

function KpiCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="kpi-card">
      <span className="kpi-value">{value}</span>
      <span className="kpi-label">{label}</span>
      {sub && <span className="kpi-sub">{sub}</span>}
    </div>
  );
}

function SectionDivider() {
  return <hr className="sidebar-divider" />;
}

function Spinner() {
  return <div className="sidebar-spinner" />;
}

function EmptyState({ msg }: { msg: string }) {
  return <p className="sidebar-empty">{msg}</p>;
}

function fmt(n: number | null | undefined, dec = 0): string {
  if (n == null || isNaN(Number(n))) return "—";
  return Number(n).toFixed(dec);
}

function fmtDelay(s: number): string {
  if (s < 60)  return `${Math.round(s)}s`;
  return `${(s / 60).toFixed(1)} min`;
}

function delayBadge(avgDelay: number): string {
  if (avgDelay <  30) return "on-time";
  if (avgDelay <  90) return "minor";
  if (avgDelay < 180) return "moderate";
  return "severe";
}

// ─── Section: Reliability ─────────────────────────────────────────────────────

interface ReliabilityRow {
  route_id: string;
  sample_events: number;
  avg_delay_seconds: number;
}

function ReliabilityPanel({
  startDate, endDate,
}: { startDate: string; endDate: string }) {
  const [rows,    setRows]    = useState<ReliabilityRow[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!API_BASE) return;
    setLoading(true);
    axios
      .get(`${API_BASE}/reliability/summary`, {
        params:  { start_date: startDate, end_date: endDate },
        headers: apiHeaders(),
      })
      .then((r) => setRows(r.data as ReliabilityRow[]))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [startDate, endDate]);

  const totalRoutes  = rows.length;
  const avgDelay     = rows.length ? rows.reduce((s, r) => s + r.avg_delay_seconds, 0) / rows.length : 0;
  const onTimeCount  = rows.filter((r) => r.avg_delay_seconds < 30).length;
  const onTimePct    = totalRoutes ? Math.round((onTimeCount / totalRoutes) * 100) : 0;

  const sorted = [...rows].sort((a, b) => b.avg_delay_seconds - a.avg_delay_seconds).slice(0, 10);

  return (
    <>
      <p className="sidebar-desc">On-time performance and delay KPIs per route.</p>
      <SectionDivider />

      {loading ? <Spinner /> : (
        <>
          <div className="kpi-grid">
            <KpiCard label="Routes"    value={String(totalRoutes)} />
            <KpiCard label="Avg Delay" value={fmtDelay(avgDelay)} />
            <KpiCard label="On Time"   value={`${onTimePct}%`} sub="< 30 s" />
          </div>

          <SectionDivider />
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h3 className="sidebar-table-title" style={{ margin: 0 }}>Worst Performing Routes</h3>
            {sorted.length > 0 && (
              <button className="export-btn" onClick={() => downloadCSV("reliability.csv", sorted)}>Export CSV</button>
            )}
          </div>

          {sorted.length === 0
            ? <EmptyState msg="No reliability data. Run the RT ingestor to populate." />
            : (
              <ul className="data-list" style={{ marginTop: "0.25rem" }}>
                {sorted.map((r) => (
                  <li key={r.route_id} className="data-list-item">
                    <span className="data-list-primary">Route {r.route_id}</span>
                    <span className={`delay-badge delay-badge--${delayBadge(r.avg_delay_seconds)}`}>
                      {fmtDelay(r.avg_delay_seconds)}
                    </span>
                  </li>
                ))}
              </ul>
            )
          }
          <SectionDivider />
          <h3 className="sidebar-table-title">Daily Trend</h3>
          <ReliabilityTrendChart startDate={startDate} endDate={endDate} />
        </>
      )}
    </>
  );
}

// ─── Section: Crowding ────────────────────────────────────────────────────────

interface CrowdingRow {
  route_id: string;
  trip_id: string | null;
  stop_id: string | null;
  service_date: string;
  time_bucket: string;
  crowding_level: string;
  model_version: string | null;
}

function CrowdingPanel({ startDate, endDate }: { startDate: string; endDate: string }) {
  const [rows,    setRows]    = useState<CrowdingRow[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!API_BASE) return;
    setLoading(true);
    axios
      .get(`${API_BASE}/crowding/predictions`, {
        params:  { start_date: startDate, end_date: endDate },
        headers: apiHeaders(),
      })
      .then((r) => setRows(r.data as CrowdingRow[]))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [startDate, endDate]);

  const counts = { low: 0, medium: 0, high: 0, unknown: 0 };
  for (const r of rows) {
    const k = r.crowding_level as keyof typeof counts;
    if (k in counts) counts[k]++;
    else counts.unknown++;
  }
  const total = rows.length || 1;

  const routeCounts: Record<string, { low: number; medium: number; high: number }> = {};
  for (const r of rows) {
    if (!routeCounts[r.route_id]) routeCounts[r.route_id] = { low: 0, medium: 0, high: 0 };
    const bucket = routeCounts[r.route_id];
    if (r.crowding_level === "high")   bucket.high++;
    else if (r.crowding_level === "medium") bucket.medium++;
    else                               bucket.low++;
  }
  const topRoutes = Object.entries(routeCounts)
    .sort(([, a], [, b]) => b.high - a.high)
    .slice(0, 8);

  return (
    <>
      <p className="sidebar-desc">Predicted passenger load levels by route and stop.</p>
      <SectionDivider />

      {loading ? <Spinner /> : (
        <>
          <div className="kpi-grid">
            <KpiCard label="Predictions" value={String(rows.length)} />
            <KpiCard label="High"        value={String(counts.high)}   sub={`${Math.round(counts.high / total * 100)}%`} />
            <KpiCard label="Low"         value={String(counts.low)}    sub={`${Math.round(counts.low  / total * 100)}%`} />
          </div>

          <SectionDivider />

          <div className="crowding-bars">
            {(["high", "medium", "low"] as const).map((level) => {
              const colors = { high: "#ef4444", medium: "#f97316", low: "#22c55e" };
              const pct = Math.round(counts[level] / total * 100);
              return (
                <div key={level} className="crowding-bar-row">
                  <span className="crowding-bar-label">{level.charAt(0).toUpperCase() + level.slice(1)}</span>
                  <div className="crowding-bar-track">
                    <div
                      className="crowding-bar-fill"
                      style={{ width: `${pct}%`, background: colors[level] }}
                    />
                  </div>
                  <span className="crowding-bar-pct">{pct}%</span>
                </div>
              );
            })}
          </div>

          <SectionDivider />
          <h3 className="sidebar-table-title">Routes by High Crowding</h3>

          {topRoutes.length === 0
            ? <EmptyState msg="No crowding predictions. Run the data pipeline first." />
            : (
              <ul className="data-list">
                {topRoutes.map(([routeId, b]) => (
                  <li key={routeId} className="data-list-item">
                    <span className="data-list-primary">Route {routeId}</span>
                    <span className="crowding-mini-dots">
                      {b.high   > 0 && <span className="dot dot--high"   title={`${b.high} high`}   />}
                      {b.medium > 0 && <span className="dot dot--medium" title={`${b.medium} med`}   />}
                      {b.low    > 0 && <span className="dot dot--low"    title={`${b.low} low`}    />}
                    </span>
                  </li>
                ))}
              </ul>
            )
          }
        </>
      )}
    </>
  );
}

// ─── Section: Safety ─────────────────────────────────────────────────────────

interface SafetyRow {
  stop_id: string;
  safety_score: number;
  crime_incidents_nearby: number;
  collisions_nearby: number;
  lighting_score: number;
  pedestrian_infra_score: number;
  last_computed_at: string;
}

function SafetyPanel() {
  const [rows,    setRows]    = useState<SafetyRow[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!API_BASE) return;
    setLoading(true);
    axios
      .get(`${API_BASE}/safety/stops`, { headers: apiHeaders() })
      .then((r) => setRows(r.data as SafetyRow[]))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, []);

  const sorted    = [...rows].sort((a, b) => b.safety_score - a.safety_score);
  const avgScore  = rows.length ? rows.reduce((s, r) => s + r.safety_score, 0) / rows.length : 0;
  const highRisk  = rows.filter((r) => r.safety_score > 5).length;

  function riskLabel(score: number): string {
    if (score <= 2) return "Low";
    if (score <= 5) return "Moderate";
    if (score <= 8) return "Elevated";
    return "High";
  }
  function riskClass(score: number): string {
    if (score <= 2) return "delay-badge--on-time";
    if (score <= 5) return "delay-badge--minor";
    if (score <= 8) return "delay-badge--moderate";
    return "delay-badge--severe";
  }

  return (
    <>
      <p className="sidebar-desc">Stop-level safety scores based on nearby crime and collision incidents.</p>
      <SectionDivider />

      {loading ? <Spinner /> : (
        <>
          <div className="kpi-grid">
            <KpiCard label="Stops scored" value={String(rows.length)} />
            <KpiCard label="Avg score"    value={fmt(avgScore, 1)} />
            <KpiCard label="High risk"    value={String(highRisk)} sub="score > 5" />
          </div>

          <SectionDivider />
          <h3 className="sidebar-table-title">Most At-Risk Stops</h3>

          {sorted.length === 0
            ? <EmptyState msg="No safety scores. Load incidents and run safety_scoring." />
            : (
              <ul className="data-list">
                {sorted.slice(0, 10).map((r) => (
                  <li key={r.stop_id} className="data-list-item">
                    <span className="data-list-primary">{r.stop_id}</span>
                    <span className={`delay-badge ${riskClass(r.safety_score)}`}>
                      {riskLabel(r.safety_score)} ({fmt(r.safety_score, 1)})
                    </span>
                  </li>
                ))}
              </ul>
            )
          }
        </>
      )}
    </>
  );
}

// ─── Section: Coverage ────────────────────────────────────────────────────────

interface CoverageCell {
  id: number;
  cell_id: string;
  nearest_stop_id: string | null;
  distance_to_nearest_stop_m: number;
  stops_within_walk: number;
  effective_frequency_per_hour: number;
  equity_score: number | null;
}

function CoveragePanel() {
  const [cells,   setCells]   = useState<CoverageCell[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!API_BASE) return;
    setLoading(true);
    axios
      .get(`${API_BASE}/coverage/cells`, { headers: apiHeaders() })
      .then((r) => {
        const fc = r.data as GeoJSON.FeatureCollection;
        setCells(fc.features.map((f) => f.properties as CoverageCell));
      })
      .catch(() => setCells([]))
      .finally(() => setLoading(false));
  }, []);

  const wellServed  = cells.filter((c) => c.effective_frequency_per_hour >= 2  && c.distance_to_nearest_stop_m <= 400).length;
  const desertCells = cells.filter((c) => c.effective_frequency_per_hour <  2  || c.distance_to_nearest_stop_m >  400).length;
  const avgFreq     = cells.length ? cells.reduce((s, c) => s + (c.effective_frequency_per_hour || 0), 0) / cells.length : 0;
  const pctServed   = cells.length ? Math.round(wellServed / cells.length * 100) : 0;

  // suppress unused variable warning
  void desertCells;

  return (
    <>
      <p className="sidebar-desc">Transit accessibility grid and underserved desert zones.</p>
      <SectionDivider />

      {loading ? <Spinner /> : (
        <>
          <div className="kpi-grid">
            <KpiCard label="Grid cells"    value={String(cells.length)} />
            <KpiCard label="Well served"   value={`${pctServed}%`}  sub="≥ 2 trips/hr" />
            <KpiCard label="Avg frequency" value={fmt(avgFreq, 1)}   sub="trips/hr" />
          </div>

          <SectionDivider />

          <div className="coverage-breakdown">
            <div className="coverage-bar-row">
              <span className="coverage-bar-label">Well served</span>
              <div className="coverage-bar-track">
                <div className="coverage-bar-fill coverage-bar-fill--served" style={{ width: `${pctServed}%` }} />
              </div>
              <span className="coverage-bar-pct">{pctServed}%</span>
            </div>
            <div className="coverage-bar-row">
              <span className="coverage-bar-label">Desert zones</span>
              <div className="coverage-bar-track">
                <div className="coverage-bar-fill coverage-bar-fill--desert" style={{ width: `${100 - pctServed}%` }} />
              </div>
              <span className="coverage-bar-pct">{100 - pctServed}%</span>
            </div>
          </div>

          {cells.length === 0 && (
            <EmptyState msg="No coverage data. Run build_coverage_cells() in the data pipeline." />
          )}
        </>
      )}
    </>
  );
}

// ─── Section: Demand ─────────────────────────────────────────────────────────

interface DemandRow {
  route_id: string;
  trip_id: string | null;
  stop_id: string | null;
  service_date: string;
  time_bucket: string;
  forecast_boardings: number;
  lower_ci: number | null;
  upper_ci: number | null;
  model_version: string | null;
}

function DemandPanel({ startDate, endDate }: { startDate: string; endDate: string }) {
  const [rows,    setRows]    = useState<DemandRow[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!API_BASE) return;
    setLoading(true);
    axios
      .get(`${API_BASE}/demand/forecasts`, {
        params:  { start_date: startDate, end_date: endDate },
        headers: apiHeaders(),
      })
      .then((r) => setRows(r.data as DemandRow[]))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [startDate, endDate]);

  const totalBoardings = rows.reduce((s, r) => s + (r.forecast_boardings || 0), 0);

  const byRoute: Record<string, number> = {};
  for (const r of rows) {
    byRoute[r.route_id] = (byRoute[r.route_id] || 0) + (r.forecast_boardings || 0);
  }
  const topRoutes = Object.entries(byRoute).sort(([, a], [, b]) => b - a).slice(0, 10);
  const maxVal = topRoutes[0]?.[1] || 1;

  return (
    <>
      <p className="sidebar-desc">Short-term demand forecasts by route and stop.</p>
      <SectionDivider />

      {loading ? <Spinner /> : (
        <>
          <div className="kpi-grid">
            <KpiCard label="Total boardings" value={totalBoardings.toLocaleString()} />
            <KpiCard label="Routes"          value={String(Object.keys(byRoute).length)} />
            <KpiCard label="Predictions"     value={String(rows.length)} />
          </div>

          <SectionDivider />
          <h3 className="sidebar-table-title">Top Routes by Boardings</h3>

          {topRoutes.length === 0
            ? <EmptyState msg="No demand forecasts. Run the data pipeline first." />
            : (
              <ul className="data-list demand-list">
                {topRoutes.map(([routeId, boardings]) => (
                  <li key={routeId} className="data-list-item demand-list-item">
                    <span className="data-list-primary">Route {routeId}</span>
                    <div className="demand-bar-track">
                      <div
                        className="demand-bar-fill"
                        style={{ width: `${Math.round((boardings / maxVal) * 100)}%` }}
                      />
                    </div>
                    <span className="demand-bar-value">{Math.round(boardings)}</span>
                  </li>
                ))}
              </ul>
            )
          }
        </>
      )}
    </>
  );
}

// ─── Section: Route Explorer ──────────────────────────────────────────────────

interface RouteRow { route_id: string; route_short_name: string; route_long_name: string; route_color: string | null; }

function RouteExplorerPanel({ onRouteSelect, selectedRouteId, startDate, endDate }: { onRouteSelect: (id: string) => void; selectedRouteId: string | null; startDate: string; endDate: string }) {
  const [routes, setRoutes] = useState<RouteRow[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!API_BASE) return;
    setLoading(true);
    axios.get(`${API_BASE}/routes`, { headers: apiHeaders() })
      .then(r => setRoutes(r.data as RouteRow[]))
      .catch(() => setRoutes([]))
      .finally(() => setLoading(false));
  }, []);

  const filtered = routes.filter(r =>
    !filter || r.route_short_name?.toLowerCase().includes(filter.toLowerCase()) ||
    r.route_long_name?.toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <>
      <p className="sidebar-desc">Select a route to highlight its path and stops on the map.</p>
      <SectionDivider />
      <input
        className="route-search-input"
        placeholder="Search routes…"
        value={filter}
        onChange={e => setFilter(e.target.value)}
      />
      {loading ? <Spinner /> : (
        <ul className="data-list route-list">
          {filtered.slice(0, 40).map(r => (
            <li key={r.route_id}
              className={`data-list-item route-list-item ${r.route_id === selectedRouteId ? "route-list-item--active" : ""}`}
              onClick={() => onRouteSelect(r.route_id)}
            >
              <span className="route-chip-mini"
                style={{
                  background: `#${r.route_color || "3b82f6"}22`,
                  borderColor: `#${r.route_color || "3b82f6"}66`,
                  color: `#${r.route_color || "93c5fd"}`,
                }}>
                {r.route_short_name || r.route_id}
              </span>
              <span className="data-list-primary route-long-name">{r.route_long_name ?? ""}</span>
            </li>
          ))}
          {filtered.length === 0 && <EmptyState msg="No routes match." />}
        </ul>
      )}
      {selectedRouteId && (
        <RouteHeadwayChart routeId={selectedRouteId} startDate={startDate} endDate={endDate} />
      )}
    </>
  );
}

// ─── Section: Bunching ────────────────────────────────────────────────────────

interface BunchingRow {
  route_id: string;
  event_count: number;
  avg_delay_seconds: number;
  delay_stddev: number;
  max_delay_seconds: number;
  late_events: number;
  late_pct: number;
}

function BunchingPanel({ startDate, endDate }: { startDate: string; endDate: string }) {
  const [rows, setRows] = useState<BunchingRow[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!API_BASE) return;
    setLoading(true);
    axios.get(`${API_BASE}/bunching/summary`, {
      params: { start_date: startDate, end_date: endDate },
      headers: apiHeaders(),
    })
      .then(r => setRows(r.data as BunchingRow[]))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [startDate, endDate]);

  const maxStddev = rows[0]?.delay_stddev || 1;
  const avgStddev = rows.length ? rows.reduce((s, r) => s + r.delay_stddev, 0) / rows.length : 0;
  const irregular = rows.filter(r => r.delay_stddev > avgStddev * 1.5).length;

  function irregClass(s: number): string {
    if (s < avgStddev * 0.5) return "delay-badge--on-time";
    if (s < avgStddev)        return "delay-badge--minor";
    if (s < avgStddev * 1.5)  return "delay-badge--moderate";
    return "delay-badge--severe";
  }

  return (
    <>
      <p className="sidebar-desc">Routes ranked by delay variability — high σ indicates bunching or gapping.</p>
      <SectionDivider />
      {loading ? <Spinner /> : (
        <>
          <div className="kpi-grid">
            <KpiCard label="Routes"     value={String(rows.length)} />
            <KpiCard label="Avg σ"      value={`${Math.round(avgStddev)}s`} />
            <KpiCard label="Irregular"  value={String(irregular)} sub="σ > 1.5× avg" />
          </div>
          <SectionDivider />
          <h3 className="sidebar-table-title">Most Irregular Routes</h3>
          {rows.length === 0
            ? <EmptyState msg="No data. Run the data pipeline first." />
            : (
              <ul className="data-list">
                {rows.slice(0, 15).map(r => (
                  <li key={r.route_id} className="data-list-item bunching-row">
                    <span className="data-list-primary">Rt {r.route_id}</span>
                    <div className="bunching-bar-track">
                      <div className="bunching-bar-fill"
                        style={{ width: `${Math.round((r.delay_stddev / maxStddev) * 100)}%`,
                                 background: r.delay_stddev > avgStddev * 1.5 ? "#ef4444" : r.delay_stddev > avgStddev ? "#f97316" : "#22c55e" }} />
                    </div>
                    <span className={`delay-badge ${irregClass(r.delay_stddev)}`}>σ {Math.round(r.delay_stddev)}s</span>
                  </li>
                ))}
              </ul>
            )
          }
        </>
      )}
    </>
  );
}

// ─── CSV export helper ────────────────────────────────────────────────────────

function downloadCSV(filename: string, rows: object[]) {
  if (!rows.length) return;
  const keys = Object.keys(rows[0]);
  const lines = [
    keys.join(","),
    ...rows.map((r) =>
      keys.map((k) => JSON.stringify((r as Record<string, unknown>)[k] ?? "")).join(",")
    ),
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Reliability trend chart ─────────────────────────────────────────────────

interface TrendPoint { date: string; avg_delay: number; on_time_pct: number; }

function ReliabilityTrendChart({ startDate, endDate }: { startDate: string; endDate: string }) {
  const [data, setData] = useState<TrendPoint[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    axios.get(`${API_BASE}/reliability/trend`, {
      params: { start_date: startDate, end_date: endDate },
      headers: apiHeaders(),
    })
      .then((r) => setData(r.data as TrendPoint[]))
      .catch(() => setData([]))
      .finally(() => setLoading(false));
  }, [startDate, endDate]);

  if (loading) return <Spinner />;
  if (data.length === 0) return <EmptyState msg="No trend data yet." />;

  return (
    <div style={{ width: "100%", height: 140, marginTop: "0.5rem" }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: -20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.1)" />
          <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#94a3b8" }} tickFormatter={(v: string) => v.slice(5)} />
          <YAxis yAxisId={0} tick={{ fontSize: 10, fill: "#94a3b8" }} />
          <YAxis yAxisId={1} orientation="right" tick={{ fontSize: 10, fill: "#94a3b8" }} unit="%" />
          <Tooltip
            contentStyle={{ background: "#0f172a", border: "1px solid rgba(148,163,184,0.2)", borderRadius: 6, fontSize: 12 }}
            labelStyle={{ color: "#e2e8f0" }}
            itemStyle={{ color: "#94a3b8" }}
          />
          <Line yAxisId={0} type="monotone" dataKey="avg_delay" stroke="#f97316" strokeWidth={2} dot={false} name="Avg delay (s)" />
          <Line yAxisId={1} type="monotone" dataKey="on_time_pct" stroke="#22c55e" strokeWidth={2} dot={false} name="On-time %" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─── Route headway chart ──────────────────────────────────────────────────────

interface HeadwayPoint { hour: number; avg_headway_minutes: number; }

function RouteHeadwayChart({ routeId, startDate, endDate }: { routeId: string; startDate: string; endDate: string }) {
  const [data, setData] = useState<HeadwayPoint[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    axios.get(`${API_BASE}/routes/${encodeURIComponent(routeId)}/headways`, {
      params: { start_date: startDate, end_date: endDate },
      headers: apiHeaders(),
    })
      .then((r) => setData(r.data as HeadwayPoint[]))
      .catch(() => setData([]))
      .finally(() => setLoading(false));
  }, [routeId, startDate, endDate]);

  if (loading) return <Spinner />;
  if (data.length === 0) return null;

  return (
    <>
      <SectionDivider />
      <h3 className="sidebar-table-title">Headway by Hour of Day</h3>
      <div style={{ width: "100%", height: 130 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: -20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.1)" />
            <XAxis dataKey="hour" tick={{ fontSize: 10, fill: "#94a3b8" }} tickFormatter={(h: number) => `${h}h`} />
            <YAxis tick={{ fontSize: 10, fill: "#94a3b8" }} unit="m" />
            <Tooltip
              contentStyle={{ background: "#0f172a", border: "1px solid rgba(148,163,184,0.2)", borderRadius: 6, fontSize: 12 }}
              labelStyle={{ color: "#e2e8f0" }}
              itemStyle={{ color: "#94a3b8" }}
            />
            <Line type="monotone" dataKey="avg_headway_minutes" stroke="#38bdf8" strokeWidth={2} dot={false} name="Headway (min)" />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}

// ─── Section: Live Vehicles ───────────────────────────────────────────────────

interface Vehicle {
  vehicle_id: string | null;
  trip_id: string | null;
  route_id: string | null;
  latitude: number;
  longitude: number;
  bearing: number | null;
  speed: number | null;
  occupancy_status: string | null;
  timestamp: string | null;
}

function LiveVehiclesPanel() {
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  const fetchVehicles = () => {
    setLoading(true);
    axios.get(`${API_BASE}/vehicles/live`)
      .then((r) => {
        // Backend returns GeoJSON FeatureCollection; extract properties from each feature
        const fc = r.data as GeoJSON.FeatureCollection;
        const vs = fc.features.map((f) => f.properties as Vehicle);
        setVehicles(vs);
        const latest = vs.reduce<string | null>((max, v) => {
          const t = v.timestamp;
          return t && (!max || t > max) ? t : max;
        }, null);
        setLastUpdated(latest);
      })
      .catch(() => setVehicles([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchVehicles();
    const id = setInterval(fetchVehicles, 30_000);
    return () => clearInterval(id);
  }, []);

  const byRoute: Record<string, number> = {};
  for (const v of vehicles) {
    if (v.route_id) byRoute[v.route_id] = (byRoute[v.route_id] || 0) + 1;
  }
  const topRoutes = Object.entries(byRoute).sort((a, b) => b[1] - a[1]).slice(0, 12);

  return (
    <>
      <p className="sidebar-desc">Live vehicle positions from GTFS-RT, refreshed every 30 s.</p>
      <SectionDivider />
      {loading && vehicles.length === 0 ? (
        <Spinner />
      ) : (
        <>
          <div className="kpi-grid">
            <KpiCard label="Active vehicles" value={String(vehicles.length)} />
            <KpiCard label="Active routes" value={String(Object.keys(byRoute).length)} />
            <KpiCard label="Updated" value={lastUpdated ? new Date(lastUpdated).toLocaleTimeString() : "—"} />
          </div>
          <SectionDivider />
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
            <h3 className="sidebar-table-title" style={{ margin: 0 }}>Vehicles by Route</h3>
            <button className="preset-btn" onClick={fetchVehicles}>Refresh</button>
          </div>
          {topRoutes.length === 0 ? (
            <EmptyState msg="No live vehicles. Run the GTFS-RT ingestor to populate." />
          ) : (
            <ul className="data-list">
              {topRoutes.map(([routeId, count]) => (
                <li key={routeId} className="data-list-item">
                  <span className="data-list-primary">Route {routeId}</span>
                  <span className="delay-badge delay-badge--on-time">{count} vehicle{count !== 1 ? "s" : ""}</span>
                </li>
              ))}
            </ul>
          )}
          {vehicles.length > 0 && (
            <button className="export-btn" style={{ marginTop: "0.5rem" }} onClick={() => downloadCSV("vehicles.csv", vehicles)}>
              Export CSV
            </button>
          )}
        </>
      )}
    </>
  );
}

// ─── Section: Route Comparison ────────────────────────────────────────────────

interface CompareRoute {
  route_id: string;
  route_short_name: string;
  avg_delay_seconds: number;
  on_time_pct: number;
  event_count: number;
  delay_stddev: number | null;
  stop_count: number | null;
}

function RouteComparisonPanel({ startDate, endDate }: { startDate: string; endDate: string }) {
  const [routes, setRoutes] = useState<{ route_id: string; route_short_name: string }[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [data, setData] = useState<CompareRoute[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");

  useEffect(() => {
    axios.get(`${API_BASE}/routes`, { headers: apiHeaders() })
      .then((r) => setRoutes(r.data))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (selected.length === 0) { setData([]); return; }
    setLoading(true);
    axios.get(`${API_BASE}/routes/compare`, {
      params: { route_ids: selected.join(","), start_date: startDate, end_date: endDate },
      headers: apiHeaders(),
    })
      .then((r) => setData(r.data as CompareRoute[]))
      .catch(() => setData([]))
      .finally(() => setLoading(false));
  }, [selected, startDate, endDate]);

  const filtered = routes.filter(
    (r) =>
      !search ||
      r.route_short_name?.toLowerCase().includes(search.toLowerCase()) ||
      r.route_id.toLowerCase().includes(search.toLowerCase())
  );

  const maxDelay = data.length ? Math.max(...data.map((d) => d.avg_delay_seconds), 1) : 1;

  return (
    <>
      <p className="sidebar-desc">Select up to 5 routes to compare performance side-by-side.</p>
      <SectionDivider />
      <input
        className="route-search-input"
        placeholder="Add route…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      <ul className="data-list route-list" style={{ maxHeight: "120px", overflowY: "auto", marginBottom: "0.5rem" }}>
        {filtered.slice(0, 20).map((r) => (
          <li
            key={r.route_id}
            className={`data-list-item route-list-item ${selected.includes(r.route_id) ? "route-list-item--active" : ""}`}
            onClick={() => {
              setSelected((prev) =>
                prev.includes(r.route_id)
                  ? prev.filter((x) => x !== r.route_id)
                  : prev.length < 5
                  ? [...prev, r.route_id]
                  : prev
              );
              setSearch("");
            }}
          >
            <span className="route-chip-mini">{r.route_short_name || r.route_id}</span>
          </li>
        ))}
      </ul>
      {selected.length > 0 && (
        <div className="comparison-chips">
          {selected.map((id) => (
            <span
              key={id}
              className="route-chip"
              style={{ cursor: "pointer" }}
              onClick={() => setSelected((prev) => prev.filter((x) => x !== id))}
            >
              {routes.find((r) => r.route_id === id)?.route_short_name || id} ✕
            </span>
          ))}
        </div>
      )}
      {loading ? (
        <Spinner />
      ) : data.length > 0 ? (
        <>
          <SectionDivider />
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h3 className="sidebar-table-title" style={{ margin: 0 }}>Comparison</h3>
            <button className="export-btn" onClick={() => downloadCSV("route_comparison.csv", data)}>Export CSV</button>
          </div>
          <ul className="data-list" style={{ marginTop: "0.5rem" }}>
            {data.map((d) => (
              <li key={d.route_id} className="data-list-item" style={{ flexDirection: "column", alignItems: "flex-start", gap: "0.25rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between", width: "100%" }}>
                  <span className="data-list-primary">Route {d.route_short_name || d.route_id}</span>
                  <span className={`delay-badge delay-badge--${d.avg_delay_seconds < 60 ? "on-time" : d.avg_delay_seconds < 180 ? "minor" : "moderate"}`}>
                    {fmtDelay(d.avg_delay_seconds)}
                  </span>
                </div>
                <div className="bunching-bar-track" style={{ width: "100%" }}>
                  <div
                    className="bunching-bar-fill"
                    style={{
                      width: `${Math.round((d.avg_delay_seconds / maxDelay) * 100)}%`,
                      background: d.avg_delay_seconds < 60 ? "#22c55e" : d.avg_delay_seconds < 180 ? "#f97316" : "#ef4444",
                    }}
                  />
                </div>
                <div style={{ display: "flex", gap: "0.5rem", fontSize: "0.72rem", color: "#94a3b8" }}>
                  <span>{d.on_time_pct ?? "—"}% on-time</span>
                  <span>{d.event_count} trips</span>
                  {d.stop_count != null && <span>{d.stop_count} stops</span>}
                </div>
              </li>
            ))}
          </ul>
        </>
      ) : selected.length === 0 ? (
        <EmptyState msg="Select routes above to compare." />
      ) : null}
    </>
  );
}

// ─── Root Sidebar component ───────────────────────────────────────────────────

interface SidebarProps {
  activeSection:    Section;
  startDate:        string;
  endDate:          string;
  onStartDateChange: (v: string) => void;
  onEndDateChange:   (v: string) => void;
  onRouteSelect:    (id: string) => void;
  selectedRouteId:  string | null;
}

const SECTION_TITLES: Record<Section, string> = {
  reliability: "Transit Reliability",
  crowding:    "Crowding Prediction",
  safety:      "Stop Safety",
  coverage:    "Transit Coverage",
  demand:      "Demand Forecast",
  routes:      "Route Explorer",
  bunching:    "Bunching Analysis",
  vehicles:    "Live Vehicles",
  comparison:  "Route Comparison",
};

export const Sidebar: React.FC<SidebarProps> = ({
  activeSection,
  startDate,
  endDate,
  onStartDateChange,
  onEndDateChange,
  onRouteSelect,
  selectedRouteId,
}) => {
  return (
    <aside className="sidebar">
      <h2 className="sidebar-section-title">{SECTION_TITLES[activeSection]}</h2>

      <div className="sidebar-date-range">
        <div className="date-presets">
          {[
            { label: "Today", days: 0 },
            { label: "7d",    days: 7 },
            { label: "30d",   days: 30 },
          ].map(({ label, days }) => (
            <button key={label} className="preset-btn" onClick={() => {
              const end = new Date();
              const start = new Date();
              start.setDate(start.getDate() - days);
              onEndDateChange(end.toISOString().slice(0, 10));
              onStartDateChange(start.toISOString().slice(0, 10));
            }}>{label}</button>
          ))}
        </div>
        <label>
          <span className="label-text">From</span>
          <input
            type="date"
            value={startDate}
            onChange={(e) => onStartDateChange(e.target.value)}
            className="date-input"
          />
        </label>
        <label>
          <span className="label-text">To</span>
          <input
            type="date"
            value={endDate}
            onChange={(e) => onEndDateChange(e.target.value)}
            className="date-input"
          />
        </label>
      </div>

      {activeSection === "reliability" && <ReliabilityPanel startDate={startDate} endDate={endDate} />}
      {activeSection === "crowding"    && <CrowdingPanel    startDate={startDate} endDate={endDate} />}
      {activeSection === "safety"      && <SafetyPanel />}
      {activeSection === "coverage"    && <CoveragePanel />}
      {activeSection === "demand"      && <DemandPanel     startDate={startDate} endDate={endDate} />}
      {activeSection === "routes"      && <RouteExplorerPanel onRouteSelect={onRouteSelect} selectedRouteId={selectedRouteId} startDate={startDate} endDate={endDate} />}
      {activeSection === "bunching"    && <BunchingPanel startDate={startDate} endDate={endDate} />}
      {activeSection === "vehicles"    && <LiveVehiclesPanel />}
      {activeSection === "comparison"  && <RouteComparisonPanel startDate={startDate} endDate={endDate} />}

      <p className="sidebar-backend-hint">
        API: <code>{API_BASE}</code>
      </p>
    </aside>
  );
};

import React, { useEffect, useState } from "react";
import axios from "axios";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
  LabelList,
} from "recharts";

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string) || "http://localhost:8000";
const API_KEY  = (import.meta.env.VITE_API_KEY  as string) || "";

function apiHeaders(): Record<string, string> {
  return API_KEY ? { "X-API-Key": API_KEY } : {};
}

// ─── Types ────────────────────────────────────────────────────────────────────

interface AgencyOtp {
  agency_id: string;
  agency_name: string;
  total_observations: number;
  on_time_count: number;
  on_time_pct: number;
  avg_delay_seconds: number;
  median_delay_seconds: number;
  p90_delay_seconds: number;
  trend: number;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function barColor(otp: number): string {
  if (otp >= 90) return "#22c55e";
  if (otp >= 75) return "#facc15";
  return "#ef4444";
}

function trendArrow(trend: number): string {
  if (trend > 0.5) return "▲";
  if (trend < -0.5) return "▼";
  return "—";
}

function trendColor(trend: number): string {
  if (trend > 0.5) return "#22c55e";
  if (trend < -0.5) return "#ef4444";
  return "#94a3b8";
}

function fmt(n: number | null | undefined, dec = 1): string {
  if (n == null || isNaN(Number(n))) return "—";
  return Number(n).toFixed(dec);
}

function fmtSeconds(s: number | null | undefined): string {
  if (s == null || isNaN(Number(s))) return "—";
  const abs = Math.abs(Number(s));
  if (abs < 60) return `${Math.round(Number(s))}s`;
  return `${(Number(s) / 60).toFixed(1)}m`;
}

// ─── Custom bar label — shows trend arrow to the right of each bar ────────────

interface LabelProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  index?: number;
  data: AgencyOtp[];
}

function TrendLabel({ x = 0, y = 0, width = 0, height = 0, index = 0, data }: LabelProps) {
  const entry = data[index];
  if (!entry) return null;
  const { trend } = entry;
  const arrow = trendArrow(trend);
  const color = trendColor(trend);
  const sign = trend > 0 ? "+" : "";
  return (
    <text
      x={x + width + 6}
      y={y + height / 2 + 4}
      fill={color}
      fontSize={10}
      fontWeight={600}
    >
      {arrow} {sign}{fmt(trend, 1)}%
    </text>
  );
}

// ─── KPI card ─────────────────────────────────────────────────────────────────

function KpiCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="kpi-card">
      <span className="kpi-value">{value}</span>
      <span className="kpi-label">{label}</span>
      {sub && <span className="kpi-sub">{sub}</span>}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

interface BenchmarkPanelProps {
  startDate: string;
  endDate: string;
}

export default function BenchmarkPanel({ startDate, endDate }: BenchmarkPanelProps) {
  const [data, setData] = useState<AgencyOtp[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!startDate || !endDate) return;
    setLoading(true);
    setError(null);
    axios
      .get<AgencyOtp[]>(`${API_BASE}/benchmarks/agency-otp`, {
        params: { start_date: startDate, end_date: endDate },
        headers: apiHeaders(),
      })
      .then((r) => setData(r.data))
      .catch(() => setError("Failed to load benchmark data."))
      .finally(() => setLoading(false));
  }, [startDate, endDate]);

  if (loading) return <div className="sidebar-spinner" />;

  if (error) return <p className="sidebar-empty">{error}</p>;

  if (data.length === 0) {
    return (
      <p className="sidebar-empty">
        No stop observation data for this date range.
        Load the 511.org archive with <code>load_stop_observations</code>.
      </p>
    );
  }

  const best  = data[0];
  const worst = data[data.length - 1];
  const regionalAvg =
    data.reduce((sum, d) => sum + (d.on_time_pct ?? 0), 0) / data.length;

  const chartData = [...data].reverse(); // best at top in horizontal chart

  return (
    <>
      {/* ── KPIs ── */}
      <div className="kpi-grid">
        <KpiCard
          label="Best Agency"
          value={best.agency_name}
          sub={`${fmt(best.on_time_pct)}% on-time`}
        />
        <KpiCard
          label="Regional Avg"
          value={`${fmt(regionalAvg)}%`}
          sub="on-time"
        />
        <KpiCard
          label="Worst Agency"
          value={worst.agency_name}
          sub={`${fmt(worst.on_time_pct)}% on-time`}
        />
      </div>

      <hr className="sidebar-divider" />

      {/* ── Horizontal bar chart ── */}
      <h3 className="sidebar-table-title">On-Time Performance by Agency</h3>
      <div className="benchmark-chart-wrap">
        <ResponsiveContainer width="100%" height={Math.max(chartData.length * 36, 120)}>
          <BarChart
            layout="vertical"
            data={chartData}
            margin={{ top: 4, right: 72, bottom: 4, left: 4 }}
          >
            <XAxis
              type="number"
              domain={[0, 100]}
              unit="%"
              tick={{ fontSize: 10, fill: "#94a3b8" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              type="category"
              dataKey="agency_name"
              width={130}
              tick={{ fontSize: 11, fill: "#e2e8f0" }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              cursor={{ fill: "rgba(148,163,184,0.05)" }}
              contentStyle={{
                background: "#0f172a",
                border: "1px solid rgba(148,163,184,0.2)",
                borderRadius: 6,
                fontSize: 12,
              }}
              labelStyle={{ color: "#e2e8f0", fontWeight: 600 }}
              formatter={(value: unknown) => [
                typeof value === "number" ? `${fmt(value)}%` : "—",
                "On-time",
              ]}
            />
            <Bar dataKey="on_time_pct" radius={[0, 3, 3, 0]} maxBarSize={22}>
              {chartData.map((entry, i) => (
                <Cell key={i} fill={barColor(entry.on_time_pct)} fillOpacity={0.85} />
              ))}
              <LabelList
                content={(props) => (
                  <TrendLabel {...(props as any)} data={chartData} />
                )}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <hr className="sidebar-divider" />

      {/* ── Legend ── */}
      <div className="benchmark-legend">
        <span style={{ color: "#22c55e" }}>■</span> ≥90% on-time
        <span style={{ color: "#facc15", marginLeft: "0.75rem" }}>■</span> 75–90%
        <span style={{ color: "#ef4444", marginLeft: "0.75rem" }}>■</span> &lt;75%
      </div>

      <hr className="sidebar-divider" />

      {/* ── Data table ── */}
      <h3 className="sidebar-table-title">Detailed Metrics</h3>
      <div className="benchmark-table-wrap">
        <table className="benchmark-table">
          <thead>
            <tr>
              <th>Agency</th>
              <th>OTP %</th>
              <th>Avg delay</th>
              <th>Median</th>
              <th>P90</th>
              <th>Trend</th>
              <th>Observations</th>
            </tr>
          </thead>
          <tbody>
            {data.map((row) => {
              const trend = row.trend ?? 0;
              return (
                <tr key={row.agency_id}>
                  <td>
                    <span className="benchmark-agency-id">{row.agency_id}</span>{" "}
                    {row.agency_name}
                  </td>
                  <td style={{ color: barColor(row.on_time_pct), fontWeight: 600 }}>
                    {fmt(row.on_time_pct)}%
                  </td>
                  <td>{fmtSeconds(row.avg_delay_seconds)}</td>
                  <td>{fmtSeconds(row.median_delay_seconds)}</td>
                  <td>{fmtSeconds(row.p90_delay_seconds)}</td>
                  <td style={{ color: trendColor(trend), fontWeight: 600 }}>
                    {trendArrow(trend)}{" "}
                    {trend !== 0
                      ? `${trend > 0 ? "+" : ""}${fmt(trend, 1)}%`
                      : "—"}
                  </td>
                  <td style={{ color: "#94a3b8", fontSize: "0.75rem" }}>
                    {row.total_observations.toLocaleString()}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

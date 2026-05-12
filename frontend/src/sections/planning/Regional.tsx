import React, { useMemo } from "react";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { useFilters } from "../../context/FilterContext";
import { useAgencies } from "../../context/AgenciesContext";
import { useAgencyRollups, type AgencyRollup } from "../../lib/useAgencyRollups";
import {
  KpiCard, DataList, Spinner, EmptyState, SectionError, ExportButton,
  type DataListItem,
} from "../../components/primitives";
import { fmtMin, fmtPct } from "../../lib/format";
import { agencyColor } from "../../lib/agencies";
import "../sections.css";
import "./planning.css";

const MODE_ORDER: ReadonlyArray<string> = ["bus", "rail", "ferry", "multi", "other"];
const MODE_LABELS: Record<string, string> = {
  bus: "Bus", rail: "Rail", ferry: "Ferry", multi: "Multi-modal", other: "Other",
};
const MODE_COLORS: Record<string, string> = {
  bus:   "#3b82f6",
  rail:  "#a855f7",
  ferry: "#0099CC",
  multi: "#22c55e",
  other: "#64748b",
};

/** Regional — for MPO / regional planners coordinating across the
 *  30+ Bay Area operators. Composes the agencies-rollup endpoint
 *  into a side-by-side leaderboard, modal share, and an
 *  investment-priority focus list. */
export const Regional: React.FC = () => {
  const { filters }   = useFilters();
  const { agencies, byId } = useAgencies();
  const { rows: rollupAll, loading, error } = useAgencyRollups(filters.startDate, filters.endDate);

  // Restrict to "useful" agencies (drops 511 admin + un-ingested operators).
  const rollup = useMemo(
    () => rollupAll.filter(r => byId[r.agency_id]?.has_data !== false),
    [rollupAll, byId],
  );

  const modeShare = useMemo(() => {
    const tally = new Map<string, { routes: number; stops: number }>();
    for (const r of rollup) {
      const mode = (byId[r.agency_id]?.agency_type ?? "other").toLowerCase();
      const key  = MODE_ORDER.includes(mode) ? mode : "other";
      const cur  = tally.get(key) ?? { routes: 0, stops: 0 };
      cur.routes += r.routes_count ?? 0;
      cur.stops  += r.stops_count  ?? 0;
      tally.set(key, cur);
    }
    return MODE_ORDER
      .map(m => ({ mode: m, label: MODE_LABELS[m], color: MODE_COLORS[m], ...(tally.get(m) ?? { routes: 0, stops: 0 }) }))
      .filter(m => m.routes > 0 || m.stops > 0);
  }, [rollup, byId]);

  // Best / worst by OTP (only for agencies that reported any sample).
  const withOtp = rollup.filter(r => r.otp_pct != null && (r.sample_events ?? 0) > 0);
  const bestOtp  = withOtp.length ? [...withOtp].sort((a, b) => (b.otp_pct! - a.otp_pct!))[0] : null;
  const worstOtp = withOtp.length ? [...withOtp].sort((a, b) => (a.otp_pct! - b.otp_pct!))[0] : null;

  const totalRoutes = rollup.reduce((s, r) => s + (r.routes_count ?? 0), 0);

  const underperformers: DataListItem[] = withOtp
    .sort((a, b) => (a.otp_pct! - b.otp_pct!))
    .slice(0, 5)
    .map(r => ({
      id: r.agency_id,
      primary:   r.agency_name ?? r.agency_id,
      secondary: `${r.routes_count ?? 0} routes · avg ${fmtMin(r.avg_delay_seconds ?? 0)}`,
      trailing:  fmtPct(r.otp_pct),
    }));

  return (
    <div className="section">
      <div className="section__header">
        <h2 className="section__title">Regional</h2>
        <span className="section__subtitle">
          Cross-agency comparison · modal share · investment focus
        </span>
      </div>

      {error && <SectionError message={error} onRetry={() => window.location.reload()} />}

      <div className="section__kpi-strip">
        <KpiCard label="Agencies tracked" value={String(rollup.length)} sub="with operational data" />
        <KpiCard label="Best OTP"         value={bestOtp  ? fmtPct(bestOtp.otp_pct)  : "—"} sub={bestOtp  ? bestOtp.agency_name  ?? bestOtp.agency_id  : ""} />
        <KpiCard label="Worst OTP"        value={worstOtp ? fmtPct(worstOtp.otp_pct) : "—"} sub={worstOtp ? worstOtp.agency_name ?? worstOtp.agency_id : ""} deltaIsGood={false} />
        <KpiCard label="Total routes"     value={String(totalRoutes)} sub="across the region" />
        <KpiCard label="Mode mix"
          value={modeShare.length ? `${modeShare[0].label}-led` : "—"}
          sub={modeShare.length ? `${Math.round((modeShare[0].routes / Math.max(1, totalRoutes)) * 100)}% of routes` : ""}
        />
      </div>

      <div className="section__grid">
        <div className="section__panel">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <h3 className="section__panel-title">Cross-agency leaderboard</h3>
            <ExportButton
              filename="planning-regional-leaderboard.csv"
              rows={rollup.map(r => ({
                agency_id:         r.agency_id,
                agency_name:       r.agency_name ?? r.agency_id,
                mode:              byId[r.agency_id]?.agency_type ?? "",
                routes_count:      r.routes_count ?? 0,
                stops_count:       r.stops_count ?? 0,
                otp_pct:           r.otp_pct ?? null,
                avg_delay_seconds: r.avg_delay_seconds ?? null,
                hot_stops:         r.hot_stops ?? 0,
              }))}
            />
          </div>
          {loading && rollup.length === 0 ? <Spinner /> :
           rollup.length === 0 ? (
             <EmptyState message="No agency rollups available." />
           ) : (
             <Leaderboard rows={rollup} byId={byId} />
           )}
        </div>

        <div className="section__panel">
          <h3 className="section__panel-title">Modal share (routes)</h3>
          {modeShare.length === 0 ? <EmptyState message="No mode data." /> : (
            <ModalSharePie data={modeShare} totalRoutes={totalRoutes} />
          )}
        </div>
      </div>

      <div className="section__grid">
        <div className="section__panel">
          <h3 className="section__panel-title">Investment priority — bottom 5 OTP</h3>
          {underperformers.length === 0 ? (
            <EmptyState message="No agencies have OTP samples in this window." hint="Load stop_observations or widen the date range." />
          ) : (
            <DataList items={underperformers} />
          )}
        </div>

        <div className="planning-placeholder" style={{ borderRadius: "var(--radius-2)" }}>
          <div className="planning-placeholder__phase">Coming in a follow-up</div>
          <h3 className="planning-placeholder__title" style={{ fontSize: "var(--text-md)" }}>Transfer-point reliability + county coverage</h3>
          <p className="planning-placeholder__body" style={{ fontSize: "var(--text-sm)" }}>
            Two MPO-shaped slices that need new backend before they land:
          </p>
          <ul className="planning-placeholder__features">
            <li>Transfer points — stops shared by ≥2 agencies, ranked by daily transfer volume.</li>
            <li>County rollup — coverage_cells joined to county polygons for the RTP cycle.</li>
            <li>Quarter-over-quarter OTP drift — needs historical rollup snapshots.</li>
          </ul>
        </div>
      </div>
    </div>
  );
};

// ────────────────────────────────────────────────────────────────────────────

interface LeaderboardProps {
  rows: AgencyRollup[];
  byId: Record<string, { agency_type?: string | null }>;
}

const Leaderboard: React.FC<LeaderboardProps> = ({ rows, byId }) => {
  // Sort: agencies with OTP first (best → worst), then those without.
  const sorted = useMemo(() => {
    return [...rows].sort((a, b) => {
      const aHas = a.otp_pct != null;
      const bHas = b.otp_pct != null;
      if (aHas !== bHas) return aHas ? -1 : 1;
      if (aHas && bHas) return (b.otp_pct! - a.otp_pct!);
      return (b.routes_count ?? 0) - (a.routes_count ?? 0);
    });
  }, [rows]);

  return (
    <div className="planning-leaderboard">
      <div className="planning-leaderboard__head">
        <span>Agency</span>
        <span>Mode</span>
        <span style={{ textAlign: "right" }}>Routes</span>
        <span style={{ textAlign: "right" }}>Stops</span>
        <span style={{ textAlign: "right" }}>OTP</span>
        <span style={{ textAlign: "right" }}>Avg delay</span>
        <span style={{ textAlign: "right" }}>Hot stops</span>
      </div>
      <div className="planning-leaderboard__body">
        {sorted.map(r => {
          const mode = byId[r.agency_id]?.agency_type ?? "—";
          const otp  = r.otp_pct;
          const cls  = otp == null ? "" :
                       otp >= 90 ? "planning-leaderboard__row--good" :
                       otp >= 75 ? "" :
                       "planning-leaderboard__row--bad";
          return (
            <div key={r.agency_id} className={`planning-leaderboard__row ${cls}`}>
              <span>
                <span className="planning-leaderboard__code" style={{ color: agencyColor(r.agency_id) }}>
                  {r.agency_id}
                </span>{" "}
                <span className="planning-leaderboard__name">{r.agency_name ?? r.agency_id}</span>
              </span>
              <span className="planning-leaderboard__mode">{MODE_LABELS[mode] ?? mode}</span>
              <span style={{ textAlign: "right" }}>{r.routes_count ?? 0}</span>
              <span style={{ textAlign: "right" }}>{r.stops_count ?? 0}</span>
              <span style={{ textAlign: "right" }}>{otp == null ? "—" : fmtPct(otp)}</span>
              <span style={{ textAlign: "right" }}>{r.avg_delay_seconds == null ? "—" : fmtMin(r.avg_delay_seconds)}</span>
              <span style={{ textAlign: "right" }}>{r.hot_stops ?? 0}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

interface ModalSharePieProps {
  data: { mode: string; label: string; color: string; routes: number; stops: number }[];
  totalRoutes: number;
}

const ModalSharePie: React.FC<ModalSharePieProps> = ({ data, totalRoutes }) => (
  <div style={{ display: "flex", alignItems: "center", gap: "var(--space-4)" }}>
    <ResponsiveContainer width="55%" height={220}>
      <PieChart>
        <Pie
          data={data}
          dataKey="routes"
          nameKey="label"
          cx="50%" cy="50%"
          innerRadius={48} outerRadius={84}
          paddingAngle={2}
          isAnimationActive={false}
        >
          {data.map(d => <Cell key={d.mode} fill={d.color} />)}
        </Pie>
        <Tooltip contentStyle={{ background: "#1a2334", border: "1px solid #283448", borderRadius: 8, fontSize: 12 }} />
      </PieChart>
    </ResponsiveContainer>
    <ul className="planning-modal-legend">
      {data.map(d => (
        <li key={d.mode}>
          <span className="planning-modal-legend__swatch" style={{ background: d.color }} />
          <span className="planning-modal-legend__label">{d.label}</span>
          <span className="planning-modal-legend__value">
            {d.routes} routes · {Math.round((d.routes / Math.max(1, totalRoutes)) * 100)}%
          </span>
        </li>
      ))}
    </ul>
  </div>
);

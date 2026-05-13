import React, { useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";
import {
  KpiCard, DataList, Spinner, EmptyState, SectionError, ExportButton,
  type DataListItem,
} from "../../components/primitives";
import { SectionMap } from "../../components/SectionMap";
import { TransferDesertsPanel } from "./TransferDesertsPanel";
import "../sections.css";
import "./planning.css";

interface CoverageCellProps {
  cell_id: string;
  distance_to_nearest_stop_m: number | null;
  stops_within_walk: number | null;
  effective_frequency_per_hour: number | null;
  equity_score: number | null;
}
interface EquityCellProps {
  cell_id: string;
  equity_score: number;
  low_income_population: number;
  no_car_households: number;
  population: number;
  equity_tier: "very_high" | "high" | "medium" | "low";
}
interface DesertProps {
  id: number | string;
  desert_score: number;
  notes: string | null;
}

interface ScoredCell {
  cell_id: string;
  equity_score: number;
  equity_tier: EquityCellProps["equity_tier"];
  population: number;
  distance: number | null;
  freq: number | null;
  poor_access: boolean;
  need_score: number;
}

const POOR_ACCESS_DISTANCE_M = 400;       // ~5 min walk
const POOR_ACCESS_FREQ_PER_H = 1;          // < 1 bus per hour

/** Coverage — for the city / municipal planner.
 *  Answers "where does our city lack transit that high-need residents rely on?"
 *  by intersecting per-cell equity scores with per-cell access metrics
 *  (distance + frequency). The composite ranking is the planner-actionable
 *  output that neither Equity & Safety nor Network produces on its own. */
export const Coverage: React.FC = () => {
  const [cells,   setCells]   = useState<CoverageCellProps[]>([]);
  const [equity,  setEquity]  = useState<EquityCellProps[]>([]);
  const [deserts, setDeserts] = useState<DesertProps[]>([]);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);
  const [tick,    setTick]    = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function fetchAll() {
      setLoading(true); setError(null);
      try {
        const [cRes, eRes, dRes] = await Promise.all([
          api.get<{ features: { properties: CoverageCellProps }[] }>("/coverage/cells").catch(() => ({ data: { features: [] } })),
          api.get<{ features: { properties: EquityCellProps }[]   }>("/equity/score" ).catch(() => ({ data: { features: [] } })),
          api.get<{ features: { properties: DesertProps }[]       }>("/coverage/deserts").catch(() => ({ data: { features: [] } })),
        ]);
        if (cancelled) return;
        setCells  ((cRes.data?.features ?? []).map(f => f.properties));
        setEquity ((eRes.data?.features ?? []).map(f => f.properties));
        setDeserts((dRes.data?.features ?? []).map(f => f.properties));
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchAll();
    return () => { cancelled = true; };
  }, [tick]);

  // Join equity rows with coverage-cells on cell_id, then score by
  // equity_score weighted by access shortfall.
  const scored = useMemo<ScoredCell[]>(() => {
    const byId = new Map(cells.map(c => [c.cell_id, c]));
    return equity.map(e => {
      const cov = byId.get(e.cell_id);
      const distance = cov?.distance_to_nearest_stop_m ?? null;
      const freq     = cov?.effective_frequency_per_hour ?? null;
      const poor_access =
        (distance != null && distance > POOR_ACCESS_DISTANCE_M) ||
        (freq     != null && freq     < POOR_ACCESS_FREQ_PER_H);
      const need_score = e.equity_score * (poor_access ? 1 : 0.3);
      return {
        cell_id: e.cell_id,
        equity_score: e.equity_score,
        equity_tier:  e.equity_tier,
        population:   e.population,
        distance, freq, poor_access, need_score,
      };
    }).sort((a, b) => b.need_score - a.need_score);
  }, [cells, equity]);

  const HIGH_TIERS = new Set<EquityCellProps["equity_tier"]>(["very_high", "high"]);

  const cellCount     = cells.length;
  const desertCount   = deserts.length;
  const highNeedPop   = scored.filter(s => HIGH_TIERS.has(s.equity_tier))
                              .reduce((s, c) => s + c.population, 0);
  const underservedPop = scored.filter(s => HIGH_TIERS.has(s.equity_tier) && s.poor_access)
                               .reduce((s, c) => s + c.population, 0);
  const avgDistance = cells.length === 0 ? null :
    cells.reduce((s, c) => s + (c.distance_to_nearest_stop_m ?? 0), 0) /
      cells.filter(c => c.distance_to_nearest_stop_m != null).length;

  const fmtPop = (n: number) => n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
  const fmtDist = (m: number | null) => m == null ? "—" : `${Math.round(m)} m`;

  const underservedItems: DataListItem[] = scored
    .filter(s => HIGH_TIERS.has(s.equity_tier) && s.poor_access)
    .slice(0, 20)
    .map(s => ({
      id: s.cell_id,
      primary: s.cell_id,
      secondary: `${s.equity_tier.replace("_", " ")} need · ${fmtPop(s.population)} residents · ${fmtDist(s.distance)} to stop`,
      trailing: s.need_score.toFixed(3),
    }));

  const desertItems: DataListItem[] = [...deserts]
    .sort((a, b) => b.desert_score - a.desert_score)
    .slice(0, 20)
    .map(d => ({
      id: String(d.id),
      primary: d.notes ?? `Desert ${d.id}`,
      secondary: "Transit desert",
      trailing: d.desert_score.toFixed(2),
    }));

  return (
    <div className="section">
      <div className="section__header">
        <h2 className="section__title">Coverage</h2>
        <span className="section__subtitle">
          Where the city lacks transit that high-need residents rely on
        </span>
      </div>

      {error && <SectionError message={error} onRetry={() => setTick(t => t + 1)} />}

      <div className="section__kpi-strip">
        <KpiCard label="Coverage cells"        value={String(cellCount)} sub="hex grid" />
        <KpiCard label="Transit deserts"       value={String(desertCount)} deltaIsGood={false} />
        <KpiCard label="High-need residents"   value={fmtPop(highNeedPop)} sub="in very-high or high tier" />
        <KpiCard label="Underserved high-need" value={fmtPop(underservedPop)} sub={`> ${POOR_ACCESS_DISTANCE_M} m or < ${POOR_ACCESS_FREQ_PER_H} bus/hr`} deltaIsGood={false} />
        <KpiCard label="Avg distance"          value={fmtDist(avgDistance)} sub="cell → nearest stop" />
      </div>

      <div className="section__grid">
        <SectionMap mapMode="coverage" title="Coverage grid + transit deserts" height={460} />
        <div className="section__panel">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <h3 className="section__panel-title">Highest-need underserved zones</h3>
            <ExportButton
              filename="planning-coverage-underserved.csv"
              rows={underservedItems.map(i => ({
                cell_id: i.id, secondary: i.secondary, need_score: i.trailing,
              }))}
            />
          </div>
          {loading && underservedItems.length === 0 ? <Spinner /> :
           underservedItems.length === 0 ? (
             <EmptyState
               message="No high-need cells with poor access in this dataset."
               hint="Either coverage is sufficient, or the equity/coverage cells haven't been populated yet."
             />
           ) : (
             <DataList items={underservedItems} />
           )}
        </div>
      </div>

      <div className="section__grid">
        <div className="section__panel">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <h3 className="section__panel-title">Transit deserts ranked</h3>
            <ExportButton
              filename="planning-coverage-deserts.csv"
              rows={desertItems.map(d => ({
                id: d.id, name: d.primary, desert_score: d.trailing,
              }))}
            />
          </div>
          {loading && desertItems.length === 0 ? <Spinner /> :
           desertItems.length === 0 ? (
             <EmptyState message="No transit deserts in the current dataset." />
           ) : (
             <DataList items={desertItems} />
           )}
        </div>
        <div className="section__panel">
          <h3 className="section__panel-title">Equity tier breakdown</h3>
          {scored.length === 0 ? (
            <EmptyState message="No equity scoring data available." />
          ) : (
            <ul className="planning-coverage-tiers">
              {(["very_high", "high", "medium", "low"] as const).map(tier => {
                const cellsInTier = scored.filter(s => s.equity_tier === tier);
                const pop = cellsInTier.reduce((s, c) => s + c.population, 0);
                const pct = scored.length === 0 ? 0 : Math.round((cellsInTier.length / scored.length) * 100);
                return (
                  <li key={tier} className="planning-coverage-tier">
                    <span className={`planning-coverage-tier__chip planning-coverage-tier__chip--${tier}`}>
                      {tier.replace("_", " ")}
                    </span>
                    <span className="planning-coverage-tier__count">{cellsInTier.length} cells</span>
                    <span className="planning-coverage-tier__pop">{fmtPop(pop)} residents</span>
                    <span className="planning-coverage-tier__pct">{pct}%</span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>

      <TransferDesertsPanel />
    </div>
  );
};

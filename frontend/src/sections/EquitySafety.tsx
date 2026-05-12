import React, { useEffect, useState } from "react";
import { useFilters } from "../context/FilterContext";
import { useSelection } from "../context/SelectionContext";
import { api } from "../lib/api";
import { KpiCard, DataList, BarChart, Spinner, EmptyState, SectionError, ExportButton, type DataListItem, type BarPoint } from "../components/primitives";
import { SectionMap } from "../components/SectionMap";
import { SafetyRow } from "../types/data";
import "./sections.css";

interface EquityFeature { properties: { equity_score?: number; }; }

export const EquitySafety: React.FC = () => {
  const { filters } = useFilters();
  const { selection, setStopId } = useSelection();

  const [equityFeatures, setEquityFeatures] = useState<EquityFeature[]>([]);
  const [hotStops, setHotStops] = useState<SafetyRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function fetchAll() {
      setLoading(true);
      setError(null);
      try {
        const [eq, hot] = await Promise.all([
          api.get<{ features: EquityFeature[] }>("/equity/score").catch(() => ({ data: { features: [] } })),
          api.get<SafetyRow[]>("/safety/stops").catch(() => ({ data: [] })),
        ]);
        if (cancelled) return;
        setEquityFeatures(eq.data?.features ?? []);
        setHotStops(hot.data ?? []);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchAll();
    return () => { cancelled = true; };
  }, [tick]);

  const tractCount = equityFeatures.length;
  const avgEquity = tractCount > 0
    ? equityFeatures.reduce((s, f) => s + (f.properties.equity_score ?? 0), 0) / tractCount
    : null;

  const hotStopsCount = hotStops.filter(s => s.safety_score >= 8).length;

  const buckets = [
    { label: "0–2",  range: [0, 2]   as const, color: "#22c55e" },
    { label: "2–5",  range: [2, 5]   as const, color: "#facc15" },
    { label: "5–8",  range: [5, 8]   as const, color: "#f97316" },
    { label: "8–12", range: [8, 12]  as const, color: "#ef4444" },
    { label: "12+",  range: [12, 999] as const, color: "#7f1d1d" },
  ];
  const histogram: BarPoint[] = buckets.map(b => ({
    label: b.label,
    value: hotStops.filter(s => s.safety_score >= b.range[0] && s.safety_score < b.range[1]).length,
    color: b.color,
  }));

  const hotList: DataListItem[] = hotStops
    .filter(s => s.safety_score >= 8)
    .filter(s => !filters.search || (s.stop_name ?? s.stop_id).toLowerCase().includes(filters.search.toLowerCase()))
    .sort((a, b) => b.safety_score - a.safety_score)
    .slice(0, 25)
    .map(s => ({
      id: s.stop_id,
      primary: s.stop_name ?? s.stop_id,
      secondary: s.stop_id,
      trailing: s.safety_score.toFixed(1),
    }));

  return (
    <div className="section">
      <div className="section__header">
        <h2 className="section__title">Equity &amp; Safety</h2>
        <span className="section__subtitle">Tract-level service equity and stop risk</span>
      </div>

      {error && (
        <SectionError
          message={error}
          onRetry={() => setTick(t => t + 1)}
        />
      )}

      <div className="section__kpi-strip">
        <KpiCard label="Tracts"          value={String(tractCount)} sub="with equity score" />
        <KpiCard label="Avg equity"      value={avgEquity === null ? "—" : avgEquity.toFixed(3)} />
        <KpiCard label="Hot stops"       value={String(hotStopsCount)} sub="safety ≥ 8" deltaIsGood={false} />
        <KpiCard label="Incidents"       value="—" sub="loaded by ETL" />
      </div>

      <div className="section__grid">
        <SectionMap mapMode="equity" title="Tract equity scores" height={460} />
        <div className="section__panel">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <h3 className="section__panel-title">Highest-risk stops</h3>
            <ExportButton
              filename="highest-risk-stops.csv"
              rows={hotList.map(s => ({ stop_id: s.secondary, stop_name: s.primary, safety_score: s.trailing }))}
            />
          </div>
          {loading && hotList.length === 0 ? <Spinner /> :
           hotList.length === 0 ? <EmptyState message="No stops above the safety threshold." /> :
           <DataList items={hotList} selectedId={selection.stopId} onSelect={setStopId} />}
        </div>
      </div>

      <div className="section__panel">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <h3 className="section__panel-title">Safety score distribution</h3>
          <ExportButton filename="safety-distribution.csv" rows={histogram.map(b => ({ bucket: b.label, count: b.value }))} />
        </div>
        <BarChart data={histogram} height={220} />
      </div>
    </div>
  );
};

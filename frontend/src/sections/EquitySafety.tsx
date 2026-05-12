import React, { useEffect, useState } from "react";
import { useFilters } from "../context/FilterContext";
import { useSelection } from "../context/SelectionContext";
import { api } from "../lib/api";
import { KpiCard, DataList, Spinner, EmptyState, type DataListItem } from "../components/primitives";
import { SectionMap } from "../components/SectionMap";
import "./sections.css";

interface EquityFeature { properties: { equity_score?: number; }; }
interface SafetyRow { stop_id: string; stop_name?: string; safety_score: number; }

export const EquitySafety: React.FC = () => {
  const { filters } = useFilters();
  const { selection, setStopId } = useSelection();

  const [equityFeatures, setEquityFeatures] = useState<EquityFeature[]>([]);
  const [hotStops, setHotStops] = useState<SafetyRow[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function fetchAll() {
      setLoading(true);
      try {
        const [eq, hot] = await Promise.all([
          api.get<{ features: EquityFeature[] }>("/equity/score").catch(() => ({ data: { features: [] } })),
          api.get<SafetyRow[]>("/safety/stops", { params: { min_score: 8 } }).catch(() => ({ data: [] })),
        ]);
        if (cancelled) return;
        setEquityFeatures(eq.data?.features ?? []);
        setHotStops(hot.data ?? []);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchAll();
    return () => { cancelled = true; };
  }, []);

  const tractCount = equityFeatures.length;
  const avgEquity = tractCount > 0
    ? equityFeatures.reduce((s, f) => s + (f.properties.equity_score ?? 0), 0) / tractCount
    : null;

  const hotList: DataListItem[] = hotStops
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

      <div className="section__kpi-strip">
        <KpiCard label="Tracts"          value={String(tractCount)} sub="with equity score" />
        <KpiCard label="Avg equity"      value={avgEquity === null ? "—" : avgEquity.toFixed(3)} />
        <KpiCard label="Hot stops"       value={String(hotStops.length)} sub="safety ≥ 8" deltaIsGood={false} />
        <KpiCard label="Incidents"       value="—" sub="loaded by ETL" />
      </div>

      <div className="section__grid">
        <SectionMap mapMode="equity" title="Tract equity scores" height={460} />
        <div className="section__panel">
          <h3 className="section__panel-title">Highest-risk stops</h3>
          {loading && hotList.length === 0 ? <Spinner /> :
           hotList.length === 0 ? <EmptyState message="No stops above the safety threshold." /> :
           <DataList items={hotList} selectedId={selection.stopId} onSelect={setStopId} />}
        </div>
      </div>
    </div>
  );
};

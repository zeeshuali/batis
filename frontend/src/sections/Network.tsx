import React, { useEffect, useState } from "react";
import { useFilters } from "../context/FilterContext";
import { useSelection } from "../context/SelectionContext";
import { api } from "../lib/api";
import { KpiCard, DataList, Spinner, EmptyState, SectionError, ExportButton, type DataListItem } from "../components/primitives";
import { SectionMap } from "../components/SectionMap";
import { PlannerPanel } from "../components/PlannerPanel";
import { agencyName } from "../lib/agencies";
import { RouteRow } from "../types/data";
import "./sections.css";

interface DesertFeature { properties: { cell_id: string; desert_score: number; nearest_stop_distance_m?: number; }; }

export const Network: React.FC = () => {
  const { filters } = useFilters();
  const { selection, setRouteId } = useSelection();

  const [routes, setRoutes] = useState<RouteRow[]>([]);
  const [cellCount, setCellCount]   = useState<number | null>(null);
  const [desertCount, setDesertCount] = useState<number | null>(null);
  const [desertList, setDesertList] = useState<DesertFeature[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [plannerMode, setPlannerMode] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function fetchAll() {
      setLoading(true);
      setError(null);
      try {
        const [routesRes, cellsRes, desertsRes] = await Promise.all([
          api.get<RouteRow[]>("/routes"),
          api.get<{ features?: unknown[] }>("/coverage/cells").catch(() => ({ data: { features: [] } })),
          api.get<{ features: DesertFeature[] }>("/coverage/deserts").catch(() => ({ data: { features: [] as DesertFeature[] } })),
        ]);
        if (cancelled) return;
        setRoutes(routesRes.data ?? []);
        setCellCount(cellsRes.data?.features?.length ?? 0);
        setDesertList(desertsRes.data?.features ?? []);
        setDesertCount(desertsRes.data?.features?.length ?? 0);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchAll();
    return () => { cancelled = true; };
  }, [tick]);

  const filtered: DataListItem[] = routes
    .filter(r => filters.agencies.length === 0 || (r.agency_id && filters.agencies.includes(r.agency_id)))
    .filter(r => !filters.search || (r.route_short_name ?? r.route_id).toLowerCase().includes(filters.search.toLowerCase()))
    .slice(0, 100)
    .map(r => ({
      id: r.route_id,
      primary:   r.route_short_name ?? r.route_id,
      secondary: r.agency_id ? agencyName(r.agency_id) : undefined,
    }));

  const desertItems: DataListItem[] = desertList
    .slice()
    .sort((a, b) => b.properties.desert_score - a.properties.desert_score)
    .slice(0, 50)
    .map(d => ({
      id: d.properties.cell_id,
      primary: d.properties.cell_id,
      secondary: d.properties.nearest_stop_distance_m
        ? `${Math.round(d.properties.nearest_stop_distance_m)} m to nearest stop`
        : undefined,
      trailing: d.properties.desert_score.toFixed(2),
    }));

  return (
    <div className="section">
      <div className="section__header">
        <h2 className="section__title">Network</h2>
        <span className="section__subtitle">Routes · coverage · service deserts</span>
        <button
          type="button"
          className="export-button"
          onClick={() => setPlannerMode(p => !p)}
        >
          {plannerMode ? "← Back to coverage" : "Plan a trip"}
        </button>
      </div>

      {error && (
        <SectionError
          message={error}
          onRetry={() => setTick(t => t + 1)}
        />
      )}

      <div className="section__kpi-strip">
        <KpiCard label="Total routes"    value={String(routes.length)} sub={`${filters.agencies.length} agencies`} />
        <KpiCard label="Coverage cells"  value={cellCount   === null ? "—" : String(cellCount)} />
        <KpiCard label="Transit deserts" value={desertCount === null ? "—" : String(desertCount)} deltaIsGood={false} />
        <KpiCard label="In view"         value={String(filtered.length)} sub="after filters" />
      </div>

      <div className="section__grid">
        <SectionMap
          mapMode={plannerMode ? "planner" : "coverage"}
          title={plannerMode ? "Trip planner" : "Coverage hex grid"}
          height={460}
        />
        {plannerMode ? <PlannerPanel /> : (
          <div className="section__panel">
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <h3 className="section__panel-title">Routes</h3>
              <ExportButton
                filename="network-routes.csv"
                rows={filtered.map(r => ({ route_id: r.id, name: r.primary, agency: r.secondary }))}
              />
            </div>
            {loading && filtered.length === 0 ? <Spinner /> :
             filtered.length === 0 ? <EmptyState message="No routes match the current filters." /> :
             <DataList items={filtered} selectedId={selection.routeId} onSelect={setRouteId} />}
          </div>
        )}
      </div>

      <div className="section__panel">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <h3 className="section__panel-title">Transit deserts</h3>
          <ExportButton
            filename="network-deserts.csv"
            rows={desertItems.map(d => ({
              cell_id: d.id,
              nearest_stop_m: d.secondary,
              desert_score: d.trailing,
            }))}
          />
        </div>
        {loading && desertItems.length === 0 ? <Spinner /> :
         desertItems.length === 0 ? <EmptyState message="No transit deserts identified." /> :
         <DataList items={desertItems} />}
      </div>
    </div>
  );
};

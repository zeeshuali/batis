import React, { useEffect, useState } from "react";
import { useFilters } from "../context/FilterContext";
import { useSelection } from "../context/SelectionContext";
import { api } from "../lib/api";
import { KpiCard, DataList, Spinner, EmptyState, type DataListItem } from "../components/primitives";
import { SectionMap } from "../components/SectionMap";
import { agencyName } from "../lib/agencies";
import { RouteRow } from "../types/data";
import "./sections.css";

export const Network: React.FC = () => {
  const { filters } = useFilters();
  const { selection, setRouteId } = useSelection();

  const [routes, setRoutes] = useState<RouteRow[]>([]);
  const [cellCount, setCellCount]   = useState<number | null>(null);
  const [desertCount, setDesertCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function fetchAll() {
      setLoading(true);
      try {
        const [routesRes, cellsRes, desertsRes] = await Promise.all([
          api.get<RouteRow[]>("/routes"),
          api.get<{ features?: unknown[] }>("/coverage/cells").catch(() => ({ data: { features: [] } })),
          api.get<{ features?: unknown[] }>("/coverage/deserts").catch(() => ({ data: { features: [] } })),
        ]);
        if (cancelled) return;
        setRoutes(routesRes.data ?? []);
        setCellCount(cellsRes.data?.features?.length ?? 0);
        setDesertCount(desertsRes.data?.features?.length ?? 0);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchAll();
    return () => { cancelled = true; };
  }, []);

  const filtered: DataListItem[] = routes
    .filter(r => filters.agencies.length === 0 || (r.agency_id && filters.agencies.includes(r.agency_id)))
    .filter(r => !filters.search || (r.route_short_name ?? r.route_id).toLowerCase().includes(filters.search.toLowerCase()))
    .slice(0, 100)
    .map(r => ({
      id: r.route_id,
      primary:   r.route_short_name ?? r.route_id,
      secondary: r.agency_id ? agencyName(r.agency_id) : undefined,
    }));

  return (
    <div className="section">
      <div className="section__header">
        <h2 className="section__title">Network</h2>
        <span className="section__subtitle">Routes · coverage · service deserts</span>
      </div>

      <div className="section__kpi-strip">
        <KpiCard label="Total routes"    value={String(routes.length)} sub={`${filters.agencies.length} agencies`} />
        <KpiCard label="Coverage cells"  value={cellCount   === null ? "—" : String(cellCount)} />
        <KpiCard label="Transit deserts" value={desertCount === null ? "—" : String(desertCount)} deltaIsGood={false} />
        <KpiCard label="In view"         value={String(filtered.length)} sub="after filters" />
      </div>

      <div className="section__grid">
        <SectionMap mapMode="coverage" title="Coverage hex grid" height={460} />
        <div className="section__panel">
          <h3 className="section__panel-title">Routes</h3>
          {loading && filtered.length === 0 ? <Spinner /> :
           filtered.length === 0 ? <EmptyState message="No routes match the current filters." /> :
           <DataList items={filtered} selectedId={selection.routeId} onSelect={setRouteId} />}
        </div>
      </div>
    </div>
  );
};

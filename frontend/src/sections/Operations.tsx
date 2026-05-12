import React, { useEffect, useState } from "react";
import { useFilters } from "../context/FilterContext";
import { useSelection } from "../context/SelectionContext";
import { api } from "../lib/api";
import { KpiCard, DataList, Spinner, EmptyState, type DataListItem } from "../components/primitives";
import { SectionMap } from "../components/SectionMap";
import "./sections.css";

interface ReliabilityRow {
  route_id: string;
  sample_events: number;
  avg_delay_seconds: number;
  on_time_pct?: number;
}
/** /vehicles/live returns a GeoJSON FeatureCollection, not a flat array. */
interface VehicleFC { type: "FeatureCollection"; features: unknown[]; }
/** /bunching/summary returns rows with late_events / event_count / avg_delay_seconds. */
interface BunchingRow { route_id: string; event_count: number; late_events?: number; avg_delay_seconds?: number; }

function fmtMin(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  return `${(seconds / 60).toFixed(1)} min`;
}

export const Operations: React.FC = () => {
  const { filters } = useFilters();
  const { selection, setRouteId } = useSelection();

  const [reliability, setReliability] = useState<ReliabilityRow[]>([]);
  const [vehicleCount, setVehicleCount] = useState<number>(0);
  const [bunching, setBunching] = useState<BunchingRow[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function fetchAll() {
      setLoading(true);
      try {
        const [rel, veh, bun] = await Promise.all([
          api.get<ReliabilityRow[]>("/reliability/summary", { params: { start_date: filters.startDate, end_date: filters.endDate } }).catch(() => ({ data: [] as ReliabilityRow[] })),
          api.get<VehicleFC>("/vehicles/live").catch(() => ({ data: { type: "FeatureCollection" as const, features: [] } })),
          api.get<BunchingRow[]>("/bunching/summary", { params: { start_date: filters.startDate, end_date: filters.endDate } }).catch(() => ({ data: [] as BunchingRow[] })),
        ]);
        if (cancelled) return;
        setReliability(rel.data ?? []);
        setVehicleCount(veh.data?.features?.length ?? 0);
        setBunching(bun.data ?? []);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchAll();
    return () => { cancelled = true; };
  }, [filters.startDate, filters.endDate]);

  const totalEvents = reliability.reduce((s, r) => s + r.sample_events, 0);
  const networkOtp = totalEvents > 0
    ? reliability.reduce((s, r) => s + ((r.on_time_pct ?? 0) * r.sample_events), 0) / totalEvents
    : null;
  const avgDelay = totalEvents > 0
    ? reliability.reduce((s, r) => s + (r.avg_delay_seconds * r.sample_events), 0) / totalEvents
    : null;
  const bunchedTotal = bunching.reduce((s, b) => s + (b.late_events ?? 0), 0);

  const worst: DataListItem[] = [...reliability]
    .filter(r => r.sample_events >= 10)
    .filter(r => !filters.search || r.route_id.toLowerCase().includes(filters.search.toLowerCase()))
    .sort((a, b) => b.avg_delay_seconds - a.avg_delay_seconds)
    .slice(0, 12)
    .map(r => ({
      id: r.route_id,
      primary: r.route_id,
      secondary: `${r.sample_events} events`,
      trailing: fmtMin(r.avg_delay_seconds),
    }));

  return (
    <div className="section">
      <div className="section__header">
        <h2 className="section__title">Operations</h2>
        <span className="section__subtitle">{filters.startDate} → {filters.endDate}</span>
      </div>

      <div className="section__kpi-strip">
        <KpiCard label="Network OTP"   value={networkOtp === null ? "—" : `${networkOtp.toFixed(1)}%`} />
        <KpiCard label="Avg delay"     value={avgDelay   === null ? "—" : fmtMin(avgDelay)} />
        <KpiCard label="Live vehicles" value={String(vehicleCount)} />
        <KpiCard label="Bunched"       value={String(bunchedTotal)} sub="events in window" />
      </div>

      <div className="section__grid">
        <SectionMap mapMode="reliability" title="Network reliability" height={460} />
        <div className="section__panel">
          <h3 className="section__panel-title">Slowest performers</h3>
          {loading && worst.length === 0 ? <Spinner /> :
           worst.length === 0 ? <EmptyState message="No route data in this window." /> :
           <DataList items={worst} selectedId={selection.routeId} onSelect={setRouteId} />}
        </div>
      </div>
    </div>
  );
};

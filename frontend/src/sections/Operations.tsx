import React, { useEffect, useState } from "react";
import { useFilters } from "../context/FilterContext";
import { useSelection } from "../context/SelectionContext";
import { api } from "../lib/api";
import { KpiCard, DataList, BarChart, Spinner, EmptyState, SectionError, ExportButton, type DataListItem, type BarPoint } from "../components/primitives";
import { SectionMap } from "../components/SectionMap";
import { ReliabilityRow, VehicleFC, BunchingRow, CrowdingRow } from "../types/data";
import { fmtMin, fmtPct } from "../lib/format";
import "./sections.css";

export const Operations: React.FC = () => {
  const { filters } = useFilters();
  const { selection, setRouteId } = useSelection();

  const [reliability, setReliability] = useState<ReliabilityRow[]>([]);
  const [vehicleCount, setVehicleCount] = useState<number>(0);
  const [bunching, setBunching] = useState<BunchingRow[]>([]);
  const [crowding, setCrowding] = useState<CrowdingRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function fetchAll() {
      setLoading(true);
      setError(null);
      try {
        const [rel, veh, bun, crowd] = await Promise.all([
          api.get<ReliabilityRow[]>("/reliability/summary", { params: { start_date: filters.startDate, end_date: filters.endDate } }).catch(() => ({ data: [] as ReliabilityRow[] })),
          api.get<VehicleFC>("/vehicles/live").catch(() => ({ data: { type: "FeatureCollection" as const, features: [] } })),
          api.get<BunchingRow[]>("/bunching/summary", { params: { start_date: filters.startDate, end_date: filters.endDate } }).catch(() => ({ data: [] as BunchingRow[] })),
          api.get<CrowdingRow[]>("/crowding/predictions", { params: { start_date: filters.startDate, end_date: filters.endDate } }).catch(() => ({ data: [] as CrowdingRow[] })),
        ]);
        if (cancelled) return;
        setReliability(rel.data ?? []);
        setVehicleCount(veh.data?.features?.length ?? 0);
        setBunching(bun.data ?? []);
        setCrowding(crowd.data ?? []);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchAll();
    return () => { cancelled = true; };
  }, [filters.startDate, filters.endDate, tick]);

  const totalEvents = reliability.reduce((s, r) => s + r.sample_events, 0);
  const networkOtp = totalEvents > 0
    ? reliability.reduce((s, r) => s + ((r.on_time_pct ?? 0) * r.sample_events), 0) / totalEvents
    : null;
  const avgDelay = totalEvents > 0
    ? reliability.reduce((s, r) => s + (r.avg_delay_seconds * r.sample_events), 0) / totalEvents
    : null;
  const bunchedTotal = bunching.reduce((s, b) => s + (b.late_events ?? 0), 0);

  const crowdingBars: BarPoint[] = (() => {
    const counts = new Map<string, number>();
    for (const c of crowding) {
      if (c.crowding_level === "high") {
        counts.set(c.route_id, (counts.get(c.route_id) ?? 0) + 1);
      }
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10)
      .map(([route_id, value]) => ({ label: route_id, value, color: "#ef4444" }));
  })();

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

      {error && (
        <SectionError
          message={error}
          onRetry={() => setTick(t => t + 1)}
        />
      )}

      <div className="section__kpi-strip">
        <KpiCard label="Network OTP"   value={fmtPct(networkOtp)} />
        <KpiCard label="Avg delay"     value={avgDelay   === null ? "—" : fmtMin(avgDelay)} />
        <KpiCard label="Live vehicles" value={String(vehicleCount)} />
        <KpiCard label="Bunched"       value={String(bunchedTotal)} sub="events in window" />
      </div>

      <div className="section__grid">
        <SectionMap mapMode="reliability" title="Network reliability" height={460} />
        <div className="section__panel">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <h3 className="section__panel-title">Slowest performers</h3>
            <ExportButton filename="operations-slowest.csv" rows={worst.map(r => ({ route_id: r.id, primary: r.primary, secondary: r.secondary, trailing: r.trailing }))} />
          </div>
          {loading && worst.length === 0 ? <Spinner /> :
           worst.length === 0 ? <EmptyState message="No route data in this window." /> :
           <DataList items={worst} selectedId={selection.routeId} onSelect={setRouteId} />}
        </div>
      </div>

      <div className="section__panel">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <h3 className="section__panel-title">Top high-crowding routes</h3>
          <ExportButton filename="operations-crowding.csv" rows={crowdingBars.map(b => ({ route_id: b.label, high_events: b.value }))} />
        </div>
        {crowdingBars.length === 0
          ? <EmptyState message="No high-crowding predictions in this window." />
          : <BarChart data={crowdingBars} height={260} />}
      </div>
    </div>
  );
};

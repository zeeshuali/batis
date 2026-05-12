import React, { useEffect, useState } from "react";
import { useFilters } from "../context/FilterContext";
import { useSelection } from "../context/SelectionContext";
import { useAgencies } from "../context/AgenciesContext";
import { api } from "../lib/api";
import { KpiCard, DataList, TrendChart, Spinner, EmptyState, SectionError, type DataListItem, type TrendPoint } from "../components/primitives";
import { SectionMap } from "../components/SectionMap";
import { ReliabilityRow, TrendRow, SafetyRow } from "../types/data";
import { fmtMin, fmtPct } from "../lib/format";
import "./sections.css";

export const Overview: React.FC = () => {
  const { filters } = useFilters();
  const { selection, setRouteId } = useSelection();
  const { agencies } = useAgencies();

  const [reliabilityRows, setReliabilityRows] = useState<ReliabilityRow[]>([]);
  const [trendRows, setTrendRows] = useState<TrendRow[]>([]);
  const [routeCount, setRouteCount] = useState<number | null>(null);
  const [hotStops, setHotStops] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function fetchAll() {
      setLoading(true);
      setError(null);
      try {
        const [rel, trend, routes, safety] = await Promise.all([
          api.get<ReliabilityRow[]>("/reliability/summary", { params: { start_date: filters.startDate, end_date: filters.endDate } }),
          api.get<TrendRow[]>("/reliability/trend", { params: { start_date: filters.startDate, end_date: filters.endDate } }).catch(() => ({ data: [] })),
          api.get<{ route_id: string }[]>("/routes"),
          api.get<SafetyRow[]>("/safety/stops", { params: { min_score: 8 } }).catch(() => ({ data: [] })),
        ]);
        if (cancelled) return;
        setReliabilityRows(rel.data ?? []);
        setTrendRows(trend.data ?? []);
        setRouteCount(routes.data?.length ?? 0);
        setHotStops(safety.data?.length ?? 0);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchAll();
    return () => { cancelled = true; };
  }, [filters.startDate, filters.endDate, tick]);

  const totalEvents = reliabilityRows.reduce((s, r) => s + (r.sample_events || 0), 0);
  const networkOtp = totalEvents > 0
    ? reliabilityRows.reduce((s, r) => s + ((r.on_time_pct ?? 0) * r.sample_events), 0) / totalEvents
    : null;
  const avgDelay = totalEvents > 0
    ? reliabilityRows.reduce((s, r) => s + (r.avg_delay_seconds * r.sample_events), 0) / totalEvents
    : null;

  const worstRoutes: DataListItem[] = [...reliabilityRows]
    .filter(r => r.sample_events >= 10)
    .sort((a, b) => b.avg_delay_seconds - a.avg_delay_seconds)
    .slice(0, 10)
    .map(r => ({
      id:       r.route_id,
      primary:  r.route_id,
      secondary: `${r.sample_events} events`,
      trailing: fmtMin(r.avg_delay_seconds),
    }));

  const trendPoints: TrendPoint[] = trendRows
    .map(t => {
      const d = t.date ?? t.service_date ?? "";
      return { x: d.slice(5), y: t.avg_delay ?? null };
    })
    .filter(p => p.x !== "");

  return (
    <div className="section">
      <div className="section__header">
        <h2 className="section__title">Overview</h2>
        <span className="section__subtitle">Network health · {filters.startDate} → {filters.endDate}</span>
      </div>

      {error && (
        <SectionError
          message={error}
          onRetry={() => setTick(t => t + 1)}
        />
      )}

      <div className="section__kpi-strip">
        <KpiCard label="Routes"      value={routeCount === null ? "—" : String(routeCount)} sub={`across ${filters.agencies.length || agencies.length} agencies`} />
        <KpiCard label="Network OTP" value={fmtPct(networkOtp)} />
        <KpiCard label="Avg delay"   value={avgDelay  === null ? "—" : fmtMin(avgDelay)} deltaIsGood={false} />
        <KpiCard label="Hot stops"   value={hotStops  === null ? "—" : String(hotStops)} sub="safety score ≥ 8" deltaIsGood={false} />
      </div>

      <div className="section__grid">
        <SectionMap mapMode="reliability" title="Network reliability" height={420} />
        <div className="section__panel">
          <h3 className="section__panel-title">Slowest performers</h3>
          {loading && worstRoutes.length === 0 ? <Spinner /> : worstRoutes.length === 0 ? (
            <EmptyState message="No route data in this window." hint="Widen the date range or pick more agencies." />
          ) : (
            <DataList items={worstRoutes} selectedId={selection.routeId} onSelect={setRouteId} />
          )}
        </div>
      </div>

      <div className="section__panel">
        <h3 className="section__panel-title">Network delay trend</h3>
        {loading && trendPoints.length === 0 ? <Spinner /> : trendPoints.length === 0 ? (
          <EmptyState message="No trend data in this window." />
        ) : (
          <TrendChart data={trendPoints} yLabel="sec" />
        )}
      </div>
    </div>
  );
};

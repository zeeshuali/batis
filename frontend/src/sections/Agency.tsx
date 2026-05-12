import React, { useEffect, useState } from "react";
import { useAgencies } from "../context/AgenciesContext";
import { useSelection } from "../context/SelectionContext";
import { useFilters } from "../context/FilterContext";
import { useUrlState } from "../lib/useUrlState";
import { api } from "../lib/api";
import {
  KpiCard, DataList, TrendChart, Spinner, EmptyState, SectionError,
  type DataListItem, type TrendPoint,
} from "../components/primitives";
import { SectionMap } from "../components/SectionMap";
import { fmtMin, fmtPct } from "../lib/format";
import { ReliabilityRow, TrendRow } from "../types/data";
import "./sections.css";

interface AlertRow { id: string; header: string; effect: string; agency_id: string | null; }
interface RouteRow { route_id: string; route_short_name: string | null; agency_id: string | null; }

export const Agency: React.FC = () => {
  const { state, setState } = useUrlState();
  const { filters } = useFilters();
  const { byId, loading: agenciesLoading } = useAgencies();
  const { selection, setRouteId } = useSelection();

  const agencyId = state.agency_id;
  const agency   = agencyId ? byId[agencyId] : null;

  const [reliability, setReliability] = useState<ReliabilityRow[]>([]);
  const [trend,       setTrend]       = useState<TrendRow[]>([]);
  const [routes,      setRoutes]      = useState<RouteRow[]>([]);
  const [alerts,      setAlerts]      = useState<AlertRow[]>([]);
  const [routeCount,  setRouteCount]  = useState<number | null>(null);
  const [stopCount,   setStopCount]   = useState<number | null>(null);
  const [liveVehicles, setLiveVehicles] = useState<number | null>(null);
  const [hotStops,    setHotStops]    = useState<number | null>(null);
  const [loading,     setLoading]     = useState(false);
  const [error,       setError]       = useState<string | null>(null);
  const [tick,        setTick]        = useState(0);

  useEffect(() => {
    if (!agencyId) return;
    let cancelled = false;
    async function fetchAll() {
      setLoading(true); setError(null);
      try {
        const params = { agency_id: agencyId };
        const dateParams = { ...params, start_date: filters.startDate, end_date: filters.endDate };
        const [relRes, trendRes, routesRes, alertsRes, safetyRes, vehiclesRes] = await Promise.all([
          api.get<ReliabilityRow[]>("/reliability/summary", { params: dateParams }).catch(() => ({ data: [] })),
          api.get<TrendRow[]>("/reliability/trend",         { params: dateParams }).catch(() => ({ data: [] })),
          api.get<RouteRow[]>("/routes").catch(() => ({ data: [] })),
          api.get<AlertRow[]>("/alerts").catch(() => ({ data: [] })),
          api.get<{ stop_id: string }[]>("/safety/stops", { params: { ...params, min_score: 8 } }).catch(() => ({ data: [] })),
          api.get<{ vehicle_id: string }[]>("/vehicles/live", { params }).catch(() => ({ data: [] })),
        ]);
        if (cancelled) return;
        const agencyRoutes = (routesRes.data ?? []).filter(r => r.agency_id === agencyId);
        setReliability(relRes.data ?? []);
        setTrend(trendRes.data ?? []);
        setRoutes(agencyRoutes);
        setAlerts((alertsRes.data ?? []).filter(a => a.agency_id === agencyId));
        setRouteCount(agencyRoutes.length);
        setLiveVehicles(Array.isArray(vehiclesRes.data) ? vehiclesRes.data.length : 0);
        setHotStops((safetyRes.data ?? []).length);
        // /safety/stops returns one row per stop in the agency; safety_score≥8 was the hot-stops filter.
        // For total stop count we re-call without the min_score floor.
        const stopsAllRes = await api.get<{ stop_id: string }[]>("/safety/stops", { params }).catch(() => ({ data: [] }));
        if (cancelled) return;
        setStopCount((stopsAllRes.data ?? []).length);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchAll();
    return () => { cancelled = true; };
  }, [agencyId, filters.startDate, filters.endDate, tick]);

  const back = () => setState({ ...state, section: "overview", agency_id: null });

  if (agenciesLoading && !agency && agencyId) {
    return <div className="section"><Spinner /></div>;
  }
  if (!agencyId || !agency) {
    return (
      <div className="section">
        <div className="section__header">
          <h2 className="section__title">Agency</h2>
          <button type="button" className="export-button" onClick={back}>← Back to Overview</button>
        </div>
        <EmptyState
          message="Pick an agency from Overview → By agency to drill in."
          hint={agencyId ? `Unknown agency "${agencyId}"` : undefined}
        />
      </div>
    );
  }

  const totalEvents = reliability.reduce((s, r) => s + (r.sample_events || 0), 0);
  const networkOtp  = totalEvents > 0
    ? reliability.reduce((s, r) => s + ((r.on_time_pct ?? 0) * r.sample_events), 0) / totalEvents
    : null;
  const avgDelay    = totalEvents > 0
    ? reliability.reduce((s, r) => s + (r.avg_delay_seconds * r.sample_events), 0) / totalEvents
    : null;

  const worstRoutes: DataListItem[] = [...reliability]
    .filter(r => r.sample_events >= 10)
    .sort((a, b) => b.avg_delay_seconds - a.avg_delay_seconds)
    .slice(0, 10)
    .map(r => ({
      id: r.route_id, primary: r.route_id,
      secondary: `${r.sample_events} events`,
      trailing: fmtMin(r.avg_delay_seconds),
    }));

  const routeItems: DataListItem[] = routes.slice(0, 50).map(r => ({
    id: r.route_id, primary: r.route_short_name ?? r.route_id,
  }));

  const alertItems: DataListItem[] = alerts.slice(0, 50).map(a => ({
    id: a.id, primary: a.header, secondary: a.effect,
  }));

  const trendPoints: TrendPoint[] = trend
    .map(t => ({ x: (t.date ?? t.service_date ?? "").slice(5), y: t.avg_delay ?? null }))
    .filter(p => p.x !== "");

  return (
    <div className="section">
      <div className="section__header">
        <h2 className="section__title">{agency.agency_name}</h2>
        <span className="section__subtitle">
          {[agency.agency_type, agency.monitored ? "Live RT" : null]
            .filter(Boolean).join(" · ") || agency.agency_id}
        </span>
        <button type="button" className="export-button" onClick={back}>← Back to Overview</button>
      </div>

      {error && <SectionError message={error} onRetry={() => setTick(t => t + 1)} />}

      <div className="section__kpi-strip">
        <KpiCard label="Routes"         value={routeCount   === null ? "—" : String(routeCount)} />
        <KpiCard label="Stops"          value={stopCount    === null ? "—" : String(stopCount)} />
        <KpiCard label="Network OTP"    value={fmtPct(networkOtp)} />
        <KpiCard label="Avg delay"      value={avgDelay     === null ? "—" : fmtMin(avgDelay)} deltaIsGood={false} />
        <KpiCard label="Live vehicles"  value={liveVehicles === null ? "—" : String(liveVehicles)} />
        <KpiCard label="Active alerts"  value={String(alerts.length)} deltaIsGood={false} />
        <KpiCard label="Hot stops"      value={hotStops     === null ? "—" : String(hotStops)} sub="safety ≥ 8" deltaIsGood={false} />
      </div>

      <div className="section__grid">
        <SectionMap mapMode="reliability" title="Network reliability" height={420} agencyFilter={agencyId} />
        <div className="section__panel">
          <h3 className="section__panel-title">Slowest routes</h3>
          {loading && worstRoutes.length === 0 ? <Spinner /> : worstRoutes.length === 0 ? (
            <EmptyState message="No reliability data in this window." />
          ) : (
            <DataList items={worstRoutes} selectedId={selection.routeId} onSelect={setRouteId} />
          )}
        </div>
      </div>

      <div className="section__panel">
        <h3 className="section__panel-title">Delay trend</h3>
        {loading && trendPoints.length === 0 ? <Spinner /> : trendPoints.length === 0 ? (
          <EmptyState message="No trend data in this window." />
        ) : (
          <TrendChart data={trendPoints} yLabel="sec" />
        )}
      </div>

      <div className="section__grid">
        <div className="section__panel">
          <h3 className="section__panel-title">Routes</h3>
          {routeItems.length === 0 ? <EmptyState message="No routes recorded for this agency." />
            : <DataList items={routeItems} selectedId={selection.routeId} onSelect={setRouteId} />}
        </div>
        <div className="section__panel">
          <h3 className="section__panel-title">Active alerts</h3>
          {alertItems.length === 0 ? <EmptyState message="No active alerts." />
            : <DataList items={alertItems} />}
        </div>
      </div>
    </div>
  );
};

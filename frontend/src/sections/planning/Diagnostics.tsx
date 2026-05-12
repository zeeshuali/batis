import React, { useEffect, useState } from "react";
import { useFilters } from "../../context/FilterContext";
import { useSelection } from "../../context/SelectionContext";
import { api } from "../../lib/api";
import {
  KpiCard, DataList, Spinner, EmptyState, SectionError, ExportButton,
  type DataListItem,
} from "../../components/primitives";
import { SectionMap } from "../../components/SectionMap";
import { ReliabilityRow } from "../../types/data";
import { fmtMin, fmtPct } from "../../lib/format";
import "../sections.css";

interface BunchingRow { route_id: string; bunched_events: number | null; }
interface SafetyRow   { stop_id: string; stop_name?: string | null; safety_score: number | null; }
interface CrowdingRow { route_id: string; crowding_level: string | null; }

/** Diagnostics — for the agency service planner.
 *  Answers "what needs my attention this week?" by composing the same
 *  endpoints Operations + Equity already use, but reframed as planner
 *  decision queues (worst-OTP routes, bunchiest routes, hot stops needing
 *  investment, overcrowded routes). */
export const Diagnostics: React.FC = () => {
  const { filters } = useFilters();
  const { selection, setRouteId } = useSelection();

  const [reliability, setReliability] = useState<ReliabilityRow[]>([]);
  const [bunching,    setBunching]    = useState<BunchingRow[]>([]);
  const [hotStops,    setHotStops]    = useState<SafetyRow[]>([]);
  const [crowding,    setCrowding]    = useState<CrowdingRow[]>([]);
  const [loading,     setLoading]     = useState(false);
  const [error,       setError]       = useState<string | null>(null);
  const [tick,        setTick]        = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function fetchAll() {
      setLoading(true); setError(null);
      try {
        const params = { start_date: filters.startDate, end_date: filters.endDate };
        const single = filters.agencies.length === 1 ? { agency_id: filters.agencies[0] } : {};
        const [rel, bn, sf, cr] = await Promise.all([
          api.get<ReliabilityRow[]>("/reliability/summary", { params: { ...params, ...single } }).catch(() => ({ data: [] })),
          api.get<BunchingRow[]>  ("/bunching/summary",     { params: { ...params, ...single } }).catch(() => ({ data: [] })),
          api.get<SafetyRow[]>    ("/safety/stops",         { params: { min_score: 8, ...single } }).catch(() => ({ data: [] })),
          api.get<CrowdingRow[]>  ("/crowding/predictions").catch(() => ({ data: [] })),
        ]);
        if (cancelled) return;
        setReliability(rel.data ?? []);
        setBunching(bn.data ?? []);
        setHotStops(sf.data ?? []);
        setCrowding(cr.data ?? []);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchAll();
    return () => { cancelled = true; };
  }, [filters.startDate, filters.endDate, filters.agencies, tick]);

  const totalEvents = reliability.reduce((s, r) => s + (r.sample_events || 0), 0);
  const networkOtp  = totalEvents > 0
    ? reliability.reduce((s, r) => s + ((r.on_time_pct ?? 0) * r.sample_events), 0) / totalEvents
    : null;

  // Worst-OTP routes with meaningful sample.
  const reliabilityQueue: DataListItem[] = [...reliability]
    .filter(r => r.sample_events >= 10)
    .sort((a, b) => (a.on_time_pct ?? 0) - (b.on_time_pct ?? 0))
    .slice(0, 10)
    .map(r => ({
      id: r.route_id,
      primary: r.route_id,
      secondary: `${r.sample_events} events · avg ${fmtMin(r.avg_delay_seconds)}`,
      trailing: fmtPct(r.on_time_pct),
    }));

  const bunchingQueue: DataListItem[] = [...bunching]
    .filter(b => (b.bunched_events ?? 0) > 0)
    .sort((a, b) => (b.bunched_events ?? 0) - (a.bunched_events ?? 0))
    .slice(0, 10)
    .map(b => ({
      id: b.route_id, primary: b.route_id,
      secondary: "Bunching events this window",
      trailing: String(b.bunched_events ?? 0),
    }));

  const hotStopsQueue: DataListItem[] = [...hotStops]
    .filter(s => (s.safety_score ?? 0) >= 8)
    .sort((a, b) => (b.safety_score ?? 0) - (a.safety_score ?? 0))
    .slice(0, 10)
    .map(s => ({
      id: s.stop_id,
      primary: s.stop_name ?? s.stop_id,
      secondary: "Safety score ≥ 8 — needs investment",
      trailing: (s.safety_score ?? 0).toFixed(1),
    }));

  // Crowding: group by route, count high-crowding entries.
  const crowdingByRoute = new Map<string, number>();
  for (const c of crowding) {
    if (c.crowding_level === "high") {
      crowdingByRoute.set(c.route_id, (crowdingByRoute.get(c.route_id) ?? 0) + 1);
    }
  }
  const crowdingQueue: DataListItem[] = [...crowdingByRoute.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([route_id, count]) => ({
      id: route_id, primary: route_id,
      secondary: "High-crowding predictions",
      trailing: String(count),
    }));

  return (
    <div className="section">
      <div className="section__header">
        <h2 className="section__title">Diagnostics</h2>
        <span className="section__subtitle">
          What needs the service planner's attention this window
        </span>
      </div>

      {error && <SectionError message={error} onRetry={() => setTick(t => t + 1)} />}

      <div className="section__kpi-strip">
        <KpiCard label="Network OTP"     value={fmtPct(networkOtp)} />
        <KpiCard label="Routes flagged"  value={String(reliabilityQueue.length)} sub="OTP triage queue" deltaIsGood={false} />
        <KpiCard label="Bunched routes"  value={String(bunchingQueue.length)} sub="Service irregularity" deltaIsGood={false} />
        <KpiCard label="Hot stops"       value={String(hotStopsQueue.length)} sub="Investment candidates" deltaIsGood={false} />
        <KpiCard label="Crowded routes"  value={String(crowdingQueue.length)} sub="Predicted high-crowding" deltaIsGood={false} />
      </div>

      <div className="section__grid">
        <SectionMap mapMode="reliability" title="Reliability map" height={420} />
        <div className="section__panel">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <h3 className="section__panel-title">OTP triage queue</h3>
            <ExportButton
              filename="planning-diagnostics-otp.csv"
              rows={reliabilityQueue.map(r => ({ route_id: r.id, otp: r.trailing }))}
            />
          </div>
          {loading && reliabilityQueue.length === 0 ? <Spinner /> :
           reliabilityQueue.length === 0 ? (
             <EmptyState message="No routes flagged." hint="Either the window is too narrow or every route is on time." />
           ) : (
             <DataList items={reliabilityQueue} selectedId={selection.routeId} onSelect={setRouteId} />
           )}
        </div>
      </div>

      <div className="section__grid">
        <div className="section__panel">
          <h3 className="section__panel-title">Bunching candidates</h3>
          {loading && bunchingQueue.length === 0 ? <Spinner /> :
           bunchingQueue.length === 0 ? (
             <EmptyState message="No bunching events recorded." />
           ) : (
             <DataList items={bunchingQueue} selectedId={selection.routeId} onSelect={setRouteId} />
           )}
        </div>
        <div className="section__panel">
          <h3 className="section__panel-title">Hot stops needing investment</h3>
          {loading && hotStopsQueue.length === 0 ? <Spinner /> :
           hotStopsQueue.length === 0 ? (
             <EmptyState message="No high-risk stops in this filter." />
           ) : (
             <DataList items={hotStopsQueue} />
           )}
        </div>
      </div>

      <div className="section__panel">
        <h3 className="section__panel-title">Predicted high-crowding routes</h3>
        {loading && crowdingQueue.length === 0 ? <Spinner /> :
         crowdingQueue.length === 0 ? (
           <EmptyState message="No crowding predictions available." />
         ) : (
           <DataList items={crowdingQueue} selectedId={selection.routeId} onSelect={setRouteId} />
         )}
      </div>
    </div>
  );
};

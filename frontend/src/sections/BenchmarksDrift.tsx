import React, { useEffect, useState } from "react";
import { useFilters } from "../context/FilterContext";
import { api } from "../lib/api";
import { KpiCard, BarChart, DataList, Spinner, EmptyState, SectionError, ExportButton, type BarPoint, type DataListItem } from "../components/primitives";
import { agencyColor, agencyName } from "../lib/agencies";
import { AgencyOtpRow } from "../types/data";
import "./sections.css";

interface TrafficEvent {
  event_id: string;
  event_type: string;
  severity?: string;
  description?: string;
  start_time?: string;
}

export const BenchmarksDrift: React.FC = () => {
  const { filters } = useFilters();
  const [otp, setOtp] = useState<AgencyOtpRow[]>([]);
  const [trafficCount, setTrafficCount] = useState<number | null>(null);
  const [trafficEvents, setTrafficEvents] = useState<TrafficEvent[]>([]);
  const [workZoneCount, setWorkZoneCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function fetchAll() {
      setLoading(true);
      setError(null);
      try {
        const [otpRes, eventsRes, wzRes] = await Promise.all([
          api.get<AgencyOtpRow[]>("/benchmarks/agency-otp", { params: { start_date: filters.startDate, end_date: filters.endDate } }).catch(() => ({ data: [] })),
          api.get<{ features: { properties: TrafficEvent }[] }>("/traffic/events").catch(() => ({ data: { features: [] as { properties: TrafficEvent }[] } })),
          api.get<{ features?: unknown[] }>("/traffic/work-zones").catch(() => ({ data: { features: [] } })),
        ]);
        if (cancelled) return;
        setOtp(otpRes.data ?? []);
        const features = eventsRes.data?.features ?? [];
        setTrafficCount(features.length);
        setTrafficEvents(features.map(f => f.properties));
        setWorkZoneCount(wzRes.data?.features?.length ?? 0);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchAll();
    return () => { cancelled = true; };
  }, [filters.startDate, filters.endDate, tick]);

  // Benchmarks compares *all* agencies the backend returns — the section's
  // whole point is cross-agency comparison. We don't apply the global agency
  // filter here because (a) the dev DB has more agency IDs than ALL_AGENCY_IDS
  // knows about, so filtering would silently drop unknown agencies; and
  // (b) users who deselect an agency in the filter bar still want to *see*
  // it in a benchmark — they'd just be deciding which agency to highlight
  // in other sections.
  const bars: BarPoint[] = [...otp]
    .sort((a, b) => b.on_time_pct - a.on_time_pct)
    .map(r => ({
      label: r.agency_id,
      value: Number(r.on_time_pct.toFixed(1)),
      color: agencyColor(r.agency_id),
    }));

  const eventItems: DataListItem[] = trafficEvents
    .slice(0, 50)
    .map(ev => ({
      id: ev.event_id,
      primary:   ev.description ?? ev.event_id,
      secondary: [ev.event_type, ev.severity].filter(Boolean).join(" · "),
      trailing:  ev.start_time ? new Date(ev.start_time).toLocaleString() : "—",
    }));

  return (
    <div className="section">
      <div className="section__header">
        <h2 className="section__title">Benchmarks &amp; Drift</h2>
        <span className="section__subtitle">Agency OTP comparison · roadway disruptions</span>
      </div>

      {error && (
        <SectionError
          message={error}
          onRetry={() => setTick(t => t + 1)}
        />
      )}

      <div className="section__kpi-strip">
        <KpiCard label="Agencies"        value={String(bars.length)} sub="in current filter" />
        <KpiCard label="Best OTP"        value={bars[0] ? `${bars[0].value}%` : "—"} sub={bars[0] ? agencyName(bars[0].label) : ""} />
        <KpiCard label="Traffic events"  value={trafficCount  === null ? "—" : String(trafficCount)} deltaIsGood={false} />
        <KpiCard label="Work zones"      value={workZoneCount === null ? "—" : String(workZoneCount)} />
      </div>

      <div className="section__panel">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <h3 className="section__panel-title">Cross-agency OTP</h3>
          <ExportButton
            filename="benchmarks-agency-otp.csv"
            rows={bars.map(b => ({ agency_id: b.label, on_time_pct: b.value }))}
          />
        </div>
        {loading && bars.length === 0 ? <Spinner /> :
         bars.length === 0 ? <EmptyState message="No benchmark data in this window." hint="Stop_observations may not be loaded for this date range." /> :
         <BarChart data={bars} height={320} />}
      </div>

      <div className="section__panel">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <h3 className="section__panel-title">Active traffic events</h3>
          <ExportButton
            filename="traffic-events.csv"
            rows={trafficEvents.map(ev => ({
              id: ev.event_id,
              type: ev.event_type,
              severity: ev.severity,
              description: ev.description,
              start_time: ev.start_time,
            }))}
          />
        </div>
        {loading && eventItems.length === 0 ? <Spinner /> :
         eventItems.length === 0 ? <EmptyState message="No active traffic events." /> :
         <DataList items={eventItems} />}
      </div>
    </div>
  );
};

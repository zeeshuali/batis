import React, { useEffect, useMemo, useState } from "react";
import { useSelection } from "../../context/SelectionContext";
import { api } from "../../lib/api";
import {
  KpiCard, DataList, Spinner, EmptyState, SectionError, ExportButton,
  type DataListItem,
} from "../../components/primitives";
import { SectionMap } from "../../components/SectionMap";
import "../sections.css";
import "./planning.css";

interface SafetyStopFeature {
  geometry: { type: "Point"; coordinates: [number, number] };
  properties: {
    stop_id: string;
    stop_name: string | null;
    safety_score: number | null;
    crime_incidents_nearby?: number | null;
    collisions_nearby?:      number | null;
  };
}
interface CoverageCellFeature {
  geometry: { type: "Polygon"; coordinates: number[][][] };
  properties: {
    cell_id: string;
    distance_to_nearest_stop_m: number | null;
    effective_frequency_per_hour: number | null;
    equity_score: number | null;
  };
}
interface EquityCellFeature {
  geometry: { type: "Polygon"; coordinates: number[][][] };
  properties: {
    cell_id: string;
    equity_score: number;
    population: number;
    equity_tier: "very_high" | "high" | "medium" | "low";
  };
}

const INSPECTION_RADIUS_M = 500;
const POOR_ACCESS_DISTANCE_M = 400;
const POOR_ACCESS_FREQ_PER_H = 1;
const HIGH_EQUITY_THRESHOLD = 0.15;

/** Haversine in metres. Good enough for the per-click ranking — the
 *  database has the authoritative spatial join via ::geography. */
function haversineM(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const R = 6371000;
  const toRad = (d: number) => d * Math.PI / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

/** Approximate polygon centroid by averaging vertex coordinates. Off
 *  for non-convex shapes but the hex grid is regular — close enough. */
function polygonCentroid(coords: number[][][]): [number, number] {
  const ring = coords[0] ?? [];
  if (ring.length === 0) return [0, 0];
  let sx = 0, sy = 0;
  for (const [x, y] of ring) { sx += x; sy += y; }
  return [sx / ring.length, sy / ring.length];
}

/** Workbench — click-to-inspect a corridor or zone.
 *  Stays backend-free in Phase 4: we pre-fetch the per-stop and per-cell
 *  geometries once, then haversine-filter against the click point each time
 *  the user drops a pin. Clicks feel instant. */
export const Workbench: React.FC = () => {
  const { selection, setWorkbenchPoint } = useSelection();
  const point = selection.workbenchPoint;

  const [stops,   setStops]   = useState<SafetyStopFeature[]>([]);
  const [cells,   setCells]   = useState<CoverageCellFeature[]>([]);
  const [equity,  setEquity]  = useState<EquityCellFeature[]>([]);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);
  const [tick,    setTick]    = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function fetchAll() {
      setLoading(true); setError(null);
      try {
        const [sRes, cRes, eRes] = await Promise.all([
          api.get<{ features: SafetyStopFeature[]   }>("/safety/stops/geo").catch(() => ({ data: { features: [] } })),
          api.get<{ features: CoverageCellFeature[] }>("/coverage/cells" ).catch(() => ({ data: { features: [] } })),
          api.get<{ features: EquityCellFeature[]   }>("/equity/score"   ).catch(() => ({ data: { features: [] } })),
        ]);
        if (cancelled) return;
        setStops (sRes.data?.features ?? []);
        setCells (cRes.data?.features ?? []);
        setEquity(eRes.data?.features ?? []);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchAll();
    return () => { cancelled = true; };
  }, [tick]);

  /** Filter the pre-fetched corpora to within INSPECTION_RADIUS_M of the
   *  click point and rank by relevance. */
  const inspection = useMemo(() => {
    if (!point) return null;
    const cellById = new Map(cells.map(c => [c.properties.cell_id, c]));
    const nearbyStops = stops
      .map(f => ({
        f,
        distance: haversineM(point.lat, point.lng, f.geometry.coordinates[1], f.geometry.coordinates[0]),
      }))
      .filter(s => s.distance <= INSPECTION_RADIUS_M)
      .sort((a, b) => a.distance - b.distance);

    const nearbyCells = equity
      .map(f => {
        const [cx, cy] = polygonCentroid(f.geometry.coordinates);
        const dist = haversineM(point.lat, point.lng, cy, cx);
        const cov = cellById.get(f.properties.cell_id);
        const distance_to_stop = cov?.properties.distance_to_nearest_stop_m ?? null;
        const freq             = cov?.properties.effective_frequency_per_hour ?? null;
        const poor_access =
          (distance_to_stop != null && distance_to_stop > POOR_ACCESS_DISTANCE_M) ||
          (freq             != null && freq             < POOR_ACCESS_FREQ_PER_H);
        return { f, dist, distance_to_stop, freq, poor_access };
      })
      .filter(c => c.dist <= INSPECTION_RADIUS_M)
      .sort((a, b) => (b.f.properties.equity_score - a.f.properties.equity_score));

    const popInRadius   = nearbyCells.reduce((s, c) => s + c.f.properties.population, 0);
    const popUnderserved = nearbyCells
      .filter(c => c.poor_access && c.f.properties.equity_score >= HIGH_EQUITY_THRESHOLD)
      .reduce((s, c) => s + c.f.properties.population, 0);
    const avgEquity = nearbyCells.length === 0 ? null :
      nearbyCells.reduce((s, c) => s + c.f.properties.equity_score, 0) / nearbyCells.length;
    const hotStops = nearbyStops.filter(s => (s.f.properties.safety_score ?? 0) >= 8).length;

    let recommendation: string;
    if (nearbyStops.length === 0) {
      recommendation = "Service gap — no stops within 500 m. Strong candidate for a new route or extension.";
    } else if (popUnderserved > 1000) {
      recommendation = `Increase frequency or add coverage — ${(popUnderserved / 1000).toFixed(1)}k high-need residents have poor access here.`;
    } else if (hotStops > 0) {
      recommendation = `Existing stops need investment — ${hotStops} stop${hotStops > 1 ? "s" : ""} with safety score ≥ 8 nearby.`;
    } else if (avgEquity !== null && avgEquity >= HIGH_EQUITY_THRESHOLD) {
      recommendation = "High-equity area with adequate access — preserve or modestly enhance current service.";
    } else {
      recommendation = "Low-need area with adequate access — no immediate service change indicated.";
    }

    return { nearbyStops, nearbyCells, popInRadius, popUnderserved, avgEquity, hotStops, recommendation };
  }, [point, stops, cells, equity]);

  const fmtPop  = (n: number) => n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
  const fmtDist = (m: number) => `${Math.round(m)} m`;

  const stopItems: DataListItem[] = (inspection?.nearbyStops ?? []).slice(0, 15).map(s => ({
    id: s.f.properties.stop_id,
    primary: s.f.properties.stop_name ?? s.f.properties.stop_id,
    secondary: `${fmtDist(s.distance)} from click`,
    trailing: s.f.properties.safety_score == null ? "—" : s.f.properties.safety_score.toFixed(1),
  }));

  const cellItems: DataListItem[] = (inspection?.nearbyCells ?? [])
    .filter(c => c.poor_access && c.f.properties.equity_score >= HIGH_EQUITY_THRESHOLD)
    .slice(0, 10)
    .map(c => ({
      id: c.f.properties.cell_id,
      primary: c.f.properties.cell_id,
      secondary: `${c.f.properties.equity_tier.replace("_", " ")} need · ${fmtPop(c.f.properties.population)} residents`,
      trailing: c.f.properties.equity_score.toFixed(3),
    }));

  return (
    <div className="section">
      <div className="section__header">
        <h2 className="section__title">Workbench</h2>
        <span className="section__subtitle">
          Click anywhere on the map to inspect coverage, demand, and stops within 500 m
        </span>
        {point && (
          <button
            type="button"
            className="export-button"
            onClick={() => setWorkbenchPoint(null)}
          >
            Clear pin
          </button>
        )}
      </div>

      {error && <SectionError message={error} onRetry={() => setTick(t => t + 1)} />}

      {point && inspection && (
        <div className="section__kpi-strip">
          <KpiCard label="Stops within 500 m"     value={String(inspection.nearbyStops.length)} />
          <KpiCard label="Residents in radius"    value={fmtPop(inspection.popInRadius)} />
          <KpiCard label="High-need underserved"  value={fmtPop(inspection.popUnderserved)} sub="poor access in radius" deltaIsGood={false} />
          <KpiCard label="Avg equity score"       value={inspection.avgEquity == null ? "—" : inspection.avgEquity.toFixed(3)} />
          <KpiCard label="Hot stops"              value={String(inspection.hotStops)} sub="safety ≥ 8" deltaIsGood={false} />
        </div>
      )}

      <div className="section__grid">
        <SectionMap mapMode="workbench" title="Click to inspect" height={480} />
        <div className="section__panel">
          {!point && (
            <EmptyState
              message="Click anywhere on the map to inspect."
              hint="The Workbench summarises stops, coverage, and equity within 500 m of where you click."
            />
          )}
          {loading && !inspection && <Spinner />}
          {point && inspection && (
            <>
              <div className="planning-workbench__rec">
                <div className="planning-workbench__rec-label">Service recommendation</div>
                <div className="planning-workbench__rec-body">{inspection.recommendation}</div>
                <div className="planning-workbench__rec-meta">
                  Inspection point: {point.lat.toFixed(5)}, {point.lng.toFixed(5)}
                </div>
              </div>

              <div className="planning-workbench__sub">
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <h3 className="section__panel-title">Stops within 500 m</h3>
                  <ExportButton
                    filename="planning-workbench-stops.csv"
                    rows={stopItems.map(s => ({
                      stop_id: s.id, name: s.primary, distance: s.secondary, safety: s.trailing,
                    }))}
                  />
                </div>
                {stopItems.length === 0 ? (
                  <EmptyState message="No stops in this radius — service gap." />
                ) : (
                  <DataList items={stopItems} />
                )}
              </div>

              <div className="planning-workbench__sub">
                <h3 className="section__panel-title">Underserved high-need cells nearby</h3>
                {cellItems.length === 0 ? (
                  <EmptyState message="No high-need cells with poor access in this radius." />
                ) : (
                  <DataList items={cellItems} />
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

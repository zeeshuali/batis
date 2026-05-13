import React, { useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";
import {
  KpiCard, Spinner, EmptyState, SectionError, ExportButton,
} from "../../components/primitives";
import { SectionMap } from "../../components/SectionMap";
import { ServiceGapDrawer } from "./ServiceGapDrawer";
import "../sections.css";
import "./planning.css";

interface GapProps {
  cell_id:             string;
  gap_pct:             number;
  gap_tier:            "very_high" | "high" | "moderate" | "low" | null;
  scheduled_arrivals:  number;
  missed_arrivals:     number;
  window_start:        string;
  window_end:          string;
  equity_score:        number | null;
  equity_adjusted_gap: number | null;
  population:          number | null;
}

interface GapFeature {
  type:       "Feature";
  geometry:   GeoJSON.Geometry;
  properties: GapProps;
}

const fmtPct = (v: number | null) => v == null ? "—" : `${v.toFixed(1)}%`;
const fmtInt = (v: number | null) => v == null ? "—" : v.toLocaleString();

/** Planning → Service Delivery Gap — % of scheduled stop arrivals
 *  that didn't happen, per cell, over the trailing 12-month window. */
export const ServiceDeliveryGap: React.FC = () => {
  const [features, setFeatures] = useState<GapFeature[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(null);
    api.get<GeoJSON.FeatureCollection>("/equity/service-delivery-gap")
      .then(res => {
        if (cancelled) return;
        setFeatures(res.data.features as unknown as GapFeature[]);
      })
      .catch(err => { if (!cancelled) setError(err?.message ?? "Failed to load"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const kpis = useMemo(() => {
    const total      = features.length;
    const gaps       = features.map(f => f.properties.gap_pct);
    const mean       = gaps.length === 0 ? null
                      : gaps.reduce((a, b) => a + b, 0) / gaps.length;
    const high       = features.filter(f => f.properties.gap_pct >= 5).length;
    const worst      = gaps.length === 0 ? null : Math.max(...gaps);
    const totalMissed = features.reduce((a, f) => a + f.properties.missed_arrivals, 0);
    return { total, mean, high, worst, totalMissed };
  }, [features]);

  const topTen = useMemo(() => {
    return [...features]
      .sort((a, b) => (b.properties.equity_adjusted_gap ?? 0)
                    - (a.properties.equity_adjusted_gap ?? 0))
      .slice(0, 10);
  }, [features]);

  return (
    <div className="section">
      <div className="section__header">
        <h2 className="section__title">Service Delivery Gap</h2>
        <span className="section__subtitle">
          % of scheduled stop arrivals that didn't happen (trailing 12 months)
        </span>
      </div>

      {error && <SectionError message={error} onRetry={() => window.location.reload()} />}

      {loading && !error && (
        <div className="section__panel"><Spinner /></div>
      )}

      {!loading && !error && features.length === 0 && (
        <EmptyState
          message="No service delivery gap data yet."
          hint="Run the nightly ETL — the service-delivery-gap compute step populates the table."
        />
      )}

      {!loading && !error && features.length > 0 && (
        <>
          <div className="section__kpi-strip">
            <KpiCard label="Cells"            value={fmtInt(kpis.total)} />
            <KpiCard label="Mean gap"         value={fmtPct(kpis.mean)} />
            <KpiCard label="High-gap cells"   value={fmtInt(kpis.high)}
                     sub="≥5%" />
            <KpiCard label="Worst gap"        value={fmtPct(kpis.worst)} />
            <KpiCard label="Total missed"     value={fmtInt(kpis.totalMissed)}
                     sub="stop-arrivals" />
          </div>

          <div className="section__grid">
            <SectionMap mapMode="service-delivery-gap"
                        title="Cell-level gap choropleth"
                        height={520} />
            <div className="section__panel">
              <div style={{ display: "flex", alignItems: "center",
                            justifyContent: "space-between" }}>
                <h3 className="section__panel-title">
                  Top-10 equity-adjusted high-gap cells
                </h3>
                <ExportButton
                  filename="planning-service-delivery-gap.csv"
                  rows={features.map(f => ({
                    cell_id:             f.properties.cell_id,
                    gap_pct:             f.properties.gap_pct,
                    gap_tier:            f.properties.gap_tier,
                    scheduled_arrivals:  f.properties.scheduled_arrivals,
                    missed_arrivals:     f.properties.missed_arrivals,
                    equity_score:        f.properties.equity_score,
                    equity_adjusted_gap: f.properties.equity_adjusted_gap,
                    population:          f.properties.population,
                    window_start:        f.properties.window_start,
                    window_end:          f.properties.window_end,
                  }))}
                />
              </div>
              <p className="planning-fares__caption">
                Sorted by gap_pct × equity_score so cells where high-need
                residents lose the most service surface first.
              </p>
              <ul className="planning-fares__burden-list">
                {topTen.map(f => (
                  <li key={f.properties.cell_id} className="planning-fares__burden-row">
                    <span className="planning-fares__burden-cell">{f.properties.cell_id}</span>
                    <span className="planning-fares__burden-equity">
                      equity {(f.properties.equity_score ?? 0).toFixed(3)}
                    </span>
                    <span className="planning-fares__burden-fare">
                      {fmtPct(f.properties.gap_pct)}
                    </span>
                    <span className="planning-fares__burden-score">
                      {f.properties.gap_tier ?? "—"}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <ServiceGapDrawer />
        </>
      )}
    </div>
  );
};

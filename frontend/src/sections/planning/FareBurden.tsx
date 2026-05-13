import React, { useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";
import {
  KpiCard, Spinner, EmptyState, SectionError, ExportButton,
} from "../../components/primitives";
import { SectionMap } from "../../components/SectionMap";
import "../sections.css";
import "./planning.css";

interface FareBurdenProps {
  cell_id:                 string;
  median_fare_to_sf:       number | null;
  median_fare_to_oakland:  number | null;
  median_fare_to_sfo:      number | null;
  worst_fare:              number | null;
  burden_pct:              number | null;
  burden_tier:             "very_high" | "high" | "moderate" | "low" | null;
  reachable_anchor_count:  number | null;
  population:              number | null;
  median_household_income: number | null;
}

interface CellFeature {
  type:        "Feature";
  geometry:    GeoJSON.Geometry;
  properties:  FareBurdenProps;
}

const TIER_LABEL: Record<NonNullable<FareBurdenProps["burden_tier"]>, string> = {
  very_high: "Very high (≥15%)",
  high:      "High (10–15%)",
  moderate:  "Moderate (5–10%)",
  low:       "Low (<5%)",
};

const fmtMoney = (v: number | null) => v == null ? "—" : `$${v.toFixed(2)}`;
const fmtPct   = (v: number | null) => v == null ? "—" : `${v.toFixed(1)}%`;
const fmtInt   = (v: number | null) => v == null ? "—" : v.toLocaleString();

/** Planning → Fare Burden — regional choropleth of monthly fare cost
 *  as a % of median household income, computed against three anchor
 *  destinations (SF / Oakland / SFO). */
export const FareBurden: React.FC = () => {
  const [features, setFeatures] = useState<CellFeature[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(null);
    api.get<GeoJSON.FeatureCollection>("/equity/fare-burden")
      .then(res => {
        if (cancelled) return;
        // The endpoint only returns polygon cells today; cast directly.
        setFeatures(res.data.features as unknown as CellFeature[]);
      })
      .catch(err => { if (!cancelled) setError(err?.message ?? "Failed to load fare burden"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const kpis = useMemo(() => {
    const total      = features.length;
    const reachable  = features.filter(f => (f.properties.reachable_anchor_count ?? 0) > 0).length;
    const burdens    = features
      .map(f => f.properties.burden_pct)
      .filter((v): v is number => v != null)
      .sort((a, b) => a - b);
    const medianBurden = burdens.length === 0
      ? null
      : burdens.length % 2 === 1
        ? burdens[(burdens.length - 1) / 2]
        : (burdens[burdens.length / 2 - 1] + burdens[burdens.length / 2]) / 2;
    const highBurden = features.filter(f => {
      const t = f.properties.burden_tier;
      return t === "very_high" || t === "high";
    }).length;
    const worst = burdens.length === 0 ? null : burdens[burdens.length - 1];
    return { total, reachable, medianBurden, highBurden, worst };
  }, [features]);

  const topHighBurden = useMemo(() => {
    return [...features]
      .filter(f => f.properties.burden_pct != null)
      .sort((a, b) => (b.properties.burden_pct ?? 0) - (a.properties.burden_pct ?? 0))
      .slice(0, 10);
  }, [features]);

  return (
    <div className="section">
      <div className="section__header">
        <h2 className="section__title">Fare Burden</h2>
        <span className="section__subtitle">
          Monthly fare cost as % of median household income, vs. SF / Oakland / SFO anchors
        </span>
      </div>

      {error && <SectionError message={error} onRetry={() => window.location.reload()} />}

      {loading && !error && (
        <div className="section__panel"><Spinner /></div>
      )}

      {!loading && !error && features.length === 0 && (
        <EmptyState
          message="No fare burden data yet."
          hint="Run the nightly ETL — step 14 (Fare burden compute) populates the fare_burden table."
        />
      )}

      {!loading && !error && features.length > 0 && (
        <>
          <div className="section__kpi-strip">
            <KpiCard label="Cells"             value={fmtInt(kpis.total)} />
            <KpiCard label="Reachable"         value={fmtInt(kpis.reachable)}
              sub={`${((kpis.reachable / kpis.total) * 100).toFixed(0)}% of cells`} />
            <KpiCard label="Median burden"     value={fmtPct(kpis.medianBurden)}
              sub="of monthly HH income" />
            <KpiCard label="High-burden cells" value={fmtInt(kpis.highBurden)}
              sub="≥10% of income" />
            <KpiCard label="Worst burden"      value={fmtPct(kpis.worst)} />
          </div>

          <div className="section__grid">
            <SectionMap mapMode="fare-burden" title="Regional fare-burden choropleth" height={520} />
            <div className="section__panel">
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <h3 className="section__panel-title">Top-10 high-burden cells</h3>
                <ExportButton
                  filename="planning-fare-burden.csv"
                  rows={features.map(f => ({
                    cell_id:                 f.properties.cell_id,
                    median_fare_to_sf:       f.properties.median_fare_to_sf,
                    median_fare_to_oakland:  f.properties.median_fare_to_oakland,
                    median_fare_to_sfo:      f.properties.median_fare_to_sfo,
                    worst_fare:              f.properties.worst_fare,
                    burden_pct:              f.properties.burden_pct,
                    burden_tier:             f.properties.burden_tier,
                    reachable_anchor_count:  f.properties.reachable_anchor_count,
                    population:              f.properties.population,
                    median_household_income: f.properties.median_household_income,
                  }))}
                />
              </div>
              <p className="planning-fares__caption">
                Cells where the worst-of-three anchor round-trip × 22 workdays consumes the
                largest share of monthly median household income. Burden bands:{" "}
                {(Object.entries(TIER_LABEL) as [NonNullable<FareBurdenProps["burden_tier"]>, string][])
                  .map(([k, label]) => <span key={k}>{label}{k === "low" ? "" : " · "}</span>)}
              </p>
              <ul className="planning-fares__burden-list">
                {topHighBurden.map(f => (
                  <li key={f.properties.cell_id} className="planning-fares__burden-row">
                    <span className="planning-fares__burden-cell">{f.properties.cell_id}</span>
                    <span className="planning-fares__burden-equity">
                      worst {fmtMoney(f.properties.worst_fare)}
                    </span>
                    <span className="planning-fares__burden-fare">
                      {fmtPct(f.properties.burden_pct)}
                    </span>
                    <span className="planning-fares__burden-score">
                      {f.properties.burden_tier
                        ? TIER_LABEL[f.properties.burden_tier].split(" ")[0]
                        : "—"}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

import React, { useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";
import {
  KpiCard, Spinner, EmptyState, SectionError, ExportButton,
} from "../../components/primitives";
import { SectionMap } from "../../components/SectionMap";
import { ADAGapDrawer } from "./ADAGapDrawer";
import { useSelection } from "../../context/SelectionContext";
import "../sections.css";
import "./planning.css";

interface AdaStopProps {
  stop_id:              string;
  agency_id:            string;
  stop_name:            string;
  wheelchair_boarding:  number | null;
  supply_penalty:       number | null;
  ambulatory_pop_400m:  number;
  gap_score:            number;
  gap_tier:             "low" | "moderate" | "high" | "very_high" | null;
  pathways_override:    boolean;
  routes_serving:       string[];
}

interface AdaStopFeature {
  type:       "Feature";
  geometry:   { type: "Point"; coordinates: [number, number] };
  properties: AdaStopProps;
}

type AdaStopFC = { type: "FeatureCollection"; features: AdaStopFeature[] };

const fmtInt = (v: number | null) => v == null ? "—" : v.toLocaleString();

/** Planning → ADA Accessibility Gap — stops to prioritise for wheelchair
 *  retrofit, ranked by gap_score (ambulatory population × supply penalty). */
export const ADAGap: React.FC = () => {
  const { setAdaGapDrillStop } = useSelection();
  const [features, setFeatures] = useState<AdaStopFeature[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .get<AdaStopFC>("/accessibility/gaps", { params: { limit: 20000 } })
      .then(r => { if (!cancelled) setFeatures(r.data.features as AdaStopFeature[]); })
      .catch(e => { if (!cancelled) setError(e?.message ?? "Failed to load"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const kpis = useMemo(() => {
    const total         = features.length;
    const inaccessible  = features.filter(f => f.properties.wheelchair_boarding === 2).length;
    const unknown       = features.filter(f =>
      f.properties.wheelchair_boarding === 0 || f.properties.wheelchair_boarding == null
    ).length;
    const overrides     = features.filter(f => f.properties.pathways_override).length;
    const totalUnderserved = Math.round(
      features
        .filter(f => f.properties.gap_tier === "very_high")
        .reduce((acc, f) => acc + (f.properties.gap_score ?? 0), 0)
    );
    return { total, inaccessible, unknown, overrides, totalUnderserved };
  }, [features]);

  const topTen = useMemo(() => {
    return [...features]
      .sort((a, b) => (b.properties.gap_score ?? 0) - (a.properties.gap_score ?? 0))
      .slice(0, 10);
  }, [features]);

  return (
    <div className="section">
      <div className="section__header">
        <h2 className="section__title">ADA Accessibility Gap</h2>
        <span className="section__subtitle">
          Stops to prioritise for wheelchair retrofit, ranked by gap score
        </span>
      </div>

      {error && <SectionError message={error} onRetry={() => window.location.reload()} />}

      {loading && !error && (
        <div className="section__panel"><Spinner /></div>
      )}

      {!loading && !error && features.length === 0 && (
        <EmptyState
          message="No ADA gap data yet."
          hint="Run the nightly ETL — the ADA accessibility gap compute step populates the table."
        />
      )}

      {!loading && !error && features.length > 0 && (
        <>
          <div className="section__kpi-strip">
            <KpiCard label="Stops scored"     value={fmtInt(kpis.total)} />
            <KpiCard label="Inaccessible"     value={fmtInt(kpis.inaccessible)} />
            <KpiCard label="Unknown status"   value={fmtInt(kpis.unknown)} />
            <KpiCard label="Pathways override" value={fmtInt(kpis.overrides)} />
            <KpiCard label="Total underserved" value={fmtInt(kpis.totalUnderserved)}
                     sub="very-high tier gap score" />
          </div>

          <div className="section__grid">
            <SectionMap mapMode="ada-gap"
                        title="Stop-level ADA gap map"
                        height={520} />
            <div className="section__panel">
              <div style={{ display: "flex", alignItems: "center",
                            justifyContent: "space-between" }}>
                <h3 className="section__panel-title">
                  Top-10 stops to retrofit
                </h3>
                <ExportButton
                  filename="planning-ada-gap.csv"
                  rows={features.map(f => ({
                    stop_id:             f.properties.stop_id,
                    agency_id:           f.properties.agency_id,
                    stop_name:           f.properties.stop_name,
                    gap_score:           f.properties.gap_score,
                    gap_tier:            f.properties.gap_tier,
                    ambulatory_pop_400m: f.properties.ambulatory_pop_400m,
                    supply_penalty:      f.properties.supply_penalty,
                    wheelchair_boarding: f.properties.wheelchair_boarding,
                    pathways_override:   f.properties.pathways_override,
                  }))}
                />
              </div>
              <p className="planning-fares__caption">
                Sorted by gap_score (ambulatory population × supply penalty) so
                stops serving the most underserved residents surface first.
              </p>
              <ul className="planning-fares__burden-list">
                {topTen.map(f => (
                  <li key={`${f.properties.agency_id}-${f.properties.stop_id}`}
                      className="planning-fares__burden-row"
                      style={{ cursor: "pointer" }}
                      onClick={() => setAdaGapDrillStop(f.properties.stop_id)}
                  >
                    <span className="planning-fares__burden-cell">
                      {f.properties.stop_name}
                    </span>
                    <span className="planning-fares__burden-equity">
                      {f.properties.agency_id}
                    </span>
                    <span className="planning-fares__burden-fare">
                      {Math.round(f.properties.gap_score).toLocaleString()}
                    </span>
                    <span className="planning-fares__burden-score">
                      {f.properties.gap_tier ?? "—"}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <ADAGapDrawer />
        </>
      )}
    </div>
  );
};

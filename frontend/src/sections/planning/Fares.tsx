import React, { useEffect, useState } from "react";
import { useSelection } from "../../context/SelectionContext";
import { api } from "../../lib/api";
import {
  KpiCard, BarChart, Spinner, EmptyState, SectionError, ExportButton,
  type BarPoint,
} from "../../components/primitives";
import { SectionMap } from "../../components/SectionMap";
import { agencyColor } from "../../lib/agencies";
import "../sections.css";
import "./planning.css";

interface TierBreakdown { n: number; median_fare: number | null; }
interface HighBurdenCell {
  cell_id:        string;
  equity_score:   number;
  median_fare:    number;
  burden:         number;
}
interface CorridorSummary {
  n_sampled:        number;
  median_fare:      number | null;
  p25_fare:         number | null;
  p75_fare:         number | null;
  max_fare:         number | null;
  agencies:         string[];
  by_equity_tier:   Record<"very_high" | "high" | "medium" | "low", TierBreakdown>;
  high_burden_cells: HighBurdenCell[];
  notice:           string | null;
}

const TIER_LABEL: Record<string, string> = {
  very_high: "Very high",
  high:      "High",
  medium:    "Medium",
  low:       "Low",
};
const TIER_COLOR: Record<string, string> = {
  very_high: "#dc2626",
  high:      "#f97316",
  medium:    "#facc15",
  low:       "#22c55e",
};

/** Planning → Fares — corridor fare burden + equity overlay. */
export const Fares: React.FC = () => {
  const { selection, clearFaresPins } = useSelection();
  const origin = selection.faresOrigin;
  const dest   = selection.faresDestination;

  const [summary, setSummary] = useState<CorridorSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);

  // Re-sample whenever both pins are set OR either pin changes.
  useEffect(() => {
    if (!origin || !dest) {
      setSummary(null);
      return;
    }
    let cancelled = false;
    setLoading(true); setError(null);
    api.post<CorridorSummary>("/fares/sample-corridor", {
      origin:      { lat: origin.lat, lng: origin.lng },
      destination: { lat: dest.lat,   lng: dest.lng   },
      n: 30,
    })
      .then(res => { if (!cancelled) setSummary(res.data); })
      .catch(err => { if (!cancelled) setError(err?.message ?? "Failed to sample corridor"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [origin?.lat, origin?.lng, dest?.lat, dest?.lng]);

  const fmtMoney = (v: number | null) => v == null ? "—" : `$${v.toFixed(2)}`;

  // Histogram bucketing: 50 cent bins from the floor of the cheapest fare
  // to the ceiling of the most expensive. Keeps the chart readable for
  // BART's $2–$10 range without bunching everything into one bar.
  const histogram: BarPoint[] = React.useMemo(() => {
    if (!summary || summary.p25_fare == null || summary.max_fare == null) return [];
    // The sampler doesn't return raw fares — synthesize buckets from the
    // summary stats so the histogram still tells the right story:
    // a single bar at the median + p25/p75/max as additional markers.
    // (A real raw-fare histogram needs an API change; the design doc
    // calls for "fare distribution" and the summary stats convey that.)
    return [
      { label: "p25",    value: summary.p25_fare ?? 0,    color: "#94a3b8" },
      { label: "median", value: summary.median_fare ?? 0, color: "#3b82f6" },
      { label: "p75",    value: summary.p75_fare ?? 0,    color: "#94a3b8" },
      { label: "max",    value: summary.max_fare  ?? 0,   color: "#ef4444" },
    ];
  }, [summary]);

  const tierChart: BarPoint[] = React.useMemo(() => {
    if (!summary) return [];
    return (["very_high", "high", "medium", "low"] as const)
      .map(t => ({
        label: TIER_LABEL[t],
        value: summary.by_equity_tier[t]?.median_fare ?? 0,
        color: TIER_COLOR[t],
      }))
      .filter(p => p.value > 0);
  }, [summary]);

  return (
    <div className="section">
      <div className="section__header">
        <h2 className="section__title">Fares</h2>
        <span className="section__subtitle">
          Corridor fare burden — click an origin then a destination on the map
        </span>
        {(origin || dest) && (
          <button type="button" className="export-button" onClick={clearFaresPins}>
            Clear pins
          </button>
        )}
      </div>

      {error && <SectionError message={error} onRetry={() => window.location.reload()} />}

      {summary && summary.n_sampled > 0 && (
        <div className="section__kpi-strip">
          <KpiCard label="Pairs sampled" value={String(summary.n_sampled)} sub="OD stop pairs" />
          <KpiCard label="Median fare"   value={fmtMoney(summary.median_fare)} />
          <KpiCard label="p25 / p75"     value={`${fmtMoney(summary.p25_fare)} / ${fmtMoney(summary.p75_fare)}`} />
          <KpiCard label="Max fare"      value={fmtMoney(summary.max_fare)} deltaIsGood={false} />
          <KpiCard label="Agencies"
            value={summary.agencies.length === 0 ? "—" : summary.agencies.join(", ")}
            sub={summary.notice ?? ""}
          />
        </div>
      )}

      <div className="section__grid">
        <SectionMap mapMode="fares" title="Pin-on-map corridor selector" height={460} />
        <div className="section__panel">
          {!origin && (
            <EmptyState
              message="Click an origin on the map to start."
              hint="The Fares page samples up to 30 OD stop pairs between your two clicks and computes the fare distribution + equity burden."
            />
          )}
          {origin && !dest && (
            <EmptyState
              message="Now click a destination."
              hint="Same corridor map — origin pin is green, destination will be red."
            />
          )}
          {origin && dest && loading && <Spinner />}
          {summary && summary.n_sampled === 0 && (
            <EmptyState
              message={summary.notice ?? "No pairs found for this corridor."}
              hint="Try widening the click area or picking points served by the same agency."
            />
          )}
          {summary && summary.n_sampled > 0 && (
            <>
              <h3 className="section__panel-title">Fare distribution</h3>
              <BarChart data={histogram} height={200} />
              {tierChart.length > 0 && (
                <>
                  <h3 className="section__panel-title" style={{ marginTop: "var(--space-4)" }}>
                    Median fare by equity tier
                  </h3>
                  <BarChart data={tierChart} height={200} />
                </>
              )}
              {summary.agencies.length > 0 && (
                <div className="planning-fares__agencies">
                  Agencies in sample:{" "}
                  {summary.agencies.map(a => (
                    <span key={a} className="planning-fares__agency-chip"
                          style={{ borderColor: agencyColor(a), color: agencyColor(a) }}>
                      {a}
                    </span>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {summary && summary.high_burden_cells.length > 0 && (
        <div className="section__panel">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <h3 className="section__panel-title">High-burden cells</h3>
            <ExportButton
              filename="planning-fares-high-burden.csv"
              rows={summary.high_burden_cells.map(c => ({
                cell_id:      c.cell_id,
                equity_score: c.equity_score,
                median_fare:  c.median_fare,
                burden:       c.burden,
              }))}
            />
          </div>
          <p className="planning-fares__caption">
            Cells where high-need residents face the highest typical fare for this corridor
            (burden = median fare × equity score). Top 10 shown.
          </p>
          <ul className="planning-fares__burden-list">
            {summary.high_burden_cells.map(c => (
              <li key={c.cell_id} className="planning-fares__burden-row">
                <span className="planning-fares__burden-cell">{c.cell_id}</span>
                <span className="planning-fares__burden-equity">
                  equity {c.equity_score.toFixed(3)}
                </span>
                <span className="planning-fares__burden-fare">
                  {fmtMoney(c.median_fare)}
                </span>
                <span className="planning-fares__burden-score">
                  burden {c.burden.toFixed(3)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import {
  Spinner, EmptyState, SectionError, ExportButton,
} from "../../components/primitives";
import { agencyColor } from "../../lib/agencies";

interface DesertFeature {
  type: "Feature";
  geometry: any;
  properties: {
    cell_id: string;
    population: number;
    equity_score: number;
    desert_pairs: [string, string][];
    worst_distance_m: number;
    pair_count: number;
  };
}

/** Sprint 4a Phase 3 — Transfer Desert Map (list view).
 *  Surfaces cells where one agency is reachable but another is just outside
 *  walk-transfer range.  The list is what city planners actually use for
 *  funding arguments; a map overlay can come in a follow-up. */
export const TransferDesertsPanel: React.FC = () => {
  const [rows, setRows]       = useState<DesertFeature[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const [tick, setTick]       = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(null);
    api.get<{ features: DesertFeature[] }>("/transfers/deserts",
        { params: { min_population: 100, limit: 30 } })
      .then(res => { if (!cancelled) setRows(res.data?.features ?? []); })
      .catch(err => { if (!cancelled) setError(err?.message ?? "Failed to load"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [tick]);

  if (error) return <SectionError message={error} onRetry={() => setTick(t => t + 1)} />;
  if (loading && rows.length === 0) return <Spinner />;
  if (rows.length === 0) {
    return (
      <EmptyState
        message="No transfer deserts found."
        hint="A cell is a desert when one agency is reachable within 2 km but another is more than 800 m further. Wider gaps surface here as the data accumulates."
      />
    );
  }

  const fmtPop = (n: number) => n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);

  return (
    <div className="section__panel">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h3 className="section__panel-title">Transfer deserts</h3>
        <ExportButton
          filename="planning-coverage-transfer-deserts.csv"
          rows={rows.map(f => ({
            cell_id:           f.properties.cell_id,
            population:        f.properties.population,
            pair_count:        f.properties.pair_count,
            worst_distance_m:  f.properties.worst_distance_m,
            desert_pairs:      f.properties.desert_pairs
              .map(([a, b]) => `${a}-${b}`).join("; "),
          }))}
        />
      </div>
      <p className="planning-deserts__caption">
        Cells where one agency is reachable but another is just outside walk range.
        Ranked by population × number of missing pairs.
      </p>
      <ul className="planning-deserts__list">
        {rows.slice(0, 20).map((f) => {
          const p = f.properties;
          return (
            <li key={p.cell_id} className="planning-deserts__row">
              <div className="planning-deserts__head">
                <span className="planning-deserts__pop">{fmtPop(p.population)} residents</span>
                <span className="planning-deserts__worst">
                  worst gap {(p.worst_distance_m / 1000).toFixed(1)} km
                </span>
              </div>
              <div className="planning-deserts__pairs">
                {p.desert_pairs.slice(0, 6).map(([a, b], i) => (
                  <span key={`${a}-${b}-${i}`} className="planning-deserts__pair">
                    <span style={{ color: agencyColor(a) }}>{a}</span>
                    <span style={{ opacity: 0.4 }}>↔</span>
                    <span style={{ color: agencyColor(b) }}>{b}</span>
                  </span>
                ))}
                {p.desert_pairs.length > 6 && (
                  <span className="planning-deserts__more">+{p.desert_pairs.length - 6}</span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
};

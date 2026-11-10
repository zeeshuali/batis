import React, { useEffect, useMemo, useState } from "react";
import { useAgencies } from "../../context/AgenciesContext";
import { api } from "../../lib/api";
import {
  DataList, Spinner, EmptyState, SectionError, ExportButton,
  type DataListItem,
} from "../../components/primitives";
import { agencyColor } from "../../lib/agencies";

interface TransferRow {
  from_agency: string;
  to_agency:   string;
  transfer_stop_id:   string;
  transfer_stop_name: string | null;
  from_stop_pk:       number;
  to_stop_pk:         number;
  to_stop_id:         string;
  to_stop_name:       string | null;
  distance_m:         number;
  scheduled_transfer_minutes: number | null;
  success_rate_pct:           number | null;
  median_gap_seconds:         number | null;
  n_observations:             number;
}

/** Color-scale a success-rate cell: green ≥90, red <60, ramp in between. */
function successColor(pct: number | null, alpha = 0.85): string {
  if (pct == null) return "transparent";
  if (pct >= 90) return `rgba(34, 197, 94, ${alpha})`;   // green
  if (pct >= 75) return `rgba(132, 204, 22, ${alpha})`;  // lime
  if (pct >= 60) return `rgba(250, 204, 21, ${alpha})`;  // yellow
  if (pct >= 40) return `rgba(249, 115, 22, ${alpha})`;  // orange
  return `rgba(239, 68, 68, ${alpha})`;                  // red
}

/** Heat-map panel — rows = from_agency, columns = to_agency. Each cell
 *  aggregates all transfer stops between the pair into one success_rate. */
export const TransferReliabilityPanel: React.FC = () => {
  const { agencies, byId } = useAgencies();
  const [rows, setRows]       = useState<TransferRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const [tick, setTick]       = useState(0);
  const [activePair, setActivePair] = useState<{ from: string; to: string } | null>(null);
  const [radii, setRadii]     = useState<number[]>([]);
  const [radius, setRadius]   = useState<number | null>(null);

  // Radius options (and the default) come from the backend settings.
  useEffect(() => {
    api.get<{ radii_m: number[]; default_m: number }>("/transfers/radii")
      .then(res => { setRadii(res.data.radii_m); setRadius(r => r ?? res.data.default_m); })
      .catch(err => setError(err?.message ?? "Failed to load radii"));
  }, []);

  useEffect(() => {
    if (radius == null) return;
    let cancelled = false;
    setLoading(true); setError(null);
    api.get<TransferRow[]>("/transfers/reliability", { params: { min_observations: 1, limit: 2000, radius_m: radius } })
      .then(res => { if (!cancelled) setRows(Array.isArray(res.data) ? res.data : []); })
      .catch(err => { if (!cancelled) setError(err?.message ?? "Failed to load"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [tick, radius]);

  // Only show agencies that actually appear in the transfer matrix — most of
  // the 47-row catalog has no transfer data, and rendering empty rows/columns
  // is just noise.
  const pairAgencies = useMemo(() => {
    const ids = new Set<string>();
    for (const r of rows) { ids.add(r.from_agency); ids.add(r.to_agency); }
    return agencies.filter(a => ids.has(a.agency_id));
  }, [rows, agencies]);

  // Aggregate per (from, to) pair: weighted success rate + total observations.
  const matrix = useMemo(() => {
    const m = new Map<string, { success_rate: number | null; n: number }>();
    const buckets = new Map<string, { weighted: number; n: number }>();
    for (const r of rows) {
      const key = `${r.from_agency}→${r.to_agency}`;
      const cur = buckets.get(key) ?? { weighted: 0, n: 0 };
      const rate = r.success_rate_pct ?? 0;
      cur.weighted += rate * r.n_observations;
      cur.n        += r.n_observations;
      buckets.set(key, cur);
    }
    for (const [key, b] of buckets) {
      m.set(key, { success_rate: b.n > 0 ? b.weighted / b.n : null, n: b.n });
    }
    return m;
  }, [rows]);

  // Drill-down list when a cell is active.
  const drill: DataListItem[] = useMemo(() => {
    if (!activePair) return [];
    return rows
      .filter(r => r.from_agency === activePair.from && r.to_agency === activePair.to)
      .sort((a, b) => (a.success_rate_pct ?? 100) - (b.success_rate_pct ?? 100))
      .slice(0, 20)
      .map(r => ({
        id: `${r.from_stop_pk}-${r.to_stop_pk}`,
        primary: `${r.transfer_stop_name ?? r.transfer_stop_id} → ${r.to_stop_name ?? r.to_stop_id}`,
        secondary: `${r.distance_m} m · median gap ${Math.round((r.median_gap_seconds ?? 0))}s · ${r.n_observations} obs`,
        trailing: r.success_rate_pct == null ? "—" : `${Number(r.success_rate_pct).toFixed(0)}%`,
      }));
  }, [activePair, rows]);

  // Worst transfer points across all pairs.
  const worstTop10: DataListItem[] = useMemo(() => {
    return [...rows]
      .filter(r => r.n_observations >= 5)
      .sort((a, b) => (a.success_rate_pct ?? 100) - (b.success_rate_pct ?? 100))
      .slice(0, 10)
      .map(r => ({
        id: `${r.from_stop_pk}-${r.to_stop_pk}`,
        primary: `${r.from_agency}→${r.to_agency}: ${r.transfer_stop_name ?? r.transfer_stop_id} → ${r.to_stop_name ?? r.to_stop_id}`,
        secondary: `${r.distance_m} m · ${r.n_observations} observations`,
        trailing: r.success_rate_pct == null ? "—" : `${Number(r.success_rate_pct).toFixed(0)}%`,
      }));
  }, [rows]);

  if (error) {
    return <SectionError message={error} onRetry={() => setTick(t => t + 1)} />;
  }
  if ((loading || radius == null) && rows.length === 0) {
    return <Spinner />;
  }

  return (
    <>
      <div className="section__panel">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <h3 className="section__panel-title">Cross-agency transfer reliability</h3>
          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            Walking distance between stops
            <select value={radius ?? ""} onChange={e => setRadius(Number(e.target.value))}
                    aria-label="Transfer radius in metres">
              {radii.map(r => <option key={r} value={r}>{r} m</option>)}
            </select>
          </label>
          <ExportButton
            filename="transfer-reliability.csv"
            rows={rows.map(r => ({
              from_agency: r.from_agency,
              to_agency:   r.to_agency,
              from_stop_id:   r.transfer_stop_id,
              from_stop_name: r.transfer_stop_name,
              to_stop_id:     r.to_stop_id,
              to_stop_name:   r.to_stop_name,
              distance_m:     r.distance_m,
              success_rate_pct:   r.success_rate_pct,
              median_gap_seconds: r.median_gap_seconds,
              n_observations:     r.n_observations,
            }))}
          />
        </div>

        {rows.length === 0 && (
          <EmptyState
            message={`No transfer data within ${radius} m.`}
            hint="Stops of different agencies are matched by distance. Try a larger radius, or run compute_transfer_reliability() after loading stop_observations."
          />
        )}
        <div className="transfer-matrix">
          <table className="transfer-matrix__grid">
            <thead>
              <tr>
                <th className="transfer-matrix__corner">from \ to</th>
                {pairAgencies.map(a => (
                  <th key={a.agency_id} className="transfer-matrix__col"
                      style={{ color: agencyColor(a.agency_id) }}
                      title={a.agency_name}>
                    {a.agency_id}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {pairAgencies.map(from => (
                <tr key={from.agency_id}>
                  <th className="transfer-matrix__row"
                      style={{ color: agencyColor(from.agency_id) }}
                      title={from.agency_name}>
                    {from.agency_id}
                  </th>
                  {pairAgencies.map(to => {
                    if (from.agency_id === to.agency_id) {
                      return <td key={to.agency_id} className="transfer-matrix__cell transfer-matrix__cell--diag">—</td>;
                    }
                    const cell = matrix.get(`${from.agency_id}→${to.agency_id}`);
                    const isActive = activePair?.from === from.agency_id && activePair?.to === to.agency_id;
                    if (!cell) {
                      return <td key={to.agency_id} className="transfer-matrix__cell transfer-matrix__cell--empty">·</td>;
                    }
                    return (
                      <td key={to.agency_id}
                          className={`transfer-matrix__cell ${isActive ? "transfer-matrix__cell--active" : ""}`}
                          style={{ background: successColor(cell.success_rate) }}
                          onClick={() => setActivePair({ from: from.agency_id, to: to.agency_id })}
                          title={`${from.agency_id}→${to.agency_id} · ${cell.n} observations`}>
                        <span className="transfer-matrix__pct">
                          {cell.success_rate == null ? "—" : `${cell.success_rate.toFixed(0)}%`}
                        </span>
                        <span className="transfer-matrix__n">n={cell.n}</span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {activePair && (
          <div className="transfer-matrix__drill">
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
              <strong>
                {byId[activePair.from]?.agency_name ?? activePair.from}
                {" → "}
                {byId[activePair.to]?.agency_name ?? activePair.to}
                {" — transfer stops"}
              </strong>
              <button type="button" className="export-button" onClick={() => setActivePair(null)}>Close</button>
            </div>
            {drill.length === 0 ? <EmptyState message="No transfer stops for this pair." />
              : <DataList items={drill} />}
          </div>
        )}
      </div>

      <div className="section__panel">
        <h3 className="section__panel-title">Worst transfer points</h3>
        {worstTop10.length === 0 ? (
          <EmptyState message="Not enough observations yet — give the nightly job a few runs to accumulate data."/>
        ) : (
          <DataList items={worstTop10} />
        )}
      </div>
    </>
  );
};

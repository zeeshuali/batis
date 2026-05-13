import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useSelection } from "../../context/SelectionContext";
import { agencyColor } from "../../lib/agencies";
import { Spinner } from "../../components/primitives";
import "./planning.css";

interface RouteRow {
  agency_id:          string;
  route_id:           string;
  scheduled_arrivals: number;
  missed_arrivals:    number;
  missed_pct:         number;
}

/** Slide-in drawer that shows the top-N routes responsible for a
 *  cell's service-delivery gap.  Mounts when
 *  selection.serviceGapDrillCell is non-null; the parent page renders
 *  this once and lets it self-control via context. */
export const ServiceGapDrawer: React.FC = () => {
  const { selection, setServiceGapDrillCell } = useSelection();
  const cellId = selection.serviceGapDrillCell;

  const [rows,    setRows]    = useState<RouteRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);

  useEffect(() => {
    if (!cellId) { setRows([]); return; }
    let cancelled = false;
    setLoading(true); setError(null);
    api.get<RouteRow[]>(
      `/equity/service-delivery-gap/cells/${encodeURIComponent(cellId)}/routes?limit=5`
    )
      .then(res => { if (!cancelled) setRows(res.data); })
      .catch(err => { if (!cancelled) setError(err?.message ?? "Failed to load"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [cellId]);

  if (!cellId) return null;

  return (
    <aside className="planning-gap__drawer" role="dialog" aria-label="Service gap drill-down">
      <header className="planning-gap__drawer-header">
        <div>
          <div className="planning-gap__drawer-title">Cell {cellId}</div>
          <div className="planning-gap__drawer-subtitle">
            Top routes by missed-arrival count (12 mo)
          </div>
        </div>
        <button type="button" className="export-button"
                onClick={() => setServiceGapDrillCell(null)}>
          Close
        </button>
      </header>

      {loading && <Spinner />}
      {error && <div className="planning-gap__drawer-error">{error}</div>}

      {!loading && !error && rows.length === 0 && (
        <div className="planning-gap__drawer-empty">
          No route observations in this cell for the window.
        </div>
      )}

      {!loading && !error && rows.length > 0 && (
        <ul className="planning-fares__burden-list">
          {rows.map(r => (
            <li key={`${r.agency_id}-${r.route_id}`} className="planning-fares__burden-row">
              <span className="planning-fares__burden-cell"
                    style={{ color: agencyColor(r.agency_id) }}>
                {r.agency_id}
              </span>
              <span className="planning-fares__burden-equity">{r.route_id}</span>
              <span className="planning-fares__burden-fare">{r.missed_pct.toFixed(1)}%</span>
              <span className="planning-fares__burden-score">
                {r.missed_arrivals.toLocaleString()} / {r.scheduled_arrivals.toLocaleString()}
              </span>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
};

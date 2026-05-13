import React, { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useSelection } from "../../context/SelectionContext";
import { agencyColor } from "../../lib/agencies";
import { Spinner } from "../../components/primitives";
import "./planning.css";

interface RouteRow {
  route_id:        string;
  agency_id:       string;
  trips_per_day:   number;
}

interface TractRow {
  tract_geoid:          string;
  ambulatory_pop:       number;
  area_weighted_share:  number;
}

interface BreakdownResponse {
  stop_id:              string;
  stop_name:            string;
  agency_id:            string;
  gap_score:            number;
  gap_tier:             "low" | "moderate" | "high" | "very_high" | null;
  wheelchair_boarding:  number | null;
  supply_penalty:       number | null;
  routes:               RouteRow[];
  tracts:               TractRow[];
}

/** Slide-in drawer that shows per-stop ADA gap detail (routes + tracts).
 *  Mounts when selection.adaGapDrillStop is non-null; the parent page
 *  renders this once and lets it self-control via context. */
export const ADAGapDrawer: React.FC = () => {
  const { selection, setAdaGapDrillStop } = useSelection();
  const stopId = selection.adaGapDrillStop;

  const [data,    setData]    = useState<BreakdownResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);

  useEffect(() => {
    if (!stopId) { setData(null); return; }
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .get<BreakdownResponse>(
        `/accessibility/gaps/stops/${encodeURIComponent(stopId)}/breakdown`
      )
      .then(res => { if (!cancelled) setData(res.data); })
      .catch(err => { if (!cancelled) setError(err?.message ?? "Failed to load"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [stopId]);

  if (!stopId) return null;

  return (
    <aside className="ada-gap-drawer" role="dialog" aria-label="ADA gap stop detail">
      <div className="ada-gap-drawer__header">
        <div>
          <strong>{data?.stop_name ?? stopId}</strong>
          {data?.agency_id && (
            <span style={{ marginLeft: 8, fontSize: "0.8rem",
                           color: agencyColor(data.agency_id) }}>
              {data.agency_id}
            </span>
          )}
        </div>
        <button
          type="button"
          className="ada-gap-drawer__close"
          aria-label="Close"
          onClick={() => setAdaGapDrillStop(null)}
        >
          ×
        </button>
      </div>

      {loading && <Spinner />}
      {error && <div className="planning-gap__drawer-error">{error}</div>}

      {data && !loading && !error && (
        <>
          <p className="ada-gap-drawer__score">
            Gap score:{" "}
            <strong>{Math.round(data.gap_score).toLocaleString()}</strong>
            {" · "}
            <span className={`tier--${data.gap_tier ?? "none"}`}>
              {data.gap_tier?.replace("_", " ") ?? "—"}
            </span>
          </p>

          <h4 style={{ margin: "0 0 6px", fontSize: "0.85rem" }}>Routes serving</h4>
          {(data.routes ?? []).length === 0 ? (
            <p style={{ fontSize: "0.85rem", color: "var(--color-fg-3)" }}>
              No route data.
            </p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Route</th>
                  <th>Agency</th>
                  <th>Trips/day</th>
                </tr>
              </thead>
              <tbody>
                {(data.routes ?? []).map(r => (
                  <tr key={`${r.agency_id}-${r.route_id}`}>
                    <td>{r.route_id}</td>
                    <td style={{ color: agencyColor(r.agency_id) }}>{r.agency_id}</td>
                    <td>{r.trips_per_day}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h4 style={{ margin: "12px 0 6px", fontSize: "0.85rem" }}>Top contributing tracts</h4>
          {(data.tracts ?? []).length === 0 ? (
            <p style={{ fontSize: "0.85rem", color: "var(--color-fg-3)" }}>
              No tract data.
            </p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Tract</th>
                  <th>Ambulatory pop</th>
                  <th>Area share</th>
                </tr>
              </thead>
              <tbody>
                {(data.tracts ?? []).slice(0, 3).map(t => (
                  <tr key={t.tract_geoid}>
                    <td style={{ fontFamily: "var(--font-mono, ui-monospace)",
                                 fontSize: "0.8rem" }}>
                      {t.tract_geoid}
                    </td>
                    <td>{t.ambulatory_pop.toLocaleString()}</td>
                    <td>{(t.area_weighted_share * 100).toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </aside>
  );
};

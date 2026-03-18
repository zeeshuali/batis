import React, { useEffect, useState } from "react";
import axios from "axios";

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string) || "http://localhost:8000";
const API_KEY  = (import.meta.env.VITE_API_KEY  as string) || "";
function h() { return API_KEY ? { "X-API-Key": API_KEY } : {}; }

interface StopDetail {
  stop_id: string;
  stop_code: string | null;
  stop_name: string | null;
  stop_lat: number;
  stop_lon: number;
  safety_score: number;
  crime_incidents_nearby: number;
  collisions_nearby: number;
  delay_history: { date: string; avg_delay: number | null; n: number }[];
  routes: { route_id: string; route_short_name: string; route_long_name: string; route_color: string }[];
  departures: { departure_time: string; route_id: string; route_short_name: string; trip_headsign: string | null }[];
  nearby_incidents: { incident_type: string; severity: number; date: string | null; distance_m: number }[];
}

interface Props { stopId: string | null; onClose: () => void; }

function fmt(n: number | null | undefined, dec = 0) {
  if (n == null || isNaN(Number(n))) return "—";
  return Number(n).toFixed(dec);
}

export const StopDrawer: React.FC<Props> = ({ stopId, onClose }) => {
  const [detail, setDetail] = useState<StopDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!stopId) { setDetail(null); return; }
    setLoading(true);
    axios.get(`${API_BASE}/stops/${encodeURIComponent(stopId)}`, { headers: h() })
      .then(r => setDetail(r.data))
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [stopId]);

  if (!stopId) return null;

  const maxDelay = detail ? Math.max(...detail.delay_history.map(d => d.avg_delay ?? 0), 1) : 1;
  const safetyRisk = (s: number) => s > 8 ? "severe" : s > 5 ? "moderate" : s > 2 ? "minor" : "on-time";

  return (
    <div className={`stop-drawer ${stopId ? "stop-drawer--open" : ""}`}>
      <div className="stop-drawer-header">
        <div className="stop-drawer-title">
          {loading ? "Loading…" : (detail?.stop_name ?? `Stop ${stopId}`)}
          {detail?.stop_code && <span className="stop-drawer-code">#{detail.stop_code}</span>}
        </div>
        <button className="stop-drawer-close" onClick={onClose} aria-label="Close">✕</button>
      </div>

      {loading && <div className="stop-drawer-spinner" />}

      {!loading && detail && (
        <div className="stop-drawer-body">
          {/* Safety score */}
          <section className="drawer-section">
            <h4 className="drawer-section-title">Safety</h4>
            <div className="drawer-kpi-row">
              <div className="drawer-kpi">
                <span className="drawer-kpi-val">{fmt(detail.safety_score, 1)}</span>
                <span className="drawer-kpi-lbl">Risk score</span>
              </div>
              <div className="drawer-kpi">
                <span className="drawer-kpi-val">{detail.crime_incidents_nearby}</span>
                <span className="drawer-kpi-lbl">Crime nearby</span>
              </div>
              <div className="drawer-kpi">
                <span className="drawer-kpi-val">{detail.collisions_nearby}</span>
                <span className="drawer-kpi-lbl">Collisions</span>
              </div>
            </div>
            <div className={`delay-badge delay-badge--${safetyRisk(detail.safety_score)}`} style={{display:"inline-block",marginTop:"0.35rem"}}>
              {detail.safety_score > 8 ? "High risk" : detail.safety_score > 5 ? "Elevated" : detail.safety_score > 2 ? "Moderate" : "Low risk"}
            </div>
          </section>

          {/* Delay history sparkline */}
          {detail.delay_history.length > 0 && (
            <section className="drawer-section">
              <h4 className="drawer-section-title">Delay History (last 14 days)</h4>
              <div className="delay-sparkline">
                {[...detail.delay_history].reverse().map((d) => {
                  const barH = Math.max(4, Math.round(((d.avg_delay ?? 0) / maxDelay) * 44));
                  const color = (d.avg_delay ?? 0) < 60 ? "#22c55e" : (d.avg_delay ?? 0) < 180 ? "#f97316" : "#ef4444";
                  return (
                    <div key={d.date} className="sparkline-bar-wrap" title={`${d.date}: ${d.avg_delay ?? 0}s avg delay`}>
                      <div className="sparkline-bar" style={{ height: `${barH}px`, background: color }} />
                      <span className="sparkline-date">{d.date.slice(5)}</span>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* Routes serving */}
          {detail.routes.length > 0 && (
            <section className="drawer-section">
              <h4 className="drawer-section-title">Routes Serving This Stop</h4>
              <div className="drawer-routes">
                {detail.routes.map(r => (
                  <span key={r.route_id} className="route-chip"
                    style={{
                      background: `#${r.route_color || "3b82f6"}22`,
                      borderColor: `#${r.route_color || "3b82f6"}88`,
                      color: `#${r.route_color || "93c5fd"}`,
                    }}>
                    {r.route_short_name || r.route_id}
                  </span>
                ))}
              </div>
            </section>
          )}

          {/* Scheduled departures */}
          {detail.departures.length > 0 && (
            <section className="drawer-section">
              <h4 className="drawer-section-title">Scheduled Departures</h4>
              <ul className="drawer-departures">
                {detail.departures.map((d, i) => (
                  <li key={i} className="departure-row">
                    <span className="departure-time">{d.departure_time}</span>
                    <span className="departure-route">Rt {d.route_short_name || d.route_id}</span>
                    <span className="departure-headsign">{d.trip_headsign ?? ""}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* Nearby incidents */}
          {detail.nearby_incidents.length > 0 && (
            <section className="drawer-section">
              <h4 className="drawer-section-title">Nearby Incidents (within 300 m)</h4>
              <ul className="drawer-incidents">
                {detail.nearby_incidents.map((inc, i) => (
                  <li key={i} className="incident-row">
                    <span className={`incident-type incident-type--${inc.incident_type}`}>{inc.incident_type}</span>
                    <span className="incident-dist">{inc.distance_m}m</span>
                    <span className="incident-date">{inc.date ?? "—"}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {detail.nearby_incidents.length === 0 && detail.delay_history.length === 0 && (
            <p className="drawer-empty">No incident or delay data for this stop.</p>
          )}
        </div>
      )}

      {!loading && !detail && stopId && (
        <p className="drawer-empty">Could not load stop details.</p>
      )}
    </div>
  );
};

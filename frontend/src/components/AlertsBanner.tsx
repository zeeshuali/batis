import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import { agencyColor, agencyName } from "../lib/agencies";
import { useAgencies } from "../context/AgenciesContext";

interface Alert { id: string; header: string; effect: string; cause: string; agency_id: string | null; }

export const AlertsBanner: React.FC = () => {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const { byId: agenciesById } = useAgencies();

  useEffect(() => {
    const fetchAlerts = () => {
      api
        .get(`/alerts`)
        .then(r => setAlerts(Array.isArray(r.data) ? r.data : []))
        .catch(err => {
          if (err?.response?.status !== 401) {
            console.warn("[AlertsBanner] Failed to fetch alerts:", err?.message ?? err);
          }
        });
    };
    fetchAlerts();
    const id = setInterval(fetchAlerts, 5 * 60 * 1000);
    return () => clearInterval(id);
  }, []);

  const visible = alerts.filter(a => !dismissed.has(a.id));
  if (visible.length === 0) return null;

  return (
    <div className="alerts-banner">
      {visible.slice(0, 3).map(a => (
        <div key={a.id} className="alert-item">
          <span className="alert-icon">⚠</span>
          {a.agency_id && (
            <span
              className="alert-agency-badge"
              style={{ background: agencyColor(a.agency_id) + "33", borderColor: agencyColor(a.agency_id), color: agencyColor(a.agency_id) }}
              title={agencyName(a.agency_id, agenciesById)}
            >
              {a.agency_id}
            </span>
          )}
          <span className="alert-text">{a.header}</span>
          <span className="alert-effect">{a.effect}</span>
          <button className="alert-dismiss" onClick={() => setDismissed(prev => new Set([...prev, a.id]))}>✕</button>
        </div>
      ))}
    </div>
  );
};

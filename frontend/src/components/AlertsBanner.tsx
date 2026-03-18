import React, { useEffect, useState } from "react";
import axios from "axios";

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string) || "http://localhost:8000";

interface Alert { id: string; header: string; effect: string; cause: string; }

export const AlertsBanner: React.FC = () => {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  useEffect(() => {
    const fetch = () => {
      axios.get(`${API_BASE}/alerts`).then(r => setAlerts(r.data)).catch(() => {});
    };
    fetch();
    const id = setInterval(fetch, 5 * 60 * 1000);
    return () => clearInterval(id);
  }, []);

  const visible = alerts.filter(a => !dismissed.has(a.id));
  if (visible.length === 0) return null;

  return (
    <div className="alerts-banner">
      {visible.slice(0, 3).map(a => (
        <div key={a.id} className="alert-item">
          <span className="alert-icon">⚠</span>
          <span className="alert-text">{a.header}</span>
          <span className="alert-effect">{a.effect}</span>
          <button className="alert-dismiss" onClick={() => setDismissed(prev => new Set([...prev, a.id]))}>✕</button>
        </div>
      ))}
    </div>
  );
};

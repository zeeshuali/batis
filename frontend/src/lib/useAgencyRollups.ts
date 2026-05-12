import { useEffect, useState } from "react";
import { api } from "../lib/api";

export interface AgencyRollup {
  agency_id:     string;
  agency_name:   string | null;
  routes_count:  number | null;
  stops_count:   number | null;
  otp_7d:        number | null;   // 0..100
  avg_delay_7d:  number | null;   // seconds
  alerts_active: number | null;
  hot_stops:     number | null;
}

/** Fetch the per-agency KPI rollup for a date window.  Mirrors the inline
 *  fetch pattern in Overview.tsx so a future cleanup can collapse them. */
export function useAgencyRollups(startDate: string, endDate: string) {
  const [rows, setRows]       = useState<AgencyRollup[]>([]);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(null);
    api.get<AgencyRollup[]>("/agencies/rollup", { params: { start_date: startDate, end_date: endDate } })
      .then(res => { if (!cancelled) setRows(Array.isArray(res.data) ? res.data : []); })
      .catch(err => { if (!cancelled) setError(err?.message ?? "Failed to load"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [startDate, endDate]);

  return { rows, loading, error };
}

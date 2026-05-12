import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { api, apiHeaders } from "../lib/api";
import type { AgencyMeta } from "../lib/agencies";

interface AgenciesApi {
  agencies: AgencyMeta[];
  byId: Record<string, AgencyMeta>;
  loading: boolean;
  error: string | null;
}

const AgenciesContext = createContext<AgenciesApi | null>(null);

export const AgenciesProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [agencies, setAgencies] = useState<AgencyMeta[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.get<AgencyMeta[]>("/agencies", { headers: apiHeaders() })
      .then(res => {
        if (cancelled) return;
        setAgencies(Array.isArray(res.data) ? res.data : []);
        setError(null);
      })
      .catch(err => {
        if (cancelled) return;
        setError(err?.message ?? "Failed to load agencies");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const byId = useMemo(() => {
    const out: Record<string, AgencyMeta> = {};
    for (const a of agencies) out[a.agency_id] = a;
    return out;
  }, [agencies]);

  const value = useMemo<AgenciesApi>(
    () => ({ agencies, byId, loading, error }),
    [agencies, byId, loading, error],
  );

  return <AgenciesContext.Provider value={value}>{children}</AgenciesContext.Provider>;
};

export function useAgencies(): AgenciesApi {
  const v = useContext(AgenciesContext);
  if (!v) throw new Error("useAgencies must be used inside an AgenciesProvider");
  return v;
}

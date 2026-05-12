import React, { createContext, useCallback, useContext, useMemo, useState } from "react";
import { ALL_AGENCY_IDS } from "../lib/agencies";

export interface Filters {
  startDate: string;       // YYYY-MM-DD
  endDate:   string;       // YYYY-MM-DD
  agencies:  string[];     // e.g. ["AC", "BA"]
  search:    string;       // free-text route search
}

interface FilterApi {
  filters: Filters;
  setDateRange: (start: string, end: string) => void;
  setAgencies:  (ids: string[]) => void;
  setSearch:    (q: string) => void;
}

const FilterContext = createContext<FilterApi | null>(null);

function isoDate(offsetDays = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}

export const FilterProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [startDate, setStartDate] = useState<string>(() => isoDate(-7));
  const [endDate,   setEndDate]   = useState<string>(() => isoDate(0));
  const [agencies,  setAgenciesState] = useState<string[]>(() => [...ALL_AGENCY_IDS]);
  const [search,    setSearchState]   = useState<string>("");

  const setDateRange = useCallback((s: string, e: string) => {
    setStartDate(s);
    setEndDate(e);
  }, []);

  const setAgencies = useCallback((ids: string[]) => {
    setAgenciesState(ids.length > 0 ? ids : [...ALL_AGENCY_IDS]);
  }, []);

  const setSearch = useCallback((q: string) => setSearchState(q), []);

  const value = useMemo<FilterApi>(
    () => ({ filters: { startDate, endDate, agencies, search }, setDateRange, setAgencies, setSearch }),
    [startDate, endDate, agencies, search, setDateRange, setAgencies, setSearch]
  );

  return <FilterContext.Provider value={value}>{children}</FilterContext.Provider>;
};

export function useFilters(): FilterApi {
  const v = useContext(FilterContext);
  if (!v) throw new Error("useFilters must be used inside a FilterProvider");
  return v;
}

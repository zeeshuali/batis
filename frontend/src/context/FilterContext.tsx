import React, { createContext, useCallback, useContext, useMemo } from "react";
import { useUrlState } from "../lib/useUrlState";

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
  const { state, setState } = useUrlState();

  const startDate = state.from ?? isoDate(-7);
  const endDate   = state.to   ?? isoDate(0);
  // `[]` is the canonical "all agencies" value — FilterBar passes through
  // whatever the user has actively toggled; "all selected" is elided to null
  // in the URL by setAgencies below.
  const agencies  = state.agencies ?? [];
  const search    = state.q ?? "";

  const setDateRange = useCallback((s: string, e: string) => {
    setState({ ...state, from: s, to: e });
  }, [state, setState]);

  const setAgencies = useCallback((ids: string[]) => {
    // "[] means all" — elide the empty value from the URL so the share link
    // doesn't carry a vestigial `agencies=` parameter.
    setState({ ...state, agencies: ids.length === 0 ? null : ids });
  }, [state, setState]);

  const setSearch = useCallback((q: string) => {
    setState({ ...state, q: q || null });
  }, [state, setState]);

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

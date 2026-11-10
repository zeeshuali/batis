import { useCallback, useEffect, useState } from "react";

export type SectionKey = "overview" | "operations" | "network" | "equity" | "benchmarks" | "agency" | "planning" | "status";
const SECTION_KEYS: readonly SectionKey[] = ["overview", "operations", "network", "equity", "benchmarks", "agency", "planning", "status"];

export interface UrlState {
  section:    SectionKey;
  /** Sub-page within the active section.  Only "planning" uses this today
   *  (sub = "diagnostics" | "coverage" | "regional" | "workbench" |
   *  "scenarios"); other sections ignore it. */
  subsection: string | null;
  from:       string | null;    // YYYY-MM-DD
  to:         string | null;
  agencies:   string[] | null;  // null means "all"
  q:          string | null;    // search
  agency_id:  string | null;    // selected agency for the "agency" drill-down section
}

const DEFAULT_STATE: UrlState = {
  section: "overview",
  subsection: null,
  from: null, to: null,
  agencies: null, q: null,
  agency_id: null,
};

export function parseHash(hash: string): UrlState {
  const raw = hash.replace(/^#/, "");
  const [sectionPart, queryPart] = raw.split("?");
  const section: SectionKey = (SECTION_KEYS as readonly string[]).includes(sectionPart)
    ? (sectionPart as SectionKey) : "overview";
  const params = new URLSearchParams(queryPart ?? "");
  const ag = params.get("agencies");
  return {
    section,
    subsection: params.get("sub")  || null,
    from:       params.get("from") || null,
    to:         params.get("to")   || null,
    agencies:   ag ? ag.split(",").filter(Boolean) : null,
    q:          params.get("q")    || null,
    agency_id:  params.get("id")   || null,
  };
}

export function encodeHash(state: UrlState): string {
  const params = new URLSearchParams();
  if (state.subsection)        params.set("sub", state.subsection);
  if (state.from)              params.set("from", state.from);
  if (state.to)                params.set("to", state.to);
  if (state.agencies && state.agencies.length > 0) params.set("agencies", state.agencies.join(","));
  if (state.q)                 params.set("q", state.q);
  if (state.agency_id)         params.set("id", state.agency_id);
  const query = params.toString();
  // URLSearchParams percent-encodes commas; restore them for readability.
  const pretty = query.replace(/%2C/g, ",");
  return pretty ? `#${state.section}?${pretty}` : `#${state.section}`;
}

export function useUrlState() {
  const [state, setStateImpl] = useState<UrlState>(() => parseHash(window.location.hash));

  useEffect(() => {
    const onHashChange = () => setStateImpl(parseHash(window.location.hash));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const setState = useCallback((next: UrlState) => {
    const hash = encodeHash(next);
    if (hash !== window.location.hash) {
      // Writing window.location.hash fires `hashchange` synchronously, and
      // the listener above will then call setStateImpl. Don't call it
      // directly here or we double-render on every filter change.
      window.location.hash = hash;
    } else {
      // No hash change means no listener fires; update state directly so
      // re-setting an unchanged state still works (e.g. forcing a refetch).
      setStateImpl(next);
    }
  }, []);

  return { state, setState, defaults: DEFAULT_STATE };
}

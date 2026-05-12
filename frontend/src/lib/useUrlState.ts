import { useCallback, useEffect, useState } from "react";

export type SectionKey = "overview" | "operations" | "network" | "equity" | "benchmarks";
const SECTION_KEYS: readonly SectionKey[] = ["overview", "operations", "network", "equity", "benchmarks"];

export interface UrlState {
  section:  SectionKey;
  from:     string | null;     // YYYY-MM-DD
  to:       string | null;
  agencies: string[] | null;   // null means "all"
  q:        string | null;     // search
}

const DEFAULT_STATE: UrlState = { section: "overview", from: null, to: null, agencies: null, q: null };

export function parseHash(hash: string): UrlState {
  const raw = hash.replace(/^#/, "");
  const [sectionPart, queryPart] = raw.split("?");
  const section: SectionKey = (SECTION_KEYS as readonly string[]).includes(sectionPart)
    ? (sectionPart as SectionKey) : "overview";
  const params = new URLSearchParams(queryPart ?? "");
  const ag = params.get("agencies");
  return {
    section,
    from:     params.get("from") || null,
    to:       params.get("to")   || null,
    agencies: ag ? ag.split(",").filter(Boolean) : null,
    q:        params.get("q")    || null,
  };
}

export function encodeHash(state: UrlState): string {
  const params = new URLSearchParams();
  if (state.from)              params.set("from", state.from);
  if (state.to)                params.set("to", state.to);
  if (state.agencies && state.agencies.length > 0) params.set("agencies", state.agencies.join(","));
  if (state.q)                 params.set("q", state.q);
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
    if (hash !== window.location.hash) window.location.hash = hash;
    setStateImpl(next);
  }, []);

  return { state, setState, defaults: DEFAULT_STATE };
}

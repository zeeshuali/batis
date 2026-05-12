import { useCallback, useEffect, useState } from "react";

export type SectionKey = "overview" | "operations" | "network" | "equity" | "benchmarks";

const SECTION_KEYS: readonly SectionKey[] = [
  "overview", "operations", "network", "equity", "benchmarks",
];

function readHash(): SectionKey {
  const raw = window.location.hash.replace(/^#/, "");
  return (SECTION_KEYS as readonly string[]).includes(raw) ? (raw as SectionKey) : "overview";
}

export function useSectionRoute() {
  const [section, setSectionState] = useState<SectionKey>(() => readHash());

  useEffect(() => {
    const onHashChange = () => setSectionState(readHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const setSection = useCallback((next: SectionKey) => {
    window.location.hash = `#${next}`;
    setSectionState(next);
  }, []);

  return { section, setSection };
}

import React from "react";
import { useUrlState } from "../lib/useUrlState";
import { Diagnostics } from "./planning/Diagnostics";
import { Coverage }    from "./planning/Coverage";
import { Regional }    from "./planning/Regional";
import { Workbench }   from "./planning/Workbench";
import { Scenarios }   from "./planning/Scenarios";
import { Fares }       from "./planning/Fares";
import "./sections.css";
import "./planning/planning.css";

type SubKey = "diagnostics" | "coverage" | "regional" | "workbench" | "scenarios" | "fares";
const SUBS: { key: SubKey; label: string; persona: string }[] = [
  { key: "diagnostics", label: "Diagnostics", persona: "Agency service planner" },
  { key: "coverage",    label: "Coverage",    persona: "City / municipal planner" },
  { key: "regional",    label: "Regional",    persona: "MPO / regional planner" },
  { key: "workbench",   label: "Workbench",   persona: "Click-to-inspect a corridor" },
  { key: "scenarios",   label: "Scenarios",   persona: "What-if simulation" },
  { key: "fares",       label: "Fares",       persona: "Corridor fare burden + equity overlay" },
];

const DEFAULT_SUB: SubKey = "diagnostics";

function asSubKey(s: string | null | undefined): SubKey {
  return SUBS.some(x => x.key === s) ? (s as SubKey) : DEFAULT_SUB;
}

export const Planning: React.FC = () => {
  const { state, setState } = useUrlState();
  const active = asSubKey(state.subsection);
  const setActive = (key: SubKey) =>
    setState({ ...state, section: "planning", subsection: key });

  const persona = SUBS.find(s => s.key === active)?.persona ?? "";

  return (
    <div className="planning">
      <div className="planning__subnav" role="tablist">
        {SUBS.map(s => (
          <button
            key={s.key}
            type="button"
            role="tab"
            aria-selected={active === s.key}
            className={`planning__subnav-tab ${active === s.key ? "planning__subnav-tab--active" : ""}`}
            onClick={() => setActive(s.key)}
          >
            {s.label}
          </button>
        ))}
        <span className="planning__persona">{persona}</span>
      </div>

      <div className="planning__body">
        {active === "diagnostics" && <Diagnostics />}
        {active === "coverage"    && <Coverage />}
        {active === "regional"    && <Regional />}
        {active === "workbench"   && <Workbench />}
        {active === "scenarios"   && <Scenarios />}
        {active === "fares"       && <Fares />}
      </div>
    </div>
  );
};

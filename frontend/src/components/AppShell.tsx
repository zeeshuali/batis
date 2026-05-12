import React, { useState } from "react";
import { FilterBar } from "./FilterBar";
import { Overview } from "../sections/Overview";
import { Operations } from "../sections/Operations";
import { Network } from "../sections/Network";
import { EquitySafety } from "../sections/EquitySafety";
import { BenchmarksDrift } from "../sections/BenchmarksDrift";
import "../design/shell.css";

export type SectionKey = "overview" | "operations" | "network" | "equity" | "benchmarks";

const TABS: { key: SectionKey; label: string }[] = [
  { key: "overview",   label: "Overview"          },
  { key: "operations", label: "Operations"        },
  { key: "network",    label: "Network"           },
  { key: "equity",     label: "Equity & Safety"   },
  { key: "benchmarks", label: "Benchmarks & Drift"},
];

export const AppShell: React.FC = () => {
  const [active, setActive] = useState<SectionKey>("overview");

  return (
    <div className="shell" data-theme="dark">
      <header className="shell-header">
        <span className="shell-header__brand">BATIS</span>
        <nav className="shell-nav" role="tablist">
          {TABS.map(t => (
            <button
              key={t.key}
              role="tab"
              aria-selected={active === t.key}
              className={`shell-nav__tab ${active === t.key ? "shell-nav__tab--active" : ""}`}
              onClick={() => setActive(t.key)}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      <FilterBar />

      <main className="shell-main">
        {active === "overview"   && <Overview />}
        {active === "operations" && <Operations />}
        {active === "network"    && <Network />}
        {active === "equity"     && <EquitySafety />}
        {active === "benchmarks" && <BenchmarksDrift />}
      </main>

      <aside className="shell-rail">
        <div className="shell-rail__placeholder">Ask BATIS — coming in Plan 1c</div>
      </aside>
    </div>
  );
};

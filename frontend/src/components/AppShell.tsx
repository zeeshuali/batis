import React from "react";
import { FilterBar } from "./FilterBar";
import { AlertsBanner } from "./AlertsBanner";
import { StopDrawer } from "./StopDrawer";
import { Overview } from "../sections/Overview";
import { Operations } from "../sections/Operations";
import { Network } from "../sections/Network";
import { EquitySafety } from "../sections/EquitySafety";
import { BenchmarksDrift } from "../sections/BenchmarksDrift";
import { useTheme } from "../context/ThemeContext";
import { useSectionRoute, type SectionKey } from "../lib/useSectionRoute";
import "../design/shell.css";

export type { SectionKey } from "../lib/useSectionRoute";

const TABS: { key: SectionKey; label: string }[] = [
  { key: "overview",   label: "Overview"          },
  { key: "operations", label: "Operations"        },
  { key: "network",    label: "Network"           },
  { key: "equity",     label: "Equity & Safety"   },
  { key: "benchmarks", label: "Benchmarks & Drift"},
];

export const AppShell: React.FC = () => {
  const { section: active, setSection: setActive } = useSectionRoute();
  const { theme, toggle } = useTheme();

  return (
    <div className="shell">
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
        <button
          type="button"
          className="shell-header__theme-toggle"
          onClick={toggle}
          aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          title={theme === "dark" ? "Switch to light" : "Switch to dark"}
        >
          {theme === "dark" ? "☀" : "🌙"}
        </button>
      </header>

      <div className="shell-alerts">
        <AlertsBanner />
      </div>

      <FilterBar />

      <main className="shell-main">
        {active === "overview"   && <Overview />}
        {active === "operations" && <Operations />}
        {active === "network"    && <Network />}
        {active === "equity"     && <EquitySafety />}
        {active === "benchmarks" && <BenchmarksDrift />}
      </main>

      <aside className="shell-rail">
        <div className="shell-rail__placeholder">Ask BATIS — coming in Phase 2</div>
      </aside>

      <StopDrawer />
    </div>
  );
};

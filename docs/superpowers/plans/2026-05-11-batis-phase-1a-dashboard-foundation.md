# BATIS Phase 1a — Dashboard Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the BATIS 2.0 shell — five-section nav, design system tokens, global filter bar, filter + selection contexts, extracted primitives, and a fully-built Overview section — without breaking the existing map/drawer/alerts components.

**Architecture:** A new `AppShell` component wraps everything; `FilterContext` and `SelectionContext` providers replace the dozen-prop drilldown in the current `App.tsx`; visual primitives (`KpiCard`, `DataList`, `TrendChart`, `BarChart`, `Spinner`, `EmptyState`) move out of `Sidebar.tsx` into `components/primitives/`; five section components (`Overview`, `Operations`, `Network`, `EquitySafety`, `BenchmarksDrift`) replace the 14-tab `Sidebar` router. Overview is the only section with real content in 1a — the other four ship as stubs so the nav is testable end-to-end. `MapView.tsx`, `StopDrawer.tsx`, `AlertsBanner.tsx`, `BenchmarkPanel.tsx`, and `AiAssistant.tsx` are unchanged and rendered inside the new shell unchanged. The current 2,137-line `styles.css` is left in place; new styles live in `design/` and `sections/` as scoped CSS files.

**Tech Stack:** React 18, TypeScript 5.6, Vite 5, Mapbox GL JS 3, Recharts 3, Axios. Phase 1a adds Vitest + @testing-library/react for component tests. No new runtime deps; no backend changes.

---

## Pre-flight: what to know before starting

This plan operates in `/home/mza/projects/batis` on branch `main`, with the BATIS dockerized stack running per `docker-compose.yml`. Frontend lives in `frontend/`; tests will be invoked via `npm test` from that directory.

The 5-section nav replaces 14 tabs from the current `App.tsx` (lines 60–93):

| New section | Job it answers | Absorbs today's tabs |
|---|---|---|
| Overview | "What needs my attention today?" | (new — no current equivalent) |
| Operations | "How is the network performing now and over the past week?" | Reliability, Bunching, Live Vehicles, Crowding, Comparison |
| Network | "What does the network look like, and where does it serve?" | Routes, Coverage, Trip Planner |
| Equity & Safety | "Where is service delivery failing?" | Equity, Safety |
| Benchmarks & Drift | "How do agencies compare?" | Benchmarks, Demand, Traffic |

**Plan 1a builds Overview only.** Operations / Network / Equity & Safety / Benchmarks & Drift get placeholder shells in this plan; their real content is Plan 1b. This is deliberate: foundation must work end-to-end before populating four more sections.

The existing `frontend/src/components/Sidebar.tsx` (1,862 lines) stays in place for now — it isn't rendered by `App.tsx` after this plan, but the file is kept so its KPI/chart logic remains a reference for Plan 1b's section content extraction. **Plan 1a does not delete `Sidebar.tsx`.**

Existing styles in `frontend/src/styles.css` (2,137 lines) are kept untouched on disk, but **not imported by main.tsx in Plan 1a**. The legacy file defines class names (`.kpi-card`, `.agency-pill`, etc.) that would otherwise collide with the new primitives in `components/primitives/`. Plan 1b re-imports it when `MapView` and `StopDrawer` are reintroduced into the shell. The `mapbox-gl/dist/mapbox-gl.css` import is similarly dropped in 1a (no map is rendered) and restored in 1b.

---

## File Structure

**New files (all created in this plan):**

- `frontend/vitest.config.ts` — Vitest config
- `frontend/src/setupTests.ts` — Testing Library / jest-dom setup
- `frontend/src/design/tokens.css` — CSS custom properties (color, space, type, radius, shadow)
- `frontend/src/design/tokens.ts` — TS mirrors of the tokens for in-component use
- `frontend/src/design/shell.css` — base reset + AppShell grid layout
- `frontend/src/context/FilterContext.tsx` — global filter provider + hook
- `frontend/src/context/FilterContext.test.tsx`
- `frontend/src/context/SelectionContext.tsx` — entity selection provider + hook
- `frontend/src/context/SelectionContext.test.tsx`
- `frontend/src/components/primitives/KpiCard.tsx`
- `frontend/src/components/primitives/KpiCard.test.tsx`
- `frontend/src/components/primitives/DataList.tsx`
- `frontend/src/components/primitives/DataList.test.tsx`
- `frontend/src/components/primitives/TrendChart.tsx`
- `frontend/src/components/primitives/BarChart.tsx`
- `frontend/src/components/primitives/Spinner.tsx`
- `frontend/src/components/primitives/EmptyState.tsx`
- `frontend/src/components/primitives/primitives.css`
- `frontend/src/components/primitives/index.ts`
- `frontend/src/components/AppShell.tsx` — header + section nav + filter bar + main area + agent-rail placeholder
- `frontend/src/components/AppShell.test.tsx`
- `frontend/src/components/FilterBar.tsx`
- `frontend/src/components/FilterBar.test.tsx`
- `frontend/src/sections/Overview.tsx` — real content
- `frontend/src/sections/Overview.test.tsx`
- `frontend/src/sections/Operations.tsx` — stub
- `frontend/src/sections/Network.tsx` — stub
- `frontend/src/sections/EquitySafety.tsx` — stub
- `frontend/src/sections/BenchmarksDrift.tsx` — stub
- `frontend/src/sections/sections.css`
- `frontend/src/lib/api.ts` — shared axios helpers (`apiHeaders`, `API_BASE`)

**Modified files:**

- `frontend/package.json` — add Vitest + Testing Library devDeps, add `test` script
- `frontend/src/main.tsx` — import the new tokens.css + shell.css before mapbox/styles
- `frontend/src/App.tsx` — replace 14-tab nav with `AppShell` + `FilterProvider` + `SelectionProvider`; pass section-aware props to the still-existing `MapView` and `StopDrawer`

**Untouched:**

- `frontend/src/components/MapView.tsx` — kept as-is; Plan 1b refactors its layer dispatch
- `frontend/src/components/Sidebar.tsx` — kept as a reference for Plan 1b; no longer rendered after this plan
- `frontend/src/components/StopDrawer.tsx`, `AlertsBanner.tsx`, `BenchmarkPanel.tsx`, `AiAssistant.tsx`
- `frontend/src/styles.css` — left alone
- `frontend/src/lib/agencies.ts`

---

## Task 1: Add Vitest + Testing Library

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/src/setupTests.ts`
- Create: `frontend/src/sample.test.ts`

- [ ] **Step 1: Add devDependencies**

From `frontend/`:

```bash
npm install --save-dev \
  vitest@^2.1.0 \
  @vitest/ui@^2.1.0 \
  @testing-library/react@^16.0.0 \
  @testing-library/jest-dom@^6.5.0 \
  @testing-library/user-event@^14.5.2 \
  jsdom@^25.0.0
```

Expected: `package.json` now lists those in `devDependencies`. `package-lock.json` updated.

- [ ] **Step 2: Add a `test` script to `package.json`**

Edit `frontend/package.json`, change the `scripts` block to add `test` and `test:run`:

```json
"scripts": {
  "dev": "vite",
  "build": "vite build",
  "preview": "vite preview",
  "test": "vitest",
  "test:run": "vitest run",
  "lint": "echo \"no lint configured\""
}
```

- [ ] **Step 3: Create `frontend/vitest.config.ts`**

```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react-swc";

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
    css: false,
  },
});
```

- [ ] **Step 4: Create `frontend/src/setupTests.ts`**

```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 5: Create a sample test to prove the infra works**

`frontend/src/sample.test.ts`:

```ts
import { describe, it, expect } from "vitest";

describe("sample", () => {
  it("sums two numbers", () => {
    expect(1 + 1).toBe(2);
  });
});
```

- [ ] **Step 6: Run the test suite**

From `frontend/`:

```bash
npm run test:run
```

Expected: exit code 0, output ends with `1 passed`.

- [ ] **Step 7: Delete the sample test (no longer needed)**

```bash
rm src/sample.test.ts
```

- [ ] **Step 8: Commit**

From the repo root:

```bash
git add frontend/package.json frontend/package-lock.json frontend/vitest.config.ts frontend/src/setupTests.ts
git commit -m "$(cat <<'EOF'
Add Vitest + Testing Library to the frontend

Adds Vitest, @testing-library/react, @testing-library/jest-dom,
@testing-library/user-event, and jsdom as devDependencies, with a
vitest config that points at the React SWC plugin and a setup file
that wires jest-dom matchers. Adds `test` (watch) and `test:run`
(one-shot) npm scripts. Phase 1a tasks land their tests against this
substrate.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Design tokens (CSS variables + TS mirror)

**Files:**
- Create: `frontend/src/design/tokens.css`
- Create: `frontend/src/design/tokens.ts`

These tokens are the single source of truth for color, spacing, typography, radius, and shadow. CSS files use the custom properties; TS components use the typed mirror.

- [ ] **Step 1: Create `frontend/src/design/tokens.css`**

```css
/* BATIS 2.0 design tokens.
   All colors, spacing, type, radius, shadow values live here.
   Light + dark parity via [data-theme="light"] / [data-theme="dark"].
*/

:root,
:root[data-theme="dark"] {
  /* Surface */
  --color-bg-0:     #0b0f17;
  --color-bg-1:     #111826;
  --color-bg-2:     #1a2334;
  --color-border:   #283448;
  --color-overlay:  rgba(11, 15, 23, 0.72);

  /* Foreground */
  --color-fg-0:     #f1f5f9;
  --color-fg-1:     #cbd5e1;
  --color-fg-2:     #94a3b8;
  --color-fg-3:     #64748b;

  /* Brand + semantic */
  --color-brand:    #3b82f6;
  --color-brand-2:  #60a5fa;
  --color-success:  #22c55e;
  --color-warn:     #f59e0b;
  --color-critical: #ef4444;
  --color-info:     #06b6d4;

  /* Accent for selections */
  --color-accent:   #a78bfa;
}

:root[data-theme="light"] {
  --color-bg-0:     #ffffff;
  --color-bg-1:     #f8fafc;
  --color-bg-2:     #f1f5f9;
  --color-border:   #e2e8f0;
  --color-overlay:  rgba(255, 255, 255, 0.85);

  --color-fg-0:     #0f172a;
  --color-fg-1:     #334155;
  --color-fg-2:     #475569;
  --color-fg-3:     #64748b;

  --color-brand:    #2563eb;
  --color-brand-2:  #3b82f6;
  --color-success:  #16a34a;
  --color-warn:     #d97706;
  --color-critical: #dc2626;
  --color-info:     #0891b2;

  --color-accent:   #7c3aed;
}

:root {
  /* Spacing (4px scale) */
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-5: 1.5rem;
  --space-6: 2rem;
  --space-8: 3rem;

  /* Radii */
  --radius-1: 4px;
  --radius-2: 8px;
  --radius-3: 12px;
  --radius-pill: 999px;

  /* Type scale */
  --font-sans: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", system-ui, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;

  --text-xs:   0.75rem;
  --text-sm:   0.875rem;
  --text-base: 1rem;
  --text-lg:   1.125rem;
  --text-xl:   1.25rem;
  --text-2xl:  1.5rem;
  --text-3xl:  1.875rem;

  --leading-tight: 1.2;
  --leading-base:  1.5;

  /* Shadows */
  --shadow-1: 0 1px 2px rgba(0, 0, 0, 0.06), 0 1px 1px rgba(0, 0, 0, 0.04);
  --shadow-2: 0 4px 8px rgba(0, 0, 0, 0.08), 0 2px 4px rgba(0, 0, 0, 0.04);
  --shadow-3: 0 10px 24px rgba(0, 0, 0, 0.12), 0 4px 8px rgba(0, 0, 0, 0.06);

  /* Layout */
  --shell-header-h:  56px;
  --shell-filterbar-h: 52px;
  --shell-rail-w:    320px;
}
```

- [ ] **Step 2: Create `frontend/src/design/tokens.ts`**

```ts
/** Typed mirror of CSS tokens. Use when a component needs a token at
 *  the JS layer (e.g. inline style props, Recharts color props).
 *  CSS files should use the CSS custom properties directly.
 */

export const space = {
  s1: "0.25rem",
  s2: "0.5rem",
  s3: "0.75rem",
  s4: "1rem",
  s5: "1.5rem",
  s6: "2rem",
  s8: "3rem",
} as const;

export const radius = {
  r1: 4,
  r2: 8,
  r3: 12,
  pill: 999,
} as const;

export const text = {
  xs: "0.75rem",
  sm: "0.875rem",
  base: "1rem",
  lg: "1.125rem",
  xl: "1.25rem",
  xl2: "1.5rem",
  xl3: "1.875rem",
} as const;

/** Semantic color names. Maps to CSS variables; use `var(--color-fg-1)` in
 *  CSS and these constants in JS-driven contexts. Values are dark-theme
 *  defaults; CSS variable lookup is preferred for theme-aware reads.
 */
export const semanticColors = {
  brand:     "#3b82f6",
  success:   "#22c55e",
  warn:      "#f59e0b",
  critical:  "#ef4444",
  info:      "#06b6d4",
  fg0:       "#f1f5f9",
  fg1:       "#cbd5e1",
  fg2:       "#94a3b8",
  fg3:       "#64748b",
  bg0:       "#0b0f17",
  bg1:       "#111826",
  bg2:       "#1a2334",
} as const;

export type SemanticColor = keyof typeof semanticColors;
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/design/
git commit -m "$(cat <<'EOF'
Add BATIS 2.0 design tokens (CSS variables + TS mirror)

Establishes a single source of truth for color, spacing, typography,
radius, and shadow values. Dark + light parity via data-theme on
:root. CSS files consume the variables directly; TS components import
the typed mirror in tokens.ts when they need a value at the JS layer
(Recharts stroke colors, inline styles). The existing 2,137-line
styles.css is untouched — Phase 1a's new components use these tokens,
the old components keep their legacy styles.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Shell base styles + reset

**Files:**
- Create: `frontend/src/design/shell.css`

- [ ] **Step 1: Create the shell stylesheet**

```css
@import "./tokens.css";

/* Reset */
*, *::before, *::after { box-sizing: border-box; }
html, body, #root { height: 100%; margin: 0; }

body {
  font-family: var(--font-sans);
  font-size: var(--text-base);
  line-height: var(--leading-base);
  color: var(--color-fg-0);
  background: var(--color-bg-0);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* AppShell grid */
.shell {
  display: grid;
  grid-template-rows:
    var(--shell-header-h)
    var(--shell-filterbar-h)
    1fr;
  grid-template-columns: 1fr var(--shell-rail-w);
  grid-template-areas:
    "header   header"
    "filter   filter"
    "main     rail";
  height: 100vh;
  width: 100vw;
}

.shell--rail-collapsed {
  grid-template-columns: 1fr 0;
}

.shell-header     { grid-area: header; }
.shell-filterbar  { grid-area: filter; }
.shell-main       { grid-area: main; overflow: auto; }
.shell-rail       { grid-area: rail; overflow: hidden; border-left: 1px solid var(--color-border); }

/* Header */
.shell-header {
  display: flex;
  align-items: center;
  gap: var(--space-5);
  padding: 0 var(--space-5);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-bg-1);
}

.shell-header__brand {
  font-size: var(--text-lg);
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--color-fg-0);
}

.shell-nav {
  display: flex;
  gap: var(--space-1);
  margin-left: auto;
}

.shell-nav__tab {
  appearance: none;
  border: 1px solid transparent;
  background: transparent;
  color: var(--color-fg-2);
  padding: var(--space-2) var(--space-3);
  font: inherit;
  font-size: var(--text-sm);
  border-radius: var(--radius-2);
  cursor: pointer;
  transition: color 120ms, background 120ms, border-color 120ms;
}

.shell-nav__tab:hover {
  color: var(--color-fg-0);
  background: var(--color-bg-2);
}

.shell-nav__tab--active {
  color: var(--color-fg-0);
  background: var(--color-bg-2);
  border-color: var(--color-border);
}

/* Filter bar */
.shell-filterbar {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: 0 var(--space-5);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-bg-1);
  font-size: var(--text-sm);
}

/* Agent rail placeholder */
.shell-rail__placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--color-fg-3);
  font-size: var(--text-sm);
  padding: var(--space-4);
  text-align: center;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/design/shell.css
git commit -m "$(cat <<'EOF'
Add base reset + AppShell grid layout

Defines the 3-row × 2-column shell grid: header, filter bar, then a
main area + agent rail at 320px. Adds the minimal CSS reset, body
typography from the tokens, and tab nav styles. The rail is laid out
even though Plan 1a only renders a placeholder there — Plan 1c will
mount the Agent inside.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: FilterContext

**Files:**
- Create: `frontend/src/context/FilterContext.tsx`
- Create: `frontend/src/context/FilterContext.test.tsx`

Holds the global filter state: date range, selected agencies, and a free-text route search. Defaults: last 7 days, all agencies, empty search.

- [ ] **Step 1: Write the failing test**

`frontend/src/context/FilterContext.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterProvider, useFilters } from "./FilterContext";

function Probe() {
  const { filters, setAgencies, setSearch, setDateRange } = useFilters();
  return (
    <div>
      <span data-testid="start">{filters.startDate}</span>
      <span data-testid="end">{filters.endDate}</span>
      <span data-testid="agencies">{filters.agencies.join(",")}</span>
      <span data-testid="search">{filters.search}</span>
      <button onClick={() => setAgencies(["AC", "BA"])}>set</button>
      <button onClick={() => setSearch("51B")}>search</button>
      <button onClick={() => setDateRange("2026-01-01", "2026-01-07")}>range</button>
    </div>
  );
}

describe("FilterContext", () => {
  it("provides defaults: last 7 days, all agencies, empty search", () => {
    render(<FilterProvider><Probe /></FilterProvider>);
    expect(screen.getByTestId("agencies").textContent).not.toBe("");
    expect(screen.getByTestId("search").textContent).toBe("");
    expect(screen.getByTestId("start").textContent).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(screen.getByTestId("end").textContent).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("updates agencies, search, and date range", async () => {
    render(<FilterProvider><Probe /></FilterProvider>);
    await userEvent.click(screen.getByText("set"));
    expect(screen.getByTestId("agencies").textContent).toBe("AC,BA");
    await userEvent.click(screen.getByText("search"));
    expect(screen.getByTestId("search").textContent).toBe("51B");
    await userEvent.click(screen.getByText("range"));
    expect(screen.getByTestId("start").textContent).toBe("2026-01-01");
    expect(screen.getByTestId("end").textContent).toBe("2026-01-07");
  });

  it("useFilters throws when used outside provider", () => {
    function Naked() {
      useFilters();
      return null;
    }
    const consoleErr = console.error;
    console.error = () => {};
    try {
      expect(() => render(<Naked />)).toThrow(/FilterProvider/);
    } finally {
      console.error = consoleErr;
    }
  });
});
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
npm run test:run -- src/context/FilterContext.test.tsx
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `FilterContext`**

`frontend/src/context/FilterContext.tsx`:

```tsx
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
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
npm run test:run -- src/context/FilterContext.test.tsx
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/context/FilterContext.tsx frontend/src/context/FilterContext.test.tsx
git commit -m "$(cat <<'EOF'
Add FilterContext — global date range + agencies + search

Holds the cross-section filter state with defaults of last 7 days,
all 8 known agencies, empty search. setAgencies refuses to clear the
list (falls back to all agencies) so dashboards never query with
agencies=[]. useFilters throws if used outside a FilterProvider — a
common bug class worth a loud error.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: SelectionContext

**Files:**
- Create: `frontend/src/context/SelectionContext.tsx`
- Create: `frontend/src/context/SelectionContext.test.tsx`

Holds the currently focused entities — selected route, selected stop, hovered stop — that other widgets cross-filter against. Plan 1a only writes to this from the Overview section; Plan 1b extends consumers across all sections + map.

- [ ] **Step 1: Write the failing test**

`frontend/src/context/SelectionContext.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SelectionProvider, useSelection } from "./SelectionContext";

function Probe() {
  const { selection, setRouteId, setStopId, setHoveredStopId, clear } = useSelection();
  return (
    <div>
      <span data-testid="route">{selection.routeId ?? "none"}</span>
      <span data-testid="stop">{selection.stopId ?? "none"}</span>
      <span data-testid="hover">{selection.hoveredStopId ?? "none"}</span>
      <button onClick={() => setRouteId("51B")}>r</button>
      <button onClick={() => setStopId("S001")}>s</button>
      <button onClick={() => setHoveredStopId("S002")}>h</button>
      <button onClick={clear}>c</button>
    </div>
  );
}

describe("SelectionContext", () => {
  it("starts empty", () => {
    render(<SelectionProvider><Probe /></SelectionProvider>);
    expect(screen.getByTestId("route").textContent).toBe("none");
    expect(screen.getByTestId("stop").textContent).toBe("none");
    expect(screen.getByTestId("hover").textContent).toBe("none");
  });

  it("setters update individual fields, clear resets all", async () => {
    render(<SelectionProvider><Probe /></SelectionProvider>);
    await userEvent.click(screen.getByText("r"));
    await userEvent.click(screen.getByText("s"));
    await userEvent.click(screen.getByText("h"));
    expect(screen.getByTestId("route").textContent).toBe("51B");
    expect(screen.getByTestId("stop").textContent).toBe("S001");
    expect(screen.getByTestId("hover").textContent).toBe("S002");
    await userEvent.click(screen.getByText("c"));
    expect(screen.getByTestId("route").textContent).toBe("none");
    expect(screen.getByTestId("stop").textContent).toBe("none");
    expect(screen.getByTestId("hover").textContent).toBe("none");
  });
});
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
npm run test:run -- src/context/SelectionContext.test.tsx
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `SelectionContext`**

`frontend/src/context/SelectionContext.tsx`:

```tsx
import React, { createContext, useCallback, useContext, useMemo, useState } from "react";

export interface Selection {
  routeId:        string | null;
  stopId:         string | null;
  hoveredStopId:  string | null;
}

interface SelectionApi {
  selection: Selection;
  setRouteId:        (id: string | null) => void;
  setStopId:         (id: string | null) => void;
  setHoveredStopId:  (id: string | null) => void;
  clear: () => void;
}

const SelectionContext = createContext<SelectionApi | null>(null);

export const SelectionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [routeId,       setRouteIdState]       = useState<string | null>(null);
  const [stopId,        setStopIdState]        = useState<string | null>(null);
  const [hoveredStopId, setHoveredStopIdState] = useState<string | null>(null);

  const setRouteId       = useCallback((id: string | null) => setRouteIdState(id), []);
  const setStopId        = useCallback((id: string | null) => setStopIdState(id), []);
  const setHoveredStopId = useCallback((id: string | null) => setHoveredStopIdState(id), []);
  const clear = useCallback(() => {
    setRouteIdState(null);
    setStopIdState(null);
    setHoveredStopIdState(null);
  }, []);

  const value = useMemo<SelectionApi>(
    () => ({ selection: { routeId, stopId, hoveredStopId }, setRouteId, setStopId, setHoveredStopId, clear }),
    [routeId, stopId, hoveredStopId, setRouteId, setStopId, setHoveredStopId, clear]
  );

  return <SelectionContext.Provider value={value}>{children}</SelectionContext.Provider>;
};

export function useSelection(): SelectionApi {
  const v = useContext(SelectionContext);
  if (!v) throw new Error("useSelection must be used inside a SelectionProvider");
  return v;
}
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
npm run test:run -- src/context/SelectionContext.test.tsx
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/context/SelectionContext.tsx frontend/src/context/SelectionContext.test.tsx
git commit -m "$(cat <<'EOF'
Add SelectionContext — focused route / stop / hovered stop

Holds the entities the user has focused so other widgets can
cross-filter. Plan 1a only writes selection from the Overview
section; Plan 1b will wire MapView and Operations to consume it too.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Shared API helpers

**Files:**
- Create: `frontend/src/lib/api.ts`

Today every component duplicates the API_BASE / API_KEY axios header boilerplate. Extracts it into one module so primitives, sections, and future contexts all use the same source.

- [ ] **Step 1: Implement**

```ts
import axios, { AxiosInstance } from "axios";

export const API_BASE: string = (import.meta.env.VITE_API_BASE_URL as string) || "http://localhost:8000";
const API_KEY: string = (import.meta.env.VITE_API_KEY as string) || "";

export function apiHeaders(): Record<string, string> {
  return API_KEY ? { "X-API-Key": API_KEY } : {};
}

export const api: AxiosInstance = axios.create({
  baseURL: API_BASE,
  headers: apiHeaders(),
  timeout: 30000,
});
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "$(cat <<'EOF'
Extract shared axios helpers to lib/api.ts

The API base URL + X-API-Key header boilerplate was duplicated in
Sidebar.tsx, StopDrawer.tsx, MapView.tsx, AiAssistant.tsx, and
BenchmarkPanel.tsx. New shell components import { api, apiHeaders,
API_BASE } from one place; existing components keep their inline
versions until Plan 1b refactors them.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Primitives — `KpiCard`, `Spinner`, `EmptyState`

**Files:**
- Create: `frontend/src/components/primitives/KpiCard.tsx`
- Create: `frontend/src/components/primitives/KpiCard.test.tsx`
- Create: `frontend/src/components/primitives/Spinner.tsx`
- Create: `frontend/src/components/primitives/EmptyState.tsx`
- Create: `frontend/src/components/primitives/primitives.css`

These three are the simplest primitives; bigger chart wrappers come in Task 8.

- [ ] **Step 1: Write the KpiCard failing test**

`frontend/src/components/primitives/KpiCard.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { KpiCard } from "./KpiCard";

describe("KpiCard", () => {
  it("renders label and value", () => {
    render(<KpiCard label="On-time %" value="87%" />);
    expect(screen.getByText("On-time %")).toBeInTheDocument();
    expect(screen.getByText("87%")).toBeInTheDocument();
  });

  it("renders sub when provided", () => {
    render(<KpiCard label="Routes" value="349" sub="across 8 agencies" />);
    expect(screen.getByText("across 8 agencies")).toBeInTheDocument();
  });

  it("renders delta with up/down marker", () => {
    render(<KpiCard label="OTP" value="87%" delta={2.3} deltaIsGood />);
    const delta = screen.getByText(/\+2\.3/);
    expect(delta).toBeInTheDocument();
    expect(delta.className).toMatch(/kpi-card__delta--good/);
  });

  it("renders negative delta as bad when deltaIsGood is false", () => {
    render(<KpiCard label="Delay" value="3.2 min" delta={-0.4} deltaIsGood={false} />);
    const delta = screen.getByText(/-0\.4/);
    expect(delta.className).toMatch(/kpi-card__delta--bad/);
  });
});
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
npm run test:run -- src/components/primitives/KpiCard.test.tsx
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `KpiCard`**

```tsx
import React from "react";
import "./primitives.css";

export interface KpiCardProps {
  label: string;
  value: string;
  sub?: string;
  /** Numeric change vs previous period. Renders sign + 1 decimal place. */
  delta?: number;
  /** When true a positive delta is rendered "good" (green); when false it's bad.
   *  Useful because some metrics improve as they fall (delay) and some as they rise (OTP). */
  deltaIsGood?: boolean;
}

export const KpiCard: React.FC<KpiCardProps> = ({ label, value, sub, delta, deltaIsGood = true }) => {
  let deltaCls = "";
  if (delta !== undefined) {
    const positive = delta >= 0;
    const good = positive === deltaIsGood;
    deltaCls = good ? "kpi-card__delta--good" : "kpi-card__delta--bad";
  }
  return (
    <div className="kpi-card">
      <span className="kpi-card__value">{value}</span>
      <span className="kpi-card__label">{label}</span>
      {sub && <span className="kpi-card__sub">{sub}</span>}
      {delta !== undefined && (
        <span className={`kpi-card__delta ${deltaCls}`}>
          {delta >= 0 ? "+" : ""}{delta.toFixed(1)}
        </span>
      )}
    </div>
  );
};
```

- [ ] **Step 4: Implement `Spinner`**

```tsx
import React from "react";
import "./primitives.css";

export const Spinner: React.FC<{ size?: "sm" | "md" }> = ({ size = "md" }) => (
  <span className={`spinner spinner--${size}`} role="progressbar" aria-label="Loading" />
);
```

- [ ] **Step 5: Implement `EmptyState`**

```tsx
import React from "react";
import "./primitives.css";

export const EmptyState: React.FC<{ message: string; hint?: string }> = ({ message, hint }) => (
  <div className="empty-state">
    <p className="empty-state__msg">{message}</p>
    {hint && <p className="empty-state__hint">{hint}</p>}
  </div>
);
```

- [ ] **Step 6: Implement `primitives.css`**

```css
@import "../../design/tokens.css";

.kpi-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-4);
  background: var(--color-bg-1);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-3);
  min-width: 160px;
  position: relative;
}

.kpi-card__value {
  font-size: var(--text-2xl);
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--color-fg-0);
  line-height: var(--leading-tight);
}

.kpi-card__label {
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-fg-2);
}

.kpi-card__sub {
  font-size: var(--text-xs);
  color: var(--color-fg-3);
}

.kpi-card__delta {
  position: absolute;
  top: var(--space-2);
  right: var(--space-3);
  font-size: var(--text-xs);
  font-weight: 600;
  padding: 2px var(--space-2);
  border-radius: var(--radius-pill);
}

.kpi-card__delta--good { background: rgba(34, 197, 94, 0.15);  color: var(--color-success); }
.kpi-card__delta--bad  { background: rgba(239, 68, 68, 0.15);  color: var(--color-critical); }

/* Spinner */
.spinner {
  display: inline-block;
  border: 2px solid var(--color-border);
  border-top-color: var(--color-fg-1);
  border-radius: 50%;
  animation: spin 700ms linear infinite;
}
.spinner--sm { width: 14px; height: 14px; }
.spinner--md { width: 24px; height: 24px; }

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Empty state */
.empty-state {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-5);
  text-align: center;
}
.empty-state__msg  { font-size: var(--text-sm); color: var(--color-fg-1); margin: 0; }
.empty-state__hint { font-size: var(--text-xs); color: var(--color-fg-3); margin: 0; }
```

- [ ] **Step 7: Run the KpiCard test**

```bash
npm run test:run -- src/components/primitives/KpiCard.test.tsx
```

Expected: 4 passed.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/primitives/
git commit -m "$(cat <<'EOF'
Extract KpiCard, Spinner, EmptyState primitives from Sidebar.tsx

These three were inline helpers in Sidebar.tsx (lines 19, 34, 38).
KpiCard gains a delta prop with deltaIsGood polarity — some KPIs
improve as they rise (OTP), some as they fall (delay), so the caller
declares which direction is good. All three consume the new design
tokens. Sidebar.tsx still has its own copies inline; Plan 1b deletes
them once sections fully migrate.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Primitives — `DataList`, `TrendChart`, `BarChart`

**Files:**
- Create: `frontend/src/components/primitives/DataList.tsx`
- Create: `frontend/src/components/primitives/DataList.test.tsx`
- Create: `frontend/src/components/primitives/TrendChart.tsx`
- Create: `frontend/src/components/primitives/BarChart.tsx`

- [ ] **Step 1: Write the DataList failing test**

`frontend/src/components/primitives/DataList.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DataList } from "./DataList";

describe("DataList", () => {
  it("renders one row per item with primary + secondary text", () => {
    render(
      <DataList
        items={[
          { id: "a", primary: "Route 51B", secondary: "AC Transit", trailing: "2.3 min" },
          { id: "b", primary: "Route 72",  secondary: "AC Transit", trailing: "1.1 min" },
        ]}
      />
    );
    expect(screen.getByText("Route 51B")).toBeInTheDocument();
    expect(screen.getByText("Route 72")).toBeInTheDocument();
    expect(screen.getByText("2.3 min")).toBeInTheDocument();
  });

  it("calls onSelect with the item id when a row is clicked", async () => {
    const onSelect = vi.fn();
    render(
      <DataList
        items={[{ id: "a", primary: "Route 51B" }]}
        onSelect={onSelect}
      />
    );
    await userEvent.click(screen.getByText("Route 51B"));
    expect(onSelect).toHaveBeenCalledWith("a");
  });

  it("highlights the selected row", () => {
    render(
      <DataList
        items={[{ id: "a", primary: "Route 51B" }, { id: "b", primary: "Route 72" }]}
        selectedId="b"
      />
    );
    const rows = screen.getAllByRole("button");
    expect(rows[1].className).toMatch(/data-list__row--selected/);
    expect(rows[0].className).not.toMatch(/data-list__row--selected/);
  });
});
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
npm run test:run -- src/components/primitives/DataList.test.tsx
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `DataList`**

```tsx
import React from "react";
import "./primitives.css";

export interface DataListItem {
  id: string;
  primary:    string;
  secondary?: string;
  trailing?:  React.ReactNode;
}

export interface DataListProps {
  items:       DataListItem[];
  selectedId?: string | null;
  onSelect?:   (id: string) => void;
}

export const DataList: React.FC<DataListProps> = ({ items, selectedId, onSelect }) => (
  <ul className="data-list">
    {items.map((item) => {
      const selected = selectedId === item.id;
      return (
        <li key={item.id} className="data-list__li">
          <button
            type="button"
            className={`data-list__row ${selected ? "data-list__row--selected" : ""}`}
            onClick={() => onSelect?.(item.id)}
            disabled={!onSelect}
          >
            <span className="data-list__primary">{item.primary}</span>
            {item.secondary && <span className="data-list__secondary">{item.secondary}</span>}
            {item.trailing  !== undefined && <span className="data-list__trailing">{item.trailing}</span>}
          </button>
        </li>
      );
    })}
  </ul>
);
```

- [ ] **Step 4: Append DataList styles to `primitives.css`**

Append to `frontend/src/components/primitives/primitives.css`:

```css
.data-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
  background: var(--color-border);
  border-radius: var(--radius-2);
  overflow: hidden;
}

.data-list__li { background: var(--color-bg-1); }

.data-list__row {
  width: 100%;
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border: none;
  background: transparent;
  font: inherit;
  text-align: left;
  color: var(--color-fg-0);
  cursor: pointer;
  transition: background 120ms;
}

.data-list__row:hover:not(:disabled)  { background: var(--color-bg-2); }
.data-list__row:disabled              { cursor: default; opacity: 0.95; }
.data-list__row--selected             { background: var(--color-bg-2); box-shadow: inset 3px 0 0 var(--color-brand); }

.data-list__primary    { font-weight: 500; }
.data-list__secondary  { color: var(--color-fg-2); font-size: var(--text-sm); }
.data-list__trailing   { margin-left: auto; color: var(--color-fg-1); font-size: var(--text-sm); }
```

- [ ] **Step 5: Implement `TrendChart`**

`frontend/src/components/primitives/TrendChart.tsx`:

```tsx
import React from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer } from "recharts";

export interface TrendPoint {
  x: string;
  y: number | null;
}

export interface TrendChartProps {
  data:    TrendPoint[];
  yLabel?: string;
  color?:  string;
  height?: number;
}

export const TrendChart: React.FC<TrendChartProps> = ({ data, yLabel, color = "#3b82f6", height = 200 }) => (
  <ResponsiveContainer width="100%" height={height}>
    <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
      <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.15)" />
      <XAxis dataKey="x" stroke="#94a3b8" fontSize={11} tickLine={false} />
      <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={false} label={yLabel ? { value: yLabel, angle: -90, position: "insideLeft", fill: "#94a3b8", fontSize: 11 } : undefined} />
      <Tooltip contentStyle={{ background: "#1a2334", border: "1px solid #283448", borderRadius: 8, fontSize: 12 }} />
      <Line type="monotone" dataKey="y" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
    </LineChart>
  </ResponsiveContainer>
);
```

- [ ] **Step 6: Implement `BarChart`**

`frontend/src/components/primitives/BarChart.tsx`:

```tsx
import React from "react";
import { BarChart as RBarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, Cell } from "recharts";

export interface BarPoint {
  label: string;
  value: number;
  color?: string;
}

export interface BarChartProps {
  data:    BarPoint[];
  height?: number;
  /** When set, bars use this color; otherwise each bar's `.color` is used,
   *  falling back to brand blue. */
  color?:  string;
}

export const BarChart: React.FC<BarChartProps> = ({ data, height = 220, color }) => (
  <ResponsiveContainer width="100%" height={height}>
    <RBarChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
      <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.15)" />
      <XAxis dataKey="label" stroke="#94a3b8" fontSize={11} tickLine={false} interval={0} angle={-30} textAnchor="end" height={50} />
      <YAxis stroke="#94a3b8" fontSize={11} tickLine={false} axisLine={false} />
      <Tooltip contentStyle={{ background: "#1a2334", border: "1px solid #283448", borderRadius: 8, fontSize: 12 }} />
      <Bar dataKey="value" radius={[4, 4, 0, 0]} isAnimationActive={false}>
        {data.map((d, i) => (
          <Cell key={i} fill={color ?? d.color ?? "#3b82f6"} />
        ))}
      </Bar>
    </RBarChart>
  </ResponsiveContainer>
);
```

- [ ] **Step 7: Run all primitives tests**

```bash
npm run test:run -- src/components/primitives/
```

Expected: 7 passed (4 KpiCard + 3 DataList).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/primitives/
git commit -m "$(cat <<'EOF'
Extract DataList, TrendChart, BarChart primitives

DataList takes a flat items array of {id, primary, secondary?,
trailing?} and an optional onSelect — the row-list pattern used in
every old Sidebar panel. Selected row gets a brand-coloured left
border, hovered rows shift background. TrendChart and BarChart are
thin Recharts wrappers with consistent dark-theme styling, axis
formatting, and no animation (charts in BI tools shouldn't dance on
every re-render). Plan 1b sections use these directly.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Primitives index re-export

**Files:**
- Create: `frontend/src/components/primitives/index.ts`

- [ ] **Step 1: Implement**

```ts
export { KpiCard } from "./KpiCard";
export type { KpiCardProps } from "./KpiCard";
export { DataList } from "./DataList";
export type { DataListProps, DataListItem } from "./DataList";
export { TrendChart } from "./TrendChart";
export type { TrendChartProps, TrendPoint } from "./TrendChart";
export { BarChart } from "./BarChart";
export type { BarChartProps, BarPoint } from "./BarChart";
export { Spinner } from "./Spinner";
export { EmptyState } from "./EmptyState";
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/primitives/index.ts
git commit -m "$(cat <<'EOF'
Add primitives barrel export

Lets sections import from "components/primitives" rather than poking
at individual files. Re-exports types alongside the components.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: `FilterBar` component

**Files:**
- Create: `frontend/src/components/FilterBar.tsx`
- Create: `frontend/src/components/FilterBar.test.tsx`

Renders the three filter controls — date range, agency picker, route search — bound to `FilterContext`.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/FilterBar.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterProvider, useFilters } from "../context/FilterContext";
import { FilterBar } from "./FilterBar";

function Probe() {
  const { filters } = useFilters();
  return <div data-testid="probe">{`${filters.startDate}|${filters.endDate}|${filters.agencies.join(",")}|${filters.search}`}</div>;
}

describe("FilterBar", () => {
  it("renders the three controls", () => {
    render(<FilterProvider><FilterBar /></FilterProvider>);
    expect(screen.getByLabelText(/from/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/to/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/route/i)).toBeInTheDocument();
  });

  it("updates the FilterContext when search is typed", async () => {
    render(
      <FilterProvider>
        <FilterBar />
        <Probe />
      </FilterProvider>
    );
    const input = screen.getByPlaceholderText(/route/i);
    await userEvent.type(input, "51B");
    expect(screen.getByTestId("probe").textContent).toMatch(/\|51B$/);
  });

  it("toggles agencies when an agency pill is clicked", async () => {
    render(
      <FilterProvider>
        <FilterBar />
        <Probe />
      </FilterProvider>
    );
    // Click "AC" — it should already be selected by default (all selected);
    // clicking removes it from the list.
    const acPill = screen.getByRole("button", { name: /^AC( |$)/ });
    await userEvent.click(acPill);
    expect(screen.getByTestId("probe").textContent).not.toMatch(/,?AC,/);
  });
});
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
npm run test:run -- src/components/FilterBar.test.tsx
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `FilterBar`**

```tsx
import React from "react";
import { useFilters } from "../context/FilterContext";
import { AGENCY_LIST, agencyName } from "../lib/agencies";
import "./FilterBar.css";

export const FilterBar: React.FC = () => {
  const { filters, setDateRange, setAgencies, setSearch } = useFilters();

  const toggleAgency = (id: string) => {
    const next = filters.agencies.includes(id)
      ? filters.agencies.filter(a => a !== id)
      : [...filters.agencies, id];
    setAgencies(next);
  };

  return (
    <div className="filter-bar shell-filterbar">
      <div className="filter-bar__group">
        <label className="filter-bar__label">
          <span>From</span>
          <input
            type="date"
            value={filters.startDate}
            onChange={(e) => setDateRange(e.target.value, filters.endDate)}
          />
        </label>
        <label className="filter-bar__label">
          <span>To</span>
          <input
            type="date"
            value={filters.endDate}
            onChange={(e) => setDateRange(filters.startDate, e.target.value)}
          />
        </label>
      </div>

      <div className="filter-bar__pills">
        {AGENCY_LIST.map(a => {
          const active = filters.agencies.includes(a.id);
          return (
            <button
              key={a.id}
              type="button"
              className={`agency-pill ${active ? "agency-pill--active" : ""}`}
              style={active ? { borderColor: a.color, color: a.color } : undefined}
              onClick={() => toggleAgency(a.id)}
              title={agencyName(a.id)}
            >
              {a.id}
            </button>
          );
        })}
      </div>

      <input
        type="search"
        className="filter-bar__search"
        placeholder="Search route…"
        value={filters.search}
        onChange={(e) => setSearch(e.target.value)}
      />
    </div>
  );
};
```

- [ ] **Step 4: Create `frontend/src/components/FilterBar.css`**

```css
@import "../design/tokens.css";

.filter-bar { display: flex; gap: var(--space-4); align-items: center; }

.filter-bar__group { display: flex; gap: var(--space-3); align-items: center; }

.filter-bar__label {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-fg-2);
}

.filter-bar__label input[type="date"] {
  background: var(--color-bg-2);
  border: 1px solid var(--color-border);
  color: var(--color-fg-0);
  padding: 4px var(--space-2);
  border-radius: var(--radius-1);
  font: inherit;
  font-size: var(--text-sm);
  color-scheme: dark;
}

.filter-bar__pills { display: flex; gap: 4px; flex-wrap: wrap; }

.agency-pill {
  appearance: none;
  background: transparent;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-pill);
  color: var(--color-fg-2);
  padding: 2px var(--space-2);
  font: inherit;
  font-size: var(--text-xs);
  cursor: pointer;
  transition: background 120ms, color 120ms, border-color 120ms;
}
.agency-pill:hover { color: var(--color-fg-0); }
.agency-pill--active {
  background: rgba(59, 130, 246, 0.1);
}

.filter-bar__search {
  margin-left: auto;
  background: var(--color-bg-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-2);
  padding: 4px var(--space-3);
  color: var(--color-fg-0);
  font: inherit;
  font-size: var(--text-sm);
  width: 240px;
}
.filter-bar__search::placeholder { color: var(--color-fg-3); }
```

- [ ] **Step 5: Run the test to confirm it passes**

```bash
npm run test:run -- src/components/FilterBar.test.tsx
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/FilterBar.tsx frontend/src/components/FilterBar.test.tsx frontend/src/components/FilterBar.css
git commit -m "$(cat <<'EOF'
Add FilterBar bound to FilterContext

Renders the three global filter controls — date range, agency
multi-select pills, free-text route search — and writes through to
FilterContext so every section sees the same filter state. Pills
respect the agency colors from lib/agencies.ts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Section scaffolds (4 stubs)

**Files:**
- Create: `frontend/src/sections/Operations.tsx`
- Create: `frontend/src/sections/Network.tsx`
- Create: `frontend/src/sections/EquitySafety.tsx`
- Create: `frontend/src/sections/BenchmarksDrift.tsx`
- Create: `frontend/src/sections/sections.css`

Stubs are deliberate placeholders. They render a friendly "Plan 1b" message so the nav is testable end-to-end without requiring real content yet.

- [ ] **Step 1: Create `sections.css`**

```css
@import "../design/tokens.css";

.section {
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.section__header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-4);
}

.section__title {
  font-size: var(--text-2xl);
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--color-fg-0);
  margin: 0;
}

.section__subtitle {
  font-size: var(--text-sm);
  color: var(--color-fg-2);
}

.section__kpi-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--space-3);
}

.section__grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
}

.section__panel {
  background: var(--color-bg-1);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-3);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-height: 280px;
}

.section__panel-title {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-fg-1);
  margin: 0;
}

.section-stub {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: var(--space-8);
  background: var(--color-bg-1);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-3);
  color: var(--color-fg-2);
}
```

- [ ] **Step 2: Create the 4 stub components**

`frontend/src/sections/Operations.tsx`:

```tsx
import React from "react";
import "./sections.css";

export const Operations: React.FC = () => (
  <div className="section">
    <div className="section__header">
      <h2 className="section__title">Operations</h2>
      <span className="section__subtitle">Reliability · bunching · live vehicles · crowding</span>
    </div>
    <div className="section-stub">
      <p>Real content lands in Plan 1b.</p>
      <p>Will absorb today's Reliability, Bunching, Live Vehicles, Crowding, and Comparison tabs.</p>
    </div>
  </div>
);
```

`frontend/src/sections/Network.tsx`:

```tsx
import React from "react";
import "./sections.css";

export const Network: React.FC = () => (
  <div className="section">
    <div className="section__header">
      <h2 className="section__title">Network</h2>
      <span className="section__subtitle">Routes · coverage · trip planning</span>
    </div>
    <div className="section-stub">
      <p>Real content lands in Plan 1b.</p>
      <p>Will absorb today's Routes, Coverage, and Trip Planner tabs.</p>
    </div>
  </div>
);
```

`frontend/src/sections/EquitySafety.tsx`:

```tsx
import React from "react";
import "./sections.css";

export const EquitySafety: React.FC = () => (
  <div className="section">
    <div className="section__header">
      <h2 className="section__title">Equity &amp; Safety</h2>
      <span className="section__subtitle">Service delivery and risk by census tract</span>
    </div>
    <div className="section-stub">
      <p>Real content lands in Plan 1b.</p>
      <p>Will absorb today's Equity and Safety tabs with cross-overlays.</p>
    </div>
  </div>
);
```

`frontend/src/sections/BenchmarksDrift.tsx`:

```tsx
import React from "react";
import "./sections.css";

export const BenchmarksDrift: React.FC = () => (
  <div className="section">
    <div className="section__header">
      <h2 className="section__title">Benchmarks &amp; Drift</h2>
      <span className="section__subtitle">Agency comparison · schedule drift · cross-modal</span>
    </div>
    <div className="section-stub">
      <p>Real content lands in Plan 1b.</p>
      <p>Will absorb today's Benchmarks, Demand, and Traffic tabs.</p>
    </div>
  </div>
);
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/sections/Operations.tsx frontend/src/sections/Network.tsx frontend/src/sections/EquitySafety.tsx frontend/src/sections/BenchmarksDrift.tsx frontend/src/sections/sections.css
git commit -m "$(cat <<'EOF'
Scaffold Operations / Network / Equity & Safety / Benchmarks sections

Stub components that render a section header and a friendly
"Plan 1b" placeholder. Shipping the nav with these stubs in 1a means
the AppShell and FilterBar are testable end-to-end without waiting
on real section content.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: `Overview` section (real content)

**Files:**
- Create: `frontend/src/sections/Overview.tsx`
- Create: `frontend/src/sections/Overview.test.tsx`

Renders four KPIs from existing backend endpoints, a "worst routes by avg delay" data list, and a simple network-wide trend sparkline. Reads the date range and agencies from `FilterContext`. Writes `routeId` to `SelectionContext` when a route is clicked.

- [ ] **Step 1: Write the failing test**

`frontend/src/sections/Overview.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterProvider } from "../context/FilterContext";
import { SelectionProvider, useSelection } from "../context/SelectionContext";
import { Overview } from "./Overview";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    api: {
      get: vi.fn(async (url: string) => {
        if (url.startsWith("/reliability/summary")) {
          return { data: [
            { route_id: "51B", sample_events: 200, avg_delay_seconds: 240, on_time_pct: 55 },
            { route_id: "72",  sample_events: 150, avg_delay_seconds: 60,  on_time_pct: 92 },
          ] };
        }
        if (url.startsWith("/reliability/trend")) {
          return { data: [
            { service_date: "2026-05-04", avg_delay: 90 },
            { service_date: "2026-05-05", avg_delay: 110 },
          ] };
        }
        if (url.startsWith("/routes")) {
          return { data: [{ route_id: "51B" }, { route_id: "72" }] };
        }
        if (url.startsWith("/safety/stops")) {
          return { data: [{ stop_id: "S1", safety_score: 12 }, { stop_id: "S2", safety_score: 4 }] };
        }
        return { data: [] };
      }),
    },
  };
});

function CapturedRoute() {
  const { selection } = useSelection();
  return <div data-testid="captured">{selection.routeId ?? "none"}</div>;
}

function wrap(ui: React.ReactElement) {
  return (
    <FilterProvider>
      <SelectionProvider>
        {ui}
      </SelectionProvider>
    </FilterProvider>
  );
}

describe("Overview", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the four KPI tiles", async () => {
    render(wrap(<Overview />));
    await waitFor(() => expect(screen.getByText(/Routes/i)).toBeInTheDocument());
    expect(screen.getByText(/Network OTP/i)).toBeInTheDocument();
    expect(screen.getByText(/Avg delay/i)).toBeInTheDocument();
    expect(screen.getByText(/Hot stops/i)).toBeInTheDocument();
  });

  it("renders the worst-routes list with route ids", async () => {
    render(wrap(<Overview />));
    await waitFor(() => expect(screen.getByText("51B")).toBeInTheDocument());
    expect(screen.getByText("72")).toBeInTheDocument();
  });

  it("clicking a worst-route row writes routeId to SelectionContext", async () => {
    render(wrap(<><Overview /><CapturedRoute /></>));
    await waitFor(() => expect(screen.getByText("51B")).toBeInTheDocument());
    await userEvent.click(screen.getByText("51B"));
    expect(screen.getByTestId("captured").textContent).toBe("51B");
  });
});
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
npm run test:run -- src/sections/Overview.test.tsx
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `Overview`**

```tsx
import React, { useEffect, useState } from "react";
import { useFilters } from "../context/FilterContext";
import { useSelection } from "../context/SelectionContext";
import { api } from "../lib/api";
import { KpiCard, DataList, TrendChart, Spinner, EmptyState, type DataListItem, type TrendPoint } from "../components/primitives";
import "./sections.css";

interface ReliabilityRow {
  route_id: string;
  sample_events: number;
  avg_delay_seconds: number;
  on_time_pct?: number;
}
interface TrendRow { service_date: string; avg_delay: number; }
interface SafetyRow { stop_id: string; safety_score: number; }

function fmtMin(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  return `${(seconds / 60).toFixed(1)} min`;
}

export const Overview: React.FC = () => {
  const { filters } = useFilters();
  const { selection, setRouteId } = useSelection();

  const [reliabilityRows, setReliabilityRows] = useState<ReliabilityRow[]>([]);
  const [trendRows, setTrendRows] = useState<TrendRow[]>([]);
  const [routeCount, setRouteCount] = useState<number | null>(null);
  const [hotStops, setHotStops] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function fetchAll() {
      setLoading(true);
      try {
        const [rel, trend, routes, safety] = await Promise.all([
          api.get<ReliabilityRow[]>("/reliability/summary", { params: { start_date: filters.startDate, end_date: filters.endDate } }),
          api.get<TrendRow[]>("/reliability/trend", { params: { start_date: filters.startDate, end_date: filters.endDate } }).catch(() => ({ data: [] })),
          api.get<{ route_id: string }[]>("/routes"),
          api.get<SafetyRow[]>("/safety/stops", { params: { min_score: 8 } }).catch(() => ({ data: [] })),
        ]);
        if (cancelled) return;
        setReliabilityRows(rel.data ?? []);
        setTrendRows(trend.data ?? []);
        setRouteCount(routes.data?.length ?? 0);
        setHotStops(safety.data?.length ?? 0);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchAll();
    return () => { cancelled = true; };
  }, [filters.startDate, filters.endDate]);

  const totalEvents = reliabilityRows.reduce((s, r) => s + (r.sample_events || 0), 0);
  const networkOtp = totalEvents > 0
    ? reliabilityRows.reduce((s, r) => s + ((r.on_time_pct ?? 0) * r.sample_events), 0) / totalEvents
    : null;
  const avgDelay = totalEvents > 0
    ? reliabilityRows.reduce((s, r) => s + (r.avg_delay_seconds * r.sample_events), 0) / totalEvents
    : null;

  const worstRoutes: DataListItem[] = [...reliabilityRows]
    .filter(r => r.sample_events >= 10)
    .sort((a, b) => b.avg_delay_seconds - a.avg_delay_seconds)
    .slice(0, 10)
    .map(r => ({
      id:       r.route_id,
      primary:  r.route_id,
      secondary: `${r.sample_events} events`,
      trailing: fmtMin(r.avg_delay_seconds),
    }));

  const trendPoints: TrendPoint[] = trendRows.map(t => ({ x: t.service_date.slice(5), y: t.avg_delay }));

  return (
    <div className="section">
      <div className="section__header">
        <h2 className="section__title">Overview</h2>
        <span className="section__subtitle">Network health · {filters.startDate} → {filters.endDate}</span>
      </div>

      <div className="section__kpi-strip">
        <KpiCard label="Routes"      value={routeCount === null ? "—" : String(routeCount)} sub={`across ${filters.agencies.length} agencies`} />
        <KpiCard label="Network OTP" value={networkOtp === null ? "—" : `${networkOtp.toFixed(1)}%`} />
        <KpiCard label="Avg delay"   value={avgDelay  === null ? "—" : fmtMin(avgDelay)} deltaIsGood={false} />
        <KpiCard label="Hot stops"   value={hotStops  === null ? "—" : String(hotStops)} sub="safety score ≥ 8" deltaIsGood={false} />
      </div>

      <div className="section__grid">
        <div className="section__panel">
          <h3 className="section__panel-title">Worst routes by avg delay</h3>
          {loading && worstRoutes.length === 0 ? <Spinner /> : worstRoutes.length === 0 ? (
            <EmptyState message="No route data in this window." hint="Widen the date range or pick more agencies." />
          ) : (
            <DataList items={worstRoutes} selectedId={selection.routeId} onSelect={setRouteId} />
          )}
        </div>

        <div className="section__panel">
          <h3 className="section__panel-title">Network delay trend</h3>
          {loading && trendPoints.length === 0 ? <Spinner /> : trendPoints.length === 0 ? (
            <EmptyState message="No trend data in this window." />
          ) : (
            <TrendChart data={trendPoints} yLabel="sec" />
          )}
        </div>
      </div>
    </div>
  );
};
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
npm run test:run -- src/sections/Overview.test.tsx
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/sections/Overview.tsx frontend/src/sections/Overview.test.tsx
git commit -m "$(cat <<'EOF'
Build Overview section content

Renders the four headline KPIs (routes count, network OTP, avg delay,
hot stops with safety score ≥ 8), a worst-routes-by-delay list bound
to SelectionContext, and a network delay trend sparkline. All four
fetches run in parallel from the FilterContext date range; trend and
safety queries fail-open so a missing endpoint can't blank the whole
section. Clicking a worst-route row writes routeId to the
SelectionContext — Plan 1b's MapView refactor will consume it.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: `AppShell` component

**Files:**
- Create: `frontend/src/components/AppShell.tsx`
- Create: `frontend/src/components/AppShell.test.tsx`

The grid layout, brand, section tabs, filter bar slot, and main area. Renders a placeholder for the Agent rail. Holds `activeSection` state internally.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/AppShell.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterProvider } from "../context/FilterContext";
import { SelectionProvider } from "../context/SelectionContext";
import { AppShell } from "./AppShell";

function wrap(ui: React.ReactElement) {
  return (
    <FilterProvider>
      <SelectionProvider>{ui}</SelectionProvider>
    </FilterProvider>
  );
}

describe("AppShell", () => {
  it("renders brand, all five tabs, and filter bar", () => {
    render(wrap(<AppShell />));
    expect(screen.getByText(/BATIS/)).toBeInTheDocument();
    ["Overview", "Operations", "Network", "Equity & Safety", "Benchmarks & Drift"].forEach(label => {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    });
    expect(screen.getByLabelText(/from/i)).toBeInTheDocument();
  });

  it("renders Overview by default", () => {
    render(wrap(<AppShell />));
    expect(screen.getByRole("heading", { name: "Overview" })).toBeInTheDocument();
  });

  it("switches sections when a tab is clicked", async () => {
    render(wrap(<AppShell />));
    await userEvent.click(screen.getByRole("button", { name: "Operations" }));
    expect(screen.getByRole("heading", { name: "Operations" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Network" }));
    expect(screen.getByRole("heading", { name: "Network" })).toBeInTheDocument();
  });

  it("renders an agent rail placeholder", () => {
    render(wrap(<AppShell />));
    expect(screen.getByText(/Ask BATIS/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
npm run test:run -- src/components/AppShell.test.tsx
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `AppShell`**

```tsx
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
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
npm run test:run -- src/components/AppShell.test.tsx
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AppShell.tsx frontend/src/components/AppShell.test.tsx
git commit -m "$(cat <<'EOF'
Add AppShell — header, 5-tab nav, filter bar slot, main, rail

Three-row grid (header, filter, main+rail). Tab nav switches between
the five sections; Overview is the default. Agent rail renders a
placeholder for now — Plan 1c mounts the real Agent there. Routing
stays in component state in 1a; Plan 1c moves it to the URL.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Rewire `App.tsx` to use the new shell

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/main.tsx`

`App.tsx` shrinks from 128 lines to a handful: wrap providers, render `AppShell`. The old 14-tab nav, sidebar, map, and stop drawer are removed from this render path — they live on as files but aren't mounted. (Plan 1b reintroduces the map and stop drawer inside the new shell.)

- [ ] **Step 1: Replace `frontend/src/App.tsx` entirely**

```tsx
import React from "react";
import { FilterProvider } from "./context/FilterContext";
import { SelectionProvider } from "./context/SelectionContext";
import { AppShell } from "./components/AppShell";

export const App: React.FC = () => (
  <FilterProvider>
    <SelectionProvider>
      <AppShell />
    </SelectionProvider>
  </FilterProvider>
);
```

- [ ] **Step 2: Update `frontend/src/main.tsx`**

Drop the legacy `styles.css` and `mapbox-gl.css` imports — neither's consumers are rendered in 1a. The legacy CSS defines class names (`.kpi-card`, `.agency-pill`, etc.) that would otherwise collide with the new primitives. Plan 1b reintroduces both imports when `MapView` and `StopDrawer` come back into the shell.

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import "./design/shell.css";
import { App } from "./App";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

- [ ] **Step 3: Run the full test suite**

```bash
npm run test:run
```

Expected: all tests pass (FilterContext 3 + SelectionContext 2 + KpiCard 4 + DataList 3 + FilterBar 3 + Overview 3 + AppShell 4 = 22 tests).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/main.tsx
git commit -m "$(cat <<'EOF'
Rewire App.tsx and main.tsx to use the new shell

App.tsx collapses to a 9-line provider sandwich around AppShell. The
old MapView / Sidebar / StopDrawer / AlertsBanner render path is gone
for this turn — those files are untouched and will be brought back
into the shell by Plan 1b. main.tsx drops the legacy styles.css and
mapbox-gl.css imports so the new primitives don't collide with
.kpi-card / .agency-pill rules from the old global stylesheet; both
imports come back when MapView and StopDrawer are reintroduced in
Plan 1b.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Manual browser QA

**Files:** none modified.

End-to-end visual check against a running dev server.

- [ ] **Step 1: Start the frontend dev server**

If the dockerized stack from Phase 0 is still running, it will pick up the changes automatically (Vite HMR + the bind-mount on `frontend/src`). Otherwise:

```bash
cd frontend && npm run dev
```

- [ ] **Step 2: Open http://localhost:5173 in a browser**

Expected:
- Dark theme applied
- "BATIS" brand at top-left of the header
- Five tabs across the top: Overview (active), Operations, Network, Equity & Safety, Benchmarks & Drift
- Filter bar below the header with From/To date inputs (defaulting to last 7 days), eight agency pills (all active), search input on the right
- Overview content: four KPI tiles (Routes / Network OTP / Avg delay / Hot stops), a "Worst routes by avg delay" list with real route IDs from the dev DB, a network delay trend sparkline
- Agent rail placeholder on the right reading "Ask BATIS — coming in Plan 1c"

- [ ] **Step 3: Smoke-check each section tab**

Click Operations, Network, Equity & Safety, Benchmarks & Drift in turn. Each should render its stub message. Click Overview to return.

- [ ] **Step 4: Smoke-check filter behaviour**

Change the From date to 30 days ago. Overview should refetch and the KPI values should change. Click an agency pill (e.g. AC) to remove it from the filter; click again to re-add. Type "51" in the search box; it should not throw (Overview doesn't consume search in 1a; Plan 1b will).

- [ ] **Step 5: Smoke-check selection**

Click a row in the worst-routes list. The row should highlight with a brand-coloured left border. React DevTools (if available) should show `SelectionContext.selection.routeId` set to that route id. No map yet — selection is internal-only in 1a.

- [ ] **Step 6: Sign off**

If any of steps 2–5 fail, file the issue and fix before merging Plan 1a. Otherwise this plan is complete.

---

## Verification (end-to-end)

After all tasks complete, an engineer joining the project should be able to:

1. **Install + test:**
   ```bash
   cd frontend && npm install && npm run test:run
   ```
   Expected: 22 tests pass.

2. **Run the dev server + dockerized backend:**
   ```bash
   docker compose up -d postgres backend
   cd frontend && npm run dev
   ```
   Open http://localhost:5173 and see the new shell with a populated Overview.

3. **Confirm the legacy code is still functional (for Plan 1b):**
   The unrendered `Sidebar.tsx`, `MapView.tsx`, `StopDrawer.tsx`, `AlertsBanner.tsx`, `BenchmarkPanel.tsx`, `AiAssistant.tsx` still type-check (`npm run build`). They aren't reachable from the new shell yet but are intact for Plan 1b to wire back in.

---

## What this plan does NOT do

Explicitly deferred:

- **Operations / Network / Equity & Safety / Benchmarks & Drift content** — Plan 1b
- **Map refactor + cross-filter wiring** — Plan 1b (MapView currently is not rendered by the new shell)
- **Stop drawer reintegration** — Plan 1b
- **Alerts banner reintegration** — Plan 1b
- **Route search behaviour** — Plan 1b (input exists but no consumer)
- **URL routing / saved views / CSV export / dark-light toggle** — Plan 1c
- **Agent rail enablement** — Phase 2 (per the spec; placeholder only in 1a)
- **Deletion of `Sidebar.tsx`** — Plan 1b once sections fully replace it

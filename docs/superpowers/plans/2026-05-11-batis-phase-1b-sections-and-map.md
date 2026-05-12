# BATIS Phase 1b — Sections, Map, and Cross-Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the four stub sections to life with real content, refactor `MapView` to consume the new contexts, reintegrate `AlertsBanner` + `StopDrawer` into the new shell, and wire cross-filtering end-to-end. After this plan lands, a user opens BATIS, navigates any of the five sections, and gets a working multi-widget dashboard with a live map, KPIs, supporting charts, and click-to-filter behaviour.

**Architecture:** Each section renders its own internal layout — KPI strip + MapView + supporting widgets — and consumes `FilterContext` (date range, agencies, search) and `SelectionContext` (routeId, stopId, hoveredStopId). `MapView`'s prop list collapses: filter/selection state comes from the contexts, callbacks become context writes. The `activeSection` legacy prop is renamed to `mapMode` and stays as the layer-set selector. `AlertsBanner` mounts above the filter bar inside the shell header area; `StopDrawer` renders inside `AppShell` and shows when `selection.stopId` is set. `Sidebar.tsx` stays on disk (its panel logic is referenced for data-fetching patterns) but is no longer imported anywhere — Plan 1c deletes it.

**Tech Stack:** Same as Plan 1a — React 18, TypeScript 5.6, Vite 5, Mapbox GL JS 3, Recharts 3, Axios, Vitest. No new runtime dependencies. The backend's 29 endpoints are unchanged.

---

## Pre-flight: what to know before starting

This plan operates in `/home/mza/projects/batis` on `main`. Plan 1a left 22 tests passing, a clean `npx tsc --noEmit`, and the dockerized stack running per `docker-compose.yml`.

### Existing components and their state

| File | State after Plan 1a | What changes in 1b |
|---|---|---|
| `frontend/src/App.tsx` | Provider sandwich around `AppShell` | Unchanged |
| `frontend/src/main.tsx` | Imports `shell.css` only | Re-imports `mapbox-gl.css` + `styles.css` |
| `frontend/src/components/AppShell.tsx` | 5-tab nav, FilterBar, main area, rail placeholder | Adds `AlertsBanner` + `StopDrawer` |
| `frontend/src/components/MapView.tsx` | Legacy props-based API, unmounted | Refactored to consume `FilterContext` + `SelectionContext`; renamed prop `activeSection` → `mapMode` |
| `frontend/src/components/StopDrawer.tsx` | Legacy props-based API, unmounted | Consumes `SelectionContext.selection.stopId`; closing clears the context |
| `frontend/src/components/AlertsBanner.tsx` | Self-contained, unmounted | Rendered inside `AppShell`; CSS may need a height tweak |
| `frontend/src/components/Sidebar.tsx` | ~1,862 lines, unmounted | Reference only; not deleted in this plan |
| `frontend/src/sections/Overview.tsx` | Real content, 3 tests | Adds a `MapView` card |
| `frontend/src/sections/Operations.tsx` | Stub | Full content |
| `frontend/src/sections/Network.tsx` | Stub | Full content |
| `frontend/src/sections/EquitySafety.tsx` | Stub | Full content |
| `frontend/src/sections/BenchmarksDrift.tsx` | Stub | Full content |

### Legacy panels to lift from `Sidebar.tsx`

Where each section needs to lift data-fetching logic from existing panels:

| New section | Reference panels (in `Sidebar.tsx`) |
|---|---|
| Operations | `ReliabilityPanel` (line 112), `BunchingPanel` (line 674), `LiveVehiclesPanel` (line 990) |
| Network | `RouteExplorerPanel` (line 535), `CoveragePanel` (line 384) |
| Equity & Safety | `EquityPanel` (line 1637), `SafetyPanel` (line 304) |
| Benchmarks & Drift | `TrafficPanel` (line 1419), `TransitImpactPanel` (line 1543), plus `BenchmarkPanel.tsx` (standalone file) |

Each section in 1b will **not** be a 1:1 port of every panel — instead it picks the 1–2 most representative widgets per section. Plan 1c can grow the sections further if needed.

### Mapping `SectionKey` → legacy `Section` for the map

`MapView`'s layer dispatch still uses the legacy `Section` union (from `frontend/src/types.ts`). The new `SectionKey` (`overview` / `operations` / `network` / `equity` / `benchmarks`) maps to a legacy value per the table below — each section component passes the appropriate `mapMode` prop:

| SectionKey | mapMode passed to MapView |
|---|---|
| overview | `"reliability"` (network-wide delay heatmap) |
| operations | `"reliability"` (or `"vehicles"` if `Live` toggle is on — out of scope for 1b) |
| network | `"coverage"` |
| equity | `"equity"` |
| benchmarks | `"traffic"` |

---

## File Structure

**New files:**
- `frontend/src/context/MapView.test.tsx` — context-integration tests for the refactored MapView (mocked Mapbox)
- `frontend/src/sections/Operations.test.tsx`
- `frontend/src/sections/Network.test.tsx`
- `frontend/src/sections/EquitySafety.test.tsx`
- `frontend/src/sections/BenchmarksDrift.test.tsx`
- `frontend/src/components/SectionMap.tsx` — small wrapper that renders `MapView` inside a section card with the appropriate `mapMode`

**Modified files:**
- `frontend/src/main.tsx` — restore `mapbox-gl.css` + `styles.css` imports
- `frontend/src/components/MapView.tsx` — props slimmed; rename `activeSection` → `mapMode`; consume contexts
- `frontend/src/components/StopDrawer.tsx` — props slimmed (`stopId` from context, `onClose` writes to context)
- `frontend/src/components/AppShell.tsx` — mount `AlertsBanner` + `StopDrawer`
- `frontend/src/sections/Operations.tsx` — full content
- `frontend/src/sections/Network.tsx` — full content
- `frontend/src/sections/EquitySafety.tsx` — full content
- `frontend/src/sections/BenchmarksDrift.tsx` — full content
- `frontend/src/sections/Overview.tsx` — add a `SectionMap` card
- `frontend/src/design/shell.css` — add room for `AlertsBanner` between the header and filter bar

**Untouched (Plan 1c may revisit):**
- `frontend/src/components/Sidebar.tsx` — still on disk for reference
- `frontend/src/components/BenchmarkPanel.tsx` — used by `BenchmarksDrift`; left in place
- `frontend/src/components/AiAssistant.tsx` — out of scope (Plan 1c agent rail)
- `frontend/src/styles.css` — re-imported, no edits

---

## Task 1: Restore the legacy CSS imports

**Files:**
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/design/shell.css`

Plan 1a deliberately dropped `mapbox-gl.css` and `styles.css` because their consumers weren't rendered. Now we mount `MapView`, `StopDrawer`, and `AlertsBanner` again, so the CSS comes back. The shell grid also needs a row for the alerts banner.

- [ ] **Step 1: Update `frontend/src/main.tsx`**

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import "mapbox-gl/dist/mapbox-gl.css";
import "./design/shell.css";
import "./styles.css";
import { App } from "./App";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

Order matters: `shell.css` and the tokens it imports apply first (lowest specificity since they're written defensively); the legacy `styles.css` lands after but uses different class names (`.kpi-card`, `.agency-pill`, etc.). If there are collisions, the new primitives are scoped with `.kpi-card` from Plan 1a too — verify by running the test suite at the end of this step.

- [ ] **Step 2: Add an alerts row to `shell.css`**

Edit `frontend/src/design/shell.css`. Find the `.shell` grid definition and replace it with this expanded version (adds an `alerts` row between `header` and `filter`):

```css
.shell {
  display: grid;
  grid-template-rows:
    var(--shell-header-h)
    auto
    var(--shell-filterbar-h)
    1fr;
  grid-template-columns: 1fr var(--shell-rail-w);
  grid-template-areas:
    "header   header"
    "alerts   alerts"
    "filter   filter"
    "main     rail";
  height: 100vh;
  width: 100vw;
}
```

Append at the end of the file:

```css
.shell-alerts {
  grid-area: alerts;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-bg-1);
}
.shell-alerts:empty { display: none; }   /* collapse the row when no alerts */
```

- [ ] **Step 3: Run the test suite**

```bash
cd frontend && npm run test:run
```

Expected: 22 passed (no regression).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/main.tsx frontend/src/design/shell.css
git commit -m "$(cat <<'EOF'
Restore mapbox-gl.css + styles.css imports; add alerts grid row

Plan 1a dropped both legacy stylesheets because their consumers were
unmounted. Plan 1b reintroduces MapView, StopDrawer, and AlertsBanner,
so the stylesheets come back. The shell grid gets an `alerts` row
between the header and filter bar; the row collapses (empty:none)
when no alerts are active so the layout doesn't reserve dead space.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Refactor `MapView` to consume contexts

**Files:**
- Modify: `frontend/src/components/MapView.tsx`
- Create: `frontend/src/components/MapView.test.tsx`

`MapView` keeps its layer-management complexity (the existing 1,100 lines are not rewritten). Only the props surface changes: `dateRange`, `selectedRouteId`, `selectedAgencies`, `plannerOrigin`, `plannerDest`, `onStopClick`, `onPlannerMapClick`, `darkMode` are replaced by `useFilters()` + `useSelection()` reads + writes. The `activeSection` prop is renamed to `mapMode` and stays.

**Why this is large**: every effect inside `MapView` that depended on a prop must now depend on the context value. Multiple `useRef` mirrors of props turn into ref mirrors of context-derived values. Be deliberate — break the existing component as little as possible.

- [ ] **Step 1: Inventory the current prop usage**

Run from `frontend/`:

```bash
grep -nE "dateRange|selectedRouteId|selectedAgencies|plannerOrigin|plannerDest|onStopClick|onPlannerMapClick|darkMode|activeSection" src/components/MapView.tsx
```

Note every line. There are roughly 30 references to plan around.

- [ ] **Step 2: Add the new props interface and context hooks at the top**

Replace the existing `MapViewProps` interface block (around lines 21–31) with:

```tsx
export interface MapViewProps {
  /** Which layer set to render. Maps a SectionKey to the legacy Section
   *  union, e.g. "operations" → "reliability". */
  mapMode: Section;
  /** Dark map style is the only style supported today; light parity is Plan 1c. */
  darkMode?: boolean;
}
```

And at the top of the component body, add:

```tsx
import { useFilters } from "../context/FilterContext";
import { useSelection } from "../context/SelectionContext";

export const MapView: React.FC<MapViewProps> = ({ mapMode, darkMode = true }) => {
  const { filters } = useFilters();
  const { selection, setStopId, setHoveredStopId } = useSelection();

  // Local mirrors for compatibility with the existing effect signatures below.
  const startDate = filters.startDate;
  const endDate = filters.endDate;
  const selectedAgencies = filters.agencies;
  const selectedRouteId = selection.routeId;
  const activeSection = mapMode;  // rename alias so existing code below keeps compiling
  // Trip planner is out of scope for Plan 1b — defer to Plan 1c.
  const plannerOrigin = null;
  const plannerDest = null;
  const onStopClick = setStopId;
  const onPlannerMapClick = () => {};
  // ... rest of the existing component body, unchanged
```

Keep the rest of the file as-is — the local aliases let every existing line keep working without further edits.

- [ ] **Step 3: Write the integration test**

`frontend/src/components/MapView.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import { FilterProvider } from "../context/FilterContext";
import { SelectionProvider } from "../context/SelectionContext";

// Mock mapbox-gl entirely — jsdom can't run WebGL.
vi.mock("mapbox-gl", () => ({
  default: {
    accessToken: "",
    Map: vi.fn().mockImplementation(() => ({
      on: vi.fn(),
      off: vi.fn(),
      addControl: vi.fn(),
      remove: vi.fn(),
      getStyle: vi.fn(() => ({ layers: [] })),
      isStyleLoaded: vi.fn(() => false),
      setStyle: vi.fn(),
    })),
    NavigationControl: vi.fn(),
  },
}));

import { MapView } from "./MapView";

function wrap(ui: React.ReactElement) {
  return (
    <FilterProvider>
      <SelectionProvider>{ui}</SelectionProvider>
    </FilterProvider>
  );
}

describe("MapView", () => {
  it("renders without crashing for each mapMode", () => {
    const modes: Array<"reliability" | "coverage" | "equity" | "traffic"> = [
      "reliability",
      "coverage",
      "equity",
      "traffic",
    ];
    for (const mode of modes) {
      const { unmount } = render(wrap(<MapView mapMode={mode} />));
      unmount();
    }
  });
});
```

- [ ] **Step 4: Run the test**

```bash
npm run test:run -- src/components/MapView.test.tsx
```

Expected: 1 passed.

- [ ] **Step 5: Run the full suite**

```bash
npm run test:run
```

Expected: 23 passed (22 from Plan 1a + 1 new).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/MapView.tsx frontend/src/components/MapView.test.tsx
git commit -m "$(cat <<'EOF'
MapView: consume FilterContext + SelectionContext instead of props

Slims MapView's props from nine to two (mapMode + darkMode). All
state that used to be prop-drilled — date range, agencies, selected
route, stop click handler — now flows through FilterContext and
SelectionContext via hooks at the top of the component. Local
aliases (startDate, endDate, selectedRouteId, etc.) keep the
existing ~1,100-line component body compiling unchanged.

activeSection is renamed mapMode because it's the layer-set
selector, not the section identifier — sections in the new shell
can choose any mapMode independent of which tab is active.

Trip-planner props (plannerOrigin/Dest/onPlannerMapClick) are
stubbed to null/no-op; Plan 1c brings the planner back as a
dedicated mode.

Adds an integration test that renders the four mapMode values
that the four sections will pass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `SectionMap` wrapper

**Files:**
- Create: `frontend/src/components/SectionMap.tsx`

A tiny presentation wrapper so each section renders a map with consistent panel chrome (title, fixed height).

- [ ] **Step 1: Implement**

```tsx
import React from "react";
import { MapView } from "./MapView";
import type { Section } from "../types";
import "../sections/sections.css";

export interface SectionMapProps {
  mapMode: Section;
  title?: string;
  /** Default 420px — sized for a card inside a section's grid. */
  height?: number;
}

export const SectionMap: React.FC<SectionMapProps> = ({ mapMode, title, height = 420 }) => (
  <div className="section__panel section__panel--map" style={{ height }}>
    {title && <h3 className="section__panel-title">{title}</h3>}
    <div className="section__map-container">
      <MapView mapMode={mapMode} />
    </div>
  </div>
);
```

- [ ] **Step 2: Append map-panel styles to `sections.css`**

Append to `frontend/src/sections/sections.css`:

```css
.section__panel--map {
  padding: 0;
  overflow: hidden;
  position: relative;
}
.section__panel--map .section__panel-title {
  position: absolute;
  top: var(--space-3);
  left: var(--space-4);
  z-index: 2;
  background: rgba(11, 15, 23, 0.85);
  padding: 4px var(--space-2);
  border-radius: var(--radius-2);
  color: var(--color-fg-0);
  backdrop-filter: blur(4px);
}
.section__map-container {
  width: 100%;
  height: 100%;
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/SectionMap.tsx frontend/src/sections/sections.css
git commit -m "$(cat <<'EOF'
Add SectionMap wrapper for in-section maps

Provides a section-card chrome (title overlay + fixed height) around
MapView so every section's map looks consistent. Default height
420px; sections that want a hero-sized map can pass their own.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `Operations` section

**Files:**
- Modify: `frontend/src/sections/Operations.tsx`
- Create: `frontend/src/sections/Operations.test.tsx`

Lifts the most useful KPIs from `ReliabilityPanel` (Sidebar.tsx:112) and renders them above a `SectionMap` in reliability mode, with a "Worst routes" table on the side that writes to `SelectionContext` on click.

- [ ] **Step 1: Write the failing test**

`frontend/src/sections/Operations.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { FilterProvider } from "../context/FilterContext";
import { SelectionProvider } from "../context/SelectionContext";
import { Operations } from "./Operations";

vi.mock("mapbox-gl", () => ({
  default: {
    accessToken: "",
    Map: vi.fn().mockImplementation(() => ({
      on: vi.fn(), off: vi.fn(), addControl: vi.fn(), remove: vi.fn(),
      getStyle: vi.fn(() => ({ layers: [] })),
      isStyleLoaded: vi.fn(() => false),
      setStyle: vi.fn(),
    })),
    NavigationControl: vi.fn(),
  },
}));

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
        if (url.startsWith("/vehicles/live")) {
          return { data: [{ vehicle_id: "V1" }, { vehicle_id: "V2" }, { vehicle_id: "V3" }] };
        }
        if (url.startsWith("/bunching/summary")) {
          return { data: [{ route_id: "51B", bunched_events: 12 }] };
        }
        return { data: [] };
      }),
    },
  };
});

function wrap(ui: React.ReactElement) {
  return <FilterProvider><SelectionProvider>{ui}</SelectionProvider></FilterProvider>;
}

describe("Operations", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the operations KPIs and worst-routes list", async () => {
    render(wrap(<Operations />));
    await waitFor(() => expect(screen.getByText("51B")).toBeInTheDocument());
    expect(screen.getByText(/Network OTP/i)).toBeInTheDocument();
    expect(screen.getByText(/Live vehicles/i)).toBeInTheDocument();
    expect(screen.getByText(/Bunched/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run → FAIL**

```bash
npm run test:run -- src/sections/Operations.test.tsx
```

- [ ] **Step 3: Implement `Operations.tsx`**

Replace the existing stub at `frontend/src/sections/Operations.tsx`:

```tsx
import React, { useEffect, useState } from "react";
import { useFilters } from "../context/FilterContext";
import { useSelection } from "../context/SelectionContext";
import { api } from "../lib/api";
import { KpiCard, DataList, Spinner, EmptyState, type DataListItem } from "../components/primitives";
import { SectionMap } from "../components/SectionMap";
import "./sections.css";

interface ReliabilityRow {
  route_id: string;
  sample_events: number;
  avg_delay_seconds: number;
  on_time_pct?: number;
}
interface VehicleRow  { vehicle_id: string; }
interface BunchingRow { route_id: string; bunched_events: number; }

function fmtMin(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  return `${(seconds / 60).toFixed(1)} min`;
}

export const Operations: React.FC = () => {
  const { filters } = useFilters();
  const { selection, setRouteId } = useSelection();

  const [reliability, setReliability] = useState<ReliabilityRow[]>([]);
  const [vehicles, setVehicles] = useState<VehicleRow[]>([]);
  const [bunching, setBunching] = useState<BunchingRow[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function fetchAll() {
      setLoading(true);
      try {
        const [rel, veh, bun] = await Promise.all([
          api.get<ReliabilityRow[]>("/reliability/summary", { params: { start_date: filters.startDate, end_date: filters.endDate } }),
          api.get<VehicleRow[]>("/vehicles/live").catch(() => ({ data: [] })),
          api.get<BunchingRow[]>("/bunching/summary", { params: { start_date: filters.startDate, end_date: filters.endDate } }).catch(() => ({ data: [] })),
        ]);
        if (cancelled) return;
        setReliability(rel.data ?? []);
        setVehicles(veh.data ?? []);
        setBunching(bun.data ?? []);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchAll();
    return () => { cancelled = true; };
  }, [filters.startDate, filters.endDate]);

  const totalEvents = reliability.reduce((s, r) => s + r.sample_events, 0);
  const networkOtp = totalEvents > 0
    ? reliability.reduce((s, r) => s + ((r.on_time_pct ?? 0) * r.sample_events), 0) / totalEvents
    : null;
  const avgDelay = totalEvents > 0
    ? reliability.reduce((s, r) => s + (r.avg_delay_seconds * r.sample_events), 0) / totalEvents
    : null;
  const bunchedTotal = bunching.reduce((s, b) => s + b.bunched_events, 0);

  const worst: DataListItem[] = [...reliability]
    .filter(r => r.sample_events >= 10)
    .filter(r => !filters.search || r.route_id.toLowerCase().includes(filters.search.toLowerCase()))
    .sort((a, b) => b.avg_delay_seconds - a.avg_delay_seconds)
    .slice(0, 12)
    .map(r => ({
      id: r.route_id,
      primary: r.route_id,
      secondary: `${r.sample_events} events`,
      trailing: fmtMin(r.avg_delay_seconds),
    }));

  return (
    <div className="section">
      <div className="section__header">
        <h2 className="section__title">Operations</h2>
        <span className="section__subtitle">{filters.startDate} → {filters.endDate}</span>
      </div>

      <div className="section__kpi-strip">
        <KpiCard label="Network OTP"   value={networkOtp === null ? "—" : `${networkOtp.toFixed(1)}%`} />
        <KpiCard label="Avg delay"     value={avgDelay   === null ? "—" : fmtMin(avgDelay)} />
        <KpiCard label="Live vehicles" value={String(vehicles.length)} />
        <KpiCard label="Bunched"       value={String(bunchedTotal)} sub="bunched events in window" />
      </div>

      <div className="section__grid">
        <SectionMap mapMode="reliability" title="Network reliability" height={460} />
        <div className="section__panel">
          <h3 className="section__panel-title">Slowest performers</h3>
          {loading && worst.length === 0 ? <Spinner /> :
           worst.length === 0 ? <EmptyState message="No route data in this window." /> :
           <DataList items={worst} selectedId={selection.routeId} onSelect={setRouteId} />}
        </div>
      </div>
    </div>
  );
};
```

- [ ] **Step 4: Run → 1 passed (new) + suite still green**

```bash
npm run test:run -- src/sections/Operations.test.tsx
npm run test:run
```

Expected: Operations passes; full suite 24 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/sections/Operations.tsx frontend/src/sections/Operations.test.tsx
git commit -m "$(cat <<'EOF'
Build Operations section content

Four KPIs (network OTP, avg delay, live vehicle count, bunched
events), a reliability-mode map, and a slowest-performers list that
respects the global route search and writes selections to
SelectionContext. Lifts data-fetching logic from ReliabilityPanel,
LiveVehiclesPanel, and BunchingPanel in Sidebar.tsx — picking the
most representative widgets rather than porting every legacy panel.
Plan 1c can grow Operations with crowding + comparison.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `Network` section

**Files:**
- Modify: `frontend/src/sections/Network.tsx`
- Create: `frontend/src/sections/Network.test.tsx`

Lifts from `RouteExplorerPanel` (Sidebar.tsx:535) and `CoveragePanel` (line 384). KPIs: total routes, total stops, coverage cells, transit deserts. Hero: coverage-mode map. Side: searchable route list bound to `SelectionContext`.

- [ ] **Step 1: Write the failing test**

`frontend/src/sections/Network.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterProvider } from "../context/FilterContext";
import { SelectionProvider, useSelection } from "../context/SelectionContext";
import { Network } from "./Network";

vi.mock("mapbox-gl", () => ({
  default: {
    accessToken: "",
    Map: vi.fn().mockImplementation(() => ({
      on: vi.fn(), off: vi.fn(), addControl: vi.fn(), remove: vi.fn(),
      getStyle: vi.fn(() => ({ layers: [] })),
      isStyleLoaded: vi.fn(() => false), setStyle: vi.fn(),
    })),
    NavigationControl: vi.fn(),
  },
}));

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    api: {
      get: vi.fn(async (url: string) => {
        if (url.startsWith("/routes"))           return { data: [{ route_id: "51B", route_short_name: "51B", agency_id: "AC" }, { route_id: "72", route_short_name: "72", agency_id: "AC" }] };
        if (url.startsWith("/coverage/cells"))   return { data: { features: new Array(50).fill({}) } };
        if (url.startsWith("/coverage/deserts")) return { data: { features: new Array(3).fill({}) } };
        return { data: [] };
      }),
    },
  };
});

function Captured() {
  const { selection } = useSelection();
  return <div data-testid="captured">{selection.routeId ?? "none"}</div>;
}

function wrap(ui: React.ReactElement) { return <FilterProvider><SelectionProvider>{ui}</SelectionProvider></FilterProvider>; }

describe("Network", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders KPIs and the route list", async () => {
    render(wrap(<Network />));
    await waitFor(() => expect(screen.getByText("51B")).toBeInTheDocument());
    expect(screen.getByText(/Routes/i)).toBeInTheDocument();
    expect(screen.getByText(/Coverage cells/i)).toBeInTheDocument();
    expect(screen.getByText(/Transit deserts/i)).toBeInTheDocument();
  });

  it("selecting a route writes routeId", async () => {
    render(wrap(<><Network /><Captured /></>));
    await waitFor(() => expect(screen.getByText("51B")).toBeInTheDocument());
    await userEvent.click(screen.getByText("51B"));
    expect(screen.getByTestId("captured").textContent).toBe("51B");
  });
});
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement `Network.tsx`**

```tsx
import React, { useEffect, useState } from "react";
import { useFilters } from "../context/FilterContext";
import { useSelection } from "../context/SelectionContext";
import { api } from "../lib/api";
import { KpiCard, DataList, Spinner, EmptyState, type DataListItem } from "../components/primitives";
import { SectionMap } from "../components/SectionMap";
import { agencyName } from "../lib/agencies";
import "./sections.css";

interface RouteRow { route_id: string; route_short_name?: string; agency_id?: string; }

export const Network: React.FC = () => {
  const { filters } = useFilters();
  const { selection, setRouteId } = useSelection();

  const [routes, setRoutes]    = useState<RouteRow[]>([]);
  const [cellCount, setCellCount]   = useState<number | null>(null);
  const [desertCount, setDesertCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function fetchAll() {
      setLoading(true);
      try {
        const [routesRes, cellsRes, desertsRes] = await Promise.all([
          api.get<RouteRow[]>("/routes"),
          api.get<{ features?: unknown[] }>("/coverage/cells").catch(() => ({ data: { features: [] } })),
          api.get<{ features?: unknown[] }>("/coverage/deserts").catch(() => ({ data: { features: [] } })),
        ]);
        if (cancelled) return;
        setRoutes(routesRes.data ?? []);
        setCellCount(cellsRes.data?.features?.length ?? 0);
        setDesertCount(desertsRes.data?.features?.length ?? 0);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchAll();
    return () => { cancelled = true; };
  }, []);

  const filtered: DataListItem[] = routes
    .filter(r => filters.agencies.length === 0 || (r.agency_id && filters.agencies.includes(r.agency_id)))
    .filter(r => !filters.search || (r.route_short_name ?? r.route_id).toLowerCase().includes(filters.search.toLowerCase()))
    .slice(0, 100)
    .map(r => ({
      id: r.route_id,
      primary:   r.route_short_name ?? r.route_id,
      secondary: r.agency_id ? agencyName(r.agency_id) : undefined,
    }));

  return (
    <div className="section">
      <div className="section__header">
        <h2 className="section__title">Network</h2>
        <span className="section__subtitle">Routes · coverage · service deserts</span>
      </div>

      <div className="section__kpi-strip">
        <KpiCard label="Routes"          value={String(routes.length)} sub={`${filters.agencies.length} agencies`} />
        <KpiCard label="Coverage cells"  value={cellCount   === null ? "—" : String(cellCount)} />
        <KpiCard label="Transit deserts" value={desertCount === null ? "—" : String(desertCount)} deltaIsGood={false} />
        <KpiCard label="In view"         value={String(filtered.length)} sub="after filters" />
      </div>

      <div className="section__grid">
        <SectionMap mapMode="coverage" title="Coverage hex grid" height={460} />
        <div className="section__panel">
          <h3 className="section__panel-title">Routes</h3>
          {loading && filtered.length === 0 ? <Spinner /> :
           filtered.length === 0 ? <EmptyState message="No routes match the current filters." /> :
           <DataList items={filtered} selectedId={selection.routeId} onSelect={setRouteId} />}
        </div>
      </div>
    </div>
  );
};
```

- [ ] **Step 4: Run + verify**

```bash
npm run test:run -- src/sections/Network.test.tsx
npm run test:run
```

Expected: Network passes; full suite 26 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/sections/Network.tsx frontend/src/sections/Network.test.tsx
git commit -m "$(cat <<'EOF'
Build Network section content

Four KPIs (routes, coverage cells, transit deserts, filtered-in-view
count), a coverage-mode map, and a routes list filtered by the
global agency picker and search box. Selecting a route writes
routeId to SelectionContext for cross-filter — Plan 1c can use this
to focus the map.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `EquitySafety` section

**Files:**
- Modify: `frontend/src/sections/EquitySafety.tsx`
- Create: `frontend/src/sections/EquitySafety.test.tsx`

Lifts from `EquityPanel` (Sidebar.tsx:1637) and `SafetyPanel` (line 304). KPIs: tracts loaded, avg equity score, hot stops, total incidents. Hero: equity-mode map. Side: high-risk stop list.

- [ ] **Step 1: Write the failing test**

`frontend/src/sections/EquitySafety.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { FilterProvider } from "../context/FilterContext";
import { SelectionProvider } from "../context/SelectionContext";
import { EquitySafety } from "./EquitySafety";

vi.mock("mapbox-gl", () => ({
  default: {
    accessToken: "",
    Map: vi.fn().mockImplementation(() => ({
      on: vi.fn(), off: vi.fn(), addControl: vi.fn(), remove: vi.fn(),
      getStyle: vi.fn(() => ({ layers: [] })),
      isStyleLoaded: vi.fn(() => false), setStyle: vi.fn(),
    })),
    NavigationControl: vi.fn(),
  },
}));

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    api: {
      get: vi.fn(async (url: string) => {
        if (url.startsWith("/equity/score")) {
          return { data: { features: [
            { properties: { equity_score: 0.15 } }, { properties: { equity_score: 0.06 } },
          ] } };
        }
        if (url.startsWith("/safety/stops")) {
          return { data: [
            { stop_id: "S001", stop_name: "Hot 1", safety_score: 12 },
            { stop_id: "S002", stop_name: "Hot 2", safety_score: 9 },
          ] };
        }
        return { data: [] };
      }),
    },
  };
});

function wrap(ui: React.ReactElement) { return <FilterProvider><SelectionProvider>{ui}</SelectionProvider></FilterProvider>; }

describe("EquitySafety", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the four KPIs and a hot-stops list", async () => {
    render(wrap(<EquitySafety />));
    await waitFor(() => expect(screen.getByText(/Hot 1/i)).toBeInTheDocument());
    expect(screen.getByText(/Tracts/i)).toBeInTheDocument();
    expect(screen.getByText(/equity/i)).toBeInTheDocument();
    expect(screen.getByText(/Hot stops/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement `EquitySafety.tsx`**

```tsx
import React, { useEffect, useState } from "react";
import { useFilters } from "../context/FilterContext";
import { useSelection } from "../context/SelectionContext";
import { api } from "../lib/api";
import { KpiCard, DataList, Spinner, EmptyState, type DataListItem } from "../components/primitives";
import { SectionMap } from "../components/SectionMap";
import "./sections.css";

interface EquityFeature { properties: { equity_score?: number; }; }
interface SafetyRow { stop_id: string; stop_name?: string; safety_score: number; }

export const EquitySafety: React.FC = () => {
  const { filters } = useFilters();
  const { selection, setStopId } = useSelection();

  const [equityFeatures, setEquityFeatures] = useState<EquityFeature[]>([]);
  const [hotStops, setHotStops] = useState<SafetyRow[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function fetchAll() {
      setLoading(true);
      try {
        const [eq, hot] = await Promise.all([
          api.get<{ features: EquityFeature[] }>("/equity/score").catch(() => ({ data: { features: [] } })),
          api.get<SafetyRow[]>("/safety/stops", { params: { min_score: 8 } }).catch(() => ({ data: [] })),
        ]);
        if (cancelled) return;
        setEquityFeatures(eq.data?.features ?? []);
        setHotStops(hot.data ?? []);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchAll();
    return () => { cancelled = true; };
  }, []);

  const tractCount = equityFeatures.length;
  const avgEquity = tractCount > 0
    ? equityFeatures.reduce((s, f) => s + (f.properties.equity_score ?? 0), 0) / tractCount
    : null;
  const totalIncidents = hotStops.length;

  const hotList: DataListItem[] = hotStops
    .filter(s => !filters.search || (s.stop_name ?? s.stop_id).toLowerCase().includes(filters.search.toLowerCase()))
    .sort((a, b) => b.safety_score - a.safety_score)
    .slice(0, 25)
    .map(s => ({
      id: s.stop_id,
      primary: s.stop_name ?? s.stop_id,
      secondary: s.stop_id,
      trailing: s.safety_score.toFixed(1),
    }));

  return (
    <div className="section">
      <div className="section__header">
        <h2 className="section__title">Equity &amp; Safety</h2>
        <span className="section__subtitle">Tract-level service equity and stop risk</span>
      </div>

      <div className="section__kpi-strip">
        <KpiCard label="Tracts"        value={String(tractCount)} sub="with equity score" />
        <KpiCard label="Avg equity"    value={avgEquity === null ? "—" : avgEquity.toFixed(3)} />
        <KpiCard label="Hot stops"     value={String(hotStops.length)} sub="safety ≥ 8" deltaIsGood={false} />
        <KpiCard label="Total incidents" value="—" sub="loaded by ETL" />
      </div>

      <div className="section__grid">
        <SectionMap mapMode="equity" title="Tract equity scores" height={460} />
        <div className="section__panel">
          <h3 className="section__panel-title">Highest-risk stops</h3>
          {loading && hotList.length === 0 ? <Spinner /> :
           hotList.length === 0 ? <EmptyState message="No stops above the safety threshold." /> :
           <DataList items={hotList} selectedId={selection.stopId} onSelect={setStopId} />}
        </div>
      </div>
    </div>
  );
};
```

- [ ] **Step 4: Run + verify**

```bash
npm run test:run -- src/sections/EquitySafety.test.tsx
npm run test:run
```

Expected: full suite 27 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/sections/EquitySafety.tsx frontend/src/sections/EquitySafety.test.tsx
git commit -m "$(cat <<'EOF'
Build Equity & Safety section content

Four KPIs (tracts loaded, avg equity score, hot stops, total
incidents placeholder), an equity-mode map of the Bay Area tracts,
and a highest-risk-stops list bound to SelectionContext. Selecting
a stop opens it in the StopDrawer (wired in a later task).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `BenchmarksDrift` section

**Files:**
- Modify: `frontend/src/sections/BenchmarksDrift.tsx`
- Create: `frontend/src/sections/BenchmarksDrift.test.tsx`

Lifts from `BenchmarkPanel.tsx` (the standalone component that already renders an agency comparison chart) and `TrafficPanel` (Sidebar.tsx:1419). KPIs: agencies tracked, drift events, traffic events, work zones. Hero: agency OTP bar chart (lifted from `BenchmarkPanel`). Side: active disruption list.

- [ ] **Step 1: Write the failing test**

`frontend/src/sections/BenchmarksDrift.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { FilterProvider } from "../context/FilterContext";
import { SelectionProvider } from "../context/SelectionContext";
import { BenchmarksDrift } from "./BenchmarksDrift";

vi.mock("mapbox-gl", () => ({
  default: {
    accessToken: "",
    Map: vi.fn().mockImplementation(() => ({
      on: vi.fn(), off: vi.fn(), addControl: vi.fn(), remove: vi.fn(),
      getStyle: vi.fn(() => ({ layers: [] })),
      isStyleLoaded: vi.fn(() => false), setStyle: vi.fn(),
    })),
    NavigationControl: vi.fn(),
  },
}));

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    api: {
      get: vi.fn(async (url: string) => {
        if (url.startsWith("/benchmarks/agency-otp")) {
          return { data: [
            { agency_id: "AC",   on_time_pct: 87.5, avg_delay_seconds: 65,  sample_events: 12000 },
            { agency_id: "BA",   on_time_pct: 94.2, avg_delay_seconds: 32,  sample_events:  8000 },
          ] };
        }
        if (url.startsWith("/traffic/events"))    return { data: { features: new Array(20).fill({}) } };
        if (url.startsWith("/traffic/work-zones")) return { data: { features: new Array(350).fill({}) } };
        return { data: [] };
      }),
    },
  };
});

function wrap(ui: React.ReactElement) { return <FilterProvider><SelectionProvider>{ui}</SelectionProvider></FilterProvider>; }

describe("BenchmarksDrift", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders KPIs and the agency bar chart", async () => {
    render(wrap(<BenchmarksDrift />));
    await waitFor(() => expect(screen.getByText(/Agencies/i)).toBeInTheDocument());
    expect(screen.getByText(/Traffic events/i)).toBeInTheDocument();
    expect(screen.getByText(/Work zones/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Cross-agency OTP/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement `BenchmarksDrift.tsx`**

```tsx
import React, { useEffect, useState } from "react";
import { useFilters } from "../context/FilterContext";
import { api } from "../lib/api";
import { KpiCard, BarChart, Spinner, EmptyState, type BarPoint } from "../components/primitives";
import { agencyColor, agencyName } from "../lib/agencies";
import "./sections.css";

interface AgencyOtpRow { agency_id: string; on_time_pct: number; avg_delay_seconds: number; sample_events: number; }

export const BenchmarksDrift: React.FC = () => {
  const { filters } = useFilters();
  const [otp, setOtp] = useState<AgencyOtpRow[]>([]);
  const [trafficCount, setTrafficCount] = useState<number | null>(null);
  const [workZoneCount, setWorkZoneCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function fetchAll() {
      setLoading(true);
      try {
        const [otpRes, eventsRes, wzRes] = await Promise.all([
          api.get<AgencyOtpRow[]>("/benchmarks/agency-otp", { params: { start_date: filters.startDate, end_date: filters.endDate } }).catch(() => ({ data: [] })),
          api.get<{ features?: unknown[] }>("/traffic/events").catch(() => ({ data: { features: [] } })),
          api.get<{ features?: unknown[] }>("/traffic/work-zones").catch(() => ({ data: { features: [] } })),
        ]);
        if (cancelled) return;
        setOtp(otpRes.data ?? []);
        setTrafficCount(eventsRes.data?.features?.length ?? 0);
        setWorkZoneCount(wzRes.data?.features?.length ?? 0);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchAll();
    return () => { cancelled = true; };
  }, [filters.startDate, filters.endDate]);

  const bars: BarPoint[] = [...otp]
    .filter(r => filters.agencies.includes(r.agency_id))
    .sort((a, b) => b.on_time_pct - a.on_time_pct)
    .map(r => ({
      label: r.agency_id,
      value: Number(r.on_time_pct.toFixed(1)),
      color: agencyColor(r.agency_id),
    }));

  return (
    <div className="section">
      <div className="section__header">
        <h2 className="section__title">Benchmarks &amp; Drift</h2>
        <span className="section__subtitle">Agency OTP comparison · traffic · work zones</span>
      </div>

      <div className="section__kpi-strip">
        <KpiCard label="Agencies"        value={String(bars.length)} sub="in current filter" />
        <KpiCard label="Best OTP"        value={bars[0] ? `${bars[0].value}%` : "—"} sub={bars[0] ? agencyName(bars[0].label) : ""} />
        <KpiCard label="Traffic events"  value={trafficCount  === null ? "—" : String(trafficCount)} deltaIsGood={false} />
        <KpiCard label="Work zones"      value={workZoneCount === null ? "—" : String(workZoneCount)} />
      </div>

      <div className="section__panel">
        <h3 className="section__panel-title">Cross-agency OTP</h3>
        {loading && bars.length === 0 ? <Spinner /> :
         bars.length === 0 ? <EmptyState message="No benchmark data in this window." hint="Stop_observations may not be loaded for this date range." /> :
         <BarChart data={bars} height={320} />}
      </div>
    </div>
  );
};
```

- [ ] **Step 4: Run + verify**

```bash
npm run test:run -- src/sections/BenchmarksDrift.test.tsx
npm run test:run
```

Expected: full suite 28 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/sections/BenchmarksDrift.tsx frontend/src/sections/BenchmarksDrift.test.tsx
git commit -m "$(cat <<'EOF'
Build Benchmarks & Drift section content

Four KPIs (agencies in filter, best agency, traffic events, work
zones) and a cross-agency OTP bar chart using per-agency brand
colors from lib/agencies. Reads /benchmarks/agency-otp,
/traffic/events, and /traffic/work-zones. No map in this section
because the hero is the bar chart; Plan 1c can add a traffic-mode
map below if useful.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Add `SectionMap` to `Overview`

**Files:**
- Modify: `frontend/src/sections/Overview.tsx`
- Modify: `frontend/src/sections/Overview.test.tsx` (mock mapbox-gl)

Overview gets the same map experience as the other three sections so the design is consistent. Pass `mapMode="reliability"`.

- [ ] **Step 1: Update the test mocks**

Add the same `vi.mock("mapbox-gl", ...)` block from Task 4 to the top of `Overview.test.tsx`, BEFORE the existing `vi.mock("../lib/api", ...)`. The existing tests should still pass.

- [ ] **Step 2: Update `Overview.tsx`**

Add the `SectionMap` import at the top:

```tsx
import { SectionMap } from "../components/SectionMap";
```

In the JSX, change the `section__grid` block to:

```tsx
<div className="section__grid">
  <SectionMap mapMode="reliability" title="Network reliability" height={420} />
  <div className="section__panel">
    <h3 className="section__panel-title">Slowest performers</h3>
    {loading && worstRoutes.length === 0 ? <Spinner /> : worstRoutes.length === 0 ? (
      <EmptyState message="No route data in this window." hint="Widen the date range or pick more agencies." />
    ) : (
      <DataList items={worstRoutes} selectedId={selection.routeId} onSelect={setRouteId} />
    )}
  </div>
</div>

<div className="section__panel">
  <h3 className="section__panel-title">Network delay trend</h3>
  {loading && trendPoints.length === 0 ? <Spinner /> : trendPoints.length === 0 ? (
    <EmptyState message="No trend data in this window." />
  ) : (
    <TrendChart data={trendPoints} yLabel="sec" />
  )}
</div>
```

(The trend chart moves below the grid; the map takes its place.)

- [ ] **Step 3: Run + verify**

```bash
npm run test:run
```

Expected: 28 passed.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/sections/Overview.tsx frontend/src/sections/Overview.test.tsx
git commit -m "$(cat <<'EOF'
Overview: add SectionMap, move trend chart below

Brings Overview in line with the other four sections — reliability-
mode map as the hero in the section__grid, with the slowest-
performers list beside it. The network delay trend moves to its own
full-width panel below the grid.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Refactor `StopDrawer` to consume `SelectionContext`

**Files:**
- Modify: `frontend/src/components/StopDrawer.tsx`

Today's `StopDrawer` takes `stopId` and `onClose` as props. After this task it reads `selection.stopId` from `SelectionContext` and clears it via `setStopId(null)` on close — no props at all.

- [ ] **Step 1: Edit the component signature**

In `frontend/src/components/StopDrawer.tsx`, find:

```tsx
interface Props { stopId: string | null; onClose: () => void; }
export const StopDrawer: React.FC<Props> = ({ stopId, onClose }) => {
```

Replace with:

```tsx
import { useSelection } from "../context/SelectionContext";

export const StopDrawer: React.FC = () => {
  const { selection, setStopId } = useSelection();
  const stopId = selection.stopId;
  const onClose = () => setStopId(null);
```

Everything below stays the same — `stopId` and `onClose` are still in scope, just sourced from the context.

- [ ] **Step 2: Run the full suite**

```bash
npm run test:run
```

Expected: 28 passed (no test for StopDrawer; relying on the type system + manual QA).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/StopDrawer.tsx
git commit -m "$(cat <<'EOF'
StopDrawer: consume SelectionContext

Replaces props (stopId, onClose) with context reads. Closing the
drawer clears selection.stopId, which keeps the map and the drawer
in sync — clicking elsewhere on the map will close the drawer, and
clicking the X clears the highlighted stop.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Mount `AlertsBanner` + `StopDrawer` in `AppShell`

**Files:**
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/components/AppShell.test.tsx`

- [ ] **Step 1: Update the test to assert both components mount**

In `frontend/src/components/AppShell.test.tsx`, append a new test inside the existing `describe("AppShell", ...)`:

```tsx
  it("mounts the alerts banner area and the stop drawer container", () => {
    render(wrap(<AppShell />));
    // The alerts banner renders an empty container by default (no alerts in test);
    // assert the grid area exists by class.
    expect(document.querySelector(".shell-alerts")).toBeInTheDocument();
    // StopDrawer mounts but renders null when stopId is null — the AppShell still
    // creates a slot for it. Verify via DOM that there's no drawer overlay yet.
    expect(document.querySelector(".stop-drawer--open")).not.toBeInTheDocument();
  });
```

Also extend the mapbox-gl mock from Task 4 by adding the same block to the top of this file (before the `api` mock). The Overview that AppShell renders by default now contains a `SectionMap`.

- [ ] **Step 2: Run → FAIL (selector doesn't match the unmounted components yet)**

```bash
npm run test:run -- src/components/AppShell.test.tsx
```

- [ ] **Step 3: Update `AppShell.tsx`**

```tsx
import React, { useState } from "react";
import { FilterBar } from "./FilterBar";
import { AlertsBanner } from "./AlertsBanner";
import { StopDrawer } from "./StopDrawer";
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
        <div className="shell-rail__placeholder">Ask BATIS — coming in Plan 1c</div>
      </aside>

      <StopDrawer />
    </div>
  );
};
```

- [ ] **Step 4: Run + verify**

```bash
npm run test:run -- src/components/AppShell.test.tsx
npm run test:run
```

Expected: 29 passed (28 + 1 new AppShell test).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AppShell.tsx frontend/src/components/AppShell.test.tsx
git commit -m "$(cat <<'EOF'
AppShell: mount AlertsBanner + StopDrawer

AlertsBanner sits in the new `shell-alerts` grid row between the
header and the filter bar — it collapses to zero height when no
alerts are active. StopDrawer renders at the end of the shell tree;
it reads selection.stopId from SelectionContext and renders nothing
when no stop is selected.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Manual browser QA

**Files:** none modified.

End-to-end visual check against the dockerized stack.

- [ ] **Step 1: Confirm the stack is running**

```bash
docker compose ps
```

Expected: `batis-postgres-1`, `batis-postgres-test-1`, `batis-backend-1`, `batis-frontend-1` all up.

- [ ] **Step 2: Open http://localhost:5173 in a browser**

Expected:
- Dark theme, BATIS brand, five tabs, filter bar with last-7-days default
- AlertsBanner row visible if any service alerts are active; collapsed otherwise
- **Overview**: 4 KPIs, reliability map (rendered, tile-loaded), worst-routes list, trend sparkline
- **Operations**: 4 KPIs (OTP, delay, live vehicles, bunched), reliability map, slowest performers list
- **Network**: 4 KPIs (routes/cells/deserts/in-view), coverage hex grid map, routes list filtered by agency + search
- **Equity & Safety**: 4 KPIs, equity tract map, hot stops list
- **Benchmarks & Drift**: 4 KPIs, cross-agency OTP bar chart with brand colors
- Clicking a stop on the map opens the StopDrawer with live departures, safety, delay history
- Closing the drawer clears the selection (no stop highlighted on the map)

- [ ] **Step 3: Cross-filter smoke**

In Network, type "51" in the search box. The routes list filters to matching routes. In Operations, click "51B" in the slowest performers list; the row highlights. Switch to Network — the same route 51B is still highlighted (cross-section selection persistence).

- [ ] **Step 4: Sign off**

If any check fails, file the issue and fix before merging Plan 1b. Otherwise the plan is complete.

---

## Verification (end-to-end)

After all tasks complete, an engineer joining the project should be able to:

1. **Install + test:**
   ```bash
   cd frontend && npm install && npm run test:run
   ```
   Expected: 29 tests pass.

2. **Run the full stack:**
   ```bash
   docker compose up -d
   ```
   Open http://localhost:5173 — see all five sections functional with real backend data.

3. **Verify no regressions in the legacy code:**
   ```bash
   cd frontend && npx tsc --noEmit
   ```
   Expected: clean (the legacy `Sidebar.tsx` still type-checks because Plan 1a's `types.ts` still exists).

---

## What this plan does NOT do

Explicitly deferred to Plan 1c:

- **URL routing / saved views** — section state stays in component memory; reload returns to Overview
- **CSV / PNG export per widget**
- **Dark / light theme toggle** — only dark ships in 1b
- **Agent rail enablement** — placeholder text stays
- **Trip planner** — out of scope; the `planner` legacy mapMode is unused
- **Deletion of `Sidebar.tsx`** — kept on disk for reference; Plan 1c deletes it once Operations / Network / Equity & Safety / Benchmarks have absorbed the remaining widgets that aren't in 1b
- **Multi-widget richness** — each section in 1b ships with 4 KPIs + 1 hero + 1 supporting widget. Plan 1c can add the second/third supporting widgets per the spec's "2–4 supporting charts + paginated data table" pattern.
- **Search applied to map** — the search input filters list widgets only; map filtering is Plan 1c.
- **Cross-filter from list → map** — selection writes the routeId but the map doesn't re-style based on it in 1b; that's Plan 1c.

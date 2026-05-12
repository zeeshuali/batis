# BATIS Phase 1d — Richness, Export, and Trip Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the final Phase 1 features: CSV export on every widget, trip planner reintegration, one substantial new supporting widget per section, search-as-map-filter, and URL-encoded filter state. After Plan 1d ships, Phase 1 is feature-complete and Phase 2 (Agent foundation) begins from a polished baseline.

**Architecture:** No new top-level abstractions. A shared `download.ts` helper handles CSV serialisation; each widget gains an "Export" affordance via a tiny `ExportButton` primitive. Trip planner reuses the existing legacy `planner` `Section` value as a `mapMode`, with a new `Planner` panel inside the Network section that captures origin/destination from map clicks. Each section gains exactly one new supporting widget that targets the most user-visible gap from Plan 1b: Operations → crowding bar chart, Network → transit deserts list, Equity & Safety → safety score histogram, Benchmarks & Drift → active traffic events table. `MapView` consumes both `selection.routeId` AND `filters.search` to filter stop layers. The `useSectionRoute` hook from Plan 1c is renamed and expanded to `useUrlState` and encodes section + date range + agencies + search alongside the section name in the hash.

**Tech Stack:** Same as Plans 1a–1c. No new runtime dependencies.

---

## Pre-flight: what to know

This plan operates in `/home/mza/projects/batis` on `main`. Plan 1c left ~41 vitest tests passing, a clean `npx tsc --noEmit`, theme toggle + URL routing + section error states + cross-filter highlighting. The dockerized stack is running.

### Backend endpoints used in Plan 1d

| Section | New endpoint(s) the plan calls | Returns |
|---|---|---|
| Trip planner | `GET /trip-planner?from_lat&from_lng&to_lat&to_lng` | itinerary JSON |
| Operations crowding | `GET /crowding/predictions?start_date&end_date` | rows with `crowding_level` |
| Network deserts | `GET /coverage/deserts` (already called) — promoted to a list | GeoJSON `features` |
| Equity safety histogram | `GET /safety/stops` (already called) — bucketed in the client | safety rows |
| Benchmarks traffic | `GET /traffic/events` (already called) — list shape | GeoJSON `features` with severity |

All endpoints exist on the backend (see `backend/app/main.py`). No backend changes are required by Plan 1d.

### Naming conventions

- New shared helper: `frontend/src/lib/download.ts`
- New primitive: `frontend/src/components/primitives/ExportButton.tsx`
- Trip planner panel: `frontend/src/components/PlannerPanel.tsx`
- Renamed hook: `frontend/src/lib/useUrlState.ts` (was `useSectionRoute.ts` in Plan 1c)

### What's explicitly NOT in this plan

- **Saved views** (named bookmarks beyond the URL hash) — too speculative without product feedback
- **PNG / SVG export** of charts and maps — Plan 1e candidate
- **Multi-widget paginated tables** with column sort + filter — Plan 1e candidate
- **Agent rail enablement** — Phase 2 per the master spec
- **`/transfers/reliability`** and other Sprint 4+ endpoints from the BLUEPRINT — backend work first

---

## File Structure

**New files:**
- `frontend/src/lib/download.ts` — CSV serialisation + browser-side download
- `frontend/src/lib/download.test.ts`
- `frontend/src/components/primitives/ExportButton.tsx`
- `frontend/src/components/primitives/ExportButton.test.tsx`
- `frontend/src/components/PlannerPanel.tsx` — origin/dest capture + itinerary display
- `frontend/src/components/PlannerPanel.test.tsx`
- `frontend/src/lib/useUrlState.ts` — replaces `useSectionRoute.ts` with a broader scope
- `frontend/src/lib/useUrlState.test.ts`

**Modified files:**
- `frontend/src/components/primitives/index.ts` — export `ExportButton`
- `frontend/src/components/MapView.tsx` — consume `filters.search`; emit click coords to a new `PlannerContext` when in planner mode
- `frontend/src/context/SelectionContext.tsx` — add `plannerOrigin` / `plannerDest` (replaces MapView's stubs)
- `frontend/src/context/FilterContext.tsx` — read initial state from `useUrlState`; emit hash updates on change
- `frontend/src/sections/Overview.tsx` — wire ExportButton to the worst-routes list
- `frontend/src/sections/Operations.tsx` — add crowding bar chart + ExportButton
- `frontend/src/sections/Network.tsx` — add transit deserts list + ExportButton; mount `PlannerPanel`
- `frontend/src/sections/EquitySafety.tsx` — add safety histogram + ExportButton
- `frontend/src/sections/BenchmarksDrift.tsx` — add active traffic events table + ExportButton
- `frontend/src/components/AppShell.tsx` — switch from `useSectionRoute` to `useUrlState`
- `frontend/src/components/AppShell.test.tsx` — update import + add filter-hash assertions

**Deleted files:**
- `frontend/src/lib/useSectionRoute.ts` (folded into `useUrlState.ts`)
- `frontend/src/lib/useSectionRoute.test.ts`

---

## Task 1: CSV download helper + `ExportButton` primitive

**Files:**
- Create: `frontend/src/lib/download.ts`
- Create: `frontend/src/lib/download.test.ts`
- Create: `frontend/src/components/primitives/ExportButton.tsx`
- Create: `frontend/src/components/primitives/ExportButton.test.tsx`
- Modify: `frontend/src/components/primitives/index.ts`
- Modify: `frontend/src/components/primitives/primitives.css` (append button styles)

A small CSV helper + a "📥 Export" button that any widget can drop in.

- [ ] **Step 1: TDD — write `download.test.ts` first**

```ts
import { describe, it, expect } from "vitest";
import { toCsv } from "./download";

describe("toCsv", () => {
  it("emits a header row and one row per object", () => {
    const out = toCsv([{ a: 1, b: "x" }, { a: 2, b: "y" }]);
    expect(out.split("\n")).toEqual(["a,b", "1,x", "2,y"]);
  });

  it("escapes commas and quotes", () => {
    const out = toCsv([{ name: 'a, "b"', n: 1 }]);
    expect(out.split("\n")[1]).toBe('"a, ""b""",1');
  });

  it("uses headers in the order of the first row's keys", () => {
    const out = toCsv([{ b: 1, a: 2 }]);
    expect(out.split("\n")[0]).toBe("b,a");
  });

  it("returns an empty string for an empty array", () => {
    expect(toCsv([])).toBe("");
  });

  it("renders null/undefined as empty cells", () => {
    const out = toCsv([{ a: null, b: undefined, c: 0 }]);
    expect(out.split("\n")[1]).toBe(",,0");
  });
});
```

- [ ] **Step 2: Run → FAIL**

```bash
npm run test:run -- src/lib/download.test.ts
```

- [ ] **Step 3: Implement `download.ts`**

```ts
/** Serialise a uniform array of objects to a CSV string.
 *  Header row uses keys from the FIRST row (so caller controls column order).
 *  Strings containing commas, quotes, or newlines are RFC-4180 escaped.
 *  null and undefined render as empty cells.
 */
export function toCsv<T extends Record<string, unknown>>(rows: T[]): string {
  if (rows.length === 0) return "";
  const headers = Object.keys(rows[0]);
  const lines = [headers.join(",")];
  for (const row of rows) {
    lines.push(headers.map(h => escape(row[h])).join(","));
  }
  return lines.join("\n");
}

function escape(value: unknown): string {
  if (value === null || value === undefined) return "";
  const s = String(value);
  if (/[",\n]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

/** Trigger a browser download of the given CSV content with the given filename. */
export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
```

- [ ] **Step 4: Run → 5 passed**

```bash
npm run test:run -- src/lib/download.test.ts
```

- [ ] **Step 5: TDD `ExportButton`**

`frontend/src/components/primitives/ExportButton.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const downloadCsv = vi.fn();
vi.mock("../../lib/download", async () => {
  const actual = await vi.importActual<typeof import("../../lib/download")>("../../lib/download");
  return { ...actual, downloadCsv };
});

import { ExportButton } from "./ExportButton";

describe("ExportButton", () => {
  beforeEach(() => downloadCsv.mockClear());

  it("renders an Export label and downloads when clicked", async () => {
    render(<ExportButton filename="test.csv" rows={[{ a: 1 }]} />);
    const btn = screen.getByRole("button", { name: /export/i });
    await userEvent.click(btn);
    expect(downloadCsv).toHaveBeenCalledWith("test.csv", "a\n1");
  });

  it("is disabled when rows is empty", () => {
    render(<ExportButton filename="x.csv" rows={[]} />);
    expect(screen.getByRole("button", { name: /export/i })).toBeDisabled();
  });
});
```

- [ ] **Step 6: Implement `ExportButton.tsx`**

```tsx
import React from "react";
import { downloadCsv, toCsv } from "../../lib/download";
import "./primitives.css";

export interface ExportButtonProps {
  filename: string;
  rows: Record<string, unknown>[];
  label?: string;
}

export const ExportButton: React.FC<ExportButtonProps> = ({ filename, rows, label = "Export" }) => (
  <button
    type="button"
    className="export-button"
    disabled={rows.length === 0}
    onClick={() => downloadCsv(filename, toCsv(rows))}
  >
    <span aria-hidden="true">↓</span> {label}
  </button>
);
```

- [ ] **Step 7: Append button styles to `primitives.css`**

```css
.export-button {
  appearance: none;
  background: transparent;
  border: 1px solid var(--color-border);
  color: var(--color-fg-2);
  font: inherit;
  font-size: var(--text-xs);
  padding: 2px var(--space-2);
  border-radius: var(--radius-1);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.export-button:hover:not(:disabled) { color: var(--color-fg-0); background: var(--color-bg-2); }
.export-button:disabled            { opacity: 0.4; cursor: default; }
```

- [ ] **Step 8: Export from barrel**

In `frontend/src/components/primitives/index.ts`, append:

```ts
export { ExportButton } from "./ExportButton";
export type { ExportButtonProps } from "./ExportButton";
```

- [ ] **Step 9: Run + verify**

```bash
npm run test:run
```

Expected: 48 passed (41 from 1c + 5 download + 2 ExportButton).

- [ ] **Step 10: Commit**

```bash
git add frontend/src/lib/download.ts frontend/src/lib/download.test.ts \
        frontend/src/components/primitives/ExportButton.tsx \
        frontend/src/components/primitives/ExportButton.test.tsx \
        frontend/src/components/primitives/index.ts \
        frontend/src/components/primitives/primitives.css
git commit -m "$(cat <<'EOF'
Add CSV download helper and ExportButton primitive

frontend/src/lib/download.ts exports toCsv (RFC-4180 escape) and
downloadCsv (Blob + a[download] click). ExportButton wraps both for
the "Export" affordance every list / table / chart will get in the
section-richness tasks that follow.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `useUrlState` hook (replaces `useSectionRoute`)

**Files:**
- Create: `frontend/src/lib/useUrlState.ts`
- Create: `frontend/src/lib/useUrlState.test.ts`
- Delete: `frontend/src/lib/useSectionRoute.ts`
- Delete: `frontend/src/lib/useSectionRoute.test.ts`
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/context/FilterContext.tsx`

The Plan 1c hook only persisted the active section. Plan 1d expands it to encode the full UI state (section + start_date + end_date + agencies + search) so reload / shareable links restore everything. Hash format: `#operations?from=2026-05-04&to=2026-05-11&agencies=AC,BA&q=51`.

- [ ] **Step 1: TDD — write the test**

`frontend/src/lib/useUrlState.test.ts`:

```ts
import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useUrlState, parseHash, encodeHash } from "./useUrlState";

describe("parseHash / encodeHash", () => {
  it("round-trips an empty state to a section-only hash", () => {
    expect(parseHash("#network")).toEqual({ section: "network", from: null, to: null, agencies: null, q: null });
    expect(encodeHash({ section: "network", from: null, to: null, agencies: null, q: null })).toBe("#network");
  });

  it("encodes and decodes a full state", () => {
    const state = {
      section: "equity" as const,
      from: "2026-04-01",
      to: "2026-04-30",
      agencies: ["AC", "BA"],
      q: "51",
    };
    const hash = encodeHash(state);
    expect(hash).toContain("#equity?");
    expect(hash).toContain("from=2026-04-01");
    expect(hash).toContain("to=2026-04-30");
    expect(hash).toContain("agencies=AC,BA");
    expect(hash).toContain("q=51");
    expect(parseHash(hash)).toEqual(state);
  });

  it("returns overview for an unknown section", () => {
    expect(parseHash("#wat").section).toBe("overview");
  });
});

describe("useUrlState", () => {
  beforeEach(() => { window.location.hash = ""; });

  it("starts with defaults", () => {
    const { result } = renderHook(() => useUrlState());
    expect(result.current.state.section).toBe("overview");
  });

  it("setState rewrites the hash", () => {
    const { result } = renderHook(() => useUrlState());
    act(() => result.current.setState({ ...result.current.state, section: "network", q: "51" }));
    expect(window.location.hash).toContain("#network");
    expect(window.location.hash).toContain("q=51");
  });

  it("responds to external hashchange", () => {
    const { result } = renderHook(() => useUrlState());
    act(() => {
      window.location.hash = "#benchmarks?from=2026-01-01&to=2026-01-07";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(result.current.state.section).toBe("benchmarks");
    expect(result.current.state.from).toBe("2026-01-01");
  });
});
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement `useUrlState.ts`**

```ts
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
  return query ? `#${state.section}?${query}` : `#${state.section}`;
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
```

- [ ] **Step 4: Run → 6 passed**

- [ ] **Step 5: Refactor `AppShell` to use `useUrlState`**

Replace the `useSectionRoute` import and call with:

```tsx
import { useUrlState } from "../lib/useUrlState";

// inside AppShell:
const { state, setState } = useUrlState();
const active = state.section;
const setActive = (key: SectionKey) => setState({ ...state, section: key });
```

- [ ] **Step 6: Wire `FilterContext` to `useUrlState`**

`FilterContext` should read its initial values from `useUrlState` and emit hash updates when filters change. The cleanest pattern is to use `useUrlState` inside `FilterProvider`:

```tsx
// at the top of FilterContext.tsx:
import { useUrlState } from "../lib/useUrlState";

export const FilterProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { state, setState } = useUrlState();

  const startDate = state.from ?? isoDate(-7);
  const endDate   = state.to   ?? isoDate(0);
  const agencies  = state.agencies ?? [...ALL_AGENCY_IDS];
  const search    = state.q ?? "";

  const setDateRange = useCallback((s: string, e: string) => {
    setState({ ...state, from: s, to: e });
  }, [state, setState]);

  const setAgencies = useCallback((ids: string[]) => {
    const next = ids.length > 0 ? ids : [...ALL_AGENCY_IDS];
    // Encode as null in the URL when it matches the "all" default to keep URLs short.
    setState({ ...state, agencies: next.length === ALL_AGENCY_IDS.length ? null : next });
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
```

Update the `FilterContext.test.tsx` assertions to expect the same observable behaviour through the hash.

- [ ] **Step 7: Delete the old hook + test**

```bash
git rm frontend/src/lib/useSectionRoute.ts frontend/src/lib/useSectionRoute.test.ts
```

- [ ] **Step 8: Update `AppShell.test.tsx`**

Add a filter-hash assertion:

```tsx
  it("encodes search into the hash when typed", async () => {
    window.location.hash = "";
    render(wrap(<AppShell />));
    const input = screen.getByPlaceholderText(/route/i);
    await userEvent.type(input, "51");
    expect(window.location.hash).toContain("q=51");
  });
```

Remove the old `#operations` hash-only assertion or rewrite it to match the new hash format (`#operations?…`).

- [ ] **Step 9: Run + verify**

```bash
npm run test:run
npx tsc --noEmit
```

Expected: ~52 passed (48 from Task 1 + 6 useUrlState − the deleted Plan 1c useSectionRoute tests + 1 AppShell filter-hash test).

- [ ] **Step 10: Commit**

```bash
git add -A frontend/src/lib/ frontend/src/components/AppShell.tsx frontend/src/components/AppShell.test.tsx \
        frontend/src/context/FilterContext.tsx
git commit -m "$(cat <<'EOF'
Replace useSectionRoute with useUrlState — full filter state in hash

useUrlState encodes section + date range + agency picker + search
into the URL hash. FilterProvider reads its initial state from the
hash and pushes updates back. Reload, back/forward, and shareable
links now preserve the whole filter selection, not just the section.

Format: `#section?from=…&to=…&agencies=AC,BA&q=51`. Defaults are
elided to keep canonical URLs short — selecting all agencies, for
example, produces `#operations` rather than spelling out all eight.

Plan 1c's useSectionRoute is removed; AppShell drives its tabs from
useUrlState directly.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Trip planner reintegration

**Files:**
- Create: `frontend/src/components/PlannerPanel.tsx`
- Create: `frontend/src/components/PlannerPanel.test.tsx`
- Modify: `frontend/src/context/SelectionContext.tsx` — add `plannerOrigin` / `plannerDest`
- Modify: `frontend/src/context/SelectionContext.test.tsx`
- Modify: `frontend/src/components/MapView.tsx` — emit map clicks to context when `mapMode === "planner"`
- Modify: `frontend/src/sections/Network.tsx` — add a "Trip planner" tab below the map

The trip planner was the most click-heavy feature in the legacy dashboard. Plan 1d brings it back inside Network, behind a small toggle: clicking "Plan a trip" swaps the coverage map for the planner map; clicking a stop on the planner map captures origin, then destination, then renders an itinerary from `/trip-planner`.

- [ ] **Step 1: Extend `SelectionContext` with planner coords**

In `SelectionContext.tsx`:

```tsx
export interface LatLng { lat: number; lng: number; }

export interface Selection {
  routeId:        string | null;
  stopId:         string | null;
  hoveredStopId:  string | null;
  plannerOrigin:  LatLng | null;
  plannerDest:    LatLng | null;
}

// Add setters:
//   setPlannerOrigin(p: LatLng | null): void
//   setPlannerDest(p: LatLng | null): void
//   resetPlanner(): void
```

Update `clear()` to also null both planner coords. Append corresponding tests to `SelectionContext.test.tsx`.

- [ ] **Step 2: Update `MapView` to write planner clicks**

In `MapView.tsx`, find the existing map `click` handler (probably handling `onStopClick`). When `mapMode === "planner"`, the click handler should instead:

```ts
if (mapMode === "planner") {
  if (!selection.plannerOrigin) {
    setPlannerOrigin({ lat: e.lngLat.lat, lng: e.lngLat.lng });
  } else if (!selection.plannerDest) {
    setPlannerDest({ lat: e.lngLat.lat, lng: e.lngLat.lng });
  } else {
    resetPlanner();
    setPlannerOrigin({ lat: e.lngLat.lat, lng: e.lngLat.lng });
  }
  return;
}
```

The existing layer logic for the planner mode (origin/destination markers) already exists in MapView.tsx from the legacy code — surface it again by un-stubbing the `plannerOrigin` / `plannerDest` aliases from Plan 1b.

- [ ] **Step 3: TDD — write `PlannerPanel.test.tsx`**

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterProvider } from "../context/FilterContext";
import { SelectionProvider, useSelection } from "../context/SelectionContext";
import { PlannerPanel } from "./PlannerPanel";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    api: {
      get: vi.fn(async () => ({ data: {
        legs: [{ route_short_name: "51B", from_stop: "Telegraph", to_stop: "Shattuck", duration_minutes: 18 }],
        total_duration_minutes: 18,
        transfers: 0,
      } })),
    },
  };
});

function ClickToSetOrigin() {
  const { setPlannerOrigin, setPlannerDest } = useSelection();
  return (
    <>
      <button onClick={() => setPlannerOrigin({ lat: 37.8, lng: -122.27 })}>set-origin</button>
      <button onClick={() => setPlannerDest  ({ lat: 37.7, lng: -122.42 })}>set-dest</button>
    </>
  );
}

function wrap(ui: React.ReactElement) {
  return <FilterProvider><SelectionProvider>{ui}</SelectionProvider></FilterProvider>;
}

describe("PlannerPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("prompts to click an origin when empty", () => {
    render(wrap(<PlannerPanel />));
    expect(screen.getByText(/click the map to set an origin/i)).toBeInTheDocument();
  });

  it("renders itinerary legs once origin + dest are set", async () => {
    render(wrap(<><PlannerPanel /><ClickToSetOrigin /></>));
    await userEvent.click(screen.getByText("set-origin"));
    await userEvent.click(screen.getByText("set-dest"));
    await waitFor(() => expect(screen.getByText(/51B/)).toBeInTheDocument());
    expect(screen.getByText(/18 min/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Run → FAIL**

- [ ] **Step 5: Implement `PlannerPanel.tsx`**

```tsx
import React, { useEffect, useState } from "react";
import { useSelection, type LatLng } from "../context/SelectionContext";
import { api } from "../lib/api";
import { Spinner, EmptyState } from "./primitives";
import "../sections/sections.css";

interface Leg {
  route_short_name?: string;
  route_id?: string;
  from_stop?: string;
  to_stop?: string;
  duration_minutes: number;
}
interface Itinerary {
  legs: Leg[];
  total_duration_minutes: number;
  transfers: number;
}

export const PlannerPanel: React.FC = () => {
  const { selection, resetPlanner } = useSelection();
  const [itin, setItin] = useState<Itinerary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const o: LatLng | null = selection.plannerOrigin;
  const d: LatLng | null = selection.plannerDest;

  useEffect(() => {
    if (!o || !d) { setItin(null); return; }
    let cancelled = false;
    async function fetchTrip() {
      setLoading(true); setError(null);
      try {
        const res = await api.get<Itinerary>("/trip-planner", {
          params: { from_lat: o!.lat, from_lng: o!.lng, to_lat: d!.lat, to_lng: d!.lng },
        });
        if (!cancelled) setItin(res.data);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to plan trip");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchTrip();
    return () => { cancelled = true; };
  }, [o, d]);

  if (!o) {
    return (
      <div className="section__panel">
        <h3 className="section__panel-title">Trip planner</h3>
        <EmptyState message="Click the map to set an origin." hint="Then click again to pick a destination." />
      </div>
    );
  }

  if (!d) {
    return (
      <div className="section__panel">
        <h3 className="section__panel-title">Trip planner</h3>
        <EmptyState message="Origin set. Click the map again for a destination." />
        <button className="export-button" onClick={resetPlanner}>Reset</button>
      </div>
    );
  }

  return (
    <div className="section__panel">
      <h3 className="section__panel-title">Trip planner</h3>
      {loading && <Spinner />}
      {error && <p className="section-error__msg">{error}</p>}
      {itin && (
        <>
          <p>
            Total: <strong>{itin.total_duration_minutes} min</strong> · transfers: {itin.transfers}
          </p>
          <ul className="data-list">
            {itin.legs.map((leg, i) => (
              <li key={i} className="data-list__li">
                <div className="data-list__row" style={{ pointerEvents: "none" }}>
                  <span className="data-list__primary">{leg.route_short_name ?? leg.route_id ?? "Walk"}</span>
                  <span className="data-list__secondary">{leg.from_stop} → {leg.to_stop}</span>
                  <span className="data-list__trailing">{leg.duration_minutes} min</span>
                </div>
              </li>
            ))}
          </ul>
          <button className="export-button" onClick={resetPlanner}>Reset</button>
        </>
      )}
    </div>
  );
};
```

- [ ] **Step 6: Mount `PlannerPanel` in Network**

In `Network.tsx`, add a "Plan a trip" toggle near the map title. When enabled, the SectionMap switches to `mapMode="planner"`; below the map (or beside it), `PlannerPanel` renders. When disabled, coverage map + routes list as before.

Simplest pattern: add a local `useState<boolean>(false)` for `plannerMode`, and a small toggle button. When true, replace the routes-list panel with `<PlannerPanel />` and pass `mapMode="planner"` to `SectionMap`.

- [ ] **Step 7: Run + verify**

```bash
npm run test:run
```

Expected: ~57 passed (52 from Task 2 + 2 planner + 3 SelectionContext additions).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/PlannerPanel.tsx frontend/src/components/PlannerPanel.test.tsx \
        frontend/src/context/SelectionContext.tsx frontend/src/context/SelectionContext.test.tsx \
        frontend/src/components/MapView.tsx frontend/src/sections/Network.tsx
git commit -m "$(cat <<'EOF'
Trip planner reintegration in Network section

SelectionContext gains plannerOrigin / plannerDest / setters /
resetPlanner. MapView writes the next click into whichever planner
slot is empty when mapMode === "planner". The Network section gains
a "Plan a trip" toggle that swaps the coverage map for the planner
map and shows a new PlannerPanel which fetches /trip-planner and
renders the itinerary legs.

The legacy planner stubs in MapView (plannerOrigin = null,
onPlannerMapClick no-op) from Plan 1b are gone — the existing
origin/dest marker layers in MapView already had the layer specs
ready; this commit hooks them up to real context state.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Operations richness — crowding bar chart + export

**Files:**
- Modify: `frontend/src/sections/Operations.tsx`
- Modify: `frontend/src/sections/Operations.test.tsx`

Operations gets a fourth panel: a horizontal bar chart of crowding levels by route (top 10 by high-crowding count), with an ExportButton on the slowest-performers list.

- [ ] **Step 1: Update the test**

Extend the existing test mock for `/crowding/predictions`:

```tsx
if (url.startsWith("/crowding/predictions")) {
  return { data: [
    { route_id: "51B", trip_id: null, stop_id: null, service_date: "...", time_bucket: "AM_PEAK", crowding_level: "high", model_version: "v1" },
    { route_id: "51B", trip_id: null, stop_id: null, service_date: "...", time_bucket: "AM_PEAK", crowding_level: "high", model_version: "v1" },
    { route_id: "72",  trip_id: null, stop_id: null, service_date: "...", time_bucket: "AM_PEAK", crowding_level: "medium", model_version: "v1" },
  ] };
}
```

Add a test:

```tsx
  it("renders a crowding chart panel", async () => {
    render(wrap(<Operations />));
    await waitFor(() => expect(screen.getByRole("heading", { name: /crowding/i })).toBeInTheDocument());
  });
```

- [ ] **Step 2: Run → FAIL** (panel doesn't exist yet)

- [ ] **Step 3: Implement**

Add to `Operations.tsx`:

```tsx
import { BarChart, ExportButton, type BarPoint } from "../components/primitives";

// ... in the fetchAll Promise.all, add:
api.get<CrowdingRow[]>("/crowding/predictions", { params: { start_date: filters.startDate, end_date: filters.endDate } }).catch(() => ({ data: [] })),

// ... new state:
const [crowding, setCrowding] = useState<CrowdingRow[]>([]);

// ... new derived:
const crowdingBars: BarPoint[] = (() => {
  const counts = new Map<string, number>();
  for (const c of crowding) {
    if (c.crowding_level === "high") {
      counts.set(c.route_id, (counts.get(c.route_id) ?? 0) + 1);
    }
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([route_id, value]) => ({ label: route_id, value, color: "#ef4444" }));
})();

// ... in JSX, add a panel below the section__grid:
<div className="section__panel">
  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
    <h3 className="section__panel-title">Top high-crowding routes</h3>
    <ExportButton filename="operations-crowding.csv" rows={crowdingBars.map(b => ({ route_id: b.label, high_events: b.value }))} />
  </div>
  {crowdingBars.length === 0
    ? <EmptyState message="No crowding predictions in this window." />
    : <BarChart data={crowdingBars} height={260} />}
</div>
```

Also add an ExportButton beside the Slowest Performers title:

```tsx
<div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
  <h3 className="section__panel-title">Slowest performers</h3>
  <ExportButton filename="operations-slowest.csv" rows={worst.map(r => ({ route_id: r.id, primary: r.primary, secondary: r.secondary, trailing: r.trailing }))} />
</div>
```

Define `CrowdingRow` in `types/data.ts`:

```ts
export interface CrowdingRow {
  route_id: string;
  trip_id: string | null;
  stop_id: string | null;
  service_date: string;
  time_bucket: string;
  crowding_level: "low" | "medium" | "high" | "unknown";
  model_version: string | null;
}
```

- [ ] **Step 4: Run + verify**

```bash
npm run test:run
```

Expected: ~58 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/sections/Operations.tsx frontend/src/sections/Operations.test.tsx frontend/src/types/data.ts
git commit -m "$(cat <<'EOF'
Operations: add crowding bar chart + export buttons

Adds a fourth panel below the section grid: top-10 routes by
high-crowding prediction count, rendered as a BarChart. The
Slowest Performers list gains an ExportButton for CSV download.
CrowdingRow type lifts into types/data.ts so other sections can
reuse it.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Network richness — transit deserts list + export

**Files:**
- Modify: `frontend/src/sections/Network.tsx`
- Modify: `frontend/src/sections/Network.test.tsx`

Network gets a deserts list panel that names + describes underserved geographic cells, with an ExportButton.

- [ ] **Step 1: Update the test mock**

```tsx
if (url.startsWith("/coverage/deserts")) {
  return { data: { features: [
    { properties: { cell_id: "DRT-1", desert_score: 0.82, nearest_stop_distance_m: 1200 } },
    { properties: { cell_id: "DRT-2", desert_score: 0.71, nearest_stop_distance_m: 950 } },
  ] } };
}
```

Add a test:

```tsx
  it("renders the transit deserts list", async () => {
    render(wrap(<Network />));
    await waitFor(() => expect(screen.getByText(/Transit deserts/i)).toBeInTheDocument());
    expect(await screen.findByText("DRT-1")).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement**

Add to `Network.tsx`:

```tsx
import { ExportButton } from "../components/primitives";

interface DesertFeature { properties: { cell_id: string; desert_score: number; nearest_stop_distance_m?: number; }; }

// ... in fetchAll, replace the existing /coverage/deserts call:
api.get<{ features: DesertFeature[] }>("/coverage/deserts").catch(() => ({ data: { features: [] } })),
// ...
setDesertList(desertsRes.data?.features ?? []);

// ... new state:
const [desertList, setDesertList] = useState<DesertFeature[]>([]);

// ... derived list items:
const desertItems: DataListItem[] = desertList
  .sort((a, b) => b.properties.desert_score - a.properties.desert_score)
  .slice(0, 50)
  .map(d => ({
    id: d.properties.cell_id,
    primary: d.properties.cell_id,
    secondary: d.properties.nearest_stop_distance_m ? `${Math.round(d.properties.nearest_stop_distance_m)} m to nearest stop` : undefined,
    trailing: d.properties.desert_score.toFixed(2),
  }));

// ... new panel in JSX:
<div className="section__panel">
  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
    <h3 className="section__panel-title">Transit deserts</h3>
    <ExportButton filename="network-deserts.csv" rows={desertItems.map(d => ({ cell_id: d.id, nearest_stop_m: d.secondary, desert_score: d.trailing }))} />
  </div>
  {desertItems.length === 0
    ? <EmptyState message="No transit deserts identified." />
    : <DataList items={desertItems} />}
</div>
```

- [ ] **Step 4: Run + verify**

```bash
npm run test:run
```

Expected: ~59 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/sections/Network.tsx frontend/src/sections/Network.test.tsx
git commit -m "$(cat <<'EOF'
Network: add transit deserts list + export

Promotes /coverage/deserts from a KPI count to a real panel that
names each desert cell, shows the distance to its nearest stop, and
ranks by desert score. Comes with a CSV export. Plan 1c surfaced
the KPI; Plan 1d turns it into something a planner can act on.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Equity & Safety richness — safety score histogram + export

**Files:**
- Modify: `frontend/src/sections/EquitySafety.tsx`
- Modify: `frontend/src/sections/EquitySafety.test.tsx`

Adds a distribution view of safety scores so a researcher can see the long-tail of high-risk stops at a glance.

- [ ] **Step 1: Update the test**

Extend the `/safety/stops` mock to return more rows spanning a range:

```tsx
if (url.startsWith("/safety/stops")) {
  return { data: [
    ...Array.from({ length: 5 }, (_, i) => ({ stop_id: `S${i}`, stop_name: `Mid ${i}`, safety_score: 4 + i })),
    { stop_id: "SH1", stop_name: "Hot 1", safety_score: 12 },
    { stop_id: "SH2", stop_name: "Hot 2", safety_score: 9 },
  ] };
}
```

Add:

```tsx
  it("renders a safety score distribution chart", async () => {
    render(wrap(<EquitySafety />));
    await waitFor(() => expect(screen.getByRole("heading", { name: /safety score distribution/i })).toBeInTheDocument());
  });
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement**

In `EquitySafety.tsx`, add a histogram. Buckets: `0-2`, `2-5`, `5-8`, `8-12`, `12+`.

```tsx
import { BarChart, ExportButton, type BarPoint } from "../components/primitives";

// ... new fetch (no api change — we lift `hotStops` to a broader sample)
// Drop the min_score=8 filter so we get the full distribution:
api.get<SafetyRow[]>("/safety/stops").catch(() => ({ data: [] })),

// ... derived:
const buckets = [
  { label: "0–2",  range: [0, 2]   as const, color: "#22c55e" },
  { label: "2–5",  range: [2, 5]   as const, color: "#facc15" },
  { label: "5–8",  range: [5, 8]   as const, color: "#f97316" },
  { label: "8–12", range: [8, 12]  as const, color: "#ef4444" },
  { label: "12+",  range: [12, 999] as const, color: "#7f1d1d" },
];
const histogram: BarPoint[] = buckets.map(b => ({
  label: b.label,
  value: hotStops.filter(s => s.safety_score >= b.range[0] && s.safety_score < b.range[1]).length,
  color: b.color,
}));

// ... new panel:
<div className="section__panel">
  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
    <h3 className="section__panel-title">Safety score distribution</h3>
    <ExportButton filename="safety-distribution.csv" rows={histogram.map(b => ({ bucket: b.label, count: b.value }))} />
  </div>
  <BarChart data={histogram} height={220} />
</div>
```

Also add ExportButton to the existing Highest-risk Stops panel.

- [ ] **Step 4: Run + verify**

```bash
npm run test:run
```

Expected: ~60 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/sections/EquitySafety.tsx frontend/src/sections/EquitySafety.test.tsx
git commit -m "$(cat <<'EOF'
Equity & Safety: add safety score distribution + exports

Buckets every stop's safety score into five tiers (0–2, 2–5, 5–8,
8–12, 12+) and renders the histogram in a new panel. Drops the
min_score=8 filter on /safety/stops so the full distribution is
visible. Adds ExportButton to both the histogram and the highest-
risk-stops list.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Benchmarks & Drift richness — active traffic events table + export

**Files:**
- Modify: `frontend/src/sections/BenchmarksDrift.tsx`
- Modify: `frontend/src/sections/BenchmarksDrift.test.tsx`

Benchmarks already has a KPI count for traffic events; turn it into a paginated table with severity, location, and dates, plus exports.

- [ ] **Step 1: Update the test**

Extend the `/traffic/events` mock to return event details:

```tsx
if (url.startsWith("/traffic/events")) {
  return { data: { features: [
    { properties: { event_id: "EVT-1", event_type: "incident", severity: "major",   description: "Crash on 580",  start_time: "2026-05-12T08:00:00Z" } },
    { properties: { event_id: "EVT-2", event_type: "construction", severity: "minor", description: "Lane closure", start_time: "2026-05-12T09:00:00Z" } },
  ] } };
}
```

Add:

```tsx
  it("renders the active traffic events table", async () => {
    render(wrap(<BenchmarksDrift />));
    await waitFor(() => expect(screen.getByText(/Crash on 580/i)).toBeInTheDocument());
  });
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement**

```tsx
import { DataList, ExportButton, type DataListItem } from "../components/primitives";

interface TrafficEvent { event_id: string; event_type: string; severity?: string; description?: string; start_time?: string; }

const [trafficEvents, setTrafficEvents] = useState<TrafficEvent[]>([]);

// In fetchAll, replace the existing /traffic/events count-only call with:
api.get<{ features: { properties: TrafficEvent }[] }>("/traffic/events").catch(() => ({ data: { features: [] } })),
// ...
setTrafficEvents(eventsRes.data?.features?.map(f => f.properties) ?? []);

// Derived list:
const eventItems: DataListItem[] = trafficEvents
  .slice(0, 50)
  .map(ev => ({
    id: ev.event_id,
    primary: ev.description ?? ev.event_id,
    secondary: [ev.event_type, ev.severity].filter(Boolean).join(" · "),
    trailing: ev.start_time ? new Date(ev.start_time).toLocaleString() : "—",
  }));

// New panel:
<div className="section__panel">
  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
    <h3 className="section__panel-title">Active traffic events</h3>
    <ExportButton filename="traffic-events.csv" rows={trafficEvents.map(ev => ({ id: ev.event_id, type: ev.event_type, severity: ev.severity, description: ev.description, start_time: ev.start_time }))} />
  </div>
  {eventItems.length === 0
    ? <EmptyState message="No active traffic events." />
    : <DataList items={eventItems} />}
</div>
```

Also add ExportButton to the Cross-agency OTP panel.

- [ ] **Step 4: Run + verify**

```bash
npm run test:run
```

Expected: ~61 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/sections/BenchmarksDrift.tsx frontend/src/sections/BenchmarksDrift.test.tsx
git commit -m "$(cat <<'EOF'
Benchmarks & Drift: active traffic events table + exports

Promotes the traffic-events KPI count to a real list panel with one
row per event (description, severity, start time). Adds CSV export
to both the events list and the cross-agency OTP chart.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Search-as-map-filter

**Files:**
- Modify: `frontend/src/components/MapView.tsx`

Plan 1c made MapView filter stop layers by `selection.routeId`. Plan 1d extends that: when `filters.search` is non-empty, the same filter expression also restricts stops to ones whose `route_id` (or `routes_serving` array) matches the search substring.

- [ ] **Step 1: Update the filter effect in `MapView.tsx`**

In the effect that calls `setFilter` on the stop layers:

```ts
useEffect(() => {
  if (!mapRef.current || !mapRef.current.isStyleLoaded()) return;
  const routeId = selection.routeId;
  const search = filters.search.trim().toLowerCase();

  const clauses: any[] = [];
  if (routeId) {
    clauses.push(["any",
      ["==", ["get", "route_id"], routeId],
      ["in", routeId, ["coalesce", ["get", "routes_serving"], ""]],
    ]);
  }
  if (search) {
    clauses.push(["any",
      ["in", search, ["downcase", ["coalesce", ["get", "route_id"], ""]]],
      ["in", search, ["downcase", ["coalesce", ["get", "routes_serving"], ""]]],
    ]);
  }
  const filter = clauses.length === 0
    ? null
    : clauses.length === 1 ? clauses[0] : ["all", ...clauses];

  for (const layer of ["reliability-layer", "safety-layer", "crowding-layer", "demand-layer"]) {
    if (mapRef.current.getLayer(layer)) {
      mapRef.current.setFilter(layer, filter as mapboxgl.FilterSpecification);
    }
  }
}, [selection.routeId, filters.search]);
```

(Mapbox's `["in", needle, haystack]` accepts strings — it returns true if `haystack` contains `needle`. Adjust to whatever expression syntax the existing layer setup uses; this is a structural sketch.)

- [ ] **Step 2: Manual browser check**

Open Operations. Type `51` in the search box. The stop circles on the map should narrow to routes whose names contain "51". Clear the search → all stops return.

- [ ] **Step 3: Run + verify**

```bash
npm run test:run
```

Expected: 61 passed (no test for this; runtime check via browser QA in Task 9).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/MapView.tsx
git commit -m "$(cat <<'EOF'
MapView: include filters.search in the stop-layer filter

Extends Plan 1c's selection.routeId filter so when the user types in
the global search box, the map's stop layers also narrow to stops
whose route_id or routes_serving matches. Clearing the search
removes the filter clause; the routeId clause is independent.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Browser QA + Phase 1 closeout

**Files:** none modified.

End-to-end check + sign Phase 1 off.

- [ ] **Step 1: Confirm stack**

```bash
docker compose ps
```

Expected: postgres, postgres-test, backend, frontend all up.

- [ ] **Step 2: Open http://localhost:5173/ + hard reload**

Smoke-check each section:

- **Overview**: 4 KPIs · map · slowest list with Export · trend chart
- **Operations**: 4 KPIs · map · slowest list with Export · crowding bar chart with Export
- **Network**: 4 KPIs · map · routes list with Export · deserts list with Export · "Plan a trip" toggle
- **Equity & Safety**: 4 KPIs · map · highest-risk list with Export · safety distribution chart with Export
- **Benchmarks & Drift**: 4 KPIs · OTP bar chart with Export · active traffic events list with Export
- Theme toggle works
- URL hash encodes section + filters (visible in browser address bar)
- Click "Plan a trip" in Network: map switches to planner mode, clicks set origin then destination, PlannerPanel renders an itinerary or empty state
- Type a route number in the search box: route list narrows AND the map's stop circles narrow

- [ ] **Step 3: Final test pass**

```bash
cd frontend && npm run test:run
npx tsc --noEmit
```

Expected: ~61 passed, type-check clean.

- [ ] **Step 4: Sign off**

If everything green, Phase 1 of the BATIS 2.0 redesign is **complete**. Phase 2 (Agent foundation per the master spec at `docs/superpowers/specs/2026-05-11-batis-redesign-ai-agent.md`) begins from here.

---

## Verification (end-to-end)

After all tasks complete:

1. **Install + tests:** `cd frontend && npm install && npm run test:run` → ~61 tests pass.

2. **Filter URL persistence:** apply a date range and an agency filter, hard reload, both restore.

3. **CSV export:** click Export on any widget → browser downloads a `.csv` with the right rows.

4. **Trip planner end-to-end:** Network → Plan a trip → click two points on the map → see an itinerary.

5. **Search-as-map-filter:** type a route in the search box → list AND map filter together.

6. **Type-check:** `npx tsc --noEmit` clean.

---

## What this plan does NOT do

- **PNG / SVG chart + map export** — Plan 1e candidate (needs an image-capture library)
- **Saved views with names** — beyond URL hash; needs storage + UI
- **Sortable / paginated tables** — current tables are slice(0, N) lists
- **Schedule-drift detection visualisation** — backend endpoint exists (`/schedule-drift/{agency_id}/{route_id}`) but no UI yet
- **Agent rail enablement** — Phase 2 of the master spec

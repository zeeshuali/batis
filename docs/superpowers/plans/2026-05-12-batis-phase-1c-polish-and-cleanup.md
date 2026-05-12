# BATIS Phase 1c — Polish and Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close out Phase 1 of the BATIS 2.0 redesign. Fix the lingering Mapbox style-spec validation error, lift duplicated code into shared modules, add real error states + dark/light toggle + URL routing to the shell, wire selection-driven map highlighting, and retire `Sidebar.tsx`. After Plan 1c, Phase 1 is complete and Phase 2 (Agent foundation) can begin from a clean baseline.

**Architecture:** No new top-level abstractions. Polish what Plans 1a + 1b shipped: replace inline duplicates with `frontend/src/lib/format.ts` and `frontend/src/types/data.ts`; introduce a single `SectionError` primitive; add a `ThemeContext` for dark/light; encode the active section in the URL hash so reload + back/forward work; let `MapView` consume `selection.routeId` to apply a filter expression to existing layers; delete `Sidebar.tsx` and the dormant `.kpi-card` rule in `styles.css`. No new dependencies.

**Tech Stack:** Same as Plans 1a/1b — React 18, TypeScript 5.6, Vite 5, Mapbox GL JS 3, Recharts 3, Axios, Vitest. No backend changes.

---

## Pre-flight: what to know

This plan operates in `/home/mza/projects/batis` on `main`. Plans 1a + 1b left 29 vitest tests passing, `npx tsc --noEmit` clean, the dockerized stack running. The dashboard renders all five sections with real backend data after the Plan 1b polish commit.

### Outstanding items this plan addresses (from the Plan 1a/1b reviewer reports)

| Item | Severity | Where it surfaced |
|---|---|---|
| MapView paint validation: `Type string is not interpolatable` | Console-noise (non-fatal but the map mis-renders one layer) | MapView.tsx:590 + 612 (circle-stroke-color expressions) |
| Duplicate `fmtMin` in `Overview.tsx` + `Operations.tsx` | DRY | Plan 1b reviewer |
| Duplicate `ReliabilityRow` type | DRY | Plan 1b reviewer |
| StopDrawer + AlertsBanner use raw `axios` instead of `api` from `lib/api.ts` | Inconsistency | Plan 1b reviewer |
| Sections silently swallow errors on primary fetch | UX hole | Plan 1b reviewer |
| Legacy `.kpi-card` rule in `styles.css` shadowed by `primitives.css` | Latent ordering dependency | Plan 1b reviewer |
| `Sidebar.tsx` (1,862 lines) still on disk, not rendered | Cleanup | Plans 1a + 1b deferral |
| `data-theme` attribute lives on `<div class="shell">` but tokens scope to `:root` | Theme toggle precondition | Plan 1a CSS audit |

### What's explicitly NOT in this plan (Plan 1d candidates)

- Trip planner reintegration (replaces MapView's stubbed `plannerOrigin`/`plannerDest`)
- CSV / PNG export per widget
- Multi-widget richness per section (more KPIs, more charts, paginated tables)
- Saved views / shareable URLs beyond the active section
- Agent rail enablement — that's Phase 2 per the spec

---

## File Structure

**New files:**
- `frontend/src/lib/format.ts` — shared formatting helpers (`fmtMin`, `fmtPct`, `fmtDelta`)
- `frontend/src/types/data.ts` — shared backend response types (`ReliabilityRow`, `TrendRow`, `SafetyRow`, `BunchingRow`, `VehicleFC`, `AgencyOtpRow`)
- `frontend/src/components/primitives/SectionError.tsx` — error panel
- `frontend/src/components/primitives/SectionError.test.tsx`
- `frontend/src/context/ThemeContext.tsx` — dark / light theme state + toggle
- `frontend/src/context/ThemeContext.test.tsx`
- `frontend/src/lib/useSectionRoute.ts` — hash-based section routing hook
- `frontend/src/lib/useSectionRoute.test.ts`

**Modified files:**
- `frontend/src/components/MapView.tsx` — fix the paint expression for `*-layer-border.circle-stroke-color`; subscribe to `selection.routeId` and apply a `filter` expression to stop circles
- `frontend/src/sections/Overview.tsx` — adopt shared types + format, surface fetch errors
- `frontend/src/sections/Operations.tsx` — same
- `frontend/src/sections/Network.tsx` — same
- `frontend/src/sections/EquitySafety.tsx` — same
- `frontend/src/sections/BenchmarksDrift.tsx` — same
- `frontend/src/components/StopDrawer.tsx` — use the `api` instance from `lib/api.ts`
- `frontend/src/components/AlertsBanner.tsx` — same
- `frontend/src/components/AppShell.tsx` — wrap in `ThemeProvider`, render a theme toggle in the header, drive section state from `useSectionRoute`
- `frontend/src/components/AppShell.test.tsx` — add a theme-toggle assertion + URL-hash assertion
- `frontend/src/design/tokens.css` — `data-theme="dark|light"` on `<html>` (not on `.shell`) so token vars actually flip
- `frontend/src/components/primitives/index.ts` — export `SectionError`
- `frontend/src/styles.css` — delete the dormant `.kpi-card` ruleset; rename other class collisions where Sidebar's deletion exposes them
- `frontend/src/App.tsx` — wrap providers including `ThemeProvider`

**Deleted files:**
- `frontend/src/components/Sidebar.tsx` (1,862 lines)
- `frontend/src/types.ts` — only if no other consumer survives the Sidebar deletion (the legacy `Section` union may still be referenced by MapView's layer dispatch; if so, keep `types.ts` but slim it)

---

## Task 1: Fix MapView paint expression errors

**Files:**
- Modify: `frontend/src/components/MapView.tsx`

`MapView.tsx:590` and `:612` add `reliability-layer-border` and `safety-layer-border` with `circle-stroke-color` expressions that fail Mapbox's style validation: `Type string is not interpolatable`. The fix depends on what the expression looks like — likely an `interpolate` whose stops mix a string color literal with a non-color value, or a `case` expression nested incorrectly.

- [ ] **Step 1: Inspect the offending expressions**

From `frontend/`:

```bash
sed -n '580,620p' src/components/MapView.tsx
```

Expected: see two `addLayer` blocks with `paint.circle-stroke-color` expressions. Note the expression shape.

- [ ] **Step 2: Identify the fix**

Mapbox's `interpolate` expressions require the stops' OUTPUT values to be numbers or colors written as `["rgba", ...]` / `["to-color", ...]` / `["literal", color]`. Bare color *string literals* (e.g. `"#ff0000"`) at interpolation stops are not interpolatable in newer Mapbox GL JS versions — they need to be wrapped or replaced.

If the expression looks like:

```js
"circle-stroke-color": [
  "case",
  ["==", ["get", "selected"], true],
  "interpolate", ...      // ← broken: interpolate cannot be a case branch like this
  "#ffffff"
]
```

…rewrite as a `match` / `case` whose branches are literal colors, and move any interpolation into a separate paint property. Or, if the expression is simply mixing color types, wrap each color in `["to-color", "#hex"]`.

The simplest defensive fix (if the expression is essentially "highlight on hover/select, otherwise gray"): replace with

```js
"circle-stroke-color": [
  "case",
  ["==", ["get", "stop_id"], ["literal", ""]], "#3b82f6",
  "rgba(255,255,255,0.3)"
]
```

…or similar — a plain `case` returning two color literals validates cleanly.

- [ ] **Step 3: Apply the fix**

Edit `MapView.tsx` so both `circle-stroke-color` expressions validate. Test in the browser by hard-reloading http://localhost:5173/ and confirming the console no longer prints the `Type string is not interpolatable` errors for those two layers. The other layers should keep rendering as before (delay heatmap, safety scores).

- [ ] **Step 4: Run tests**

```bash
npm run test:run
```

Expected: 29 passed (MapView test stays green because the mock doesn't validate paint expressions).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/MapView.tsx
git commit -m "$(cat <<'EOF'
MapView: fix circle-stroke-color paint validation

Two layers (reliability-layer-border, safety-layer-border) used
paint expressions that failed Mapbox GL JS style validation with
'Type string is not interpolatable'. Rewrite both to a plain case
expression returning literal colors, which validates cleanly under
the current Mapbox version.

The console-side error was harmless (the layers still rendered with
a fallback) but cluttered the console and may have caused subtle
visual differences. With the fix the two layers now render with the
intended stroke color in every state.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Shared format + types modules

**Files:**
- Create: `frontend/src/lib/format.ts`
- Create: `frontend/src/types/data.ts`

Lifts duplicated `fmtMin` (Overview + Operations) and `ReliabilityRow` interface (Overview + Operations) into shared modules. Sections that follow can import from one place.

- [ ] **Step 1: Create `frontend/src/lib/format.ts`**

```ts
/** Format a duration in seconds as a short human string.
 *  < 60s → "Ns"; >= 60s → "M.M min".
 */
export function fmtMin(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const s = Number(seconds);
  if (!isFinite(s)) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  return `${(s / 60).toFixed(1)} min`;
}

/** Format a percentage value (0–100) with one decimal place; null → "—". */
export function fmtPct(value: number | null | undefined): string {
  if (value == null || !isFinite(Number(value))) return "—";
  return `${Number(value).toFixed(1)}%`;
}

/** Format a signed delta with sign + one decimal. */
export function fmtDelta(value: number | null | undefined): string {
  if (value == null || !isFinite(Number(value))) return "—";
  const v = Number(value);
  return v >= 0 ? `+${v.toFixed(1)}` : v.toFixed(1);
}
```

- [ ] **Step 2: Create `frontend/src/types/data.ts`**

```ts
/** Shared backend response types. The sections each import the rows they
 *  consume. Field names track the actual /backend/app/main.py endpoints —
 *  any drift between these and the API is a bug worth fixing here, not in
 *  individual sections.
 */

export interface ReliabilityRow {
  route_id: string;
  sample_events: number;
  avg_delay_seconds: number;
  on_time_pct?: number;
}

export interface TrendRow {
  /** /reliability/trend uses `date`; older mock data may use `service_date`. */
  date?: string;
  service_date?: string;
  avg_delay: number | null;
}

export interface SafetyRow {
  stop_id: string;
  stop_name?: string;
  safety_score: number;
  crime_incidents_nearby?: number;
  collisions_nearby?: number;
}

export interface BunchingRow {
  route_id: string;
  event_count: number;
  late_events?: number;
  avg_delay_seconds?: number;
}

/** /vehicles/live is a GeoJSON FeatureCollection, not a flat array. */
export interface VehicleFC {
  type: "FeatureCollection";
  features: unknown[];
}

export interface AgencyOtpRow {
  agency_id: string;
  on_time_pct: number;
  avg_delay_seconds: number;
  sample_events: number;
}

export interface RouteRow {
  route_id: string;
  route_short_name?: string;
  agency_id?: string;
}
```

- [ ] **Step 3: Run tests**

```bash
npm run test:run
```

Expected: 29 passed (no consumers yet; modules added but unimported).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/format.ts frontend/src/types/data.ts
git commit -m "$(cat <<'EOF'
Add shared format helpers and backend response types

frontend/src/lib/format.ts: fmtMin, fmtPct, fmtDelta — the duration
and percentage helpers that were duplicated in Overview and
Operations now live in one place.

frontend/src/types/data.ts: ReliabilityRow, TrendRow, SafetyRow,
BunchingRow, VehicleFC, AgencyOtpRow, RouteRow — shared response
types so a backend field-name change shows up as one TS error
instead of five identical bugs across sections.

No section migrated to these yet; that lands in the next commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Migrate sections to shared types + format

**Files:**
- Modify: `frontend/src/sections/Overview.tsx`
- Modify: `frontend/src/sections/Operations.tsx`
- Modify: `frontend/src/sections/Network.tsx`
- Modify: `frontend/src/sections/EquitySafety.tsx`
- Modify: `frontend/src/sections/BenchmarksDrift.tsx`

Five small, mechanical replacements. Each section drops its local interface declarations and local `fmtMin`, imports from the shared modules instead.

- [ ] **Step 1: Update each section**

For each of the five section files:

1. Replace the local `interface ReliabilityRow {...}` / `interface TrendRow {...}` / etc. with `import { ReliabilityRow, TrendRow, ... } from "../types/data";`
2. Replace the local `function fmtMin(seconds: number) {...}` with `import { fmtMin } from "../lib/format";` and delete the local function.

Example diff for `Overview.tsx`:

```tsx
-interface ReliabilityRow {
-  route_id: string;
-  sample_events: number;
-  avg_delay_seconds: number;
-  on_time_pct?: number;
-}
-interface TrendRow { date?: string; service_date?: string; avg_delay: number | null; }
-interface SafetyRow { stop_id: string; safety_score: number; }
-
-function fmtMin(seconds: number): string {
-  if (seconds < 60) return `${Math.round(seconds)}s`;
-  return `${(seconds / 60).toFixed(1)} min`;
-}
+import { ReliabilityRow, TrendRow, SafetyRow } from "../types/data";
+import { fmtMin, fmtPct } from "../lib/format";
```

Then in the JSX, swap `${networkOtp.toFixed(1)}%` for `fmtPct(networkOtp)`.

- [ ] **Step 2: Run the full suite**

```bash
npm run test:run
```

Expected: 29 passed (tests don't import these; they just call the components).

- [ ] **Step 3: Run the type-check**

```bash
npx tsc --noEmit
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/sections/Overview.tsx frontend/src/sections/Operations.tsx frontend/src/sections/Network.tsx frontend/src/sections/EquitySafety.tsx frontend/src/sections/BenchmarksDrift.tsx
git commit -m "$(cat <<'EOF'
Migrate sections to shared types + format helpers

Replaces five local copies of ReliabilityRow / TrendRow / etc. with
imports from frontend/src/types/data.ts, and five local fmtMin
helpers with frontend/src/lib/format.ts. Calls to fmtMin/fmtPct
gain null tolerance from the shared implementation.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `SectionError` primitive + per-section error state

**Files:**
- Create: `frontend/src/components/primitives/SectionError.tsx`
- Create: `frontend/src/components/primitives/SectionError.test.tsx`
- Modify: `frontend/src/components/primitives/index.ts`
- Modify: `frontend/src/sections/Overview.tsx` (and the other four sections)
- Append: `frontend/src/components/primitives/primitives.css`

Sections currently render empty KPIs when a fetch fails — the user can't tell the difference between "no data" and "network error". A small `SectionError` primitive and an `error` state in each section closes that hole.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/primitives/SectionError.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SectionError } from "./SectionError";

describe("SectionError", () => {
  it("renders the title and message", () => {
    render(<SectionError title="Failed to load" message="Backend returned 500" />);
    expect(screen.getByText("Failed to load")).toBeInTheDocument();
    expect(screen.getByText("Backend returned 500")).toBeInTheDocument();
  });

  it("calls onRetry when the retry button is clicked", async () => {
    const onRetry = vi.fn();
    render(<SectionError message="Network error" onRetry={onRetry} />);
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run → FAIL**

```bash
npm run test:run -- src/components/primitives/SectionError.test.tsx
```

- [ ] **Step 3: Implement `SectionError`**

```tsx
import React from "react";
import "./primitives.css";

export interface SectionErrorProps {
  title?: string;
  message: string;
  onRetry?: () => void;
}

export const SectionError: React.FC<SectionErrorProps> = ({ title = "Couldn't load this section", message, onRetry }) => (
  <div className="section-error" role="alert">
    <p className="section-error__title">{title}</p>
    <p className="section-error__msg">{message}</p>
    {onRetry && (
      <button type="button" className="section-error__retry" onClick={onRetry}>
        Retry
      </button>
    )}
  </div>
);
```

Append to `primitives.css`:

```css
.section-error {
  padding: var(--space-5);
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.35);
  border-radius: var(--radius-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  text-align: center;
}
.section-error__title { font-weight: 600; color: var(--color-critical); margin: 0; }
.section-error__msg   { color: var(--color-fg-2); font-size: var(--text-sm); margin: 0; }
.section-error__retry {
  align-self: center;
  background: transparent;
  border: 1px solid var(--color-border);
  color: var(--color-fg-0);
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-2);
  cursor: pointer;
  font: inherit;
  font-size: var(--text-sm);
}
.section-error__retry:hover { background: var(--color-bg-2); }
```

- [ ] **Step 4: Add to barrel export**

In `frontend/src/components/primitives/index.ts`, append:

```ts
export { SectionError } from "./SectionError";
export type { SectionErrorProps } from "./SectionError";
```

- [ ] **Step 5: Add error state to each section**

For each of the five sections, the pattern is the same. Example for Overview:

```tsx
const [error, setError] = useState<string | null>(null);

useEffect(() => {
  let cancelled = false;
  async function fetchAll() {
    setLoading(true);
    setError(null);
    try {
      const [rel, trend, routes, safety] = await Promise.all([...]);
      if (cancelled) return;
      // ... existing setState calls
    } catch (err) {
      if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      if (!cancelled) setLoading(false);
    }
  }
  fetchAll();
  return () => { cancelled = true; };
}, [filters.startDate, filters.endDate]);
```

Then in JSX, render `<SectionError message={error} onRetry={() => setError(null) /* effect retries via dep change */} />` at the top of the section body if `error` is set. Simplest pattern: replace the whole section body with the SectionError when `error` is non-null.

Apply to Overview, Operations, Network, EquitySafety, BenchmarksDrift.

- [ ] **Step 6: Run → all green**

```bash
npm run test:run
```

Expected: 31 passed (29 existing + 2 new SectionError).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/primitives/SectionError.tsx \
        frontend/src/components/primitives/SectionError.test.tsx \
        frontend/src/components/primitives/primitives.css \
        frontend/src/components/primitives/index.ts \
        frontend/src/sections/
git commit -m "$(cat <<'EOF'
Surface fetch errors in every section

Adds a SectionError primitive (alert role + retry button) and wires
each of the five sections to render it when the primary Promise.all
rejects. Closes the Plan 1b reviewer note about silently-empty
sections on a network error.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `ThemeContext` + dark/light toggle

**Files:**
- Create: `frontend/src/context/ThemeContext.tsx`
- Create: `frontend/src/context/ThemeContext.test.tsx`
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/components/AppShell.test.tsx`
- Modify: `frontend/src/App.tsx` (add the provider)
- Modify: `frontend/src/design/tokens.css` (move `data-theme` scope from elements to `:root`)

Today the dark tokens apply because `:root` has them by default; the `data-theme="dark"` on the `.shell` div is decorative. To toggle, we need to set `data-theme` on `<html>`.

- [ ] **Step 1: Write the failing test**

`frontend/src/context/ThemeContext.test.tsx`:

```tsx
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider, useTheme } from "./ThemeContext";

function Probe() {
  const { theme, toggle, setTheme } = useTheme();
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <button onClick={toggle}>toggle</button>
      <button onClick={() => setTheme("light")}>light</button>
    </div>
  );
}

describe("ThemeContext", () => {
  beforeEach(() => {
    document.documentElement.removeAttribute("data-theme");
    window.localStorage.clear();
  });

  it("defaults to dark and sets data-theme on <html>", () => {
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByTestId("theme").textContent).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("toggles dark ↔ light", async () => {
    render(<ThemeProvider><Probe /></ThemeProvider>);
    await userEvent.click(screen.getByText("toggle"));
    expect(screen.getByTestId("theme").textContent).toBe("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("setTheme writes to localStorage", async () => {
    render(<ThemeProvider><Probe /></ThemeProvider>);
    await userEvent.click(screen.getByText("light"));
    expect(window.localStorage.getItem("batis.theme")).toBe("light");
  });
});
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement `ThemeContext`**

```tsx
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

export type Theme = "dark" | "light";

interface ThemeApi {
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeApi | null>(null);
const STORAGE_KEY = "batis.theme";

function readInitialTheme(): Theme {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch { /* localStorage unavailable */ }
  return "dark";
}

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [theme, setThemeState] = useState<Theme>(() => readInitialTheme());

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try { window.localStorage.setItem(STORAGE_KEY, theme); } catch { /* ignore */ }
  }, [theme]);

  const setTheme = useCallback((t: Theme) => setThemeState(t), []);
  const toggle   = useCallback(() => setThemeState(t => t === "dark" ? "light" : "dark"), []);

  const value = useMemo<ThemeApi>(() => ({ theme, setTheme, toggle }), [theme, setTheme, toggle]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
};

export function useTheme(): ThemeApi {
  const v = useContext(ThemeContext);
  if (!v) throw new Error("useTheme must be used inside a ThemeProvider");
  return v;
}
```

- [ ] **Step 4: Confirm the new tests pass**

```bash
npm run test:run -- src/context/ThemeContext.test.tsx
```

Expected: 3 passed.

- [ ] **Step 5: Update `tokens.css` to scope dark/light to `:root` only**

The current file already scopes `:root` and `:root[data-theme="dark"]` identically (defaulting to dark) and `:root[data-theme="light"]` to light values. That's correct — no edit needed in `tokens.css` itself. Just verify by reading the file.

- [ ] **Step 6: Add a theme toggle button to `AppShell.tsx`**

Insert into the header, after the brand span (or at the right edge before the nav, whichever feels right):

```tsx
import { useTheme } from "../context/ThemeContext";

// inside AppShell:
const { theme, toggle } = useTheme();

// in the header JSX, after the nav:
<button
  type="button"
  className="shell-header__theme-toggle"
  onClick={toggle}
  aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
  title={theme === "dark" ? "Switch to light" : "Switch to dark"}
>
  {theme === "dark" ? "☀" : "🌙"}
</button>
```

Append to `shell.css`:

```css
.shell-header__theme-toggle {
  appearance: none;
  background: transparent;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-pill);
  color: var(--color-fg-1);
  width: 32px;
  height: 32px;
  cursor: pointer;
  font-size: 14px;
}
.shell-header__theme-toggle:hover { color: var(--color-fg-0); background: var(--color-bg-2); }
```

Remove the now-redundant `data-theme="dark"` attribute from the `<div class="shell">` element (it's owned by ThemeProvider on `<html>`).

- [ ] **Step 7: Update `AppShell.test.tsx` for the toggle**

Add a new test inside the existing `describe`:

```tsx
  it("renders a theme toggle that flips data-theme on <html>", async () => {
    render(wrap(<AppShell />));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    await userEvent.click(screen.getByLabelText(/switch to light theme/i));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });
```

Also update the existing `wrap` helper to include `ThemeProvider`:

```tsx
import { ThemeProvider } from "../context/ThemeContext";

function wrap(ui: React.ReactElement) {
  return (
    <ThemeProvider>
      <FilterProvider>
        <SelectionProvider>{ui}</SelectionProvider>
      </FilterProvider>
    </ThemeProvider>
  );
}
```

- [ ] **Step 8: Update `App.tsx`**

```tsx
import React from "react";
import { ThemeProvider } from "./context/ThemeContext";
import { FilterProvider } from "./context/FilterContext";
import { SelectionProvider } from "./context/SelectionContext";
import { AppShell } from "./components/AppShell";

export const App: React.FC = () => (
  <ThemeProvider>
    <FilterProvider>
      <SelectionProvider>
        <AppShell />
      </SelectionProvider>
    </FilterProvider>
  </ThemeProvider>
);
```

- [ ] **Step 9: Run + verify**

```bash
npm run test:run
```

Expected: 35 passed (31 existing + 3 ThemeContext + 1 AppShell theme test).

- [ ] **Step 10: Commit**

```bash
git add frontend/src/context/ThemeContext.tsx frontend/src/context/ThemeContext.test.tsx \
        frontend/src/components/AppShell.tsx frontend/src/components/AppShell.test.tsx \
        frontend/src/App.tsx frontend/src/design/shell.css
git commit -m "$(cat <<'EOF'
Add ThemeContext + dark/light toggle in the header

ThemeProvider owns the theme state, persists to localStorage, and
writes data-theme="dark|light" onto <html> so the CSS variable
scopes in tokens.css actually flip. AppShell renders a small toggle
button on the right side of the header. The data-theme="dark"
attribute on the .shell div (decorative in Plans 1a/1b) is dropped.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: URL routing for the active section

**Files:**
- Create: `frontend/src/lib/useSectionRoute.ts`
- Create: `frontend/src/lib/useSectionRoute.test.ts`
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/components/AppShell.test.tsx`

A reload currently snaps back to Overview. Encode the active section in the URL hash (`#operations`, `#network`, …) so reload, back/forward, and shareable links all work without adding a router dependency.

- [ ] **Step 1: Write the failing test**

`frontend/src/lib/useSectionRoute.test.ts`:

```ts
import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSectionRoute } from "./useSectionRoute";

describe("useSectionRoute", () => {
  beforeEach(() => { window.location.hash = ""; });

  it("defaults to overview when the hash is empty", () => {
    const { result } = renderHook(() => useSectionRoute());
    expect(result.current.section).toBe("overview");
  });

  it("reads a valid section from the hash on init", () => {
    window.location.hash = "#network";
    const { result } = renderHook(() => useSectionRoute());
    expect(result.current.section).toBe("network");
  });

  it("ignores an unknown hash and falls back to overview", () => {
    window.location.hash = "#wat";
    const { result } = renderHook(() => useSectionRoute());
    expect(result.current.section).toBe("overview");
  });

  it("setSection writes the hash", () => {
    const { result } = renderHook(() => useSectionRoute());
    act(() => result.current.setSection("equity"));
    expect(window.location.hash).toBe("#equity");
    expect(result.current.section).toBe("equity");
  });

  it("responds to external hashchange events (back/forward)", () => {
    const { result } = renderHook(() => useSectionRoute());
    act(() => {
      window.location.hash = "#benchmarks";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(result.current.section).toBe("benchmarks");
  });
});
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement the hook**

```ts
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
```

- [ ] **Step 4: Confirm new tests pass**

```bash
npm run test:run -- src/lib/useSectionRoute.test.ts
```

Expected: 5 passed.

- [ ] **Step 5: Drive `AppShell` from the hook**

In `AppShell.tsx`, replace:

```tsx
const [active, setActive] = useState<SectionKey>("overview");
```

with:

```tsx
import { useSectionRoute } from "../lib/useSectionRoute";

const { section: active, setSection: setActive } = useSectionRoute();
```

Remove `useState` and the local `SectionKey` type definition; export `SectionKey` from `useSectionRoute.ts` and re-export from `AppShell.tsx` for compatibility.

- [ ] **Step 6: Update `AppShell.test.tsx`**

Add a new test:

```tsx
  it("writes the hash when a tab is clicked", async () => {
    window.location.hash = "";
    render(wrap(<AppShell />));
    await userEvent.click(screen.getByRole("tab", { name: "Equity & Safety" }));
    expect(window.location.hash).toBe("#equity");
  });
```

- [ ] **Step 7: Run + verify**

```bash
npm run test:run
```

Expected: 41 passed (35 from Task 5 + 5 useSectionRoute + 1 AppShell hash test).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/useSectionRoute.ts frontend/src/lib/useSectionRoute.test.ts \
        frontend/src/components/AppShell.tsx frontend/src/components/AppShell.test.tsx
git commit -m "$(cat <<'EOF'
Persist the active section in the URL hash

Adds a useSectionRoute hook that reads/writes the active section as
a URL hash (`#operations`, `#network`, …). AppShell drives its tabs
from this hook, so reload + back/forward + shareable links all work
without pulling in a router dependency. Unknown hashes fall back to
overview.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Migrate StopDrawer + AlertsBanner to the `api` instance

**Files:**
- Modify: `frontend/src/components/StopDrawer.tsx`
- Modify: `frontend/src/components/AlertsBanner.tsx`

Both still use raw `axios` + inline API_BASE / API_KEY duplication. Switch to the `api` instance from `lib/api.ts` for consistency.

- [ ] **Step 1: Update `StopDrawer.tsx`**

Replace the top of the file:

```tsx
-import axios from "axios";
+import { api } from "../lib/api";

-const API_BASE = (import.meta.env.VITE_API_BASE_URL as string) || "http://localhost:8000";
-const API_KEY  = (import.meta.env.VITE_API_KEY  as string) || "";
-function h() { return API_KEY ? { "X-API-Key": API_KEY } : {}; }
```

Then replace each `axios.get(`${API_BASE}/stops/${sid}`, { headers: h() })` with `api.get(`/stops/${sid}`)`. The `api` instance already attaches the API key via `apiHeaders()`.

- [ ] **Step 2: Update `AlertsBanner.tsx`**

Same pattern: import `api` from `lib/api`, replace inline boilerplate, change `axios.get(`${API_BASE}/alerts`)` to `api.get("/alerts")`. Note: `/alerts` is not auth-protected on the backend, but using `api` is fine — it sends the header but the endpoint ignores it.

- [ ] **Step 3: Run + verify**

```bash
npm run test:run
```

Expected: 41 passed (no test changes; existing tests still cover both components).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/StopDrawer.tsx frontend/src/components/AlertsBanner.tsx
git commit -m "$(cat <<'EOF'
StopDrawer + AlertsBanner: use the api instance

Drops duplicated API_BASE / API_KEY / apiHeaders boilerplate; both
components now go through the shared axios instance in lib/api.ts.
Closes the Plan 1b reviewer note about inconsistent HTTP wiring.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: MapView cross-filter — highlight `selection.routeId`

**Files:**
- Modify: `frontend/src/components/MapView.tsx`

When a section writes `selection.routeId`, MapView should react. Plan 1c does the minimum useful thing: dim stop circles that aren't on the selected route. The existing layer logic already has a `selectedRouteId` ref; this task wires the actual visual effect.

- [ ] **Step 1: Locate the existing `selectedRouteIdRef` usage**

```bash
grep -n "selectedRouteIdRef" frontend/src/components/MapView.tsx
```

Expected: a ref declared near the top of the component, used inside an effect that runs on `[selectedRouteId]`.

- [ ] **Step 2: Apply a `filter` expression to the stop circle layers**

Inside the effect that fires on `selectedRouteId`, find the call to `map.setFilter(...)` (or add one if not present) for `reliability-layer` / `safety-layer` / `crowding-layer` / `demand-layer`. The filter should match `route_id` membership:

```ts
useEffect(() => {
  if (!mapRef.current || !mapRef.current.isStyleLoaded()) return;
  const routeId = selection.routeId;
  const filter = routeId
    ? ["any", ["==", ["get", "route_id"], routeId], ["in", routeId, ["get", "routes_serving"]]]
    : null;
  for (const layer of ["reliability-layer", "safety-layer", "crowding-layer", "demand-layer"]) {
    if (mapRef.current.getLayer(layer)) {
      mapRef.current.setFilter(layer, filter as mapboxgl.FilterSpecification);
    }
  }
}, [selection.routeId]);
```

(Naming / variables may need to track the existing code's conventions — match what's already there.)

- [ ] **Step 3: Manual browser check**

Hard-reload the dashboard. In Operations, click a route in the Slowest Performers list. The map's stop layer should filter to only stops on that route (or that include it in their `routes_serving` array, depending on how the backend properties are shaped). Clicking again on the same route should keep the selection. Selecting another route updates the filter. Switching sections still keeps the selection.

- [ ] **Step 4: Run tests**

```bash
npm run test:run
```

Expected: 41 passed (MapView's vitest mock doesn't validate filter expressions; this is purely a runtime behaviour).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/MapView.tsx
git commit -m "$(cat <<'EOF'
MapView: apply a route filter when selection.routeId is set

When a section writes a routeId into SelectionContext, MapView now
applies a filter expression to the stop circle layers so only stops
on that route remain visible. Clearing the selection (clicking the
same row twice, or switching back to overview) removes the filter.

Cross-filter from list → map is the user-visible glue between
Plan 1a/1b's section content and the existing map. Plan 1d can
extend this with hover-driven highlighting and selection-driven
route shape rendering.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Retire `Sidebar.tsx` + legacy CSS cleanup

**Files:**
- Delete: `frontend/src/components/Sidebar.tsx`
- Modify: `frontend/src/styles.css` (delete the dormant `.kpi-card` ruleset)
- Modify: `frontend/src/types.ts` (slim or delete depending on remaining consumers)

`Sidebar.tsx` (1,862 lines) has been on disk unmounted since Plan 1a. With Plans 1a–1c's section content in place, nothing imports it. Same for the dormant `.kpi-card` rule in `styles.css` and (possibly) `frontend/src/types.ts`'s legacy `Section` union.

- [ ] **Step 1: Confirm no imports of Sidebar remain**

```bash
grep -rn "from .*[\"']\./Sidebar\|from .*[\"']\./components/Sidebar\|import.*Sidebar" frontend/src
```

Expected: zero hits, or only matches inside Sidebar.tsx itself.

- [ ] **Step 2: Delete the file**

```bash
git rm frontend/src/components/Sidebar.tsx
```

- [ ] **Step 3: Check if `types.ts`'s `Section` union is still consumed**

```bash
grep -rn "from .*[\"']\.\./types\|from .*[\"']\./types" frontend/src
```

If only `MapView.tsx` and `SectionMap.tsx` still import `Section`, keep `types.ts`. If nothing imports it, `git rm` it.

- [ ] **Step 4: Drop the dormant `.kpi-card` block from `styles.css`**

```bash
grep -n "^\.kpi-card[^_]" frontend/src/styles.css
```

If the match is the bare `.kpi-card { ... }` rule (no `__` BEM children), delete that block. Keep any rules used elsewhere.

- [ ] **Step 5: Run tests + typecheck**

```bash
npm run test:run
npx tsc --noEmit
```

Expected: 41 passed, no type errors.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
Retire Sidebar.tsx and the dormant .kpi-card legacy CSS

The 1,862-line Sidebar.tsx has been unmounted since Plan 1a; with
all five sections fully populated by Plans 1b/1c, nothing imports
it any more. Delete the file. Same fate for the bare .kpi-card rule
in styles.css — primitives.css owns the new KPI cards via BEM
classes, so the legacy rule was dormant and a latent collision
risk. If types.ts's legacy Section union still has consumers
(MapView, SectionMap), leave it; otherwise drop that too.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Browser QA + final test pass

**Files:** none modified.

- [ ] **Step 1: Confirm the dockerized stack is running**

```bash
docker compose ps
```

Expected: postgres, postgres-test, backend, frontend all up + healthy.

- [ ] **Step 2: Open http://localhost:5173/ in a browser, hard reload**

Expected:
- Dashboard renders the new shell, dark theme by default
- Theme toggle on the right side of the header flips dark ↔ light without remount
- Reload while on Operations stays on Operations (URL has `#operations`)
- Back / Forward buttons walk through section history
- No "Type string is not interpolatable" errors in the DevTools console
- Clicking a route in any section's list dims other routes on the map
- Throwing the backend offline (`docker compose stop backend`) shows a `SectionError` with a Retry button in each section

- [ ] **Step 3: Run the final test suite**

```bash
cd frontend && npm run test:run
```

Expected: 41 passed.

- [ ] **Step 4: Final typecheck**

```bash
npx tsc --noEmit
```

Expected: clean.

- [ ] **Step 5: Sign off**

If any check fails, file the issue and fix before marking Phase 1 complete. Otherwise Phase 1 is done — Plan 1d (planner, exports, multi-widget richness) and Phase 2 (Agent foundation) can begin.

---

## Verification (end-to-end)

After all tasks complete:

1. **Fresh install + tests pass:**
   ```bash
   cd frontend && npm install && npm run test:run
   ```
   Expected: 41 tests pass.

2. **Theme toggle persists across reload**: switch to light, hard-reload, still light.

3. **Section persists across reload**: navigate to `#equity`, reload, still on Equity & Safety.

4. **Cross-filter works**: click a route in Operations, switch to Network, the same route stays highlighted (selection persists across sections).

5. **Type check clean:**
   ```bash
   cd frontend && npx tsc --noEmit
   ```

---

## What this plan does NOT do

Deferred to Plan 1d:

- Trip planner reintegration (planner mapMode + Network UI)
- CSV / PNG export per widget
- Multi-widget richness per section (more KPIs, supporting charts, paginated tables)
- Saved views beyond the active section (e.g. saving the date range + selection as a named view)
- Search-as-filter on the map (Plan 1c only filters lists)
- Agent rail enablement — Phase 2, per the master spec

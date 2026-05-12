import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterProvider } from "../context/FilterContext";
import { ThemeProvider } from "../context/ThemeContext";
import { AgenciesProvider } from "../context/AgenciesContext";
import { SelectionProvider } from "../context/SelectionContext";
import { Planning } from "./Planning";

vi.mock("mapbox-gl", () => ({
  default: {
    accessToken: "",
    Map: vi.fn().mockImplementation(() => ({
      on: vi.fn(), off: vi.fn(), addControl: vi.fn(), remove: vi.fn(),
      getStyle: vi.fn(() => ({ layers: [] })),
      isStyleLoaded: vi.fn(() => false), setStyle: vi.fn(),
      getSource: vi.fn(), getLayer: vi.fn(), getCanvas: vi.fn(() => ({ style: {} })),
    })),
    NavigationControl: vi.fn(),
    ScaleControl: vi.fn(),
    Popup: vi.fn().mockImplementation(() => ({
      setLngLat: function() { return this; },
      setHTML:  function() { return this; },
      addTo:    function() { return this; },
      remove:   function() { return this; },
    })),
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
        if (url.startsWith("/bunching/summary"))     return { data: [{ route_id: "51B", bunched_events: 12 }] };
        if (url.startsWith("/safety/stops"))         return { data: [{ stop_id: "S1", stop_name: "Hot Stop", safety_score: 11 }] };
        if (url.startsWith("/crowding/predictions")) return { data: [{ route_id: "51B", crowding_level: "high" }] };
        if (url.startsWith("/coverage/cells")) {
          return { data: { features: [
            { properties: { cell_id: "C1", distance_to_nearest_stop_m: 800, stops_within_walk: 0, effective_frequency_per_hour: 0.5, equity_score: 0.3 } },
            { properties: { cell_id: "C2", distance_to_nearest_stop_m: 200, stops_within_walk: 4, effective_frequency_per_hour: 4,   equity_score: 0.1 } },
          ] } };
        }
        if (url.startsWith("/coverage/deserts")) {
          return { data: { features: [
            { properties: { id: 1, desert_score: 0.85, notes: "West Oakland gap" } },
            { properties: { id: 2, desert_score: 0.62, notes: null } },
          ] } };
        }
        if (url === "/agencies") {
          return { data: [
            { agency_id: "AC", agency_name: "AC Transit", agency_type: "bus",  monitored: true, has_data: true },
            { agency_id: "BA", agency_name: "BART",       agency_type: "rail", monitored: true, has_data: true },
            { agency_id: "5E", agency_name: "511 Emergency", agency_type: "other", monitored: false, has_data: false },
          ] };
        }
        if (url.startsWith("/agencies/rollup")) {
          return { data: [
            { agency_id: "AC", agency_name: "AC Transit", monitored: true, routes_count: 76, stops_count: 4707, otp_pct: 82.5, avg_delay_seconds: 120, sample_events: 5000, hot_stops: 12, alerts_active: 3 },
            { agency_id: "BA", agency_name: "BART",       monitored: true, routes_count: 14, stops_count:  287, otp_pct: 94.2, avg_delay_seconds:  32, sample_events: 3000, hot_stops:  1, alerts_active: 1 },
            { agency_id: "5E", agency_name: "511 Emergency", monitored: false, routes_count: 0, stops_count: 0, otp_pct: null, avg_delay_seconds: null, sample_events: 0, hot_stops: 0, alerts_active: 0 },
          ] };
        }
        if (url.startsWith("/equity/score")) {
          return { data: { features: [
            { properties: { cell_id: "C1", equity_score: 0.3, low_income_population: 800, no_car_households: 120, population: 1200, equity_tier: "very_high" } },
            { properties: { cell_id: "C2", equity_score: 0.1, low_income_population: 100, no_car_households: 20,  population: 800,  equity_tier: "low"       } },
          ] } };
        }
        return { data: [] };
      }),
    },
  };
});

function wrap(ui: React.ReactElement) {
  return (
    <ThemeProvider>
      <AgenciesProvider>
        <FilterProvider>
          <SelectionProvider>{ui}</SelectionProvider>
        </FilterProvider>
      </AgenciesProvider>
    </ThemeProvider>
  );
}

describe("Planning", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.location.hash = "#planning";
  });

  it("renders the sub-nav with all 5 sub-pages", () => {
    render(wrap(<Planning />));
    for (const label of ["Diagnostics", "Coverage", "Regional", "Workbench", "Scenarios"]) {
      expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
    }
  });

  it("defaults to Diagnostics when no subsection is in the URL", async () => {
    render(wrap(<Planning />));
    await waitFor(() => expect(screen.getByRole("heading", { name: /^Diagnostics$/i })).toBeInTheDocument());
  });

  it("clicking a sub-nav tab switches the body and writes the hash", async () => {
    render(wrap(<Planning />));
    await userEvent.click(screen.getByRole("tab", { name: "Coverage" }));
    expect(window.location.hash).toContain("#planning");
    expect(window.location.hash).toContain("sub=coverage");
    expect(await screen.findByRole("heading", { name: /^Coverage$/i })).toBeInTheDocument();
  });

  it("renders the Diagnostics KPI strip from mocked endpoints", async () => {
    render(wrap(<Planning />));
    await waitFor(() => expect(screen.getByText(/Network OTP/i)).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: /OTP triage queue/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Hot stops needing investment/i })).toBeInTheDocument();
  });

  it("falls back to Diagnostics for an unknown sub key", async () => {
    window.location.hash = "#planning?sub=bogus";
    render(wrap(<Planning />));
    await waitFor(() => expect(screen.getByRole("heading", { name: /^Diagnostics$/i })).toBeInTheDocument());
  });

  it("Regional sub-page filters out non-useful agencies and ranks the leaderboard", async () => {
    window.location.hash = "#planning?sub=regional";
    render(wrap(<Planning />));
    await waitFor(() => expect(screen.getByRole("heading", { name: /Cross-agency leaderboard/i })).toBeInTheDocument());
    // BART + AC Transit both appear (in multiple places — leaderboard
    // row, KPI sub-labels, etc.). Just verify presence at least once.
    expect(screen.getAllByText("BART").length).toBeGreaterThan(0);
    expect(screen.getAllByText("AC Transit").length).toBeGreaterThan(0);
    // 511 Emergency (has_data=false) is filtered out entirely.
    expect(screen.queryByText("511 Emergency")).not.toBeInTheDocument();
    // Best/Worst OTP show the right agency by name.
    const bestKpi = screen.getByText(/^Best OTP$/i).closest(".kpi-card");
    expect(bestKpi?.textContent).toMatch(/BART/);
    const worstKpi = screen.getByText(/^Worst OTP$/i).closest(".kpi-card");
    expect(worstKpi?.textContent).toMatch(/AC Transit/);
  });

  it("Coverage sub-page composes the underserved-zones list from equity × coverage", async () => {
    window.location.hash = "#planning?sub=coverage";
    render(wrap(<Planning />));
    // C1 is high-need (very_high tier) AND poor access (800 m > 400) → appears.
    await waitFor(() => expect(screen.getByRole("heading", { name: /Highest-need underserved zones/i })).toBeInTheDocument());
    expect(screen.getByText("C1")).toBeInTheDocument();
    // C2 is low-tier and good access → does NOT appear in the underserved list.
    expect(screen.queryByText("C2")).not.toBeInTheDocument();
    // Transit deserts panel renders the ranked notes.
    expect(screen.getByText(/West Oakland gap/i)).toBeInTheDocument();
    // KPI: underserved high-need population is C1's 1200 → 1.2k.  Both
    // "High-need residents" and "Underserved high-need" cards show the
    // same value here because C1 is the only high-need cell and it has
    // poor access, so getAllByText returns two matches.
    expect(screen.getAllByText("1.2k").length).toBeGreaterThanOrEqual(1);
  });
});

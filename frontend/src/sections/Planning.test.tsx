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
});

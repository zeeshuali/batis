import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterProvider } from "../context/FilterContext";
import { ThemeProvider } from "../context/ThemeContext";
import { AgenciesProvider } from "../context/AgenciesContext";
import { SelectionProvider } from "../context/SelectionContext";
import { Agency } from "./Agency";

vi.mock("mapbox-gl", () => ({
  default: {
    accessToken: "",
    Map: vi.fn().mockImplementation(() => ({
      on: vi.fn(), off: vi.fn(), addControl: vi.fn(), remove: vi.fn(),
      getStyle: vi.fn(() => ({ layers: [] })),
      isStyleLoaded: vi.fn(() => false), setStyle: vi.fn(),
      getSource: vi.fn(), getLayer: vi.fn(), getCanvas: vi.fn(() => ({ style: {} })),
      fitBounds: vi.fn(),
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
        if (url === "/agencies") {
          return { data: [{ agency_id: "AC", agency_name: "AC Transit", agency_type: "bus", monitored: true }] };
        }
        if (url.startsWith("/reliability/summary")) {
          return { data: [
            { route_id: "51B", sample_events: 200, avg_delay_seconds: 240, on_time_pct: 55 },
          ] };
        }
        if (url.startsWith("/routes")) {
          return { data: [{ route_id: "51B", route_short_name: "51B", agency_id: "AC" }] };
        }
        if (url.startsWith("/alerts")) {
          return { data: [{ id: "a1", header: "Detour on Telegraph", effect: "DETOUR", agency_id: "AC" }] };
        }
        if (url.startsWith("/vehicles/live")) return { data: [{ vehicle_id: "V1" }, { vehicle_id: "V2" }] };
        if (url.startsWith("/safety/stops"))  return { data: [{ stop_id: "S1" }, { stop_id: "S2" }, { stop_id: "S3" }] };
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

describe("Agency", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.location.hash = "#agency?id=AC";
  });

  it("renders the header with name + type + Live RT chip", async () => {
    render(wrap(<Agency />));
    await waitFor(() => expect(screen.getByText("AC Transit")).toBeInTheDocument());
    expect(screen.getByText(/Live RT/)).toBeInTheDocument();
  });

  it("renders 7 KPI cards from the mocked endpoints", async () => {
    render(wrap(<Agency />));
    await waitFor(() => expect(screen.getByText("AC Transit")).toBeInTheDocument());
    for (const label of ["Routes", "Stops", "Network OTP", "Avg delay", "Live vehicles", "Active alerts", "Hot stops"]) {
      // "Routes" also appears as a panel heading further down — getAllByText
      // tolerates that without weakening the assertion.
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
  });

  it("Back to Overview clears section + agency_id", async () => {
    render(wrap(<Agency />));
    await waitFor(() => expect(screen.getByText("AC Transit")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /Back to Overview/i }));
    expect(window.location.hash).toBe("#overview");
  });

  it("shows an empty state when no agency_id is in the URL", async () => {
    window.location.hash = "#agency";
    render(wrap(<Agency />));
    await waitFor(() => expect(screen.getByText(/Pick an agency/i)).toBeInTheDocument());
  });
});

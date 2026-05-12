import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { FilterProvider } from "../context/FilterContext";
import { ThemeProvider } from "../context/ThemeContext";
import { AgenciesProvider } from "../context/AgenciesContext";
import { SelectionProvider } from "../context/SelectionContext";
import { EquitySafety } from "./EquitySafety";

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
        if (url.startsWith("/equity/score")) {
          return { data: { features: [
            { properties: { equity_score: 0.15 } }, { properties: { equity_score: 0.06 } },
          ] } };
        }
        if (url.startsWith("/safety/stops")) {
          return { data: [
            { stop_id: "S0", stop_name: "Low 0",  safety_score: 1 },
            { stop_id: "S1", stop_name: "Mid 1",  safety_score: 3 },
            { stop_id: "S2", stop_name: "Mid 2",  safety_score: 6 },
            { stop_id: "S3", stop_name: "Hot 3",  safety_score: 9 },
            { stop_id: "S4", stop_name: "Hot 4",  safety_score: 12 },
          ] };
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

describe("EquitySafety", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the four KPIs and a hot-stops list", async () => {
    render(wrap(<EquitySafety />));
    await waitFor(() => expect(screen.getByText(/Hot 3/i)).toBeInTheDocument());
    expect(screen.getByText(/Tracts/i)).toBeInTheDocument();
    expect(screen.getByText(/Avg equity/i)).toBeInTheDocument();
    expect(screen.getByText(/Hot stops/i)).toBeInTheDocument();
  });

  it("renders a safety score distribution chart", async () => {
    render(wrap(<EquitySafety />));
    await waitFor(() => expect(screen.getByRole("heading", { name: /Safety score distribution/i })).toBeInTheDocument());
  });
});

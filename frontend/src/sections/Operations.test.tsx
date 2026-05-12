import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { FilterProvider } from "../context/FilterContext";
import { ThemeProvider } from "../context/ThemeContext";
import { AgenciesProvider } from "../context/AgenciesContext";
import { SelectionProvider } from "../context/SelectionContext";
import { Operations } from "./Operations";

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
      setHTML: function() { return this; },
      addTo: function() { return this; },
      remove: function() { return this; },
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
        if (url.startsWith("/vehicles/live")) {
          return { data: [{ vehicle_id: "V1" }, { vehicle_id: "V2" }, { vehicle_id: "V3" }] };
        }
        if (url.startsWith("/bunching/summary")) {
          return { data: [{ route_id: "51B", bunched_events: 12 }] };
        }
        if (url.startsWith("/crowding/predictions")) {
          return { data: [
            { route_id: "51B", trip_id: null, stop_id: null, service_date: "2026-05-12", time_bucket: "AM_PEAK", crowding_level: "high", model_version: "v1" },
            { route_id: "51B", trip_id: null, stop_id: null, service_date: "2026-05-12", time_bucket: "AM_PEAK", crowding_level: "high", model_version: "v1" },
            { route_id: "72",  trip_id: null, stop_id: null, service_date: "2026-05-12", time_bucket: "AM_PEAK", crowding_level: "medium", model_version: "v1" },
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

describe("Operations", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the operations KPIs and worst-routes list", async () => {
    render(wrap(<Operations />));
    await waitFor(() => expect(screen.getByText("51B")).toBeInTheDocument());
    expect(screen.getByText(/Network OTP/i)).toBeInTheDocument();
    expect(screen.getByText(/Live vehicles/i)).toBeInTheDocument();
    expect(screen.getByText(/Bunched/i)).toBeInTheDocument();
  });

  it("renders a crowding chart panel", async () => {
    render(wrap(<Operations />));
    await waitFor(() => expect(screen.getByRole("heading", { name: /Top high-crowding routes/i })).toBeInTheDocument());
  });
});

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterProvider } from "../context/FilterContext";
import { ThemeProvider } from "../context/ThemeContext";
import { AgenciesProvider } from "../context/AgenciesContext";
import { SelectionProvider, useSelection } from "../context/SelectionContext";
import { Overview } from "./Overview";

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
    <ThemeProvider>
      <AgenciesProvider>
        <FilterProvider>
          <SelectionProvider>
            {ui}
          </SelectionProvider>
        </FilterProvider>
      </AgenciesProvider>
    </ThemeProvider>
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

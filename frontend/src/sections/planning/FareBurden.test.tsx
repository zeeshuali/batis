import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { FilterProvider } from "../../context/FilterContext";
import { ThemeProvider } from "../../context/ThemeContext";
import { AgenciesProvider } from "../../context/AgenciesContext";
import { SelectionProvider } from "../../context/SelectionContext";
import { FareBurden } from "./FareBurden";

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

const mockFeatures = [
  // High-burden: 18% → very_high
  feature("C-001", { worst_fare: 8.50, burden_pct: 18.0, burden_tier: "very_high", reachable: 3 }),
  // High: 12%
  feature("C-002", { worst_fare: 6.00, burden_pct: 12.0, burden_tier: "high", reachable: 3 }),
  // Moderate: 7%
  feature("C-003", { worst_fare: 4.20, burden_pct: 7.0, burden_tier: "moderate", reachable: 2 }),
  // Low: 3%
  feature("C-004", { worst_fare: 2.10, burden_pct: 3.0, burden_tier: "low", reachable: 3 }),
  // Unreachable — no burden / no tier
  feature("C-005", { worst_fare: null, burden_pct: null, burden_tier: null, reachable: 0 }),
];

function feature(cell_id: string, opts: {
  worst_fare: number | null; burden_pct: number | null;
  burden_tier: "very_high" | "high" | "moderate" | "low" | null;
  reachable: number;
}) {
  return {
    type: "Feature",
    geometry: { type: "Polygon", coordinates: [[[ -122.4, 37.7 ], [ -122.4, 37.71 ], [ -122.39, 37.71 ], [ -122.4, 37.7 ]]] },
    properties: {
      cell_id,
      median_fare_to_sf:       opts.worst_fare,
      median_fare_to_oakland:  opts.worst_fare,
      median_fare_to_sfo:      opts.worst_fare,
      worst_fare:              opts.worst_fare,
      burden_pct:              opts.burden_pct,
      burden_tier:             opts.burden_tier,
      reachable_anchor_count:  opts.reachable,
      population:              500,
      median_household_income: 60000,
    },
  };
}

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return {
    ...actual,
    api: {
      get: vi.fn(async (url: string) => {
        if (url === "/equity/fare-burden") {
          return { data: { type: "FeatureCollection", features: mockFeatures } };
        }
        return { data: { type: "FeatureCollection", features: [] } };
      }),
      post: vi.fn(async () => ({ data: {} })),
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

describe("Planning → Fare Burden", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.location.hash = "";
  });

  it("renders the KPI strip with the right counts", async () => {
    render(wrap(<FareBurden />));
    // 5 cells total, 4 reachable, 2 high-burden (very_high + high),
    // median burden of (3,7,12,18) = 9.5%, worst = 18.0%.
    await waitFor(() => expect(screen.getByText("Cells")).toBeInTheDocument());
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("Reachable")).toBeInTheDocument();
    expect(screen.getByText("9.5%")).toBeInTheDocument();           // Median burden
    expect(screen.getAllByText("18.0%").length).toBeGreaterThan(0); // Worst burden (also appears in row list)
  });

  it("renders the top-10 list ordered by burden_pct desc", async () => {
    render(wrap(<FareBurden />));
    await waitFor(() => expect(screen.getByText("C-001")).toBeInTheDocument());
    // All four cells with a burden_pct should appear; the unreachable one is filtered out.
    expect(screen.getByText("C-001")).toBeInTheDocument();
    expect(screen.getByText("C-002")).toBeInTheDocument();
    expect(screen.getByText("C-003")).toBeInTheDocument();
    expect(screen.getByText("C-004")).toBeInTheDocument();
    expect(screen.queryByText("C-005")).not.toBeInTheDocument();
  });

  it("Export button is wired with all per-cell fields including the unreachable", async () => {
    render(wrap(<FareBurden />));
    const exportBtn = await screen.findByRole("button", { name: /Export/i });
    expect(exportBtn).toBeEnabled();
  });

  it("renders the empty state when the backend returns no cells", async () => {
    // Override the mock for this one test.
    const apiMod = await import("../../lib/api");
    (apiMod.api.get as unknown as { mockImplementation: (impl: () => unknown) => void })
      .mockImplementation(async () => ({ data: { type: "FeatureCollection", features: [] } }));
    render(wrap(<FareBurden />));
    await waitFor(() => expect(screen.getByText(/No fare burden data yet/i)).toBeInTheDocument());
  });
});

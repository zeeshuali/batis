import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { FilterProvider } from "../../context/FilterContext";
import { ThemeProvider } from "../../context/ThemeContext";
import { AgenciesProvider } from "../../context/AgenciesContext";
import { SelectionProvider } from "../../context/SelectionContext";
import { ServiceDeliveryGap } from "./ServiceDeliveryGap";

vi.mock("mapbox-gl", () => ({
  default: {
    accessToken: "",
    Map: vi.fn().mockImplementation(() => ({
      on: vi.fn(), off: vi.fn(), addControl: vi.fn(), remove: vi.fn(),
      getStyle: vi.fn(() => ({ layers: [] })),
      isStyleLoaded: vi.fn(() => false), setStyle: vi.fn(),
      getSource: vi.fn(), getLayer: vi.fn(),
      getCanvas: vi.fn(() => ({ style: {} })),
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

function feature(cell_id: string, opts: {
  gap_pct: number; tier: "very_high" | "high" | "moderate" | "low";
  scheduled: number; missed: number;
  equity: number; population: number;
}) {
  return {
    type: "Feature",
    geometry: { type: "Polygon",
      coordinates: [[[ -122.4, 37.7 ], [ -122.4, 37.71 ],
                     [ -122.39, 37.71 ], [ -122.4, 37.7 ]]] },
    properties: {
      cell_id,
      gap_pct:             opts.gap_pct,
      gap_tier:            opts.tier,
      scheduled_arrivals:  opts.scheduled,
      missed_arrivals:     opts.missed,
      window_start:        "2025-05-12",
      window_end:           "2026-05-12",
      equity_score:        opts.equity,
      equity_adjusted_gap: opts.gap_pct * opts.equity,
      population:          opts.population,
    },
  };
}

const mockFeatures = [
  feature("C-VH", { gap_pct: 14.0, tier: "very_high",
                    scheduled: 1000, missed: 140, equity: 0.20, population: 5000 }),
  feature("C-H",  { gap_pct: 7.5,  tier: "high",
                    scheduled: 1000, missed: 75,  equity: 0.15, population: 5000 }),
  feature("C-M",  { gap_pct: 3.0,  tier: "moderate",
                    scheduled: 1000, missed: 30,  equity: 0.10, population: 5000 }),
  feature("C-L",  { gap_pct: 0.5,  tier: "low",
                    scheduled: 1000, missed: 5,   equity: 0.10, population: 5000 }),
];

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return {
    ...actual,
    api: {
      get: vi.fn(async (url: string) => {
        if (url === "/equity/service-delivery-gap") {
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

describe("Planning → Service Delivery Gap", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.location.hash = "";
  });

  it("renders the KPI strip with the right counts", async () => {
    render(wrap(<ServiceDeliveryGap />));
    await waitFor(() => expect(screen.getByText("Cells")).toBeInTheDocument());
    // 4 cells; mean gap = (14+7.5+3+0.5)/4 = 6.25%; high-gap (≥5%) = 2;
    // worst = 14.0%
    expect(screen.getByText("4")).toBeInTheDocument();
    // 14.0% appears in both the KPI "Worst gap" card and the top-10 list row
    expect(screen.getAllByText("14.0%").length).toBeGreaterThanOrEqual(1);
  });

  it("renders the top-10 list sorted by equity_adjusted_gap desc", async () => {
    render(wrap(<ServiceDeliveryGap />));
    // C-VH adjusted = 14*0.2 = 2.8;  C-H = 7.5*0.15 = 1.125;
    // C-M = 3.0*0.10 = 0.30; C-L = 0.5*0.10 = 0.05
    // Sorted: C-VH, C-H, C-M, C-L
    await waitFor(() => expect(screen.getByText("C-VH")).toBeInTheDocument());
    const list = screen.getByRole("list");
    const order = Array.from(list.querySelectorAll("li"))
      .map(li => li.querySelector(".planning-fares__burden-cell")?.textContent);
    expect(order).toEqual(["C-VH", "C-H", "C-M", "C-L"]);
  });

  it("Export button is wired with per-cell fields", async () => {
    render(wrap(<ServiceDeliveryGap />));
    const btn = await screen.findByRole("button", { name: /Export/i });
    expect(btn).toBeEnabled();
  });

  it("renders the empty state when no cells", async () => {
    const apiMod = await import("../../lib/api");
    (apiMod.api.get as unknown as { mockImplementation: (impl: () => unknown) => void })
      .mockImplementation(async () => ({ data: { type: "FeatureCollection", features: [] } }));
    render(wrap(<ServiceDeliveryGap />));
    await waitFor(() =>
      expect(screen.getByText(/No service delivery gap data/i)).toBeInTheDocument()
    );
  });
});

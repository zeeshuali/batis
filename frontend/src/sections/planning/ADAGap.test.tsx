import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterProvider } from "../../context/FilterContext";
import { ThemeProvider } from "../../context/ThemeContext";
import { AgenciesProvider } from "../../context/AgenciesContext";
import { SelectionProvider, useSelection } from "../../context/SelectionContext";
import { ADAGap } from "./ADAGap";
import { useEffect, useRef } from "react";

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
      setHTML:   function() { return this; },
      addTo:     function() { return this; },
      remove:    function() { return this; },
    })),
  },
}));

vi.mock("../../components/SectionMap", () => ({
  SectionMap: () => <div data-testid="section-map" />,
}));

function stopFeature(stop_id: string, opts: {
  gap_score: number;
  gap_tier: "very_high" | "high" | "moderate" | "low";
  wheelchair_boarding: number | null;
  ambulatory_pop: number;
  pathways_override?: boolean;
}) {
  return {
    type: "Feature",
    geometry: { type: "Point", coordinates: [-122.27, 37.80] },
    properties: {
      stop_id,
      agency_id:           "AC",
      stop_name:           `Stop ${stop_id}`,
      wheelchair_boarding: opts.wheelchair_boarding,
      supply_penalty:      0.5,
      ambulatory_pop_400m: opts.ambulatory_pop,
      gap_score:           opts.gap_score,
      gap_tier:            opts.gap_tier,
      pathways_override:   opts.pathways_override ?? false,
      routes_serving:      ["51B"],
    },
  };
}

const mockFeatures = [
  stopFeature("S-VH", { gap_score: 2000, gap_tier: "very_high", wheelchair_boarding: 2,  ambulatory_pop: 4000 }),
  stopFeature("S-H",  { gap_score: 1000, gap_tier: "high",      wheelchair_boarding: 0,  ambulatory_pop: 2000 }),
  stopFeature("S-M",  { gap_score:  500, gap_tier: "moderate",  wheelchair_boarding: 1,  ambulatory_pop: 1000 }),
  stopFeature("S-L",  { gap_score:  100, gap_tier: "low",       wheelchair_boarding: null, ambulatory_pop: 200,
                         pathways_override: true }),
];

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return {
    ...actual,
    api: {
      get: vi.fn(async (url: string) => {
        if (url === "/accessibility/gaps") {
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

describe("Planning → ADA Gap", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.location.hash = "";
  });

  it("renders KPI cards with the correct computed values", async () => {
    render(wrap(<ADAGap />));
    await waitFor(() => expect(screen.getByText("Stops scored")).toBeInTheDocument());
    // 4 stops total
    expect(screen.getByText("4")).toBeInTheDocument();
    // inaccessible = 1, unknown = 2 — both appear as KPI values
    // "1" may appear multiple times (inaccessible + pathways_override),
    // so just assert at least one appears
    expect(screen.getAllByText("1").length).toBeGreaterThanOrEqual(1);
    // unknown: wheelchair_boarding === 0 or null → S-H (0) + S-L (null) = 2
    expect(screen.getByText("2")).toBeInTheDocument();
    // totalUnderserved = round(2000) from S-VH very_high tier
    // "2,000" may appear in both KPI and in the top-10 list row
    expect(screen.getAllByText("2,000").length).toBeGreaterThanOrEqual(1);
  });

  it("renders top-10 list sorted by gap_score DESC", async () => {
    render(wrap(<ADAGap />));
    await waitFor(() => expect(screen.getByText("Stop S-VH")).toBeInTheDocument());
    const list = screen.getByRole("list");
    const cells = Array.from(list.querySelectorAll(".planning-fares__burden-cell"))
      .map(el => el.textContent);
    expect(cells[0]).toBe("Stop S-VH");
    expect(cells[1]).toBe("Stop S-H");
    expect(cells[2]).toBe("Stop S-M");
    expect(cells[3]).toBe("Stop S-L");
  });

  it("row click sets adaGapDrillStop in context", async () => {
    let captured: string | null = null;
    function Spy() {
      const { selection } = useSelection();
      const ref = useRef(selection.adaGapDrillStop);
      useEffect(() => { ref.current = selection.adaGapDrillStop; });
      captured = selection.adaGapDrillStop;
      return null;
    }
    render(wrap(<><ADAGap /><Spy /></>));
    await waitFor(() => expect(screen.getByText("Stop S-VH")).toBeInTheDocument());
    const row = screen.getByText("Stop S-VH").closest("li")!;
    await userEvent.click(row);
    await waitFor(() => expect(captured).toBe("S-VH"));
  });

  it("Export button is present and enabled", async () => {
    render(wrap(<ADAGap />));
    const btn = await screen.findByRole("button", { name: /Export/i });
    expect(btn).toBeEnabled();
  });
});

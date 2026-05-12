import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import { FilterProvider } from "../context/FilterContext";
import { AgenciesProvider } from "../context/AgenciesContext";
import { SelectionProvider } from "../context/SelectionContext";

// Mock mapbox-gl entirely — jsdom can't run WebGL.
vi.mock("mapbox-gl", () => ({
  default: {
    accessToken: "",
    Map: vi.fn().mockImplementation(() => ({
      on: vi.fn(),
      off: vi.fn(),
      addControl: vi.fn(),
      remove: vi.fn(),
      getStyle: vi.fn(() => ({ layers: [] })),
      isStyleLoaded: vi.fn(() => false),
      setStyle: vi.fn(),
      getSource: vi.fn(() => undefined),
      getLayer: vi.fn(() => undefined),
      getCanvas: vi.fn(() => ({ style: {} })),
    })),
    NavigationControl: vi.fn(),
    ScaleControl: vi.fn(),
    Popup: vi.fn().mockImplementation(() => ({
      setLngLat: vi.fn().mockReturnThis(),
      setHTML: vi.fn().mockReturnThis(),
      addTo: vi.fn().mockReturnThis(),
      remove: vi.fn().mockReturnThis(),
    })),
  },
}));

import { MapView } from "./MapView";

function wrap(ui: React.ReactElement) {
  return (
    <AgenciesProvider>
      <FilterProvider>
        <SelectionProvider>{ui}</SelectionProvider>
      </FilterProvider>
    </AgenciesProvider>
  );
}

describe("MapView", () => {
  it("renders without crashing for each mapMode", () => {
    const modes: Array<"reliability" | "coverage" | "equity" | "traffic"> = [
      "reliability",
      "coverage",
      "equity",
      "traffic",
    ];
    for (const mode of modes) {
      const { unmount } = render(wrap(<MapView mapMode={mode} />));
      unmount();
    }
  });

  it("accepts an agencyFilter prop without crashing", () => {
    // The map mock's style.load callback is never fired (isStyleLoaded
    // returns false in this test), so we can't introspect setFilter calls
    // here — but the prop should at least flow through and the component
    // should mount cleanly under each combination.
    const { unmount } = render(wrap(<MapView mapMode="reliability" agencyFilter="AC" />));
    unmount();
    const { unmount: u2 } = render(wrap(<MapView mapMode="reliability" agencyFilter={null} />));
    u2();
  });
});

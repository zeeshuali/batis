import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import { FilterProvider } from "../context/FilterContext";
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
    <FilterProvider>
      <SelectionProvider>{ui}</SelectionProvider>
    </FilterProvider>
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
});

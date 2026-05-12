import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterProvider } from "../context/FilterContext";
import { ThemeProvider } from "../context/ThemeContext";
import { SelectionProvider, useSelection } from "../context/SelectionContext";
import { Network } from "./Network";

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
        if (url.startsWith("/routes"))           return { data: [
          { route_id: "51B", route_short_name: "51B", agency_id: "AC" },
          { route_id: "72",  route_short_name: "72",  agency_id: "AC" },
        ] };
        if (url.startsWith("/coverage/cells"))   return { data: { features: new Array(50).fill({}) } };
        if (url.startsWith("/coverage/deserts")) return { data: { features: new Array(3).fill({}) } };
        return { data: [] };
      }),
    },
  };
});

function Captured() {
  const { selection } = useSelection();
  return <div data-testid="captured">{selection.routeId ?? "none"}</div>;
}

function wrap(ui: React.ReactElement) { return <ThemeProvider><FilterProvider><SelectionProvider>{ui}</SelectionProvider></FilterProvider></ThemeProvider>; }

describe("Network", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders KPIs and the route list", async () => {
    render(wrap(<Network />));
    await waitFor(() => expect(screen.getByText("51B")).toBeInTheDocument());
    expect(screen.getByText(/Coverage cells/i)).toBeInTheDocument();
    expect(screen.getByText(/Transit deserts/i)).toBeInTheDocument();
  });

  it("selecting a route writes routeId", async () => {
    render(wrap(<><Network /><Captured /></>));
    await waitFor(() => expect(screen.getByText("51B")).toBeInTheDocument());
    await userEvent.click(screen.getByText("51B"));
    expect(screen.getByTestId("captured").textContent).toBe("51B");
  });
});

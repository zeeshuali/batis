import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterProvider } from "../context/FilterContext";
import { SelectionProvider } from "../context/SelectionContext";
import { AppShell } from "./AppShell";

// jsdom has no WebGL — section maps would crash when a section that embeds
// SectionMap (e.g. Operations) mounts during tab-switch tests. Stub mapbox-gl
// the same way the section tests do.
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

// Mock the API the Overview section calls — AppShell renders Overview by default.
vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    api: {
      get: vi.fn(async () => ({ data: [] })),
    },
  };
});

function wrap(ui: React.ReactElement) {
  return (
    <FilterProvider>
      <SelectionProvider>{ui}</SelectionProvider>
    </FilterProvider>
  );
}

describe("AppShell", () => {
  it("renders brand, all five tabs, and filter bar", () => {
    render(wrap(<AppShell />));
    expect(screen.getByText("BATIS")).toBeInTheDocument();
    ["Overview", "Operations", "Network", "Equity & Safety", "Benchmarks & Drift"].forEach(label => {
      expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
    });
    expect(screen.getByLabelText(/from/i)).toBeInTheDocument();
  });

  it("renders Overview by default", () => {
    render(wrap(<AppShell />));
    expect(screen.getByRole("heading", { name: "Overview" })).toBeInTheDocument();
  });

  it("switches sections when a tab is clicked", async () => {
    render(wrap(<AppShell />));
    await userEvent.click(screen.getByRole("tab", { name: "Operations" }));
    expect(screen.getByRole("heading", { name: "Operations" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Network" }));
    expect(screen.getByRole("heading", { name: "Network" })).toBeInTheDocument();
  });

  it("renders an agent rail placeholder", () => {
    render(wrap(<AppShell />));
    expect(screen.getByText(/Ask BATIS/i)).toBeInTheDocument();
  });

  it("mounts the alerts banner area and the stop drawer container", () => {
    render(wrap(<AppShell />));
    // The alerts banner renders an empty container by default (no alerts in test);
    // assert the grid area exists by class.
    expect(document.querySelector(".shell-alerts")).toBeInTheDocument();
    // StopDrawer renders nothing when stopId is null — verify there's no
    // "open" drawer overlay.
    expect(document.querySelector(".stop-drawer--open")).not.toBeInTheDocument();
  });
});

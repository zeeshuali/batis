import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterProvider } from "../context/FilterContext";
import { SelectionProvider } from "../context/SelectionContext";
import { ThemeProvider } from "../context/ThemeContext";
import { AgenciesProvider } from "../context/AgenciesContext";
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
    <ThemeProvider>
      <AgenciesProvider>
        <FilterProvider>
          <SelectionProvider>{ui}</SelectionProvider>
        </FilterProvider>
      </AgenciesProvider>
    </ThemeProvider>
  );
}

describe("AppShell", () => {
  beforeEach(() => { window.location.hash = ""; });

  it("renders brand, tabs, and filter bar", () => {
    render(wrap(<AppShell />));
    expect(screen.getByText("BATIS")).toBeInTheDocument();
    ["Overview", "Operations", "Network", "Equity & Safety", "Benchmarks & Drift", "Status"].forEach(label => {
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

  it("writes the hash when a tab is clicked", async () => {
    window.location.hash = "";
    render(wrap(<AppShell />));
    await userEvent.click(screen.getByRole("tab", { name: "Equity & Safety" }));
    expect(window.location.hash).toBe("#equity");
  });

  it("encodes search into the hash when typed", async () => {
    window.location.hash = "";
    render(wrap(<AppShell />));
    const input = screen.getByPlaceholderText(/route/i);
    await userEvent.type(input, "51");
    expect(window.location.hash).toContain("q=51");
  });

  it("renders a theme toggle that flips data-theme on <html>", async () => {
    document.documentElement.removeAttribute("data-theme");
    window.localStorage.clear();
    render(wrap(<AppShell />));
    // ThemeProvider applies "dark" on mount via useEffect; in jsdom this happens synchronously
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    await userEvent.click(screen.getByLabelText(/switch to light theme/i));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });
});

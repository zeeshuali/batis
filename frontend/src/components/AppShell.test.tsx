import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterProvider } from "../context/FilterContext";
import { SelectionProvider } from "../context/SelectionContext";
import { AppShell } from "./AppShell";

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
});

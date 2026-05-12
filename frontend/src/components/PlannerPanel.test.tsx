import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterProvider } from "../context/FilterContext";
import { SelectionProvider, useSelection } from "../context/SelectionContext";
import { ThemeProvider } from "../context/ThemeContext";
import { PlannerPanel } from "./PlannerPanel";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    api: {
      get: vi.fn(async () => ({ data: {
        legs: [{ route_short_name: "51B", from_stop: "Telegraph", to_stop: "Shattuck", duration_minutes: 18 }],
        total_duration_minutes: 18,
        transfers: 0,
      } })),
    },
  };
});

function ClickToSet() {
  const { setPlannerOrigin, setPlannerDest } = useSelection();
  return (
    <>
      <button onClick={() => setPlannerOrigin({ lat: 37.8, lng: -122.27 })}>set-origin</button>
      <button onClick={() => setPlannerDest  ({ lat: 37.7, lng: -122.42 })}>set-dest</button>
    </>
  );
}

function wrap(ui: React.ReactElement) {
  return (
    <ThemeProvider>
      <FilterProvider>
        <SelectionProvider>{ui}</SelectionProvider>
      </FilterProvider>
    </ThemeProvider>
  );
}

describe("PlannerPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.location.hash = "";
  });

  it("prompts to click an origin when empty", () => {
    render(wrap(<PlannerPanel />));
    expect(screen.getByText(/click the map to set an origin/i)).toBeInTheDocument();
  });

  it("renders itinerary legs once origin + dest are set", async () => {
    render(wrap(<><PlannerPanel /><ClickToSet /></>));
    await userEvent.click(screen.getByText("set-origin"));
    await userEvent.click(screen.getByText("set-dest"));
    await waitFor(() => expect(screen.getByText(/51B/)).toBeInTheDocument());
    expect(screen.getByText(/18 min/)).toBeInTheDocument();
  });
});

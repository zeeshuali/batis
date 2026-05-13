import React, { useEffect } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterProvider } from "../../context/FilterContext";
import { ThemeProvider } from "../../context/ThemeContext";
import { AgenciesProvider } from "../../context/AgenciesContext";
import { SelectionProvider, useSelection } from "../../context/SelectionContext";
import { ADAGapDrawer } from "./ADAGapDrawer";

const mockBreakdown = {
  stop_id:             "S-VH",
  stop_name:           "Main & 1st",
  agency_id:           "AC",
  gap_score:           2000,
  gap_tier:            "very_high" as const,
  wheelchair_boarding: 2,
  supply_penalty:      0.5,
  routes: [
    { route_id: "51B", agency_id: "AC", trips_per_day: 42 },
    { route_id: "1",   agency_id: "AC", trips_per_day: 20 },
  ],
  tracts: [
    { tract_geoid: "06001400100", ambulatory_pop: 1200, area_weighted_share: 0.42 },
    { tract_geoid: "06001400200", ambulatory_pop:  800, area_weighted_share: 0.28 },
    { tract_geoid: "06001400300", ambulatory_pop:  400, area_weighted_share: 0.15 },
  ],
};

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return {
    ...actual,
    api: {
      get: vi.fn(async (url: string) => {
        if (url.includes("/accessibility/gaps/stops/") && url.endsWith("/breakdown")) {
          return { data: mockBreakdown };
        }
        return { data: {} };
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

/** Helper: sets adaGapDrillStop in context via useEffect. */
function Setter({ stopId }: { stopId: string | null }) {
  const { setAdaGapDrillStop } = useSelection();
  useEffect(() => { setAdaGapDrillStop(stopId); }, [stopId, setAdaGapDrillStop]);
  return null;
}

describe("ADAGapDrawer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.location.hash = "";
  });

  it("renders nothing when adaGapDrillStop is null", () => {
    render(wrap(<><Setter stopId={null} /><ADAGapDrawer /></>));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders routes and top-3 tracts when a stop is selected", async () => {
    render(wrap(<><Setter stopId="S-VH" /><ADAGapDrawer /></>));
    await waitFor(() => expect(screen.getByText("51B")).toBeInTheDocument());
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    // top-3 tracts
    expect(screen.getByText("06001400100")).toBeInTheDocument();
    expect(screen.getByText("06001400200")).toBeInTheDocument();
    expect(screen.getByText("06001400300")).toBeInTheDocument();
    // gap score
    expect(screen.getByText("2,000")).toBeInTheDocument();
    // stop name
    expect(screen.getByText("Main & 1st")).toBeInTheDocument();
  });

  it("close button clears adaGapDrillStop", async () => {
    render(wrap(<><Setter stopId="S-VH" /><ADAGapDrawer /></>));
    await waitFor(() => expect(screen.getByText("51B")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /Close/i }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

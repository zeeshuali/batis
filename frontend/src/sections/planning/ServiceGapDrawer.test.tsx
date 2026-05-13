import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterProvider } from "../../context/FilterContext";
import { ThemeProvider } from "../../context/ThemeContext";
import { AgenciesProvider } from "../../context/AgenciesContext";
import { SelectionProvider, useSelection } from "../../context/SelectionContext";
import { ServiceGapDrawer } from "./ServiceGapDrawer";

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return {
    ...actual,
    api: {
      get: vi.fn(async (url: string) => {
        if (url.includes("/equity/service-delivery-gap/cells/") && url.endsWith("/routes?limit=5")) {
          return { data: [
            { agency_id: "AC", route_id: "51B", scheduled_arrivals: 1000,
              missed_arrivals: 180, missed_pct: 18.0 },
            { agency_id: "AC", route_id: "O",   scheduled_arrivals:  800,
              missed_arrivals:  80, missed_pct: 10.0 },
          ] };
        }
        return { data: [] };
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

function PickCell({ cellId }: { cellId: string | null }) {
  const { setServiceGapDrillCell } = useSelection();
  React.useEffect(() => { setServiceGapDrillCell(cellId); }, [cellId, setServiceGapDrillCell]);
  return null;
}

describe("ServiceGapDrawer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.location.hash = "";
  });

  it("renders nothing when no drill cell selected", () => {
    render(wrap(<><PickCell cellId={null} /><ServiceGapDrawer /></>));
    expect(screen.queryByText(/missed/i)).not.toBeInTheDocument();
  });

  it("renders the top routes when a cell is selected", async () => {
    render(wrap(<><PickCell cellId="C-VH" /><ServiceGapDrawer /></>));
    await waitFor(() => expect(screen.getByText("51B")).toBeInTheDocument());
    expect(screen.getByText("O")).toBeInTheDocument();
    expect(screen.getByText("18.0%")).toBeInTheDocument();
  });

  it("close button clears the selection", async () => {
    render(wrap(<><PickCell cellId="C-VH" /><ServiceGapDrawer /></>));
    await waitFor(() => expect(screen.getByText("51B")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /Close/i }));
    expect(screen.queryByText("51B")).not.toBeInTheDocument();
  });
});

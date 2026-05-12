import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterProvider, useFilters } from "../context/FilterContext";
import { AgenciesProvider } from "../context/AgenciesContext";
import { FilterBar } from "./FilterBar";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    api: {
      get: vi.fn(async (url: string) => {
        if (url === "/agencies") {
          return { data: [
            { agency_id: "AC", agency_name: "AC Transit" },
            { agency_id: "BA", agency_name: "BART" },
          ] };
        }
        return { data: [] };
      }),
    },
  };
});

function Probe() {
  const { filters } = useFilters();
  return <div data-testid="probe">{`${filters.startDate}|${filters.endDate}|${filters.agencies.join(",")}|${filters.search}`}</div>;
}

function wrap(ui: React.ReactElement) {
  return <AgenciesProvider><FilterProvider>{ui}</FilterProvider></AgenciesProvider>;
}

describe("FilterBar", () => {
  it("renders the three controls", () => {
    render(wrap(<FilterBar />));
    expect(screen.getByLabelText(/from/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/to/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/route/i)).toBeInTheDocument();
  });

  it("updates the FilterContext when search is typed", async () => {
    render(wrap(<><FilterBar /><Probe /></>));
    const input = screen.getByPlaceholderText(/route/i);
    await userEvent.type(input, "51B");
    expect(screen.getByTestId("probe").textContent).toMatch(/\|51B$/);
  });

  it("toggles agencies when an agency pill is clicked", async () => {
    render(wrap(<><FilterBar /><Probe /></>));
    // With the new "[] means all" semantic, no pill is initially active.
    // Clicking "AC" adds it to the (otherwise empty) selection.
    const acPill = await screen.findByRole("button", { name: /^AC( |$)/ });
    await userEvent.click(acPill);
    expect(screen.getByTestId("probe").textContent).toMatch(/\|AC\|/);
  });
});

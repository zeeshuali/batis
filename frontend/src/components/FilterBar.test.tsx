import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterProvider, useFilters } from "../context/FilterContext";
import { FilterBar } from "./FilterBar";

function Probe() {
  const { filters } = useFilters();
  return <div data-testid="probe">{`${filters.startDate}|${filters.endDate}|${filters.agencies.join(",")}|${filters.search}`}</div>;
}

describe("FilterBar", () => {
  it("renders the three controls", () => {
    render(<FilterProvider><FilterBar /></FilterProvider>);
    expect(screen.getByLabelText(/from/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/to/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/route/i)).toBeInTheDocument();
  });

  it("updates the FilterContext when search is typed", async () => {
    render(
      <FilterProvider>
        <FilterBar />
        <Probe />
      </FilterProvider>
    );
    const input = screen.getByPlaceholderText(/route/i);
    await userEvent.type(input, "51B");
    expect(screen.getByTestId("probe").textContent).toMatch(/\|51B$/);
  });

  it("toggles agencies when an agency pill is clicked", async () => {
    render(
      <FilterProvider>
        <FilterBar />
        <Probe />
      </FilterProvider>
    );
    // Click "AC" — it should already be selected by default (all selected);
    // clicking removes it from the list.
    const acPill = screen.getByRole("button", { name: /^AC( |$)/ });
    await userEvent.click(acPill);
    expect(screen.getByTestId("probe").textContent).not.toMatch(/,?AC,/);
  });
});

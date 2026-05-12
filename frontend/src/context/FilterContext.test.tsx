import { describe, it, expect } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterProvider, useFilters } from "./FilterContext";

function Probe() {
  const { filters, setAgencies, setSearch, setDateRange } = useFilters();
  return (
    <div>
      <span data-testid="start">{filters.startDate}</span>
      <span data-testid="end">{filters.endDate}</span>
      <span data-testid="agencies">{filters.agencies.join(",")}</span>
      <span data-testid="search">{filters.search}</span>
      <button onClick={() => setAgencies(["AC", "BA"])}>set</button>
      <button onClick={() => setSearch("51B")}>search</button>
      <button onClick={() => setDateRange("2026-01-01", "2026-01-07")}>range</button>
    </div>
  );
}

describe("FilterContext", () => {
  it("provides defaults: last 7 days, all agencies, empty search", () => {
    render(<FilterProvider><Probe /></FilterProvider>);
    expect(screen.getByTestId("agencies").textContent).not.toBe("");
    expect(screen.getByTestId("search").textContent).toBe("");
    expect(screen.getByTestId("start").textContent).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(screen.getByTestId("end").textContent).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("updates agencies, search, and date range", async () => {
    render(<FilterProvider><Probe /></FilterProvider>);
    await userEvent.click(screen.getByText("set"));
    expect(screen.getByTestId("agencies").textContent).toBe("AC,BA");
    await userEvent.click(screen.getByText("search"));
    expect(screen.getByTestId("search").textContent).toBe("51B");
    await userEvent.click(screen.getByText("range"));
    expect(screen.getByTestId("start").textContent).toBe("2026-01-01");
    expect(screen.getByTestId("end").textContent).toBe("2026-01-07");
  });

  it("useFilters throws when used outside provider", () => {
    function Naked() {
      useFilters();
      return null;
    }
    const consoleErr = console.error;
    console.error = () => {};
    try {
      expect(() => render(<Naked />)).toThrow(/FilterProvider/);
    } finally {
      console.error = consoleErr;
    }
  });
});

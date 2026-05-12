import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AgenciesProvider } from "../context/AgenciesContext";
import { FilterProvider, useFilters } from "../context/FilterContext";
import { AgencyCombobox } from "./AgencyCombobox";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    api: {
      get: vi.fn(async (url: string) => {
        if (url === "/agencies") {
          return { data: [
            { agency_id: "AC", agency_name: "AC Transit",       monitored: true,  has_data: true  },
            { agency_id: "BA", agency_name: "BART",             monitored: true,  has_data: true  },
            { agency_id: "CT", agency_name: "Caltrain",         monitored: true,  has_data: true  },
            { agency_id: "5E", agency_name: "511 Emergency",    monitored: false, has_data: false },
            { agency_id: "XX", agency_name: "Empty Operator",   monitored: false, has_data: false },
          ] };
        }
        return { data: [] };
      }),
    },
  };
});

function Selected() {
  const { filters } = useFilters();
  return <div data-testid="selected">{filters.agencies.join(",")}</div>;
}

function wrap(ui: React.ReactElement) {
  return <AgenciesProvider><FilterProvider>{ui}</FilterProvider></AgenciesProvider>;
}

describe("AgencyCombobox", () => {
  it("trigger shows 'All agencies' when nothing is selected", async () => {
    render(wrap(<AgencyCombobox />));
    await waitFor(() => expect(screen.getByText("All agencies")).toBeInTheDocument());
  });

  it("hides has_data=false agencies by default and reveals them via the toggle", async () => {
    render(wrap(<AgencyCombobox />));
    await userEvent.click(screen.getByRole("button", { name: /Agencies/i }));
    // Useful agencies are visible.
    expect(await screen.findByText("AC Transit")).toBeInTheDocument();
    expect(screen.getByText("BART")).toBeInTheDocument();
    expect(screen.getByText("Caltrain")).toBeInTheDocument();
    // Noise agencies are hidden.
    expect(screen.queryByText("511 Emergency")).not.toBeInTheDocument();
    expect(screen.queryByText("Empty Operator")).not.toBeInTheDocument();

    // Flip the toggle.
    await userEvent.click(screen.getByLabelText(/Show 511 internal/i));
    expect(await screen.findByText("511 Emergency")).toBeInTheDocument();
    expect(screen.getByText("Empty Operator")).toBeInTheDocument();
  });

  it("typing narrows the list", async () => {
    render(wrap(<AgencyCombobox />));
    await userEvent.click(screen.getByRole("button", { name: /Agencies/i }));
    const search = await screen.findByPlaceholderText(/Search agencies/i);
    await userEvent.type(search, "bart");
    expect(screen.getByText("BART")).toBeInTheDocument();
    expect(screen.queryByText("AC Transit")).not.toBeInTheDocument();
    expect(screen.queryByText("Caltrain")).not.toBeInTheDocument();
  });

  it("checkboxes drive FilterContext.agencies; chip ✕ removes one", async () => {
    render(wrap(<><AgencyCombobox /><Selected /></>));
    await userEvent.click(screen.getByRole("button", { name: /Agencies/i }));
    const acRow = (await screen.findByText("AC Transit")).closest("label")!;
    const baRow = (await screen.findByText("BART")).closest("label")!;
    await userEvent.click(acRow.querySelector('input[type="checkbox"]')!);
    await userEvent.click(baRow.querySelector('input[type="checkbox"]')!);
    expect(screen.getByTestId("selected").textContent).toBe("AC,BA");
    // Remove BA via chip ✕.
    await userEvent.click(screen.getByLabelText(/Remove BA/i));
    expect(screen.getByTestId("selected").textContent).toBe("AC");
  });

  it("'Monitored only' selects RT-enabled agencies with has_data", async () => {
    render(wrap(<><AgencyCombobox /><Selected /></>));
    await userEvent.click(screen.getByRole("button", { name: /Agencies/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Monitored only/i }));
    // Order is insertion order — AC, BA, CT all qualify.
    expect(screen.getByTestId("selected").textContent).toBe("AC,BA,CT");
  });

  it("'Clear' resets to the empty (= all) selection", async () => {
    render(wrap(<><AgencyCombobox /><Selected /></>));
    await userEvent.click(screen.getByRole("button", { name: /Agencies/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Monitored only/i }));
    expect(screen.getByTestId("selected").textContent).toBe("AC,BA,CT");
    await userEvent.click(screen.getByRole("button", { name: /^Clear$/i }));
    expect(screen.getByTestId("selected").textContent).toBe("");
  });
});

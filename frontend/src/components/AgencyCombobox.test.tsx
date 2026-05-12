import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
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
            { agency_id: "AC", agency_name: "AC Transit",       agency_type: "bus",   monitored: true,  has_data: true  },
            { agency_id: "SM", agency_name: "SamTrans",         agency_type: "bus",   monitored: true,  has_data: true  },
            { agency_id: "CT", agency_name: "Caltrain",         agency_type: "rail",  monitored: true,  has_data: true  },
            { agency_id: "BA", agency_name: "BART",             agency_type: "multi", monitored: true,  has_data: true  },
            { agency_id: "5E", agency_name: "511 Emergency",    agency_type: "other", monitored: false, has_data: false },
            { agency_id: "XX", agency_name: "Empty Operator",   agency_type: "bus",   monitored: false, has_data: false },
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
  beforeEach(() => { window.location.hash = ""; });

  it("trigger shows 'All agencies' when nothing is selected", async () => {
    render(wrap(<AgencyCombobox />));
    expect(await screen.findByText("All agencies")).toBeInTheDocument();
  });

  it("groups agencies by mode (Bus, Rail, Multi-modal) in canonical order", async () => {
    render(wrap(<AgencyCombobox />));
    await userEvent.click(screen.getByRole("button", { name: /Agencies/i }));
    // Useful agencies span 3 modes — 'Other' suppressed because Bus/Rail/Multi cover them.
    expect(await screen.findByRole("button", { name: /Select all Bus/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Select all Rail/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Select all Multi-modal/i })).toBeInTheDocument();
    // Mode order is Bus → Rail → Multi-modal.  Confirm via DOM position.
    const bus  = screen.getByRole("button", { name: /Select all Bus/i });
    const rail = screen.getByRole("button", { name: /Select all Rail/i });
    const mult = screen.getByRole("button", { name: /Select all Multi-modal/i });
    expect(bus.compareDocumentPosition(rail) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(rail.compareDocumentPosition(mult) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("clicking a mode header selects every agency in that mode", async () => {
    render(wrap(<><AgencyCombobox /><Selected /></>));
    await userEvent.click(screen.getByRole("button", { name: /Agencies/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Select all Bus/i }));
    // Useful Bus agencies: AC + SM.
    expect(screen.getByTestId("selected").textContent).toBe("AC,SM");
  });

  it("clicking a mode header again deselects every agency in that mode", async () => {
    render(wrap(<><AgencyCombobox /><Selected /></>));
    await userEvent.click(screen.getByRole("button", { name: /Agencies/i }));
    const busBtn = await screen.findByRole("button", { name: /Select all Bus/i });
    await userEvent.click(busBtn);
    expect(screen.getByTestId("selected").textContent).toBe("AC,SM");
    // Title swaps once everything in the group is on.
    const deselectBtn = await screen.findByRole("button", { name: /Deselect all Bus/i });
    await userEvent.click(deselectBtn);
    expect(screen.getByTestId("selected").textContent).toBe("");
  });

  it("'Show all agencies' toggle reveals has_data=false rows", async () => {
    render(wrap(<AgencyCombobox />));
    await userEvent.click(screen.getByRole("button", { name: /Agencies/i }));
    expect(screen.queryByText("511 Emergency")).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText(/Show all agencies/i));
    expect(await screen.findByText("511 Emergency")).toBeInTheDocument();
    expect(screen.getByText("Empty Operator")).toBeInTheDocument();
  });

  it("typing narrows the list within its mode group", async () => {
    render(wrap(<AgencyCombobox />));
    await userEvent.click(screen.getByRole("button", { name: /Agencies/i }));
    const search = await screen.findByPlaceholderText(/Search agencies/i);
    await userEvent.type(search, "bart");
    expect(screen.getByText("BART")).toBeInTheDocument();
    expect(screen.queryByText("AC Transit")).not.toBeInTheDocument();
    expect(screen.queryByText("Caltrain")).not.toBeInTheDocument();
    // The empty Bus and Rail groups are suppressed; only Multi-modal remains.
    expect(screen.queryByRole("button", { name: /Select all Bus/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Select all Multi-modal/i })).toBeInTheDocument();
  });

  it("chip ✕ removes one agency from the selection", async () => {
    render(wrap(<><AgencyCombobox /><Selected /></>));
    await userEvent.click(screen.getByRole("button", { name: /Agencies/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Select all Bus/i }));
    expect(screen.getByTestId("selected").textContent).toBe("AC,SM");
    await userEvent.click(screen.getByLabelText(/Remove AC/i));
    expect(screen.getByTestId("selected").textContent).toBe("SM");
  });

  it("'Monitored only' selects RT agencies regardless of mode", async () => {
    render(wrap(<><AgencyCombobox /><Selected /></>));
    await userEvent.click(screen.getByRole("button", { name: /Agencies/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Monitored only/i }));
    // AC + SM (bus) + CT (rail) + BA (multi) — all monitored & useful.
    expect(screen.getByTestId("selected").textContent).toBe("AC,SM,CT,BA");
  });

  it("'Clear' resets to the empty (= all) selection", async () => {
    render(wrap(<><AgencyCombobox /><Selected /></>));
    await userEvent.click(screen.getByRole("button", { name: /Agencies/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Monitored only/i }));
    await userEvent.click(screen.getByRole("button", { name: /^Clear$/i }));
    expect(screen.getByTestId("selected").textContent).toBe("");
  });
});

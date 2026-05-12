import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { AgenciesProvider, useAgencies } from "./AgenciesContext";

vi.mock("../lib/api", () => ({
  api: { get: vi.fn() },
  apiHeaders: () => ({}),
}));

import { api } from "../lib/api";
const mockGet = api.get as unknown as ReturnType<typeof vi.fn>;

function Probe() {
  const { agencies, byId, loading, error } = useAgencies();
  return (
    <div>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="error">{error ?? ""}</span>
      <span data-testid="count">{agencies.length}</span>
      <span data-testid="ac-name">{byId["AC"]?.agency_name ?? "—"}</span>
    </div>
  );
}

describe("AgenciesContext", () => {
  beforeEach(() => { mockGet.mockReset(); });

  it("fetches /agencies on mount and exposes the catalog", async () => {
    mockGet.mockResolvedValueOnce({ data: [
      { agency_id: "AC", agency_name: "AC Transit" },
      { agency_id: "BA", agency_name: "BART" },
    ] });
    render(<AgenciesProvider><Probe /></AgenciesProvider>);
    await waitFor(() => expect(screen.getByTestId("loading").textContent).toBe("false"));
    expect(screen.getByTestId("count").textContent).toBe("2");
    expect(screen.getByTestId("ac-name").textContent).toBe("AC Transit");
    expect(mockGet).toHaveBeenCalledWith("/agencies", expect.any(Object));
  });

  it("captures fetch errors without throwing", async () => {
    mockGet.mockRejectedValueOnce(new Error("network down"));
    render(<AgenciesProvider><Probe /></AgenciesProvider>);
    await waitFor(() => expect(screen.getByTestId("loading").textContent).toBe("false"));
    expect(screen.getByTestId("error").textContent).toBe("network down");
    expect(screen.getByTestId("count").textContent).toBe("0");
  });

  it("useAgencies throws when used outside the provider", () => {
    function Naked() { useAgencies(); return null; }
    const consoleErr = console.error;
    console.error = () => {};
    try {
      expect(() => render(<Naked />)).toThrow(/AgenciesProvider/);
    } finally {
      console.error = consoleErr;
    }
  });
});

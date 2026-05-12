import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { FilterProvider } from "../context/FilterContext";
import { SelectionProvider } from "../context/SelectionContext";
import { BenchmarksDrift } from "./BenchmarksDrift";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    api: {
      get: vi.fn(async (url: string) => {
        if (url.startsWith("/benchmarks/agency-otp")) {
          return { data: [
            { agency_id: "AC", on_time_pct: 87.5, avg_delay_seconds: 65, sample_events: 12000 },
            { agency_id: "BA", on_time_pct: 94.2, avg_delay_seconds: 32, sample_events:  8000 },
          ] };
        }
        if (url.startsWith("/traffic/events"))    return { data: { features: new Array(20).fill({}) } };
        if (url.startsWith("/traffic/work-zones")) return { data: { features: new Array(350).fill({}) } };
        return { data: [] };
      }),
    },
  };
});

function wrap(ui: React.ReactElement) { return <FilterProvider><SelectionProvider>{ui}</SelectionProvider></FilterProvider>; }

describe("BenchmarksDrift", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders KPIs and the agency bar chart", async () => {
    render(wrap(<BenchmarksDrift />));
    await waitFor(() => expect(screen.getByText(/^Agencies$/)).toBeInTheDocument());
    expect(screen.getByText(/Traffic events/i)).toBeInTheDocument();
    expect(screen.getByText(/Work zones/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Cross-agency OTP/i })).toBeInTheDocument();
  });
});

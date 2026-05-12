import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { KpiCard } from "./KpiCard";

describe("KpiCard", () => {
  it("renders label and value", () => {
    render(<KpiCard label="On-time %" value="87%" />);
    expect(screen.getByText("On-time %")).toBeInTheDocument();
    expect(screen.getByText("87%")).toBeInTheDocument();
  });

  it("renders sub when provided", () => {
    render(<KpiCard label="Routes" value="349" sub="across 8 agencies" />);
    expect(screen.getByText("across 8 agencies")).toBeInTheDocument();
  });

  it("renders delta with up/down marker", () => {
    render(<KpiCard label="OTP" value="87%" delta={2.3} deltaIsGood />);
    const delta = screen.getByText(/\+2\.3/);
    expect(delta).toBeInTheDocument();
    expect(delta.className).toMatch(/kpi-card__delta--good/);
  });

  it("renders negative delta as bad when deltaIsGood is false", () => {
    render(<KpiCard label="Delay" value="3.2 min" delta={-0.4} deltaIsGood={false} />);
    const delta = screen.getByText(/-0\.4/);
    expect(delta.className).toMatch(/kpi-card__delta--bad/);
  });
});

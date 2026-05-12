import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useUrlState, parseHash, encodeHash } from "./useUrlState";

describe("parseHash / encodeHash", () => {
  it("round-trips an empty state to a section-only hash", () => {
    expect(parseHash("#network")).toEqual({
      section: "network", subsection: null, from: null, to: null, agencies: null, q: null, agency_id: null,
    });
    expect(encodeHash({
      section: "network", subsection: null, from: null, to: null, agencies: null, q: null, agency_id: null,
    })).toBe("#network");
  });

  it("encodes and decodes a full state", () => {
    const state = {
      section: "equity" as const,
      subsection: null,
      from: "2026-04-01",
      to: "2026-04-30",
      agencies: ["AC", "BA"],
      q: "51",
      agency_id: null,
    };
    const hash = encodeHash(state);
    expect(hash).toContain("#equity?");
    expect(hash).toContain("from=2026-04-01");
    expect(hash).toContain("to=2026-04-30");
    expect(hash).toContain("agencies=AC,BA");
    expect(hash).toContain("q=51");
    expect(parseHash(hash)).toEqual(state);
  });

  it("round-trips an #agency drill-down state", () => {
    const state = {
      section: "agency" as const,
      subsection: null,
      from: "2026-05-01",
      to: "2026-05-08",
      agencies: null,
      q: null,
      agency_id: "BA",
    };
    const hash = encodeHash(state);
    expect(hash).toContain("#agency?");
    expect(hash).toContain("id=BA");
    expect(parseHash(hash)).toEqual(state);
  });

  it("round-trips a #planning sub-page state", () => {
    const state = {
      section: "planning" as const,
      subsection: "coverage",
      from: null, to: null,
      agencies: null, q: null,
      agency_id: null,
    };
    const hash = encodeHash(state);
    expect(hash).toContain("#planning?");
    expect(hash).toContain("sub=coverage");
    expect(parseHash(hash)).toEqual(state);
  });

  it("returns overview for an unknown section", () => {
    expect(parseHash("#wat").section).toBe("overview");
  });
});

describe("useUrlState", () => {
  beforeEach(() => { window.location.hash = ""; });

  it("starts with defaults", () => {
    const { result } = renderHook(() => useUrlState());
    expect(result.current.state.section).toBe("overview");
  });

  it("setState rewrites the hash", () => {
    const { result } = renderHook(() => useUrlState());
    act(() => result.current.setState({ ...result.current.state, section: "network", q: "51" }));
    expect(window.location.hash).toContain("#network");
    expect(window.location.hash).toContain("q=51");
  });

  it("responds to external hashchange", () => {
    const { result } = renderHook(() => useUrlState());
    act(() => {
      window.location.hash = "#benchmarks?from=2026-01-01&to=2026-01-07";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(result.current.state.section).toBe("benchmarks");
    expect(result.current.state.from).toBe("2026-01-01");
  });
});

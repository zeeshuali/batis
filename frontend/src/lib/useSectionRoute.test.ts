import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSectionRoute } from "./useSectionRoute";

describe("useSectionRoute", () => {
  beforeEach(() => { window.location.hash = ""; });

  it("defaults to overview when the hash is empty", () => {
    const { result } = renderHook(() => useSectionRoute());
    expect(result.current.section).toBe("overview");
  });

  it("reads a valid section from the hash on init", () => {
    window.location.hash = "#network";
    const { result } = renderHook(() => useSectionRoute());
    expect(result.current.section).toBe("network");
  });

  it("ignores an unknown hash and falls back to overview", () => {
    window.location.hash = "#wat";
    const { result } = renderHook(() => useSectionRoute());
    expect(result.current.section).toBe("overview");
  });

  it("setSection writes the hash", () => {
    const { result } = renderHook(() => useSectionRoute());
    act(() => result.current.setSection("equity"));
    expect(window.location.hash).toBe("#equity");
    expect(result.current.section).toBe("equity");
  });

  it("responds to external hashchange events (back/forward)", () => {
    const { result } = renderHook(() => useSectionRoute());
    act(() => {
      window.location.hash = "#benchmarks";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(result.current.section).toBe("benchmarks");
  });
});

import { describe, it, expect } from "vitest";
import { toCsv } from "./download";

describe("toCsv", () => {
  it("emits a header row and one row per object", () => {
    const out = toCsv([{ a: 1, b: "x" }, { a: 2, b: "y" }]);
    expect(out.split("\n")).toEqual(["a,b", "1,x", "2,y"]);
  });

  it("escapes commas and quotes", () => {
    const out = toCsv([{ name: 'a, "b"', n: 1 }]);
    expect(out.split("\n")[1]).toBe('"a, ""b""",1');
  });

  it("uses headers in the order of the first row's keys", () => {
    const out = toCsv([{ b: 1, a: 2 }]);
    expect(out.split("\n")[0]).toBe("b,a");
  });

  it("returns an empty string for an empty array", () => {
    expect(toCsv([])).toBe("");
  });

  it("renders null/undefined as empty cells", () => {
    const out = toCsv([{ a: null, b: undefined, c: 0 }]);
    expect(out.split("\n")[1]).toBe(",,0");
  });
});

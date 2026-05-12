import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider, useTheme } from "./ThemeContext";

function Probe() {
  const { theme, toggle, setTheme } = useTheme();
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <button onClick={toggle}>toggle</button>
      <button onClick={() => setTheme("light")}>light</button>
    </div>
  );
}

describe("ThemeContext", () => {
  beforeEach(() => {
    document.documentElement.removeAttribute("data-theme");
    window.localStorage.clear();
  });

  it("defaults to dark and sets data-theme on <html>", () => {
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByTestId("theme").textContent).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("toggles dark ↔ light", async () => {
    render(<ThemeProvider><Probe /></ThemeProvider>);
    await userEvent.click(screen.getByText("toggle"));
    expect(screen.getByTestId("theme").textContent).toBe("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("setTheme writes to localStorage", async () => {
    render(<ThemeProvider><Probe /></ThemeProvider>);
    await userEvent.click(screen.getByText("light"));
    expect(window.localStorage.getItem("batis.theme")).toBe("light");
  });
});

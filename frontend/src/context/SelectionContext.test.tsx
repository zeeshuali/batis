import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SelectionProvider, useSelection } from "./SelectionContext";

function Probe() {
  const { selection, setRouteId, setStopId, setHoveredStopId, clear } = useSelection();
  return (
    <div>
      <span data-testid="route">{selection.routeId ?? "none"}</span>
      <span data-testid="stop">{selection.stopId ?? "none"}</span>
      <span data-testid="hover">{selection.hoveredStopId ?? "none"}</span>
      <button onClick={() => setRouteId("51B")}>r</button>
      <button onClick={() => setStopId("S001")}>s</button>
      <button onClick={() => setHoveredStopId("S002")}>h</button>
      <button onClick={clear}>c</button>
    </div>
  );
}

describe("SelectionContext", () => {
  it("starts empty", () => {
    render(<SelectionProvider><Probe /></SelectionProvider>);
    expect(screen.getByTestId("route").textContent).toBe("none");
    expect(screen.getByTestId("stop").textContent).toBe("none");
    expect(screen.getByTestId("hover").textContent).toBe("none");
  });

  it("setters update individual fields, clear resets all", async () => {
    render(<SelectionProvider><Probe /></SelectionProvider>);
    await userEvent.click(screen.getByText("r"));
    await userEvent.click(screen.getByText("s"));
    await userEvent.click(screen.getByText("h"));
    expect(screen.getByTestId("route").textContent).toBe("51B");
    expect(screen.getByTestId("stop").textContent).toBe("S001");
    expect(screen.getByTestId("hover").textContent).toBe("S002");
    await userEvent.click(screen.getByText("c"));
    expect(screen.getByTestId("route").textContent).toBe("none");
    expect(screen.getByTestId("stop").textContent).toBe("none");
    expect(screen.getByTestId("hover").textContent).toBe("none");
  });
});

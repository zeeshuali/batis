import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SelectionProvider, useSelection } from "./SelectionContext";

function Probe() {
  const {
    selection,
    setRouteId,
    setStopId,
    setHoveredStopId,
    setPlannerOrigin,
    setPlannerDest,
    resetPlanner,
    clear,
  } = useSelection();
  return (
    <div>
      <span data-testid="route">{selection.routeId ?? "none"}</span>
      <span data-testid="stop">{selection.stopId ?? "none"}</span>
      <span data-testid="hover">{selection.hoveredStopId ?? "none"}</span>
      <span data-testid="origin">
        {selection.plannerOrigin
          ? `${selection.plannerOrigin.lat},${selection.plannerOrigin.lng}`
          : "none"}
      </span>
      <span data-testid="dest">
        {selection.plannerDest
          ? `${selection.plannerDest.lat},${selection.plannerDest.lng}`
          : "none"}
      </span>
      <button onClick={() => setRouteId("51B")}>r</button>
      <button onClick={() => setStopId("S001")}>s</button>
      <button onClick={() => setHoveredStopId("S002")}>h</button>
      <button onClick={() => setPlannerOrigin({ lat: 37.8, lng: -122.27 })}>origin</button>
      <button onClick={() => setPlannerDest({ lat: 37.7, lng: -122.42 })}>dest</button>
      <button onClick={resetPlanner}>reset</button>
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
    expect(screen.getByTestId("origin").textContent).toBe("none");
    expect(screen.getByTestId("dest").textContent).toBe("none");
  });

  it("setters update individual fields, clear resets all", async () => {
    render(<SelectionProvider><Probe /></SelectionProvider>);
    await userEvent.click(screen.getByText("r"));
    await userEvent.click(screen.getByText("s"));
    await userEvent.click(screen.getByText("h"));
    await userEvent.click(screen.getByText("origin"));
    await userEvent.click(screen.getByText("dest"));
    expect(screen.getByTestId("route").textContent).toBe("51B");
    expect(screen.getByTestId("stop").textContent).toBe("S001");
    expect(screen.getByTestId("hover").textContent).toBe("S002");
    expect(screen.getByTestId("origin").textContent).toBe("37.8,-122.27");
    expect(screen.getByTestId("dest").textContent).toBe("37.7,-122.42");
    await userEvent.click(screen.getByText("c"));
    expect(screen.getByTestId("route").textContent).toBe("none");
    expect(screen.getByTestId("stop").textContent).toBe("none");
    expect(screen.getByTestId("hover").textContent).toBe("none");
    expect(screen.getByTestId("origin").textContent).toBe("none");
    expect(screen.getByTestId("dest").textContent).toBe("none");
  });

  it("planner setters update state, resetPlanner clears them", async () => {
    render(<SelectionProvider><Probe /></SelectionProvider>);
    await userEvent.click(screen.getByText("origin"));
    await userEvent.click(screen.getByText("dest"));
    expect(screen.getByTestId("origin").textContent).toBe("37.8,-122.27");
    expect(screen.getByTestId("dest").textContent).toBe("37.7,-122.42");
    await userEvent.click(screen.getByText("reset"));
    expect(screen.getByTestId("origin").textContent).toBe("none");
    expect(screen.getByTestId("dest").textContent).toBe("none");
  });
});

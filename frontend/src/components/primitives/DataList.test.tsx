import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DataList } from "./DataList";

describe("DataList", () => {
  it("renders one row per item with primary + secondary text", () => {
    render(
      <DataList
        items={[
          { id: "a", primary: "Route 51B", secondary: "AC Transit", trailing: "2.3 min" },
          { id: "b", primary: "Route 72",  secondary: "AC Transit", trailing: "1.1 min" },
        ]}
      />
    );
    expect(screen.getByText("Route 51B")).toBeInTheDocument();
    expect(screen.getByText("Route 72")).toBeInTheDocument();
    expect(screen.getByText("2.3 min")).toBeInTheDocument();
  });

  it("calls onSelect with the item id when a row is clicked", async () => {
    const onSelect = vi.fn();
    render(
      <DataList
        items={[{ id: "a", primary: "Route 51B" }]}
        onSelect={onSelect}
      />
    );
    await userEvent.click(screen.getByText("Route 51B"));
    expect(onSelect).toHaveBeenCalledWith("a");
  });

  it("highlights the selected row", () => {
    render(
      <DataList
        items={[{ id: "a", primary: "Route 51B" }, { id: "b", primary: "Route 72" }]}
        selectedId="b"
      />
    );
    const rows = screen.getAllByRole("button");
    expect(rows[1].className).toMatch(/data-list__row--selected/);
    expect(rows[0].className).not.toMatch(/data-list__row--selected/);
  });
});

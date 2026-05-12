import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SectionError } from "./SectionError";

describe("SectionError", () => {
  it("renders the title and message", () => {
    render(<SectionError title="Failed to load" message="Backend returned 500" />);
    expect(screen.getByText("Failed to load")).toBeInTheDocument();
    expect(screen.getByText("Backend returned 500")).toBeInTheDocument();
  });

  it("calls onRetry when the retry button is clicked", async () => {
    const onRetry = vi.fn();
    render(<SectionError message="Network error" onRetry={onRetry} />);
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

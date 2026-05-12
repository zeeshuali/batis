import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { downloadCsv } = vi.hoisted(() => ({ downloadCsv: vi.fn() }));
vi.mock("../../lib/download", async () => {
  const actual = await vi.importActual<typeof import("../../lib/download")>("../../lib/download");
  return { ...actual, downloadCsv };
});

import { ExportButton } from "./ExportButton";

describe("ExportButton", () => {
  beforeEach(() => downloadCsv.mockClear());

  it("renders an Export label and downloads when clicked", async () => {
    render(<ExportButton filename="test.csv" rows={[{ a: 1 }]} />);
    const btn = screen.getByRole("button", { name: /export/i });
    await userEvent.click(btn);
    expect(downloadCsv).toHaveBeenCalledWith("test.csv", "a\n1");
  });

  it("is disabled when rows is empty", () => {
    render(<ExportButton filename="x.csv" rows={[]} />);
    expect(screen.getByRole("button", { name: /export/i })).toBeDisabled();
  });
});

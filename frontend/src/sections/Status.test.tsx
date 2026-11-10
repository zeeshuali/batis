import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Status } from "./Status";

const now = new Date().toISOString();
const activities = {
  generated_at: now, overall: "warn", categories: ["Ingestion", "External APIs"],
  cards: [
    { key: "stop_obs_backfill", title: "Stop observations backfill", category: "Ingestion", description: "d",
      schedule: "Daily 03:00", status: "running", headline: "Running for 4 min", next_run: null,
      metrics: [{ label: "Months loaded", value: "2 of 12" }],
      progress: { label: "2026-08: parsing and inserting (3,400,000 rows), about 13% of a typical month", pct: 13,
                  overall_pct: 18, overall_label: "2 of 12 months loaded", elapsed_minutes: 4 } },
    { key: "rt_ingestor", title: "Live vehicles & trip updates", category: "Ingestion", description: "d",
      schedule: "Every 180s", status: "error", headline: "vehicle insert failed", next_run: null,
      metrics: [{ label: "Errors (24 h)", value: "3" }], progress: null },
    { key: "api_511", title: "511.org API", category: "External APIs", description: "d", schedule: "On demand",
      status: "ok", headline: "Last call 2 min ago", next_run: null,
      metrics: [{ label: "Used this hour", value: "4 / 60" }], progress: null },
  ],
};
const status = { generated_at: now, overall: "error", checks: [
  { key: "rt_fresh", label: "Live data freshness", status: "error", detail: "no new data for 864 min" },
  { key: "database", label: "Database", status: "ok", detail: "fine" }] };
const detail = {
  key: "stop_obs_backfill", title: "Stop observations backfill", status: "running", headline: "Running", generated_at: now,
  sections: {
    overview: { description: "Loads the monthly archive.", how_it_works: ["Pick the newest missing month"], schedule: "Daily 03:00",
                command: "python -m app.workers.backfill_stop_observations", next_run: null, metrics: [], used_by_note: null },
    progress: { current: { label: "2026-08: downloading (268 MB)", pct: null, elapsed_minutes: 2 },
                months: [{ month: "2026-10", state: "loaded", rows: null, source: "earlier load", loaded_at: null },
                         { month: "2026-08", state: "loading", rows: null, source: null, loaded_at: null }] },
    runs: { runs: [{ id: 3, job: "stop_observations_load", started_at: now, finished_at: null, status: "running",
                     rows_written: null, duration_s: 120, details: { month: "2026-08" }, error: null }] },
    data: { tables: [{ table: "stop_observations", label: "Stop observations", rows: 52000000, size: "20 GB", latest: null, note: "row count is an estimate" }] },
    errors: { items: [{ when: now, kind: "job run", where: "stop_observations_load", message: "Interrupted manually" }] },
    config: { settings: [{ name: "STOP_OBS_BACKFILL_MAX_MONTHS_BACK", value: 12 }], command: "x", schedule: "Daily 03:00", log_file: "backend/logs/x.log", tables: ["stop_observations"] },
    logs: { path: "backend/logs/x.log", lines: ["2026 INFO [stop-obs] Downloaded 2026-08"] },
  },
};

const get = vi.fn(async (url: string, _config?: unknown) => {
  if (url === "/admin/activities") return { data: activities };
  if (url === "/admin/status") return { data: status };
  if (url === "/admin/activities/stop_obs_backfill") return { data: detail };
  return { data: {} };
});
vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return { ...actual, api: { get: (u: string, c?: unknown) => get(u, c) } };
});

describe("Status", () => {
  beforeEach(() => get.mockClear());

  it("shows one card per activity grouped by category, with live backfill progress", async () => {
    render(<Status />);
    expect(await screen.findByText("Problem detected")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Ingestion" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "External APIs" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Open details/ })).toHaveLength(3);
    expect(screen.getByText(/2026-08: parsing and inserting \(3,400,000 rows\)/)).toBeInTheDocument();
    expect(screen.getByText("2 of 12")).toBeInTheDocument();
    expect(screen.getByText("no new data for 864 min")).toBeInTheDocument();
  });

  it("opens a card and shows its detail in separate category tabs", async () => {
    render(<Status />);
    await userEvent.click(await screen.findByRole("button", { name: /Stop observations backfill, running/ }));
    const dialog = await screen.findByRole("dialog", { name: /Stop observations backfill details/ });
    const tabs = within(dialog).getAllByRole("tab").map(t => t.textContent);
    expect(tabs.join("|")).toMatch(/Overview.*Progress.*Runs.*Data.*Errors.*Config.*Logs/);
    expect(within(dialog).getByText("Loads the monthly archive.")).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("tab", { name: "Progress" }));
    expect(within(dialog).getByText(/downloading \(268 MB\)/)).toBeInTheDocument();
    expect(within(dialog).getByText("2026-10")).toBeInTheDocument();
    expect(within(dialog).getByText("loading")).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("tab", { name: "Runs" }));
    expect(within(dialog).getByText("month: 2026-08")).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("tab", { name: /Errors/ }));
    expect(within(dialog).getByText("Interrupted manually")).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("tab", { name: "Logs" }));
    expect(within(dialog).getByText(/Downloaded 2026-08/)).toBeInTheDocument();
  });

  it("closes the detail panel with the Close button", async () => {
    render(<Status />);
    await userEvent.click(await screen.findByRole("button", { name: /Stop observations backfill, running/ }));
    await screen.findByRole("dialog");
    await userEvent.click(screen.getByRole("button", { name: "Close details" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

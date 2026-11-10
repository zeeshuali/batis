import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Status } from "./Status";

const snapshot = {
  generated_at: new Date().toISOString(), overall: "error",
  checks: [
    { key: "database", label: "Database", status: "ok", detail: "PostgreSQL 16" },
    { key: "rt_fresh", label: "Live data freshness", status: "error", detail: "no new data for 864 min" },
  ],
  db: { ok: true, latency_ms: 4, size_mb: 22042, version: "16", extensions: ["postgis", "vector"] },
  data: [{ table: "gtfs_stops", label: "GTFS stops", rows: 20260, latest: null, age_minutes: null, status: "ok", note: null }],
  api: {
    rate_limit: { limit: 60, used_last_hour: 51, remaining: 9, pct_used: 85, oldest_call_expires_in_minutes: 12 },
    sources: [{ source: "511", calls_24h: 40, errors_24h: 4, error_rate_pct: 10, avg_ms: 300,
                last_call: new Date().toISOString(), last_status_code: 429, last_ok: false, last_error: "HTTP 429 Too Many Requests" }],
    error: null,
  },
  jobs: [{ job: "rt_ingestor", status: "error", last_status: "error", last_started: new Date().toISOString(),
           age_minutes: 1, duration_s: 2.5, rows_written: null, error: "vehicle insert failed", note: null,
           runs_24h: 10, errors_24h: 3 }],
  threads: [{ name: "five11-rt-ingestor", alive: false }],
  services: { ollama: { reachable: true, models: ["llama3.1:8b"], configured_model: "llama3.1:8b", model_present: true, url: "x" } },
};

const get = vi.fn(async (url: string, _config?: unknown) => {
  if (url === "/admin/status") return { data: snapshot };
  if (url === "/admin/api-calls") return { data: [{ id: 1, called_at: new Date().toISOString(), source: "511",
      endpoint: "api.511.org/Transit/TripUpdates", status_code: 429, ok: false, duration_ms: 50, error: "HTTP 429 Too Many Requests" }] };
  if (url === "/admin/job-runs") return { data: [{ id: 9, job: "rt_ingestor", started_at: new Date().toISOString(),
      finished_at: null, status: "error", rows_written: null, error: "vehicle insert failed" }] };
  return { data: [] };
});
vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return { ...actual, api: { get: (u: string, c?: unknown) => get(u, c) } };
});

describe("Status", () => {
  beforeEach(() => get.mockClear());

  it("shows the overall banner, failing check, 511 budget and API call error", async () => {
    render(<Status />);
    expect(await screen.findByText("Problem detected")).toBeInTheDocument();
    expect(screen.getByText("no new data for 864 min")).toBeInTheDocument();
    expect(screen.getByText("51 / 60")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: /511 requests/i })).toHaveAttribute("aria-valuenow", "51");
    expect(screen.getAllByText("HTTP 429 Too Many Requests").length).toBeGreaterThan(0);
    expect(screen.getByText("api.511.org/Transit/TripUpdates")).toBeInTheDocument();
  });

  it("expands a job to its recent runs", async () => {
    render(<Status />);
    await userEvent.click(await screen.findByText("rt_ingestor"));
    await waitFor(() => expect(get).toHaveBeenCalledWith("/admin/job-runs", expect.anything()));
    expect(await screen.findByText(/Recent runs: rt_ingestor/)).toBeInTheDocument();
  });

  it("passes the errors-only filter to the API", async () => {
    render(<Status />);
    await userEvent.click(await screen.findByLabelText(/errors only/i));
    await waitFor(() => {
      const last = get.mock.calls.filter(c => c[0] === "/admin/api-calls").at(-1);
      expect((last?.[1] as unknown as { params: { errors_only: boolean } }).params.errors_only).toBe(true);
    });
  });
});

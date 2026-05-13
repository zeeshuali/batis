import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterProvider } from "../../context/FilterContext";
import { ThemeProvider } from "../../context/ThemeContext";
import { AgenciesProvider } from "../../context/AgenciesContext";
import { SelectionProvider, useSelection } from "../../context/SelectionContext";
import { Fares } from "./Fares";

vi.mock("mapbox-gl", () => ({
  default: {
    accessToken: "",
    Map: vi.fn().mockImplementation(() => ({
      on: vi.fn(), off: vi.fn(), addControl: vi.fn(), remove: vi.fn(),
      getStyle: vi.fn(() => ({ layers: [] })),
      isStyleLoaded: vi.fn(() => false), setStyle: vi.fn(),
      getSource: vi.fn(), getLayer: vi.fn(), getCanvas: vi.fn(() => ({ style: {} })),
    })),
    NavigationControl: vi.fn(),
    ScaleControl: vi.fn(),
    Popup: vi.fn().mockImplementation(() => ({
      setLngLat: function() { return this; },
      setHTML:  function() { return this; },
      addTo:    function() { return this; },
      remove:   function() { return this; },
    })),
  },
}));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return {
    ...actual,
    api: {
      get:  vi.fn(async () => ({ data: [] })),
      post: vi.fn(async (url: string) => {
        if (url === "/fares/sample-corridor") {
          return { data: {
            n_sampled:   30,
            median_fare: 4.50,
            p25_fare:    3.20,
            p75_fare:    6.50,
            max_fare:    9.40,
            agencies:    ["AC", "BA"],
            by_equity_tier: {
              very_high: { n: 5, median_fare: 5.00 },
              high:      { n: 10, median_fare: 4.55 },
              medium:    { n: 8, median_fare: 4.20 },
              low:       { n: 7, median_fare: 3.50 },
            },
            high_burden_cells: [
              { cell_id: "C1", equity_score: 0.31, median_fare: 6.20, burden: 1.92 },
              { cell_id: "C2", equity_score: 0.18, median_fare: 5.00, burden: 0.90 },
            ],
            notice: null,
          } };
        }
        return { data: {} };
      }),
    },
  };
});

function wrap(ui: React.ReactElement) {
  return (
    <ThemeProvider>
      <AgenciesProvider>
        <FilterProvider>
          <SelectionProvider>{ui}</SelectionProvider>
        </FilterProvider>
      </AgenciesProvider>
    </ThemeProvider>
  );
}

/** Driver helper: sets both fares pins via the cycle, then renders Fares. */
const _BERKELEY = { lat: 37.871, lng: -122.272 };
const _EMBARCAD = { lat: 37.793, lng: -122.397 };
function Driver({ point }: { point: { lat: number; lng: number } | null }) {
  const { setFaresPin } = useSelection();
  React.useEffect(() => {
    if (point) setFaresPin(point);
  }, [point, setFaresPin]);
  return null;
}

describe("Planning → Fares", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.location.hash = "";
  });

  it("renders the empty state until an origin is picked", async () => {
    render(wrap(<Fares />));
    await waitFor(() => expect(screen.getByText(/Click an origin on the map/i)).toBeInTheDocument());
  });

  it("after first click shows the 'now click a destination' empty state", async () => {
    render(wrap(<><Driver point={_BERKELEY} /><Fares /></>));
    await waitFor(() => expect(screen.getByText(/Now click a destination/i)).toBeInTheDocument());
  });

  it("after both clicks renders the KPI strip + fare distribution + tier chart", async () => {
    // Mount in a way that lets us set both pins sequentially.
    function Pair() {
      const { setFaresPin } = useSelection();
      React.useEffect(() => {
        setFaresPin(_BERKELEY);
        setFaresPin(_EMBARCAD);
      }, [setFaresPin]);
      return null;
    }
    render(wrap(<><Pair /><Fares /></>));
    await waitFor(() => expect(screen.getByText(/Pairs sampled/i)).toBeInTheDocument());
    expect(screen.getAllByText(/Median fare/i).length).toBeGreaterThan(0);
    expect(screen.getByText("$4.50")).toBeInTheDocument();   // median
    expect(screen.getByText(/Agencies in sample/i)).toBeInTheDocument();
    // Fare distribution + tier chart are both rendered.
    expect(screen.getByText(/Fare distribution/i)).toBeInTheDocument();
    expect(screen.getByText(/Median fare by equity tier/i)).toBeInTheDocument();
  });

  it("renders the high-burden cells list with the top cell highlighted", async () => {
    function Pair() {
      const { setFaresPin } = useSelection();
      React.useEffect(() => {
        setFaresPin(_BERKELEY);
        setFaresPin(_EMBARCAD);
      }, [setFaresPin]);
      return null;
    }
    render(wrap(<><Pair /><Fares /></>));
    await waitFor(() => expect(screen.getByText(/High-burden cells/i)).toBeInTheDocument());
    expect(screen.getByText("C1")).toBeInTheDocument();
    expect(screen.getByText("C2")).toBeInTheDocument();
    // Top row's burden (1.92) shows up.
    expect(screen.getByText(/burden 1\.920/)).toBeInTheDocument();
  });

  it("'Clear pins' resets selection and returns to the empty state", async () => {
    function Pair() {
      const { setFaresPin } = useSelection();
      React.useEffect(() => {
        setFaresPin(_BERKELEY);
        setFaresPin(_EMBARCAD);
      }, [setFaresPin]);
      return null;
    }
    render(wrap(<><Pair /><Fares /></>));
    await waitFor(() => expect(screen.getByText(/Pairs sampled/i)).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /Clear pins/i }));
    await waitFor(() => expect(screen.getByText(/Click an origin on the map/i)).toBeInTheDocument());
  });

  it("the fares-pin cycle replaces origin on click 3 while keeping destination", async () => {
    /** Drives the cycle through three clicks and probes the SelectionContext
     *  state to verify origin/dest match the design doc's documented cycle. */
    function CycleDriver() {
      const { setFaresPin, selection } = useSelection();
      const [step, setStep] = React.useState(0);
      React.useEffect(() => {
        if (step === 0) { setFaresPin({ lat: 37.87, lng: -122.27 }); setStep(1); }   // origin
        else if (step === 1) { setFaresPin({ lat: 37.79, lng: -122.40 }); setStep(2); } // destination
        else if (step === 2) { setFaresPin({ lat: 37.80, lng: -122.27 }); setStep(3); } // cycle → new origin
      }, [step, setFaresPin]);
      return (
        <div data-testid="state">
          {step}|{selection.faresOrigin?.lat ?? "null"}|{selection.faresDestination?.lat ?? "null"}
        </div>
      );
    }
    render(wrap(<CycleDriver />));
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("3|37.8|37.79"));
    // After click 3 origin is the new lat 37.80; destination stayed 37.79.
  });
});

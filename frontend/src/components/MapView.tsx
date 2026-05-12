import React, { useCallback, useEffect, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import axios from "axios";
import type { LatLng, Section } from "../types";
import { AGENCY_LIST, ALL_AGENCY_IDS } from "../lib/agencies";
import { useFilters } from "../context/FilterContext";
import { useSelection } from "../context/SelectionContext";

// ─── Config ──────────────────────────────────────────────────────────────────

const MAPBOX_TOKEN = (import.meta.env.VITE_MAPBOX_ACCESS_TOKEN as string) || "";
const API_BASE = (import.meta.env.VITE_API_BASE_URL as string) || "http://localhost:8000";
const API_KEY = (import.meta.env.VITE_API_KEY as string) || "";

if (MAPBOX_TOKEN) mapboxgl.accessToken = MAPBOX_TOKEN;

function apiHeaders(): Record<string, string> {
  return API_KEY ? { "X-API-Key": API_KEY } : {};
}

// ─── Types ────────────────────────────────────────────────────────────────────

export interface MapViewProps {
  /** Which layer set to render. Maps a SectionKey to the legacy Section
   *  union, e.g. "operations" → "reliability". */
  mapMode: Section;
  /** Dark map style is the only style supported today; light parity is Plan 1c. */
  darkMode?: boolean;
}

interface LegendItem {
  color: string;
  label: string;
  shape?: "circle" | "square";
}

// ─── Layer / source constants ─────────────────────────────────────────────────

const SOURCES = ["reliability-stops", "safety-stops", "crowding-stops", "demand-stops", "coverage-cells", "deserts", "equity-cells", "selected-route", "rt-vehicles", "planner-origin", "planner-dest", "traffic-events", "work-zones", "affected-routes"] as const;

const SECTION_LAYERS: Record<Section, string[]> = {
  // reliability-heat is included here so toggleLayers hides it when leaving these sections.
  // Actual visibility within the section is managed by the heatmapMode toggle effect.
  reliability: ["reliability-layer", "reliability-layer-border", "reliability-heat"],
  safety:      ["safety-layer", "safety-layer-border"],
  crowding:    ["crowding-layer", "crowding-layer-border"],
  demand:      ["demand-layer"],
  coverage:    ["coverage-fill", "coverage-outline", "deserts-fill", "deserts-outline"],
  equity:      ["equity-fill", "equity-outline"],
  routes:      ["route-shape-line", "route-stops-circle"],
  bunching:    ["reliability-layer", "reliability-layer-border", "reliability-heat"],
  vehicles:    ["vehicles-layer"],
  comparison:  [],
  planner:     ["planner-origin-circle", "planner-dest-circle"],
  ai:          [],
  benchmarks:  [],
  traffic:     ["traffic-events-layer", "work-zones-layer", "affected-routes-layer"],
};

const ALL_LAYERS = Object.values(SECTION_LAYERS).flat();

// ─── Paint expressions ────────────────────────────────────────────────────────

const DELAY_COLOR: mapboxgl.Expression = [
  "interpolate", ["linear"], ["coalesce", ["get", "avg_delay_seconds"], 0],
  0,   "#22c55e",
  60,  "#facc15",
  120, "#f97316",
  300, "#ef4444",
];

const SAFETY_COLOR: mapboxgl.Expression = [
  "interpolate", ["linear"], ["coalesce", ["get", "safety_score"], 0],
  0,  "#22c55e",
  3,  "#facc15",
  6,  "#f97316",
  10, "#ef4444",
];

const CROWDING_COLOR: mapboxgl.Expression = [
  "match", ["coalesce", ["get", "dominant_crowding_level"], "unknown"],
  "low",     "#22c55e",
  "medium",  "#f97316",
  "high",    "#ef4444",
  /* else */ "#475569",
];

const DEMAND_RADIUS: mapboxgl.Expression = [
  "interpolate", ["linear"], ["coalesce", ["get", "total_boardings"], 0],
  0,   4,
  50,  8,
  150, 14,
  400, 22,
];

const COVERAGE_COLOR: mapboxgl.Expression = [
  "interpolate", ["linear"], ["coalesce", ["get", "effective_frequency_per_hour"], 0],
  0,   "#0f172a",
  0.5, "#1e3a5f",
  2,   "#1d4ed8",
  5,   "#38bdf8",
  8,   "#bae6fd",
];

// Agency color lookup for vehicle dots — flat match expression, evaluated on GPU
const AGENCY_VEHICLE_COLOR: mapboxgl.Expression = [
  "match", ["coalesce", ["get", "agency_id"], ""],
  ...AGENCY_LIST.flatMap(a => [a.id, a.color]),
  "#888888", // fallback
];

// ─── Legend definitions ───────────────────────────────────────────────────────

const LEGENDS: Record<Section, { title: string; items: LegendItem[] }> = {
  reliability: {
    title: "Avg. Delay",
    items: [
      { color: "#22c55e", label: "On time  (< 1 min)" },
      { color: "#facc15", label: "Minor    (1–2 min)" },
      { color: "#f97316", label: "Moderate (2–5 min)" },
      { color: "#ef4444", label: "Severe   (> 5 min)" },
    ],
  },
  safety: {
    title: "Safety Risk",
    items: [
      { color: "#22c55e", label: "Low risk" },
      { color: "#facc15", label: "Moderate" },
      { color: "#f97316", label: "Elevated" },
      { color: "#ef4444", label: "High risk" },
    ],
  },
  crowding: {
    title: "Crowding Level",
    items: [
      { color: "#22c55e", label: "Low" },
      { color: "#f97316", label: "Medium" },
      { color: "#ef4444", label: "High" },
      { color: "#475569", label: "Unknown" },
    ],
  },
  demand: {
    title: "Forecast Boardings",
    items: [
      { color: "#a855f7", label: "High (> 150 boardings)" },
      { color: "#c084fc", label: "Medium (50–150)" },
      { color: "#e9d5ff", label: "Low (< 50)" },
    ],
  },
  coverage: {
    title: "Transit Coverage",
    items: [
      { color: "#bae6fd", label: "High frequency",   shape: "square" },
      { color: "#1d4ed8", label: "Moderate",          shape: "square" },
      { color: "#0f172a", label: "Low / no service",  shape: "square" },
      { color: "#ef4444", label: "Transit desert",    shape: "square" },
    ],
  },
  equity: {
    title: "Equity Analysis",
    items: [
      { color: "#dc2626", label: "Very high need", shape: "square" },
      { color: "#f97316", label: "High need",      shape: "square" },
      { color: "#facc15", label: "Moderate need",  shape: "square" },
      { color: "#22c55e", label: "Low need",        shape: "square" },
    ],
  },
  routes: {
    title: "Route Explorer",
    items: [
      { color: "#38bdf8", label: "Route shape",  shape: "square" },
      { color: "#38bdf8", label: "Stops" },
    ],
  },
  bunching: {
    title: "Service Irregularity",
    items: [
      { color: "#22c55e", label: "Consistent  (low σ)" },
      { color: "#facc15", label: "Variable" },
      { color: "#ef4444", label: "Irregular   (high σ)" },
    ],
  },
  vehicles: {
    title: "Live Vehicles",
    items: AGENCY_LIST.map(a => ({ color: a.color, label: a.name })),
  },
  comparison: {
    title: "Route Comparison",
    items: [],
  },
  planner: {
    title: "Trip Planner",
    items: [
      { color: "#22c55e", label: "Origin (click map)" },
      { color: "#ef4444", label: "Destination" },
    ],
  },
  ai: {
    title: "AI Assistant",
    items: [],
  },
  benchmarks: {
    title: "Agency Benchmarks",
    items: [],
  },
  traffic: {
    title: "Traffic",
    items: [
      { color: "#ef4444", label: "Active incident" },
      { color: "#f97316", label: "Work zone" },
    ],
  },
};

// ─── Popup HTML builders ──────────────────────────────────────────────────────

function fmt(n: number | null | undefined, decimals = 0): string {
  if (n == null || isNaN(n)) return "—";
  return n.toFixed(decimals);
}

function popupRow(label: string, value: string): string {
  return `<div class="popup-row"><span class="popup-label">${label}</span><span class="popup-value">${value}</span></div>`;
}

function popupHTML(title: string, rows: string[]): string {
  return `<div class="map-popup"><div class="popup-title">${title}</div>${rows.join("")}</div>`;
}

function reliabilityPopup(p: Record<string, unknown>): string {
  const delay = Number(p.avg_delay_seconds ?? 0);
  const status = delay < 60 ? "On time" : delay < 120 ? "Minor delay" : delay < 300 ? "Moderate delay" : "Severe delay";
  return popupHTML(String(p.stop_name ?? p.stop_id ?? "Stop"), [
    popupRow("Avg delay", `${fmt(delay, 0)} s`),
    popupRow("Status", status),
    popupRow("Observations", String(p.sample_count ?? "—")),
  ]);
}

function safetyPopup(p: Record<string, unknown>): string {
  return popupHTML(String(p.stop_name ?? p.stop_id ?? "Stop"), [
    popupRow("Safety score",    fmt(Number(p.safety_score), 2)),
    popupRow("Crime incidents", String(p.crime_incidents_nearby ?? "—")),
    popupRow("Collisions",      String(p.collisions_nearby    ?? "—")),
  ]);
}

function crowdingPopup(p: Record<string, unknown>): string {
  const level = String(p.dominant_crowding_level ?? "unknown");
  return popupHTML(String(p.stop_name ?? p.stop_id ?? "Stop"), [
    popupRow("Crowding",     level.charAt(0).toUpperCase() + level.slice(1)),
    popupRow("Predictions",  String(p.prediction_count ?? "—")),
  ]);
}

function demandPopup(p: Record<string, unknown>): string {
  return popupHTML(String(p.stop_name ?? p.stop_id ?? "Stop"), [
    popupRow("Forecast boardings", fmt(Number(p.total_boardings), 0)),
    popupRow("Routes serving",     String(p.routes_serving ?? "—")),
  ]);
}

function coveragePopup(p: Record<string, unknown>): string {
  const freq = Number(p.effective_frequency_per_hour ?? 0);
  const dist = Number(p.distance_to_nearest_stop_m ?? 0);
  return popupHTML("Coverage Cell", [
    popupRow("Freq (trips/hr)",   fmt(freq, 1)),
    popupRow("Nearest stop",      `${fmt(dist, 0)} m`),
    popupRow("Stops in walk",     String(p.stops_within_walk ?? "—")),
  ]);
}

function equityPopup(p: Record<string, unknown>): string {
  const tier = String(p.equity_tier ?? "").replace("_", " ");
  return popupHTML("Equity Zone", [
    popupRow("Equity score",    fmt(Number(p.equity_score), 3)),
    popupRow("Tier",            tier.toUpperCase()),
    popupRow("Est. population", fmt(Number(p.population), 0)),
    popupRow("Low-income pop.", fmt(Number(p.low_income_population), 0)),
    popupRow("No-car HH",       fmt(Number(p.no_car_households), 0)),
  ]);
}

function desertPopup(p: Record<string, unknown>): string {
  return popupHTML("Transit Desert", [
    popupRow("Desert score", fmt(Number(p.desert_score), 2)),
    popupRow("Notes",        String(p.notes ?? "Low coverage area")),
  ]);
}

function routeStopPopup(p: Record<string, unknown>): string {
  return popupHTML(String(p.stop_name ?? p.stop_id ?? "Stop"), [
    popupRow("Stop ID", String(p.stop_id ?? "—")),
    popupRow("Sequence", String(p.stop_sequence ?? "—")),
  ]);
}

function vehiclePopup(p: Record<string, unknown>): string {
  return popupHTML(`Vehicle ${p.vehicle_id ?? "—"}`, [
    popupRow("Route", String(p.route_id ?? "—")),
    popupRow("Speed", p.speed ? `${fmt(Number(p.speed), 1)} m/s` : "—"),
    popupRow("Bearing", p.bearing ? `${fmt(Number(p.bearing), 0)}°` : "—"),
  ]);
}

function trafficEventPopup(p: Record<string, unknown>): string {
  return popupHTML(String(p.description ?? p.event_type ?? "Incident"), [
    popupRow("Type",     String(p.event_type ?? "—")),
    popupRow("Severity", String(p.severity   ?? "—")),
    popupRow("Road",     String(p.road_name  ?? "—")),
  ]);
}

function workZonePopup(p: Record<string, unknown>): string {
  return popupHTML(String(p.road_name ?? "Work Zone"), [
    popupRow("Description", String(p.description ?? "—")),
    popupRow("Start", p.start_time ? new Date(String(p.start_time)).toLocaleDateString() : "—"),
    popupRow("End",   p.end_time   ? new Date(String(p.end_time)).toLocaleDateString()   : "—"),
  ]);
}

// ─── Map layer popup layer IDs ────────────────────────────────────────────────

const POPUP_LAYERS: Partial<Record<string, (p: Record<string, unknown>) => string>> = {
  "reliability-layer":       reliabilityPopup,
  "safety-layer":            safetyPopup,
  "crowding-layer":          crowdingPopup,
  "demand-layer":            demandPopup,
  "coverage-fill":           coveragePopup,
  "equity-fill":             equityPopup,
  "deserts-fill":            desertPopup,
  "route-stops-circle":      routeStopPopup,
  "vehicles-layer":          vehiclePopup,
  "traffic-events-layer":    trafficEventPopup,
  "work-zones-layer":        workZonePopup,
};

// Stop circle layers that support onStopClick
const STOP_CLICK_LAYERS = [
  "reliability-layer",
  "safety-layer",
  "crowding-layer",
  "demand-layer",
  "route-stops-circle",
];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function emptyFC(): GeoJSON.FeatureCollection {
  return { type: "FeatureCollection", features: [] };
}

function setSource(map: mapboxgl.Map, id: string, data: GeoJSON.FeatureCollection) {
  const src = map.getSource(id) as mapboxgl.GeoJSONSource | undefined;
  if (src) src.setData(data);
}

// ─── Component ────────────────────────────────────────────────────────────────

export const MapView: React.FC<MapViewProps> = ({ mapMode, darkMode = true }) => {
  // Read filter + selection from contexts. Local aliases below keep the
  // rest of the ~1,100-line component compiling unchanged.
  const { filters } = useFilters();
  const { selection, setStopId, setPlannerOrigin, setPlannerDest, resetPlanner } = useSelection();

  const startDate = filters.startDate;
  const endDate = filters.endDate;
  const dateRange = { startDate, endDate };
  const selectedAgencies = filters.agencies;
  const selectedRouteId = selection.routeId;
  const activeSection = mapMode;
  const onStopClick = setStopId;
  const plannerOrigin: LatLng | null = selection.plannerOrigin;
  const plannerDest: LatLng | null = selection.plannerDest;
  const onPlannerMapClick = (lat: number, lng: number) => {
    if (!selection.plannerOrigin) {
      setPlannerOrigin({ lat, lng });
    } else if (!selection.plannerDest) {
      setPlannerDest({ lat, lng });
    } else {
      resetPlanner();
      setPlannerOrigin({ lat, lng });
    }
  };

  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef         = useRef<mapboxgl.Map | null>(null);
  const mapLoadedRef   = useRef(false);
  const popupRef       = useRef<mapboxgl.Popup | null>(null);
  const selectedRouteIdRef = useRef<string | null>(selectedRouteId);

  // Stable refs for use inside async map callbacks
  const darkModeRef           = useRef(darkMode);
  const activeSectionRef      = useRef(activeSection);
  const dateRangeRef          = useRef(dateRange);
  const onStopClickRef        = useRef(onStopClick);
  const onPlannerMapClickRef  = useRef(onPlannerMapClick);
  const isFirstRenderRef      = useRef(true);

  // Keep refs in sync with props/state
  useEffect(() => { selectedRouteIdRef.current = selectedRouteId; }, [selectedRouteId]);
  useEffect(() => { darkModeRef.current = darkMode; }, [darkMode]);
  useEffect(() => { activeSectionRef.current = activeSection; }, [activeSection]);
  useEffect(() => { dateRangeRef.current = dateRange; }, [dateRange]);
  useEffect(() => { onStopClickRef.current = onStopClick; }, [onStopClick]);
  useEffect(() => { onPlannerMapClickRef.current = onPlannerMapClick; }, [onPlannerMapClick]);

  const [loading,    setLoading]    = useState(false);
  const [error,      setError]      = useState<string | null>(null);
  const [isEmpty,    setIsEmpty]    = useState(false);
  const [heatmapMode, setHeatmapMode] = useState(false);

  // ── Apply data to a source (safe: waits for map load) ──────────────────────
  const applyGeoJSON = useCallback(
    (sourceId: string, data: GeoJSON.FeatureCollection) => {
      if (mapRef.current && mapLoadedRef.current) {
        setSource(mapRef.current, sourceId, data);
      }
    },
    []
  );

  // ── Fetch data for the active section ──────────────────────────────────────
  const fetchSection = useCallback(
    async (section: Section, start: string, end: string) => {
      if (!API_BASE) return;
      setLoading(true);
      setError(null);
      setIsEmpty(false);

      const h = apiHeaders();
      const p = { params: { start_date: start, end_date: end }, headers: h };

      try {
        switch (section) {
          case "reliability": {
            const res = await axios.get(`${API_BASE}/reliability/stops/geo`, p);
            const fc = res.data as GeoJSON.FeatureCollection;
            applyGeoJSON("reliability-stops", fc);
            setIsEmpty(fc.features.length === 0);
            break;
          }
          case "safety": {
            const res = await axios.get(`${API_BASE}/safety/stops/geo`, { headers: h });
            const fc = res.data as GeoJSON.FeatureCollection;
            applyGeoJSON("safety-stops", fc);
            setIsEmpty(fc.features.length === 0);
            break;
          }
          case "crowding": {
            const res = await axios.get(`${API_BASE}/crowding/stops/geo`, p);
            const fc = res.data as GeoJSON.FeatureCollection;
            applyGeoJSON("crowding-stops", fc);
            setIsEmpty(fc.features.length === 0);
            break;
          }
          case "demand": {
            const res = await axios.get(`${API_BASE}/demand/stops/geo`, p);
            const fc = res.data as GeoJSON.FeatureCollection;
            applyGeoJSON("demand-stops", fc);
            setIsEmpty(fc.features.length === 0);
            break;
          }
          case "coverage": {
            const [cellsRes, desertsRes] = await Promise.all([
              axios.get(`${API_BASE}/coverage/cells`,   { headers: h }),
              axios.get(`${API_BASE}/coverage/deserts`, { headers: h }),
            ]);
            const cells   = cellsRes.data   as GeoJSON.FeatureCollection;
            const deserts = desertsRes.data as GeoJSON.FeatureCollection;
            applyGeoJSON("coverage-cells", cells);
            applyGeoJSON("deserts",        deserts);
            setIsEmpty(cells.features.length === 0);
            break;
          }
          case "equity": {
            const res = await axios.get(`${API_BASE}/equity/score`, { headers: h });
            const fc  = res.data as GeoJSON.FeatureCollection;
            applyGeoJSON("equity-cells", fc);
            setIsEmpty(fc.features.length === 0);
            break;
          }
          case "routes": {
            const routeId = selectedRouteIdRef.current;
            if (routeId) {
              const res = await axios.get(`${API_BASE}/routes/${encodeURIComponent(routeId)}/geo`, { headers: h });
              applyGeoJSON("selected-route", res.data as GeoJSON.FeatureCollection);
              setIsEmpty(false);
            } else {
              applyGeoJSON("selected-route", emptyFC());
              setIsEmpty(false);
            }
            break;
          }
          case "bunching": {
            const res = await axios.get(`${API_BASE}/reliability/stops/geo`, p);
            const fc = res.data as GeoJSON.FeatureCollection;
            applyGeoJSON("reliability-stops", fc);
            setIsEmpty(fc.features.length === 0);
            break;
          }
          case "vehicles": {
            const res = await axios.get(`${API_BASE}/vehicles/live`);
            const fc = res.data as GeoJSON.FeatureCollection;
            applyGeoJSON("rt-vehicles", fc);
            setIsEmpty(fc.features.length === 0);
            break;
          }
          case "comparison": {
            setIsEmpty(false);
            break;
          }
          case "traffic": {
            const [eventsRes, zonesRes, impactRes] = await Promise.all([
              axios.get(`${API_BASE}/traffic/events`,          { headers: h }),
              axios.get(`${API_BASE}/traffic/work-zones`,      { headers: h }),
              axios.get(`${API_BASE}/traffic/transit-impact`,  { headers: h }),
            ]);
            const evFC = eventsRes.data as GeoJSON.FeatureCollection;
            const wzFC = zonesRes.data  as GeoJSON.FeatureCollection;
            applyGeoJSON("traffic-events", evFC);
            applyGeoJSON("work-zones",     wzFC);

            // Build affected-routes FeatureCollection from unique route_ids
            const impactRows = impactRes.data as {
              route_id: string; alert_level: string;
            }[];
            const seen = new Map<string, string>(); // route_id → alert_level
            for (const row of impactRows) {
              // CRITICAL takes priority over WARNING/WATCH
              const prev = seen.get(row.route_id);
              if (!prev || row.alert_level === "CRITICAL" || (row.alert_level === "WARNING" && prev === "WATCH")) {
                seen.set(row.route_id, row.alert_level);
              }
            }
            const shapeResults = await Promise.allSettled(
              [...seen.entries()].map(([rid, level]) =>
                axios
                  .get<GeoJSON.FeatureCollection>(`${API_BASE}/routes/${rid}/geo`, { headers: h })
                  .then(r => ({ fc: r.data, level }))
              )
            );
            const affectedFeatures: GeoJSON.Feature[] = [];
            for (const r of shapeResults) {
              if (r.status === "fulfilled") {
                for (const feat of r.value.fc.features) {
                  affectedFeatures.push({ ...feat, properties: { ...(feat.properties ?? {}), alert_level: r.value.level } });
                }
              }
            }
            applyGeoJSON("affected-routes", { type: "FeatureCollection", features: affectedFeatures });
            setIsEmpty(evFC.features.length === 0 && wzFC.features.length === 0 && affectedFeatures.length === 0);
            break;
          }
          case "planner":
          case "ai": {
            setIsEmpty(false);
            break;
          }
        }
      } catch (err: unknown) {
        if (axios.isAxiosError(err)) {
          if (err.response?.status === 401) {
            setError("API key required — set VITE_API_KEY in .env");
          } else {
            setError(err.message ?? "Failed to load data");
          }
        }
      } finally {
        setLoading(false);
      }
    },
    [applyGeoJSON]
  );

  // ── Add all sources, layers, and event handlers to the map ──────────────────
  // Called on initial load and after every setStyle() call.
  const setupMapContent = useCallback((map: mapboxgl.Map) => {
    // ── Add all GeoJSON sources ────────────────────────────────────────────
    for (const id of SOURCES) {
      if (!map.getSource(id)) {
        map.addSource(id, { type: "geojson", data: emptyFC() });
      }
    }

    // ── Reliability ────────────────────────────────────────────────────────
    map.addLayer({
      id: "reliability-layer", type: "circle", source: "reliability-stops",
      layout: { visibility: "none" },
      paint: {
        "circle-color":        DELAY_COLOR,
        "circle-radius":       7,
        "circle-opacity":      0.88,
        "circle-stroke-width": 0,
      },
    });
    map.addLayer({
      id: "reliability-layer-border", type: "circle", source: "reliability-stops",
      layout: { visibility: "none" },
      paint: {
        "circle-color":   "transparent",
        "circle-radius":  8,
        "circle-stroke-width": 1.5,
        // circle-stroke-color accepts an interpolate expression directly;
        // wrapping in ["to-color", ...] fails style validation because
        // to-color expects a single color value, not an expression.
        "circle-stroke-color": DELAY_COLOR,
        "circle-stroke-opacity": 0.5,
      },
    });

    // ── Safety ─────────────────────────────────────────────────────────────
    map.addLayer({
      id: "safety-layer", type: "circle", source: "safety-stops",
      layout: { visibility: "none" },
      paint: {
        "circle-color":   SAFETY_COLOR,
        "circle-radius":  7,
        "circle-opacity": 0.88,
      },
    });
    map.addLayer({
      id: "safety-layer-border", type: "circle", source: "safety-stops",
      layout: { visibility: "none" },
      paint: {
        "circle-color":  "transparent",
        "circle-radius":  8,
        "circle-stroke-width": 1.5,
        "circle-stroke-color": SAFETY_COLOR,
        "circle-stroke-opacity": 0.5,
      },
    });

    // ── Crowding ───────────────────────────────────────────────────────────
    map.addLayer({
      id: "crowding-layer", type: "circle", source: "crowding-stops",
      layout: { visibility: "none" },
      paint: {
        "circle-color":   CROWDING_COLOR,
        "circle-radius":  7,
        "circle-opacity": 0.88,
      },
    });
    map.addLayer({
      id: "crowding-layer-border", type: "circle", source: "crowding-stops",
      layout: { visibility: "none" },
      paint: {
        "circle-color":  "transparent",
        "circle-radius":  8,
        "circle-stroke-width": 1.5,
        "circle-stroke-color": ["to-color", CROWDING_COLOR],
        "circle-stroke-opacity": 0.5,
      },
    });

    // ── Demand ─────────────────────────────────────────────────────────────
    map.addLayer({
      id: "demand-layer", type: "circle", source: "demand-stops",
      layout: { visibility: "none" },
      paint: {
        "circle-color":   "#a855f7",
        "circle-radius":  DEMAND_RADIUS,
        "circle-opacity": 0.75,
        "circle-stroke-width": 1,
        "circle-stroke-color": "#d8b4fe",
        "circle-stroke-opacity": 0.6,
      },
    });

    // ── Coverage cells ─────────────────────────────────────────────────────
    map.addLayer({
      id: "coverage-fill", type: "fill", source: "coverage-cells",
      layout: { visibility: "none" },
      paint: {
        "fill-color":   COVERAGE_COLOR,
        "fill-opacity": 0.65,
      },
    });
    map.addLayer({
      id: "coverage-outline", type: "line", source: "coverage-cells",
      layout: { visibility: "none" },
      paint: {
        "line-color":   "rgba(148,163,184,0.15)",
        "line-width":   0.5,
      },
    });

    // ── Equity cells ──────────────────────────────────────────────────────
    map.addLayer({
      id: "equity-fill", type: "fill", source: "equity-cells",
      layout: { visibility: "none" },
      paint: {
        "fill-color": [
          "interpolate", ["linear"],
          ["coalesce", ["get", "equity_score"], 0.5],
          0.0,  "#22c55e",   // low need → green
          0.1,  "#86efac",
          0.15, "#facc15",   // moderate → yellow
          0.25, "#f97316",   // high → orange
          0.35, "#dc2626",   // very high → deep red
        ],
        "fill-opacity": 0.7,
      },
    });
    map.addLayer({
      id: "equity-outline", type: "line", source: "equity-cells",
      layout: { visibility: "none" },
      paint: {
        "line-color":   "rgba(148,163,184,0.12)",
        "line-width":   0.5,
      },
    });

    // ── Transit deserts ────────────────────────────────────────────────────
    map.addLayer({
      id: "deserts-fill", type: "fill", source: "deserts",
      layout: { visibility: "none" },
      paint: {
        "fill-color":   "#ef4444",
        "fill-opacity": 0.22,
      },
    });
    map.addLayer({
      id: "deserts-outline", type: "line", source: "deserts",
      layout: { visibility: "none" },
      paint: {
        "line-color":   "#ef4444",
        "line-width":   1.5,
        "line-opacity": 0.7,
        "line-dasharray": [3, 2],
      },
    });

    // ── Live vehicles ──────────────────────────────────────────────────────
    map.addLayer({
      id: "vehicles-layer", type: "circle", source: "rt-vehicles",
      layout: { visibility: "none" },
      paint: {
        "circle-color": AGENCY_VEHICLE_COLOR,
        "circle-radius": 7,
        "circle-opacity": 0.9,
        "circle-stroke-width": 2,
        "circle-stroke-color": "#0f172a",
      },
    });

    // ── Reliability heatmap ────────────────────────────────────────────────
    map.addLayer({
      id: "reliability-heat", type: "heatmap", source: "reliability-stops",
      layout: { visibility: "none" },
      paint: {
        "heatmap-weight": ["interpolate", ["linear"], ["coalesce", ["get", "avg_delay_seconds"], 0], 0, 0, 300, 1],
        "heatmap-intensity": 1.5,
        "heatmap-color": [
          "interpolate", ["linear"], ["heatmap-density"],
          0, "rgba(0,0,0,0)",
          0.2, "#22c55e",
          0.5, "#facc15",
          0.8, "#f97316",
          1, "#ef4444",
        ],
        "heatmap-radius": 25,
        "heatmap-opacity": 0.7,
      },
    });

    // ── Selected route ─────────────────────────────────────────────────────
    map.addLayer({
      id: "route-shape-line", type: "line", source: "selected-route",
      filter: ["==", ["get", "feature_type"], "shape"],
      layout: { visibility: "none", "line-join": "round", "line-cap": "round" },
      paint: { "line-color": "#38bdf8", "line-width": 4, "line-opacity": 0.9 },
    });
    map.addLayer({
      id: "route-stops-circle", type: "circle", source: "selected-route",
      filter: ["==", ["get", "feature_type"], "stop"],
      layout: { visibility: "none" },
      paint: {
        "circle-color": "#38bdf8", "circle-radius": 6,
        "circle-stroke-width": 2, "circle-stroke-color": "#0f172a",
      },
    });

    // ── Traffic incidents ──────────────────────────────────────────────────
    map.addLayer({
      id: "traffic-events-layer", type: "circle", source: "traffic-events",
      layout: { visibility: "none" },
      paint: {
        "circle-color": [
          "match", ["coalesce", ["get", "severity"], ""],
          "Major",    "#ef4444",
          "Moderate", "#f97316",
          /* else */  "#facc15",
        ],
        "circle-radius":       10,
        "circle-opacity":      0.9,
        "circle-stroke-width": 2,
        "circle-stroke-color": "#0f172a",
      },
    });

    // ── Work zones ─────────────────────────────────────────────────────────
    map.addLayer({
      id: "work-zones-layer", type: "line", source: "work-zones",
      layout: { visibility: "none", "line-join": "round", "line-cap": "round" },
      paint: {
        "line-color":     "#f97316",
        "line-width":     4,
        "line-opacity":   0.85,
        "line-dasharray": [2, 2],
      },
    });

    // ── Affected routes (traffic impact) ──────────────────────────────────
    map.addLayer({
      id: "affected-routes-layer", type: "line", source: "affected-routes",
      layout: { visibility: "none", "line-join": "round", "line-cap": "round" },
      paint: {
        "line-color": [
          "match", ["coalesce", ["get", "alert_level"], "WATCH"],
          "CRITICAL", "#ef4444",
          "WARNING",  "#f97316",
          /* else */  "#facc15",
        ],
        "line-width":   5,
        "line-opacity": 0.85,
      },
    });

    // ── Trip planner markers ───────────────────────────────────────────────
    map.addLayer({
      id: "planner-origin-circle", type: "circle", source: "planner-origin",
      layout: { visibility: "none" },
      paint: {
        "circle-color": "#22c55e",
        "circle-radius": 10,
        "circle-stroke-width": 3,
        "circle-stroke-color": "#fff",
        "circle-opacity": 0.95,
      },
    });
    map.addLayer({
      id: "planner-dest-circle", type: "circle", source: "planner-dest",
      layout: { visibility: "none" },
      paint: {
        "circle-color": "#ef4444",
        "circle-radius": 10,
        "circle-stroke-width": 3,
        "circle-stroke-color": "#fff",
        "circle-opacity": 0.95,
      },
    });

    // ── Planner map click ──────────────────────────────────────────────────
    map.on("click", (e) => {
      if (activeSectionRef.current !== "planner") return;
      onPlannerMapClickRef.current(e.lngLat.lat, e.lngLat.lng);
    });

    // ── Hover interactions (popups only) ───────────────────────────────────
    for (const [layerId, buildPopup] of Object.entries(POPUP_LAYERS)) {
      map.on("mousemove", layerId, (e) => {
        map.getCanvas().style.cursor = "pointer";
        const feature = e.features?.[0];
        if (!feature || !popupRef.current || !buildPopup) return;
        const props = feature.properties as Record<string, unknown>;
        popupRef.current
          .setLngLat(e.lngLat)
          .setHTML(buildPopup(props))
          .addTo(map);
      });

      map.on("mouseleave", layerId, () => {
        map.getCanvas().style.cursor = "";
        popupRef.current?.remove();
      });
    }

    // ── Click handlers for stop layers ─────────────────────────────────────
    for (const layerId of STOP_CLICK_LAYERS) {
      map.on("click", layerId, (e) => {
        const props = e.features?.[0]?.properties as Record<string, unknown> | undefined;
        if (props?.stop_id) onStopClickRef.current(String(props.stop_id));
      });
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Initialise map ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (mapRef.current || !mapContainerRef.current || !MAPBOX_TOKEN) return;

    const map = new mapboxgl.Map({
      container: mapContainerRef.current,
      style: darkModeRef.current
        ? "mapbox://styles/mapbox/dark-v11"
        : "mapbox://styles/mapbox/light-v11",
      center: [-122.2711, 37.8044],
      zoom:   11,
    });

    map.addControl(new mapboxgl.NavigationControl(), "bottom-right");
    map.addControl(new mapboxgl.ScaleControl({ unit: "metric" }), "bottom-left");

    popupRef.current = new mapboxgl.Popup({
      closeButton:  false,
      closeOnClick: false,
      maxWidth:     "240px",
      className:    "batis-popup",
    });

    map.on("load", () => {
      setupMapContent(map);
      mapLoadedRef.current = true;
      mapRef.current = map;
      toggleLayers(map, activeSectionRef.current);
      fetchSection(activeSectionRef.current, dateRangeRef.current.startDate, dateRangeRef.current.endDate);
    });

    return () => {
      map.remove();
      mapRef.current   = null;
      mapLoadedRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Switch Mapbox base style when darkMode toggles ──────────────────────────
  useEffect(() => {
    // Skip the first render — map style is set correctly at init time
    if (isFirstRenderRef.current) {
      isFirstRenderRef.current = false;
      return;
    }
    const map = mapRef.current;
    if (!map) return;

    setHeatmapMode(false); // reset heatmap; it will be re-enabled by the user if desired
    const newStyle = darkMode
      ? "mapbox://styles/mapbox/dark-v11"
      : "mapbox://styles/mapbox/light-v11";
    mapLoadedRef.current = false;
    map.once("style.load", () => {
      setupMapContent(map);
      mapLoadedRef.current = true;
      toggleLayers(map, activeSectionRef.current);
      fetchSection(activeSectionRef.current, dateRangeRef.current.startDate, dateRangeRef.current.endDate);
    });
    map.setStyle(newStyle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [darkMode]);

  // ── Toggle layer visibility on section change ───────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoadedRef.current) return;
    toggleLayers(map, activeSection);
    fetchSection(activeSection, dateRange.startDate, dateRange.endDate);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSection, dateRange.startDate, dateRange.endDate]);

  // ── Re-fetch route geo when selectedRouteId changes (routes section) ────────
  useEffect(() => {
    if (activeSection === "routes" && mapLoadedRef.current) {
      fetchSection("routes", dateRange.startDate, dateRange.endDate);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRouteId]);

  // ── Cross-filter stop-circle layers when a route is selected ────────────────
  // Stop properties typically expose either `route_id` (single-route stops)
  // or `routes_serving` (a comma-separated list). Match either.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      if (!map.isStyleLoaded()) return;
      const rid = selectedRouteId;
      const filter: any = rid
        ? [
            "any",
            ["==", ["get", "route_id"], rid],
            ["in", rid, ["coalesce", ["get", "routes_serving"], ""]],
          ]
        : null;
      for (const layerId of [
        "reliability-layer",
        "reliability-layer-border",
        "safety-layer",
        "safety-layer-border",
        "crowding-layer",
        "crowding-layer-border",
        "demand-layer",
      ]) {
        if (map.getLayer(layerId)) {
          try { map.setFilter(layerId, filter); } catch { /* ignore unsupported layer types */ }
        }
      }
    };
    if (map.isStyleLoaded()) {
      apply();
    } else {
      map.once("style.load", apply);
    }
  }, [selectedRouteId]);

  // ── Poll vehicles every 30s when in vehicles section ─────────────────────
  useEffect(() => {
    if (activeSection !== "vehicles") return;
    const id = setInterval(() => {
      if (mapLoadedRef.current) fetchSection("vehicles", dateRange.startDate, dateRange.endDate);
    }, 30_000);
    return () => clearInterval(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSection]);

  // ── Update planner marker sources ────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoadedRef.current) return;
    const fc: GeoJSON.FeatureCollection = plannerOrigin
      ? { type: "FeatureCollection", features: [{ type: "Feature", geometry: { type: "Point", coordinates: [plannerOrigin.lng, plannerOrigin.lat] }, properties: {} }] }
      : emptyFC();
    setSource(map, "planner-origin", fc);
  }, [plannerOrigin]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoadedRef.current) return;
    const fc: GeoJSON.FeatureCollection = plannerDest
      ? { type: "FeatureCollection", features: [{ type: "Feature", geometry: { type: "Point", coordinates: [plannerDest.lng, plannerDest.lat] }, properties: {} }] }
      : emptyFC();
    setSource(map, "planner-dest", fc);
  }, [plannerDest]);

  // ── Crosshair cursor in planner mode ─────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoadedRef.current) return;
    map.getCanvas().style.cursor = activeSection === "planner" ? "crosshair" : "";
  }, [activeSection]);

  // ── Filter vehicles layer by selected agencies ────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoadedRef.current) return;
    if (!map.getLayer("vehicles-layer")) return;
    const allSelected = selectedAgencies.length === ALL_AGENCY_IDS.length;
    map.setFilter(
      "vehicles-layer",
      allSelected ? null : ["in", ["get", "agency_id"], ["literal", selectedAgencies]],
    );
  }, [selectedAgencies]);

  // ── Toggle heatmap vs dot view for reliability/bunching ──────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoadedRef.current) return;
    const isHeatSection = activeSection === "reliability" || activeSection === "bunching";
    const useHeat = heatmapMode && isHeatSection;
    if (map.getLayer("reliability-heat")) map.setLayoutProperty("reliability-heat", "visibility", useHeat ? "visible" : "none");
    if (isHeatSection) {
      const circleVis = useHeat ? "none" : "visible";
      if (map.getLayer("reliability-layer")) map.setLayoutProperty("reliability-layer", "visibility", circleVis);
      if (map.getLayer("reliability-layer-border")) map.setLayoutProperty("reliability-layer-border", "visibility", circleVis);
    }
  }, [heatmapMode, activeSection]);

  // ─── Render ──────────────────────────────────────────────────────────────────

  const legend = LEGENDS[activeSection];

  return (
    <div className="map-container">
      {MAPBOX_TOKEN ? (
        <div className="map-wrapper" ref={mapContainerRef} />
      ) : (
        <div className="map-placeholder">
          <p>Map requires a Mapbox token.</p>
          <p className="map-placeholder-hint">
            Set <code>VITE_MAPBOX_ACCESS_TOKEN</code> in <code>.env</code> and restart.
          </p>
        </div>
      )}

      {/* Legend */}
      {MAPBOX_TOKEN && (
        <div className="map-legend">
          <p className="legend-title">{legend.title}</p>
          {legend.items.map((item) => (
            <div key={item.label} className="legend-row">
              {item.shape === "square" ? (
                <span className="legend-swatch-square" style={{ background: item.color }} />
              ) : (
                <span className="legend-swatch" style={{ background: item.color }} />
              )}
              <span className="legend-label">{item.label}</span>
            </div>
          ))}
        </div>
      )}

      {/* Heatmap toggle */}
      {MAPBOX_TOKEN && (activeSection === "reliability" || activeSection === "bunching") && (
        <button
          className="map-heatmap-toggle"
          onClick={() => setHeatmapMode((h) => !h)}
        >
          {heatmapMode ? "Dot View" : "Heatmap"}
        </button>
      )}

      {/* Loading overlay */}
      {loading && (
        <div className="map-loading">
          <span className="map-loading-spinner" />
          <span>Loading data…</span>
        </div>
      )}

      {/* Empty state */}
      {!loading && isEmpty && (
        <div className="map-empty">
          No data available for this selection.
          <br />
          <small>Run the data pipeline to populate the database.</small>
        </div>
      )}

      {/* Error toast */}
      {error && (
        <div className="map-api-error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
};

// ─── Layer toggle helper (module-level so it doesn't re-create on render) ─────

function toggleLayers(map: mapboxgl.Map, active: Section) {
  const seen = new Set<string>();
  for (const [, layers] of Object.entries(SECTION_LAYERS) as [Section, string[]][]) {
    for (const layerId of layers) {
      if (seen.has(layerId)) continue;
      // reliability-heat visibility is managed exclusively by the heatmapMode effect.
      // Always hide it here; the effect will show it if needed.
      if (layerId === "reliability-heat") {
        if (map.getLayer(layerId)) map.setLayoutProperty(layerId, "visibility", "none");
        seen.add(layerId);
        continue;
      }
      const isActive = SECTION_LAYERS[active].includes(layerId);
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(layerId, "visibility", isActive ? "visible" : "none");
      }
      seen.add(layerId);
    }
  }
}

// Suppress unused import warning
void ALL_LAYERS;

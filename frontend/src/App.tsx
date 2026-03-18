import React, { useMemo, useState } from "react";
import { MapView } from "./components/MapView";
import { Sidebar } from "./components/Sidebar";
import { StopDrawer } from "./components/StopDrawer";
import { AlertsBanner } from "./components/AlertsBanner";

export type Section = "reliability" | "crowding" | "safety" | "coverage" | "demand" | "routes" | "bunching" | "vehicles" | "comparison" | "planner";

export interface LatLng { lat: number; lng: number; }

function defaultStartDate(): string {
  const d = new Date();
  d.setDate(d.getDate() - 7);
  return d.toISOString().slice(0, 10);
}

function defaultEndDate(): string {
  return new Date().toISOString().slice(0, 10);
}

export const App: React.FC = () => {
  const [activeSection, setActiveSection] = useState<Section>("reliability");
  const [startDate, setStartDate] = useState(defaultStartDate);
  const [endDate, setEndDate] = useState(defaultEndDate);
  const [selectedStopId, setSelectedStopId] = useState<string | null>(null);
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  const [darkMode, setDarkMode] = useState(true);
  const [plannerOrigin, setPlannerOrigin] = useState<LatLng | null>(null);
  const [plannerDest, setPlannerDest] = useState<LatLng | null>(null);

  const handlePlannerMapClick = (lat: number, lng: number) => {
    if (!plannerOrigin) {
      setPlannerOrigin({ lat, lng });
    } else if (!plannerDest) {
      setPlannerDest({ lat, lng });
    } else {
      // Third click resets: start over with new origin
      setPlannerOrigin({ lat, lng });
      setPlannerDest(null);
    }
  };

  const handleSectionChange = (s: Section) => {
    setActiveSection(s);
    if (s !== "planner") {
      setPlannerOrigin(null);
      setPlannerDest(null);
    }
  };

  const dateRange = useMemo(
    () => ({ startDate, endDate }),
    [startDate, endDate]
  );

  return (
    <div className="app-root" data-theme={darkMode ? "dark" : "light"}>
      <header className="app-header">
        <h1>Bay Area Transit Intelligence</h1>
        <nav className="app-nav">
          {(["reliability", "crowding", "safety", "coverage", "demand", "routes", "bunching", "vehicles", "comparison", "planner"] as Section[]).map((s) => (
            <button
              key={s}
              className={s === activeSection ? "tab active" : "tab"}
              onClick={() => handleSectionChange(s)}
            >
              {s === "reliability" && "Transit Reliability"}
              {s === "crowding" && "Crowding Prediction"}
              {s === "safety" && "Stop Safety"}
              {s === "coverage" && "Transit Coverage"}
              {s === "demand" && "Demand Forecast"}
              {s === "routes" && "Route Explorer"}
              {s === "bunching" && "Bunching"}
              {s === "vehicles" && "Live Vehicles"}
              {s === "comparison" && "Route Compare"}
              {s === "planner" && "Trip Planner"}
            </button>
          ))}
        </nav>
        <button
          className="mode-toggle"
          onClick={() => setDarkMode(d => !d)}
          title={darkMode ? "Switch to light mode" : "Switch to dark mode"}
        >
          {darkMode ? "☀" : "🌙"}
        </button>
      </header>
      <AlertsBanner />
      <div className="app-body">
        <Sidebar
          activeSection={activeSection}
          startDate={startDate}
          endDate={endDate}
          onStartDateChange={setStartDate}
          onEndDateChange={setEndDate}
          onRouteSelect={setSelectedRouteId}
          selectedRouteId={selectedRouteId}
          plannerOrigin={plannerOrigin}
          plannerDest={plannerDest}
          onResetPlanner={() => { setPlannerOrigin(null); setPlannerDest(null); }}
        />
        <MapView
          activeSection={activeSection}
          dateRange={dateRange}
          onStopClick={setSelectedStopId}
          selectedRouteId={selectedRouteId}
          darkMode={darkMode}
          plannerOrigin={plannerOrigin}
          plannerDest={plannerDest}
          onPlannerMapClick={handlePlannerMapClick}
        />
        <StopDrawer stopId={selectedStopId} onClose={() => setSelectedStopId(null)} />
      </div>
    </div>
  );
};



import React from "react";
import "./planning.css";

export const Scenarios: React.FC = () => (
  <div className="planning-placeholder">
    <div className="planning-placeholder__phase">Planning · Phase 5 (biggest lift)</div>
    <h2 className="planning-placeholder__title">Scenarios</h2>
    <p className="planning-placeholder__body">
      What-if simulation. Drop a hypothetical route on the map, set frequency, and watch the
      coverage / equity / demand metrics recompute against the existing network. The only sub-page
      that requires new backend work: a <code>scenarios</code> table, synthetic GTFS isochrone
      computation, and a delta-vs-baseline service.
    </p>
    <ul className="planning-placeholder__features">
      <li>Pin-on-map scenario editor with stop and frequency controls</li>
      <li>Live delta KPIs: residents reached, equity-need served, demand match %</li>
      <li>Save / share scenarios via URL (persisted server-side)</li>
      <li>Side-by-side comparison of multiple scenarios</li>
    </ul>
  </div>
);

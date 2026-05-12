import React from "react";
import "./planning.css";

export const Workbench: React.FC = () => (
  <div className="planning-placeholder">
    <div className="planning-placeholder__phase">Planning · Phase 4</div>
    <h2 className="planning-placeholder__title">Workbench</h2>
    <p className="planning-placeholder__body">
      Click-to-inspect surface. Reshapes the existing rider trip planner into a service planner
      tool: click a corridor on the map to see its demand profile, current service level, and
      ranked suggestions for service additions.
    </p>
    <ul className="planning-placeholder__features">
      <li>Map click → corridor demand + current frequency side panel</li>
      <li>"Suggest service" ranking based on demand vs current supply</li>
      <li>Underserved zones panel (replaces today's itinerary panel)</li>
      <li>Stop-level demand breakdown for the selected corridor</li>
    </ul>
  </div>
);

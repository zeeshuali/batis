import React from "react";
import "./planning.css";

export const Coverage: React.FC = () => (
  <div className="planning-placeholder">
    <div className="planning-placeholder__phase">Planning · Phase 2 (next)</div>
    <h2 className="planning-placeholder__title">Coverage</h2>
    <p className="planning-placeholder__body">
      City and municipal planners ask "where does our city lack transit it doesn't already have?".
      This page will compose <code>/coverage/cells</code>, <code>/coverage/deserts</code>, and{" "}
      <code>/equity/score</code> into a planner-shaped view of underserved population.
    </p>
    <ul className="planning-placeholder__features">
      <li>Transit deserts ranked by population × equity-need score</li>
      <li>Coverage by census tract and supervisorial / council district</li>
      <li>Stop accessibility map (ADA gaps, shelter, lighting)</li>
      <li>"Underserved jobs/housing access" — TOD alignment view</li>
    </ul>
  </div>
);

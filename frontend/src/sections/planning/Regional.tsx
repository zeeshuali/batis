import React from "react";
import "./planning.css";

export const Regional: React.FC = () => (
  <div className="planning-placeholder">
    <div className="planning-placeholder__phase">Planning · Phase 3</div>
    <h2 className="planning-placeholder__title">Regional</h2>
    <p className="planning-placeholder__body">
      For MPO and regional planners (MTC, etc.) coordinating across the 30+ Bay Area agencies.
      Composes <code>/benchmarks/agency-otp</code>, a new <code>/regional/transfer-points</code>{" "}
      endpoint, and the agencies catalog rollups.
    </p>
    <ul className="planning-placeholder__features">
      <li>Cross-agency OTP leaderboard with quarter-over-quarter drift</li>
      <li>Transfer-point reliability ranked by daily transfer volume</li>
      <li>Modal-share donut (bus vs rail vs ferry vs multi-modal)</li>
      <li>County-level coverage rollup for the RTP investment cycle</li>
    </ul>
  </div>
);

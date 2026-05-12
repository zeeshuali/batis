import React from "react";
import "./primitives.css";

export interface KpiCardProps {
  label: string;
  value: string;
  sub?: string;
  /** Numeric change vs previous period. Renders sign + 1 decimal place. */
  delta?: number;
  /** Caller's verdict on whether the delta represents an improvement.
   *  `deltaIsGood: true` renders the delta in the success color; `false`
   *  in the critical color. The component does not infer polarity from the
   *  sign of `delta` — callers know their metric's direction (delay falling
   *  is good; OTP rising is good) and pass the right flag. */
  deltaIsGood?: boolean;
}

export const KpiCard: React.FC<KpiCardProps> = ({ label, value, sub, delta, deltaIsGood = true }) => {
  let deltaCls = "";
  if (delta !== undefined) {
    deltaCls = deltaIsGood ? "kpi-card__delta--good" : "kpi-card__delta--bad";
  }
  return (
    <div className="kpi-card">
      <span className="kpi-card__value">{value}</span>
      <span className="kpi-card__label">{label}</span>
      {sub && <span className="kpi-card__sub">{sub}</span>}
      {delta !== undefined && (
        <span className={`kpi-card__delta ${deltaCls}`}>
          {delta >= 0 ? "+" : ""}{delta.toFixed(1)}
        </span>
      )}
    </div>
  );
};

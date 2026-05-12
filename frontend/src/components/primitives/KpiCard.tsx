import React from "react";
import "./primitives.css";

export interface KpiCardProps {
  label: string;
  value: string;
  sub?: string;
  /** Numeric change vs previous period. Renders sign + 1 decimal place. */
  delta?: number;
  /** When true a positive delta is rendered "good" (green); when false it's bad.
   *  Useful because some metrics improve as they fall (delay) and some as they rise (OTP). */
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

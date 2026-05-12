import React from "react";
import { MapView } from "./MapView";
import { useTheme } from "../context/ThemeContext";
import type { Section } from "../types";
import "../sections/sections.css";

export interface SectionMapProps {
  mapMode: Section;
  title?: string;
  /** Default 420px — sized for a card inside a section's grid. */
  height?: number;
  /** If set, MapView narrows the stop / vehicle layers to this agency
   *  and fits the viewport to its stops. Used by the Agency drill-down. */
  agencyFilter?: string | null;
}

export const SectionMap: React.FC<SectionMapProps> = ({ mapMode, title, height = 420, agencyFilter }) => {
  const { theme } = useTheme();
  return (
    <div className="section__panel section__panel--map" style={{ height }}>
      {title && <h3 className="section__panel-title">{title}</h3>}
      <div className="section__map-container">
        <MapView mapMode={mapMode} darkMode={theme === "dark"} agencyFilter={agencyFilter} />
      </div>
    </div>
  );
};

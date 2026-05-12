import React, { useEffect, useState } from "react";
import { useSelection } from "../context/SelectionContext";
import type { LatLng } from "../types";
import { api } from "../lib/api";
import { Spinner, EmptyState } from "./primitives";
import "../sections/sections.css";

interface Leg {
  route_short_name?: string;
  route_id?: string;
  from_stop?: string;
  to_stop?: string;
  duration_minutes: number;
}
interface Itinerary {
  legs: Leg[];
  total_duration_minutes: number;
  transfers: number;
}

export const PlannerPanel: React.FC = () => {
  const { selection, resetPlanner } = useSelection();
  const [itin, setItin] = useState<Itinerary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const o: LatLng | null = selection.plannerOrigin;
  const d: LatLng | null = selection.plannerDest;

  useEffect(() => {
    if (!o || !d) { setItin(null); return; }
    let cancelled = false;
    async function fetchTrip() {
      setLoading(true); setError(null);
      try {
        const res = await api.get<Itinerary>("/trip-planner", {
          params: { from_lat: o!.lat, from_lng: o!.lng, to_lat: d!.lat, to_lng: d!.lng },
        });
        if (!cancelled) setItin(res.data);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to plan trip");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchTrip();
    return () => { cancelled = true; };
  }, [o, d]);

  if (!o) {
    return (
      <div className="section__panel">
        <h3 className="section__panel-title">Trip planner</h3>
        <EmptyState message="Click the map to set an origin." hint="Then click again to pick a destination." />
      </div>
    );
  }

  if (!d) {
    return (
      <div className="section__panel">
        <h3 className="section__panel-title">Trip planner</h3>
        <EmptyState message="Origin set. Click the map again for a destination." />
        <button className="export-button" onClick={resetPlanner}>Reset</button>
      </div>
    );
  }

  return (
    <div className="section__panel">
      <h3 className="section__panel-title">Trip planner</h3>
      {loading && <Spinner />}
      {error && <p className="section-error__msg">{error}</p>}
      {itin && (
        <>
          <p>Total duration: <strong>{itin.total_duration_minutes}m</strong> · transfers: {itin.transfers}</p>
          <ul className="data-list">
            {itin.legs.map((leg, i) => (
              <li key={i} className="data-list__li">
                <div className="data-list__row" style={{ pointerEvents: "none" }}>
                  <span className="data-list__primary">{leg.route_short_name ?? leg.route_id ?? "Walk"}</span>
                  <span className="data-list__secondary">{leg.from_stop} → {leg.to_stop}</span>
                  <span className="data-list__trailing">{leg.duration_minutes} min</span>
                </div>
              </li>
            ))}
          </ul>
          <button className="export-button" onClick={resetPlanner}>Reset</button>
        </>
      )}
    </div>
  );
};

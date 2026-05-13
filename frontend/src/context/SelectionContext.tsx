import React, { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import type { LatLng } from "../types";

export interface Selection {
  routeId:        string | null;
  stopId:         string | null;
  hoveredStopId:  string | null;
  plannerOrigin:  LatLng | null;
  plannerDest:    LatLng | null;
  /** Inspection point for the Planning → Workbench sub-page.
   *  Set by clicking the map when activeSection === "workbench". */
  workbenchPoint: LatLng | null;
  /** Hypothetical-stop list for the Planning → Scenarios builder.  Each
   *  click in scenarios mode appends a point. The editor persists the
   *  list to /scenarios when the user hits Save. */
  scenarioStops: LatLng[];
  /** Corridor endpoints for the Planning → Fares sub-page.  Click 1 sets
   *  origin, click 2 sets destination, click 3+ replaces origin (keeps
   *  destination since planners usually hold it steady while exploring
   *  origins). */
  faresOrigin:      LatLng | null;
  faresDestination: LatLng | null;
}

interface SelectionApi {
  selection: Selection;
  setRouteId:         (id: string | null) => void;
  setStopId:          (id: string | null) => void;
  setHoveredStopId:   (id: string | null) => void;
  setPlannerOrigin:   (p: LatLng | null) => void;
  setPlannerDest:     (p: LatLng | null) => void;
  setWorkbenchPoint:  (p: LatLng | null) => void;
  addScenarioStop:    (p: LatLng) => void;
  removeScenarioStop: (index: number) => void;
  setScenarioStops:   (stops: LatLng[]) => void;
  /** Cycles through the {origin, destination, replace-origin} state on
   *  each call.  The "Clear pins" button uses clearFaresPins() to reset
   *  to state 0. */
  setFaresPin:        (p: LatLng) => void;
  clearFaresPins:     () => void;
  resetPlanner:       () => void;
  clear: () => void;
}

const SelectionContext = createContext<SelectionApi | null>(null);

export const SelectionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [routeId,        setRouteIdState]        = useState<string | null>(null);
  const [stopId,         setStopIdState]         = useState<string | null>(null);
  const [hoveredStopId,  setHoveredStopIdState]  = useState<string | null>(null);
  const [plannerOrigin,  setPlannerOriginState]  = useState<LatLng | null>(null);
  const [plannerDest,    setPlannerDestState]    = useState<LatLng | null>(null);
  const [workbenchPoint, setWorkbenchPointState] = useState<LatLng | null>(null);
  const [scenarioStops,  setScenarioStopsState]  = useState<LatLng[]>([]);
  const [faresOrigin,      setFaresOriginState]      = useState<LatLng | null>(null);
  const [faresDestination, setFaresDestinationState] = useState<LatLng | null>(null);

  const setRouteId        = useCallback((id: string | null) => setRouteIdState(id), []);
  const setStopId         = useCallback((id: string | null) => setStopIdState(id), []);
  const setHoveredStopId  = useCallback((id: string | null) => setHoveredStopIdState(id), []);
  const setPlannerOrigin  = useCallback((p: LatLng | null) => setPlannerOriginState(p), []);
  const setPlannerDest    = useCallback((p: LatLng | null) => setPlannerDestState(p), []);
  const setWorkbenchPoint = useCallback((p: LatLng | null) => setWorkbenchPointState(p), []);
  const setScenarioStops  = useCallback((stops: LatLng[]) => setScenarioStopsState(stops), []);
  const addScenarioStop   = useCallback((p: LatLng) =>
    setScenarioStopsState(prev => [...prev, p]), []);
  const removeScenarioStop = useCallback((index: number) =>
    setScenarioStopsState(prev => prev.filter((_, i) => i !== index)), []);
  // Refs mirror the latest state so setFaresPin's cycle logic reads
  // consistent values without setter-inside-setter gymnastics.
  const faresOriginRef = useRef<LatLng | null>(null);
  const faresDestRef   = useRef<LatLng | null>(null);
  faresOriginRef.current = faresOrigin;
  faresDestRef.current   = faresDestination;
  // Fares-pin cycle:
  //   state 0 (both null)        → click sets origin       → state 1
  //   state 1 (origin only)      → click sets destination  → state 2
  //   state 2 (both set)         → click replaces origin   → state 1
  // Destination is preserved on the cycle because planners usually hold
  // it steady while exploring origins.  "Clear pins" resets to state 0.
  const setFaresPin = useCallback((p: LatLng) => {
    if (faresOriginRef.current === null) {
      faresOriginRef.current = p;           // sync ref so back-to-back calls
      setFaresOriginState(p);               //   see the post-update state
    } else if (faresDestRef.current === null) {
      faresDestRef.current = p;
      setFaresDestinationState(p);
    } else {
      faresOriginRef.current = p;           // 2 → 1 (destination retained)
      setFaresOriginState(p);
    }
  }, []);
  const clearFaresPins = useCallback(() => {
    faresOriginRef.current = null;
    faresDestRef.current   = null;
    setFaresOriginState(null);
    setFaresDestinationState(null);
  }, []);
  const resetPlanner = useCallback(() => {
    setPlannerOriginState(null);
    setPlannerDestState(null);
  }, []);
  const clear = useCallback(() => {
    setRouteIdState(null);
    setStopIdState(null);
    setHoveredStopIdState(null);
    setPlannerOriginState(null);
    setPlannerDestState(null);
    setWorkbenchPointState(null);
    setScenarioStopsState([]);
    setFaresOriginState(null);
    setFaresDestinationState(null);
  }, []);

  const value = useMemo<SelectionApi>(
    () => ({
      selection: { routeId, stopId, hoveredStopId, plannerOrigin, plannerDest, workbenchPoint, scenarioStops, faresOrigin, faresDestination },
      setRouteId,
      setStopId,
      setHoveredStopId,
      setPlannerOrigin,
      setPlannerDest,
      setWorkbenchPoint,
      addScenarioStop,
      removeScenarioStop,
      setScenarioStops,
      setFaresPin,
      clearFaresPins,
      resetPlanner,
      clear,
    }),
    [routeId, stopId, hoveredStopId, plannerOrigin, plannerDest, workbenchPoint, scenarioStops, faresOrigin, faresDestination, setRouteId, setStopId, setHoveredStopId, setPlannerOrigin, setPlannerDest, setWorkbenchPoint, addScenarioStop, removeScenarioStop, setScenarioStops, setFaresPin, clearFaresPins, resetPlanner, clear]
  );

  return <SelectionContext.Provider value={value}>{children}</SelectionContext.Provider>;
};

export function useSelection(): SelectionApi {
  const v = useContext(SelectionContext);
  if (!v) throw new Error("useSelection must be used inside a SelectionProvider");
  return v;
}

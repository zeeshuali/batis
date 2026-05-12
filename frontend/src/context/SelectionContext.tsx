import React, { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { LatLng } from "../types";

export interface Selection {
  routeId:        string | null;
  stopId:         string | null;
  hoveredStopId:  string | null;
  plannerOrigin:  LatLng | null;
  plannerDest:    LatLng | null;
}

interface SelectionApi {
  selection: Selection;
  setRouteId:        (id: string | null) => void;
  setStopId:         (id: string | null) => void;
  setHoveredStopId:  (id: string | null) => void;
  setPlannerOrigin:  (p: LatLng | null) => void;
  setPlannerDest:    (p: LatLng | null) => void;
  resetPlanner:      () => void;
  clear: () => void;
}

const SelectionContext = createContext<SelectionApi | null>(null);

export const SelectionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [routeId,       setRouteIdState]       = useState<string | null>(null);
  const [stopId,        setStopIdState]        = useState<string | null>(null);
  const [hoveredStopId, setHoveredStopIdState] = useState<string | null>(null);
  const [plannerOrigin, setPlannerOriginState] = useState<LatLng | null>(null);
  const [plannerDest,   setPlannerDestState]   = useState<LatLng | null>(null);

  const setRouteId       = useCallback((id: string | null) => setRouteIdState(id), []);
  const setStopId        = useCallback((id: string | null) => setStopIdState(id), []);
  const setHoveredStopId = useCallback((id: string | null) => setHoveredStopIdState(id), []);
  const setPlannerOrigin = useCallback((p: LatLng | null) => setPlannerOriginState(p), []);
  const setPlannerDest   = useCallback((p: LatLng | null) => setPlannerDestState(p), []);
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
  }, []);

  const value = useMemo<SelectionApi>(
    () => ({
      selection: { routeId, stopId, hoveredStopId, plannerOrigin, plannerDest },
      setRouteId,
      setStopId,
      setHoveredStopId,
      setPlannerOrigin,
      setPlannerDest,
      resetPlanner,
      clear,
    }),
    [routeId, stopId, hoveredStopId, plannerOrigin, plannerDest, setRouteId, setStopId, setHoveredStopId, setPlannerOrigin, setPlannerDest, resetPlanner, clear]
  );

  return <SelectionContext.Provider value={value}>{children}</SelectionContext.Provider>;
};

export function useSelection(): SelectionApi {
  const v = useContext(SelectionContext);
  if (!v) throw new Error("useSelection must be used inside a SelectionProvider");
  return v;
}

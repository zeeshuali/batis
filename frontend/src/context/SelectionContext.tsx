import React, { createContext, useCallback, useContext, useMemo, useState } from "react";

export interface Selection {
  routeId:        string | null;
  stopId:         string | null;
  hoveredStopId:  string | null;
}

interface SelectionApi {
  selection: Selection;
  setRouteId:        (id: string | null) => void;
  setStopId:         (id: string | null) => void;
  setHoveredStopId:  (id: string | null) => void;
  clear: () => void;
}

const SelectionContext = createContext<SelectionApi | null>(null);

export const SelectionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [routeId,       setRouteIdState]       = useState<string | null>(null);
  const [stopId,        setStopIdState]        = useState<string | null>(null);
  const [hoveredStopId, setHoveredStopIdState] = useState<string | null>(null);

  const setRouteId       = useCallback((id: string | null) => setRouteIdState(id), []);
  const setStopId        = useCallback((id: string | null) => setStopIdState(id), []);
  const setHoveredStopId = useCallback((id: string | null) => setHoveredStopIdState(id), []);
  const clear = useCallback(() => {
    setRouteIdState(null);
    setStopIdState(null);
    setHoveredStopIdState(null);
  }, []);

  const value = useMemo<SelectionApi>(
    () => ({ selection: { routeId, stopId, hoveredStopId }, setRouteId, setStopId, setHoveredStopId, clear }),
    [routeId, stopId, hoveredStopId, setRouteId, setStopId, setHoveredStopId, clear]
  );

  return <SelectionContext.Provider value={value}>{children}</SelectionContext.Provider>;
};

export function useSelection(): SelectionApi {
  const v = useContext(SelectionContext);
  if (!v) throw new Error("useSelection must be used inside a SelectionProvider");
  return v;
}

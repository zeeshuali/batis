/** Legacy types shared by the pre-Plan-1a components (MapView, Sidebar) that
 *  are still on disk but no longer rendered by the new shell. Plan 1b will
 *  either rewrite those consumers or delete this file. New components should
 *  use the BATIS 2.0 contexts (FilterContext, SelectionContext) instead.
 */

export interface LatLng {
  lat: number;
  lng: number;
}

/** The legacy 14-tab section union. The new shell uses `SectionKey` in
 *  `components/AppShell.tsx` instead. This stays only so the unmounted
 *  legacy files keep type-checking until Plan 1b folds them in.
 */
export type Section =
  | "reliability"
  | "crowding"
  | "safety"
  | "coverage"
  | "demand"
  | "routes"
  | "bunching"
  | "vehicles"
  | "comparison"
  | "planner"
  | "ai"
  | "benchmarks"
  | "traffic"
  | "equity"
  | "workbench"
  | "scenarios"
  | "fares"
  | "fare-burden"
  | "service-delivery-gap";

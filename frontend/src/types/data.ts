/** Shared backend response types. The sections each import the rows they
 *  consume. Field names track the actual /backend/app/main.py endpoints —
 *  any drift between these and the API is a bug worth fixing here, not in
 *  individual sections.
 */

export interface ReliabilityRow {
  route_id: string;
  /** Added in Phase 3 — /reliability/summary now GROUPs by
   *  (agency_id, route_id) so each row carries its agency. Optional
   *  to keep legacy clients/mock data happy. */
  agency_id?: string;
  sample_events: number;
  avg_delay_seconds: number;
  on_time_pct?: number;
}

export interface TrendRow {
  /** /reliability/trend uses `date`; older mock data may use `service_date`. */
  date?: string;
  service_date?: string;
  avg_delay: number | null;
}

export interface SafetyRow {
  stop_id: string;
  stop_name?: string;
  safety_score: number;
  crime_incidents_nearby?: number;
  collisions_nearby?: number;
}

export interface BunchingRow {
  route_id: string;
  event_count: number;
  late_events?: number;
  avg_delay_seconds?: number;
}

/** /vehicles/live is a GeoJSON FeatureCollection, not a flat array. */
export interface VehicleFC {
  type: "FeatureCollection";
  features: unknown[];
}

export interface AgencyOtpRow {
  agency_id: string;
  on_time_pct: number;
  avg_delay_seconds: number;
  sample_events: number;
}

export interface RouteRow {
  route_id: string;
  route_short_name?: string;
  agency_id?: string;
}

export interface CrowdingRow {
  route_id: string;
  trip_id: string | null;
  stop_id: string | null;
  service_date: string;
  time_bucket: string;
  crowding_level: "low" | "medium" | "high" | "unknown";
  model_version: string | null;
}

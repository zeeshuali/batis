/**
 * Agency identity helpers.
 *
 * The authoritative agency catalog now lives in the backend `agencies`
 * table and is fetched into the app via `AgenciesContext`. This module
 * provides the colour/name helpers that consumers use to render that
 * data — both for known agencies (BRAND_COLORS) and for any 511.org
 * operator the backend may discover later (hash-based fallback).
 */

/** Hand-curated brand colours for the most visible Bay Area operators. */
export const BRAND_COLORS: Record<string, string> = {
  AC: "#FFD700", // AC Transit
  BA: "#0099CC", // BART
  SF: "#BF2B45", // Muni / SFMTA
  CT: "#DB4026", // Caltrain
  SM: "#005DAA", // SamTrans
  GG: "#FFA500", // Golden Gate
  WH: "#006DB6", // WETA Ferry
  VN: "#4CAF50", // VTA
};

export interface AgencyMeta {
  agency_id: string;
  agency_name: string;
  agency_type?: string | null;
  monitored?: boolean | null;
  agency_url?: string | null;
  agency_phone?: string | null;
}

/** Deterministic 32-bit djb2 hash of a string — stable across reloads. */
function hash(str: string): number {
  let h = 5381;
  for (let i = 0; i < str.length; i++) {
    h = ((h << 5) + h + str.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

/** Return a stable colour for an agency id.
 *  Brand colour if known, otherwise an HSL derived from a hash of the id. */
export function agencyColor(id: string | null | undefined): string {
  if (!id) return "#888888";
  const brand = BRAND_COLORS[id];
  if (brand) return brand;
  const hue = hash(id) % 360;
  return `hsl(${hue}, 55%, 55%)`;
}

/** Look up an agency's display name. Pass `agencies` (from useAgencies)
 *  for the catalog lookup; falls back to the id literal if absent. */
export function agencyName(
  id: string | null | undefined,
  agencies?: ReadonlyArray<AgencyMeta> | Record<string, AgencyMeta>,
): string {
  if (!id) return "Unknown";
  if (agencies) {
    const meta = Array.isArray(agencies)
      ? agencies.find(a => a.agency_id === id)
      : (agencies as Record<string, AgencyMeta>)[id];
    if (meta?.agency_name) return meta.agency_name;
  }
  return LEGACY_NAMES[id] ?? id;
}

/** Fallback names used when no catalog is available (tests, early render). */
const LEGACY_NAMES: Record<string, string> = {
  AC: "AC Transit",
  BA: "BART",
  SF: "Muni",
  CT: "Caltrain",
  SM: "SamTrans",
  GG: "Golden Gate",
  WH: "Ferry WETA",
  VN: "VTA",
};


export interface Agency {
  id: string;
  name: string;
  color: string;
}

export const AGENCY_LIST: Agency[] = [
  { id: "AC", name: "AC Transit",  color: "#FFD700" },
  { id: "BA", name: "BART",        color: "#0099CC" },
  { id: "SF", name: "Muni",        color: "#BF2B45" },
  { id: "CT", name: "Caltrain",    color: "#DB4026" },
  { id: "SM", name: "SamTrans",    color: "#005DAA" },
  { id: "GG", name: "Golden Gate", color: "#FFA500" },
  { id: "WH", name: "Ferry WETA",  color: "#006DB6" },
  { id: "VN", name: "VTA",         color: "#4CAF50" },
];

export const ALL_AGENCY_IDS: string[] = AGENCY_LIST.map(a => a.id);

export function agencyColor(id: string | null | undefined): string {
  return AGENCY_LIST.find(a => a.id === id)?.color ?? "#888888";
}

export function agencyName(id: string | null | undefined): string {
  return AGENCY_LIST.find(a => a.id === id)?.name ?? (id ?? "Unknown");
}

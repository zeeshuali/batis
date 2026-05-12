/** Format a duration in seconds as a short human string.
 *  < 60s → "Ns"; >= 60s → "M.M min".
 */
export function fmtMin(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const s = Number(seconds);
  if (!isFinite(s)) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  return `${(s / 60).toFixed(1)} min`;
}

/** Format a percentage value (0–100) with one decimal place; null → "—". */
export function fmtPct(value: number | null | undefined): string {
  if (value == null || !isFinite(Number(value))) return "—";
  return `${Number(value).toFixed(1)}%`;
}

/** Format a signed delta with sign + one decimal. */
export function fmtDelta(value: number | null | undefined): string {
  if (value == null || !isFinite(Number(value))) return "—";
  const v = Number(value);
  return v >= 0 ? `+${v.toFixed(1)}` : v.toFixed(1);
}

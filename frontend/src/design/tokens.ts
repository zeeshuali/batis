/** Typed mirror of CSS tokens. Use when a component needs a token at
 *  the JS layer (e.g. inline style props, Recharts color props).
 *  CSS files should use the CSS custom properties directly.
 */

export const space = {
  s1: "0.25rem",
  s2: "0.5rem",
  s3: "0.75rem",
  s4: "1rem",
  s5: "1.5rem",
  s6: "2rem",
  s8: "3rem",
} as const;

export const radius = {
  r1: 4,
  r2: 8,
  r3: 12,
  pill: 999,
} as const;

export const text = {
  xs: "0.75rem",
  sm: "0.875rem",
  base: "1rem",
  lg: "1.125rem",
  xl: "1.25rem",
  xl2: "1.5rem",
  xl3: "1.875rem",
} as const;

/** Semantic color names. Maps to CSS variables; use `var(--color-fg-1)` in
 *  CSS and these constants in JS-driven contexts. Values are dark-theme
 *  defaults; CSS variable lookup is preferred for theme-aware reads.
 */
export const semanticColors = {
  brand:     "#3b82f6",
  success:   "#22c55e",
  warn:      "#f59e0b",
  critical:  "#ef4444",
  info:      "#06b6d4",
  fg0:       "#f1f5f9",
  fg1:       "#cbd5e1",
  fg2:       "#94a3b8",
  fg3:       "#64748b",
  bg0:       "#0b0f17",
  bg1:       "#111826",
  bg2:       "#1a2334",
} as const;

export type SemanticColor = keyof typeof semanticColors;

"""Service Delivery Gap — per-cell scheduled-vs-observed trip
completion over a trailing 12-month window.

See docs/superpowers/specs/2026-05-12-sprint-5b-design.md.
"""
from __future__ import annotations

from typing import Any, Optional


def _gap_tier(pct: Optional[float]) -> Optional[str]:
    """Map gap_pct to a 4-tier label.  None when pct is None.

    Tier bands derive from FTA's "OTP ≥ 95%" benchmark:
      <2     low         — well within tolerance
      2–5    moderate    — below benchmark, not yet a problem
      5–10   high        — operationally problematic
      ≥10    very_high   — a real service-delivery failure
    """
    if pct is None:
        return None
    if pct >= 10: return "very_high"
    if pct >= 5:  return "high"
    if pct >= 2:  return "moderate"
    return "low"

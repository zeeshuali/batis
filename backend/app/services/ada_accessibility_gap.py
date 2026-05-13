"""ADA Accessibility Gap — per-stop scoring of supply_penalty
(wheelchair_boarding + Pathways override) × demand (areal-
interpolated ACS B18105 ambulatory pop in 400m catchment).

See docs/superpowers/specs/2026-05-13-sprint-5c-design.md.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection


logger = logging.getLogger(__name__)


def _supply_penalty(
    wheelchair_boarding: Optional[int],
    has_accessible_pathway: Optional[bool],
    location_type: Optional[int],
) -> float:
    """Map wheelchair_boarding + Pathways-override to penalty in [0, 1].

      wheelchair_boarding = 1 (accessible)        → 0.0
      wheelchair_boarding = 0 / None (unknown)    → 0.5
      wheelchair_boarding = 2 (not accessible)    → 1.0

    Pathways override (rail stations only — location_type in {1, 2}):
      has_accessible_pathway is False
        → 1.0 (regardless of wheelchair_boarding)

    has_accessible_pathway = None means "no pathways data for this
    stop" — do not override; fall through to wheelchair_boarding.
    """
    if location_type in (1, 2) and has_accessible_pathway is False:
        return 1.0
    if wheelchair_boarding == 1:
        return 0.0
    if wheelchair_boarding == 2:
        return 1.0
    return 0.5


def _gap_tier(score: float, *, p90: float, p75: float, p50: float) -> str:
    """Percentile-banded tier label.

    Stops with score == 0 always return 'low' (already accessible —
    no investment need regardless of demand).
    """
    if score <= 0:
        return "low"
    if score >= p90:
        return "very_high"
    if score >= p75:
        return "high"
    if score >= p50:
        return "moderate"
    return "low"

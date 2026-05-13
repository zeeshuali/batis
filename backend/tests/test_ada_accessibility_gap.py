import pytest

from app.services.ada_accessibility_gap import _gap_tier, _supply_penalty


# ── _supply_penalty ──────────────────────────────────────────────────────────

def test_supply_penalty_accessible():
    # wheelchair_boarding=1 means accessible → 0.0 (regardless of pathways)
    assert _supply_penalty(1, has_accessible_pathway=True, location_type=0) == 0.0
    assert _supply_penalty(1, has_accessible_pathway=None, location_type=1) == 0.0


def test_supply_penalty_not_accessible():
    # wheelchair_boarding=2 means not accessible → 1.0
    assert _supply_penalty(2, has_accessible_pathway=True, location_type=0) == 1.0


def test_supply_penalty_unknown():
    # wheelchair_boarding=0 / None means unknown → 0.5
    assert _supply_penalty(0, has_accessible_pathway=None, location_type=0) == 0.5
    assert _supply_penalty(None, has_accessible_pathway=None, location_type=0) == 0.5


def test_supply_penalty_pathways_override_rail_only():
    # Rail station with explicit pathways data, no accessible path:
    # override to 1.0 regardless of wheelchair_boarding.
    assert _supply_penalty(1, has_accessible_pathway=False, location_type=1) == 1.0
    assert _supply_penalty(1, has_accessible_pathway=False, location_type=2) == 1.0
    # Bus stop with the same flag should NOT override.
    assert _supply_penalty(1, has_accessible_pathway=False, location_type=0) == 0.0


def test_supply_penalty_pathways_override_only_when_explicit_false():
    # has_accessible_pathway = None means "no pathways data for this stop"
    # — do not override; fall through to wheelchair_boarding.
    assert _supply_penalty(1, has_accessible_pathway=None, location_type=1) == 0.0
    assert _supply_penalty(2, has_accessible_pathway=None, location_type=1) == 1.0


# ── _gap_tier ────────────────────────────────────────────────────────────────

def test_gap_tier_zero_is_low():
    # Already-accessible stops have gap_score = 0; always 'low'.
    assert _gap_tier(0.0, p90=100, p75=50, p50=20) == "low"


def test_gap_tier_percentile_bands():
    # gap_score >= p90 → very_high
    assert _gap_tier(150.0, p90=100, p75=50, p50=20) == "very_high"
    # p75 <= gap_score < p90 → high
    assert _gap_tier(75.0,  p90=100, p75=50, p50=20) == "high"
    # p50 <= gap_score < p75 → moderate
    assert _gap_tier(30.0,  p90=100, p75=50, p50=20) == "moderate"
    # gap_score < p50 → low
    assert _gap_tier(5.0,   p90=100, p75=50, p50=20) == "low"


def test_gap_tier_boundaries_inclusive_at_lower_edge():
    # Exactly at p90 → very_high (>=)
    assert _gap_tier(100.0, p90=100, p75=50, p50=20) == "very_high"
    assert _gap_tier(50.0,  p90=100, p75=50, p50=20) == "high"
    assert _gap_tier(20.0,  p90=100, p75=50, p50=20) == "moderate"

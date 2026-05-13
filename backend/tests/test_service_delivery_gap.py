"""Tests for backend/app/services/service_delivery_gap.py."""
import pytest

from app.services.service_delivery_gap import _gap_tier


@pytest.mark.parametrize("pct,expected", [
    (None,  None),
    (0.0,   "low"),
    (1.99,  "low"),
    (2.0,   "moderate"),
    (4.99,  "moderate"),
    (5.0,   "high"),
    (9.99,  "high"),
    (10.0,  "very_high"),
    (50.0,  "very_high"),
])
def test_gap_tier_bands(pct, expected):
    assert _gap_tier(pct) == expected

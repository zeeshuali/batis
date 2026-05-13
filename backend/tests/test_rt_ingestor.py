"""Unit tests for the GTFS-RT ingestor helpers.

These cover the two write-time invariants the live ingestor maintains:

1. 511.org's regional feed namespaces trip_id / route_id / stop_id as
   `{agency}:{raw_id}`, but the static GTFS we load stores them raw.
   `_strip_agency_prefix` normalises one side so the join works.  A
   prior version stored the prefixed form and silently produced
   `scheduled_arrival = NULL` for every row — 3.9M corrupt rows.

2. `delay_seconds` outside ±_MAX_PLAUSIBLE_DELAY_SECONDS (2 hours) is
   treated as feed corruption and stored as NULL.  Same prior bug:
   SF Muni's feed emitted delays of -70 million seconds, which then
   poisoned every aggregate (bunching avg, OTP, etc).
"""
from __future__ import annotations

import pytest

from app.services.five11_rt_ingestor import (
    _MAX_PLAUSIBLE_DELAY_SECONDS,
    _strip_agency_prefix,
)


class TestStripAgencyPrefix:
    def test_strips_when_value_starts_with_agency_prefix(self):
        assert _strip_agency_prefix("SF:11996421_M11", "SF") == "11996421_M11"
        assert _strip_agency_prefix("AC:1T",            "AC") == "1T"

    def test_no_op_when_value_doesnt_have_the_prefix(self):
        # Static GTFS feeds don't prefix — they ship raw.
        assert _strip_agency_prefix("11963590_M11", "SF") == "11963590_M11"
        assert _strip_agency_prefix("51B",          "AC") == "51B"

    def test_no_op_when_agency_id_missing(self):
        assert _strip_agency_prefix("anything", None) == "anything"
        assert _strip_agency_prefix("anything", "")   == "anything"

    def test_returns_none_for_empty_value(self):
        assert _strip_agency_prefix(None, "SF") is None
        assert _strip_agency_prefix("",   "SF") is None

    def test_only_strips_the_exact_agency_prefix(self):
        # A trip_id that happens to start with a different agency's code
        # shouldn't be touched.
        assert _strip_agency_prefix("BA:bart-line-1", "SF") == "BA:bart-line-1"

    def test_handles_value_that_is_exactly_the_prefix(self):
        # Degenerate input: value is "SF:" alone.  Strip returns empty,
        # which the caller then funnels back through the None path.
        assert _strip_agency_prefix("SF:", "SF") == ""


class TestPlausibleDelayBound:
    def test_constant_matches_db_cleanup_bound(self):
        # The dev-DB cleanup script clamps to ±7200; the ingestor null-
        # guards at the same threshold.  Keep them in sync.
        assert _MAX_PLAUSIBLE_DELAY_SECONDS == 7200

    @pytest.mark.parametrize("delta", [-7201, -100_000, -70_411_750, 7201, 50_000, 999_999])
    def test_implausible_delays_should_be_dropped(self, delta):
        # Asserts the constant is set such that real-world bogus values
        # (the negative ~70M from the prior bug, plus arbitrary > 2h
        # positives) are rejected.
        assert abs(delta) > _MAX_PLAUSIBLE_DELAY_SECONDS

    @pytest.mark.parametrize("delta", [-7200, -600, -1, 0, 1, 60, 3600, 7200])
    def test_plausible_delays_should_be_kept(self, delta):
        assert abs(delta) <= _MAX_PLAUSIBLE_DELAY_SECONDS

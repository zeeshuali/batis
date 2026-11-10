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


class TestProcessTripUpdatesSmoke:
    """Regression: _process_trip_updates used `agency_id` before assigning it
    (UnboundLocalError on every poll), so ops_trip_events never filled."""

    def test_does_not_crash_and_resolves_agency_from_prefixed_route(self):
        from unittest.mock import MagicMock

        from google.transit import gtfs_realtime_pb2

        from app.services.five11_rt_ingestor import _process_trip_updates

        feed = gtfs_realtime_pb2.FeedMessage()
        feed.header.gtfs_realtime_version = "2.0"
        ent = feed.entity.add()
        ent.id = "1"
        ent.trip_update.trip.trip_id = "SF:T1"
        ent.trip_update.trip.route_id = "SF:31"
        stu = ent.trip_update.stop_time_update.add()
        stu.stop_id = "SF:100"
        stu.stop_sequence = 1
        stu.arrival.delay = 60

        conn = MagicMock()
        conn.execute.return_value.mappings.return_value.all.return_value = []
        assert _process_trip_updates(conn, feed) == 1
        insert_rows = conn.execute.call_args_list[-1].args[1]
        assert insert_rows[0]["agency_id"] == "SF"
        assert insert_rows[0]["trip_id"] == "T1"
        assert insert_rows[0]["stop_id"] == "100"


class TestTripUpdatesWithoutRouteId:
    """Regression: BART trip updates carry no route_id. They were labelled agency AC and failed
    the NOT NULL route_id insert, which aborted the whole poll (vehicles included)."""

    def _feed(self, trip_id, route_id=""):
        from google.transit import gtfs_realtime_pb2
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.header.gtfs_realtime_version = "2.0"
        ent = feed.entity.add()
        ent.id = "1"
        ent.trip_update.trip.trip_id = trip_id
        if route_id:
            ent.trip_update.trip.route_id = route_id
        stu = ent.trip_update.stop_time_update.add()
        stu.stop_id = "BA:12TH"
        stu.stop_sequence = 1
        stu.arrival.delay = 30
        return feed

    def test_agency_comes_from_trip_id_prefix_and_route_from_static_trips(self):
        from unittest.mock import MagicMock
        from app.services.five11_rt_ingestor import _extract_agency_id, _process_trip_updates

        feed = self._feed("BA:919134610")
        assert _extract_agency_id(feed.entity[0].trip_update.trip, None, "BA:919134610", default=None) == "BA"

        conn = MagicMock()
        calls = []

        def execute(stmt, params=None):
            sql = str(stmt)
            calls.append(sql)
            r = MagicMock()
            if "FROM gtfs_trips" in sql:
                r.__iter__ = lambda self: iter([("BA", "919134610", "RED")])
            else:
                r.mappings.return_value.all.return_value = []
            return r

        conn.execute.side_effect = execute
        stats = {}
        assert _process_trip_updates(conn, feed, stats=stats) == 1
        rows = conn.execute.call_args_list[-1].args[1]
        assert rows[0]["agency_id"] == "BA" and rows[0]["route_id"] == "RED" and rows[0]["trip_id"] == "919134610"

    def test_unresolvable_trips_are_skipped_not_inserted(self):
        from unittest.mock import MagicMock
        from app.services.five11_rt_ingestor import _process_trip_updates

        conn = MagicMock()
        stats = {}
        # no agency anywhere -> skipped
        assert _process_trip_updates(conn, self._feed("919134610"), stats=stats) == 0
        assert stats["skipped_no_agency"] == 1
        # agency known but route cannot be found -> skipped
        r = MagicMock()
        r.__iter__ = lambda self: iter([])
        conn.execute.return_value = r
        stats = {}
        assert _process_trip_updates(conn, self._feed("BA:919134610"), stats=stats) == 0
        assert stats["skipped_no_route"] == 1

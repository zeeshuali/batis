"""Unit tests for the backfill_last_n_months helper.

We don't hit 511.org from the test suite — only check that the helper
forwards args to the existing load_missing_months and returns its
result unchanged.  An integration smoke-test against a single real
month is the responsibility of the operator after deploy."""
from unittest.mock import patch

from app.services.five11_stop_observations import backfill_last_n_months


def test_backfill_last_n_months_forwards_args():
    fake = {"2025-04": 100_000, "2025-05": 110_000}
    with patch(
        "app.services.five11_stop_observations.load_missing_months",
        return_value=fake,
    ) as m:
        result = backfill_last_n_months(conn=None, n=2)
    m.assert_called_once_with(None, months_back=2)
    assert result == fake


def test_backfill_last_n_months_default_n_is_12():
    with patch(
        "app.services.five11_stop_observations.load_missing_months",
        return_value={},
    ) as m:
        backfill_last_n_months(conn=None)
    m.assert_called_once_with(None, months_back=12)

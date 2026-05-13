from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.services.census_ambulatory_loader import load_b18105


_FAKE_TRACT_RESPONSE = [
    ["B18105_001E",
     "B18105_004E","B18105_007E","B18105_010E","B18105_013E","B18105_016E",
     "B18105_020E","B18105_023E","B18105_026E","B18105_029E","B18105_032E",
     "state","county","tract"],
    # total=4000, ambulatory bins sum: 5+10+25+40+30 + 5+12+30+50+40 = 247
    ["4000", "5","10","25","40","30",
             "5","12","30","50","40",
             "06","001","400100"],
]


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """pydantic-settings caches; clear between tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def cleanup_ambulatory(db_conn):
    try:
        yield
    finally:
        db_conn.execute(text(
            "DELETE FROM census_ambulatory WHERE tract_geoid = '06001400100'"
        ))
        db_conn.commit()


def _make_mock(payload):
    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self_inner): return payload
    return R()


def test_load_b18105_aggregates_bins(monkeypatch, db_conn, cleanup_ambulatory):
    monkeypatch.setenv("CENSUS_API_KEY", "test-key")
    get_settings.cache_clear()

    with patch("app.services.census_ambulatory_loader.requests.get") as mock_get:
        def fake_get(url, **kwargs):
            if "county:001" in url:
                return _make_mock(_FAKE_TRACT_RESPONSE)
            return _make_mock(_FAKE_TRACT_RESPONSE[:1])
        mock_get.side_effect = fake_get

        n = load_b18105(db_conn)
        db_conn.commit()

    assert n >= 1

    row = db_conn.execute(text(
        "SELECT tract_geoid, ambulatory_pop, total_pop "
        "FROM census_ambulatory WHERE tract_geoid = '06001400100'"
    )).fetchone()
    assert row is not None
    assert row[0] == "06001400100"
    assert row[1] == 247
    assert row[2] == 4000


def test_load_b18105_handles_negative_sentinels(monkeypatch, db_conn, cleanup_ambulatory):
    monkeypatch.setenv("CENSUS_API_KEY", "test-key")
    get_settings.cache_clear()

    bad = list(_FAKE_TRACT_RESPONSE)
    bad[1] = ["4000",
              "-666666666","10","25","40","30",
              "5","12","30","50","40",
              "06","001","400100"]

    with patch("app.services.census_ambulatory_loader.requests.get") as mock_get:
        def fake_get(url, **kwargs):
            if "county:001" in url:
                return _make_mock(bad)
            return _make_mock(bad[:1])
        mock_get.side_effect = fake_get

        n = load_b18105(db_conn)
        db_conn.commit()

    assert n >= 1

    row = db_conn.execute(text(
        "SELECT ambulatory_pop FROM census_ambulatory "
        "WHERE tract_geoid = '06001400100'"
    )).fetchone()
    assert row is not None
    # Negative sentinel treated as 0; total = 0+10+25+40+30+5+12+30+50+40 = 242
    assert row[0] == 242

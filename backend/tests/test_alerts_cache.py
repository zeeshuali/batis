"""/alerts must not hit 511 on every request (it shares the 60 req/hour budget)."""
from unittest.mock import patch

from app.services import alerts_loader


def _reset():
    alerts_loader._cache.update(at=0.0, data=None)


def test_second_call_within_ttl_uses_cache():
    _reset()
    with patch.object(alerts_loader, "_fetch_service_alerts", return_value=([{"id": "a"}], True)) as f:
        assert alerts_loader.get_service_alerts() == [{"id": "a"}]
        assert alerts_loader.get_service_alerts() == [{"id": "a"}]
        assert f.call_count == 1


def test_failed_fetch_is_not_cached():
    _reset()
    with patch.object(alerts_loader, "_fetch_service_alerts", return_value=([], False)) as f:
        alerts_loader.get_service_alerts()
        alerts_loader.get_service_alerts()
        assert f.call_count == 2


def test_cache_expires_after_ttl():
    _reset()
    with patch.object(alerts_loader, "_fetch_service_alerts", return_value=([{"id": "a"}], True)) as f:
        alerts_loader.get_service_alerts()
        alerts_loader._cache["at"] -= 10_000
        alerts_loader.get_service_alerts()
        assert f.call_count == 2


def test_budget_plan_fits_511_limit():
    from app.core.config import Settings
    s = Settings()
    per_hour = (3600 / s.five11_rt_poll_seconds * 2
                + 3600 / s.five11_traffic_poll_seconds * 3
                + 3600 / s.five11_alerts_cache_seconds)
    assert per_hour <= s.five11_rate_limit_per_hour - 10

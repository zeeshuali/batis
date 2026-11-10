"""The daily worker commits one month per transaction so a late failure keeps earlier months."""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

from app.workers import backfill_stop_observations as w


def _run(monkeypatch, steps, per_run=2):
    calls = []
    txs = []

    @contextmanager
    def begin():
        txs.append(1)
        yield MagicMock()

    engine = MagicMock()
    engine.begin = begin
    monkeypatch.setattr(w, "get_engine", lambda: engine)
    monkeypatch.setattr(w.sys, "argv", ["backfill"])
    monkeypatch.setattr(w, "get_settings", lambda: MagicMock(stop_obs_backfill_months_per_run=per_run))
    it = iter(steps)

    def fake_step(conn, months_per_run=None, max_months_back=None):
        calls.append(months_per_run)
        return next(it)

    monkeypatch.setattr(w, "backfill_step", fake_step)
    return calls, txs


def test_loads_two_months_in_separate_transactions(monkeypatch):
    calls, txs = _run(monkeypatch, [{"2026-07": 10}, {"2026-06": 20}])
    assert w.main() == 0
    assert calls == [1, 1] and len(txs) == 2


def test_stops_when_nothing_left(monkeypatch):
    calls, _ = _run(monkeypatch, [{"2026-07": 10}, {}])
    assert w.main() == 0 and len(calls) == 2


def test_failure_stops_the_run_and_returns_nonzero(monkeypatch):
    calls, _ = _run(monkeypatch, [{"2026-07": -1}, {"2026-06": 20}])
    assert w.main() == 1 and len(calls) == 1

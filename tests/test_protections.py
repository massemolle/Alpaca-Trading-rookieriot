"""Gate 0 protections (Roadmap v2) — offline, DB layer mocked."""
from __future__ import annotations

import protections


def _mock_query(monkeypatch, results: dict):
    """results maps a substring of the SQL to the row to return."""
    calls = []

    def fake(sql, params):
        calls.append(sql)
        for key, row in results.items():
            if key in sql:
                return row
        return (0,)

    monkeypatch.setattr(protections, "_query_one", fake)
    return calls


def test_all_clear(monkeypatch):
    _mock_query(monkeypatch, {"count(*)": (0,), "max(equity)": (100_000.0, 100_000.0),
                              "max(closed_at)": (None,), "sum(realized_pnl)": (0.0,)})
    assert protections.global_halt().allowed
    assert protections.check_underlying("SPY").allowed


def test_stop_streak_halts_all_entries(monkeypatch):
    _mock_query(monkeypatch, {"count(*)": (6,), "max(equity)": (100_000.0, 99_900.0)})
    res = protections.global_halt()
    assert not res.allowed
    assert any("stop_streak" in r for r in res.reasons)


def test_drawdown_halts_all_entries(monkeypatch):
    _mock_query(monkeypatch, {"count(*)": (0,), "max(equity)": (100_000.0, 96_500.0)})
    res = protections.global_halt()
    assert not res.allowed
    assert any("drawdown" in r for r in res.reasons)


def test_drawdown_fails_closed_on_query_error(monkeypatch):
    def fake(sql, params):
        if "max(equity)" in sql:
            raise RuntimeError("db down")
        return (0,)
    monkeypatch.setattr(protections, "_query_one", fake)
    res = protections.global_halt()
    assert not res.allowed
    assert any("fail-closed" in r for r in res.reasons)


def test_stop_streak_fails_open_on_query_error(monkeypatch):
    def fake(sql, params):
        if "count(*)" in sql:
            raise RuntimeError("db down")
        return (100_000.0, 100_000.0)
    monkeypatch.setattr(protections, "_query_one", fake)
    assert protections.global_halt().allowed  # conformance check: fail-open


def test_cooldown_locks_underlying(monkeypatch):
    import datetime
    _mock_query(monkeypatch, {"max(closed_at)": (datetime.datetime(2026, 9, 3, 13, 30),),
                              "sum(realized_pnl)": (0.0,)})
    res = protections.check_underlying("QQQ")
    assert not res.allowed
    assert any("cooldown" in r for r in res.reasons)


def test_low_profit_locks_underlying(monkeypatch):
    _mock_query(monkeypatch, {"max(closed_at)": (None,), "sum(realized_pnl)": (-587.0,)})
    res = protections.check_underlying("QQQ")
    assert not res.allowed
    assert any("low_profit" in r for r in res.reasons)

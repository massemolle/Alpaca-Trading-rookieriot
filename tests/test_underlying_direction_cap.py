"""Same-direction stack cap (2026-10-08) — offline, no network.

Identical-direction verticals on one underlying are one bet taken N times:
the 4 concurrent IWM bull puts all stopped out inside an hour on the
2026-10-07 gap (−$344) while the dollar concentration cap sat ~10x away
from binding. These tests pin the count gate in risk_gate and its
enforcement at the post-LLM pretrade re-check.
"""
from __future__ import annotations

import asyncio
import dataclasses
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pretrade_gate
import risk_gate
from tests.conftest import FakeClient, make_plan, snapshot, FakeMCP


def _base_kwargs(**overrides) -> dict:
    defaults = dict(
        equity=100_000.0,
        daily_pl_pct=0.0,
        open_spreads_count=0,
        max_loss=430.0,
        expiration=date.today() + timedelta(days=14),
        today=date.today(),
    )
    defaults.update(overrides)
    return defaults


def _pin_cap(monkeypatch, n: int):
    # The cap is env-tunable and the nightly gate runs pytest with .env
    # sourced — pin it so these tests assert the counting logic, not
    # whatever the environment happens to set (same pattern as the
    # concurrent-cap test in test_pretrade_gate.py).
    pinned = dataclasses.replace(
        risk_gate.config,
        risk=dataclasses.replace(risk_gate.config.risk, max_per_underlying_direction=n),
    )
    monkeypatch.setattr(risk_gate, "config", pinned)
    monkeypatch.setattr(pretrade_gate, "config", pinned)


def test_blocks_third_same_direction_spread(monkeypatch):
    _pin_cap(monkeypatch, 2)
    check = risk_gate.check_new_spread(
        **_base_kwargs(underlying="IWM"),
        same_direction_count=2,
        direction="bull_put",
    )
    assert not check.allowed
    assert any("IWM" in r and "bull_put" in r for r in check.reasons)


def test_allows_second_same_direction_spread(monkeypatch):
    # The "deliberate add on conviction" move stays legal: 1 live spread,
    # adding the 2nd (XLE on 2026-10-08) passes.
    _pin_cap(monkeypatch, 2)
    check = risk_gate.check_new_spread(
        **_base_kwargs(underlying="XLE"),
        same_direction_count=1,
        direction="bull_put",
    )
    assert check.allowed, check.reasons


def test_omitted_count_is_a_no_op(monkeypatch):
    # Backward compatible: callers that never pass same_direction_count
    # (the lab, older tests) keep working exactly as before.
    _pin_cap(monkeypatch, 2)
    check = risk_gate.check_new_spread(**_base_kwargs(underlying="IWM"))
    assert check.allowed, check.reasons


def test_cap_value_comes_from_config(monkeypatch):
    _pin_cap(monkeypatch, 3)
    check = risk_gate.check_new_spread(
        **_base_kwargs(underlying="IWM"),
        same_direction_count=2,
        direction="bull_put",
    )
    assert check.allowed, check.reasons


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _mcp_for(plan):
    return FakeMCP({
        plan.short_symbol: snapshot(1.90, 2.10),
        plan.long_symbol: snapshot(0.45, 0.55),
    })


def test_pretrade_recheck_counts_live_same_direction_rows(fake_db, monkeypatch):
    _pin_cap(monkeypatch, 2)
    plan = make_plan()  # SPY bull_put
    fake_db.extend(
        {"underlying": "SPY", "direction": "bull_put", "max_loss": 420.0, "contracts": 1}
        for _ in range(2)
    )
    result = run(pretrade_gate.pre_trade_check(_mcp_for(plan), FakeClient(), plan))
    assert not result.allowed
    assert "per-underlying/direction cap" in result.reason


def test_pretrade_recheck_ignores_opposite_direction_rows(fake_db, monkeypatch):
    # 2 live SPY bear calls do not block a SPY bull put — opposite
    # directions are different bets (TLT ran both sides profitably).
    _pin_cap(monkeypatch, 2)
    plan = make_plan()  # SPY bull_put
    fake_db.extend(
        {"underlying": "SPY", "direction": "bear_call", "max_loss": 420.0, "contracts": 1}
        for _ in range(2)
    )
    result = run(pretrade_gate.pre_trade_check(_mcp_for(plan), FakeClient(), plan))
    assert result.allowed, result.reasons

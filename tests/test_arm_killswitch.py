"""Arm 3 (Killswitch replication) — offline tests of the gate ladder."""
from __future__ import annotations

import pytest

from arm_killswitch import config as kcfg, gates


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    monkeypatch.setattr(gates.book, "open_positions", lambda: [])


def test_exit_ladder_precedence():
    # DTE force-close beats everything, even a winner.
    assert gates.exit_decision(1.0, 2.0, 100, 95, "call", kcfg.FORCE_CLOSE_DTE) == "dte_force_close"
    assert gates.exit_decision(1.0, 1.6, 100, 95, "call", 30) == "take_profit"
    assert gates.exit_decision(1.0, 0.2, 100, 95, "call", 30) == "premium_floor"
    assert gates.exit_decision(1.0, 0.9, 94.0, 95.0, "call", 30) == "atr_stop"
    assert gates.exit_decision(1.0, 1.1, 100, 95, "call", 30) is None


def test_put_stop_direction_mirrors():
    # For a put, the stop fires when spot rises ABOVE the stop level.
    assert gates.exit_decision(1.0, 0.9, 106.0, 105.0, "put", 30) == "atr_stop"
    assert gates.exit_decision(1.0, 0.9, 104.0, 105.0, "put", 30) is None


def test_order_gates_reject_rich_premium():
    g = gates.order_gates("SPY", "call", premium=300, equity=100_000,
                          price_ratio=1.8, theta_per_day=1.0, delta=0.65)
    assert not g.allowed and any("rich" in r for r in g.reasons)


def test_order_gates_reject_theta_burden():
    g = gates.order_gates("SPY", "call", premium=300, equity=100_000,
                          price_ratio=1.0, theta_per_day=20.0, delta=0.65)  # 6.7%/day
    assert not g.allowed and any("theta" in r for r in g.reasons)


def test_order_gates_reject_delta_outside_band():
    g = gates.order_gates("SPY", "call", premium=300, equity=100_000,
                          price_ratio=1.0, theta_per_day=1.0, delta=0.30)
    assert not g.allowed and any("delta" in r for r in g.reasons)


def test_order_gates_size_shrinks_to_budget():
    # 4% of 100k = $4,000 budget; $300 premium -> 13 contracts, never more.
    g = gates.order_gates("SPY", "call", premium=300, equity=100_000,
                          price_ratio=1.0, theta_per_day=1.0, delta=0.65)
    assert g.allowed and g.contracts == 13


def test_correlation_group_cap(monkeypatch):
    held = [{"underlying": u, "right_": "call"} for u in ("SPY", "QQQ", "DIA")]
    monkeypatch.setattr(gates.book, "open_positions", lambda: held)
    g = gates.order_gates("IWM", "call", 300, 100_000, 1.0, 1.0, 0.65)
    assert not g.allowed and any("correlation group" in r for r in g.reasons)


def test_killswitch_halts_entries_only(monkeypatch):
    monkeypatch.setattr(kcfg, "TRADING_HALTED", True)
    g = gates.pre_model_gates(equity=100_000, daily_pl=0)
    assert not g.allowed and any("killswitch" in r for r in g.reasons)
    # exits remain pure/unaffected
    assert gates.exit_decision(1.0, 1.6, 100, 95, "call", 30) == "take_profit"


def test_daily_loss_gate():
    g = gates.pre_model_gates(equity=100_000, daily_pl=-2_500)
    assert not g.allowed and any("daily loss" in r for r in g.reasons)


@pytest.mark.asyncio
async def test_executor_honors_caller_dry_run_not_sleeve_flag(monkeypatch):
    """2026-10-15 incident: arm 3 passed KS_DRY_RUN=true but the shared
    executor read PREMIUM_DRY_RUN (live) and placed 20 real paper contracts.
    A caller-supplied dry_run must win over the module's own flag."""
    from premium_buyer import config as pcfg, executor

    monkeypatch.setattr(pcfg, "DRY_RUN", False)   # premium sleeve is LIVE

    class ExplodingMCP:
        async def call(self, *a, **k):
            raise AssertionError("a dry-run caller must never reach the broker")

    res = await executor.buy(ExplodingMCP(), "TLT261127C00079000", 18, 2.165, dry_run=True)
    assert res is not None and res["status"] == "dry_run"
    res2 = await executor.sell_to_close(ExplodingMCP(), "TLT261127C00079000", 18, 2.165, dry_run=True)
    assert res2 is not None and res2["status"] == "dry_run"

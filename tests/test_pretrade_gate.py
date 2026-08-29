"""Unit tests for the second risk gate (pretrade_gate.pre_trade_check).

All offline: FakeMCP serves canned snapshots, FakeClient serves account
state, fake_db serves the open-spreads book. Frozen config is respected —
tests use values compatible with the shipped defaults (2% max loss/equity,
5 concurrent, 10-21 DTE, 25% concentration is config.risk.max_concentration_pct).
"""
from __future__ import annotations

import asyncio

import pytest

import pretrade_gate
from pretrade_gate import pre_trade_check
from tests.conftest import FakeClient, FakeMCP, make_plan, snapshot


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def make_mcp(plan, short=(1.90, 2.10), long=(0.45, 0.55), age_minutes=1.0):
    return FakeMCP({
        plan.short_symbol: snapshot(*short, age_minutes=age_minutes),
        plan.long_symbol: snapshot(*long, age_minutes=age_minutes),
    })


def test_happy_path_updates_plan(fake_db):
    plan = make_plan()  # original credit 150
    mcp = make_mcp(plan)  # fresh mids: short 2.00, long 0.50 → credit 150
    result = run(pre_trade_check(mcp, FakeClient(), plan))
    assert result.allowed, result.reasons
    assert result.plan.credit_estimate == 150.0
    assert result.plan.max_loss == 350.0
    assert result.facts["fresh_credit"] == 150.0
    assert result.facts["equity_at_check"] == 100_000.0


def test_stale_quote_blocks(fake_db):
    plan = make_plan()
    mcp = make_mcp(plan, age_minutes=30)
    result = run(pre_trade_check(mcp, FakeClient(), plan))
    assert not result.allowed
    assert "stale" in result.reason


def test_credit_shrink_blocks(fake_db):
    plan = make_plan(credit_estimate=200.0)  # fresh credit 150 → 25% shrink
    mcp = make_mcp(plan)
    result = run(pre_trade_check(mcp, FakeClient(), plan))
    assert not result.allowed
    assert "shrank" in result.reason


def test_small_shrink_passes_with_updated_credit(fake_db):
    plan = make_plan(credit_estimate=160.0)  # fresh 150 → 6% shrink, allowed
    mcp = make_mcp(plan)
    result = run(pre_trade_check(mcp, FakeClient(), plan))
    assert result.allowed
    assert result.plan.credit_estimate == 150.0  # trades on the fresh number


def test_missing_quotes_block(fake_db):
    plan = make_plan()
    mcp = FakeMCP({})  # no snapshots at all
    result = run(pre_trade_check(mcp, FakeClient(), plan))
    assert not result.allowed
    assert "unavailable" in result.reason


def test_concurrent_cap_counts_intracycle_opens(fake_db):
    plan = make_plan()
    fake_db.extend({"underlying": f"T{i}", "max_loss": 300.0, "contracts": 1} for i in range(3))
    mcp = make_mcp(plan)
    # 3 in DB + 2 opened earlier this cycle = 5 = at the cap → blocked
    result = run(pre_trade_check(mcp, FakeClient(), plan, opened_this_cycle=2))
    assert not result.allowed
    assert "concurrent" in result.reason
    # sanity: with only 1 opened this cycle it passes
    result_ok = run(pre_trade_check(make_mcp(plan), FakeClient(), plan, opened_this_cycle=1))
    assert result_ok.allowed, result_ok.reasons


def test_concentration_enforced_post_llm(fake_db):
    """Regression: the inline gate omitted existing_exposure/underlying, so
    the per-underlying cap only ran pre-LLM. It must run here too."""
    plan = make_plan()
    cap = pretrade_gate.risk_gate.config.risk.max_concentration_pct
    fake_db.append({"underlying": "SPY", "max_loss": 100_000.0 * cap, "contracts": 1})
    mcp = make_mcp(plan)
    result = run(pre_trade_check(mcp, FakeClient(), plan))
    assert not result.allowed
    assert "concentration" in result.reason


def test_buying_power_floor(fake_db):
    plan = make_plan()
    mcp = make_mcp(plan)
    result = run(pre_trade_check(mcp, FakeClient(buying_power=100.0), plan))
    assert not result.allowed
    assert "buying power" in result.reason


def test_gate_fails_closed_on_internal_error(fake_db):
    plan = make_plan()

    class ExplodingMCP:
        async def call(self, tool, arguments):
            raise ConnectionError("boom")

    result = run(pre_trade_check(ExplodingMCP(), FakeClient(), plan))
    assert not result.allowed
    assert "fail-closed" in result.reason

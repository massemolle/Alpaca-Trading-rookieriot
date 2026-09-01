"""Unit tests for the second risk gate (pretrade_gate.pre_trade_check).

All offline: FakeMCP serves canned snapshots, FakeClient serves account
state, fake_db serves the open-spreads book.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

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
    assert result.contracts >= 1


def test_stale_quote_blocks(fake_db):
    plan = make_plan()
    mcp = make_mcp(plan, age_minutes=30)
    result = run(pre_trade_check(mcp, FakeClient(), plan))
    assert not result.allowed
    assert "stale" in result.reason


def test_missing_quote_timestamp_blocks(fake_db):
    plan = make_plan()
    mcp = FakeMCP({
        plan.short_symbol: {"latestQuote": {"bp": 1.9, "ap": 2.1}},  # no t
        plan.long_symbol: snapshot(0.45, 0.55),
    })
    result = run(pre_trade_check(mcp, FakeClient(), plan))
    assert not result.allowed
    assert "no timestamp" in result.reason


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
    assert result.plan.credit_estimate == 150.0


def test_missing_quotes_block(fake_db):
    plan = make_plan()
    mcp = FakeMCP({})
    result = run(pre_trade_check(mcp, FakeClient(), plan))
    assert not result.allowed
    assert "unavailable" in result.reason


def test_concurrent_cap_counts_intracycle_opens(fake_db, monkeypatch):
    # Pin the cap: the live cap is env-tunable (D21 raised it to 8), and the
    # nightly gate runs pytest with .env sourced — this test must assert the
    # counting logic, not whatever cap the environment happens to set.
    import dataclasses
    import pretrade_gate
    import risk_gate
    pinned = dataclasses.replace(
        pretrade_gate.config,
        risk=dataclasses.replace(pretrade_gate.config.risk, max_concurrent_spreads=5),
    )
    monkeypatch.setattr(pretrade_gate, "config", pinned)
    monkeypatch.setattr(risk_gate, "config", pinned)
    plan = make_plan()
    fake_db.extend({"underlying": f"T{i}", "max_loss": 300.0, "contracts": 1} for i in range(3))
    mcp = make_mcp(plan)
    result = run(pre_trade_check(mcp, FakeClient(), plan, opened_this_cycle=2))
    assert not result.allowed
    assert "concurrent" in result.reason
    result_ok = run(pre_trade_check(make_mcp(plan), FakeClient(), plan, opened_this_cycle=1))
    assert result_ok.allowed, result_ok.reasons


def test_concentration_enforced_post_llm(fake_db):
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


def test_multi_contract_uses_total_max_loss(fake_db, capped_contracts):
    """Gate must validate buying power for N contracts, not one."""
    plan = make_plan()  # max_loss 350
    mcp = make_mcp(plan)
    # 5 contracts × 350 = 1750 — BP of 1000 must fail
    result = run(pre_trade_check(
        mcp, FakeClient(buying_power=1000.0), plan, contracts=5,
    ))
    assert not result.allowed
    assert "buying power" in result.reason
    assert result.contracts == 5


def test_multi_contract_concentration(fake_db, capped_contracts):
    plan = make_plan()  # max_loss 350
    # Existing 18k exposure; 5×350=1750 → 19750 under 20k cap → pass
    # 10×350=3500 → 21500 over 20k → fail
    fake_db.append({"underlying": "SPY", "max_loss": 18000.0, "contracts": 1})
    ok = run(pre_trade_check(
        make_mcp(plan), FakeClient(), plan, contracts=5,
    ))
    assert ok.allowed, ok.reasons
    bad = run(pre_trade_check(
        make_mcp(plan), FakeClient(), plan, contracts=10,
    ))
    assert not bad.allowed
    assert "concentration" in bad.reason


def test_gate_fails_closed_on_internal_error(fake_db):
    plan = make_plan()

    class ExplodingMCP:
        async def call(self, tool, arguments):
            raise ConnectionError("boom")

    result = run(pre_trade_check(ExplodingMCP(), FakeClient(), plan))
    assert not result.allowed
    assert "fail-closed" in result.reason

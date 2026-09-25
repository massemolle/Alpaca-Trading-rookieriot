"""The live book must include in-flight rows, and marks must be real prices.

Live evidence 2026-09-25, one incident chain:

1. 13:30:07Z — seconds after the open — the indicative feed quoted TLT
   260928C81 no-bid x 2.50 (a spread genuinely worth ~$25 marked at $250),
   which fired a fictional stop on spread id 35; the close order (limit
   debit 2.75 against a $0.74 credit) rested at the broker all day.
2. That parked the row in pending_close — and every exposure, concentration
   and budget read used get_open_spreads (status='open' only), so the row's
   very real broker legs vanished from the book the gates and the judge saw.
   At 18:01Z the judge was told XLE held 1 spread/$413 while the broker held
   2/$824 and it "deliberately" stacked a third; the session ended with 9
   live spreads against a concurrent cap of 8.

Pinned here:
- risk_gate.should_close never fires the STOP off a one-sided (bid-less
  short) mark, while the profit target and real two-sided stops still work;
- executor_mcp.get_spread_mark_detail reports the short leg's sidedness and
  get_spread_mark's mark math is unchanged;
- manage_open_spreads submits no close order for a one-sided garbage stop
  (and still does for a genuine two-sided one);
- db.get_live_spreads covers open + pending + pending_close;
- pretrade_gate counts pending_close rows toward the concurrent cap and
  concentration.
"""
from __future__ import annotations

import asyncio
import dataclasses
import inspect

import pytest

import bot
import db
import executor_mcp
import pretrade_gate
import risk_gate
from pretrade_gate import pre_trade_check
from tests.conftest import FakeClient, FakeMCP, make_plan, snapshot


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


# --------------------------------------------------- should_close stop guard

def _pin_exit_limits(monkeypatch):
    pinned = dataclasses.replace(
        risk_gate.config,
        risk=dataclasses.replace(
            risk_gate.config.risk, profit_target_pct=0.50, stop_loss_multiple=2.0
        ),
    )
    monkeypatch.setattr(risk_gate, "config", pinned)


def test_two_sided_stop_still_fires(monkeypatch):
    _pin_exit_limits(monkeypatch)
    close, reason = risk_gate.should_close(
        credit_received=74.0, current_mark=250.0, short_leg_two_sided=True
    )
    assert close and "stop hit" in reason


def test_default_keeps_stop_live_for_legacy_callers(monkeypatch):
    # Lab / tests that can't assess the book keep the pre-2026-09-25 behavior.
    _pin_exit_limits(monkeypatch)
    close, reason = risk_gate.should_close(credit_received=74.0, current_mark=250.0)
    assert close and "stop hit" in reason


def test_one_sided_mark_cannot_fire_the_stop(monkeypatch):
    # The literal 2026-09-25 numbers: $74 credit, $250 ask-only "mark".
    _pin_exit_limits(monkeypatch)
    close, reason = risk_gate.should_close(
        credit_received=74.0, current_mark=250.0, short_leg_two_sided=False
    )
    assert not close and reason is None


def test_profit_target_unaffected_by_one_sided_book(monkeypatch):
    # An inflated ask can only understate profit; a tiny ask-only mark that
    # clears the target is honest and must still close the winner.
    _pin_exit_limits(monkeypatch)
    close, reason = risk_gate.should_close(
        credit_received=74.0, current_mark=5.0, short_leg_two_sided=False
    )
    assert close and "profit target" in reason


# ------------------------------------------------------ get_spread_mark_detail

SHORT = "TLT260928C00081000"
LONG = "TLT260928C00086000"


def test_detail_two_sided_book():
    mcp = FakeMCP({SHORT: snapshot(0.20, 0.30), LONG: snapshot(0.01, 0.05)})
    mark, two_sided = run(executor_mcp.get_spread_mark_detail(mcp, SHORT, LONG))
    assert mark == pytest.approx((0.30 - 0.01) * 100)
    assert two_sided is True


def test_detail_flags_bidless_short():
    # The 13:30:07Z book shape: short no-bid x 2.50, long empty.
    mcp = FakeMCP({SHORT: snapshot(0.0, 2.50), LONG: snapshot(0.0, 0.0)})
    mark, two_sided = run(executor_mcp.get_spread_mark_detail(mcp, SHORT, LONG))
    assert mark == pytest.approx(250.0)
    assert two_sided is False


def test_detail_missing_quote_is_none():
    mcp = FakeMCP({SHORT: snapshot(0.20, 0.30)})  # long symbol absent
    mark, two_sided = run(executor_mcp.get_spread_mark_detail(mcp, SHORT, LONG))
    assert mark is None and two_sided is False


def test_get_spread_mark_math_unchanged():
    mcp = FakeMCP({SHORT: snapshot(0.20, 0.30), LONG: snapshot(0.01, 0.05)})
    assert run(executor_mcp.get_spread_mark(mcp, SHORT, LONG)) == pytest.approx(29.0)


# --------------------------------------- manage_open_spreads: no bogus close

class _ExitDB:
    def __init__(self, spreads):
        self.spreads = spreads
        self.status_updates: list[tuple] = []
        self.closes: list[tuple] = []

    def get_manageable_spreads(self):
        return [dict(s) for s in self.spreads if s.get("status") in ("open", "pending")]

    def get_spreads_by_status(self, status):
        return [dict(s) for s in self.spreads if s.get("status") == status]

    def update_spread_status(self, spread_id, status, **kwargs):
        self.status_updates.append((spread_id, status, kwargs))

    def record_spread_close(self, spread_id, status, realized_pnl):
        self.closes.append((spread_id, status, realized_pnl))


def _tlt_row():
    return {
        "id": 35,
        "status": "open",
        "underlying": "TLT",
        "direction": "bear_call",
        "expiration": "2099-01-01",  # far away: no force-close
        "short_symbol": SHORT,
        "long_symbol": LONG,
        "contracts": 1,
        "credit_received": "74.0",
        "alpaca_order_ids": ["open-order-id"],
    }


def _exit_setup(monkeypatch, short_quote, long_quote):
    _pin_exit_limits(monkeypatch)
    fake_db = _ExitDB([_tlt_row()])
    monkeypatch.setattr(bot, "db", fake_db)
    close_calls = []

    async def fake_close(mcp, **kwargs):
        close_calls.append(kwargs)
        return executor_mcp.OrderResult(
            order_ids=["close-order-id"], client_order_id="c",
            status="filled", fill_credit=150.0,
        )

    monkeypatch.setattr(executor_mcp, "close_spread", fake_close)
    mcp = FakeMCP({SHORT: snapshot(*short_quote), LONG: snapshot(*long_quote)})
    return fake_db, close_calls, mcp


@pytest.mark.asyncio
async def test_at_open_garbage_mark_submits_no_close(monkeypatch):
    fake_db, close_calls, mcp = _exit_setup(
        monkeypatch, short_quote=(0.0, 2.50), long_quote=(0.0, 0.0)
    )
    await bot.manage_open_spreads(mcp, FakeClient(), market_open=True)
    assert close_calls == [], "a bid-less $250 'mark' must not stop out a $74-credit spread"
    assert fake_db.closes == [] and fake_db.status_updates == []


@pytest.mark.asyncio
async def test_real_two_sided_stop_still_closes(monkeypatch):
    fake_db, close_calls, mcp = _exit_setup(
        monkeypatch, short_quote=(1.40, 1.55), long_quote=(0.05, 0.10)
    )
    await bot.manage_open_spreads(mcp, FakeClient(), market_open=True)
    assert len(close_calls) == 1, "a genuine 2x stop on a two-sided book must still close"
    assert fake_db.closes and fake_db.closes[0][0] == 35


# ------------------------------------------------------------- live-book reads

def test_get_live_spreads_covers_all_inflight_statuses():
    # No test DB here — pin the status set in the SQL itself so a future
    # edit can't silently drop pending_close out of the live book again.
    src = inspect.getsource(db.get_live_spreads)
    for status in ("'open'", "'pending'", "'pending_close'"):
        assert status in src, f"get_live_spreads must include {status}"


def test_pretrade_cap_counts_pending_close_rows(fake_db, monkeypatch):
    pinned = dataclasses.replace(
        pretrade_gate.config,
        risk=dataclasses.replace(pretrade_gate.config.risk, max_concurrent_spreads=5),
    )
    monkeypatch.setattr(pretrade_gate, "config", pinned)
    monkeypatch.setattr(risk_gate, "config", pinned)
    plan = make_plan()
    # 3 filled + 2 whose closes are resting at the broker: 5 live = cap hit.
    fake_db.extend(
        {"underlying": f"T{i}", "max_loss": 300.0, "contracts": 1, "status": "open"}
        for i in range(3)
    )
    fake_db.extend(
        {"underlying": f"P{i}", "max_loss": 300.0, "contracts": 1, "status": "pending_close"}
        for i in range(2)
    )
    mcp = FakeMCP({
        plan.short_symbol: snapshot(1.90, 2.10),
        plan.long_symbol: snapshot(0.45, 0.55),
    })
    result = run(pre_trade_check(mcp, FakeClient(), plan))
    assert not result.allowed
    assert "concurrent" in result.reason


def test_pretrade_concentration_counts_pending_close_exposure(fake_db):
    plan = make_plan()  # SPY
    cap = pretrade_gate.risk_gate.config.risk.max_concentration_pct
    fake_db.append({
        "underlying": "SPY", "max_loss": 100_000.0 * cap, "contracts": 1,
        "status": "pending_close",
    })
    mcp = FakeMCP({
        plan.short_symbol: snapshot(1.90, 2.10),
        plan.long_symbol: snapshot(0.45, 0.55),
    })
    result = run(pre_trade_check(mcp, FakeClient(), plan))
    assert not result.allowed
    assert "concentration" in result.reason

"""Menu-only screening under the drawdown halt (D29, 2026-11-27) — offline.

The drawdown halt reads SHARED-account equity, so another sleeve's marks can
bench this sleeve for whole days (10-19, 11-23, 11-27) — and before D29 those
days produced zero menu rows, so the standing sleeve-scoped-halt proposal's
cost was unmeasurable. These tests pin the pieces:
(1) find_candidates' breaker waiver zeroes ONLY the shared-account daily-loss
    input — every other limit (including the concurrent cap) still sees real
    inputs,
(2) _drawdown_only_halt probes the PURE drawdown halt only — a stop_streak
    (the sleeve's own record) or a fail-closed drawdown error never probes,
(3) regret_summary segregates halted rows into halt_window_* fields, apart
    from both the judge's dropped stats and the cap-window stats,
(4) resolved_dropped_cycles never asks for the (nonexistent) drop reasoning
    of a halt-probe cycle, and
(5) evening_context tells halt probes from cap probes by the journaled
    protections prefix.
"""
from __future__ import annotations

import asyncio
import dataclasses
import inspect
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bot
import evening_context
import protections
import risk_gate
import shadow_book
from signals.swing import Signal
from tests.conftest import make_plan


# ---------------------------------------------------------------------------
# find_candidates: the waiver is breaker-only
# ---------------------------------------------------------------------------

def _pin_risk(monkeypatch):
    risk = dataclasses.replace(
        risk_gate.config.risk,
        max_concurrent_spreads=8, min_dte=7, max_dte=21, max_daily_loss_pct=0.03,
    )
    cfg = dataclasses.replace(risk_gate.config, risk=risk)
    monkeypatch.setattr(risk_gate, "config", cfg)


def _run_find_candidates(monkeypatch, *, open_count: int, breaker_waived: bool,
                         daily_pl_pct: float, plan=None):
    _pin_risk(monkeypatch)
    plan = plan or make_plan()

    monkeypatch.setattr(bot, "get_universe", lambda: ["SPY"])
    monkeypatch.setattr(
        bot, "filter_universe",
        lambda universe, client, rejections_out=None: [SimpleNamespace(symbol="SPY")],
    )
    monkeypatch.setattr(
        bot, "generate_swing_signals",
        lambda tickers, client: [
            Signal(ticker="SPY", direction="long", strength=0.5,
                   indicators={}, reasoning=["test"]),
        ],
    )
    monkeypatch.setattr(
        bot, "_apply_trend_and_volatility_filters",
        lambda client, signals: (
            [(s, 0.15, {"prev_close": None, "today_open": None}) for s in signals], []),
    )
    monkeypatch.setattr(
        bot.protections, "check_underlying",
        lambda ticker: SimpleNamespace(allowed=True, reasons=[]),
    )
    monkeypatch.setattr(bot.db, "get_live_spreads", lambda: [])

    async def fake_build_spread(mcp, ticker, direction, **kwargs):
        return plan

    monkeypatch.setattr(bot, "build_spread", fake_build_spread)

    client = SimpleNamespace(
        get_latest_quote=lambda symbol: {"bid_price": 99.90, "ask_price": 100.10},
    )
    account = {"equity": 100_000.0, "daily_pl_pct": daily_pl_pct}
    return asyncio.run(bot.find_candidates(
        None, client, account, open_count, breaker_waived=breaker_waived,
    ))


def test_tripped_breaker_without_waiver_rejects(monkeypatch):
    # -5% shared-account day (11-27 read -5.5%): the gate's breaker fires.
    candidates, rejections = _run_find_candidates(
        monkeypatch, open_count=0, breaker_waived=False, daily_pl_pct=-0.05,
    )
    assert candidates == []
    gate_rej = [r for r in rejections if r.get("stage") == "risk_gate"]
    assert len(gate_rej) == 1
    assert any("circuit breaker" in reason for reason in gate_rej[0]["reasons"])


def test_breaker_waiver_admits_candidate(monkeypatch):
    candidates, rejections = _run_find_candidates(
        monkeypatch, open_count=0, breaker_waived=True, daily_pl_pct=-0.05,
    )
    assert [c["ticker"] for c in candidates] == ["SPY"]
    assert all(r.get("stage") != "risk_gate" for r in rejections)


def test_waiver_is_breaker_only_other_limits_still_reject(monkeypatch):
    # A 2-DTE plan violates the [7, 21] window; the breaker waiver must not help.
    plan = make_plan(expiration=date.today() + timedelta(days=2))
    candidates, rejections = _run_find_candidates(
        monkeypatch, open_count=0, breaker_waived=True, daily_pl_pct=-0.05, plan=plan,
    )
    assert candidates == []
    gate_rej = [r for r in rejections if r.get("stage") == "risk_gate"]
    assert len(gate_rej) == 1
    assert any("DTE" in reason for reason in gate_rej[0]["reasons"])
    assert not any("circuit breaker" in reason for reason in gate_rej[0]["reasons"])


def test_breaker_waiver_does_not_waive_the_cap(monkeypatch):
    # The halt probe runs only with remaining_budget > 0; if the book were
    # at cap, the cap must still reject — breaker_waived is not a cap waiver.
    candidates, rejections = _run_find_candidates(
        monkeypatch, open_count=8, breaker_waived=True, daily_pl_pct=-0.05,
    )
    assert candidates == []
    gate_rej = [r for r in rejections if r.get("stage") == "risk_gate"]
    assert len(gate_rej) == 1
    assert any("concurrent cap" in reason for reason in gate_rej[0]["reasons"])


# ---------------------------------------------------------------------------
# _drawdown_only_halt: probe the pure drawdown halt, nothing else
# ---------------------------------------------------------------------------

def _prot(*reasons: str) -> protections.ProtectionResult:
    return protections.ProtectionResult(allowed=not reasons, reasons=list(reasons))


def test_drawdown_only_halt_true_on_pure_drawdown():
    assert bot._drawdown_only_halt(_prot(
        "drawdown: equity 105,879 is 6.0% below the 5-day peak 112,598 (max 3%) — entries halted",
    ))


def test_drawdown_only_halt_false_when_stop_streak_present():
    assert not bot._drawdown_only_halt(_prot(
        "stop_streak: 4 stop-outs in the last 24h (max 4) — vol regime moved, entries halted",
        "drawdown: equity 105,879 is 6.0% below the 5-day peak 112,598 (max 3%) — entries halted",
    ))


def test_drawdown_only_halt_false_on_fail_closed_error():
    # The fail-closed message means we don't know WHY we're halted — no probe.
    assert not bot._drawdown_only_halt(_prot(
        "drawdown check errored — fail-closed, entries halted",
    ))


def test_drawdown_only_halt_false_when_allowed():
    assert not bot._drawdown_only_halt(_prot())


def test_run_cycle_halt_branch_waives_breaker_only_under_pure_drawdown():
    # Structural pin: the halt-probe branch exists, is gated on the pure-
    # drawdown helper, and is the only breaker_waived call site in run_cycle.
    src = inspect.getsource(bot.run_cycle)
    assert "_drawdown_only_halt(prot)" in src
    assert src.count("breaker_waived=True") == 1


# ---------------------------------------------------------------------------
# regret_summary: halted rows price the halt, not the cap, not the judge
# ---------------------------------------------------------------------------

def _menu_row(cycle_id: int, *, status: str = "open", realized=None, mark=None,
              credit: float = 100.0) -> dict:
    return {
        "cycle_id": cycle_id, "underlying": "SPY", "direction": "bull_put",
        "short_strike": 640.0, "long_strike": 635.0, "expiration": "2026-12-11",
        "status": status, "same_as_llm": False, "credit_received": credit,
        "contracts": 1, "realized_pnl": realized, "unrealized_mark": mark,
    }


def test_halted_rows_segregated_from_dropped_and_cap_stats():
    rows = [
        _menu_row(1, status="closed_profit", realized=50.0),   # a real judge drop
        _menu_row(2, status="closed_profit", realized=40.0),   # at-capacity winner
        _menu_row(3, status="closed_profit", realized=25.0),   # halt-window winner
        _menu_row(3, status="closed_stop", realized=-35.0),    # halt-window loser
    ]
    summary = shadow_book.regret_summary(rows, capacity_cycles={2}, halted_cycles={3})
    assert summary["dropped_count"] == 1
    assert summary["dropped_total_usd"] == 50.0
    assert summary["best_dropped"]["cycle_id"] == 1
    assert summary["cap_window_count"] == 1
    assert summary["cap_window_total_usd"] == 40.0
    assert summary["halt_window_count"] == 2
    assert summary["halt_window_total_usd"] == -10.0
    assert summary["halt_window_positive_count"] == 1
    assert summary["halt_window_positive_total_usd"] == 25.0
    by_key = {(t["cycle_id"], t["outcome_usd"]): t for t in summary["rows"]}
    assert not by_key[(1, 50.0)]["halted_entry"]
    assert by_key[(3, 25.0)]["halted_entry"]
    assert not by_key[(3, 25.0)]["at_capacity"]


def test_cycle_in_both_sets_counts_as_halted():
    # _skip_reasoning puts the protections halt above the cap, so a cycle
    # that was both halted and at cap journals as halted — the summary must
    # agree and never double count.
    rows = [_menu_row(7, status="closed_profit", realized=30.0)]
    summary = shadow_book.regret_summary(rows, capacity_cycles={7}, halted_cycles={7})
    assert summary["halt_window_count"] == 1
    assert summary["cap_window_count"] == 0
    assert summary["dropped_count"] == 0


def test_no_halted_set_preserves_existing_behavior():
    rows = [
        _menu_row(1, status="closed_profit", realized=50.0),
        _menu_row(2, status="closed_profit", realized=40.0),
    ]
    summary = shadow_book.regret_summary(rows, capacity_cycles={2})
    assert summary["dropped_count"] == 1
    assert summary["cap_window_count"] == 1
    assert summary["halt_window_count"] == 0
    assert all(not t["halted_entry"] for t in summary["rows"])


def test_resolved_dropped_cycles_skips_halted_rows():
    rows = [
        _menu_row(1, status="closed_profit", realized=50.0),
        _menu_row(3, status="closed_profit", realized=25.0),
    ]
    summary = shadow_book.regret_summary(rows, halted_cycles={3})
    # Cycle 3 resolved profitable but the judge never saw it — there is no
    # drop reasoning in its journal to classify, so it must not be fetched.
    assert shadow_book.resolved_dropped_cycles(summary["rows"]) == [1]


# ---------------------------------------------------------------------------
# evening_context: the journaled prefix tells the two probes apart
# ---------------------------------------------------------------------------

def test_split_probe_cycles_on_journaled_reasoning():
    rows = [
        {"id": 10, "reasoning": (
            "No new positions — protections: drawdown: equity 105,879 is 6.0% "
            "below the 5-day peak 112,598 (max 3%) — entries halted. Exits stay "
            "active. Menu-only screening ran: 2 gate-approved candidate(s) "
            "tracked virtually to price the entry halt (no LLM call, nothing "
            "executable).")},
        {"id": 11, "reasoning": (
            "No new positions — book at the concurrent-spread cap (8 open, 0 "
            "remaining budget); not screening. Exits stay active. Menu-only "
            "screening ran: 3 gate-approved candidate(s) tracked virtually to "
            "price the cap (no LLM call, nothing executable).")},
        {"id": 12, "reasoning": None},
    ]
    capacity, halted = evening_context._split_probe_cycles(rows)
    assert halted == {10}
    assert capacity == {11, 12}


def test_split_prefix_matches_bot_skip_reasoning():
    # The split keys off _skip_reasoning's exact protections message; if that
    # string ever changes, this pin fails before the classification silently
    # breaks in production.
    prot = protections.ProtectionResult(allowed=False, reasons=["drawdown: x"])
    msg = bot._skip_reasoning(
        options_level_ok=True, options_level=3, market_open=True,
        blackout=False, blackout_reason=None, prot=prot,
        close_window=False, close_window_reason=None,
        remaining_budget=5, open_spread_count=0,
    )
    assert msg.startswith(evening_context._HALT_SKIP_PREFIX)

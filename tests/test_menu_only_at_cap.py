"""Menu-only screening at the concurrent cap (D26, 2026-10-09) — offline.

Before D26, an at-cap cycle skipped screening entirely: 11 of 16 market
cycles on 2026-10-09 (and all of 2026-09-15) produced no menu rows, so the
cap's opportunity cost was unmeasurable. These tests pin the three pieces:
(1) find_candidates' capacity waiver disables ONLY the concurrent-cap check,
(2) regret_summary segregates at-capacity rows from the judge's dropped
stats, and (3) resolved_dropped_cycles never asks for the (nonexistent)
drop reasoning of a cycle the judge never saw.
"""
from __future__ import annotations

import asyncio
import dataclasses
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bot
import risk_gate
import shadow_book
from signals.swing import Signal
from tests.conftest import make_plan


# ---------------------------------------------------------------------------
# find_candidates: the waiver is cap-only
# ---------------------------------------------------------------------------

def _pin_risk(monkeypatch):
    # Cap and DTE window are env-tunable and the gate sources .env — pin
    # them so these tests assert the waiver logic, not the environment.
    risk = dataclasses.replace(
        risk_gate.config.risk, max_concurrent_spreads=8, min_dte=7, max_dte=21,
    )
    cfg = dataclasses.replace(risk_gate.config, risk=risk)
    monkeypatch.setattr(risk_gate, "config", cfg)


def _run_find_candidates(monkeypatch, *, open_count: int, capacity_waived: bool, plan=None):
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
        lambda client, signals: ([(s, 0.15) for s in signals], []),
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
    account = {"equity": 100_000.0, "daily_pl_pct": 0.0}
    return asyncio.run(bot.find_candidates(
        None, client, account, open_count, capacity_waived=capacity_waived,
    ))


def test_at_cap_without_waiver_rejects_on_concurrent_cap(monkeypatch):
    candidates, rejections = _run_find_candidates(
        monkeypatch, open_count=8, capacity_waived=False,
    )
    assert candidates == []
    gate_rej = [r for r in rejections if r.get("stage") == "risk_gate"]
    assert len(gate_rej) == 1
    assert any("concurrent cap" in reason for reason in gate_rej[0]["reasons"])


def test_waiver_admits_candidate_at_cap(monkeypatch):
    candidates, rejections = _run_find_candidates(
        monkeypatch, open_count=8, capacity_waived=True,
    )
    assert [c["ticker"] for c in candidates] == ["SPY"]
    assert all(r.get("stage") != "risk_gate" for r in rejections)


def test_waiver_is_cap_only_other_limits_still_reject(monkeypatch):
    # A 2-DTE plan violates the [7, 21] window; the waiver must not help it.
    plan = make_plan(expiration=date.today() + timedelta(days=2))
    candidates, rejections = _run_find_candidates(
        monkeypatch, open_count=8, capacity_waived=True, plan=plan,
    )
    assert candidates == []
    gate_rej = [r for r in rejections if r.get("stage") == "risk_gate"]
    assert len(gate_rej) == 1
    assert any("DTE" in reason for reason in gate_rej[0]["reasons"])
    assert not any("concurrent cap" in reason for reason in gate_rej[0]["reasons"])


# ---------------------------------------------------------------------------
# regret_summary: at-capacity rows price the cap, not the judge
# ---------------------------------------------------------------------------

def _menu_row(cycle_id: int, *, status: str = "open", realized=None, mark=None,
              credit: float = 100.0) -> dict:
    return {
        "cycle_id": cycle_id, "underlying": "SPY", "direction": "bull_put",
        "short_strike": 640.0, "long_strike": 635.0, "expiration": "2026-10-23",
        "status": status, "same_as_llm": False, "credit_received": credit,
        "contracts": 1, "realized_pnl": realized, "unrealized_mark": mark,
    }


def test_capacity_rows_segregated_from_dropped_stats():
    rows = [
        _menu_row(1, status="closed_profit", realized=50.0),   # a real judge drop
        _menu_row(2, status="closed_profit", realized=40.0),   # at-capacity winner
        _menu_row(2, status="closed_stop", realized=-30.0),    # at-capacity loser
    ]
    summary = shadow_book.regret_summary(rows, capacity_cycles={2})
    assert summary["dropped_count"] == 1
    assert summary["dropped_total_usd"] == 50.0
    assert summary["best_dropped"]["cycle_id"] == 1
    assert summary["cap_window_count"] == 2
    assert summary["cap_window_total_usd"] == 10.0
    assert summary["cap_window_positive_count"] == 1
    assert summary["cap_window_positive_total_usd"] == 40.0
    by_cycle = {(t["cycle_id"], t["outcome_usd"]): t for t in summary["rows"]}
    assert not by_cycle[(1, 50.0)]["at_capacity"]
    assert by_cycle[(2, 40.0)]["at_capacity"]


def test_no_capacity_set_preserves_existing_behavior():
    rows = [
        _menu_row(1, status="closed_profit", realized=50.0),
        _menu_row(2, status="closed_profit", realized=40.0),
    ]
    summary = shadow_book.regret_summary(rows)
    assert summary["dropped_count"] == 2
    assert summary["dropped_total_usd"] == 90.0
    assert summary["cap_window_count"] == 0
    assert all(not t["at_capacity"] for t in summary["rows"])


def test_resolved_dropped_cycles_skips_capacity_rows():
    rows = [
        _menu_row(1, status="closed_profit", realized=50.0),
        _menu_row(2, status="closed_profit", realized=40.0),
    ]
    summary = shadow_book.regret_summary(rows, capacity_cycles={2})
    # Cycle 2 resolved profitable but the judge never saw it — there is no
    # drop reasoning in its journal to classify, so it must not be fetched.
    assert shadow_book.resolved_dropped_cycles(summary["rows"]) == [1]

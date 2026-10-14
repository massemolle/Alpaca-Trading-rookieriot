"""D25 stack cap fires pre-LLM with the DB's direction vocabulary — offline.

The cap count dict in bot.find_candidates is keyed by the live rows'
direction ('bull_put'/'bear_call'), but until 2026-10-14 the lookup used
sig.direction ('long'/'short'), so same_direction_count was always 0 and
the pre-LLM D25 check could never fire — a 3rd XLE bull_put reached the
judge four cycles running on 2026-10-14 while the post-LLM gate rejected
it at the cap every time. These tests run find_candidates end-to-end
against a live book of stacked verticals and pin the vocabulary mapping:
a 'long' signal builds a bull_put and must be counted against bull_put
rows, and only against them.
"""
from __future__ import annotations

import asyncio
import dataclasses
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bot
import risk_gate
from signals.swing import Signal
from tests.conftest import make_plan


def _pin_risk(monkeypatch):
    # Caps and the DTE window are env-tunable and the gate sources .env —
    # pin them so these tests assert the cap logic, not the environment.
    risk = dataclasses.replace(
        risk_gate.config.risk,
        max_concurrent_spreads=8, min_dte=7, max_dte=21,
        max_per_underlying_direction=2,
    )
    cfg = dataclasses.replace(risk_gate.config, risk=risk)
    monkeypatch.setattr(risk_gate, "config", cfg)


def _live_row(direction: str, short_strike: float) -> dict:
    # Strikes differ from make_plan's 640/635 so the held-leg sets never
    # collide with the plan under test (build_spread is stubbed anyway).
    k = int(short_strike)
    opt = "P" if direction == "bull_put" else "C"
    return {
        "underlying": "SPY", "direction": direction, "status": "open",
        "contracts": 1, "max_loss": 350.0,
        "short_symbol": f"SPY261030{opt}00{k}000",
        "long_symbol": f"SPY261030{opt}00{k - 5}000",
    }


def _run_find_candidates(monkeypatch, *, live_rows: list[dict]):
    _pin_risk(monkeypatch)
    plan = make_plan()  # SPY bull_put — what a 'long' signal builds

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
    monkeypatch.setattr(bot.db, "get_live_spreads", lambda: live_rows)

    async def fake_build_spread(mcp, ticker, direction, **kwargs):
        return plan

    monkeypatch.setattr(bot, "build_spread", fake_build_spread)

    client = SimpleNamespace(
        get_latest_quote=lambda symbol: {"bid_price": 99.90, "ask_price": 100.10},
    )
    account = {"equity": 100_000.0, "daily_pl_pct": 0.0}
    return asyncio.run(bot.find_candidates(
        None, client, account, len(live_rows), capacity_waived=False,
    ))


def test_two_same_direction_rows_block_the_third_pre_llm(monkeypatch):
    candidates, rejections = _run_find_candidates(
        monkeypatch,
        live_rows=[_live_row("bull_put", 630), _live_row("bull_put", 625)],
    )
    assert candidates == []
    gate_rej = [r for r in rejections if r.get("stage") == "risk_gate"]
    assert len(gate_rej) == 1
    assert any("per-underlying/direction cap" in reason
               for reason in gate_rej[0]["reasons"])
    # The rejection must speak the DB vocabulary, like the post-LLM gate.
    assert any("bull_put" in reason for reason in gate_rej[0]["reasons"])


def test_opposite_direction_rows_do_not_count(monkeypatch):
    # Two live bear calls are a different bet — a bull put must pass.
    candidates, rejections = _run_find_candidates(
        monkeypatch,
        live_rows=[_live_row("bear_call", 660), _live_row("bear_call", 665)],
    )
    assert [c["ticker"] for c in candidates] == ["SPY"]
    assert all(r.get("stage") != "risk_gate" for r in rejections)


def test_one_same_direction_row_stays_under_cap(monkeypatch):
    candidates, rejections = _run_find_candidates(
        monkeypatch,
        live_rows=[_live_row("bull_put", 630)],
    )
    assert [c["ticker"] for c in candidates] == ["SPY"]
    assert all(r.get("stage") != "risk_gate" for r in rejections)

"""Live-tape facts for the judge (2026-11-25) — offline.

On the 11-24/11-25 gap-reversal days the judge asserted intraday direction
("the trend pushes price away from the short strike", c1081) while the
underlying rallied intraday; every such entry stopped same-day. The signals
are daily-bar computed and blind to the session, and no fact carried the
tape. These tests pin the fix: `_day_context` extracts previous close /
today's open from the filter's bars, find_candidates publishes
{TKR}_DAY_MOVE_PCT and {TKR}_FROM_OPEN_PCT when (and only when) the bars
support them, and the prompt glossary names both facts.
"""
from __future__ import annotations

import asyncio
import dataclasses
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bot
import llm_reasoner
import risk_gate
from signals.swing import Signal
from tests.conftest import make_plan


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ---------------------------------------------------------------------------
# _day_context extraction
# ---------------------------------------------------------------------------

def test_day_context_prev_close_and_today_open():
    bars = pd.DataFrame([
        {"timestamp": "2026-01-02 05:00:00+00:00", "open": 98.0, "close": 99.0},
        {"timestamp": "2026-01-03 05:00:00+00:00", "open": 99.5, "close": 100.0},
        {"timestamp": f"{_today()} 05:00:00+00:00", "open": 97.0, "close": 98.2},
    ])
    ctx = bot._day_context(bars)
    assert ctx == {"prev_close": 100.0, "today_open": 97.0}


def test_day_context_without_todays_bar_omits_open():
    # IEX may not print today's in-progress daily bar — prev close must
    # still resolve from the last prior session, today_open stays None.
    bars = pd.DataFrame([
        {"timestamp": "2026-01-02 05:00:00+00:00", "open": 98.0, "close": 99.0},
        {"timestamp": "2026-01-03 05:00:00+00:00", "open": 99.5, "close": 100.0},
    ])
    ctx = bot._day_context(bars)
    assert ctx == {"prev_close": 100.0, "today_open": None}


def test_day_context_degrades_to_none_without_timestamps():
    # The funnel tests' fake bars have no timestamp/open columns; empty
    # frames happen on fetch failures. Both must yield Nones, never raise.
    assert bot._day_context(pd.DataFrame()) == {"prev_close": None, "today_open": None}
    bars = pd.DataFrame([{"close": 100.0, "high": 101.0, "low": 99.0}])
    assert bot._day_context(bars) == {"prev_close": None, "today_open": None}


# ---------------------------------------------------------------------------
# find_candidates publishes the facts from the day context
# ---------------------------------------------------------------------------

def _pin_risk(monkeypatch):
    risk = dataclasses.replace(
        risk_gate.config.risk, max_concurrent_spreads=8, min_dte=7, max_dte=21,
    )
    cfg = dataclasses.replace(risk_gate.config, risk=risk)
    monkeypatch.setattr(risk_gate, "config", cfg)


def _run_find_candidates(monkeypatch, day_ctx: dict):
    _pin_risk(monkeypatch)
    plan = make_plan()

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
        lambda client, signals: ([(s, 0.15, day_ctx) for s in signals], []),
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
        None, client, account, 0, capacity_waived=False,
    ))


def _facts_by_id(candidate: dict) -> dict:
    return {f["fact_id"]: f for f in candidate["facts"]}


def test_tape_facts_published_with_full_day_context(monkeypatch):
    # spot mid is 100.00 (99.90/100.10): −2% vs a 102.04 prev close,
    # +1% off a 99.0099 open — the gap-down-then-bounce shape of 11-25.
    candidates, _ = _run_find_candidates(
        monkeypatch, {"prev_close": 102.04, "today_open": 99.0099})
    assert len(candidates) == 1
    facts = _facts_by_id(candidates[0])
    assert facts["SPY_DAY_MOVE_PCT"]["value"] == -2.0
    assert facts["SPY_FROM_OPEN_PCT"]["value"] == 1.0


def test_tape_facts_omitted_not_zeroed_without_bars(monkeypatch):
    # No usable day context → the candidate still reaches the judge, with
    # the tape facts absent (the prompt tells the judge absence = unknown).
    candidates, _ = _run_find_candidates(
        monkeypatch, {"prev_close": None, "today_open": None})
    assert len(candidates) == 1
    facts = _facts_by_id(candidates[0])
    assert "SPY_DAY_MOVE_PCT" not in facts
    assert "SPY_FROM_OPEN_PCT" not in facts


def test_from_open_alone_can_be_absent(monkeypatch):
    candidates, _ = _run_find_candidates(
        monkeypatch, {"prev_close": 102.04, "today_open": None})
    facts = _facts_by_id(candidates[0])
    assert facts["SPY_DAY_MOVE_PCT"]["value"] == -2.0
    assert "SPY_FROM_OPEN_PCT" not in facts


# ---------------------------------------------------------------------------
# prompt glossary
# ---------------------------------------------------------------------------

def test_prompt_names_the_tape_facts():
    # The judge can only cite facts the prompt teaches it to read; the
    # glossary must name both ids and tie them to intraday claims.
    p = llm_reasoner.SYSTEM_PROMPT
    assert "_DAY_MOVE_PCT" in p
    assert "_FROM_OPEN_PCT" in p
    assert "DAILY bars" in p


def test_prompt_forbids_uncited_intraday_claims():
    # The 11-25 failure shape: asserting what price is doing today with no
    # fact. The glossary must bind intraday claims to the tape facts and
    # keep an against-tape read a haircut, not a veto (11-19 tune intact).
    p = llm_reasoner.SYSTEM_PROMPT
    assert "without citing one of these" in p
    assert "not an automatic veto" in p

"""Premium-buyer sleeve (podium lessons) — offline tests."""
from __future__ import annotations

import pytest

import rhetoric
from premium_buyer import brier, config as pcfg, executor
from premium_buyer.builder import build_buy
from tests.test_spread_builder_otm import ChainMCP, _contract
from tests.conftest import snapshot


# ---- rhetoric audit (new addition #1) ---------------------------------------

def _cands():
    return [{"ticker": "SPY", "facts": [
        {"fact_id": "SPY_PREMIUM", "value": 250.0},
        {"fact_id": "SPY_PRICE_RATIO", "value": 1.2},
    ]}]


def test_rhetoric_accepts_accurate_quotes():
    assert rhetoric.audit_values(_cands(), "paying $250 [SPY_PREMIUM] at ratio 1.2 [SPY_PRICE_RATIO]") == []


def test_rhetoric_catches_misquote():
    flags = rhetoric.audit_values(_cands(), "a cheap $120 [SPY_PREMIUM] entry")
    assert flags and "misquotes" in flags[0]


def test_rhetoric_catches_unknown_fact():
    flags = rhetoric.audit_values(_cands(), "IV rank 80 [SPY_IV_RANK]")
    assert flags and "unknown fact" in flags[0]


def test_alignment_blocks_self_contradiction():
    flags = rhetoric.audit_alignment([{"ticker": "SPY", "p_move": 0.40}], min_p=0.55)
    assert flags and "contradicts belief" in flags[0]
    assert rhetoric.audit_alignment([{"ticker": "SPY", "p_move": 0.70}], min_p=0.55) == []
    assert rhetoric.audit_alignment([{"ticker": "SPY"}], min_p=0.55)  # missing p flagged


# ---- Brier (new addition #2) -------------------------------------------------

def test_brier_scoring_math():
    # long call, +2% move, threshold 1% -> outcome 1; p=0.7 -> (0.7-1)^2=0.09
    assert brier.score(0.7, "long", 100.0, 102.0, 1.0) == (1, 0.09)
    # long, flat market -> outcome 0; p=0.7 -> 0.49
    assert brier.score(0.7, "long", 100.0, 100.2, 1.0) == (0, 0.49)
    # short direction mirrors
    assert brier.score(0.6, "short", 100.0, 98.5, 1.0)[0] == 1


# ---- executor ids ------------------------------------------------------------

def test_premium_order_ids_idempotent_within_hour():
    a = executor._cid("open", "SPY261016C00770000", 1)
    b = executor._cid("open", "SPY261016C00770000", 1)
    c = executor._cid("open", "SPY261016C00770000", 2)
    assert a == b and a != c


# ---- builder richness gate ---------------------------------------------------

def _chain_with_quotes(ticker, right, strike_quotes, expiration):
    contracts, snaps = [], {}
    for strike, (bid, ask) in strike_quotes.items():
        c = _contract(ticker, right, strike, expiration)
        contracts.append(c)
        snaps[c["symbol"]] = snapshot(bid, ask)
    return contracts, snaps


@pytest.mark.asyncio
async def test_builder_rejects_rich_premium(monkeypatch):
    # Quote mid ~6.0 but BS fair ~ small at low vol -> ratio >> cap -> no plan.
    from datetime import date, timedelta
    exp = (date.today() + timedelta(days=9)).isoformat()
    contracts, snaps = _chain_with_quotes("TSTP", "call", {104.0: (5.9, 6.1)}, exp)
    plan, why = await build_buy(ChainMCP(contracts, snaps), "TSTP", "long",
                                spot=100.0, realized_vol=0.10)
    assert plan is None and "fairly-priced" in why


@pytest.mark.asyncio
async def test_builder_accepts_fair_premium():
    from datetime import date, timedelta
    from black_scholes import bs_price
    exp_d = date.today() + timedelta(days=9)
    fair = bs_price(spot=100.0, strike=102.0, dte_days=9, volatility=0.35, option_type="call")
    bid, ask = round(fair * 0.97, 2), round(fair * 1.03, 2)
    contracts, snaps = _chain_with_quotes("TSTQ", "call", {102.0: (bid, ask)}, exp_d.isoformat())
    plan, why = await build_buy(ChainMCP(contracts, snaps), "TSTQ", "long",
                                spot=100.0, realized_vol=0.35)
    assert plan is not None, why
    assert plan.direction == "call" and plan.price_ratio <= pcfg.RICHNESS_CAP
    assert any(f["fact_id"] == "TSTQ_PRICE_RATIO" for f in plan.facts)


# ---- reconciler exclusion ----------------------------------------------------

def test_reconciler_excludes_buyer_legs(monkeypatch):
    import reconciler as rec
    monkeypatch.setattr(rec, "_premium_leg_quantities",
                        lambda: {"SPY261016C00770000": 1})
    positions = [
        {"symbol": "SPY261016C00770000", "side": "long", "qty": 1.0},   # buyer's — drop
        {"symbol": "QQQ260914C00725000", "side": "short", "qty": 2.0},  # credit bot's — keep
    ]
    out = rec._exclude_foreign_legs(positions)
    assert len(out) == 1 and out[0]["symbol"].startswith("QQQ")


def test_reconciler_partial_overlap_reduces_qty(monkeypatch):
    import reconciler as rec
    monkeypatch.setattr(rec, "_premium_leg_quantities",
                        lambda: {"SPY261016C00770000": 1})
    positions = [{"symbol": "SPY261016C00770000", "side": "long", "qty": 3.0}]
    out = rec._exclude_foreign_legs(positions)
    assert len(out) == 1 and out[0]["qty"] == 2.0


# ---- credit-sleeve podium upgrades -------------------------------------------

def test_normalize_selected_accepts_both_shapes():
    import llm_reasoner
    tk, p = llm_reasoner.normalize_selected([{"ticker": "SPY", "p_win": 0.7}, "QQQ"])
    assert tk == ["SPY", "QQQ"]
    assert p["SPY"] == 0.7 and p["QQQ"] is None
    assert llm_reasoner.normalize_selected([]) == ([], {})
    assert llm_reasoner.normalize_selected([{"no_ticker": 1}]) == ([], {})


def test_credit_brier_math():
    import credit_forecasts
    assert credit_forecasts.brier(0.8, 1) == 0.04
    assert credit_forecasts.brier(0.8, 0) == 0.64
    assert credit_forecasts.brier(0.5, 1) == 0.25  # coin flip reference

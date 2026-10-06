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


# Grouped citations (c449 2026-10-05 false block): numbers and tags pair
# positionally, not nearest-number-to-each-tag.

def _iwm_cands():
    return [{"ticker": "IWM", "facts": [
        {"fact_id": "IWM_CREDIT_EST", "value": 85.5},
        {"fact_id": "IWM_MAX_LOSS", "value": 414.5},
    ]}]


def test_rhetoric_slash_pair_adjacent_brackets_pairs_positionally():
    # Verbatim shape that produced the c449 false block.
    text = "best raw risk/reward ($85.5/$414.5 [IWM_CREDIT_EST][IWM_MAX_LOSS])"
    assert rhetoric.audit_values(_iwm_cands(), text) == []


def test_rhetoric_slash_pair_comma_list_pairs_positionally():
    text = "thin reward: $85.5/$414.5 [IWM_CREDIT_EST, IWM_MAX_LOSS] today"
    assert rhetoric.audit_values(_iwm_cands(), text) == []


def test_rhetoric_still_catches_swapped_pair():
    text = "risk/reward $414.5/$85.5 [IWM_CREDIT_EST][IWM_MAX_LOSS]"
    flags = rhetoric.audit_values(_iwm_cands(), text)
    assert len(flags) == 2 and all("misquotes" in f for f in flags)


def test_rhetoric_single_number_multi_tag_matches_any():
    # One number against a tag group: fine if it matches one of them...
    assert rhetoric.audit_values(
        _iwm_cands(), "only $414.5 [IWM_CREDIT_EST, IWM_MAX_LOSS] at risk") == []
    # ...flagged when it matches none.
    flags = rhetoric.audit_values(
        _iwm_cands(), "only $999 [IWM_CREDIT_EST, IWM_MAX_LOSS] at risk")
    assert flags and "misquotes" in flags[0]


def test_rhetoric_ambiguous_count_mismatch_not_flagged():
    # 2 numbers vs 3 tags: pairing is ambiguous — no value flags.
    cands = [{"ticker": "IWM", "facts": [
        {"fact_id": "IWM_CREDIT_EST", "value": 85.5},
        {"fact_id": "IWM_MAX_LOSS", "value": 414.5},
        {"fact_id": "IWM_DTE", "value": 10},
    ]}]
    text = "$1/$2 [IWM_CREDIT_EST, IWM_MAX_LOSS, IWM_DTE]"
    assert rhetoric.audit_values(cands, text) == []


def test_rhetoric_thousands_separator_parsed():
    cands = [{"ticker": "IWM", "facts": [{"fact_id": "IWM_OPEN_MAX_LOSS", "value": 1257.5}]}]
    assert rhetoric.audit_values(cands, "carrying $1,257.5 [IWM_OPEN_MAX_LOSS]") == []


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


# ---- executor order shape (2026-10-06: every live submit of the sleeve's
# first two days was 422-rejected, code 40010001 "either side or
# position_intent must be set" — the payload used the mleg `legs` shape for
# an order_class=simple order; alpaca-py's OrderRequest documents symbol and
# side/position_intent as top-level requirements for every class but mleg) --

class _OrderMCP:
    def __init__(self, result=None, raise_exc=None):
        self.result = result if result is not None else {
            "id": "ord-1", "status": "accepted", "filled_avg_price": None}
        self.raise_exc = raise_exc
        self.calls = []

    async def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.result


@pytest.mark.asyncio
async def test_premium_buy_payload_is_toplevel_single_leg(monkeypatch):
    monkeypatch.setattr(pcfg, "DRY_RUN", False)
    mcp = _OrderMCP()
    res = await executor.buy(mcp, "SPY261014C00784000", 1, 3.15)
    tool, args = mcp.calls[0]
    assert tool == "place_option_order"
    assert "legs" not in args  # legs is the mleg-only shape
    assert args["symbol"] == "SPY261014C00784000"
    assert args["side"] == "buy" and args["position_intent"] == "buy_to_open"
    assert args["order_class"] == "simple" and args["type"] == "limit"
    assert args["limit_price"] == str(round(3.15 * 1.05, 2))
    assert args["qty"] == "1" and args["time_in_force"] == "day"
    assert args["client_order_id"].startswith("prem-open-")
    assert res is not None and res["id"] == "ord-1"


@pytest.mark.asyncio
async def test_premium_sell_payload_is_toplevel_single_leg(monkeypatch):
    monkeypatch.setattr(pcfg, "DRY_RUN", False)
    mcp = _OrderMCP()
    res = await executor.sell_to_close(mcp, "SPY261014C00784000", 1, 4.00)
    tool, args = mcp.calls[0]
    assert tool == "place_option_order"
    assert "legs" not in args
    assert args["symbol"] == "SPY261014C00784000"
    assert args["side"] == "sell" and args["position_intent"] == "sell_to_close"
    assert args["order_class"] == "simple"
    assert args["limit_price"] == str(round(4.00 * 0.95, 2))
    assert res is not None


@pytest.mark.asyncio
async def test_premium_buy_api_rejection_returns_none(monkeypatch):
    # The literal 2026-10-05/06 rejection shape must map to None (no fill),
    # never to a recorded position.
    monkeypatch.setattr(pcfg, "DRY_RUN", False)
    mcp = _OrderMCP(result={"error": {
        "message": "API rejected the order", "http_status": 422,
        "detail": {"code": 40010001,
                   "message": "either side or position_intent must be set"}}})
    assert await executor.buy(mcp, "NVDA261012C00242500", 1, 2.04) is None


@pytest.mark.asyncio
async def test_premium_orders_fail_closed_on_tool_exception(monkeypatch):
    # A tool-level error (e.g. schema mismatch raised by mcp.call) must not
    # propagate out of the executor — run.cycle() calls buy() mid-loop.
    monkeypatch.setattr(pcfg, "DRY_RUN", False)
    mcp = _OrderMCP(raise_exc=RuntimeError("Alpaca MCP tool failed"))
    assert await executor.buy(mcp, "SPY261014C00784000", 1, 3.15) is None
    assert await executor.sell_to_close(mcp, "SPY261014C00784000", 1, 3.15) is None


@pytest.mark.asyncio
async def test_premium_dry_run_places_no_order(monkeypatch):
    monkeypatch.setattr(pcfg, "DRY_RUN", True)
    mcp = _OrderMCP()
    res = await executor.buy(mcp, "SPY261014C00784000", 1, 3.15)
    assert mcp.calls == [] and res["status"] == "dry_run"


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

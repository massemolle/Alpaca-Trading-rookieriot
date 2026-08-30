"""Regression tests for a real sign bug in _extract_filled_avg_price
(fixed 2026-08-30, see its docstring in executor_mcp.py for the full
writeup): Alpaca's top-level filled_avg_price for a net-credit mleg order
uses the OPPOSITE sign convention from this project's credit_received/
fill_credit (negative = credit, "cost to acquire"). A naive `float(avg)`
read of that field -- what this function did before this fix -- would
record every real credit open as a NEGATIVE credit, and (via
close_spread's fill_debit, which reuses the same extraction) would
silently invert the sign of every real close's debit, inflating
bot.py's `realized_pnl = credit_received - close_debit` instead of
correctly subtracting it.

No test previously covered this at all -- these numbers are the real
NVDA iron condor order (short put 0.93, long put 0.59, short call 0.54,
long call 0.34 -> net credit $0.54/share) fetched live from a sibling
project sharing this exact alpaca-mcp-server integration, confirming the
real top-level value for that order was -0.54.
"""
from __future__ import annotations

import pytest

from executor_mcp import (
    OrderResult,
    _extract_filled_avg_price,
    close_spread,
    open_spread,
)
from tests.conftest import FakeMCP, make_plan


class _RecordingMCP(FakeMCP):
    """Extends the shared FakeMCP to also answer place_option_order."""

    def __init__(self, place_order_response: dict):
        super().__init__()
        self._place_order_response = place_order_response

    async def call(self, tool: str, arguments: dict):
        self.calls.append((tool, arguments))
        if tool == "place_option_order":
            return self._place_order_response
        return await super().call(tool, arguments)


def test_top_level_filled_avg_price_is_negated():
    """Real value from the real order: top-level -0.54 for an actual
    $0.54/share credit received. A naive positive read would be wrong."""
    result = {"data": {"id": "o1", "status": "filled", "filled_avg_price": "-0.54"}}
    assert _extract_filled_avg_price(result) == pytest.approx(0.54)


def test_per_leg_matches_a_real_two_leg_vertical():
    """This project's spreads are always exactly 2 legs (one short, one
    long) -- per-leg computation already gave the correct sign for that
    shape before this fix; this is a sanity check, not new behavior."""
    result = {"data": {"id": "o1", "status": "filled", "legs": [
        {"symbol": "SPY260911P00640000", "side": "sell", "filled_avg_price": "0.93"},
        {"symbol": "SPY260911P00635000", "side": "buy", "filled_avg_price": "0.59"},
    ]}}
    assert _extract_filled_avg_price(result) == pytest.approx(0.34)


def test_per_leg_sums_not_averages_across_multiple_legs_per_side():
    """Separate real bug fixed alongside the sign issue: the per-leg
    computation averaged each side's fill prices (`/ len(...)`) instead of
    summing them. Currently dormant for this project (spreads are always
    exactly 1 leg per side, where sum == average), but would silently
    halve the credit for any structure with more than one leg per side.
    Uses the real NVDA order from the docstring above (2 credit legs, 2
    debit legs, real net credit $0.54/share) as the regression case."""
    result = {"data": {"id": "o1", "status": "filled", "legs": [
        {"symbol": "NVDA260909P00205000", "side": "sell", "filled_avg_price": "0.93"},
        {"symbol": "NVDA260909P00200000", "side": "buy", "filled_avg_price": "0.59"},
        {"symbol": "NVDA260909C00240000", "side": "sell", "filled_avg_price": "0.54"},
        {"symbol": "NVDA260909C00245000", "side": "buy", "filled_avg_price": "0.34"},
    ]}}
    assert _extract_filled_avg_price(result) == pytest.approx(0.54)


@pytest.mark.asyncio
async def test_open_spread_records_a_positive_credit():
    """Immediate fill, top-level-only response (no legs) -- the exact
    shape that triggered the bug. Must come back POSITIVE."""
    mcp = _RecordingMCP({
        "data": {"id": "o1", "status": "filled", "filled_avg_price": "-1.40"},
    })
    plan = make_plan(credit_estimate=150.0)

    order = await open_spread(mcp, plan, contracts=1)

    assert isinstance(order, OrderResult)
    assert order.fill_credit == pytest.approx(140.0)


@pytest.mark.asyncio
async def test_close_spread_records_a_positive_debit_not_a_negative_credit():
    """The critical case: closing legs shaped exactly like a real buy-to-
    close/sell-to-close pair. Before this fix, fill_debit came back
    NEGATIVE here (the raw net-received value, un-negated) -- silently
    flipping the sign of realized_pnl for every real close."""
    mcp = _RecordingMCP({
        "data": {"id": "o1", "status": "filled", "legs": [
            # Buying back the short leg costs more than selling the long
            # leg returns -- a real $1.50/share debit to close.
            {"symbol": "SPY260911P00640000", "side": "buy", "filled_avg_price": "2.00"},
            {"symbol": "SPY260911P00635000", "side": "sell", "filled_avg_price": "0.50"},
        ]},
    })

    order = await close_spread(mcp, "SPY260911P00640000", "SPY260911P00635000", contracts=1)

    assert order.fill_credit == pytest.approx(150.0), (
        f"expected a positive $150/contract debit, got {order.fill_credit} -- "
        "sign regression in close_spread's fill_debit"
    )


@pytest.mark.asyncio
async def test_realized_pnl_uses_the_corrected_positive_debit():
    """End-to-end sanity matching bot.py's own formula
    (realized_pnl = credit_received - close_debit): a spread opened for
    $150/contract credit, closed at the $150/contract debit above, must
    net to ~$0 -- not double-count as a ~$300 profit, which is what the
    pre-fix negative-debit bug would have produced."""
    mcp = _RecordingMCP({
        "data": {"id": "o1", "status": "filled", "legs": [
            {"symbol": "SPY260911P00640000", "side": "buy", "filled_avg_price": "2.00"},
            {"symbol": "SPY260911P00635000", "side": "sell", "filled_avg_price": "0.50"},
        ]},
    })
    order = await close_spread(mcp, "SPY260911P00640000", "SPY260911P00635000", contracts=1)

    credit_received = 150.0
    realized_pnl = credit_received - order.fill_credit  # bot.py's own formula
    assert realized_pnl == pytest.approx(0.0)

"""Held-leg collision avoidance (2026-09-18 nightly finding, cycle 266).

Live incident: with QQQ 705/700 (exp 09-28) open — the account LONG the
700P — the builder proposed QQQ 700/695 on the same expiration. Its short
leg sells the very contract the book is long, so Alpaca inferred
sell_to_close against our specified sell_to_open and 422-rejected the whole
order ("position intent mismatch", code 42210000), erasing the judge's pick
for the cycle. Had it filled, it would have stripped the hedge off the
existing spread. The builder now skips any (short, long) pair that would
SELL a held-long or BUY a held-short contract, falling through to the next
short in delta order. Re-adding to a SAME-side position (stacking the
identical spread, as cycle 267's 705/700 did successfully) must stay
allowed — that keeps matching open intents at the broker.
"""
from __future__ import annotations

import pytest

import spread_builder
from spread_builder import build_spread
from tests.test_spread_builder_otm import ChainMCP, _chain, _contract


@pytest.fixture(autouse=True)
def _clear_contract_cache():
    spread_builder._contract_cache.clear()
    yield
    spread_builder._contract_cache.clear()


def _sym(ticker: str, option_type: str, strike: float) -> str:
    # The fake-chain symbol for a strike (expiration not encoded in the fake).
    return _contract(ticker, option_type, strike, "unused")["symbol"]


# Bull-put chain, spot 100: unconstrained the builder picks 95/90 (pinned by
# test_spread_builder_otm/_long_leg). All quotes pass both liquidity gates.
_QUOTES = {
    95.0: (1.00, 1.10),
    90.0: (0.40, 0.45),
    85.0: (0.15, 0.165),
}


@pytest.mark.asyncio
async def test_no_held_legs_builds_the_usual_spread():
    contracts, snaps = _chain("TSTG", "put", _QUOTES)
    plan = await build_spread(ChainMCP(contracts, snaps), "TSTG", "long",
                              spot_price=100.0, realized_vol=0.30)
    assert plan is not None
    assert plan.short_strike == 95.0 and plan.long_strike == 90.0


@pytest.mark.asyncio
async def test_short_leg_selling_a_held_long_falls_through():
    # The cycle-266 shape: the delta-best short (95P) is a contract the book
    # holds LONG. Selling it would be inferred sell_to_close → the whole
    # candidate pair is skipped and the next short (90) builds 90/85.
    contracts, snaps = _chain("TSTH", "put", _QUOTES)
    plan = await build_spread(
        ChainMCP(contracts, snaps), "TSTH", "long",
        spot_price=100.0, realized_vol=0.30,
        held_long_symbols={_sym("TSTH", "put", 95.0)},
    )
    assert plan is not None
    assert plan.short_strike == 90.0 and plan.long_strike == 85.0


@pytest.mark.asyncio
async def test_long_leg_buying_a_held_short_skips_the_pair():
    # 95's snapped long (90P) is a contract the book holds SHORT: buying it
    # would be inferred buy_to_close, so 95/90 is skipped as a pair. 90 is
    # still a legal SHORT leg (adding to an existing short position keeps
    # sell_to_open valid) → 90/85 builds.
    contracts, snaps = _chain("TSTI", "put", _QUOTES)
    plan = await build_spread(
        ChainMCP(contracts, snaps), "TSTI", "long",
        spot_price=100.0, realized_vol=0.30,
        held_short_symbols={_sym("TSTI", "put", 90.0)},
    )
    assert plan is not None
    assert plan.short_strike == 90.0 and plan.long_strike == 85.0


@pytest.mark.asyncio
async def test_identical_restack_stays_allowed():
    # Cycle-267 behavior pinned: the book already holds 95/90 (short 95P,
    # long 90P). Opening the identical spread re-adds on the SAME side of
    # each contract — no intent mismatch — and must still build.
    contracts, snaps = _chain("TSTJ", "put", _QUOTES)
    plan = await build_spread(
        ChainMCP(contracts, snaps), "TSTJ", "long",
        spot_price=100.0, realized_vol=0.30,
        held_short_symbols={_sym("TSTJ", "put", 95.0)},
        held_long_symbols={_sym("TSTJ", "put", 90.0)},
    )
    assert plan is not None
    assert plan.short_strike == 95.0 and plan.long_strike == 90.0


@pytest.mark.asyncio
async def test_every_viable_short_colliding_builds_nothing():
    # 95 and 90 are both held long; 85 has no further-OTM long available.
    # Exhaustion must yield no plan — never a colliding one.
    contracts, snaps = _chain("TSTK", "put", _QUOTES)
    plan = await build_spread(
        ChainMCP(contracts, snaps), "TSTK", "long",
        spot_price=100.0, realized_vol=0.30,
        held_long_symbols={_sym("TSTK", "put", 95.0), _sym("TSTK", "put", 90.0)},
    )
    assert plan is None

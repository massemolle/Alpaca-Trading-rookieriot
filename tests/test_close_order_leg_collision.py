"""Working-close-order leg collision (2026-10-12 nightly finding, cycle 536).

Live incident: at 15:30:08Z the profit-target close for XLF 54/49 (spread id
78) was submitted — buy-to-close XLF261023P00054000, sell-to-close
XLF261023P00049000 — and rested, parking the row in pending_close. At
15:31:51Z the judge's "add on conviction" pick rebuilt the IDENTICAL legs,
so the open order tried to sell-to-open the 54P and buy-to-open the 49P:
opposite-side orders on the same contracts, which Alpaca 403-rejected as a
potential wash trade (code 40310000, "opposite side market/stop order
exists") and the cycle recorded decision 'error'. The combination was also
economically incoherent — paying $0.23 to close while re-selling the
identical spread at a $0.21 minimum credit. The builder now skips any pair
whose short leg has a working buy-to-close or whose long leg has a working
sell-to-close, falling through to the next short in delta order (the 55/50
that filled cleanly at cycle 538, one cycle later). A merely-open identical
restack — no close order working — must STAY allowed, as pinned by
test_spread_builder_leg_collision.test_identical_restack_stays_allowed.
"""
from __future__ import annotations

import re
from pathlib import Path

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
    return _contract(ticker, option_type, strike, "unused")["symbol"]


# Bull-put chain, spot 100: unconstrained the builder picks 95/90 (pinned by
# test_spread_builder_otm/_long_leg). All quotes pass both liquidity gates.
_QUOTES = {
    95.0: (1.00, 1.10),
    90.0: (0.40, 0.45),
    85.0: (0.15, 0.165),
    80.0: (0.06, 0.066),
}


@pytest.mark.asyncio
async def test_no_closing_legs_builds_the_usual_spread():
    contracts, snaps = _chain("TSTL", "put", _QUOTES)
    plan = await build_spread(ChainMCP(contracts, snaps), "TSTL", "long",
                              spot_price=100.0, realized_vol=0.30)
    assert plan is not None
    assert plan.short_strike == 95.0 and plan.long_strike == 90.0


@pytest.mark.asyncio
async def test_short_leg_with_working_buy_to_close_falls_through():
    # A buy-to-close is working on the 95P (its spread is pending_close).
    # Selling it to open would put opposite-side orders on one contract —
    # the pair is skipped and the next short builds 90/85.
    contracts, snaps = _chain("TSTM", "put", _QUOTES)
    plan = await build_spread(
        ChainMCP(contracts, snaps), "TSTM", "long",
        spot_price=100.0, realized_vol=0.30,
        closing_short_symbols={_sym("TSTM", "put", 95.0)},
    )
    assert plan is not None
    assert plan.short_strike == 90.0 and plan.long_strike == 85.0


@pytest.mark.asyncio
async def test_long_leg_with_working_sell_to_close_skips_the_pair():
    # A sell-to-close is working on the 90P. Buying it to open collides, so
    # 95/90 is skipped as a pair. 90 stays a legal SHORT leg (a new sell
    # matches the close order's own side — no opposite-side conflict) →
    # 90/85 builds.
    contracts, snaps = _chain("TSTN", "put", _QUOTES)
    plan = await build_spread(
        ChainMCP(contracts, snaps), "TSTN", "long",
        spot_price=100.0, realized_vol=0.30,
        closing_long_symbols={_sym("TSTN", "put", 90.0)},
    )
    assert plan is not None
    assert plan.short_strike == 90.0 and plan.long_strike == 85.0


@pytest.mark.asyncio
async def test_cycle_536_shape_builds_the_next_clean_pair():
    # The literal incident: the book holds 95/90 (short 95P, long 90P) AND
    # its close order is resting. Held sets alone would allow the identical
    # restack (cycle-267 exemption); the closing sets must block it. 95 is
    # out as a short (buy-to-close working), 90 is out as a short (held
    # long), so the first clean pair is 85/80 — a real plan, not an error.
    contracts, snaps = _chain("TSTO", "put", _QUOTES)
    plan = await build_spread(
        ChainMCP(contracts, snaps), "TSTO", "long",
        spot_price=100.0, realized_vol=0.30,
        held_short_symbols={_sym("TSTO", "put", 95.0)},
        held_long_symbols={_sym("TSTO", "put", 90.0)},
        closing_short_symbols={_sym("TSTO", "put", 95.0)},
        closing_long_symbols={_sym("TSTO", "put", 90.0)},
    )
    assert plan is not None
    assert plan.short_strike == 85.0 and plan.long_strike == 80.0


def test_bot_feeds_closing_legs_from_pending_close_rows_only():
    """Pin bot.py's wiring in source (idiom: test_cap_single_count).

    - the closing sets are populated only for status == 'pending_close';
    - every build_spread call site passes both closing sets through.
    """
    src = Path(__file__).resolve().parent.parent.joinpath("bot.py").read_text()
    guard = src.index('if s.get("status") == "pending_close":')
    closing_fill = src.index("closing.add(s[key])")
    assert guard < closing_fill, "closing sets must be gated on pending_close"
    build_calls = re.findall(r"build_spread\(", src)
    assert build_calls, "build_spread call site not found in bot.py"
    assert src.count("closing_short_symbols=closing_short_symbols") == len(build_calls)
    assert src.count("closing_long_symbols=closing_long_symbols") == len(build_calls)

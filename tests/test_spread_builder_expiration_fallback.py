"""Expiration fallback: "nearest expiration THAT BUILDS" (2026-09-10 nightly).

The builder used to commit to the single nearest expiration in the DTE
window; if that chain couldn't produce a proper spread the whole ticker died
for the cycle even when the next expiration built cleanly. GLD 2026-09-09:
the 09-21 chain topped out at 420, so after the same-strike-snap fix the
only buildable spreads were width-1 (~$10-20 credit vs ~$85 max loss) — the
correct 419/424-shaped spread lived on the next expiration up.

Rules pinned here:
- expirations are tried nearest-first; the first ON-WIDTH plan (strike width
  within WIDTH_TOLERANCE of spread_width_dollars) wins immediately,
- an off-width plan is kept only as a last resort when no attempted
  expiration builds on-width (never worse than the pre-fallback builder),
- at most MAX_EXPIRATION_ATTEMPTS expirations are attempted (bounds
  snapshot-endpoint load on junk chains).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

import spread_builder
from spread_builder import build_spread
from config import config
from tests.conftest import snapshot
from tests.test_spread_builder_otm import ChainMCP, _contract


@pytest.fixture(autouse=True)
def _clear_contract_cache():
    spread_builder._contract_cache.clear()
    yield
    spread_builder._contract_cache.clear()


def _exp(offset_days: int) -> str:
    return (date.today() + timedelta(days=offset_days)).isoformat()


# Two expirations inside the [min_dte, max_dte] window, nearest first.
NEAR = config.risk.min_dte + 2
FAR = config.risk.min_dte + 8


def _multi_chain(ticker: str, option_type: str,
                 per_exp: dict[str, dict[float, tuple[float, float] | None]]):
    """Like test_spread_builder_otm._chain but spanning several expirations.
    Symbols get the expiration digits appended so the same strike on two
    expirations doesn't collide in the snapshot dict."""
    contracts, snaps = [], {}
    for exp, quotes in per_exp.items():
        for strike, quote in quotes.items():
            c = _contract(ticker, option_type, strike, exp)
            c = dict(c, symbol=f"{c['symbol']}X{exp.replace('-', '')}")
            contracts.append(c)
            bid, ask = quote if quote is not None else (0.2, 1.8)
            snaps[c["symbol"]] = snapshot(bid, ask)
    return contracts, snaps


# The GLD chain-top shape: only width-1 buildable at the nearest expiration.
_CHAIN_TOP = {109.0: (0.50, 0.55), 110.0: (0.30, 0.33)}
# A healthy shape that builds a full-width spread (110/115 at these deltas).
_FULL_WIDTH = {105.0: (1.00, 1.10), 110.0: (0.45, 0.50), 115.0: (0.20, 0.22)}


@pytest.mark.asyncio
async def test_chain_top_width1_defers_to_next_expiration():
    contracts, snaps = _multi_chain("TSTG", "call", {
        _exp(NEAR): _CHAIN_TOP,
        _exp(FAR): _FULL_WIDTH,
    })
    plan = await build_spread(ChainMCP(contracts, snaps), "TSTG", "short",
                              spot_price=100.0, realized_vol=0.30)
    assert plan is not None
    assert plan.expiration.isoformat() == _exp(FAR)
    assert abs(plan.short_strike - plan.long_strike) == config.risk.spread_width_dollars


@pytest.mark.asyncio
async def test_unbuildable_nearest_expiration_falls_through():
    # Nearest expiration is a single chain-edge strike: no spread possible
    # at all there. Pre-fallback the ticker died; now the next builds.
    contracts, snaps = _multi_chain("TSTH", "call", {
        _exp(NEAR): {110.0: (0.9, 1.1)},
        _exp(FAR): _FULL_WIDTH,
    })
    plan = await build_spread(ChainMCP(contracts, snaps), "TSTH", "short",
                              spot_price=100.0, realized_vol=0.30)
    assert plan is not None
    assert plan.direction == "bear_call"
    assert plan.expiration.isoformat() == _exp(FAR)


@pytest.mark.asyncio
async def test_on_width_nearest_expiration_wins_immediately():
    # Both expirations build on-width: the nearest must win (theta priority
    # unchanged) — the fallback never defers a healthy chain.
    contracts, snaps = _multi_chain("TSTI", "call", {
        _exp(NEAR): _FULL_WIDTH,
        _exp(FAR): _FULL_WIDTH,
    })
    plan = await build_spread(ChainMCP(contracts, snaps), "TSTI", "short",
                              spot_price=100.0, realized_vol=0.30)
    assert plan is not None
    assert plan.expiration.isoformat() == _exp(NEAR)


@pytest.mark.asyncio
async def test_all_off_width_keeps_nearest_as_last_resort():
    # No expiration builds on-width: the nearest buildable (off-width) plan
    # is returned — a narrow GLD-style spread beats losing the ticker, and
    # this is exactly the pre-fallback single-expiration outcome.
    contracts, snaps = _multi_chain("TSTJ", "call", {
        _exp(NEAR): _CHAIN_TOP,
        _exp(FAR): {119.0: (0.30, 0.33), 120.0: (0.10, 0.11)},
    })
    plan = await build_spread(ChainMCP(contracts, snaps), "TSTJ", "short",
                              spot_price=100.0, realized_vol=0.30)
    assert plan is not None
    assert plan.expiration.isoformat() == _exp(NEAR)
    assert plan.short_strike == 109.0 and plan.long_strike == 110.0


@pytest.mark.asyncio
async def test_attempts_are_capped():
    # Three junk expirations exhaust the attempt budget; a viable fourth is
    # never quoted (bounds snapshot load — a chain like this isn't tradeable).
    per_exp = {
        _exp(config.risk.min_dte + i): {110.0: (0.9, 1.1)}
        for i in (1, 3, 5)
    }
    per_exp[_exp(config.risk.min_dte + 7)] = _FULL_WIDTH
    contracts, snaps = _multi_chain("TSTK", "call", per_exp)
    plan = await build_spread(ChainMCP(contracts, snaps), "TSTK", "short",
                              spot_price=100.0, realized_vol=0.30)
    assert plan is None
    assert spread_builder.MAX_EXPIRATION_ATTEMPTS == 3

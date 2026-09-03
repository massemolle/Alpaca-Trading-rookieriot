"""build_spread must never pick an ITM short leg.

Live incident (2026-09-02 cycle 53, recurred 2026-09-03 cycle 71): on the
indicative feed the OTM side of XLK's chain quoted too wide to pass the
per-leg liquidity gate, so the closest-to-target-delta *liquid* strike was
several points ITM — producing "credit spreads" whose credit exceeded their
max loss (intrinsic value on stale mids, not premium). The builder now
requires the short leg to be OTM relative to spot; a chain whose OTM strikes
are all illiquid yields no plan at all.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

import spread_builder
from spread_builder import build_spread
from config import config
from tests.conftest import FakeMCP, snapshot


class ChainMCP(FakeMCP):
    """FakeMCP that also answers get_option_contracts with a canned chain."""

    def __init__(self, contracts: list[dict], snapshots: dict[str, dict]):
        super().__init__(snapshots)
        self.contracts = contracts

    async def call(self, tool: str, arguments: dict):
        if tool == "get_option_contracts":
            self.calls.append((tool, arguments))
            return {"data": {"option_contracts": self.contracts, "next_page_token": None}}
        return await super().call(tool, arguments)


@pytest.fixture(autouse=True)
def _clear_contract_cache():
    spread_builder._contract_cache.clear()
    yield
    spread_builder._contract_cache.clear()


def _expiration() -> str:
    mid_dte = (config.risk.min_dte + config.risk.max_dte) // 2
    return (date.today() + timedelta(days=mid_dte)).isoformat()


def _contract(ticker: str, option_type: str, strike: float, expiration: str) -> dict:
    # Mirrors the real get_option_contracts shape: string-typed strike,
    # nullable open_interest (null = data gap on this feed, not illiquidity).
    letter = "C" if option_type == "call" else "P"
    symbol = f"{ticker}{letter}{int(strike * 1000):08d}"
    return {
        "symbol": symbol,
        "strike_price": str(strike),
        "expiration_date": expiration,
        "type": option_type,
        "open_interest": None,
    }


def _chain(ticker: str, option_type: str, quotes: dict[float, tuple[float, float] | None]):
    """quotes: strike -> (bid, ask), or None for an untradeably wide quote."""
    exp = _expiration()
    contracts, snaps = [], {}
    for strike, quote in quotes.items():
        c = _contract(ticker, option_type, strike, exp)
        contracts.append(c)
        bid, ask = quote if quote is not None else (0.2, 1.8)  # ~160% of mid
        snaps[c["symbol"]] = snapshot(bid, ask)
    return contracts, snaps


@pytest.mark.asyncio
async def test_bear_call_with_only_itm_strikes_liquid_builds_nothing():
    # Spot 100: the OTM calls (105/110/115) quote too wide to pass liquidity,
    # only ITM strikes survive — pre-fix the delta sort picked one of them.
    contracts, snaps = _chain("TSTA", "call", {
        90.0: (10.9, 11.1),
        95.0: (6.4, 6.6),
        105.0: None,
        110.0: None,
        115.0: None,
    })
    plan = await build_spread(ChainMCP(contracts, snaps), "TSTA", "short",
                              spot_price=100.0, realized_vol=0.30)
    assert plan is None


@pytest.mark.asyncio
async def test_bear_call_picks_otm_short_even_when_itm_strikes_are_liquid():
    contracts, snaps = _chain("TSTB", "call", {
        90.0: (10.9, 11.1),
        95.0: (6.4, 6.6),
        105.0: (2.4, 2.6),
        110.0: (1.0, 1.1),
        115.0: (0.40, 0.45),
    })
    plan = await build_spread(ChainMCP(contracts, snaps), "TSTB", "short",
                              spot_price=100.0, realized_vol=0.30)
    assert plan is not None
    assert plan.direction == "bear_call"
    assert plan.short_strike > 100.0
    assert plan.long_strike > plan.short_strike
    assert plan.max_loss > 0


@pytest.mark.asyncio
async def test_bull_put_with_only_itm_strikes_liquid_builds_nothing():
    contracts, snaps = _chain("TSTC", "put", {
        110.0: (10.2, 10.4),
        105.0: (5.4, 5.6),
        95.0: None,
        90.0: None,
        85.0: None,
    })
    plan = await build_spread(ChainMCP(contracts, snaps), "TSTC", "long",
                              spot_price=100.0, realized_vol=0.30)
    assert plan is None


@pytest.mark.asyncio
async def test_bull_put_picks_otm_short_below_spot():
    contracts, snaps = _chain("TSTD", "put", {
        105.0: (5.4, 5.6),
        95.0: (1.0, 1.1),
        90.0: (0.40, 0.45),
        85.0: (0.15, 0.165),
    })
    plan = await build_spread(ChainMCP(contracts, snaps), "TSTD", "long",
                              spot_price=100.0, realized_vol=0.30)
    assert plan is not None
    assert plan.direction == "bull_put"
    assert plan.short_strike < 100.0
    assert plan.long_strike < plan.short_strike
    assert plan.max_loss > 0


@pytest.mark.asyncio
async def test_live_incident_itm_credit_exceeding_max_loss_is_rejected():
    # The 2026-09-03 cycle-71 shape: XLK spot ~185.85, short 177.5 / long
    # 182.5 bear call, both legs ITM with tight-enough fat-mid quotes; the
    # $5 width made credit (~$350) exceed max loss (~$150). Must not build.
    contracts, snaps = _chain("TSTE", "call", {
        177.5: (8.3, 8.9),
        182.5: (5.0, 5.2),
        187.5: None,
        190.0: None,
    })
    plan = await build_spread(ChainMCP(contracts, snaps), "TSTE", "short",
                              spot_price=185.85, realized_vol=0.21)
    assert plan is None

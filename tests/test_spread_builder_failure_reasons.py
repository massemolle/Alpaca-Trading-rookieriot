"""build_spread's failure_reasons out-list must say WHY a ticker built nothing.

Evening-review evidence trail: XLK and TLT hit "no viable spread plan" every
cycle from 2026-09-02 through 2026-11-17, and the journal's gate_rejections
carried only that opaque string — the real causes (XLK: every OTM call quotes
wider than the liquidity gate on the indicative feed; TLT: the far-OTM long
legs are penny options with huge relative spreads) sat at INFO in a 14MB
bot.log that no evening session read for 2.5 months. These tests pin that
each builder failure branch now reports a specific, per-expiration reason,
and that providing the list never changes what gets built.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

import spread_builder
from spread_builder import build_spread
from config import config
from tests.conftest import FakeMCP, snapshot


class ChainMCP(FakeMCP):
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
async def test_illiquid_otm_chain_reports_per_expiration_reason():
    # The XLK pattern: OTM calls exist but all quote too wide to pass the
    # per-leg liquidity gate.
    contracts, snaps = _chain("TSTF", "call", {
        105.0: None,
        110.0: None,
        115.0: None,
    })
    reasons: list[str] = []
    plan = await build_spread(ChainMCP(contracts, snaps), "TSTF", "short",
                              spot_price=100.0, realized_vol=0.30,
                              failure_reasons=reasons)
    assert plan is None
    assert len(reasons) == 1  # one expiration attempted, one reason
    assert _expiration() in reasons[0]
    assert "OTM and liquid" in reasons[0]


@pytest.mark.asyncio
async def test_empty_chain_reports_dte_window():
    reasons: list[str] = []
    plan = await build_spread(ChainMCP([], {}), "TSTG", "short",
                              spot_price=100.0, realized_vol=0.30,
                              failure_reasons=reasons)
    assert plan is None
    assert len(reasons) == 1
    assert "no call contracts" in reasons[0]


@pytest.mark.asyncio
async def test_junk_long_legs_report_reason():
    # The TLT pattern: a liquid short exists, but its snapped long leg quotes
    # too wide even for the relaxed long-leg gate.
    contracts, snaps = _chain("TSTH", "call", {
        105.0: (2.4, 2.6),
        110.0: None,
    })
    reasons: list[str] = []
    plan = await build_spread(ChainMCP(contracts, snaps), "TSTH", "short",
                              spot_price=100.0, realized_vol=0.30,
                              failure_reasons=reasons)
    assert plan is None
    assert len(reasons) == 1
    assert "no tradeable long leg" in reasons[0]


@pytest.mark.asyncio
async def test_successful_build_reports_nothing():
    contracts, snaps = _chain("TSTI", "call", {
        105.0: (2.4, 2.6),
        110.0: (1.0, 1.1),
        115.0: (0.40, 0.45),
    })
    reasons: list[str] = []
    plan = await build_spread(ChainMCP(contracts, snaps), "TSTI", "short",
                              spot_price=100.0, realized_vol=0.30,
                              failure_reasons=reasons)
    assert plan is not None
    assert reasons == []


@pytest.mark.asyncio
async def test_omitting_the_list_is_still_safe():
    contracts, snaps = _chain("TSTJ", "call", {
        105.0: None,
        110.0: None,
    })
    plan = await build_spread(ChainMCP(contracts, snaps), "TSTJ", "short",
                              spot_price=100.0, realized_vol=0.30)
    assert plan is None

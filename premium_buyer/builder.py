"""Pick a concrete long option for a directional signal: ~0.40Δ contract,
5-14 DTE, liquidity-checked, PRICED FAIRLY — the Killswitch-derived
richness gate says: never buy premium quoting above RICHNESS_CAP x its
Black-Scholes value at realized vol (the buyer's mirror of our credit
bot's "never sell cheap premium"). Reuses the credit bot's verified MCP
plumbing (chain fetch, snapshots, liquidity checks, BS delta)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from black_scholes import bs_delta, bs_price
from premium_buyer import config as pcfg
from spread_builder import _fetch_contracts, _fetch_snapshots, _mid_from_snapshot, _passes_liquidity

logger = logging.getLogger(__name__)


@dataclass
class BuyPlan:
    underlying: str
    direction: str       # 'call' | 'put'
    symbol: str
    strike: float
    expiration: date
    mid: float           # per-share
    premium: float       # per-contract $, = mid * 100
    price_ratio: float   # mid / bs_fair
    facts: list


async def build_buy(mcp, ticker: str, signal_direction: str, spot: float, realized_vol: float) -> tuple[BuyPlan | None, str | None]:
    """signal 'long' -> call, 'short' -> put. Returns (plan, rejection_reason)."""
    right = "call" if signal_direction == "long" else "put"
    today = datetime.now(timezone.utc).date()
    min_exp, max_exp = today + timedelta(days=pcfg.MIN_DTE), today + timedelta(days=pcfg.MAX_DTE)
    contracts = await _fetch_contracts(mcp, ticker, right, min_exp, max_exp)
    if not contracts:
        return None, "no contracts in DTE window"

    def dte_of(c):
        return (date.fromisoformat(c["expiration_date"]) - today).days

    def delta_of(c):
        return abs(bs_delta(spot=spot, strike=float(c["strike_price"]),
                            dte_days=max(dte_of(c), 1), volatility=realized_vol,
                            option_type=right))

    ranked = sorted(contracts, key=lambda c: (abs(delta_of(c) - pcfg.TARGET_DELTA), dte_of(c)))[:8]
    snaps = await _fetch_snapshots(mcp, [c["symbol"] for c in ranked])
    for c in ranked:
        snap = snaps.get(c["symbol"], {})
        if not _passes_liquidity(c, snap):
            continue
        mid = _mid_from_snapshot(snap)
        if mid is None or mid <= 0:
            continue
        dte = max(dte_of(c), 1)
        fair = bs_price(spot=spot, strike=float(c["strike_price"]), dte_days=dte,
                        volatility=realized_vol, option_type=right)
        if fair <= 0:
            continue
        ratio = mid / fair
        if ratio > pcfg.RICHNESS_CAP:
            logger.info("%s %s rejected: price ratio %.2f > cap %.2f",
                        ticker, c["symbol"], ratio, pcfg.RICHNESS_CAP)
            continue
        premium = round(mid * 100, 2)
        if premium > pcfg.MAX_PREMIUM_PER_POSITION:
            continue
        exp = date.fromisoformat(c["expiration_date"])
        facts = [
            {"fact_id": f"{ticker}_PREMIUM", "value": premium, "source": "alpaca_mcp_option_snapshot",
             "quality": "indicative_delayed", "derivation": "mid x 100"},
            {"fact_id": f"{ticker}_PRICE_RATIO", "value": round(ratio, 3), "source": "computed",
             "quality": "computed", "derivation": "mid / black_scholes(RV) — <=1 means cheap vs realized vol"},
            {"fact_id": f"{ticker}_DTE", "value": dte, "source": "computed", "quality": "computed",
             "derivation": None},
            {"fact_id": f"{ticker}_SPOT", "value": round(spot, 2), "source": "alpaca_stock_quote",
             "quality": "realtime_iex", "derivation": "bid/ask mid"},
        ]
        return BuyPlan(ticker, right, c["symbol"], float(c["strike_price"]), exp,
                       mid, premium, round(ratio, 3), facts), None
    return None, "no liquid, fairly-priced contract near target delta"

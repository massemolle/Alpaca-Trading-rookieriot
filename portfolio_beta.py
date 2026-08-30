"""Beta-weighted delta for the currently open book (2026-08-30, adapted
from the sibling project — Alejdro83/alpaca-options-agent, same hackathon
team's other strategy instance): "this portfolio moves like N shares of
SPY" -- the standard tastytrade/thinkorswim framing, expressing net
delta-dollar exposure per underlying in SPY-equivalent share terms via
each underlying's beta against SPY.

Scoped down from the sibling's version on purpose: this repo's book is
verticals only (no iron condor legs), so there is no "is this actually
delta-neutral" question to answer -- what's genuinely useful here is
simpler: how directionally exposed is the WHOLE book right now, across
however many concurrent verticals are open, expressed as one number.

Real broker-computed delta for currently HELD option legs (confirmed live
on the sibling project: Alpaca returns populated greeks for held
positions, null for anything not held -- spread_builder.py's
Black-Scholes proxy stays the right tool for candidate selection, this
changes nothing there). Beta computed from real trailing daily returns
(BETA_LOOKBACK_DAYS), never a hardcoded/assumed table. Falls back to
beta=1.0 ("moves like the market") only when real history is genuinely
unavailable, always logged when it happens.

Monitoring only -- called once per cycle from run_cycle(), independent of
manage_open_spreads (the real close/P&L path). Never raises; a failure
here must never affect a real close.
"""
from __future__ import annotations

import logging
import statistics
from datetime import datetime, timedelta, timezone

import db

logger = logging.getLogger(__name__)

BETA_LOOKBACK_DAYS = 95  # ~65 trading days after weekends/holidays -- enough for a stable regression
BETA_DEFAULT = 1.0  # fallback when real history is unavailable -- "moves like the market" is the honest default, not 0


async def _fetch_daily_closes(mcp, symbol: str) -> dict[str, float] | None:
    """{date_str: close} for the trailing BETA_LOOKBACK_DAYS, or None on
    failure/insufficient data. get_stock_bars via MCP silently returns
    zero bars on a paper account without feed='iex' (SIP is 403/empty on
    recent data for paper accounts) -- forced explicitly below.
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=BETA_LOOKBACK_DAYS)
    try:
        result = await mcp.call("get_stock_bars", {
            "symbols": symbol, "timeframe": "1Day", "feed": "iex", "limit": 100,
            "start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d"),
        })
    except Exception:
        logger.exception("Failed to fetch bars for %s (beta calc)", symbol)
        return None
    bars = (result or {}).get("data", {}).get("bars", {}).get(symbol, [])
    if len(bars) < 20:
        return None
    return {b["t"][:10]: float(b["c"]) for b in bars}


def _returns_from_closes(closes: dict[str, float]) -> dict[str, float]:
    """Daily % returns keyed by the LATER date of each consecutive pair,
    so two return series can be aligned by date even if one has a gap the
    other doesn't -- never assume equal-length series line up positionally.
    """
    dates = sorted(closes)
    returns = {}
    for prev, cur in zip(dates, dates[1:]):
        if closes[prev]:
            returns[cur] = (closes[cur] - closes[prev]) / closes[prev]
    return returns


def _compute_beta(stock_returns: dict[str, float], spy_returns: dict[str, float]) -> float | None:
    """beta = cov(stock, spy) / var(spy), over dates present in both series.
    None (not BETA_DEFAULT) when there isn't enough overlap -- the caller
    decides the fallback so this stays a pure, testable calculation.
    """
    shared_dates = sorted(set(stock_returns) & set(spy_returns))
    if len(shared_dates) < 15:
        return None
    x = [stock_returns[d] for d in shared_dates]
    y = [spy_returns[d] for d in shared_dates]
    spy_var = statistics.variance(y)
    if spy_var == 0:
        return None
    mean_x, mean_y = statistics.mean(x), statistics.mean(y)
    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / (len(x) - 1)
    return cov / spy_var


async def record_beta_weighted_delta(mcp) -> None:
    """Called once per cycle from run_cycle(). Never raises."""
    try:
        await _record_inner(mcp)
    except Exception:
        logger.exception("record_beta_weighted_delta failed (non-fatal, monitoring only)")


async def _record_inner(mcp) -> None:
    open_spreads = db.get_open_spreads()
    if not open_spreads:
        return

    all_symbols: list[str] = []
    for s in open_spreads:
        all_symbols += [s["short_symbol"], s["long_symbol"]]

    result = await mcp.call(
        "get_option_snapshot",
        {"symbols": ",".join(sorted(set(all_symbols))), "feed": "indicative"},
    )
    snapshots = (result or {}).get("data", {}).get("snapshots", {})

    spy_closes = await _fetch_daily_closes(mcp, "SPY")
    spy_returns = _returns_from_closes(spy_closes) if spy_closes else {}
    spy_price = spy_closes[max(spy_closes)] if spy_closes else None  # most recent close

    beta_by_underlying: dict[str, float] = {}
    price_by_underlying: dict[str, float | None] = {}
    for underlying in sorted({s["underlying"] for s in open_spreads}):
        closes = await _fetch_daily_closes(mcp, underlying)
        if not closes:
            logger.info("beta_weighted_delta: no bars for %s, beta defaults to %.1f", underlying, BETA_DEFAULT)
            beta_by_underlying[underlying] = BETA_DEFAULT
            price_by_underlying[underlying] = None
            continue
        price_by_underlying[underlying] = closes[max(closes)]
        beta = _compute_beta(_returns_from_closes(closes), spy_returns) if spy_returns else None
        if beta is None:
            logger.info("beta_weighted_delta: insufficient overlap to compute beta for %s, defaulting to %.1f",
                        underlying, BETA_DEFAULT)
        beta_by_underlying[underlying] = beta if beta is not None else BETA_DEFAULT

    net_delta = 0.0
    beta_weighted_delta = 0.0
    per_spread: list[dict] = []
    legs_missing_greeks = 0
    # Tracks whether EVERY spread got a real contribution -- one spread
    # missing price data must only mark the aggregate incomplete, never
    # silently stop later spreads (in iteration order) from contributing
    # their own share.
    complete = spy_price is not None

    for s in open_spreads:
        contracts = int(s.get("contracts") or 1)
        spread_delta = 0.0
        for symbol, sign in ((s["short_symbol"], -1), (s["long_symbol"], 1)):
            greeks = snapshots.get(symbol, {}).get("greeks")
            if greeks is None:
                legs_missing_greeks += 1
                continue
            spread_delta += sign * float(greeks.get("delta", 0.0)) * contracts
        net_delta += spread_delta

        # Beta-weighted delta contribution of this spread: share-equivalent
        # delta (option delta is per-share; one contract = 100 shares) times
        # the underlying's own price gives dollar delta; dividing by SPY's
        # price and scaling by beta expresses that dollar exposure in
        # "SPY-equivalent shares" -- the standard framing for "this
        # portfolio moves like N shares of SPY".
        underlying_price = price_by_underlying.get(s["underlying"])
        spread_bwd = None
        if spy_price is not None and underlying_price:
            dollar_delta = spread_delta * 100 * underlying_price
            spread_bwd = dollar_delta / spy_price * beta_by_underlying[s["underlying"]]
            beta_weighted_delta += spread_bwd
        else:
            complete = False  # this spread's own price (or SPY's) is missing -- total is now a partial sum

        per_spread.append({
            "spread_id": s["id"], "underlying": s["underlying"],
            "delta": round(spread_delta, 4),
            "beta": round(beta_by_underlying.get(s["underlying"], BETA_DEFAULT), 3),
            "beta_weighted_delta": round(spread_bwd, 2) if spread_bwd is not None else None,
        })

    if legs_missing_greeks:
        logger.info(
            "beta_weighted_delta: %d leg(s) had no broker greeks available (indicative feed only "
            "populates greeks for held positions -- this can lag right after a fresh open)",
            legs_missing_greeks,
        )
    if not complete:
        logger.info("beta_weighted_delta: partial sum (missing price data for some underlying)")

    db.record_beta_weighted_delta(
        net_delta=round(net_delta, 4),
        beta_weighted_delta=round(beta_weighted_delta, 2) if complete else None,
        per_spread=per_spread,
    )

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from alpaca_client import AlpacaClient
from config import config

logger = logging.getLogger(__name__)


@dataclass
class Candidate:
    symbol: str
    price: float
    volume: int
    spread_pct: float
    snapshot: dict[str, Any]


def _passes_filters(
    symbol: str,
    snapshot: dict[str, Any],
    quote: dict[str, Any],
    sf: Any,
) -> tuple[Candidate | None, str | None]:
    """Returns (candidate, None) on pass, (None, reason) on rejection."""
    price = snapshot.get("latest_trade_price") or snapshot.get("daily_close")
    if price is None:
        return None, "no price in snapshot"
    price = float(price)

    if price < sf.min_price or price > sf.max_price:
        return None, f"price {price:.2f} outside [{sf.min_price:.0f}, {sf.max_price:.0f}]"

    volume = snapshot.get("daily_volume")
    if volume is None or volume < sf.min_avg_volume:
        return None, f"volume {volume} below min {sf.min_avg_volume}"

    spread_pct = quote.get("spread_pct", 0.0)
    if spread_pct > sf.max_spread_pct:
        return None, f"spread {spread_pct:.2f}% above max {sf.max_spread_pct:.2f}%"

    # Market-cap range filter
    market_cap = snapshot.get("market_cap")
    if market_cap is not None:
        market_cap = float(market_cap)
        if market_cap < sf.min_market_cap or market_cap > sf.max_market_cap:
            return None, (
                f"market_cap {market_cap:.0f} outside "
                f"[{sf.min_market_cap:.0f}, {sf.max_market_cap:.0f}]"
            )
    else:
        logger.debug("%s: market_cap unavailable in snapshot, skipping filter", symbol)

    # Min ATR % filter (atr field expected in snapshot if available)
    atr_value = snapshot.get("atr") or snapshot.get("daily_atr")
    if atr_value is not None and price > 0:
        atr_pct = float(atr_value) / price * 100
        if atr_pct < sf.min_atr_pct:
            return None, f"ATR% {atr_pct:.2f} below min {sf.min_atr_pct:.2f}"
    else:
        logger.debug("%s: ATR data unavailable in snapshot, skipping filter", symbol)

    return Candidate(
        symbol=symbol,
        price=price,
        volume=volume,
        spread_pct=spread_pct,
        snapshot=snapshot,
    ), None


def filter_universe(
    tickers: list[str],
    client: AlpacaClient | None = None,
    rejections_out: list[dict] | None = None,
) -> list[Candidate]:
    """`rejections_out`, when given, is appended with one
    {"ticker", "stage": "screening", "reasons": [...]} dict per rejected
    symbol so callers can journal why the funnel narrowed (added 2026-09-01:
    screening dropped 2/3 of the live universe all day with reasons visible
    only at DEBUG level)."""
    if client is None:
        client = AlpacaClient()

    sf = config.screening
    candidates: list[Candidate] = []

    def _record_rejection(symbol: str, reason: str) -> None:
        logger.info("Screening rejected %s: %s", symbol, reason)
        if rejections_out is not None:
            rejections_out.append(
                {"ticker": symbol, "stage": "screening", "reasons": [reason]}
            )

    batch_size = 100
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        try:
            snapshots = client.get_snapshots(batch)
        except Exception as exc:
            logger.error("Snapshot batch failed: %s", exc)
            continue

        for symbol, snap in snapshots.items():
            try:
                quote = client.get_latest_quote(symbol)
            except Exception:
                _record_rejection(symbol, "quote fetch failed")
                continue

            c, reason = _passes_filters(symbol, snap, quote, sf)
            if c is not None:
                candidates.append(c)
            else:
                _record_rejection(symbol, reason or "unknown")

    logger.info("Screening: %d / %d tickers passed filters", len(candidates), len(tickers))
    return candidates

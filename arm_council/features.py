"""Build their MarketSnapshot from our existing Alpaca data (daily bars +
latest quote). Pure transform split out for offline tests."""
from __future__ import annotations

import pandas as pd

from arm_council.scoring import Snapshot


def rsi14(closes: pd.Series, period: int = 14) -> float:
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, 1e-9)
    return float((100 - 100 / (1 + rs)).iloc[-1])


def snapshot_from_bars(symbol: str, bars: pd.DataFrame, bid: float, ask: float) -> Snapshot | None:
    if bars is None or len(bars) < 30 or "close" not in bars:
        return None
    closes = bars["close"].astype(float)
    vols = bars["volume"].astype(float)
    price = (bid + ask) / 2 if bid and ask else float(closes.iloc[-1])
    rets = closes.pct_change().dropna()
    realized_vol = float(rets.tail(20).std() * (252 ** 0.5) * 100)
    avg_vol = float(vols.tail(21)[:-1].mean()) or 1.0
    rvol = float(vols.iloc[-1]) / avg_vol
    prev_avg = float(vols.tail(11)[:-1].mean()) or 1.0
    volume_accel = (float(vols.tail(5).mean()) / prev_avg - 1) * 100
    change24h = float(closes.iloc[-1] / closes.iloc[-2] - 1) * 100
    # momentum 0-100 from 10-day return, scaled like their 0-100 band
    mom_raw = float(closes.iloc[-1] / closes.iloc[-11] - 1) * 100 if len(closes) > 11 else 0.0
    momentum = max(0.0, min(100.0, 50 + mom_raw * 5))
    spread_bps = ((ask - bid) / price * 10_000) if price and ask and bid else 100.0
    return Snapshot(symbol=symbol, price=price, change24h=round(change24h, 2),
                    rsi14=round(rsi14(closes), 2), rvol=round(rvol, 2),
                    volume_accel=round(volume_accel, 2), realized_vol=round(realized_vol, 2),
                    liquidity_usd=round(price * float(vols.tail(20).mean()), 0),
                    spread_bps=round(spread_bps, 2), momentum=round(momentum, 2))

"""TrendFilter price-alignment gate (2026-11-18): `require_price_alignment`
additionally requires the current close on the signal's side of EMA50 —
longs above, shorts below. Default (False) must stay live behavior: the
crossover-only check. The flag is a DARK lab hypothesis (backtest_lab
L2e/L3e), born 2026-11-18 when the menu book resolved bull_puts 2W/27L
(−$1,250) on tickers whose EMA50/200 crossover still read bullish while
price fell through the 50-day; the lab REJECTED unconditional adoption on
the cached Apr-2025→Aug-2026 window (L3e +$161 vs L3 +$1,289 — below-EMA50
longs there were profitable dip-buys).

ADX is monkeypatched to a constant, as in test_trend_filter_adx_gate: these
tests pin the gate logic, not the ADX arithmetic.
"""
from __future__ import annotations

import pandas as pd

from signals.trend_filter import TrendFilter


def _df(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "close": closes,
        "high": [c + 1.0 for c in closes],
        "low": [c - 1.0 for c in closes],
    })


def _pullback_in_uptrend(rows: int = 260, pullback: int = 20) -> pd.DataFrame:
    # Long rise then a sharp pullback: EMA50 stays above EMA200 (crossover
    # still bullish) while the last close sits below EMA50.
    closes = [300.0 + 0.5 * i for i in range(rows - pullback)]
    for i in range(pullback):
        closes.append(closes[-1] - 2.0)
    return _df(closes)


def _bounce_in_downtrend(rows: int = 260, bounce: int = 20) -> pd.DataFrame:
    closes = [430.0 - 0.5 * i for i in range(rows - bounce)]
    for i in range(bounce):
        closes.append(closes[-1] + 2.0)
    return _df(closes)


def _patch_adx(monkeypatch, value: float = 15.0) -> None:
    monkeypatch.setattr(
        TrendFilter, "_compute_adx",
        staticmethod(lambda high, low, close, period=14:
                     pd.Series([value] * len(close), index=close.index)),
    )


def _assert_fixture_premise(df: pd.DataFrame, bullish_cross: bool,
                            close_below_ema50: bool) -> None:
    # Guard: the scenarios only test the gate if the synthetic data really
    # has crossover and price on the intended sides.
    ema50 = df["close"].ewm(span=50, adjust=False).mean().iloc[-1]
    ema200 = df["close"].ewm(span=200, adjust=False).mean().iloc[-1]
    assert bool(ema50 > ema200) == bullish_cross
    assert bool(df["close"].iloc[-1] < ema50) == close_below_ema50


def test_default_allows_pullback_long(monkeypatch):
    _patch_adx(monkeypatch)
    df = _pullback_in_uptrend()
    _assert_fixture_premise(df, bullish_cross=True, close_below_ema50=True)
    result = TrendFilter().check(df, "long")
    assert result.allowed is True


def test_alignment_blocks_long_below_ema50(monkeypatch):
    _patch_adx(monkeypatch)
    df = _pullback_in_uptrend()
    tf = TrendFilter(require_price_alignment=True)
    result = tf.check(df, "long")
    assert result.allowed is False
    assert any("price below EMA50" in r for r in result.reasoning)


def test_alignment_blocks_short_above_ema50(monkeypatch):
    _patch_adx(monkeypatch)
    df = _bounce_in_downtrend()
    _assert_fixture_premise(df, bullish_cross=False, close_below_ema50=False)
    tf = TrendFilter(require_price_alignment=True)
    result = tf.check(df, "short")
    assert result.allowed is False
    assert any("price above EMA50" in r for r in result.reasoning)


def test_alignment_passes_aligned_directions(monkeypatch):
    _patch_adx(monkeypatch)
    tf = TrendFilter(require_price_alignment=True)
    rising = _df([300.0 + 0.5 * i for i in range(260)])
    falling = _df([430.0 - 0.5 * i for i in range(260)])
    assert tf.check(rising, "long").allowed is True
    assert tf.check(falling, "short").allowed is True


def test_alignment_does_not_bypass_counter_trend_block(monkeypatch):
    _patch_adx(monkeypatch)
    tf = TrendFilter(require_price_alignment=True)
    rising = _df([300.0 + 0.5 * i for i in range(260)])
    result = tf.check(rising, "short")
    assert result.allowed is False
    assert "BLOCKED: Short against bullish trend" in result.reasoning

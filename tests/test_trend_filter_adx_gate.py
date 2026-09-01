"""TrendFilter ADX gate (2026-09-01): `block_only_strong_trend` makes the
counter-trend block conditional on ADX > adx_threshold. Default (False) must
stay the unconditional block — that is live behavior; the gated mode is a lab
hypothesis (see backtest_lab L2b/L3b) born on 2026-09-01, when the filter
emptied the whole menu while itself reporting "weak trend" (ADX 11.8-16.5)
on every blocked ticker.

ADX is monkeypatched to a constant: these tests pin the gate logic, not the
ADX arithmetic (which is unchanged and exercised by the lab).
"""
from __future__ import annotations

import pandas as pd
import pytest

from signals.trend_filter import TrendFilter


def _trending_df(rising: bool, rows: int = 260) -> pd.DataFrame:
    # Monotonic drift guarantees EMA50 > EMA200 (rising) or < (falling);
    # rows > ema_slow + 20 so the insufficient-data early-return is skipped.
    step = 0.5 if rising else -0.5
    close = [400.0 + step * i for i in range(rows)]
    return pd.DataFrame({
        "close": close,
        "high": [c + 1.0 for c in close],
        "low": [c - 1.0 for c in close],
    })


def _patch_adx(monkeypatch, value: float) -> None:
    monkeypatch.setattr(
        TrendFilter, "_compute_adx",
        staticmethod(lambda high, low, close, period=14:
                     pd.Series([value] * len(close), index=close.index)),
    )


def test_default_blocks_counter_trend_even_on_weak_adx(monkeypatch):
    _patch_adx(monkeypatch, 15.0)
    result = TrendFilter().check(_trending_df(rising=True), "short")
    assert result.allowed is False
    assert "BLOCKED: Short against bullish trend" in result.reasoning


def test_gated_mode_allows_counter_trend_when_adx_weak(monkeypatch):
    _patch_adx(monkeypatch, 15.0)
    tf = TrendFilter(block_only_strong_trend=True)
    result = tf.check(_trending_df(rising=True), "short")
    assert result.allowed is True
    assert any("Counter-trend allowed" in r for r in result.reasoning)
    assert result.adx == pytest.approx(15.0)


def test_gated_mode_still_blocks_counter_trend_when_adx_strong(monkeypatch):
    _patch_adx(monkeypatch, 30.0)
    tf = TrendFilter(block_only_strong_trend=True)
    result = tf.check(_trending_df(rising=True), "short")
    assert result.allowed is False
    assert "BLOCKED: Short against bullish trend" in result.reasoning


def test_gated_mode_bearish_side_is_symmetric(monkeypatch):
    tf = TrendFilter(block_only_strong_trend=True)
    _patch_adx(monkeypatch, 15.0)
    assert tf.check(_trending_df(rising=False), "long").allowed is True
    _patch_adx(monkeypatch, 30.0)
    strong = tf.check(_trending_df(rising=False), "long")
    assert strong.allowed is False
    assert "BLOCKED: Long against bearish trend" in strong.reasoning


def test_trend_aligned_direction_allowed_in_both_modes(monkeypatch):
    _patch_adx(monkeypatch, 15.0)
    df = _trending_df(rising=True)
    assert TrendFilter().check(df, "long").allowed is True
    assert TrendFilter(block_only_strong_trend=True).check(df, "long").allowed is True

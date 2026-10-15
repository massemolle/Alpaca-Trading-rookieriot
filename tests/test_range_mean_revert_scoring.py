"""range_mean_revert scoring variant (2026-10-15): in weak-trend regimes the
RSI/MACD z-score terms flip from a momentum read to a mean-reversion read.

Default (False) must stay the production scoring — that is live behavior and
what the pre-variant lab baselines measured; the flipped mode is a DARK lab
hypothesis (see backtest_lab L3c), born on 2026-10-15 when the engine scored
QQQ at RSI z=-2.2/-2.6 ON the lower Bollinger band as a 0.62-0.74-strength
SHORT in a ranging regime — the Bollinger term votes bounce (+0.5) while the
oscillator terms vote continuation, by construction, at every range extreme.

Indicators are handed in as crafted series: these tests pin the scoring
arithmetic and the regime gate, not the indicator math (unchanged, exercised
elsewhere). The parity tests guard the documented "flat copy, no auto-sync"
convention between signals.swing and backtest_optimize._signal_from_df.
"""
from __future__ import annotations

import sys
import types

import pandas as pd
import pytest

# Same stub backtest_lab.py uses: backtest_optimize imports trading_bot's
# HistoricalDataLoader at top level, which only exists on Will's machine.
_stub = types.ModuleType("backtest.data")
_stub.HistoricalDataLoader = object
_pkg = types.ModuleType("backtest")
_pkg.data = _stub
sys.modules.setdefault("backtest", _pkg)
sys.modules.setdefault("backtest.data", _stub)

import backtest_optimize as bo  # noqa: E402
import signals.swing as swing  # noqa: E402
from signals.adaptive import AdaptiveIndicators, AdaptiveResult  # noqa: E402
from signals.regime import Regime, RegimeResult  # noqa: E402

ROWS = 60


def _df() -> pd.DataFrame:
    # Flat tape: SMA50 == close (so the "above SMA50" term goes to the else
    # branch, deterministically) and SMA200 is NaN at 60 rows (term skipped).
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-02", periods=ROWS, freq="D"),
        "close": [100.0] * ROWS,
        "high": [101.0] * ROWS,
        "low": [99.0] * ROWS,
    })


def _result(is_strong_trend: bool) -> AdaptiveResult:
    """Oversold-at-the-lower-band shape: RSI dives on the last bar
    (z ~ -4.2), MACD hist dives with it (z ~ -4.2), close <= bb_lower."""
    regime = Regime.TRENDING if is_strong_trend else Regime.RANGING
    flat = pd.Series([0.0] * ROWS)
    return AdaptiveResult(
        regime=RegimeResult(
            regime=regime, adx=30.0 if is_strong_trend else 12.0,
            vol_20d=0.01, vol_60d_avg=0.01, vol_ratio=1.0,
            is_high_vol=False, is_strong_trend=is_strong_trend,
        ),
        params=AdaptiveIndicators().get_params(regime),
        rsi=pd.Series([50.0] * (ROWS - 1) + [30.0]),
        macd_line=flat,
        macd_signal=flat,
        macd_hist=pd.Series([0.0] * (ROWS - 1) + [-1.0]),
        atr=pd.Series([1.0] * ROWS),
        bb_upper=pd.Series([200.0] * ROWS),
        bb_middle=pd.Series([150.0] * ROWS),
        bb_lower=pd.Series([100.5] * ROWS),  # last close 100 <= 100.5: touch
        ema9=flat,
        ema21=flat,
    )


class _FakeAdaptive:
    def __init__(self, result: AdaptiveResult) -> None:
        self._result = result

    def compute(self, df: pd.DataFrame) -> AdaptiveResult:
        return self._result


# --- lab copy: backtest_optimize._signal_from_df ---------------------------

def test_default_scores_oversold_at_lower_band_as_short():
    # Pins live behavior (today's QQQ c583/c588 shape): momentum read wins.
    sig = bo._signal_from_df("TST", _df(), _FakeAdaptive(_result(False)))
    assert sig.direction == "short"
    assert sig.strength == 1.0  # |score| ~ 2.67, capped


def test_flag_flips_to_long_in_weak_trend_regime():
    sig = bo._signal_from_df("TST", _df(), _FakeAdaptive(_result(False)),
                             range_mean_revert=True)
    assert sig.direction == "long"


def test_flag_is_inert_in_strong_trend_regime():
    base = bo._signal_from_df("TST", _df(), _FakeAdaptive(_result(True)))
    gated = bo._signal_from_df("TST", _df(), _FakeAdaptive(_result(True)),
                               range_mean_revert=True)
    assert (gated.direction, gated.strength) == (base.direction, base.strength)
    assert base.direction == "short"


# --- live function: signals.swing.generate_swing_signals --------------------

def _run_swing(monkeypatch, result: AdaptiveResult, **kwargs):
    monkeypatch.setattr(swing, "AdaptiveIndicators",
                        lambda: _FakeAdaptive(result))
    bars = [types.SimpleNamespace(timestamp=ts, close=100.0, high=101.0,
                                  low=99.0)
            for ts in pd.date_range("2026-01-02", periods=ROWS, freq="D")]
    fake_client = types.SimpleNamespace(
        _data=types.SimpleNamespace(
            get_stock_bars=lambda req: types.SimpleNamespace(
                data={"TST": bars})))
    out = swing.generate_swing_signals(["TST"], fake_client, **kwargs)
    assert len(out) == 1
    return out[0]


def test_live_default_matches_lab_copy(monkeypatch):
    live = _run_swing(monkeypatch, _result(False))
    lab = bo._signal_from_df("TST", _df(), _FakeAdaptive(_result(False)))
    assert (live.direction, live.strength) == (lab.direction, lab.strength)
    assert not any("range_mean_revert" in r for r in live.reasoning)


def test_live_flag_matches_lab_copy_and_says_so(monkeypatch):
    live = _run_swing(monkeypatch, _result(False), range_mean_revert=True)
    lab = bo._signal_from_df("TST", _df(), _FakeAdaptive(_result(False)),
                             range_mean_revert=True)
    assert (live.direction, live.strength) == (lab.direction, lab.strength)
    assert live.direction == "long"
    assert any("range_mean_revert" in r for r in live.reasoning)


def test_live_flag_inert_in_strong_trend(monkeypatch):
    base = _run_swing(monkeypatch, _result(True))
    gated = _run_swing(monkeypatch, _result(True), range_mean_revert=True)
    assert (gated.direction, gated.strength) == (base.direction, base.strength)
    assert not any("range_mean_revert" in r for r in gated.reasoning)

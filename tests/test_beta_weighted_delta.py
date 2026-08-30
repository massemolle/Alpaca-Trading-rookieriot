"""portfolio_beta.py's pure math (2026-08-30, adapted from the sibling
project) — offline, no network. Synthetic return series with an exact
known beta, same verification method used when the sibling project built
this."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portfolio_beta import _compute_beta, _returns_from_closes


def _synthetic_closes(returns: list[float], start_price: float = 100.0) -> dict[str, float]:
    """Build a {date: close} series from a list of daily returns, dates
    just sequential 'D01', 'D02', ... labels -- _compute_beta only cares
    about alignment by key, not real calendar dates."""
    closes = {"D00": start_price}
    price = start_price
    for i, r in enumerate(returns, start=1):
        price = price * (1 + r)
        closes[f"D{i:02d}"] = price
    return closes


def test_returns_from_closes_aligns_by_later_date():
    closes = {"D00": 100.0, "D01": 110.0, "D02": 99.0}
    returns = _returns_from_closes(closes)
    assert set(returns) == {"D01", "D02"}
    assert abs(returns["D01"] - 0.10) < 1e-9
    assert abs(returns["D02"] - (-0.10)) < 1e-9


def test_compute_beta_exact_for_a_perfectly_scaled_series():
    # SPY moves +1%/-1%/+2%/-1.5%/+0.5% each day; the stock moves exactly
    # 2x that -- beta should come back essentially exactly 2.0.
    spy_rets = [0.01, -0.01, 0.02, -0.015, 0.005] * 4  # repeat for >15 shared dates
    stock_rets = [r * 2.0 for r in spy_rets]

    spy_closes = _synthetic_closes(spy_rets)
    stock_closes = _synthetic_closes(stock_rets)

    beta = _compute_beta(_returns_from_closes(stock_closes), _returns_from_closes(spy_closes))
    assert beta is not None
    assert abs(beta - 2.0) < 1e-6


def test_compute_beta_exact_for_a_different_scale_with_a_data_gap():
    # Same idea at beta=1.5, but the stock's RETURN SERIES is missing a
    # couple of dates (a real, if rare, data hazard) -- _compute_beta must
    # align on the dates present in BOTH series, not assume equal-length
    # series line up positionally. Built directly as returns dicts (not
    # via _synthetic_closes/_returns_from_closes) so removing dates here
    # can't also corrupt adjacent-day return math the way deleting a raw
    # close would.
    dates = [f"D{i:02d}" for i in range(1, 22)]
    spy_pattern = [0.01, -0.02, 0.015, -0.01, 0.02, 0.005, -0.015] * 3
    spy_returns = dict(zip(dates, spy_pattern))
    stock_returns = {d: r * 1.5 for d, r in spy_returns.items()}
    # Drop two dates from the stock series entirely.
    for missing in dates[3:5]:
        del stock_returns[missing]

    beta = _compute_beta(stock_returns, spy_returns)
    assert beta is not None
    assert abs(beta - 1.5) < 1e-6


def test_compute_beta_returns_none_on_insufficient_overlap():
    spy_closes = _synthetic_closes([0.01, -0.01, 0.02])  # only 3 return points
    stock_closes = _synthetic_closes([0.02, -0.02, 0.04])
    beta = _compute_beta(_returns_from_closes(stock_closes), _returns_from_closes(spy_closes))
    assert beta is None  # fewer than 15 shared dates -- caller falls back to BETA_DEFAULT

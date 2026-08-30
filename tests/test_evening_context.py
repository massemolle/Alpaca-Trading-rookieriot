"""Offline test for the evening context's market_day metrics computation."""
from __future__ import annotations

import evening_context


def _bar(day, o, h, l, c, v=1_000_000):
    return {"timestamp": f"2026-08-{day:02d}T04:00:00", "open": o, "high": h,
            "low": l, "close": c, "volume": v}


def test_day_metrics_math():
    bars = [_bar(d, 100.0, 101.0, 99.0, 100.0) for d in range(1, 25)]
    bars.append(_bar(28, 101.0, 103.0, 100.0, 102.0, v=2_000_000))  # +2% day, +1% gap
    m = evening_context._day_metrics(bars)
    assert m["day_move_pct"] == 2.0
    assert m["gap_open_pct"] == 1.0
    assert m["day_range_pct"] == 3.0
    assert m["volume_vs_20d"] == 2.0
    assert m["date"] == "2026-08-28"
    assert m["realized_vol_20d_pct_annualized"] is not None


def test_day_metrics_handles_unsorted_and_short():
    assert evening_context._day_metrics([_bar(1, 1, 1, 1, 1)]) == {}
    bars = [_bar(2, 100, 101, 99, 100), _bar(1, 100, 101, 99, 100)]  # unsorted
    assert evening_context._day_metrics(bars)["date"] == "2026-08-02"

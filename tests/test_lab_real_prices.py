"""Real-price lab layer (Roadmap v2) — pure parts, offline."""
from __future__ import annotations

from datetime import date

import lab_real_prices as lrp


def test_occ_symbol_format():
    assert lrp.occ_symbol("QQQ", date(2026, 9, 14), "C", 725.0) == "QQQ260914C00725000"
    assert lrp.occ_symbol("SPY", date(2026, 9, 10), "P", 751.0) == "SPY260910P00751000"
    assert lrp.occ_symbol("XLF", date(2026, 9, 18), "P", 52.5) == "XLF260918P00052500"


def test_snap_helpers():
    assert lrp.snap_strike(724.63) == 725.0
    assert lrp.snap_strike(52.4, 0.5) == 52.5
    assert lrp.snap_to_friday(date(2026, 9, 7)) == date(2026, 9, 11)   # Mon -> Fri
    assert lrp.snap_to_friday(date(2026, 9, 11)) == date(2026, 9, 11)  # Fri stays


def test_fills_are_conservative():
    # Credit received < close-to-close difference; debit paid > it.
    assert lrp.entry_credit(1.00, 0.30) < 0.70
    assert lrp.exit_debit(1.00, 0.30) > 0.70


def _bars(seq):  # {day: close} in order
    return {f"2026-09-{i+7:02d}": v for i, v in enumerate(seq)}


def test_simulate_profit_target():
    short = _bars([1.00, 0.60, 0.30]); long = _bars([0.30, 0.20, 0.10])
    r = lrp.simulate_real_spread(short, long, "2026-09-07", date(2026, 9, 25))
    assert r["exit_reason"] == "profit_target" and r["pnl"] > 0


def test_simulate_stop():
    short = _bars([1.00, 2.20]); long = _bars([0.30, 0.60])
    r = lrp.simulate_real_spread(short, long, "2026-09-07", date(2026, 9, 25))
    assert r["exit_reason"] == "stop" and r["pnl"] < 0


def test_simulate_data_end_is_labeled():
    short = _bars([1.00, 0.95]); long = _bars([0.30, 0.28])
    r = lrp.simulate_real_spread(short, long, "2026-09-07", date(2026, 9, 25))
    assert r["exit_reason"] == "data_end"


def test_missing_entry_day_returns_none():
    assert lrp.simulate_real_spread({}, {}, "2026-09-07", date(2026, 9, 25)) is None

"""Offline tests for the evening context's sleeve attribution — the pure
partition of shared-account broker positions into per-sleeve buckets.

Why this exists: all four arms trade the same paper account, and the credit
bot's circuit breaker / drawdown halt key off ACCOUNT daily P&L. On
2026-10-19 they halted entries all day for a -3.3% account move the credit
book alone could not have produced (7 open spreads, ~$2.9k summed max loss).
The attribution section is what lets the evening review say WHICH sleeve's
positions moved the account.
"""
from __future__ import annotations

import evening_context


def _pos(symbol, mv, upl, intraday=None):
    return {
        "symbol": symbol,
        "market_value": mv,
        "unrealized_pl": upl,
        "unrealized_intraday_pl": intraday,
    }


def _sleeves(**kw):
    base = {"credit_bot": set(), "premium_buyer": set(),
            "killswitch": set(), "council": set()}
    base.update({k: set(v) for k, v in kw.items()})
    return base


def test_positions_bucket_by_claimed_symbol():
    sleeves = _sleeves(
        credit_bot={"XLK261030C00188000", "XLK261030C00193000"},
        council={"NVDA"},
    )
    positions = [
        _pos("XLK261030C00188000", -250.0, -60.0, -40.0),  # short leg: negative mv
        _pos("XLK261030C00193000", 110.0, 20.0, 15.0),
        _pos("NVDA", 18000.0, -3100.0, -3000.0),
    ]
    b = evening_context._attribute_positions(positions, sleeves)
    assert b["credit_bot"]["n"] == 2
    assert b["credit_bot"]["market_value"] == -140.0
    assert b["credit_bot"]["unrealized_intraday_pl"] == -25.0
    assert b["council"]["n"] == 1
    assert b["council"]["unrealized_intraday_pl"] == -3000.0
    assert b["unattributed"]["n"] == 0


def test_unclaimed_positions_land_in_unattributed():
    # Manual-experiment legs belong to no sleeve's live rows — they must be
    # visible, not silently merged into a sleeve.
    b = evening_context._attribute_positions(
        [_pos("SPY261022P00768000", -80.0, -12.0, -5.0)], _sleeves()
    )
    assert b["unattributed"]["n"] == 1
    assert b["unattributed"]["symbols"] == ["SPY261022P00768000"]
    assert b["unattributed"]["unrealized_intraday_pl"] == -5.0


def test_contested_symbol_goes_to_first_claimant_in_dict_order():
    sleeves = _sleeves(credit_bot={"QQQ"}, council={"QQQ"})
    b = evening_context._attribute_positions([_pos("QQQ", 100.0, 1.0, 1.0)], sleeves)
    assert b["credit_bot"]["n"] == 1
    assert b["council"]["n"] == 0


def test_missing_intraday_counts_as_zero_not_crash():
    # Older callers / mocks may not carry unrealized_intraday_pl at all.
    sleeves = _sleeves(council={"AAPL"})
    b = evening_context._attribute_positions(
        [{"symbol": "AAPL", "market_value": 500.0, "unrealized_pl": 10.0}],
        sleeves,
    )
    assert b["council"]["unrealized_intraday_pl"] == 0.0
    assert b["council"]["market_value"] == 500.0


def test_empty_inputs_yield_zeroed_buckets():
    b = evening_context._attribute_positions([], _sleeves())
    assert set(b) == {"credit_bot", "premium_buyer", "killswitch",
                      "council", "unattributed"}
    for bucket in b.values():
        assert bucket["n"] == 0
        assert bucket["market_value"] == 0.0

"""One-sided underlying quotes must never become prices (2026-09-30).

Live incident: after the 4pm close SPY's bid dropped to 0 and two account
snapshots recorded spy_price 381.19 — (0 + 762.38) / 2, half the real
price — corrupting the dashboard's 'skill vs market' overlay. The same
raw (ask+bid)/2 lived on the candidate-construction spot path in
bot.find_candidates, and get_latest_quote maps a zero bid to
spread_pct 0.0, which the screening width filter read as "infinitely
tight". One rule at all three sites: a one-sided quote is missing data,
never a price (same integrity rule as executor_mcp.get_spread_mark_detail's
option-leg guard, 09-25).
"""
from __future__ import annotations

import pytest

import benchmark
from alpaca_client import two_sided_mid
from screening.filters import filter_universe


# ---------------------------------------------------------------------------
# two_sided_mid — the shared rule
# ---------------------------------------------------------------------------

def test_two_sided_quote_returns_mid():
    assert two_sided_mid({"bid_price": 762.30, "ask_price": 762.38}) == pytest.approx(762.34)


def test_literal_incident_shape_bidless_returns_none():
    # The 2026-09-30 20:00Z snapshot shape: bid gone, ask alive. The old
    # code produced 381.19 from this; it must produce nothing.
    assert two_sided_mid({"bid_price": 0.0, "ask_price": 762.38}) is None


def test_askless_quote_returns_none():
    assert two_sided_mid({"bid_price": 762.30, "ask_price": 0.0}) is None


def test_missing_or_malformed_sides_return_none():
    assert two_sided_mid(None) is None
    assert two_sided_mid({}) is None
    assert two_sided_mid({"bid_price": 762.30}) is None
    assert two_sided_mid({"bid_price": None, "ask_price": 762.38}) is None
    assert two_sided_mid({"bid_price": "garbage", "ask_price": 762.38}) is None


def test_string_numerics_coerce():
    # Postgres/JSON round-trips deliver numerics as strings elsewhere in
    # this codebase; the guard must coerce rather than reject them.
    assert two_sided_mid({"bid_price": "10.0", "ask_price": "11.0"}) == 10.5


# ---------------------------------------------------------------------------
# benchmark.spy_mid — the snapshot consumer
# ---------------------------------------------------------------------------

class _FakeQuoteClient:
    def __init__(self, quote=None, raise_exc=False):
        self.quote = quote
        self.raise_exc = raise_exc

    def get_latest_quote(self, symbol):
        assert symbol == "SPY"
        if self.raise_exc:
            raise RuntimeError("feed down")
        return self.quote


def test_spy_mid_two_sided_rounds():
    client = _FakeQuoteClient({"bid_price": 762.331, "ask_price": 762.382})
    assert benchmark.spy_mid(client) == 762.36


def test_spy_mid_one_sided_returns_none_not_half_price():
    client = _FakeQuoteClient({"bid_price": 0.0, "ask_price": 762.38})
    assert benchmark.spy_mid(client) is None


def test_spy_mid_failure_still_returns_none():
    assert benchmark.spy_mid(_FakeQuoteClient(raise_exc=True)) is None


# ---------------------------------------------------------------------------
# screening width filter — one-sided must reject, not pass as 0.0
# ---------------------------------------------------------------------------

class _FakeScreeningClient:
    def __init__(self, quote):
        self.quote = quote

    def get_snapshots(self, batch):
        return {s: {"latest_trade_price": 100.0, "daily_volume": 5_000_000,
                    "atr": 2.0} for s in batch}

    def get_latest_quote(self, symbol):
        return self.quote


def test_screening_rejects_one_sided_quote():
    # get_latest_quote's spread_pct falls back to 0.0 when bid <= 0 — the
    # exact shape that used to sail through the width filter.
    client = _FakeScreeningClient(
        {"bid_price": 0.0, "ask_price": 100.10, "spread_pct": 0.0})
    rejections: list[dict] = []
    kept = filter_universe(["SPY"], client, rejections_out=rejections)
    assert kept == []
    assert len(rejections) == 1
    assert rejections[0]["stage"] == "screening"
    assert "one-sided" in rejections[0]["reasons"][0]


def test_screening_still_passes_two_sided_quote():
    client = _FakeScreeningClient(
        {"bid_price": 99.99, "ask_price": 100.01, "spread_pct": 0.02})
    kept = filter_universe(["SPY"], client)
    assert [c.symbol for c in kept] == ["SPY"]

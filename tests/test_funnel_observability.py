"""Funnel observability (2026-09-01): every pre-menu rejection — screening,
trend filter, vol filter — must carry a journaled reason. Motivated by
2026-08-31: the menu was empty all day and neither the log nor the decision
journal could say which stage emptied it (trend blocks were a silent
`continue`; screening reasons were DEBUG-only). Also pins the screening
max_price fix: the 300 cap carried over from stock trading structurally
excluded SPY (~767) and QQQ (~717) from the ETF universe."""
from __future__ import annotations

import bot
from screening.filters import filter_universe
from signals.swing import Signal


# ---------------------------------------------------------------------------
# Screening stage
# ---------------------------------------------------------------------------

class FakeScreeningClient:
    def __init__(self, snapshots: dict[str, dict], quotes: dict[str, dict] | None = None,
                 quote_fails: set[str] | None = None):
        self.snapshots = snapshots
        self.quotes = quotes or {}
        self.quote_fails = quote_fails or set()

    def get_snapshots(self, batch):
        return {s: self.snapshots[s] for s in batch if s in self.snapshots}

    def get_latest_quote(self, symbol):
        if symbol in self.quote_fails:
            raise RuntimeError("quote unavailable")
        return self.quotes.get(symbol, {"spread_pct": 0.01})


def _snap(price: float, volume: int = 5_000_000, atr: float | None = None) -> dict:
    snap = {"latest_trade_price": price, "daily_volume": volume}
    if atr is not None:
        snap["atr"] = atr
    return snap


def test_spy_qqq_price_levels_pass_screening():
    # Regression pin for the max_price 300 -> 1000 fix: index-ETF price
    # levels must survive screening; a genuinely extreme price must not.
    client = FakeScreeningClient({
        "SPY": _snap(767.17, atr=6.0),
        "QQQ": _snap(716.69, atr=7.0),
        "BRKA": _snap(1500.0, atr=12.0),
    })
    rejections: list[dict] = []
    kept = filter_universe(["SPY", "QQQ", "BRKA"], client, rejections_out=rejections)
    assert sorted(c.symbol for c in kept) == ["QQQ", "SPY"]
    assert len(rejections) == 1
    rej = rejections[0]
    assert rej["ticker"] == "BRKA"
    assert rej["stage"] == "screening"
    assert "price" in rej["reasons"][0]


def test_screening_rejection_reasons_are_reported():
    client = FakeScreeningClient(
        {
            "THIN": _snap(100.0, volume=1_000),        # below min_avg_volume
            "QUIET": _snap(100.0, atr=0.1),            # ATR% 0.1 < min 0.5
            "NOQUOTE": _snap(100.0),
        },
        quote_fails={"NOQUOTE"},
    )
    rejections: list[dict] = []
    kept = filter_universe(["THIN", "QUIET", "NOQUOTE"], client, rejections_out=rejections)
    assert kept == []
    by_ticker = {r["ticker"]: r for r in rejections}
    assert set(by_ticker) == {"THIN", "QUIET", "NOQUOTE"}
    assert all(r["stage"] == "screening" for r in rejections)
    assert "volume" in by_ticker["THIN"]["reasons"][0]
    assert "ATR%" in by_ticker["QUIET"]["reasons"][0]
    assert "quote" in by_ticker["NOQUOTE"]["reasons"][0]


def test_filter_universe_without_rejections_out_still_works():
    client = FakeScreeningClient({"SPY": _snap(767.17, atr=6.0)})
    kept = filter_universe(["SPY"], client)
    assert [c.symbol for c in kept] == ["SPY"]


# ---------------------------------------------------------------------------
# Trend / volatility filter stage
# ---------------------------------------------------------------------------

class FakeBarsClient:
    def __init__(self, bars: list[dict]):
        self.bars = bars

    def get_bars(self, *args, **kwargs):
        return self.bars


def _bars(closes: list[float], ranges: list[float]) -> list[dict]:
    return [
        {"close": c, "high": c + r, "low": c - r}
        for c, r in zip(closes, ranges)
    ]


def _signal(ticker: str, direction: str) -> Signal:
    return Signal(ticker=ticker, direction=direction, strength=0.8, indicators={})


def test_trend_block_is_logged_and_recorded():
    # Steadily rising closes -> EMA50 > EMA200 (bullish); a short signal
    # must be blocked AND leave a journaled trace (was a silent continue).
    closes = [100 + i * 0.5 for i in range(260)]
    client = FakeBarsClient(_bars(closes, [1.0] * 260))
    kept, rejections = bot._apply_trend_and_volatility_filters(
        client, [_signal("SPY", "short")]
    )
    assert kept == []
    assert len(rejections) == 1
    rej = rejections[0]
    assert rej["ticker"] == "SPY"
    assert rej["stage"] == "trend_filter"
    assert any("BLOCKED" in r for r in rej["reasons"])


def test_vol_floor_rejection_is_recorded():
    # Rising price with constant absolute range: ATR% declines monotonically,
    # so the latest reading ranks near the bottom of its own history — below
    # even the relaxed floor. Trend passes (bullish + long), vol must reject
    # with a journaled percentile reason.
    closes = [100 + i * 1.0 for i in range(260)]
    client = FakeBarsClient(_bars(closes, [1.0] * 260))
    kept, rejections = bot._apply_trend_and_volatility_filters(
        client, [_signal("SPY", "long")]
    )
    assert kept == []
    assert len(rejections) == 1
    rej = rejections[0]
    assert rej["stage"] == "vol_filter"
    assert "realized vol percentile" in rej["reasons"][0]


def test_aligned_signal_with_elevated_vol_survives():
    # Mild uptrend, quiet history, volatile recent stretch: ATR% of the last
    # bar ranks near the top -> passes both filters, no rejections recorded.
    closes = [100 + i * 0.05 for i in range(260)]
    ranges = [0.2] * 230 + [3.0] * 30
    client = FakeBarsClient(_bars(closes, ranges))
    kept, rejections = bot._apply_trend_and_volatility_filters(
        client, [_signal("SPY", "long")]
    )
    assert rejections == []
    assert len(kept) == 1
    sig, realized_vol = kept[0]
    assert sig.ticker == "SPY"
    assert realized_vol > 0

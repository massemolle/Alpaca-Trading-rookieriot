"""Entry fills must stay inside ONE slippage budget of the judged credit.

Live evidence 2026-09-11: the pre-trade gate re-anchors plan.credit_estimate
to the fresh mid (tolerating 20% decay), then the marketable-limit floor took
another max_entry_slippage_pct off THAT — a compounded floor ~28% below the
credit the LLM actually selected on. Both wide-quoted fills that day landed
exactly at the compounded floor (GLD judged $68 → filled $51, XLK judged $53
→ filled $39), and XLK's stop (2x of the *fill*) then sat below the spread's
own crossing cost at entry — it stopped out 90 minutes later, −$39, on a day
XLK rose +1.31%. `bot._entry_limit_credit` anchors the floor to
max(judged, fresh) so the entry either fills within the single documented
slippage budget of the judged economics or rests unfilled and dies through
the existing pending → rejected path.

Also covered here: the pending → open resolution path in manage_open_spreads
reads the REST order's fill price. Alpaca's top-level filled_avg_price is
"cost to acquire" — NEGATIVE for a credit open (CLAUDE.md sign gotcha, same
class as tests/test_fill_confirmation_sign.py). The old naive float() read
would record a pending-resolved credit as negative, flipping should_close
into an instant bogus "profit target" exit; the path now reuses the
executor's pinned extractor. The anchored (higher) limit makes resting
orders more common, so this path is load-bearing now.
"""
from __future__ import annotations

import pytest

import bot
import executor_mcp
from tests.conftest import FakeMCP


# ---------------------------------------------------------------- limit anchor

def test_limit_floor_anchors_to_judged_credit_when_fresh_is_lower():
    # The gate's re-anchored fresh credit must NOT drag the floor down.
    assert bot._entry_limit_credit(68.0, 56.5) == executor_mcp.limit_credit_price(68.0)
    assert bot._entry_limit_credit(68.0, 56.5) > executor_mcp.limit_credit_price(56.5)


def test_limit_floor_would_have_refused_the_0911_fills():
    """Regression pin of the exact 2026-09-11 shapes: the floors implied by
    the judged credits sit strictly ABOVE the degraded fills that happened
    ($0.51/share GLD, $0.39/share XLK) — under the anchored floor those
    orders rest unfilled instead of filling at the compounded bottom."""
    gld_floor = bot._entry_limit_credit(68.0, 56.5)
    xlk_floor = bot._entry_limit_credit(53.0, 43.5)
    # Anchor identity (env-robust: no assumption about the slippage value):
    assert gld_floor == executor_mcp.limit_credit_price(68.0)  # 0.61 at the 10% default
    assert xlk_floor == executor_mcp.limit_credit_price(53.0)  # 0.48 at the 10% default
    # The regression itself: floors strictly above the fills that happened.
    # (Only a slippage budget >=25% could re-admit them — that failure would
    # be real, not spurious.)
    assert gld_floor > 0.51
    assert xlk_floor > 0.39


def test_limit_floor_takes_fresh_credit_when_it_improved():
    # If the market moved FOR us between selection and the gate, demand the
    # better price — the anchor never lowers the floor, only raises it.
    assert bot._entry_limit_credit(68.0, 80.0) == executor_mcp.limit_credit_price(80.0)


# ------------------------------------------------- pending-resolution sign fix

class _RecordingDB:
    def __init__(self, spreads):
        self.spreads = spreads
        self.status_updates: list[tuple] = []

    def get_manageable_spreads(self):
        return [dict(s) for s in self.spreads]

    def update_spread_status(self, spread_id, status, **kwargs):
        self.status_updates.append((spread_id, status, kwargs))


class _OrderClient:
    def __init__(self, order):
        self._order = order

    def get_order(self, order_id):
        return dict(self._order)


def _pending_row(**overrides):
    row = {
        "id": 42,
        "status": "pending",
        "underlying": "GLD",
        "direction": "bear_call",
        "expiration": "2099-01-01",
        "short_symbol": "GLD260921C00413000",
        "long_symbol": "GLD260921C00418000",
        "contracts": 1,
        "credit_received": "68.0",
        "alpaca_order_ids": ["abc-123"],
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_pending_resolution_negates_top_level_fill_price(monkeypatch):
    """A resting credit open that fills later reports top-level
    filled_avg_price = -0.54 for a real $0.54/share credit (the pinned
    Alpaca convention). The resolved row must record +54.0, not -54.0."""
    fake_db = _RecordingDB([_pending_row()])
    monkeypatch.setattr(bot, "db", fake_db)
    client = _OrderClient({"id": "abc-123", "status": "filled", "filled_avg_price": "-0.54"})

    await bot.manage_open_spreads(FakeMCP(), client, market_open=False)

    assert fake_db.status_updates, "pending spread was never resolved"
    spread_id, status, kwargs = fake_db.status_updates[0]
    assert (spread_id, status) == (42, "open")
    assert kwargs.get("fill_credit") == pytest.approx(54.0)


@pytest.mark.asyncio
async def test_pending_resolution_prefers_per_leg_fill_prices(monkeypatch):
    """REST mleg orders also carry per-leg fills; the extractor's per-leg
    net (sell 0.93 - buy 0.59 = 0.34/share) takes precedence over the
    top-level field and needs no sign flip."""
    fake_db = _RecordingDB([_pending_row()])
    monkeypatch.setattr(bot, "db", fake_db)
    client = _OrderClient({
        "id": "abc-123", "status": "filled",
        "filled_avg_price": "-0.34",  # would also be correct via negation
        "legs": [
            {"symbol": "GLD260921C00413000", "side": "sell", "filled_avg_price": "0.93"},
            {"symbol": "GLD260921C00418000", "side": "buy", "filled_avg_price": "0.59"},
        ],
    })

    await bot.manage_open_spreads(FakeMCP(), client, market_open=False)

    assert fake_db.status_updates, "pending spread was never resolved"
    _, status, kwargs = fake_db.status_updates[0]
    assert status == "open"
    assert kwargs.get("fill_credit") == pytest.approx(34.0)

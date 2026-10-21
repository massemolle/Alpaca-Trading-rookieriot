"""Virtual books may only realize exits when the real book could trade.

Live evidence 2026-10-21: the 20:30Z cron cycle (after the 20:00Z close)
"stopped" the shadow/random/menu rows for XLK 188/193 and 190/195 at
after-hours marks (−$162 / −$144.5 realized at 20:30:15–16Z), while the real
spreads on the same strikes were lawfully held — bot.manage_open_spreads
skips all exit handling when the market is closed, so the real book settles
them at the NEXT open's prices. Nine of the sixty virtual closes in that
night's context window carried 20:30Z timestamps: prices no order could
trade at, flowing straight into the ablation totals and menu-regret
outcomes the nightly review decides from.

Pinned here:
- market closed → manage_open refreshes two-sided marks (evening-context
  telemetry) but realizes NOTHING: no stop, no profit target, no expiry
  settlement;
- market open → stop realization unchanged;
- the default (no kwarg) stays open-market behavior, and bot.py must pass
  its session state through explicitly.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import executor_mcp
import shadow_book


def _row(**over) -> dict:
    row = {
        "id": 1,
        "short_symbol": "XLK261030C00188000",
        "long_symbol": "XLK261030C00193000",
        "credit_received": "100.0",
        "contracts": 1,
        "expiration": "2099-01-01",  # far out: should_force_close stays False
    }
    row.update(over)
    return row


def _wire(monkeypatch, *, rows, mark, two_sided):
    marks: list[tuple] = []
    closes: list[tuple] = []
    monkeypatch.setattr(shadow_book, "_get_open", lambda: rows)
    monkeypatch.setattr(shadow_book, "_mark", lambda rid, m: marks.append((rid, m)))
    monkeypatch.setattr(
        shadow_book, "_close", lambda rid, status, pnl: closes.append((rid, status, pnl))
    )

    async def fake_mark_detail(mcp, short, long):
        return mark, two_sided

    monkeypatch.setattr(executor_mcp, "get_spread_mark_detail", fake_mark_detail)
    return marks, closes


@pytest.mark.asyncio
async def test_closed_market_marks_but_realizes_nothing(monkeypatch):
    # Two-sided mark deep past the 2x stop — open-market behavior would stop.
    marks, closes = _wire(monkeypatch, rows=[_row()], mark=250.0, two_sided=True)
    await shadow_book.manage_open(None, market_open=False)
    assert marks == [(1, 250.0)]
    assert closes == []


@pytest.mark.asyncio
async def test_closed_market_defers_expiry_settlement(monkeypatch):
    # Expired row with a dead quote: open-market behavior books closed_expiry;
    # closed-market must wait for a session, like the real force-close path.
    marks, closes = _wire(
        monkeypatch, rows=[_row(expiration="2020-01-01")], mark=None, two_sided=False
    )
    await shadow_book.manage_open(None, market_open=False)
    assert marks == []
    assert closes == []


@pytest.mark.asyncio
async def test_open_market_stop_unchanged(monkeypatch):
    marks, closes = _wire(monkeypatch, rows=[_row()], mark=250.0, two_sided=True)
    await shadow_book.manage_open(None, market_open=True)
    assert marks == [(1, 250.0)]
    assert closes == [(1, "closed_stop", -150.0)]


@pytest.mark.asyncio
async def test_default_is_open_market(monkeypatch):
    # Callers that predate the kwarg keep trading-session behavior.
    _, closes = _wire(monkeypatch, rows=[_row()], mark=250.0, two_sided=True)
    await shadow_book.manage_open(None)
    assert closes == [(1, "closed_stop", -150.0)]


def test_bot_passes_session_state_through():
    source = Path(__file__).resolve().parent.parent.joinpath("bot.py").read_text()
    assert "shadow_book.manage_open(mcp, market_open=market_open)" in source, (
        "bot.py must pass its market_open flag to shadow_book.manage_open — "
        "an unqualified call realizes virtual exits on after-hours quotes"
    )

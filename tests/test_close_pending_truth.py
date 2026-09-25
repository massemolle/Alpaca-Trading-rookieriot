"""A close that has not filled must never book P&L.

Live evidence 2026-09-23 (TLT id 35, 81/86 bear call): the profit target
fired at 14:30Z, the close limit order rested past the executor's poll
window, and manage_open_spreads fell back to booking the MARK as the exit
price — the DB recorded closed_profit +$38 while both legs (and the working
order) were still at the broker. From 15:00Z on, every cycle of the session
reconcile-blocked against that divergence ("broker option legs missing from
DB"), which also skipped ALL exit management for the five genuinely open
spreads on a red day. The order expired at the bell; the position survived
the day unmanaged and the block persists until the row is repaired.

Pinned here:
- a pending (unfilled) close parks the row as pending_close, records no
  realized P&L, and stores the close order id;
- pending_close rows are resolved against the broker next cycle — a real
  fill books the real debit (both sign conventions), a dead order reverts
  the row to open and exit management resumes the same cycle;
- the reconciler treats pending_close legs as expected-at-broker, so the
  in-flight cycle does not block the whole bot;
- the DRY_RUN close shape (status "dry_run") still records the mark-based
  close, unchanged.
"""
from __future__ import annotations

import pytest

import bot
import executor_mcp
import risk_gate
from tests.conftest import FakeMCP


class _CloseDB:
    def __init__(self, spreads):
        self.spreads = spreads
        self.status_updates: list[tuple] = []
        self.closes: list[tuple] = []

    def get_manageable_spreads(self):
        return [dict(s) for s in self.spreads if s.get("status") in ("open", "pending")]

    def get_spreads_by_status(self, status):
        return [dict(s) for s in self.spreads if s.get("status") == status]

    def update_spread_status(self, spread_id, status, **kwargs):
        self.status_updates.append((spread_id, status, kwargs))

    def record_spread_close(self, spread_id, status, realized_pnl):
        self.closes.append((spread_id, status, realized_pnl))


class _OrderClient:
    def __init__(self, order=None):
        self._order = order or {}

    def get_order(self, order_id):
        return dict(self._order)


def _tlt_row(**overrides):
    # The exact 2026-09-23 shape: id 35, $74 credit, profit target at a $36 mark.
    row = {
        "id": 35,
        "status": "open",
        "underlying": "TLT",
        "direction": "bear_call",
        "expiration": "2099-01-01",
        "short_symbol": "TLT260928C00081000",
        "long_symbol": "TLT260928C00086000",
        "contracts": 1,
        "credit_received": "74.0",
        "alpaca_order_ids": ["open-order-id"],
    }
    row.update(overrides)
    return row


def _wire_exit_path(monkeypatch, close_result, mark=36.0):
    """Route an open spread straight into the close submission."""
    monkeypatch.setattr(risk_gate, "should_force_close", lambda **kw: (False, None))
    monkeypatch.setattr(risk_gate, "should_close", lambda **kw: (True, "profit target"))

    async def fake_mark(mcp, short_symbol, long_symbol):
        return mark, True  # (mark, short leg two-sided)

    async def fake_close(mcp, **kwargs):
        return close_result

    monkeypatch.setattr(executor_mcp, "get_spread_mark_detail", fake_mark)
    monkeypatch.setattr(executor_mcp, "close_spread", fake_close)


# ------------------------------------------------ recording, at close submit

@pytest.mark.asyncio
async def test_resting_close_parks_pending_close_and_books_nothing(monkeypatch):
    """Regression pin of 2026-09-23: status 'pending' + no fill price must
    NOT fall back to the mark — no realized P&L, row parked as
    pending_close with the close order id."""
    fake_db = _CloseDB([_tlt_row()])
    monkeypatch.setattr(bot, "db", fake_db)
    _wire_exit_path(monkeypatch, executor_mcp.OrderResult(
        order_ids=["close-order-id"], client_order_id="c", status="pending",
        fill_credit=None,
    ))

    await bot.manage_open_spreads(FakeMCP(), _OrderClient(), market_open=True)

    assert fake_db.closes == [], "an unfilled close must not record a close"
    assert fake_db.status_updates == [
        (35, "pending_close", {"alpaca_order_ids": ["close-order-id"]}),
    ]


@pytest.mark.asyncio
async def test_filled_close_still_books_the_real_debit(monkeypatch):
    fake_db = _CloseDB([_tlt_row()])
    monkeypatch.setattr(bot, "db", fake_db)
    _wire_exit_path(monkeypatch, executor_mcp.OrderResult(
        order_ids=["close-order-id"], client_order_id="c", status="filled",
        fill_credit=36.0,  # real debit paid
    ))

    await bot.manage_open_spreads(FakeMCP(), _OrderClient(), market_open=True)

    assert fake_db.closes == [(35, "closed_profit", pytest.approx(38.0))]


@pytest.mark.asyncio
async def test_dry_run_close_shape_still_records_mark_based_close(monkeypatch):
    """DRY_RUN close_spread returns status 'dry_run' with no fill — the
    simulated books must keep recording the mark-based close."""
    fake_db = _CloseDB([_tlt_row()])
    monkeypatch.setattr(bot, "db", fake_db)
    _wire_exit_path(monkeypatch, executor_mcp.OrderResult(
        order_ids=["dryrun-close-x"], client_order_id="c", status="dry_run",
        fill_credit=None,
    ), mark=36.0)

    await bot.manage_open_spreads(FakeMCP(), _OrderClient(), market_open=True)

    assert fake_db.closes == [(35, "closed_profit", pytest.approx(38.0))]
    assert fake_db.status_updates == []


# ------------------------------------------------- pending_close resolution

@pytest.mark.asyncio
async def test_pending_close_resolves_real_fill_topline_sign(monkeypatch):
    """Close order filled after resting: top-level filled_avg_price is cost
    to acquire (+0.36 for a $0.36/share debit); the resolver must book a
    +$38 profit on the $74 credit, not −$110."""
    row = _tlt_row(status="pending_close", alpaca_order_ids=["close-order-id"])
    fake_db = _CloseDB([row])
    monkeypatch.setattr(bot, "db", fake_db)
    client = _OrderClient({"id": "close-order-id", "status": "filled",
                           "filled_avg_price": "0.36"})

    await bot.manage_open_spreads(FakeMCP(), client, market_open=False)

    assert fake_db.closes == [(35, "closed_profit", pytest.approx(38.0))]


@pytest.mark.asyncio
async def test_pending_close_resolves_real_fill_per_leg(monkeypatch):
    """Per-leg fills: buy short back 0.80, sell long 0.30 → net debit 0.50
    → realized 74 − 50 = +24."""
    row = _tlt_row(status="pending_close", alpaca_order_ids=["close-order-id"])
    fake_db = _CloseDB([row])
    monkeypatch.setattr(bot, "db", fake_db)
    client = _OrderClient({
        "id": "close-order-id", "status": "filled",
        "legs": [
            {"symbol": "TLT260928C00081000", "side": "buy", "filled_avg_price": "0.80"},
            {"symbol": "TLT260928C00086000", "side": "sell", "filled_avg_price": "0.30"},
        ],
    })

    await bot.manage_open_spreads(FakeMCP(), client, market_open=False)

    assert fake_db.closes == [(35, "closed_profit", pytest.approx(24.0))]


@pytest.mark.asyncio
async def test_pending_close_dead_order_reverts_to_open_and_resumes_exits(monkeypatch):
    """The day order expired unfilled: the position is still ours. The row
    goes back to 'open' and exit management resumes THE SAME cycle — here
    the retried close fills, proving the fall-through."""
    row = _tlt_row(status="pending_close", alpaca_order_ids=["close-order-id"])
    fake_db = _CloseDB([row])
    monkeypatch.setattr(bot, "db", fake_db)
    _wire_exit_path(monkeypatch, executor_mcp.OrderResult(
        order_ids=["close-order-2"], client_order_id="c", status="filled",
        fill_credit=36.0,
    ))
    client = _OrderClient({"id": "close-order-id", "status": "expired"})

    await bot.manage_open_spreads(FakeMCP(), client, market_open=True)

    assert (35, "open", {}) in fake_db.status_updates
    assert fake_db.closes == [(35, "closed_profit", pytest.approx(38.0))]


@pytest.mark.asyncio
async def test_pending_close_dead_order_after_expiration_closes_expiry(monkeypatch):
    """If the contracts expired before any close filled, settlement already
    happened at the broker — record closed_expiry with unknown P&L instead
    of resurrecting a position that no longer exists."""
    row = _tlt_row(status="pending_close", alpaca_order_ids=["close-order-id"],
                   expiration="2020-01-01")
    fake_db = _CloseDB([row])
    monkeypatch.setattr(bot, "db", fake_db)
    client = _OrderClient({"id": "close-order-id", "status": "expired"})

    await bot.manage_open_spreads(FakeMCP(), client, market_open=False)

    assert fake_db.closes == [(35, "closed_expiry", None)]
    assert fake_db.status_updates == []


@pytest.mark.asyncio
async def test_pending_close_still_working_is_left_alone(monkeypatch):
    row = _tlt_row(status="pending_close", alpaca_order_ids=["close-order-id"])
    fake_db = _CloseDB([row])
    monkeypatch.setattr(bot, "db", fake_db)
    client = _OrderClient({"id": "close-order-id", "status": "accepted"})

    await bot.manage_open_spreads(FakeMCP(), client, market_open=True)

    assert fake_db.closes == []
    assert fake_db.status_updates == []


# ----------------------------------------------------- reconciler awareness

class _BrokerClient:
    def __init__(self, positions):
        self._positions = positions

    def get_positions(self):
        return [dict(p) for p in self._positions]

    def get_orders(self, status="open"):
        return []


def _reconciler_db(monkeypatch, *, open_rows=(), pending_close_rows=()):
    import reconciler as rec

    class FakeDB:
        @staticmethod
        def get_open_spreads():
            return [dict(r) for r in open_rows]

        @staticmethod
        def get_spreads_by_status(status):
            if status == "pending_close":
                return [dict(r) for r in pending_close_rows]
            return []

        @staticmethod
        def get_recently_closed_spreads(days=10):
            return []

        @staticmethod
        def reopen_spread(spread_id):
            raise AssertionError(
                "false-close self-heal must not fire in these scenarios"
            )

    monkeypatch.setattr(rec, "db", FakeDB)
    return rec


def test_reconcile_tolerates_pending_close_legs_at_broker(monkeypatch):
    """The exact 2026-09-23 broker state (both TLT legs still held) must
    NOT block when the DB explains them with a pending_close row."""
    rec = _reconciler_db(monkeypatch, pending_close_rows=[{
        "id": 35,
        "short_symbol": "TLT260928C00081000",
        "long_symbol": "TLT260928C00086000",
        "contracts": 1,
    }])
    client = _BrokerClient([
        {"symbol": "TLT260928C00081000", "side": "short", "qty": 1.0},
        {"symbol": "TLT260928C00086000", "side": "long", "qty": 1.0},
    ])

    assert rec.reconcile(client).ok


def test_reconcile_still_blocks_truly_orphan_legs(monkeypatch):
    """Without the pending_close row the same broker state stays a block —
    the safety check is narrowed for known in-flight legs only."""
    rec = _reconciler_db(monkeypatch)
    client = _BrokerClient([
        {"symbol": "TLT260928C00081000", "side": "short", "qty": 1.0},
        {"symbol": "TLT260928C00086000", "side": "long", "qty": 1.0},
    ])

    result = rec.reconcile(client)
    assert not result.ok
    assert "missing from DB" in result.reason


def test_reconcile_skips_qty_check_for_in_flight_symbols(monkeypatch):
    """A stacked symbol mid-close: one spread open, its twin pending_close.
    Broker qty (2) exceeds the settled expectation (1) for exactly one
    cycle — that transition must not block."""
    legs = {
        "short_symbol": "QQQ261002P00730000",
        "long_symbol": "QQQ261002P00725000",
        "contracts": 1,
    }
    rec = _reconciler_db(
        monkeypatch,
        open_rows=[{"id": 1, **legs}],
        pending_close_rows=[{"id": 2, **legs}],
    )
    client = _BrokerClient([
        {"symbol": "QQQ261002P00730000", "side": "short", "qty": 2.0},
        {"symbol": "QQQ261002P00725000", "side": "long", "qty": 2.0},
    ])

    assert rec.reconcile(client).ok

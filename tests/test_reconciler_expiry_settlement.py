"""Reconciler expiry settlement (2026-09-28).

TLT id 35's force-close rested unfilled through its own expiration day; the
day order died at the bell and the pending-close resolver correctly flipped
the row back to 'open'. Overnight the expired legs left the broker, so the
next morning's reconcile would read the row as phantom ("DB-open legs
missing at broker") and fail-close every cycle — the 09-24 deadlock class
again, but in the one direction _heal_false_closes cannot repair (the heal
needs legs PRESENT at the broker).

Pinned here: an 'open' row settles to closed_expiry (P&L None) only under
proof — expiration STRICTLY before today (UTC) AND neither leg at the
broker. Expiring today, any leg still present, or an unexpired row with
missing legs: nothing is touched and divergence blocks exactly as before.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

TODAY = datetime.now(timezone.utc).date()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()
NEXT_WEEK = (TODAY + timedelta(days=7)).isoformat()


def _row(**overrides):
    row = {
        "id": 35,
        "underlying": "TLT",
        "short_symbol": "TLT260928C00081000",
        "long_symbol": "TLT260928C00086000",
        "contracts": 1,
        "status": "open",
        "expiration": YESTERDAY,
        "realized_pnl": None,
        "closed_at": None,
    }
    row.update(overrides)
    return row


TLT_LEGS = [
    {"symbol": "TLT260928C00081000", "side": "short", "qty": 1.0},
    {"symbol": "TLT260928C00086000", "side": "long", "qty": 1.0},
]


class _BrokerClient:
    def __init__(self, positions):
        self._positions = positions

    def get_positions(self):
        return [dict(p) for p in self._positions]

    def get_orders(self, status="open"):
        return []


def _wire(monkeypatch, *, rows):
    """Stateful fake db, mirroring test_reconciler_false_close_heal: writes
    mutate the row list so re-reads inside reconcile see the new state."""
    import reconciler as rec

    rows = [dict(r) for r in rows]

    class FakeDB:
        closed: list[tuple[int, str, float | None]] = []

        @staticmethod
        def get_open_spreads():
            return [dict(r) for r in rows if r.get("status") == "open"]

        @staticmethod
        def get_spreads_by_status(status):
            return [dict(r) for r in rows if r.get("status") == status]

        @staticmethod
        def get_recently_closed_spreads(days=10):
            return [
                dict(r) for r in rows
                if str(r.get("status", "")).startswith("closed")
            ]

        @staticmethod
        def record_spread_close(spread_id, status, realized_pnl):
            FakeDB.closed.append((spread_id, status, realized_pnl))
            for r in rows:
                if r["id"] == spread_id:
                    r["status"] = status
                    r["realized_pnl"] = realized_pnl

        @staticmethod
        def reopen_spread(spread_id):
            for r in rows:
                if r["id"] == spread_id:
                    r["status"] = "open"
                    r["realized_pnl"] = None
                    r["closed_at"] = None

    FakeDB.closed = []
    monkeypatch.setattr(rec, "db", FakeDB)
    return rec, FakeDB, rows


def test_expired_row_with_no_broker_legs_settles_and_unblocks(monkeypatch):
    """The literal morning-after shape: expiration passed, legs gone —
    closed_expiry with unknown P&L, and the cycle proceeds."""
    rec, fake, rows = _wire(monkeypatch, rows=[_row()])
    result = rec.reconcile(_BrokerClient([]))

    assert result.ok
    assert fake.closed == [(35, "closed_expiry", None)]
    assert rows[0]["status"] == "closed_expiry"
    assert rows[0]["realized_pnl"] is None


def test_expiration_as_date_object_settles(monkeypatch):
    """Postgres date columns arrive as datetime.date, not str."""
    rec, fake, rows = _wire(
        monkeypatch, rows=[_row(expiration=TODAY - timedelta(days=1))]
    )
    result = rec.reconcile(_BrokerClient([]))

    assert result.ok
    assert rows[0]["status"] == "closed_expiry"


def test_expired_row_with_legs_still_at_broker_is_untouched(monkeypatch):
    """Broker hasn't processed the expiration yet: no settlement — the row
    stays open for the manage loop, and nothing blocks (legs match)."""
    rec, fake, rows = _wire(monkeypatch, rows=[_row()])
    result = rec.reconcile(_BrokerClient(TLT_LEGS))

    assert result.ok
    assert fake.closed == []
    assert rows[0]["status"] == "open"


def test_expired_row_with_one_surviving_leg_blocks(monkeypatch):
    """One leg still at the broker (e.g. the short was assigned): no proof
    of clean settlement — no settle, and the missing leg blocks."""
    rec, fake, rows = _wire(monkeypatch, rows=[_row()])
    result = rec.reconcile(_BrokerClient(TLT_LEGS[:1]))

    assert not result.ok
    assert fake.closed == []
    assert rows[0]["status"] == "open"
    assert "missing at broker" in result.reason


def test_unexpired_row_with_missing_legs_still_blocks(monkeypatch):
    """Regression guard: the phantom check is unchanged for live
    expirations — vanished legs on an unexpired spread stay a hard block."""
    rec, fake, rows = _wire(monkeypatch, rows=[_row(expiration=NEXT_WEEK)])
    result = rec.reconcile(_BrokerClient([]))

    assert not result.ok
    assert fake.closed == []
    assert rows[0]["status"] == "open"


def test_expiring_today_with_missing_legs_still_blocks(monkeypatch):
    """Expiration day itself is not proof — the contracts may still trade
    (or the legs' absence means something worse). Strictly-past only."""
    rec, fake, rows = _wire(monkeypatch, rows=[_row(expiration=TODAY.isoformat())])
    result = rec.reconcile(_BrokerClient([]))

    assert not result.ok
    assert fake.closed == []


def test_unreadable_expiration_never_settles(monkeypatch):
    rec, fake, rows = _wire(monkeypatch, rows=[_row(expiration="not-a-date")])
    result = rec.reconcile(_BrokerClient([]))

    assert not result.ok
    assert fake.closed == []


def test_settlement_does_not_mask_other_divergence(monkeypatch):
    """One provably-expired row settles, but an unexplained broker leg still
    blocks, and the reason names only the genuine orphan."""
    orphan_leg = {"symbol": "GLD261005C00406000", "side": "short", "qty": 1.0}
    rec, fake, rows = _wire(monkeypatch, rows=[_row()])
    result = rec.reconcile(_BrokerClient([orphan_leg]))

    assert not result.ok
    assert rows[0]["status"] == "closed_expiry"
    assert "GLD261005C00406000" in result.reason
    assert "TLT260928C00081000" not in result.reason


def test_settled_row_is_not_resurrected_by_false_close_heal(monkeypatch):
    """closed_expiry rows enter the heal's candidate set, but with zero legs
    at the broker there is no orphan evidence — the settlement sticks."""
    rec, fake, rows = _wire(monkeypatch, rows=[_row()])
    result = rec.reconcile(_BrokerClient([]))
    assert rows[0]["status"] == "closed_expiry"

    # A second reconcile of the settled state stays clean and writes nothing.
    result = rec.reconcile(_BrokerClient([]))
    assert result.ok
    assert fake.closed == [(35, "closed_expiry", None)]

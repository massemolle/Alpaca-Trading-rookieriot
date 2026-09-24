"""Reconciler false-close self-heal (2026-09-24).

2026-09-23's incident left spread id 35 recorded as closed_profit while the
broker still held both TLT legs — the close order expired unfilled. The
09-23 fixes stopped NEW fictional closes (pending closes now park as
pending_close), but the already-poisoned row deadlocked every cycle of
2026-09-24 (325–341): entries AND all exit management skipped for a full
trading day because a one-row manual repair never ran.

Pinned here: when the broker holds BOTH legs of a recently-closed row at the
row's exact side and quantity, that is broker-truth proof the close never
took effect — the reconciler reverts the row to open (clearing the
fictional P&L) and re-runs the comparison once from fresh reads. Anything
short of an exact match heals nothing and blocks exactly as before; the
repair direction is only ever DB → broker.
"""
from __future__ import annotations


ROW_35 = {
    "id": 35,
    "underlying": "TLT",
    "short_symbol": "TLT260928C00081000",
    "long_symbol": "TLT260928C00086000",
    "contracts": 1,
    "status": "closed_profit",
    "realized_pnl": "38.0",
    "closed_at": "2026-09-23 14:30:53+00:00",
}

BROKER_TLT_LEGS = [
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
    """Stateful fake db: reopen_spread mutates the row so the reconcile
    re-run sees it as open, exactly like the real table."""
    import reconciler as rec

    rows = [dict(r) for r in rows]

    class FakeDB:
        reopened: list[int] = []

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
        def reopen_spread(spread_id):
            FakeDB.reopened.append(spread_id)
            for r in rows:
                if r["id"] == spread_id:
                    r["status"] = "open"
                    r["realized_pnl"] = None
                    r["closed_at"] = None

    monkeypatch.setattr(rec, "db", FakeDB)
    return rec, FakeDB, rows


def test_exact_row_35_shape_heals_and_unblocks(monkeypatch):
    """The live deadlock: closed_profit row, both legs at broker at recorded
    side+qty → row reverts to open and the cycle proceeds."""
    rec, fake, rows = _wire(monkeypatch, rows=[ROW_35])
    result = rec.reconcile(_BrokerClient(BROKER_TLT_LEGS))

    assert result.ok
    assert fake.reopened == [35]
    assert rows[0]["status"] == "open"
    assert rows[0]["realized_pnl"] is None
    assert rows[0]["closed_at"] is None


def test_no_matching_closed_row_still_blocks(monkeypatch):
    """Same broker legs, but the only closed row names different contracts —
    genuine orphans stay a hard block."""
    other = dict(ROW_35, id=99, short_symbol="SPY261005P00756000",
                 long_symbol="SPY261005P00751000")
    rec, fake, _ = _wire(monkeypatch, rows=[other])
    result = rec.reconcile(_BrokerClient(BROKER_TLT_LEGS))

    assert not result.ok
    assert "missing from DB" in result.reason
    assert fake.reopened == []


def test_single_leg_at_broker_blocks(monkeypatch):
    """Only one of the row's legs survives at the broker (e.g. a partial
    manual unwind): no proof the close never happened — no heal, block."""
    rec, fake, _ = _wire(monkeypatch, rows=[ROW_35])
    result = rec.reconcile(_BrokerClient(BROKER_TLT_LEGS[:1]))

    assert not result.ok
    assert fake.reopened == []


def test_qty_mismatch_blocks(monkeypatch):
    """Broker qty differs from the row's contracts (also covers two identical
    falsely-closed rows stacking to qty 2): fail closed for humans."""
    legs = [dict(BROKER_TLT_LEGS[0], qty=2.0), dict(BROKER_TLT_LEGS[1], qty=2.0)]
    rec, fake, _ = _wire(monkeypatch, rows=[ROW_35])
    result = rec.reconcile(_BrokerClient(legs))

    assert not result.ok
    assert fake.reopened == []


def test_side_flip_blocks(monkeypatch):
    """A leg on the wrong side is out-of-band trading, not a false close."""
    legs = [dict(BROKER_TLT_LEGS[0], side="long"), dict(BROKER_TLT_LEGS[1])]
    rec, fake, _ = _wire(monkeypatch, rows=[ROW_35])
    result = rec.reconcile(_BrokerClient(legs))

    assert not result.ok
    assert fake.reopened == []


def test_residual_orphans_still_block_after_heal(monkeypatch):
    """The heal fires for the provable false close, but an extra unexplained
    leg keeps the second pass blocking — single retry, no loop, and the
    remaining reason names only the genuine orphan."""
    legs = BROKER_TLT_LEGS + [{"symbol": "GLD261005C00406000", "side": "short", "qty": 1.0}]
    rec, fake, rows = _wire(monkeypatch, rows=[ROW_35])
    result = rec.reconcile(_BrokerClient(legs))

    assert not result.ok
    assert fake.reopened == [35]
    assert rows[0]["status"] == "open"
    assert "GLD261005C00406000" in result.reason
    assert "TLT260928C00081000" not in result.reason


def test_two_false_closes_both_heal(monkeypatch):
    """Independent falsely-closed rows in one cycle each repair."""
    spy = {
        "id": 40,
        "underlying": "SPY",
        "short_symbol": "SPY261005P00756000",
        "long_symbol": "SPY261005P00751000",
        "contracts": 1,
        "status": "closed_stop",
        "realized_pnl": "-20.0",
        "closed_at": "2026-09-23 15:00:00+00:00",
    }
    legs = BROKER_TLT_LEGS + [
        {"symbol": "SPY261005P00756000", "side": "short", "qty": 1.0},
        {"symbol": "SPY261005P00751000", "side": "long", "qty": 1.0},
    ]
    rec, fake, rows = _wire(monkeypatch, rows=[ROW_35, spy])
    result = rec.reconcile(_BrokerClient(legs))

    assert result.ok
    assert sorted(fake.reopened) == [35, 40]
    assert all(r["status"] == "open" for r in rows)

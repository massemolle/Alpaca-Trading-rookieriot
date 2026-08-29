"""Broker ↔ local-book reconciliation.

Alpaca positions/orders are the source of truth. The local `spreads` table is
a journal that must match; unexplained divergence blocks new entries.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import db

logger = logging.getLogger(__name__)


@dataclass
class ReconcileResult:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    broker_option_symbols: set[str] = field(default_factory=set)
    db_leg_symbols: set[str] = field(default_factory=set)
    pending_spreads: list[dict[str, Any]] = field(default_factory=list)
    open_orders: list[dict[str, Any]] = field(default_factory=list)

    @property
    def reason(self) -> str | None:
        return "; ".join(self.reasons) if self.reasons else None


def _option_symbols_from_positions(positions: list[dict[str, Any]]) -> set[str]:
    """Option OCC symbols typically contain digits + put/call letter; equity
    underlyings are short tickers. Conservative: treat any symbol longer than
    6 chars OR containing a digit as an option leg.
    """
    out: set[str] = set()
    for p in positions:
        sym = str(p.get("symbol") or "")
        if not sym:
            continue
        if any(ch.isdigit() for ch in sym) or len(sym) > 6:
            out.add(sym)
    return out


def _db_leg_symbols(spreads: list[dict[str, Any]]) -> set[str]:
    legs: set[str] = set()
    for s in spreads:
        if s.get("short_symbol"):
            legs.add(s["short_symbol"])
        if s.get("long_symbol"):
            legs.add(s["long_symbol"])
    return legs


def reconcile(client, *, block_on_mismatch: bool = True) -> ReconcileResult:
    """Compare Alpaca option positions to DB open/pending spreads.

    - Legs in DB but not at broker → phantom local position (block).
    - Legs at broker but not in DB → orphaned broker position (block).
    Pending spreads (submitted, not yet filled) are listed but do not by
    themselves fail reconciliation when their legs are still absent.
    """
    reasons: list[str] = []
    try:
        positions = client.get_positions()
    except Exception as exc:
        logger.exception("Failed to fetch broker positions")
        return ReconcileResult(ok=False, reasons=[f"broker positions unavailable: {exc}"])

    try:
        open_orders = client.get_orders(status="open")
    except Exception as exc:
        logger.exception("Failed to fetch open orders")
        return ReconcileResult(ok=False, reasons=[f"broker open orders unavailable: {exc}"])

    try:
        open_spreads = db.get_open_spreads()
        pending_spreads = db.get_spreads_by_status("pending")
    except Exception as exc:
        logger.exception("Failed to fetch local spreads")
        return ReconcileResult(ok=False, reasons=[f"local book unavailable: {exc}"])

    broker_syms = _option_symbols_from_positions(positions)
    # Pending rows are expected not to have broker positions yet — exclude
    # their legs from the "phantom DB" check.
    pending_legs = _db_leg_symbols(pending_spreads)
    open_legs = _db_leg_symbols(open_spreads)

    phantom = open_legs - broker_syms
    orphan = broker_syms - open_legs - pending_legs

    if phantom:
        reasons.append(f"DB-open legs missing at broker: {sorted(phantom)}")
    if orphan:
        reasons.append(f"broker option legs missing from DB: {sorted(orphan)}")

    ok = not reasons if block_on_mismatch else True
    if reasons:
        logger.error("Reconciliation mismatch: %s", "; ".join(reasons))
    else:
        logger.info(
            "Reconciliation OK: %d broker option legs, %d DB-open, %d pending, %d open orders",
            len(broker_syms), len(open_spreads), len(pending_spreads), len(open_orders),
        )

    return ReconcileResult(
        ok=ok,
        reasons=reasons,
        broker_option_symbols=broker_syms,
        db_leg_symbols=open_legs | pending_legs,
        pending_spreads=pending_spreads,
        open_orders=open_orders,
    )

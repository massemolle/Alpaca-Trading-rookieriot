"""Protections — "Gate 0" (Roadmap v2, adapted from freqtrade's protections).

Deterministic, journal-derived locks checked BEFORE screening and both risk
gates. Unlike freqtrade's event-written PairLocks, every lock here is
COMPUTED from the trades journal / snapshots each cycle — stateless, so it
survives restarts by construction and cannot desync from history.

Locks (all env-tunable, all fail-open on query error EXCEPT the drawdown
halt, which fails closed — it is a money-bounding check):

- cooldown:    an underlying that stopped out within PROT_COOLDOWN_MIN
               minutes may not be re-entered (would have stopped the
               2026-09-03 pattern of re-shorting QQQ 30 min after a stop).
- stop_streak: PROT_STOP_GUARD_N stop-outs across the book within
               PROT_STOP_GUARD_HOURS halts ALL new entries (a stop cluster
               means the vol regime moved; 2026-09-03 saw 6 in one day).
- drawdown:    equity down more than PROT_MAX_DRAWDOWN_PCT from the peak of
               the last PROT_DRAWDOWN_DAYS days halts ALL new entries while
               the condition holds.
- low_profit:  an underlying with cumulative realized P&L below
               PROT_LOW_PROFIT_FLOOR over PROT_LOW_PROFIT_DAYS is locked.

Exits and management are NEVER blocked by protections.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import db

logger = logging.getLogger(__name__)

_STOP_STATUSES = ("closed_stop",)


def _f(name: str, default: float) -> float:
    val = os.environ.get(name)
    return float(val) if val is not None else default


@dataclass
class ProtectionResult:
    allowed: bool
    reasons: list[str]


def _query_one(sql: str, params: tuple):
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def global_halt() -> ProtectionResult:
    """Book-level checks: stop-streak and drawdown. Blocks ALL new entries."""
    reasons: list[str] = []
    s = db._schema()

    # Stop-streak guard (fail-open: a broken query must not halt trading on
    # its own — this is a conformance check, not a money bound).
    n_max = int(_f("PROT_STOP_GUARD_N", 4))
    window_h = _f("PROT_STOP_GUARD_HOURS", 24)
    try:
        row = _query_one(
            f"""select count(*) from {s}.spreads
                where status = any(%s)
                  and closed_at > now() - make_interval(hours => %s)""",
            (list(_STOP_STATUSES), window_h),
        )
        if row and row[0] >= n_max:
            reasons.append(
                f"stop_streak: {row[0]} stop-outs in the last {window_h:.0f}h "
                f"(max {n_max}) — vol regime moved, entries halted"
            )
    except Exception:
        logger.exception("protections: stop_streak query failed (fail-open)")

    # Drawdown halt (fail-closed: this bounds money).
    dd_max = _f("PROT_MAX_DRAWDOWN_PCT", 0.03)
    dd_days = _f("PROT_DRAWDOWN_DAYS", 5)
    try:
        row = _query_one(
            f"""select max(equity), (select equity from {s}.account_snapshots
                                     order by snapshot_at desc limit 1)
                from {s}.account_snapshots
                where snapshot_at > now() - make_interval(days => %s)""",
            (dd_days,),
        )
        if row and row[0] and row[1]:
            peak, last = float(row[0]), float(row[1])
            if peak > 0 and (peak - last) / peak > dd_max:
                reasons.append(
                    f"drawdown: equity {last:,.0f} is {(peak - last) / peak:.1%} below "
                    f"the {dd_days:.0f}-day peak {peak:,.0f} (max {dd_max:.0%}) — entries halted"
                )
    except Exception:
        logger.exception("protections: drawdown query failed (FAIL-CLOSED)")
        reasons.append("drawdown check errored — fail-closed, entries halted")

    return ProtectionResult(allowed=not reasons, reasons=reasons)


def check_underlying(underlying: str) -> ProtectionResult:
    """Per-symbol checks: cooldown after a stop, chronic-loser lock."""
    reasons: list[str] = []
    s = db._schema()

    cooldown_min = _f("PROT_COOLDOWN_MIN", 90)
    try:
        row = _query_one(
            f"""select max(closed_at) from {s}.spreads
                where underlying = %s and status = any(%s)
                  and closed_at > now() - make_interval(mins => %s)""",
            (underlying, list(_STOP_STATUSES), cooldown_min),
        )
        if row and row[0] is not None:
            reasons.append(
                f"cooldown: {underlying} stopped out at {row[0]:%H:%M} UTC — "
                f"no re-entry for {cooldown_min:.0f} min"
            )
    except Exception:
        logger.exception("protections: cooldown query failed (fail-open)")

    floor = _f("PROT_LOW_PROFIT_FLOOR", -300.0)
    lp_days = _f("PROT_LOW_PROFIT_DAYS", 7)
    try:
        row = _query_one(
            f"""select coalesce(sum(realized_pnl), 0) from {s}.spreads
                where underlying = %s and realized_pnl is not null
                  and closed_at > now() - make_interval(days => %s)""",
            (underlying, lp_days),
        )
        if row and float(row[0]) < floor:
            reasons.append(
                f"low_profit: {underlying} realized ${float(row[0]):,.0f} over "
                f"{lp_days:.0f}d (floor ${floor:,.0f}) — symbol locked"
            )
    except Exception:
        logger.exception("protections: low_profit query failed (fail-open)")

    return ProtectionResult(allowed=not reasons, reasons=reasons)

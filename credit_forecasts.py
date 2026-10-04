"""Brier scoring for the CREDIT sleeve (podium upgrade, 2026-10-04).

Every candidate the judge sees is recorded with its stated p_win (taken) or
NULL (declined), plus the spread's own geometry. Resolution is mechanical
and needs no new cron: a prediction resolves when its spread closed (win =
realized_pnl > 0) or, for declined candidates, when the menu-book's
counterfactual episode for the same symbols closed. Brier = (p - outcome)^2;
coin flip = 0.25. Declined predictions carry NULL p and are scored only for
the regret view, never into the judge's Brier."""
from __future__ import annotations

import logging

import db

logger = logging.getLogger(__name__)

_DDL = """
create table if not exists {s}.credit_forecasts (
  id serial primary key, ts timestamptz default now(), cycle_id int,
  underlying text, direction text, short_symbol text, long_symbol text,
  stated_p numeric, taken boolean, outcome int, brier numeric,
  resolved_at timestamptz);
"""


def ensure_table() -> None:
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(_DDL.format(s=db._schema()))


def brier(stated_p: float, outcome: int) -> float:
    """Pure: squared error of a probabilistic forecast."""
    return round((stated_p - outcome) ** 2, 4)


def record(cycle_id: int, candidates: list[dict], p_by_ticker: dict, taken: list[str]) -> None:
    try:
        ensure_table()
        with db._connection() as conn, conn.cursor() as cur:
            for c in candidates:
                tk = c.get("ticker")
                plan = c.get("_plan")
                cur.execute(
                    f"""insert into {db._schema()}.credit_forecasts
                        (cycle_id, underlying, direction, short_symbol, long_symbol,
                         stated_p, taken)
                        values (%s,%s,%s,%s,%s,%s,%s)""",
                    (cycle_id, tk, c.get("direction"),
                     getattr(plan, "short_symbol", None), getattr(plan, "long_symbol", None),
                     p_by_ticker.get(tk), tk in taken),
                )
    except Exception:
        logger.exception("credit forecast recording failed (non-fatal)")


def resolve_due() -> int:
    """Score forecasts whose spread (taken) or menu-book episode (declined)
    has closed. Outcome 1 = that spread made money."""
    import psycopg2.extras
    s = db._schema()
    n = 0
    try:
        ensure_table()
        with db._connection() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"""
                select f.id, f.stated_p,
                       coalesce(sp.realized_pnl, mb.realized_pnl) pnl
                from {s}.credit_forecasts f
                left join {s}.spreads sp
                       on sp.short_symbol = f.short_symbol and sp.long_symbol = f.long_symbol
                      and sp.closed_at is not null and f.taken
                left join {s}.shadow_positions mb
                       on mb.short_symbol = f.short_symbol and mb.long_symbol = f.long_symbol
                      and mb.policy = 'menu' and mb.closed_at is not null and not f.taken
                where f.resolved_at is null
                  and coalesce(sp.realized_pnl, mb.realized_pnl) is not null
                limit 200""")
            for r in cur.fetchall():
                outcome = 1 if float(r["pnl"]) > 0 else 0
                b = brier(float(r["stated_p"]), outcome) if r["stated_p"] is not None else None
                cur.execute(f"""update {s}.credit_forecasts
                                set outcome=%s, brier=%s, resolved_at=now() where id=%s""",
                            (outcome, b, r["id"]))
                n += 1
    except Exception:
        logger.exception("credit forecast resolution failed (non-fatal)")
    return n


def summary() -> dict:
    try:
        with db._connection() as conn, conn.cursor() as cur:
            cur.execute(f"""select count(*) filter (where resolved_at is not null),
                            avg(brier) filter (where taken),
                            avg(case when outcome is not null and taken then outcome end),
                            avg(case when outcome is not null and not taken then outcome end)
                            from {db._schema()}.credit_forecasts""")
            n, b_taken, win_taken, win_declined = cur.fetchone()
            return {"n_resolved": n,
                    "brier_taken": float(b_taken) if b_taken is not None else None,
                    "win_rate_taken": float(win_taken) if win_taken is not None else None,
                    "win_rate_declined": float(win_declined) if win_declined is not None else None,
                    "coin_flip_reference": 0.25}
    except Exception:
        logger.exception("credit forecast summary failed")
        return {}

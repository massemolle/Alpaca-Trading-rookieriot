"""Arm-3 book — own tables, same shared schema."""
from __future__ import annotations

import json

import db

_DDL = """
create table if not exists {s}.ks_positions (
  id serial primary key, underlying text, symbol text, right_ text,
  strike numeric, expiration date, contracts int, premium_paid numeric,
  entry_spot numeric, atr numeric, stop_spot numeric, stated_p numeric,
  status text default 'open', opened_at timestamptz default now(),
  closed_at timestamptz, exit_reason text, realized_pnl numeric,
  client_order_id text);
create table if not exists {s}.ks_journal (
  id serial primary key, ts timestamptz default now(), decision text,
  candidates jsonb, selected jsonb, reasoning text, rejections jsonb);
"""


def ensure_tables():
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(_DDL.format(s=db._schema()))


def open_position(**kw) -> int:
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""insert into {db._schema()}.ks_positions
                (underlying, symbol, right_, strike, expiration, contracts, premium_paid,
                 entry_spot, atr, stop_spot, stated_p, client_order_id)
                values (%(underlying)s,%(symbol)s,%(right)s,%(strike)s,%(expiration)s,
                        %(contracts)s,%(premium_paid)s,%(entry_spot)s,%(atr)s,%(stop_spot)s,
                        %(stated_p)s,%(client_order_id)s) returning id""", kw)
        return cur.fetchone()[0]


def close_position(pid, reason, pnl):
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(f"""update {db._schema()}.ks_positions set status='closed',
                        closed_at=now(), exit_reason=%s, realized_pnl=%s where id=%s""",
                    (reason, pnl, pid))


def open_positions() -> list[dict]:
    import psycopg2.extras
    with db._connection() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"select * from {db._schema()}.ks_positions where status='open' order by id")
        return list(cur.fetchall())


def open_leg_quantities() -> dict[str, int]:
    out: dict[str, int] = {}
    for p in open_positions():
        out[p["symbol"]] = out.get(p["symbol"], 0) + int(p["contracts"])
    return out


def journal(decision, candidates, selected, reasoning, rejections):
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(f"""insert into {db._schema()}.ks_journal
                        (decision, candidates, selected, reasoning, rejections)
                        values (%s,%s,%s,%s,%s)""",
                    (decision, json.dumps(candidates, default=str),
                     json.dumps(selected, default=str), reasoning,
                     json.dumps(rejections, default=str)))

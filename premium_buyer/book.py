"""Premium-buyer persistence — own tables in the shared Supabase schema.
Create-if-missing at runtime so there is no manual migration step."""
from __future__ import annotations

import json

import db

_DDL = """
create table if not exists {s}.premium_positions (
  id serial primary key, underlying text, symbol text, right_ text,
  strike numeric, expiration date, contracts int, premium_paid numeric,
  stated_p numeric, status text default 'open', opened_at timestamptz default now(),
  closed_at timestamptz, exit_reason text, realized_pnl numeric,
  client_order_id text, order_ids jsonb);
create table if not exists {s}.premium_journal (
  id serial primary key, ts timestamptz default now(), decision text,
  candidates jsonb, selected jsonb, reasoning text, audit_flags jsonb,
  rejections jsonb);
create table if not exists {s}.premium_predictions (
  id serial primary key, ts timestamptz default now(), underlying text,
  direction text, stated_p numeric, spot_at numeric, horizon_date date,
  taken boolean, outcome int, brier numeric, resolved_at timestamptz);
"""


def ensure_tables() -> None:
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(_DDL.format(s=db._schema()))


def open_position(**kw) -> int:
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""insert into {db._schema()}.premium_positions
                (underlying, symbol, right_, strike, expiration, contracts,
                 premium_paid, stated_p, client_order_id, order_ids)
                values (%(underlying)s,%(symbol)s,%(right)s,%(strike)s,%(expiration)s,
                        %(contracts)s,%(premium_paid)s,%(stated_p)s,%(client_order_id)s,
                        %(order_ids)s) returning id""",
            dict(kw, order_ids=json.dumps(kw.get("order_ids") or [])),
        )
        return cur.fetchone()[0]


def close_position(pid: int, exit_reason: str, realized_pnl: float | None) -> None:
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""update {db._schema()}.premium_positions
                set status='closed', closed_at=now(), exit_reason=%s, realized_pnl=%s
                where id=%s""",
            (exit_reason, realized_pnl, pid),
        )


def open_positions() -> list[dict]:
    import psycopg2.extras
    with db._connection() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"select * from {db._schema()}.premium_positions where status='open' order by id")
        return list(cur.fetchall())


def open_leg_quantities() -> dict[str, int]:
    """{occ_symbol: total_long_contracts} — consumed by the CREDIT bot's
    reconciler so this sleeve's legs are never counted as orphans there."""
    out: dict[str, int] = {}
    for p in open_positions():
        out[p["symbol"]] = out.get(p["symbol"], 0) + int(p["contracts"])
    return out


def realized_today() -> float:
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(f"""select coalesce(sum(realized_pnl),0) from {db._schema()}.premium_positions
                        where closed_at::date = current_date""")
        return float(cur.fetchone()[0])


def journal(decision: str, candidates, selected, reasoning: str, audit_flags, rejections) -> None:
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""insert into {db._schema()}.premium_journal
                (decision, candidates, selected, reasoning, audit_flags, rejections)
                values (%s,%s,%s,%s,%s,%s)""",
            (decision, json.dumps(candidates, default=str), json.dumps(selected, default=str),
             reasoning, json.dumps(audit_flags, default=str), json.dumps(rejections, default=str)),
        )


def record_prediction(underlying, direction, stated_p, spot_at, horizon_date, taken) -> None:
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""insert into {db._schema()}.premium_predictions
                (underlying, direction, stated_p, spot_at, horizon_date, taken)
                values (%s,%s,%s,%s,%s,%s)""",
            (underlying, direction, stated_p, spot_at, horizon_date, taken),
        )

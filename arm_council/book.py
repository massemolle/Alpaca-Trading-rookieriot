"""Arm-4 book — equity positions (the original trades equities, not options)."""
from __future__ import annotations

import json

import db

_DDL = """
create table if not exists {s}.council_positions (
  id serial primary key, symbol text, qty numeric, entry_px numeric,
  size_usd numeric, opportunity numeric, risk_score numeric, confidence numeric,
  status text default 'open', opened_at timestamptz default now(),
  closed_at timestamptz, exit_reason text, realized_pnl numeric, client_order_id text);
create table if not exists {s}.council_journal (
  id serial primary key, ts timestamptz default now(), symbol text, decision text,
  conclusion text, thesis_status text, multi_factor numeric, opportunity numeric,
  risk numeric, gate_passed boolean, violations jsonb, vulnerabilities jsonb, claims jsonb);
"""


def ensure_tables():
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(_DDL.format(s=db._schema()))


def open_position(**kw) -> int:
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(f"""insert into {db._schema()}.council_positions
            (symbol, qty, entry_px, size_usd, opportunity, risk_score, confidence, client_order_id)
            values (%(symbol)s,%(qty)s,%(entry_px)s,%(size_usd)s,%(opportunity)s,
                    %(risk_score)s,%(confidence)s,%(client_order_id)s) returning id""", kw)
        return cur.fetchone()[0]


def close_position(pid, reason, pnl):
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(f"""update {db._schema()}.council_positions set status='closed',
                        closed_at=now(), exit_reason=%s, realized_pnl=%s where id=%s""",
                    (reason, pnl, pid))


def open_positions() -> list[dict]:
    import psycopg2.extras
    with db._connection() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"select * from {db._schema()}.council_positions where status='open' order by id")
        return list(cur.fetchall())


def gross_exposure() -> float:
    return sum(float(p["size_usd"]) for p in open_positions())


def journal(symbol, decision_label, d: dict):
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(f"""insert into {db._schema()}.council_journal
            (symbol, decision, conclusion, thesis_status, multi_factor, opportunity,
             risk, gate_passed, violations, vulnerabilities, claims)
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (symbol, decision_label, d.get("conclusion"), d.get("thesis_status"),
                     d.get("multi_factor"), d.get("opportunity"), d.get("risk"),
                     d.get("gate_passed"), json.dumps(d.get("violations", [])),
                     json.dumps(d.get("vulnerabilities", [])), json.dumps(d.get("claims", []), default=str)))

"""Builds state/evening_context.json — everything the nightly engineer
(Fable) needs to review the day: decisions, positions, ablation, lab.
Read-only; run by run_evening_review.sh before the Fable session starts.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import psycopg2.extras

import db


def _q(cur, sql: str) -> list[dict]:
    cur.execute(sql)
    return [dict(r) for r in cur.fetchall()]


def main() -> None:
    s = db._schema()
    with db._connection() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        ctx = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "cycles_recent": _q(cur, f"select id, decision, reasoning, error, ran_at from {s}.cycles order by id desc limit 12"),
            "journal_recent": _q(cur, f"""select cycle_id, candidates, llm_selected, llm_reasoning,
                                          shadow_selected, gate_rejections, pre_trade_rejections, created_at
                                          from {s}.decision_journal order by id desc limit 12"""),
            "spreads_all": _q(cur, f"select * from {s}.spreads order by opened_at desc limit 30"),
            "shadow_positions": _q(cur, f"select * from {s}.shadow_positions order by opened_at desc limit 60"),
            "snapshots_recent": _q(cur, f"select * from {s}.account_snapshots order by snapshot_at desc limit 10"),
            "lab_summary": _q(cur, f"select * from {s}.lab_summary order by id"),
        }
    # Feed the previous session back in — especially a REVERTED one: the next
    # engineer must see what was tried and which tests it broke, or it will
    # repeat the same mistake nightly (learned from the first live run, where
    # a good idea — a credit-to-width floor — was reverted for breaking the
    # fill-confirmation sign tests).
    state = Path(__file__).resolve().parent / "state"
    prev_review = state / "evening_review_last.md"
    prev_gate = state / "evening_gate.log"
    ctx["previous_session"] = {
        "review": prev_review.read_text()[-6000:] if prev_review.exists() else None,
        "gate_log_tail": prev_gate.read_text()[-3000:] if prev_gate.exists() else None,
    }
    out = Path(__file__).resolve().parent / "state" / "evening_context.json"
    out.write_text(json.dumps(ctx, indent=1, default=str))
    print(f"context written: {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

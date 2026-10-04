"""Brier scoring — NEW ADDITION #2 (Autobelay pattern): every stated
probability — taken AND declined — is recorded and later scored against
what the underlying actually did. Resolution runs inside the normal cycle;
no extra cron. Brier = (p - outcome)^2; coin flip scores 0.25."""
from __future__ import annotations

import logging

import db
from premium_buyer import config as pcfg

logger = logging.getLogger(__name__)


def score(stated_p: float, direction: str, spot_at: float, spot_now: float,
          threshold_pct: float) -> tuple[int, float]:
    """Pure: outcome (1 if the move reached threshold in the predicted
    direction) and Brier contribution (p - outcome)^2."""
    move_pct = (spot_now - spot_at) / spot_at * 100
    favorable = move_pct >= threshold_pct if direction == "long" else move_pct <= -threshold_pct
    outcome = 1 if favorable else 0
    return outcome, round((stated_p - outcome) ** 2, 4)


def resolve_due(client) -> int:
    """Score matured predictions (horizon_date <= today) using current spot
    vs spot_at. Outcome = 1 if move in predicted direction >= threshold."""
    import psycopg2.extras
    n = 0
    with db._connection() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"""select id, underlying, direction, stated_p, spot_at from
                        {db._schema()}.premium_predictions
                        where resolved_at is null and horizon_date <= current_date limit 50""")
        rows = cur.fetchall()
        for r in rows:
            try:
                q = client.get_latest_quote(r["underlying"])
                spot = (q["ask_price"] + q["bid_price"]) / 2
                stated = float(r["stated_p"]) if r["stated_p"] is not None else None
                outcome, brier = score(stated if stated is not None else 0.5,
                                       r["direction"], float(r["spot_at"]), spot,
                                       pcfg.MOVE_THRESHOLD_PCT)
                cur.execute(f"""update {db._schema()}.premium_predictions
                                set outcome=%s, brier=%s, resolved_at=now() where id=%s""",
                            (outcome, brier if stated is not None else None, r["id"]))
                n += 1
            except Exception:
                logger.exception("brier resolve failed for prediction %s", r["id"])
    return n


def summary() -> dict:
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(f"""select count(*), avg(brier),
                        avg(brier) filter (where taken),
                        avg(brier) filter (where not taken)
                        from {db._schema()}.premium_predictions where resolved_at is not null""")
        n, all_b, taken_b, decl_b = cur.fetchone()
        return {"n_resolved": n, "brier_all": float(all_b) if all_b is not None else None,
                "brier_taken": float(taken_b) if taken_b is not None else None,
                "brier_declined": float(decl_b) if decl_b is not None else None,
                "coin_flip_reference": 0.25}

"""Shadow book — the live ablation (PLAN Science / D17 PR4).

Every cycle, alongside the real (LLM-selected) book, two counterfactual
policies get VIRTUAL positions on the exact same gate-approved candidates:

- 'shadow': bot._shadow_select's mechanical rule (strength × credit/max_loss)
- 'random': uniform picks, matched trade rate (same count as the LLM took;
  abstains when the LLM abstained — so the comparison isolates SELECTION
  quality, not trade frequency)

Virtual fills at credit_estimate, same sizing rule as the real book, marked
each cycle with the same cost-to-close quote and closed by the same
profit-target/stop/force-close rules. The dashboard then shows cumulative
P&L per policy: "did the LLM's judgment add dollars over the rule, over
random?" — honest either way.
"""
from __future__ import annotations

import json
import logging
import random
from datetime import date, datetime, timezone

import db
import executor_mcp
import risk_gate

logger = logging.getLogger(__name__)


# --- persistence -----------------------------------------------------------

def _record_open(cycle_id: int, policy: str, cand: dict, plan, contracts: int, same_as_llm: bool) -> None:
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            insert into {db._schema()}.shadow_positions
                (cycle_id, policy, underlying, direction, expiration, short_strike, long_strike,
                 short_symbol, long_symbol, contracts, credit_received, max_loss, status, same_as_llm)
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'open',%s)
            """,
            (cycle_id, policy, plan.underlying, plan.direction, plan.expiration.isoformat(),
             plan.short_strike, plan.long_strike, plan.short_symbol, plan.long_symbol,
             contracts, plan.credit_estimate, plan.max_loss, same_as_llm),
        )


def _get_open() -> list[dict]:
    import psycopg2.extras
    with db._connection() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"select * from {db._schema()}.shadow_positions where status='open' order by opened_at")
        return list(cur.fetchall())


def _mark(row_id: int, mark: float) -> None:
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"update {db._schema()}.shadow_positions set unrealized_mark=%s where id=%s",
            (mark, row_id),
        )


def _close(row_id: int, status: str, realized_pnl: float | None) -> None:
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""update {db._schema()}.shadow_positions
                set status=%s, realized_pnl=%s, closed_at=now(), unrealized_mark=NULL
                where id=%s""",
            (status, realized_pnl, row_id),
        )


# --- per-cycle hooks -------------------------------------------------------

def open_counterfactuals(
    cycle_id: int,
    candidates: list[dict],
    llm_selected: list[str],
    shadow_selected: list[str],
    sizing_fn,
    equity: float,
    max_risk_pct: float,
) -> None:
    """Called after the real decisions are journaled. `candidates` are the
    gate-approved dicts still carrying their `_plan`. Never raises."""
    try:
        by_ticker = {c["ticker"]: c for c in candidates}
        n_llm = len(llm_selected)

        # random policy: matched trade rate, deterministic per cycle so a
        # crashed/re-run cycle can't re-roll a luckier pick
        rng = random.Random(cycle_id)
        random_selected = rng.sample(sorted(by_ticker), min(n_llm, len(by_ticker))) if n_llm else []

        for policy, picks in (("shadow", shadow_selected), ("random", random_selected)):
            for ticker in picks:
                cand = by_ticker.get(ticker)
                if cand is None or "_plan" not in cand:
                    continue
                plan = cand["_plan"]
                contracts = sizing_fn(
                    equity=equity, max_loss_per_contract=plan.max_loss, max_risk_pct=max_risk_pct
                )
                _record_open(cycle_id, policy, cand, plan, contracts, same_as_llm=ticker in llm_selected)
        logger.info(
            "shadow book: recorded shadow=%s random=%s (llm took %d)",
            shadow_selected, random_selected, n_llm,
        )
    except Exception:
        logger.exception("shadow book open_counterfactuals failed (non-fatal)")


async def manage_open(mcp) -> None:
    """Mark all open virtual positions; close them by the same rules as the
    real book. Called once per cycle. Never raises."""
    try:
        for row in _get_open():
            try:
                mark = await executor_mcp.get_spread_mark(mcp, row["short_symbol"], row["long_symbol"])
            except Exception:
                logger.exception("shadow mark failed for %s", row["id"])
                continue
            force, force_reason = risk_gate.should_force_close(expiration=_as_date(row["expiration"]))
            if mark is None:
                if force:
                    _close(row["id"], "closed_expiry", None)
                continue
            _mark(row["id"], mark)
            close, _reason = risk_gate.should_close(
                credit_received=float(row["credit_received"]), current_mark=mark
            )
            if close or force:
                contracts = int(row.get("contracts") or 1)
                realized = (float(row["credit_received"]) - mark) * contracts
                status = "closed_expiry" if force else ("closed_profit" if realized > 0 else "closed_stop")
                _close(row["id"], status, realized)
    except Exception:
        logger.exception("shadow book manage_open failed (non-fatal)")


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()

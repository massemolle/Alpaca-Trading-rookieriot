"""Shadow book — live ablation on the SAME executable candidate menu.

Policies:
- 'shadow': mechanical rule (selector.shadow_select)
- 'random': matched trade count AND aggregate max-loss budget to the LLM

Virtual fills use the candidate's credit_estimate (conservative synthetic mid)
so policy attribution is comparable; real broker fills are reported separately
as execution quality on the live book.
"""
from __future__ import annotations

import logging
import random
from datetime import date, datetime

import db
import executor_mcp
import risk_gate
from selector import aggregate_max_loss

logger = logging.getLogger(__name__)


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


def _pick_random_matched(
    candidates: list[dict],
    llm_selected: list[str],
    cycle_id: int,
) -> list[str]:
    """Match LLM on trade count and approximate aggregate max-loss budget."""
    by_ticker = {c["ticker"]: c for c in candidates}
    n_llm = len(llm_selected)
    if n_llm == 0 or not by_ticker:
        return []
    llm_risk = aggregate_max_loss(candidates, llm_selected)
    rng = random.Random(cycle_id)
    pool = sorted(by_ticker.keys())
    # Try several draws; keep the one closest under the LLM risk budget.
    best: list[str] = []
    best_gap = float("inf")
    for offset in range(20):
        rng_i = random.Random(cycle_id * 100_003 + offset)
        picks = rng_i.sample(pool, min(n_llm, len(pool)))
        risk = aggregate_max_loss(candidates, picks)
        if risk <= llm_risk + 1e-9:
            return picks
        gap = abs(risk - llm_risk)
        if gap < best_gap:
            best_gap = gap
            best = picks
    return best or rng.sample(pool, min(n_llm, len(pool)))


def open_counterfactuals(
    cycle_id: int,
    candidates: list[dict],
    llm_selected: list[str],
    shadow_selected: list[str],
    sizing_fn,
    equity: float,
    max_risk_pct: float,
) -> None:
    try:
        by_ticker = {c["ticker"]: c for c in candidates}
        random_selected = _pick_random_matched(candidates, llm_selected, cycle_id)

        for policy, picks in (("shadow", shadow_selected), ("random", random_selected)):
            for ticker in picks:
                cand = by_ticker.get(ticker)
                if cand is None or "_plan" not in cand:
                    continue
                plan = cand["_plan"]
                contracts = int(cand.get("contracts") or 0)
                if contracts < 1:
                    contracts = sizing_fn(
                        equity=equity,
                        max_loss_per_contract=plan.max_loss,
                        max_risk_pct=max_risk_pct,
                    )
                if contracts < 1:
                    continue
                _record_open(
                    cycle_id, policy, cand, plan, contracts,
                    same_as_llm=ticker in llm_selected,
                )
        logger.info(
            "shadow book: recorded shadow=%s random=%s (llm took %d)",
            shadow_selected, random_selected, len(llm_selected),
        )
    except Exception:
        logger.exception("shadow book open_counterfactuals failed (non-fatal)")


async def manage_open(mcp) -> None:
    try:
        for row in _get_open():
            try:
                mark = await executor_mcp.get_spread_mark(
                    mcp, row["short_symbol"], row["long_symbol"]
                )
            except Exception:
                logger.exception("shadow mark failed for %s", row["id"])
                continue
            force, _force_reason = risk_gate.should_force_close(
                expiration=_as_date(row["expiration"])
            )
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
                status = (
                    "closed_expiry" if force
                    else ("closed_profit" if realized > 0 else "closed_stop")
                )
                _close(row["id"], status, realized)
    except Exception:
        logger.exception("shadow book manage_open failed (non-fatal)")


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()

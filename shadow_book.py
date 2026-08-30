"""Shadow book — live ablation on the SAME executable candidate menu.

Policies:
- 'shadow': mechanical rule (selector.shadow_select)
- 'random': matched trade count AND aggregate max-loss budget to the LLM
- 'menu':   EVERY gate-approved candidate, picked or not — the full
            counterfactual menu, so the evening review can measure regret
            (profitable candidates the LLM dropped). Not an ablation arm:
            it is not risk-matched, so it must never be summed against the
            policy books above.

Virtual fills use the candidate's credit_estimate (conservative synthetic mid)
so policy attribution is comparable; real broker fills are reported separately
as execution quality on the live book.
"""
from __future__ import annotations

import logging
import os
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


def _menu_open_symbol_pairs() -> set:
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""select short_symbol, long_symbol from {db._schema()}.shadow_positions
                where policy='menu' and status='open'"""
        )
        return {(r[0], r[1]) for r in cur.fetchall()}


def open_menu_book(
    cycle_id: int,
    candidates: list[dict],
    llm_selected: list[str],
    sizing_fn,
    equity: float,
    max_risk_pct: float,
) -> None:
    """Virtually fill EVERY gate-approved candidate (policy='menu').

    Dedup on the open (short, long) symbol pair — an unchanged menu must not
    re-open the same spread every 30 minutes; a new episode starts only after
    the old virtual position closed. MENU_BOOK_MAX_OPEN caps marking load.
    """
    try:
        cap = int(os.environ.get("MENU_BOOK_MAX_OPEN", "20"))
        already = _menu_open_symbol_pairs()
        n_open = len(already)
        for cand in candidates:
            plan = cand.get("_plan")
            if plan is None:
                continue
            pair = (plan.short_symbol, plan.long_symbol)
            if pair in already:
                continue
            if n_open >= cap:
                logger.info("menu book: cap %d reached — skipping %s", cap, plan.underlying)
                continue
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
                cycle_id, "menu", cand, plan, contracts,
                same_as_llm=cand.get("ticker") in llm_selected,
            )
            already.add(pair)
            n_open += 1
    except Exception:
        logger.exception("menu book open failed (non-fatal)")


def regret_summary(menu_rows: list[dict]) -> dict:
    """Pure regret computation for the evening context.

    outcome_usd per row: realized_pnl when closed; (credit − mark) × contracts
    while open and marked; None when never marked. 'Dropped' = the LLM did not
    take it (whatever the rule/random books did).
    """
    table = []
    for r in menu_rows:
        credit = float(r["credit_received"])
        contracts = int(r.get("contracts") or 1)
        if r.get("realized_pnl") is not None:
            outcome = float(r["realized_pnl"])
        elif r.get("unrealized_mark") is not None:
            outcome = (credit - float(r["unrealized_mark"])) * contracts
        else:
            outcome = None
        table.append({
            "cycle_id": r.get("cycle_id"),
            "underlying": r.get("underlying"),
            "direction": r.get("direction"),
            "short_strike": float(r["short_strike"]) if r.get("short_strike") is not None else None,
            "long_strike": float(r["long_strike"]) if r.get("long_strike") is not None else None,
            "expiration": str(r.get("expiration")),
            "status": r.get("status"),
            "taken_by_llm": bool(r.get("same_as_llm")),
            "outcome_usd": round(outcome, 2) if outcome is not None else None,
        })
    dropped = [t for t in table if not t["taken_by_llm"] and t["outcome_usd"] is not None]
    taken = [t for t in table if t["taken_by_llm"] and t["outcome_usd"] is not None]
    dropped_pos = [t for t in dropped if t["outcome_usd"] > 0]
    return {
        "note": (
            "Every gate-approved candidate is virtually tracked (policy='menu'), picked or "
            "not. Regret = profitable candidates the LLM dropped. One lucky miss is noise — "
            "act on patterns, and read the journal's cited reasoning for those cycles first."
        ),
        "rows": table,
        "taken_count": len(taken),
        "taken_total_usd": round(sum(t["outcome_usd"] for t in taken), 2),
        "dropped_count": len(dropped),
        "dropped_total_usd": round(sum(t["outcome_usd"] for t in dropped), 2),
        "dropped_positive_count": len(dropped_pos),
        "dropped_positive_total_usd": round(sum(t["outcome_usd"] for t in dropped_pos), 2),
        "best_dropped": max(dropped, key=lambda t: t["outcome_usd"], default=None),
    }


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
